import ctypes
import logging
import os
import sys

from PyQt6.QtCore import QObject, QTimer
from PyQt6.QtGui import QAction, QActionGroup
from PyQt6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

import app_settings
import i18n
from battery_estimator import BatteryEstimator, BatteryHistory, format_duration
from i18n import tr
from ui_components import DARK_MENU_STYLE, create_tray_icon, taskbar_is_light
from version import __version__
from worker import INITIAL_STATE, HeadsetWorker

log = logging.getLogger("hypertray")

ESTIMATE_TICK_MS = 60_000
THEME_CHECK_MS = 2000        # how often to check whether the taskbar switched light/dark
TRIM_DELAY_MS = 5000         # after the start and after the panel was closed


def release_unused_memory():
    """Hand the pages not used lately back to Windows. A tray app sits idle
    almost all the time; the pages come back cheaply when they are needed."""
    if sys.platform == "win32":
        k32 = ctypes.windll.kernel32
        k32.GetCurrentProcess.restype = ctypes.c_void_p
        k32.K32EmptyWorkingSet.argtypes = [ctypes.c_void_p]
        k32.K32EmptyWorkingSet(k32.GetCurrentProcess())


class HeadsetApp(QObject):
    """Tray icon and menu. Talks to the headset only through HeadsetWorker."""

    def __init__(self, protocol, settings):
        super().__init__()
        self.settings = settings
        self.state = dict(INITIAL_STATE)
        self.panel = None            # HeadsetPanel, created on first use
        i18n.set_language(settings.language)
        self.estimator = BatteryEstimator(os.path.join(app_settings.data_dir(), "battery.json"))
        self.history = BatteryHistory(os.path.join(app_settings.data_dir(), "battery_history.json"))

        self.worker = HeadsetWorker(protocol, settings.poll_interval_s)
        self.worker.state_changed.connect(self.sync_state)

        self.tray = QSystemTrayIcon(self)
        self._light_taskbar = taskbar_is_light()
        self.tray.setToolTip(tr("Looking for headset..."))
        self.tray.activated.connect(self.on_tray_activated)
        self.menu = self._build_menu()
        self.tray.setContextMenu(self.menu)
        self.sync_state(self.state)
        self.tray.show()
        self.worker.start()
        QTimer.singleShot(TRIM_DELAY_MS, release_unused_memory)

        # The worker only reports changes; the estimator also needs the passage of time.
        self.estimate_timer = QTimer(self)
        self.estimate_timer.timeout.connect(self._refresh_estimate)
        self.estimate_timer.start(ESTIMATE_TICK_MS)

        # The ring and glyph follow the taskbar colour, which can change at any time.
        self.theme_timer = QTimer(self)
        self.theme_timer.timeout.connect(self._check_taskbar_theme)
        self.theme_timer.start(THEME_CHECK_MS)

    # --- menu construction ---
    @staticmethod
    def _info_action(menu, text=""):
        act = QAction(text, menu)
        act.setEnabled(False)
        menu.addAction(act)
        return act

    @staticmethod
    def _toggle_action(menu, text, handler):
        act = QAction(text, menu)
        act.setCheckable(True)
        act.triggered.connect(handler)
        menu.addAction(act)
        return act

    def _build_menu(self):
        menu = QMenu()
        menu.setStyleSheet(DARK_MENU_STYLE)

        self.connection_info = self._info_action(menu)
        self.battery_info = self._info_action(menu)
        self.estimate_info = self._info_action(menu)
        self.charging_info = self._info_action(menu)
        menu.addSeparator()

        self.mute_act = self._toggle_action(
            menu, tr("Microphone muted"), lambda checked: self.worker.submit("muted", checked))
        panel_act = QAction(tr("Headset panel..."), menu)
        panel_act.triggered.connect(self.show_panel)
        font = panel_act.font()
        font.setBold(True)
        panel_act.setFont(font)
        menu.addAction(panel_act)
        menu.setDefaultAction(panel_act)
        menu.addSeparator()

        self._build_settings_menu(menu)
        menu.addSeparator()

        quit_act = QAction(tr("Quit"), menu)
        quit_act.triggered.connect(self.on_quit)
        menu.addAction(quit_act)
        return menu

    def _build_settings_menu(self, parent):
        sub = parent.addMenu(tr("Settings"))
        sub.setStyleSheet(DARK_MENU_STYLE)

        self.autostart_act = self._toggle_action(sub, tr("Start with Windows"), self.on_autostart_toggled)
        self.autostart_act.setChecked(app_settings.is_autostart_enabled())

        _, self.poll_group = self._choice_menu(
            sub, tr("Battery refresh"), app_settings.POLL_OPTIONS, self.on_poll_interval)
        self._check_choice(self.poll_group, self.settings.poll_interval_s)

        languages = [(code, tr(label) if code == i18n.AUTO else label) for code, label in i18n.LANGUAGES]
        _, self.language_group = self._choice_menu(sub, tr("Language"), languages, self.on_language)
        self._check_choice(self.language_group, self.settings.language)

        sub.addSeparator()
        self._info_action(sub, tr("Version {}").format(__version__))

    def _choice_menu(self, parent, title, options, handler):
        sub = parent.addMenu(title)
        sub.setStyleSheet(DARK_MENU_STYLE)
        group = QActionGroup(sub)
        group.setExclusive(True)
        for value, label in options:
            act = QAction(label, group)
            act.setCheckable(True)
            act.setData(value)
            sub.addAction(act)
        group.triggered.connect(lambda act: handler(act.data()))
        return sub, group

    @staticmethod
    def _check_choice(group, value):
        match = next((act for act in group.actions() if act.data() == value), None)
        if match is not None:
            # Checking inside the exclusive group lets Qt uncheck the previous
            # choice and keeps its notion of the current action up to date.
            match.setChecked(True)
            return
        # Unknown value: exclusive groups can't be fully unchecked, so relax it briefly.
        group.setExclusive(False)
        for act in group.actions():
            act.setChecked(False)
        group.setExclusive(True)

    # --- tray clicks and the panel ---
    def on_tray_activated(self, reason):
        if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick):
            self.show_panel()

    def _new_panel(self):
        from panel import HeadsetPanel      # loaded on first use, keeps the start light
        panel = HeadsetPanel(self)
        panel.closed.connect(lambda: self._panel_closed(panel))
        return panel

    def _panel_closed(self, panel):
        if self.panel is panel:
            self.panel = None
            QTimer.singleShot(TRIM_DELAY_MS, release_unused_memory)

    def show_panel(self):
        if self.panel is None:
            self.panel = self._new_panel()
        self.panel.show_panel()

    def on_language(self, code):
        """Switch the UI language: rebuild the menu and the panel in place."""
        self.settings.language = code
        i18n.set_language(code)
        old_menu = self.menu
        self.menu = self._build_menu()
        self.tray.setContextMenu(self.menu)
        old_menu.deleteLater()
        self.sync_state(self.state)
        if self.panel is not None:
            old, visible = self.panel, self.panel.isVisible()
            self.panel = self._new_panel()
            self.panel.adopt(old)
            old.shutdown()
            old.hide()
            old.deleteLater()
            if visible:
                self.panel.show_panel()

    def sync_menu_settings(self):
        """Tray menu checks after a setting changed in the panel."""
        self.autostart_act.setChecked(app_settings.is_autostart_enabled())
        self._check_choice(self.poll_group, self.settings.poll_interval_s)
        self._check_choice(self.language_group, self.settings.language)

    def _sync_panel_settings(self):
        if self.panel is not None:
            self.panel.sync_app_settings()

    # --- settings ---
    def on_autostart_toggled(self, checked):
        try:
            app_settings.set_autostart(checked)
        except OSError as e:
            log.error("Cannot change autostart: %s", e)
        self.autostart_act.setChecked(app_settings.is_autostart_enabled())
        self._sync_panel_settings()

    def on_poll_interval(self, seconds):
        self.settings.poll_interval_s = seconds
        self.worker.poll_interval_s = seconds
        self._sync_panel_settings()

    def on_quit(self):
        if self.panel is not None:
            self.panel.close()              # sends a change still waiting for its debounce
        self.estimate_timer.stop()
        self.estimator.finish_session()     # keep what this session taught us
        self.worker.stop()
        if not self.worker.wait(5000):
            log.warning("Worker did not stop in time")
        self.tray.hide()
        QApplication.quit()

    # --- state ---
    def _status_text(self):
        if not self.state["dongle"]:
            return tr("Dongle not found")
        if not self.state["connected"]:
            return tr("Headset off / out of range")
        return tr("Headset connected")

    def sync_state(self, state):
        self.state = state
        connected = state["connected"]
        bat, charging = state["battery"], state["charging"]

        self.connection_info.setText(self._status_text())
        self.battery_info.setText(tr("Battery level: {}").format(f"{bat}%" if bat is not None else "---"))
        self.charging_info.setText(tr("Charging status: {}").format(tr(charging) if charging else "---"))
        self.mute_act.setEnabled(connected)
        self.mute_act.setChecked(bool(state["muted"]))

        self._update_icon()
        self._refresh_estimate()
        if self.panel is not None:
            self.panel.update_state(state)

    def _update_icon(self):
        state = self.state
        connected = state["connected"]
        self.tray.setIcon(create_tray_icon(
            state["battery"], charging=state["charging"] == "Charging", active=connected,
            light_taskbar=self._light_taskbar, muted=connected and bool(state["muted"])))

    def _check_taskbar_theme(self):
        light = taskbar_is_light()
        if light != self._light_taskbar:
            self._light_taskbar = light
            self._update_icon()

    def _refresh_estimate(self):
        state = self.state
        bat, charging = state["battery"], state["charging"]
        self.estimator.update(bat, charging, state["connected"])
        self.history.record(bat, charging, state["connected"])   # repeats a steady level now and then
        left = format_duration(self.estimator.hours_left(bat, charging))
        self.estimate_info.setText(tr("Estimated time left: {}").format(left) if left else "")
        self.estimate_info.setVisible(left is not None)

        if bat is None:
            self.tray.setToolTip(self.connection_info.text())
            return
        lines = [tr("Battery level: {}").format(f"{bat}%")]
        if left:
            lines.append(tr("Time left: {}").format(left))
        lines.append(tr("Charging status: {}").format(tr(charging) if charging else "---"))
        if state["muted"]:
            lines.append(tr("Microphone muted"))
        self.tray.setToolTip("\n".join(lines))
