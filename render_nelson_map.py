#!/usr/bin/env python3
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont


root = Path(__file__).resolve().parent
fuel = np.array(Image.open(root / "nelson-pilot/raw/fuel_display_100m.png").convert("RGB"))
burn = np.loadtxt(
    root / "Cell2Fire/results/nelson-conditional-test/Grids/Grids1/ForestGrid04.csv",
    delimiter=",",
)

image = Image.fromarray(fuel)
draw = ImageDraw.Draw(image)
for row, col in np.argwhere(burn == 1):
    draw.rectangle((int(col), int(row), int(col), int(row)), fill=(230, 70, 30))

map_image = image.resize((1340, 810), Image.Resampling.NEAREST)
legend = Image.open(root / "nelson-pilot/raw/fuel_legend.png").convert("RGB")
output = Image.new("RGB", (1700, 810), "white")
output.paste(map_image, (0, 0))

draw = ImageDraw.Draw(output)
title_font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 21)
text_font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 15)
small_font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 13)
panel_x = 1365

draw.text((panel_x, 25), "Nelson, BC", fill="black", font=title_font)
draw.text((panel_x, 52), "Cell2Fire conditional test", fill="black", font=text_font)
draw.rectangle((panel_x, 86, panel_x + 22, 108), fill=(230, 70, 30))
draw.text((panel_x + 32, 88), "Simulated burned cells", fill="black", font=text_font)
draw.text((panel_x, 120), "72 cells / about 72 ha", fill="black", font=small_font)
draw.text((panel_x, 145), "Underlying CWFIS FBP fuel types", fill="black", font=text_font)
output.paste(legend, (panel_x, 170))
draw.text(
    (panel_x, 565),
    "One ignition; synthetic severe weather;\nnot a forecast or probability map.",
    fill="black",
    font=small_font,
    spacing=5,
)

output.save(root / "nelson-pilot/nelson-conditional-test.png")
