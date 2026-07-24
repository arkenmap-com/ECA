#!/usr/bin/env python3
"""Config-driven Cell2Fire burn-probability pipeline.

The pipeline deliberately separates data acquisition from simulation.  An area
configuration points to harmonized fuel/topography rasters, a Cell2Fire weather
library, and historical ignition points.  The tool then prepares Cell2Fire
inputs, samples runs, executes the model, aggregates probabilities, and builds
an interactive Leaflet map.

Usage:
    python3 fire_sim_pipeline.py --config examples/nelson-50km-2025.json --stage all
    python3 fire_sim_pipeline.py --config examples/nelson-50km-2025.json --stage validate
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import os
import shutil
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import numpy as np
from pyproj import Transformer


ROOT = Path(__file__).resolve().parent
DEFAULT_ANALYSIS_CRS = "EPSG:3005"
DEFAULT_FUEL_MAP: dict[int, dict[str, str]] = {
    2: {"type": "C2", "label": "C2 boreal spruce", "color": "#226838"},
    3: {"type": "C3", "label": "C3 mature pine", "color": "#82c691"},
    4: {"type": "C4", "label": "C4 immature pine", "color": "#788c00"},
    5: {"type": "C5", "label": "C5 pine", "color": "#d8a6e1"},
    7: {"type": "C7", "label": "C7 Douglas-fir", "color": "#6c00ed"},
    11: {"type": "NF", "label": "Non-fuel", "color": "#787878"},
    13: {"type": "D1", "label": "D1 deciduous", "color": "#b8ab7b"},
    31: {"type": "O1a", "label": "O1a grass", "color": "#ffffbe"},
    101: {"type": "NF", "label": "Non-fuel", "color": "#919191"},
    102: {"type": "NF", "label": "Water / non-fuel", "color": "#64cdeb"},
    105: {"type": "NF", "label": "Non-fuel", "color": "#646464"},
    415: {"type": "M1", "pc": "15", "label": "M1 15% conifer", "color": "#ffd281"},
    625: {"type": "M1", "pc": "25", "label": "M1 25% conifer", "color": "#ffc460"},
    650: {"type": "M1", "pc": "50", "label": "M1 50% conifer", "color": "#ffb53e"},
    675: {"type": "M1", "pc": "75", "label": "M1 75% conifer", "color": "#ffa612"},
    -9999: {"type": "NF", "label": "NoData / non-fuel", "color": "#6e6e6e"},
}
WEATHER_FIELDS = [
    "Scenario", "datetime", "APCP", "TMP", "RH", "WS", "WD",
    "FFMC", "DMC", "DC", "ISI", "BUI", "FWI",
]
DAILY_FWI_FIELDS = ["ffmc", "dmc", "dc", "isi", "bui", "fwi"]


def die(message: str) -> None:
    raise SystemExit(f"Error: {message}")


def resolve(value: str | Path, base: Path = ROOT) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else base / path


def load_config(path: Path) -> dict[str, Any]:
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        die(f"Configuration file not found: {path}")
    except json.JSONDecodeError as exc:
        die(f"Invalid JSON in {path}: {exc}")
    if not isinstance(config, dict):
        die("The configuration root must be a JSON object.")
    config["_config_path"] = str(path)
    return config


def cfg_path(config: dict[str, Any], section: str, key: str, default: str | None = None) -> Path:
    value = config.get(section, {}).get(key, default)
    if value is None:
        die(f"Missing {section}.{key} in configuration.")
    return resolve(value)


def input_paths(config: dict[str, Any]) -> dict[str, Path]:
    inputs = config.get("inputs", {})
    required = ("fuel_raster", "elevation_raster", "slope_raster", "aspect_raster",
                "weather_library", "weather_scenarios", "ignitions_geojson", "fbp_lookup_table")
    paths: dict[str, Path] = {}
    for key in required:
        value = inputs.get(key)
        if value is None:
            die(f"Missing inputs.{key} in configuration.")
        paths[key] = resolve(value)
    return paths


def output_paths(config: dict[str, Any]) -> dict[str, Path]:
    outputs = config.get("outputs", {})
    name = str(config.get("name", "fire-sim"))
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in name).strip("-")
    return {
        "cell2fire": resolve(outputs.get("cell2fire_input_dir", f"Cell2Fire/data/{safe}")),
        "outputs": resolve(outputs.get("output_dir", f"runs/{safe}/outputs")),
        "web": resolve(outputs.get("web_map_dir", f"runs/{safe}/web-map")),
    }


def runtime_config(config: dict[str, Any]) -> dict[str, Any]:
    sim = config.setdefault("simulation", {})
    name = str(config.get("name", "fire-sim"))
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in name).strip("-")
    sim.setdefault("runs", 1000)
    sim.setdefault("seed", 20250716)
    sim.setdefault("workers", 1)
    sim.setdefault("weather_hours", 6)
    sim.setdefault("fire_period_length_hours", 1.0)
    sim.setdefault("ros_cv", 0.0)
    sim.setdefault("cell_size_m", 250)
    sim.setdefault("scratch_root", f"/private/tmp/fire-sim/{safe}")
    sim.setdefault("cell2fire_python", str(ROOT / "Cell2Fire" / ".venv" / "bin" / "python"))
    sim.setdefault("cell2fire_main", str(ROOT / "Cell2Fire" / "cell2fire" / "main.py"))
    return sim


def raster_values(path: Path) -> tuple[np.ndarray, dict[str, Any]]:
    try:
        info = json.loads(subprocess.check_output(["gdalinfo", "-json", str(path)], text=True))
    except FileNotFoundError:
        die("gdalinfo is required but was not found on PATH.")
    with tempfile.NamedTemporaryFile(suffix=".xyz", delete=False) as temp:
        xyz = Path(temp.name)
    try:
        subprocess.run(["gdal_translate", "-q", "-of", "XYZ", str(path), str(xyz)], check=True)
        values = np.loadtxt(xyz, usecols=2).reshape(info["size"][1], info["size"][0])
    finally:
        xyz.unlink(missing_ok=True)
    return values, info


def fuel_map(config: dict[str, Any]) -> dict[int, dict[str, str]]:
    raw = config.get("fuel_map")
    if raw is None:
        return DEFAULT_FUEL_MAP
    mapping: dict[int, dict[str, str]] = {}
    for key, value in raw.items():
        if isinstance(value, str):
            mapping[int(key)] = {"type": value, "label": value, "color": "#888888"}
        elif isinstance(value, dict) and "type" in value:
            entry = {str(k): str(v) for k, v in value.items()}
            entry.setdefault("label", entry["type"])
            entry.setdefault("color", "#888888")
            mapping[int(key)] = entry
        else:
            die(f"fuel_map[{key}] must be a fuel type string or object with a type field.")
    mapping.setdefault(-9999, DEFAULT_FUEL_MAP[-9999])
    return mapping


def nearest_burnable(row: int, col: int, burnable: np.ndarray) -> tuple[int, int] | None:
    rows, cols = burnable.shape
    for radius in range(0, 8):
        r0, r1 = max(0, row - radius), min(rows, row + radius + 1)
        c0, c1 = max(0, col - radius), min(cols, col + radius + 1)
        candidates = np.argwhere(burnable[r0:r1, c0:c1])
        if len(candidates):
            r, c = candidates[0]
            return int(r + r0), int(c + c0)
    return None


def selected_weather_scenarios(scenarios: list[dict[str, str]], sim: dict[str, Any]) -> list[dict[str, str]]:
    """Apply optional inclusive ISO date bounds to the weather scenario table."""
    start_raw = sim.get("weather_start_date")
    end_raw = sim.get("weather_end_date")
    if not start_raw and not end_raw:
        return scenarios
    try:
        start = dt.date.fromisoformat(str(start_raw)) if start_raw else dt.date.min
        end = dt.date.fromisoformat(str(end_raw)) if end_raw else dt.date.max
    except ValueError as exc:
        die(f"simulation.weather_start_date/weather_end_date must use ISO dates (YYYY-MM-DD): {exc}")
    if start > end:
        die("simulation.weather_start_date must be on or before weather_end_date.")
    selected = []
    for scenario in scenarios:
        raw_date = scenario.get("date") or str(scenario.get("scenario", "")).split("_")[-1]
        try:
            scenario_date = dt.date.fromisoformat(str(raw_date)[:4] + "-" + str(raw_date)[4:6] + "-" + str(raw_date)[6:8])
        except (ValueError, IndexError):
            die(f"Could not parse weather scenario date: {raw_date!r}")
        if start <= scenario_date <= end:
            selected.append(scenario)
    return selected


def validate(config: dict[str, Any]) -> dict[str, Any]:
    paths = input_paths(config)
    for key, path in paths.items():
        if not path.exists():
            die(f"Input file for {key} does not exist: {path}")
    sim = runtime_config(config)
    if int(sim["runs"]) < 1:
        die("simulation.runs must be at least 1.")
    if int(sim["weather_hours"]) < 1:
        die("simulation.weather_hours must be at least 1.")
    if int(sim["workers"]) < 1:
        die("simulation.workers must be at least 1.")
    fuel, info = raster_values(paths["fuel_raster"])
    for key in ("elevation_raster", "slope_raster", "aspect_raster"):
        values, _ = raster_values(paths[key])
        if values.shape != fuel.shape:
            die(f"{key} shape {values.shape} does not match fuel shape {fuel.shape}.")
    mapping = fuel_map(config)
    unknown = sorted(set(np.unique(fuel.astype(int))) - set(mapping))
    if unknown:
        die(f"Fuel values {unknown} are not in fuel_map; add them to the area configuration.")
    weather_hours = int(sim["weather_hours"])
    with paths["weather_library"].open(newline="", encoding="utf-8") as source:
        weather_headers = csv.DictReader(source).fieldnames or []
        required = set(WEATHER_FIELDS)
        if not required.issubset(weather_headers):
            die(f"weather_library is missing columns: {sorted(required - set(weather_headers))}")
    with paths["weather_scenarios"].open(newline="", encoding="utf-8") as source:
        scenarios = selected_weather_scenarios(list(csv.DictReader(source)), sim)
    if not scenarios:
        die("weather_scenarios contains no scenarios after the configured date filter.")
    if not config.get("analysis_crs"):
        config["analysis_crs"] = DEFAULT_ANALYSIS_CRS
    return {"fuel_shape": fuel.shape, "geo_info": info, "scenario_count": len(scenarios), "mapping": mapping}


def prepare(config: dict[str, Any]) -> Path:
    report = validate(config)
    paths = input_paths(config)
    outputs = output_paths(config)
    sim = runtime_config(config)
    out = outputs["cell2fire"]
    out.mkdir(parents=True, exist_ok=True)
    (out / "Weathers").mkdir(exist_ok=True)
    fuel, info = raster_values(paths["fuel_raster"])
    elevation, _ = raster_values(paths["elevation_raster"])
    slope, _ = raster_values(paths["slope_raster"])
    aspect, _ = raster_values(paths["aspect_raster"])
    rows, cols = fuel.shape
    origin_x, cell_x, _, origin_y, _, cell_y = info["geoTransform"]
    mapping = report["mapping"]

    with (out / "Forest.asc").open("w", encoding="utf-8") as target:
        target.write(f"ncols {cols}\n")
        target.write(f"nrows {rows}\n")
        target.write(f"xllcorner {origin_x}\n")
        target.write(f"yllcorner {origin_y + rows * cell_y}\n")
        target.write(f"cellsize {abs(cell_x)}\n")
        target.write("NODATA_value -9999\n")
        for line in fuel.astype(int):
            target.write(" ".join(map(str, line)) + "\n")

    x = origin_x + cell_x * (np.arange(cols) + 0.5)
    y = origin_y + cell_y * (np.arange(rows) + 0.5)
    xx, yy = np.meshgrid(x, y)
    lon, lat = Transformer.from_crs(config.get("analysis_crs", DEFAULT_ANALYSIS_CRS), "EPSG:4326", always_xy=True).transform(xx, yy)
    columns = ["fueltype", "mon", "jd", "M", "jd_min", "lat", "lon", "elev", "ffmc", "ws", "waz", "bui", "ps", "saz", "pc", "pdf", "gfl", "cur", "time", "pattern"]
    with (out / "Data.csv").open("w", newline="", encoding="utf-8") as target:
        writer = csv.DictWriter(target, fieldnames=columns)
        writer.writeheader()
        for raw, z, slp, asp, latitude, longitude in zip(fuel.ravel().astype(int), elevation.ravel(), slope.ravel(), aspect.ravel(), lat.ravel(), lon.ravel(), strict=True):
            entry = mapping[raw]
            writer.writerow({
                "fueltype": entry["type"], "mon": str(config.get("model", {}).get("month", 8)), "jd": str(config.get("model", {}).get("julian_day", 220)),
                "lat": f"{latitude:.5f}", "lon": f"{longitude:.5f}", "elev": f"{z:.1f}", "ps": f"{max(float(slp), 0):.2f}",
                "saz": f"{0 if asp < 0 else asp:.1f}", "pc": entry.get("pc", ""), "gfl": str(config.get("model", {}).get("gfl", 0.75)), "time": str(config.get("model", {}).get("time", 20)),
            })

    with paths["weather_scenarios"].open(newline="", encoding="utf-8") as source:
        scenarios = selected_weather_scenarios(list(csv.DictReader(source)), sim)
    by_scenario: dict[str, list[dict[str, str]]] = {}
    with paths["weather_library"].open(newline="", encoding="utf-8") as source:
        for record in csv.DictReader(source):
            by_scenario.setdefault(record["Scenario"], []).append(record)
    weather_manifest: list[dict[str, Any]] = []
    for index, scenario in enumerate(scenarios, start=1):
        name = scenario["scenario"]
        records = by_scenario.get(name, [])
        if len(records) != int(sim["weather_hours"]):
            die(f"Scenario {name} has {len(records)} hourly records; expected {sim['weather_hours']}.")
        with (out / "Weathers" / f"Weather{index}.csv").open("w", newline="", encoding="utf-8") as target:
            writer = csv.DictWriter(target, fieldnames=WEATHER_FIELDS)
            writer.writeheader()
            writer.writerows(records)
        weather_manifest.append({"weather_index": index, **scenario})
    with (out / "weather_manifest.csv").open("w", newline="", encoding="utf-8") as target:
        writer = csv.DictWriter(target, fieldnames=weather_manifest[0].keys())
        writer.writeheader()
        writer.writerows(weather_manifest)

    try:
        features = json.loads(paths["ignitions_geojson"].read_text(encoding="utf-8"))["features"]
    except (KeyError, json.JSONDecodeError) as exc:
        die(f"Could not read GeoJSON ignition features: {exc}")
    burnable = np.vectorize(lambda code: mapping[int(code)]["type"] != "NF")(fuel)
    to_grid = Transformer.from_crs("EPSG:4326", config.get("analysis_crs", DEFAULT_ANALYSIS_CRS), always_xy=True)
    valid_ignitions: list[dict[str, Any]] = []
    fields = config.get("ignition_fields", {})
    for feature in features:
        geometry = feature.get("geometry") or {}
        if geometry.get("type") != "Point":
            continue
        coordinates = geometry.get("coordinates") or []
        if len(coordinates) < 2:
            continue
        longitude, latitude = float(coordinates[0]), float(coordinates[1])
        gx, gy = to_grid.transform(longitude, latitude)
        row = int((origin_y - gy) / abs(cell_y))
        col = int((gx - origin_x) / cell_x)
        if not (0 <= row < rows and 0 <= col < cols):
            continue
        snapped = nearest_burnable(row, col, burnable)
        if not snapped:
            continue
        properties = feature.get("properties") or {}
        valid_ignitions.append({
            "fire_number": properties.get(fields.get("fire_number", "FIRE_NUMBER"), ""),
            "fire_year": properties.get(fields.get("fire_year", "FIRE_YEAR"), ""),
            "fire_cause": properties.get(fields.get("fire_cause", "FIRE_CAUSE"), ""),
            "ignition_lat": latitude, "ignition_lon": longitude,
            "cell_id": snapped[0] * cols + snapped[1] + 1,
        })
    if not valid_ignitions:
        die("No usable historical ignition points fall within the fuel grid.")
    rng = np.random.default_rng(int(sim["seed"]))
    chosen_weather = rng.integers(1, len(weather_manifest) + 1, size=int(sim["runs"]))
    if sim.get("ignition_sampling") == "exhaustive":
        if int(sim["runs"]) != len(valid_ignitions):
            die("simulation.runs must equal the usable ignition count for exhaustive ignition sampling.")
        chosen_ignitions = np.arange(len(valid_ignitions))
    else:
        chosen_ignitions = rng.integers(0, len(valid_ignitions), size=int(sim["runs"]))
    run_rows: list[dict[str, Any]] = []
    for run_id, (weather_index, ignition_index) in enumerate(zip(chosen_weather, chosen_ignitions, strict=True), start=1):
        run_rows.append({
            "run_id": run_id, "weather_index": int(weather_index), "scenario": weather_manifest[int(weather_index) - 1]["scenario"], **valid_ignitions[int(ignition_index)]
        })
    with (out / "run_manifest.csv").open("w", newline="", encoding="utf-8") as target:
        writer = csv.DictWriter(target, fieldnames=run_rows[0].keys())
        writer.writeheader()
        writer.writerows(run_rows)
    shutil.copyfile(paths["fbp_lookup_table"], out / "fbp_lookup_table.csv")
    metadata = {
        "name": config.get("name", "fire-sim"), "display_name": config.get("display_name", config.get("name", "Fire simulation")),
        "analysis_crs": config.get("analysis_crs", DEFAULT_ANALYSIS_CRS), "grid": {"rows": rows, "columns": cols, "cell_size_m": float(abs(cell_x))},
        "weather_scenarios": len(weather_manifest), "usable_ignitions": len(valid_ignitions), "planned_runs": len(run_rows), "seed": int(sim["seed"]),
    }
    (out / "input_metadata.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    print(f"Prepared {out}: {len(weather_manifest)} weather scenarios and {len(run_rows)} runs.")
    return out


def setup_instance(base: Path, scratch: Path, run: dict[str, str]) -> Path:
    instance = scratch / f"run_{int(run['run_id']):04d}"
    instance.mkdir(parents=True, exist_ok=True)
    for name in ("Forest.asc", "Data.csv", "fbp_lookup_table.csv"):
        target = instance / name
        if target.exists() or target.is_symlink():
            target.unlink()
        target.symlink_to(base / name)
    shutil.copyfile(base / "Weathers" / f"Weather{run['weather_index']}.csv", instance / "Weather.csv")
    with (instance / "Ignitions.csv").open("w", newline="", encoding="utf-8") as target:
        writer = csv.writer(target)
        writer.writerow(["Year", "Ncell"])
        writer.writerow([1, run["cell_id"]])
    return instance


def run_simulations(config: dict[str, Any]) -> Path:
    paths = output_paths(config)
    base = paths["cell2fire"]
    manifest_path = base / "run_manifest.csv"
    if not manifest_path.exists():
        die(f"Missing {manifest_path}; run --stage prepare first.")
    sim = runtime_config(config)
    results = resolve(sim["results_dir"]) if sim.get("results_dir") else resolve(sim["scratch_root"]) / "results"
    scratch = resolve(sim["scratch_root"]) / "instances"
    results.mkdir(parents=True, exist_ok=True)
    scratch.mkdir(parents=True, exist_ok=True)
    rows = list(csv.DictReader(manifest_path.open(newline="", encoding="utf-8")))
    python = resolve(sim["cell2fire_python"])
    runner = resolve(sim["cell2fire_main"])
    if not python.exists():
        die(f"Cell2Fire Python executable not found: {python}")
    if not runner.exists():
        die(f"Cell2Fire runner not found: {runner}")

    def one(run: dict[str, str]) -> None:
        output = results / f"run_{int(run['run_id']):04d}"
        if list((output / "Grids" / "Grids1").glob("ForestGrid*.csv")):
            return
        instance = setup_instance(base, scratch, run)
        output.mkdir(parents=True, exist_ok=True)
        env = os.environ | {"MPLCONFIGDIR": str(scratch / "mpl"), "XDG_CACHE_HOME": str(scratch / "cache")}
        command = [str(python), str(runner), "--input-instance-folder", f"{instance}/", "--output-folder", str(output), "--ignitions", "--sim-years", "1", "--nsims", "1", "--finalGrid", "--weather", "rows", "--nweathers", "1", "--Fire-Period-Length", str(sim["fire_period_length_hours"]), "--ROS-CV", str(sim["ros_cv"]), "--seed", str(int(sim["seed"]) + int(run["run_id"])), "--max-fire-periods", str(sim["weather_hours"])]
        if sim.get("save_intermediate_grids"):
            command.append("--grids")
        with (output / "runner.log").open("w", encoding="utf-8") as log:
            subprocess.run(command, cwd=runner.parent, env=env, stdout=log, stderr=subprocess.STDOUT, check=True)

    print(f"Running {len(rows)} Cell2Fire simulations with {sim['workers']} worker(s).")
    if int(sim["workers"]) == 1:
        for index, row in enumerate(rows, start=1):
            print(f"[{index}/{len(rows)}] run {row['run_id']}: {row['scenario']}", flush=True)
            one(row)
    else:
        with ThreadPoolExecutor(max_workers=int(sim["workers"])) as executor:
            list(executor.map(one, rows))
    config.setdefault("simulation", {})["results_dir"] = str(results)
    print(f"Completed simulation outputs in {results}")
    return results


def aggregate(config: dict[str, Any]) -> Path:
    paths = output_paths(config)
    base = paths["cell2fire"]
    sim = runtime_config(config)
    results = resolve(sim["results_dir"]) if sim.get("results_dir") else resolve(sim["scratch_root"]) / "results"
    out = paths["outputs"]
    forest = base / "Forest.asc"
    if not forest.exists():
        die(f"Missing {forest}; run --stage prepare first.")
    header = forest.read_text(encoding="utf-8").splitlines()[:6]
    rows, cols = int(header[1].split()[1]), int(header[0].split()[1])
    burn_count = np.zeros((rows, cols), dtype=np.uint32)
    run_rows: list[dict[str, Any]] = []
    aggregation_limit = sim.get("aggregation_run_limit")
    if aggregation_limit is not None:
        aggregation_limit = int(aggregation_limit)
        if aggregation_limit < 1:
            die("simulation.aggregation_run_limit must be at least 1.")
    for run in sorted(results.glob("run_*")):
        grids = sorted((run / "Grids" / "Grids1").glob("ForestGrid*.csv"))
        if not grids:
            continue
        if aggregation_limit is not None and len(run_rows) >= aggregation_limit:
            break
        final = np.loadtxt(grids[-1], delimiter=",")
        if final.shape != burn_count.shape:
            die(f"Unexpected grid shape in {grids[-1]}: {final.shape}; expected {(rows, cols)}")
        burnt = final == 1
        burn_count += burnt
        run_rows.append({"run": run.name, "burned_cells": int(burnt.sum())})
    if not run_rows:
        die(f"No completed Cell2Fire grids found in {results}.")
    out.mkdir(parents=True, exist_ok=True)
    probability = burn_count / len(run_rows)
    for name, data, fmt in (("burn_count.asc", burn_count, "%d"), ("burn_probability.asc", probability, "%.8f")):
        with (out / name).open("w", encoding="utf-8") as target:
            target.write("\n".join(header) + "\n")
            np.savetxt(target, data, fmt=fmt, delimiter=" ")
    analysis_crs = config.get("analysis_crs", DEFAULT_ANALYSIS_CRS)
    for name in ("burn_count", "burn_probability"):
        subprocess.run(["gdal_translate", "-q", "-a_srs", str(analysis_crs), str(out / f"{name}.asc"), str(out / f"{name}.tif")], check=True)
    colors = out / "probability_colors.txt"
    if len(run_rows) == 1:
        colors.write_text("0 0 0 0 0\n1 189 0 38 235\n", encoding="utf-8")
    else:
        colors.write_text(
            "0 0 0 0 0\n"
            "0.001 255 255 178 180\n"
            "0.005 254 217 118 195\n"
            "0.01 254 178 76 210\n"
            "0.025 253 141 60 220\n"
            "0.05 240 59 32 230\n"
            "0.1 189 0 38 240\n"
            "0.2 128 0 38 255\n"
            "0.3 72 0 35 255\n",
            encoding="utf-8",
        )
    subprocess.run(["gdaldem", "color-relief", "-alpha", str(out / "burn_probability.tif"), str(colors), str(out / "burn_probability.png")], check=True)
    with (out / "run_summary.csv").open("w", encoding="utf-8") as target:
        target.write("run,burned_cells\n")
        target.writelines(f"{row['run']},{row['burned_cells']}\n" for row in run_rows)
    metadata = {
        "name": config.get("name", "fire-sim"), "display_name": config.get("display_name", config.get("name", "Fire simulation")),
        "completed_runs": len(run_rows), "requested_runs": int(sim["runs"]), "mean_burned_cells": float(np.mean([row["burned_cells"] for row in run_rows])),
        "max_burned_cells": int(np.max([row["burned_cells"] for row in run_rows])), "cells_with_nonzero_probability": int((burn_count > 0).sum()),
        "maximum_probability": float(probability.max()), "cell_size_m": float(sim["cell_size_m"]), "analysis_crs": analysis_crs,
        "scenario": config.get("scenario_description", "Configured Cell2Fire weather and ignition scenario"),
        "aggregation_run_limit": aggregation_limit,
        "partial_aggregation": aggregation_limit is not None and aggregation_limit < int(sim["runs"]),
    }
    (out / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(metadata, indent=2))
    return out


def html_template(config: dict[str, Any], metadata: dict[str, Any], bounds: list[list[float]], tile_max_zoom: int, fuel_entries: list[dict[str, str]], has_growth_intervals: bool = False) -> str:
    title = str(config.get("display_name", config.get("name", "Fire simulation")))
    legend = "".join(f'<span class="swatch" style="background:{entry["color"]}"></span><span>{entry["label"]}</span>' for entry in fuel_entries)
    ignition_label = "Included ignition-grid points" if metadata.get("partial_aggregation") else "Ignition-grid points"
    if int(metadata.get("completed_runs", 0)) == 1:
        probability_label = "48-hour burned footprint"
        probability_legend = '<span class="swatch" style="background:#bd0026"></span><span>Burned during simulation</span>'
    else:
        probability_label = "Burn frequency"
        probability_legend = (
            '<span class="swatch" style="background:#ffffb2"></span><span>0.1–0.5%</span>'
            '<span class="swatch" style="background:#fed976"></span><span>0.5–1%</span>'
            '<span class="swatch" style="background:#feb24c"></span><span>1–2.5%</span>'
            '<span class="swatch" style="background:#fd8d3c"></span><span>2.5–5%</span>'
            '<span class="swatch" style="background:#f03b20"></span><span>5–10%</span>'
            '<span class="swatch" style="background:#bd0026"></span><span>10–20%</span>'
            '<span class="swatch" style="background:#480023"></span><span>20–30%</span>'
        )
    config_js = json.dumps({
        "metadata": metadata, "bounds": bounds, "tileMaxZoom": tile_max_zoom,
        "ignitionLabel": ignition_label, "probabilityLabel": probability_label,
        "hasGrowthIntervals": has_growth_intervals,
    })
    growth_legend = (
        '<details class="legend-group" open><summary>Fire growth by elapsed time</summary><div class="legend">'
        '<span class="swatch" style="background:#ffeda0"></span><span>0–12 hours</span>'
        '<span class="swatch" style="background:#feb24c"></span><span>12–24 hours</span>'
        '<span class="swatch" style="background:#f03b20"></span><span>24–36 hours</span>'
        '<span class="swatch" style="background:#800026"></span><span>36–48 hours</span>'
        '</div></details>'
    ) if has_growth_intervals else ""
    return f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>{title} Fire Simulation Map</title><link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"><style>
html,body,#map{{height:100%;margin:0}}.leaflet-container{{background:#f7f7f7}}.panel{{max-width:340px;font:14px/1.4 system-ui,sans-serif}}.panel h1{{font-size:16px;margin:0 0 6px}}.legend{{display:grid;grid-template-columns:18px 1fr;gap:4px 8px;align-items:center;margin-top:8px}}.fuel-legend{{grid-template-columns:16px 1fr 16px 1fr;font-size:12px}}.legend-group{{margin-top:8px}}.legend-group summary{{cursor:pointer;font-weight:700}}.swatch{{height:12px}}
</style></head><body><main id="map" aria-label="{title} Cell2Fire simulation map"></main><script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script><script>window.FIRE_SIM_MAP={config_js};const cfg=window.FIRE_SIM_MAP;const map=L.map('map');map.fitBounds(cfg.bounds,{{padding:[12,12]}});const topo=L.tileLayer('https://{{s}}.tile.opentopomap.org/{{z}}/{{x}}/{{y}}.png',{{maxZoom:17,attribution:'Map data: &copy; OpenStreetMap contributors, SRTM | Map style: &copy; OpenTopoMap (CC-BY-SA)'}}).addTo(map);const streets=L.tileLayer('https://tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png',{{maxZoom:19,attribution:'&copy; OpenStreetMap contributors'}});const PlainGreyLayer=L.GridLayer.extend({{createTile:()=>{{const tile=document.createElement('div');tile.style.background='#d9d9d9';return tile;}}}});const plainGrey=new PlainGreyLayer({{tileSize:256}});const noBasemap=L.layerGroup();const baseLayers={{'Topographic (OpenTopoMap)':topo,'OpenStreetMap':streets,'Plain grey':plainGrey,'No basemap':noBasemap}};const fuel=L.tileLayer('tiles/fuel/{{z}}/{{x}}/{{y}}.png',{{opacity:.58,maxNativeZoom:cfg.tileMaxZoom}});const probability=L.tileLayer('tiles/probability/{{z}}/{{x}}/{{y}}.png',{{opacity:.83,maxNativeZoom:cfg.tileMaxZoom}});const growth=cfg.hasGrowthIntervals?L.tileLayer('tiles/growth/{{z}}/{{x}}/{{y}}.png',{{opacity:.86,maxNativeZoom:cfg.tileMaxZoom}}).addTo(map):null;if(!growth)probability.addTo(map);const overlays={{'FBP fuel types':fuel}};overlays[cfg.probabilityLabel]=probability;if(growth)overlays['Fire growth - 12-hour intervals']=growth;const layerControl=L.control.layers(baseLayers,overlays,{{collapsed:false}}).addTo(map);fetch('data/ignitions.geojson').then(r=>r.json()).then(data=>{{const ignitions=L.geoJSON(data,{{pointToLayer:(_,latlng)=>L.circleMarker(latlng,{{radius:5,color:'#422',weight:1,fillColor:'#f4c542',fillOpacity:.9}}),onEachFeature:(feature,layer)=>layer.bindPopup(`<strong>${{feature.properties.GRID_ID||''}}</strong>`)}});layerControl.addOverlay(ignitions,cfg.ignitionLabel);}});L.control.scale({{imperial:false}}).addTo(map);const m=cfg.metadata;const note=L.control({{position:'topright'}});note.onAdd=()=>{{const div=L.DomUtil.create('section','leaflet-control panel');const partial=m.partial_aggregation?`<p><strong>Partial aggregation:</strong> First ${{m.completed_runs.toLocaleString()}} of ${{m.requested_runs.toLocaleString()}} spatially ordered ignition runs. Not a full-AOI probability estimate.</p>`:'';div.innerHTML=`<h1>{title}</h1><div>${{m.completed_runs.toLocaleString()}} Cell2Fire run${{m.completed_runs===1?'':'s'}} · ${{m.cell_size_m}} m cells</div><div>${{m.scenario}}</div>${{partial}}{growth_legend}<details class="legend-group"><summary>${{cfg.probabilityLabel}} legend</summary><div class="legend">{probability_legend}</div></details><details class="legend-group"><summary>FBP [Fire Behaviour Prediction] fuel-type legend</summary><div class="legend fuel-legend">{legend}</div></details><p><strong>Planning scenario only.</strong> Not a live-fire forecast or operational decision product.</p>`;return div;}};note.addTo(map);</script></body></html>
'''


def build_map(config: dict[str, Any]) -> Path:
    paths = output_paths(config)
    out, web = paths["outputs"], paths["web"]
    metadata_path = out / "metadata.json"
    if not metadata_path.exists():
        die(f"Missing {metadata_path}; run --stage aggregate first.")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    web.mkdir(parents=True, exist_ok=True)
    (web / "data").mkdir(exist_ok=True)
    fuel_path = input_paths(config)["fuel_raster"]
    _, info = raster_values(fuel_path)
    colors = web / "data" / "fuel_colors.txt"
    mapping = fuel_map(config)
    lines = []
    entries: list[dict[str, str]] = []
    seen_types: set[str] = set()
    for code, entry in sorted(mapping.items()):
        alpha = 0 if entry["type"] == "NF" else 255
        rgb = tuple(int(entry["color"].lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
        lines.append(f"{code} {rgb[0]} {rgb[1]} {rgb[2]} {alpha}")
        if entry["type"] != "NF" and entry["type"] not in seen_types:
            entries.append(entry)
            seen_types.add(entry["type"])
    colors.write_text("\n".join(lines) + "\n", encoding="utf-8")
    fuel_display = web / "data" / "fuel_display.tif"
    subprocess.run(["gdaldem", "color-relief", "-alpha", str(fuel_path), str(colors), str(fuel_display)], check=True)
    tile_sources = [(out / "burn_probability.png", "probability", "bilinear"), (fuel_display, "fuel", "near")]
    growth_source = out / "fire_growth_12h_intervals.png"
    if growth_source.exists():
        tile_sources.append((growth_source, "growth", "near"))
    for source, name, resampling in tile_sources:
        destination = web / "tiles" / name
        if destination.exists():
            shutil.rmtree(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["gdal2tiles.py", "--xyz", "-p", "mercator", "-z", "8-12", "-r", resampling, "-w", "none", str(source), str(destination)], check=True)
    ignition = input_paths(config)["ignitions_geojson"]
    ignition_target = web / "data" / "ignitions.geojson"
    if metadata.get("partial_aggregation"):
        ignition_data = json.loads(ignition.read_text(encoding="utf-8"))
        ignition_data["features"] = ignition_data.get("features", [])[:int(metadata["completed_runs"])]
        ignition_target.write_text(json.dumps(ignition_data, separators=(",", ":")) + "\n", encoding="utf-8")
    else:
        shutil.copyfile(ignition, ignition_target)
    rows, cols = info["size"][1], info["size"][0]
    origin_x, cell_x, _, origin_y, _, cell_y = info["geoTransform"]
    transform = Transformer.from_crs(config.get("analysis_crs", DEFAULT_ANALYSIS_CRS), "EPSG:4326", always_xy=True)
    west, south = transform.transform(origin_x, origin_y + rows * cell_y)
    east, north = transform.transform(origin_x + cols * cell_x, origin_y)
    bounds = [[south, west], [north, east]]
    (web / "index.html").write_text(
        html_template(config, metadata, bounds, 12, entries, growth_source.exists()),
        encoding="utf-8",
    )
    print(f"Built {web}")
    return web


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path, help="Area JSON configuration.")
    parser.add_argument("--stage", choices=("validate", "prepare", "run", "aggregate", "map", "all"), default="all")
    args = parser.parse_args()
    config = load_config(args.config.resolve())
    report = validate(config)
    print(f"Validated {config.get('display_name', config.get('name', 'fire simulation'))}: {report['fuel_shape'][1]}x{report['fuel_shape'][0]} cells, {report['scenario_count']} weather scenarios.")
    if args.stage == "validate":
        return
    if args.stage in ("prepare", "all"):
        prepare(config)
    if args.stage in ("run", "all"):
        run_simulations(config)
    if args.stage in ("aggregate", "all"):
        aggregate(config)
    if args.stage in ("map", "all"):
        build_map(config)


if __name__ == "__main__":
    main()
