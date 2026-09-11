"""
Employee roster (TM / FM / ZO / AM Yard / MVI) loaded from the roster
workbook ("employee data sheet.xlsx", auto-detected by config.py).

Adds the UC/zone -> employees lookups the dashboard needs to answer
"how many vehicles are working in this employee's area".
"""
from __future__ import annotations

from collections import defaultdict
from functools import lru_cache

from .. import config
from . import core, geo


@lru_cache(maxsize=1)
def load_roster():
    """(employees, roster_ucs, stats, all_lahore_ucs) -- see
    core.load_employee_roster for the shape of each."""
    path = config.latest_employee_roster()
    if path is None:
        raise FileNotFoundError(
            "No employee roster workbook found (looked for employee*sheet*.xlsx "
            "/ employee*data*.xlsx at the project root)."
        )
    return core.load_employee_roster(str(path), geo.load_ucs())


def employees_list() -> list[dict]:
    employees, *_ = load_roster()
    return employees


def uc_to_employees() -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = defaultdict(list)
    for e in employees_list():
        for uc in e["resolved_ucs"]:
            out[uc].append(e)
    return dict(out)


def zone_to_employees() -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = defaultdict(list)
    for e in employees_list():
        for z in e["resolved_zones"]:
            out[z].append(e)
    return dict(out)
