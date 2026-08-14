# Open ECA data acquisition

This ArcPy-free module downloads watershed-bounded vector inputs from BC Data
Catalogue WFS services into one GeoPackage and writes a matching provenance
manifest. The acquisition bbox uses EPSG:3005.

```shell
python3 -m open_eca.data_acquisition catalogue-search "forest vegetation"
python3 -m open_eca.data_acquisition acquire \
  --config open_eca/config/bc_catalogue_layers.json \
  --bbox 1050000 450000 1060000 460000 \
  --output data/example_inputs.gpkg
```

The provided configuration contains the verified VRI source and is not the
final data contract. Add the remaining public vector layers after their
catalogue records and fields have been verified. Supply DEM data separately as a local GeoTIFF
or Cloud Optimized GeoTIFF; WFS is a vector service.

`ogr2ogr` must be on `PATH`. It is supplied by GDAL and by standard QGIS
installations. The module explicitly requests WFS 1.1 because the current
DataBC public service rejects GDAL's WFS 2.0 attribute-filter encoding.

## Watershed preparation

The first analysis module writes canonical `watershed` and `subbasins` layers
to a GeoPackage in BC Albers (EPSG:3005). It calculates hectare areas and
normalizes the fields used by the next porting stages.

```shell
python3 -m open_eca.watershed \
  --input data/subbasins.geojson \
  --basin-field BASIN_NAME \
  --subbasin-field SUBBASIN_NAME \
  --output data/watershed.gpkg
```

## DEM and H60 zones

The DEM module clips the source DEM, calculates the valid-cell 40th percentile,
and writes H60 Above/Below polygons with hectare areas.

```shell
python3 -m open_eca.dem \
  --dem data/source_dem.tif \
  --watershed data/watershed.gpkg \
  --clipped-dem data/clipped_dem.tif \
  --zones data/h60_zones.gpkg
```

## Recovery curves

The recovery module consumes the existing recovery-curve workbook and a
QGIS-reviewed openings layer. It produces `Recovery` and `Error` fields and
supports the existing `Override` convention when `--override` is supplied.
An equivalent nested JSON curve file is also supported for headless use.
The web app defaults to the bundled Kootenay calibration and requires an
explicit field team. Its province-wide synthetic preset is for testing only;
use a locally reviewed upload outside the five Kootenay field teams. Curve
loaders preserve decimal thresholds and reject malformed or non-monotonic
tables before analysis.

## Opening assembly

`open_eca.openings` contains the reusable workflow operations that merge the
VRI, RESULTS forest-cover, and FTA opening sources; add lower-priority sources
only outside already-counted openings; split by H60 and sub-basin; and
calculate ECA-ready hectare fields. The public RESULTS Openings administrative
boundary is also acquired as a conservative gap check. Only mapped,
non-retired openings disturbed in the past 20 years are requested. Their
geometry is added at zero recovery only where it is not already represented by
VRI, RESULTS forest cover, or FTA, so gross opening boundaries cannot replace
better vegetation or tenure geometry. These records are labelled `RESULTS
Openings (recent unmatched)` for review.

Polygon interiors are topology-cleaned at every opening-source boundary. Within
a single source, earlier cached records retain the shared area and later
records are trimmed; between sources, the documented source-precedence chain
controls which geometry retains it. The assembled openings, other openings,
H60/sub-basin splits, and BEC recovery splits are each validated to contain no
positive-area overlap before output is written.

## Complete draft tool

Acquire the configured public layers into an input cache, provide a local DEM,
then run the draft tool. The BBOX must be EPSG:3005.

```shell
python3 -m open_eca.data_acquisition acquire \
  --config open_eca/config/bc_catalogue_layers.json \
  --bbox XMIN YMIN XMAX YMAX \
  --output data/catalogue_inputs.gpkg

python3 -m open_eca.draft \
  --watershed data/subbasins.gpkg \
  --basin-field BASIN_NAME \
  --subbasin-field SUBBASIN_NAME \
  --inputs data/catalogue_inputs.gpkg \
  --dem data/dem.tif \
  --recovery-curves templates/TKO_ECA_Recovery_Curves.xlsx \
  --field-team Boundary \
  --output outputs/example_draft
```

The output folder contains `ECA_Draft.gpkg`, a clipped DEM, a provenance
manifest, CSV/HTML reports, and an editable `openings` layer. Use that
layer for the analyst QA/QC pass before a later final-tool run.

## Interactive map dashboard

Create a portable HTML map from a completed draft. It embeds the draft's map
data and uses Leaflet/OpenStreetMap for the interactive base map, so opening it
requires internet access for the map library and tiles.

```shell
python3 -m open_eca.dashboard \
  --draft outputs/example_draft/ECA_Draft.gpkg \
  --output outputs/example_draft/eca_dashboard.html
```

For QGIS, build and install the `qgis_plugin` package documented in
[`qgis_plugin/README.md`](../qgis_plugin/README.md). It registers **Create ECA
Draft** in the Processing Toolbox and includes the Open ECA engine in the
installable release ZIP. For quick development only, you can instead add
`open_eca/qgis/eca_draft_algorithm.py` to a QGIS Processing scripts folder.

## Local web app

Run a browser-based version of the draft workflow locally:

```shell
python3 -m webapp.app
```

Then open <http://127.0.0.1:8000>. The app searches the BC Freshwater Atlas
for the watershed boundary, accepts a catalogue cache and recovery curves, and
can include extra local vector layers as ECA-opening or context-only inputs.
The default web mode automatically clips NRCan's open, Canada-wide 30 m MRDEM
terrain model and activates the same H60 Above/Below split used by the
command-line workflow. An uploaded GeoTIFF can override it, or H60 can be
disabled explicitly. Each completed run has an embedded dashboard plus
GeoPackage, CSV, clipped-DEM, and DEM-provenance downloads. See
[`webapp/README.md`](../webapp/README.md) for the deployment and data-handling
notes.
