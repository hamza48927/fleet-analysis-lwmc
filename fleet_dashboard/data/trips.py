"""
Loads the "Rickshaw Trips" workbook(s) (New folder/*.xlsx) used to score
TM/FM performance: one row per vehicle per day, with its Zone, UC and trip
count for that day (or a Remarks note like Stopped/NR/Tracker Issue when it
didn't move).

Handles two workbook layouts, auto-detected per file:

  - "Per-day-per-circle" (the original layout): one file per circle per
    date, sheet "Combine Circle ", the date given once in a title cell
    ("...Report DD-MM-YYYY...") and the circle inferred from the filename.
  - "Combined sheet" (e.g. "LRs Combine Sheet 1st Aug till 28 Aug-2026.xlsx"):
    one file covering many dates and every town/circle at once, single
    sheet, with the date given per ROW instead of once per file. Its header
    row mislabels that date column "Sr. No" (a leftover from whatever
    column used to be there), so the date column is detected by its cell
    type (datetime) rather than trusted from the header text. There is no
    circle information in this layout -- rows from it get circle=None,
    which only means they're excluded when a specific circle is picked in
    the Reports tab (they still count under "All circles").

Both layouts resolve to the same row shape: date, circle, town, zone, uc,
vehicle, trips.
"""
from __future__ import annotations

import datetime as dt
import math
import re
from pathlib import Path

import openpyxl
import pandas as pd

from .. import config


def normalize_col(name):
    return re.sub(r"[^a-z0-9]", "", str(name).lower())


def extract_date_from_title(ws):
    """A single date for the whole file, from a title cell like '...Report
    27-08-2026...' (rows 1-3). None if no such title is present -- e.g. the
    combined-sheet layout, which instead carries a date per row."""
    for row in ws.iter_rows(min_row=1, max_row=3, values_only=True):
        for c in row:
            if isinstance(c, str) and "Report" in c:
                m = re.search(r"(\d{2})-(\d{2})-(\d{4})", c)
                if m:
                    d, mo, y = m.groups()
                    return f"{y}-{mo}-{d}"
    return None


def _infer_circle(filename: str) -> str | None:
    """Circle from the filename, if it says so -- only the per-day-per-
    circle layout does. None (unknown/combined) otherwise, rather than
    guessing, since a wrong circle label would silently corrupt the
    Reports tab's circle filter."""
    low = filename.lower()
    if "circle-ii" in low or "circle ii" in low:
        return "Circle-II"
    if "circle 1" in low or "circle-1" in low or "circle i" in low:
        return "Circle 1"
    return None


def _find_sheet(wb):
    for name in wb.sheetnames:
        if "combine circle" in name.lower():
            return wb[name]
    return wb[wb.sheetnames[0]]


def _find_header_row(rows):
    for i, row in enumerate(rows[:6]):
        if any(cell and normalize_col(cell) in ("srno", "sno") for cell in row):
            return i
    return None


def _find_date_column(rows, header_i, sample=20):
    """The combined-sheet layout's date column is mislabeled in the header,
    so it's identified by content instead: the first column whose sampled
    data cells are all datetime values."""
    data_rows = rows[header_i + 1: header_i + 1 + sample]
    if not data_rows:
        return None
    ncols = len(data_rows[0])
    for col in range(ncols):
        vals = [r[col] for r in data_rows if col < len(r) and r[col] is not None]
        if vals and all(isinstance(v, dt.datetime) for v in vals):
            return col
    return None


def load_trip_file(path: Path):
    wb = openpyxl.load_workbook(path, data_only=True)
    ws = _find_sheet(wb)
    file_date = extract_date_from_title(ws)
    circle = _infer_circle(path.name)
    rows = list(ws.iter_rows(values_only=True))

    header_i = _find_header_row(rows)
    if header_i is None:
        raise RuntimeError(f"header row not found in {path.name}")
    header = rows[header_i]
    date_col = _find_date_column(rows, header_i)

    colmap = {}
    for i, h in enumerate(header):
        if not h:
            continue
        n = normalize_col(h)
        if n in ("uc", "ucarea"):
            colmap["uc"] = i
        elif n == "zone":
            colmap["zone"] = i
        elif n == "town":
            colmap["town"] = i
        elif n == "rickshaw":
            colmap["vehicle"] = i
        elif "uc" in n and "trip" in n:
            colmap["trips"] = i
        elif n == "remarks":
            colmap["remarks"] = i

    out = []
    for row in rows[header_i + 1:]:
        veh = row[colmap["vehicle"]] if "vehicle" in colmap else None
        if not veh:
            continue
        zone_raw = row[colmap["zone"]] if "zone" in colmap else None
        uc_raw = row[colmap["uc"]] if "uc" in colmap else None
        trips_raw = row[colmap["trips"]] if "trips" in colmap else None

        zone = None
        if zone_raw not in (None, ""):
            try:
                zone = int(zone_raw)
            except (TypeError, ValueError):
                zm = re.search(r"\d+", str(zone_raw))
                zone = int(zm.group()) if zm else None

        uc = None
        if uc_raw not in (None, ""):
            um = re.search(r"\d+", str(uc_raw))
            uc = int(um.group()) if um else None

        trips = None
        if isinstance(trips_raw, (int, float)) and not (isinstance(trips_raw, float) and math.isnan(trips_raw)):
            trips = int(trips_raw)

        row_date = file_date
        if date_col is not None and date_col < len(row) and isinstance(row[date_col], dt.datetime):
            row_date = row[date_col].strftime("%Y-%m-%d")

        out.append({
            "date": row_date, "circle": circle,
            "town": row[colmap["town"]] if "town" in colmap else None,
            "zone": zone, "uc": uc, "vehicle": veh, "trips": trips,
        })
    return out


def load_all_trips(files: list[Path] | None = None) -> pd.DataFrame:
    """All rows from every available trip-report workbook, newest files
    last. Columns: date, circle, town, zone, uc, vehicle, trips."""
    files = files if files is not None else config.trip_report_files()
    all_rows = []
    for f in sorted(files):
        all_rows.extend(load_trip_file(f))
    return pd.DataFrame(all_rows, columns=["date", "circle", "town", "zone", "uc", "vehicle", "trips"])


def available_dates(df: pd.DataFrame | None = None) -> list[str]:
    df = df if df is not None else load_all_trips()
    if df.empty:
        return []
    return sorted(d for d in df["date"].dropna().unique())


def available_circles(df: pd.DataFrame | None = None) -> list[str]:
    df = df if df is not None else load_all_trips()
    if df.empty:
        return []
    return sorted(df["circle"].dropna().unique())
