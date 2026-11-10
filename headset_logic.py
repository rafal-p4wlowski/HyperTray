"""HID protocol for the HyperX Cloud III Wireless.

Follows the approach of LennardKittner/HyperHeadset: every report the headset
sends, whether it answers a query or is an unsolicited event (mute button,
charger plugged in, headset switched on/off), is parsed into a state update,
and the input buffer is always read until empty. Answers therefore can never
get out of step with the queries that caused them.
"""
import logging
import time

import hid

log = logging.getLogger(__name__)

VENDOR_ID = 0x03F0
PRODUCT_IDS = (0x05B7, 0x0C9D)

REPORT_ID = 0x66
PACKET_SIZE = 62
READ_SIZE = 64
RESPONSE_DELAY = 0.05      # seconds between a write and the first read
RESPONSE_TIMEOUT_MS = 1000
MAX_REPORTS_PER_READ = 64  # upper bound, so a chatty device can't stall the loop

# Queries
CMD_GET_WIRELESS_STATUS = 0x82
CMD_GET_SIDE_TONE       = 0x84
CMD_GET_AUTO_SHUTDOWN   = 0x85
CMD_GET_MUTE            = 0x86
CMD_GET_SIDE_TONE_VOL   = 0x88
CMD_GET_BATTERY         = 0x89
CMD_GET_CHARGING        = 0x8A

# Setters
CMD_SET_SIDE_TONE       = 0x01
CMD_SET_AUTO_SHUTDOWN   = 0x02
CMD_SET_MUTE            = 0x03
CMD_SET_SIDE_TONE_VOL   = 0x05

# Unsolicited events
EVT_MUTE            = 0x0A
EVT_WIRELESS_STATUS = 0x0B
EVT_CHARGING        = 0x0C
EVT_BATTERY         = 0x0D

CHARGING_STATES = {0: "Not charging", 1: "Charging", 2: "Fully charged"}

# Wireless status goes first: when the headset is off, the remaining queries
# are skipped instead of each waiting for a timeout.
FULL_REFRESH_QUERIES = (
    CMD_GET_WIRELESS_STATUS,
    CMD_GET_CHARGING,
    CMD_GET_BATTERY,
    CMD_GET_AUTO_SHUTDOWN,
    CMD_GET_MUTE,
    CMD_GET_SIDE_TONE,
    CMD_GET_SIDE_TONE_VOL,
)

# setting name -> (set command, query that reads the value back)
SETTINGS = {
    "muted":         (CMD_SET_MUTE, CMD_GET_MUTE),
    "side_tone":     (CMD_SET_SIDE_TONE, CMD_GET_SIDE_TONE),
    "side_tone_vol": (CMD_SET_SIDE_TONE_VOL, CMD_GET_SIDE_TONE_VOL),
    "auto_shutdown": (CMD_SET_AUTO_SHUTDOWN, CMD_GET_AUTO_SHUTDOWN),
}


class HeadsetError(Exception):
    """Communication with the dongle failed; the device must be reopened."""


def parse_report(report):
    """Turn one input report into a dict of state updates (empty if not relevant)."""
    if len(report) < 5 or report[0] != REPORT_ID:
        return {}
    cmd, a, b, c = report[1], report[2], report[3], report[4]

    if cmd in (CMD_GET_MUTE, EVT_MUTE):
        return {"muted": a == 1}
    if cmd in (CMD_GET_WIRELESS_STATUS, EVT_WIRELESS_STATUS):
        return {"connected": a == 1}
    if cmd in (CMD_GET_CHARGING, EVT_CHARGING):
        return {"charging": CHARGING_STATES.get(a, "Charge error")}
    if cmd in (CMD_GET_BATTERY, EVT_BATTERY):
        # Both state bytes are zero when the dongle has no battery data.
        return {"battery": c} if (a or b) else {}
    if cmd == CMD_GET_AUTO_SHUTDOWN:
        return {"auto_shutdown": a}
    if cmd == CMD_GET_SIDE_TONE:
        return {"side_tone": a == 1}
    if cmd == CMD_GET_SIDE_TONE_VOL:
        return {"side_tone_vol": a}

    log.debug("Unhandled report: %s", " ".join(f"{x:02X}" for x in report[:8]))
    return {}


class _Transport:
    """Thin wrapper over either HID binding that can be installed as `hid`:
    `hidapi` (cython-hidapi, has hid.device) or `hid` (ctypes, has hid.Device,
    needs hidapi.dll next to the program or on PATH)."""

    def __init__(self, path):
        try:
            if hasattr(hid, "device"):
                self._dev = hid.device()
                self._dev.open_path(path)
                self._as_bytes = False
            else:
                self._dev = hid.Device(path=path)
                self._as_bytes = True
        except Exception as e:
            raise HeadsetError(f"cannot open {path!r}: {e}") from e

    def write(self, packet):
        data = bytes(packet) if self._as_bytes else list(packet)
        error = None
        try:
            if self._dev.write(data) >= 0:
                return
        except Exception as e:
            error = e
        # Some Windows HID stacks reject output reports on this interface
        # ("Incorrect function"); the headset also accepts a feature report.
        try:
            if self._dev.send_feature_report(data) >= 0:
                return
        except Exception:
            pass
        raise HeadsetError(f"write failed: {error or 'device returned -1'}")

    def read(self, timeout_ms):
        """Return one report as a list of ints, or None on timeout."""
        # cython-hidapi treats timeout 0 as "block forever", so never pass 0.
        try:
            data = self._dev.read(READ_SIZE, max(1, int(timeout_ms)))
        except Exception as e:
            raise HeadsetError(f"read failed: {e}") from e
        return list(data) if data else None

    def close(self):
        try:
            self._dev.close()
        except Exception:
            pass


class Headset:
    def __init__(self, transport, info):
        self._t = transport
        self.info = info
        self.reports_received = 0

    @classmethod
    def connect(cls):
        """Open the dongle interface that answers our queries, or return None.

        The dongle exposes several HID interfaces and on Windows only one of
        them accepts control packets, so each candidate is probed.
        """
        try:
            devices = hid.enumerate(VENDOR_ID, 0)
        except Exception as e:
            log.warning("HID enumeration failed: %s", e)
            return None
        candidates = [d for d in devices if d["product_id"] in PRODUCT_IDS]
        candidates.sort(key=lambda d: d.get("usage_page", 0), reverse=True)

        for info in candidates:
            desc = (f"PID {info['product_id']:04X} interface {info.get('interface_number')} "
                    f"usage page {info.get('usage_page', 0):04X}")
            try:
                headset = cls(_Transport(info["path"]), info)
            except HeadsetError as e:
                log.debug("Skipping %s: %s", desc, e)
                continue
            try:
                headset.query(CMD_GET_WIRELESS_STATUS)
            except HeadsetError as e:
                log.debug("Skipping %s: %s", desc, e)
            if headset.reports_received:
                log.info("Connected to %s", desc)
                return headset
            log.debug("No answer from %s", desc)
            headset.close()
        return None

    def send(self, cmd, value=0):
        packet = [REPORT_ID, cmd, value & 0xFF] + [0] * (PACKET_SIZE - 3)
        self._t.write(packet)

    def read_updates(self, timeout_ms):
        """Wait up to timeout_ms for a report, then read everything already
        queued. Returns one update dict per report, oldest first; they must be
        applied in order (e.g. a stale battery answer followed by a
        "headset switched off" event)."""
        updates = []
        timeout = timeout_ms
        for _ in range(MAX_REPORTS_PER_READ):
            report = self._t.read(timeout)
            if report is None:
                break
            self.reports_received += 1
            update = parse_report(report)
            if update:
                updates.append(update)
            timeout = 0
        return updates

    def query(self, cmd):
        self.send(cmd)
        time.sleep(RESPONSE_DELAY)
        return self.read_updates(RESPONSE_TIMEOUT_MS)

    def apply_setting(self, name, value):
        """Change a setting and return the updates read back from the headset."""
        set_cmd, get_cmd = SETTINGS[name]
        self.send(set_cmd, int(value))
        time.sleep(RESPONSE_DELAY)
        return self.query(get_cmd)

    def close(self):
        self._t.close()
