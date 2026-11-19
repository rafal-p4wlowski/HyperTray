"""Polish user interface."""
import ast
from pathlib import Path

import pytest

import headset_logic as hl
import i18n
import panel as panel_module
from conftest import wait_until

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def english_afterwards():
    yield
    i18n.set_language(i18n.ENGLISH)


def test_every_translated_text_exists():
    """Each tr("...") literal in the code has a Polish translation."""
    missing = set()
    for name in ("panel.py", "tray_app.py"):
        tree = ast.parse((ROOT / name).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "tr"
                    and node.args and isinstance(node.args[0], ast.Constant)):
                if node.args[0].value not in i18n.PL:
                    missing.add(node.args[0].value)
    assert not missing


def test_data_names_are_translated():
    names = list(hl.CHARGING_STATES.values()) + ["Charge error"] + list(hl.COLORS.values())
    names += list(panel_module.STATUS_FIELDS) + list(panel_module.INFO_FIELDS)
    names += list(panel_module.SETTING_LABELS.values()) + [label for _, label in panel_module.CHART_RANGES]
    names += [label for code, label in i18n.LANGUAGES if code == i18n.AUTO]
    assert [n for n in names if n not in i18n.PL] == []


def test_resolve_auto(monkeypatch):
    class Locale:
        def __init__(self, name):
            self._name = name

        def name(self):
            return self._name

    monkeypatch.setattr(i18n.QLocale, "system", staticmethod(lambda: Locale("pl_PL")))
    assert i18n.resolve(i18n.AUTO) == i18n.POLISH
    monkeypatch.setattr(i18n.QLocale, "system", staticmethod(lambda: Locale("de_DE")))
    assert i18n.resolve(i18n.AUTO) == i18n.ENGLISH


def test_switch_language_rebuilds_menu_and_panel(app):
    app.show_panel()
    old_panel = app.panel
    old_panel.tabs.setCurrentIndex(2)
    old_panel._set_chart_range(168)
    app.on_language(i18n.POLISH)
    assert app.settings.language == "pl"
    assert app.menu.defaultAction().text() == "Panel słuchawek..."
    assert app.connection_info.text() == "Słuchawki połączone"
    assert app.charging_info.text() == "Ładowanie: Nie ładuje się"
    new = app.panel
    assert new is not old_panel and new.isVisible()
    assert new.tabs.tabText(0) == "Stan" and new.tabs.currentIndex() == 2
    assert new.chart.hours == 168
    assert new.info_values["Colour"].text() == "Czarno-czerwony"
    assert new.shutdown_group.button(0).text() == "Nigdy"
    app.on_language(i18n.ENGLISH)
    assert app.menu.defaultAction().text() == "Headset panel..."
    assert wait_until(lambda: app.panel.tabs.tabText(0) == "Status")


def test_language_from_panel(app):
    app.show_panel()
    panel = app.panel
    panel.language_combo.setCurrentIndex(panel.language_combo.findData("pl"))
    panel.language_combo.activated.emit(panel.language_combo.currentIndex())
    assert wait_until(lambda: app.panel is not panel)
    assert app.panel.tabs.tabText(3) == "Ustawienia"
    assert [a.data() for a in app.language_group.actions() if a.isChecked()] == ["pl"]
