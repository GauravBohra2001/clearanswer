# AGENTS.md — ClearAnswer working conventions

## Project overview

ClearAnswer is a Research Claim Auditor (OncoSys hackathon, Track 2 "Evidence Navigator"): a Flask web demo (`app.py`) and a CLI (`run.py`) that run an Anthropic-based agent pipeline (extract one claim per sentence → verify each against deterministic pandas queries) on a frozen TCGA-BRCA release directory. Output is `audit.json` in the shared findings format v0.2, plus an optional standalone HTML report. The CLI is the only script a judge/user runs for a judged audit; the web app is a demo wrapper around the same pipeline (submit → poll status → export).

## Python conventions

- Windows repo. Use the project venv for every command: `venv/Scripts/python.exe`.
- Entry points: `run.py` (CLI — the only script a judge runs) and `app.py` (Flask demo, default port **5050**, override with `PORT`). Both share `config.py`, which reads `.env` at import time.
- Layout: `agents/` (orchestrator + base agent with LLM retry/backoff), `core/` (data model, loader, trace collector, evidence, guard, semantic layer, logging setup), `tools/` (deterministic query tools), `output.py` (audit.json writer + validator), `html_report.py`.
- Tests: pytest-style suite in `core/tests/` (has `__init__.py`) plus a script-style root test. Run both:
  - `venv/Scripts/python.exe -m pytest core/tests/`
  - `venv/Scripts/python.exe test_foundation.py`
  - `pytest` is not in `requirements.txt` but is installed in the venv; install it there if missing.
  - `test_foundation.py` and `core/tests/test_data_model.py` need the local TCGA-BRCA checkout at `oncosys-hackathon-challenge/data/tcga-brca/` (gitignored, never committed). `test_data_model.py` honors a `TCGA_DATA_DIR` override.
- Keep changes minimal and scoped to the task; do not restructure unrelated code.
- Never commit `.env`, `logs/`, or generated outputs — all gitignored. Note `.gitignore` also ignores loose `*.json` (so audit.json never lands in git) and the local-only `oncosys-hackathon-challenge/` checkout.

## OpenSpec workflow (the core convention)

Every behavior change, however small, is tracked through the spec-driven lifecycle under `openspec/` (`config.yaml`: `schema: spec-driven`). Current capability specs live in `openspec/specs/<capability>/spec.md` (12 capabilities); active changes in `openspec/changes/<kebab-name>/`, completed ones in `openspec/changes/archive/`.

A change directory contains, in planning order:
- `proposal.md` — Why / What Changes / Capabilities / Impact
- `specs/<capability>/spec.md` — the **delta** against the main spec (ADDED/MODIFIED requirements with WHEN/THEN scenarios), not a copy of it
- `design.md` — how; `tasks.md` — checkboxed implementation steps
- (plus a `.openspec.yaml` metadata file: schema + created date)

1. **Propose first** — `/openspec-propose "<description>"` creates the change directory and planning artifacts. Planning only: no code is written in this step.
2. **Implement** — `/openspec-apply-change <name>`: work through `tasks.md` top to bottom; mark each checkbox `- [x]` only after the task is implemented **and** verified; rerun `openspec instructions apply --change <name> --json` after every mark and confirm progress changed.
3. **Archive when done** — `/openspec-archive-change` moves the change to `changes/archive/` and syncs its deltas into `openspec/specs/`.

The spec delta in a change is authoritative for what the code must do. If implementation reveals a design issue, update the artifacts (`/openspec-update-change`) rather than silently diverging from the spec.

## Version control rules

- Commit small and frequently: each logical step (an artifact written, a task completed, a fix) gets its own commit.
- Every commit message MUST reference the OpenSpec change or capability it implements or amends, e.g. `add-error-logging: add setup_logging module` or `audit-output: fix findings schema validation`. Commits not tied to any change (pure docs/chore) say so explicitly: `chore: ...`.
  - History note: existing commits are short lowercase descriptions or carry a `type:` prefix (e.g. feat/fix/docs/ui/test/demo/style/web/export); none reference an OpenSpec change yet — new commits follow the rule above.
- Never bundle unrelated working-tree changes into a spec-referenced commit; never commit secrets or gitignored artifacts.
- Branch model: work happens on feature branches, PRs target `main` (e.g. current branch `said/local`, remote `origin/main`).

## Quick reference

| What | Where / command |
| --- | --- |
| Plan a change | `/openspec-propose "<description>"` |
| Implement tasks | `/openspec-apply-change <name>` |
| Archive + sync specs | `/openspec-archive-change` |
| Other skills | `/openspec-explore`, `/openspec-update-change`, `/openspec-sync-specs` |
| List changes | `openspec list --json` |
| Change status | `openspec status --change <name> --json` |
| Apply progress | `openspec instructions apply --change <name> --json` |
| Validate a change | `openspec validate <name>` |
| Capability specs | `openspec/specs/<capability>/spec.md` (12 capabilities) |
| Active / archived changes | `openspec/changes/<name>/` · `openspec/changes/archive/` |
| Run tests | `venv/Scripts/python.exe -m pytest core/tests/` + `venv/Scripts/python.exe test_foundation.py` |
| CLI audit | `venv/Scripts/python.exe run.py <data_dir> <report.md> [--output audit.json] [--verbose]` |
| Web demo | `venv/Scripts/python.exe app.py` (port 5050, override with `PORT`) |
