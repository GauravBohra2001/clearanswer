# agent-trace Specification

## Purpose
Record every step an agent takes — plan, query, execute, interpret, reflect, extract, guard — into one ordered audit trail so a reviewer or judge can replay exactly how each verdict was reached. The trace is the system's proof that verification was done by deterministic tool calls rather than model memory: it serializes to JSON for the audit output and to Markdown for human review.

## Requirements

### Requirement: Structured step entries
The system SHALL record each agent step as a TraceEntry carrying the agent name, stage, optional input_data and output_data, a reasoning string, a list of tool calls, a duration in milliseconds, and a UTC ISO-8601 timestamp. A step is the atomic unit of agent work; one collector is shared across all agents in a run so every step lands in a single ordered trail.

#### Scenario: Step fields
- **WHEN** the verifier records a query step
- **THEN** the entry carries agent_name "verifier", stage "query", the tool calls made, and a UTC timestamp

### Requirement: Automatic timing via context manager
The system SHALL provide a start_step(agent_name, stage) context manager that sets the timestamp at entry and computes duration_ms (rounded to 3 decimals) from a high-resolution counter in a finally block, guaranteeing the entry is appended even if the step body raises. The yielded entry SHALL be mutable so callers assign input_data, output_data, reasoning, and tool_calls inside the block.

#### Scenario: Duration captured on exception
- **WHEN** code inside a start_step block raises
- **THEN** the entry is still appended with its duration measured up to the failure point

### Requirement: Manual step logging from agents
BaseAgent SHALL provide log_step(stage, ...) which builds a TraceEntry stamped with the agent's name and the current UTC time, appends it to the shared collector, and returns it. Agents without an injected collector SHALL create their own so trace recording never fails silently.

#### Scenario: Agent logs a step
- **WHEN** the extractor calls log_step("extract", reasoning=...)
- **THEN** a TraceEntry with agent_name "extractor" is appended to the run's shared collector

### Requirement: JSON serialization for audit output
The system SHALL serialize the collector to a list of plain dicts (one per entry, full field set) so it can be embedded under a private key in the audit output without further conversion.

#### Scenario: Trace embedded in audit
- **WHEN** to_dict is called after a full run
- **THEN** it returns one dict per step in execution order, each with agent_name, stage, input_data, output_data, reasoning, tool_calls, duration_ms, and timestamp

### Requirement: Human-readable Markdown rendering
The system SHALL render the trace as Markdown: a top-level "Agent trace" heading, then one numbered section per step showing agent/stage, When and Duration, and Reasoning, Input, Output (repr-truncated to 240 characters with an ellipsis), and each tool call's name and input. An empty collector SHALL render a placeholder rather than an empty document.

#### Scenario: Long values truncated
- **WHEN** a step's output_data repr exceeds 240 characters
- **THEN** the Markdown shows the first 239 characters plus an ellipsis

### Requirement: Shared LLM client
Every agent SHALL share a single Anthropic client obtained from a lazy singleton, which SHALL raise RuntimeError when no API key is configured or only a placeholder is present. The client SHALL pass through an optional ANTHROPIC_BASE_URL override so non-default providers can be targeted. No temperature parameter SHALL be sent with requests; determinism comes from the tool computations, not sampling settings.

#### Scenario: Missing API key
- **WHEN** an agent is constructed without ANTHROPIC_API_KEY set
- **THEN** client acquisition raises RuntimeError instead of silently proceeding

### Requirement: Transient-error retry
call_llm SHALL retry on transient failures — HTTP status in {408, 409, 429, 500, 502, 503, 504, 529} or error types whose names contain timeout, connection, apiconnection, ratelimit, or overload — for up to MAX_RETRIES (2) additional attempts with exponential backoff of 2^attempt seconds. Non-transient errors SHALL propagate immediately.

#### Scenario: Rate limit retried
- **WHEN** a call fails with status 429 on the first attempt
- **THEN** the agent sleeps 1 second and retries, up to two further attempts before re-raising

#### Scenario: Bad request not retried
- **WHEN** a call fails with a non-transient error (e.g. invalid model)
- **THEN** the exception propagates without retry or backoff
