"""Acquire watershed-scoped ECA inputs from BC Data Catalogue WFS services.

The module deliberately keeps downloaded inputs separate from analysis.  It
creates an immutable GeoPackage cache plus a provenance manifest, allowing the
QGIS review workflow and the future command-line workflow to reproduce the
same analysis from the same source snapshot.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.error import URLError
from urllib.request import urlopen

import geopandas as gpd


CATALOGUE_API = "https://catalogue.data.gov.bc.ca/api/3/action/package_search"
DEFAULT_SOURCE_CONFIG = Path(__file__).parent / "config" / "bc_catalogue_layers.json"


@dataclass(frozen=True)
class LayerSource:
    """A vector layer to acquire from an OGC WFS endpoint."""

    name: str
    service_url: str
    type_name: str
    catalogue_record: str | None = None
    where: str | None = None

    @classmethod
    def from_mapping(cls, source: dict[str, Any]) -> "LayerSource":
        required = ("name", "service_url", "type_name")
        missing = [key for key in required if not source.get(key)]
        if missing:
            raise ValueError(f"Layer configuration is missing: {', '.join(missing)}")
        return cls(**{key: source.get(key) for key in (*required, "catalogue_record", "where")})


def load_sources(config_path: Path) -> list[LayerSource]:
    """Load and validate a JSON data-source configuration."""
    with config_path.open(encoding="utf-8") as stream:
        config = json.load(stream)
    layers = config.get("layers")
    if not isinstance(layers, list) or not layers:
        raise ValueError("Configuration must contain a non-empty 'layers' list.")
    sources = [LayerSource.from_mapping(layer) for layer in layers]
    names = [source.name for source in sources]
    if len(names) != len(set(names)):
        raise ValueError("Layer names must be unique.")
    return sources


def wfs_command(
    source: LayerSource,
    output_path: Path,
    bbox: tuple[float, float, float, float],
    append: bool,
) -> list[str]:
    """Build the ogr2ogr command for a single watershed-bounded WFS layer."""
    # DataBC advertises WFS 2.0, but its public services currently reject
    # GDAL's WFS 2.0 FilterEncoding requests for several catalogue layers.
    # WFS 1.1 accepts the same spatial and attribute filters and is supported
    # across the configured endpoints.
    service_url = source.service_url
    if "VERSION=" not in service_url.upper():
        service_url = f"{service_url}{'' if service_url.endswith('?') else '&'}VERSION=1.1.0"

    command = ["ogr2ogr"]
    if append:
        command.extend(["-update", "-append"])
    command.extend([
        "-f", "GPKG",
        str(output_path),
        f"WFS:{service_url}",
        source.type_name,
        "-nln", source.name,
        "-spat", *(str(value) for value in bbox),
        "-nlt", "PROMOTE_TO_MULTI",
    ])
    if source.where:
        command.extend(["-where", _resolve_relative_dates(source.where)])
    return command


def _resolve_relative_dates(expression: str, today: date | None = None) -> str:
    """Replace portable relative-day expressions with an OGR date literal."""
    reference_date = today or datetime.now(timezone.utc).date()

    def replacement(match: re.Match[str]) -> str:
        cutoff = reference_date - timedelta(days=int(match.group(1)))
        return f"'{cutoff.isoformat()}'"

    return re.sub(r"CURRENT_TIMESTAMP\s*-\s*(\d+)", replacement, expression, flags=re.IGNORECASE)


def _split_large_in_filter(expression: str | None, chunk_size: int = 10) -> list[str | None]:
    """Split a simple long IN filter to stay below restrictive WFS URL limits."""
    if not expression:
        return [expression]
    match = re.fullmatch(r"\s*([A-Za-z_][A-Za-z0-9_]*)\s+IN\s*\((.+)\)\s*", expression, re.IGNORECASE)
    if not match:
        return [expression]
    values = [value.strip() for value in match.group(2).split(",")]
    if len(values) <= chunk_size:
        return [expression]
    field = match.group(1)
    return [
        f"{field} IN ({', '.join(values[index:index + chunk_size])})"
        for index in range(0, len(values), chunk_size)
    ]


def _run(command: list[str]) -> None:
    try:
        subprocess.run(command, check=True, text=True)
    except FileNotFoundError as error:
        raise RuntimeError(
            "ogr2ogr was not found. Install GDAL or use the GDAL bundled with QGIS."
        ) from error
    except subprocess.CalledProcessError as error:
        raise RuntimeError(f"Data acquisition failed: {' '.join(command)}") from error


def _table_counts(gpkg_path: Path, names: list[str]) -> dict[str, int]:
    with sqlite3.connect(gpkg_path) as connection:
        return {
            name: int(connection.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0])
            for name in names
        }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def acquire(
    sources: list[LayerSource],
    output_path: Path,
    bbox: tuple[float, float, float, float],
    overwrite: bool = False,
) -> Path:
    """Write the requested WFS layers to a GeoPackage and provenance manifest.

    The target is only replaced after every requested layer is downloaded, so
    an interrupted run never leaves a partially built cache at ``output_path``.
    Coordinates are expected in EPSG:3005, the native CRS of the configured BC
    web services and the recommended working CRS for this project.
    """
    if bbox[0] >= bbox[2] or bbox[1] >= bbox[3]:
        raise ValueError("BBOX must be xmin ymin xmax ymax.")
    if output_path.exists() and not overwrite:
        raise FileExistsError(f"Output already exists: {output_path}. Use --overwrite to replace it.")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_dir = Path(tempfile.mkdtemp(prefix="eca-acquire-", dir=output_path.parent))
    temporary_gpkg = temporary_dir / output_path.name
    try:
        wrote_layer = False
        for source in sources:
            for where in _split_large_in_filter(source.where):
                _run(wfs_command(replace(source, where=where), temporary_gpkg, bbox, append=wrote_layer))
                wrote_layer = True

        counts = _table_counts(temporary_gpkg, [source.name for source in sources])
        manifest = {
            "format": "open-eca-input-manifest/v1",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "crs": "EPSG:3005",
            "bbox": list(bbox),
            "layers": [
                {
                    "name": source.name,
                    "service_url": source.service_url,
                    "type_name": source.type_name,
                    "catalogue_record": source.catalogue_record,
                    "where": source.where,
                    "effective_where": [
                        _resolve_relative_dates(where)
                        for where in _split_large_in_filter(source.where)
                        if where
                    ],
                    "feature_count": counts[source.name],
                }
                for source in sources
            ],
            "sha256": _sha256(temporary_gpkg),
        }
        manifest_path = output_path.with_suffix(".provenance.json")
        if manifest_path.exists() and not overwrite:
            raise FileExistsError(f"Manifest already exists: {manifest_path}.")
        os.replace(temporary_gpkg, output_path)
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        return output_path
    finally:
        shutil.rmtree(temporary_dir, ignore_errors=True)


def watershed_bbox(
    watershed_path: Path,
    padding_m: float = 100,
) -> tuple[float, float, float, float]:
    """Return a BC Albers bounding box suitable for scoped WFS downloads."""
    if padding_m < 0:
        raise ValueError("Watershed BBOX padding cannot be negative.")
    watershed = gpd.read_file(watershed_path)
    if watershed.empty:
        raise ValueError("Input watershed contains no features.")
    if watershed.crs is None:
        raise ValueError("Input watershed has no CRS.")
    watershed = watershed.loc[watershed.geometry.notna() & ~watershed.geometry.is_empty]
    if watershed.empty:
        raise ValueError("Input watershed has no usable geometry.")
    xmin, ymin, xmax, ymax = watershed.to_crs("EPSG:3005").total_bounds
    return (
        float(xmin - padding_m),
        float(ymin - padding_m),
        float(xmax + padding_m),
        float(ymax + padding_m),
    )


def acquire_for_watershed(
    watershed_path: Path,
    output_path: Path,
    config_path: Path = DEFAULT_SOURCE_CONFIG,
    padding_m: float = 100,
) -> Path:
    """Download the standard public BCGW-backed inputs around a watershed."""
    return acquire(
        load_sources(config_path),
        output_path,
        watershed_bbox(watershed_path, padding_m),
    )


def search_catalogue(query: str, rows: int = 10) -> list[dict[str, str]]:
    """Return compact BC Data Catalogue search results through its CKAN API."""
    url = f"{CATALOGUE_API}?{urlencode({'q': query, 'rows': rows})}"
    try:
        with urlopen(url, timeout=30) as response:  # noqa: S310 - fixed public endpoint
            payload = json.load(response)
    except URLError as error:
        raise RuntimeError(
            "Could not reach the BC Data Catalogue API. Check network access and try again."
        ) from error
    if not payload.get("success"):
        raise RuntimeError("BC Data Catalogue search did not succeed.")
    return [
        {"title": item["title"], "name": item["name"], "url": item["url"]}
        for item in payload["result"]["results"]
    ]


def _parse_bbox(values: list[str]) -> tuple[float, float, float, float]:
    if len(values) != 4:
        raise argparse.ArgumentTypeError("BBOX needs four values: xmin ymin xmax ymax")
    try:
        return tuple(float(value) for value in values)  # type: ignore[return-value]
    except ValueError as error:
        raise argparse.ArgumentTypeError("BBOX values must be numeric.") from error


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    acquire_parser = commands.add_parser("acquire", help="Acquire configured layers into a GeoPackage.")
    acquire_parser.add_argument("--config", type=Path, required=True, help="Layer source JSON file.")
    acquire_parser.add_argument("--bbox", nargs=4, required=True, metavar=("XMIN", "YMIN", "XMAX", "YMAX"))
    acquire_parser.add_argument("--output", type=Path, required=True, help="Output .gpkg path.")
    acquire_parser.add_argument("--overwrite", action="store_true")
    search_parser = commands.add_parser("catalogue-search", help="Search the BC Data Catalogue API.")
    search_parser.add_argument("query")
    search_parser.add_argument("--rows", type=int, default=10)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "catalogue-search":
            print(json.dumps(search_catalogue(args.query, args.rows), indent=2))
            return 0
        sources = load_sources(args.config)
        bbox = _parse_bbox(args.bbox)
        output = acquire(sources, args.output, bbox, args.overwrite)
        print(f"Created {output}")
        return 0
    except (FileExistsError, RuntimeError, ValueError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    sys.exit(main())
