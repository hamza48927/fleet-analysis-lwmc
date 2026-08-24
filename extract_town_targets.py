#!/usr/bin/env python3
"""
Extract per-town fleet TARGET figures, and a per-vehicle registry lookup,
from "Lahore Fleet+LRs.xlsx" -- the LWMC fleet establishment roster -- into
a clean reference file the dashboard build can read.

This supersedes an earlier version of this script that read "vehicle
data.xlsx" (an hourly control-room log). Those hourly-log target numbers
turned out to be wrong -- confirmed by the user and cross-checked here:
comparing them to live GPS-deployed counts landed in a nonsensical 180-450%
for the whole fleet, or an implausible 0-118% even when narrowed to
Loader-Rickshaw-only. "Lahore Fleet+LRs.xlsx" is a flat per-vehicle
registry (Sr No / Vehicle ID / Fuel ID / Vehicle Category / Town), not an
hourly snapshot, and its per-vehicle Vehicle ID column matches ~96% of the
live VTMS "vehicle" field directly -- so instead of only producing
town-level aggregates, this script also emits a vehicle_id -> {category,
town} lookup so build_master.py can join each live vehicle to its REAL
registered category and town, which is far more reliable than VTMS's own
vehicle_type field (blank for ~63% of live vehicles).

Run this again only if "Lahore Fleet+LRs.xlsx" is replaced with an updated
version (it is NOT part of the daily VTMS build cycle -- build_master.py
just reads the JSON this script produces).
Output: Reference Documents/town_targets.json
"""
import json
import pathlib
from collections import Counter, defaultdict

import openpyxl

SRC_XLSX = "Lahore Fleet+LRs.xlsx"
OUT_JSON = "Reference Documents/town_targets.json"

# The registry spells this one town differently than lahore_ucs.geojson;
# normalize so the dashboard can join target vs. live-GPS-actual directly
# on town name. Everything else in the registry already matches the
# geojson's town strings exactly.
TOWN_NORM = {'samanabad town': 'Samnabad Town'}

GEOJSON_TOWNS = {
    'Allama Iqbal Town', 'Aziz Bhatti Town', 'DGBT', 'Gulberg Town',
    'Nishter Town', 'Ravi Town', 'Samnabad Town', 'Shalimar Town', 'Wagha Town',
}


def norm_town(s):
    if not isinstance(s, str) or not s.strip():
        return None
    t = s.strip()
    return TOWN_NORM.get(t.lower(), t)


def norm_vehicle_id(s):
    """Same normalization build_master.py's norm_key() applies to VTMS
    vehicle numbers, so the two can be joined reliably regardless of
    hyphen/space formatting differences."""
    if not isinstance(s, str):
        return None
    return ''.join(ch for ch in s.strip().upper() if ch.isalnum())


def main():
    wb = openpyxl.load_workbook(SRC_XLSX, data_only=True)
    ws = wb['Sheet1']

    vehicles = {}          # normalized vehicle id -> {category, town, raw_id}
    conflicts = []         # ids seen twice with different category/town
    town_totals = Counter()
    town_lr = Counter()
    n_rows = 0
    n_no_id = 0

    for row in ws.iter_rows(min_row=2, values_only=True):
        # columns: (blank, Sr No, Vehicle ID, Fuel ID, Vehicle Category, Town, <unlabeled>)
        _, sr, vid, fid, cat, town, _g = row
        if vid is None:
            continue
        n_rows += 1
        key = norm_vehicle_id(vid)
        if not key:
            n_no_id += 1
            continue
        cat = cat.strip() if isinstance(cat, str) else None
        town_n = norm_town(town)

        if key in vehicles:
            prev = vehicles[key]
            if prev['category'] != cat or prev['town'] != town_n:
                conflicts.append({'vehicle_id': str(vid).strip(), 'kept': prev,
                                   'dropped': {'category': cat, 'town': town_n}})
            continue  # first occurrence wins
        vehicles[key] = {'category': cat, 'town': town_n, 'raw_id': str(vid).strip()}

        if town_n:
            town_totals[town_n] += 1
            if cat == 'Loader Rickshaw':
                town_lr[town_n] += 1

    towns = {}
    for town in sorted(town_totals):
        towns[town] = {
            'target_total_vehicles': town_totals[town],
            'target_lr_vehicles': town_lr.get(town, 0),
            'in_uc_geojson': town in GEOJSON_TOWNS,
        }

    print(f"Parsed {n_rows} registry rows ({n_rows - n_no_id} with a usable Vehicle ID, "
          f"{len(vehicles)} unique after de-duplication, {len(conflicts)} conflicting duplicates)")
    print(f"\n{'Town':22s}{'Total target':>14s}{'LR target':>12s}")
    for town, t in sorted(towns.items(), key=lambda x: -x[1]['target_total_vehicles']):
        tag = '' if t['in_uc_geojson'] else '  (no UC polygon -- reference only)'
        print(f"{town:22s}{t['target_total_vehicles']:>14d}{t['target_lr_vehicles']:>12d}{tag}")
    if conflicts:
        print(f"\n{len(conflicts)} vehicle IDs appeared more than once with different data "
              f"(kept the first occurrence, listed in '_conflicts' in the output):")
        for c in conflicts[:10]:
            print(f"  {c['vehicle_id']}: kept {c['kept']}, dropped {c['dropped']}")

    out = {
        'source_file': SRC_XLSX,
        'note': ("Per-town fleet targets and a per-vehicle registry lookup, extracted from "
                 "the LWMC fleet establishment roster (Lahore Fleet+LRs.xlsx) -- a flat "
                 "per-vehicle list (Vehicle ID / Vehicle Category / Town), not an hourly "
                 "snapshot. 'target_total_vehicles' is every registered vehicle assigned to "
                 "that town; 'target_lr_vehicles' is the Loader Rickshaw subset. The 'vehicles' "
                 "map lets build_master.py join each live VTMS vehicle to its REAL registered "
                 "category/town by Vehicle ID, which is far more reliable than VTMS's own "
                 "vehicle_type field (frequently blank)."),
        'towns': towns,
        'vehicles': {k: {'category': v['category'], 'town': v['town']} for k, v in vehicles.items()},
        '_conflicts': conflicts,
    }
    pathlib.Path('Reference Documents').mkdir(exist_ok=True)
    json.dump(out, open(OUT_JSON, 'w', encoding='utf-8'), indent=2, ensure_ascii=False)
    print(f"\nWrote {OUT_JSON}")


if __name__ == '__main__':
    main()
