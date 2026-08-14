"""Recovery-curve calculation independent of ArcPy."""

from __future__ import annotations

import argparse
import json
import math
import posixpath
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
PARAMETER_COLUMNS = ("h0", "h1", "h2", "h3", "h4", "h5", "cc0", "cc1", "cc2", "cc3", "cc4")
ERRORS = {
    999: "Recovery Curve Code Error",
    998: "BEC Error",
    997: "Field Team Error",
    996: "BEC Sub-Zone Error",
}


def _number(value: Any, location: str) -> int | float:
    """Return a finite numeric threshold without discarding decimal precision."""
    if isinstance(value, bool):
        raise ValueError(f"{location} must be a number, not a boolean.")
    try:
        number = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{location} must be numeric (found {value!r}).") from error
    if not math.isfinite(number):
        raise ValueError(f"{location} must be finite (found {value!r}).")
    return int(number) if number.is_integer() else number


def _params(values: list[Any] | tuple[Any, ...], location: str) -> tuple[int | float, ...]:
    if len(values) != len(PARAMETER_COLUMNS):
        raise ValueError(f"{location} must contain exactly 11 recovery thresholds.")
    result = tuple(_number(value, f"{location} {column}") for column, value in zip(PARAMETER_COLUMNS, values))
    if result not in {_ZEROS, _ONES, _TWOS}:
        heights, crowns = result[:6], result[6:]
        if any(left > right for left, right in zip(heights, heights[1:])):
            raise ValueError(f"{location} height thresholds must be non-decreasing.")
        if any(left > right for left, right in zip(crowns, crowns[1:])):
            raise ValueError(f"{location} crown-closure thresholds must be non-decreasing.")
        if heights[0] < 0 or crowns[0] < 0 or crowns[-1] > 100:
            raise ValueError(f"{location} thresholds must use non-negative heights and crown closure from 0 to 100%.")
    return result


def _load_xlsx_curves_without_openpyxl(path: Path) -> dict[str, Any]:
    """Read a recovery workbook using only the Python standard library.

    This keeps the CLI runnable in a minimal QGIS/GDAL Python environment where
    ``openpyxl`` is not installed. It supports both inline and shared strings
    and resolves worksheet relationship targets instead of assuming sheet order.
    """
    namespace = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
                 "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships"}
    with zipfile.ZipFile(path) as archive:
        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        relationships = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        targets = {
            relation.attrib["Id"]: relation.attrib["Target"]
            for relation in relationships
            if relation.attrib.get("Type", "").endswith("/worksheet")
        }
        shared_strings: list[str] = []
        if "xl/sharedStrings.xml" in archive.namelist():
            shared = ET.fromstring(archive.read("xl/sharedStrings.xml"))
            shared_strings = ["".join(item.itertext()) for item in shared]
        sheets = [
            (sheet.attrib["name"], targets[sheet.attrib[f"{{{namespace['r']}}}id"]])
            for sheet in workbook.findall("x:sheets/x:sheet", namespace)
        ]
        curves: dict[str, Any] = {}
        for sheet_name, target in sheets:
            team_name = sheet_name.strip()
            if team_name in curves:
                raise ValueError(f"Duplicate recovery sheet name after trimming: {team_name!r}")
            member = posixpath.normpath(posixpath.join("xl", target.lstrip("/")))
            if member.startswith("xl/xl/"):
                member = member[3:]
            root = ET.fromstring(archive.read(member))
            records: list[dict[str, str]] = []
            for row in root.findall("x:sheetData/x:row", namespace):
                record: dict[str, str] = {}
                for cell in row.findall("x:c", namespace):
                    match = re.match(r"([A-Z]+)", cell.attrib["r"])
                    if not match:
                        continue
                    value = "".join(cell.find("x:is", namespace).itertext()) if cell.find("x:is", namespace) is not None else cell.findtext("x:v", default="", namespaces=namespace)
                    if cell.attrib.get("t") == "s" and value:
                        value = shared_strings[int(value)]
                    record[match.group(1)] = value
                records.append(record)
            if not records:
                continue
            header = records[0]
            column_for_key = {value.strip(): column for column, value in header.items()}
            missing = sorted(set(("BEC_Zone", "BEC_Subzone", *PARAMETER_COLUMNS)) - set(column_for_key))
            if missing:
                raise ValueError(f"Recovery sheet {sheet_name!r} is missing columns: {', '.join(missing)}")
            team: dict[str, Any] = {}
            grouped: dict[str, list[dict[str, str]]] = {}
            for record in records[1:]:
                zone = record.get(column_for_key["BEC_Zone"], "").strip()
                if zone:
                    grouped.setdefault(zone, []).append(record)
            for zone, rows in grouped.items():
                subzones = [row for row in rows if row.get(column_for_key["BEC_Subzone"], "").strip()]
                zone_rows = [row for row in rows if not row.get(column_for_key["BEC_Subzone"], "").strip()]
                if subzones:
                    names = [row[column_for_key["BEC_Subzone"]].strip() for row in subzones]
                    if zone_rows or len(names) != len(set(names)):
                        raise ValueError(f"{team_name}/{zone} must use either one zone curve or unique subzone curves.")
                    values = {
                        row[column_for_key["BEC_Subzone"]].strip(): _params(
                            [row.get(column_for_key[column], "") for column in PARAMETER_COLUMNS],
                            f"{sheet_name}/{zone}/{row[column_for_key['BEC_Subzone']].strip()}",
                        )
                        for row in subzones
                    }
                    team[zone] = {**values, "_default": _TWOS}
                elif len(zone_rows) == 1:
                    row = rows[0]
                    team[zone] = _params(
                        [row.get(column_for_key[column], "") for column in PARAMETER_COLUMNS],
                        f"{sheet_name}/{zone}",
                    )
                else:
                    raise ValueError(f"{team_name}/{zone} contains more than one zone-level curve.")
            team["_default"] = _ZEROS
            curves[team_name] = team
    curves["_default"] = _ONES
    return curves


def load_curves(path: Path) -> dict[str, Any]:
    """Load field-team recovery curves from the existing workbook or JSON format."""
    if path.suffix.lower() == ".json":
        with path.open(encoding="utf-8") as stream:
            raw = json.load(stream)

        def normalize(value: Any, location: str = "recovery curves") -> Any:
            if isinstance(value, list):
                return _params(value, location)
            if isinstance(value, dict):
                return {str(key).strip(): normalize(item, f"{location}/{str(key).strip()}") for key, item in value.items()}
            return value

        return normalize(raw)
    if path.suffix.lower() != ".xlsx":
        raise ValueError("Recovery curves must be an .xlsx workbook or .json file.")
    try:
        workbook = pd.ExcelFile(path, engine="openpyxl")
    except ImportError:
        return _load_xlsx_curves_without_openpyxl(path)
    curves: dict[str, Any] = {}
    for sheet_name in workbook.sheet_names:
        team_name = sheet_name.strip()
        if team_name in curves:
            raise ValueError(f"Duplicate recovery sheet name after trimming: {team_name!r}")
        frame = pd.read_excel(workbook, sheet_name=sheet_name, engine="openpyxl")
        frame.columns = frame.columns.str.strip()
        missing = sorted(set(("BEC_Zone", "BEC_Subzone", *PARAMETER_COLUMNS)) - set(frame.columns))
        if missing:
            raise ValueError(f"Recovery sheet {sheet_name!r} is missing columns: {', '.join(missing)}")
        team: dict[str, Any] = {}
        for zone, group in frame.groupby("BEC_Zone", dropna=True, sort=False):
            subzones = group[group["BEC_Subzone"].notna()]
            zone_rows = group[group["BEC_Subzone"].isna()]
            if not subzones.empty:
                names = [str(value).strip() for value in subzones["BEC_Subzone"]]
                if not zone_rows.empty or len(names) != len(set(names)):
                    raise ValueError(f"{team_name}/{str(zone).strip()} must use either one zone curve or unique subzone curves.")
                team[str(zone).strip()] = {
                    **{
                        str(row["BEC_Subzone"]).strip(): _params(
                            [row[column] for column in PARAMETER_COLUMNS],
                            f"{sheet_name}/{str(zone).strip()}/{str(row['BEC_Subzone']).strip()}",
                        )
                        for _, row in subzones.iterrows()
                    },
                    "_default": _TWOS,
                }
            elif len(group) == 1:
                row = group.iloc[0]
                team[str(zone).strip()] = _params(
                    [row[column] for column in PARAMETER_COLUMNS], f"{sheet_name}/{str(zone).strip()}",
                )
            else:
                raise ValueError(f"{team_name}/{str(zone).strip()} contains more than one zone-level curve.")
        team["_default"] = _ZEROS
        curves[team_name] = team
    curves["_default"] = _ONES
    return curves


def _lookup(mapping: dict[str, Any], key: Any, default: Any) -> Any:
    """Match data labels case-insensitively while ignoring incidental spaces."""
    if key in mapping:
        return mapping[key]
    normalized = " ".join(str(key).split()).casefold() if key is not None and not pd.isna(key) else ""
    return next(
        (value for candidate, value in mapping.items() if " ".join(str(candidate).split()).casefold() == normalized),
        default,
    )


def get_params(field_team: str, zone: str, subzone: str | None, curves: dict[str, Any]) -> tuple[int | float, ...]:
    """Look up curve parameters, preserving the legacy sentinel semantics."""
    team = _lookup(curves, field_team, curves.get("_default", _ONES))
    if isinstance(team, tuple):
        return team
    zone_value = _lookup(team, zone, team.get("_default", _ZEROS))
    if isinstance(zone_value, dict):
        return _lookup(zone_value, subzone, zone_value.get("_default", _TWOS))
    return zone_value


def calculate_recovery(height: float | None, crown: float | None, params: tuple[int | float, ...]) -> int:
    """Return a recovery percentage or the legacy 996–999 diagnostic code."""
    if params == _ZEROS:
        return 998
    if params == _ONES:
        return 997
    if params == _TWOS:
        return 996
    if len(params) != 11:
        return 999
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
            recovery = _number(override, f"Override for row {_}")
            if not 0 <= recovery <= 100:
                raise ValueError(f"Override for row {_} must be between 0 and 100 (found {override!r}).")
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
