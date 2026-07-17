#!/usr/bin/env python3
"""Aggregate independent Cell2Fire runs into a georeferenced probability map."""

from __future__ import annotations

import csv
import json
import subprocess
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parent
BASE = ROOT / "Cell2Fire" / "data" / "nelson-50km-2025"
RUNS = Path("/private/tmp/nelson-2025-results")
OUT = ROOT / "long-term" / "nelson-50km" / "outputs"


def main() -> None:
    forest = BASE / "Forest.asc"
    header = forest.read_text(encoding="utf-8").splitlines()[:6]
    rows = int(header[1].split()[1])
    cols = int(header[0].split()[1])
    burn_count = np.zeros((rows, cols), dtype=np.uint32)
    run_rows: list[dict[str, object]] = []
    for run in sorted(RUNS.glob("run_*")):
        grids = sorted((run / "Grids" / "Grids1").glob("ForestGrid*.csv"))
        if not grids:
            continue
        final = np.loadtxt(grids[-1], delimiter=",")
        if final.shape != burn_count.shape:
            raise ValueError(f"Unexpected grid shape in {grids[-1]}")
        burnt = final == 1
        burn_count += burnt
        run_rows.append({"run": run.name, "burned_cells": int(burnt.sum())})
    if not run_rows:
        raise SystemExit("No completed Cell2Fire grids found.")

    OUT.mkdir(parents=True, exist_ok=True)
    probability = burn_count / len(run_rows)
    for name, data, fmt in (("burn_count.asc", burn_count, "%d"), ("burn_probability.asc", probability, "%.8f")):
        with (OUT / name).open("w", encoding="utf-8") as target:
            target.write("\n".join(header) + "\n")
            np.savetxt(target, data, fmt=fmt, delimiter=" ")
    for name in ("burn_count", "burn_probability"):
        subprocess.run([
            "gdal_translate", "-q", "-a_srs", "EPSG:3005", str(OUT / f"{name}.asc"), str(OUT / f"{name}.tif"),
        ], check=True)

    colors = OUT / "probability_colors.txt"
    colors.write_text(
        "0 0 0 0 0\n0.001 255 255 178 180\n0.005 254 204 92 210\n0.01 253 141 60 220\n0.025 240 59 32 230\n0.05 189 0 38 240\n0.1 128 0 38 255\n",
        encoding="utf-8",
    )
    subprocess.run([
        "gdaldem", "color-relief", "-alpha", str(OUT / "burn_probability.tif"), str(colors), str(OUT / "burn_probability.png"),
    ], check=True)
    (OUT / "run_summary.csv").write_text(
        "run,burned_cells\n" + "".join(f"{row['run']},{row['burned_cells']}\n" for row in run_rows), encoding="utf-8"
    )
    metadata = {
        "completed_runs": len(run_rows),
        "mean_burned_cells": float(np.mean([row["burned_cells"] for row in run_rows])),
        "max_burned_cells": int(np.max([row["burned_cells"] for row in run_rows])),
        "cells_with_nonzero_probability": int((burn_count > 0).sum()),
        "maximum_probability": float(probability.max()),
        "cell_size_m": 250,
        "scenario": "2025 BCWS weather; historical ignition locations; current fuel landscape",
    }
    (OUT / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(metadata, indent=2))


if __name__ == "__main__":
    main()
