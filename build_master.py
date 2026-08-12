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
EMPLOYEE_XLSX = "employee data.xlsx"       # TM/FM/AM-Yard/Night-Shift roster (performance scoping)
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

# ---------- employee roster (performance-scoping) ----------
# Town abbreviation -> full town name, matched against lahore_ucs.geojson's
# `town` property. Verified 1:1 against the geojson's 9 actual town strings
# (nothing left over either direction) but NOT verified against the org's
# own definition of these abbreviations -- review if a mapping looks wrong.
TOWN_ABBR = {
    'AIT': 'Allama Iqbal Town', 'SBT': 'Shalimar Town', 'GT': 'Gulberg Town',
    'NT': 'Nishter Town', 'RT': 'Ravi Town', 'ST': 'Samnabad Town',
    'WT': 'Wagha Town', 'ABT': 'Aziz Bhatti Town', 'DGBT': 'DGBT',
}

ZONE_START_RE = re.compile(r'zone[\s-]*', re.IGNORECASE)
NUM_TOKEN_RE = re.compile(r'(\d+)\s*-?\s*([ab])?', re.IGNORECASE)

def extract_zone_numbers(text):
    """Find every 'Zone <n[,n...]>' cluster in text (comma/&/and separated,
    tolerant of lettered sub-zones like '12-A'). Only digits that directly
    follow the literal word 'Zone' count -- bare digits elsewhere in the
    string (e.g. 'Canal Road Cricle 1') must never be picked up."""
    zones, letter_flagged = [], False
    for m in ZONE_START_RE.finditer(text):
        run_match = re.match(r'[\dABand,&\s-]*', text[m.end():], re.IGNORECASE)
        run = run_match.group(0) if run_match else ''
        for nm in NUM_TOKEN_RE.finditer(run):
            zones.append(nm.group(1))
            if nm.group(2):
                letter_flagged = True
    return zones, letter_flagged

def _split_list(s):
    return [t.strip() for t in re.split(r'[,&]| and ', s, flags=re.IGNORECASE) if t.strip()]

def _town_wildcard(text):
    """Whole-string town wildcard ('GT Complete', 'WT', 'DGBT Complete') or
    a trailing-parenthesis town list (AM Yards: 'Bedian & Kahna (NT)',
    'Saggiyan (RT,DGBT)')."""
    candidate = re.sub(r'\bcomplete\b', '', text, flags=re.IGNORECASE).strip()
    toks = _split_list(candidate)
    if toks and all(t.upper() in TOWN_ABBR for t in toks):
        return [TOWN_ABBR[t.upper()] for t in toks]
    m = re.search(r'\(([^)]*)\)\s*$', text)
    if m:
        toks2 = _split_list(m.group(1))
        if toks2 and all(t.upper() in TOWN_ABBR for t in toks2):
            return [TOWN_ABBR[t.upper()] for t in toks2]
    return None

def resolve_area(raw_text, zone_to_ucs, town_to_ucs):
    """Resolve one Zone/Yard cell to a set of UC codes.
    Returns (method, resolved_zones, resolved_ucs, warnings)."""
    text = '' if raw_text is None else str(raw_text).strip()
    if not text or text == '-':
        return 'unresolved', [], [], [f"empty/placeholder area text: {raw_text!r}"]

    # 1. explicit UC list: a parenthesized number list (with or without a
    #    'UC' prefix) that isn't itself another zone/town reference
    for grp in re.findall(r'\(([^)]*)\)', text):
        nums = re.findall(r'(?:UC[\s-]?)?(\d{2,4})', grp)
        stripped = re.sub(r'UC', '', grp, flags=re.IGNORECASE)
        if nums and not re.search(r'[A-Za-z]{2,}', stripped):
            zones, _ = extract_zone_numbers(text)
            ucs_list = sorted({f"UC-{n}" for n in nums})
            return 'explicit_uc', sorted({f"Zone-{z}" for z in zones}), ucs_list, []

    # 2. zone list (comma/&/and separated, lettered sub-zones approximated
    #    to their base numeric zone)
    zones, letter_flagged = extract_zone_numbers(text)
    if zones:
        warnings = []
        if letter_flagged:
            warnings.append(f"lettered sub-zone approximated to parent zone: {raw_text!r}")
        zone_labels = sorted({f"Zone-{z}" for z in zones})
        ucs_list = sorted({uc for zl in zone_labels for uc in zone_to_ucs.get(zl, [])})
        leftover = ZONE_START_RE.sub('', text)
        leftover = re.sub(r'[\dABand,&\s()-]', '', leftover, flags=re.IGNORECASE)
        if len(leftover) > 2:
            warnings.append(f"ignored trailing text: {raw_text!r}")
        return 'zone_list', zone_labels, ucs_list, warnings

    # 3. town wildcard (whole-cell or AM-Yards trailing-paren form)
    towns = _town_wildcard(text)
    if towns:
        ucs_list = sorted({uc for t in towns for uc in town_to_ucs.get(t, [])})
        return 'town_wildcard', [], ucs_list, []

    # 4. unresolved -- surfaced, not dropped
    return 'unresolved', [], [], [f"unrecognized area text: {raw_text!r}"]

def _clean_id(v):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    s = str(v).strip()
    return s if s else None

def load_employee_roster(xlsx_path, ucs):
    zone_to_ucs, town_to_ucs = {}, {}
    for u in ucs:
        zone_to_ucs.setdefault(u['zone'], set()).add(u['uc'])
        town_to_ucs.setdefault(u['town'], set()).add(u['uc'])
    zone_to_ucs = {k: sorted(v) for k, v in zone_to_ucs.items()}
    town_to_ucs = {k: sorted(v) for k, v in town_to_ucs.items()}
    all_lahore_ucs = sorted({u['uc'] for u in ucs})

    employees = []
    stats = {r: {'total': 0, 'excluded': 0, 'resolved': 0, 'unresolved': 0}
             for r in ('TM', 'FM', 'AM_YARD', 'NIGHT_SHIFT')}

    def add_employee(role, sheet_row, name, area_text, contact=None, cnic=None,
                      designation=None, circle=None):
        stats[role]['total'] += 1
        method, zones, ucs_list, warns = resolve_area(area_text, zone_to_ucs, town_to_ucs)
        stats[role]['unresolved' if method == 'unresolved' else 'resolved'] += 1
        employees.append({
            'id': f"{role}-{sheet_row}",
            'name': str(name).strip(),
            'role': role,
            'designation': None if designation is None or pd.isna(designation) else str(designation).strip(),
            'circle': None if circle is None or pd.isna(circle) else str(circle).strip(),
            'contact': _clean_id(contact),
            'cnic': _clean_id(cnic),
            'raw_area_text': None if area_text is None or pd.isna(area_text) else str(area_text).strip(),
            'resolution_method': method,
            'resolved_zones': zones,
            'resolved_ucs': ucs_list,
            'warnings': warns,
        })

    tm = pd.read_excel(xlsx_path, sheet_name='TMs', header=3)
    tm['Circle'] = tm['Circle'].ffill()
    tm['Town'] = tm['Town'].ffill()
    for i, row in tm.iterrows():
        if pd.isna(row.get('TM')):
            continue
        sheet_row = int(row['Sr.No']) if pd.notna(row.get('Sr.No')) else i + 4
        if pd.isna(row.get('Zone')):
            stats['TM']['excluded'] += 1
            continue
        add_employee('TM', sheet_row, row['TM'], row['Zone'],
                      contact=row.get('Contact No'), circle=row.get('Circle'))

    fm = pd.read_excel(xlsx_path, sheet_name='FMs', header=2)
    fm['Circle'] = fm['Circle'].ffill()
    for i, row in fm.iterrows():
        if pd.isna(row.get('Sr.No')):
            continue
        sheet_row = int(row['Sr.No'])
        if pd.isna(row.get('Name of FM')):
            stats['FM']['excluded'] += 1
            continue
        add_employee('FM', sheet_row, row['Name of FM'], row['Zone'],
                      cnic=row.get('CNIC'), designation=row.get('Designation'), circle=row.get('Circle'))

    am = pd.read_excel(xlsx_path, sheet_name='AM Yards', header=4)
    am['Circle'] = am['Circle'].ffill()
    for i, row in am.iterrows():
        if pd.isna(row.get('Sr. No')):
            continue
        sheet_row = int(row['Sr. No'])
        if pd.isna(row.get('Name of AM Yard')):
            stats['AM_YARD']['excluded'] += 1
            continue
        add_employee('AM_YARD', sheet_row, row['Name of AM Yard'], row['Yard'],
                      cnic=row.get('CNIC'), designation=row.get('Designation'), circle=row.get('Circle'))

    # Night Shift: detected structurally (this sheet has no area column at
    # all), so every row here means "responsible for all of Lahore" -- this
    # generalizes to any future no-area-column sheet, not just this one name.
    ns = pd.read_excel(xlsx_path, sheet_name='Night Shift', header=3)
    for i, row in ns.iterrows():
        if pd.isna(row.get('Name')):
            continue
        stats['NIGHT_SHIFT']['total'] += 1
        stats['NIGHT_SHIFT']['resolved'] += 1
        employees.append({
            'id': f"NIGHT_SHIFT-{i + 1}",
            'name': str(row['Name']).strip(),
            'role': 'NIGHT_SHIFT',
            'designation': None if pd.isna(row.get('Designation')) else str(row['Designation']).strip(),
            'circle': None,
            'contact': None,
            'cnic': _clean_id(row.get('CNIC')),
            'raw_area_text': None,
            'resolution_method': 'all_lahore',
            'resolved_zones': [],
            'resolved_ucs': all_lahore_ucs,
            'warnings': [],
        })

    roster_ucs = sorted({uc for e in employees for uc in e['resolved_ucs']})
    return employees, roster_ucs, stats, all_lahore_ucs

def print_roster_report(employees, roster_ucs, stats, all_lahore_ucs):
    print(); print("=" * 55); print("EMPLOYEE ROSTER — coverage report"); print("=" * 55)
    for role in ('TM', 'FM', 'AM_YARD', 'NIGHT_SHIFT'):
        s = stats[role]
        print(f"{role}: {s['total']} rows -> {s['resolved']} resolved, "
              f"{s['unresolved']} unresolved, {s['excluded']} excluded")
    unresolved = [e for e in employees if e['resolution_method'] == 'unresolved']
    if unresolved:
        print("\nUnresolved (needs manual mapping):")
        for e in unresolved:
            print(f"  - {e['name']} ({e['role']}): {e['raw_area_text']!r}")
    approx = [e for e in employees if any('lettered sub-zone' in w for w in e['warnings'])]
    if approx:
        print("\nLettered sub-zone approximations (widened to the full parent zone):")
        for e in approx:
            print(f"  - {e['name']} ({e['role']}): {e['raw_area_text']!r}")
    covered, total = len(roster_ucs), len(all_lahore_ucs)
    pct = round(100 * covered / total, 1) if total else 0
    print(f"\nRoster covers {covered}/{total} Lahore UCs ({pct}%)")
    uncovered = sorted(set(all_lahore_ucs) - set(roster_ucs))
    if uncovered:
        print(f"Uncovered UCs ({len(uncovered)}): {', '.join(uncovered)}")

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

    # ---- employee roster (performance-scoping) ----
    # vehicle data is the primary product, so a roster problem (missing file,
    # unexpected sheet layout) must not abort the whole build -- degrade to
    # an empty roster instead and say so loudly.
    try:
        employees, roster_ucs, roster_stats, all_lahore_ucs = load_employee_roster(EMPLOYEE_XLSX, ucs)
        print_roster_report(employees, roster_ucs, roster_stats, all_lahore_ucs)
    except Exception as e:
        print(f"\nWARNING: could not load employee roster ({EMPLOYEE_XLSX}): {e}")
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
        'employees': employees,
        'roster_ucs': roster_ucs,
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
