"""Draws assets/terjiman.png and assets/terjiman.ico with Qt, so no extra packages are needed.

The sky blue of East Turkistan's flag, the Kok Bayraq (#0099FF, the same as T-Player), with a white speech bubble
that holds the letter te, the first letter of the Uyghur word for translator.

    .venv\\Scripts\\python.exe tools\\make_icon.py
"""
import struct
import sys
from pathlib import Path

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QGuiApplication, QImage, QPainter, QPainterPath

ROOT = Path(__file__).resolve().parents[1]
SIZE = 1024                                     # drawn large, then shrunk, for smooth edges
BLUE = QColor(0, 153, 255)
SIZES = (16, 20, 24, 32, 40, 48, 64, 96, 128, 256)


def draw() -> QImage:
    image = QImage(SIZE, SIZE, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(BLUE)
    painter.drawRoundedRect(QRectF(0, 0, SIZE, SIZE), SIZE * 0.225, SIZE * 0.225)

    body = QRectF(SIZE * 0.16, SIZE * 0.18, SIZE * 0.68, SIZE * 0.52)
    bubble = QPainterPath()
    bubble.addRoundedRect(body, SIZE * 0.15, SIZE * 0.15)
    tail = QPainterPath()
    tail.moveTo(SIZE * 0.30, SIZE * 0.62)
    tail.lineTo(SIZE * 0.24, SIZE * 0.85)
    tail.lineTo(SIZE * 0.50, SIZE * 0.66)
    tail.closeSubpath()
    painter.setBrush(QColor("white"))
    painter.drawPath(bubble.united(tail))

    font = QFont("Microsoft Uighur")
    font.setPixelSize(int(SIZE * 0.70))
    font.setBold(True)
    letter = QPainterPath()
    letter.addText(0, 0, font, "ت")         # ت, drawn as its outline so it can be centred exactly
    letter.translate(body.center() - letter.boundingRect().center())
    painter.fillPath(letter, BLUE)
    painter.end()
    return image


def shrink(image: QImage, size: int) -> QImage:
    while image.width() > size * 2:              # halve step by step: smoother than one big jump
        image = image.scaled(image.width() // 2, image.height() // 2, Qt.AspectRatioMode.IgnoreAspectRatio,
                             Qt.TransformationMode.SmoothTransformation)
    return image.scaled(size, size, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)


def png(image: QImage) -> bytes:
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    return bytes(data)


def ico(images: list[QImage]) -> bytes:
    """A .ico file whose pictures are stored as PNG (Windows Vista and later read these)."""
    blobs = [png(image) for image in images]
    offset = 6 + 16 * len(blobs)
    header, entries, body = struct.pack("<HHH", 0, 1, len(blobs)), b"", b""
    for image, blob in zip(images, blobs):
        side = image.width() if image.width() < 256 else 0
        entries += struct.pack("<BBBBHHII", side, side, 0, 0, 1, 32, len(blob), offset + len(body))
        body += blob
    return header + entries + body


if __name__ == "__main__":
    app = QGuiApplication(sys.argv)
    big = draw()
    assets = ROOT / "assets"
    assets.mkdir(exist_ok=True)
    shrink(big, 256).save(str(assets / "terjiman.png"))
    (assets / "terjiman.ico").write_bytes(ico([shrink(big, s) for s in SIZES]))
    print("wrote", assets / "terjiman.png", "and", assets / "terjiman.ico")
