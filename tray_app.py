import logging

from PyQt6.QtCore import QObject
from PyQt6.QtGui import QAction, QActionGroup
from PyQt6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

import app_settings
from ui_components import DARK_MENU_STYLE, create_qicon, get_battery_color
from version import __version__
from worker import INITIAL_STATE, HeadsetWorker

log = logging.getLogger("hyperheadset")

SIDE_TONE_VOLUMES = (0, 50, 100, 200)
SHUTDOWN_OPTIONS = (
    (0, "Disabled"), (5, "5 min"), (10, "10 min"), (15, "15 min"), (30, "30 min"),
    (45, "45 min"), (60, "1 hour"), (90, "1.5 hours"), (120, "2 hours"),
)
POLL_OPTIONS = ((10, "10 s"), (30, "30 s"), (60, "1 min"))


class HeadsetApp(QObject):
    """Tray icon and menu. Talks to the headset only through HeadsetWorker."""

    def __init__(self, protocol, settings):
        super().__init__()
        self.settings = settings
        self.state = dict(INITIAL_STATE)

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

        _, self.poll_group = self._choice_menu(sub, "Battery refresh", POLL_OPTIONS, self.on_poll_interval)
        self._check_choice(self.poll_group, self.settings.poll_interval_s)

        sub.addSeparator()
        self._info_action(sub, f"Version {__version__}")

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
        # Exclusive groups can't be fully unchecked, so relax it for unknown values.
        group.setExclusive(False)
        for act in group.actions():
            act.setChecked(act.data() == value)
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

    def on_poll_interval(self, seconds):
        self.settings.poll_interval_s = seconds
        self.worker.poll_interval_s = seconds

    def on_quit(self):
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

        self.mute_act.setChecked(bool(state["muted"]))
        self.side_tone_act.setChecked(bool(state["side_tone"]))
        self._check_choice(self.vol_group, state["side_tone_vol"])
        self._check_choice(self.shutdown_group, state["auto_shutdown"])

        self.tray.setIcon(create_qicon(str(bat) if bat is not None else "-", get_battery_color(bat)))
        if bat is not None:
            self.tray.setToolTip(f"Battery level: {bat}%\nCharging status: {state['charging'] or '---'}")
        else:
            self.tray.setToolTip(status)
