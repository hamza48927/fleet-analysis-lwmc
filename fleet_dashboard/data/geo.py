"""
Lahore UC/zone boundary loading and point-in-polygon resolution.
Thin wrapper around data/core.py's geometry helpers, cached for the life of
the process.
"""
from __future__ import annotations

from functools import lru_cache

from .. import config
from . import core


@lru_cache(maxsize=1)
def load_ucs():
    """List of UC dicts (uc, town, zone, ring, bbox) from the Lahore
    UC/zone GeoJSON."""
    return core.load_ucs(str(config.UC_GEOJSON))


def assign_uc(lon, lat):
    """(uc, town, zone) for a coordinate, or (None, None, None) if it falls
    outside every Lahore UC polygon."""
    return core.assign_uc(lon, lat, load_ucs())


def uc_to_zone_map() -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for u in load_ucs():
        out.setdefault(u["uc"], set()).add(u["zone"])
    return out


def all_towns() -> list[str]:
    return sorted({u["town"] for u in load_ucs()})


def all_zones() -> list[str]:
    return sorted({u["zone"] for u in load_ucs()}, key=core.zone_sort_key)


def all_ucs() -> list[str]:
    return sorted({u["uc"] for u in load_ucs()})
