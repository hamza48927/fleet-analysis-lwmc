from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtWidgets import QApplication, QMainWindow
from PySide6.QtWebEngineCore import QWebEngineSettings, QWebEngineDownloadRequest
from PySide6.QtWebEngineWidgets import QWebEngineView


ROOT = Path(__file__).resolve().parent
HTML_PATH = ROOT / "LWMC_Fleet_Dashboard.html"
DATA_PATH = ROOT / "dashboard_data.json"
RUNTIME_HTML_PATH = ROOT / "_runtime_dashboard.html"


def load_dashboard_html() -> str:
    html = HTML_PATH.read_text(encoding="utf-8")
    data = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))

    fallback = """
(function () {
  if (window.L) return;
  function makeLayer() {
    return {
      _layers: [],
      addTo() { return this; },
      addLayer(layer) { this._layers.push(layer); return this; },
      clearLayers() { this._layers = []; return this; },
      eachLayer(fn) { this._layers.forEach(fn); return this; },
      bindPopup() { return this; },
      bindTooltip() { return this; },
      on() { return this; },
      setStyle() { return this; },
      openPopup() { return this; },
    };
  }
  window.L = {
    map() {
      return {
        setView() { return this; },
        fitBounds() { return this; },
        addLayer() { return this; },
        removeLayer() { return this; },
        on() { return this; },
      };
    },
    tileLayer() { return { addTo() { return this; } }; },
    geoJSON() { return { addTo() { return this; } }; },
    layerGroup() { return makeLayer(); },
    circleMarker() { return makeLayer(); },
    latLngBounds(points) {
      return {
        isValid() { return Array.isArray(points) && points.length > 0; },
        pad() { return this; },
      };
    },
  };
})();
"""

    pattern = r"const DATA\s*=\s*\{.*?\};"
    replacement = f"{fallback}\nconst DATA = {payload};"
    updated, count = re.subn(pattern, replacement, html, count=1, flags=re.S)
    if count != 1:
        raise RuntimeError("Could not find dashboard data block in LWMC_Fleet_Dashboard.html")
    return updated


class DashboardWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("LWMC Fleet Dashboard")
        self.resize(1600, 980)

        self.view = QWebEngineView(self)
        self.view.settings().setAttribute(
            QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls,
            True,
        )
        self.setCentralWidget(self.view)
        self.view.page().profile().downloadRequested.connect(self._handle_download)

        html = load_dashboard_html()
        RUNTIME_HTML_PATH.write_text(html, encoding="utf-8")
        self.view.setUrl(QUrl.fromLocalFile(str(RUNTIME_HTML_PATH)))

    def _handle_download(self, download: QWebEngineDownloadRequest) -> None:
        download.setDownloadDirectory(str(ROOT))
        download.setDownloadFileName(download.suggestedFileName())
        download.accept()


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("LWMC Fleet Dashboard")
    window = DashboardWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
