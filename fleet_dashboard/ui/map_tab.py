"""
Map & Analytics tab: embeds the existing Leaflet/HTML fleet dashboard
(LWMC_Fleet_Dashboard.html) inside a QWebEngineView, re-splicing in the
freshest dashboard_data.json at launch so this tab doesn't go stale even if
the HTML file on disk was last re-embedded a few builds ago.

This is the same approach the old standalone fleet_dashboard_app.py used
(kept here, folded into the unified dashboard, instead of as its own
separate desktop app) -- including the QWebChannel bridge that lets the
page's own "Export .xlsx" button save straight to the reports/ folder
instead of going through the browser's download prompt.
"""
from __future__ import annotations

import base64
import json
import re

from PySide6.QtCore import QObject, QUrl, Slot
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import QWebEngineDownloadRequest, QWebEngineSettings
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from .. import config

HTML_PATH = config.PROJECT_ROOT / "LWMC_Fleet_Dashboard.html"
DATA_PATH = config.PROJECT_ROOT / "dashboard_data.json"
RUNTIME_HTML_PATH = config.PROJECT_ROOT / "_runtime_dashboard.html"

_LEAFLET_FALLBACK_JS = """
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
    polyline() { return makeLayer(); },
    latLngBounds(points) {
      return {
        isValid() { return Array.isArray(points) && points.length > 0; },
        pad() { return this; },
      };
    },
  };
})();
"""


def _load_dashboard_html() -> str:
    html = HTML_PATH.read_text(encoding="utf-8")
    data = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))

    pattern = r"const DATA\s*=\s*\{.*?\};"
    replacement = f"{_LEAFLET_FALLBACK_JS}\nconst DATA = {payload};"
    updated, count = re.subn(pattern, replacement, html, count=1, flags=re.S)
    if count != 1:
        raise RuntimeError(f"Could not find dashboard data block in {HTML_PATH.name}")

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


class _DashboardBridge(QObject):
    def __init__(self, root) -> None:
        super().__init__()
        self._root = root.resolve()

    @Slot(str, str, result=bool)
    def saveXlsx(self, base64_payload: str, filename: str) -> bool:
        try:
            config.REPORTS_DIR.mkdir(exist_ok=True)
            safe_name = __import__("pathlib").Path(filename).name
            target = (config.REPORTS_DIR / safe_name).resolve()
            if config.REPORTS_DIR.resolve() not in target.parents and target != config.REPORTS_DIR.resolve():
                return False
            target.write_bytes(base64.b64decode(base64_payload))
            return True
        except Exception:
            return False


class MapTab(QWidget):
    """Wraps the QWebEngineView + QWebChannel bridge in a QWidget so it can
    be dropped straight into the main window's tab bar. Call reload() any
    time dashboard_data.json / LWMC_Fleet_Dashboard.html may have changed
    (e.g. after picking new data sources) to refresh in place -- the view
    is created lazily on the first reload() that finds both files present,
    so this also recovers from "files missing at startup"."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.view: QWebEngineView | None = None
        self._channel = None
        self._bridge = None

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)

        self._missing_label = QLabel()
        self._missing_label.setStyleSheet("padding:24px; font-size:13px; color:#8a5a2a;")
        self._missing_label.setWordWrap(True)
        self._layout.addWidget(self._missing_label)

        self.reload()

    def reload(self) -> None:
        """Re-splices the freshest dashboard_data.json into the HTML and
        reloads the page (or, the first time both files are present,
        creates the QWebEngineView)."""
        if not HTML_PATH.exists() or not DATA_PATH.exists():
            missing = HTML_PATH.name if not HTML_PATH.exists() else DATA_PATH.name
            self._missing_label.setText(
                f"Map & Analytics tab needs {missing} at the project root.\n"
                f"Import a VTMS Export above, or run: python -m fleet_dashboard.pipeline.build_master"
            )
            self._missing_label.show()
            if self.view is not None:
                self.view.hide()
            return

        try:
            html = _load_dashboard_html()
        except Exception as e:
            self._missing_label.setText(
                f"Map & Analytics tab failed to load {HTML_PATH.name}/{DATA_PATH.name}:\n{e}\n\n"
                f"Try re-running: python -m fleet_dashboard.pipeline.build_master"
            )
            self._missing_label.show()
            if self.view is not None:
                self.view.hide()
            return

        self._missing_label.hide()

        if self.view is None:
            self.view = QWebEngineView(self)
            self.view.settings().setAttribute(
                QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True,
            )
            self.view.page().profile().downloadRequested.connect(self._handle_download)
            self._channel = QWebChannel(self.view.page())
            self._bridge = _DashboardBridge(config.PROJECT_ROOT)
            self._channel.registerObject("dashboardBridge", self._bridge)
            self.view.page().setWebChannel(self._channel)
            # Native HTML <select> popups in QWebEngineView occasionally fail
            # to open on click if the view hasn't received keyboard focus yet
            # -- easy to hit right after the tab first shows. Re-grabbing
            # focus once the page has actually finished loading is the
            # standard mitigation.
            self.view.page().loadFinished.connect(lambda ok: self.view.setFocus())
            self._layout.addWidget(self.view)
        else:
            self.view.show()

        RUNTIME_HTML_PATH.write_text(html, encoding="utf-8")
        self.view.setUrl(QUrl.fromLocalFile(str(RUNTIME_HTML_PATH)))

    def _handle_download(self, download: QWebEngineDownloadRequest) -> None:
        download.setDownloadDirectory(str(config.PROJECT_ROOT))
        download.setDownloadFileName(download.suggestedFileName())
        download.accept()
