"""Regenerate the Celsiview brand assets (icon + logo, @1x + @2x).

Run from the repo root:

    pipenv run python scripts/generate_brand.py

Outputs are written to custom_components/celsiview/brand/ and are picked up
automatically by Home Assistant (>= 2026.3), HACS, and GPM via the bundled-
brands convention. Requires Pillow and DejaVu Sans Bold installed on the
host (Debian/Ubuntu: apt install fonts-dejavu-core).
"""
from __future__ import annotations

import os
from PIL import Image, ImageDraw, ImageFont

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(REPO_ROOT, "custom_components", "celsiview", "brand")

FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"


def hx(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


BG1 = hx("#0E7490")       # rounded-square gradient top-left (cyan-700)
BG2 = hx("#164E63")       # rounded-square gradient bottom-right (cyan-900)
GLASS = hx("#F8FAFC")     # thermometer body
MERCURY_TOP = hx("#FBBF24")   # amber-400
MERCURY_BOT = hx("#F97316")   # orange-500
WORDMARK = hx("#0F172A")      # slate-900 fill on wordmark
STROKE = hx("#FFFFFF")        # light halo around wordmark — readable on dark bg


def gradient_diag(size: tuple[int, int], c1, c2) -> Image.Image:
    w, h = size
    img = Image.new("RGBA", size, c1 + (255,))
    d = ImageDraw.Draw(img)
    maxd = w + h - 2
    for i in range(maxd + 1):
        t = i / maxd
        c = tuple(int(c1[k] + (c2[k] - c1[k]) * t) for k in range(3)) + (255,)
        x0 = max(0, i - (h - 1))
        y0 = min(i, h - 1)
        x1 = min(i, w - 1)
        y1 = max(0, i - (w - 1))
        d.line([(x0, y0), (x1, y1)], fill=c)
    return img


def gradient_vert(size: tuple[int, int], c1, c2) -> Image.Image:
    w, h = size
    img = Image.new("RGBA", size, c1 + (255,))
    d = ImageDraw.Draw(img)
    for y in range(h):
        t = y / max(1, h - 1)
        c = tuple(int(c1[k] + (c2[k] - c1[k]) * t) for k in range(3)) + (255,)
        d.line([(0, y), (w - 1, y)], fill=c)
    return img


def rounded_mask(size: tuple[int, int], radius: int) -> Image.Image:
    m = Image.new("L", size, 0)
    ImageDraw.Draw(m).rounded_rectangle(
        [(0, 0), (size[0] - 1, size[1] - 1)], radius, fill=255
    )
    return m


def draw_thermometer(canvas: Image.Image, cx: int, cy: int, h: int) -> None:
    d = ImageDraw.Draw(canvas)
    bulb_r = int(h * 0.17)
    stem_w = int(h * 0.15)
    top = cy - int(h * 0.45)
    bulb_cy = cy + int(h * 0.30)

    d.rounded_rectangle(
        [(cx - stem_w // 2, top), (cx + stem_w // 2, bulb_cy + bulb_r)],
        radius=stem_w // 2, fill=GLASS + (255,),
    )
    d.ellipse(
        [(cx - bulb_r, bulb_cy - bulb_r), (cx + bulb_r, bulb_cy + bulb_r)],
        fill=GLASS + (255,),
    )

    merc_w = max(6, int(stem_w * 0.50))
    merc_r = int(bulb_r * 0.72)
    merc_bot = bulb_cy + merc_r
    merc_top_y = int(bulb_cy - (bulb_cy - top) * 0.58)

    merc_h = merc_bot - merc_top_y
    merc_canvas = gradient_vert((merc_w, merc_h), MERCURY_TOP, MERCURY_BOT)
    mask = Image.new("L", (merc_w, merc_h), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        [(0, 0), (merc_w - 1, merc_h - 1)], radius=merc_w // 2, fill=255,
    )
    canvas.paste(merc_canvas, (cx - merc_w // 2, merc_top_y), mask)

    mid = tuple((MERCURY_TOP[k] + MERCURY_BOT[k]) // 2 for k in range(3))
    d.ellipse(
        [(cx - merc_r, bulb_cy - merc_r), (cx + merc_r, bulb_cy + merc_r)],
        fill=mid + (255,),
    )

    tick_len = int(h * 0.055)
    tick_thick = max(3, int(h * 0.012))
    gap = int(h * 0.028)
    for i in range(4):
        y = top + int((bulb_cy - top) * (i + 1) / 5)
        for sx in (
            (cx + stem_w // 2 + gap, cx + stem_w // 2 + gap + tick_len),
            (cx - stem_w // 2 - gap - tick_len, cx - stem_w // 2 - gap),
        ):
            d.rounded_rectangle(
                [(sx[0], y - tick_thick // 2), (sx[1], y + tick_thick // 2)],
                radius=tick_thick // 2, fill=GLASS + (220,),
            )


def make_icon(size: int = 1024) -> Image.Image:
    bg = gradient_diag((size, size), BG1, BG2)
    icon = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    icon.paste(bg, (0, 0), rounded_mask((size, size), int(size * 0.22)))
    draw_thermometer(icon, size // 2, size // 2, h=int(size * 0.78))
    return icon


def make_logo(icon: Image.Image, text: str = "Celsiview") -> Image.Image:
    ih = icon.height
    pad = int(ih * 0.06)
    inner_icon = ih - 2 * pad

    font_size = int(ih * 0.46)
    font = ImageFont.truetype(FONT, font_size)
    stroke_w = max(2, int(font_size * 0.032))

    tmp = Image.new("RGBA", (10, 10))
    td = ImageDraw.Draw(tmp)
    bbox = td.textbbox((0, 0), text, font=font, stroke_width=stroke_w)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]

    icon_right = pad + inner_icon + int(ih * 0.08)
    total_w = icon_right + tw + pad
    logo = Image.new("RGBA", (total_w, ih), (0, 0, 0, 0))

    ir = icon.resize((inner_icon, inner_icon), Image.LANCZOS)
    logo.paste(ir, (pad, pad), ir)

    d = ImageDraw.Draw(logo)
    tx = icon_right - bbox[0]
    ty = (ih - th) // 2 - bbox[1]
    d.text(
        (tx, ty), text, font=font,
        fill=WORDMARK + (255,),
        stroke_width=stroke_w,
        stroke_fill=STROKE + (255,),
    )
    return logo


def save_square(img: Image.Image, name: str) -> None:
    for variant, target in ((f"{name}.png", 256), (f"{name}@2x.png", 512)):
        img.resize((target, target), Image.LANCZOS).save(
            os.path.join(OUT, variant), optimize=True
        )


def save_landscape(img: Image.Image, name: str) -> None:
    w, h = img.size
    for variant, target_h in ((f"{name}.png", 256), (f"{name}@2x.png", 512)):
        img.resize((int(w * target_h / h), target_h), Image.LANCZOS).save(
            os.path.join(OUT, variant), optimize=True
        )


def main() -> None:
    os.makedirs(OUT, exist_ok=True)
    icon_hi = make_icon(1024)
    save_square(icon_hi, "icon")
    save_landscape(make_logo(icon_hi, "Celsiview"), "logo")
    for f in sorted(os.listdir(OUT)):
        p = os.path.join(OUT, f)
        print(f"{f}: {Image.open(p).size} {os.path.getsize(p)} bytes")


if __name__ == "__main__":
    main()
