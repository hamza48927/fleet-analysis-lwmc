"""
Shared, dependency-free data helpers used by every part of the dashboard:
VTMS column cleaning, UC/zone point-in-polygon resolution, and employee
roster parsing.

This is the one place this logic lives. The daily pipeline
(fleet_dashboard/pipeline/build_master.py), the live in-app snapshot
(fleet_dashboard/data/*.py) and the performance reports
(fleet_dashboard/reports/*.py) all import from here instead of each
re-implementing (or importing a copy of) the same parsing rules.
"""
from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import pandas as pd

TEHSIL_TO_DISTRICT = {
    'AlIT': 'Lahore', 'ShTo': 'Lahore', 'RaTo': 'Lahore', 'NiTo': 'Lahore', 'WaTo': 'Lahore',
    'DaGB': 'Lahore', 'SaTo': 'Lahore', 'AzBT': 'Lahore', 'GuTo': 'Lahore',
    'Shei': 'Sheikhupura', 'Fero': 'Sheikhupura', 'Muri': 'Sheikhupura', 'Safd': 'Sheikhupura', 'Shar': 'Sheikhupura',
    'Kasu': 'Kasur', 'Patt': 'Kasur', 'Chun': 'Kasur', 'KoRK': 'Kasur',
    'NaSa': 'Nankana Sahib', 'SaHi': 'Nankana Sahib', 'ShKo': 'Nankana Sahib',
    'OtSi': 'Other',
}

# the same 9 Lahore tehsil codes, mapped to the town a vehicle is REGISTERED
# under (its home office) -- used to detect whether a vehicle's current
# GPS-derived uc_town matches where it's actually assigned, i.e. is it
# working inside its own area or has it strayed into someone else's.
TEHSIL_TO_TOWN = {
    'AlIT': 'Allama Iqbal Town', 'ShTo': 'Shalimar Town', 'RaTo': 'Ravi Town',
    'NiTo': 'Nishter Town', 'WaTo': 'Wagha Town', 'DaGB': 'DGBT',
    'SaTo': 'Samnabad Town', 'AzBT': 'Aziz Bhatti Town', 'GuTo': 'Gulberg Town',
}

# Town abbreviation -> full town name, matched against lahore_ucs.geojson's
# `town` property.
TOWN_ABBR = {
    'AIT': 'Allama Iqbal Town', 'SBT': 'Shalimar Town', 'GT': 'Gulberg Town',
    'NT': 'Nishter Town', 'RT': 'Ravi Town', 'ST': 'Samnabad Town',
    'WT': 'Wagha Town', 'ABT': 'Aziz Bhatti Town', 'DGBT': 'DGBT',
}

# Full town-name spelling -> geojson's canonical spelling. The roster
# spreadsheet writes towns out in full but doesn't always match
# lahore_ucs.geojson's own spelling.
TOWN_FULL_NORM = {
    'allama iqbal town': 'Allama Iqbal Town', 'gulberg town': 'Gulberg Town',
    'nishtar town': 'Nishter Town', 'nishter town': 'Nishter Town',
    'ravi town': 'Ravi Town', 'samanabad town': 'Samnabad Town',
    'samnabad town': 'Samnabad Town', 'wagha town': 'Wagha Town',
    'aziz bhatti town': 'Aziz Bhatti Town',
    'data gunj bakhsh town': 'DGBT', 'dgbt': 'DGBT',
    'shalimar town': 'Shalimar Town',
}

# Sheet name -> role code, in the roster workbook ("employee data sheet.xlsx").
ROSTER_SHEETS = [
    ('Town Managers', 'TM'), ('Fleet Managers', 'FM'),
    ('Zonal Officers', 'ZO'), ('AM Yards', 'AM_YARD'), ('MVI', 'MVI'),
]

MAX_TRACK_POINTS_PER_VEHICLE = 250


# ---------- column cleaning ----------
def num(s):
    return pd.to_numeric(s.astype(str).str.replace(',', '', regex=False).replace('-', np.nan), errors='coerce')


def norm_key(s):
    return s.astype(str).str.upper().str.replace(r'[^A-Z0-9]', '', regex=True)


def norm_vehicle_id(s):
    """Scalar version of norm_key, for joining a single id (e.g. from a
    registry spreadsheet) against a norm_key'd dataframe column."""
    if not isinstance(s, str):
        return None
    return ''.join(ch for ch in s.strip().upper() if ch.isalnum())


# ---------- point in polygon (ray casting, no deps) ----------
def point_in_ring(x, y, ring):
    inside = False
    n = len(ring)
    j = n - 1
    for i in range(n):
        xi, yi = ring[i]
        xj, yj = ring[j]
        if ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / (yj - yi + 1e-15) + xi):
            inside = not inside
        j = i
    return inside


def load_ucs(path):
    import json
    gj = json.load(open(path))
    ucs = []
    for ft in gj['features']:
        ring = ft['geometry']['coordinates'][0]
        xs = [p[0] for p in ring]
        ys = [p[1] for p in ring]
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


def zone_sort_key(z):
    m = re.match(r'Zone-(\d+)', str(z))
    return int(m.group(1)) if m else 0


# ---------- employee roster parsing ----------
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
    list of abbreviations like 'WT, ABT& RR') to a set of UC codes. Resolves
    whatever tokens ARE recognized and flags the rest."""
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


def _cell_str(v):
    return None if v is None or (isinstance(v, float) and pd.isna(v)) else str(v).strip() or None


def _extract_numbers(text):
    """Pulls bare UC/zone numbers out of a cell that may carry parenthetical
    annotations ('231 (PP-159)' -- a provincial-assembly constituency
    reference, not a UC) or letter-suffixed sub-codes ('194-B (Barki Road)'
    -- collapsed to its base number 194). Parenthetical content is dropped
    entirely before extracting digits, so annotation numbers never get
    mistaken for UC/zone numbers."""
    cleaned = re.sub(r'\([^)]*\)', ' ', str(text))
    return re.findall(r'\d+', cleaned)


def resolve_roster_row(role, town_raw, zone_nums_raw, uc_nums_raw, area_raw, workshop_raw, zone_to_ucs, town_to_ucs):
    """Resolve one roster row to a set of UC codes, picking the most
    specific populated column in priority order: explicit UC numbers, zone
    numbers, town text, then free-text Area/Workshop as a last resort."""
    uc_s = _cell_str(uc_nums_raw)
    if uc_s:
        nums = _extract_numbers(uc_s)
        ucs_list = sorted({f"UC-{n}" for n in nums}, key=lambda s: int(s.split('-')[1]))
        return 'explicit_uc', ucs_list, []
    zn_s = _cell_str(zone_nums_raw)
    if zn_s:
        nums = _extract_numbers(zn_s)
        zone_labels = sorted({f"Zone-{n}" for n in nums}, key=lambda s: int(s.split('-')[1]))
        ucs_list = sorted({uc for zl in zone_labels for uc in zone_to_ucs.get(zl, [])})
        return 'zone_list', ucs_list, []
    ucs_list, warns = resolve_town_field(_cell_str(town_raw), town_to_ucs)
    if ucs_list:
        return 'town_wildcard', ucs_list, warns
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


def load_employee_roster(xlsx_path, ucs):
    """Returns (employees, roster_ucs, stats, all_lahore_ucs). Each employee
    dict has: id, name, role, designation, circle, shift, contact, cnic,
    raw_town, raw_area_text, posting_type, message, message_type,
    resolution_method, resolved_zones, resolved_ucs, warnings."""
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
            zones = sorted({z for uc in ucs_list for z in uc_to_zones.get(uc, ())}, key=zone_sort_key)
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
    print()
    print("=" * 55)
    print("EMPLOYEE ROSTER — coverage report")
    print("=" * 55)
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


# ---------- vehicle history tracks (per-vehicle route for the day) ----------
# Two export layouts have been seen for this, both usable interchangeably:
#   - small "vehicle_history_<start>_to_<end>.csv" (one day, a few MB): a
#     'vehicle' + 'recordDateTime' column pair.
#   - large per-second "activity_<start>_to_<end>.csv" (multi-day, can be
#     multiple GB / tens of millions of rows): 'Registration Number' (or
#     'alias') + 'date' instead. Read in chunks and filtered down to one
#     day as it streams in, rather than ever loading the whole file, so a
#     multi-gigabyte export doesn't need to fit in memory at once.
TRACK_VEHICLE_COLS = ['vehicle', 'Registration Number', 'alias']
TRACK_TIME_COLS = ['recordDateTime', 'date']

_TRACK_DATE_RANGE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})_to_(\d{4}-\d{2}-\d{2})")

# Caches the most recent result (path + mtime + params -> result) so
# reloading the app after changing an unrelated data source doesn't re-scan
# a multi-gigabyte activity export it's already processed once this session.
_track_cache: dict = {}


def _track_target_date_from_filename(path) -> str | None:
    """The end date of a '..._YYYY-MM-DD_to_YYYY-MM-DD.csv' filename (the
    most recent day in the export), used as the default day to keep when
    the caller doesn't ask for a specific one."""
    m = _TRACK_DATE_RANGE_RE.search(Path(path).name)
    return m.group(2) if m else None


def load_vehicle_tracks(csv_path, max_points=MAX_TRACK_POINTS_PER_VEHICLE, target_date=None,
                         chunksize=1_000_000):
    """Returns (tracks, single_date). tracks: {vkey: [[lat,lon,time,speed],...]},
    each vehicle's points sorted by time and downsampled to at most
    max_points. single_date is 'YYYY-MM-DD' when the result covers exactly
    one calendar day (the normal case -- either the file already was one
    day, or target_date/the filename's date range picked one), in which
    case `time` is compacted to "HH:MM:SS"; otherwise `time` is a full ISO
    string.

    A multi-day export keeps only ONE day (target_date, or the filename's
    end date, or -- failing both -- whatever the data itself turns out to
    be) rather than all of them: the map only ever shows one day's route
    per vehicle at a time, so carrying every day into dashboard_data.json
    would just bloat the payload for no benefit."""
    csv_path = Path(csv_path)
    if target_date is None:
        target_date = _track_target_date_from_filename(csv_path)

    cache_key = (str(csv_path), csv_path.stat().st_mtime, max_points, target_date)
    cached = _track_cache.get(cache_key)
    if cached is not None:
        return cached

    header = pd.read_csv(csv_path, nrows=0).columns.tolist()
    vehicle_col = next((c for c in TRACK_VEHICLE_COLS if c in header), None)
    time_col = next((c for c in TRACK_TIME_COLS if c in header), None)
    if vehicle_col is None or time_col is None or 'lat' not in header or 'lon' not in header:
        raise RuntimeError(f"Unrecognized vehicle-track CSV layout in {csv_path.name} (columns: {header})")
    has_speed = 'speed' in header
    usecols = [vehicle_col, time_col, 'lat', 'lon'] + (['speed'] if has_speed else [])
    time_fmt = '%H:%M:%S' if target_date else '%Y-%m-%dT%H:%M:%S'

    buffers: dict[str, list] = {}
    seen_dates: set = set()

    for chunk in pd.read_csv(csv_path, usecols=usecols, chunksize=chunksize):
        chunk['lat'] = pd.to_numeric(chunk['lat'], errors='coerce')
        chunk['lon'] = pd.to_numeric(chunk['lon'], errors='coerce')
        chunk['_t'] = pd.to_datetime(chunk[time_col], errors='coerce')
        chunk = chunk.dropna(subset=[vehicle_col, 'lat', 'lon', '_t'])
        if chunk.empty:
            continue
        if target_date:
            chunk = chunk[chunk['_t'].dt.strftime('%Y-%m-%d') == target_date]
            if chunk.empty:
                continue
        seen_dates.update(chunk['_t'].dt.strftime('%Y-%m-%d').unique().tolist())

        vkeys = norm_key(chunk[vehicle_col]).to_numpy()
        lats = chunk['lat'].round(6).to_numpy()
        lons = chunk['lon'].round(6).to_numpy()
        times = chunk['_t'].dt.strftime(time_fmt).to_numpy()
        speeds = chunk['speed'].to_numpy() if has_speed else [None] * len(chunk)

        for vkey, lat, lon, t, sp in zip(vkeys, lats, lons, times, speeds):
            buffers.setdefault(vkey, []).append(
                [float(lat), float(lon), t, None if pd.isna(sp) else round(float(sp), 1)]
            )

    single_date = target_date or (next(iter(seen_dates)) if len(seen_dates) == 1 else None)

    tracks = {}
    for vkey, pts in buffers.items():
        pts.sort(key=lambda p: p[2])
        if len(pts) > max_points:
            idx = np.linspace(0, len(pts) - 1, max_points).round().astype(int)
            pts = [pts[i] for i in sorted(set(idx))]
        tracks[vkey] = pts

    _track_cache.clear()
    _track_cache[cache_key] = (tracks, single_date)
    return tracks, single_date
