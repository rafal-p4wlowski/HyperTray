"""User preferences (QSettings, stored under HKCU\\Software\\HyperHeadset)
and the "Start with Windows" entry in the registry Run key."""
import logging
import os
import sys
import winreg

from PyQt6.QtCore import QSettings

log = logging.getLogger(__name__)

APP_NAME = "HyperHeadset"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
# Battery refresh choices: (seconds, menu label). The original project polls
# every 3 s, so 5 s is still safe for the dongle.
POLL_OPTIONS = (
    (5, "5 s"), (10, "10 s"), (30, "30 s"), (60, "1 min"),
    (120, "2 min"), (300, "5 min"), (600, "10 min"),
)
POLL_INTERVALS = tuple(seconds for seconds, _ in POLL_OPTIONS)
DEFAULT_POLL_INTERVAL = 10


def data_dir():
    r"""%APPDATA%\HyperHeadset (log and battery statistics)."""
    path = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), APP_NAME)
    os.makedirs(path, exist_ok=True)
    return path


class AppSettings:
    def __init__(self):
        self._s = QSettings(APP_NAME, APP_NAME)

    @property
    def left_click_mute(self):
        return self._s.value("left_click_mute", True, type=bool)

    @left_click_mute.setter
    def left_click_mute(self, value):
        self._s.setValue("left_click_mute", bool(value))

    @property
    def poll_interval_s(self):
        value = self._s.value("poll_interval_s", DEFAULT_POLL_INTERVAL, type=int)
        return value if value in POLL_INTERVALS else DEFAULT_POLL_INTERVAL

    @poll_interval_s.setter
    def poll_interval_s(self, value):
        self._s.setValue("poll_interval_s", int(value))


def autostart_command():
    """Command line Windows should run at logon."""
    if getattr(sys, "frozen", False):  # PyInstaller build
        return f'"{sys.executable}"'
    pythonw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    if not os.path.exists(pythonw):
        pythonw = sys.executable
    script = os.path.abspath(os.path.join(os.path.dirname(__file__), "main.py"))
    return f'"{pythonw}" "{script}"'


def _read_autostart():
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            return winreg.QueryValueEx(key, APP_NAME)[0]
    except FileNotFoundError:
        return None


def is_autostart_enabled():
    return _read_autostart() is not None


def set_autostart(enabled):
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        if enabled:
            winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, autostart_command())
        else:
            try:
                winreg.DeleteValue(key, APP_NAME)
            except FileNotFoundError:
                pass
    log.info("Start with Windows %s", "enabled" if enabled else "disabled")


def refresh_autostart():
    """If autostart is on but points elsewhere (program moved), fix the path."""
    current = _read_autostart()
    if current is not None and current.lower() != autostart_command().lower():
        log.info("Updating autostart path (was %s)", current)
        set_autostart(True)
