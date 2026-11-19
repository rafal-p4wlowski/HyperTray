"""In-memory stand-in for the cython-hidapi `hid` module that simulates a
HyperX Cloud III Wireless dongle. conftest.py installs it as `hid` before
headset_logic is imported.

The dongle exposes two interfaces like the real one: "if0" answers control
packets, "if3" rejects writes (as the consumer-control interface does).

Firmware quirks seen on the real headset are reproduced:
- a write takes effect `apply_delay` seconds later (0.5-1 s on the headset);
  a query sent before still returns the old value;
- the confirmation is an event (mute 0x0A, side tone 0x09, silent 0x0E) or an
  echo of the command (0x02, 0x05) with the new value;
- unsupported values and writes of the current value get no answer at all;
- side tone volume is a signed byte in -5..+5.
"""
import collections
import threading
import time

REPORT_SIZE = 64
INFO = [0xB7, 0x08, 0xF0, 0x03, 0x09, 0x31] + list(b" HP, IncHyperX Cloud III Wireless")

# set command -> (attribute, allowed values, confirmation report command)
SETTERS = {
    0x01: ("side_tone", {0, 1}, 0x09),
    0x02: ("auto_shutdown", {0, 10, 20, 30}, 0x02),
    0x03: ("muted", {0, 1}, 0x0A),
    0x04: ("silent", {0, 1}, 0x0E),
    0x05: ("side_tone_vol", set(range(0, 6)) | set(range(251, 256)), 0x05),
}
GETTERS = {0x84: "side_tone", 0x85: "auto_shutdown", 0x86: "muted", 0x87: "silent", 0x88: "side_tone_vol",
           0x8A: "charging", 0x8C: "mic_connected", 0x8F: "color"}


class Dongle:
    def __init__(self):
        self.reset()

    def reset(self):
        self.present = True
        self.headset_on = True
        self.battery = 80
        self.voltage_mv = 3950
        self.charging = 0
        self.muted = 0
        self.side_tone = 0
        self.side_tone_vol = 0          # raw byte, 251..255 = -5..-1
        self.silent = 0
        self.auto_shutdown = 10
        self.mic_connected = 1
        self.color = 2
        self.sirk = [0] * 16
        self.apply_delay = 0.15
        self.writes = []            # command byte of every accepted packet
        self.set_values = []        # (command, value) of every setter packet
        self.read_timeouts = []
        self._queue = collections.deque()
        self._pending = []          # (due time, attribute, value, confirmation command)
        self._lock = threading.Lock()

    def push(self, cmd, *data):
        """Queue an input report, e.g. an unsolicited event."""
        report = [0x66, cmd, *data]
        report += [0] * (REPORT_SIZE - len(report))
        with self._lock:
            self._queue.append(report)

    def pop(self):
        self._apply_due()
        with self._lock:
            return self._queue.popleft() if self._queue else None

    def _apply_due(self):
        now = time.monotonic()
        with self._lock:
            due = [p for p in self._pending if p[0] <= now]
            self._pending = [p for p in self._pending if p[0] > now]
        for _, attr, value, confirm in due:
            setattr(self, attr, value)
            self.push(confirm, value, 1 if confirm in (0x05, 0x09, 0x0A) else 0)

    def handle(self, packet):
        cmd, value = packet[1], packet[2]
        self.writes.append(cmd)
        on = self.headset_on
        if cmd == 0x82:
            self.push(0x82, 1 if on else 0)
        elif cmd == 0x83:
            self.push(0x83, *self.sirk)
        elif cmd == 0x81:
            self.push(0x81, *INFO)
        elif not on:
            return                  # headset off: only the dongle answers
        elif cmd == 0x89:
            self.push(0x89, self.voltage_mv >> 8, self.voltage_mv & 0xFF, self.battery)
        elif cmd in GETTERS:
            self.push(cmd, getattr(self, GETTERS[cmd]))
        elif cmd in SETTERS:
            attr, allowed, confirm = SETTERS[cmd]
            self.set_values.append((cmd, value))
            if value in allowed and value != getattr(self, attr):
                with self._lock:
                    self._pending.append((time.monotonic() + self.apply_delay, attr, value, confirm))
        elif cmd == 0x1E:
            self.sirk = [0] * 16


DONGLE = Dongle()


def enumerate(vendor_id=0, product_id=0):
    if not DONGLE.present:
        return []
    common = {"vendor_id": 0x03F0, "product_id": 0x05B7, "release_number": 0x4109}
    return [
        {**common, "path": b"if3", "usage_page": 0x000C, "interface_number": 3},
        {**common, "path": b"if0", "usage_page": 0xFF13, "interface_number": 3},
    ]


class device:
    def open_path(self, path):
        if not DONGLE.present:
            raise OSError("open failed")
        self.path = path

    def write(self, data):
        if not DONGLE.present:
            raise OSError("write error")
        if self.path != b"if0":
            return -1
        DONGLE.handle(list(data))
        return len(data)

    def send_feature_report(self, data):
        return -1

    def read(self, size, timeout_ms=0):
        DONGLE.read_timeouts.append(timeout_ms)
        if timeout_ms <= 0:
            # cython-hidapi blocks forever here; fail loudly instead of hanging.
            raise RuntimeError("blocking read (timeout 0) would hang the worker")
        if not DONGLE.present:
            raise OSError("read error")
        end = time.monotonic() + timeout_ms / 1000
        while True:
            report = DONGLE.pop()
            if report is not None:
                return report[:size]
            if time.monotonic() >= end:
                return []
            time.sleep(0.002)

    def close(self):
        pass
