"""
Loads the fleet establishment registry (every Vehicle ID / Category / Town
from "Lahore Fleet+LRs.xlsx"), plus its derived per-town targets, from
Reference Documents/town_targets.json -- produced by
fleet_dashboard/pipeline/extract_town_targets.py.

This is the full registry, not just the vehicles currently reporting live
in VTMS: a vehicle that is registered but not live today still appears here.
"""
from __future__ import annotations

import json

import pandas as pd

from .. import config


def load_registry() -> pd.DataFrame:
    """One row per registered vehicle: vkey, raw_id, category, town."""
    data = json.loads(config.TOWN_TARGETS_JSON.read_text(encoding="utf-8"))
    vehicles = data.get("vehicles", {})
    rows = [
        {
            "vkey": key,
            "raw_id": v.get("raw_id") or key,
            "registry_category": v.get("category"),
            "registry_town": v.get("town"),
        }
        for key, v in vehicles.items()
    ]
    return pd.DataFrame(rows)


def load_town_targets() -> dict:
    """town -> {target_total_vehicles, target_lr_vehicles, in_uc_geojson}."""
    data = json.loads(config.TOWN_TARGETS_JSON.read_text(encoding="utf-8"))
    return data.get("towns", {})
