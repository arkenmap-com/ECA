#!/usr/bin/env python3
"""Serve a small local GUI for the config-driven fire simulation pipeline."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parent
GUI = ROOT / "pipeline-gui" / "index.html"
DEFAULT_CONFIG = ROOT / "examples" / "nelson-50km-2025.json"
TMP_ROOT = Path("/private/tmp/fire-sim-gui")
JOB_LOCK = threading.Lock()
JOB: dict[str, Any] = {
    "status": "idle",
    "message": "Load the default configuration, then validate or run it.",
    "log": "No job started.",
    "process": None,
    "config_path": None,
    "paths": None,
}


def output_paths(config: dict[str, Any]) -> dict[str, str]:
    outputs = config.get("outputs", {})
    cell2fire = outputs.get("cell2fire_input_dir", f"Cell2Fire/data/{config.get('name', 'fire-sim')}")
    output_dir = outputs.get("output_dir", f"runs/{config.get('name', 'fire-sim')}/outputs")
    web = outputs.get("web_map_dir", f"runs/{config.get('name', 'fire-sim')}/web-map")
    return {"Cell2Fire inputs": str(cell2fire), "results": str(output_dir), "web map": str(web)}


def read_log() -> str:
    process = JOB.get("process")
    if process is None:
        return str(JOB.get("log", ""))
    if process.poll() is not None and JOB.get("status") == "running":
        JOB["status"] = "success" if process.returncode == 0 else "failed"
        JOB["message"] = "Pipeline completed." if process.returncode == 0 else f"Pipeline failed with exit code {process.returncode}."
    return str(JOB.get("log", ""))


def collect_output(process: subprocess.Popen[str]) -> None:
    """Read the child process without blocking the HTTP status endpoint."""
    if process.stdout is not None:
        for line in process.stdout:
            with JOB_LOCK:
                JOB["log"] = str(JOB.get("log", "")) + line
    returncode = process.wait()
    with JOB_LOCK:
        if JOB.get("process") is process and JOB.get("status") == "running":
            JOB["status"] = "success" if returncode == 0 else "failed"
            JOB["message"] = "Pipeline completed." if returncode == 0 else f"Pipeline failed with exit code {returncode}."


def start_job(config: dict[str, Any]) -> None:
    global JOB
    with JOB_LOCK:
        read_log()
        if JOB.get("process") is not None and JOB["process"].poll() is None:
            raise RuntimeError("A pipeline job is already running.")
        TMP_ROOT.mkdir(parents=True, exist_ok=True)
        fd, raw_path = tempfile.mkstemp(prefix="config-", suffix=".json", dir=TMP_ROOT)
        os.close(fd)
        config_path = Path(raw_path)
        config_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
        command = [sys.executable, str(ROOT / "fire_sim_pipeline.py"), "--config", str(config_path), "--stage", "all"]
        process = subprocess.Popen(command, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
        JOB = {
            "status": "running",
            "message": "Pipeline started. Waiting for output…",
            "log": "$ " + " ".join(command) + "\n",
            "process": process,
            "config_path": str(config_path),
            "paths": output_paths(config),
        }
        threading.Thread(target=collect_output, args=(process,), daemon=True).start()


class Handler(BaseHTTPRequestHandler):
    def send_json(self, data: dict[str, Any], status: int = 200) -> None:
        payload = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path == "/":
            payload = GUI.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        if path == "/api/default-config":
            self.send_json(json.loads(DEFAULT_CONFIG.read_text(encoding="utf-8")))
            return
        if path == "/api/status":
            with JOB_LOCK:
                log = read_log()
                response = {key: value for key, value in JOB.items() if key not in ("process", "config_path")}
                response["log"] = log
            self.send_json(response)
            return
        self.send_error(404)

    def read_body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        try:
            value = json.loads(self.rfile.read(length).decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ValueError(f"Invalid JSON request: {exc}") from exc
        if not isinstance(value, dict):
            raise ValueError("Request body must be a JSON object.")
        return value

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        try:
            if path == "/api/validate":
                config = self.read_body()
                TMP_ROOT.mkdir(parents=True, exist_ok=True)
                fd, raw_path = tempfile.mkstemp(prefix="validate-", suffix=".json", dir=TMP_ROOT)
                os.close(fd)
                config_path = Path(raw_path)
                config_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
                command = [sys.executable, str(ROOT / "fire_sim_pipeline.py"), "--config", str(config_path), "--stage", "validate"]
                completed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
                self.send_json({"ok": completed.returncode == 0, "message": "Inputs validated successfully." if completed.returncode == 0 else "Validation failed.", "log": (completed.stdout + completed.stderr).strip(), "paths": output_paths(config)}, 200)
                return
            if path == "/api/run":
                config = self.read_body()
                try:
                    start_job(config)
                except RuntimeError as exc:
                    self.send_json({"ok": False, "message": str(exc), "log": read_log()}, 409)
                    return
                self.send_json({"ok": True, "message": JOB["message"], "log": JOB["log"], "paths": JOB["paths"]})
                return
            if path == "/api/stop":
                with JOB_LOCK:
                    process = JOB.get("process")
                    if process is not None and process.poll() is None:
                        process.terminate()
                        JOB["status"] = "failed"
                        JOB["message"] = "Pipeline stopped by user."
                        JOB["log"] = read_log() + "\n[stopped by user]\n"
                self.send_json({"ok": True, "message": JOB["message"], "log": JOB["log"]})
                return
            self.send_error(404)
        except ValueError as exc:
            self.send_json({"ok": False, "message": str(exc), "log": ""}, 400)
        except Exception as exc:  # keep the local GUI responsive on tool errors
            self.send_json({"ok": False, "message": f"Server error: {exc}", "log": ""}, 500)

    def log_message(self, format: str, *args: Any) -> None:
        print(f"[gui] {format % args}")


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=4180)
    args = parser.parse_args()
    if not GUI.exists() or not DEFAULT_CONFIG.exists():
        raise SystemExit("GUI assets or the example configuration are missing.")
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Fire simulation GUI: http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping GUI server.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
