import logging
import queue
import threading
import time

from PyQt6.QtCore import QThread, pyqtSignal

log = logging.getLogger("hypertray")

LISTEN_MS = 300            # how long each loop iteration waits for headset events
FULL_REFRESH_S = 180       # querying everything too often destabilises the dongle
RECONNECT_INTERVAL_S = 2

INITIAL_STATE = {
    "dongle": False,       # dongle found and opened
    "connected": False,    # headset switched on and linked to the dongle
    "battery": None,
    "voltage_mv": None,
    "charging": None,
    "muted": None,
    "mic_connected": None,
    "side_tone": None,
    "side_tone_vol": None,
    "silent": None,
    "auto_shutdown": None,
    "sirk_reset_required": None,
    "color": None,
    "model": None,
    "headset_pid": None,
    "headset_firmware": None,
    "dongle_firmware": None,
}
# Only meaningful while the headset is linked.
LIVE_KEYS = ("battery", "voltage_mv", "charging")


class HeadsetWorker(QThread):
    """Owns the HID device. All USB traffic happens in this thread; the GUI
    only sends requests through submit() and receives state_changed."""

    state_changed = pyqtSignal(dict)
    busy_changed = pyqtSignal(bool)      # commands queued or running

    def __init__(self, protocol, poll_interval_s=60):
        super().__init__()
        self.hl = protocol
        # Battery poll interval (or wireless status while the headset is off).
        # Plain attribute: written by the GUI thread, read here.
        self.poll_interval_s = poll_interval_s
        self._commands = queue.Queue()
        self._pending = 0
        self._pending_lock = threading.Lock()
        self._stop = threading.Event()
        self._refresh_needed = False  # set when the headset (re)connects or on request
        self.state = dict(INITIAL_STATE)

    # Called from the GUI thread.
    def submit(self, setting, value):
        with self._pending_lock:
            self._pending += 1
            first = self._pending == 1
        if first:
            self.busy_changed.emit(True)
        self._commands.put((setting, value))

    def request_refresh(self):
        """Read every setting again (the panel's Reload button)."""
        self._refresh_needed = True

    @property
    def busy(self):
        return self._pending > 0

    def stop(self):
        self._stop.set()

    def run(self):
        headset = None
        try:
            while not self._stop.is_set():
                headset = self.hl.Headset.connect()
                if headset is None:
                    self._drop_pending_commands()
                    self._apply(dict(INITIAL_STATE))
                    self._stop.wait(RECONNECT_INTERVAL_S)
                    continue
                self._apply({"dongle": True, "dongle_firmware": headset.dongle_firmware})
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
        next_full, last_poll = now + FULL_REFRESH_S, now

        while not self._stop.is_set():
            self._run_commands(headset)

            self._apply(headset.read_updates(LISTEN_MS))

            now = time.monotonic()
            if self._refresh_needed or now >= next_full:
                self._full_refresh(headset)
                next_full, last_poll = now + FULL_REFRESH_S, now
            elif now - last_poll >= self.poll_interval_s:
                # Battery level is not reported spontaneously. While the headset is
                # off, ask for the wireless status instead (also detects a dead handle).
                cmd = self.hl.CMD_GET_BATTERY if self.state["connected"] else self.hl.CMD_GET_WIRELESS_STATUS
                self._apply(headset.query(cmd))
                last_poll = now

    def _full_refresh(self, headset):
        self._refresh_needed = False
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
            try:
                self._run_command(headset, setting, value)
            finally:
                self._command_done()

    def _run_command(self, headset, setting, value):
        if not self.state["connected"]:
            log.info("Headset off, dropping %s = %s", setting, value)
            return
        if setting == "reset_sirk":
            self._apply(headset.reset_sirk())
            log.info("SIRK reset done, reset required now: %s", self.state["sirk_reset_required"])
            return
        if self.state.get(setting) == value:
            return                  # the headset would not confirm a write of the current value
        log.info("Setting %s = %s", setting, value)
        try:
            self._apply(headset.apply_setting(setting, value))
        except ValueError as e:
            log.warning("Not sent: %s", e)
            return
        if self.state.get(setting) != value:
            log.warning("Headset kept %s = %s instead of %s", setting, self.state.get(setting), value)

    def _command_done(self):
        with self._pending_lock:
            self._pending -= 1
            idle = self._pending == 0
        if idle:
            self.busy_changed.emit(False)

    def _drop_pending_commands(self):
        while True:
            try:
                self._commands.get_nowait()
            except queue.Empty:
                return
            self._command_done()

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
            for key in LIVE_KEYS:
                new[key] = None
        if new != self.state:
            if new["sirk_reset_required"] != self.state["sirk_reset_required"] and new["sirk_reset_required"] is not None:
                log.info("Pairing key (SIRK) reset required: %s", new["sirk_reset_required"])
            if new["connected"] != self.state["connected"]:
                log.info("Headset %s", "connected" if new["connected"] else "disconnected")
                # The connect event may arrive in any read (also inside a query),
                # so the full refresh is requested here rather than by the caller.
                self._refresh_needed = new["connected"]
            self.state = new
            self.state_changed.emit(dict(new))
