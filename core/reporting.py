"""
Excel report generation for ECA analysis.

Converts feature classes to pandas DataFrames, creates pivot tables
per sub-basin, and exports multi-sheet Excel workbooks using xlsxwriter.
"""

import arcpy
import os
import sys
import numpy as np
import pandas as pd

from core.workspace import (
    FC_OPENINGS_RECOVERY, FC_OTHER_OPENINGS, FC_PEST_INFESTATION,
    FC_H60_BASIN, FC_WATERSHED, FC_SUBBASINS, FC_H60_LINE, gdb_fc,
)


def export_html_dashboard(output_gdb, html_path, data, basin, basin_area):
    """Export a self-contained HTML dashboard with a Leaflet map and ECA tables."""
    import tempfile
    from datetime import date

    arcpy.AddMessage("Exporting HTML Dashboard")

    def _to_geojson(fc_name):
        fc = gdb_fc(output_gdb, fc_name)
        if not arcpy.Exists(fc):
            return '{"type":"FeatureCollection","features":[]}'
        scratch = arcpy.env.scratchFolder or tempfile.gettempdir()
        tmp = os.path.join(scratch, f"eca_dash_{fc_name}.geojson")
        arcpy.conversion.FeaturesToJSON(fc, tmp, geoJSON="GEOJSON", outputToWGS84="WGS84")
        with open(tmp, "r", encoding="utf-8") as fh:
            return fh.read()

    openings_gj  = _to_geojson(FC_OPENINGS_RECOVERY)
    watershed_gj = _to_geojson(FC_WATERSHED)
    subbasins_gj = _to_geojson(FC_SUBBASINS)
    h60_gj       = _to_geojson(FC_H60_LINE)

    # Raw dataframes
    df_open  = data["openings"][0][0]
    df_other = data["other_openings"][0][0]
    # Summary pivot is the last item appended by build_summary_sheets
    openings_dfs = data["openings"][0]
    summary_df   = openings_dfs[-1] if len(openings_dfs) > 1 else openings_dfs[0]

    def _df_to_html(df, tid):
        return df.to_html(
            table_id=tid, classes="data-table", border=0, index=False,
            float_format=lambda x: f"{x:.2f}", na_rep="",
        )

    summary_html  = _df_to_html(summary_df, "tbl-summary")
    openings_html = _df_to_html(df_open,    "tbl-openings")
    other_html    = _df_to_html(df_other,   "tbl-other")
    today         = date.today().strftime("%Y-%m-%d")

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>ECA Final Report \u2013 {basin}</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{font-family:Arial,sans-serif;font-size:13px;color:#222;background:#f4f6f8}}
  header{{background:#1a3a5c;color:#fff;padding:14px 20px}}
  header h1{{font-size:1.4em}}
  header p{{opacity:.8;font-size:.85em;margin-top:2px}}
  .container{{max-width:1400px;margin:0 auto;padding:16px}}
  section{{background:#fff;border-radius:6px;box-shadow:0 1px 4px rgba(0,0,0,.12);margin-bottom:18px;padding:16px}}
  section h2{{font-size:1em;font-weight:bold;margin-bottom:10px;color:#1a3a5c;border-bottom:2px solid #1a3a5c;padding-bottom:4px}}
  #map{{height:520px;width:100%;border-radius:4px}}
  .legend{{background:white;padding:8px 10px;border-radius:4px;line-height:1.7;font-size:12px;
           box-shadow:0 1px 4px rgba(0,0,0,.25);max-height:280px;overflow-y:auto}}
  .legend i{{display:inline-block;width:13px;height:13px;margin-right:5px;border-radius:2px;vertical-align:middle}}
  table.data-table{{width:100%;border-collapse:collapse;font-size:12px}}
  table.data-table th{{background:#1a3a5c;color:#fff;padding:6px 8px;text-align:left;white-space:nowrap;cursor:pointer;user-select:none}}
  table.data-table th.sort-asc::after{{content:' \25b2';font-size:.7em}}
  table.data-table th.sort-desc::after{{content:' \25bc';font-size:.7em}}
  table.data-table td{{padding:5px 8px;border-bottom:1px solid #e0e4ea;white-space:nowrap}}
  table.data-table tr:nth-child(even) td{{background:#f4f6f8}}
  table.data-table tr:hover td{{background:#dce8f5}}
  .scroll-wrap{{overflow-x:auto;max-height:420px;overflow-y:auto}}
  .stats-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px;margin-bottom:14px}}
  .stat-card{{background:#eef3f9;border-radius:5px;padding:12px;text-align:center}}
  .stat-card .val{{font-size:1.5em;font-weight:bold;color:#1a3a5c}}
  .stat-card .lbl{{font-size:.8em;color:#555;margin-top:2px}}
  .tab-bar{{display:flex;gap:4px;margin-bottom:10px}}
  .tab-btn{{padding:5px 14px;border:1px solid #1a3a5c;border-radius:4px 4px 0 0;
            background:#eef3f9;cursor:pointer;font-size:12px}}
  .tab-btn.active{{background:#1a3a5c;color:white}}
  .tab-pane{{display:none}}
  .tab-pane.active{{display:block}}
</style>
</head>
<body>
<header>
  <h1>ECA Final Analysis \u2013 {basin}</h1>
  <p>Generated: {today}&nbsp;|&nbsp;Total Basin Area: {basin_area:.1f} ha</p>
</header>
<div class="container">

  <section>
    <h2>Openings Map</h2>
    <div id="map"></div>
  </section>

  <section>
    <h2>ECA Summary</h2>
    <div id="stats-grid" class="stats-grid"></div>
    <div class="scroll-wrap">{summary_html}</div>
  </section>

  <section>
    <h2>Report Data</h2>
    <div class="tab-bar">
      <button class="tab-btn active" onclick="showTab(event,'openings')">Openings</button>
      <button class="tab-btn" onclick="showTab(event,'other')">Other Openings</button>
    </div>
    <div id="tab-openings" class="tab-pane active">
      <div class="scroll-wrap">{openings_html}</div>
    </div>
    <div id="tab-other" class="tab-pane">
      <div class="scroll-wrap">{other_html}</div>
    </div>
  </section>

</div>
<script>
function showTab(e,name){{
  document.querySelectorAll('.tab-pane').forEach(el=>el.classList.remove('active'));
  document.querySelectorAll('.tab-btn').forEach(el=>el.classList.remove('active'));
  document.getElementById('tab-'+name).classList.add('active');
  e.currentTarget.classList.add('active');
}}
function makeSortable(tbl){{
  const ths=tbl.querySelectorAll('th');
  ths.forEach((th,ci)=>{{
    th.addEventListener('click',()=>{{
      const asc=!th.classList.contains('sort-asc');
      ths.forEach(h=>h.classList.remove('sort-asc','sort-desc'));
      th.classList.add(asc?'sort-asc':'sort-desc');
      const tbody=tbl.querySelector('tbody');
      const rows=[...tbody.querySelectorAll('tr')];
      rows.sort((a,b)=>{{
        const av=a.cells[ci]?.textContent.trim()??'';
        const bv=b.cells[ci]?.textContent.trim()??'';
        const an=parseFloat(av),bn=parseFloat(bv);
        const cmp=(!isNaN(an)&&!isNaN(bn))?(an-bn):av.localeCompare(bv);
        return asc?cmp:-cmp;
      }});
      rows.forEach(r=>tbody.appendChild(r));
    }});
  }});
}}
document.querySelectorAll('table.data-table').forEach(makeSortable);

const openingsGJ  = {openings_gj};
const watershedGJ = {watershed_gj};
const subbasinsGJ = {subbasins_gj};
const h60GJ       = {h60_gj};

const map = L.map('map');
const baseOSM=L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png',{{
  attribution:'\u00a9 OpenStreetMap contributors',maxZoom:19
}});
const baseSat=L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{{z}}/{{y}}/{{x}}',{{
  attribution:'Tiles &copy; Esri &mdash; Source: Esri, USGS, NOAA',maxZoom:19
}});
baseOSM.addTo(map);

const PALETTE=['#e6194B','#3cb44b','#4363d8','#f58231','#911eb4',
  '#42d4f4','#f032e6','#bfef45','#469990','#dcbeff','#9A6324','#800000','#aaffc3'];
const srcColors={{}};
let palIdx=0;
function srcColor(s){{if(!srcColors[s])srcColors[s]=PALETTE[palIdx++%PALETTE.length];return srcColors[s];}}

const openingsLayer=L.geoJSON(openingsGJ,{{
  style:f=>({{fillColor:srcColor(f.properties.ECAsrc||'Unknown'),color:'#444',weight:.5,fillOpacity:.75}}),
  onEachFeature:function(f,layer){{
    const p=f.properties;
    const POPUP_FIELDS=['LINE_7B_DISTURBANCE_HISTORY','CROWN_CLOSURE','PROJ_HEIGHT_1','ECAsrc','Info','Override','Hectares'];
    const rows=POPUP_FIELDS
      .filter(k=>k in p)
      .map(k=>`<tr><td><b>${{k}}</b></td><td>${{p[k]??''}}</td></tr>`).join('');
    layer.bindPopup(`<table style="font-size:11px;border-collapse:collapse">${{rows}}</table>`,{{maxWidth:320}});
  }},
}}).addTo(map);

const watershedLayer=L.geoJSON(watershedGJ,{{style:{{color:'#1a3a5c',weight:2.5,fill:false}}}}).addTo(map);

const subbasinsLayer=L.geoJSON(subbasinsGJ,{{
  style:{{color:'#666',weight:1.2,fill:false,dashArray:'5 3'}},
  onEachFeature:function(f,layer){{
    if(f.properties.Sub_Basin)layer.bindTooltip(String(f.properties.Sub_Basin));
  }},
}}).addTo(map);

const h60Layer=L.geoJSON(h60GJ,{{style:{{color:'#c0392b',weight:1.5,dashArray:'6 3'}}}}).addTo(map);

L.control.layers(
  {{'Street Map':baseOSM,'Satellite':baseSat}},
  {{'Openings':openingsLayer,'Watershed':watershedLayer,'Sub-Basins':subbasinsLayer,'H60 Line':h60Layer}},
  {{collapsed:false}}
).addTo(map);

const legend=L.control({{position:'bottomright'}});
legend.onAdd=function(){{
  const div=L.DomUtil.create('div','legend');
  div.innerHTML='<b>Source Layer</b><br>';
  setTimeout(()=>{{
    Object.entries(srcColors).forEach(([k,v])=>{{
      div.innerHTML+=`<i style="background:${{v}}"></i>${{k}}<br>`;
    }});
  }},150);
  return div;
}};
legend.addTo(map);

if(openingsGJ.features&&openingsGJ.features.length){{
  map.fitBounds(openingsLayer.getBounds(),{{padding:[20,20]}});
}}else if(watershedGJ.features&&watershedGJ.features.length){{
  map.fitBounds(watershedLayer.getBounds(),{{padding:[20,20]}});
}}

(function(){{
  const features=openingsGJ.features||[];
  let totalArea=0,totalECA=0;
  features.forEach(f=>{{
    const ha=parseFloat(f.properties.Hectares)||0;
    const rec=parseFloat(f.properties.Recovery)||0;
    totalArea+=ha; totalECA+=ha-(rec/100*ha);
  }});
  const basinArea={basin_area};
  const ecaPct=basinArea>0?(totalECA/basinArea*100):0;
  document.getElementById('stats-grid').innerHTML=`
    <div class="stat-card"><div class="val">${{totalArea.toFixed(1)}}</div><div class="lbl">Openings Area (ha)</div></div>
    <div class="stat-card"><div class="val">${{totalECA.toFixed(1)}}</div><div class="lbl">ECA (ha)</div></div>
    <div class="stat-card"><div class="val">${{ecaPct.toFixed(1)}}%</div><div class="lbl">ECA of Basin</div></div>
    <div class="stat-card"><div class="val">${{basinArea.toFixed(1)}}</div><div class="lbl">Total Basin Area (ha)</div></div>
  `;
}})();
</script>
</body>
</html>"""

    with open(html_path, "w", encoding="utf-8") as fh:
        fh.write(html)
    arcpy.AddMessage(f"HTML Dashboard: {html_path}")


def _ensure_xlsxwriter_available():
    """Load vendored xlsxwriter when ArcGIS Pro can't import it."""
    try:
        import xlsxwriter  # noqa: F401
        return
    except ModuleNotFoundError:
        pass

    vendored_root = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..", "..", "!Python_Repository")
    )
    vendored_package = os.path.join(vendored_root, "xlsxwriter")

    if os.path.isdir(vendored_package) and vendored_root not in sys.path:
        sys.path.insert(0, vendored_root)

    try:
        import xlsxwriter  # noqa: F401
    except ModuleNotFoundError as exc:
        raise ModuleNotFoundError(
            "No module named 'xlsxwriter'. Install it in ArcGIS Pro or place the "
            "vendored package at {!r}.".format(vendored_package)
        ) from exc


# ---------------------------------------------------------------------------
# Column rename mappings
# ---------------------------------------------------------------------------
_OPENINGS_RENAME = {
    "Sub_Basin": "Sub-Basin",
    "ECAsrc": "Source Layer",
    "SUBZONE": "BEC Sub-Zone",
    "ZONE": "BEC Zone",
    "ELEVATION": "H60 Line",
    "CROWN_CLOSURE": "Crown Closure %",
    "PROJ_HEIGHT_1": "Projected Height (m)",
    "Recovery": "Recovery %",
    "Hectares": "Area (ha)",
    "Error": "Calculation Error",
    "BasinArea": "Total Area",
    "SubBasinArea": "Sub-Basin Area",
    "H60Area": "H60 Area",
}

_OTHER_RENAME = {
    "Sub_Basin": "Sub-Basin",
    "ECAsrc": "Source Layer",
    "ELEVATION": "H60 Line",
    "Hectares": "Area (ha)",
    "BasinArea": "Total Area",
    "SubBasinArea": "Sub-Basin Area",
    "H60Area": "H60 Area",
}

_PEST_RENAME = {
    "Sub_Basin": "Sub-Basin",
    "ECAsrc": "Source Layer",
    "ELEVATION": "H60 Line",
    "AREA_HA": "Area (ha)",
    "BasinArea": "Total Area",
    "SubBasinArea": "Sub-Basin Area",
    "CAPTURE_YEAR": "Capture Year",
    "PEST_SEVERITY_CODE": "Severity",
    "PEST_SPECIES_CODE": "Species Code",
    "PEST_SPECIES_COMMON_NAME": "Species",
}

_SUBBASIN_RENAME = {
    "Sub_Basin": "Sub-Basin",
    "ELEVATION": "Elevation",
    "H60BsnArea": "Area (Ha)",
    "percent": "% of Total Sub-Basin Area",
}


def _fc_to_dataframe(fc, fields):
    """Read a feature class into a DataFrame using a SearchCursor.

    Unlike FeatureClassToNumPyArray this handles None values in numeric
    fields without raising a TypeError.
    """
    with arcpy.da.SearchCursor(fc, fields) as cursor:
        rows = [row for row in cursor]
    df = pd.DataFrame(rows, columns=fields) if rows else pd.DataFrame(columns=fields)
    # Fill numeric nulls with 0 so downstream math doesn't produce NaN
    numeric_cols = df.select_dtypes(include="number").columns
    df[numeric_cols] = df[numeric_cols].fillna(0)
    return df


def convert_feature_classes(output_gdb):
    """Convert output GDB feature classes to DataFrames for reporting.

    Returns a dict with keys: openings, other_openings, pest, subbasins
    Each value is ``(df_list, sheet_list)`` where the first item is raw data.
    """
    openings_fields = (
        "Sub_Basin", "ECAsrc", "ZONE", "SUBZONE", "ELEVATION",
        "CROWN_CLOSURE", "PROJ_HEIGHT_1", "Recovery", "Hectares", "Error",
        "BasinArea", "SubBasinArea", "Info", "H60Area",
    )
    other_fields = (
        "Sub_Basin", "ECAsrc", "ELEVATION", "Hectares",
        "BasinArea", "SubBasinArea", "H60Area",
    )
    pest_fields = (
        "Sub_Basin", "ECAsrc", "ELEVATION", "AREA_HA",
        "BasinArea", "SubBasinArea", "PEST_SEVERITY_CODE", "PEST_SPECIES_CODE",
        "PEST_SPECIES_COMMON_NAME", "CAPTURE_YEAR",
    )
    subbasin_fields = ("Sub_Basin", "ELEVATION", "H60BsnArea", "percent")

    arcpy.AddMessage("Preparing Reports")

    openings_fc = gdb_fc(output_gdb, FC_OPENINGS_RECOVERY)
    other_fc = gdb_fc(output_gdb, FC_OTHER_OPENINGS)
    pest_fc = gdb_fc(output_gdb, FC_PEST_INFESTATION)
    subbasins_fc = gdb_fc(output_gdb, FC_H60_BASIN)

    # --- Openings ---
    df_open = _fc_to_dataframe(openings_fc, openings_fields).rename(columns=_OPENINGS_RENAME)
    df_open["ECA"] = df_open["Area (ha)"] - (df_open["Recovery %"] / 100 * df_open["Area (ha)"])
    openings_data = ([df_open], ["Openings Raw Data"])

    # --- Other Openings ---
    df_other = _fc_to_dataframe(other_fc, other_fields).rename(columns=_OTHER_RENAME)
    other_data = ([df_other], ["Other Openings Raw Data"])

    # --- Pest ---
    df_pest = _fc_to_dataframe(pest_fc, pest_fields).rename(columns=_PEST_RENAME)
    pest_data = ([df_pest], ["Pest Infestation Raw Data"])

    # --- Subbasins ---
    df_sub = _fc_to_dataframe(subbasins_fc, subbasin_fields).rename(columns=_SUBBASIN_RENAME)
    sub_data = ([df_sub], ["Summary"])

    return {
        "openings": openings_data,
        "other_openings": other_data,
        "pest": pest_data,
        "subbasins": sub_data,
    }


def build_subbasin_sheets(data):
    """Split raw data into per-subbasin pivot sheets.

    Modifies *data* dict in place by appending sheets.
    Returns ``(openings_cols, other_cols, subbasin_cols)``.
    """
    col = "Sub-Basin"

    # --- Openings ---
    df_list, sheet_list = data["openings"]
    df = df_list[0]
    openings_cols = sorted(set(df[col].values))
    for basin in openings_cols:
        sub_df = df.loc[df[col] == basin]
        pivot = pd.pivot_table(
            sub_df, values="ECA",
            index=["BEC Zone", "BEC Sub-Zone", "Source Layer", "Sub-Basin Area"],
            columns="H60 Line", aggfunc="sum", fill_value=0,
        ).reset_index().rename_axis(None, axis=1)

        sub_area = pivot["Sub-Basin Area"]
        for missing in ("H60 Above", "H60 Below"):
            if missing not in pivot.columns:
                pivot[missing] = 0
        pivot["Total ECA (ha)"] = pivot.get("H60 Above", 0) + pivot.get("H60 Below", 0)
        pivot["ECA %"] = pivot["Total ECA (ha)"] / sub_area * 100
        df_list.append(pivot)
        sheet_list.append(str(basin))

    # --- Other Openings ---
    df_list, sheet_list = data["other_openings"]
    df = df_list[0]
    other_cols = sorted(set(df[col].values))
    for basin in other_cols:
        sub_df = df.loc[df[col] == basin]
        pivot = pd.pivot_table(
            sub_df, values="Area (ha)",
            index=["Source Layer", "Sub-Basin Area"],
            columns="H60 Line", aggfunc="sum", fill_value=0,
        ).reset_index().rename_axis(None, axis=1)

        total = 0
        for c in ("H60 Above", "H60 Below"):
            if c in pivot.columns:
                total = total + pivot[c]
        pivot["Total (ha)"] = total
        df_list.append(pivot)
        sheet_list.append(str(basin))

    # --- Pest ---
    df_list, sheet_list = data["pest"]
    df = df_list[0]
    pest_cols = sorted(set(df[col].values))
    for basin in pest_cols:
        sub_df = df.loc[df[col] == basin]
        pivot = pd.pivot_table(
            sub_df, values="Area (ha)",
            index=["Source Layer", "Capture Year", "Severity",
                   "Species Code", "Species", "Sub-Basin Area"],
            columns="H60 Line", aggfunc="sum", fill_value=0,
        ).reset_index().rename_axis(None, axis=1)

        total = 0
        for c in ("H60 Above", "H60 Below"):
            if c in pivot.columns:
                total = total + pivot[c]
        pivot["Total (ha)"] = total
        df_list.append(pivot)
        sheet_list.append(str(basin))

    # --- Subbasins ---
    df_list, sheet_list = data["subbasins"]
    df = df_list[0]
    subbasin_cols = sorted(set(df[col].values))
    for basin in subbasin_cols:
        sub_df = df.loc[df[col] == basin]
        df_list.append(sub_df)
        sheet_list.append(str(basin))

    # Remove the summary placeholder
    del df_list[0]
    del sheet_list[0]

    return openings_cols, other_cols, subbasin_cols


def build_summary_sheets(data, openings_cols, other_cols):
    """Create watershed-wide summary pivot sheets."""
    col = "Sub-Basin"

    # --- Openings Summary ---
    df_list, sheet_list = data["openings"]
    df = df_list[0]
    summary = pd.pivot_table(
        df, values="ECA",
        index=["Source Layer", "Total Area"],
        columns=col, aggfunc="sum", fill_value=0,
    ).reset_index().rename_axis(None, axis=1)

    totals = sum(summary[c] for c in openings_cols if c in summary.columns)
    summary["Totals"] = totals
    summary["ECA %"] = summary["Totals"] / summary["Total Area"] * 100
    df_list.append(summary)
    sheet_list.append("Summary")

    # --- Other Openings Summary ---
    df_list, sheet_list = data["other_openings"]
    df = df_list[0]
    summary = pd.pivot_table(
        df, values="Area (ha)",
        index=["Source Layer", "Total Area"],
        columns=col, aggfunc="sum", fill_value=0,
    ).reset_index().rename_axis(None, axis=1)

    totals = sum(summary[c] for c in other_cols if c in summary.columns)
    summary["Totals"] = totals
    df_list.append(summary)
    sheet_list.append("Other Openings Summary")


def export_reports(data, output_paths, basin_area, subbasins_data=None):
    """Export all three Excel reports.

    *output_paths*: dict with keys xlsx_openings, xlsx_other, xlsx_pest.
    *subbasins_data*: (df_list, sheet_list) for subbasin H60 data.
    """
    _export_openings(data["openings"], output_paths["xlsx_openings"],
                     basin_area, subbasins_data)
    _export_other_openings(data["other_openings"], output_paths["xlsx_other"])
    _export_pest(data["pest"], output_paths["xlsx_pest"])


def _export_openings(openings_data, xlsx_path, basin_area, subbasins_data):
    """Export Openings report as multi-sheet Excel workbook."""
    _ensure_xlsxwriter_available()
    df_list, sheet_list = openings_data
    # Reverse so Summary comes first
    df_list_r = list(reversed(df_list))
    sheet_list_r = list(reversed(sheet_list))

    arcpy.AddMessage("Exporting Openings Report")
    writer = pd.ExcelWriter(xlsx_path, engine="xlsxwriter")

    sb_df_list = subbasins_data[0] if subbasins_data else []
    sb_sheet_list = subbasins_data[1] if subbasins_data else []

    for dataframe, sheet in zip(df_list_r, sheet_list_r):
        dataframe = dataframe.reset_index(drop=True)
        dataframe.index = dataframe.index + 1

        # Check for matching subbasin table
        sub_df = None
        if sheet not in ("Openings Raw Data", "Summary"):
            for tbl, sht in zip(sb_df_list, sb_sheet_list):
                if sht == sheet:
                    sub_df = tbl.iloc[:, 1:]
                    break

        dataframe.to_excel(writer, sheet_name=sheet, index=False, startrow=1, startcol=0)
        if sub_df is not None:
            sub_df.to_excel(
                writer, sheet_name=sheet, index=False,
                startrow=dataframe.shape[0] + 4, startcol=0,
            )

        worksheet = writer.sheets[sheet]
        workbook = writer.book
        col_fmt = workbook.add_format({"num_format": "0.00"})
        row_fmt = workbook.add_format({"num_format": "0.00"})
        title_fmt = workbook.add_format({"bold": True, "font_size": 26, "align": "center"})

        worksheet.set_column(0, dataframe.shape[1], 20)
        worksheet.set_column(1, 1, 30)

        if sheet == "Openings Raw Data":
            _format_raw_data_sheet(worksheet, workbook, dataframe, title_fmt, col_fmt,
                                   "Openings Raw Data", 14)
        elif sheet == "Summary":
            _format_summary_sheet(worksheet, workbook, dataframe, title_fmt, col_fmt,
                                  basin_area, "ECA Analysis Summary")
        else:
            _format_subbasin_sheet(worksheet, workbook, dataframe, title_fmt, col_fmt,
                                   row_fmt, sheet, sub_df)

    writer.close()


def _export_other_openings(other_data, xlsx_path):
    """Export Other Openings report."""
    _ensure_xlsxwriter_available()
    df_list, sheet_list = other_data
    df_list_r = list(reversed(df_list))
    sheet_list_r = list(reversed(sheet_list))

    arcpy.AddMessage("Exporting Other Openings Report")
    writer = pd.ExcelWriter(xlsx_path, engine="xlsxwriter")

    for dataframe, sheet in zip(df_list_r, sheet_list_r):
        dataframe = dataframe.reset_index(drop=True)
        dataframe.index = dataframe.index + 1
        dataframe.to_excel(writer, sheet_name=sheet, index=False, startrow=1, startcol=0)

        worksheet = writer.sheets[sheet]
        workbook = writer.book
        col_fmt = workbook.add_format({"num_format": "0.00"})
        title_fmt = workbook.add_format({"bold": True, "font_size": 26, "align": "center"})

        worksheet.set_column(0, dataframe.shape[1], 20)
        worksheet.set_column(1, 1, 30)

        cols = list(dataframe.columns)
        n_cols = len(cols)
        n_rows = dataframe.shape[0]

        if sheet == "Other Openings Raw Data":
            worksheet.set_column(0, 1, 30)
            worksheet.set_column(2, 2, 12)
            worksheet.set_column(3, 5, 13, col_fmt)
            worksheet.set_column(6, 6, 20)
            worksheet.set_column(7, 7, 13, col_fmt)
            col_names = [{"header": c} for c in cols[1:-1]]
            col_names.insert(0, {"header": cols[0], "total_string": "Total"})
            col_names.append({"header": cols[-1]})
            del col_names[3]
            col_names.insert(3, {"header": cols[3], "total_function": "sum"})
            if n_rows > 0:
                worksheet.add_table(1, 0, n_rows + 2, n_cols - 1, {
                    "total_row": True, "columns": col_names,
                })
            worksheet.merge_range(0, 0, 0, 7, "Other Openings Raw Data", title_fmt)
        elif sheet == "Other Openings Summary":
            n_basin = n_cols - 2
            worksheet.set_column(0, 0, 30)
            worksheet.set_column(1, n_basin + 1, 20, col_fmt)
            col_names = [{"header": cols[1]}]
            col_names.insert(0, {"header": cols[0], "total_string": "Total"})
            for c in cols[2:]:
                col_names.append({"header": c, "total_function": "sum"})
            if n_rows > 0:
                worksheet.add_table(1, 0, n_rows + 2, n_cols - 1, {
                    "total_row": True, "columns": col_names,
                })
            worksheet.merge_range(0, 0, 0, n_cols - 1, "ECA Analysis Summary", title_fmt)
        else:
            worksheet.set_column(0, 0, 30)
            worksheet.set_column(1, 4, 15, col_fmt)
            col_names = [{"header": c} for c in cols[1:-4]]
            col_names.insert(0, {"header": cols[0], "total_string": "Total"})
            for c in cols[-4:]:
                col_names.append({"header": c, "total_function": "sum"})
            if n_rows > 0:
                worksheet.add_table(1, 0, n_rows + 2, n_cols - 1, {
                    "total_row": True, "columns": col_names,
                })
            worksheet.merge_range(0, 0, 0, 4, f"{sheet} Sub-Basin", title_fmt)

    writer.close()


def _export_pest(pest_data, xlsx_path):
    """Export Pest Infestation report."""
    _ensure_xlsxwriter_available()
    df_list, sheet_list = pest_data
    df_list_r = list(reversed(df_list))
    sheet_list_r = list(reversed(sheet_list))

    arcpy.AddMessage("Exporting Pest Infestation Report")
    writer = pd.ExcelWriter(xlsx_path, engine="xlsxwriter")

    for dataframe, sheet in zip(df_list_r, sheet_list_r):
        dataframe = dataframe.reset_index(drop=True)
        dataframe.index = dataframe.index + 1
        dataframe.to_excel(writer, sheet_name=sheet, index=False, startrow=1, startcol=0)

        worksheet = writer.sheets[sheet]
        workbook = writer.book
        col_fmt = workbook.add_format({"num_format": "0.00"})
        title_fmt = workbook.add_format({"bold": True, "font_size": 26, "align": "center"})

        worksheet.set_column(0, dataframe.shape[1], 20)
        worksheet.set_column(1, 1, 30)

        cols = list(dataframe.columns)
        n_cols = len(cols)
        n_rows = dataframe.shape[0]

        if sheet == "Pest Infestation Raw Data":
            worksheet.set_column(0, 1, 30)
            worksheet.set_column(2, 2, 12)
            worksheet.set_column(3, 5, 13, col_fmt)
            worksheet.set_column(6, 6, 20)
            worksheet.set_column(7, 7, 15)
            worksheet.set_column(8, 8, 35)
            worksheet.set_column(9, 9, 15)
            col_names = [{"header": c} for c in cols[1:-1]]
            col_names.insert(0, {"header": cols[0]})
            col_names.append({"header": cols[-1]})
            if n_rows > 0:
                worksheet.add_table(1, 0, n_rows + 2, n_cols - 1, {
                    "total_row": True, "columns": col_names,
                })
            worksheet.merge_range(0, 0, 0, 9, "Pest Infestation Raw Data", title_fmt)
        else:
            worksheet.set_column(0, 0, 25)
            worksheet.set_column(1, 3, 14)
            worksheet.set_column(4, 4, 25)
            worksheet.set_column(5, 8, 14, col_fmt)
            col_names = [{"header": c} for c in cols[1:-4]]
            col_names.insert(0, {"header": cols[0]})
            for c in cols[-4:]:
                col_names.append({"header": c})
            if n_rows > 0:
                worksheet.add_table(1, 0, n_rows + 2, n_cols - 1, {
                    "total_row": True, "columns": col_names,
                })
            worksheet.merge_range(0, 0, 0, 8, f"{sheet} Sub-Basin", title_fmt)

    writer.close()


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def _format_raw_data_sheet(ws, wb, df, title_fmt, col_fmt, title, merge_end):
    """Format the raw data sheet with table and totals."""
    cols = list(df.columns)
    n_rows, n_cols = df.shape
    ws.set_column(1, 1, 30)
    ws.set_column(2, 2, 12)
    ws.set_column(4, 4, 13)
    ws.set_column(6, 6, 20, col_fmt)
    ws.set_column(7, 7, 14)
    ws.set_column(8, 8, 12, col_fmt)
    ws.set_column(10, 10, 13, col_fmt)
    ws.set_column(11, 11, 18, col_fmt)
    ws.set_column(12, 12, 20)
    ws.set_column(13, 14, 10, col_fmt)

    col_names = [{"header": c} for c in cols[1:-1]]
    col_names.insert(0, {"header": cols[0], "total_string": "Total"})
    col_names.append({"header": cols[-1], "total_function": "sum"})
    del col_names[8]
    col_names.insert(8, {"header": cols[8], "total_function": "sum"})
    if n_rows > 0:
        ws.add_table(1, 0, n_rows + 2, n_cols - 1, {
            "total_row": True, "columns": col_names,
        })
    ws.merge_range(0, 0, 0, merge_end, title, title_fmt)


def _format_summary_sheet(ws, wb, df, title_fmt, col_fmt, basin_area, title):
    """Format the Summary sheet with totals and percentage row."""
    cols = list(df.columns)
    n_rows, n_cols = df.shape
    n_basin = n_cols - 2

    ws.set_column(0, 0, 30)
    ws.set_column(1, n_basin + 1, 20, col_fmt)

    col_names = [{"header": cols[1]}]
    col_names.insert(0, {"header": cols[0], "total_string": "Total"})
    for c in cols[2:]:
        col_names.append({"header": c, "total_function": "sum"})
    if n_rows > 0:
        ws.add_table(1, 0, n_rows + 2, n_cols - 1, {
            "total_row": True, "columns": col_names,
        })
    ws.merge_range(0, 0, 0, n_cols - 1, title, title_fmt)

    # Add percentage row below the table's total row
    if n_rows > 0:
        _ensure_xlsxwriter_available()
        from xlsxwriter.utility import xl_col_to_name

        pct_row = n_rows + 3              # 0-indexed row for the percentage values
        total_row_xl = n_rows + 3         # 1-indexed Excel row of the total row

        ws.write_string(pct_row, 1, "Total %")
        for col_idx in range(2, n_cols - 1):
            col_letter = xl_col_to_name(col_idx)
            formula = f"={col_letter}{total_row_xl}/{basin_area}*100"
            ws.write_formula(pct_row, col_idx, formula, col_fmt)


def _format_subbasin_sheet(ws, wb, df, title_fmt, col_fmt, row_fmt, sheet, sub_df):
    """Format a per-subbasin sheet."""
    cols = list(df.columns)
    n_rows, n_cols = df.shape

    ws.set_column(2, 2, 30)
    ws.set_column(3, 7, 15, col_fmt)

    # Format subbasin H60 table if present
    if sub_df is not None:
        ws.set_row(n_rows + 5, 15, row_fmt)
        ws.set_row(n_rows + 6, 15, row_fmt)
        blue_fmt = wb.add_format({"bg_color": "#AED6F1"})
        ws.conditional_format(
            n_rows + 4, 0, n_rows + 6, 3,
            {"type": "no_blanks", "format": blue_fmt},
        )

    col_names = [{"header": c} for c in cols[1:-4]]
    col_names.insert(0, {"header": cols[0], "total_string": "Total"})
    for c in cols[-4:]:
        col_names.append({"header": c, "total_function": "sum"})
    if n_rows > 0:
        ws.add_table(1, 0, n_rows + 2, n_cols - 1, {
            "total_row": True, "columns": col_names,
        })
    ws.merge_range(0, 0, 0, 7, f"{sheet} Sub-Basin", title_fmt)
