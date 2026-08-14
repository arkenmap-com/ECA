# CODEBASE

## Purpose
This project is an ArcGIS Pro Python toolbox for Equivalent Clearcut Area (ECA) workflows.
It builds watershed-level geospatial outputs, computes recovery, and exports reporting tables.

## Entry Points
- ECA_Toolbox.pyt
  - Main toolbox definition.
  - Wires together estimate/final workflows and calls into modules under core/.
- ECA_Toolbox.pyt.xml
  - Toolbox metadata.
- ECA_Toolbox.ECAEstimateTool.pyt.xml
  - Estimate tool metadata.
- ECA_Toolbox.ECAFinalTool.pyt.xml
  - Final tool metadata.

## High-Level Flow (Estimate)
1. Validate input watershed/subbasins and build workspace outputs.
2. Clip transport layers, buffer, and merge road/rail/pipeline openings.
3. Clip opening-related layers (VRI, Results, FTA, other, pest).
4. Merge VRI + Results + FTA by OPENING_ID with overlap erasure.
5. Promote the VRI/Results/FTA opening merge for lower-priority processing.
6. Build OtherOpenings and Pest layers.
7. Split layers by H60 and subbasin; add BEC and field team attributes.
8. Apply recovery curves and create recovery output layer.
9. Export report-ready tables/workbooks.

## Core Modules
- core/config.py
  - Constants: field names, templates, hardcoded path defaults, recovery defaults.
- core/database.py
  - Spreadsheet loading, SDE connection checks, layer path resolution, optional joins.
- core/workspace.py
  - Output/scratch GDB and folder management, metadata persistence, cleanup helpers.
- core/watershed.py
  - Watershed/subbasin setup and validation.
- core/dem.py
  - DEM clip, H60 percentile logic, slope/aspect derivation.
- core/openings.py
  - Transport buffering/merge, opening clipping, VRI/Results/FTA merge, final openings build.
- core/other_openings.py
  - Other openings chain, pest processing, H60 and subbasin splits, BEC/field-team intersection.
- core/recovery.py
  - Recovery curve loading and per-feature recovery calculation.
- core/reporting.py
  - Feature-class-to-table conversion and report export formatting.
- core/erase_features.py
  - Erase helper logic compatible with available ArcGIS licensing.
- core/utils.py
  - Shared helpers (field operations, append, area calculations, mappings).

## Configuration and Templates
- templates/TKO_ECA_Input_Layers.xlsx
  - Primary workflow config.
  - Sheets: Layers, DEMs, Joins.
- templates/TKO_ECA_Recovery_Curves.xlsx
  - Preferred source for recovery curves.
- README.md
  - Detailed architecture, processing diagrams, and operational notes.

## Key Data Contracts
- Opening pipeline expects OPENING_ID and source-tracking fields to map cleanly.
- Source labels are carried through ECAsrc/ECAsrc_1 harmonization during merges/append operations.
- Spreadsheet columns in Layers/DEMs/Joins drive nearly all data source behavior.

## Outputs
- Estimate GDB: ECA_Estimate.gdb
- Final GDB: ECA_Final.gdb
- Report folders under output directory (EstimateOutputs or Final_Outputs)
- Additional docs copied to output folder when available.

## Open-Source Port
- `open_eca/data_acquisition.py`
  - ArcPy-free CLI that queries BC Data Catalogue WFS services into a
    watershed-bounded GeoPackage and writes a provenance manifest.
- `open_eca/watershed.py`
  - ArcPy-free GeoPackage preparation for watershed and sub-basin geometry.
- `open_eca/spatial.py`
  - ArcPy-free clipping and dissolved transport-buffer operations.
- `open_eca/dem.py`
  - ArcPy-free DEM clipping, 40th-percentile elevation, and H60 zone creation.
- `open_eca/recovery.py`
  - ArcPy-free recovery curves that retain the existing workbook and override contract.
- `open_eca/openings.py`
  - ArcPy-free opening precedence, H60/sub-basin split, and ECA-area operations.
- `open_eca/draft.py`
  - Complete ArcPy-free ECA Estimate workflow and report packaging.
- `open_eca/qgis/eca_draft_algorithm.py`
  - QGIS Processing Toolbox wrapper for the draft workflow.
- `open_eca/config/bc_catalogue_layers.json`
  - Starter source mapping for verified public catalogue layers.

## Maintenance Notes
- Most behavior changes should be made through spreadsheet configuration first.
- Keep field-name constants synchronized with geoprocessing expectations.
- When editing toolbox parameters in .pyt, keep companion XML metadata aligned.
- Favor small, testable changes in core/openings.py and core/other_openings.py, where most merge/priority logic lives.
