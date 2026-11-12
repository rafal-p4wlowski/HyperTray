import pytest
from PyQt6.QtGui import QAction, QActionGroup
from PyQt6.QtWidgets import QMenu

from tray_app import HeadsetApp
from ui_components import create_qicon, get_battery_color


def solid_colors(icon):
    img = icon.pixmap(64, 64).toImage()
    return {img.pixelColor(x, y).name() for x in range(64) for y in range(64)
            if img.pixelColor(x, y).alpha() == 255}


@pytest.mark.parametrize("level, color", [(None, "#9ca3af"), (80, "#22c55e"), (42, "#f59e0b"), (10, "#ef4444")])
def test_battery_colors_are_not_swapped(qapp, level, color):
    assert get_battery_color(level).lower() == color
    assert color in solid_colors(create_qicon("88", get_battery_color(level)))


GREEN, YELLOW, RED = "#22c55e", "#facc15", "#ef4444"


@pytest.mark.parametrize("charging, muted, present, absent", [
    (False, False, {GREEN}, {YELLOW, RED}),        # digits
    (True, False, {YELLOW}, {GREEN, RED}),         # bolt replaces the digits
    (False, True, {RED}, {GREEN, YELLOW}),         # crossed-out mic replaces the digits
    (True, True, {RED}, {GREEN, YELLOW}),          # muted takes precedence over charging
])
def test_status_symbol_replaces_digits(qapp, charging, muted, present, absent):
    colors = solid_colors(create_qicon("50", "#22C55E", charging=charging, muted=muted))
    assert present <= colors
    assert not (absent & colors)


def make_group(values):
    menu = QMenu()
    group = QActionGroup(menu)
    for v in values:
        act = QAction(str(v), group)
        act.setCheckable(True)
        act.setData(v)
    return menu, group


def test_choice_group_keeps_a_single_check(qapp):
    menu, group = make_group([0, 50, 100, 200])
    checked = lambda: [a.data() for a in group.actions() if a.isChecked()]
    HeadsetApp._check_choice(group, 50)
    group.actions()[3].trigger()                      # user picks 200
    assert checked() == [200]
    HeadsetApp._check_choice(group, 77)               # unknown value from the headset
    assert checked() == []
    HeadsetApp._check_choice(group, 100)
    group.actions()[0].trigger()
    assert checked() == [0]
