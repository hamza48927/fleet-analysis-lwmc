"""
Left-hand sidebar: Status / Vehicle Type / Town / Zone / UC / Employee
filters, each a searchable (type-to-filter) combo box, plus a live totals
summary and Reset button.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox, QCompleter, QGroupBox, QLabel, QPushButton,
    QVBoxLayout, QWidget,
)

from .. import config

ALL = ""  # sentinel combo-box value meaning "no filter"


def _searchable_combo(items: list[str], placeholder: str) -> QComboBox:
    box = QComboBox()
    box.setEditable(True)
    box.addItem(f"All {placeholder}", ALL)
    for it in items:
        box.addItem(it, it)
    box.setInsertPolicy(QComboBox.NoInsert)
    completer = QCompleter(box.model(), box)
    completer.setCompletionMode(QCompleter.PopupCompletion)
    completer.setFilterMode(Qt.MatchContains)
    completer.setCaseSensitivity(Qt.CaseInsensitive)
    box.setCompleter(completer)
    box.setCurrentIndex(0)
    return box


class FilterPanel(QWidget):
    filters_changed = Signal()
    reset_clicked = Signal()
    report_clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(300)

        self.status_box = QComboBox()
        self.status_box.addItem("All", ALL)
        self.status_box.addItem("Moving", "moving")
        self.status_box.addItem("Still", "still")
        self.status_box.addItem("Not Live (registry only)", "not_live")

        self.type_box: QComboBox | None = None
        self.town_box: QComboBox | None = None
        self.zone_box: QComboBox | None = None
        self.uc_box: QComboBox | None = None
        self.employee_box: QComboBox | None = None

        self.summary_label = QLabel()
        self.summary_label.setWordWrap(True)
        self.summary_label.setStyleSheet("color:#557b70; font-size:11px;")

        self.employee_note = QLabel()
        self.employee_note.setWordWrap(True)
        self.employee_note.setStyleSheet("color:#0f766e; font-weight:600; font-size:11px;")
        self.employee_note.hide()

        self._build_layout()

    def _build_layout(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        title = QLabel("Fleet Table Filters")
        title.setStyleSheet("font-size:14px; font-weight:700;")
        layout.addWidget(title)

        layout.addWidget(self._boxed("Status", self.status_box))

        layout.addWidget(QLabel("Loading reference data…"))
        self._placeholder_row = layout.count() - 1

        layout.addWidget(self._section_label("Summary"))
        layout.addWidget(self.summary_label)
        layout.addWidget(self.employee_note)

        layout.addStretch(1)

        self.reset_btn = QPushButton("Reset filters")
        self.reset_btn.clicked.connect(self.reset_clicked.emit)
        layout.addWidget(self.reset_btn)

        self.report_btn = QPushButton("Generate Fleet Registry Report (.xlsx)")
        self.report_btn.setStyleSheet(
            "background:#0d9488; color:white; font-weight:700; padding:8px; border-radius:6px;"
        )
        self.report_btn.clicked.connect(self.report_clicked.emit)
        layout.addWidget(self.report_btn)

        self._layout = layout

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

    def populate_reference_data(self, categories, towns, zones, ucs, employees):
        """Fills in the option lists (category/town/zone/UC/employee) after
        the fleet snapshot has been assembled. Safe to call more than once
        (e.g. after a data-source reload) -- any previously-inserted
        reference-data group boxes are removed first rather than piling up
        duplicates."""
        if not hasattr(self, "_ref_group_boxes"):
            self._ref_group_boxes = []
        if self._ref_group_boxes:
            for gb in self._ref_group_boxes:
                self._layout.removeWidget(gb)
                gb.deleteLater()
            self._ref_group_boxes = []
        else:
            item = self._layout.takeAt(self._placeholder_row)
            if item and item.widget():
                item.widget().deleteLater()

        self.type_box = _searchable_combo(categories, "vehicle types")
        self.town_box = _searchable_combo(towns, "towns")
        self.zone_box = _searchable_combo(zones, "zones")
        self.uc_box = _searchable_combo(ucs, "UCs")

        self.employee_box = QComboBox()
        self.employee_box.setEditable(True)
        self.employee_box.addItem("All staff / vehicles", ALL)
        role_label = config.ROLE_LABEL
        for role in config.ROLE_ORDER:
            for e in sorted([e for e in employees if e["role"] == role], key=lambda e: e["name"]):
                n_uc = len(e["resolved_ucs"])
                text = f"{e['name']} · {role_label[role]} · {n_uc} UC{'s' if n_uc != 1 else ''}"
                self.employee_box.addItem(text, e["id"])
        self.employee_box.setInsertPolicy(QComboBox.NoInsert)
        completer = QCompleter(self.employee_box.model(), self.employee_box)
        completer.setCompletionMode(QCompleter.PopupCompletion)
        completer.setFilterMode(Qt.MatchContains)
        completer.setCaseSensitivity(Qt.CaseInsensitive)
        self.employee_box.setCompleter(completer)

        for box, label in (
            (self.type_box, "Vehicle Type"), (self.town_box, "Town"),
            (self.zone_box, "Zone"), (self.uc_box, "UC"),
            (self.employee_box, "Employee"),
        ):
            gb = self._boxed(label, box)
            self._layout.insertWidget(self._layout.count() - 4, gb)
            self._ref_group_boxes.append(gb)

        for box in (self.status_box, self.type_box, self.town_box,
                    self.zone_box, self.uc_box, self.employee_box):
            box.currentIndexChanged.connect(lambda _index: self.filters_changed.emit())

    def current_filters(self) -> dict:
        def val(box):
            return box.currentData() if box is not None else ALL
        return {
            "status": val(self.status_box) or ALL,
            "category": val(self.type_box) or ALL,
            "town": val(self.town_box) or ALL,
            "zone": val(self.zone_box) or ALL,
            "uc": val(self.uc_box) or ALL,
            "employee_id": val(self.employee_box) or ALL,
        }

    def reset(self):
        for box in (self.status_box, self.type_box, self.town_box,
                    self.zone_box, self.uc_box, self.employee_box):
            if box is not None:
                box.setCurrentIndex(0)

    def set_summary(self, text: str, employee_text: str = ""):
        self.summary_label.setText(text)
        if employee_text:
            self.employee_note.setText(employee_text)
            self.employee_note.show()
        else:
            self.employee_note.hide()
