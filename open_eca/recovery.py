"""Recovery-curve calculation independent of ArcPy."""

from __future__ import annotations

import argparse
import json
import re
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import geopandas as gpd
import pandas as pd


_ZEROS = (0,) * 11
_ONES = (1,) * 11
_TWOS = (2,) * 11
ERRORS = {
    999: "Recovery Curve Code Error",
    998: "BEC Error",
    997: "Field Team Error",
    996: "BEC Sub-Zone Error",
}


def _load_xlsx_curves_without_openpyxl(path: Path) -> dict[str, Any]:
    """Read this project's small, unshared-string recovery workbook with stdlib.

    This keeps the CLI runnable in a minimal QGIS/GDAL Python environment where
    ``openpyxl`` is not installed.  It is intentionally limited to the
    recovery-curve workbook layout rather than being a general XLSX reader.
    """
    namespace = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
                 "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships"}
    columns = ("h0", "h1", "h2", "h3", "h4", "h5", "cc0", "cc1", "cc2", "cc3", "cc4")
    with zipfile.ZipFile(path) as archive:
        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        sheets = [(sheet.attrib["name"], index + 1) for index, sheet in enumerate(workbook.findall("x:sheets/x:sheet", namespace))]
        curves: dict[str, Any] = {}
        for sheet_name, index in sheets:
            root = ET.fromstring(archive.read(f"xl/worksheets/sheet{index}.xml"))
            records: list[dict[str, str]] = []
            for row in root.findall("x:sheetData/x:row", namespace):
                record: dict[str, str] = {}
                for cell in row.findall("x:c", namespace):
                    match = re.match(r"([A-Z]+)", cell.attrib["r"])
                    if not match:
                        continue
                    value = cell.findtext("x:is/x:t", default="", namespaces=namespace)
                    if not value:
                        value = cell.findtext("x:v", default="", namespaces=namespace)
                    record[match.group(1)] = value
                records.append(record)
            if not records:
                continue
            header = records[0]
            column_for_key = {value: column for column, value in header.items()}
            team: dict[str, Any] = {}
            grouped: dict[str, list[dict[str, str]]] = {}
            for record in records[1:]:
                zone = record.get("A", "").strip()
                if zone:
                    grouped.setdefault(zone, []).append(record)
            for zone, rows in grouped.items():
                subzones = [row for row in rows if row.get("B", "").strip()]
                if subzones:
                    values = {
                        row["B"].strip(): tuple(int(row.get(column_for_key[column], "0")) for column in columns)
                        for row in subzones
                    }
                    team[zone] = {**values, "_default": _TWOS}
                elif len(rows) == 1:
                    row = rows[0]
                    team[zone] = tuple(int(row.get(column_for_key[column], "0")) for column in columns)
            team["_default"] = _ZEROS
            curves[sheet_name.strip()] = team
    curves["_default"] = _ONES
    return curves


def load_curves(path: Path) -> dict[str, Any]:
    """Load field-team recovery curves from the existing workbook or JSON format."""
    if path.suffix.lower() == ".json":
        with path.open(encoding="utf-8") as stream:
            raw = json.load(stream)

        def normalize(value: Any) -> Any:
            if isinstance(value, list):
                return tuple(value)
            if isinstance(value, dict):
                return {key: normalize(item) for key, item in value.items()}
            return value

        return normalize(raw)
    columns = ["h0", "h1", "h2", "h3", "h4", "h5", "cc0", "cc1", "cc2", "cc3", "cc4"]
    try:
        workbook = pd.ExcelFile(path, engine="openpyxl")
    except ImportError:
        return _load_xlsx_curves_without_openpyxl(path)
    curves: dict[str, Any] = {}
    for sheet_name in workbook.sheet_names:
        frame = pd.read_excel(workbook, sheet_name=sheet_name, engine="openpyxl")
        frame.columns = frame.columns.str.strip()
        team: dict[str, Any] = {}
        for zone, group in frame.groupby("BEC_Zone", dropna=True, sort=False):
            subzones = group[group["BEC_Subzone"].notna()]
            if not subzones.empty:
                team[str(zone).strip()] = {
                    **{
                        str(row["BEC_Subzone"]).strip(): tuple(int(row[column]) for column in columns)
                        for _, row in subzones.iterrows()
                    },
                    "_default": _TWOS,
                }
            elif len(group) == 1:
                row = group.iloc[0]
                team[str(zone).strip()] = tuple(int(row[column]) for column in columns)
        team["_default"] = _ZEROS
        curves[sheet_name.strip()] = team
    curves["_default"] = _ONES
    return curves


def get_params(field_team: str, zone: str, subzone: str | None, curves: dict[str, Any]) -> tuple[int, ...]:
    """Look up curve parameters, preserving the legacy sentinel semantics."""
    team = curves.get(field_team, curves.get("_default", _ONES))
    if isinstance(team, tuple):
        return team
    zone_value = team.get(zone, team.get("_default", _ZEROS))
    if isinstance(zone_value, dict):
        return zone_value.get(subzone, zone_value["_default"])
    return zone_value


def calculate_recovery(height: float | None, crown: float | None, params: tuple[int, ...]) -> int:
    """Return a recovery percentage or the legacy 996–999 diagnostic code."""
    if params == _ZEROS:
        return 998
    if params == _ONES:
        return 997
    if params == _TWOS:
        return 996
    h0, h1, h2, h3, h4, h5, cc0, cc1, cc2, cc3, cc4 = params
    h = 0 if height is None or pd.isna(height) else height
    cc = 0 if crown is None or pd.isna(crown) else crown
    if h < h0:
        return 0
    if h < h1:
        return 0 if cc < cc0 else 10 if cc < cc1 else 20 if cc < cc2 else 30
    if h < h2:
        return 0 if cc < cc0 else 20 if cc < cc1 else 30 if cc < cc2 else 50
    if cc < cc0:
        return 0
    if cc < cc1:
        return 30
    if cc < cc2:
        return 50
    if cc < cc3:
        return 70
    if h < h3:
        return 80
    if h < h4:
        return 80 if cc < cc4 else 90
    if h < h5:
        return 90 if cc < cc4 else 100
    return 100


def apply_recovery(
    openings: gpd.GeoDataFrame,
    curves: dict[str, Any],
    has_override: bool = False,
) -> gpd.GeoDataFrame:
    """Apply recovery curves and preserve diagnostics in ``Error``."""
    required = {"Field_Team", "ZONE", "SUBZONE", "PROJ_HEIGHT_1", "CROWN_CLOSURE"}
    missing = sorted(required - set(openings.columns))
    if missing:
        raise ValueError(f"Openings layer is missing recovery fields: {', '.join(missing)}")
    result = openings.copy()
    recoveries: list[int | float] = []
    errors: list[str] = []
    for _, row in result.iterrows():
        override = row.get("Override", -1)
        if has_override and pd.notna(override) and override != -1:
            recovery = override
        else:
            recovery = calculate_recovery(
                row["PROJ_HEIGHT_1"], row["CROWN_CLOSURE"],
                get_params(row["Field_Team"], row["ZONE"], row["SUBZONE"], curves),
            )
        errors.append(ERRORS.get(recovery, "None"))
        recoveries.append(0 if recovery in ERRORS else recovery)
    result["Recovery"] = recoveries
    result["Error"] = errors
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--input-layer", default="openings_bec")
    parser.add_argument("--curves", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--override", action="store_true")
    args = parser.parse_args(argv)
    try:
        results = apply_recovery(
            gpd.read_file(args.input, layer=args.input_layer), load_curves(args.curves), args.override,
        )
    except (ValueError, OSError) as error:
        parser.error(str(error))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    results.to_file(args.output, layer="openings_recovery", driver="GPKG")
    print(f"Calculated recovery for {len(results)} openings")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
