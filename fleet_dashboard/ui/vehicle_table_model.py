"""
QAbstractTableModel backed by a pandas DataFrame, so the vehicle table
stays responsive with several thousand rows (a QTableWidget populated cell
by cell would not).
"""
from __future__ import annotations

import pandas as pd
from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt

COLUMNS = [
    ("raw_id", "Vehicle ID"),
    ("category", "Category"),
    ("town", "Town"),
    ("uc_zone", "Zone"),
    ("uc", "UC"),
    ("status", "Status"),
    ("is_live", "Live?"),
    ("in_registry", "In Registry?"),
    ("in_assigned_area", "In Assigned Area?"),
    ("distance_km", "Distance (km)"),
    ("working_min", "Working (min)"),
    ("battery_volt", "Battery (V)"),
]

STATUS_LABEL = {"moving": "Moving", "still": "Still", "not_live": "Not Live"}


class VehicleTableModel(QAbstractTableModel):
    def __init__(self, df: pd.DataFrame | None = None, parent=None):
        super().__init__(parent)
        self._df = df if df is not None else pd.DataFrame(columns=[c for c, _ in COLUMNS])

    def set_dataframe(self, df: pd.DataFrame):
        self.beginResetModel()
        self._df = df.reset_index(drop=True)
        self.endResetModel()

    def dataframe(self) -> pd.DataFrame:
        return self._df

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._df)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(COLUMNS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role != Qt.DisplayRole:
            return None
        if orientation == Qt.Horizontal:
            return COLUMNS[section][1]
        return str(section + 1)

    def data(self, index: QModelIndex, role=Qt.DisplayRole):
        if not index.isValid() or role not in (Qt.DisplayRole, Qt.ToolTipRole):
            return None
        col_key, _ = COLUMNS[index.column()]
        val = self._df.iat[index.row(), self._df.columns.get_loc(col_key)]
        if val is None or (isinstance(val, float) and pd.isna(val)):
            return "—"
        if col_key == "status":
            return STATUS_LABEL.get(val, val)
        if col_key in ("is_live", "in_registry"):
            return "Yes" if bool(val) else "No"
        if col_key == "in_assigned_area":
            if val is True:
                return "Yes"
            if val is False:
                return "No"
            return "—"
        if col_key == "distance_km" and isinstance(val, (int, float)):
            return f"{val:,.1f}"
        if col_key == "working_min" and isinstance(val, (int, float)):
            return f"{val:,.0f}"
        if col_key == "battery_volt" and isinstance(val, (int, float)):
            return f"{val:.1f}"
        return str(val)
