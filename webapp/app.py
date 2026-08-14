"""Local web application for running and reviewing Open ECA draft analyses.

Run with ``python3 -m webapp.app`` and browse to http://127.0.0.1:8000.
The application is deliberately local-first: uploaded source data and outputs
remain in its data directory, and no data is sent to an external service.
"""

from __future__ import annotations

import argparse
import html
import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from threading import Lock

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse

from open_eca.data_acquisition import acquire_for_watershed
from open_eca.dashboard import create_dashboard
from open_eca.draft import AdditionalInput, run_draft
from open_eca.fwa import download_named_watershed, search_named_watersheds
from open_eca.recovery import load_curves


TEST_CURVES = Path(__file__).with_name("test_recovery_curves.json")


@dataclass
class Run:
    """The small amount of status needed for one local analysis run."""

    identifier: str
    directory: Path
    state: str = "queued"
    stage: str = "Waiting to start"
    live_data: bool = False
    basin: str | None = None
    error: str | None = None


def _page(title: str, content: str, script: str = "") -> HTMLResponse:
    return HTMLResponse(
        f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{html.escape(title)} · Open ECA</title>
<style>
:root{{color-scheme:light;--navy:#163a4d;--teal:#146c70;--paper:#fff;--line:#d7e0e4;--muted:#536570}}
*{{box-sizing:border-box}}body{{margin:0;background:#f3f6f7;color:#1b2838;font:15px system-ui,-apple-system,sans-serif}}
header{{padding:18px max(24px,calc((100vw - 1180px)/2));background:var(--navy);color:#fff}}header a{{color:#fff;text-decoration:none}}header strong{{font-size:20px}}main{{max-width:1180px;margin:28px auto;padding:0 24px}}.card{{background:var(--paper);border:1px solid var(--line);border-radius:9px;padding:24px;box-shadow:0 1px 2px #163a4d0d}}h1{{margin:0 0 8px;font-size:28px}}h2{{font-size:18px;margin:28px 0 10px}}p{{line-height:1.5}}.muted{{color:var(--muted)}}.grid{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px}}label{{display:block;font-weight:650;margin:0 0 6px}}input,select{{width:100%;padding:9px;border:1px solid #aebfc6;border-radius:5px;background:white;font:inherit}}input[type=radio]{{width:auto}}.field{{margin:0 0 16px}}.help{{font-size:12px;color:var(--muted);margin:5px 0 0}}button,.button{{display:inline-block;border:0;border-radius:5px;background:var(--teal);color:#fff;padding:10px 14px;font:inherit;font-weight:650;cursor:pointer;text-decoration:none}}button.secondary,.button.secondary{{background:#fff;color:var(--navy);border:1px solid #9aafb7}}.source-choice{{display:flex;gap:20px;margin:10px 0 18px}}.source-choice label{{font-weight:500}}.additional{{border-top:1px solid var(--line);margin-top:12px;padding-top:16px}}.additional-row{{display:grid;grid-template-columns:1.4fr 1fr 1fr 1fr .7fr auto;gap:10px;align-items:end;margin:10px 0}}.additional-row label{{font-size:12px}}.error{{background:#fff0f0;border:1px solid #e3a5a5;color:#852020;padding:12px;border-radius:5px}}.status{{padding:10px 12px;border-radius:5px;background:#e8f2f3;color:#115e61;font-weight:650}}.downloads{{display:flex;flex-wrap:wrap;gap:8px;margin:16px 0}}iframe{{width:100%;height:760px;border:1px solid var(--line);border-radius:6px;background:#fff}}[hidden]{{display:none!important}}@media(max-width:760px){{.grid,.additional-row{{grid-template-columns:1fr}}.additional-row button{{width:max-content}}}}
.notice{{background:#fff8e6;border:1px solid #e2c46d;color:#654d0b;padding:10px 12px;border-radius:5px}}
</style></head><body><header><a href="/"><strong>Open ECA</strong> <span>Draft analysis workspace</span></a></header><main>{content}</main>{script}</body></html>"""
    )


def _home() -> HTMLResponse:
    return _page(
        "New analysis",
        """<section class="card"><h1>New ECA draft</h1><p class="muted">Select a watershed and run an ECA draft with current public BC Geographic Warehouse data. Files stay on this computer in the configured web-app data folder.</p>
<form action="/runs" method="post" enctype="multipart/form-data"><div class="grid">
<div class="field"><label for="fwa-search">Freshwater Atlas watershed</label><input id="fwa-search" type="search" placeholder="e.g. Falls Creek" autocomplete="off"><p class="help">Search the BC Freshwater Atlas, then select the exact named watershed. Names are not always unique.</p><button id="find-watersheds" class="secondary" type="button">Find watersheds</button><div id="fwa-results" class="help" aria-live="polite"></div><input id="fwa-id" name="fwa_id" type="hidden" required></div>
<div class="field"><label>Analysis data</label><div class="source-choice"><label><input name="data_source" type="radio" value="bc_live" checked> Live BC data</label><label><input name="data_source" type="radio" value="upload"> Prepared cache</label></div><div id="inputs-field" hidden><label for="inputs">Catalogue input cache</label><input id="inputs" name="inputs" type="file" accept=".gpkg"><p class="help">GeoPackage containing VRI openings and BEC zones, plus any standard source layers.</p></div><p id="live-help" class="help">Downloads current, watershed-scoped layers from BC OpenMaps. A provenance manifest records the source snapshot.</p></div>
<div class="field"><label>Recovery curves</label><div class="source-choice"><label><input name="curve_source" type="radio" value="test" checked> Synthetic test preset</label><label><input name="curve_source" type="radio" value="upload"> Upload curves</label></div><p id="test-curves-help" class="notice"><strong>Testing only.</strong> These plausible synthetic curves are not calibrated, approved, or suitable for operational decisions. <a href="/test-recovery-curves.json">View JSON</a>.</p><div id="curves-field" hidden><label for="curves">Curve workbook or JSON</label><input id="curves" name="curves" type="file" accept=".xlsx,.json"></div></div>
<div class="field"><label for="field_team">Field team</label><input id="field_team" name="field_team" value="Synthetic Test" placeholder="Boundary"><p class="help">Use “Synthetic Test” with the test preset. For uploaded curves, enter the matching workbook sheet or JSON team name.</p></div>
</div><p class="help">This streamlined mode does not use a DEM: ECA is reported for the entire selected watershed, without an H60 elevation split.</p><section class="additional"><h2>Additional inputs</h2><p class="muted">Add local vector layers without changing the catalogue cache. “ECA opening” adds uncovered area to the ECA calculation; “Context only” is retained as other openings.</p><div id="additional-inputs"></div><button class="secondary" id="add-input" type="button">Add input layer</button></section><p><button type="submit">Run ECA draft</button></p></form></section>""",
        """<script>
const list=document.querySelector('#additional-inputs');document.querySelector('#add-input').addEventListener('click',()=>{const row=document.createElement('div');row.className='additional-row';row.innerHTML=`<div><label>Vector layer<input type="file" name="additional_files" accept=".gpkg,.geojson,.json,.shp" required></label></div><div><label>Source label<input name="additional_labels" placeholder="Local harvest block" required></label></div><div><label>Role<select name="additional_roles"><option value="opening">ECA opening</option><option value="other">Context only</option></select></label></div><div><label>GeoPackage layer <span class="muted">(optional)</span><input name="additional_layers" placeholder="layer_name"></label></div><div><label>Buffer (m) <span class="muted">(optional)</span><input name="additional_buffers" type="number" min="0" step="0.1" placeholder="0"></label></div><button class="secondary" type="button">Remove</button>`;row.querySelector('button').addEventListener('click',()=>row.remove());list.append(row)});
const inputsField=document.querySelector('#inputs-field'),inputs=document.querySelector('#inputs'),liveHelp=document.querySelector('#live-help');document.querySelectorAll('input[name=data_source]').forEach(radio=>radio.addEventListener('change',()=>{if(!radio.checked)return;const upload=radio.value==='upload';inputsField.hidden=!upload;liveHelp.hidden=upload;inputs.required=upload}));
const curvesField=document.querySelector('#curves-field'),curves=document.querySelector('#curves'),testCurvesHelp=document.querySelector('#test-curves-help'),fieldTeam=document.querySelector('#field_team');document.querySelectorAll('input[name=curve_source]').forEach(radio=>radio.addEventListener('change',()=>{if(!radio.checked)return;const upload=radio.value==='upload';curvesField.hidden=!upload;testCurvesHelp.hidden=upload;curves.required=upload;if(upload&&fieldTeam.value==='Synthetic Test')fieldTeam.value='';if(!upload&&!fieldTeam.value.trim())fieldTeam.value='Synthetic Test'}));
const fwaSearch=document.querySelector('#fwa-search'),fwaResults=document.querySelector('#fwa-results'),fwaId=document.querySelector('#fwa-id');document.querySelector('#find-watersheds').addEventListener('click',async()=>{const query=fwaSearch.value.trim();if(query.length<2){fwaResults.textContent='Enter at least two characters.';return}fwaResults.textContent='Searching the BC Freshwater Atlas…';try{const response=await fetch(`/fwa/search?q=${encodeURIComponent(query)}`);const payload=await response.json();if(!response.ok)throw new Error(payload.detail||'Search failed');fwaResults.replaceChildren();if(!payload.length){fwaResults.textContent='No named watersheds found.';return}payload.forEach(item=>{const label=document.createElement('label'),radio=document.createElement('input');radio.type='radio';radio.name='fwa-choice';radio.value=item.named_watershed_id;radio.addEventListener('change',()=>{fwaId.value=item.named_watershed_id});label.append(radio,` ${item.name} — ID ${item.named_watershed_id}${item.area_ha===null?'':`, ${item.area_ha.toLocaleString(undefined,{maximumFractionDigits:0})} ha`}`);fwaResults.append(label)})}catch(error){fwaResults.textContent=error.message}});
</script>""",
    )


def _safe_filename(name: str | None, fallback: str) -> str:
    candidate = Path(name or fallback).name
    return candidate if candidate and candidate != "." else fallback


async def _save_upload(upload: UploadFile, directory: Path, prefix: str, max_bytes: int) -> Path:
    filename = _safe_filename(upload.filename, prefix)
    destination = directory / f"{prefix}_{filename}"
    written = 0
    try:
        with destination.open("wb") as target:
            while chunk := await upload.read(1024 * 1024):
                written += len(chunk)
                if written > max_bytes:
                    raise HTTPException(
                        status_code=413,
                        detail=f"Uploaded files must be smaller than {max_bytes // (1024 * 1024)} MB.",
                    )
                target.write(chunk)
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    finally:
        await upload.close()
    return destination


def create_app(data_dir: Path | None = None) -> FastAPI:
    """Create the application; ``data_dir`` is injectable for tests and deployments."""
    root = (data_dir or Path(os.environ.get("ECA_DATA_DIR", "webapp_data"))).resolve()
    root.mkdir(parents=True, exist_ok=True)
    max_upload_bytes = int(os.environ.get("ECA_MAX_UPLOAD_MB", "100")) * 1024 * 1024
    runs: dict[str, Run] = {}
    lock = Lock()
    analysis_lock = Lock()
    app = FastAPI(title="Open ECA", docs_url=None, redoc_url=None)

    def get_run(identifier: str) -> Run:
        with lock:
            run = runs.get(identifier)
        if run is None:
            raise HTTPException(status_code=404, detail="Analysis run not found.")
        return run

    def execute(run: Run, fwa_id: int, inputs: Path | None, curves: Path, field_team: str | None, extras: tuple[AdditionalInput, ...]) -> None:
        with analysis_lock:
            run.state = "running"
            try:
                run.stage = "Downloading Freshwater Atlas watershed"
                watershed_path = run.directory / "uploads" / "fwa_watershed.geojson"
                download_named_watershed(fwa_id, watershed_path)
                if inputs is None:
                    run.stage = "Downloading current BC warehouse layers"
                    inputs = acquire_for_watershed(
                        watershed_path,
                        run.directory / "inputs" / "bc_catalogue_inputs.gpkg",
                    )
                run.stage = "Calculating ECA draft"
                result = run_draft(watershed_path, "GNIS_NAME", "GNIS_NAME", inputs, None, load_curves(curves), run.directory / "output", field_team, extras)
                run.stage = "Building dashboard"
                create_dashboard(result.geopackage, run.directory / "output" / "eca_dashboard.html")
                run.basin = result.basin
                run.stage = "Complete"
                run.state = "complete"
            except Exception as error:  # Show a concise diagnostic on the result page.
                run.error = str(error)
                run.stage = "Failed"
                run.state = "failed"

    @app.get("/health")
    def health() -> JSONResponse:
        return JSONResponse({"status": "ok"})

    @app.get("/test-recovery-curves.json")
    def test_recovery_curves() -> FileResponse:
        return FileResponse(
            TEST_CURVES,
            media_type="application/json",
            filename="synthetic-test-recovery-curves.json",
        )

    @app.get("/", response_class=HTMLResponse)
    def home() -> HTMLResponse:
        return _home()

    @app.get("/fwa/search")
    def fwa_search(q: str) -> JSONResponse:
        try:
            matches = search_named_watersheds(q)
        except (RuntimeError, ValueError) as error:
            raise HTTPException(status_code=502 if isinstance(error, RuntimeError) else 422, detail=str(error)) from error
        return JSONResponse([match.to_dict() for match in matches])

    @app.post("/runs")
    async def create_run(
        background_tasks: BackgroundTasks,
        fwa_id: int = Form(...),
        data_source: str = Form("bc_live"),
        inputs: UploadFile | None = File(default=None),
        curve_source: str = Form("test"),
        curves: UploadFile | None = File(default=None),
        field_team: str = Form(""),
        additional_files: list[UploadFile] = File(default=[]),
        additional_labels: list[str] = Form(default=[]),
        additional_roles: list[str] = Form(default=[]),
        additional_layers: list[str] = Form(default=[]),
        additional_buffers: list[str] = Form(default=[]),
    ) -> RedirectResponse:
        if data_source not in {"bc_live", "upload"}:
            raise HTTPException(status_code=422, detail="Choose live BC data or a prepared cache.")
        if curve_source not in {"test", "upload"}:
            raise HTTPException(status_code=422, detail="Choose the synthetic test curves or upload a curve file.")
        if curve_source == "upload" and (curves is None or not curves.filename):
            raise HTTPException(status_code=422, detail="Upload a recovery-curve workbook or JSON file.")
        if data_source == "upload" and (inputs is None or not inputs.filename):
            raise HTTPException(status_code=422, detail="Upload a catalogue input cache for prepared-cache mode.")
        if data_source == "bc_live" and not field_team.strip():
            raise HTTPException(status_code=422, detail="Field team is required for live BC data.")
        if len(additional_files) != len(additional_labels) or len(additional_files) != len(additional_roles):
            raise HTTPException(status_code=422, detail="Each additional input needs a layer, source label, and role.")
        if additional_buffers and len(additional_files) != len(additional_buffers):
            raise HTTPException(status_code=422, detail="Each additional input needs a valid buffer value.")
        identifier = uuid.uuid4().hex[:12]
        directory = root / identifier
        uploads = directory / "uploads"
        uploads.mkdir(parents=True)
        saved_inputs = await _save_upload(inputs, uploads, "inputs", max_upload_bytes) if data_source == "upload" and inputs is not None else None
        saved_curves = (
            await _save_upload(curves, uploads, "curves", max_upload_bytes)
            if curve_source == "upload" and curves is not None
            else TEST_CURVES
        )
        extras: list[AdditionalInput] = []
        for index, upload in enumerate(additional_files):
            path = await _save_upload(upload, uploads, f"additional_{index + 1}", max_upload_bytes)
            try:
                buffer_m = float(additional_buffers[index] or 0) if additional_buffers else 0
            except ValueError as error:
                raise HTTPException(status_code=422, detail="Additional input buffers must be numbers.") from error
            extras.append(AdditionalInput(path, additional_labels[index].strip(), additional_roles[index], additional_layers[index].strip() or None, True, buffer_m))
        run = Run(identifier, directory, live_data=data_source == "bc_live")
        with lock:
            runs[identifier] = run
        background_tasks.add_task(execute, run, fwa_id, saved_inputs, saved_curves, field_team.strip() or None, tuple(extras))
        return RedirectResponse(f"/runs/{identifier}", status_code=303)

    @app.get("/runs/{identifier}", response_class=HTMLResponse)
    def run_page(identifier: str) -> HTMLResponse:
        run = get_run(identifier)
        if run.state in {"queued", "running"}:
            return _page("Analysis running", f'<section class="card"><h1>Analysis {html.escape(run.state)}</h1><p class="status">{html.escape(run.stage)}</p><p class="muted">Live downloads can take several minutes for large watersheds. Run ID: {html.escape(identifier)}</p></section>', '<script>setTimeout(()=>location.reload(),2000)</script>')
        if run.state == "failed":
            return _page("Analysis failed", f'<section class="card"><h1>Analysis could not finish</h1><p class="error">{html.escape(run.error or "Unknown error")}</p><p><a class="button secondary" href="/">Start another analysis</a></p></section>')
        source_downloads = ""
        if run.live_data:
            source_downloads = f'<a class="button secondary" href="/runs/{identifier}/files/inputs">Download source snapshot</a><a class="button secondary" href="/runs/{identifier}/files/provenance">Download provenance</a>'
        return _page(
            run.basin or "ECA draft",
            f'''<section class="card"><h1>{html.escape(run.basin or "ECA draft")} — completed</h1><p class="status">Draft output is ready.</p><div class="downloads"><a class="button" href="/runs/{identifier}/files/dashboard">Open dashboard</a><a class="button secondary" href="/runs/{identifier}/files/geopackage">Download GeoPackage</a><a class="button secondary" href="/runs/{identifier}/files/summary">Download ECA summary</a><a class="button secondary" href="/runs/{identifier}/files/openings">Download opening records</a>{source_downloads}</div><iframe title="Interactive ECA dashboard" src="/runs/{identifier}/files/dashboard"></iframe></section>''',
        )

    @app.get("/runs/{identifier}/status")
    def run_status(identifier: str) -> JSONResponse:
        run = get_run(identifier)
        return JSONResponse({"id": run.identifier, "state": run.state, "stage": run.stage, "live_data": run.live_data, "basin": run.basin, "error": run.error})

    @app.get("/runs/{identifier}/files/{file_kind}")
    def download(identifier: str, file_kind: str) -> FileResponse:
        run = get_run(identifier)
        paths = {
            "dashboard": (run.directory / "output" / "eca_dashboard.html", "text/html", None),
            "geopackage": (run.directory / "output" / "ECA_Draft.gpkg", "application/geopackage+sqlite3", "ECA_Draft.gpkg"),
            "summary": (run.directory / "output" / "reports" / "eca_summary.csv", "text/csv", "eca_summary.csv"),
            "openings": (run.directory / "output" / "reports" / "openings_recovery.csv", "text/csv", "openings_recovery.csv"),
            "inputs": (run.directory / "inputs" / "bc_catalogue_inputs.gpkg", "application/geopackage+sqlite3", "bc_catalogue_inputs.gpkg"),
            "provenance": (run.directory / "inputs" / "bc_catalogue_inputs.provenance.json", "application/json", "bc_catalogue_inputs.provenance.json"),
        }
        if file_kind not in paths:
            raise HTTPException(status_code=404, detail="Requested output is not available.")
        path, media_type, filename = paths[file_kind]
        if not path.is_file():
            raise HTTPException(status_code=404, detail="Requested output is not available yet.")
        return FileResponse(path, media_type=media_type, filename=filename)

    return app


app = create_app()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path("webapp_data"), help="Local folder for uploaded files and outputs.")
    parser.add_argument("--host", default="127.0.0.1", help="Bind address (default: local computer only).")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args(argv)
    import uvicorn

    uvicorn.run(create_app(args.data_dir), host=args.host, port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
