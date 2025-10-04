#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os, sys, json, time, csv, requests, platform
from datetime import datetime, timedelta

from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QTableWidget, QTableWidgetItem, QSpinBox, QCheckBox,
    QMessageBox, QTextEdit, QPlainTextEdit, QTabWidget, QMenuBar, QAction,
    QFileDialog, QProgressBar, QGraphicsView, QGraphicsScene, QGraphicsRectItem,
    QGraphicsTextItem, QGridLayout, QSizePolicy, QDialog, QFormLayout,
    QDialogButtonBox, QDoubleSpinBox, QGroupBox, QComboBox, QSplitter, QHeaderView
)
from PyQt5.QtCore import Qt, QTimer, QPointF, QDateTime
from PyQt5.QtGui import QBrush, QPen, QColor, QFont, QPainter, QTextCursor
from PyQt5.QtChart import QChart, QChartView, QLineSeries, QValueAxis, QDateTimeAxis

# ========== Memori (optional) ==========
# Tries to use `memorisdk`. If missing, falls back to plain HTTP POST to MEMORI_URL/events.
# Disable entirely by leaving MEMORI_ENABLED unset or set to "0".
MEMORI_ENABLED = os.getenv("MEMORI_ENABLED", "0") not in ("0", "", "false", "False")
MEMORI_URL = os.getenv("MEMORI_URL", "").rstrip("/")
MEMORI_API_KEY = os.getenv("MEMORI_API_KEY", "")
MEMORI_STREAM_DEFAULT = os.getenv("MEMORI_STREAM", "status")
MEMORI_STREAM_ALERT = os.getenv("MEMORI_STREAM_ALERT", "alert")
MEMORI_STREAM_CONSOLE = os.getenv("MEMORI_STREAM_CONSOLE", "console")

class _MemoriClient:
    def __init__(self, enabled: bool, url: str, api_key: str):
        self.enabled = enabled and bool(url) and bool(api_key)
        self.url = url
        self.api_key = api_key
        self._sdk = None
        if self.enabled:
            try:
                import memorisdk  # type: ignore
                self._sdk = memorisdk.Client(api_key=self.api_key, base_url=self.url)
            except Exception:
                self._sdk = None

        # throttle console events to avoid spamming
        self._last_console_push = 0.0
        self._console_interval = 5.0  # seconds

    def send(self, stream: str, payload: dict):
        """Fire-and-forget send."""
        if not self.enabled:
            return
        try:
            if self._sdk:
                # memorisdk path
                self._sdk.events.create(stream=stream, payload=payload)
            else:
                # generic HTTP fallback
                headers = {
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                }
                # common endpoint guess; adjust if your server differs
                url = f"{self.url}/events"
                requests.post(url, headers=headers, json={"stream": stream, "payload": payload}, timeout=3)
        except Exception:
            # swallow to avoid UI interruption
            pass

    def send_status(self, payload: dict):
        self.send(MEMORI_STREAM_DEFAULT, payload)

    def send_alert(self, message: str, level: str = "WARNING", extra: dict = None):
        data = {
            "ts": datetime.utcnow().isoformat() + "Z",
            "level": level,
            "message": message,
            "host": platform.node(),
        }
        if extra:
            data.update(extra)
        self.send(MEMORI_STREAM_ALERT, data)

    def send_console_tail(self, last_line: str):
        now = time.time()
        if now - self._last_console_push < self._console_interval:
            return
        self._last_console_push = now
        self.send(MEMORI_STREAM_CONSOLE, {
            "ts": datetime.utcnow().isoformat() + "Z",
            "line": last_line[-2000:],  # cap size
            "host": platform.node(),
        })

MEMORI = _MemoriClient(MEMORI_ENABLED, MEMORI_URL, MEMORI_API_KEY)

# ========== Helpers ==========
def jpretty(obj):
    try:
        return json.dumps(obj, indent=2, ensure_ascii=False)
    except Exception:
        return str(obj)

def join_url(base, path):
    base = base.rstrip("/")
    if not path.startswith("/"):
        path = "/" + path
    return base + path

def ok_style(ok):
    return "color:#0a0;" if ok else "color:#a00;"

def format_bytes(size):
    """Convert bytes to human readable format"""
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size < 1024.0:
            return f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} PB"

OVERVIEW_ENDPOINTS = [
    ("health",            "GET", "/health"),
    ("status",            "GET", "/status"),
    ("heartbeat",         "GET", "/heartbeat"),
    ("reindex_status",    "GET", "/reindex/status"),
    ("index_stats",       "GET", "/index/stats"),
    ("safeguards_status", "GET", "/safeguards/status"),
    ("gpu_status",        "GET", "/gpu/status"),
    ("memory_status",     "GET", "/memory/status"),
]

# ========== Threshold dialog ==========
class ThresholdsDialog(QDialog):
    def __init__(self, parent=None, values=None):
        super().__init__(parent)
        self.setWindowTitle("Set Thresholds & Alerts")
        self.setModal(True)
        self.resize(500, 600)
        
        v = QVBoxLayout(self)
        form = QFormLayout()

        vals = values or {}
        def d(key, fallback): return float(vals.get(key, fallback))

        # Warning thresholds (%)
        self.warn_guiding  = QDoubleSpinBox(); self.warn_guiding.setRange(0,100); self.warn_guiding.setValue(d("warn_guiding",80)); self.warn_guiding.setSuffix(" %")
        self.warn_traveler = QDoubleSpinBox(); self.warn_traveler.setRange(0,100); self.warn_traveler.setValue(d("warn_traveler",80)); self.warn_traveler.setSuffix(" %")
        self.warn_symbols  = QDoubleSpinBox(); self.warn_symbols.setRange(0,100); self.warn_symbols.setValue(d("warn_symbols",80)); self.warn_symbols.setSuffix(" %")

        # Failure thresholds (%)
        self.bad_guiding  = QDoubleSpinBox(); self.bad_guiding.setRange(0,100); self.bad_guiding.setValue(d("bad_guiding",60)); self.bad_guiding.setSuffix(" %")
        self.bad_traveler = QDoubleSpinBox(); self.bad_traveler.setRange(0,100); self.bad_traveler.setValue(d("bad_traveler",60)); self.bad_traveler.setSuffix(" %")
        self.bad_symbols  = QDoubleSpinBox(); self.bad_symbols.setRange(0,100); self.bad_symbols.setValue(d("bad_symbols",60)); self.bad_symbols.setSuffix(" %")

        # Min scrolls (warn if ≤ this)
        self.min_scrolls  = QSpinBox(); self.min_scrolls.setRange(0, 10_000_000); self.min_scrolls.setValue(int(vals.get("min_scrolls", 0)))
        
        # Alert settings
        self.alert_sound = QCheckBox("Play alert sound")
        self.alert_sound.setChecked(vals.get("alert_sound", False))
        self.alert_notification = QCheckBox("Show desktop notifications")
        self.alert_notification.setChecked(vals.get("alert_notification", False))
        self.alert_cooldown = QSpinBox()
        self.alert_cooldown.setRange(1, 3600)
        self.alert_cooldown.setValue(vals.get("alert_cooldown", 300))
        self.alert_cooldown.setSuffix(" seconds")

        form.addRow("Warn: Guiding >=", self.warn_guiding)
        form.addRow("Warn: Traveler >=", self.warn_traveler)
        form.addRow("Warn: Symbols >=", self.warn_symbols)
        form.addRow("Bad:  Guiding <", self.bad_guiding)
        form.addRow("Bad:  Traveler <", self.bad_traveler)
        form.addRow("Bad:  Symbols <", self.bad_symbols)
        form.addRow("Warn if Scrolls Loaded ≤", self.min_scrolls)
        
        form.addRow(QLabel("<hr><b>Alert Settings</b>"))
        form.addRow("Alert Cooldown", self.alert_cooldown)
        form.addRow("", self.alert_sound)
        form.addRow("", self.alert_notification)

        v.addLayout(form)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)

    def values(self):
        return {
            "warn_guiding":  float(self.warn_guiding.value()),
            "warn_traveler": float(self.warn_traveler.value()),
            "warn_symbols":  float(self.warn_symbols.value()),
            "bad_guiding":   float(self.bad_guiding.value()),
            "bad_traveler":  float(self.bad_traveler.value()),
            "bad_symbols":   float(self.bad_symbols.value()),
            "min_scrolls":   int(self.min_scrolls.value()),
            "alert_sound":   self.alert_sound.isChecked(),
            "alert_notification": self.alert_notification.isChecked(),
            "alert_cooldown": self.alert_cooldown.value(),
        }

# ========== Alert History Dialog ==========
class AlertHistoryDialog(QDialog):
    def __init__(self, parent=None, alerts=None):
        super().__init__(parent)
        self.setWindowTitle("Alert History")
        self.setModal(True)
        self.resize(800, 400)
        
        layout = QVBoxLayout(self)
        self.table = QTableWidget()
        self.table.setColumnCount(3)
        self.table.setHorizontalHeaderLabels(["Time", "Level", "Message"])
        self.table.setColumnWidth(0, 160)
        self.table.setColumnWidth(1, 80)
        self.table.setColumnWidth(2, 500)
        layout.addWidget(self.table)
        
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.rejected.connect(self.reject)
        layout.addWidget(bb)
        
        if alerts:
            self.load_alerts(alerts)
    
    def load_alerts(self, alerts):
        self.table.setRowCount(len(alerts))
        for row, alert in enumerate(alerts):
            self.table.setItem(row, 0, QTableWidgetItem(alert.get('time', '')))
            self.table.setItem(row, 1, QTableWidgetItem(alert.get('level', '')))
            self.table.setItem(row, 2, QTableWidgetItem(alert.get('message', '')))
            
            level = alert.get('level', '').lower()
            if level == 'critical':
                color = QColor(220, 53, 69)
            elif level == 'warning':
                color = QColor(255, 193, 7)
            else:
                color = QColor(40, 167, 69)
            for col in range(3):
                self.table.item(row, col).setBackground(color)

# ========== App ==========
class MirrorMonitor(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("🪞 Mirror v4 Monitor — Enhanced Dashboard")
        self.resize(1520, 980)

        # Build UI first, then init charts, then first refresh
        self.build_ui()
        self.init_charts()
        self.apply_theme("light")
        self.refresh_all()

    def _to_msecs(self, ts):
        if isinstance(ts, QDateTime):
            return int(ts.toMSecsSinceEpoch())
        from datetime import datetime as _dt
        if isinstance(ts, _dt):
            return int(ts.timestamp() * 1000)
        if isinstance(ts, (int, float)):
            return int(ts)
        return 0

    # ---------- Build the WHOLE UI ----------
    def build_ui(self):
        # Defaults
        self.base_url = "http://127.0.0.1:8080"
        self.root_path = ""            # e.g. "/mirror-v4"
        self.interval_s = 5

        # Thresholds (editable via dialog)
        self.thresholds = {
            "warn_guiding": 80.0,
            "warn_traveler": 80.0,
            "warn_symbols": 80.0,
            "bad_guiding": 60.0,
            "bad_traveler": 60.0,
            "bad_symbols": 60.0,
            "min_scrolls": 0,
            "alert_sound": False,
            "alert_notification": False,
            "alert_cooldown": 300
        }
        
        # Historical data storage
        self.history = {
            'timestamps': [],
            'gpu_util': [],
            'cadence_metrics': {'guiding': [], 'traveler': [], 'symbols': []},
            'memory_usage': [],
            'request_counts': [],
            'alert_history': []
        }
        
        # Alert state
        self.last_alert_time = 0
        self.current_alert_level = "ok"

        # Menu bar
        menubar = QMenuBar(self)
        file_menu = menubar.addMenu("File")
        tools_menu = menubar.addMenu("Tools")
        view_menu  = menubar.addMenu("View")
        help_menu  = menubar.addMenu("Help")

        act_quit = QAction("Quit", self, triggered=lambda: QApplication.instance().quit())
        act_export_reqs = QAction("Export Requests CSV", self, triggered=self.export_requests_csv)
        act_export_rag  = QAction("Export RAG CSV", self, triggered=self.export_rag_csv)
        act_export_history = QAction("Export History Data", self, triggered=self.export_history_data)
        act_kick_reindex = QAction("Kick Reindex (background)", self, triggered=self.kick_reindex_bg)
        act_copy_status_curl = QAction("Copy curl for /status", self, triggered=self.copy_status_curl)
        act_light = QAction("Light Theme", self, checkable=True)
        act_dark  = QAction("Dark Theme", self, checkable=True)
        act_compact = QAction("Compact View", self, checkable=True, triggered=self.toggle_compact_view)
        act_dark.setChecked(False); act_light.setChecked(True)
        act_light.toggled.connect(lambda on: self.apply_theme("light" if on else "dark"))
        act_dark.toggled.connect(lambda on: self.apply_theme("dark" if on else "light"))
        act_thresholds = QAction("Set Thresholds…", self, triggered=self.open_thresholds)
        act_alert_history = QAction("View Alert History", self, triggered=self.show_alert_history)
        act_clear_history = QAction("Clear History Data", self, triggered=self.clear_history_data)
        act_about = QAction("About", self, triggered=self.show_about)

        file_menu.addAction(act_export_reqs)
        file_menu.addAction(act_export_rag)
        file_menu.addAction(act_export_history)
        file_menu.addSeparator()
        file_menu.addAction(act_quit)

        tools_menu.addAction(act_kick_reindex)
        tools_menu.addAction(act_copy_status_curl)
        tools_menu.addSeparator()
        tools_menu.addAction(act_clear_history)

        view_menu.addAction(act_light)
        view_menu.addAction(act_dark)
        view_menu.addAction(act_compact)
        view_menu.addSeparator()
        view_menu.addAction(act_thresholds)
        view_menu.addAction(act_alert_history)

        help_menu.addAction(act_about)

        # Top bar
        controls = QHBoxLayout()
        controls.addWidget(QLabel("Base URL:"))
        self.base_edit = QLineEdit(self.base_url); self.base_edit.setMinimumWidth(320)
        controls.addWidget(self.base_edit)

        controls.addWidget(QLabel("Root path:"))
        self.root_edit = QLineEdit(self.root_path)
        self.root_edit.setPlaceholderText("e.g. /mirror-v4 (optional)")
        controls.addWidget(self.root_edit)

        controls.addWidget(QLabel("Refresh (s):"))
        self.int_spin = QSpinBox(); self.int_spin.setRange(1, 3600); self.int_spin.setValue(self.interval_s)
        controls.addWidget(self.int_spin)

        self.auto_chk = QCheckBox("Auto")
        self.auto_chk.stateChanged.connect(self.toggle_auto)
        controls.addWidget(self.auto_chk)

        self.refresh_btn = QPushButton("Refresh now", clicked=self.refresh_all)
        controls.addWidget(self.refresh_btn)
        
        # Test connection button
        self.test_btn = QPushButton("Test Connection", clicked=self.test_connection)
        controls.addWidget(self.test_btn)

        # Header status (pill + text)
        status_row = QHBoxLayout()
        self.status_pill = QLabel("●")
        self.status_pill.setFixedWidth(18)
        self.status_pill.setAlignment(Qt.AlignCenter)
        self.status_pill.setStyleSheet("color:#fff; background:#777; border-radius:9px;")
        status_row.addWidget(self.status_pill)
        self.status_line = QLabel("Status: -")
        status_line_font = QFont(); status_line_font.setBold(True)
        self.status_line.setFont(status_line_font)
        status_row.addWidget(self.status_line)
        status_row.addStretch(1)
        
        # Alert indicator
        self.alert_indicator = QLabel("🔔")
        self.alert_indicator.setToolTip("No active alerts")
        self.alert_indicator.setStyleSheet("color: #28a745; font-size: 16px;")
        status_row.addWidget(self.alert_indicator)

        # Tabs
        self.tabs = QTabWidget()

        # --- Overview tab ---
        self.overview_tab = QWidget()
        ov = QVBoxLayout(self.overview_tab)

        self.overview_table = QTableWidget()
        self.overview_table.setColumnCount(2)
        self.overview_table.setHorizontalHeaderLabels(["Endpoint", "OK / Summary"])
        self.overview_table.setColumnWidth(0, 220)
        self.overview_table.setColumnWidth(1, 900)
        self.overview_table.setRowCount(len(OVERVIEW_ENDPOINTS))
        for i, (name, _, path) in enumerate(OVERVIEW_ENDPOINTS):
            self.overview_table.setItem(i, 0, QTableWidgetItem(f"{name} ({path})"))
            self.overview_table.setItem(i, 1, QTableWidgetItem("—"))
        ov.addWidget(self.overview_table)

        ov.addWidget(QLabel("Details (selected endpoint)"))
        self.detail_json = QTextEdit(); self.detail_json.setReadOnly(True)
        ov.addWidget(self.detail_json)

        self.overview_table.cellClicked.connect(self.show_overview_detail)
        self.tabs.addTab(self.overview_tab, "Overview")

        # --- Flow tab ---
        self.flow_tab = QWidget()
        fl = QGridLayout(self.flow_tab)

        self.flow_view = QGraphicsView()
        self.flow_scene = QGraphicsScene(self.flow_view)
        self.flow_view.setScene(self.flow_scene)
        self.flow_view.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        self.pb_traveler = QProgressBar(); self.pb_traveler.setFormat("Traveler %p%")
        self.pb_guiding  = QProgressBar(); self.pb_guiding.setFormat("Guiding %p%")
        self.pb_symbols  = QProgressBar(); self.pb_symbols.setFormat("Symbols %p%")

        self.modules_grid = QWidget()
        mg = QGridLayout(self.modules_grid); mg.setColumnStretch(1, 1)
        self.dot_temporal = QLabel("●"); self.dot_symbol = QLabel("●"); self.dot_conv = QLabel("●")
        for d in (self.dot_temporal, self.dot_symbol, self.dot_conv):
            d.setStyleSheet("color:#aaa; font-size:16px;")
        mg.addWidget(QLabel("Temporal"), 0, 0); mg.addWidget(self.dot_temporal, 0, 1)
        mg.addWidget(QLabel("Symbol"),   1, 0); mg.addWidget(self.dot_symbol,   1, 1)
        mg.addWidget(QLabel("Conversation"), 2, 0); mg.addWidget(self.dot_conv, 2, 1)
        
        # Cadence history chart
        self.cadence_chart_view = QChartView(); self.cadence_chart_view.setRenderHint(QPainter.Antialiasing)
        self.cadence_chart = QChart(); self.cadence_chart.setTitle("Cadence History")
        self.cadence_chart_view.setChart(self.cadence_chart); self.cadence_chart_view.setMinimumHeight(200)

        fl.addWidget(self.flow_view,     0, 0, 4, 1)
        fl.addWidget(QLabel("Cadence (%)"), 0, 1)
        fl.addWidget(self.pb_traveler,   1, 1)
        fl.addWidget(self.pb_guiding,    2, 1)
        fl.addWidget(self.pb_symbols,    3, 1)
        fl.addWidget(QLabel("Modules"),  4, 1)
        fl.addWidget(self.modules_grid,  5, 1)
        fl.addWidget(self.cadence_chart_view, 6, 0, 1, 2)
        self.tabs.addTab(self.flow_tab, "Flow")

        # --- GPU tab ---
        self.gpu_tab = QWidget()
        gg = QVBoxLayout(self.gpu_tab)
        self.gpu_summary = QLabel("GPU: -")
        gg.addWidget(self.gpu_summary)
        self.gpu_table = QTableWidget()
        self.gpu_table.setColumnCount(6)
        self.gpu_table.setHorizontalHeaderLabels(["Index", "Name", "Util %", "Mem (MB) used/total", "Temp °C", "Power W"])
        self.gpu_table.setColumnWidth(0, 60)
        self.gpu_table.setColumnWidth(1, 260)
        self.gpu_table.setColumnWidth(2, 80)
        self.gpu_table.setColumnWidth(3, 180)
        self.gpu_table.setColumnWidth(4, 80)
        self.gpu_table.setColumnWidth(5, 80)
        gg.addWidget(self.gpu_table)
        
        # GPU history chart
        self.gpu_chart_view = QChartView(); self.gpu_chart_view.setRenderHint(QPainter.Antialiasing)
        self.gpu_chart = QChart(); self.gpu_chart.setTitle("GPU Utilization History")
        self.gpu_chart_view.setChart(self.gpu_chart); self.gpu_chart_view.setMinimumHeight(200)
        gg.addWidget(self.gpu_chart_view)
        self.tabs.addTab(self.gpu_tab, "GPU")

        # --- Requests tab ---
        self.req_tab = QWidget()
        rq = QVBoxLayout(self.req_tab)
        
        # Request filter controls
        filter_layout = QHBoxLayout()
        filter_layout.addWidget(QLabel("Filter by:"))
        self.req_filter_combo = QComboBox()
        self.req_filter_combo.addItems(["All", "Success", "Failed"])
        self.req_filter_combo.currentTextChanged.connect(self.filter_requests)
        filter_layout.addWidget(self.req_filter_combo)
        filter_layout.addStretch()
        rq.addLayout(filter_layout)
        
        self.req_table = QTableWidget()
        self.req_table.setColumnCount(5)
        self.req_table.setHorizontalHeaderLabels(["Time", "User", "Latency ms", "OK", "Question"])
        self.req_table.setColumnWidth(0, 160)
        self.req_table.setColumnWidth(1, 120)
        self.req_table.setColumnWidth(2, 100)
        self.req_table.setColumnWidth(3, 60)
        self.req_table.setColumnWidth(4, 700)
        rq.addWidget(self.req_table)
        
        # Request stats
        stats_layout = QHBoxLayout()
        self.req_stats_label = QLabel("Total: 0 | Success: 0 | Failed: 0 | Avg Latency: 0ms")
        stats_layout.addWidget(self.req_stats_label)
        stats_layout.addStretch()
        rq.addLayout(stats_layout)
        
        self.tabs.addTab(self.req_tab, "Requests")

        # --- RAG tab ---
        self.rag_tab = QWidget()
        rg = QVBoxLayout(self.rag_tab)

        top_row = QHBoxLayout()
        self.rag_table = QTableWidget()
        self.rag_table.setColumnCount(4)
        self.rag_table.setHorizontalHeaderLabels(["Time", "Latency ms", "Question", "Top-k"])
        self.rag_table.setColumnWidth(0, 160)
        self.rag_table.setColumnWidth(1, 100)
        self.rag_table.setColumnWidth(2, 560)
        self.rag_table.setColumnWidth(3, 60)
        top_row.addWidget(self.rag_table, 3)

        self.hits_table = QTableWidget()
        self.hits_table.setColumnCount(3)
        self.hits_table.setHorizontalHeaderLabels(["Doc ID", "Title", "Score"])
        self.hits_table.setColumnWidth(0, 220)
        self.hits_table.setColumnWidth(1, 420)
        self.hits_table.setColumnWidth(2, 80)
        top_row.addWidget(self.hits_table, 2)
        rg.addLayout(top_row)

        rg.addWidget(QLabel("Document Preview:"))
        self.doc_preview = QPlainTextEdit(); self.doc_preview.setReadOnly(True)
        rg.addWidget(self.doc_preview)
        
        # RAG performance chart
        self.rag_chart_view = QChartView(); self.rag_chart_view.setRenderHint(QPainter.Antialiasing)
        self.rag_chart = QChart(); self.rag_chart.setTitle("RAG Latency History")
        self.rag_chart_view.setChart(self.rag_chart); self.rag_chart_view.setMinimumHeight(200)
        rg.addWidget(self.rag_chart_view)
        
        self.tabs.addTab(self.rag_tab, "RAG")

        self.rag_table.cellClicked.connect(self.on_rag_row_clicked)
        self.hits_table.cellClicked.connect(self.on_hit_clicked)

        # --- Console tab ---
        self.console_tab = QWidget()
        cl = QVBoxLayout(self.console_tab)
        btnrow = QHBoxLayout()
        self.console_refresh = QPushButton("Refresh Console", clicked=self.refresh_console)
        self.console_auto = QCheckBox("Auto")
        self.console_auto.stateChanged.connect(self.toggle_console_auto)
        btnrow.addWidget(self.console_refresh); btnrow.addWidget(self.console_auto); btnrow.addStretch(1)
        cl.addLayout(btnrow)

        self.console = QPlainTextEdit(); self.console.setReadOnly(True)
        self.console.setMaximumBlockCount(2000)  # keep it smooth
        cl.addWidget(self.console)
        self.tabs.addTab(self.console_tab, "Console")
        
        # --- Analytics tab ---
        self.analytics_tab = QWidget()
        al = QVBoxLayout(self.analytics_tab)
        
        # System metrics over time
        self.metrics_chart_view = QChartView(); self.metrics_chart_view.setRenderHint(QPainter.Antialiasing)
        self.metrics_chart = QChart(); self.metrics_chart.setTitle("System Metrics Over Time")
        self.metrics_chart_view.setChart(self.metrics_chart); self.metrics_chart_view.setMinimumHeight(300)
        al.addWidget(self.metrics_chart_view)
        
        # Memory usage
        self.memory_chart_view = QChartView(); self.memory_chart_view.setRenderHint(QPainter.Antialiasing)
        self.memory_chart = QChart(); self.memory_chart.setTitle("Memory Usage")
        self.memory_chart_view.setChart(self.memory_chart); self.memory_chart_view.setMinimumHeight(300)
        al.addWidget(self.memory_chart_view)
        
        self.tabs.addTab(self.analytics_tab, "Analytics")

        # Root layout
        root = QVBoxLayout(self)
        root.setMenuBar(menubar)
        root.addLayout(controls)
        root.addLayout(status_row)
        root.addWidget(self.tabs, 1)

        # Timers
        self.timer = QTimer(self); self.timer.timeout.connect(self.refresh_all)
        self.console_timer = QTimer(self); self.console_timer.timeout.connect(self.refresh_console)

        # State caches
        self._overview_details = {}
        self._rag_cache = []
        self._all_requests = []

    # ---------- Theme ----------
    def apply_theme(self, which: str):
        if which == "dark":
            self.setStyleSheet("""
                QWidget { background: #1e1e1e; color: #e0e0e0; }
                QLineEdit, QTextEdit, QPlainTextEdit, QTableWidget, QProgressBar {
                    background: #2a2a2a; color: #e0e0e0; border: 1px solid #444;
                }
                QHeaderView::section { background: #333; color: #ddd; }
                QPushButton { background: #333; color: #eee; border: 1px solid #555; }
                QPushButton:hover { background: #444; }
                QTabWidget::pane { border: 1px solid #444; }
                QTabBar::tab { background: #333; color: #ddd; padding: 8px; }
                QTabBar::tab:selected { background: #2a2a2a; }
            """)
            for chart in [self.cadence_chart, self.gpu_chart, self.rag_chart, self.metrics_chart, self.memory_chart]:
                chart.setTheme(QChart.ChartThemeDark)
        else:
            self.setStyleSheet("")
            for chart in [self.cadence_chart, self.gpu_chart, self.rag_chart, self.metrics_chart, self.memory_chart]:
                chart.setTheme(QChart.ChartThemeLight)

    # ---------- Compact View ----------
    def toggle_compact_view(self, checked):
        if checked:
            self.resize(1000, 700)
            self.setStyleSheet(self.styleSheet() + "QTableWidget { font-size: 10px; }")
        else:
            self.resize(1520, 980)
            self.setStyleSheet(self.styleSheet().replace("QTableWidget { font-size: 10px; }", ""))

    # ---------- Initialize Charts ONLY ----------
    def init_charts(self):
        # Initialize cadence chart
        self.cadence_series = {}
        self.cadence_chart = self.cadence_chart
        colors = {"guiding": QColor(40, 167, 69), "traveler": QColor(0, 123, 255), "symbols": QColor(111, 66, 193)}
        for metric, color in colors.items():
            series = QLineSeries(); series.setName(metric.capitalize()); series.setColor(color)
            self.cadence_chart.addSeries(series)
            self.cadence_series[metric] = series
        
        axis_x = QDateTimeAxis(); axis_x.setFormat("hh:mm:ss"); axis_x.setTitleText("Time")
        self.cadence_chart.addAxis(axis_x, Qt.AlignBottom)
        axis_y = QValueAxis(); axis_y.setRange(0, 100); axis_y.setTitleText("Percentage")
        self.cadence_chart.addAxis(axis_y, Qt.AlignLeft)
        for series in self.cadence_series.values():
            series.attachAxis(axis_x); series.attachAxis(axis_y)
        
        # GPU chart
        self.gpu_series = QLineSeries(); self.gpu_series.setName("GPU Utilization"); self.gpu_series.setColor(QColor(220, 53, 69))
        self.gpu_chart = self.gpu_chart; self.gpu_chart.addSeries(self.gpu_series)
        gpu_axis_x = QDateTimeAxis(); gpu_axis_x.setFormat("hh:mm:ss"); gpu_axis_x.setTitleText("Time")
        self.gpu_chart.addAxis(gpu_axis_x, Qt.AlignBottom)
        gpu_axis_y = QValueAxis(); gpu_axis_y.setRange(0, 100); gpu_axis_y.setTitleText("Percentage")
        self.gpu_chart.addAxis(gpu_axis_y, Qt.AlignLeft)
        self.gpu_series.attachAxis(gpu_axis_x); self.gpu_series.attachAxis(gpu_axis_y)
        
        # RAG chart
        self.rag_series = QLineSeries(); self.rag_series.setName("RAG Latency"); self.rag_series.setColor(QColor(253, 126, 20))
        self.rag_chart = self.rag_chart; self.rag_chart.addSeries(self.rag_series)
        rag_axis_x = QDateTimeAxis(); rag_axis_x.setFormat("hh:mm:ss"); rag_axis_x.setTitleText("Time")
        self.rag_chart.addAxis(rag_axis_x, Qt.AlignBottom)
        rag_axis_y = QValueAxis(); rag_axis_y.setTitleText("Latency (ms)")
        self.rag_chart.addAxis(rag_axis_y, Qt.AlignLeft)
        self.rag_series.attachAxis(rag_axis_x); self.rag_series.attachAxis(rag_axis_y)
        
        # Metrics chart
        self.metrics_series = {}
        metrics_colors = { "requests": QColor(40, 167, 69), "scrolls": QColor(0, 123, 255), "memory": QColor(111, 66, 193) }
        for metric, color in metrics_colors.items():
            series = QLineSeries(); series.setName(metric.capitalize()); series.setColor(color)
            self.metrics_chart.addSeries(series)
            self.metrics_series[metric] = series
        metrics_axis_x = QDateTimeAxis(); metrics_axis_x.setFormat("hh:mm:ss"); metrics_axis_x.setTitleText("Time")
        self.metrics_chart.addAxis(metrics_axis_x, Qt.AlignBottom)
        metrics_axis_y = QValueAxis(); metrics_axis_y.setTitleText("Value")
        self.metrics_chart.addAxis(metrics_axis_y, Qt.AlignLeft)
        for series in self.metrics_series.values():
            series.attachAxis(metrics_axis_x); series.attachAxis(metrics_axis_y)
            
        # Memory chart
        self.memory_series = QLineSeries(); self.memory_series.setName("Memory Usage"); self.memory_series.setColor(QColor(32, 201, 151))
        self.memory_chart.addSeries(self.memory_series)
        memory_axis_x = QDateTimeAxis(); memory_axis_x.setFormat("hh:mm:ss"); memory_axis_x.setTitleText("Time")
        self.memory_chart.addAxis(memory_axis_x, Qt.AlignBottom)
        memory_axis_y = QValueAxis(); memory_axis_y.setTitleText("MB")
        self.memory_chart.addAxis(memory_axis_y, Qt.AlignLeft)
        self.memory_series.attachAxis(memory_axis_x); self.memory_series.attachAxis(memory_axis_y)

    # ---------- URL helpers ----------
    def root_join(self, p: str) -> str:
        base = self.base_edit.text().strip()
        root = self.root_edit.text().strip()
        return join_url(base, (root.rstrip("/") + p) if root else p)

    # ---------- Requests ----------
    def request_json(self, method, path):
        url = self.root_join(path)
        try:
            r = requests.request(method, url, timeout=10)
            if "application/json" in (r.headers.get("content-type") or ""):
                return True, r.json()
            try:
                return True, r.json()
            except Exception:
                return True, {"raw": r.text[:2000]}
        except Exception as e:
            return False, {"error": str(e)}

    # ---------- Test Connection ----------
    def test_connection(self):
        self.status_line.setText("Testing connection...")
        ok, payload = self.request_json("GET", "/health")
        if ok:
            QMessageBox.information(self, "Connection Test", f"Successfully connected to {self.root_join('/health')}")
            self.status_line.setText("Connection test successful")
            MEMORI.send_status({"evt": "connection.ok", "ts": datetime.utcnow().isoformat()+"Z", "url": self.root_join('/health')})
        else:
            QMessageBox.critical(self, "Connection Test", f"Failed to connect: {payload.get('error', 'Unknown error')}")
            self.status_line.setText("Connection test failed")
            MEMORI.send_alert(f"Connection test failed: {payload.get('error','?')}", level="CRITICAL")

    # ---------- Thresholds ----------
    def open_thresholds(self):
        dlg = ThresholdsDialog(self, self.thresholds)
        if dlg.exec_() == QDialog.Accepted:
            self.thresholds = dlg.values()
            self.refresh_all()

    # ---------- Alert History ----------
    def show_alert_history(self):
        dlg = AlertHistoryDialog(self, self.history['alert_history'])
        dlg.exec_()

    # ---------- Refresh cycles ----------
    def toggle_auto(self, state):
        self.interval_s = self.int_spin.value()
        if state == Qt.Checked:
            self.timer.start(self.interval_s * 1000)
            self.status_line.setText("Status: auto-refresh ON")
        else:
            self.timer.stop()
            self.status_line.setText("Status: auto-refresh OFF")

    def refresh_all(self):
        current_time = datetime.now()
        ok_count = 0
        details = {}
        for i, (name, method, path) in enumerate(OVERVIEW_ENDPOINTS):
            ok, payload = self.request_json(method, path)
            details[name] = payload
            cell = self.overview_table.item(i, 1)
            if ok:
                ok_count += 1
                cell.setText(self.summarize_overview(name, payload))
                cell.setForeground(QBrush(QColor(0, 0, 0)))
            else:
                cell.setText(f"ERROR: {payload.get('error','?')}")
                cell.setForeground(QBrush(QColor(255, 0, 0)))

        self._overview_details = details

        # Memori heartbeat (lightweight)
        try:
            hb = {
                "evt": "heartbeat",
                "ts": datetime.utcnow().isoformat()+"Z",
                "scrolls_loaded": (details.get("status", {}) or {}).get("scrolls_loaded", 0),
                "gpu_ok": (details.get("gpu_status", {}) or {}).get("ok", False),
                "requests_ask": (details.get("status", {}) or {}).get("requests", {}).get("ask", 0),
            }
            MEMORI.send_status(hb)
        except Exception:
            pass

        # Fill GPU tab
        self.fill_gpu(details.get("gpu_status", {}))

        # Requests
        ok_t, trace = self.request_json("GET", "/trace/recent?limit=200")
        if ok_t: 
            self.fill_requests(trace)
            items = trace.get("items", [])
            self.history['request_counts'].append(len(items))
            if len(self.history['request_counts']) > 100:
                self.history['request_counts'].pop(0)

        # RAG
        ok_r, rag = self.request_json("GET", "/rag/last?limit=50")
        if ok_r: 
            self.fill_rag(rag)
            items = rag.get("items", [])
            if items:
                avg_latency = sum(item.get("latency_ms", 0) for item in items) / len(items)
                self.update_rag_chart(current_time, avg_latency)

        # Console (manual unless auto)
        if not self.console_auto.isChecked():
            self.refresh_console()

        # Status pill + Flow
        st = details.get("status", {}) or {}
        state = self.evaluate_overall_state(st)
        title, bg = self._pill(state)
        self.status_pill.setStyleSheet(f"color:#fff; background:{bg}; border-radius:9px;")
        self.status_line.setText(f"Status: {ok_count}/{len(OVERVIEW_ENDPOINTS)} endpoints OK · {title}")

        # Alert indicator
        self.update_alert_indicator(state)
        
        # Alerts
        self.check_alerts(st, state)

        self.render_flow(st)
        self.update_cadence_and_modules(st)
        
        # History + charts
        self.update_history(current_time, st, details.get("gpu_status", {}))
        self.update_charts()

        # default detail pane shows first row detail
        self.show_overview_detail(0, 1)

    # ---------- History ----------
    def update_history(self, current_time, status_data, gpu_data):
        self.history['timestamps'].append(current_time)
        if len(self.history['timestamps']) > 100:
            for key in list(self.history.keys()):
                if key != 'alert_history' and self.history[key]:
                    self.history[key].pop(0)
        
        cadence = status_data.get("cadence", {}) or {}
        for metric in ['guiding', 'traveler', 'symbols']:
            self.history['cadence_metrics'][metric].append(cadence.get(f"{metric}_pct", 0))
        
        if gpu_data and gpu_data.get("ok"):
            self.history['gpu_util'].append(gpu_data.get("util_avg_pct", 0))
        
        memory = status_data.get("memory", {}) or {}
        if memory:
            self.history['memory_usage'].append(memory.get("used_mb", 0))

    # ---------- Charts ----------
    def update_charts(self):
        # Cadence
        for metric, series in self.cadence_series.items():
            series.clear()
            for i, value in enumerate(self.history['cadence_metrics'][metric]):
                if i < len(self.history['timestamps']):
                    series.append(self._to_msecs(self.history['timestamps'][i]), value)
        
        # GPU
        self.gpu_series.clear()
        for i, value in enumerate(self.history['gpu_util']):
            if i < len(self.history['timestamps']):
                self.gpu_series.append(self._to_msecs(self.history['timestamps'][i]), value)
                
        # Metrics
        for metric, series in self.metrics_series.items():
            series.clear()
            if metric == "requests":
                data = self.history['request_counts']
            elif metric == "scrolls":
                status_data = self._overview_details.get("status", {})
                data = [status_data.get("scrolls_loaded", 0)] * len(self.history['timestamps'])
            else:
                data = self.history['memory_usage']
            for i, value in enumerate(data):
                if i < len(self.history['timestamps']):
                    series.append(self._to_msecs(self.history['timestamps'][i]), value)
        
        # Memory
        self.memory_series.clear()
        for i, value in enumerate(self.history['memory_usage']):
            if i < len(self.history['timestamps']):
                self.memory_series.append(self._to_msecs(self.history['timestamps'][i]), value)

    def update_rag_chart(self, current_time, latency):
        self.rag_series.append(self._to_msecs(current_time), latency)
        if self.rag_series.count() > 50:
            self.rag_series.removePoints(0, self.rag_series.count() - 50)
        points = [self.rag_series.at(i).y() for i in range(self.rag_series.count())]
        if points:
            min_val = max(0.0, min(points) * 0.9)
            max_val = max(points) * 1.1
            axis = self.rag_chart.axes(Qt.Vertical)[0]
            axis.setRange(min_val, max_val)

    # ---------- Alerts ----------
    def check_alerts(self, status_data, system_state):
        current_time = time.time()
        cadence = status_data.get("cadence", {}) or {}
        scrolls = status_data.get("scrolls_loaded", 0)
        
        if current_time - self.last_alert_time < self.thresholds['alert_cooldown']:
            return
            
        alerts = []
        
        if cadence.get("guiding_pct", 0) < self.thresholds['bad_guiding']:
            alerts.append(("CRITICAL", f"Guiding cadence critically low: {cadence.get('guiding_pct', 0):.1f}%"))
        elif cadence.get("guiding_pct", 0) < self.thresholds['warn_guiding']:
            alerts.append(("WARNING", f"Guiding cadence low: {cadence.get('guiding_pct', 0):.1f}%"))
            
        if cadence.get("traveler_pct", 0) < self.thresholds['bad_traveler']:
            alerts.append(("CRITICAL", f"Traveler cadence critically low: {cadence.get('traveler_pct', 0):.1f}%"))
        elif cadence.get("traveler_pct", 0) < self.thresholds['warn_traveler']:
            alerts.append(("WARNING", f"Traveler cadence low: {cadence.get('traveler_pct', 0):.1f}%"))
            
        if cadence.get("symbols_pct", 0) < self.thresholds['bad_symbols']:
            alerts.append(("CRITICAL", f"Symbols cadence critically low: {cadence.get('symbols_pct', 0):.1f}%"))
        elif cadence.get("symbols_pct", 0) < self.thresholds['warn_symbols']:
            alerts.append(("WARNING", f"Symbols cadence low: {cadence.get('symbols_pct', 0):.1f}%"))
            
        if scrolls <= self.thresholds['min_scrolls']:
            alerts.append(("WARNING", f"Scrolls loaded ({scrolls}) below minimum threshold"))
            
        if alerts:
            self.last_alert_time = current_time
            for level, message in alerts:
                self.trigger_alert(level, message)

    def trigger_alert(self, level, message):
        alert_record = {
            'time': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            'level': level,
            'message': message
        }
        self.history['alert_history'].append(alert_record)
        if len(self.history['alert_history']) > 100:
            self.history['alert_history'].pop(0)
            
        if self.thresholds['alert_notification']:
            if level == "CRITICAL":
                QMessageBox.critical(self, f"CRITICAL Alert", message)
            else:
                QMessageBox.warning(self, f"Warning Alert", message)
                
        # (Optional) sound hook here
        # ...

        # Memori push
        MEMORI.send_alert(message, level=level)

        self.update_alert_indicator(level.lower())

    def update_alert_indicator(self, state):
        if state in ("bad", "critical"):
            self.alert_indicator.setText("🔔")
            self.alert_indicator.setStyleSheet("color: #dc3545; font-size: 16px;")
            self.alert_indicator.setToolTip("CRITICAL alert active")
        elif state == "warn":
            self.alert_indicator.setText("🔔")
            self.alert_indicator.setStyleSheet("color: #ffc107; font-size: 16px;")
            self.alert_indicator.setToolTip("Warning alert active")
        else:
            self.alert_indicator.setText("🔔")
            self.alert_indicator.setStyleSheet("color: #28a745; font-size: 16px;")
            self.alert_indicator.setToolTip("No active alerts")

    # ---------- Summaries ----------
    def summarize_overview(self, name, p):
        try:
            if name == "health":
                return f"ok={p.get('ok')} version={p.get('version','')}"
            if name == "status":
                up = p.get("uptime_sec", 0)
                scr = p.get("scrolls_loaded", 0)
                reqs = p.get("requests", {})
                cadence = p.get("cadence", {})
                return f"uptime={up}s scrolls={scr} | ask={reqs.get('ask',0)} health={reqs.get('health',0)} | GQ={cadence.get('guiding_pct',0):.1f}% Traveler={cadence.get('traveler_pct',0):.1f}% Syms={cadence.get('symbols_pct',0):.1f}%"
            if name == "heartbeat":
                return f"uptime={p.get('uptime_sec',0)}s scrolls_loaded={p.get('scrolls_loaded',0)}"
            if name == "reindex_status":
                return f"indexing={p.get('indexing')}"
            if name == "index_stats":
                docs = p.get("docs","?")
                last = p.get("last","-")
                return f"docs={docs} last={'ok' if isinstance(last, dict) else last}"
            if name == "safeguards_status":
                t = p.get("temporal",{}).get("state","-")
                s = p.get("symbol",{}).get("state","-")
                c = p.get("conversation",{}).get("state","-")
                return f"temporal={t} symbol={s} conversation={c}"
            if name == "gpu_status":
                if not p or not p.get("ok", False):
                    return f"gpu=unavailable ({p.get('error','no nvml')})"
                return f"gpus={p.get('count',0)} util_avg={p.get('util_avg_pct',0):.0f}% mem={p.get('mem_used_mb',0)}/{p.get('mem_total_mb',0)}MB"
            if name == "memory_status":
                return f"travelers={p.get('travelers',0)} identities={p.get('identities',0)} profiles={p.get('profiles',0)}"
            return jpretty(p)[:200]
        except Exception:
            return jpretty(p)[:200]

    # ---------- Detail ----------
    def show_overview_detail(self, row, col):
        if row < 0 or row >= len(OVERVIEW_ENDPOINTS): return
        name = OVERVIEW_ENDPOINTS[row][0]
        payload = self._overview_details.get(name, {})
        self.detail_json.setText(jpretty(payload))

    # ---------- Flow helpers ----------
    def _flow_nodes(self):
        return {
            "guard":      (20,  40, 140, 48, "Guard"),
            "guide":      (200, 40, 140, 48, "Guide"),
            "retriever":  (380, 40, 160, 48, "Retriever"),
            "synthesis":  (580, 40, 160, 48, "Synthesis"),
            "resonance":  (780, 40, 160, 48, "Resonance"),
            "lucidity":   (980, 40, 140, 48, "Lucidity"),
            "ledger":     (1160,40, 140, 48, "Ledger"),
            "learning":   (1340,40, 160, 48, "Learning"),
        }

    def _status_color(self, state: str):
        if state == "ok":   return QColor("#1fa93a")
        if state == "warn": return QColor("#e6a700")
        return QColor("#c92a2a")

    def _pill(self, state: str):
        if state == "ok":   return ("Healthy",  "#1fa93a")
        if state == "warn": return ("Degraded", "#e6a700")
        return ("Failed",   "#c92a2a")

    def evaluate_overall_state(self, status_payload: dict):
        th = self.thresholds
        gq  = float((status_payload.get("cadence",{}) or {}).get("guiding_pct", 0))
        trav= float((status_payload.get("cadence",{}) or {}).get("traveler_pct", 0))
        syms= float((status_payload.get("cadence",{}) or {}).get("symbols_pct", 0))
        scr = int(status_payload.get("scrolls_loaded", 0))

        if gq < th["bad_guiding"] or trav < th["bad_traveler"] or syms < th["bad_symbols"]:
            return "bad"
        if gq < th["warn_guiding"] or trav < th["warn_traveler"] or syms < th["warn_symbols"] or scr <= th["min_scrolls"]:
            return "warn"
        return "ok"

    def render_flow(self, status_payload: dict):
        self.flow_scene.clear()
        nodes = self._flow_nodes()
        safe = status_payload or {}
        guards = safe.get("safeguards", {}) or {}
        cadence = safe.get("cadence", {}) or {}
        gq = float(cadence.get("guiding_pct", 0))
        trav = float(cadence.get("traveler_pct", 0))
        syms = float(cadence.get("symbols_pct", 0))
        scrolls = int(safe.get("scrolls_loaded", 0))

        th = self.thresholds
        node_state = {
            "guard":     "ok",
            "guide":     "ok",
            "retriever": "ok" if scrolls > th["min_scrolls"] else "warn",
            "synthesis": "ok",
            "resonance": "ok",
            "lucidity":  "ok",
            "ledger":    "ok",
            "learning":  "ok",
        }

        if guards.get("temporal",{}).get("state") == "OPEN": node_state["guide"] = "warn"
        if guards.get("symbol",{}).get("state") == "OPEN":   node_state["resonance"] = "warn"
        if guards.get("conversation",{}).get("state") == "OPEN": node_state["guide"] = "warn"

        if gq   < th["warn_guiding"]:   node_state["lucidity"]  = "warn"
        if trav < th["warn_traveler"]:  node_state["guide"]     = "warn"
        if syms < th["warn_symbols"]:   node_state["resonance"] = "warn"

        font = QFont(); font.setPointSize(10); font.setBold(True)
        pen = QPen(QColor("#333")); pen.setWidth(2)

        for key, (x,y,w,h,label) in nodes.items():
            rect = QGraphicsRectItem(x,y,w,h)
            rect.setPen(pen)
            rect.setBrush(QBrush(self._status_color(node_state.get(key,"ok"))))
            self.flow_scene.addItem(rect)
            text = QGraphicsTextItem(label)
            text.setFont(font); text.setDefaultTextColor(QColor("#fff"))
            text.setPos(x+10, y+12)
            self.flow_scene.addItem(text)

        arrow_pen = QPen(QColor("#888")); arrow_pen.setWidth(2)
        keys = list(nodes.keys())
        for i in range(len(keys)-1):
            k1, k2 = keys[i], keys[i+1]
            x1,y1,w1,h1,_ = (*nodes[k1],)
            x2,y2,w2,h2,_ = (*nodes[k2],)
            self.flow_scene.addLine(x1+w1, y1+h1/2, x2, y2+h2/2, arrow_pen)

        self.flow_scene.setSceneRect(0, 0, 1520, 140)

    def update_cadence_and_modules(self, status_payload: dict):
        cadence = status_payload.get("cadence", {}) or {}
        self.pb_traveler.setValue(int(cadence.get("traveler_pct", 0)))
        self.pb_guiding.setValue(int(cadence.get("guiding_pct", 0)))
        self.pb_symbols.setValue(int(cadence.get("symbols_pct", 0)))

        def dot(lbl: QLabel, state: str):
            color = {"CLOSED": "#1fa93a", "OPEN": "#e6a700"}.get(state, "#999")
            lbl.setStyleSheet(f"color:{color}; font-size:16px;")

        sfg = status_payload.get("safeguards", {}) or {}
        dot(self.dot_temporal, sfg.get("temporal",{}).get("state"))
        dot(self.dot_symbol,   sfg.get("symbol",{}).get("state"))
        dot(self.dot_conv,     sfg.get("conversation",{}).get("state"))

    # ---------- GPU ----------
    def fill_gpu(self, gpu):
        if not gpu or not gpu.get("ok"):
            self.gpu_summary.setText(f"GPU: unavailable — {gpu.get('error','')}")
            self.gpu_table.setRowCount(0)
            return
        self.gpu_summary.setText(
            f"GPU: {gpu.get('count',0)} device(s) · util_avg={gpu.get('util_avg_pct',0):.1f}% · "
            f"mem={gpu.get('mem_used_mb',0)}/{gpu.get('mem_total_mb',0)} MB "
            f"(provider: {gpu.get('provider','nvml')})"
        )
        gpus = gpu.get("gpus", []) or []
        self.gpu_table.setRowCount(len(gpus))
        for r, g in enumerate(gpus):
            def s(k):
                v = g.get(k, "")
                if isinstance(v, float): return f"{v:.1f}"
                return str(v)
            self.gpu_table.setItem(r, 0, QTableWidgetItem(s("index")))
            self.gpu_table.setItem(r, 1, QTableWidgetItem(s("name")))
            self.gpu_table.setItem(r, 2, QTableWidgetItem(s("util_pct")))
            mem = f"{g.get('mem_used_mb',0)}/{g.get('mem_total_mb',0)}"
            self.gpu_table.setItem(r, 3, QTableWidgetItem(mem))
            self.gpu_table.setItem(r, 4, QTableWidgetItem(s("temp_c")))
            self.gpu_table.setItem(r, 5, QTableWidgetItem(s("power_w")))
            
            util = g.get("util_pct", 0)
            if util > 90:
                color = QColor(255, 0, 0)
            elif util > 70:
                color = QColor(255, 165, 0)
            else:
                color = QColor(0, 128, 0)
            for c in range(6):
                self.gpu_table.item(r, c).setBackground(color)

    # ---------- Requests ----------
    def fill_requests(self, trace_json):
        items = trace_json.get("items", [])
        self._all_requests = items
        self.filter_requests(self.req_filter_combo.currentText())
        
        total = len(items)
        success = sum(1 for it in items if it.get("ok"))
        failed = total - success
        avg_latency = sum(it.get("latency_ms", 0) for it in items) / total if total > 0 else 0
        
        self.req_stats_label.setText(
            f"Total: {total} | Success: {success} | Failed: {failed} | Avg Latency: {avg_latency:.1f}ms"
        )
        
    def filter_requests(self, filter_type):
        if not self._all_requests:
            return
        if filter_type == "All":
            items = self._all_requests
        elif filter_type == "Success":
            items = [it for it in self._all_requests if it.get("ok")]
        else:
            items = [it for it in self._all_requests if not it.get("ok")]
            
        self.req_table.setRowCount(len(items))
        for r, it in enumerate(items):
            ts = it.get("ts", 0)
            when = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts/1000)) if ts else "-"
            self.req_table.setItem(r, 0, QTableWidgetItem(when))
            self.req_table.setItem(r, 1, QTableWidgetItem(str(it.get("user","-"))))
            self.req_table.setItem(r, 2, QTableWidgetItem(str(it.get("latency_ms",""))))
            ok_item = QTableWidgetItem("✔" if it.get("ok") else "✖")
            self.req_table.setItem(r, 3, ok_item)
            self.req_table.setItem(r, 4, QTableWidgetItem(it.get("q","")))
            
            color = QColor(220, 255, 220) if it.get("ok") else QColor(255, 220, 220)
            for c in range(5):
                self.req_table.item(r, c).setBackground(color)

    # ---------- RAG ----------
    def fill_rag(self, rag_json):
        items = rag_json.get("items", [])
        self._rag_cache = items
        self.rag_table.setRowCount(len(items))
        self.hits_table.setRowCount(0); self.doc_preview.setPlainText("")
        for r, it in enumerate(items):
            ts = it.get("ts", 0)
            when = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts/1000)) if ts else "-"
            self.rag_table.setItem(r, 0, QTableWidgetItem(when))
            self.rag_table.setItem(r, 1, QTableWidgetItem(str(it.get("latency_ms",""))))
            self.rag_table.setItem(r, 2, QTableWidgetItem(it.get("question","")))
            topk = len(it.get("hits", []) or [])
            self.rag_table.setItem(r, 3, QTableWidgetItem(str(topk)))
            
            latency = it.get("latency_ms", 0)
            if latency > 5000:
                color = QColor(255, 200, 200)
            elif latency > 1000:
                color = QColor(255, 235, 200)
            else:
                color = QColor(220, 255, 220)
            for c in range(4):
                self.rag_table.item(r, c).setBackground(color)

    def on_rag_row_clicked(self, row, col):
        items = getattr(self, "_rag_cache", [])
        if row < 0 or row >= len(items): return
        hits = items[row].get("hits", []) or []
        self.hits_table.setRowCount(len(hits))
        for i, h in enumerate(hits):
            self.hits_table.setItem(i, 0, QTableWidgetItem(str(h.get("id",""))))
            self.hits_table.setItem(i, 1, QTableWidgetItem(str(h.get("title",""))))
            sc = h.get("score", "")
            self.hits_table.setItem(i, 2, QTableWidgetItem(f"{sc:.3f}" if isinstance(sc, (int, float)) else str(sc)))
            
            score = h.get("score", 0) if isinstance(h.get("score"), (int, float)) else 0
            if score > 0.8:
                color = QColor(220, 255, 220)
            elif score > 0.5:
                color = QColor(255, 235, 200)
            else:
                color = QColor(255, 220, 220)
            for c in range(3):
                self.hits_table.item(i, c).setBackground(color)
                
        self.doc_preview.setPlainText("")

    def on_hit_clicked(self, row, col):
        it = self.hits_table.item(row, 0)
        if not it: return
        doc_id = it.text().strip()
        ok, payload = self.request_json("GET", f"/rag/doc?id={doc_id}")
        if ok:
            text = payload.get("text","")
            meta = payload.get("meta",{})
            title = payload.get("title","")
            self.doc_preview.setPlainText(f"# {title}\n\n{jpretty(meta)}\n\n{text}")
        else:
            self.doc_preview.setPlainText(f"Error loading doc {doc_id}")

    # ---------- Console ----------
    def _console_at_bottom(self) -> bool:
        sb = self.console.verticalScrollBar()
        return sb.value() >= sb.maximum() - 3

    def _scroll_console_to_bottom(self):
        self.console.moveCursor(QTextCursor.End)
        self.console.ensureCursorVisible()
        sb = self.console.verticalScrollBar()
        sb.setValue(sb.maximum())

    def refresh_console(self):
        ok, payload = self.request_json("GET", "/logs/tail?lines=500")
        if ok:
            lines = payload.get("lines", [])
            self.console.setPlainText("\n".join(lines))
            # Memori: push last line throttled
            if lines:
                MEMORI.send_console_tail(lines[-1])
        else:
            self.console.setPlainText(f"ERROR: {payload.get('error','?')}")

        # Always stick to bottom after refresh:
        self._scroll_console_to_bottom()

        # If you prefer “only when already at bottom OR auto mode”, use this instead:
        # if self._console_at_bottom() or self.console_auto.isChecked():
        #     self._scroll_console_to_bottom()

    def toggle_console_auto(self, state):
        if state == Qt.Checked:
            self.console_timer.start(2000)
        else:
            self.console_timer.stop()

    # ---------- Tools / Menu ----------
    def kick_reindex_bg(self):
        url = self.root_join("/reindex")
        try:
            r = requests.post(url, params={"background":"true"}, timeout=10)
            if r.ok:
                QMessageBox.information(self, "Reindex", f"Kicked: {jpretty(r.json())}")
            else:
                QMessageBox.warning(self, "Reindex", f"HTTP {r.status_code}: {r.text[:500]}")
        except Exception as e:
            QMessageBox.critical(self, "Reindex", str(e))

    def copy_status_curl(self):
        try:
            import pyperclip
            url = self.root_join("/status")
            pyperclip.copy(f"curl -s {url} | jq .")
            QMessageBox.information(self, "Copied", "curl command copied to clipboard.")
        except Exception:
            QMessageBox.information(self, "curl", f"curl -s {self.root_join('/status')} | jq .")

    def export_requests_csv(self):
        path, _ = QFileDialog.getSaveFileName(self, "Export Requests", "", "CSV Files (*.csv)")
        if not path: return
        try:
            rows = self.req_table.rowCount()
            with open(path, "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(["time","user","latency_ms","ok","question"])
                for r in range(rows):
                    vals = []
                    for c in range(5):
                        it = self.req_table.item(r, c)
                        vals.append(it.text() if it else "")
                    w.writerow(vals)
            QMessageBox.information(self, "Export", "Requests exported.")
        except Exception as e:
            QMessageBox.critical(self, "Export Requests", str(e))

    def export_rag_csv(self):
        path, _ = QFileDialog.getSaveFileName(self, "Export RAG", "", "CSV Files (*.csv)")
        if not path: return
        try:
            rows = self.rag_table.rowCount()
            with open(path, "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(["time","latency_ms","question","topk"])
                for r in range(rows):
                    vals = []
                    for c in range(4):
                        it = self.rag_table.item(r, c)
                        vals.append(it.text() if it else "")
                    w.writerow(vals)
            QMessageBox.information(self, "Export", "RAG exported.")
        except Exception as e:
            QMessageBox.critical(self, "Export RAG", str(e))
            
    def export_history_data(self):
        path, _ = QFileDialog.getSaveFileName(self, "Export History Data", "", "CSV Files (*.csv)")
        if not path: return
        try:
            with open(path, "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(["timestamp", "guiding_pct", "traveler_pct", "symbols_pct", "gpu_util", "memory_mb", "request_count"])
                for i in range(len(self.history['timestamps'])):
                    row = [
                        self.history['timestamps'][i].strftime("%Y-%m-%d %H:%M:%S") if i < len(self.history['timestamps']) else "",
                        self.history['cadence_metrics']['guiding'][i] if i < len(self.history['cadence_metrics']['guiding']) else "",
                        self.history['cadence_metrics']['traveler'][i] if i < len(self.history['cadence_metrics']['traveler']) else "",
                        self.history['cadence_metrics']['symbols'][i] if i < len(self.history['cadence_metrics']['symbols']) else "",
                        self.history['gpu_util'][i] if i < len(self.history['gpu_util']) else "",
                        self.history['memory_usage'][i] if i < len(self.history['memory_usage']) else "",
                        self.history['request_counts'][i] if i < len(self.history['request_counts']) else ""
                    ]
                    w.writerow(row)
            QMessageBox.information(self, "Export", "History data exported.")
        except Exception as e:
            QMessageBox.critical(self, "Export History", str(e))
            
    def clear_history_data(self):
        reply = QMessageBox.question(self, "Clear History", 
                                    "Are you sure you want to clear all history data?",
                                    QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.Yes:
            for key in self.history.keys():
                if key != 'alert_history':
                    self.history[key] = []
            for chart in [self.cadence_chart, self.gpu_chart, self.rag_chart, self.metrics_chart, self.memory_chart]:
                for s in chart.series():
                    chart.removeSeries(s)
                for ax in chart.axes():
                    chart.removeAxis(ax)
            self.init_charts()
            QMessageBox.information(self, "Clear History", "History data cleared.")

    def show_about(self):
        QMessageBox.information(self, "About",
            "Mirror v4 Monitor - Enhanced Edition\n\n"
            "• Overview (health/status/safeguards/index/memory/GPU)\n"
            "• Flow (diagram + status pill + cadence bars + module dots)\n"
            "• Requests (recent /ask traces with filtering)\n"
            "• RAG (retrieved docs per request; preview)\n"
            "• Console (tail /logs/tail)\n"
            "• Analytics (historical charts and metrics)\n\n"
            "Features:\n"
            "• Historical trend charts\n"
            "• Alert system with configurable thresholds\n"
            "• Request filtering and statistics\n"
            "• Export functionality for all data\n"
            "• Dark/light theme support\n\n"
            "Memori: optional event streaming for status/alerts/console tail."
        )

# ----------------- Main -----------------
if __name__ == "__main__":
    app = QApplication(sys.argv)
    w = MirrorMonitor()
    w.show()
    sys.exit(app.exec_())
