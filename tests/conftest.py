import os
import sys
import time

# Must happen before anything imports Qt or the HID binding.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(TESTS_DIR))
sys.path.insert(0, TESTS_DIR)

import fake_hid  # noqa: E402

sys.modules["hid"] = fake_hid

import pytest  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402


class FakeSettings:
    """Keeps tests away from the real registry."""
    left_click_mute = True
    poll_interval_s = 1


def wait_until(condition, timeout=5.0):
    """Process Qt events until condition() is true. Returns whether it became true."""
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        QApplication.processEvents()
        if condition():
            return True
        time.sleep(0.01)
    QApplication.processEvents()
    return condition()


def settle(seconds=0.5):
    """Process events for a while (for checks that something did NOT happen)."""
    wait_until(lambda: False, seconds)


@pytest.fixture(scope="session")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def dongle():
    fake_hid.DONGLE.reset()
    yield fake_hid.DONGLE
    fake_hid.DONGLE.reset()


@pytest.fixture
def app(qapp, dongle, tmp_path, monkeypatch):
    import app_settings
    import headset_logic
    import tray_app

    monkeypatch.setattr(app_settings, "data_dir", lambda: str(tmp_path))
    tray = tray_app.HeadsetApp(headset_logic, FakeSettings())
    # SIRK is the last query of the full refresh.
    assert wait_until(lambda: tray.state["sirk_reset_required"] is not None), "initial refresh did not finish"
    yield tray
    tray.on_quit()
