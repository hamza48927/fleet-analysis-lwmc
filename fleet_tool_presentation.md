# Fleet Tool — HOD Presentation

## The Problem
Right now, there's no single live view of where our vehicles are and whether each town/zone has the coverage it's supposed to.

## What This Tool Is
This is the **Fleet Tool**, currently a **working prototype** covering Lahore. It's built on the city's UC/zone map, the roster sheet (linking employees and vehicles to zones), and daily raw vehicle export data. It gives one live dashboard showing vehicle status, area coverage, and working-hour patterns — down to the zone level, not just citywide.

## Why This Matters for HODs
- **Live map, one screen.** See every vehicle's status (moving, idle, or stopped) across the city in real time, instead of piecing it together from raw exports.
- **Coverage at a glance.** Each town shows actual fleet count against its assigned target, so gaps in area coverage are visible immediately.
- **Working-hours visibility.** A per-town breakdown shows how much of the day vehicles were actually active — useful for spotting underused fleet without digging through logs.
- **One-click reporting.** Data exports straight to Excel (by town, by zone, by employee) — no manual spreadsheet building for reviews.

## Demo Flow (2 minutes)
- Open the dashboard and show the citywide overview.
- Drill down from Town → Zone → UC to show how coverage narrows.
- Show the live map with vehicle status colors.
- Show the working-hours table for one town.
- Export a report to Excel live.

## Questions HODs Might Ask
**Q: Is this live data or a test version?**
A: It's a prototype running on real vehicle and roster data — built to prove the concept before full rollout.

**Q: How often does it update?**
A: It's built from the latest daily export; live/real-time refresh is part of the rollout plan, not the prototype stage.

**Q: What happens after the prototype stage?**
A: Once validated, it becomes the shared base for the Compliance and Attendance tools we're also building.

## What's Next
This Fleet Tool is the foundation. The Compliance Tool (staffing vs. approved roster) and Attendance Tool will reuse the same zone map and roster data, so all three eventually give HODs one consistent view instead of three separate systems.
