"""
Persistent "Data sources" bar shown above the tab bar, visible from every
tab (Map & Analytics, Fleet Table, Reports). Lets the user pick each input
file by browsing instead of dropping it into the project root under a
filename the code has to guess -- when a source's filename or export
layout changes, you re-point the button at the new file, not edit code.

The chosen path is remembered (fleet_dashboard/config.py's
SETTINGS_PATH, a small gitignored JSON file) so it's picked up on every
future load without re-selecting, and every field it feeds (Fleet Table,
Reports, Map & Analytics) reloads automatically once a source changes.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFileDialog, QFrame, QHBoxLayout, QLabel, QPushButton, QWidget,
)

from .. import config

# key, button label, file-name filter, multi-select?
SOURCES = [
    ("vtms_csv", "VTMS Export", "CSV files (*.csv)", False),
    ("vehicle_status", "Vehicle Status", "Excel files (*.xls *.xlsx)", False),
    ("employee_roster", "Employee Roster", "Excel files (*.xlsx)", False),
    ("trip_files", "Trip Reports", "Excel files (*.xlsx)", True),
    ("fleet_registry", "Fleet Registry", "Excel files (*.xlsx)", False),
    ("vehicle_history", "Vehicle Tracks (GPS history)", "CSV files (*.csv)", False),
]


def _auto_text(key: str) -> str:
    if key == "vtms_csv":
        p = config.latest_vtms_csv()
    elif key == "vehicle_status":
        p = config.latest_vehicle_status_file()
    elif key == "employee_roster":
        p = config.latest_employee_roster()
    elif key == "fleet_registry":
        p = config.fleet_registry_xlsx()
        p = p if p.exists() else None
    elif key == "trip_files":
        files = config.trip_report_files()
        return f"auto: {len(files)} file(s)" if files else "not found"
    elif key == "vehicle_history":
        p = config.latest_vehicle_history_csv()
    else:
        p = None
    return f"auto: {p.name}" if p else "not found"


class DataSourcesBar(QWidget):
    """Emits sources_changed(key) whenever the user picks a new file for
    one of the tracked sources."""

    sources_changed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("DataSourcesBar")
        self.setStyleSheet("#DataSourcesBar { background:#f3f7f5; border-bottom:1px solid #d7e3de; }")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(8)

        title = QLabel("Data sources:")
        title.setStyleSheet("font-weight:700; color:#33403c;")
        layout.addWidget(title)

        self._status_labels: dict[str, QLabel] = {}
        for key, label, file_filter, multi in SOURCES:
            btn = QPushButton(f"Import {label}…")
            btn.setStyleSheet("padding:4px 10px;")
            btn.clicked.connect(lambda _checked=False, k=key, f=file_filter, m=multi: self._pick(k, f, m))
            layout.addWidget(btn)

            status = QLabel()
            status.setStyleSheet("color:#557b70; font-size:11px;")
            status.setToolTip(label)
            layout.addWidget(status)
            self._status_labels[key] = status

            sep = QFrame()
            sep.setFrameShape(QFrame.VLine)
            sep.setStyleSheet("color:#d7e3de;")
            layout.addWidget(sep)

        self.reset_btn = QPushButton("Reset to auto-detect")
        self.reset_btn.setStyleSheet("padding:4px 10px;")
        self.reset_btn.clicked.connect(self._reset_all)
        layout.addWidget(self.reset_btn)

        layout.addStretch(1)
        self.refresh_labels()

    def _pick(self, key: str, file_filter: str, multi: bool):
        if multi:
            paths, _ = QFileDialog.getOpenFileNames(
                self, "Select trip report file(s)", str(config.PROJECT_ROOT), file_filter)
            if not paths:
                return
            config.set_sources_override(key, paths)
        else:
            path, _ = QFileDialog.getOpenFileName(
                self, "Select file", str(config.PROJECT_ROOT), file_filter)
            if not path:
                return
            config.set_source_override(key, path)
        self.refresh_labels()
        self.sources_changed.emit(key)

    def _reset_all(self):
        for key, *_ in SOURCES:
            config.clear_source_override(key)
        self.refresh_labels()
        self.sources_changed.emit("*")

    def refresh_labels(self):
        for key, label, *_ in SOURCES:
            override = config.get_source_override(key)
            if override:
                text = (f"{len(override)} file(s) selected" if isinstance(override, list)
                        else Path(override).name)
            else:
                text = _auto_text(key)
            self._status_labels[key].setText(text)
