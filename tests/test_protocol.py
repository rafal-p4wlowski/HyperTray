import pytest

import headset_logic as hl


def report(cmd, *data):
    return [0x66, cmd, *data] + [0] * (64 - 2 - len(data))


@pytest.mark.parametrize("cmd, data, expected", [
    (0x86, (1,), {"muted": True}),
    (0x0A, (0,), {"muted": False}),               # mute button event
    (0x82, (1,), {"connected": True}),
    (0x0B, (0,), {"connected": False}),           # headset switched off
    (0x8A, (1,), {"charging": "Charging"}),
    (0x0C, (2,), {"charging": "Fully charged"}),
    (0x8A, (9,), {"charging": "Charge error"}),
    (0x89, (0x0E, 0xB8, 39), {"battery": 39, "voltage_mv": 3768}),   # as read from the headset
    (0x0D, (0, 1, 7), {"battery": 7, "voltage_mv": 1}),
    (0x89, (0, 0, 55), {}),                       # no battery data
    (0x85, (30,), {"auto_shutdown": 30}),
    (0x84, (1,), {"side_tone": True}),
    (0x88, (5,), {"side_tone_vol": 5}),
    (0x88, (0xFB,), {"side_tone_vol": -5}),       # signed byte
    (0x05, (0xFE, 1), {"side_tone_vol": -2}),     # echo confirming a write
    (0x02, (20, 0), {"auto_shutdown": 20}),       # echo confirming a write
    (0x09, (1, 1), {"side_tone": True}),          # mute button held, or a write confirmed
    (0x87, (1,), {"silent": True}),
    (0x0E, (0,), {"silent": False}),
    (0x8C, (1,), {"mic_connected": True}),
    (0x07, (0,), {"mic_connected": False}),       # microphone unplugged
    (0x8F, (2,), {"color": "Black/Red"}),
    (0x8F, (7,), {"color": "#7"}),
    (0x83, (0,) * 16, {"sirk_reset_required": False}),
    (0x83, (0, 5) + (0,) * 14, {"sirk_reset_required": True}),
    (0x99, (1,), {}),                             # unknown command
])
def test_parse_report(cmd, data, expected):
    assert hl.parse_report(report(cmd, *data)) == expected


def test_parse_report_rejects_foreign_reports():
    assert hl.parse_report([0x01, 0x86, 1, 0, 0]) == {}
    assert hl.parse_report([0x66, 0x86]) == {}


def test_connect_picks_the_interface_that_answers(dongle):
    headset = hl.Headset.connect()
    assert headset is not None
    assert headset.info["path"] == b"if0"
    headset.close()


def test_connect_without_dongle(dongle):
    dongle.present = False
    assert hl.Headset.connect() is None


def test_read_updates_drains_all_reports_in_order(dongle):
    headset = hl.Headset.connect()
    dongle.push(0x89, 1, 1, 40)    # stale battery answer...
    dongle.push(0x0B, 0)           # ...then "headset switched off"
    dongle.push(0x0A, 1)
    assert headset.read_updates(100) == [{"battery": 40, "voltage_mv": 257}, {"connected": False}, {"muted": True}]
    assert headset.read_updates(50) == []
    headset.close()


def test_reads_never_use_a_blocking_timeout(dongle):
    headset = hl.Headset.connect()
    dongle.push(0x0A, 1)
    dongle.push(0x0A, 0)
    headset.read_updates(100)
    assert dongle.read_timeouts and min(dongle.read_timeouts) >= 1
    headset.close()


def test_parse_info():
    data = [0xB7, 0x08, 0xF0, 0x03, 0x09, 0x31] + list(b" HP, IncHyperX Cloud III Wireless")
    assert hl.parse_report(report(0x81, *data)) == {
        "headset_pid": 0x08B7, "headset_firmware": "3.1.0.9", "model": "HyperX Cloud III Wireless"}


def test_format_firmware():
    assert hl.format_firmware(0x4109) == "4.1.0.9"
    assert hl.format_firmware(0) is None


def test_apply_setting_waits_for_the_confirmation(dongle):
    dongle.apply_delay = 0.4                     # a query before that would still return 10
    headset = hl.Headset.connect()
    updates = headset.apply_setting("auto_shutdown", 30)
    assert updates == [{"auto_shutdown": 30}, {"auto_shutdown": 30}]   # echo, then the read-back
    assert dongle.auto_shutdown == 30
    headset.close()


def test_apply_setting_sends_signed_side_tone_volume(dongle):
    headset = hl.Headset.connect()
    assert headset.apply_setting("side_tone_vol", -4)[-1] == {"side_tone_vol": -4}
    assert dongle.set_values == [(0x05, 0xFC)]
    headset.close()


def test_apply_setting_refused_by_the_headset(dongle, monkeypatch):
    """The headset ignores the value: no confirmation, the read-back shows the old one."""
    monkeypatch.setattr(hl, "CONFIRM_TIMEOUT_S", 0.3)
    monkeypatch.setitem(hl.SETTINGS, "auto_shutdown", (0x02, 0x85, lambda v: v))   # skip our own check
    headset = hl.Headset.connect()
    assert headset.apply_setting("auto_shutdown", 15) == [{"auto_shutdown": 10}]
    headset.close()


@pytest.mark.parametrize("name, value", [("side_tone_vol", 6), ("side_tone_vol", -6), ("auto_shutdown", 5),
                                         ("muted", 2), ("silent", -1)])
def test_unsupported_values_are_not_sent(dongle, name, value):
    headset = hl.Headset.connect()
    with pytest.raises(ValueError):
        headset.apply_setting(name, value)
    assert dongle.set_values == []
    headset.close()


def test_errors_become_headset_error(dongle):
    headset = hl.Headset.connect()
    dongle.present = False
    with pytest.raises(hl.HeadsetError):
        headset.query(hl.CMD_GET_BATTERY)
