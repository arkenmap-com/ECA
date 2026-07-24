# AOI [area of interest] 24-hour prevailing-wind run - partial 500-run result

## Result

The simulation was stopped at the requested cutoff and aggregated using exactly **runs 1-500**. Five additional runs completed while the eight parallel workers were being stopped; those outputs remain saved but were excluded from the aggregation.

| Statistic | Partial result |
|---|---:|
| Aggregated runs | 500 |
| Requested exhaustive grid | 1,028 |
| Mean burned area | 16.90 km² |
| Median burned area | 13.89 km² |
| 90th-percentile burned area | 32.52 km² |
| Maximum burned area | 47.42 km² |
| Maximum cell reach frequency | 29.8% |

The probability surface and web map are available in the corresponding run directory. These results are conditional fire-reach frequencies, not annual burn probabilities.

## Prevailing-wind choice and rationale

The simulation fixed wind direction at **193° from south-southwest**, using the meteorological convention that direction identifies where wind comes from. The modeled wind therefore pushed fire primarily toward north-northeast. Cell2Fire accepts integer wind azimuths, so the calculated 193.38° direction was rounded to 193°.

The direction was calculated as the **wind-speed-weighted circular mean** of 20,178 non-calm hourly Smallwood observations from June-August 2016-2025.

Wind speed was used as the weight because stronger winds exert more directional influence on fire spread than calm or light-wind observations. The full ten-summer record was used so the direction represents prevailing severe-season flow rather than the trajectory from only 20 August 2018.

For comparison:

- the most frequent individual 22.5° sector was south-southeast, representing 13.96% of observations;
- the unweighted circular average was 231.22° from southwest; and
- the selected wind-speed-weighted circular average was 193.38° from south-southwest.

The selected direction has a resultant vector concentration of 0.395. This indicates a dispersed directional distribution, so 193° should be understood as a representative simplification rather than a strongly dominant wind direction.

## Weather treatment

The run retained the observed 24 hourly records from 20 August 2018 for:

- precipitation;
- temperature;
- relative humidity;
- wind speed;
- FFMC [Fine Fuel Moisture Code];
- ISI [Initial Spread Index]; and
- FWI [Fire Weather Index].

DMC [Duff Moisture Code], DC [Drought Code], and BUI [Build Up Index] were held at their observed noon values because the source supplies them as daily indices. The observed hourly wind directions were replaced by the fixed 193° prevailing direction.

## Critical limitation: spatially biased cutoff

The ignition manifest is spatially ordered. Runs 1-500 are therefore a contiguous first portion of the 1,028-point ignition grid, not a spatially balanced random or systematic sample of the entire AOI.

Consequently:

- the 29.8% maximum reach frequency uses 500 as its denominator;
- the surface is strongly influenced by which half of the ignition grid was completed first;
- it should not be compared directly with the complete 1,028-run six-hour surface; and
- it should not be described as a full-AOI burn-probability estimate.

If a defensible 500-run result is needed, the preferred approach is to create a new spatially balanced 500-point ignition sample before running the model.

## Saved evidence

- [Weather and prevailing-wind rationale](../runs/aoi-25m-bcdem-summer-p90-24h-prevailing/data/weather/prepared/weather_summary.json)
- [Hourly weather library](../runs/aoi-25m-bcdem-summer-p90-24h-prevailing/data/weather/prepared/weather_library.csv)
- [Aggregation metadata](../runs/aoi-25m-bcdem-summer-p90-24h-prevailing/outputs/metadata.json)
- [Run-level burned-cell summary](../runs/aoi-25m-bcdem-summer-p90-24h-prevailing/outputs/run_summary.csv)
- [Burn-frequency image](../runs/aoi-25m-bcdem-summer-p90-24h-prevailing/outputs/burn_probability.png)
- [Interactive web map](../runs/aoi-25m-bcdem-summer-p90-24h-prevailing/web-map/index.html)

