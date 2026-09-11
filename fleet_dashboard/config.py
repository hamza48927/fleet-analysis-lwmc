"""
Paths and constants for the LWMC Fleet Dashboard.

Every input file is auto-detected by filename pattern + most-recent
modification time rather than hardcoded, so the app does not need a manual
edit whenever a new day's export (or a renamed roster workbook) shows up.
"""
from __future__ import annotations

import datetime as dt
import glob
import json
import os
import re
import sys
from pathlib import Path

if getattr(sys, "frozen", False):
    # Packaged (PyInstaller) build: __file__ resolves inside the bundled
    # _internal folder, not the folder the user drops daily exports into.
    # The exe is meant to sit next to that data (see build docs), so anchor
    # on its own location instead.
    PROJECT_ROOT = Path(sys.executable).resolve().parent
else:
    PROJECT_ROOT = Path(__file__).resolve().parent.parent

UC_GEOJSON = PROJECT_ROOT / "lahore_ucs.geojson"
TOWN_TARGETS_JSON = PROJECT_ROOT / "Reference Documents" / "town_targets.json"
FLEET_REGISTRY_XLSX = PROJECT_ROOT / "Lahore Fleet+LRs.xlsx"
DASHBOARD_TEMPLATE_HTML = PROJECT_ROOT / "dashboard_template.html"

REPORTS_DIR = PROJECT_ROOT / "reports"
TRIP_REPORTS_DIR = PROJECT_ROOT / "New folder"

# Static reference assets the app ships with (not daily data -- those still
# have to be dropped next to the exe or picked via Import). Bundled into the
# frozen build so a fresh copy of the exe + _internal folder works in any
# folder without the user having to also carry these specific files around;
# seeded onto disk once, on first run, so every existing PROJECT_ROOT-relative
# path above keeps working unchanged.
if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
    import shutil

    _BUNDLE_ROOT = Path(sys._MEIPASS)
    for _target in (UC_GEOJSON, FLEET_REGISTRY_XLSX, DASHBOARD_TEMPLATE_HTML, TOWN_TARGETS_JSON):
        if _target.exists():
            continue
        _bundled = _BUNDLE_ROOT / _target.relative_to(PROJECT_ROOT)
        if _bundled.exists():
            _target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(_bundled, _target)

# User-picked file overrides (via the "Import ..." buttons in the app),
# remembered across restarts so a source only needs to be picked once --
# not gitignored per se but at a dotfile name that won't get committed by
# accident, and *.json under the project root is the app's own state, not
# input data. See set_source_override / get_source_override below.
SETTINGS_PATH = PROJECT_ROOT / ".fleet_dashboard_sources.json"

# key -> whether it holds a list of paths (multi-file) or a single path
SOURCE_KEYS = {
    "vtms_csv": False,
    "vehicle_status": False,
    "employee_roster": False,
    "fleet_registry": False,
    "vehicle_history": False,
    "trip_files": True,
}


def _load_overrides() -> dict:
    if not SETTINGS_PATH.exists():
        return {}
    try:
        return json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_overrides(data: dict) -> None:
    SETTINGS_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")


def set_source_override(key: str, path) -> None:
    """Remembers a single-file override (VTMS export, roster, etc.), picked
    by the user via an Import button instead of relying on auto-detection."""
    data = _load_overrides()
    data[key] = str(path)
    _save_overrides(data)


def set_sources_override(key: str, paths: list) -> None:
    """Remembers a multi-file override (trip reports)."""
    data = _load_overrides()
    data[key] = [str(p) for p in paths]
    _save_overrides(data)


def clear_source_override(key: str) -> None:
    data = _load_overrides()
    if data.pop(key, None) is not None:
        _save_overrides(data)


def get_source_override(key: str):
    """Path (or list[Path] for multi-file keys) the user explicitly picked
    for `key`, if any -- filtered to files that still exist on disk (a
    picked file that's since been moved/deleted is treated as no override,
    falling back to auto-detection, rather than silently erroring)."""
    val = _load_overrides().get(key)
    if val is None:
        return None
    if isinstance(val, list):
        paths = [Path(p) for p in val if Path(p).exists()]
        return paths or None
    p = Path(val)
    return p if p.exists() else None

ROLE_LABEL = {
    "TM": "Town Manager",
    "FM": "Fleet Manager",
    "ZO": "Zonal Officer",
    "AM_YARD": "AM Yard",
    "MVI": "MVI",
}
ROLE_ORDER = ["TM", "FM", "ZO", "AM_YARD", "MVI"]

# role code -> the roster workbook sheet name that holds it, and the label
# used on performance reports for that role.
PERFORMANCE_ROLES = {
    "TM": {"sheet": "Town Managers", "label": "Town Manager"},
    "FM": {"sheet": "Fleet Managers", "label": "Fleet Manager"},
}


def _is_lock_file(path: str) -> bool:
    return Path(path).name.startswith("~$")


def _latest(pattern: str) -> Path | None:
    matches = [m for m in glob.glob(str(PROJECT_ROOT / pattern)) if not _is_lock_file(m)]
    if not matches:
        return None
    return Path(max(matches, key=os.path.getmtime))


def latest_vtms_csv() -> Path | None:
    override = get_source_override("vtms_csv")
    if override is not None:
        return override
    return _latest("export-vtms-active-logs-*.csv")


def latest_vehicle_status_file() -> Path | None:
    override = get_source_override("vehicle_status")
    if override is not None:
        return override
    # LWMC's vehicle-status export has appeared under both a plain "vs.xlsx"
    # name and a timestamped "Vehicle_Status_*.xls" name -- check both and
    # take whichever is newest.
    candidates = []
    for pattern in ("Vehicle_Status_*.xls*", "vs.xlsx"):
        candidates.extend(m for m in glob.glob(str(PROJECT_ROOT / pattern)) if not _is_lock_file(m))
    if not candidates:
        return None
    return Path(max(candidates, key=os.path.getmtime))


def latest_vehicle_history_csv() -> Path | None:
    """Per-vehicle GPS track export used for the map's route-tracking
    feature. Seen under two names -- the small single-day
    'vehicle_history_*.csv' and the large multi-day, per-second
    'activity_*.csv' (can be several GB) -- both handled by
    data/core.py's load_vehicle_tracks."""
    override = get_source_override("vehicle_history")
    if override is not None:
        return override
    candidates = []
    for pattern in ("vehicle_history_*.csv", "activity_*.csv"):
        candidates.extend(m for m in glob.glob(str(PROJECT_ROOT / pattern)) if not _is_lock_file(m))
    if not candidates:
        return None
    return Path(max(candidates, key=os.path.getmtime))


def latest_employee_roster() -> Path | None:
    override = get_source_override("employee_roster")
    if override is not None:
        return override
    # Filename has changed once already ("employee sheet caping.xlsx" ->
    # "employee data sheet.xlsx") -- match on prefix, not the exact name, so
    # the next rename does not silently break every report.
    candidates = []
    for pattern in ("employee*sheet*.xlsx", "employee*data*.xlsx"):
        candidates.extend(m for m in glob.glob(str(PROJECT_ROOT / pattern)) if not _is_lock_file(m))
    if not candidates:
        return None
    return Path(max(set(candidates), key=os.path.getmtime))


def fleet_registry_xlsx() -> Path:
    """The LWMC fleet establishment registry workbook (Lahore Fleet+LRs.xlsx
    by default) that extract_town_targets.py reads."""
    override = get_source_override("fleet_registry")
    return override if override is not None else FLEET_REGISTRY_XLSX


def trip_report_files() -> list[Path]:
    """Daily 'Rickshaw Trips' workbook(s) (per-vehicle, per-day trip counts
    by Zone/UC) used for TM/FM performance scoring. Looked for in New
    folder/ first (where they currently live) and, failing that, anywhere
    at the project root, so relocating that folder does not break reports."""
    override = get_source_override("trip_files")
    if override is not None:
        return override
    found = sorted(TRIP_REPORTS_DIR.glob("*.xlsx")) if TRIP_REPORTS_DIR.is_dir() else []
    found = [p for p in found if not _is_lock_file(str(p))]
    if found:
        return found
    return sorted(
        p for p in PROJECT_ROOT.glob("Rickshaws Trips Report*.xlsx")
        if not _is_lock_file(str(p))
    )


DATE_RE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")


def default_snapshot_date(vtms_path: Path | None) -> str:
    """YYYY-MM-DD guessed from a VTMS export filename
    (export-vtms-active-logs-DD-MM-YYYY-...), falling back to today."""
    if vtms_path is not None:
        m = re.search(r"(\d{2})-(\d{2})-(\d{4})", vtms_path.name)
        if m:
            d, mo, y = m.groups()
            return f"{y}-{mo}-{d}"
    return dt.date.today().isoformat()
