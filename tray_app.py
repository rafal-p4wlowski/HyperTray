import logging
import os

from PyQt6.QtCore import QObject, QTimer
from PyQt6.QtGui import QAction, QActionGroup
from PyQt6.QtWidgets import QApplication, QMenu, QMessageBox, QSystemTrayIcon

import app_settings
from battery_estimator import BatteryEstimator, format_duration
from ui_components import DARK_MENU_STYLE, create_qicon, get_battery_color
from version import __version__
from worker import INITIAL_STATE, HeadsetWorker

log = logging.getLogger("hypertray")

SIDE_TONE_VOLUMES = (0, 50, 100, 200)
SHUTDOWN_OPTIONS = (
    (0, "Disabled"), (5, "5 min"), (10, "10 min"), (15, "15 min"), (30, "30 min"),
    (45, "45 min"), (60, "1 hour"), (90, "1.5 hours"), (120, "2 hours"),
)
ESTIMATE_TICK_MS = 60_000


class HeadsetApp(QObject):
    """Tray icon and menu. Talks to the headset only through HeadsetWorker."""

    def __init__(self, protocol, settings):
        super().__init__()
        self.settings = settings
        self.state = dict(INITIAL_STATE)
        self.estimator = BatteryEstimator(os.path.join(app_settings.data_dir(), "battery.json"))

        self.worker = HeadsetWorker(protocol, settings.poll_interval_s)
        self.worker.state_changed.connect(self.sync_state)

        self.tray = QSystemTrayIcon(self)
        self.tray.setIcon(create_qicon("...", get_battery_color(None)))
        self.tray.setToolTip("Looking for headset...")
        self.tray.activated.connect(self.on_tray_activated)
        self.menu = self._build_menu()
        self.tray.setContextMenu(self.menu)
        self.sync_state(self.state)
        self.tray.show()
        self.worker.start()

        # The worker only reports changes; the estimator also needs the passage of time.
        self.estimate_timer = QTimer(self)
        self.estimate_timer.timeout.connect(self._refresh_estimate)
        self.estimate_timer.start(ESTIMATE_TICK_MS)

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
            menu, "Microphone muted", lambda checked: self.worker.submit("muted", checked))
        menu.addSeparator()

        self.side_tone_act = self._toggle_action(
            menu, "Side tone", lambda checked: self.worker.submit("side_tone", checked))
        self.vol_menu, self.vol_group = self._choice_menu(
            menu, "Side tone volume", [(v, str(v)) for v in SIDE_TONE_VOLUMES],
            lambda v: self.worker.submit("side_tone_vol", v))
        menu.addSeparator()

        self.shutdown_menu, self.shutdown_group = self._choice_menu(
            menu, "Automatic shutdown", SHUTDOWN_OPTIONS,
            lambda v: self.worker.submit("auto_shutdown", v))
        menu.addSeparator()

        self._build_settings_menu(menu)
        self._build_advanced_menu(menu)
        menu.addSeparator()

        quit_act = QAction("Quit", menu)
        quit_act.triggered.connect(self.on_quit)
        menu.addAction(quit_act)
        return menu

    def _build_settings_menu(self, parent):
        sub = parent.addMenu("Settings")
        sub.setStyleSheet(DARK_MENU_STYLE)

        self.autostart_act = self._toggle_action(sub, "Start with Windows", self.on_autostart_toggled)
        self.autostart_act.setChecked(app_settings.is_autostart_enabled())

        self.left_click_act = self._toggle_action(
            sub, "Left click toggles mute",
            lambda checked: setattr(self.settings, "left_click_mute", checked))
        self.left_click_act.setChecked(self.settings.left_click_mute)

        _, self.poll_group = self._choice_menu(
            sub, "Battery refresh", app_settings.POLL_OPTIONS, self.on_poll_interval)
        self._check_choice(self.poll_group, self.settings.poll_interval_s)

        sub.addSeparator()
        self._info_action(sub, f"Version {__version__}")

    def _build_advanced_menu(self, parent):
        self.advanced_menu = parent.addMenu("Advanced")
        self.advanced_menu.setStyleSheet(DARK_MENU_STYLE)
        self.sirk_info = self._info_action(self.advanced_menu)
        self.sirk_reset_act = QAction("Reset headset pairing (SIRK)...", self.advanced_menu)
        self.sirk_reset_act.triggered.connect(self.on_reset_sirk)
        self.advanced_menu.addAction(self.sirk_reset_act)

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

    # --- handlers ---
    def on_tray_activated(self, reason):
        if (reason == QSystemTrayIcon.ActivationReason.Trigger
                and self.settings.left_click_mute and self.state["connected"]):
            self.worker.submit("muted", not self.state["muted"])

    def on_autostart_toggled(self, checked):
        try:
            app_settings.set_autostart(checked)
        except OSError as e:
            log.error("Cannot change autostart: %s", e)
        self.autostart_act.setChecked(app_settings.is_autostart_enabled())

    def on_reset_sirk(self):
        answer = QMessageBox.warning(
            None, "Reset headset pairing",
            "This resets the pairing key (SIRK) shared by the headset and the dongle.\n\n"
            "The headset may disconnect from the dongle. If it does not reconnect, pair it "
            "again following the headset manual.\n\n"
            "This feature is experimental. Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if answer == QMessageBox.StandardButton.Yes:
            log.info("User confirmed SIRK reset")
            self.worker.submit("reset_sirk", None)

    def on_poll_interval(self, seconds):
        self.settings.poll_interval_s = seconds
        self.worker.poll_interval_s = seconds

    def on_quit(self):
        self.estimate_timer.stop()
        self.estimator.finish_session()  # keep what this session taught us
        self.worker.stop()
        if not self.worker.wait(3000):
            log.warning("Worker did not stop in time")
        self.tray.hide()
        QApplication.quit()

    # --- state ---
    def sync_state(self, state):
        self.state = state
        connected = state["connected"]
        bat = state["battery"]

        if not state["dongle"]:
            status = "Dongle not found"
        elif not connected:
            status = "Headset off / out of range"
        else:
            status = "Headset connected"
        self.connection_info.setText(status)
        self.battery_info.setText(f"Battery level: {bat}%" if bat is not None else "Battery level: ---")
        self.charging_info.setText(f"Charging status: {state['charging'] or '---'}")

        for act in (self.mute_act, self.side_tone_act):
            act.setEnabled(connected)
        self.vol_menu.setEnabled(connected)
        self.shutdown_menu.setEnabled(connected)

        sirk = state["sirk_reset_required"]
        self.sirk_info.setText("Pairing reset required: " + ("---" if sirk is None else "Yes" if sirk else "No"))
        self.sirk_reset_act.setEnabled(connected)

        self.mute_act.setChecked(bool(state["muted"]))
        self.side_tone_act.setChecked(bool(state["side_tone"]))
        self._check_choice(self.vol_group, state["side_tone_vol"])
        self._check_choice(self.shutdown_group, state["auto_shutdown"])

        self.tray.setIcon(create_qicon(
            str(bat) if bat is not None else "-", get_battery_color(bat),
            charging=state["charging"] == "Charging", muted=connected and bool(state["muted"])))
        self._refresh_estimate()

    def _refresh_estimate(self):
        state = self.state
        bat, charging = state["battery"], state["charging"]
        self.estimator.update(bat, charging, state["connected"])
        left = format_duration(self.estimator.hours_left(bat, charging))
        self.estimate_info.setText(f"Estimated time left: {left}" if left else "")
        self.estimate_info.setVisible(left is not None)

        if bat is None:
            self.tray.setToolTip(self.connection_info.text())
            return
        lines = [f"Battery level: {bat}%"]
        if left:
            lines.append(f"Time left: {left}")
        lines.append(f"Charging status: {charging or '---'}")
        if state["muted"]:
            lines.append("Microphone muted")
        self.tray.setToolTip("\n".join(lines))
