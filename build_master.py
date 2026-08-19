#!/usr/bin/env python3
"""
Build the LWMC fleet master dataset for the local dashboard.

Scope: Lahore city only (Sheikhupura/Kasur/Nankana Sahib rows are dropped --
       UC/zone geometry, the employee roster, and fleet targets are all
       Lahore-specific, so those districts have nothing to attach to here)
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
EMPLOYEE_XLSX = "employee sheet caping.xlsx"  # TM/FM/ZO/AM-Yard/MVI roster (performance scoping)
TOWN_TARGETS_JSON = "Reference Documents/town_targets.json"  # from extract_town_targets.py
SNAPSHOT_DATE = "2026-08-11"

TEHSIL_TO_DISTRICT = {
    'AlIT':'Lahore','ShTo':'Lahore','RaTo':'Lahore','NiTo':'Lahore','WaTo':'Lahore',
    'DaGB':'Lahore','SaTo':'Lahore','AzBT':'Lahore','GuTo':'Lahore',
    'Shei':'Sheikhupura','Fero':'Sheikhupura','Muri':'Sheikhupura','Safd':'Sheikhupura','Shar':'Sheikhupura',
    'Kasu':'Kasur','Patt':'Kasur','Chun':'Kasur','KoRK':'Kasur',
    'NaSa':'Nankana Sahib','SaHi':'Nankana Sahib','ShKo':'Nankana Sahib',
    'OtSi':'Other',
}

# the same 9 Lahore tehsil codes, mapped to the town a vehicle is REGISTERED
# under (its home office) -- used to detect whether a vehicle's current
# GPS-derived uc_town matches where it's actually assigned, i.e. is it
# working inside its own area or has it strayed into someone else's.
TEHSIL_TO_TOWN = {
    'AlIT':'Allama Iqbal Town', 'ShTo':'Shalimar Town', 'RaTo':'Ravi Town',
    'NiTo':'Nishter Town', 'WaTo':'Wagha Town', 'DaGB':'DGBT',
    'SaTo':'Samnabad Town', 'AzBT':'Aziz Bhatti Town', 'GuTo':'Gulberg Town',
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

# Full town-name spelling -> geojson's canonical spelling. "employee sheet
# caping.xlsx" writes towns out in full (not abbreviated like the old
# roster file) but doesn't always match lahore_ucs.geojson's own spelling
# ("Nishtar"/"Nishter", "Data Gunj Bakhsh Town"/"DGBT", "Samanabad"/
# "Samnabad") -- same normalization problem extract_town_targets.py already
# solved for the fleet registry, applied here to the roster.
TOWN_FULL_NORM = {
    'allama iqbal town': 'Allama Iqbal Town', 'gulberg town': 'Gulberg Town',
    'nishtar town': 'Nishter Town', 'nishter town': 'Nishter Town',
    'ravi town': 'Ravi Town', 'samanabad town': 'Samnabad Town',
    'samnabad town': 'Samnabad Town', 'wagha town': 'Wagha Town',
    'aziz bhatti town': 'Aziz Bhatti Town',
    'data gunj bakhsh town': 'DGBT', 'dgbt': 'DGBT',
    'shalimar town': 'Shalimar Town',
}

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

def resolve_town_field(text, town_to_ucs):
    """Resolve a roster 'Town' cell (full names, sometimes a comma/&-joined
    list of abbreviations like 'WT, ABT& RR') to a set of UC codes. Unlike
    _town_wildcard's all-or-nothing match, this resolves whatever tokens ARE
    recognized and flags the rest -- 'WT, ABT& RR' should still resolve to
    Wagha Town + Aziz Bhatti Town with 'RR' flagged, not be thrown away."""
    if not text or not str(text).strip():
        return [], []
    toks = _split_list(str(text).strip())
    matched, unmatched = [], []
    for t in toks:
        norm = TOWN_FULL_NORM.get(t.strip().lower()) or TOWN_ABBR.get(t.strip().upper())
        if norm:
            matched.append(norm)
        else:
            unmatched.append(t)
    if not matched:
        return [], []
    ucs_list = sorted({uc for tn in matched for uc in town_to_ucs.get(tn, [])})
    warnings = [f"partially matched town list, ignored: {', '.join(unmatched)}"] if unmatched else []
    return ucs_list, warnings

def _clean_id(v):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    s = str(v).strip()
    return s if s else None

# Sheet name -> role code. "employee sheet caping.xlsx" replaced the old
# TMs/FMs/AM Yards/Night Shift workbook: Zonal Officers and MVI are new
# roles, and "Night Shift" is no longer a separate sheet -- it's now a
# per-row Shift value (1st/2nd/Night) inside each of these 5 sheets, so a
# person working two shifts appears as two rows (handled naturally since
# each row gets its own id from its own Sr. No.).
ROSTER_SHEETS = [
    ('Town Managers', 'TM'), ('Fleet Managers', 'FM'),
    ('Zonal Officers', 'ZO'), ('AM Yards', 'AM_YARD'), ('MVI', 'MVI'),
]

def _cell_str(v):
    return None if v is None or (isinstance(v, float) and pd.isna(v)) else str(v).strip() or None

def resolve_roster_row(role, town_raw, zone_nums_raw, uc_nums_raw, area_raw, workshop_raw, zone_to_ucs, town_to_ucs):
    """Resolve one roster row to a set of UC codes. Unlike the old employee
    data.xlsx (which needed regex extraction), this file already resolves
    Zone Numbers / UC Numbers to clean comma-separated int lists -- so this
    just picks the most specific column that's populated, in priority
    order, instead of re-deriving them from free text."""
    uc_s = _cell_str(uc_nums_raw)
    if uc_s:
        nums = [n.strip() for n in re.split(r'[,\s]+', uc_s) if n.strip()]
        ucs_list = sorted({f"UC-{n}" for n in nums}, key=lambda s: int(s.split('-')[1]))
        return 'explicit_uc', ucs_list, []
    zn_s = _cell_str(zone_nums_raw)
    if zn_s:
        nums = [n.strip() for n in re.split(r'[,\s]+', zn_s) if n.strip()]
        zone_labels = sorted({f"Zone-{n}" for n in nums}, key=lambda s: int(s.split('-')[1]))
        ucs_list = sorted({uc for zl in zone_labels for uc in zone_to_ucs.get(zl, [])})
        return 'zone_list', ucs_list, []
    ucs_list, warns = resolve_town_field(_cell_str(town_raw), town_to_ucs)
    if ucs_list:
        return 'town_wildcard', ucs_list, warns
    # Town column was blank/unresolvable -- some rows (mostly MVI/AM Yard
    # workshop postings) carry the same information in Area/Workshop text
    # instead, either as a bare abbreviation list ("SBT, NT, AIT, GT") or a
    # trailing-paren town tag ("Childran Workshop (NT)").
    for free_text in (_cell_str(workshop_raw), _cell_str(area_raw)):
        if not free_text:
            continue
        ucs_list, warns = resolve_town_field(free_text, town_to_ucs)
        if ucs_list:
            return 'town_wildcard', ucs_list, warns
        towns = _town_wildcard(free_text)
        if towns:
            ucs_list = sorted({uc for t in towns for uc in town_to_ucs.get(t, [])})
            return 'town_wildcard', ucs_list, []
    return 'unresolved', [], []

def _zone_sort_key(z):
    m = re.match(r'Zone-(\d+)', z)
    return int(m.group(1)) if m else 0

def load_employee_roster(xlsx_path, ucs):
    zone_to_ucs, town_to_ucs, uc_to_zones = {}, {}, {}
    for u in ucs:
        zone_to_ucs.setdefault(u['zone'], set()).add(u['uc'])
        town_to_ucs.setdefault(u['town'], set()).add(u['uc'])
        uc_to_zones.setdefault(u['uc'], set()).add(u['zone'])
    zone_to_ucs = {k: sorted(v) for k, v in zone_to_ucs.items()}
    town_to_ucs = {k: sorted(v) for k, v in town_to_ucs.items()}
    all_lahore_ucs = sorted({u['uc'] for u in ucs})

    employees = []
    stats = {r: {'total': 0, 'resolved': 0, 'unresolved': 0} for _, r in ROSTER_SHEETS}

    for sheet_name, role in ROSTER_SHEETS:
        df = pd.read_excel(xlsx_path, sheet_name=sheet_name, header=1)
        for _, row in df.iterrows():
            if pd.isna(row.get('Name')) or not str(row.get('Name')).strip():
                continue
            stats[role]['total'] += 1
            sr = row.get('Sr. No.')
            sheet_row = int(sr) if pd.notna(sr) else stats[role]['total']
            method, ucs_list, warns = resolve_roster_row(
                role, row.get('Town'), row.get('Zone Numbers'), row.get('UC Numbers'),
                row.get('Area'), row.get('Workshop / Yard'), zone_to_ucs, town_to_ucs)
            stats[role]['unresolved' if method == 'unresolved' else 'resolved'] += 1
            # Zones covered, derived from the KML/geojson's own UC->zone
            # mapping applied to the UCs just resolved above -- this reflects
            # ground truth (lahore_ucs.geojson) rather than re-echoing the
            # roster's raw "Zone Numbers" text, so it's correct regardless of
            # which resolution path (explicit UC list / zone list / town
            # wildcard) actually produced ucs_list.
            zones = sorted({z for uc in ucs_list for z in uc_to_zones.get(uc, ())}, key=_zone_sort_key)
            employees.append({
                'id': f"{role}-{sheet_row}",
                'name': str(row['Name']).strip(),
                'role': role,
                'designation': _cell_str(row.get('Sub-Designation')),
                'circle': _cell_str(row.get('Circle')),
                'shift': _cell_str(row.get('Shift')),
                'contact': _clean_id(row.get('Contact No')),
                'cnic': _clean_id(row.get('CNIC')),
                'raw_town': _cell_str(row.get('Town')),
                'raw_area_text': _cell_str(row.get('Area')) or _cell_str(row.get('Workshop / Yard')),
                'posting_type': _cell_str(row.get('Posting Type')),
                'message': _cell_str(row.get('Message')),
                'message_type': _cell_str(row.get('Message Type')),
                'resolution_method': method,
                'resolved_zones': zones,
                'resolved_ucs': ucs_list,
                'warnings': warns,
            })

    roster_ucs = sorted({uc for e in employees for uc in e['resolved_ucs']})
    return employees, roster_ucs, stats, all_lahore_ucs

def print_roster_report(employees, roster_ucs, stats, all_lahore_ucs):
    print(); print("=" * 55); print("EMPLOYEE ROSTER — coverage report"); print("=" * 55)
    for _, role in ROSTER_SHEETS:
        s = stats[role]
        print(f"{role}: {s['total']} rows -> {s['resolved']} resolved, {s['unresolved']} unresolved")
    unresolved = [e for e in employees if e['resolution_method'] == 'unresolved']
    if unresolved:
        print("\nUnresolved (needs manual mapping):")
        for e in unresolved:
            print(f"  - {e['name']} ({e['role']}): town={e['raw_town']!r} area={e['raw_area_text']!r}")
    partial = [e for e in employees if any('partially matched' in w for w in e['warnings'])]
    if partial:
        print("\nPartially matched town lists (unmatched tokens ignored):")
        for e in partial:
            print(f"  - {e['name']} ({e['role']}): {e['raw_town']!r} -> {e['warnings']}")
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

    # Dashboard scope is Lahore city only -- UC/zone/town geometry, the
    # employee roster, and the fleet targets are all Lahore-specific, so
    # Sheikhupura/Kasur/Nankana Sahib vehicles are dropped here rather than
    # carried through as dead weight nothing downstream can make use of.
    n_before = len(lw)
    lw = lw[lw['district'] == 'Lahore'].copy()
    print(f"Scope: Lahore only -- kept {len(lw)}/{n_before} VTMS/LWMC rows "
          f"({n_before - len(lw)} non-Lahore rows dropped)")

    lw['vkey']          = norm_key(lw['Vehicle'])
    lw['snapshot']      = SNAPSHOT_DATE

    # fleet establishment registry (Reference Documents/town_targets.json,
    # from extract_town_targets.py) -- gives each vehicle its REAL registered
    # category/town by Vehicle ID, far more reliable than VTMS's own
    # vehicle_type field (blank for most rows). Additive reference data: a
    # missing/stale file degrades to "no registry match for anyone" rather
    # than failing the build.
    try:
        fleet_registry = json.load(open(TOWN_TARGETS_JSON, encoding='utf-8'))
    except Exception as e:
        print(f"\nWARNING: could not load fleet registry ({TOWN_TARGETS_JSON}): {e}")
        print("Run extract_town_targets.py first if 'Lahore Fleet+LRs.xlsx' is present.")
        fleet_registry = {'towns': {}, 'vehicles': {}}
    reg_vehicles = fleet_registry.get('vehicles', {})
    lw['registry_category'] = lw['vkey'].map(lambda k: reg_vehicles.get(k, {}).get('category'))
    lw['registry_town']     = lw['vkey'].map(lambda k: reg_vehicles.get(k, {}).get('town'))

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

    # assigned_town = the town a vehicle is actually registered to. Prefer
    # the fleet registry (matched by Vehicle ID -- authoritative, covers
    # ~96% of live vehicles); fall back to the tehsil-code-derived town
    # (coarser, but covers everyone) only when a vehicle has no registry
    # match. in_assigned_area compares that against where its live GPS
    # currently places it. Only meaningful for the 9 Lahore towns -- a
    # vehicle with no resolvable home town gets None, not False, since
    # "assigned area" isn't defined for it here.
    lw['assigned_town'] = lw['registry_town'].fillna(lw['code'].map(TEHSIL_TO_TOWN))
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
            'uc','uc_town','uc_zone','registry_category','assigned_town','in_assigned_area','snapshot']
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

    # ---- town fleet targets vs. live-deployed (Reference Documents/town_targets.json) ----
    # additive reference data, not part of the daily VTMS/roster inputs -- if
    # it's missing or stale, degrade to an empty list rather than fail the build.
    #
    # Both targets (LR-only and full fleet) now come from the fleet
    # establishment registry, and "deployed" is filtered by registry_category
    # (joined by Vehicle ID) rather than VTMS's own vehicle_type field --
    # that field is blank for most live rows, so text-matching against it
    # undercounts badly. registry_category is populated for ~96% of the
    # live fleet, giving a real apples-to-apples comparison for both figures.
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
        print(f"\nWARNING: could not compute town targets ({TOWN_TARGETS_JSON}): {e}")
        print("Run extract_town_targets.py first if 'vehicle data.xlsx' is present.")
        town_targets = []

    payload = {
        'snapshot': SNAPSHOT_DATE,
        'points': records,
        'ucs': ucs_geo,
        'uc_stats': {k:{'vehicles':int(v['vehicles']),'moving':int(v['moving']),
                        'dist':float(v['dist'])} for k,v in agg.items()},
        'employees': employees,
        'roster_ucs': roster_ucs,
        'town_targets': town_targets,
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
    json.dump(payload, open('dashboard_data.json','w'), allow_nan=False)
    print("Wrote dashboard_data.json")

if __name__ == '__main__':
    main()
