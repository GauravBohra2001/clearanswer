"""Flask wrapper around the Research Claim Auditor pipeline.

The CLI entry point (run.py) stays authoritative for judged runs. This file
exists so a browser-based demo can post a report, poll for progress, and
pull the final audit.json dict without reaching into agents/ directly.

Design notes
------------
* The real OrchestratorAgent reads a report FROM DISK (so it can hash the
  file's path for the question field). The /api/audit endpoint therefore
  writes the posted text to a per-job scratch file and feeds the path in.
  Nothing in the pipeline is modified for this wrapper.
* Audits run on a background daemon thread so the request thread returns
  immediately with a job_id and the browser can poll /api/status.
* Jobs live in a module-level dict. This is intentional for a single-process
  demo; a multi-worker deployment would need an external store.
* CORS is handled by a tiny after_request hook so the wrapper has zero extra
  dependencies beyond Flask itself.
"""
from __future__ import annotations

import os
import tempfile
import threading
import traceback
import uuid
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv()

from flask import Flask, jsonify, render_template, request, send_from_directory

from agents.orchestrator import OrchestratorAgent

APP_DIR = Path(__file__).resolve().parent
DEFAULT_DATA_DIR = (APP_DIR / "oncosys-hackathon-challenge" / "data" / "tcga-brca" / "raw").resolve()
# Scratch dir for posted report text. One subdir per job so cleanup is easy
# and two concurrent requests cannot clobber each other's input.
SCRATCH_DIR = Path(tempfile.gettempdir()) / "clearanswer_jobs"
SCRATCH_DIR.mkdir(parents=True, exist_ok=True)

app = Flask(__name__, template_folder="templates", static_folder="static")

# jobs[job_id] -> {state, result, error, claims}
# state is one of: queued, extracting, verifying, done, error
_jobs: dict[str, dict[str, Any]] = {}
_jobs_lock = threading.Lock()


# --------------------------------------------------------------------- CORS

@app.after_request
def _add_cors_headers(response):
    """Permissive CORS for the local demo. Judges may host the UI elsewhere."""
    response.headers.setdefault("Access-Control-Allow-Origin", "*")
    response.headers.setdefault("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
    response.headers.setdefault(
        "Access-Control-Allow-Headers", "Content-Type, Authorization"
    )
    return response


@app.route("/api/audit", methods=["OPTIONS"])
@app.route("/api/status/<job_id>", methods=["OPTIONS"])
@app.route("/api/result/<job_id>", methods=["OPTIONS"])
def _cors_preflight(job_id: str | None = None):
    return ("", 204)


# ---------------------------------------------------------- frontend routes

@app.route("/")
def index():
    """Render the SPA template when one is present.

    The demo frontend is expected at templates/index.html. If it is not yet
    built, we return a small hint instead of a 500 so the API is still usable.
    """
    if (APP_DIR / "templates" / "index.html").exists():
        return render_template("index.html")
    return (
        "<h1>Research Claim Auditor API</h1>"
        "<p>Frontend not built yet. Try POST /api/audit with "
        "<code>{\"report_text\": \"...\"}</code>.</p>",
        200,
    )


@app.route("/static/<path:name>")
def _static(name: str):
    return send_from_directory(app.static_folder, name)


# ------------------------------------------------------------- audit routes

@app.route("/api/audit", methods=["POST"])
def start_audit():
    try:
        report_text = _extract_report_text(request)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    if not report_text.strip():
        return jsonify({"error": "report is empty"}), 400

    data_dir = request.values.get("data_dir") or str(DEFAULT_DATA_DIR)
    team = request.values.get("team") or "clearanswer"

    job_id = uuid.uuid4().hex
    job_dir = SCRATCH_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    report_path = job_dir / "report.md"
    report_path.write_text(report_text, encoding="utf-8")

    with _jobs_lock:
        _jobs[job_id] = {
            "state": "queued",
            "result": None,
            "error": None,
            "claims": [],
            "team": team,
        }

    worker = threading.Thread(
        target=_run_audit_job,
        args=(job_id, report_path, data_dir, team),
        daemon=True,
        name=f"audit-{job_id[:8]}",
    )
    worker.start()
    return jsonify({"job_id": job_id})


@app.route("/api/status/<job_id>", methods=["GET"])
def get_status(job_id: str):
    with _jobs_lock:
        job = _jobs.get(job_id)
        if not job:
            return jsonify({"error": "unknown job_id"}), 404
        # Copy fields the UI needs; omit the full result dict here so a long
        # poll does not ship megabytes when the UI only wants the state.
        payload = {
            "job_id": job_id,
            "state": job["state"],
            "claims": _project_claims(job),
        }
        if job["error"]:
            payload["error"] = job["error"]
        return jsonify(payload)


@app.route("/api/result/<job_id>", methods=["GET"])
def get_result(job_id: str):
    with _jobs_lock:
        job = _jobs.get(job_id)
    if not job:
        return jsonify({"error": "unknown job_id"}), 404
    if job["state"] == "error":
        return jsonify({"error": job["error"] or "audit failed"}), 500
    if job["state"] != "done":
        return jsonify({"state": job["state"], "message": "still processing"}), 202
    return jsonify(job["result"])


# --------------------------------------------------------- background worker

def _run_audit_job(job_id: str, report_path: Path, data_dir: str, team: str) -> None:
    """Runs the orchestrator pipeline and records the outcome on the job dict."""
    _set_state(job_id, "extracting")
    try:
        orchestrator = OrchestratorAgent(team=team)
        # The orchestrator does extract and verify in one call; once the
        # extractor returns, it is already verifying claims. We flip the
        # state marker to 'verifying' here so a UI polling at ~1Hz sees the
        # transition even though there is no streaming hook today.
        _set_state(job_id, "verifying")
        audit = orchestrator.run(report_path=str(report_path), data_dir=data_dir)
        with _jobs_lock:
            _jobs[job_id]["result"] = audit
            _jobs[job_id]["claims"] = audit.get("findings", [])
            _jobs[job_id]["state"] = "done"
    except Exception as e:  # noqa: BLE001 — surfaced to the client
        tb = traceback.format_exc(limit=5)
        with _jobs_lock:
            _jobs[job_id]["state"] = "error"
            _jobs[job_id]["error"] = f"{type(e).__name__}: {e}\n{tb}"


def _set_state(job_id: str, state: str) -> None:
    with _jobs_lock:
        if job_id in _jobs:
            _jobs[job_id]["state"] = state


# ------------------------------------------------------- helpers and parsers

def _extract_report_text(req) -> str:
    """Pull report text out of a JSON body, a form field, or an uploaded file."""
    # 1) JSON body: {"report_text": "..."}
    if req.is_json:
        payload = req.get_json(silent=True) or {}
        text = payload.get("report_text") or payload.get("report")
        if text:
            return str(text)
    # 2) Multipart file upload: field name 'file' (or 'report')
    for key in ("file", "report", "report_file"):
        f = req.files.get(key)
        if f and f.filename:
            return f.read().decode("utf-8", errors="replace")
    # 3) Plain form field fallback.
    text = req.values.get("report_text") or req.values.get("report")
    if text:
        return str(text)
    raise ValueError(
        "no report text provided (send JSON {report_text: ...} or a multipart file)"
    )


def _project_claims(job: dict) -> list[dict]:
    """Expose a stable, smaller claim shape for the status endpoint.

    While the audit is running we have no partial findings, so we return an
    empty list. When it is done we project each finding to the shape the
    demo frontend expects: claim_text, verdict, correct_value, summary.
    """
    if job["state"] != "done" or not job["result"]:
        return []
    out = []
    for f in job["result"].get("findings", []):
        out.append({
            "id": f.get("id"),
            "claim_text": f.get("claim_text"),
            "verdict": f.get("claim_verdict"),
            "correct_value": f.get("correct_value"),
            "summary": f.get("summary"),
            "needs_human_review": f.get("needs_human_review", False),
            "limitation": f.get("limitation"),
        })
    return out


# ------------------------------------------------------------------ entrypoint

if __name__ == "__main__":
    # debug=True is fine for the demo. Disable the reloader so the background
    # worker threads do not get killed by the double-start reloader process.
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=True, use_reloader=False)
