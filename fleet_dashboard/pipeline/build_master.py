#!/usr/bin/env python3
"""
Build the LWMC fleet master dataset for the local dashboard.

Scope: Lahore city only (Sheikhupura/Kasur/Nankana Sahib rows are dropped --
       UC/zone geometry, the employee roster, and fleet targets are all
       Lahore-specific, so those districts have nothing to attach to here)
Sources used: VTMS active logs + LWMC vehicle-status export (auto-detected
       by filename pattern + most-recent modification time -- see
       fleet_dashboard/config.py -- so this no longer needs a manual edit
       each day). VTCS is intentionally NOT used.
Geography: Lahore UC boundaries (KML -> GeoJSON), assigned to vehicles by
       point-in-polygon.

Re-run this each day on a new export folder to append to the time-series.
Outputs (written at the project root, same as before):
  - master_YYYY-MM-DD.csv     (tidy per-vehicle table)
  - dashboard_data.json       (compact payload the HTML dashboard reads / embeds)
  - LWMC_Fleet_Dashboard.html (re-embedded from dashboard_template.html, if present)
  - coverage report printed to stdout

Run with:  python -m fleet_dashboard.pipeline.build_master
"""
from __future__ import annotations

import json
import math

import numpy as np
import pandas as pd

from .. import config
from ..data import core

# ---------- build ----------
def main():
    vtms_path = config.latest_vtms_csv()
    if vtms_path is None:
        raise SystemExit("No VTMS export found (export-vtms-active-logs-*.csv) at the project root.")
    status_path = config.latest_vehicle_status_file()
    snapshot_date = config.default_snapshot_date(vtms_path)

    v = pd.read_csv(vtms_path)
    lw = v[v['Company'] == 'LWMC'].copy()

    lw['distance_km']   = core.num(lw['Distance (Km)'])
    lw['working_min']   = core.num(lw['Working Hours (In Minutes)'])
    lw['lat']           = pd.to_numeric(lw['Latitude'], errors='coerce')
    lon                 = pd.to_numeric(lw['Longitude'], errors='coerce'); lw['lon'] = lon
    lw['code']          = lw['Tehsil'].str.replace('LWMC-','',regex=False)
    lw['district']      = lw['code'].map(core.TEHSIL_TO_DISTRICT).fillna('Other')

    # Dashboard scope is Lahore city only -- UC/zone/town geometry, the
    # employee roster, and the fleet targets are all Lahore-specific, so
    # Sheikhupura/Kasur/Nankana Sahib vehicles are dropped here rather than
    # carried through as dead weight nothing downstream can make use of.
    n_before = len(lw)
    lw = lw[lw['district'] == 'Lahore'].copy()
    print(f"Scope: Lahore only -- kept {len(lw)}/{n_before} VTMS/LWMC rows "
          f"({n_before - len(lw)} non-Lahore rows dropped)")

    lw['vkey']          = core.norm_key(lw['Vehicle'])
    lw['snapshot']      = snapshot_date

    # fleet establishment registry (Reference Documents/town_targets.json,
    # from extract_town_targets.py) -- gives each vehicle its REAL registered
    # category/town by Vehicle ID, far more reliable than VTMS's own
    # vehicle_type field (blank for most rows). Additive reference data: a
    # missing/stale file degrades to "no registry match for anyone" rather
    # than failing the build.
    try:
        fleet_registry = json.load(open(config.TOWN_TARGETS_JSON, encoding='utf-8'))
    except Exception as e:
        print(f"\nWARNING: could not load fleet registry ({config.TOWN_TARGETS_JSON}): {e}")
        print("Run `python -m fleet_dashboard.pipeline.extract_town_targets` first if "
              "'Lahore Fleet+LRs.xlsx' is present.")
        fleet_registry = {'towns': {}, 'vehicles': {}}
    reg_vehicles = fleet_registry.get('vehicles', {})
    lw['registry_category'] = lw['vkey'].map(lambda k: reg_vehicles.get(k, {}).get('category'))
    lw['registry_town']     = lw['vkey'].map(lambda k: reg_vehicles.get(k, {}).get('town'))

    # enrich with LWMC status file (battery voltage, reporting status) --
    # optional: the export is sometimes a legacy .xls saved under an .xlsx
    # name, so sniff the real format instead of trusting the extension, and
    # degrade to blank battery/reporting fields (rather than aborting the
    # whole build) if the file isn't present that day.
    if status_path is not None:
        with open(status_path, 'rb') as fh:
            is_legacy_xls = fh.read(8) == b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1'
        xls_engine = 'xlrd' if is_legacy_xls else 'openpyxl'
        st = pd.read_excel(status_path, header=3, engine=xls_engine).dropna(how='all').copy()
        st['vkey']          = core.norm_key(st['Vehicle Reg No'])
        st['battery_volt']  = pd.to_numeric(st['Battery Status'], errors='coerce')
        st['tracker_offline'] = st['battery_volt'] < 2
        st_small = st[['vkey','Reporting Status','Status Text','battery_volt','tracker_offline']]\
                     .drop_duplicates('vkey')\
                     .rename(columns={'Reporting Status':'reporting_status','Status Text':'status_text'})
        lw = lw.merge(st_small, on='vkey', how='left')
    else:
        print(f"\nWARNING: no vehicle-status export found (Vehicle_Status_*.xls* / vs.xlsx) -- "
              f"battery/reporting fields will be blank for this build.")
        for col in ('reporting_status', 'status_text'):
            lw[col] = None
        # numeric/boolean columns need a real NaN, not plain None -- a
        # None-filled object column blows up later .round() calls
        lw['battery_volt'] = np.nan
        lw['tracker_offline'] = False

    # assign UC by point-in-polygon
    ucs = core.load_ucs(str(config.UC_GEOJSON))
    tags = [core.assign_uc(r.lon, r.lat, ucs) if pd.notna(r.lon) and pd.notna(r.lat) else (None,None,None)
            for r in lw.itertuples()]
    lw['uc'], lw['uc_town'], lw['uc_zone'] = zip(*tags)

    # assigned_town = the town a vehicle is actually registered to. Prefer
    # the fleet registry (matched by Vehicle ID -- authoritative, covers
    # ~96% of live vehicles); fall back to the tehsil-code-derived town
    # (coarser, but covers everyone) only when a vehicle has no registry
    # match. in_assigned_area compares that against where its live GPS
    # currently places it. Only meaningful for the 9 Lahore towns -- a
    # vehicle with no resolvable home town gets None, not False, since
    # "assigned area" isn't defined for it here.
    lw['assigned_town'] = lw['registry_town'].fillna(lw['code'].map(core.TEHSIL_TO_TOWN))
    def _in_area(row):
        if row['assigned_town'] is None or pd.isna(row['assigned_town']):
            return None
        if row['uc_town'] is None or pd.isna(row['uc_town']):
            return False
        return bool(row['assigned_town'] == row['uc_town'])
    lw['in_assigned_area'] = lw.apply(_in_area, axis=1)

    keep = ['Vehicle ID','Vehicle','vkey','district','Office','Tehsil','Vehicle Type','Vehicle Used For',
            'Vehicle Status','Engine Status','distance_km','working_min','lat','lon',
            'Timestamp','Last Received At','reporting_status','status_text','battery_volt',
            'tracker_offline','uc','uc_town','uc_zone','registry_category','assigned_town',
            'in_assigned_area','snapshot']
    master = lw[keep].rename(columns={
        'Vehicle ID':'vehicle_id','Vehicle':'vehicle','Vehicle Type':'vehicle_type',
        'Vehicle Used For':'used_for','Vehicle Status':'status','Engine Status':'engine',
        'Office':'office','Tehsil':'tehsil_code','Timestamp':'timestamp','Last Received At':'last_received'})

    out_csv = config.PROJECT_ROOT / f"master_{snapshot_date}.csv"
    master.to_csv(out_csv, index=False)

    # ---- coverage report ----
    print("="*55); print("LWMC FLEET MASTER — build report"); print("="*55)
    print(f"Snapshot: {snapshot_date}")
    print(f"VTMS export: {vtms_path.name}")
    print(f"Vehicle-status export: {status_path.name if status_path else 'not found'}")
    print(f"Vehicles: {len(master)}  (unique: {master['vkey'].nunique()})")
    print(f"With valid GPS: {master['lat'].notna().sum()}")
    print(f"Matched to LWMC status file: {master['reporting_status'].notna().sum()}")
    print(f"Assigned to a UC (Lahore city): {master['uc'].notna().sum()}")
    print()
    print("By town:"); print(master['uc_town'].value_counts(dropna=False).to_string())
    print()
    print("By status:"); print(master['status'].value_counts().to_string())
    print(f"\nTotal distance today (km): {master['distance_km'].sum():,.0f}")
    print(f"Engine ON but not moving: {((master['engine']=='on') & (master['status']!='moving')).sum()}")
    print(f"Wrote {out_csv}")

    # ---- employee roster (performance-scoping) ----
    # vehicle data is the primary product, so a roster problem (missing file,
    # unexpected sheet layout) must not abort the whole build -- degrade to
    # an empty roster instead and say so loudly.
    employee_xlsx = config.latest_employee_roster()
    try:
        if employee_xlsx is None:
            raise FileNotFoundError("no employee*sheet*.xlsx / employee*data*.xlsx found at the project root")
        employees, roster_ucs, roster_stats, all_lahore_ucs = core.load_employee_roster(str(employee_xlsx), ucs)
        core.print_roster_report(employees, roster_ucs, roster_stats, all_lahore_ucs)
    except Exception as e:
        print(f"\nWARNING: could not load employee roster ({employee_xlsx}): {e}")
        print("Dashboard will have no roster data -- 'Roster-scoped' mode will be empty.")
        employees, roster_ucs = [], []

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
            'uc','uc_town','uc_zone','registry_category','assigned_town','in_assigned_area','snapshot']
    def clean(v):
        if v is None: return None
        if isinstance(v, float) and math.isnan(v): return None
        return v
    records = [{k: clean(val) for k, val in r.items()} for r in pts[cols].to_dict('records')]

    ucs_geo = json.load(open(config.UC_GEOJSON))
    # per-UC aggregates for the coverage layer
    agg = master.dropna(subset=['uc']).groupby('uc').agg(
        vehicles=('vkey','count'),
        moving=('status', lambda s:(s=='moving').sum()),
        dist=('distance_km','sum')).round(0).to_dict('index')

    # ---- town fleet targets vs. live-deployed (Reference Documents/town_targets.json) ----
    # additive reference data, not part of the daily VTMS/roster inputs -- if
    # it's missing or stale, degrade to an empty list rather than fail the build.
    #
    # Both targets (LR-only and full fleet) come from the fleet establishment
    # registry, and "deployed" is filtered by registry_category (joined by
    # Vehicle ID) rather than VTMS's own vehicle_type field -- that field is
    # blank for most live rows, so text-matching against it undercounts
    # badly. registry_category is populated for ~96% of the live fleet,
    # giving a real apples-to-apples comparison for both figures.
    try:
        town_targets_raw = fleet_registry.get('towns', {})
        if not town_targets_raw:
            raise ValueError("registry loaded but has no 'towns' data")
        lr = master[master['registry_category'] == 'Loader Rickshaw']
        lr_actual = lr.dropna(subset=['uc_town']).groupby('uc_town').agg(
            vehicles=('vkey','count'),
            moving=('status', lambda s: (s == 'moving').sum()),
        ).to_dict('index')
        full_actual = master.dropna(subset=['uc_town']).groupby('uc_town').agg(
            vehicles=('vkey','count'),
            moving=('status', lambda s: (s == 'moving').sum()),
        ).to_dict('index')
        n_matched = master['registry_category'].notna().sum()
        town_targets = []
        for town, t in town_targets_raw.items():
            lr_a = lr_actual.get(town, {'vehicles': 0, 'moving': 0})
            full_a = full_actual.get(town, {'vehicles': 0, 'moving': 0})
            target_lr = t['target_lr_vehicles']
            target_total = t['target_total_vehicles']
            lr_deployed = int(lr_a['vehicles'])
            full_deployed = int(full_a['vehicles'])
            town_targets.append({
                'town': town,
                'target_lr': target_lr,
                'lr_deployed': lr_deployed,
                'lr_moving': int(lr_a['moving']),
                'lr_deployment_pct': round(100 * lr_deployed / target_lr, 1) if target_lr else None,
                'target_total': target_total,
                'full_fleet_deployed': full_deployed,
                'full_fleet_moving': int(full_a['moving']),
                'full_fleet_deployment_pct': round(100 * full_deployed / target_total, 1) if target_total else None,
                'in_uc_geojson': t['in_uc_geojson'],
            })
        town_targets.sort(key=lambda x: -(x['target_total'] or 0))

        print(); print("=" * 55); print("TOWN FLEET TARGETS — registry target vs. registry-matched live-deployed"); print("=" * 55)
        print(f"Registry-matched: {n_matched}/{len(master)} live vehicles have a known registry category\n")
        for tt in town_targets:
            lr_pct = f"{tt['lr_deployment_pct']}%" if tt['lr_deployment_pct'] is not None else 'n/a'
            full_pct = f"{tt['full_fleet_deployment_pct']}%" if tt['full_fleet_deployment_pct'] is not None else 'n/a'
            print(f"{tt['town']:20s} LR target={tt['target_lr']:>4}  LR deployed={tt['lr_deployed']:>4} ({lr_pct})   |  "
                  f"full target={tt['target_total']:>4}  full deployed={tt['full_fleet_deployed']:>4} ({full_pct})")

        n_assignable = master['in_assigned_area'].notna().sum()
        n_in_area = (master['in_assigned_area'] == True).sum()
        print(f"\nIn assigned area (Lahore vehicles with a known home town): "
              f"{n_in_area}/{n_assignable} currently within their own registered town "
              f"({round(100*n_in_area/n_assignable,1) if n_assignable else 0}%)")
    except Exception as e:
        print(f"\nWARNING: could not compute town targets ({config.TOWN_TARGETS_JSON}): {e}")
        print("Run `python -m fleet_dashboard.pipeline.extract_town_targets` first if "
              "'Lahore Fleet+LRs.xlsx' is present.")
        town_targets = []

    history_csv = config.latest_vehicle_history_csv()
    if history_csv is not None:
        vehicle_tracks, tracks_date = core.load_vehicle_tracks(str(history_csv))
        n_pts = sum(len(v) for v in vehicle_tracks.values())
        print(f"\nVehicle history tracks: {len(vehicle_tracks)} vehicles, "
              f"{n_pts:,} points (from {history_csv.name})")
    else:
        print(f"\nWARNING: no vehicle history export found (vehicle_history_*.csv) -- "
              f"no route-track data this build.")
        vehicle_tracks, tracks_date = {}, None

    payload = {
        'snapshot': snapshot_date,
        'points': records,
        'ucs': ucs_geo,
        'uc_stats': {k:{'vehicles':int(v['vehicles']),'moving':int(v['moving']),
                        'dist':float(v['dist'])} for k,v in agg.items()},
        'employees': employees,
        'roster_ucs': roster_ucs,
        'town_targets': town_targets,
        'vehicle_tracks': vehicle_tracks,
        'vehicle_tracks_date': tracks_date,
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
            'by_town': master['uc_town'].value_counts(dropna=True).to_dict(),
            'assignable': int(master['in_assigned_area'].notna().sum()),
            'in_assigned_area': int((master['in_assigned_area'] == True).sum()),
        }
    }
    data_json = config.PROJECT_ROOT / 'dashboard_data.json'
    json.dump(payload, open(data_json, 'w'), allow_nan=False)
    print(f"Wrote {data_json}")

    # ---- re-embed into the standalone HTML dashboard, if the template is present ----
    template_path = config.PROJECT_ROOT / 'dashboard_template.html'
    html_out_path = config.PROJECT_ROOT / 'LWMC_Fleet_Dashboard.html'
    if template_path.exists():
        template = template_path.read_text(encoding='utf-8')
        html = template.replace('/*DATA*/', json.dumps(payload, allow_nan=False))
        html_out_path.write_text(html, encoding='utf-8')
        print(f"Wrote {html_out_path}")
    else:
        print(f"\nNote: {template_path.name} not found -- skipped re-embedding the standalone HTML dashboard.")


if __name__ == '__main__':
    main()
