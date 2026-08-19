from __future__ import annotations

import base64
import json
import re
import sys
from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtCore import QObject, Slot
from PySide6.QtWidgets import QApplication, QMainWindow
from PySide6.QtWebEngineCore import QWebEngineSettings, QWebEngineDownloadRequest
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWebChannel import QWebChannel


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
    geoJSON(geojson) {
      const group = makeLayer();
      ((geojson && geojson.features) || []).forEach(feature => {
        group._layers.push({
          feature,
          addTo() { return this; },
          bindTooltip() { return this; },
          unbindTooltip() { return this; },
          bindPopup() { return this; },
          on() { return this; },
          setStyle() { return this; },
        });
      });
      return group;
    },
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
    updated = updated.replace(
        '<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"\n'
        '        integrity="sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo=" crossorigin=""></script>',
        '<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"\n'
        '        integrity="sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo=" crossorigin=""></script>\n'
        '<script src="qrc:///qtwebchannel/qwebchannel.js"></script>',
    )
    updated = updated.replace(
        '<script>\nconst STATUS_COLOR = {moving:\'#16a34a\', still:\'#d97706\', idle:\'#2563eb\'};',
        '<script>\nlet DASHBOARD_BRIDGE = null;\n'
        "if (typeof qt !== 'undefined' && qt.webChannelTransport && typeof QWebChannel !== 'undefined') {\n"
        '  new QWebChannel(qt.webChannelTransport, channel => {\n'
        '    DASHBOARD_BRIDGE = channel.objects.dashboardBridge || null;\n'
        '    window.dashboardBridge = DASHBOARD_BRIDGE;\n'
        '  });\n'
        '}\n'
        "const STATUS_COLOR = {moving:'#16a34a', still:'#d97706', idle:'#2563eb'};",
    )
    updated = updated.replace(
        '  return makeZip(files);\n}\n\n// ---- analytical report sheets ----',
        '  return makeZip(files);\n}\n\n'
        'function bytesToBase64(bytes){\n'
        "  let binary = '';\n"
        '  const chunkSize = 0x8000;\n'
        '  for(let i = 0; i < bytes.length; i += chunkSize){\n'
        '    binary += String.fromCharCode(...bytes.subarray(i, i + chunkSize));\n'
        '  }\n'
        '  return btoa(binary);\n'
        '}\n\n// ---- analytical report sheets ----',
    )
    updated = updated.replace(
        '    const bytes = buildXlsx(sheets);\n'
        '    const blob = new Blob([bytes], {type:\'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet\'});\n'
        '    const url = URL.createObjectURL(blob);\n'
        '    const stamp = (state.date || DATA.snapshot) + \'_\' + String(referenceTime.getHours()).padStart(2,\'0\') + String(referenceTime.getMinutes()).padStart(2,\'0\');\n'
        '    const a = document.createElement(\'a\');\n'
        '    a.href = url; a.download = `LWMC_Fleet_Report_${stamp}.xlsx`;\n'
        '    document.body.appendChild(a); a.click(); document.body.removeChild(a);\n'
        '    URL.revokeObjectURL(url);\n'
        '    status.textContent = `Exported ${fmt(rows.length)} vehicles across ${sheets.length} sheets.`;',
        '    const bytes = buildXlsx(sheets);\n'
        '    const stamp = (state.date || DATA.snapshot) + \'_\' + String(referenceTime.getHours()).padStart(2,\'0\') + String(referenceTime.getMinutes()).padStart(2,\'0\');\n'
        '    const filename = `LWMC_Fleet_Report_${stamp}.xlsx`;\n'
        '    const bridge = window.dashboardBridge || DASHBOARD_BRIDGE;\n'
        "    if (bridge && typeof bridge.saveXlsx === 'function') {\n"
        '      const saved = bridge.saveXlsx(bytesToBase64(bytes), filename);\n'
        "      if (!saved) throw new Error('Desktop save bridge rejected the workbook.');\n"
        '      status.textContent = `Exported ${fmt(rows.length)} vehicles across ${sheets.length} sheets to ${filename}.`;\n'
        '      return;\n'
        '    }\n'
        '    const blob = new Blob([bytes], {type:\'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet\'});\n'
        '    const url = URL.createObjectURL(blob);\n'
        '    const a = document.createElement(\'a\');\n'
        '    a.href = url; a.download = filename;\n'
        '    document.body.appendChild(a); a.click(); document.body.removeChild(a);\n'
        '    setTimeout(() => URL.revokeObjectURL(url), 1000);\n'
        '    status.textContent = `Exported ${fmt(rows.length)} vehicles across ${sheets.length} sheets.`;',
    )
    return updated


class DashboardBridge(QObject):
    def __init__(self, root: Path) -> None:
        super().__init__()
        self._root = root.resolve()

    @Slot(str, str, result=bool)
    def saveXlsx(self, base64_payload: str, filename: str) -> bool:
        try:
            safe_name = Path(filename).name
            target = (self._root / safe_name).resolve()
            if self._root not in target.parents and target != self._root:
                return False
            target.write_bytes(base64.b64decode(base64_payload))
            return True
        except Exception:
            return False


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
        self._channel = QWebChannel(self.view.page())
        self._bridge = DashboardBridge(ROOT)
        self._channel.registerObject("dashboardBridge", self._bridge)
        self.view.page().setWebChannel(self._channel)

        html = load_dashboard_html()
        RUNTIME_HTML_PATH.write_text(html, encoding="utf-8")
        # Native HTML <select> popups in QWebEngineView occasionally fail to
        # open on click if the view hasn't actually received keyboard focus
        # yet -- easy to hit right after the window first shows, or after
        # switching back from another window (e.g. the Excel save dialog).
        # Re-grabbing focus once the page has actually finished loading (not
        # just once, at construction time) is the standard mitigation.
        self.view.page().loadFinished.connect(lambda ok: self.view.setFocus())
        self.view.setUrl(QUrl.fromLocalFile(str(RUNTIME_HTML_PATH)))

    def _handle_download(self, download: QWebEngineDownloadRequest) -> None:
        download.setDownloadDirectory(str(ROOT))
        download.setDownloadFileName(download.suggestedFileName())
        download.accept()

    def focusInEvent(self, event) -> None:  # noqa: N802 (Qt override)
        super().focusInEvent(event)
        self.view.setFocus()


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("LWMC Fleet Dashboard")
    window = DashboardWindow()
    window.show()
    window.activateWindow()
    window.raise_()
    window.view.setFocus()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
