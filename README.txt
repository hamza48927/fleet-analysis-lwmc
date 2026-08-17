LWMC FLEET DASHBOARD — LOCAL KIT
================================
Scope: Lahore city only. build_master.py drops Sheikhupura/Kasur/Nankana Sahib
rows at build time -- the UC/zone geometry, employee roster, and fleet
targets are all Lahore-specific, so those districts have nothing to attach
to here.
Sources used: VTMS active logs + LWMC vehicle-status file. VTCS is NOT used.

FILES
-----
LWMC_Fleet_Dashboard.html   The dashboard. Double-click to open in any browser.
                            Data is baked in, so it works offline for the data/table/KPIs.
                            (Map background tiles need internet; without it the map is
                            blank but everything else still works.)
dashboard_template.html     Dashboard source (has "/*DATA*/" where the JSON gets spliced
                            in). Edit this, not LWMC_Fleet_Dashboard.html directly.
master_2026-08-11.csv       The clean per-vehicle table (open in Excel).
lahore_ucs.geojson          The 285 Lahore UC polygons (from your KML).
employee sheet caping.xlsx  TM/FM/Zonal-Officer/AM-Yard/MVI roster (who is responsible
                            for which zones) — read automatically by build_master.py,
                            see "Roster-scoped mode" below. Sheets: Town Managers, Fleet
                            Managers, Zonal Officers, AM Yards, MVI (plus a Summary sheet).
                            Shift (1st/2nd/Night) is a per-row column here, not a separate
                            sheet, so a person working two shifts appears as two rows.
                            Supersedes the earlier "employee data.xlsx" -- that file had
                            no Zonal Officer/MVI roles and needed regex parsing of free-text
                            zone cells; this one already resolves Zone Numbers/UC Numbers
                            to clean lists per row.
Lahore Fleet+LRs.xlsx       The LWMC fleet ESTABLISHMENT REGISTRY — one row per registered
                            vehicle (Vehicle ID, Category, Town). This is the authoritative
                            source for fleet targets. NOT part of the daily build — only
                            re-run extract_town_targets.py against it if you get an updated
                            copy. (An earlier version of this dashboard used "vehicle
                            data.xlsx", an hourly control-room log, for targets instead —
                            those numbers turned out to be wrong; this registry replaced it.)
Reference Documents/        Extracted, cleaned reference data the dashboard reads.
  town_targets.json           Per-town target fleet size (LR + full fleet) AND a
                              vehicle_id -> {category, town} lookup, both produced by
                              extract_town_targets.py from Lahore Fleet+LRs.xlsx.
extract_town_targets.py     One-off extractor: Lahore Fleet+LRs.xlsx -> Reference
                            Documents/town_targets.json. Re-run only when that file changes.
build_master.py             Regenerates the data from raw exports — run this each day.

DAILY UPDATE (time-series)
--------------------------
1. Download the new VTMS csv + LWMC .xls into this folder.
2. If the LWMC file is .xls, convert to .xlsx (Excel: Save As .xlsx) and name it vs.xlsx.
3. Edit the top of build_master.py: set VTMS_CSV and SNAPSHOT_DATE to the new file/date.
4. Run:  python3 build_master.py
   -> writes master_<date>.csv + dashboard_data.json
   -> also reads "employee sheet caping.xlsx" automatically and prints a roster
      coverage report (resolved/unresolved staff, % of Lahore UCs covered). If that
      file is missing or its layout changes, the build still completes -- roster-scoped
      mode just has no data until it's fixed.
   -> also reads Reference Documents/town_targets.json automatically and prints a
      target-vs-deployed report per town, plus how many vehicles are currently
      inside vs. outside their own assigned (home) town. Missing/stale reference
      data degrades the same way -- the build still completes.
5. Re-embed into the dashboard (one line):
   python3 -c "t=open('dashboard_template.html').read();d=open('dashboard_data.json').read();open('LWMC_Fleet_Dashboard.html','w').write(t.replace('/*DATA*/',d))"
   (keep dashboard_template.html in the folder for this step)

Keep each day's master_<date>.csv — stacking them is your time-series history.

ROSTER-SCOPED MODE
-------------------
The top bar has a "Full fleet" / "Roster-scoped" toggle. Roster-scoped mode
restricts every view (map, KPIs, charts, table, written report, Excel export)
to Lahore vehicles inside a UC that someone in "employee sheet caping.xlsx"
actually covers, and the "Employee" dropdown (left sidebar) -- always visible,
grouped by role (Tehsil Manager / Fleet Manager / Zonal Officer / AM Yard /
MVI) and showing each person's shift -- drills into one person's zone(s)
specifically. A person can cover multiple zones/UCs, and it's normal for a
TM/FM/ZO/AM Yard person to share the same UC (org hierarchy, not competing
ownership); it's also normal for the same name to appear twice if they work
two shifts. Unresolved staff (a Town/Area cell build_master.py couldn't map
to a zone/UC/town -- e.g. a route or circle with no UC polygon) still show up
in the dropdown, labeled "unresolved area", so gaps are visible rather than
hidden -- check the build's printed roster report to fix those in the source
spreadsheet.

TOWN TARGETS & ASSIGNED-AREA STATUS
-------------------------------------
Every town gets TWO target figures, both from the fleet establishment
registry (Reference Documents/town_targets.json, extracted from Lahore
Fleet+LRs.xlsx): a Loader Rickshaw target and a full-fleet (every category)
target. Both are compared against live-deployed counts for that town.

The key to why this is accurate: build_master.py joins each LIVE vehicle to
its registered category/town by matching Vehicle ID against the registry
(~96% match rate) and stores that as registry_category/registry_town/
assigned_town per vehicle. This is used instead of VTMS's own vehicle_type
field, which is blank on most live rows -- text-matching against it would
badly undercount. (An earlier attempt compared registry-style targets
against the WHOLE fleet with no category filter and got a nonsensical
180-450%; that's what tipped us off vehicle_type wasn't trustworthy enough
to filter by directly.)

Each Lahore vehicle also gets an "in assigned area" flag: does its live GPS
position currently fall inside assigned_town (registry town if matched,
else a coarser tehsil-code-derived town as fallback)? This is a snapshot
status (in/out right now), not a tracked duration -- knowing how LONG a
vehicle spends in vs. outside its area needs multiple dated snapshots
compared over time, which is exactly what stacking master_<date>.csv day
over day (see above) is for. Once a few days of history exist, entry/exit
dwell-time tracking can be built on top of this same in_assigned_area field.

REQUIREMENTS
------------
Python 3 with pandas + openpyxl + xlrd  (pip install pandas openpyxl xlrd)
No other dependencies — point-in-polygon UC tagging and the Excel exporter
are both built in (no charting/xlsx libraries needed).
