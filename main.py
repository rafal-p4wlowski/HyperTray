import logging
import os
import queue
import signal
import sys
import threading
import time
from logging.handlers import RotatingFileHandler

from PyQt6.QtCore import QThread, QTimer, pyqtSignal
from PyQt6.QtGui import QAction, QActionGroup
from PyQt6.QtWidgets import QApplication, QMenu, QMessageBox, QSystemTrayIcon

from ui_components import DARK_MENU_STYLE, create_qicon, get_battery_color

log = logging.getLogger("hyperheadset")

LISTEN_MS = 300            # how long each loop iteration waits for headset events
POLL_INTERVAL_S = 10       # battery (or wireless status when the headset is off)
FULL_REFRESH_S = 180       # querying everything too often destabilises the dongle
RECONNECT_INTERVAL_S = 2

SIDE_TONE_VOLUMES = (0, 50, 100, 200)
SHUTDOWN_OPTIONS = (
    (0, "Disabled"), (5, "5 min"), (10, "10 min"), (15, "15 min"), (30, "30 min"),
    (45, "45 min"), (60, "1 hour"), (90, "1.5 hours"), (120, "2 hours"),
)

INITIAL_STATE = {
    "dongle": False,       # dongle found and opened
    "connected": False,    # headset switched on and linked to the dongle
    "battery": None,
    "charging": None,
    "muted": None,
    "side_tone": None,
    "side_tone_vol": None,
    "auto_shutdown": None,
}


def setup_logging():
    log_dir = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), "HyperHeadset")
    os.makedirs(log_dir, exist_ok=True)
    handlers = [RotatingFileHandler(os.path.join(log_dir, "hyperheadset.log"),
                                    maxBytes=512 * 1024, backupCount=2, encoding="utf-8")]
    if sys.stderr is not None:  # None in a --noconsole build
        handlers.append(logging.StreamHandler())
    logging.basicConfig(
        level=logging.DEBUG if os.environ.get("HYPERHEADSET_DEBUG") else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=handlers,
    )
    sys.excepthook = lambda *exc: log.critical("Unhandled exception", exc_info=exc)


# --- WORKER THREAD ---
class HeadsetWorker(QThread):
    """Owns the HID device. All USB traffic happens in this thread; the GUI
    only sends requests through submit() and receives state_changed."""

    state_changed = pyqtSignal(dict)

    def __init__(self, protocol):
        super().__init__()
        self.hl = protocol
        self._commands = queue.Queue()
        self._stop = threading.Event()
        self.state = dict(INITIAL_STATE)

    # Called from the GUI thread.
    def submit(self, setting, value):
        self._commands.put((setting, value))

    def stop(self):
        self._stop.set()

    def run(self):
        headset = None
        try:
            while not self._stop.is_set():
                headset = self.hl.Headset.connect()
                if headset is None:
                    self._apply(dict(INITIAL_STATE))
                    self._stop.wait(RECONNECT_INTERVAL_S)
                    continue
                self._apply({"dongle": True})
                try:
                    self._serve(headset)
                except self.hl.HeadsetError as e:
                    log.warning("Lost connection to the dongle: %s", e)
                headset.close()
                headset = None
                if self._stop.is_set():
                    break
                self._drop_pending_commands()
                self._apply(dict(INITIAL_STATE))
                self._stop.wait(RECONNECT_INTERVAL_S)
        except Exception:
            log.exception("Worker crashed")
        finally:
            if headset is not None:
                headset.close()

    def _serve(self, headset):
        self._full_refresh(headset)
        now = time.monotonic()
        next_full, next_poll = now + FULL_REFRESH_S, now + POLL_INTERVAL_S

        while not self._stop.is_set():
            self._run_commands(headset)

            was_connected = self.state["connected"]
            self._apply(headset.read_updates(LISTEN_MS))
            just_connected = self.state["connected"] and not was_connected

            now = time.monotonic()
            if just_connected or now >= next_full:
                self._full_refresh(headset)
                next_full, next_poll = now + FULL_REFRESH_S, now + POLL_INTERVAL_S
            elif now >= next_poll:
                # Battery level is not reported spontaneously. While the headset is
                # off, ask for the wireless status instead (also detects a dead handle).
                cmd = self.hl.CMD_GET_BATTERY if self.state["connected"] else self.hl.CMD_GET_WIRELESS_STATUS
                self._apply(headset.query(cmd))
                next_poll = now + POLL_INTERVAL_S

    def _full_refresh(self, headset):
        before = headset.reports_received
        for cmd in self.hl.FULL_REFRESH_QUERIES:
            if self._stop.is_set():
                return
            self._apply(headset.query(cmd))
            if not self.state["connected"]:
                break
        if headset.reports_received == before:
            raise self.hl.HeadsetError("dongle stopped responding")

    def _run_commands(self, headset):
        while True:
            try:
                setting, value = self._commands.get_nowait()
            except queue.Empty:
                return
            log.info("Setting %s = %s", setting, value)
            self._apply(headset.apply_setting(setting, value))

    def _drop_pending_commands(self):
        while True:
            try:
                self._commands.get_nowait()
            except queue.Empty:
                return

    def _apply(self, updates):
        """Apply a dict of updates, or a list of them in order."""
        if isinstance(updates, list):
            for update in updates:
                self._apply(update)
            return
        if not updates:
            return
        new = dict(self.state)
        new.update(updates)
        if updates.get("battery") is not None:  # only a linked headset reports a battery level
            new["connected"] = True
        if not new["connected"]:
            new["battery"] = None
            new["charging"] = None
        if new != self.state:
            if new["connected"] != self.state["connected"]:
                log.info("Headset %s", "connected" if new["connected"] else "disconnected")
            self.state = new
            self.state_changed.emit(dict(new))


# --- MAIN APP ---
class HeadsetApp(QApplication):
    def __init__(self, argv, protocol):
        super().__init__(argv)
        self.setQuitOnLastWindowClosed(False)
        self.state = dict(INITIAL_STATE)

        self.worker = HeadsetWorker(protocol)
        self.worker.state_changed.connect(self.sync_state)

        self.tray = QSystemTrayIcon(self)
        self.tray.setIcon(create_qicon("...", get_battery_color(None)))
        self.tray.setToolTip("Looking for headset...")
        self.menu = self._build_menu()
        self.tray.setContextMenu(self.menu)
        self.sync_state(self.state)
        self.tray.show()
        self.worker.start()

        # Periodic timer so Python gets a chance to handle Ctrl+C.
        self.interrupt_timer = QTimer(self)
        self.interrupt_timer.timeout.connect(lambda: None)
        self.interrupt_timer.start(500)

    def _info_action(self, menu):
        act = QAction("", menu)
        act.setEnabled(False)
        menu.addAction(act)
        return act

    def _build_menu(self):
        menu = QMenu()
        menu.setStyleSheet(DARK_MENU_STYLE)

        self.connection_info = self._info_action(menu)
        self.battery_info = self._info_action(menu)
        self.charging_info = self._info_action(menu)
        menu.addSeparator()

        self.mute_act = QAction("Microphone muted", menu)
        self.mute_act.setCheckable(True)
        self.mute_act.triggered.connect(lambda checked: self.worker.submit("muted", checked))
        menu.addAction(self.mute_act)
        menu.addSeparator()

        self.side_tone_act = QAction("Side tone", menu)
        self.side_tone_act.setCheckable(True)
        self.side_tone_act.triggered.connect(lambda checked: self.worker.submit("side_tone", checked))
        menu.addAction(self.side_tone_act)

        self.vol_menu, self.vol_group = self._choice_menu(
            menu, "Side tone volume", [(v, str(v)) for v in SIDE_TONE_VOLUMES], "side_tone_vol")
        menu.addSeparator()

        self.shutdown_menu, self.shutdown_group = self._choice_menu(
            menu, "Automatic shutdown", SHUTDOWN_OPTIONS, "auto_shutdown")
        menu.addSeparator()

        quit_act = QAction("Quit", menu)
        quit_act.triggered.connect(self.on_quit)
        menu.addAction(quit_act)
        return menu

    def _choice_menu(self, parent, title, options, setting):
        sub = parent.addMenu(title)
        sub.setStyleSheet(DARK_MENU_STYLE)
        group = QActionGroup(sub)
        group.setExclusive(True)
        for value, label in options:
            act = QAction(label, group)
            act.setCheckable(True)
            act.setData(value)
            sub.addAction(act)
        group.triggered.connect(lambda act: self.worker.submit(setting, act.data()))
        return sub, group

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

    @staticmethod
    def _check_choice(group, value):
        # Exclusive groups can't be fully unchecked, so relax it for unknown values.
        group.setExclusive(False)
        for act in group.actions():
            act.setChecked(act.data() == value)
        group.setExclusive(True)

    def on_quit(self):
        self.worker.stop()
        if not self.worker.wait(3000):
            log.warning("Worker did not stop in time")
        self.tray.hide()
        self.quit()


def main():
    setup_logging()
    try:
        import headset_logic
    except ImportError as e:
        log.critical("No HID backend available: %s", e)
        app = QApplication(sys.argv)
        QMessageBox.critical(None, "HyperHeadset",
                             "Cannot load the HID library.\n\nInstall 'hidapi' "
                             "(pip install hidapi), or the 'hid' package together with hidapi.dll.\n\n"
                             f"{e}")
        return 1

    log.info("Starting")
    app = HeadsetApp(sys.argv, headset_logic)
    signal.signal(signal.SIGINT, lambda sig, frame: app.on_quit())
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
