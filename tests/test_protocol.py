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
    (0x89, (1, 1, 55), {"battery": 55}),
    (0x0D, (0, 1, 7), {"battery": 7}),
    (0x89, (0, 0, 55), {}),                       # no battery data
    (0x85, (30,), {"auto_shutdown": 30}),
    (0x84, (1,), {"side_tone": True}),
    (0x88, (200,), {"side_tone_vol": 200}),
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
    assert headset.read_updates(100) == [{"battery": 40}, {"connected": False}, {"muted": True}]
    assert headset.read_updates(50) == []
    headset.close()


def test_reads_never_use_a_blocking_timeout(dongle):
    headset = hl.Headset.connect()
    dongle.push(0x0A, 1)
    dongle.push(0x0A, 0)
    headset.read_updates(100)
    assert dongle.read_timeouts and min(dongle.read_timeouts) >= 1
    headset.close()


def test_apply_setting_reads_value_back(dongle):
    headset = hl.Headset.connect()
    assert headset.apply_setting("auto_shutdown", 45) == [{"auto_shutdown": 45}]
    assert dongle.auto_shutdown == 45
    headset.close()


def test_errors_become_headset_error(dongle):
    headset = hl.Headset.connect()
    dongle.present = False
    with pytest.raises(hl.HeadsetError):
        headset.query(hl.CMD_GET_BATTERY)
