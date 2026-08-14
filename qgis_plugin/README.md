# ECA Analysis Toolbox for QGIS

This is an installable QGIS 3.28+ Processing plugin for the open-source ECA
draft workflow. It creates a review-ready GeoPackage, clipped DEM, and CSV/HTML
reports using the existing local catalogue cache, DEM, watershed, and recovery
curve workbook.

## Build and install

From the repository root, build a distributable plugin ZIP:

```shell
python3 build_qgis_plugin.py
```

In QGIS, open **Plugins > Manage and Install Plugins > Install from ZIP**, select
`dist/eca_analysis_toolbox.zip`, then enable **ECA Analysis Toolbox**. Its
**Create ECA Draft** algorithm appears under **Processing Toolbox > ECA Analysis
Toolbox**. A green watershed icon also appears in the main QGIS toolbar; click
it to open the tool directly.

The release ZIP includes the ECA engine but relies on the QGIS Python runtime
having the packages in `requirements.txt` (notably GeoPandas, Rasterio, NumPy,
and Pandas). Install those packages into the Python environment used by your
QGIS installation before running the algorithm. On macOS with the official
QGIS bundle, this is typically:

```shell
/Applications/QGIS-LTR.app/Contents/MacOS/bin/python3.9 -m pip install --user --upgrade \
  "geopandas>=1.0" "rasterio>=1.3" "pandas>=2.0" "numpy>=1.26"
```

The output folder is intentionally required to be new or empty, preventing an
analysis run from silently overwriting a previous draft.
