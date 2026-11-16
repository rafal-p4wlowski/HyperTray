"""User preferences (QSettings, stored under HKCU\\Software\\HyperTray)
and the "Start with Windows" entry in the registry Run key."""
import logging
import os
import shutil
import sys
import winreg

from PyQt6.QtCore import QSettings

log = logging.getLogger(__name__)

APP_NAME = "HyperTray"
LEGACY_NAME = "HyperHeadset"  # name before 2.1; its settings are migrated once
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
    r"""%APPDATA%\HyperTray (log and battery statistics)."""
    path = _app_data_path(APP_NAME)
    os.makedirs(path, exist_ok=True)
    return path


def _app_data_path(name):
    return os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), name)


def migrate_legacy():
    """Carry settings, battery statistics and autostart over from the old
    program name. Safe to call on every start; does nothing once done."""
    old_settings, new_settings = QSettings(LEGACY_NAME, LEGACY_NAME), QSettings(APP_NAME, APP_NAME)
    if old_settings.allKeys():
        if not new_settings.allKeys():
            for key in old_settings.allKeys():
                new_settings.setValue(key, old_settings.value(key))
            new_settings.sync()
            log.info("Migrated settings from %s", LEGACY_NAME)
        old_settings.clear()
        old_settings.sync()
        delete_settings_key(LEGACY_NAME)

    old_dir, new_dir = _app_data_path(LEGACY_NAME), _app_data_path(APP_NAME)
    if os.path.isdir(old_dir):
        os.makedirs(new_dir, exist_ok=True)
        old_stats, new_stats = os.path.join(old_dir, "battery.json"), os.path.join(new_dir, "battery.json")
        if os.path.exists(old_stats) and not os.path.exists(new_stats):
            shutil.move(old_stats, new_stats)
            log.info("Migrated battery statistics from %s", old_dir)
        shutil.rmtree(old_dir, ignore_errors=True)  # only the old log is left

    if _read_autostart(LEGACY_NAME) is not None:
        _delete_autostart(LEGACY_NAME)
        set_autostart(True)
        log.info("Migrated autostart entry from %s", LEGACY_NAME)


def delete_settings_key(name):
    r"""Remove HKCU\Software\<name>\<name> (where QSettings keeps the values) and its parent."""
    for path in (rf"Software\{name}\{name}", rf"Software\{name}"):
        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, path)
        except OSError:
            pass


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


def _read_autostart(name=APP_NAME):
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            return winreg.QueryValueEx(key, name)[0]
    except FileNotFoundError:
        return None


def _delete_autostart(name):
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        try:
            winreg.DeleteValue(key, name)
        except FileNotFoundError:
            pass


def is_autostart_enabled():
    return _read_autostart() is not None


def set_autostart(enabled):
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        if enabled:
            winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, autostart_command())
    if not enabled:
        _delete_autostart(APP_NAME)
    log.info("Start with Windows %s", "enabled" if enabled else "disabled")


def refresh_autostart():
    """If autostart is on but points elsewhere (program moved), fix the path."""
    current = _read_autostart()
    if current is not None and current.lower() != autostart_command().lower():
        log.info("Updating autostart path (was %s)", current)
        set_autostart(True)
