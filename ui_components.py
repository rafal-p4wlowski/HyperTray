import os
from PIL import Image, ImageDraw, ImageFont
from PyQt6.QtWidgets import QMenu
from PyQt6.QtGui import QIcon, QPixmap, QImage
from PyQt6.QtCore import Qt

# --- UI HELPER ---
def get_battery_color(level):
    if level is None: return "#9CA3AF"
    if level >= 60: return "#22C55E"
    if level >= 25: return "#F59E0B"
    return "#EF4444"

def create_qicon(text, color_hex):
    image = Image.new('RGBA', (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    try: font = ImageFont.truetype("arialbd.ttf", 44)
    except: font = ImageFont.load_default()
    bbox = draw.textbbox((0, 0), text, font=font)
    w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text(((64-w)/2, (64-h)/2 - 5), text, font=font, fill=color_hex)
    data = image.tobytes("raw", "RGBA")
    qim = QImage(data, image.size[0], image.size[1], QImage.Format.Format_ARGB32).copy()
    return QIcon(QPixmap.fromImage(qim))

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
