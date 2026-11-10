"""End-to-end tests: tray app + worker thread + protocol against the fake dongle."""
from PyQt6.QtWidgets import QMessageBox, QSystemTrayIcon

from conftest import settle, wait_until

CLICK = QSystemTrayIcon.ActivationReason.Trigger


def pick(group, value):
    next(a for a in group.actions() if a.data() == value).trigger()


def checked(group):
    return [a.data() for a in group.actions() if a.isChecked()]


def test_startup_reads_everything(app):
    s = app.state
    assert (s["dongle"], s["connected"], s["battery"], s["charging"]) == (True, True, 80, "Not charging")
    assert (s["muted"], s["side_tone"], s["side_tone_vol"], s["auto_shutdown"]) == (False, False, 50, 15)
    assert app.connection_info.text() == "Headset connected"
    assert app.mute_act.isEnabled()
    assert checked(app.vol_group) == [50] and checked(app.shutdown_group) == [15]


def test_spontaneous_events(app, dongle):
    dongle.push(0x0A, 1)   # mute button on the headset
    dongle.push(0x0C, 1)   # charger plugged in
    assert wait_until(lambda: app.state["muted"] and app.state["charging"] == "Charging")
    assert "Microphone muted" in app.tray.toolTip()


def test_menu_changes_settings(app, dongle):
    app.mute_act.trigger()
    assert wait_until(lambda: app.state["muted"] is True)
    assert dongle.muted == 1
    pick(app.vol_group, 200)
    assert wait_until(lambda: app.state["side_tone_vol"] == 200)
    pick(app.shutdown_group, 30)
    assert wait_until(lambda: app.state["auto_shutdown"] == 30)
    assert (dongle.side_tone_vol, dongle.auto_shutdown) == (200, 30)
    assert checked(app.vol_group) == [200] and checked(app.shutdown_group) == [30]


def test_battery_is_polled(app, dongle):
    dongle.battery = 42
    assert wait_until(lambda: app.state["battery"] == 42, timeout=4)
    assert app.battery_info.text() == "Battery level: 42%"


def test_left_click_toggles_mute(app, dongle):
    app.on_tray_activated(CLICK)
    assert wait_until(lambda: app.state["muted"] is True)
    app.on_tray_activated(CLICK)
    assert wait_until(lambda: app.state["muted"] is False)


def test_left_click_does_nothing_when_disabled(app, dongle):
    app.settings.left_click_mute = False
    app.on_tray_activated(CLICK)
    settle()
    assert dongle.muted == 0 and 0x03 not in dongle.writes


def test_headset_off_and_on(app, dongle):
    dongle.headset_on = False
    dongle.push(0x0B, 0)
    assert wait_until(lambda: app.state["connected"] is False)
    assert app.state["battery"] is None and app.state["charging"] is None
    assert not app.mute_act.isEnabled() and not app.vol_menu.isEnabled()
    assert app.connection_info.text() == "Headset off / out of range"

    app.on_tray_activated(CLICK)           # ignored while the headset is off
    settle(0.3)
    assert 0x03 not in dongle.writes

    dongle.headset_on = True
    dongle.push(0x0B, 1)
    # Reconnecting must trigger a full refresh, so the charging state comes back too.
    assert wait_until(lambda: app.state["connected"] and app.state["charging"] == "Not charging")
    assert app.mute_act.isEnabled()


def test_dongle_unplugged_and_replugged(app, dongle):
    dongle.present = False
    assert wait_until(lambda: app.state["dongle"] is False)
    assert app.state["connected"] is False and app.state["muted"] is None
    assert app.connection_info.text() == "Dongle not found"
    dongle.present = True
    assert wait_until(lambda: app.state["connected"] and app.state["battery"] == 80, timeout=8)


def test_poll_interval_setting(app):
    pick(app.poll_group, 300)
    assert app.worker.poll_interval_s == 300 and app.settings.poll_interval_s == 300
    assert checked(app.poll_group) == [300]


def test_sirk_reset_needs_confirmation(app, dongle, monkeypatch):
    dongle.sirk = [7] * 16
    app.worker.submit("side_tone", True)  # any command; then force a full refresh read of SIRK
    assert wait_until(lambda: app.state["side_tone"] is True)
    dongle.push(0x83, *dongle.sirk)
    assert wait_until(lambda: app.state["sirk_reset_required"] is True)
    assert app.sirk_info.text() == "Pairing reset required: Yes"

    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: QMessageBox.StandardButton.No))
    app.sirk_reset_act.trigger()
    settle()
    assert 0x1E not in dongle.writes

    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes))
    app.sirk_reset_act.trigger()
    assert wait_until(lambda: app.state["sirk_reset_required"] is False)
    assert 0x1E in dongle.writes


def test_quit_stops_worker(app):
    app.on_quit()
    assert not app.worker.isRunning()
