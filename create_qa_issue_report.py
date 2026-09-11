from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.formatting.rule import FormulaRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.worksheet.table import Table, TableStyleInfo


ROOT = Path(__file__).parent
OUT = ROOT / "reports" / "LWMC_Fleet_Dashboard_QA_Issue_Report.xlsx"

NAVY = "0D1F2D"
INK = "1B2B34"
MUTED = "5C6F78"
GREEN = "158B5D"
GREEN_DARK = "0C5D43"
MINT = "E1F3EB"
AMBER = "E2972F"
RED = "B93A39"
LINE = "DAE4E0"
WHITE = "FFFFFF"


def style_title(ws, title, subtitle, end_col):
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=end_col)
    cell = ws.cell(1, 1, title)
    cell.font = Font(name="Aptos Display", size=22, bold=True, color=WHITE)
    cell.fill = PatternFill("solid", fgColor=NAVY)
    cell.alignment = Alignment(vertical="center")
    ws.row_dimensions[1].height = 38
    ws.merge_cells(start_row=2, start_column=1, end_row=2, end_column=end_col)
    cell = ws.cell(2, 1, subtitle)
    cell.font = Font(name="Aptos", size=10, italic=True, color=MUTED)
    cell.alignment = Alignment(wrap_text=True, vertical="center")
    ws.row_dimensions[2].height = 28


def style_header(row):
    for cell in row:
        cell.font = Font(name="Aptos", size=10, bold=True, color=WHITE)
        cell.fill = PatternFill("solid", fgColor=GREEN_DARK)
        cell.alignment = Alignment(wrap_text=True, vertical="center")
        cell.border = Border(bottom=Side(style="thin", color=LINE))


def apply_body(ws, min_row, max_row, max_col):
    for row in ws.iter_rows(min_row=min_row, max_row=max_row, min_col=1, max_col=max_col):
        for cell in row:
            cell.font = Font(name="Aptos", size=10, color=INK)
            cell.alignment = Alignment(wrap_text=True, vertical="top")
            cell.border = Border(bottom=Side(style="hair", color=LINE))


def add_dropdown(ws, cell_range, formula):
    validation = DataValidation(type="list", formula1=formula, allow_blank=True)
    validation.error = "Choose a value from the list."
    validation.errorTitle = "Invalid value"
    validation.prompt = "Select a value from the dropdown."
    validation.promptTitle = "QA field"
    ws.add_data_validation(validation)
    validation.add(cell_range)


def build():
    OUT.parent.mkdir(exist_ok=True)
    wb = Workbook()
    issue = wb.active
    issue.title = "Issue Log"
    checklist = wb.create_sheet("QA Checklist")
    guide = wb.create_sheet("How To Report")
    lists = wb.create_sheet("Lists")

    issue_headers = [
        "Issue ID", "Date Reported", "Reporter", "Department / Circle", "Application Version",
        "Workflow / Tab", "Severity", "Short Title", "Steps to Reproduce", "Expected Result",
        "Actual Result", "Snapshot Date", "Source File(s)", "Vehicle ID / Employee / Report",
        "Screenshot / Evidence Path", "Status", "Assigned To", "Resolution / Notes", "Date Closed",
    ]
    style_title(issue, "LWMC Fleet Dashboard - QA Issue Report", "Use one row per issue. Complete the evidence fields so the technical team can reproduce the problem.", len(issue_headers))
    for col, header in enumerate(issue_headers, 1):
        issue.cell(4, col, header)
    style_header(issue[4])
    issue.row_dimensions[4].height = 34
    for row_num in range(5, 55):
        issue.cell(row_num, 1, f"QA-{row_num - 4:03d}")
    apply_body(issue, 5, 54, len(issue_headers))
    issue.freeze_panes = "A5"
    issue.auto_filter.ref = f"A4:S54"
    widths = [12, 14, 18, 22, 18, 20, 12, 28, 40, 34, 40, 15, 32, 30, 34, 15, 20, 40, 14]
    for i, width in enumerate(widths, 1):
        issue.column_dimensions[chr(64 + i) if i <= 26 else "A"].width = width
    issue.sheet_view.showGridLines = False
    issue.conditional_formatting.add("G5:G54", FormulaRule(formula=['G5="Critical"'], fill=PatternFill("solid", fgColor="F4CCCC")))
    issue.conditional_formatting.add("G5:G54", FormulaRule(formula=['G5="High"'], fill=PatternFill("solid", fgColor="FCE5CD")))
    issue.conditional_formatting.add("P5:P54", FormulaRule(formula=['P5="Closed"'], fill=PatternFill("solid", fgColor=MINT)))

    add_dropdown(issue, "F5:F54", "='Lists'!$A$2:$A$6")
    add_dropdown(issue, "G5:G54", "='Lists'!$B$2:$B$5")
    add_dropdown(issue, "P5:P54", "='Lists'!$C$2:$C$6")

    checklist_headers = ["QA ID", "Area", "Test / User Action", "Expected Result", "Pass / Fail", "Evidence / Notes"]
    style_title(checklist, "QA Checklist", "Run this checklist after a new build or source-data change. Mark Fail in the issue log with steps and evidence.", len(checklist_headers))
    for col, header in enumerate(checklist_headers, 1):
        checklist.cell(4, col, header)
    style_header(checklist[4])
    rows = [
        ("QA-001", "Launch", "Open the application with executable and _internal folder together.", "Application opens without a startup error.", "", ""),
        ("QA-002", "Sources", "Confirm VTMS, Vehicle Status and other source labels.", "Correct filename or auto-detected status is shown.", "", ""),
        ("QA-003", "Sources", "Import one source file and wait for reload.", "The source label updates and data reloads.", "", ""),
        ("QA-004", "Map & Analytics", "Check snapshot date, KPIs and vehicle table.", "Date and counts match the selected snapshot.", "", ""),
        ("QA-005", "Map & Analytics", "Switch Full fleet / Roster-scoped and compare totals.", "Roster-scoped view limits vehicles to covered UCs.", "", ""),
        ("QA-006", "Fleet Table", "Filter by status, type, town, zone and UC.", "Rows satisfy all selected filters.", "", ""),
        ("QA-007", "Fleet Table", "Filter by Employee.", "Only vehicles in the employee's resolved UCs are shown.", "", ""),
        ("QA-008", "Fleet Table", "Click Reset filters.", "All filters return to their default values.", "", ""),
        ("QA-009", "Reports", "Generate Fleet Registry report.", "Workbook is created in reports with registry and live data.", "", ""),
        ("QA-010", "Reports", "Generate TM/FM report with a selected date or circle.", "Workbook contains only the requested scope.", "", ""),
        ("QA-011", "Reports", "Generate Combined report.", "Workbook contains overview, registry, TM and FM sheets.", "", ""),
        ("QA-012", "Recovery", "Open the reports folder and reopen generated workbook.", "Workbook opens and is readable in Excel.", "", ""),
    ]
    for r, row in enumerate(rows, 5):
        for c, value in enumerate(row, 1):
            checklist.cell(r, c, value)
    style_header(checklist[4])
    apply_body(checklist, 5, 4 + len(rows), len(checklist_headers))
    add_dropdown(checklist, f"E5:E{4 + len(rows)}", "='Lists'!$D$2:$D$4")
    checklist.freeze_panes = "A5"
    checklist.auto_filter.ref = f"A4:F{4 + len(rows)}"
    for col, width in zip("ABCDEF", [12, 20, 44, 50, 14, 42]):
        checklist.column_dimensions[col].width = width
    checklist.sheet_view.showGridLines = False

    style_title(guide, "How To Report A QA Issue", "Complete the Issue Log row and attach evidence before sending the workbook to the support or development team.", 3)
    guide_headers = [("Step", "What to record", "Example")]
    for col, value in enumerate(guide_headers[0], 1):
        guide.cell(4, col, value)
    style_header(guide[4])
    guide_rows = [
        ("1", "Short Title", "Fleet Table shows vehicles from the wrong town"),
        ("2", "Workflow / Tab", "Fleet Table"),
        ("3", "Severity", "High if the result could cause an operational decision error"),
        ("4", "Steps to Reproduce", "Open app > Fleet Table > Town = DGBT > observe rows"),
        ("5", "Expected vs Actual", "Expected only DGBT; actual includes Nishtar Town"),
        ("6", "Snapshot and Sources", "Snapshot date plus filenames shown in the source strip"),
        ("7", "Evidence", "Screenshot path, vehicle ID, report name or exported workbook"),
        ("8", "Status", "New until assigned; Closed only after retest passes"),
    ]
    for r, row in enumerate(guide_rows, 5):
        for c, value in enumerate(row, 1):
            guide.cell(r, c, value)
    apply_body(guide, 5, 4 + len(guide_rows), 3)
    for col, width in zip("ABC", [12, 28, 80]):
        guide.column_dimensions[col].width = width
    guide.sheet_view.showGridLines = False
    guide.freeze_panes = "A5"
    guide.merge_cells("A15:C15")
    guide["A15"] = "Severity guide: Critical = unusable or data-loss risk; High = materially wrong operational result; Medium = incorrect feature with workaround; Low = cosmetic or wording issue."
    guide["A15"].fill = PatternFill("solid", fgColor="FFF4DF")
    guide["A15"].font = Font(name="Aptos", size=10, bold=True, color=AMBER)
    guide["A15"].alignment = Alignment(wrap_text=True, vertical="center")
    guide.row_dimensions[15].height = 38

    lists.append(["Workflow / Tab", "Severity", "Status", "Pass / Fail"])
    for row in [
        ("Map & Analytics", "Critical", "New", "Pass"),
        ("Fleet Table", "High", "Assigned", "Fail"),
        ("Reports", "Medium", "In Progress", "Blocked"),
        ("Data Sources", "Low", "Retest", ""),
        ("Launch / Recovery", "", "Closed", ""),
    ]:
        lists.append(list(row))
    lists.sheet_state = "hidden"

    # Give end users a blank reporting line without removing the useful QA IDs.
    issue["H5"] = "Example: Town filter returns rows from another town"
    issue["F5"] = "Fleet Table"
    issue["G5"] = "High"
    issue["P5"] = "New"
    issue["I5"] = "1. Open app 2. Open Fleet Table 3. Select Town 4. Check returned rows"
    issue["J5"] = "Only vehicles assigned to the selected town are shown."
    issue["K5"] = "Rows from a different town are shown."
    issue["R5"] = "Delete or replace this example before submitting the workbook."
    for cell in issue[5]:
        cell.fill = PatternFill("solid", fgColor="FFF8E8")

    wb.properties.title = "LWMC Fleet Dashboard QA Issue Report"
    wb.properties.subject = "User QA issue reporting template"
    wb.properties.creator = "LWMC Fleet Dashboard"
    wb.save(OUT)

    # Reopen as a basic integrity check.
    check = load_workbook(OUT)
    assert check.sheetnames == ["Issue Log", "QA Checklist", "How To Report", "Lists"]
    assert check["Issue Log"]["H5"].value.startswith("Example:")
    assert check["QA Checklist"]["A5"].value == "QA-001"
    check.close()
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    build()