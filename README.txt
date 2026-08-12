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
master_2026-08-11.csv       The clean per-vehicle table (open in Excel).
lahore_ucs.geojson          The 285 Lahore UC polygons (from your KML).
build_master.py             Regenerates the data from raw exports — run this each day.

DAILY UPDATE (time-series)
--------------------------
1. Download the new VTMS csv + LWMC .xls into this folder.
2. If the LWMC file is .xls, convert to .xlsx (Excel: Save As .xlsx) and name it vs.xlsx.
3. Edit the top of build_master.py: set VTMS_CSV and SNAPSHOT_DATE to the new file/date.
4. Run:  python3 build_master.py
   -> writes master_<date>.csv + dashboard_data.json
5. Re-embed into the dashboard (one line):
   python3 -c "t=open('dashboard_template.html').read();d=open('dashboard_data.json').read();open('LWMC_Fleet_Dashboard.html','w').write(t.replace('/*DATA*/',d))"
   (keep dashboard_template.html in the folder for this step)

Keep each day's master_<date>.csv — stacking them is your time-series history.

REQUIREMENTS
------------
Python 3 with pandas + openpyxl  (pip install pandas openpyxl)
No other dependencies — point-in-polygon UC tagging is built in.
