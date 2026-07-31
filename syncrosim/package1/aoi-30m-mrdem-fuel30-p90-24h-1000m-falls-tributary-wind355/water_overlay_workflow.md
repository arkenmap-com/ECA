# Water-cell overwrite workflow

## Objective

Create a fuel raster in which hydrographic features are represented as FBP
water/non-fuel cells while retaining the original 30 m fuel grid, extent,
alignment, projection, and NoData mask.

## Inputs

1. `fuel_30m.tif` — the existing native 30 m FBP raster on the aligned
   EPSG:3005 grid.
2. BC Freshwater Atlas Stream Network layer 34, queried for
   `EDGE_TYPE = 1000` (Stream - Main Flow) and `GNIS_NAME IS NOT NULL`.
3. BC Freshwater Atlas Lakes layer 20, using all lake polygons intersecting
   the study grid.
4. The selected main tributary to Falls Creek from Stream Network layer 34.

The official services used were:

- [Freshwater Atlas streams](https://delivery.maps.gov.bc.ca/arcgis/rest/services/whse/bcgw_pub_whse_basemapping/MapServer/34)
- [Freshwater Atlas lakes](https://delivery.maps.gov.bc.ca/arcgis/rest/services/whse/bcgw_pub_whse_basemapping/MapServer/20)

## Falls Creek tributary selection

The existing named-mainstream export contained Falls Creek itself but not its
unnamed tributary segments. To select the additional tributary reproducibly:

1. Query the stream network around the named Falls Creek segments.
2. Identify unnamed `EDGE_TYPE = 1000` segments that intersect Falls Creek.
3. Select the highest-order/highest-magnitude intersecting unnamed branch:
   Freshwater Atlas `OBJECTID = 3124020`, `STREAM_ORDER = 4`,
   `STREAM_MAGNITUDE = 24`.
4. Use its `BLUE_LINE_KEY = 356567471` to retrieve all 12 available segments
   of that continuous tributary path within the AOI. This includes 11 main-flow
   segments and one river-skeleton segment needed to retain the mapped path's
   continuity.

The selected features are preserved in
`hydro/fwa_falls_creek_main_tributary.geojson`.

## Rasterization and overwrite

The workflow is implemented in `overlay_fwa_water_on_fuel_30m.py`:

1. Buffer every selected stream centerline by 15 m.
2. Rasterize buffered streams and lake polygons onto the exact fuel raster
   transform using `all_touched=True`.
3. Combine the stream and lake masks.
4. Intersect the mask with valid fuel cells only; NoData cells remain `-9999`.
5. Assign value `102` to every intersecting valid cell. Code `102` is treated
   as FBP `NF` (non-fuel) water by the pipeline.
6. Write a tiled, DEFLATE-compressed GeoTIFF and record the method in the
   raster tags and `hydro/overlay_summary.json`.

This is an overwrite operation: where a stream or lake overlaps a fuel class,
the output value becomes `102`; where it does not overlap, the original fuel
value is unchanged. The original raster is never modified.

## Result summary

- Original valid cells: 286,190
- Original water cells: 6,113
- Water cells after overlay: 13,731
- New water cells added: 7,618
- Valid cells touched by buffered streams: 6,606
- Valid cells touched by lakes: 4,180

The output raster is
`inputs/fuel_30m_hydro_named_mainstreams_falls_tributary.tif`.

