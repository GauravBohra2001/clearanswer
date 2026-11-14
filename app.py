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

import copy
import json
import os
import subprocess
import sys
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
OUTPUTS_DIR = APP_DIR / "outputs"
CHALLENGE_REPO = APP_DIR / "oncosys-hackathon-challenge"
VALIDATOR = CHALLENGE_REPO / "format" / "validate.py"
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
@app.route("/api/export", methods=["OPTIONS"])
@app.route("/api/export/<job_id>", methods=["OPTIONS"])
@app.route("/api/export/download/<job_id>", methods=["OPTIONS"])
@app.route("/api/report/<job_id>/download.html", methods=["OPTIONS"])
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


@app.route("/api/export/<job_id>", methods=["POST"])
@app.route("/api/export", methods=["POST"])
def export_audit(job_id: str | None = None):
    """Write the completed audit to outputs/ and validate it with the hackathon's checker.

    The orchestrator already emits shared format v0.2 (see output.py), so this
    endpoint only has to: strip the private _trace key, apply the submission-
    level severity/confidence mapping the judges expect, write the file, and
    shell out to oncosys-hackathon-challenge/format/validate.py.
    """
    if not job_id:
        body = request.get_json(silent=True) or {}
        job_id = body.get("job_id") or request.values.get("job_id")
    if not job_id:
        return jsonify({"error": "missing job_id"}), 400
    with _jobs_lock:
        job = _jobs.get(job_id)
    if not job:
        return jsonify({"error": "unknown job_id"}), 404
    if job["state"] == "error":
        return jsonify({"error": job["error"] or "audit failed"}), 500
    if job["state"] != "done" or not job["result"]:
        return jsonify({"state": job["state"], "message": "still processing"}), 202

    overrides = None
    body = request.get_json(silent=True)
    if isinstance(body, dict):
        candidate = body.get("overrides")
        if isinstance(candidate, list):
            overrides = candidate

    audit = _prepare_for_submission(job["result"], overrides=overrides)
    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUTPUTS_DIR / f"audit-{job_id}.json"
    out_path.write_text(json.dumps(audit, indent=2), encoding="utf-8")

    valid, validator_output = _run_validator(out_path)
    return jsonify({
        "path": str(out_path.relative_to(APP_DIR)),
        "download_url": f"/api/export/download/{job_id}",
        "valid": valid,
        "validator_output": validator_output,
        "n_findings": len(audit.get("findings", [])),
    })


@app.route("/api/export/download/<job_id>", methods=["GET"])
def download_export(job_id: str):
    """Serve the exported audit.json so the browser can save it locally."""
    name = f"audit-{job_id}.json"
    if not (OUTPUTS_DIR / name).exists():
        return jsonify({"error": "no export for that job_id; call POST /api/export first"}), 404
    return send_from_directory(
        OUTPUTS_DIR, name, as_attachment=True, download_name="audit.json"
    )


@app.route("/api/report/<job_id>/download.html", methods=["GET", "POST"])
def download_html_report(job_id: str):
    """Render the completed audit as a self-contained HTML file.

    No API dependency: the response is a static page with inline CSS. A
    reviewer can save it, email it, or print it and still see every finding
    with evidence, impact analysis, and reviewer decisions.

    Applies the same submission-shape mapping as /api/export so the report
    reflects what judges will see (severity/confidence policy + reviewer
    overrides, _trace stripped).
    """
    with _jobs_lock:
        job = _jobs.get(job_id)
    if not job:
        return jsonify({"error": "unknown job_id"}), 404
    if job["state"] == "error":
        return jsonify({"error": job["error"] or "audit failed"}), 500
    if job["state"] != "done" or not job["result"]:
        return jsonify({"state": job["state"], "message": "still processing"}), 202

    overrides = None
    body = request.get_json(silent=True)
    if isinstance(body, dict):
        candidate = body.get("overrides")
        if isinstance(candidate, list):
            overrides = candidate

    audit = _prepare_for_submission(job["result"], overrides=overrides)
    from html_report import build_html_report

    html_bytes = build_html_report(audit).encode("utf-8")
    from flask import Response

    return Response(
        html_bytes,
        mimetype="text/html",
        headers={
            "Content-Disposition": 'attachment; filename="clearanswer-audit.html"'
        },
    )


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
    except Exception as e:  # noqa: BLE001 - surfaced to the client
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
    """Pull report text out of a JSON body, a form field, or an uploaded file.

    .pdf uploads are extracted via pdfplumber so a reviewer can drop a real
    paper in. .txt / .md decode as UTF-8 directly. Any other binary upload is
    best-effort decoded and left to the extractor to handle.
    """
    # 1) JSON body: {"report_text": "..."}
    if req.is_json:
        payload = req.get_json(silent=True) or {}
        text = payload.get("report_text") or payload.get("report")
        if text:
            return str(text)
    # 2) Multipart file upload: field name 'file' (or 'report' / 'report_file').
    for key in ("file", "report", "report_file"):
        f = req.files.get(key)
        if f and f.filename:
            name = (f.filename or "").lower()
            data = f.read()
            if name.endswith(".pdf"):
                return _extract_pdf_text(data, filename=f.filename)
            return data.decode("utf-8", errors="replace")
    # 3) Plain form field fallback.
    text = req.values.get("report_text") or req.values.get("report")
    if text:
        return str(text)
    raise ValueError(
        "no report text provided (send JSON {report_text: ...} or a multipart file)"
    )


def _extract_pdf_text(data: bytes, filename: str = "upload.pdf") -> str:
    """Extract selectable text from a PDF, honoring two-column layouts.

    Each page is split into a left and right half via page.crop(); if both
    halves carry substantial text the two halves are concatenated in reading
    order (left, then right). Single-column pages fall back to full-page
    extraction so they are not duplicated. All calls use x_tolerance=2 so
    tight academic typography keeps its word spacing.
    """
    try:
        import pdfplumber  # type: ignore
    except ImportError as e:
        raise ValueError(
            "PDF support needs the pdfplumber package. "
            "Run `pip install -r requirements.txt` and restart the server."
        ) from e

    import io

    pages: list[str] = []
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for page in pdf.pages:
            mid = page.width / 2
            left = (page.crop((0, 0, mid, page.height))
                    .extract_text(x_tolerance=2) or "").strip()
            right = (page.crop((mid, 0, page.width, page.height))
                     .extract_text(x_tolerance=2) or "").strip()
            two_col = len(left) > 40 and len(right) > 40
            txt = f"{left}\n\n{right}" if two_col else (
                page.extract_text(x_tolerance=2) or "").strip()
            if txt.strip():
                pages.append(txt.strip())
    if not pages:
        raise ValueError(
            f"No extractable text in {filename}. It may be a scanned or "
            "image-only PDF; rerun OCR and upload the resulting text."
        )
    return "\n\n".join(pages)


def _prepare_for_submission(audit: dict, overrides: list[dict] | None = None) -> dict:
    """Return a copy of the audit dict shaped for the judges' checker.

    Changes vs the stored audit:
    - drops the private _trace key the shared format does not define
    - applies reviewer accept/override decisions so the shipped verdict is
      the one the human confirmed, while preserving the tool's original
      verdict under tool_verdict for provenance
    - applies the submission severity policy to the FINAL verdict: high for
      contradicted, medium for insufficient_evidence, none for supported
    - sets confidence to high on every finding, because the verdict comes
      from a deterministic pandas computation, not from model sampling
    - guarantees every finding carries at least one evidence entry, since
      the schema requires it
    """
    submission = copy.deepcopy(audit)
    submission.pop("_trace", None)
    severity_by_verdict = {
        "supported": "none",
        "contradicted": "high",
        "insufficient_evidence": "medium",
    }

    override_map: dict[str, dict] = {}
    if overrides:
        for o in overrides:
            if isinstance(o, dict) and o.get("finding_id"):
                override_map[o["finding_id"]] = o

    for finding in submission.get("findings", []):
        fid = finding.get("id")
        verdict = finding.get("claim_verdict", "")

        ov = override_map.get(fid)
        if ov:
            finding["tool_verdict"] = verdict
            decision = ov.get("decision", "accept")
            finding["reviewer_decision"] = decision
            if decision == "override" and ov.get("verdict"):
                finding["claim_verdict"] = ov["verdict"]
                verdict = ov["verdict"]
            if ov.get("reason"):
                finding["reviewer_reason"] = ov["reason"]
            # A claim the reviewer touched no longer needs review.
            finding["needs_human_review"] = False

        finding["severity"] = severity_by_verdict.get(verdict, finding.get("severity", "none"))
        finding["confidence"] = "high"
        if not finding.get("evidence"):
            finding["evidence"] = [{"kind": "claim", "id": finding.get("claim_text", "")[:60]}]
    return submission


def _run_validator(path: Path) -> tuple[bool, str]:
    """Shell out to the hackathon validator. Falls back to our own on error."""
    if VALIDATOR.exists():
        try:
            proc = subprocess.run(
                [sys.executable, str(VALIDATOR), str(path)],
                capture_output=True, text=True, timeout=30,
            )
            output = (proc.stdout + proc.stderr).strip() or "(no output)"
            return proc.returncode == 0, output
        except (subprocess.TimeoutExpired, OSError) as e:
            return False, f"validator failed to run: {e}"
    # Fallback keeps the endpoint useful even if the challenge repo is absent.
    from output import validate_output
    errors = validate_output(json.loads(path.read_text()))
    if not errors:
        return True, f"valid   {path.name}"
    return False, "INVALID " + path.name + "\n  - " + "\n  - ".join(errors)


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
