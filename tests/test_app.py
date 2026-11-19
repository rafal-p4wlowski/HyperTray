"""End-to-end tests: tray app + worker thread + protocol against the fake dongle."""
from PyQt6.QtWidgets import QSystemTrayIcon

from conftest import settle, wait_idle, wait_until

CLICK = QSystemTrayIcon.ActivationReason.Trigger
DOUBLE_CLICK = QSystemTrayIcon.ActivationReason.DoubleClick


def pick(group, value):
    next(a for a in group.actions() if a.data() == value).trigger()


def checked(group):
    return [a.data() for a in group.actions() if a.isChecked()]


def test_startup_reads_everything(app):
    s = app.state
    assert (s["dongle"], s["connected"], s["battery"], s["voltage_mv"], s["charging"]) == (
        True, True, 80, 3950, "Not charging")
    assert (s["muted"], s["side_tone"], s["side_tone_vol"], s["silent"], s["auto_shutdown"]) == (
        False, False, 0, False, 10)
    assert (s["mic_connected"], s["color"], s["model"]) == (True, "Black/Red", "HyperX Cloud III Wireless")
    assert (s["headset_pid"], s["headset_firmware"], s["dongle_firmware"]) == (0x08B7, "3.1.0.9", "4.1.0.9")
    assert app.connection_info.text() == "Headset connected"
    assert app.mute_act.isEnabled()


def test_menu_is_slim(app):
    texts = [a.text() for a in app.menu.actions() if a.text()]
    assert texts[-4:] == ["Microphone muted", "Headset panel...", "Settings", "Quit"]
    assert app.menu.defaultAction().text() == "Headset panel..."


def test_spontaneous_events(app, dongle):
    dongle.push(0x0A, 1)   # mute button on the headset
    dongle.push(0x0C, 1)   # charger plugged in
    dongle.push(0x09, 1)   # mute button held: side tone on
    dongle.push(0x07, 0)   # microphone unplugged
    assert wait_until(lambda: app.state["muted"] and app.state["charging"] == "Charging"
                      and app.state["side_tone"] and app.state["mic_connected"] is False)
    assert "Microphone muted" in app.tray.toolTip()


def test_write_waits_for_the_confirmation(app, dongle):
    """The headset answers a query with the old value until the write took effect."""
    dongle.apply_delay = 0.4
    app.worker.submit("side_tone_vol", -3)
    assert wait_idle(app)
    assert app.state["side_tone_vol"] == -3 and dongle.side_tone_vol == 253


def test_refused_value_keeps_the_headset_value(app, dongle):
    app.worker.submit("side_tone_vol", 9)          # out of range: never sent
    app.worker.submit("auto_shutdown", 15)         # not one of 0/10/20/30
    assert wait_idle(app)
    assert (app.state["side_tone_vol"], app.state["auto_shutdown"]) == (0, 10)
    assert 0x05 not in dongle.writes and 0x02 not in dongle.writes


def test_write_of_current_value_is_skipped(app, dongle):
    app.worker.submit("auto_shutdown", 10)
    assert wait_idle(app)
    assert 0x02 not in dongle.writes


def test_menu_mute(app, dongle):
    app.mute_act.trigger()
    assert wait_until(lambda: app.state["muted"] is True)
    assert dongle.muted == 1


def test_battery_is_polled(app, dongle):
    dongle.battery = 42
    assert wait_until(lambda: app.state["battery"] == 42, timeout=4)
    assert app.battery_info.text() == "Battery level: 42%"


def test_click_opens_panel(app, dongle):
    app.on_tray_activated(CLICK)
    assert app.panel is not None and app.panel.isVisible()
    first = app.panel
    app.on_tray_activated(CLICK)            # Windows reports the first click of a double click too
    app.on_tray_activated(DOUBLE_CLICK)
    settle(0.3)
    assert app.panel is first
    assert 0x03 not in dongle.writes        # a click never touches the microphone


def test_headset_off_and_on(app, dongle):
    dongle.headset_on = False
    dongle.push(0x0B, 0)
    assert wait_until(lambda: app.state["connected"] is False)
    assert app.state["battery"] is None and app.state["charging"] is None and app.state["voltage_mv"] is None
    assert not app.mute_act.isEnabled()
    assert app.connection_info.text() == "Headset off / out of range"

    app.worker.submit("muted", True)        # dropped while the headset is off
    assert wait_idle(app)
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


def test_battery_history_is_recorded(app, dongle):
    assert app.history.points[-1][1:] == (80, False)
    dongle.push(0x0C, 1)
    assert wait_until(lambda: app.history.points[-1][1:] == (80, True))


def test_quit_stops_worker(app):
    app.on_quit()
    assert not app.worker.isRunning()
