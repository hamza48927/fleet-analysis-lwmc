LWMC FLEET DASHBOARD — LOCAL KIT
================================
Scope: Lahore + Sheikhupura + Kasur + Nankana Sahib (the LWMC company in VTMS).
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
employee data.xlsx          TM/FM/AM-Yard/Night-Shift roster (who is responsible for
                            which zones) — read automatically by build_master.py, see
                            "Roster-scoped mode" below. Sheets: TMs, FMs, AM Yards,
                            Night Shift.
build_master.py             Regenerates the data from raw exports — run this each day.

DAILY UPDATE (time-series)
--------------------------
1. Download the new VTMS csv + LWMC .xls into this folder.
2. If the LWMC file is .xls, convert to .xlsx (Excel: Save As .xlsx) and name it vs.xlsx.
3. Edit the top of build_master.py: set VTMS_CSV and SNAPSHOT_DATE to the new file/date.
4. Run:  python3 build_master.py
   -> writes master_<date>.csv + dashboard_data.json
   -> also reads "employee data.xlsx" automatically and prints a roster coverage
      report (resolved/unresolved staff, % of Lahore UCs covered). If that file is
      missing or its layout changes, the build still completes -- roster-scoped mode
      just has no data until it's fixed.
5. Re-embed into the dashboard (one line):
   python3 -c "t=open('dashboard_template.html').read();d=open('dashboard_data.json').read();open('LWMC_Fleet_Dashboard.html','w').write(t.replace('/*DATA*/',d))"
   (keep dashboard_template.html in the folder for this step)

Keep each day's master_<date>.csv — stacking them is your time-series history.

ROSTER-SCOPED MODE
-------------------
The top bar has a "Full fleet" / "Roster-scoped" toggle. Roster-scoped mode
restricts every view (map, KPIs, charts, table, written report, Excel export)
to Lahore vehicles inside a UC that someone in "employee data.xlsx" actually
covers, and adds an "Employee" dropdown (left sidebar) to drill into one
person's zone(s) specifically -- a person can cover multiple zones/UCs, and
it's normal for a TM/FM/AM Yard person to share the same UC (org hierarchy,
not competing ownership). Unresolved staff (an area cell build_master.py
couldn't map to a zone/UC/town) still show up in the dropdown, labeled
"unresolved area", so gaps are visible rather than hidden -- check the
build's printed roster report to fix those in the source spreadsheet.

REQUIREMENTS
------------
Python 3 with pandas + openpyxl + xlrd  (pip install pandas openpyxl xlrd)
No other dependencies — point-in-polygon UC tagging and the Excel exporter
are both built in (no charting/xlsx libraries needed).
