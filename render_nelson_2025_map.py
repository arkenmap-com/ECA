#!/usr/bin/env python3
"""Render a static companion map for the Nelson 2025 scenario probability surface."""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parent
STUDY = ROOT / "long-term" / "nelson-50km"
FUEL = STUDY / "data" / "derived" / "fuel_250m_50km.tif"
OUT = STUDY / "outputs"

COLORS = {
    -9999: (120, 120, 120), 2: (34, 104, 56), 3: (130, 198, 145), 4: (120, 140, 0),
    5: (216, 166, 225), 7: (108, 0, 237), 11: (120, 120, 120), 13: (184, 171, 123),
    31: (255, 255, 190), 101: (145, 145, 145), 102: (100, 205, 235), 105: (100, 205, 235),
    415: (255, 210, 129), 625: (255, 196, 96), 650: (255, 181, 62), 675: (255, 166, 18),
}


def fuel_values() -> np.ndarray:
    with tempfile.NamedTemporaryFile(suffix=".xyz", delete=False) as temp:
        xyz = Path(temp.name)
    try:
        subprocess.run(["gdal_translate", "-q", "-of", "XYZ", str(FUEL), str(xyz)], check=True)
        return np.loadtxt(xyz, usecols=2).astype(int).reshape(400, 400)
    finally:
        xyz.unlink(missing_ok=True)


def main() -> None:
    fuel = fuel_values()
    probability = np.loadtxt(OUT / "burn_probability.asc", skiprows=6)
    base = np.zeros((400, 400, 3), dtype=np.uint8)
    for value, color in COLORS.items():
        base[fuel == value] = color
    overlay = base.astype(float)
    mask = probability > 0
    strength = np.clip(probability / 0.013, 0, 1)[..., None]
    red = np.zeros_like(base, dtype=float)
    red[..., 0] = 189
    red[..., 1] = 0
    red[..., 2] = 38
    overlay[mask] = overlay[mask] * (1 - 0.82 * strength[mask]) + red[mask] * (0.82 * strength[mask])
    map_image = Image.fromarray(overlay.astype(np.uint8)).resize((1000, 1000), Image.Resampling.NEAREST)
    image = Image.new("RGB", (1370, 1000), "white")
    image.paste(map_image, (0, 0))
    draw = ImageDraw.Draw(image)
    title = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 23)
    text = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 15)
    small = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 13)
    x = 1025
    metadata = json.loads((OUT / "metadata.json").read_text())
    draw.text((x, 28), "Nelson 2025 scenario", font=title, fill="black")
    draw.text((x, 58), "Cell2Fire burn probability", font=text, fill="black")
    draw.text((x, 92), f"{metadata['completed_runs']:,} runs · 250 m cells", font=text, fill="black")
    draw.text((x, 125), "Burn probability overlay", font=text, fill="black")
    for y, color, label in ((153, (255, 255, 178), "0.1–0.5%"), (180, (254, 204, 92), "0.5–1%"), (207, (240, 59, 32), "1–1.3%")):
        draw.rectangle((x, y, x + 20, y + 20), fill=color)
        draw.text((x + 30, y + 2), label, font=text, fill="black")
    draw.text((x, 250), "Fuel classes", font=text, fill="black")
    legend = [(2, "C2 Boreal spruce"), (3, "C3 mature pine"), (4, "C4 immature pine"), (5, "C5 pine"), (7, "C7 Douglas-fir"), (13, "D1 deciduous"), (31, "O1a grass"), (415, "M1 15% conifer"), (625, "M1 25% conifer"), (650, "M1 50% conifer"), (675, "M1 75% conifer"), (102, "water / non-fuel")]
    for index, (code, label) in enumerate(legend):
        y = 280 + index * 28
        draw.rectangle((x, y, x + 20, y + 20), fill=COLORS[code])
        draw.text((x + 30, y + 2), label, font=small, fill="black")
    draw.multiline_text((x, 640), "Observed 2025 BCWS weather\n+historical ignition sample\n+current fuel landscape\n\nPlanning scenario only — not a forecast.", font=text, fill="black", spacing=5)
    image.save(OUT / "nelson_2025_probability_map.png")


if __name__ == "__main__":
    main()
