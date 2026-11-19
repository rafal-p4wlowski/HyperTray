"""Headset panel end to end: tray app + panel + worker thread + fake dongle + fake Windows audio."""
import audio_endpoint
from conftest import settle, wait_idle, wait_until


def test_menu_opens_panel(app):
    app.menu.defaultAction().trigger()
    assert app.panel is not None and app.panel.isVisible()
    first = app.panel
    app.show_panel()                                         # reuses the window
    assert app.panel is first


def test_panel_shows_headset_state(panel):
    assert panel.battery_big.text() == "80%"
    assert panel.status_values["Cell voltage"].text() == "3.95 V"
    assert panel.status_values["Charging state"].text() == "Not charging"
    assert panel.info_values["Headset firmware"].text() == "3.1.0.9"
    assert panel.info_values["Dongle firmware"].text() == "4.1.0.9"
    assert panel.info_values["Headset ID"].text() == "03F0:08B7"
    assert panel.info_values["Colour"].text() == "Black/Red"
    assert panel.shutdown_group.checkedId() == 10
    assert panel.side_tone_slider.value() == 0 and not panel.side_tone_slider.isEnabled()
    assert panel.mic_detached.isHidden()
    assert "battery 80%" in panel.subtitle.text()


def test_side_tone(app, panel, dongle):
    panel.side_tone_check.setChecked(True)
    assert wait_idle(app)
    assert dongle.side_tone == 1 and panel.side_tone_slider.isEnabled()
    for v in (1, 3, 5, -2):                                  # dragging: only the last value is written
        panel.side_tone_slider.setValue(v)
    assert wait_idle(app)
    assert dongle.set_values.count((0x05, 0xFE)) == 1 and len([c for c, _ in dongle.set_values if c == 0x05]) == 1
    assert dongle.side_tone_vol == 0xFE and app.state["side_tone_vol"] == -2
    assert panel.side_tone_slider.value() == -2
    assert panel.status.text().startswith("Saved in the headset")


def test_side_tone_from_the_headset_button(panel, dongle):
    dongle.push(0x09, 1)                                     # mute button held
    assert wait_until(lambda: panel.side_tone_check.isChecked())
    assert panel.side_tone_slider.isEnabled()


def test_mute_and_silent(app, panel, dongle):
    panel.mute_check.setChecked(True)
    panel.silent_check.setChecked(True)
    assert wait_idle(app)
    assert (dongle.muted, dongle.silent) == (1, 1)
    assert app.mute_act.isChecked()                          # the tray menu follows


def test_auto_shutdown(app, panel, dongle):
    panel.shutdown_group.button(30).click()
    assert wait_idle(app)
    assert dongle.auto_shutdown == 30 and app.state["auto_shutdown"] == 30
    panel.shutdown_group.button(0).click()
    assert wait_idle(app)
    assert dongle.auto_shutdown == 0 and panel.shutdown_group.checkedId() == 0


def test_change_refused_by_the_headset_snaps_back(app, panel, dongle, monkeypatch):
    """A headset that ignores the write: the panel shows what was read back and says so."""
    real_handle = dongle.handle
    monkeypatch.setattr(dongle, "handle", lambda p: None if p[1] == 0x02 else real_handle(p))
    panel.shutdown_group.button(20).click()
    assert wait_idle(app)
    assert panel.shutdown_group.checkedId() == 10
    assert "did not take the change (Automatic shutdown)" in panel.status.text()


def test_unplugged_microphone_is_shown(panel, dongle):
    dongle.push(0x07, 0)
    assert wait_until(lambda: not panel.mic_detached.isHidden())
    dongle.push(0x07, 1)
    assert wait_until(lambda: panel.mic_detached.isHidden())


def test_headset_off_disables_controls(app, panel, dongle):
    dongle.headset_on = False
    dongle.push(0x0B, 0)
    assert wait_until(lambda: not panel.mute_check.isEnabled())
    assert not panel.shutdown_card.isEnabled() and not panel.sirk_button.isEnabled()
    assert panel.battery_big.text() == "---"
    assert panel.mic_slider.isEnabled()                      # Windows volumes do not need the headset


def test_windows_volumes(panel, windows_audio):
    mic, speakers = windows_audio[audio_endpoint.CAPTURE], windows_audio[audio_endpoint.RENDER]
    assert (panel.mic_slider.value(), panel.speaker_slider.value()) == (80, 30)
    panel.mic_slider.setValue(55)
    panel.speaker_slider.setValue(12)
    assert (mic.level, speakers.level) == (55, 12)
    speakers.level = 40                                      # changed elsewhere in Windows
    panel._refresh_audio()
    assert panel.speaker_slider.value() == 40 and speakers.level == 40


def test_windows_audio_device_missing(app, windows_audio):
    windows_audio["present"] = False
    app.show_panel()
    assert not app.panel.audio_missing.isHidden()
    assert not app.panel.mic_slider.isEnabled()


def test_windows_audio_device_goes_away(panel, windows_audio):
    windows_audio[audio_endpoint.RENDER].gone = True
    panel._refresh_audio()
    assert not panel.speaker_slider.isEnabled() and panel.mic_slider.isEnabled()


def test_sirk_reset_needs_confirmation(app, panel, dongle, monkeypatch, no_modal_dialogs):
    from PyQt6.QtWidgets import QMessageBox
    dongle.sirk = [7] * 16
    dongle.push(0x83, *dongle.sirk)
    assert wait_until(lambda: panel.sirk_label.text() == "Pairing reset required: Yes")

    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: QMessageBox.StandardButton.No)
    panel.sirk_button.click()
    settle()
    assert 0x1E not in dongle.writes

    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: QMessageBox.StandardButton.Yes)
    panel.sirk_button.click()
    assert wait_until(lambda: app.state["sirk_reset_required"] is False)
    assert 0x1E in dongle.writes and panel.sirk_label.text() == "Pairing reset required: No"


def test_reload_reads_everything_again(app, panel, dongle):
    dongle.color = 1                                         # not reported by any event
    panel._reload()
    assert wait_until(lambda: panel.info_values["Colour"].text() == "White")


def test_app_settings_sync_both_ways(app, panel):
    panel.poll_combo.setCurrentIndex(panel.poll_combo.findData(300))
    panel.poll_combo.activated.emit(panel.poll_combo.currentIndex())
    assert app.settings.poll_interval_s == 300 and app.worker.poll_interval_s == 300
    assert [a.data() for a in app.poll_group.actions() if a.isChecked()] == [300]
    next(a for a in app.poll_group.actions() if a.data() == 30).trigger()
    assert panel.poll_combo.currentData() == 30


def test_chart_follows_history(panel):
    history = panel.app.history
    now = 1_700_000_000
    history.points = [(now - 5 * 3600, 90, False), (now - 4 * 3600, None, False),
                      (now - 3 * 3600, 70, False), (now - 3600, 70, True)]
    panel.chart.now = now
    segs = panel.chart.segments()
    assert [(round((t0 - now) / 3600), lvl, chg) for t0, _, lvl, chg in segs] == [
        (-5, 90, False), (-3, 70, False), (-1, 70, True)]           # the hour off is a gap
    panel._set_chart_range(24 * 7)
    assert panel.chart.hours == 168 and panel.range_group.checkedId() == 168
    panel.chart.resize(600, 200)
    x = panel.chart._plot().right() - 1
    assert panel.chart.reading_at(x)[1:] == (70, True)
    panel.chart.grab()                                       # paints without errors


def test_pending_write_is_sent_on_close(app, panel, dongle):
    panel.side_tone_check.setChecked(True)
    assert wait_idle(app)
    panel.side_tone_slider.setValue(4)
    panel.close()                                            # within the debounce time
    assert wait_until(lambda: app.panel is None)
    assert wait_idle(app)
    assert dongle.side_tone_vol == 4


def test_closing_frees_the_panel(app, panel, windows_audio):
    panel.close()
    assert wait_until(lambda: app.panel is None)
    assert windows_audio[audio_endpoint.CAPTURE].closed
    app.show_panel()
    assert app.panel is not panel and app.panel.isVisible()
