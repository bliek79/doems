"""Rebuild DOEMS technical brand variants from the single approved brand logo."""

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


def _fit_complete_logo_on_square(image: Image.Image, size: int) -> Image.Image:
    """Fit the complete logo on a transparent square without cropping it."""
    margin = max(8, round(size * 0.06))
    available = size - (2 * margin)
    scale = min(available / image.width, available / image.height)
    target = (
        max(1, round(image.width * scale)),
        max(1, round(image.height * scale)),
    )
    resized = image.resize(target, Image.Resampling.LANCZOS)
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    canvas.alpha_composite(
        resized,
        ((size - resized.width) // 2, (size - resized.height) // 2),
    )
    return canvas


def _dark_variant(logo: Image.Image) -> Image.Image:
    """Keep the same logo geometry and adapt only dark text for dark mode."""
    dark_logo = logo.copy()
    pixels = dark_logo.load()
    for y in range(dark_logo.height):
        for x in range(175, dark_logo.width):
            red, green, blue, alpha = pixels[x, y]
            if alpha and red < 35 and green < 60 and blue < 85:
                pixels[x, y] = (245, 248, 250, alpha)
    return dark_logo


def main() -> None:
    source_bytes = SOURCE.read_bytes()
    actual_sha = hashlib.sha256(source_bytes).hexdigest()
    if actual_sha != APPROVED_LOGO_SHA256:
        raise SystemExit(f"Refusing to rebuild from unapproved logo.png: {actual_sha}")

    logo = Image.open(SOURCE).convert("RGBA")
    if logo.size != (640, 192):
        raise SystemExit(f"Unexpected approved logo dimensions: {logo.size}")

    dark_logo = _dark_variant(logo)

    # There is one visual DOEMS brand logo. Home Assistant's square icon
    # files are only technical renderings of that complete logo.
    _save(_fit_complete_logo_on_square(logo, 256), "icon.png")
    _save(_fit_complete_logo_on_square(logo, 512), "icon@2x.png")
    _save(_fit_complete_logo_on_square(dark_logo, 256), "dark_icon.png")
    _save(_fit_complete_logo_on_square(dark_logo, 512), "dark_icon@2x.png")

    _save(logo.resize((1280, 384), Image.Resampling.LANCZOS), "logo@2x.png")
    _save(dark_logo, "dark_logo.png")
    _save(dark_logo.resize((1280, 384), Image.Resampling.LANCZOS), "dark_logo@2x.png")


if __name__ == "__main__":
    main()
