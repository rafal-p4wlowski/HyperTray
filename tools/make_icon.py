"""Generate assets/icon.ico (application icon: a pair of headphones).

Run from the project root:  .venv\\Scripts\\python tools\\make_icon.py
Each size is drawn separately (thicker strokes for small sizes) and stored as
a PNG entry in the .ico container.
"""
import os
import struct
import sys

from PyQt6.QtCore import QBuffer, QByteArray, QIODevice, QRectF, Qt
from PyQt6.QtGui import QColor, QGuiApplication, QImage, QPainter, QPainterPath, QPen

SIZES = (16, 24, 32, 48, 64, 128, 256)
BACKGROUND = QColor("#1E1E1E")
ACCENT = QColor("#22C55E")


def draw(size):
    img = QImage(size, size, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.scale(size / 64, size / 64)

    # rounded square background
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(BACKGROUND)
    p.drawRoundedRect(QRectF(1, 1, 62, 62), 14, 14)

    # headband
    band = 7 if size <= 24 else 5.5
    p.setPen(QPen(ACCENT, band, cap=Qt.PenCapStyle.RoundCap))
    p.setBrush(Qt.BrushStyle.NoBrush)
    path = QPainterPath()
    path.moveTo(14, 38)
    path.arcTo(QRectF(14, 11, 36, 40), 180, -180)
    p.drawPath(path)

    # ear cups
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(ACCENT)
    p.drawRoundedRect(QRectF(8, 33, 14, 22), 5, 5)
    p.drawRoundedRect(QRectF(42, 33, 14, 22), 5, 5)
    p.end()
    return img


def png_bytes(img):
    data = QByteArray()
    buf = QBuffer(data)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG")
    return bytes(data)


def write_ico(path, images):
    entries = [(img.width(), png_bytes(img)) for img in images]
    header = struct.pack("<HHH", 0, 1, len(entries))
    offset = 6 + 16 * len(entries)
    directory, blobs = b"", b""
    for size, blob in entries:
        dim = 0 if size >= 256 else size  # 0 means 256 in the ICO format
        directory += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(blob), offset)
        blobs += blob
        offset += len(blob)
    with open(path, "wb") as f:
        f.write(header + directory + blobs)


def main():
    app = QGuiApplication(sys.argv)  # noqa: F841 (needed for QPainter)
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    out = os.path.join(root, "assets", "icon.ico")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    write_ico(out, [draw(s) for s in SIZES])
    print("written", out)


if __name__ == "__main__":
    main()
