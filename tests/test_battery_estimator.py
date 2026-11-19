import pytest

from battery_estimator import BatteryEstimator, format_duration

HOUR = 3600


def discharge(est, start, rate_pct_h, hours, t0=0, step=60, off=None, sleep_jump=None):
    """Feed a steady discharge sampled every `step` s.
    off=(from_h, to_h): headset switched off in that window (no drain, not connected).
    sleep_jump=(at_h, hours): the PC sleeps; one update arrives `hours` later."""
    t, level = t0, float(start)
    for i in range(int(hours * HOUR / step)):
        elapsed = i * step                     # simulated time, excluding the PC sleep
        on = not (off and off[0] * HOUR <= elapsed < off[1] * HOUR)
        if on:
            level -= rate_pct_h * step / HOUR
        est.update(int(level), "Not charging", on, now=t)
        t += step
        if sleep_jump and elapsed == int(sleep_jump[0] * HOUR / step) * step:
            t += sleep_jump[1] * HOUR          # monotonic clock jumps over the sleep
    return t, int(level)


def test_no_estimate_without_enough_data():
    est = BatteryEstimator()
    _, level = discharge(est, 80, 0.8, 0.4)
    assert est.session_rate() is None
    assert est.hours_left(level, "Not charging") is None


def test_rate_from_steady_discharge():
    est = BatteryEstimator()
    _, level = discharge(est, 80, 0.8, 6)
    assert est.session_rate() == pytest.approx(0.8, rel=0.05)
    assert est.hours_left(level, "Not charging") == pytest.approx(level / 0.8, rel=0.05)


def test_time_with_headset_off_is_not_counted():
    est = BatteryEstimator()
    discharge(est, 90, 1.0, 10, off=(2, 7))
    assert est.session_rate() == pytest.approx(1.0, rel=0.05)


def test_pc_sleep_gap_is_capped():
    est = BatteryEstimator()
    discharge(est, 90, 1.0, 6, sleep_jump=(3, 8))
    assert est.session_rate() == pytest.approx(1.0, rel=0.1)


def test_learned_rate_is_saved_and_reused(tmp_path):
    path = tmp_path / "battery.json"
    est = BatteryEstimator(str(path))
    t, level = discharge(est, 80, 0.8, 6)
    est.update(level, "Charging", True, now=t)        # charging ends the session
    assert est.hours_left(level, "Charging") is None
    assert path.exists()

    fresh = BatteryEstimator(str(path))
    assert fresh.learned_rate == pytest.approx(0.8, rel=0.05)
    assert fresh.hours_left(40, "Not charging") == pytest.approx(50, rel=0.05)


def test_small_upward_jitter_keeps_the_session():
    est = BatteryEstimator()
    est.update(50, "Not charging", True, now=0)
    est.update(51, "Not charging", True, now=60)
    est.update(49, "Not charging", True, now=120)
    assert est._session_low == 49 and len(est._crossings) == 1


def test_corrupt_statistics_file_is_ignored(tmp_path):
    path = tmp_path / "battery.json"
    path.write_text("not json")
    assert BatteryEstimator(str(path)).learned_rate is None


@pytest.mark.parametrize("hours, text", [
    (None, None), (0.004, "~1 min"), (0.5, "~30 min"), (4.0, "~4 h"), (4.5, "~4 h 30 min"), (18.3, "~18 h"),
])
def test_format_duration(hours, text):
    assert format_duration(hours) == text


# --- battery history (panel chart) ---

from battery_estimator import HISTORY_REPEAT_S, BatteryHistory  # noqa: E402


def test_history_records_changes_only(tmp_path):
    path = tmp_path / "history.json"
    h = BatteryHistory(str(path))
    assert not h.record(None, None, False, now=0)              # nothing before the first reading
    assert h.record(80, "Not charging", True, now=10)
    assert not h.record(80, "Not charging", True, now=20)
    assert h.record(79, "Not charging", True, now=30)
    assert h.record(79, "Charging", True, now=40)
    assert h.record(None, None, False, now=50)                 # headset off: a gap
    assert not h.record(None, None, False, now=60 + HISTORY_REPEAT_S)
    assert h.record(79, "Not charging", True, now=100)
    assert h.record(79, "Not charging", True, now=100 + HISTORY_REPEAT_S)   # steady level repeated
    assert [(b, c) for _, b, c in h.points] == [(80, False), (79, False), (79, True), (None, False),
                                                (79, False), (79, False)]
    assert BatteryHistory(str(path)).points == h.points        # survives a restart


def test_history_keeps_seven_days(tmp_path):
    h = BatteryHistory(str(tmp_path / "history.json"))
    day = 86400
    for i in range(10):
        h.record(90 - i, "Not charging", True, now=i * day)
    assert h.points[0][0] == day       # cutoff at day 2; the point before it stays (the line starts there)
    assert [p[1] for p in h.since(5 * day + 1)] == [85, 84, 83, 82, 81]


def test_history_ignores_a_broken_file(tmp_path):
    path = tmp_path / "history.json"
    path.write_text("{not json")
    assert BatteryHistory(str(path)).points == []


def test_history_loads_points_with_the_same_time(tmp_path):
    """Headset off and on again within a second: saved times are equal, one level is None."""
    path = tmp_path / "history.json"
    path.write_text('{"points":[[100,40,0],[200,null,0],[200,38,0]]}')
    assert BatteryHistory(str(path)).points == [(100, 40, False), (200, None, False), (200, 38, False)]
