# Open ECA web app

This is a local-first browser interface around the existing Open ECA draft
workflow. It stores uploads and outputs under `webapp_data/` by default and
binds only to `127.0.0.1`, so it does not publish watershed data anywhere.

Run it from the repository root:

```shell
python3 -m webapp.app
```

On macOS, you can also double-click `start_webapp.command` in the project
folder; keep the Terminal window it opens running while you use the app.

Open <http://127.0.0.1:8000>. Search the BC Freshwater Atlas by watershed
name and select the exact `NAMED_WATERSHED_ID` result. In the default **Live
BC data** mode, the app downloads that boundary and the standard analysis
layers directly from public BC OpenMaps WFS services backed by the BC
Geographic Warehouse. Supply the recovery curves and field-team name, then
download the resulting GeoPackage and reports or use the interactive map
dashboard. Live acquisition requires `ogr2ogr` from GDAL (QGIS includes it).

Choose **Prepared cache** to retain the previous offline/reproducible workflow.
That mode accepts an existing catalogue-input GeoPackage instead of making
live layer requests. Each live run also provides its acquired input GeoPackage
and a provenance JSON manifest with source URLs, filters, feature counts,
timestamp, bounding box, and SHA-256 checksum.

The public live configuration includes current pest polygons. Historic pest
polygons are not requested because BC currently exposes that dataset through
the catalogue custom-download service rather than a public WFS endpoint; they
can still be supplied through a prepared cache.

This streamlined web workflow deliberately does not use a DEM. It reports ECA
for the complete watershed and labels the elevation zone `Entire Watershed`.
It does not calculate or report an H60 elevation split. Use the command-line
or QGIS workflow with a DEM when H60 Above/Below results are required.

## Additional inputs

Use **Add input layer** for a GeoJSON, shapefile, or GeoPackage layer that is
not in the catalogue cache. Choose **ECA opening** to add only previously
uncovered area to the ECA analysis, or **Context only** to keep the layer in
the `other_openings` result without adding it to the recovery calculation.
For a multi-layer GeoPackage, provide the layer name. Additional ECA-opening
layers default to zero recovery, consistent with the existing lower-priority
opening sources. An optional buffer is applied in metres before the layer is
clipped to the watershed.

For a shared deployment, run behind authenticated HTTPS and move the data
directory to managed storage. Do not expose this local development server
directly to the internet.
