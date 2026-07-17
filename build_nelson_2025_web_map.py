#!/usr/bin/env python3
"""Build a local Leaflet web map from the completed Nelson probability rasters."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from pyproj import Transformer


ROOT = Path(__file__).resolve().parent
STUDY = ROOT / "long-term" / "nelson-50km"
OUT = STUDY / "outputs"
WEB = STUDY / "web-map"


def main() -> None:
    metadata = json.loads((OUT / "metadata.json").read_text(encoding="utf-8"))
    WEB.mkdir(exist_ok=True)
    (WEB / "data").mkdir(exist_ok=True)
    colors = WEB / "data" / "fuel_colors.txt"
    colors.write_text(
        "-9999 110 110 110 0\n2 34 104 56 255\n3 130 198 145 255\n4 120 140 0 255\n5 216 166 225 255\n7 108 0 237 255\n11 120 120 120 0\n13 184 171 123 255\n31 255 255 190 255\n101 145 145 145 0\n102 100 205 235 0\n105 100 205 235 0\n415 255 210 129 255\n625 255 196 96 255\n650 255 181 62 255\n675 255 166 18 255\n",
        encoding="utf-8",
    )
    fuel_display = WEB / "data" / "fuel_display.tif"
    subprocess.run([
        "gdaldem", "color-relief", "-alpha", str(STUDY / "data" / "derived" / "fuel_250m_50km.tif"), str(colors), str(fuel_display),
    ], check=True)
    for source, name, resampling in (
        # gdal2tiles PNG output requires Byte/UInt16; use the georeferenced
        # RGBA display PNG generated during aggregation for the probability layer.
        (OUT / "burn_probability.png", "probability", "bilinear"),
        (fuel_display, "fuel", "near"),
    ):
        destination = WEB / "tiles" / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            shutil.rmtree(destination)
        subprocess.run([
            "gdal2tiles.py", "--xyz", "-p", "mercator", "-z", "8-12", "-r", resampling, "-w", "none", str(source), str(destination),
        ], check=True)

    shutil.copyfile(STUDY / "data" / "ignitions" / "bcws_historical_ignitions_50km.geojson", WEB / "data" / "ignitions.geojson")
    transform = Transformer.from_crs(3005, 4326, always_xy=True)
    # Bounds of the 100 x 100 km 250m raster, used to frame the first map view.
    southwest = transform.transform(1579471.567, 486140.0)
    northeast = transform.transform(1679471.567, 586140.0)
    config = {
        "metadata": metadata,
        "bounds": [[southwest[1], southwest[0]], [northeast[1], northeast[0]]],
        "tileMaxZoom": 12,
    }
    (WEB / "data" / "config.js").write_text("window.NELSON_MAP = " + json.dumps(config) + ";\n", encoding="utf-8")
    print(f"Built {WEB} for {metadata['completed_runs']} completed runs.")


if __name__ == "__main__":
    main()
