"""Tray icon: a battery ring around a device glyph.

The presentation follows HaloBattery (https://github.com/HeyOkay/HaloBattery, MIT):
a dim track with the charge arc filling clockwise from the top, the glyph in the
taskbar colour (white on a dark taskbar, black on a light one), the arc amber close
to the low-battery threshold, red at or below it and green while charging. With no
reading (asleep, off, not found) the icon is translucent and has no arc.

The glyphs are Lucide "headphones" and, while the microphone is muted, a red
"mic-off" (https://lucide.dev, ISC, see licenses/), redrawn from their 24x24 SVG
paths so no SVG module has to be bundled.
"""
import sys

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap

ICON_SIZES = (16, 20, 24, 32, 40, 48, 64)   # tray sizes from 100% to 400% scaling
UNIT = 64.0                                 # the icon is designed on a 64x64 grid

RING_RADIUS = 29.5                          # centre of the ring stroke
RING_WIDTH = 4.0                            # one pixel at the 16 px tray size
NEUTRAL_OPACITY = 0.9                       # like the softer Windows tray ink
TRACK_OPACITY = (70 / 255, 45 / 255)        # track: (active, inactive)
INACTIVE_OPACITY = 110 / 255

RED = QColor(232, 17, 35)
AMBER = QColor(255, 185, 0)
GREEN = QColor(16, 196, 80)

GLYPH_FIT = 0.46                            # glyph size relative to the Lucide 24-unit grid at 0.5


def taskbar_is_light():
    if sys.platform != "win32":
        return False
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as key:
            return winreg.QueryValueEx(key, "SystemUsesLightTheme")[0] == 1
    except OSError:
        return False


def arc_color(level, charging, low, fg):
    """Green while charging, red at or below the threshold, amber 10 points above it."""
    if charging:
        return GREEN
    threshold = max(low or 0, 10)
    if level is not None and level <= threshold:
        return RED
    if level is not None and level <= threshold + 10:
        return AMBER
    return fg


def _headphones_path():
    """Lucide headphones: one stroke over the headband and both ear cups."""
    path = QPainterPath(QPointF(3, 14))
    path.lineTo(6, 14)
    path.arcTo(QRectF(4, 14, 4, 4), 90, -90)
    path.lineTo(8, 19)
    path.arcTo(QRectF(4, 17, 4, 4), 0, -90)
    path.lineTo(5, 21)
    path.arcTo(QRectF(3, 17, 4, 4), 270, -90)
    path.lineTo(3, 12)
    path.arcTo(QRectF(3, 3, 18, 18), 180, -180)
    path.lineTo(21, 19)
    path.arcTo(QRectF(17, 17, 4, 4), 0, -90)
    path.lineTo(18, 21)
    path.arcTo(QRectF(16, 17, 4, 4), 270, -90)
    path.lineTo(16, 16)
    path.arcTo(QRectF(16, 14, 4, 4), 180, -90)
    path.lineTo(21, 14)
    return path


def _mic_off_path():
    """Lucide mic-off: a microphone with a gap where the slash crosses it."""
    path = QPainterPath()
    path.moveTo(12, 19)
    path.lineTo(12, 22)                                   # stand
    path.moveTo(15, 9.34)
    path.lineTo(15, 5)
    path.arcTo(QRectF(9, 2, 6, 6), 0, 153.6)              # capsule top
    path.moveTo(16.95, 16.95)
    path.arcTo(QRectF(5, 5, 14, 14), -45, -135)           # cradle, left part
    path.lineTo(5, 10)
    path.moveTo(18.89, 13.23)
    path.arcTo(QRectF(5, 5, 14, 14), -10.12, 10.12)       # cradle, right part
    path.lineTo(19, 10)
    path.moveTo(2, 2)
    path.lineTo(22, 22)                                   # slash
    path.moveTo(9, 9)
    path.lineTo(9, 12)
    path.arcTo(QRectF(9, 9, 6, 6), 180, 135)              # capsule bottom
    return path


HEADPHONES = _headphones_path()
MIC_OFF = _mic_off_path()


def _draw_glyph(painter, path, color, opacity):
    scale = 4 * GLYPH_FIT                   # 24 Lucide units -> 64-unit icon grid
    painter.save()
    painter.translate(32, 32)
    painter.scale(scale, scale)
    painter.translate(-12, -12)
    painter.setOpacity(opacity)
    painter.setPen(QPen(color, RING_WIDTH / scale, Qt.PenStyle.SolidLine,
                        Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawPath(path)
    painter.restore()


def render_icon(size, level, charging=False, active=True, low=20, light_taskbar=False, muted=False):
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.scale(size / UNIT, size / UNIT)

    fg = QColor(0, 0, 0) if light_taskbar else QColor(255, 255, 255)
    active = active and level is not None
    ring = QRectF(32 - RING_RADIUS, 32 - RING_RADIUS, 2 * RING_RADIUS, 2 * RING_RADIUS)

    # track
    painter.setOpacity(NEUTRAL_OPACITY * TRACK_OPACITY[0 if active else 1])
    painter.setPen(QPen(fg, RING_WIDTH))
    painter.drawEllipse(ring)

    # charge arc
    if active and level > 0:
        color = arc_color(level, charging, low, fg)
        painter.setOpacity(NEUTRAL_OPACITY if color == fg else 1.0)
        pen = QPen(color, RING_WIDTH, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        if level >= 100:
            painter.drawEllipse(ring)
        else:
            span = 360 * max(level, 2) / 100
            painter.drawArc(ring, 90 * 16, -round(span * 16))

    if muted:
        _draw_glyph(painter, MIC_OFF, RED, 1.0)
    else:
        _draw_glyph(painter, HEADPHONES, fg, NEUTRAL_OPACITY * (1.0 if active else INACTIVE_OPACITY))
    painter.end()
    return pixmap


def create_tray_icon(level, charging=False, active=True, low=20, light_taskbar=None, muted=False):
    """QIcon with every tray size drawn separately, so the 1 px ring stays sharp.
    muted swaps the headphones for a red crossed-out microphone."""
    if light_taskbar is None:
        light_taskbar = taskbar_is_light()
    icon = QIcon()
    for size in ICON_SIZES:
        icon.addPixmap(render_icon(size, level, charging, active, low, light_taskbar, muted))
    return icon


# --- STYLESHEET ---
DARK_MENU_STYLE = """
QMenu {
    background-color: #1e1e1e;
    color: #e0e0e0;
    border: 1px solid #3d3d3d;
    padding: 4px;
    font-family: 'Segoe UI', Arial;
    font-size: 13px;
}
QMenu::item {
    background-color: transparent;
    padding: 6px 30px 6px 15px;
    border-radius: 4px;
    margin: 1px 4px;
}
QMenu::item:selected {
    background-color: #3d3d3d;
    color: #ffffff;
}
QMenu::item:disabled {
    color: #717171;
}
QMenu::separator {
    height: 1px;
    background: #3d3d3d;
    margin: 4px 8px;
}
"""
