# html-report Specification

## Purpose
Render a completed audit as a self-contained HTML page a reviewer can save, email, or print: inline CSS only — no JavaScript, no external fonts, no remote images, no API dependency. The design mirrors the live Flask UI (teal primary, warm cream background, verdict-tinted sections) so the frozen report feels like the same product. Every dynamic value is HTML-escaped; nothing in the page is generated or paraphrased beyond the audit dict itself.

## Requirements

### Requirement: Self-contained page structure
build_html_report SHALL return a complete HTML document for an audit dict using inline CSS only and no JavaScript — containing a header (brand line, title, the audit's question), a meta card (team, product/track, dataset, release name with file count, generation time, total findings), three summary tiles counting supported / contradicted / insufficient_evidence findings, one section per finding in order, and a footer stating that no number in the report is AI-generated.

#### Scenario: No external dependencies
- **WHEN** the rendered page is opened offline from disk
- **THEN** it displays fully styled with no network requests

### Requirement: Finding card content
Each finding SHALL render as a card with its id pill, claim text, and verdict badge. A "Needs review" tag SHALL appear only when needs_human_review is set and no reviewer_decision exists. Findings other than insufficient_evidence that carry a limitation SHALL show a one-line preview (whitespace-collapsed, truncated to 180 characters). Contradicted findings with a correct_value SHALL show a two-sided "Report claimed → Data shows" comparison block.

#### Scenario: Review tag cleared by decision
- **WHEN** a finding is flagged needs_human_review but carries reviewer_decision "accept"
- **THEN** its card omits the "Needs review" tag because the human already acted on it

### Requirement: Impact, caveat, alternatives, and evidence
Each finding card SHALL include, when present in the audit dict: an Impact section with rows for why_it_matters, next_step, and cannot_tell; a Caveat block (labeled "What was missing" for insufficient_evidence) carrying the full limitation; an alternatives block listing other columns that answer the same question with column, value, and note; and an Evidence list rendering each pointer's file-or-id, kind, note, and release.

#### Scenario: Alternative definitions shown
- **WHEN** a finding carries alternatives noting that PAM50 Luminal gives a different ER-positive number than IHC status
- **THEN** the card lists both under "Same question, different column"

### Requirement: Reviewer decision rendering
A finding carrying reviewer_decision SHALL render a decision line showing the decision, the preserved tool verdict in parentheses when present, and the reviewer reason in italics; overrides SHALL be visually distinguished from accepts.

#### Scenario: Override line
- **WHEN** a finding was overridden from contradicted to supported with a reason
- **THEN** its card shows "Reviewer: override (was contradicted) - <reason>" styled as an override

### Requirement: File writing helper
write_html_report SHALL write build_html_report's output as UTF-8 to the requested path and return the written Path so callers can persist a report without going through Flask.

#### Scenario: Write and reuse
- **WHEN** write_html_report is called with an audit dict and a path
- **THEN** the file contains the rendered page and the returned Path points at it
