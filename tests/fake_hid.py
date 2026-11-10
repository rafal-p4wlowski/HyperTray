"""In-memory stand-in for the cython-hidapi `hid` module that simulates a
HyperX Cloud III Wireless dongle. conftest.py installs it as `hid` before
headset_logic is imported.

The dongle exposes two interfaces like the real one: "if0" answers control
packets, "if3" rejects writes (as the consumer-control interface does).
"""
import collections
import threading
import time

REPORT_SIZE = 64


class Dongle:
    def __init__(self):
        self.reset()

    def reset(self):
        self.present = True
        self.headset_on = True
        self.battery = 80
        self.charging = 0
        self.muted = 0
        self.side_tone = 0
        self.side_tone_vol = 50
        self.auto_shutdown = 15
        self.sirk = [0] * 16
        self.writes = []            # command byte of every accepted packet
        self.read_timeouts = []
        self._queue = collections.deque()
        self._lock = threading.Lock()

    def push(self, cmd, *data):
        """Queue an input report, e.g. an unsolicited event."""
        report = [0x66, cmd, *data]
        report += [0] * (REPORT_SIZE - len(report))
        with self._lock:
            self._queue.append(report)

    def pop(self):
        with self._lock:
            return self._queue.popleft() if self._queue else None

    def handle(self, packet):
        cmd, value = packet[1], packet[2]
        self.writes.append(cmd)
        on = self.headset_on
        if cmd == 0x82:
            self.push(0x82, 1 if on else 0)
        elif cmd == 0x83:
            self.push(0x83, *self.sirk)
        elif not on:
            return                  # headset off: only the dongle answers
        elif cmd == 0x89:
            self.push(0x89, 1, 1, self.battery)
        elif cmd == 0x8A:
            self.push(0x8A, self.charging)
        elif cmd == 0x86:
            self.push(0x86, self.muted)
        elif cmd == 0x84:
            self.push(0x84, self.side_tone)
        elif cmd == 0x88:
            self.push(0x88, self.side_tone_vol)
        elif cmd == 0x85:
            self.push(0x85, self.auto_shutdown)
        elif cmd == 0x03:
            self.muted = value
        elif cmd == 0x01:
            self.side_tone = value
        elif cmd == 0x05:
            self.side_tone_vol = value
        elif cmd == 0x02:
            self.auto_shutdown = value
        elif cmd == 0x1E:
            self.sirk = [0] * 16


DONGLE = Dongle()


def enumerate(vendor_id=0, product_id=0):
    if not DONGLE.present:
        return []
    common = {"vendor_id": 0x03F0, "product_id": 0x05B7}
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
