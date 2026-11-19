"""Migration from the old program name (HyperHeadset) to HyperTray.
Uses throw-away registry keys and a temporary APPDATA."""
import json
import os
import uuid
import winreg

import pytest
from PyQt6.QtCore import QSettings

import app_settings


@pytest.fixture
def names(monkeypatch, tmp_path):
    tag = uuid.uuid4().hex[:8]
    old, new = f"OldTest{tag}", f"NewTest{tag}"
    run_name = f"RunTest{tag}"
    run_key = rf"Software\{run_name}\{run_name}"  # same layout, so delete_settings_key cleans it up
    winreg.CreateKey(winreg.HKEY_CURRENT_USER, run_key).Close()
    monkeypatch.setattr(app_settings, "LEGACY_NAME", old)
    monkeypatch.setattr(app_settings, "APP_NAME", new)
    monkeypatch.setattr(app_settings, "RUN_KEY", run_key)
    monkeypatch.setattr(app_settings, "autostart_command", lambda: '"C:\\new\\HyperTray.exe"')
    # _read_autostart's default argument was bound at import time.
    original_read = app_settings._read_autostart
    monkeypatch.setattr(app_settings, "_read_autostart", lambda name=None: original_read(name or new))
    monkeypatch.setenv("APPDATA", str(tmp_path))
    yield old, new, run_key
    for name in (old, new, run_name):
        app_settings.delete_settings_key(name)


def run_value(run_key, name):
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, run_key) as key:
            return winreg.QueryValueEx(key, name)[0]
    except FileNotFoundError:
        return None


def key_exists(path):
    try:
        winreg.OpenKey(winreg.HKEY_CURRENT_USER, path).Close()
        return True
    except FileNotFoundError:
        return False


def test_migrates_everything(names, tmp_path):
    old, new, run_key = names
    s = QSettings(old, old)
    s.setValue("poll_interval_s", 600)
    s.setValue("left_click_mute", False)
    s.sync()
    old_dir = tmp_path / old
    old_dir.mkdir()
    (old_dir / "battery.json").write_text(json.dumps({"rate_pct_per_hour": 4.2}))
    (old_dir / "hyperheadset.log").write_text("old log")
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, run_key, 0, winreg.KEY_SET_VALUE) as key:
        winreg.SetValueEx(key, old, 0, winreg.REG_SZ, '"C:\\old\\HyperHeadset.exe"')

    app_settings.migrate_legacy()

    migrated = QSettings(new, new)
    assert migrated.value("poll_interval_s", type=int) == 600
    assert migrated.value("left_click_mute", type=bool) is False
    assert not key_exists(rf"Software\{old}")
    assert json.loads((tmp_path / new / "battery.json").read_text())["rate_pct_per_hour"] == 4.2
    assert not old_dir.exists()
    assert run_value(run_key, old) is None
    assert run_value(run_key, new) == '"C:\\new\\HyperTray.exe"'

    app_settings.migrate_legacy()  # second run is a no-op
    assert QSettings(new, new).value("poll_interval_s", type=int) == 600


def test_does_not_overwrite_new_settings(names):
    old, new, _ = names
    QSettings(old, old).setValue("poll_interval_s", 600)
    QSettings(new, new).setValue("poll_interval_s", 30)
    app_settings.migrate_legacy()
    assert QSettings(new, new).value("poll_interval_s", type=int) == 30
    assert not key_exists(rf"Software\{old}")


def test_nothing_to_migrate(names, tmp_path):
    _, new, run_key = names
    app_settings.migrate_legacy()
    assert run_value(run_key, new) is None
    assert not os.path.exists(tmp_path / new)


def test_old_default_poll_interval_moves_to_60s(names):
    _, new, _ = names
    s = QSettings(new, new)
    s.setValue("poll_interval_s", 10)
    s.sync()
    app_settings.migrate_settings()
    assert app_settings.AppSettings().poll_interval_s == 60
    s.setValue("poll_interval_s", 10)                       # chosen again by the user later: kept
    s.sync()
    app_settings.migrate_settings()
    assert app_settings.AppSettings().poll_interval_s == 10


def test_other_poll_interval_is_kept(names):
    _, new, _ = names
    s = QSettings(new, new)
    s.setValue("poll_interval_s", 30)
    s.sync()
    app_settings.migrate_settings()
    assert app_settings.AppSettings().poll_interval_s == 30


def test_new_install_gets_60s(names):
    app_settings.migrate_settings()
    assert app_settings.AppSettings().poll_interval_s == 60


def test_left_click_mute_option_is_removed(names):
    _, new, _ = names
    s = QSettings(new, new)
    s.setValue("left_click_mute", True)
    s.sync()
    app_settings.migrate_settings()
    assert QSettings(new, new).value("left_click_mute") is None
