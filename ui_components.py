from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QFont, QFontMetrics, QIcon, QPainter, QPen, QPixmap, QPolygonF

ICON_SIZE = 64
BADGE_OUTLINE = QColor("#111111")
CHARGING_COLOR = QColor("#FACC15")
MUTED_COLOR = QColor("#EF4444")


def get_battery_color(level):
    if level is None: return "#9CA3AF"
    if level >= 60: return "#22C55E"
    if level >= 25: return "#F59E0B"
    return "#EF4444"


def _draw_muted_mic(painter):
    """Red crossed-out microphone filling the whole icon (mic muted)."""
    # Thick strokes: Windows shows tray icons at 16-32 px.
    red = QPen(MUTED_COLOR, 8, cap=Qt.PenCapStyle.RoundCap)
    painter.setPen(red)
    painter.setBrush(Qt.BrushStyle.NoBrush)
    painter.drawArc(QRectF(10, 12, 44, 36), 180 * 16, 180 * 16)       # holder
    painter.drawLine(QPointF(32, 49), QPointF(32, 56))                # stand
    painter.drawLine(QPointF(19, 59), QPointF(45, 59))                # base
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(MUTED_COLOR)
    painter.drawRoundedRect(QRectF(21, 2, 22, 38), 11, 11)            # capsule
    # Slash with a transparent gap around it, readable on light and dark taskbars.
    slash = (QPointF(8, 6), QPointF(56, 58))
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
    painter.setPen(QPen(Qt.GlobalColor.black, 13, cap=Qt.PenCapStyle.RoundCap))
    painter.drawLine(*slash)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
    painter.setPen(QPen(MUTED_COLOR, 7, cap=Qt.PenCapStyle.RoundCap))
    painter.drawLine(*slash)


def _draw_big_bolt(painter):
    """Yellow lightning bolt filling the whole icon (charging)."""
    bolt = QPolygonF([QPointF(x, y) for x, y in
                      ((44, 1), (7, 38), (28, 38), (19, 63), (57, 23), (36, 23), (52, 1))])
    painter.setPen(QPen(BADGE_OUTLINE, 3, join=Qt.PenJoinStyle.RoundJoin))
    painter.setBrush(CHARGING_COLOR)
    painter.drawPolygon(bolt)


def create_qicon(text, color_hex, charging=False, muted=False):
    """Tray icon: the battery level as digits, or a full-size symbol that
    replaces them while the mic is muted (takes precedence) or charging."""
    pixmap = QPixmap(ICON_SIZE, ICON_SIZE)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    if muted:
        _draw_muted_mic(painter)
    elif charging:
        _draw_big_bolt(painter)
    else:
        font = QFont("Segoe UI")
        font.setBold(True)
        size = 48
        while size > 12:
            font.setPixelSize(size)
            if QFontMetrics(font).horizontalAdvance(text) <= ICON_SIZE - 2:
                break
            size -= 2
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        painter.setFont(font)
        painter.setPen(QColor(color_hex))
        painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, text)

    painter.end()
    return QIcon(pixmap)


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
