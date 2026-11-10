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


BADGE_COLUMN = 20  # width reserved on the right for the charging / muted badges


def _draw_bolt(painter):
    """Lightning bolt in the top-right corner (charging)."""
    bolt = QPolygonF([QPointF(x, y) for x, y in
                      ((57, 1), (45, 17), (53, 17), (48, 31), (62, 12), (55, 12), (62, 1))])
    painter.setPen(QPen(BADGE_OUTLINE, 2, join=Qt.PenJoinStyle.RoundJoin))
    painter.setBrush(CHARGING_COLOR)
    painter.drawPolygon(bolt)


def _draw_muted(painter):
    """Red disc with a white slash in the bottom-right corner (mic muted)."""
    painter.setPen(QPen(BADGE_OUTLINE, 2))
    painter.setBrush(MUTED_COLOR)
    painter.drawEllipse(QRectF(44, 37, 19, 19))
    painter.setPen(QPen(QColor("white"), 3, cap=Qt.PenCapStyle.RoundCap))
    painter.drawLine(QPointF(49, 42), QPointF(58, 51))


def create_qicon(text, color_hex, charging=False, muted=False):
    """Render `text` (battery level) as a tray icon, shrinking the font so e.g.
    "100" fits. Charging / mic-muted badges get their own column on the right
    so they never cover the digits."""
    pixmap = QPixmap(ICON_SIZE, ICON_SIZE)
    pixmap.fill(Qt.GlobalColor.transparent)
    badges = charging or muted
    text_rect = QRectF(0, 0, ICON_SIZE - (BADGE_COLUMN if badges else 0), ICON_SIZE)

    font = QFont("Segoe UI")
    font.setBold(True)
    size = 48
    while size > 12:
        font.setPixelSize(size)
        if QFontMetrics(font).horizontalAdvance(text) <= text_rect.width() - 1:
            break
        size -= 2

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    painter.setFont(font)
    painter.setPen(QColor(color_hex))
    painter.drawText(text_rect, Qt.AlignmentFlag.AlignCenter, text)
    if charging:
        _draw_bolt(painter)
    if muted:
        _draw_muted(painter)
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
