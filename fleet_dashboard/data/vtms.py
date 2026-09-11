"""
Loads today's live snapshot: the VTMS Active Logs export (position, status,
distance, working hours) enriched with the LWMC Vehicle-Status export
(battery voltage, reporting status), and resolves each vehicle's UC/zone/
town from its GPS position via point-in-polygon.

Reuses data/core.py's column-cleaning helpers and tehsil/town mappings so
the same vehicle ends up classified the same way here as in the pipeline
build (fleet_dashboard/pipeline/build_master.py) that feeds the HTML map.
"""
from __future__ import annotations

import pandas as pd

from .. import config
from . import core, geo


def _read_vehicle_status(path) -> pd.DataFrame:
    with open(path, "rb") as fh:
        is_legacy_xls = fh.read(8) == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
    engine = "xlrd" if is_legacy_xls else "openpyxl"
    st = pd.read_excel(path, header=3, engine=engine).dropna(how="all").copy()
    st["vkey"] = core.norm_key(st["Vehicle Reg No"])
    st["battery_volt"] = pd.to_numeric(st["Battery Status"], errors="coerce")
    st["tracker_offline"] = st["battery_volt"] < 2
    return (
        st[["vkey", "Reporting Status", "Status Text", "battery_volt", "tracker_offline"]]
        .drop_duplicates("vkey")
        .rename(columns={"Reporting Status": "reporting_status", "Status Text": "status_text"})
    )


def load_live_snapshot() -> tuple[pd.DataFrame, str | None, str | None]:
    """Returns (dataframe, vtms_file_name, status_file_name). The dataframe
    has one row per vehicle currently reporting into VTMS under the LWMC
    company code, scoped to Lahore, with UC/zone/town resolved from GPS."""
    vtms_path = config.latest_vtms_csv()
    if vtms_path is None:
        return pd.DataFrame(), None, None

    v = pd.read_csv(vtms_path)
    lw = v[v["Company"] == "LWMC"].copy()
    lw["distance_km"] = core.num(lw["Distance (Km)"])
    lw["working_min"] = core.num(lw["Working Hours (In Minutes)"])
    lw["lat"] = pd.to_numeric(lw["Latitude"], errors="coerce")
    lw["lon"] = pd.to_numeric(lw["Longitude"], errors="coerce")
    lw["code"] = lw["Tehsil"].str.replace("LWMC-", "", regex=False)
    lw["district"] = lw["code"].map(core.TEHSIL_TO_DISTRICT).fillna("Other")
    lw = lw[lw["district"] == "Lahore"].copy()
    lw["vkey"] = core.norm_key(lw["Vehicle"])

    tags = [
        geo.assign_uc(r.lon, r.lat) if pd.notna(r.lon) and pd.notna(r.lat) else (None, None, None)
        for r in lw.itertuples()
    ]
    lw["uc"], lw["uc_town"], lw["uc_zone"] = zip(*tags) if tags else ([], [], [])

    status_path = config.latest_vehicle_status_file()
    if status_path is not None:
        st_small = _read_vehicle_status(status_path)
        lw = lw.merge(st_small, on="vkey", how="left")
    else:
        for col in ("reporting_status", "status_text", "battery_volt", "tracker_offline"):
            lw[col] = None

    keep = {
        "vkey": "vkey", "Vehicle": "vehicle", "Vehicle ID": "vehicle_id",
        "Vehicle Type": "vehicle_type", "Vehicle Used For": "used_for",
        "Vehicle Status": "status", "Engine Status": "engine",
        "Office": "office", "Tehsil": "tehsil_code", "code": "tehsil_short",
        "distance_km": "distance_km", "working_min": "working_min",
        "lat": "lat", "lon": "lon", "uc": "uc", "uc_town": "uc_town", "uc_zone": "uc_zone",
        "Timestamp": "timestamp", "Last Received At": "last_received",
        "reporting_status": "reporting_status", "status_text": "status_text",
        "battery_volt": "battery_volt", "tracker_offline": "tracker_offline",
    }
    out = lw.rename(columns=keep)[list(keep.values())]
    return out, vtms_path.name, (status_path.name if status_path else None)
