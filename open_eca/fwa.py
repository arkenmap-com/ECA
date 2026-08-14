"""Lookup and download named Freshwater Atlas watersheds from BC OpenMaps."""

from __future__ import annotations

import json
import ssl
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import urlopen

import certifi
import geopandas as gpd


FWA_SERVICE_URL = "https://openmaps.gov.bc.ca/geo/pub/WHSE_BASEMAPPING.FWA_NAMED_WATERSHEDS_POLY/wfs"
FWA_TYPE_NAME = "pub:WHSE_BASEMAPPING.FWA_NAMED_WATERSHEDS_POLY"


@dataclass(frozen=True)
class NamedWatershed:
    """The identifying fields needed to let an analyst choose an FWA polygon."""

    named_watershed_id: int
    name: str
    area_ha: float | None
    watershed_code: str | None
    stream_order: int | None

    def to_dict(self) -> dict[str, int | float | str | None]:
        return asdict(self)


def _request(cql_filter: str, max_features: int = 20) -> dict:
    params = urlencode({
        "service": "WFS", "version": "1.1.0", "request": "GetFeature",
        "typeName": FWA_TYPE_NAME, "outputFormat": "application/json", "srsName": "EPSG:3005",
        "CQL_FILTER": cql_filter, "maxFeatures": max_features,
    })
    try:
        context = ssl.create_default_context(cafile=certifi.where())
        with urlopen(f"{FWA_SERVICE_URL}?{params}", timeout=30, context=context) as response:  # noqa: S310 - fixed public BC endpoint
            payload = json.load(response)
    except (URLError, OSError, json.JSONDecodeError) as error:
        raise RuntimeError("Could not reach the BC Freshwater Atlas service. Check your network and try again.") from error
    if payload.get("type") != "FeatureCollection":
        raise RuntimeError("BC Freshwater Atlas returned an unexpected response.")
    return payload


def search_named_watersheds(query: str, limit: int = 20) -> list[NamedWatershed]:
    """Find named watershed candidates by case-insensitive name.

    Names are not unique in the FWA, so callers must use the returned ID to
    fetch a boundary rather than relying on the display name alone.
    """
    query = query.strip()
    if len(query) < 2:
        raise ValueError("Enter at least two characters of a watershed name.")
    if limit < 1 or limit > 100:
        raise ValueError("Result limit must be between 1 and 100.")
    escaped = query.replace("'", "''")
    payload = _request(f"GNIS_NAME ILIKE '%{escaped}%'", limit)
    candidates = []
    for feature in payload.get("features", []):
        properties = feature.get("properties", {})
        identifier = properties.get("NAMED_WATERSHED_ID")
        name = properties.get("GNIS_NAME")
        if identifier is None or not name:
            continue
        candidates.append(NamedWatershed(
            int(identifier), str(name),
            float(properties["AREA_HA"]) if properties.get("AREA_HA") is not None else None,
            str(properties["FWA_WATERSHED_CODE"]) if properties.get("FWA_WATERSHED_CODE") else None,
            int(properties["STREAM_ORDER"]) if properties.get("STREAM_ORDER") is not None else None,
        ))
    return candidates


def download_named_watershed(named_watershed_id: int, output_path: Path) -> NamedWatershed:
    """Download one exact FWA boundary and save it as a GeoJSON input layer."""
    try:
        identifier = int(named_watershed_id)
    except (TypeError, ValueError) as error:
        raise ValueError("Freshwater Atlas watershed ID must be an integer.") from error
    if identifier < 1:
        raise ValueError("Freshwater Atlas watershed ID must be positive.")
    payload = _request(f"NAMED_WATERSHED_ID = {identifier}", 2)
    features = payload.get("features", [])
    if len(features) != 1:
        raise ValueError(f"No unique Freshwater Atlas watershed was found for ID {identifier}.")
    frame = gpd.GeoDataFrame.from_features(features, crs="EPSG:3005")
    if frame.empty or "GNIS_NAME" not in frame:
        raise RuntimeError("Freshwater Atlas returned a watershed without a name or geometry.")
    frame = frame.loc[frame.geometry.notna() & ~frame.geometry.is_empty].copy()
    if frame.empty:
        raise RuntimeError("Freshwater Atlas returned an empty watershed geometry.")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_file(output_path, driver="GeoJSON")
    properties = frame.iloc[0]
    return NamedWatershed(
        identifier, str(properties["GNIS_NAME"]),
        float(properties["AREA_HA"]) if properties.get("AREA_HA") is not None else None,
        str(properties["FWA_WATERSHED_CODE"]) if properties.get("FWA_WATERSHED_CODE") else None,
        int(properties["STREAM_ORDER"]) if properties.get("STREAM_ORDER") is not None else None,
    )
