# Weather data dictionary

This document describes [`outputs/weather_data_used.csv`](outputs/weather_data_used.csv), the weather records actually supplied to the completed Nelson 50 km Cell2Fire batch.

## How the weather was derived

The input began as BC Wildfire Service (BCWS) DataMart records for May 1–October 31, 2025. The workflow retained three representative stations:

- `404` — Smallwood
- `406` — Slocan
- `408` — Norns

Records were grouped by station and day. A day became an accepted weather scenario only when it had:

1. Complete hourly observations for 12:00–17:00 local time; and
2. Complete noon FWI-system values: FFMC, DMC, DC, ISI, BUI, and FWI.

This produced 356 six-hour scenarios. The preparation step used random seed `20250716` to select one scenario for each of 1,000 independent runs. The exported file contains 6,000 rows: six hourly records for every run. Because sampling was with replacement, the same scenario may occur in multiple runs; 333 unique scenarios were selected.

Cell2Fire was run with `--weather rows`, so each six-row weather file was consumed sequentially as six one-hour weather periods. The model used a six-hour afternoon spread window (`--max-fire-periods 6`).

## Fields

| Field | Meaning and units | How it was used |
|---|---|---|
| `run_id` | Simulation run number, 1–1000. | Identifies the Monte Carlo run that consumed the row; bookkeeping only. |
| `weather_index` | Internal weather-file number, such as `345`. | Selects `Weathers/Weather345.csv` for that run. |
| `scenario` | Scenario ID, for example `406_20251020`. | Identifies the station/date weather sequence; passed through to Cell2Fire as a label. |
| `station_code` | BCWS station code. | Provenance and grouping; not a spatially varying weather field in this run. |
| `station_name` | Human-readable BCWS station name. | Provenance only. |
| `scenario_date` | Scenario date in `YYYYMMDD` format. | Provenance only; the simulation used the six rows in sequence. |
| `local_datetime_pst` | Hourly timestamp for the weather record. | Stored in the weather input and read by Cell2Fire; it does not independently advance the simulation clock. |
| `APCP_mm` | Hourly precipitation, millimetres. | Parsed into Cell2Fire's weather record, but not used by the core FBP spread calculation in this run. |
| `TMP_C` | Air temperature, °C. | Parsed and retained, but not used directly by the core FBP spread calculation in this run. |
| `RH_pct` | Relative humidity, percent. | Parsed and retained, but not used directly by the core FBP spread calculation in this run. |
| `WS_kmh` | Wind speed, km/h. | Applied to every active cell during that weather period; influences rate of spread. |
| `WD_deg` | Meteorological wind direction, degrees (0° north, 90° east, 180° south, 270° west). | Applied as the wind azimuth (`waz`); controls the direction of the fire ellipse and spread. |
| `FFMC` | Fine Fuel Moisture Code. | Applied to active cells; affects fine-fuel dryness and rate of spread. |
| `DMC` | Duff Moisture Code. | Parsed and retained in the weather record, but not copied into the active cell inputs by the core spread routine used here. |
| `DC` | Drought Code. | Parsed and retained, but not used directly by the core spread routine used here. |
| `ISI` | Initial Spread Index. | Parsed and retained; Cell2Fire calculates spread from the supplied fuel, wind, FFMC, and BUI rather than using this column directly. |
| `BUI` | Buildup Index. | Applied to active cells; represents available fuel buildup and affects rate of spread. |
| `FWI` | Fire Weather Index. | Parsed and retained for reporting; not used directly by the core spread calculation in this run. |
| `fire_number` | Historical BCWS fire identifier used as the ignition source. | Provenance for the sampled ignition; not an event that Cell2Fire replays. |
| `fire_year` | Year of the historical source fire. | Provenance only. |
| `fire_cause` | Recorded cause of the historical source fire. | Provenance only; no cause-specific ignition probability was applied in this batch. |
| `ignition_lat` | Ignition latitude in decimal degrees. | Used to locate the sampled historical ignition before snapping it to a burnable 250 m grid cell. |
| `ignition_lon` | Ignition longitude in decimal degrees. | Used with latitude to locate the sampled historical ignition before grid snapping. |
| `cell_id` | One-based flattened ID for the selected 250 m grid cell. | Written to `Ignitions.csv` as the Cell2Fire ignition cell for the run. |

## Important interpretation note

The FWI-system values are daily noon values repeated across that day's six hourly rows. This is a deliberate input simplification for the six-hour screening scenario. It does not mean that Cell2Fire recalculated FWI from temperature, humidity, and precipitation each hour. For this configuration, the principal weather drivers of modeled spread were wind speed (`WS_kmh`), wind direction (`WD_deg`), FFMC, and BUI.

