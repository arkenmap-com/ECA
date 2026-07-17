# Nelson 50 km burn-probability study

This is a **planning** study, not an active-fire forecast.

## Completed 2025 weather-conditioned scenario

The first completed scenario uses the present-day 250 m landscape, observed 2025 BCWS weather from representative nearby stations, and 2000–2023 BCWS historical ignition locations. It contains 1,000 independent Cell2Fire runs, each simulating a six-hour afternoon spread window. Its outputs are in `outputs/`:

- `burn_probability.tif` and `burn_probability.asc` — cell-level probability (burned runs / 1,000).
- `burn_count.tif` and `burn_count.asc` — number of runs reaching each cell.
- `nelson_2025_probability_map.png` — static map with legend.
- `metadata.json` and `run_summary.csv` — scenario and aggregate run record.

The interactive version is in `web-map/`. Run this from that directory, then browse to `http://127.0.0.1:4174`:

```bash
python3 -m http.server 4174
```

It includes the burn-probability overlay, FBP fuel types, and the sampled historical ignition locations. The probability estimate is conditioned on 2025 weather and the chosen modelling rules; it is not a long-term climate probability, an active-fire forecast, or an operational decision product.

`scenario-2025-weather.json`, `prepare_nelson_2025_cell2fire.py`, `run_nelson_2025_batch.py`, `aggregate_nelson_2025_probability.py`, and `build_nelson_2025_web_map.py` record the reproducible workflow.

## Planned multi-year study

The initial screening grid is 250 m: a 100 km × 100 km square centred on Nelson (160,000 cells), with the final analysis masked to the 50 km radius. The model will use the present-day fuel layer but draw weather and ignitions from 2000–2021, the complete annual historical BCWS archive currently used by this workflow. Its result therefore represents long-term exposure under the current landscape, not the probability that occurred historically.

Before execution, the workflow must:

1. Download and quality-check BCWS historical weather/Fire Weather Index records from stations representative of the study area.
2. Query BCWS historical fire locations and perimeters, then fit an ignition sampling rule and exclude records with unusable locations/dates.
3. Produce harmonized 250 m fuel, elevation, slope, aspect and non-fuel rasters.
4. Replay a small set of historical fires to calibrate and document the Cell2Fire assumptions.
5. Run an initial 1,000-iteration Monte Carlo batch, inspect convergence, then increase the run count if necessary.

The published output will include the input vintage, sampling rules, random seed(s), run count, calibration results, uncertainty notes, and a cell-level burn-probability raster.

`build_weather_library.py` converts the filtered BCWS records into six-hour Cell2Fire scenarios (noon–5 pm PST), retaining only days with complete hourly weather and noon FWI-system values.
