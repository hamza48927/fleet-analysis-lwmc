"""
Assembles the single per-vehicle table the dashboard is built on:
    every registered vehicle (Lahore Fleet+LRs.xlsx, via registry.py)
        FULL OUTER JOIN
    today's live VTMS snapshot (vtms.py), UC/zone/town already resolved

So a vehicle that is registered but not reporting today still appears (with
no live position/status); a vehicle that is reporting today but has no
registry match also still appears (flagged "not in registry"), rather than
either case being silently dropped.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from . import core, registry, roster, vtms


@dataclass
class FleetSnapshot:
    vehicles: pd.DataFrame
    employees: list
    town_targets: dict
    vtms_file: str | None
    status_file: str | None
    warnings: list[str] = field(default_factory=list)


def _assigned_town(row) -> str | None:
    if pd.notna(row.get("registry_town")):
        return row["registry_town"]
    code = row.get("tehsil_short")
    if isinstance(code, str):
        return core.TEHSIL_TO_TOWN.get(code)
    return None


def build_snapshot() -> FleetSnapshot:
    warnings: list[str] = []

    reg = registry.load_registry()
    live, vtms_file, status_file = vtms.load_live_snapshot()
    if vtms_file is None:
        warnings.append("No VTMS export found (export-vtms-active-logs-*.csv) -- "
                         "showing registry-only data, nothing marked live.")
    if status_file is None:
        warnings.append("No vehicle-status export found -- battery/reporting fields will be blank.")

    live = live.copy()
    live["is_live"] = True

    merged = reg.merge(live, on="vkey", how="outer", indicator=True)
    merged["is_live"] = merged["is_live"].fillna(False)

    # raw_id: prefer the registry's own spelling, fall back to VTMS's
    # display "vehicle" field for vehicles VTMS reports that the registry
    # has no entry for at all.
    merged["raw_id"] = merged["raw_id"].where(merged["raw_id"].notna(), merged["vehicle"])
    merged["vehicle"] = merged["vehicle"].where(merged["vehicle"].notna(), merged["raw_id"])

    merged["in_registry"] = merged["_merge"].isin(["left_only", "both"])
    merged = merged.drop(columns=["_merge"])

    merged["assigned_town"] = merged.apply(_assigned_town, axis=1)
    merged["in_assigned_area"] = None
    has_both = merged["assigned_town"].notna() & merged["uc_town"].notna()
    merged.loc[has_both, "in_assigned_area"] = (
        merged.loc[has_both, "assigned_town"] == merged.loc[has_both, "uc_town"]
    )

    # Category/town shown in the table and used for filtering: the registry
    # value where available (authoritative), falling back to VTMS's own
    # (often blank) Vehicle Type for vehicles the registry doesn't cover.
    merged["category"] = merged["registry_category"].where(
        merged["registry_category"].notna(), merged["vehicle_type"]
    )
    merged["town"] = merged["assigned_town"]

    merged["status"] = merged["status"].fillna("not_live")

    col_order = [
        "vkey", "raw_id", "vehicle", "category", "registry_category", "vehicle_type",
        "town", "registry_town", "assigned_town", "in_assigned_area",
        "uc", "uc_zone", "uc_town", "is_live", "in_registry",
        "status", "engine", "distance_km", "working_min",
        "lat", "lon", "reporting_status", "status_text", "battery_volt", "tracker_offline",
        "office", "tehsil_code", "timestamp", "last_received",
    ]
    for c in col_order:
        if c not in merged.columns:
            merged[c] = None
    merged = merged[col_order].sort_values("raw_id").reset_index(drop=True)

    try:
        employees = roster.employees_list()
    except FileNotFoundError as e:
        warnings.append(str(e))
        employees = []
    town_targets = registry.load_town_targets()

    return FleetSnapshot(
        vehicles=merged,
        employees=employees,
        town_targets=town_targets,
        vtms_file=vtms_file,
        status_file=status_file,
        warnings=warnings,
    )


def employee_vehicle_counts(vehicles: pd.DataFrame, employees: list) -> pd.DataFrame:
    """One row per employee: how many currently-live vehicles fall inside
    their resolved UCs, split by moving/still."""
    live = vehicles[vehicles["is_live"] & vehicles["uc"].notna()]
    rows = []
    for e in employees:
        uc_set = set(e["resolved_ucs"])
        if not uc_set:
            rows.append({
                "employee_id": e["id"], "name": e["name"], "role": e["role"],
                "shift": e["shift"], "uc_count": 0,
                "vehicle_count": 0, "moving": 0, "still": 0,
            })
            continue
        sub = live[live["uc"].isin(uc_set)]
        rows.append({
            "employee_id": e["id"], "name": e["name"], "role": e["role"],
            "shift": e["shift"], "uc_count": len(uc_set),
            "vehicle_count": len(sub),
            "moving": int((sub["status"] == "moving").sum()),
            "still": int((sub["status"] == "still").sum()),
        })
    return pd.DataFrame(rows)
