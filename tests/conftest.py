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
    poll_interval_s = 1
    language = "en"


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


class FakeEndpoint:
    def __init__(self, volume):
        self.level = volume
        self.gone = False
        self.closed = False

    def volume(self):
        if self.gone:
            raise OSError("device invalidated")
        return self.level

    def set_volume(self, percent):
        if self.gone:
            raise OSError("device invalidated")
        self.level = percent

    def close(self):
        self.closed = True


@pytest.fixture(autouse=True)
def windows_audio(monkeypatch):
    """Simulated Windows audio endpoints of the headset; never the real ones."""
    import audio_endpoint

    box = {"present": True, audio_endpoint.RENDER: FakeEndpoint(30), audio_endpoint.CAPTURE: FakeEndpoint(80)}

    def find(name=audio_endpoint.DEVICE_NAME):
        if not box["present"]:
            return {}
        return {flow: box[flow] for flow in (audio_endpoint.RENDER, audio_endpoint.CAPTURE) if not box[flow].gone}

    monkeypatch.setattr(audio_endpoint, "find_endpoints", find)
    return box


@pytest.fixture(autouse=True)
def no_modal_dialogs(monkeypatch):
    """A message box would block the test run; answer Yes and record it."""
    from PyQt6.QtWidgets import QMessageBox

    shown = []

    def answer(*args, **kwargs):
        shown.append(args[1:3])
        return QMessageBox.StandardButton.Yes

    for name in ("question", "warning", "information", "critical"):
        monkeypatch.setattr(QMessageBox, name, answer)
    return shown


@pytest.fixture
def app(qapp, dongle, tmp_path, monkeypatch):
    import app_settings
    import headset_logic
    import tray_app

    monkeypatch.setattr(app_settings, "data_dir", lambda: str(tmp_path))
    monkeypatch.setattr(app_settings, "is_autostart_enabled", lambda: False)
    monkeypatch.setattr(headset_logic, "CONFIRM_TIMEOUT_S", 0.6)   # the fake confirms after 0.15 s
    tray = tray_app.HeadsetApp(headset_logic, FakeSettings())
    # SIRK is the last query of the full refresh.
    assert wait_until(lambda: tray.state["sirk_reset_required"] is not None), "initial refresh did not finish"
    yield tray
    tray.on_quit()


@pytest.fixture
def panel(app):
    """The headset panel, opened."""
    app.show_panel()
    return app.panel


def wait_idle(app, timeout=5.0):
    """Send debounced panel changes and wait until the worker ran every command."""
    if app.panel is not None:
        app.panel._flush_pending()
    idle = wait_until(lambda: not app.worker.busy, timeout)
    settle(0.05)                    # deliver the queued state and busy signals
    return idle
