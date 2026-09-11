"""
QApplication bootstrap for the unified LWMC Fleet Dashboard.

Run with:  venv/Scripts/python.exe main.py
       or: venv/Scripts/python.exe -m fleet_dashboard.app
"""
from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from .ui.main_window import MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("LWMC Fleet Dashboard")
    window = MainWindow()
    window.show()
    window.activateWindow()
    window.raise_()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
