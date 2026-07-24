# Config-driven fire-simulation pipeline

`fire_sim_pipeline.py` turns the validated Nelson workflow into a reusable
area-based tool. The simulation engine remains Cell2Fire, but the study area,
input rasters, weather library, ignition data, run count, random seed, and
output locations now come from a JSON configuration file.

## Quick start

Validate the included Nelson configuration first:

```bash
python3 fire_sim_pipeline.py \
  --config examples/nelson-50km-2025.json \
  --stage validate
```

Run the complete pipeline after validation:

```bash
python3 fire_sim_pipeline.py \
  --config examples/nelson-50km-2025.json \
  --stage all
```

The stages can also be run independently:

```text
validate  check inputs and fuel classes
prepare   create Forest.asc, Data.csv, weather files, and run manifest
run       execute the independent Cell2Fire runs
aggregate create probability rasters, PNG, metadata, and run summary
map       build the Leaflet map and map tiles
all       run prepare → run → aggregate → map
```

## Creating another area

Copy the example JSON and change at least:

- `name`, `display_name`, and `study_area`;
- the four harmonized rasters under `inputs`;
- the prepared weather library and accepted scenario table;
- the historical ignition GeoJSON;
- `outputs` so the new area has its own results;
- `simulation.runs`, `seed`, and `workers` as appropriate.

For a new fuel dataset, add a `fuel_map` object. Its keys are the integer
values in the fuel raster. Each value needs a Cell2Fire FBP type; `pc` is the
optional conifer percentage for M1 mixedwood classes, while `label` and
`color` control the web-map legend. For example:

```json
"fuel_map": {
  "2": {"type": "C2", "label": "C2 spruce", "color": "#226838"},
  "415": {"type": "M1", "pc": "15", "label": "M1 15% conifer", "color": "#ffd281"},
  "101": {"type": "NF", "label": "Non-fuel", "color": "#919191"}
}
```

Then run the new configuration:

```bash
python3 fire_sim_pipeline.py --config examples/my-area.json --stage validate
python3 fire_sim_pipeline.py --config examples/my-area.json --stage all
```

Outputs are isolated by the configured area name: Cell2Fire inputs, raw run
results, probability rasters, summary metadata, and the interactive web map
are not mixed with other areas.

## Input contract

The pipeline intentionally separates acquisition from simulation. Before it
can run a new area, prepare:

1. Fuel, elevation, slope, and aspect rasters on the same grid, in the
   configured projected CRS. The current default is BC Albers, `EPSG:3005`.
2. A six-hour Cell2Fire weather library and accepted scenario table. Each
   scenario must have exactly `simulation.weather_hours` rows in the library.
3. A point GeoJSON of historical or scenario ignition locations. The default
   property names are `FIRE_NUMBER`, `FIRE_YEAR`, and `FIRE_CAUSE`; override
   them with `ignition_fields` when needed.
4. A Cell2Fire `fbp_lookup_table.csv` compatible with the FBP types in the
   fuel map.

Weather downloading and fuel/terrain acquisition are not silently automated:
those source choices require area-specific decisions and quality checks. Once
the prepared inputs exist, the simulation and mapping workflow is one command.

## Outputs

The aggregate stage writes `burn_probability.tif/.asc`, `burn_count.tif/.asc`,
`run_summary.csv`, `metadata.json`, and a colorized probability PNG. The map
stage writes a self-contained local Leaflet application with probability, fuel,
ignition, OpenStreetMap, plain-grey, and no-basemap options.

This remains a planning and research workflow. Results are not operational
fire forecasts and should be calibrated and sensitivity-tested before use for
decision-making.

## Local GUI

The same runner can be controlled from a local browser interface:

```bash
python3 fire_sim_gui.py
```

Open [http://127.0.0.1:4180](http://127.0.0.1:4180). The GUI loads the Nelson
example, lets you edit the area metadata, input paths, run count, seed, worker
count, and output folder, then exposes **Validate inputs**, **Run full
pipeline**, live logs, and **Stop job**. It launches the same
`fire_sim_pipeline.py` stages, so command-line and GUI runs use the same
configuration and outputs.

The GUI is intentionally local-only. It does not download BCWS data or invent
fuel/topography inputs; those prepared files still need to be supplied for a
new area.
