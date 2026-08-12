#!/usr/bin/env python3
"""
Build the LWMC fleet master dataset for the local dashboard.

Scope: Lahore + Sheikhupura + Kasur + Nankana Sahib  (= the whole LWMC company in VTMS)
Sources used: VTMS active logs + LWMC vehicle-status .xls  (VTCS is intentionally NOT used)
Geography: Lahore UC boundaries (KML -> GeoJSON), assigned to vehicles by point-in-polygon.

Re-run this each day on a new export folder to append to the time-series.
Outputs:
  - master_YYYY-MM-DD.csv     (tidy per-vehicle table)
  - dashboard_data.json       (compact payload the dashboard.html reads / embeds)
  - coverage report printed to stdout
"""
import pandas as pd, numpy as np, json, sys, re
from pathlib import Path

# ---------- config ----------
VTMS_CSV = "export-vtms-active-logs-11-08-2026-11_31_03.csv"
LWMC_XLS = "vs.xlsx"                       # converted from the .xls export
UC_GEOJSON = "lahore_ucs.geojson"
SNAPSHOT_DATE = "2026-08-11"

TEHSIL_TO_DISTRICT = {
    'AlIT':'Lahore','ShTo':'Lahore','RaTo':'Lahore','NiTo':'Lahore','WaTo':'Lahore',
    'DaGB':'Lahore','SaTo':'Lahore','AzBT':'Lahore','GuTo':'Lahore',
    'Shei':'Sheikhupura','Fero':'Sheikhupura','Muri':'Sheikhupura','Safd':'Sheikhupura','Shar':'Sheikhupura',
    'Kasu':'Kasur','Patt':'Kasur','Chun':'Kasur','KoRK':'Kasur',
    'NaSa':'Nankana Sahib','SaHi':'Nankana Sahib','ShKo':'Nankana Sahib',
    'OtSi':'Other',
}

def num(s):
    return pd.to_numeric(s.astype(str).str.replace(',','',regex=False).replace('-',np.nan), errors='coerce')

def norm_key(s):
    return s.astype(str).str.upper().str.replace(r'[^A-Z0-9]','',regex=True)

# ---------- point in polygon (ray casting, no deps) ----------
def point_in_ring(x, y, ring):
    inside = False
    n = len(ring)
    j = n - 1
    for i in range(n):
        xi, yi = ring[i]; xj, yj = ring[j]
        if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / (yj - yi + 1e-15) + xi):
            inside = not inside
        j = i
    return inside

def load_ucs(path):
    gj = json.load(open(path))
    ucs = []
    for ft in gj['features']:
        ring = ft['geometry']['coordinates'][0]
        xs = [p[0] for p in ring]; ys = [p[1] for p in ring]
        ucs.append({
            'uc': ft['properties']['uc'], 'town': ft['properties']['town'],
            'zone': ft['properties']['zone'], 'ring': ring,
            'bbox': (min(xs), min(ys), max(xs), max(ys)),
        })
    return ucs

def assign_uc(lon, lat, ucs):
    for u in ucs:
        x0, y0, x1, y1 = u['bbox']
        if x0 <= lon <= x1 and y0 <= lat <= y1:
            if point_in_ring(lon, lat, u['ring']):
                return u['uc'], u['town'], u['zone']
    return None, None, None

# ---------- build ----------
def main():
    v = pd.read_csv(VTMS_CSV)
    lw = v[v['Company'] == 'LWMC'].copy()

    lw['distance_km']   = num(lw['Distance (Km)'])
    lw['working_min']   = num(lw['Working Hours (In Minutes)'])
    lw['lat']           = pd.to_numeric(lw['Latitude'], errors='coerce')
    lon                 = pd.to_numeric(lw['Longitude'], errors='coerce'); lw['lon'] = lon
    lw['code']          = lw['Tehsil'].str.replace('LWMC-','',regex=False)
    lw['district']      = lw['code'].map(TEHSIL_TO_DISTRICT).fillna('Other')
    lw['vkey']          = norm_key(lw['Vehicle'])
    lw['snapshot']      = SNAPSHOT_DATE

    # enrich with LWMC status file (battery voltage, reporting status)
    # the export is sometimes a legacy .xls saved under an .xlsx name, so sniff
    # the real format instead of trusting the extension
    with open(LWMC_XLS, 'rb') as fh:
        is_legacy_xls = fh.read(8) == b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1'
    xls_engine = 'xlrd' if is_legacy_xls else 'openpyxl'
    st = pd.read_excel(LWMC_XLS, header=3, engine=xls_engine).dropna(how='all').copy()
    st['vkey']          = norm_key(st['Vehicle Reg No'])
    st['battery_volt']  = pd.to_numeric(st['Battery Status'], errors='coerce')
    st['tracker_offline'] = st['battery_volt'] < 2
    st_small = st[['vkey','Reporting Status','Status Text','battery_volt','tracker_offline']]\
                 .drop_duplicates('vkey')\
                 .rename(columns={'Reporting Status':'reporting_status','Status Text':'status_text'})
    lw = lw.merge(st_small, on='vkey', how='left')

    # assign UC by point-in-polygon
    ucs = load_ucs(UC_GEOJSON)
    tags = [assign_uc(r.lon, r.lat, ucs) if pd.notna(r.lon) and pd.notna(r.lat) else (None,None,None)
            for r in lw.itertuples()]
    lw['uc'], lw['uc_town'], lw['uc_zone'] = zip(*tags)

    keep = ['Vehicle ID','Vehicle','vkey','district','Office','Tehsil','Vehicle Type','Vehicle Used For',
            'Vehicle Status','Engine Status','distance_km','working_min','lat','lon',
            'Timestamp','Last Received At','reporting_status','status_text','battery_volt',
            'tracker_offline','uc','uc_town','uc_zone','snapshot']
    master = lw[keep].rename(columns={
        'Vehicle ID':'vehicle_id','Vehicle':'vehicle','Vehicle Type':'vehicle_type',
        'Vehicle Used For':'used_for','Vehicle Status':'status','Engine Status':'engine',
        'Office':'office','Tehsil':'tehsil_code','Timestamp':'timestamp','Last Received At':'last_received'})

    out_csv = f"master_{SNAPSHOT_DATE}.csv"
    master.to_csv(out_csv, index=False)

    # ---- coverage report ----
    print("="*55); print("LWMC FLEET MASTER — build report"); print("="*55)
    print(f"Snapshot: {SNAPSHOT_DATE}")
    print(f"Vehicles: {len(master)}  (unique: {master['vkey'].nunique()})")
    print(f"With valid GPS: {master['lat'].notna().sum()}")
    print(f"Matched to LWMC status file: {master['reporting_status'].notna().sum()}")
    print(f"Assigned to a UC (Lahore city): {master['uc'].notna().sum()}")
    print()
    print("By district:"); print(master['district'].value_counts().to_string())
    print()
    print("By status:"); print(master['status'].value_counts().to_string())
    print(f"\nTotal distance today (km): {master['distance_km'].sum():,.0f}")
    print(f"Engine ON but not moving: {((master['engine']=='on') & (master['status']!='moving')).sum()}")
    print(f"Wrote {out_csv}")

    # ---- compact dashboard payload ----
    pts = master.copy()
    pts['distance_km'] = pts['distance_km'].round(2)
    pts['battery_volt'] = pts['battery_volt'].round(1)
    # full raw column set (matches master_<date>.csv) so every written view in the
    # dashboard (popup, selected-record panel) can show the complete raw record,
    # not just the curated subset used for the map/table
    cols = ['vehicle_id','vehicle','vkey','district','office','tehsil_code','vehicle_type',
            'used_for','status','engine','distance_km','working_min','lat','lon','timestamp',
            'last_received','reporting_status','status_text','battery_volt','tracker_offline',
            'uc','uc_town','uc_zone','snapshot']
    import math
    def clean(v):
        if v is None: return None
        if isinstance(v, float) and math.isnan(v): return None
        return v
    records = [{k: clean(val) for k, val in r.items()} for r in pts[cols].to_dict('records')]

    ucs_geo = json.load(open(UC_GEOJSON))
    # per-UC aggregates for the coverage layer
    agg = master.dropna(subset=['uc']).groupby('uc').agg(
        vehicles=('vkey','count'),
        moving=('status', lambda s:(s=='moving').sum()),
        dist=('distance_km','sum')).round(0).to_dict('index')

    payload = {
        'snapshot': SNAPSHOT_DATE,
        'points': records,
        'ucs': ucs_geo,
        'uc_stats': {k:{'vehicles':int(v['vehicles']),'moving':int(v['moving']),
                        'dist':float(v['dist'])} for k,v in agg.items()},
        'summary': {
            'total': len(master),
            'moving': int((master['status']=='moving').sum()),
            'idle': int((master['status']=='idle').sum()),
            'still': int((master['status']=='still').sum()),
            'engine_on': int((master['engine']=='on').sum()),
            'idling_waste': int(((master['engine']=='on') & (master['status']!='moving')).sum()),
            'total_distance': round(float(master['distance_km'].sum()),0),
            'not_reporting': int((master['reporting_status']=='Not Reporting').sum()),
            'no_activity': int((master['status_text']=='No Activity Since Yesterday').sum()),
            'by_district': master['district'].value_counts().to_dict(),
        }
    }
    json.dump(payload, open('dashboard_data.json','w'), allow_nan=False)
    print("Wrote dashboard_data.json")

if __name__ == '__main__':
    main()
