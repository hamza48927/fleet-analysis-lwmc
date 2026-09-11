"""
Reports tab sidebar: pick a report type (Fleet Registry / TM Performance /
FM Performance / Combined) and, for the performance-based reports, filter
which dates and circles to score before generating.
"""
from __future__ import annotations

import os
import sys

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QGroupBox, QLabel, QListWidget,
    QListWidgetItem, QPushButton, QVBoxLayout, QWidget,
)

from .. import config

REPORT_TYPES = [
    ("fleet_registry", "Fleet Registry Report"),
    ("tm", "TM Performance Report (Town Managers)"),
    ("fm", "FM Performance Report (Fleet Managers)"),
    ("combined", "Combined Report (Registry + TM + FM)"),
]

# report types whose scoring is date/circle-filterable (built from the daily
# trip-report workbooks); the Fleet Registry report is a live snapshot and
# doesn't use these filters.
DATE_FILTERABLE = {"tm", "fm", "combined"}


class ReportsPanel(QWidget):
    generate_clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(320)

        self.type_box = QComboBox()
        for key, label in REPORT_TYPES:
            self.type_box.addItem(label, key)
        self.type_box.currentIndexChanged.connect(self._on_type_changed)

        self.date_list = QListWidget()
        self.date_list.setSelectionMode(QAbstractItemView.NoSelection)
        self.date_list.setMaximumHeight(140)

        self.circle_box = QComboBox()
        self.circle_box.addItem("All circles", "")

        self.status_label = QLabel("Pick a report type and click Generate.")
        self.status_label.setWordWrap(True)
        self.status_label.setStyleSheet("color:#557b70; font-size:11px;")

        self._build_layout()
        self._on_type_changed()

    def _build_layout(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        title = QLabel("Reports")
        title.setStyleSheet("font-size:14px; font-weight:700;")
        layout.addWidget(title)

        layout.addWidget(self._boxed("Report type", self.type_box))

        self.date_box_group = self._boxed("Dates to score (none checked = all)", self.date_list)
        layout.addWidget(self.date_box_group)

        self.circle_box_group = self._boxed("Circle", self.circle_box)
        layout.addWidget(self.circle_box_group)

        layout.addWidget(self._section_label("Status"))
        layout.addWidget(self.status_label)

        layout.addStretch(1)

        self.open_folder_btn = QPushButton("Open reports folder")
        self.open_folder_btn.clicked.connect(self._open_reports_folder)
        layout.addWidget(self.open_folder_btn)

        self.generate_btn = QPushButton("Generate report (.xlsx)")
        self.generate_btn.setStyleSheet(
            "background:#0d9488; color:white; font-weight:700; padding:8px; border-radius:6px;"
        )
        self.generate_btn.clicked.connect(self.generate_clicked.emit)
        layout.addWidget(self.generate_btn)

    @staticmethod
    def _boxed(label: str, widget: QWidget) -> QGroupBox:
        box = QGroupBox(label)
        v = QVBoxLayout(box)
        v.setContentsMargins(8, 14, 8, 8)
        v.addWidget(widget)
        return box

    @staticmethod
    def _section_label(text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet("font-size:10.5px; color:#84a89c; text-transform:uppercase; "
                           "letter-spacing:1px; font-weight:700; margin-top:4px;")
        return lbl

    def _on_type_changed(self):
        filterable = self.type_box.currentData() in DATE_FILTERABLE
        self.date_box_group.setVisible(filterable)
        self.circle_box_group.setVisible(filterable)

    def populate_reference_data(self, dates: list[str], circles: list[str]):
        self.date_list.clear()
        for d in dates:
            item = QListWidgetItem(d)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Unchecked)
            self.date_list.addItem(item)

        self.circle_box.clear()
        self.circle_box.addItem("All circles", "")
        for c in circles:
            self.circle_box.addItem(c, c)

    def report_type(self) -> str:
        return self.type_box.currentData()

    def selected_dates(self) -> list[str] | None:
        checked = [
            self.date_list.item(i).text()
            for i in range(self.date_list.count())
            if self.date_list.item(i).checkState() == Qt.Checked
        ]
        return checked or None

    def selected_circles(self) -> list[str] | None:
        val = self.circle_box.currentData()
        return [val] if val else None

    def set_status(self, text: str):
        self.status_label.setText(text)

    def set_generating(self, generating: bool):
        self.generate_btn.setEnabled(not generating)
        self.generate_btn.setText("Generating…" if generating else "Generate report (.xlsx)")

    def _open_reports_folder(self):
        config.REPORTS_DIR.mkdir(exist_ok=True)
        path = str(config.REPORTS_DIR)
        if sys.platform == "win32":
            os.startfile(path)  # noqa: S606
        elif sys.platform == "darwin":
            os.system(f'open "{path}"')
        else:
            os.system(f'xdg-open "{path}"')
