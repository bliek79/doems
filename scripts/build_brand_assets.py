"""Rebuild DOEMS local brand variants from the approved light logo artwork."""

from __future__ import annotations

import hashlib
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
BRAND = ROOT / "custom_components" / "doems" / "brand"
SOURCE = BRAND / "logo.png"
APPROVED_LOGO_SHA256 = "c2146ed44f0bfb9b40d2a1d21d2cd8e1f5bf22858fc13cdbe308eb54cadb1a8b"


def _save(image: Image.Image, name: str) -> None:
    image.save(BRAND / name, format="PNG", optimize=True)


def main() -> None:
    source_bytes = SOURCE.read_bytes()
    actual_sha = hashlib.sha256(source_bytes).hexdigest()
    if actual_sha != APPROVED_LOGO_SHA256:
        raise SystemExit(f"Refusing to rebuild from unapproved logo.png: {actual_sha}")

    logo = Image.open(SOURCE).convert("RGBA")
    if logo.size != (640, 192):
        raise SystemExit(f"Unexpected approved logo dimensions: {logo.size}")

    artwork = logo.crop((13, 25, 156, 168))
    icon_base = Image.new("RGBA", (192, 192), (0, 0, 0, 0))
    icon_base.alpha_composite(artwork, ((192 - artwork.width) // 2, (192 - artwork.height) // 2))
    _save(icon_base.resize((256, 256), Image.Resampling.LANCZOS), "icon.png")
    _save(icon_base.resize((512, 512), Image.Resampling.LANCZOS), "icon@2x.png")
    _save(icon_base.resize((256, 256), Image.Resampling.LANCZOS), "dark_icon.png")
    _save(icon_base.resize((512, 512), Image.Resampling.LANCZOS), "dark_icon@2x.png")
    _save(logo.resize((1280, 384), Image.Resampling.LANCZOS), "logo@2x.png")

    dark_logo = logo.copy()
    pixels = dark_logo.load()
    for y in range(dark_logo.height):
        for x in range(175, dark_logo.width):
            red, green, blue, alpha = pixels[x, y]
            if alpha and red < 35 and green < 60 and blue < 85:
                pixels[x, y] = (245, 248, 250, alpha)
    _save(dark_logo, "dark_logo.png")
    _save(dark_logo.resize((1280, 384), Image.Resampling.LANCZOS), "dark_logo@2x.png")


if __name__ == "__main__":
    main()
