#!/usr/bin/env python3
"""Build a technical PDF report for the Nelson summer 2025 Cell2Fire run.

The report is intentionally generated from the run artifacts rather than from
hand-entered numbers.  It creates a few static evidence figures, exports the
weather rows actually used by the 1,000 run manifest, then renders the report
to output/pdf/.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import rasterio
from matplotlib.colors import LinearSegmentedColormap
from matplotlib.ticker import FuncFormatter
from pyproj import Transformer
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    Image,
    KeepTogether,
    PageBreak,
    PageTemplate,
    Paragraph,
    Preformatted,
    Spacer,
    Table,
    TableStyle,
)


ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "runs" / "nelson-50km-2025-summer"
OUTPUT = ROOT / "output" / "pdf" / "nelson-50km-2025-summer-report.pdf"
ASSETS = RUN / "report-assets"
CONFIG_PATH = ROOT / "examples" / "nelson-50km-2025-summer.json"
OUTPUTS = RUN / "outputs"
PREPARED = ROOT / "Cell2Fire" / "data" / "nelson-50km-2025-summer-reusable"
DATA = ROOT / "long-term" / "nelson-50km" / "data"


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as source:
        return list(csv.DictReader(source))


def write_csv(path: Path, fields: list[str], rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as target:
        writer = csv.DictWriter(target, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def pct(value: float, digits: int = 1) -> str:
    return f"{value * 100:.{digits}f}%"


def number(value: float, digits: int = 0) -> str:
    return f"{value:,.{digits}f}"


def short_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()[:16]


def ensure_ascii(text: str) -> str:
    """Keep PDF-visible text compatible with the built-in Helvetica fonts."""

    return text.encode("ascii", "replace").decode("ascii")


def load_geojson_points(path: Path) -> tuple[np.ndarray, np.ndarray]:
    data = json.loads(path.read_text(encoding="utf-8"))
    lon: list[float] = []
    lat: list[float] = []
    for feature in data.get("features", []):
        geometry = feature.get("geometry") or {}
        coordinates = geometry.get("coordinates") or []
        if geometry.get("type") == "Point" and len(coordinates) >= 2:
            lon.append(float(coordinates[0]))
            lat.append(float(coordinates[1]))
    return np.array(lon), np.array(lat)


def build_map_figure(path: Path, probability_path: Path, ignition_path: Path) -> None:
    with rasterio.open(probability_path) as dataset:
        raster = dataset.read(1, masked=True)
        transform = dataset.transform
        crs = dataset.crs
        left, bottom, right, top = dataset.bounds

    display = np.ma.masked_where(np.ma.getdata(raster) <= 0, raster * 100.0)
    cmap = LinearSegmentedColormap.from_list(
        "fire_probability",
        ["#fffcb2", "#fecc5c", "#fd8d3c", "#f03b20", "#bd0026"],
    )
    lon, lat = load_geojson_points(ignition_path)
    if len(lon):
        to_grid = Transformer.from_crs("EPSG:4326", crs, always_xy=True)
        ix, iy = to_grid.transform(lon, lat)
    else:
        ix, iy = np.array([]), np.array([])

    fig, ax = plt.subplots(figsize=(7.6, 6.8), dpi=220)
    ax.set_facecolor("#e9e9e9")
    image = ax.imshow(
        display,
        cmap=cmap,
        vmin=0,
        vmax=2.5,
        interpolation="nearest",
        extent=[left, right, bottom, top],
        origin="upper",
    )
    if len(ix):
        ax.scatter(ix, iy, s=4, facecolors="none", edgecolors="#1d3557", alpha=0.28, linewidths=0.35, label="Historical ignition point")
    ax.set_xlabel("BC Albers easting (km)")
    ax.set_ylabel("BC Albers northing (km)")
    ax.xaxis.set_major_formatter(FuncFormatter(lambda value, _: f"{value / 1000:.0f}"))
    ax.yaxis.set_major_formatter(FuncFormatter(lambda value, _: f"{value / 1000:.0f}"))
    ax.grid(color="#777777", alpha=0.18, linewidth=0.5)
    ax.set_title("Nelson 50 km radius: summer 2025 Cell2Fire burn probability", loc="left", fontsize=12, weight="bold")
    ax.text(0.01, 0.98, "Cell probability = runs reaching cell / 1,000", transform=ax.transAxes, va="top", fontsize=8.5, color="#333333", bbox={"facecolor": "white", "alpha": 0.78, "edgecolor": "none", "pad": 3})
    colorbar = fig.colorbar(image, ax=ax, fraction=0.035, pad=0.02)
    colorbar.set_label("Burned in runs (%)")
    colorbar.set_ticks([0.1, 0.5, 1.0, 1.5, 2.0, 2.5])
    if len(ix):
        ax.legend(loc="lower left", frameon=True, framealpha=0.85, fontsize=7.5)
    fig.tight_layout()
    fig.savefig(path, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def build_burn_footprint_figure(path: Path, run_summary: list[dict[str, str]]) -> None:
    burned = np.array([int(row["burned_cells"]) for row in run_summary])
    edges = [0, 1, 10, 50, 100, 200, math.inf]
    labels = ["1", "2-10", "11-50", "51-100", "101-200", "201+"]
    counts = []
    for lower, upper in zip(edges[:-1], edges[1:], strict=True):
        if upper == math.inf:
            counts.append(int(np.sum(burned >= lower)))
        else:
            counts.append(int(np.sum((burned >= lower) & (burned <= upper))))

    fig, ax = plt.subplots(figsize=(7.2, 3.6), dpi=220)
    bars = ax.bar(labels, counts, color="#ef8354", edgecolor="#9c3d23", linewidth=0.6)
    ax.set_title("Most six-hour runs produced small footprints", loc="left", fontsize=11, weight="bold")
    ax.set_ylabel("Number of runs")
    ax.set_xlabel("Burned 250 m cells in the final grid")
    ax.grid(axis="y", color="#cccccc", alpha=0.5, linewidth=0.6)
    ax.set_axisbelow(True)
    for bar, value in zip(bars, counts, strict=True):
        ax.text(bar.get_x() + bar.get_width() / 2, value + max(counts) * 0.015, str(value), ha="center", va="bottom", fontsize=8)
    ax.text(0.99, 0.97, f"Mean: {burned.mean():.2f} cells | median: {np.median(burned):.0f}", transform=ax.transAxes, ha="right", va="top", fontsize=8.5, color="#333333")
    fig.tight_layout()
    fig.savefig(path, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def build_hit_count_figure(path: Path, burn_count_path: Path) -> None:
    with rasterio.open(burn_count_path) as dataset:
        counts_raster = dataset.read(1, masked=True)
    counts = np.asarray(counts_raster.compressed(), dtype=np.int32)
    labels = ["0", "1-2", "3-5", "6-10", "11-14"]
    bins = [0, 1, 3, 6, 11, 15]
    values = [
        int(np.sum(counts == 0)),
        int(np.sum((counts >= 1) & (counts <= 2))),
        int(np.sum((counts >= 3) & (counts <= 5))),
        int(np.sum((counts >= 6) & (counts <= 10))),
        int(np.sum((counts >= 11) & (counts <= 14))),
    ]
    fig, ax = plt.subplots(figsize=(7.2, 3.6), dpi=220)
    bars = ax.bar(labels, values, color="#3d7ea6", edgecolor="#234e70", linewidth=0.6)
    ax.set_title("Cell-level probabilities are sparse across the grid", loc="left", fontsize=11, weight="bold")
    ax.set_ylabel("Number of grid cells")
    ax.set_xlabel("Number of 1,000 runs reaching a cell")
    ax.grid(axis="y", color="#cccccc", alpha=0.5, linewidth=0.6)
    ax.set_axisbelow(True)
    for bar, value in zip(bars, values, strict=True):
        ax.text(bar.get_x() + bar.get_width() / 2, value + max(values) * 0.012, f"{value:,}", ha="center", va="bottom", fontsize=8)
    ax.text(0.99, 0.97, "One hit = 0.1 percentage points", transform=ax.transAxes, ha="right", va="top", fontsize=8.5, color="#333333")
    fig.tight_layout()
    fig.savefig(path, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def build_weather_figure(path: Path, weather_manifest: list[dict[str, str]]) -> None:
    fwi = np.array([float(row["fwi"]) for row in weather_manifest])
    stations = sorted({row["station_name"] for row in weather_manifest})
    by_station = [[float(row["fwi"]) for row in weather_manifest if row["station_name"] == station] for station in stations]
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(7.6, 3.8), gridspec_kw={"width_ratios": [1.25, 1]}, dpi=220)
    ax1.hist(fwi, bins=np.arange(0, 46, 5), color="#f2c14e", edgecolor="#976c00", linewidth=0.6)
    ax1.set_title("FWI across 184 summer scenarios", loc="left", fontsize=10.5, weight="bold")
    ax1.set_xlabel("Daily noon Fire Weather Index")
    ax1.set_ylabel("Scenarios")
    ax1.grid(axis="y", color="#cccccc", alpha=0.5, linewidth=0.6)
    ax1.axvline(float(fwi.mean()), color="#9b2226", linestyle="--", linewidth=1.2, label=f"Mean {fwi.mean():.1f}")
    ax1.legend(frameon=False, fontsize=7.5)
    ax2.boxplot(by_station, tick_labels=stations, patch_artist=True, boxprops={"facecolor": "#9ecae1", "edgecolor": "#2c5d7c"}, medianprops={"color": "#9b2226", "linewidth": 1.2}, whiskerprops={"color": "#2c5d7c"}, capprops={"color": "#2c5d7c"}, flierprops={"marker": ".", "markerfacecolor": "#2c5d7c", "markersize": 3, "alpha": 0.4})
    ax2.set_title("Station scenario distributions", loc="left", fontsize=10.5, weight="bold")
    ax2.set_ylabel("FWI")
    ax2.grid(axis="y", color="#cccccc", alpha=0.5, linewidth=0.6)
    fig.tight_layout()
    fig.savefig(path, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def export_weather_used(weather_manifest: list[dict[str, str]], run_manifest: list[dict[str, str]], path: Path) -> None:
    weather_cache: dict[str, list[dict[str, str]]] = {}
    for row in weather_manifest:
        weather_cache[row["weather_index"]] = read_csv(PREPARED / "Weathers" / f"Weather{row['weather_index']}.csv")
    fields = [
        "run_id", "weather_index", "scenario", "station_code", "station_name", "scenario_date",
        "local_datetime", "APCP_mm", "TMP_C", "RH_pct", "WS_kmh", "WD_deg", "FFMC", "DMC", "DC", "ISI", "BUI", "FWI",
        "fire_number", "fire_year", "fire_cause", "ignition_lat", "ignition_lon", "cell_id",
    ]
    rows: list[dict[str, object]] = []
    for run in run_manifest:
        for weather in weather_cache[run["weather_index"]]:
            manifest = next(item for item in weather_manifest if item["weather_index"] == run["weather_index"])
            rows.append({
                "run_id": run["run_id"], "weather_index": run["weather_index"], "scenario": run["scenario"],
                "station_code": manifest["station_code"], "station_name": manifest["station_name"], "scenario_date": manifest["date"],
                "local_datetime": weather["datetime"], "APCP_mm": weather["APCP"], "TMP_C": weather["TMP"], "RH_pct": weather["RH"],
                "WS_kmh": weather["WS"], "WD_deg": weather["WD"], "FFMC": weather["FFMC"], "DMC": weather["DMC"], "DC": weather["DC"],
                "ISI": weather["ISI"], "BUI": weather["BUI"], "FWI": weather["FWI"], "fire_number": run["fire_number"],
                "fire_year": run["fire_year"], "fire_cause": run["fire_cause"], "ignition_lat": run["ignition_lat"],
                "ignition_lon": run["ignition_lon"], "cell_id": run["cell_id"],
            })
    write_csv(path, fields, rows)


def build_assets() -> dict[str, Path]:
    ASSETS.mkdir(parents=True, exist_ok=True)
    metadata = read_json(OUTPUTS / "metadata.json")
    weather_manifest = read_csv(PREPARED / "weather_manifest.csv")
    run_manifest = read_csv(PREPARED / "run_manifest.csv")
    run_summary = read_csv(OUTPUTS / "run_summary.csv")
    assets = {
        "map": ASSETS / "probability-map.png",
        "footprints": ASSETS / "burn-footprints.png",
        "hits": ASSETS / "cell-hit-counts.png",
        "weather": ASSETS / "weather-fwi.png",
        "weather_csv": ASSETS / "weather_data_used.csv",
    }
    build_map_figure(assets["map"], OUTPUTS / "burn_probability.tif", DATA / "ignitions" / "bcws_historical_ignitions_50km.geojson")
    build_burn_footprint_figure(assets["footprints"], run_summary)
    build_hit_count_figure(assets["hits"], OUTPUTS / "burn_count.tif")
    build_weather_figure(assets["weather"], weather_manifest)
    export_weather_used(weather_manifest, run_manifest, assets["weather_csv"])
    return {"metadata": metadata, "weather_manifest": weather_manifest, "run_manifest": run_manifest, "run_summary": run_summary, **assets}


def styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle("ReportTitle", parent=base["Title"], fontName="Helvetica-Bold", fontSize=25, leading=29, textColor=colors.HexColor("#1d3557"), alignment=TA_LEFT, spaceAfter=10),
        "subtitle": ParagraphStyle("ReportSubtitle", parent=base["Normal"], fontName="Helvetica", fontSize=13, leading=17, textColor=colors.HexColor("#4a5568"), spaceAfter=18),
        "h1": ParagraphStyle("H1", parent=base["Heading1"], fontName="Helvetica-Bold", fontSize=17, leading=21, textColor=colors.HexColor("#1d3557"), spaceBefore=4, spaceAfter=9),
        "h2": ParagraphStyle("H2", parent=base["Heading2"], fontName="Helvetica-Bold", fontSize=11.5, leading=14, textColor=colors.HexColor("#2c5d7c"), spaceBefore=7, spaceAfter=4),
        "body": ParagraphStyle("Body", parent=base["BodyText"], fontName="Helvetica", fontSize=9.2, leading=12.5, textColor=colors.HexColor("#263238"), spaceAfter=6),
        "body_small": ParagraphStyle("BodySmall", parent=base["BodyText"], fontName="Helvetica", fontSize=8.1, leading=10.5, textColor=colors.HexColor("#263238"), spaceAfter=4),
        "caption": ParagraphStyle("Caption", parent=base["BodyText"], fontName="Helvetica-Oblique", fontSize=7.7, leading=9.5, textColor=colors.HexColor("#5f6b73"), spaceBefore=3, spaceAfter=8),
        "kpi_label": ParagraphStyle("KpiLabel", parent=base["BodyText"], fontName="Helvetica", fontSize=7.5, leading=9, alignment=TA_CENTER, textColor=colors.HexColor("#546e7a")),
        "kpi_value": ParagraphStyle("KpiValue", parent=base["BodyText"], fontName="Helvetica-Bold", fontSize=16, leading=19, alignment=TA_CENTER, textColor=colors.HexColor("#1d3557")),
        "table_head": ParagraphStyle("TableHead", parent=base["BodyText"], fontName="Helvetica-Bold", fontSize=7.7, leading=9.5, textColor=colors.white),
        "table": ParagraphStyle("Table", parent=base["BodyText"], fontName="Helvetica", fontSize=7.4, leading=9.1, textColor=colors.HexColor("#263238")),
        "table_small": ParagraphStyle("TableSmall", parent=base["BodyText"], fontName="Helvetica", fontSize=6.8, leading=8.2, textColor=colors.HexColor("#263238")),
        "code": ParagraphStyle("Code", parent=base["Code"], fontName="Courier", fontSize=7.3, leading=9.3, textColor=colors.HexColor("#263238"), backColor=colors.HexColor("#f4f6f7"), borderColor=colors.HexColor("#d7dee2"), borderWidth=0.5, borderPadding=6),
    }


def P(text: str, style: ParagraphStyle) -> Paragraph:
    return Paragraph(ensure_ascii(text), style)


def make_table(data: list[list[object]], widths: list[float], style: ParagraphStyle, header: bool = True, font_size: float | None = None) -> Table:
    converted: list[list[object]] = []
    for row_index, row in enumerate(data):
        converted.append([cell if isinstance(cell, (Paragraph, Image)) else P(str(cell), styles_global["table_head" if header and row_index == 0 else style.name.lower() if style.name.lower() in styles_global else "table"]) for cell in row])
    table = Table(converted, colWidths=widths, repeatRows=1 if header else 0, hAlign="LEFT")
    commands = [
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#d8e0e4")),
    ]
    if header:
        commands.extend([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2c5d7c")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ])
        for row in range(1, len(converted)):
            if row % 2 == 0:
                commands.append(("BACKGROUND", (0, row), (-1, row), colors.HexColor("#f4f7f8")))
    table.setStyle(TableStyle(commands))
    return table


styles_global: dict[str, ParagraphStyle] = {}


def metric_card(label: str, value: str, context: str = "") -> Table:
    content = [[P(value, styles_global["kpi_value"])], [P(label, styles_global["kpi_label"])]]
    if context:
        content.append([P(context, styles_global["caption"])])
    table = Table(content, colWidths=[1.68 * inch], rowHeights=None)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#eef4f7")),
        ("BOX", (0, 0), (-1, -1), 0.6, colors.HexColor("#b7cbd6")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    return table


def footer(canvas, doc) -> None:
    canvas.saveState()
    width, _ = letter
    canvas.setStrokeColor(colors.HexColor("#d8e0e4"))
    canvas.setLineWidth(0.5)
    canvas.line(doc.leftMargin, 0.42 * inch, width - doc.rightMargin, 0.42 * inch)
    canvas.setFont("Helvetica", 7.2)
    canvas.setFillColor(colors.HexColor("#6b7780"))
    canvas.drawString(doc.leftMargin, 0.25 * inch, "Nelson 50 km summer 2025 Cell2Fire report | planning and research use")
    canvas.drawRightString(width - doc.rightMargin, 0.25 * inch, f"Page {doc.page}")
    canvas.restoreState()


def build_pdf(assets: dict[str, Path]) -> Path:
    global styles_global
    styles_global = styles()
    metadata = assets["metadata"]
    config = read_json(CONFIG_PATH)
    weather_manifest = assets["weather_manifest"]
    run_manifest = assets["run_manifest"]
    run_summary = assets["run_summary"]
    burned = np.array([int(row["burned_cells"]) for row in run_summary])
    with rasterio.open(OUTPUTS / "burn_count.tif") as dataset:
        burn_counts = np.asarray(dataset.read(1, masked=True).compressed(), dtype=np.int32)

    max_count = int(burn_counts.max())
    nonzero_cells = int(np.sum(burn_counts > 0))
    total_cells = int(burn_counts.size)
    zero_cells = total_cells - nonzero_cells
    weather_stations = Counter(row["station_name"] for row in weather_manifest)
    fwi = np.array([float(row["fwi"]) for row in weather_manifest])
    unique_weather = len({row["weather_index"] for row in run_manifest})
    unique_ignition_cells = len({row["cell_id"] for row in run_manifest})
    possible_pairs = 408 * len(weather_manifest)
    baseline_path = ROOT / "runs" / "nelson-50km-2025" / "outputs" / "metadata.json"
    baseline = read_json(baseline_path) if baseline_path.exists() else None

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    doc = BaseDocTemplate(str(OUTPUT), pagesize=letter, leftMargin=0.55 * inch, rightMargin=0.55 * inch, topMargin=0.55 * inch, bottomMargin=0.58 * inch, title="Nelson 50 km summer 2025 Cell2Fire report", author="Codex")
    frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="normal")
    doc.addPageTemplates([PageTemplate(id="main", frames=[frame], onPage=footer)])

    story: list[object] = []
    story.append(Spacer(1, 0.2 * inch))
    story.append(P("Nelson 50 km Fire Simulation Report", styles_global["title"]))
    story.append(P("Summer 2025 weather-conditioned Cell2Fire scenario", styles_global["subtitle"]))
    story.append(P("Technical report | Generated 2026-07-22", styles_global["body_small"]))
    story.append(Spacer(1, 0.08 * inch))
    cover_summary = Table([[P("Main result", styles_global["h2"])], [P("This run produced a sparse cell-level burn-probability surface: the highest estimated cell probability was 1.4% (14 of 1,000 runs). That value is internally consistent with a six-hour, one-ignition-per-run screening experiment; it is not an annual probability or an operational fire forecast.", styles_global["body"])]] , colWidths=[doc.width])
    cover_summary.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e7f0f4")), ("BOX", (0, 0), (-1, -1), 0.7, colors.HexColor("#b7cbd6")), ("LEFTPADDING", (0, 0), (-1, -1), 9), ("RIGHTPADDING", (0, 0), (-1, -1), 9), ("TOPPADDING", (0, 0), (-1, -1), 7), ("BOTTOMPADDING", (0, 0), (-1, -1), 7)]))
    story.append(cover_summary)
    story.append(Spacer(1, 0.16 * inch))
    story.append(Image(str(assets["map"]), width=6.25 * inch, height=5.58 * inch))
    story.append(P("Figure 1. Static probability map from the latest completed run. The fixed color scale is shown in percent; empty grey cells are zero or no modeled burn. Historical ignition points are shown as small blue outlines.", styles_global["caption"]))
    cover_meta = [
        [P("Study area", styles_global["table_head"]), P("Nelson, British Columbia; 50 km radius", styles_global["table"])],
        [P("Weather window", styles_global["table_head"]), P("June 1-August 31, 2025; 184 accepted station-date scenarios", styles_global["table"])],
        [P("Landscape", styles_global["table_head"]), P("250 m current fuel, elevation, slope, and aspect layers; EPSG:3005", styles_global["table"])],
    ]
    meta_table = Table(cover_meta, colWidths=[1.25 * inch, 5.65 * inch])
    meta_table.setStyle(TableStyle([("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#2c5d7c")), ("TEXTCOLOR", (0, 0), (0, -1), colors.white), ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#d8e0e4")), ("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5), ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
    story.append(meta_table)

    story.append(PageBreak())
    story.append(P("Technical summary: the map is a conditional six-hour spread result", styles_global["h1"]))
    story.append(P("The latest scenario uses observed 2025 BC Wildfire Service weather records from the Smallwood and Slocan stations, sampled historical ignition locations from 2000-2023, and a current 250 m landscape. The pipeline completed all 1,000 requested Cell2Fire runs and aggregated final burned cells into a probability raster.", styles_global["body"]))
    story.append(Spacer(1, 0.04 * inch))
    kpis = Table([[metric_card("Completed runs", "1,000", "requested: 1,000"), metric_card("Mean final footprint", "33.69 cells", "2.11 km2 at 250 m"), metric_card("Maximum cell probability", "1.4%", "14 of 1,000 runs"), metric_card("Cells reached at least once", "20,140", f"{nonzero_cells / total_cells * 100:.1f}% of grid")]], colWidths=[1.72 * inch] * 4)
    kpis.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 2), ("RIGHTPADDING", (0, 0), (-1, -1), 2)]))
    story.append(kpis)
    story.append(Spacer(1, 0.12 * inch))
    story.append(P("What the result establishes", styles_global["h2"]))
    for item in [
        "The summer date filter worked as configured: 184 scenarios were retained, representing 92 dates at each of two stations.",
        "The summer-conditioned runs produced larger average footprints than the earlier all-season 2025 run: 33.69 versus 22.79 cells, when compared on the same 1,000-run design.",
        "The highest probability is low because the denominator is 1,000 single-fire trials and each trial lasts six one-hour periods. One hit is 0.1 percentage points; 14 hits is 1.4%.",
        "The probability surface should be read as conditional spread likelihood under this sampling design, not as the chance of at least one fire somewhere in the Nelson area during a year or summer.",
    ]:
        story.append(P(f"- {item}", styles_global["body"]))
    story.append(Image(str(assets["footprints"]), width=6.55 * inch, height=3.27 * inch))
    story.append(P("Figure 2. Distribution of final burned-cell counts across the 1,000 independent six-hour trials. A burned cell is a 250 m grid cell marked burned in the final Cell2Fire grid.", styles_global["caption"]))

    story.append(PageBreak())
    story.append(P("Scope, data, and metric definitions", styles_global["h1"]))
    story.append(P("The analysis covers a 50 km radius around Nelson, British Columbia. The raster processing envelope is 400 by 400 cells at 250 m resolution, or 160,000 cells before any circular study-area masking. The configured analysis CRS is BC Albers (EPSG:3005).", styles_global["body"]))
    scope_rows = [
        ["Item", "Definition used in this report"],
        ["Study area", "Nelson centre 49.4928 N, -117.2948 W; configured radius 50,000 m."],
        ["Grid", "400 x 400 cells; 250 m cell size; 160,000 raster cells."],
        ["Weather cohort", "June 1-August 31, 2025; six hourly records per scenario, 12:00-17:00 local time."],
        ["Ignition cohort", "408 historical BCWS point records; source fire years 2000-2023; 363 unique ignition cells appeared in the sampled runs."],
        ["Burn probability", "For each cell: number of completed runs with a burned final-grid value of 1 divided by the number of completed runs."],
        ["Burned area", "Number of burned cells multiplied by 0.0625 km2 per 250 m cell."],
    ]
    story.append(make_table(scope_rows, [1.45 * inch, 5.45 * inch], styles_global["table"]))
    story.append(Spacer(1, 0.12 * inch))
    story.append(P("Weather scenarios and source coverage", styles_global["h2"]))
    weather_rows = [["Station", "Accepted scenarios", "Dates", "FWI min", "FWI mean", "FWI max"]]
    for station in sorted(weather_stations):
        values = np.array([float(row["fwi"]) for row in weather_manifest if row["station_name"] == station])
        dates = sorted(row["date"] for row in weather_manifest if row["station_name"] == station)
        weather_rows.append([station, str(len(values)), f"{dates[0][:4]}-{dates[0][4:6]}-{dates[0][6:]} to {dates[-1][:4]}-{dates[-1][4:6]}-{dates[-1][6:]}", f"{values.min():.1f}", f"{values.mean():.1f}", f"{values.max():.1f}"])
    weather_rows.append(["Combined", str(len(fwi)), "2025-06-01 to 2025-08-31", f"{fwi.min():.1f}", f"{fwi.mean():.1f}", f"{fwi.max():.1f}"])
    story.append(make_table(weather_rows, [1.4 * inch, 0.9 * inch, 2.2 * inch, 0.75 * inch, 0.75 * inch, 0.75 * inch], styles_global["table"]))
    story.append(P("The weather source began as BCWS DataMart records in long-term/nelson-50km/data/bcws-weather/2025_nelson_stations.csv. The preparation workflow retained complete six-hour noon-to-17:00 sequences and complete noon FWI-system values. The latest run retained only the summer date range; it did not create a continuous chronological summer weather record.", styles_global["body_small"]))
    story.append(Image(str(assets["weather"]), width=6.9 * inch, height=3.45 * inch))
    story.append(P("Figure 3. Distribution of daily noon FWI values used as weather scenarios. The FWI values are retained for provenance and reporting; the principal spread inputs in this configuration are fuel type, wind speed, wind direction, FFMC, and BUI.", styles_global["caption"]))

    story.append(PageBreak())
    story.append(P("Methodology and experimental design", styles_global["h1"]))
    story.append(P("The pipeline prepares Cell2Fire inputs from aligned rasters and source tables, samples weather and ignition records with a fixed random seed, executes independent runs, then aggregates the final burned-cell grids. Each run has one ignition and one six-row weather file.", styles_global["body"]))
    flow = Table([[P("Aligned inputs", styles_global["body_small"]), P("Date-filter summer scenarios", styles_global["body_small"]), P("Sample one weather + one ignition", styles_global["body_small"]), P("Run Cell2Fire for 6 periods", styles_global["body_small"]), P("Aggregate burn counts", styles_global["body_small"])]], colWidths=[1.32 * inch] * 5)
    flow.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#eef4f7")), ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#b7cbd6")), ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#b7cbd6")), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("ALIGN", (0, 0), (-1, -1), "CENTER"), ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5), ("TOPPADDING", (0, 0), (-1, -1), 9), ("BOTTOMPADDING", (0, 0), (-1, -1), 9)]))
    story.append(flow)
    story.append(Spacer(1, 0.16 * inch))
    settings_rows = [
        ["Setting", "Configured value", "Role in the run"],
        ["Runs", "1,000", "Monte Carlo sample size and probability denominator."],
        ["Random seed", "20250722", "Makes weather and ignition sampling reproducible."],
        ["Weather records", "6 rows per scenario", "Consumed sequentially as six one-hour weather periods."],
        ["Fire period length", "1.0 hour", "One Cell2Fire fire period; six periods are requested."],
        ["ROS-CV", "0.0", "Deterministic rate-of-spread setting for this screening run."],
        ["Workers", "4", "Parallel execution only; does not alter model inputs."],
        ["Fuel / terrain", "250 m; EPSG:3005", "Fuel class, elevation, slope, and aspect are aligned to the same grid."],
    ]
    story.append(make_table(settings_rows, [1.4 * inch, 1.55 * inch, 3.95 * inch], styles_global["table"]))
    story.append(Spacer(1, 0.1 * inch))
    story.append(P("Sampling coverage and denominator", styles_global["h2"]))
    story.append(P(f"The run design contains 408 historical ignition records and {len(weather_manifest)} accepted weather scenarios, or {possible_pairs:,} possible ignition-weather pairs. The pipeline sampled 1,000 pairs with replacement, so the realized manifest contains {unique_ignition_cells} unique ignition cells and {unique_weather} unique weather scenarios. The aggregate raster divides each cell's burn count by the {len(run_summary):,} completed runs; therefore the smallest non-zero estimate is 1/{len(run_summary):,} = 0.1 percentage points.", styles_global["body"]))
    story.append(P("Ignition points that landed on non-burnable cells were snapped to the nearest burnable cell before being written to Cell2Fire Ignitions.csv. Historical fire number, year, and cause are provenance fields; the run did not apply cause-specific ignition weights.", styles_global["body"]))
    story.append(Preformatted("python3 fire_sim_pipeline.py --config examples/nelson-50km-2025-summer.json --stage all", styles_global["code"]))
    story.append(P("The command above is the reproducible full-pipeline invocation from the repository root. The Cell2Fire runner is called once per manifest row with --ignitions, --weather rows, --max-fire-periods 6, --finalGrid, and a run-specific seed derived from 20250722.", styles_global["body_small"]))

    story.append(PageBreak())
    story.append(P("Spatial result: burn activity is concentrated and low in absolute probability", styles_global["h1"]))
    story.append(P(f"The probability raster contains {nonzero_cells:,} cells with at least one burn hit and {zero_cells:,} cells with zero hits. The maximum cell probability is {pct(metadata['maximum_probability'])}, equal to {max_count} hits in the completed ensemble. The fixed color scale on the map is intentionally absolute: a visually warm cell is not automatically a 5% or 10% probability cell.", styles_global["body"]))
    story.append(Image(str(assets["map"]), width=6.95 * inch, height=6.2 * inch))
    story.append(P("Figure 4. Burn-probability surface from the 250 m final-grid aggregation. The map is conditional on the selected ignition and weather sampling rules and six-hour simulation horizon. It should not be interpreted as an annual hazard map.", styles_global["caption"]))
    spatial_rows = [
        ["Spatial diagnostic", "Value", "Interpretation"],
        ["Grid cells", f"{total_cells:,}", "Full 400 x 400 processing grid."],
        ["Non-zero cells", f"{nonzero_cells:,} ({nonzero_cells / total_cells * 100:.1f}%)", "Reached in at least one simulated run."],
        ["Maximum probability", f"{pct(metadata['maximum_probability'])} ({max_count}/{len(run_summary)})", "Highest empirical burn fraction for one cell."],
        ["Mean probability across grid", f"{pct(float(metadata['mean_burned_cells']) / total_cells, 3)}", "Equivalent to the mean final footprint divided by the full grid."],
        ["Mean final area", f"{float(metadata['mean_burned_cells']) * 0.0625:.2f} km2", "33.69 cells x 0.0625 km2 per cell."],
    ]
    story.append(make_table(spatial_rows, [1.65 * inch, 1.65 * inch, 3.6 * inch], styles_global["table"]))

    story.append(PageBreak())
    story.append(P("Results and comparison: summer weather increased spread, but not the probability scale", styles_global["h1"]))
    story.append(P("The summer-only scenario produced a larger mean footprint than the earlier 2025 all-season scenario, which is directionally consistent with summer conditions. The cell-level probability scale remains low because both scenarios use one ignition and a six-hour window per run.", styles_global["body"]))
    story.append(Table([[Image(str(assets["hits"]), width=3.35 * inch, height=1.68 * inch), Image(str(assets["footprints"]), width=3.35 * inch, height=1.68 * inch)]], colWidths=[3.45 * inch, 3.45 * inch], style=TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0)])))
    story.append(P("Figures 5-6. Left: most cells have zero or only one to two burn hits. Right: most runs have small final footprints, with a long tail of larger runs.", styles_global["caption"]))
    comparison_rows = [["Metric", "Summer 2025", "All-season 2025", "Change / reading"]]
    if baseline:
        comparison_rows.extend([
            ["Completed runs", f"{metadata['completed_runs']:,}", f"{baseline['completed_runs']:,}", "Same denominator."],
            ["Mean burned cells", f"{metadata['mean_burned_cells']:.2f}", f"{baseline['mean_burned_cells']:.2f}", f"{metadata['mean_burned_cells'] / baseline['mean_burned_cells'] - 1:+.1%}"],
            ["Maximum probability", pct(metadata["maximum_probability"]), pct(baseline["maximum_probability"]), f"{(metadata['maximum_probability'] - baseline['maximum_probability']) * 100:+.1f} percentage points"],
            ["Cells with non-zero probability", f"{metadata['cells_with_nonzero_probability']:,}", f"{baseline['cells_with_nonzero_probability']:,}", "Summer reached more cells in this sample."],
        ])
    else:
        comparison_rows.append(["Baseline", "Available", "Not found", "The prior all-season metadata file was unavailable."])
    story.append(make_table(comparison_rows, [1.65 * inch, 1.35 * inch, 1.35 * inch, 2.55 * inch], styles_global["table"]))
    story.append(Spacer(1, 0.1 * inch))
    story.append(P("Calculation spot-checks", styles_global["h2"]))
    checks = [
        ["Check", "Result"],
        ["Completed versus requested runs", f"{metadata['completed_runs']:,} / {metadata['requested_runs']:,}; all requested runs completed."],
        ["Maximum probability", f"max burn count {max_count} / {metadata['completed_runs']:,} = {max_count / metadata['completed_runs']:.3f} = {pct(max_count / metadata['completed_runs'])}."],
        ["Mean footprint conversion", f"{metadata['mean_burned_cells']:.2f} cells x 0.0625 km2 = {metadata['mean_burned_cells'] * 0.0625:.2f} km2."],
        ["Weather filter", f"184 scenarios x 6 hourly rows = {len(weather_manifest) * 6:,} unique prepared weather rows."],
        ["Run manifest", f"{len(run_manifest):,} rows; {unique_weather} unique weather files and {unique_ignition_cells} unique ignition cells realized."],
    ]
    story.append(make_table(checks, [1.7 * inch, 5.2 * inch], styles_global["table"]))

    story.append(PageBreak())
    story.append(P("Limitations, uncertainty, and robustness checks", styles_global["h1"]))
    story.append(P("Overall assessment: share with caveats. The run is reproducible and internally consistent as a planning-screening experiment, but it is not calibrated or designed to estimate annual wildfire risk.", styles_global["body"]))
    limitations = [
        ("Short simulation horizon", "Each fire is simulated for six one-hour periods. A longer-lived fire can travel farther and affect more cells, so these probabilities are conditional on a short spread window."),
        ("One ignition per run", "The ensemble does not simulate multiple ignitions during a summer or year. It therefore cannot answer the cumulative probability that a cell burns at least once during a season."),
        ("Sampling noise", f"With {len(run_summary):,} runs, estimates move in 0.1 percentage-point steps. Most non-zero cells have only one to two hits, so local rankings are unstable without a larger ensemble."),
        ("Weather chronology", "Each run samples one six-hour station-date scenario. The weather library is not a continuous chronological summer sequence, and scenarios are sampled uniformly rather than weighted by fire occurrence."),
        ("Ignition model", "Historical ignition points are sampled uniformly from the available point records. Fire-cause, year, and spatial intensity differences are not used as weights in this run."),
        ("Landscape and calibration", "The landscape is a current 250 m fuel/topography representation. The run has not been calibrated against observed historical fire perimeters or validated with an independent holdout."),
        ("Operational use", "Outputs are for planning and research only. They are not a live-fire forecast, evacuation product, or operational decision surface."),
    ]
    limit_rows = [["Issue", "Why it matters"]] + [[title, text] for title, text in limitations]
    story.append(make_table(limit_rows, [1.6 * inch, 5.3 * inch], styles_global["table"]))
    story.append(Spacer(1, 0.12 * inch))
    story.append(P("Robustness evidence", styles_global["h2"]))
    story.append(P("The summer filter is supported by the manifest (184 accepted scenarios from June 1-August 31, 2025), and the output denominator is reconciled to all 1,000 completed runs. Compared with the prior all-season 2025 run, summer increased mean final footprint from 22.79 to 33.69 cells and maximum probability from 1.3% to 1.4%. These are useful directional checks, but they do not replace convergence testing, calibration, or a longer-duration experiment.", styles_global["body"]))
    story.append(P("Recommended next steps", styles_global["h2"]))
    next_steps = [
        "Choose the target metric explicitly: conditional spread probability per ignition, annual cumulative probability, or probability of exceeding a burned-area threshold.",
        "For conditional spread, generate continuous 24-72 hour weather sequences and increase the ensemble to at least 10,000 runs, with stratified or exhaustive coverage of ignition cells and weather scenarios.",
        "For annual risk, model the number of ignitions per synthetic year from historical BCWS rates and simulate multiple starts per year across a full fire season.",
        "Replay a calibration set of observed fire perimeters, then report sensitivity to fuel mapping, wind, ignition weighting, duration, and run count.",
        "Keep the absolute probability scale in the map, but add a separate quantile or log-stretch view only for visual exploration; do not relabel display classes as higher probabilities.",
    ]
    for item in next_steps:
        story.append(P(f"- {item}", styles_global["body"]))
    story.append(P("Further questions", styles_global["h2"]))
    story.append(P("The key unresolved question is whether this project should represent spread conditional on a fire start or cumulative annual risk. That decision determines the ignition process, weather chronology, simulation duration, and probability denominator for the next run.", styles_global["body"]))

    story.append(PageBreak())
    story.append(P("Appendix: reproducibility and source inventory", styles_global["h1"]))
    story.append(P("The following files are the primary audit trail for this report. Paths are relative to the repository root.", styles_global["body"]))
    source_rows = [
        ["Artifact", "Purpose"],
        ["examples/nelson-50km-2025-summer.json", "Complete scenario configuration, including summer date bounds and run settings."],
        ["fire_sim_pipeline.py", "Config-driven preparation, Cell2Fire execution, aggregation, and web-map build."],
        ["Cell2Fire/data/nelson-50km-2025-summer-reusable/run_manifest.csv", "The 1,000 sampled weather-ignition pairs."],
        ["Cell2Fire/data/nelson-50km-2025-summer-reusable/weather_manifest.csv", "The 184 accepted station-date scenarios."],
        ["Cell2Fire/data/nelson-50km-2025-summer-reusable/Weathers/", "Six hourly records per accepted scenario."],
        ["runs/nelson-50km-2025-summer/outputs/burn_probability.tif", "Cell-level empirical probability raster."],
        ["runs/nelson-50km-2025-summer/outputs/burn_count.tif", "Cell-level burn-hit count raster."],
        ["runs/nelson-50km-2025-summer/outputs/run_summary.csv", "Burned-cell count for every completed run."],
        ["runs/nelson-50km-2025-summer/web-map/index.html", "Interactive local Leaflet map with probability, fuel, ignition, and basemap layers."],
        ["runs/nelson-50km-2025-summer/report-assets/weather_data_used.csv", "6,000 weather rows joined to the 1,000 run manifest rows for this report."],
    ]
    story.append(make_table(source_rows, [3.1 * inch, 3.8 * inch], styles_global["table_small"]))
    story.append(Spacer(1, 0.12 * inch))
    story.append(P("Key output checksums", styles_global["h2"]))
    checksum_rows = [["File", "SHA-256 prefix"]]
    for path in [OUTPUTS / "burn_probability.tif", OUTPUTS / "burn_count.tif", OUTPUTS / "metadata.json", PREPARED / "run_manifest.csv", PREPARED / "weather_manifest.csv"]:
        checksum_rows.append([str(path.relative_to(ROOT)), short_sha256(path)])
    story.append(make_table(checksum_rows, [5.4 * inch, 1.5 * inch], styles_global["table_small"]))
    story.append(Spacer(1, 0.12 * inch))
    story.append(P("Weather field note", styles_global["h2"]))
    story.append(P("The exported weather CSV retains the original six-hour rows and the run-level ignition provenance. Temperature, relative humidity, and precipitation are retained for traceability; in this configuration, the main spread-driving fields are wind speed, wind direction, FFMC, and BUI. Daily noon FWI-system values are repeated across that day's six rows by the prepared Cell2Fire weather files.", styles_global["body_small"]))
    story.append(Spacer(1, 0.08 * inch))
    story.append(P("Report generation note", styles_global["h2"]))
    story.append(P("This PDF was generated from the completed run artifacts on 2026-07-22. It is a static report snapshot; the interactive web map remains the best surface for toggling probability, fuel, ignition, and basemap layers.", styles_global["body_small"]))

    doc.build(story)
    return OUTPUT


def main() -> None:
    assets = build_assets()
    output = build_pdf(assets)
    print(output)
    print(json.dumps({"pdf": str(output), "assets": {key: str(value) for key, value in assets.items() if isinstance(value, Path)}}, indent=2))


if __name__ == "__main__":
    main()
