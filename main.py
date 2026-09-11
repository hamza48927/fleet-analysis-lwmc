#!/usr/bin/env python3
"""
LWMC Fleet Dashboard -- single entry point.

One PySide6 app with three tabs: Map & Analytics (the Leaflet dashboard),
Fleet Table (native, filterable), and Reports (Fleet Registry / TM / FM /
Combined, with date + circle filters). See README.txt for the full layout
and the daily data-refresh steps.

Run with:  venv/Scripts/python.exe main.py
"""
from fleet_dashboard.app import main

if __name__ == "__main__":
    raise SystemExit(main())
