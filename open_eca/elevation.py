"""Acquire a watershed-scoped open DEM from Natural Resources Canada."""

from __future__ import annotations

import hashlib
import json
import os
import ssl
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import URLError
from urllib.parse import urlencode, urlparse
from urllib.request import urlopen

import certifi
import geopandas as gpd
import rasterio

from open_eca.dem import clip_dem, percentile_elevation


STAC_SEARCH_URL = "https://datacube.services.geo.ca/stac/api/search"
MRDEM_COLLECTION = "mrdem-30"
MRDEM_RECORD_URL = "https://open.canada.ca/data/en/dataset/18752265-bda3-498c-a4ba-9dfe68cb98da"
ALLOWED_ASSET_HOST = "canelevation-dem.s3.ca-central-1.amazonaws.com"


@dataclass(frozen=True)
class DemSource:
    """One terrain-model asset selected from the NRCan STAC catalogue."""

    collection: str
    item_id: str
    asset: str
    href: str
    title: str


@dataclass(frozen=True)
class DemAcquisition:
    """Local DEM and reproducibility metadata for an automatic acquisition."""

    path: Path
    provenance: Path
    source: DemSource
    sha256: str


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _watershed_bbox(path: Path) -> tuple[float, float, float, float]:
    watershed = gpd.read_file(path)
    if watershed.empty:
        raise ValueError("Watershed boundary contains no features.")
    if watershed.crs is None:
        raise ValueError("Watershed boundary has no CRS.")
    watershed = watershed.loc[watershed.geometry.notna() & ~watershed.geometry.is_empty]
    if watershed.empty:
        raise ValueError("Watershed boundary has no usable geometry.")
    return tuple(float(value) for value in watershed.to_crs("EPSG:4326").total_bounds)


def discover_nrcan_mrdem(watershed_path: Path) -> DemSource:
    """Find NRCan's current 30 m terrain COG for a Canadian watershed."""
    params = urlencode({
        "collections": MRDEM_COLLECTION,
        "bbox": ",".join(str(value) for value in _watershed_bbox(watershed_path)),
        "limit": 10,
    })
    try:
        context = ssl.create_default_context(cafile=certifi.where())
        with urlopen(f"{STAC_SEARCH_URL}?{params}", timeout=30, context=context) as response:  # noqa: S310 - fixed NRCan endpoint
            payload = json.load(response)
    except (URLError, OSError, json.JSONDecodeError) as error:
        raise RuntimeError("Could not reach the NRCan elevation catalogue. Upload a DEM or try again later.") from error
    for item in payload.get("features", []):
        if item.get("collection") != MRDEM_COLLECTION:
            continue
        asset = item.get("assets", {}).get("dtm", {})
        href = str(asset.get("href", ""))
        parsed = urlparse(href)
        if parsed.scheme != "https" or parsed.hostname != ALLOWED_ASSET_HOST:
            continue
        return DemSource(
            MRDEM_COLLECTION, str(item.get("id", "mrdem")), "dtm", href,
            "NRCan Medium Resolution Digital Elevation Model (MRDEM) 30 m terrain model",
        )
    raise RuntimeError("NRCan MRDEM does not cover the selected watershed. Upload a local DEM instead.")


def acquire_nrcan_dem(watershed_path: Path, output_path: Path) -> DemAcquisition:
    """Stream and clip the current NRCan MRDEM terrain COG to a watershed."""
    source = discover_nrcan_mrdem(watershed_path)
    watershed = gpd.read_file(watershed_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_suffix(".tmp.tif")
    try:
        with rasterio.Env(
            GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR",
            GDAL_HTTP_MULTIRANGE="YES",
            CPL_VSIL_CURL_ALLOWED_EXTENSIONS=".tif",
        ):
            clip_dem(source.href, watershed, temporary)
        # Ensure the extract contains usable elevation before making it final.
        percentile_elevation(temporary)
        os.replace(temporary, output_path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    checksum = _sha256(output_path)
    provenance = output_path.with_suffix(".provenance.json")
    with rasterio.open(output_path) as acquired:
        output_crs = str(acquired.crs)
    provenance.write_text(json.dumps({
        "format": "open-eca-dem-source/v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "provider": "Natural Resources Canada",
        "product": source.title,
        "source": asdict(source),
        "catalogue_record": MRDEM_RECORD_URL,
        "licence": "Open Government Licence - Canada",
        "output_crs": output_crs,
        "output_sha256": checksum,
    }, indent=2) + "\n", encoding="utf-8")
    return DemAcquisition(output_path, provenance, source, checksum)
