# Open ECA web app

Hosted entry point: <https://arkenmap-com.github.io/ECA/>

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
Geographic Warehouse. Use the bundled calibrated Kootenay recovery curves with
the matching field-team name, or use the synthetic curves for a test run, then
download the resulting GeoPackage and reports or use the interactive map
dashboard. Live acquisition requires `ogr2ogr` from GDAL (QGIS includes it).

The default **Synthetic test preset** contains plausible but invented height and
crown-closure thresholds for common BC BEC zones under the field-team name
`Synthetic Test`. It exists only to exercise the workflow. It has not been
calibrated or approved and must not be used for operational decisions.

Choose **Prepared cache** to retain the previous offline/reproducible workflow.
That mode accepts an existing catalogue-input GeoPackage instead of making
live layer requests. Each live run also provides its acquired input GeoPackage
and a provenance JSON manifest with source URLs, filters, feature counts,
timestamp, bounding box, and SHA-256 checksum.

The public live configuration includes current pest polygons. Historic pest
polygons are not requested because BC currently exposes that dataset through
the catalogue custom-download service rather than a public WFS endpoint; they
can still be supplied through a prepared cache. Live acquisition includes the
authoritative RESULTS Openings view as a bounded gap check: mapped,
non-retired openings disturbed within 20 years are considered only outside
the higher-priority VRI, RESULTS forest-cover, and FTA geometry. Any included
remainder is clearly labelled and assigned zero recovery for conservative
manual review; it never replaces higher-quality source geometry.

By default the app discovers NRCan's current 30 m Medium Resolution Digital
Elevation Model terrain asset through its public STAC catalogue, streams only
the selected watershed, and calculates H60 from the 40th percentile of valid
cells. It records the source asset, catalogue record, licence, timestamp, CRS,
and checksum in a downloadable provenance file. The consistent Canada-wide
MRDEM is preferred over the higher-resolution HRDEM mosaic because H60 requires
complete watershed coverage and HRDEM remains project-dependent.

You can instead upload a georeferenced GeoTIFF covering the watershed or choose
**No H60 split**. Uploaded elevations should be in metres. With a DEM, the app
splits openings into `H60 Above` and `H60 Below` and makes the clipped raster
available with the completed run. Without one, it labels the elevation zone
`Entire Watershed`.

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

## Hosted deployment

`Dockerfile` and `render.yaml` deploy the Python/GDAL service to Render. The
static page in `docs/` embeds that service at the GitHub Pages project URL.
The free Render instance uses ephemeral storage, runs one analysis at a time,
and may take about a minute to wake after an idle period. Completed runs and
uploads are not durable across service restarts or redeploys.
