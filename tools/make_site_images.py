"""Regenerate website images (favicons, screenshots, social preview) from the
app icon and the screenshots in docs/img.

Run after changing the icon or the screenshots:  python tools/make_site_images.py
Requires Pillow and the Inter font (falls back to the default font).
"""

import os

from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
A = os.path.join(ROOT, "site", "assets")
ICON = os.path.join(ROOT, "comitra", "ui", "resources", "icon.png")
SHOTS = {"screenshot-light": "docs/img/search-light.png", "screenshot-dark": "docs/img/grouped-dark.png"}


def font(name: str, size: int):
    for base in ("/usr/share/fonts/opentype/inter/", "/Library/Fonts/", "C:/Windows/Fonts/"):
        try:
            return ImageFont.truetype(os.path.join(base, name), size)
        except OSError:
            continue
    return ImageFont.load_default()


def main() -> None:
    os.makedirs(A, exist_ok=True)
    icon = Image.open(ICON).convert("RGBA")
    for size, name in ((32, "favicon-32.png"), (180, "apple-touch-icon.png"), (192, "icon-192.png"), (512, "icon-512.png")):
        icon.resize((size, size), Image.LANCZOS).save(os.path.join(A, name))
    icon.resize((64, 64), Image.LANCZOS).save(os.path.join(A, "favicon.ico"), sizes=[(16, 16), (32, 32), (48, 48)])

    for dst, src in SHOTS.items():
        im = Image.open(os.path.join(ROOT, src)).convert("RGB")
        im.save(os.path.join(A, dst + ".png"), optimize=True)
        im.resize((1200, int(im.height * 1200 / im.width)), Image.LANCZOS).save(os.path.join(A, dst + ".webp"), quality=86)

    w, h = 1200, 630
    og = Image.new("RGB", (w, h))
    d = ImageDraw.Draw(og)
    for y in range(h):
        t = y / h
        d.line([(0, y), (w, y)], fill=(int(17 + 18 * t), int(16 + 12 * t), int(46 + 50 * t)))
    shot = Image.open(os.path.join(ROOT, SHOTS["screenshot-dark"])).convert("RGB")
    shot = shot.resize((760, int(shot.height * 760 / shot.width)), Image.LANCZOS)
    mask = Image.new("L", shot.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, *shot.size], 18, fill=255)
    og.paste(shot, (500, 150), mask)
    ic = icon.resize((120, 120), Image.LANCZOS)
    og.paste(ic, (64, 70), ic)
    d.text((64, 220), "Comitra", font=font("Inter-Bold.otf", 78), fill="white")
    y = 320
    for line in ("Search commits across", "all your git repos"):
        d.text((64, y), line, font=font("Inter-Medium.otf", 34), fill="#e0e7ff")
        y += 46
    d.text((64, 450), "Windows · macOS · Linux", font=font("Inter-Regular.otf", 24), fill="#fbbf24")
    d.text((64, 486), "Free · Open source · Offline", font=font("Inter-Regular.otf", 24), fill="#a5b4fc")
    og.save(os.path.join(A, "og-image.png"), optimize=True)
    print("site images written to", A)


if __name__ == "__main__":
    main()
