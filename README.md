# ClearAnswer - Research Claim Auditor

**Track:** Evidence Navigator (Track 2)
**Team:** clearanswer (Gaurav Bohra)
**Hackathon:** OncoSys Cancer AI Lab, Northeastern University, Nov 2026

## What it does

Upload a research report. An AI agent extracts factual claims, verifies each against the frozen TCGA-BRCA dataset, and builds an audit queue: **supported**, **contradicted**, or **insufficient evidence** - each with the calculation and source evidence behind it. A reviewer confirms each verdict. Export `audit.json` in the shared format for the organizers' checker.

**User:** A reviewer handed a report and asked "can we trust this?"

**Workflow:** Upload report → AI extracts claims → deterministic verification against data → review verdicts → export `audit.json`.

## How it works

ClearAnswer uses an LLM (Claude) to extract claims from natural language, then verifies each claim deterministically: the agent plans a pandas query, executes it against the real TCGA-BRCA files, and the math decides the verdict. The LLM never decides the verdict - it only extracts and plans.

Architecture follows Anthropic's "Building Effective Agents" Orchestrator-Workers pattern.

## Setup

```bash
git clone https://github.com/GauravBohra2001/clearanswer.git
cd clearanswer
pip install -r requirements.txt
git clone https://github.com/disleveK/oncosys-hackathon-challenge.git
python oncosys-hackathon-challenge/data/tcga-brca/fetch.py
cp .env.example .env                     # add your ANTHROPIC_API_KEY
PORT=5050 python app.py                  # open http://localhost:5050
```

`.env` must contain:

```
ANTHROPIC_API_KEY=your-key-here
```

## Practice envelope

Unseal the practice envelope to get the fresh TCGA-BRCA release files:

```bash
python oncosys-hackathon-challenge/envelopes/unseal.py practice orange meadow pilot lantern
```

The practice envelope ships only the `release/` folder plus a `README.txt`.
It does NOT include a `claim_auditor_report.md`. For the report, upload the
practice brief that lives in the challenge repo:

```
oncosys-hackathon-challenge/products/research-claim-auditor/practice_brief.md
```

On Saturday the judging envelope DOES ship a `claim_auditor_report.md`
alongside the release. The flow then is:

```bash
python oncosys-hackathon-challenge/envelopes/unseal.py <E??> <four-word code>
# then upload envelopes/opened/E??/claim_auditor_report.md in the UI
```

## Export

After the audit completes, click **Export audit.json**. The file passes `validate.py` from the challenge repo.

## Third-party code

- anthropic (MIT) - Claude API SDK
- pandas (BSD-3-Clause) - data analysis
- Flask (BSD-3-Clause) - web server
- jsonschema (MIT) - shared-format validation
- cryptography (Apache-2.0) - opens sealed envelopes

## Demo video

[link placeholder]
