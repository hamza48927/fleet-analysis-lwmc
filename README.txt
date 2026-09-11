
 LWMC FLEET DASHBOARD
================================
Scope: Lahore city only. The data pipeline drops Sheikhupura/Kasur/Nankana
Sahib rows at build time -- the UC/zone geometry, employee roster, and
fleet targets are all Lahore-specific, so those districts have nothing to
attach to here.
Sources used: VTMS active logs + LWMC vehicle-status file. VTCS is NOT used.

RUNNING THE APP
----------------
    venv/Scripts/python.exe main.py

One window, three tabs:
  Map & Analytics   The existing Leaflet map + KPI/analytics dashboard,
                     embedded (reads LWMC_Fleet_Dashboard.html / dashboard_data.json).
  Fleet Table        Native, filterable per-vehicle table -- every registered
                     vehicle (Lahore Fleet+LRs.xlsx) joined with today's live
                     VTMS snapshot. Filter by status/type/town/zone/UC/employee.
  Reports             Generate Fleet Registry, TM Performance, FM Performance,
                     or a Combined workbook, with date + circle filters for
                     the performance reports. Files are written to reports/.

APP STRUCTURE
--------------
fleet_dashboard/            The whole app -- one Python package.
  config.py                   Paths + auto-detection of the day's input files
                               (VTMS csv, vehicle-status export, roster
                               workbook, trip reports) by filename pattern +
                               most-recent modification time. No more manual
                               "edit the top of the script" every day.
  data/
    core.py                     Shared parsing: VTMS column cleaning, UC/zone
                                 point-in-polygon, employee roster resolution.
    geo.py                      Lahore UC/zone boundary loading (cached).
    registry.py                 Fleet establishment registry + town targets.
    roster.py                   Employee roster (TM/FM/ZO/AM Yard/MVI).
    vtms.py                     Today's live VTMS snapshot, UC/zone-resolved.
    trips.py                    Daily "Rickshaw Trips Report" workbooks
                                 (New folder/*.xlsx) used for TM/FM scoring.
    fleet_model.py               Joins registry + live VTMS into one table
                                 (FleetSnapshot) -- what both the Fleet Table
                                 tab and the reports are built from.
  pipeline/
    build_master.py             Daily batch build: writes master_<date>.csv,
                                 dashboard_data.json, and re-embeds
                                 LWMC_Fleet_Dashboard.html from
                                 dashboard_template.html. Run this once a day
                                 after dropping in new exports.
    extract_town_targets.py     One-off: Lahore Fleet+LRs.xlsx -> Reference
                                 Documents/town_targets.json. Re-run only when
                                 that registry workbook changes.
  reports/
    common.py                   Shared Excel-writing helpers (styled headers,
                                 autofit, freeze panes, auto-filter).
    fleet_registry_report.py    Fleet Registry workbook (registry+live table,
                                 town summary, employee coverage, exceptions).
    performance_report.py       TM/FM performance scoring, parameterized by
                                 role, with optional date/circle filters.
    combined_report.py          One workbook: overview + fleet registry +
                                 both TM and FM performance sheets.
  ui/
    main_window.py               Tab bar + background loading/report threads.
    map_tab.py                   Embeds LWMC_Fleet_Dashboard.html (QWebEngineView).
    filter_panel.py / vehicle_table_model.py    Fleet Table tab.
    reports_panel.py             Reports tab: type + date/circle filters.
  app.py                       QApplication bootstrap.
main.py                      Entry point (venv/Scripts/python.exe main.py).

FILES (data, not code)
------------------------
LWMC_Fleet_Dashboard.html   The standalone HTML dashboard (also embedded in
                            the Map & Analytics tab). Double-click to open in
                            any browser -- data is baked in, works offline
                            for the data/table/KPIs (map tiles need internet).
dashboard_template.html     Dashboard source (has "/*DATA*/" where the JSON
                            gets spliced in). Edit this, not the .html above --
                            pipeline/build_master.py re-embeds it for you.
master_<date>.csv           Daily clean per-vehicle table (open in Excel).
lahore_ucs.geojson          The Lahore UC polygons (from the source KML).
employee data sheet.xlsx    TM/FM/Zonal-Officer/AM-Yard/MVI roster (who is
                            responsible for which zones), auto-detected by
                            config.py. Sheets: Town Managers, Fleet Managers,
                            Zonal Officers, AM Yards, MVI (plus Summary).
                            Shift (1st/2nd/Night) is a per-row column, so a
                            person working two shifts appears as two rows.
Lahore Fleet+LRs.xlsx       The LWMC fleet ESTABLISHMENT REGISTRY -- one row
                            per registered vehicle (Vehicle ID, Category,
                            Town). Authoritative source for fleet targets.
                            NOT part of the daily build -- only re-run
                            extract_town_targets.py against it if updated.
New folder/                 Daily "Rickshaw Trips Report" workbooks (one per
                            circle per date) used for TM/FM performance
                            scoring -- see reports/performance_report.py.
Reference Documents/        Extracted, cleaned reference data.
  town_targets.json           Per-town target fleet size (LR + full fleet)
                               AND a vehicle_id -> {category, town} lookup,
                               both produced by extract_town_targets.py.
reports/                    Generated report workbooks land here (gitignored).

DAILY UPDATE (time-series)
--------------------------
1. Download the new VTMS csv + LWMC vehicle-status export into this folder
   (any filename matching export-vtms-active-logs-*.csv / Vehicle_Status_*.xls*
   / vs.xlsx -- config.py picks the most recently modified match, no rename
   needed).
2. Run:  venv/Scripts/python.exe -m fleet_dashboard.pipeline.build_master
   -> auto-detects the snapshot date from the VTMS filename
   -> writes master_<date>.csv + dashboard_data.json
   -> re-embeds LWMC_Fleet_Dashboard.html from dashboard_template.html
   -> also reads the roster workbook automatically and prints a roster
      coverage report (resolved/unresolved staff, % of Lahore UCs covered).
      If that file is missing or its layout changes, the build still
      completes -- roster-scoped mode just has no data until it's fixed.
   -> also reads Reference Documents/town_targets.json automatically and
      prints a target-vs-deployed report per town, plus how many vehicles
      are currently inside vs. outside their own assigned (home) town.
      Missing/stale reference data degrades the same way -- the build
      still completes.
3. Launch the app (venv/Scripts/python.exe main.py) -- the Map & Analytics
   tab reads the freshly written dashboard_data.json automatically.

Keep each day's master_<date>.csv -- stacking them is your time-series history.

REPORTS
-------
From the Reports tab (or scripted -- see below), four report types:
  Fleet Registry    Every vehicle (registry + live), town summary, employee
                    coverage, status exceptions. Always uses the live snapshot.
  TM Performance    Town Managers scored per day on deployment % and trip
                    counts within their assigned zones/UCs (out of 100:
                    20 deployment marks + 80 trip-weightage marks).
  FM Performance    Same scoring, for Fleet Managers.
  Combined          One workbook: org overview + full fleet registry + both
                    TM and FM performance sheets.
Check specific dates and/or a circle in the Reports tab to score only those --
leave nothing checked to include every available date from New folder/.

Scripted (no UI), e.g. for a scheduled task:
  venv/Scripts/python.exe -c "from fleet_dashboard.reports import performance_report as p; print(p.build('TM'))"
  venv/Scripts/python.exe -c "from fleet_dashboard.reports import combined_report as c; from fleet_dashboard.data.fleet_model import build_snapshot; print(c.build(build_snapshot()))"

ROSTER-SCOPED MODE (Map & Analytics tab)
------------------------------------------
The top bar has a "Full fleet" / "Roster-scoped" toggle. Roster-scoped mode
restricts every view (map, KPIs, charts, table, written report, Excel export)
to Lahore vehicles inside a UC that someone in the roster workbook actually
covers, and the "Employee" dropdown (left sidebar) -- always visible,
grouped by role (Tehsil Manager / Fleet Manager / Zonal Officer / AM Yard /
MVI) and showing each person's shift -- drills into one person's zone(s)
specifically. A person can cover multiple zones/UCs, and it's normal for a
TM/FM/ZO/AM Yard person to share the same UC (org hierarchy, not competing
ownership); it's also normal for the same name to appear twice if they work
two shifts. Unresolved staff (a Town/Area cell the pipeline couldn't map to
a zone/UC/town -- e.g. a route or circle with no UC polygon) still show up
in the dropdown, labeled "unresolved area", so gaps are visible rather than
hidden -- check the build's printed roster report to fix those in the source
spreadsheet.

ZONES
-----
Zone (e.g. "Zone-37") sits between UC and Town in granularity -- Lahore has
49 zones from lahore_ucs.geojson, each one a fixed group of UCs within a
single town. The "Zone" dropdown (left sidebar, next to UC) filters every
view the same way UC/Town do, and composes with them (AND, not OR). Each
roster employee's "resolved_zones" is derived from lahore_ucs.geojson's own
UC->zone mapping applied to their resolved UCs -- so it reflects ground
truth, not just whatever the roster sheet's free-text Zone Numbers column
said. Excel export and the written report both have a "By Zone" sheet/
section to match, and the Analytics tab has a "Top zones by distance" card.

WORKING HOURS DISTRIBUTION
---------------------------
The Analytics tab, Excel export ("Working Hours" sheet), and written report
all have a per-town table bucketing today's working time per vehicle into
Below 2h / 2-4h / 4-6h / 6-8h / Above 8h, plus "% below 4h" and "% below 6h"
columns. This is a distinct dimension from Town Targets (which compares
fleet counts against a target, not how long vehicles actually worked).

NAVIGATION
----------
The left sidebar's Overview/Analytics/Map/Reports/Fleet table links jump to
each section within the Map & Analytics tab.

TOWN TARGETS & ASSIGNED-AREA STATUS
-------------------------------------
Every town gets TWO target figures, both from the fleet establishment
registry (Reference Documents/town_targets.json, extracted from Lahore
Fleet+LRs.xlsx): a Loader Rickshaw target and a full-fleet (every category)
target. Both are compared against live-deployed counts for that town.

The key to why this is accurate: the pipeline joins each LIVE vehicle to its
registered category/town by matching Vehicle ID against the registry (~96%
match rate) and stores that as registry_category/registry_town/
assigned_town per vehicle. This is used instead of VTMS's own vehicle_type
field, which is blank on most live rows -- text-matching against it would
badly undercount.

Each Lahore vehicle also gets an "in assigned area" flag: does its live GPS
position currently fall inside assigned_town (registry town if matched,
else a coarser tehsil-code-derived town as fallback)? This is a snapshot
status (in/out right now), not a tracked duration -- knowing how LONG a
vehicle spends in vs. outside its area needs multiple dated snapshots
compared over time, which is exactly what stacking master_<date>.csv day
over day (see above) is for.

REQUIREMENTS
------------
Python 3 with pandas, numpy, openpyxl, xlrd, and PySide6 (incl. PySide6-Addons
for QtWebEngine, used by the Map & Analytics tab):
    pip install pandas numpy openpyxl xlrd PySide6 PySide6-Addons
No charting/xlsx dependency needed beyond openpyxl -- point-in-polygon UC
tagging and the Excel exporter are both built in.
