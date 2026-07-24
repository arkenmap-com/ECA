#!/usr/bin/env python3
"""Export the weather records actually used by the completed Cell2Fire runs."""

from __future__ import annotations

import csv
from pathlib import Path


ROOT = Path(__file__).resolve().parent
BASE = ROOT.parent.parent / "Cell2Fire" / "data" / "nelson-50km-2025"
OUTPUT = ROOT / "outputs" / "weather_data_used.csv"


def main() -> None:
    with (BASE / "run_manifest.csv").open(newline="", encoding="utf-8") as source:
        runs = list(csv.DictReader(source))

    weather_cache: dict[str, list[dict[str, str]]] = {}
    rows: list[dict[str, str]] = []
    fields = [
        "run_id", "weather_index", "scenario", "station_code", "station_name",
        "scenario_date", "local_datetime_pst", "APCP_mm", "TMP_C", "RH_pct",
        "WS_kmh", "WD_deg", "FFMC", "DMC", "DC", "ISI", "BUI", "FWI",
        "fire_number", "fire_year", "fire_cause", "ignition_lat", "ignition_lon",
        "cell_id",
    ]

    for run in runs:
        weather_index = run["weather_index"]
        if weather_index not in weather_cache:
            path = BASE / "Weathers" / f"Weather{weather_index}.csv"
            with path.open(newline="", encoding="utf-8") as source:
                weather_cache[weather_index] = list(csv.DictReader(source))
        for weather in weather_cache[weather_index]:
            scenario_date = run["scenario"].split("_", 1)[1]
            rows.append({
                "run_id": run["run_id"],
                "weather_index": weather_index,
                "scenario": run["scenario"],
                "station_code": run["scenario"].split("_", 1)[0],
                "station_name": "",
                "scenario_date": scenario_date,
                "local_datetime_pst": weather["datetime"],
                "APCP_mm": weather["APCP"],
                "TMP_C": weather["TMP"],
                "RH_pct": weather["RH"],
                "WS_kmh": weather["WS"],
                "WD_deg": weather["WD"],
                "FFMC": weather["FFMC"],
                "DMC": weather["DMC"],
                "DC": weather["DC"],
                "ISI": weather["ISI"],
                "BUI": weather["BUI"],
                "FWI": weather["FWI"],
                "fire_number": run["fire_number"],
                "fire_year": run["fire_year"],
                "fire_cause": run["fire_cause"],
                "ignition_lat": run["ignition_lat"],
                "ignition_lon": run["ignition_lon"],
                "cell_id": run["cell_id"],
            })

    # Fill station names from the manifest, keeping the export self-contained.
    names = {}
    with (BASE / "weather_manifest.csv").open(newline="", encoding="utf-8") as source:
        for record in csv.DictReader(source):
            names[record["station_code"]] = record["station_name"]
    for row in rows:
        row["station_name"] = names.get(row["station_code"], "")

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT.open("w", newline="", encoding="utf-8") as target:
        writer = csv.DictWriter(target, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    print(f"Exported {len(rows)} hourly records from {len(runs)} runs to {OUTPUT}")


if __name__ == "__main__":
    main()
