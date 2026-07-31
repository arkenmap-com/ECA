# SyncroSim Package 1 data bundle

This folder contains the input data assembled for the Nelson-area fire-spread
scenario. It is a data bundle for loading into an existing SyncroSim model
package; it is not a native `.ssim` library or a complete SyncroSim XML/code
package.

## Scenario

- 30 m aligned grid in BC Albers, EPSG:3005; 712 rows by 736 columns.
- Native 30 m NRCan FBP fuel data, with water/non-fuel code `102` applied to
  named main streams, all Freshwater Atlas lakes, and the selected main
  tributary to Falls Creek.
- 257 ignition points on a projected 1,000 m grid inside the AOI.
- 24 hourly records from Smallwood station 404 for 20 August 2018, the
  observed day nearest the June–August 2016–2025 daily-noon FWI P90, with
  wind direction overridden to 355° from north (north-northwest).
- MRDEM 30 m elevation, with matching slope and aspect rasters.

## Folder contents

- `inputs/` — GeoTIFF, GeoJSON, CSV, and FBP lookup inputs for SyncroSim.
- `hydro/` — Freshwater Atlas source features and the raster-overlay summary.
- `cell2fire/` — companion Cell2Fire-ready `Forest.asc`, `Data.csv`, weather,
  and ignition run manifest generated from the same inputs.
- `outputs/` — aggregated burn-count and conditional burn-frequency rasters,
  summary CSV/JSON, and a colorized PNG.
- `web-map/` — local Leaflet map showing the burn-frequency and fuel layers.
- `package1_config.json` — repository pipeline configuration used to prepare
  the companion Cell2Fire files.
- `package1_manifest.json` — compact provenance and count summary.
- `water_overlay_workflow.md` — reproducible water-cell overwrite method.

## Rebuild the companion Cell2Fire input

From the repository root:

```bash
python3 fire_sim_pipeline.py \
  --config syncrosim/package1/aoi-30m-mrdem-fuel30-p90-24h-1000m-falls-tributary-wind355/package1_config.json \
  --stage prepare
```

The 257-run Cell2Fire ensemble has been completed for this 1,000 m grid with
355° wind from north. The result is a conditional burn-frequency experiment
under one fixed 24-hour weather sequence, not an annual wildfire probability
or operational forecast.
