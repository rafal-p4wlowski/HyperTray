from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFont, QFontMetrics, QIcon, QPainter, QPixmap

ICON_SIZE = 64


def get_battery_color(level):
    if level is None: return "#9CA3AF"
    if level >= 60: return "#22C55E"
    if level >= 25: return "#F59E0B"
    return "#EF4444"


def create_qicon(text, color_hex):
    """Render `text` as a tray icon, shrinking the font so e.g. "100" fits."""
    pixmap = QPixmap(ICON_SIZE, ICON_SIZE)
    pixmap.fill(Qt.GlobalColor.transparent)

    font = QFont("Segoe UI")
    font.setBold(True)
    size = 48
    while size > 12:
        font.setPixelSize(size)
        if QFontMetrics(font).horizontalAdvance(text) <= ICON_SIZE - 2:
            break
        size -= 2

    painter = QPainter(pixmap)
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
