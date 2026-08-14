"""Complete open-source ECA draft (estimate) workflow.

All analysis runs from a locally cached input GeoPackage and local DEM. Source
data can therefore be inspected in QGIS and reproduced without ArcGIS Pro or
enterprise database access.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import geopandas as gpd
import pandas as pd

from open_eca.dem import derive_h60, whole_watershed_zone
from open_eca.openings import (
    add_opening_area,
    append_lower_priority,
    build_other_openings,
    clip_sources_to_watershed,
    merge_base_openings,
    split_openings,
)
from open_eca.recovery import apply_recovery, load_curves
from open_eca.spatial import buffer_transport, clip_to_boundary
from open_eca.watershed import prepare_watershed


@dataclass(frozen=True)
class DraftResult:
    basin: str
    basin_area_ha: float
    h60_elevation: float | None
    geopackage: Path
    report_dir: Path
    field_team: str


@dataclass(frozen=True)
class AdditionalInput:
    """A locally supplied layer to include in a draft analysis.

    ``role`` determines whether the layer contributes to ECA as a lower-priority
    opening or is retained as a non-recovering/context opening.  A GeoPackage
    layer name is optional because GeoJSON and single-layer GeoPackages do not
    need one.
    """

    path: Path
    source_label: str
    role: str = "opening"
    layer: str | None = None
    zero_recovery: bool = True
    buffer_m: float = 0


def _read_layer(path: Path, layer: str, required: bool = False) -> gpd.GeoDataFrame | None:
    try:
        return gpd.read_file(path, layer=layer)
    except Exception as error:
        if required:
            raise ValueError(f"Required input layer '{layer}' could not be read from {path}.") from error
        return None


def _read_additional_input(input_spec: AdditionalInput) -> gpd.GeoDataFrame:
    """Read and validate one user-supplied vector layer."""
    try:
        layer = gpd.read_file(input_spec.path, layer=input_spec.layer)
    except Exception as error:
        detail = f" layer '{input_spec.layer}'" if input_spec.layer else ""
        raise ValueError(f"Could not read additional input{detail} from {input_spec.path.name}.") from error
    if layer.empty:
        raise ValueError(f"Additional input '{input_spec.source_label}' is empty.")
    if layer.crs is None:
        raise ValueError(f"Additional input '{input_spec.source_label}' has no CRS.")
    if input_spec.role not in {"opening", "other"}:
        raise ValueError(f"Additional input '{input_spec.source_label}' has an invalid role '{input_spec.role}'.")
    if input_spec.buffer_m < 0:
        raise ValueError(f"Additional input '{input_spec.source_label}' has a negative buffer distance.")
    return layer


def _concat(parts: list[gpd.GeoDataFrame], crs: object) -> gpd.GeoDataFrame:
    parts = [part for part in parts if part is not None and not part.empty]
    if not parts:
        return gpd.GeoDataFrame(geometry=[], crs=crs)
    return gpd.GeoDataFrame(pd.concat(parts, ignore_index=True), crs=crs)


def _field_team(
    watershed: gpd.GeoDataFrame,
    teams: gpd.GeoDataFrame | None,
    supplied: str | None,
) -> str:
    if supplied:
        return supplied
    if teams is None or "FIELD_TEAM" not in teams:
        raise ValueError("Provide --field-team or an input field_teams layer with FIELD_TEAM.")
    intersection = gpd.overlay(teams.to_crs(watershed.crs), watershed[["geometry"]], how="intersection")
    if intersection.empty:
        raise ValueError("No field-team boundary intersects the watershed.")
    areas = intersection.assign(_area=intersection.geometry.area).groupby("FIELD_TEAM")["_area"].sum()
    return str(areas.idxmax())


def _transport_layers(clipped: dict[str, gpd.GeoDataFrame], watershed: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    distances = {
        "dra_minor_roads": 4, "ften_roads": 4,
        "dra_major_roads": 9, "railways": 9, "pipelines": 9,
    }
    available = [(clipped[name], distance) for name, distance in distances.items() if name in clipped]
    return buffer_transport(available, watershed) if available else gpd.GeoDataFrame(geometry=[], crs=watershed.crs)


def _recovery_layer(
    openings: gpd.GeoDataFrame,
    bec: gpd.GeoDataFrame,
    field_team: str,
    curves: dict[str, Any],
) -> gpd.GeoDataFrame:
    required = {"ZONE", "SUBZONE"}
    missing = required - set(bec.columns)
    if missing:
        raise ValueError(f"BEC layer is missing fields: {', '.join(sorted(missing))}")
    openings_bec = gpd.overlay(
        openings, bec[["ZONE", "SUBZONE", "geometry"]].to_crs(openings.crs), how="intersection",
    )
    openings_bec["Field_Team"] = field_team
    openings_bec = add_opening_area(openings_bec)
    return add_opening_area(apply_recovery(openings_bec, curves, has_override=False))


def _write_layers(path: Path, layers: dict[str, gpd.GeoDataFrame]) -> None:
    temporary = path.with_suffix(".tmp.gpkg")
    if temporary.exists():
        temporary.unlink()
    first = True
    try:
        for name, layer in layers.items():
            if layer is None:
                continue
            layer.to_file(temporary, layer=name, driver="GPKG", mode="w" if first else "a")
            first = False
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _write_reports(report_dir: Path, recovery: gpd.GeoDataFrame, basin_area: float) -> None:
    report_dir.mkdir(parents=True, exist_ok=True)
    columns = ["ECAsrc", "ELEVATION", "Sub_Basin"]
    summary = recovery.groupby(columns, dropna=False).agg(
        Openings_Hectares=("Hectares", "sum"), ECA_Hectares=("ECA_Hectares", "sum"),
    ).reset_index()
    summary["ECA_Percent_of_Basin"] = summary["ECA_Hectares"] / basin_area * 100
    summary.to_csv(report_dir / "eca_summary.csv", index=False)
    recovery.drop(columns="geometry").to_csv(report_dir / "openings_recovery.csv", index=False)
    (report_dir / "eca_summary.html").write_text(
        "<html><body><h1>ECA Draft Summary</h1>" + summary.to_html(index=False) + "</body></html>",
        encoding="utf-8",
    )


def run_draft(
    input_watershed: Path,
    basin_field: str,
    subbasin_field: str,
    inputs_gpkg: Path,
    dem_path: Path | None,
    curves: dict[str, Any],
    output_dir: Path,
    field_team: str | None = None,
    additional_inputs: tuple[AdditionalInput, ...] = (),
) -> DraftResult:
    """Run the complete estimate workflow from local open data inputs."""
    if output_dir.exists() and any(output_dir.iterdir()):
        raise FileExistsError(f"Output directory is not empty: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    workspace = Path(tempfile.mkdtemp(prefix="eca-draft-", dir=output_dir))
    try:
        watershed_gpkg = workspace / "watershed.gpkg"
        watershed_result = prepare_watershed(
            input_watershed, basin_field, subbasin_field, watershed_gpkg,
        )
        watershed = gpd.read_file(watershed_gpkg, layer="watershed")
        subbasins = gpd.read_file(watershed_gpkg, layer="subbasins")
        h60_elevation: float | None = None
        if dem_path is None:
            h60_zones = whole_watershed_zone(watershed)
        else:
            h60 = derive_h60(dem_path, watershed, workspace / "clipped_dem.tif", workspace / "h60.gpkg")
            h60_zones = gpd.read_file(h60.zones, layer="h60_zones")
            h60_elevation = h60.percentile_40th

        names = [
            "vri_openings", "results_forest_cover", "results_openings", "fta_pending_blocks", "consolidated_cut_blocks",
            "wildfire_current", "wildfire_20_years", "dra_minor_roads", "ften_roads", "dra_major_roads",
            "railways", "pipelines", "natural_openings", "vri_water", "results_pas", "private_lands",
            "historic_wildfire", "current_pest", "historic_pest", "bec_zones", "field_teams",
        ]
        raw = {name: layer for name in names if (layer := _read_layer(inputs_gpkg, name)) is not None}
        if "vri_openings" not in raw or "bec_zones" not in raw:
            raise ValueError("Inputs must include vri_openings and bec_zones layers.")
        clipped = clip_sources_to_watershed([(layer, name) for name, layer in raw.items()], watershed)
        selected_team = _field_team(watershed, clipped.get("field_teams"), field_team)

        main = merge_base_openings(
            clipped["vri_openings"], clipped.get("results_forest_cover"), clipped.get("fta_pending_blocks"),
        )
        lower: list[tuple[gpd.GeoDataFrame, str] | tuple[gpd.GeoDataFrame, str, bool]] = [
            (clipped[name], label) for name, label in (
                ("results_openings", "RESULTS Openings (recent unmatched)"),
                ("consolidated_cut_blocks", "Consolidated Cutblocks"),
                ("wildfire_current", "Current Wildfire"),
                ("wildfire_20_years", "Wildfire Past Twenty Years"),
            ) if name in clipped
        ]
        additional_other: list[tuple[gpd.GeoDataFrame, str]] = []
        for input_spec in additional_inputs:
            layer = _read_additional_input(input_spec).to_crs(watershed.crs)
            if input_spec.buffer_m:
                layer = layer.copy()
                layer["geometry"] = layer.geometry.buffer(input_spec.buffer_m)
            layer = clip_to_boundary(layer, watershed)
            if input_spec.role == "opening":
                lower.append((layer, input_spec.source_label, input_spec.zero_recovery))
            else:
                additional_other.append((layer, input_spec.source_label))
        main = append_lower_priority(main, lower)
        transport = _transport_layers(clipped, watershed)
        other_inputs = ([(transport, "Roads, Railways, Pipelines")] if not transport.empty else []) + [
            (clipped[name], label) for name, label in (
                ("natural_openings", "VRI Natural Openings"), ("vri_water", "VRI Water"),
                ("results_pas", "Results PAS"),
            ) if name in clipped
        ]
        other_inputs.extend(additional_other)
        other = build_other_openings(main, other_inputs)
        recovery = _recovery_layer(split_openings(main, h60_zones, subbasins), clipped["bec_zones"], selected_team, curves)
        pest = _concat([clipped.get("current_pest"), clipped.get("historic_pest")], watershed.crs)

        output_gpkg = output_dir / "ECA_Draft.gpkg"
        _write_layers(output_gpkg, {
            "watershed": watershed, "subbasins": subbasins, "h60_zones": h60_zones,
            "openings": main, "other_openings": other, "openings_recovery": recovery,
            "pest": pest, "private_lands": clipped.get("private_lands"),
            "historic_wildfire": clipped.get("historic_wildfire"),
        })
        if dem_path is not None:
            shutil.copy2(workspace / "clipped_dem.tif", output_dir / "clipped_dem.tif")
        report_dir = output_dir / "reports"
        _write_reports(report_dir, recovery, watershed_result.basin_area_ha)
        dem_details: dict[str, Any] | None = None
        if dem_path is not None:
            dem_details = {"path": str(dem_path)}
            provenance_path = dem_path.with_suffix(".provenance.json")
            if provenance_path.is_file():
                dem_details["provenance"] = json.loads(provenance_path.read_text(encoding="utf-8"))
        (output_dir / "draft_manifest.json").write_text(json.dumps({
            "format": "open-eca-draft/v1", "created_at": datetime.now(timezone.utc).isoformat(),
            "basin": watershed_result.basin, "basin_area_ha": watershed_result.basin_area_ha,
            "h60_elevation": h60_elevation, "field_team": selected_team,
            "inputs": str(inputs_gpkg), "dem": dem_details,
        }, indent=2) + "\n", encoding="utf-8")
        return DraftResult(watershed_result.basin, watershed_result.basin_area_ha, h60_elevation, output_gpkg, report_dir, selected_team)
    finally:
        shutil.rmtree(workspace, ignore_errors=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--watershed", type=Path, required=True)
    parser.add_argument("--basin-field", required=True)
    parser.add_argument("--subbasin-field", required=True)
    parser.add_argument("--inputs", type=Path, required=True, help="Catalogue-cached input GeoPackage.")
    parser.add_argument("--dem", type=Path, help="Optional GeoTIFF; omit to run without an H60 elevation split.")
    parser.add_argument("--recovery-curves", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--field-team", help="Optional override; otherwise derive from field_teams.")
    args = parser.parse_args(argv)
    try:
        result = run_draft(
            args.watershed, args.basin_field, args.subbasin_field, args.inputs, args.dem,
            load_curves(args.recovery_curves), args.output, args.field_team,
        )
    except (FileExistsError, OSError, ValueError) as error:
        parser.error(str(error))
    print(f"Draft ECA complete: {result.geopackage}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
