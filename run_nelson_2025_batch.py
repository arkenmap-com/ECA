#!/usr/bin/env python3
"""Run a reproducible batch of independent Cell2Fire 2025-weather scenarios."""

from __future__ import annotations

import argparse
import csv
import os
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


ROOT = Path(__file__).resolve().parent
BASE = ROOT / "Cell2Fire" / "data" / "nelson-50km-2025"
# The C++ grid writer shells out to mkdir without quoting paths; keep transient
# run outputs on a path without spaces, then publish derived outputs to STUDY.
RESULTS = Path("/private/tmp/nelson-2025-results")
RUNNER = ROOT / "Cell2Fire" / "cell2fire" / "main.py"
PYTHON = ROOT / "Cell2Fire" / ".venv" / "bin" / "python"
SCRATCH = Path("/private/tmp/nelson-2025-instances")


def link(source: Path, target: Path) -> None:
    if target.exists() or target.is_symlink():
        target.unlink()
    target.symlink_to(source)


def setup_instance(run: dict[str, str]) -> Path:
    instance = SCRATCH / f"run_{int(run['run_id']):04d}"
    instance.mkdir(parents=True, exist_ok=True)
    for name in ("Forest.asc", "Data.csv", "fbp_lookup_table.csv"):
        link(BASE / name, instance / name)
    shutil.copyfile(BASE / "Weathers" / f"Weather{run['weather_index']}.csv", instance / "Weather.csv")
    with (instance / "Ignitions.csv").open("w", newline="", encoding="utf-8") as target:
        writer = csv.writer(target)
        writer.writerow(["Year", "Ncell"])
        writer.writerow([1, run["cell_id"]])
    return instance


def run_one(run: dict[str, str]) -> None:
    output = RESULTS / f"run_{int(run['run_id']):04d}"
    if list((output / "Grids" / "Grids1").glob("ForestGrid*.csv")):
        return
    instance = setup_instance(run)
    output.mkdir(parents=True, exist_ok=True)
    env = os.environ | {
        "MPLCONFIGDIR": "/private/tmp/cell2fire-mpl",
        "XDG_CACHE_HOME": "/private/tmp/cell2fire-cache",
    }
    command = [
        str(PYTHON), str(RUNNER),
        "--input-instance-folder", f"{instance}/",
        "--output-folder", str(output),
        "--ignitions", "--sim-years", "1", "--nsims", "1", "--finalGrid",
        "--weather", "rows", "--nweathers", "1", "--Fire-Period-Length", "1.0",
        "--ROS-CV", "0.0", "--seed", str(20250716 + int(run["run_id"])),
        "--grids", "--gridsStep", "1", "--gridsFreq", "1", "--max-fire-periods", "6",
    ]
    log = output / "runner.log"
    with log.open("w", encoding="utf-8") as stream:
        subprocess.run(command, cwd=RUNNER.parent, env=env, stdout=stream, stderr=subprocess.STDOUT, check=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", type=int, default=1, help="First run id (one-based).")
    parser.add_argument("--count", type=int, default=1, help="Number of manifest rows to run.")
    parser.add_argument("--workers", type=int, default=1, help="Independent Cell2Fire processes to run concurrently.")
    args = parser.parse_args()
    with (BASE / "run_manifest.csv").open(newline="", encoding="utf-8") as source:
        rows = list(csv.DictReader(source))
    selected = [row for row in rows if args.start <= int(row["run_id"]) < args.start + args.count]
    if not selected:
        raise SystemExit("No matching run rows selected.")
    for index, row in enumerate(selected, start=1):
        print(f"[{index}/{len(selected)}] run {row['run_id']}: {row['scenario']}, ignition {row['fire_number']}", flush=True)
    if args.workers == 1:
        for row in selected:
            run_one(row)
    else:
        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            list(executor.map(run_one, selected))


if __name__ == "__main__":
    main()
