"""Create a portable interactive HTML map for an Open ECA draft GeoPackage."""

from __future__ import annotations

import argparse
import html
import json
from pathlib import Path
from typing import Any

import geopandas as gpd
import pandas as pd


def _geojson(frame: gpd.GeoDataFrame | None, fields: list[str] | None = None) -> dict[str, Any]:
    """Serialize just the map-ready fields of a layer in longitude/latitude.

    Draft opening layers include the complete VRI record (hundreds of fields).
    Restricting the browser payload keeps the portable dashboard quick to open
    and makes the popup useful rather than an unmanageable attribute dump.
    """
    if frame is None or frame.empty:
        return {"type": "FeatureCollection", "features": []}
    if fields is not None:
        available = [field for field in fields if field in frame]
        frame = frame[available + [frame.geometry.name]]
    return json.loads(frame.to_crs(4326).to_json(drop_id=True, default=str))


def _read_layer(draft: Path, name: str) -> gpd.GeoDataFrame | None:
    try:
        return gpd.read_file(draft, layer=name)
    except Exception:
        return None


def _summary_table(summary: pd.DataFrame) -> str:
    """Format the compact, analyst-facing ECA summary without raw decimals."""
    if summary.empty:
        return '<p class="empty">No recovering openings were found in this draft.</p>'
    headings = ["Source", "Elevation", "Openings (ha)", "ECA (ha)", "Basin (%)"]
    rows = []
    for row in summary.itertuples(index=False):
        rows.append(
            "<tr>"
            f"<td>{html.escape(str(row.ECAsrc))}</td>"
            f"<td>{html.escape(str(row.ELEVATION))}</td>"
            f"<td>{row.Openings_Hectares:,.1f}</td>"
            f"<td>{row.ECA_Hectares:,.1f}</td>"
            f"<td>{row.ECA_Percent_of_Basin:.2f}</td>"
            "</tr>"
        )
    header = "".join(f"<th>{heading}</th>" for heading in headings)
    return f'<table class="summary"><thead><tr>{header}</tr></thead><tbody>{"".join(rows)}</tbody></table>'


def create_dashboard(draft: Path, output: Path) -> Path:
    """Write a Leaflet dashboard with the draft's watershed and ECA layers."""
    watershed = _read_layer(draft, "watershed")
    if watershed is None or watershed.empty:
        raise ValueError("Draft GeoPackage must include a non-empty watershed layer.")
    recovery = _read_layer(draft, "openings_recovery")
    h60 = _read_layer(draft, "h60_zones")
    other = _read_layer(draft, "other_openings")
    basin_area = float(watershed["BasinArea"].sum()) if "BasinArea" in watershed else watershed.geometry.area.sum() / 10_000
    basin = str(watershed["Watershed"].iloc[0]) if "Watershed" in watershed else draft.stem
    if recovery is None or recovery.empty:
        summary = pd.DataFrame(columns=["ECAsrc", "ELEVATION", "Openings_Hectares", "ECA_Hectares"])
    else:
        summary = recovery.groupby(["ECAsrc", "ELEVATION"], dropna=False).agg(
            Openings_Hectares=("Hectares", "sum"), ECA_Hectares=("ECA_Hectares", "sum"),
        ).reset_index()
    summary["ECA_Percent_of_Basin"] = summary["ECA_Hectares"] / basin_area * 100 if basin_area else 0
    summary_html = _summary_table(summary)
    total_eca = float(summary["ECA_Hectares"].sum()) if not summary.empty else 0.0
    total_openings = float(summary["Openings_Hectares"].sum()) if not summary.empty else 0.0
    total_percent = total_eca / basin_area * 100 if basin_area else 0.0
    has_h60 = bool(h60 is not None and "ELEVATION" in h60 and h60["ELEVATION"].eq("H60 Above").any())
    above_eca = float(summary.loc[summary["ELEVATION"] == "H60 Above", "ECA_Hectares"].sum()) if not summary.empty else 0.0
    sources = sorted(str(value) for value in summary["ECAsrc"].dropna().unique())
    elevations = sorted(str(value) for value in summary["ELEVATION"].dropna().unique())
    data = {
        "watershed": _geojson(watershed, ["Watershed", "BasinArea"]),
        "h60": _geojson(h60, ["ELEVATION", "H60Area"]),
        "recovery": _geojson(recovery, [
            "ECAsrc", "ELEVATION", "Sub_Basin", "Hectares", "ECA_Hectares", "Recovery", "Error",
            "OPENING_ID", "FEATURE_ID", "HARVEST_DATE", "PROJ_AGE_1",
        ]),
        "other": _geojson(other, ["ECAsrc", "Hectares", "Info"]),
        "sources": sources, "elevations": elevations,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    page = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>__BASIN__ ECA Draft Map</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
<style>body{margin:0;font:14px system-ui,-apple-system,sans-serif;color:#1b2838;background:#f5f7f9}header{padding:18px 24px;background:#163a4d;color:white}header h1{margin:0 0 4px;font-size:25px}main{display:grid;grid-template-columns:minmax(0,2fr) minmax(325px,1fr);height:calc(100vh - 92px)}#map{height:100%;min-height:540px}aside{padding:18px;overflow:auto;background:white}h2{margin:0 0 12px}h3{font-size:14px;margin:22px 0 8px}.metrics{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:9px}.metric{background:#edf5f4;padding:10px;border-radius:6px;font-size:20px;font-weight:700;color:#146c70}.metric span{display:block;margin-top:2px;font-size:11px;font-weight:500;color:#50616d}.filters{border:1px solid #dce4e8;border-radius:6px;padding:10px;background:#fbfcfd}.filters fieldset{border:0;margin:0 0 8px;padding:0}.filters fieldset:last-child{margin-bottom:0}.filters legend{font-weight:650;font-size:12px;margin-bottom:4px}.filters label{display:block;font-size:12px;line-height:1.65;cursor:pointer}.filter-status{font-size:12px;color:#50616d;margin:8px 0 0}button{border:1px solid #8aa2ae;border-radius:4px;padding:6px 8px;background:white;color:#163a4d;cursor:pointer;font:inherit;font-size:12px}table.summary{border-collapse:collapse;width:100%;font-size:12px}.summary th{background:#e8f0f3}.summary td,.summary th{padding:6px;text-align:right;border-bottom:1px solid #dce4e8}.summary td:first-child,.summary th:first-child,.summary td:nth-child(2),.summary th:nth-child(2){text-align:left}.note,.empty{color:#50616d;font-size:12px;line-height:1.45}.legend{background:white;padding:8px;line-height:1.4;color:#334;font-size:11px;box-shadow:0 1px 4px #777}.swatch{display:inline-block;width:10px;height:10px;margin-right:4px;border-radius:2px}@media(max-width:800px){main{display:block;height:auto}#map{height:65vh}}</style>
</head><body><header><h1>__BASIN__ — draft ECA map</h1><div>BC Data Catalogue / Freshwater Atlas inputs · open-source draft output</div></header>
<main><div id="map" aria-label="Interactive draft ECA map"></div><aside><h2>Draft result</h2><div class="metrics"><div class="metric">__TOTAL_ECA__ ha<span>Total ECA (__PERCENT__% of basin)</span></div><div class="metric">__OPENINGS__ ha<span>Mapped openings</span></div><div class="metric">__ABOVE_ECA__<span>__ABOVE_LABEL__</span></div><div class="metric">__BASIN_AREA__ ha<span>Watershed area</span></div></div><h3>Map symbology</h3><label for="symbology" class="note">Colour recovering openings by</label><select id="symbology" aria-label="Opening symbology"><option value="recovery">Recovery %</option><option value="type">Opening type</option></select><h3>Filter mapped openings</h3><div id="filters" class="filters"></div><p id="filter-status" class="filter-status"></p><button id="reset-view" type="button">Reset map view</button><h3>ECA by source and elevation</h3>__SUMMARY__<p class="note">This is a screening draft: it includes currently acquired VRI and BEC data; optional tenure, roads, wildfire and local-review layers are not represented unless acquired and rerun.</p></aside></main>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script>
const data = __DATA__;
const map=L.map('map'); L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',{maxZoom:18,attribution:'© OpenStreetMap contributors'}).addTo(map);
function escapeHtml(value){const el=document.createElement('div');el.textContent=String(value);return el.innerHTML}
function popup(p){return Object.entries(p).filter(([,v])=>v!==null && v!==undefined && v!=='' && !Number.isNaN(v)).map(([k,v])=>`<b>${escapeHtml(k)}</b>: ${typeof v==='number'?v.toFixed(2):escapeHtml(v)}`).join('<br>')}
const boundary=L.geoJSON(data.watershed,{style:{color:'#132f3f',weight:3,fill:false}}).addTo(map);
const h60=L.geoJSON(data.h60,{style:f=>({color:'#8d6e63',weight:1,fillColor:f.properties.ELEVATION==='H60 Above'?'#d98f39':'#55a868',fillOpacity:.16}),onEachFeature:(f,l)=>l.bindPopup(popup(f.properties))}).addTo(map);
const sourcePalette=['#4e79a7','#f28e2b','#e15759','#76b7b2','#59a14f','#edc948','#b07aa1','#ff9da7','#9c755f','#bab0ab'];
const sourceColours=Object.fromEntries(data.sources.map((source,index)=>[source,sourcePalette[index%sourcePalette.length]]));
function recoveryColour(value){if(value>=80)return '#006d2c';if(value>=60)return '#31a354';if(value>=40)return '#78c679';if(value>=20)return '#c2e699';return '#ffffcc'}
function typeColour(value){return sourceColours[String(value)]||'#8c8c8c'}
function openingStyle(feature){const properties=feature.properties||{}, recovery=Number(properties.Recovery);const fill=symbology==='type'?typeColour(properties.ECAsrc):recoveryColour(Number.isFinite(recovery)?recovery:0);return {color:properties.ELEVATION==='H60 Above'?'#9b3123':'#245e8c',weight:1,fillColor:fill,fillOpacity:.72}}
const openings=L.geoJSON(null,{style:openingStyle,onEachFeature:(f,l)=>l.bindPopup(popup(f.properties))}).addTo(map);
const other=L.geoJSON(data.other,{style:{color:'#655',weight:1,dashArray:'4 3',fillOpacity:.18}});
const filters=document.querySelector('#filters');
function addFilterGroup(title, values, name){const fieldset=document.createElement('fieldset');const legend=document.createElement('legend');legend.textContent=title;fieldset.append(legend);values.forEach(value=>{const label=document.createElement('label'), input=document.createElement('input');input.type='checkbox';input.name=name;input.value=value;input.checked=true;input.addEventListener('change',renderOpenings);label.append(input,` ${value}`);fieldset.append(label)});filters.append(fieldset)}
addFilterGroup('Source',data.sources,'source'); addFilterGroup('Elevation zone',data.elevations,'elevation');
function selected(name){return new Set([...document.querySelectorAll(`input[name="${name}"]:checked`)].map(input=>input.value))}
function renderOpenings(){const sources=selected('source'), elevations=selected('elevation');const features=data.recovery.features.filter(feature=>sources.has(String(feature.properties.ECAsrc))&&elevations.has(String(feature.properties.ELEVATION)));openings.clearLayers();openings.addData({type:'FeatureCollection',features});document.querySelector('#filter-status').textContent=`Showing ${features.length} of ${data.recovery.features.length} mapped openings.`}
let symbology='recovery';
document.querySelector('#symbology').addEventListener('change',event=>{symbology=event.target.value;openings.setStyle(openingStyle);legend.update()});
const initialBounds=boundary.getBounds(); map.fitBounds(initialBounds,{padding:[20,20]}); document.querySelector('#reset-view').addEventListener('click',()=>map.fitBounds(initialBounds,{padding:[20,20]})); renderOpenings();
L.control.layers({'Watershed':boundary},{'H60 zones':h60,'Recovering openings':openings,'Other openings':other},{collapsed:false}).addTo(map);
function legendContent(){if(symbology==='type')return `<b>Opening type</b><br>${data.sources.map(source=>`<span class="swatch" style="background:${typeColour(source)}"></span>${escapeHtml(source)}`).join('<br>')}`;return '<b>Recovery %</b><br><span class="swatch" style="background:#ffffcc"></span>0–19%<br><span class="swatch" style="background:#c2e699"></span>20–39%<br><span class="swatch" style="background:#78c679"></span>40–59%<br><span class="swatch" style="background:#31a354"></span>60–79%<br><span class="swatch" style="background:#006d2c"></span>80–100%'}
const legend=L.control({position:'bottomleft'});legend.onAdd=function(){this._container=L.DomUtil.create('div','legend');this.update();return this._container};legend.update=function(){if(this._container)this._container.innerHTML=legendContent()};legend.addTo(map);
</script></body></html>
"""
    page = (page.replace("__BASIN__", html.escape(basin)).replace("__TOTAL_ECA__", f"{total_eca:.1f}")
            .replace("__BASIN_AREA__", f"{basin_area:,.1f}").replace("__PERCENT__", f"{total_percent:.2f}")
            .replace("__OPENINGS__", f"{total_openings:,.1f}")
            .replace("__ABOVE_ECA__", f"{above_eca:,.1f} ha" if has_h60 else "—")
            .replace("__ABOVE_LABEL__", "ECA above H60" if has_h60 else "No DEM / H60 split")
            .replace("__SUMMARY__", summary_html)
            .replace("__DATA__", json.dumps(data, separators=(",", ":"))))
    output.write_text(page, encoding="utf-8")
    return output


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--draft", type=Path, required=True, help="ECA_Draft.gpkg input.")
    parser.add_argument("--output", type=Path, required=True, help="Output .html file.")
    args = parser.parse_args(argv)
    try:
        output = create_dashboard(args.draft, args.output)
    except (OSError, ValueError) as error:
        parser.error(str(error))
    print(f"Created {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
