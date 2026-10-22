#!/usr/bin/env python3
"""Генерация kbdguard/preview.png (960x540) для реестра плагинов Noctalia."""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

W, H = 960, 540
ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "kbdguard" / "preview.png"

BG_TOP = (16, 17, 22)
BG_BOTTOM = (24, 27, 36)
CARD = (30, 33, 44)
CARD_SOFT = (38, 42, 56)
FG = (232, 234, 240)
MUTED = (150, 156, 172)
ACCENT = (122, 162, 247)
OFF = (240, 113, 120)


def font(size: int, bold: bool = False):
    candidates = [
        "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/TTF/DejaVuSans.ttf",
        "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/noto/NotoSans-Bold.ttf" if bold else "/usr/share/fonts/noto/NotoSans-Regular.ttf",
    ]
    for path in candidates:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def gradient(size, top, bottom):
    img = Image.new("RGB", size, top)
    draw = ImageDraw.Draw(img)
    for y in range(size[1]):
        ratio = y / max(size[1] - 1, 1)
        color = tuple(int(top[i] + (bottom[i] - top[i]) * ratio) for i in range(3))
        draw.line([(0, y), (size[0], y)], fill=color)
    return img


def rounded(draw, box, radius, fill, outline=None, width=1):
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def keyboard_glyph(draw, x, y, w, h, color):
    """Пиктограмма клавиатуры, вписанная ровно в рамку w×h."""
    rounded(draw, (x, y, x + w, y + h), max(3, h // 4), None, color, 2)
    pad = max(2, round(w * 0.09))
    cols = 6
    gap = max(1, round(w * 0.03))
    key_w = (w - 2 * pad - (cols - 1) * gap) / cols
    key_h = max(2, (h - 2 * pad) / 3.4)
    for row in range(2):
        for col in range(cols):
            kx = x + pad + col * (key_w + gap)
            ky = y + pad + row * (key_h + gap)
            rounded(draw, (kx, ky, kx + key_w, ky + key_h), 1, color)
    space_y = y + h - pad - key_h
    rounded(draw, (x + pad + key_w, space_y, x + w - pad - key_w, space_y + key_h), 1, color)


def main() -> None:
    img = gradient((W, H), BG_TOP, BG_BOTTOM)
    draw = ImageDraw.Draw(img)

    # имитация бара сверху
    rounded(draw, (0, 0, W, 44), 0, (22, 24, 32))
    rounded(draw, (W - 120, 8, W - 30, 36), 8, CARD_SOFT)
    keyboard_glyph(draw, W - 108, 14, 26, 16, OFF)
    draw.text((W - 74, 16), "off", font=font(15), fill=OFF)

    # карточка панели
    card = (110, 96, 850, 452)
    rounded(draw, card, 22, CARD)

    # заголовок карточки
    keyboard_glyph(draw, 140, 124, 34, 22, OFF)
    draw.text((188, 118), "Keyboard", font=font(28, True), fill=FG)
    draw.text((188, 152), "internal switch off · external untouched",
              font=font(16), fill=MUTED)

    # главный тумблер
    rounded(draw, (140, 196, 820, 250), 12, CARD_SOFT)
    draw.text((162, 212), "Internal keyboard disabled", font=font(18), fill=FG)
    rounded(draw, (742, 208, 800, 238), 15, OFF)
    draw.ellipse((768, 211, 797, 235), fill=(255, 255, 255))

    # список устройств
    rows = [
        ("AT Translated Set 2 keyboard", "internal", "off", OFF),
        ("FBX50C Keyboard", "external", "on", ACCENT),
    ]
    y = 268
    for name, tag, state, color in rows:
        rounded(draw, (140, y, 820, y + 56), 12, CARD_SOFT)
        draw.text((162, y + 10), name, font=font(17), fill=FG)
        draw.text((162, y + 32), tag, font=font(13), fill=MUTED)
        rounded(draw, (700, y + 16, 800, y + 40), 12, color)
        draw.text((712, y + 19), "on" if state == "on" else "off",
                  font=font(14, True), fill=(20, 22, 30))
        y += 68

    # защита
    rounded(draw, (140, 404, 820, 442), 10, (44, 38, 34))
    draw.text((162, 414), "Protection: never disable the last keyboard",
              font=font(15), fill=(236, 200, 130))

    # нижняя подпись
    draw.text((110, 486), "Ctrl + Alt — переключить встроенную клавиатуру",
              font=font(20), fill=FG)
    draw.text((110, 514), "kbdguard · Noctalia Shell plugin + evdev daemon",
              font=font(14), fill=MUTED)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    img.save(OUT, "PNG")
    print(f"{OUT} ({img.size[0]}x{img.size[1]})")


if __name__ == "__main__":
    main()
