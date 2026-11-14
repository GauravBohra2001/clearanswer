"""Standalone HTML report renderer.

Takes an audit dict (same shape as audit.json) and returns a self-contained
HTML page: inline CSS, no external fonts, no JavaScript, no remote images,
no API dependency. A reviewer can save the file, email it, or print it and
still see every finding with its evidence chain, impact analysis, and
reviewer decision.

Design mirrors the live Flask UI (teal primary, warm cream background,
verdict-tinted sections) so the standalone report feels like the same
product - just frozen.
"""
from __future__ import annotations

import datetime
import html
import json
from pathlib import Path
from typing import Any

_CSS = """
:root {
  --bg: #FCFBF8;
  --surface: #FFFFFF;
  --border: #ECE6DA;
  --tile: #F3EFE6;
  --ink: #1E2A3A;
  --slate: #5B6573;
  --mute: #8A919B;
  --primary: #2F6F73;
  --supported-bg: #E3EFEC;
  --supported-fg: #22545A;
  --contradicted-bg: #F8E4DE;
  --contradicted-fg: #9C3F2F;
  --insufficient-bg: #F6EEDC;
  --insufficient-fg: #8A6620;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  padding: 0;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  font-size: 15px;
  line-height: 1.5;
  color: var(--ink);
  background: var(--bg);
}
.top-bar { height: 4px; background: var(--primary); }
.wrap { max-width: 860px; margin: 0 auto; padding: 32px 24px 64px; }
.brand {
  font-size: 11px;
  font-weight: 500;
  letter-spacing: 1.5px;
  text-transform: uppercase;
  color: var(--mute);
  text-align: center;
  margin-bottom: 8px;
}
h1 {
  font-size: 28px;
  font-weight: 700;
  margin: 0 0 6px;
  text-align: center;
  color: var(--ink);
}
.subtitle {
  text-align: center;
  color: var(--slate);
  margin-bottom: 28px;
  font-size: 14px;
}
.meta-card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 16px 20px;
  margin-bottom: 20px;
  font-size: 13px;
}
.meta-row { display: flex; gap: 16px; margin: 4px 0; }
.meta-label {
  font-weight: 600;
  color: var(--slate);
  min-width: 110px;
}
.meta-value { color: var(--ink); }
.summary {
  display: flex;
  gap: 12px;
  margin-bottom: 24px;
}
.stat {
  flex: 1;
  padding: 14px 16px;
  border-radius: 12px;
  text-align: center;
}
.stat.supported { background: var(--supported-bg); color: var(--supported-fg); }
.stat.contradicted { background: var(--contradicted-bg); color: var(--contradicted-fg); }
.stat.insufficient_evidence { background: var(--insufficient-bg); color: var(--insufficient-fg); }
.stat .n {
  font-size: 24px;
  font-weight: 700;
  display: block;
  line-height: 1.1;
}
.stat .label {
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  font-weight: 600;
  margin-top: 4px;
  display: block;
}
.finding {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 14px;
  padding: 22px 24px;
  margin-bottom: 18px;
  page-break-inside: avoid;
}
.finding-head {
  display: flex;
  align-items: flex-start;
  gap: 14px;
  margin-bottom: 14px;
}
.fid {
  flex-shrink: 0;
  background: var(--tile);
  color: var(--slate);
  font-size: 11px;
  font-weight: 600;
  padding: 2px 10px;
  border-radius: 999px;
  min-width: 44px;
  text-align: center;
  line-height: 1.8;
}
.finding-body { flex: 1; }
.claim-text {
  font-size: 15px;
  color: var(--ink);
  line-height: 1.45;
  margin-bottom: 6px;
}
.limitation-line {
  font-size: 12px;
  color: var(--mute);
  font-style: italic;
  margin-top: 4px;
}
.badge {
  display: inline-block;
  font-size: 12px;
  font-weight: 600;
  padding: 3px 10px;
  border-radius: 8px;
  flex-shrink: 0;
  white-space: nowrap;
}
.badge.supported { background: var(--supported-bg); color: var(--supported-fg); }
.badge.contradicted { background: var(--contradicted-bg); color: var(--contradicted-fg); }
.badge.insufficient_evidence { background: var(--insufficient-bg); color: var(--insufficient-fg); }
.needs-review {
  display: inline-block;
  font-size: 11px;
  font-weight: 600;
  padding: 2px 8px;
  border-radius: 6px;
  background: var(--insufficient-bg);
  color: var(--insufficient-fg);
  margin-left: 6px;
}
.contradiction {
  display: flex;
  align-items: flex-start;
  gap: 14px;
  background: var(--tile);
  border-radius: 10px;
  padding: 14px 16px;
  margin-bottom: 12px;
}
.contradiction .side { flex: 1; min-width: 0; }
.contradiction .side .lbl {
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  font-weight: 600;
  color: var(--mute);
  margin-bottom: 4px;
}
.contradiction .side.report .val {
  color: var(--contradicted-fg);
  font-size: 14px;
  line-height: 1.4;
}
.contradiction .side.data .val {
  color: var(--supported-fg);
  font-size: 14px;
  font-weight: 700;
  line-height: 1.4;
}
.contradiction .arrow { color: var(--mute); padding-top: 18px; }
.impact {
  margin-top: 12px;
  padding: 14px 16px;
  border-radius: 10px;
  border-left: 4px solid var(--mute);
  background: var(--tile);
}
.impact.verdict-supported { background: var(--supported-bg); border-left-color: var(--supported-fg); }
.impact.verdict-contradicted { background: var(--contradicted-bg); border-left-color: var(--contradicted-fg); }
.impact.verdict-insufficient_evidence { background: var(--insufficient-bg); border-left-color: var(--insufficient-fg); }
.impact .lbl {
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  font-weight: 700;
  color: var(--slate);
  margin-bottom: 8px;
}
.impact-row {
  display: flex;
  gap: 10px;
  margin-top: 8px;
  font-size: 13.5px;
  color: var(--ink);
  line-height: 1.55;
}
.impact-row:first-of-type { margin-top: 0; }
.impact-row .sym {
  flex-shrink: 0;
  font-weight: 700;
  width: 16px;
  text-align: center;
}
.impact.verdict-supported .sym { color: var(--supported-fg); }
.impact.verdict-contradicted .sym { color: var(--contradicted-fg); }
.impact.verdict-insufficient_evidence .sym { color: var(--insufficient-fg); }
.impact-row .k { font-weight: 700; margin-right: 4px; }
.caveat {
  margin-top: 12px;
  padding: 10px 14px;
  border-radius: 8px;
  background: var(--tile);
  font-size: 13px;
  color: var(--slate);
}
.caveat .lbl {
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  font-weight: 700;
  color: var(--mute);
  margin-bottom: 4px;
}
.alternatives {
  margin-top: 12px;
  padding: 12px 16px;
  border-left: 3px solid var(--mute);
  border-radius: 6px;
  background: #F0F4F8;
  font-size: 13px;
}
.alternatives .lbl {
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  font-weight: 700;
  color: var(--slate);
  margin-bottom: 6px;
}
.alternatives .row { margin-top: 6px; color: var(--ink); }
.sources {
  margin-top: 12px;
  padding: 12px 14px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  font-size: 12.5px;
  color: var(--slate);
}
.sources .lbl {
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  font-weight: 700;
  color: var(--mute);
  margin-bottom: 6px;
}
.sources ul { margin: 0; padding-left: 18px; }
.sources li { margin: 2px 0; line-height: 1.5; }
.reviewer {
  margin-top: 10px;
  padding: 10px 14px;
  border-radius: 8px;
  background: var(--supported-bg);
  color: var(--supported-fg);
  font-size: 13px;
}
.reviewer.override { background: var(--contradicted-bg); color: var(--contradicted-fg); }
.reviewer .k { font-weight: 700; margin-right: 4px; }
.footer {
  margin-top: 36px;
  text-align: center;
  font-size: 11px;
  color: var(--mute);
}
@media print {
  body { background: var(--surface); }
  .top-bar { display: none; }
  .finding { border-color: #ddd; break-inside: avoid; }
}
"""


def build_html_report(audit: dict, download_name: str = "ClearAnswer audit") -> str:
    """Return the full HTML page for an audit dict."""
    producer = audit.get("producer") or {}
    data = audit.get("data") or {}
    releases = data.get("releases") or []
    release_name = (releases[0].get("name") if releases else "") or "unknown"
    file_count = len(releases[0].get("files", [])) if releases else 0
    findings = audit.get("findings") or []

    counts = {"supported": 0, "contradicted": 0, "insufficient_evidence": 0}
    for f in findings:
        v = f.get("claim_verdict")
        if v in counts:
            counts[v] += 1

    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")

    findings_html = "\n".join(_finding_html(f) for f in findings)

    return _PAGE_TEMPLATE.format(
        css=_CSS,
        title=html.escape(download_name),
        team=html.escape(producer.get("team", "")),
        product=html.escape(producer.get("product", "")),
        track=html.escape(producer.get("track", "")),
        dataset=html.escape(data.get("dataset", "")),
        release=html.escape(release_name),
        file_count=file_count,
        question=html.escape(audit.get("question", "")),
        now=now,
        n_supported=counts["supported"],
        n_contradicted=counts["contradicted"],
        n_insufficient=counts["insufficient_evidence"],
        n_total=len(findings),
        findings=findings_html,
    )


_PAGE_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title>
<style>{css}</style>
</head>
<body>
<div class="top-bar"></div>
<div class="wrap">
  <div class="brand">ClearAnswer / Research Claim Auditor</div>
  <h1>Audit report</h1>
  <p class="subtitle">{question}</p>

  <div class="meta-card">
    <div class="meta-row"><div class="meta-label">Team</div><div class="meta-value">{team}</div></div>
    <div class="meta-row"><div class="meta-label">Product</div><div class="meta-value">{product} ({track})</div></div>
    <div class="meta-row"><div class="meta-label">Dataset</div><div class="meta-value">{dataset}</div></div>
    <div class="meta-row"><div class="meta-label">Release</div><div class="meta-value">{release} ({file_count} files, SHA-256 verified)</div></div>
    <div class="meta-row"><div class="meta-label">Generated</div><div class="meta-value">{now}</div></div>
    <div class="meta-row"><div class="meta-label">Findings</div><div class="meta-value">{n_total} claim(s) checked</div></div>
  </div>

  <div class="summary">
    <div class="stat supported"><span class="n">{n_supported}</span><span class="label">Supported</span></div>
    <div class="stat contradicted"><span class="n">{n_contradicted}</span><span class="label">Contradicted</span></div>
    <div class="stat insufficient_evidence"><span class="n">{n_insufficient}</span><span class="label">Insufficient</span></div>
  </div>

  {findings}

  <p class="footer">Generated by ClearAnswer. Shared format v0.2. No AI-generated numbers: every verdict is backed by a deterministic pandas computation over the frozen TCGA-BRCA release above.</p>
</div>
</body>
</html>
"""


# ---------------------------------------------------------- finding helpers


def _finding_html(f: dict) -> str:
    verdict = f.get("claim_verdict", "")
    badge_text = {
        "supported": "Supported",
        "contradicted": "Contradicted",
        "insufficient_evidence": "Insufficient evidence",
    }.get(verdict, verdict)
    needs_review = f.get("needs_human_review") and not f.get("reviewer_decision")

    head = (
        f'<div class="finding-head">'
        f'<div class="fid">{html.escape(f.get("id", ""))}</div>'
        f'<div class="finding-body">'
        f'<div class="claim-text">{html.escape(f.get("claim_text", ""))}</div>'
    )
    if f.get("limitation") and verdict != "insufficient_evidence":
        # One-liner preview that mirrors the live UI card; the full limitation
        # lives in its own caveat block below.
        head += f'<div class="limitation-line">{html.escape(_short(f["limitation"], 180))}</div>'
    head += "</div>"
    head += f'<div><span class="badge {verdict}">{html.escape(badge_text)}</span>'
    if needs_review:
        head += '<span class="needs-review">Needs review</span>'
    head += "</div>"
    head += "</div>"

    parts = [head]

    if verdict == "contradicted" and f.get("correct_value"):
        parts.append(
            '<div class="contradiction">'
            '<div class="side report">'
            '<div class="lbl">Report claimed</div>'
            f'<div class="val">{html.escape(f.get("claim_text", ""))}</div>'
            "</div>"
            '<div class="arrow">&rarr;</div>'
            '<div class="side data">'
            '<div class="lbl">Data shows</div>'
            f'<div class="val">{html.escape(f["correct_value"])}</div>'
            "</div>"
            "</div>"
        )

    impact_html = _impact_html(f, verdict)
    if impact_html:
        parts.append(impact_html)

    if f.get("limitation"):
        lbl = "What was missing" if verdict == "insufficient_evidence" else "Caveat"
        parts.append(
            f'<div class="caveat"><div class="lbl">{lbl}</div>'
            f'{html.escape(f["limitation"])}</div>'
        )

    alts = f.get("alternatives")
    if isinstance(alts, list) and alts:
        rows = []
        for alt in alts:
            if not isinstance(alt, dict):
                continue
            bits = []
            if alt.get("column"):
                bits.append(f'<strong>{html.escape(alt["column"])}</strong>')
            if alt.get("value"):
                bits.append(html.escape(alt["value"]))
            if alt.get("note"):
                bits.append(f'<em>{html.escape(alt["note"])}</em>')
            if bits:
                rows.append(f'<div class="row">{" - ".join(bits)}</div>')
        if rows:
            parts.append(
                '<div class="alternatives">'
                '<div class="lbl">Same question, different column</div>'
                + "".join(rows)
                + "</div>"
            )

    evidence = f.get("evidence") or []
    if evidence:
        items = []
        for ev in evidence:
            label_bits = []
            if ev.get("file"):
                label_bits.append(html.escape(ev["file"]))
            elif ev.get("id"):
                label_bits.append(html.escape(str(ev["id"])))
            if ev.get("kind"):
                label_bits.append(f'({html.escape(ev["kind"])})')
            if ev.get("note"):
                label_bits.append(f'&rarr; {html.escape(ev["note"])}')
            if ev.get("release"):
                label_bits.append(f'release: {html.escape(ev["release"])}')
            items.append(f'<li>{" ".join(label_bits)}</li>')
        parts.append(
            '<div class="sources"><div class="lbl">Evidence</div>'
            f'<ul>{"".join(items)}</ul></div>'
        )

    if f.get("reviewer_decision"):
        decision = f["reviewer_decision"]
        tool_verdict = f.get("tool_verdict", "")
        reason = f.get("reviewer_reason", "")
        cls = "reviewer" + (" override" if decision == "override" else "")
        text = (
            f'<span class="k">Reviewer:</span> {html.escape(decision)}'
            + (f" (was <strong>{html.escape(tool_verdict)}</strong>)" if tool_verdict else "")
            + (f' - <em>{html.escape(reason)}</em>' if reason else "")
        )
        parts.append(f'<div class="{cls}">{text}</div>')

    return f'<div class="finding">{"".join(parts)}</div>'


def _impact_html(f: dict, verdict: str) -> str:
    rows = []
    if f.get("why_it_matters"):
        rows.append(
            '<div class="impact-row">'
            '<div class="sym">&#9679;</div>'
            f'<div><span class="k">Why it matters:</span> {html.escape(f["why_it_matters"])}</div>'
            "</div>"
        )
    if f.get("next_step"):
        rows.append(
            '<div class="impact-row">'
            '<div class="sym">&rarr;</div>'
            f'<div><span class="k">Next step:</span> {html.escape(f["next_step"])}</div>'
            "</div>"
        )
    if f.get("cannot_tell"):
        rows.append(
            '<div class="impact-row">'
            '<div class="sym">&#8856;</div>'
            f"<div><span class=\"k\">What we can't tell you:</span> {html.escape(f['cannot_tell'])}</div>"
            "</div>"
        )
    if not rows:
        return ""
    return (
        f'<div class="impact verdict-{verdict}">'
        f'<div class="lbl">Impact</div>'
        + "".join(rows)
        + "</div>"
    )


def _short(text: str, limit: int) -> str:
    text = " ".join((text or "").split())
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "..."


def write_html_report(audit: dict, path: str | Path, download_name: str = "ClearAnswer audit") -> Path:
    out = Path(path)
    out.write_text(build_html_report(audit, download_name), encoding="utf-8")
    return out


__all__ = ["build_html_report", "write_html_report"]
