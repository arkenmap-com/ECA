#!/usr/bin/env python3
"""Convert filtered BCWS records into six-hour Cell2Fire weather scenarios.

Input files are created by collect_bcws_weather.sh.  For every station/day with
complete noon FWI values and six complete hourly observations (12:00–17:00
PST), this script emits one Cell2Fire-ready scenario.  Daily FWI-system values
are carried across the six-hour sequence, while hourly weather is retained.
"""

from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parent
RAW = ROOT / "data" / "bcws-weather"
OUT = ROOT / "data" / "prepared"
STATIONS = {"404": "SMALLWOOD", "406": "SLOCAN", "408": "NORNS"}
HOURS = range(12, 18)
HOURLY_FIELDS = (
    "HOURLY_TEMPERATURE",
    "HOURLY_RELATIVE_HUMIDITY",
    "HOURLY_WIND_SPEED",
    "HOURLY_WIND_DIRECTION",
)
DAILY_FIELDS = (
    "FINE_FUEL_MOISTURE_CODE",
    "DUFF_MOISTURE_CODE",
    "DROUGHT_CODE",
    "INITIAL_SPREAD_INDEX",
    "BUILDUP_INDEX",
    "FIRE_WEATHER_INDEX",
)


def value(row: dict[str, str], field: str) -> float | None:
    raw = (row.get(field) or "").strip()
    try:
        return float(raw) if raw else None
    except ValueError:
        return None


def main() -> None:
    files = [
        path for path in sorted(RAW.glob("*_nelson_stations.csv"))
        if path.stat().st_size > 0
    ]
    if not files:
        raise SystemExit(
            f"No filtered BCWS files found in {RAW}. Run collect_bcws_weather.sh first."
        )

    by_day: dict[tuple[str, str], dict[int, dict[str, str]]] = defaultdict(dict)
    record_count = 0
    for path in files:
        with path.open(newline="", encoding="utf-8-sig") as source:
            for row in csv.DictReader(source):
                station = row["STATION_CODE"]
                if station not in STATIONS:
                    continue
                timestamp = row["DATE_TIME"]
                by_day[(station, timestamp[:8])][int(timestamp[8:10])] = row
                record_count += 1

    if not record_count:
        raise SystemExit(
            "The filtered BCWS files contain no records yet; complete the weather collector first."
        )

    OUT.mkdir(parents=True, exist_ok=True)
    weather_path = OUT / "weather_library.csv"
    scenarios_path = OUT / "weather_scenarios.csv"
    summary_path = OUT / "weather_library_summary.json"
    rejected: Counter[str] = Counter()
    scenarios: list[dict[str, object]] = []

    with weather_path.open("w", newline="", encoding="utf-8") as target:
        writer = csv.writer(target)
        writer.writerow([
            "Scenario", "datetime", "APCP", "TMP", "RH", "WS", "WD",
            "FFMC", "DMC", "DC", "ISI", "BUI", "FWI",
        ])
        for (station, date), hours in sorted(by_day.items()):
            noon = hours.get(12)
            if not noon:
                rejected["missing_noon_record"] += 1
                continue
            indices = [value(noon, field) for field in DAILY_FIELDS]
            if any(item is None for item in indices):
                rejected["missing_noon_fwi"] += 1
                continue
            if any(hour not in hours for hour in HOURS):
                rejected["missing_hour"] += 1
                continue
            if any(value(hours[hour], field) is None for hour in HOURS for field in HOURLY_FIELDS):
                rejected["missing_hourly_weather"] += 1
                continue

            scenario = f"{station}_{date}"
            ffmc, dmc, dc, isi, bui, fwi = indices
            scenarios.append({
                "scenario": scenario,
                "station_code": station,
                "station_name": STATIONS[station],
                "date": date,
                "ffmc": ffmc,
                "dmc": dmc,
                "dc": dc,
                "isi": isi,
                "bui": bui,
                "fwi": fwi,
            })
            for hour in HOURS:
                row = hours[hour]
                dt = datetime.strptime(row["DATE_TIME"], "%Y%m%d%H")
                writer.writerow([
                    scenario,
                    dt.strftime("%Y-%m-%d %H:00"),
                    value(row, "HOURLY_PRECIPITATION") or 0,
                    value(row, "HOURLY_TEMPERATURE"),
                    value(row, "HOURLY_RELATIVE_HUMIDITY"),
                    value(row, "HOURLY_WIND_SPEED"),
                    value(row, "HOURLY_WIND_DIRECTION"),
                    ffmc, dmc, dc, isi, bui, fwi,
                ])

    with scenarios_path.open("w", newline="", encoding="utf-8") as target:
        writer = csv.DictWriter(target, fieldnames=scenarios[0].keys() if scenarios else ["scenario"])
        writer.writeheader()
        writer.writerows(scenarios)

    summary = {
        "source_files": [path.name for path in files],
        "stations": STATIONS,
        "scenario_hours_pst": list(HOURS),
        "accepted_scenarios": len(scenarios),
        "rejected_days": dict(rejected),
    }
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(f"Created {len(scenarios)} six-hour weather scenarios in {weather_path}")


if __name__ == "__main__":
    main()
