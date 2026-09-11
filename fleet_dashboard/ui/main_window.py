"""
Top-level window: a tab bar with

    Map & Analytics  - the existing Leaflet/HTML dashboard, embedded
    Fleet Table      - native, filterable per-vehicle table (registry + live)
    Reports          - Fleet Registry / TM / FM / Combined report generator,
                       with date + circle filters for the performance reports

Fleet snapshot loading (VTMS + registry + roster) and every report build
run on a background QThread so several thousand rows of point-in-polygon
resolution, roster parsing and Excel writing never freeze the UI.
"""
from __future__ import annotations

import traceback
from dataclasses import dataclass

import pandas as pd
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QLabel, QMainWindow, QMessageBox, QSplitter, QStatusBar, QTableView,
    QTabWidget, QVBoxLayout, QWidget,
)

from ..data import geo, trips
from ..data.fleet_model import FleetSnapshot, build_snapshot
from ..pipeline import build_master, extract_town_targets
from ..reports import combined_report, fleet_registry_report, performance_report
from .data_sources_panel import DataSourcesBar
from .filter_panel import ALL, FilterPanel
from .map_tab import MapTab
from .reports_panel import ReportsPanel
from .vehicle_table_model import VehicleTableModel


@dataclass
class _AppData:
    snapshot: FleetSnapshot
    trip_dates: list
    trip_circles: list


class _LoadThread(QThread):
    done = Signal(object)
    failed = Signal(str)

    def run(self):
        try:
            # Regenerate the reference/derived data (Reference
            # Documents/town_targets.json, dashboard_data.json, the
            # standalone HTML dashboard) from whatever sources are
            # currently selected -- either auto-detected or picked via the
            # "Import ..." buttons -- so the Map & Analytics tab and every
            # report reflect the latest sources without a manual pipeline
            # run. Best-effort: a missing/incompatible source degrades
            # (warnings already handled inside these scripts) rather than
            # blocking the Fleet Table / Reports tabs, which build their
            # own snapshot directly and don't depend on these outputs.
            pipeline_warnings = []
            try:
                extract_town_targets.main()
            except (Exception, SystemExit) as e:
                pipeline_warnings.append(f"Town-target extraction failed: {e}")
            try:
                build_master.main()
            except (Exception, SystemExit) as e:
                pipeline_warnings.append(f"Master/dashboard build failed: {e}")

            snapshot = build_snapshot()
            snapshot.warnings = pipeline_warnings + snapshot.warnings
            try:
                trips_df = trips.load_all_trips()
                trip_dates = trips.available_dates(trips_df)
                trip_circles = trips.available_circles(trips_df)
            except Exception:
                trip_dates, trip_circles = [], []
            self.done.emit(_AppData(snapshot, trip_dates, trip_circles))
        except Exception:
            self.failed.emit(traceback.format_exc())


class _BuildReportThread(QThread):
    done = Signal(str)
    failed = Signal(str)

    def __init__(self, fn, parent=None):
        super().__init__(parent)
        self._fn = fn

    def run(self):
        try:
            path = self._fn()
            self.done.emit(path)
        except Exception:
            self.failed.emit(traceback.format_exc())


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("LWMC Fleet Dashboard")
        self.resize(1600, 980)

        self.app_data: _AppData | None = None

        self.data_sources_bar = DataSourcesBar()
        self.data_sources_bar.sources_changed.connect(self._on_sources_changed)

        self.tabs = QTabWidget()

        central = QWidget()
        central_layout = QVBoxLayout(central)
        central_layout.setContentsMargins(0, 0, 0, 0)
        central_layout.setSpacing(0)
        central_layout.addWidget(self.data_sources_bar)
        central_layout.addWidget(self.tabs)
        self.setCentralWidget(central)

        # -- Fleet Table tab --
        self.filter_panel = FilterPanel()
        self.filter_panel.filters_changed.connect(self._apply_filters)
        self.filter_panel.reset_clicked.connect(self._on_reset_filters)
        self.filter_panel.report_clicked.connect(self._on_generate_fleet_registry_report)

        self.table_view  =QTableView()
        self.table_model = VehicleTableModel()
        self.table_view.setModel(self.table_model)
        self.table_view.setAlternatingRowColors(True)
        self.table_view.setSortingEnabled(True)
        self.table_view.setSelectionBehavior(QTableView.SelectRows)
        self.table_view.horizontalHeader().setStretchLastSection(True)

        fleet_splitter = QSplitter()
        fleet_splitter.addWidget(self.filter_panel)
        fleet_splitter.addWidget(self.table_view)
        fleet_splitter.setStretchFactor(1, 1)

        fleet_tab = QWidget()
        fleet_layout = QVBoxLayout(fleet_tab)
        fleet_layout.setContentsMargins(0, 0, 0, 0)
        self.loading_label = QLabel("Loading fleet registry, VTMS snapshot and employee roster…")
        self.loading_label.setStyleSheet("padding:16px; font-size:13px; color:#557b70;")
        fleet_layout.addWidget(self.loading_label)
        fleet_layout.addWidget(fleet_splitter)
        fleet_splitter.hide()
        self._fleet_splitter = fleet_splitter

        # -- Reports tab --
        self.reports_panel = ReportsPanel()
        self.reports_panel.generate_clicked.connect(self._on_generate_report)
        reports_info = QLabel(
            "<h2>Fleet Reports</h2>"
            "<p>Choose a report type on the left:</p>"
            "<ul>"
            "<li><b>Fleet Registry Report</b> — every vehicle (registry + live), town summary, "
            "employee coverage and status exceptions. Always uses the current live snapshot.</li>"
            "<li><b>TM Performance Report</b> — Town Managers scored per day on vehicle "
            "deployment and trip counts within their assigned zones/UCs.</li>"
            "<li><b>FM Performance Report</b> — the same scoring, for Fleet Managers.</li>"
            "<li><b>Combined Report</b> — one workbook with an overview, the full fleet "
            "registry breakdown, and both TM and FM performance sheets together.</li>"
            "</ul>"
            "<p>For TM/FM/Combined, check specific dates and/or a circle to score only those — "
            "leave nothing checked to include every available date.</p>"
        )
        reports_info.setWordWrap(True)
        reports_info.setStyleSheet("padding:20px; font-size:13px; color:#33403c;")
        reports_info.setAlignment(Qt.AlignTop)

        reports_splitter = QSplitter()
        reports_splitter.addWidget(self.reports_panel)
        reports_splitter.addWidget(reports_info)
        reports_splitter.setStretchFactor(1, 1)

        # -- Map & Analytics tab (only needs dashboard_data.json, loads independently) --
        self.map_tab = MapTab()

        self.tabs.addTab(self.map_tab, "Map && Analytics")
        self.tabs.addTab(fleet_tab, "Fleet Table")
        self.tabs.addTab(reports_splitter, "Reports")

        self.setStatusBar(QStatusBar())

        self._start_load()

    # ---- loading ----
    def _start_load(self):
        self.loading_label.setText("Loading fleet registry, VTMS snapshot and employee roster…")
        self.loading_label.show()
        self._fleet_splitter.hide()
        self.data_sources_bar.setEnabled(False)
        self._load_thread = _LoadThread(self)
        self._load_thread.done.connect(self._on_loaded)
        self._load_thread.failed.connect(self._on_load_failed)
        self._load_thread.start()

    def _on_sources_changed(self, key: str):
        self.statusBar().showMessage(f"Data source changed ({key}) -- reloading…")
        self._start_load()

    def _on_load_failed(self, tb: str):
        self.data_sources_bar.setEnabled(True)
        self.loading_label.setText(f"Failed to load fleet data:\n{tb}")
        QMessageBox.critical(self, "Load failed", tb)

    def _on_loaded(self, app_data: _AppData):
        self.app_data = app_data
        snapshot = app_data.snapshot
        df = snapshot.vehicles

        categories = sorted(c for c in df["category"].dropna().unique())
        towns = geo.all_towns()
        zones = geo.all_zones()
        ucs = geo.all_ucs()
        self.filter_panel.populate_reference_data(categories, towns, zones, ucs, snapshot.employees)
        self.reports_panel.populate_reference_data(app_data.trip_dates, app_data.trip_circles)
        self.map_tab.reload()

        self.loading_label.hide()
        self._fleet_splitter.show()
        self.data_sources_bar.setEnabled(True)

        msg = f"VTMS: {snapshot.vtms_file or 'not found'}   |   Vehicle-Status: {snapshot.status_file or 'not found'}"
        if snapshot.warnings:
            msg += "   |   " + "; ".join(snapshot.warnings)
        self.statusBar().showMessage(msg)

        self._apply_filters()

    # ---- Fleet Table filtering ----
    def _apply_filters(self):
        if self.app_data is None:
            return
        df = self.app_data.snapshot.vehicles
        f = self.filter_panel.current_filters()

        mask = pd.Series(True, index=df.index)
        if f["status"] != ALL:
            mask &= df["status"] == f["status"]
        if f["category"] != ALL:
            mask &= df["category"] == f["category"]
        if f["town"] != ALL:
            mask &= df["town"] == f["town"]
        if f["zone"] != ALL:
            mask &= df["uc_zone"] == f["zone"]
        if f["uc"] != ALL:
            mask &= df["uc"] == f["uc"]

        employee_note = ""
        if f["employee_id"] != ALL:
            emp = next((e for e in self.app_data.snapshot.employees if e["id"] == f["employee_id"]), None)
            if emp is not None:
                uc_set = set(emp["resolved_ucs"])
                mask &= df["uc"].isin(uc_set)
                sub = df[mask]
                n_moving = int((sub["status"] == "moving").sum())
                n_still = int((sub["status"] == "still").sum())
                employee_note = (
                    f"{emp['name']} ({emp['role']}) covers {len(uc_set)} UC(s). "
                    f"{len(sub)} live vehicle(s) currently reporting inside their area — "
                    f"{n_moving} moving, {n_still} still."
                )
                if not uc_set:
                    employee_note = f"{emp['name']} ({emp['role']}) has no resolved UCs on record."

        filtered = df[mask]
        self.table_model.set_dataframe(filtered)

        total = len(filtered)
        live = int(filtered["is_live"].sum())
        moving = int((filtered["status"] == "moving").sum())
        still = int((filtered["status"] == "still").sum())
        in_reg = int(filtered["in_registry"].sum())
        summary = (
            f"{total:,} vehicle(s) shown\n"
            f"Live now: {live:,}  (Moving {moving:,} · Still {still:,})\n"
            f"In registry: {in_reg:,}  ·  Registry-only (not live): {total - live:,}"
        )
        self.filter_panel.set_summary(summary, employee_note)

    def _on_reset_filters(self):
        self.filter_panel.reset()
        self._apply_filters()

    # ---- report generation ----
    def _on_generate_fleet_registry_report(self):
        if self.app_data is None:
            return
        self.filter_panel.report_btn.setEnabled(False)
        self.filter_panel.report_btn.setText("Generating…")
        snapshot = self.app_data.snapshot
        self._fleet_report_thread = _BuildReportThread(
            lambda: fleet_registry_report.build_report(snapshot), self)
        self._fleet_report_thread.done.connect(self._on_fleet_report_done)
        self._fleet_report_thread.failed.connect(self._on_fleet_report_failed)
        self._fleet_report_thread.start()

    def _on_fleet_report_done(self, path: str):
        self.filter_panel.report_btn.setEnabled(True)
        self.filter_panel.report_btn.setText("Generate Fleet Registry Report (.xlsx)")
        self.statusBar().showMessage(f"Report written: {path}", 10000)
        QMessageBox.information(self, "Report generated", f"Report saved to:\n{path}")

    def _on_fleet_report_failed(self, tb: str):
        self.filter_panel.report_btn.setEnabled(True)
        self.filter_panel.report_btn.setText("Generate Fleet Registry Report (.xlsx)")
        QMessageBox.critical(self, "Report failed", tb)

    def _on_generate_report(self):
        if self.app_data is None:
            return
        report_type = self.reports_panel.report_type()
        dates = self.reports_panel.selected_dates()
        circles = self.reports_panel.selected_circles()
        snapshot = self.app_data.snapshot

        if report_type == "fleet_registry":
            fn = lambda: fleet_registry_report.build_report(snapshot)
        elif report_type == "tm":
            fn = lambda: performance_report.build("TM", dates=dates, circles=circles)
        elif report_type == "fm":
            fn = lambda: performance_report.build("FM", dates=dates, circles=circles)
        elif report_type == "combined":
            fn = lambda: combined_report.build(snapshot, dates=dates, circles=circles)
        else:
            return

        self.reports_panel.set_generating(True)
        self.reports_panel.set_status("Generating…")
        self._report_thread = _BuildReportThread(fn, self)
        self._report_thread.done.connect(self._on_report_done)
        self._report_thread.failed.connect(self._on_report_failed)
        self._report_thread.start()

    def _on_report_done(self, path: str):
        self.reports_panel.set_generating(False)
        self.reports_panel.set_status(f"Report written:\n{path}")
        QMessageBox.information(self, "Report generated", f"Report saved to:\n{path}")

    def _on_report_failed(self, tb: str):
        self.reports_panel.set_generating(False)
        self.reports_panel.set_status("Report generation failed -- see error dialog.")
        QMessageBox.critical(self, "Report failed", tb)
