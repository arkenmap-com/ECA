# AOI [area of interest] fire-spread simulation: BC [British Columbia] 25 m DEM [digital elevation model] and summer P90 [90th percentile] weather

## Technical summary

The corrected simulation completed all **1,028** planned Cell2Fire runs. Each run used one point from an exhaustive 500 m ignition grid, a six-hour observed weather sequence representative of the **90th percentile of June–August noon FWI [Fire Weather Index] at Smallwood**, and terrain derived from the GeoBC 25 m CDED [Canadian Digital Elevation Data] product.

Across those runs:

- the highest cell-level burn frequency was **5.84%** (60 of 1,028 ignition scenarios, subject to raster rounding);
- the median simulated six-hour burned area was **3.76 km²**;
- the mean simulated six-hour burned area was **4.36 km²**;
- the 90th-percentile simulated burned area was **8.40 km²**; and
- the largest simulated burned area was **17.09 km²**.

These values are **conditional fire-spread results**, not annual burn probabilities. They describe how often cells were reached under the fixed severe-weather scenario and the specified ignition grid. They do not include ignition likelihood, day-to-day weather frequency, suppression, fuel-moisture uncertainty, or multi-day fire growth.

## Burn probability surface

![Cell2Fire burn-frequency surface for the AOI](../runs/aoi-25m-bcdem-summer-p90/outputs/burn_probability.png)

The map highlights locations reached repeatedly from different ignition points during the six-hour simulations. A value of 5% means that approximately 5% of the 1,028 gridded ignition scenarios reached that cell; it does not mean the cell has a 5% chance of burning in a given year.

The maximum frequency is modest because ignitions were spread systematically across the full 257.57 km² AOI and fire growth was limited to six hours. The surface is most useful for comparing relative pathways and convergence zones within this scenario.

## Scenario definition

| Component | Configuration |
|---|---|
| Analysis grid | 25 m cells in BC Albers, EPSG [European Petroleum Survey Group] code 3005 |
| AOI area | 257.57 km² |
| Landscape grid | 854 columns × 884 rows |
| Elevation | GeoBC CDED, nominal 25 m, derived from provincial TRIM [Terrain Resource Information Management] 1:20,000 DEM |
| Elevation within AOI | 452–2,018 m; median 1,151 m |
| Fuel | Original 100 m fuel raster, nearest-neighbour resampled to the aligned 25 m grid |
| Weather station | 404 SMALLWOOD |
| Weather population | 920 complete June–August days, 2016–2025 |
| Severe-weather statistic | Empirical 90th percentile of daily noon FWI: 42.5844 |
| Selected observed sequence | 20 August 2018; noon FWI 42.576 |
| Weather duration | Six hourly records, 12:00–17:00 |
| Ignitions | 1,028 burnable points on an exhaustive 500 m grid |
| Simulation duration | Six one-hour fire periods |
| Spread variability | ROS [rate of spread] coefficient of variation = 0 |

The fuel layer is stored and simulated on a 25 m grid, but its original information content remains 100 m. Resampling creates grid alignment; it does not create new 25 m fuel detail.

## Weather selection

The weather preparation step filtered Smallwood records to June, July, and August for 2016–2025. It retained 920 complete days, calculated the empirical 90th percentile of daily noon Fire Weather Index, and selected the complete observed six-hour sequence whose noon FWI was closest to that percentile.

The chosen day, 20 August 2018, had:

- FWI [Fire Weather Index] 42.576;
- FFMC [Fine Fuel Moisture Code] 93.213;
- DMC [Duff Moisture Code] 217.442;
- DC [Drought Code] 638.593;
- ISI [Initial Spread Index] 11.247; and
- BUI [Build Up Index] 234.913.

Using a coherent observed day preserves realistic hourly relationships among temperature, relative humidity, wind speed, and wind direction. The six hourly temperatures ranged from 22.9°C to 26.6°C, relative humidity from 22% to 25%, and wind speed from 10.1 to 14.3 in the source station units.

This is a severe but plausible single weather sequence. It does not represent the full distribution of summer wind directions or severe-weather combinations.

## Terrain and ignition design

Elevation was built from four official GeoBC CDED tiles (`082f05_e`, `082f06_w`, `082f11_w`, and `082f12_e`), reprojected bilinearly to the aligned 25 m BC Albers grid. Slope and aspect were recalculated from that reprojected surface.

The ignition design placed points at 500 m spacing and retained 1,028 points that landed on burnable cells. Exhaustive sampling assigned exactly one simulation to each retained ignition point. This makes the output an equal-weight spatial experiment: every grid ignition contributes equally, regardless of the real-world likelihood of ignition at that location.

## Run results

| Statistic | Burned cells | Area |
|---|---:|---:|
| Minimum | 1 | 0.0006 km² |
| 10th percentile | 1,308 | 0.82 km² |
| 25th percentile | 3,705 | 2.32 km² |
| Median | 6,014 | 3.76 km² |
| Mean | 6,977 | 4.36 km² |
| 75th percentile | 9,540 | 5.96 km² |
| 90th percentile | 13,435 | 8.40 km² |
| 95th percentile | 16,828 | 10.52 km² |
| Maximum | 27,347 | 17.09 km² |

Area is calculated as burned cells × 625 m² per 25 m cell. Percentiles use linear interpolation over the 1,028 run totals.

## Limitations and interpretation

1. **This is not annual burn probability.** The denominator is the 1,028 equal-weight gridded ignitions, all run under one severe six-hour weather sequence.
2. **Weather variability is intentionally suppressed.** The simulation uses one representative P90 day. A directional ensemble would be needed to estimate sensitivity to wind direction and other severe-weather combinations.
3. **Spread is deterministic within each ignition scenario.** With `ROS-CV` [rate-of-spread coefficient of variation] set to 0, differences among runs mainly reflect ignition location, fuels, terrain, and the fixed weather sequence.
4. **The time horizon is short.** Six-hour footprints should not be interpreted as final-fire sizes or multi-day growth.
5. **Fuel detail is not truly 25 m.** The 100 m source fuel raster was resampled to 25 m for model alignment.
6. **Operational factors are absent.** Suppression, barriers not represented in the fuel data, spotting uncertainty, ignition probability, and forecast uncertainty are not modeled.
7. **The terrain product is the GeoBC CDED 25 m product.** It is derived from TRIM, but it is not a newly acquired high-resolution lidar DEM.

The results are appropriate for comparative planning and for identifying scenario-specific spread corridors. They are not suitable as a live-fire forecast or as a stand-alone basis for operational decisions.

## Recommended next steps

- Run a severe-weather ensemble that preserves the summer P90 threshold while sampling several observed wind directions and speeds.
- Add a lightning occurrence layer when a licensed CLDN [Canadian Lightning Detection Network] ground-strike export or an explicitly labeled satellite-lightning substitute becomes available.
- Replace the resampled 100 m fuel layer if a defensible native 25–30 m fuel product can be obtained.
- Compare the current surface with alternative durations, especially 12- and 24-hour runs, while clearly separating those scenarios.
- If the goal is annualized burn probability, add ignition likelihood and weather-frequency weights rather than treating grid ignitions equally.

## Reproducibility and source files

The scenario is defined in [`examples/aoi-25m-bcdem-summer-p90.json`](../examples/aoi-25m-bcdem-summer-p90.json). Landscape, weather, and ignition preparation is implemented in [`prepare_aoi_25m_p90.py`](../prepare_aoi_25m_p90.py), and the config-driven simulator is [`fire_sim_pipeline.py`](../fire_sim_pipeline.py).

Key saved evidence:

- [`outputs/metadata.json`](../runs/aoi-25m-bcdem-summer-p90/outputs/metadata.json)
- [`outputs/run_summary.csv`](../runs/aoi-25m-bcdem-summer-p90/outputs/run_summary.csv)
- [`data/derived/terrain_summary.json`](../runs/aoi-25m-bcdem-summer-p90/data/derived/terrain_summary.json)
- [`data/weather/prepared/weather_summary.json`](../runs/aoi-25m-bcdem-summer-p90/data/weather/prepared/weather_summary.json)
- [`data/weather/prepared/weather_library.csv`](../runs/aoi-25m-bcdem-summer-p90/data/weather/prepared/weather_library.csv)
- [`data/ignitions_500m.geojson`](../runs/aoi-25m-bcdem-summer-p90/data/ignitions_500m.geojson)
- [`web-map/index.html`](../runs/aoi-25m-bcdem-summer-p90/web-map/index.html)

Official elevation source for NTS [National Topographic System] 82F: [GeoBC 1:250,000 CDED directory](https://pub.data.gov.bc.ca/datasets/175624/82f/).
