"""Headset panel: battery history and every setting the headset supports.

Opened by a click on the tray icon or "Headset panel..." in the tray menu.
The dongle stays owned by HeadsetWorker: the panel sends changes through
worker.submit() and shows what the headset reports back, so a value the headset
refused snaps back. Volumes are Windows settings (audio_endpoint).
"""
import logging
import time

from PyQt6.QtCore import QPointF, QRectF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import (
    QButtonGroup, QCheckBox, QComboBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QMessageBox,
    QPushButton, QRadioButton, QSizePolicy, QSlider, QTabWidget, QToolTip, QVBoxLayout, QWidget,
)

import app_settings
import audio_endpoint
import headset_logic as hl
import i18n
from battery_estimator import format_duration
from i18n import tr
from version import __version__

log = logging.getLogger("hypertray")

WRITE_DEBOUNCE_MS = 300
AUDIO_POLL_MS = 1000          # Windows volumes can change elsewhere (keyboard, volume wheel)
CHART_TICK_MS = 60_000
CHART_RANGES = ((24, "24 h"), (24 * 7, "7 days"))
SETTING_LABELS = {"muted": "Microphone muted", "side_tone": "Side tone", "side_tone_vol": "Side tone volume",
                  "silent": "Silent mode", "auto_shutdown": "Automatic shutdown"}
STATUS_FIELDS = ("Connection", "Charging state", "Time left", "Cell voltage")
INFO_FIELDS = ("Model", "Colour", "Headset firmware", "Dongle firmware", "Headset ID")

ACCENT = "#2f6fff"
CHARGE_GREEN = "#10c450"
PANEL_STYLE = f"""
QWidget {{ background: #1b1c1f; color: #e0e0e0; font-family: 'Segoe UI', Arial; font-size: 13px; }}
QLabel, QCheckBox, QRadioButton {{ background: transparent; }}
QCheckBox::indicator, QRadioButton::indicator {{
    width: 14px; height: 14px; border: 1px solid #5a5e66; background: #24262b; }}
QCheckBox::indicator {{ border-radius: 3px; }}
QRadioButton::indicator {{ border-radius: 7px; }}
QCheckBox::indicator:checked, QRadioButton::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; }}
QCheckBox::indicator:disabled, QRadioButton::indicator:disabled {{ border-color: #3a3d44; }}
QCheckBox:disabled, QRadioButton:disabled, QLabel:disabled {{ color: #6a6d73; }}
QTabWidget::pane {{ border: 1px solid #2c2e33; border-radius: 6px; top: -1px; }}
QTabBar::tab {{ background: transparent; padding: 8px 18px; color: #a0a0a0; border: none; }}
QTabBar::tab:selected {{ color: {ACCENT}; border-bottom: 2px solid {ACCENT}; }}
QPushButton {{ background: #2a2c31; border: 1px solid #3a3d44; border-radius: 5px; padding: 6px 12px; }}
QPushButton:hover {{ border-color: {ACCENT}; }}
QPushButton:checked {{ background: {ACCENT}; border-color: {ACCENT}; color: white; }}
QPushButton:disabled {{ color: #666; border-color: #2c2e33; }}
QPushButton#danger {{ background: #6b1f24; border-color: #8a2a30; }}
QComboBox {{ background: #24262b; border: 1px solid #3a3d44; border-radius: 4px; padding: 3px 6px; }}
QSlider::groove:horizontal {{ height: 4px; background: #3a3d44; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: {ACCENT}; border-radius: 2px; }}
QSlider::sub-page:horizontal:disabled {{ background: #4a4d55; }}
QSlider::handle:horizontal {{ background: white; width: 14px; margin: -6px 0; border-radius: 7px; }}
QSlider::handle:horizontal:disabled {{ background: #6a6d73; }}
QLabel#title {{ font-size: 18px; font-weight: 600; }}
QLabel#big {{ font-size: 34px; font-weight: 600; }}
QLabel#muted {{ color: #8a8d93; }}
QLabel#error {{ color: #ff6b6b; }}
QFrame#card {{ background: #222428; border-radius: 6px; }}
QFrame#card QWidget {{ background: transparent; }}
"""


# ------------------------------------------------------------------ helpers

def _card(title=None):
    frame = QFrame()
    frame.setObjectName("card")
    box = QVBoxLayout(frame)
    box.setContentsMargins(14, 12, 14, 12)
    if title:
        lbl = QLabel(title)
        lbl.setStyleSheet("font-weight: 600;")
        box.addWidget(lbl)
    return frame, box


def _muted(text=""):
    lbl = QLabel(text)
    lbl.setObjectName("muted")
    lbl.setWordWrap(True)
    return lbl


def _slider(box, rng, fmt):
    """Horizontal slider with its value shown on the right."""
    row = QHBoxLayout()
    slider = QSlider(Qt.Orientation.Horizontal)
    slider.setRange(*rng)
    slider.setPageStep(1 if rng[1] - rng[0] <= 20 else 10)
    label = QLabel(fmt(rng[0]))
    label.setMinimumWidth(44)
    label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    slider.show_value = lambda v: label.setText(fmt(v))
    slider.valueChanged.connect(slider.show_value)
    row.addWidget(slider, 1)
    row.addWidget(label)
    box.addLayout(row)
    return slider


def _signed(v):
    return f"{v:+d}" if v else "0"


def _set_quietly(widget, value):
    """Show a value read from the device without sending it back."""
    widget.blockSignals(True)
    if isinstance(widget, QSlider):
        widget.setValue(value)
        widget.show_value(value)
    else:
        widget.setChecked(value)
    widget.blockSignals(False)


# -------------------------------------------------------------------- chart

class BatteryChart(QWidget):
    """Battery level over the last hours as a line; green where it charged,
    a gap where the headset was off. Hover shows the time and the level."""

    def __init__(self, history, parent=None):
        super().__init__(parent)
        self.history = history
        self.hours = CHART_RANGES[0][0]
        self.setMinimumHeight(170)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMouseTracking(True)
        self._hover_x = None
        self.now = None               # fixed "now" for tests and screenshots

    def set_hours(self, hours):
        self.hours = hours
        self.update()

    def _plot(self):
        return QRectF(38, 8, max(10, self.width() - 50), max(10, self.height() - 32))

    def _span(self):
        end = self.now or time.time()
        return end - self.hours * 3600, end

    def segments(self):
        """[(t0, t1, level, charging)] clipped to the visible span; a level of
        None (headset off) is left out. The last state lasts until now."""
        start, end = self._span()
        points = self.history.since(start)
        result = []
        for i, (t, level, charging) in enumerate(points):
            t_next = points[i + 1][0] if i + 1 < len(points) else end
            t0, t1 = max(t, start), min(t_next, end)
            if level is not None and t1 > t0:
                result.append((t0, t1, level, charging))
        return result

    def _ticks(self, start, end):
        """Time axis labels: every 6 hours over a day, every midnight over a week."""
        lt = time.localtime(start)
        daily = self.hours > 24
        i = 0
        while True:
            # mktime normalises the day/hour overflow and follows DST changes.
            t = time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday + (i if daily else 0),
                             0 if daily else 6 * i, 0, 0, 0, 0, -1))
            if t > end:
                return
            if t >= start:
                yield t, time.strftime("%d.%m" if daily else "%H:%M", time.localtime(t))
            i += 1

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        plot = self._plot()
        start, end = self._span()
        x_of = lambda t: plot.left() + (t - start) / (end - start) * plot.width()
        y_of = lambda level: plot.bottom() - level / 100 * plot.height()

        font = QFont("Segoe UI")
        font.setPixelSize(11)
        p.setFont(font)
        grid, ink = QColor("#2c2e33"), QColor("#8a8d93")
        for level in (0, 50, 100):
            y = y_of(level)
            p.setPen(QPen(grid, 1))
            p.drawLine(QPointF(plot.left(), y), QPointF(plot.right(), y))
            p.setPen(ink)
            p.drawText(QRectF(0, y - 8, plot.left() - 6, 16),
                       Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, f"{level}%")
        for t, label in self._ticks(start, end):
            x = x_of(t)
            p.setPen(QPen(grid, 1))
            p.drawLine(QPointF(x, plot.top()), QPointF(x, plot.bottom()))
            p.setPen(ink)
            p.drawText(QRectF(x - 30, plot.bottom() + 4, 60, 16), Qt.AlignmentFlag.AlignCenter, label)

        segments = self.segments()
        if not segments:
            p.setPen(ink)
            p.drawText(plot, Qt.AlignmentFlag.AlignCenter, tr("No battery readings in this period yet."))
            p.end()
            return

        # One path per run of connected segments with the same charging state.
        runs, last = [], None
        for t0, t1, level, charging in segments:
            joined = last is not None and abs(last[1] - t0) < 1 and last[3] == charging
            if not joined:
                runs.append((charging, QPainterPath(QPointF(x_of(t0), y_of(level)))))
            path = runs[-1][1]
            path.lineTo(x_of(t0), y_of(level))
            path.lineTo(x_of(t1), y_of(level))
            last = (t0, t1, level, charging)
        for charging, path in runs:
            p.setPen(QPen(QColor(CHARGE_GREEN if charging else ACCENT), 2, Qt.PenStyle.SolidLine,
                          Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            p.drawPath(path)

        if self._hover_x is not None and plot.left() <= self._hover_x <= plot.right():
            p.setPen(QPen(QColor("#5a5e66"), 1))
            p.drawLine(QPointF(self._hover_x, plot.top()), QPointF(self._hover_x, plot.bottom()))
        p.end()

    def reading_at(self, x):
        """(time, level, charging) under the x coordinate, or None."""
        plot = self._plot()
        start, end = self._span()
        t = start + (x - plot.left()) / plot.width() * (end - start)
        for t0, t1, level, charging in self.segments():
            if t0 <= t <= t1:
                return t, level, charging
        return None

    def mouseMoveEvent(self, event):
        self._hover_x = event.position().x()
        reading = self.reading_at(self._hover_x)
        if reading:
            t, level, charging = reading
            when = time.strftime("%H:%M" if self.hours <= 24 else "%d.%m %H:%M", time.localtime(t))
            text = f"{when} · {level}%" + (f" · {tr('Charging')}" if charging else "")
            QToolTip.showText(event.globalPosition().toPoint(), text, self)
        else:
            QToolTip.hideText()
        self.update()

    def leaveEvent(self, event):
        self._hover_x = None
        self.update()


# -------------------------------------------------------------------- panel

class HeadsetPanel(QWidget):
    """Freed when closed; the tray app creates a new one on demand."""

    closed = pyqtSignal()

    def __init__(self, app):
        super().__init__(None, Qt.WindowType.Window)
        self.app = app                       # HeadsetApp: state, worker, settings, history
        self.state = dict(app.state)
        self.endpoints = {}                  # audio_endpoint.RENDER/CAPTURE -> EndpointVolume
        self._requested = {}                 # setting -> value sent and not confirmed yet
        self.setWindowTitle(tr("HyperTray - Headset"))
        self.setStyleSheet(PANEL_STYLE)
        self.resize(760, 600)

        self._side_tone_timer = QTimer(self, singleShot=True, interval=WRITE_DEBOUNCE_MS)
        self._side_tone_timer.timeout.connect(self._write_side_tone_vol)
        self._audio_timer = QTimer(self, interval=AUDIO_POLL_MS)
        self._audio_timer.timeout.connect(self._refresh_audio)
        self._chart_timer = QTimer(self, interval=CHART_TICK_MS)
        self._chart_timer.timeout.connect(lambda: self.chart.update())

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 10)
        root.addLayout(self._build_header())
        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_status_tab(), tr("Status"))
        self.tabs.addTab(self._build_sound_tab(), tr("Sound"))
        self.tabs.addTab(self._build_headset_tab(), tr("Headset"))
        self.tabs.addTab(self._build_settings_tab(), tr("Settings"))
        root.addWidget(self.tabs, 1)
        self.status = _muted()
        self.status.setWordWrap(False)
        root.addWidget(self.status)

        app.worker.busy_changed.connect(self._on_busy)
        self.update_state(self.state)

    # ------------------------------------------------------------- lifecycle
    def show_panel(self):
        self.sync_app_settings()
        self._find_endpoints()
        if self.isMinimized():
            self.showNormal()
        self.show()
        self.raise_()
        self.activateWindow()
        self._audio_timer.start()
        self._chart_timer.start()

    def adopt(self, old):
        """Take over the window state of a panel being replaced (language switch)."""
        self.restoreGeometry(old.saveGeometry())
        self.tabs.setCurrentIndex(old.tabs.currentIndex())
        self._set_chart_range(old.chart.hours)

    def closeEvent(self, event):
        self.shutdown()
        event.accept()
        self.closed.emit()
        self.deleteLater()

    def shutdown(self):
        """Send a change still waiting for its debounce, stop the timers, let go of Windows audio."""
        self._flush_pending()
        self._audio_timer.stop()
        self._chart_timer.stop()
        try:
            self.app.worker.busy_changed.disconnect(self._on_busy)
        except TypeError:
            pass
        for endpoint in self.endpoints.values():
            endpoint.close()
        self.endpoints = {}

    def _flush_pending(self):
        if self._side_tone_timer.isActive():
            self._side_tone_timer.stop()
            self._write_side_tone_vol()

    def _submit(self, setting, value):
        if self.state.get(setting) == value:
            self._requested.pop(setting, None)
            return
        self._requested[setting] = value
        self.app.worker.submit(setting, value)

    def _on_busy(self, busy):
        self.busy_label.setText(tr("Saving...") if busy else "")
        if busy or not self._requested:
            return
        refused = [name for name, value in self._requested.items() if self.state.get(name) != value]
        self._requested.clear()
        self.update_state(self.state)           # a refused value snaps back
        if refused:
            names = ", ".join(tr(SETTING_LABELS[name]) for name in refused)
            self.status.setText(tr("The headset did not take the change ({}). Is it on?").format(names))
        else:
            self.status.setText(tr("Saved in the headset at {}").format(time.strftime("%H:%M:%S")))

    # ---------------------------------------------------------------- header
    def _build_header(self):
        row = QHBoxLayout()
        col = QVBoxLayout()
        self.title = QLabel("HyperX Cloud III Wireless")
        self.title.setObjectName("title")
        self.subtitle = _muted()
        self.subtitle.setWordWrap(False)
        col.addWidget(self.title)
        col.addWidget(self.subtitle)
        row.addLayout(col)
        row.addStretch(1)
        self.busy_label = _muted()
        row.addWidget(self.busy_label)
        reload_btn = QPushButton(tr("Reload"))
        reload_btn.setToolTip(tr("Read every setting from the headset again"))
        reload_btn.clicked.connect(self._reload)
        row.addWidget(reload_btn)
        return row

    def _reload(self):
        self.app.worker.request_refresh()
        self._find_endpoints()
        self.status.setText(tr("Reading the headset..."))

    # ================================================================ STATUS
    def _build_status_tab(self):
        page = QWidget()
        box = QVBoxLayout(page)

        card, cbox = _card(tr("Battery"))
        row = QHBoxLayout()
        self.battery_big = QLabel("---")
        self.battery_big.setObjectName("big")
        row.addWidget(self.battery_big)
        row.addSpacing(18)
        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        self.status_values = {}
        for i, key in enumerate(STATUS_FIELDS):
            grid.addWidget(_muted(tr(key)), i, 0)
            value = QLabel("---")
            grid.addWidget(value, i, 1)
            self.status_values[key] = value
        row.addLayout(grid)
        row.addStretch(1)
        cbox.addLayout(row)
        box.addWidget(card)

        card, cbox = _card(tr("Battery history"))
        top = QHBoxLayout()
        top.addWidget(_muted(tr("Green: charging. A gap: the headset was off.")), 1)
        self.range_group = QButtonGroup(page)
        for hours, label in CHART_RANGES:
            b = QPushButton(tr(label))
            b.setCheckable(True)
            self.range_group.addButton(b, hours)
            top.addWidget(b)
        self.range_group.idClicked.connect(self._set_chart_range)
        cbox.addLayout(top)
        self.chart = BatteryChart(self.app.history)
        cbox.addWidget(self.chart, 1)
        box.addWidget(card, 1)
        self._set_chart_range(CHART_RANGES[0][0])
        return page

    def _set_chart_range(self, hours):
        self.range_group.button(hours).setChecked(True)
        self.chart.set_hours(hours)

    # ================================================================= SOUND
    def _build_sound_tab(self):
        page = QWidget()
        grid = QGridLayout(page)

        card, cbox = _card(tr("Microphone"))
        self.mute_check = QCheckBox(tr("Microphone muted"))
        self.mute_check.toggled.connect(lambda on: self._submit("muted", on))
        cbox.addWidget(self.mute_check)
        self.mic_detached = QLabel(tr("The microphone is unplugged."))
        self.mic_detached.setObjectName("error")
        cbox.addWidget(self.mic_detached)
        cbox.addSpacing(6)
        cbox.addWidget(QLabel(tr("Microphone volume (Windows)")))
        self.mic_slider = _slider(cbox, (0, 100), lambda v: f"{v}%")
        self.mic_slider.valueChanged.connect(lambda v: self._set_windows_volume(audio_endpoint.CAPTURE, v))
        cbox.addStretch(1)
        grid.addWidget(card, 0, 0)

        card, cbox = _card(tr("Side tone"))
        self.side_tone_check = QCheckBox(tr("Hear my own voice in the headphones"))
        self.side_tone_check.toggled.connect(self._on_side_tone)
        cbox.addWidget(self.side_tone_check)
        cbox.addSpacing(6)
        cbox.addWidget(QLabel(tr("Side tone volume")))
        lo, hi = hl.SIDE_TONE_VOL_RANGE
        self.side_tone_slider = _slider(cbox, (lo, hi), _signed)
        self.side_tone_slider.valueChanged.connect(lambda _v: self._side_tone_timer.start())
        cbox.addWidget(_muted(tr("Holding the mute button on the headset also switches the side tone.")))
        cbox.addStretch(1)
        grid.addWidget(card, 0, 1)

        card, cbox = _card(tr("Headphones"))
        cbox.addWidget(QLabel(tr("Headphone volume (Windows)")))
        self.speaker_slider = _slider(cbox, (0, 100), lambda v: f"{v}%")
        self.speaker_slider.valueChanged.connect(lambda v: self._set_windows_volume(audio_endpoint.RENDER, v))
        cbox.addSpacing(6)
        self.silent_check = QCheckBox(tr("Silent mode (no sound in the headphones)"))
        self.silent_check.toggled.connect(lambda on: self._submit("silent", on))
        cbox.addWidget(self.silent_check)
        cbox.addWidget(_muted(tr("Silences the headset itself; Windows still plays to it.")))
        cbox.addStretch(1)
        grid.addWidget(card, 1, 0)

        card, cbox = _card(tr("About the volumes"))
        cbox.addWidget(_muted(tr("The headset has no volume or microphone gain setting of its own. Like NGENUITY, "
                                 "the panel sets the volume of the headset's Windows audio devices.")))
        self.audio_missing = QLabel(tr("The headset is not among the active Windows audio devices."))
        self.audio_missing.setObjectName("error")
        self.audio_missing.setWordWrap(True)
        cbox.addWidget(self.audio_missing)
        cbox.addStretch(1)
        grid.addWidget(card, 1, 1)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        grid.setRowStretch(2, 1)
        return page

    def _on_side_tone(self, on):
        self.side_tone_slider.setEnabled(on and bool(self.state["connected"]))
        self._submit("side_tone", on)

    def _write_side_tone_vol(self):
        self._submit("side_tone_vol", self.side_tone_slider.value())

    # Windows audio
    def _find_endpoints(self):
        for endpoint in self.endpoints.values():
            endpoint.close()
        self.endpoints = audio_endpoint.find_endpoints()
        self._refresh_audio()

    def _refresh_audio(self):
        for flow, slider in ((audio_endpoint.CAPTURE, self.mic_slider), (audio_endpoint.RENDER, self.speaker_slider)):
            endpoint = self.endpoints.get(flow)
            value = None
            if endpoint is not None:
                try:
                    value = endpoint.volume()
                except OSError:
                    self.endpoints.pop(flow).close()   # device went away
            slider.setEnabled(value is not None)
            if value is not None and not slider.isSliderDown():
                _set_quietly(slider, value)
        self.audio_missing.setVisible(not self.endpoints)

    def _set_windows_volume(self, flow, percent):
        endpoint = self.endpoints.get(flow)
        if endpoint is None:
            return
        try:
            if endpoint.volume() != percent:
                endpoint.set_volume(percent)
        except OSError as e:
            log.warning("Cannot set the Windows volume: %s", e)
            self._find_endpoints()

    # =============================================================== HEADSET
    def _build_headset_tab(self):
        page = QWidget()
        grid = QGridLayout(page)

        card, cbox = _card(tr("Automatic shutdown"))
        cbox.addWidget(_muted(tr("Switch the headset off when it has been idle for:")))
        self.shutdown_group = QButtonGroup(page)
        for minutes in hl.AUTO_SHUTDOWN_MINUTES:
            r = QRadioButton(tr("{} min").format(minutes) if minutes else tr("Never"))
            self.shutdown_group.addButton(r, minutes)
            cbox.addWidget(r)
        self.shutdown_group.idClicked.connect(lambda minutes: self._submit("auto_shutdown", minutes))
        cbox.addStretch(1)
        self.shutdown_card = card
        grid.addWidget(card, 0, 0)

        card, cbox = _card(tr("Device"))
        info = QGridLayout()
        info.setHorizontalSpacing(14)
        self.info_values = {}
        for i, key in enumerate(INFO_FIELDS):
            info.addWidget(_muted(tr(key)), i, 0)
            value = QLabel("---")
            value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            info.addWidget(value, i, 1)
            self.info_values[key] = value
        info.setColumnStretch(1, 1)
        cbox.addLayout(info)
        cbox.addStretch(1)
        grid.addWidget(card, 0, 1)

        card, cbox = _card(tr("Pairing"))
        cbox.addWidget(_muted(tr("If the headset no longer pairs with the dongle, the pairing key (SIRK) "
                                 "shared by both can be reset. Afterwards the headset may have to be paired "
                                 "again following its manual.")))
        self.sirk_label = QLabel("")
        cbox.addWidget(self.sirk_label)
        row = QHBoxLayout()
        self.sirk_button = QPushButton(tr("Reset pairing (SIRK)..."))
        self.sirk_button.setObjectName("danger")
        self.sirk_button.clicked.connect(self._reset_sirk)
        row.addWidget(self.sirk_button)
        row.addStretch(1)
        cbox.addLayout(row)
        grid.addWidget(card, 1, 0, 1, 2)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        grid.setRowStretch(2, 1)
        return page

    def _reset_sirk(self):
        answer = QMessageBox.warning(
            self, tr("Reset headset pairing"),
            tr("This resets the pairing key (SIRK) shared by the headset and the dongle.\n\n"
               "The headset may disconnect from the dongle. If it does not reconnect, pair it "
               "again following the headset manual.\n\nThis feature is experimental. Continue?"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if answer == QMessageBox.StandardButton.Yes:
            log.info("User confirmed SIRK reset")
            self.app.worker.submit("reset_sirk", None)

    # ============================================================== SETTINGS
    def _build_settings_tab(self):
        page = QWidget()
        row = QHBoxLayout(page)
        card, abox = _card("HyperTray")
        self.autostart_check = QCheckBox(tr("Start with Windows"))
        self.autostart_check.toggled.connect(lambda c: self._app_call(self.app.on_autostart_toggled, c))
        abox.addWidget(self.autostart_check)
        abox.addWidget(_muted(tr("A click on the tray icon opens this panel; "
                                 "the microphone can be muted from its menu.")))
        grid = QGridLayout()
        self.poll_combo = QComboBox()
        for seconds, label in app_settings.POLL_OPTIONS:
            self.poll_combo.addItem(label, seconds)
        self.poll_combo.activated.connect(
            lambda: self._app_call(self.app.on_poll_interval, self.poll_combo.currentData()))
        grid.addWidget(QLabel(tr("Battery refresh")), 0, 0)
        grid.addWidget(self.poll_combo, 0, 1)
        self.language_combo = QComboBox()
        for code, label in i18n.LANGUAGES:
            self.language_combo.addItem(tr(label) if code == i18n.AUTO else label, code)
        self.language_combo.activated.connect(self._on_language)
        grid.addWidget(QLabel(tr("Language")), 1, 0)
        grid.addWidget(self.language_combo, 1, 1)
        grid.setColumnStretch(2, 1)
        abox.addLayout(grid)
        abox.addWidget(_muted(tr("Mute, charging and power changes are shown at once; "
                                 "the refresh only follows the battery level.")))
        abox.addStretch(1)
        abox.addWidget(_muted(tr("Version {}").format(__version__)))
        row.addWidget(card, 1)
        self._syncing_app = False
        return page

    def _on_language(self):
        code = self.language_combo.currentData()
        if not self._syncing_app and code != self.app.settings.language:
            # Rebuilds this window, so let the combo box signal finish first.
            QTimer.singleShot(0, lambda: self.app.on_language(code))

    def _app_call(self, handler, value):
        if not self._syncing_app:
            handler(value)
            self.app.sync_menu_settings()

    def sync_app_settings(self):
        """Reflect the tray app settings (they can change from the tray menu too)."""
        self._syncing_app = True
        try:
            self.autostart_check.setChecked(app_settings.is_autostart_enabled())
            for combo, value in ((self.poll_combo, self.app.settings.poll_interval_s),
                                 (self.language_combo, self.app.settings.language)):
                combo.setCurrentIndex(combo.findData(value))
        finally:
            self._syncing_app = False

    # ================================================================= STATE
    def update_state(self, state):
        """Called by the tray app with every state change from the worker."""
        self.state = dict(state)
        connected = bool(state["connected"])
        bat, charging = state["battery"], state["charging"]

        if not state["dongle"]:
            connection = tr("Dongle not found")
        elif not connected:
            connection = tr("Headset off / out of range")
        else:
            connection = tr("Connected")
        if state["model"]:
            self.title.setText(state["model"])
        parts = [connection] + ([tr("battery {}%").format(bat)] if bat is not None else [])
        if charging in ("Charging", "Fully charged"):
            parts.append(tr(charging).lower())
        self.subtitle.setText(" · ".join(parts))

        # Status
        self.battery_big.setText(f"{bat}%" if bat is not None else "---")
        left = format_duration(self.app.estimator.hours_left(bat, charging))
        volts = state["voltage_mv"]
        for key, text in (("Connection", connection), ("Charging state", tr(charging) if charging else "---"),
                          ("Time left", left or "---"),
                          ("Cell voltage", f"{volts / 1000:.2f} V" if volts else "---")):
            self.status_values[key].setText(text)
        self.chart.update()

        # Sound
        for widget, key in ((self.mute_check, "muted"), (self.side_tone_check, "side_tone"),
                            (self.silent_check, "silent")):
            widget.setEnabled(connected)
            if key not in self._requested:
                _set_quietly(widget, bool(state[key]))
        self.mic_detached.setVisible(connected and state["mic_connected"] is False)
        self.side_tone_slider.setEnabled(connected and bool(state["side_tone"]))
        vol = state["side_tone_vol"]
        if (vol is not None and "side_tone_vol" not in self._requested and not self._side_tone_timer.isActive()
                and not self.side_tone_slider.isSliderDown()):
            _set_quietly(self.side_tone_slider, vol)

        # Headset
        self.shutdown_card.setEnabled(connected)
        minutes = state["auto_shutdown"]
        if "auto_shutdown" not in self._requested:
            button = self.shutdown_group.button(minutes) if minutes is not None else None
            self.shutdown_group.setExclusive(False)
            for b in self.shutdown_group.buttons():
                b.setChecked(b is button)
            self.shutdown_group.setExclusive(True)
        pid = state["headset_pid"]
        for key, text in (("Model", state["model"]), ("Colour", tr(state["color"]) if state["color"] else None),
                          ("Headset firmware", state["headset_firmware"]),
                          ("Dongle firmware", state["dongle_firmware"]),
                          ("Headset ID", f"{hl.VENDOR_ID:04X}:{pid:04X}" if pid else None)):
            self.info_values[key].setText(text or "---")
        sirk = state["sirk_reset_required"]
        self.sirk_label.setText(tr("Pairing reset required: {}").format(
            "---" if sirk is None else tr("Yes") if sirk else tr("No")))
        self.sirk_button.setEnabled(connected)
