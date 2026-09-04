# AgentICU — Multi-Agent Observability & Auto-Recovery

> **Source paper:** arXiv:2503.13657 (MAST Failure Taxonomy — NeurIPS 2025), arXiv:2604.10599 (Rethinking SE for Agentic AI — "accountability collapse")  
> **Build time:** ~6 weeks (shipped in 6 phases)  
> **Difficulty:** Hard (largest project)  
> **Signal to recruiters:** 🔥🔥🔥🔥🔥🔥 — Your signature piece. Proves you can do observability, distributed systems, and agent infrastructure. Directly referenced by Databricks as "the thing everyone needs but nobody's building."  
> **GPU required?** No  
> **Tests:** 97+ passing, 0 lint errors  
> **Package:** pip install agenticu (PyPI-ready, twine check passed)  

---

## One-Liner

An observability and self-healing system for multi-agent workflows that instruments agents to emit structured traces, classifies failures in real-time using the validated MAST taxonomy (14 failure modes, 41-86.7% failure rate), runs recovery playbooks automatically, and escalates to humans when recovery fails. It's the Datadog for AI agents.

---

## Why This Exists

The MAST Failure Taxonomy (NeurIPS 2025 spotlight) analyzed **1,600+ execution traces** across 7 popular multi-agent frameworks and found:

- **Multi-agent systems fail 41-86.7% of the time** in production
- **79% of all breakdowns** come from just 2 categories: specification ambiguity (44.2%) + coordination breakdowns (32.3%)
- **Agent handoffs fail silently** — no one knows the failure happened until something else breaks downstream

The Databricks engineer said it bluntly:
> *"One AI agent is a feature. Fifty agents is a distributed systems problem nobody's discussing. Agent handoffs fail silently. Data goes stale. Decisions become untraceable. This is the infrastructure layer everyone needs but nobody's building."*

Existing tools:
- **Arize Phoenix, LangFuse, Braintrust:** Agent observability (traces, logs, metrics) — but ZERO auto-recovery
- **LangGraph, CrewAI:** Frameworks that build agents — but no built-in failure diagnosis
- **MAST Taxonomy:** A published paper — nobody has operationalized it

AgentICU is the gap: **MAST-based real-time failure classification + automated recovery playbooks + human escalation.**

---

## Core Features

### 1. Agent Instrumentation SDK
- Drop-in decorators for LangChain, LangGraph, and CrewAI agents
- Automatically emits OpenTelemetry-compatible traces with:
  - `@trace` — every agent action
  - `@tool_call` — every tool invocation with input/output
  - `@handoff` — every agent-to-agent handoff with state snapshot
  - `@decision` — branching decisions with rationale
- Zero code changes to your agent — just add the decorator

*Example:*
```python
from agenticu import trace, tool_call, handoff

@trace(agent_id="research_agent")
@tool_call(return_snapshot=True)
def search_web(query: str) -> str:
    # Your existing code — nothing changes
    ...
```

### 2. MAST Real-Time Classifier
- Maps every failure event to one of 14 MAST failure modes:
  - **Specification:** 1.1 Disobey Task Spec, 1.2 Disobey Role Spec, 1.3 Step Repetition, 1.4 Loss of Conversation History, 1.5 Unaware of Termination
  - **Coordination:** 2.1 Conversation Reset, 2.2 Fail to Ask for Clarification, 2.3 Task Derailment, 2.4 Information Withholding, 2.5 Ignored Other Agent Input, 2.6 Reasoning-Action Mismatch
  - **Verification:** 3.1 Premature Termination, 3.2 No/Incomplete Verification, 3.3 Incorrect Verification
- Tags every trace with: `{failure_mode, category, status, timestamp, agent_id}`
- Real-time classification via pattern matching + embedding similarity to known failure signatures

### 3. Recovery Playbook Engine (14/14 implemented)
- All 14 MAST failure modes have structured recovery playbooks returning `RecoveryAction`:

| Failure Mode | Recovery Strategy |
|---|---|
| 1.1 Disobey Task Spec | Re-prompt with clarified spec + constraint validation |
| 1.2 Disobey Role Spec | Re-assert role boundary + inject constraint validation |
| 1.3 Step Repetition | Inject progress checkpoint, skip completed steps |
| 1.4 Loss of Conversation History | Replay context from last checkpoint |
| 1.5 Unaware of Termination | Signal termination again + completion guard |
| 2.1 Conversation Reset | Restore conversation state from pre-reset checkpoint |
| 2.2 Fail to Ask Clarification | Re-prompt with explicit clarification request |
| 2.3 Task Derailment | Re-anchor to task spec, trim extraneous actions |
| 2.4 Information Withholding | Force state sync — push held information to all agents |
| 2.5 Ignored Other Agent Input | Re-present ignored input, request re-evaluation |
| 2.6 Reasoning-Action Mismatch | Re-run decision step with explicit action verification |
| 3.1 Premature Termination | Restart agent from last completed span |
| 3.2 No/Incomplete Verification | Trigger adversarial verifybot re-check |
| 3.3 Incorrect Verification | Trigger adversarial re-check with VerifyBot pattern |

- **Inline recovery:** `@trace(classifier=..., store=...)` catches exceptions, classifies, runs playbook, and retries automatically
- Configurable: `max_retries=2` (PlaybookRunner), `escalate_after=2`
- Recovery success rate tracked per strategy per failure mode via Prometheus histograms

### 4. Self-Healing Controller
- **PlaybookRunner** executes playbooks with configurable retry, cooldown, and escalation
- **EscalationService** supports Slack webhooks, PagerDuty, and custom hooks for human-in-the-loop
- **MetricsTracker** records recovery success/fail per failure mode with Prometheus counters
- If a recovery fails after max retries, escalates to human with full trace context
- Inline recovery in `@trace` decorator handles exceptions transparently: classify → playbook → retry

### 5. Failure Dashboard (Grafana)
- **Failure heatmap:** Failure frequency by MAST category, agent ID, and time
- **Recovery rate:** Per-strategy success rate over time
- **Agent health:** Per-agent failure count, uptime, handoff success rate
- **Alert timeline:** When failures happened, how long recovery took, when humans were paged

### 6. Structured Trace Logging
- Every trace written to in-memory store (dev) or PostgreSQL (prod) with full event chain
- In-memory store has `max_traces` eviction guard to prevent unbounded growth
- Queryable: "show me all 'Information Withholding' failures from agent `research_agent` in the last 24 hours"
- FastAPI routes: query traces, list failures, trigger recovery, view Prometheus metrics
- Pre-built Grafana dashboard for failure heatmaps, recovery rates, agent health

### 7. CLI & Docker
- `agenticu server` — starts the FastAPI API server
- `agenticu migrate --dsn <postgres>` — applies PostgreSQL schema
- `agenticu check` — health check against running server
- `docker compose up` — starts app + PostgreSQL (auto-migrated) + Grafana with pre-loaded dashboard
- Multi-stage Dockerfile with non-root user

### 8. Security Hardening
- CORS locked to `http://localhost:3000` (configurable)
- Optional API key authentication via `Authorization: Bearer <key>` middleware
- `/health` and `/metrics` remain unauthenticated for monitoring

---

## Architecture

```
AgentICU
│
├── SDK Layer (instrumentation)
│   ├── decorators.py         # @trace, @tool_call, @handoff, @decision (+ inline recovery)
│   ├── context.py            # Automatic trace context propagation
│   └── __init__.py           # Public API: import agenticu
│
├── Collector Layer
│   ├── receiver.py           # OpenTelemetry-compatible trace exporter
│   ├── processor.py          # Event dedup, enrichment, validation
│   └── storage.py            # In-memory (dev) / PostgreSQL (prod) with max_traces eviction
│
├── Classification Layer (MAST)
│   ├── mast_taxonomy.py      # 14 failure mode definitions + regex matching rules
│   ├── classifier.py         # Two-tier: pattern match (fast) + embedding (deep)
│   └── signature_db.py       # Known failure signatures per mode
│
├── Forecasting Layer (PROMAS)
│   ├── transition_model.py   # Markov counting estimator P(failure | handoff)
│   ├── forecaster.py         # Real-time prediction at handoff points
│   └── outcome_tracker.py    # Background feedback loop: learns from new traces
│
├── Attribution Layer
│   └── causal_attributor.py  # Walk handoff chain to find root-cause agent
│
├── Recovery Layer
│   ├── playbook_registry.py  # 14 playbooks returning RecoveryAction(should_retry, instructions)
│   ├── playbook_runner.py    # Retry loop, cooldown, escalation on exhaust
│   ├── escalation.py         # Slack / PagerDuty / custom hooks
│   └── recovery_metrics.py   # Prometheus counters + per-mode success rate tracking
│
├── API Layer
│   ├── routes.py             # FastAPI — health, metrics, traces, failures, recovery
│   ├── config.py             # YAML config + env var overrides (AGENTICU__*)
│   └── cli.py                # CLI: server, migrate, check, tui
│
├── TUI (terminal ops console)
│   ├── client.py             # Async httpx client for all 11 API endpoints
│   ├── app.py                # Textual app: dashboard, traces, failures, forecast, attribution, recover
│   └── __main__.py           # python -m agenticu.tui entry
│
├── npm distribution
│   ├── package.json          # npm package "agenticu" (bin shim)
│   └── bin/agenticu.js       # Node shim: ensures pip install agenticu[tui], forwards args
│
├── Infrastructure
│   ├── Dockerfile            # Multi-stage, non-root agenticu user
│   ├── docker-compose.yml    # App + PostgreSQL + Grafana (local dev)
│   ├── schema.sql            # PostgreSQL schema (spans, failures, recovery_attempts)
│   └── infra/tofu/           # OpenTofu: AWS ECS Fargate + RDS + ALB + Grafana (prod)
│       ├── main.tf           # VPC data, ECR, RDS, ECS services, ALB, secrets, logs
│       ├── variables.tf      # region, image, DB size, api_key (sensitive)
│       ├── outputs.tf        # api_url, grafana_url, rds_endpoint, ecr repo
│       ├── versions.tf       # OpenTofu >= 1.6, S3 backend + native locking
│       └── README.md         # Deploy runbook (state bucket → push → apply → migrate)
│
├── Dashboard
│   ├── grafana_dashboard.json  # Pre-built Grafana dashboard JSON
│   └── alerts/               # PagerDuty / Slack alert templates
│
├── Community
│   ├── CONTRIBUTING.md
│   ├── CODE_OF_CONDUCT.md
│   ├── CHANGELOG.md
│   ├── LICENSE (MIT)
│   └── .github/
│       ├── workflows/ci.yml
│       ├── ISSUE_TEMPLATE/bug_report.md
│       ├── ISSUE_TEMPLATE/feature_request.md
│       └── pull_request_template.md
│
└── Tests (107 passing)
    ├── test_classifier.py    # MAST classification: patterns, signature DB
    ├── test_recovery.py      # Playbook registration, runner, metrics
    ├── test_playbooks.py     # All 14 playbooks return correct RecoveryActions
    ├── test_integration.py   # Full pipeline: trace → classify → recover
    ├── test_storage.py       # Store: CRUD, eviction, PostgreSQL pool path
    ├── test_escalation.py    # Escalation service: Slack, PagerDuty, custom hooks
    ├── test_config.py        # Config loader: defaults, env overrides, file loading
    ├── test_processor.py     # Trace processor: dedup, enrichment, clear
    ├── test_exporter.py      # OTel exporter: OK/error/failure span conversion
    ├── test_decorators.py    # SDK decorators: trace, tool_call, handoff, decision
    ├── test_context.py       # Context propagation: scope, nesting, concurrency
    ├── test_api.py           # API: health, metrics, traces, failures, recovery
    ├── test_forecaster.py    # Transition model, forecast, threshold
    ├── test_attribution.py   # Causal attribution chain, error detection
    └── test_tui_client.py    # TUI HTTP client: all endpoints, error mapping
```

---

## Tech Stack

| Component | Choice | Why |
|-----------|--------|-----|
| Framework | **FastAPI** | Async, fast, good observability support |
| Database | **In-memory** (dev) / **PostgreSQL** (prod) | asyncpg connection pool |
| SDK Pattern | **Python decorators** | Minimum friction for agent developers |
| Traces | **OpenTelemetry** | Industry standard, compatible with existing observability stacks |
| Classification | **Regex patterns** (fast) + **sentence-transformers** (deep) | Two-tier for latency |
| Recovery | **RecoveryAction** dataclass | Structured: should_retry + retry_delay + instructions |
| Dashboard | **Grafana** | Importable JSON dashboard |
| CLI | **argparse** (stdlib) | Zero dependencies |
| Container | **Docker + docker-compose** | Multi-stage, non-root |
| CI | **pytest + GitHub Actions** | 79 tests, ruff linting |
| Package | **setuptools + twine** | PyPI-ready wheel + sdist |

---

## Project Structure

```
agenticu/
├── README.md                            # Full docs: quickstart, features, CLI, Docker, API, MAST taxonomy
├── CHANGELOG.md                         # Unreleased changes
├── CONTRIBUTING.md                      # Development setup, PR process
├── CODE_OF_CONDUCT.md                   # Contributor Covenant
├── LICENSE (MIT)
├── pyproject.toml                       # Build config: setuptools, entry point, deps (+ tui extra)
├── package.json                         # npm package "agenticu" (bin shim → pip install)
├── bin/
│   └── agenticu.js                      # Node shim: ensures Python pkg, forwards args
├── MANIFEST.in                          # Includes: LICENSE, README, config.yaml, schema.sql, dashboards
├── config.yaml                          # Global config: storage, classifier, recovery, api
├── schema.sql                           # PostgreSQL: spans, failures, recovery_attempts (+ indexes)
├── Dockerfile                           # Multi-stage, non-root agenticu user
├── docker-compose.yml                   # App + PostgreSQL + Grafana (auto-migrated)
├── infra/tofu/                          # OpenTofu AWS prod stack (ECS + RDS + ALB)
│   ├── main.tf / variables.tf / outputs.tf / versions.tf
│   └── README.md                        # Deploy runbook
├── .github/
│   ├── workflows/ci.yml
│   └── ISSUE_TEMPLATE/
│       ├── bug_report.md
│       ├── feature_request.md
│       └── pull_request_template.md
├── src/
│   └── agenticu/
│       ├── __init__.py                  # Public API: trace, tool_call, handoff, decision, FailureMode
│       ├── cli.py                       # agenticu {server, migrate, check, tui}
│       ├── decorators.py                # @trace (inline recovery), @tool_call, @handoff, @decision
│       ├── context.py                   # Trace context propagation
│       ├── models.py                    # Span, RecoveryAction, RecoveryAttempt, ClassificationResult
│       ├── collector/
│       │   ├── receiver.py              # OTel SpanExporter → AgentICUSpan conversion
│       │   ├── processor.py             # Dedup, error enrichment
│       │   └── storage.py               # In-memory (max_traces) / PostgreSQL (asyncpg)
│       ├── classification/
│       │   ├── mast_taxonomy.py         # 14 modes: definitions, categories, regex patterns
│       │   ├── classifier.py            # Two-tier: pattern match (fast) / embedding (deep)
│       │   └── signature_db.py          # Default failure signatures per mode
│       ├── forecast/
│       │   ├── transition_model.py      # Markov transition learning
│       │   ├── forecaster.py            # Real-time failure prediction
│       │   └── outcome_tracker.py       # Auto-feedback loop (background)
│       ├── attribution/
│       │   ├── __init__.py
│       │   └── causal_attributor.py     # Trace failure back to root-cause agent
│       ├── recovery/
│       │   ├── playbook_registry.py     # @register + 14 playbooks → RecoveryAction
│       │   ├── playbook_runner.py       # Retry loop, cooldown, escalation
│       │   ├── escalation.py            # Slack, PagerDuty, custom hooks via httpx
│       │   └── recovery_metrics.py      # Prometheus per-mode counters
│       ├── api/
│       │   ├── routes.py                # FastAPI: health, metrics, traces, failures, recover
│       │   └── config.py                # YAML + env var (AGENTICU__*) config loader
│       ├── tui/
│       │   ├── client.py                # Async httpx client for all API endpoints
│       │   ├── app.py                   # Textual ops console (6 tabs)
│       │   └── __main__.py              # python -m agenticu.tui entry
│       └── dashboard/
│           ├── grafana_dashboard.json
│           └── alerts/
│               ├── slack_alert.json
│               └── pagerduty_alert.json
├── tests/
│   ├── test_api.py                      # 8 tests: health, metrics, traces, failures, recovery
│   ├── test_attribution.py              # 8 tests: causal attribution chain, error detection
│   ├── test_classifier.py               # 7 tests: taxonomy, patterns, signature DB
│   ├── test_config.py                   # 5 tests: defaults, env overrides, file loading
│   ├── test_context.py                  # 4 tests: context scope, nesting, concurrency
│   ├── test_decorators.py               # 9 tests: trace, tool_call, handoff, decision, errors
│   ├── test_escalation.py               # 4 tests: payload, hooks, Slack webhook
│   ├── test_exporter.py                 # 5 tests: OK/error/failure spans, dedup
│   ├── test_forecaster.py               # 9 tests: transition model, forecast, threshold
│   ├── test_integration.py              # 4 tests: full pipeline, failure query
│   ├── test_playbooks.py                # 14 tests: each playbook returns correct RecoveryAction
│   ├── test_processor.py                # 4 tests: dedup, enrichment, clear
│   ├── test_recovery.py                 # 5 tests: registry, runner, metrics
│   ├── test_storage.py                  # 7 tests: CRUD, eviction, pool path, failures
│   └── test_tui_client.py               # 10 tests: TUI HTTP client, error mapping
└── examples/
    ├── research_agent.py                # LangGraph research agent with AgentICU decorators
    ├── failure_injection.py             # Demo: auto-recovery from tool timeouts and API 500s
    └── failure_scenarios.yaml           # Test data: known failure traces from MAST paper
```

---

## Implementation (Completed in 6 Phases)

### Phase 1: RecoveryAction + Inline Recovery
- Added `RecoveryAction` dataclass (`should_retry`, `retry_delay`, `instructions`)
- Converted all 14 playbooks from bare `bool` to `RecoveryAction` with meaningful instructions
- Wired inline recovery into `@trace(classifier=..., store=...)` — catch → classify → playbook → retry
- Updated `PlaybookRunner` to handle `RecoveryAction` return type
- Demo: `examples/failure_injection.py` shows auto-recovery from tool timeouts and API 500s

### Phase 2: Infrastructure
- `schema.sql` — PostgreSQL tables: spans, failures, recovery_attempts with proper indexes
- `Dockerfile` — multi-stage build (python:3.12-slim, non-root agenticu user)
- `docker-compose.yml` — app + PostgreSQL (auto-migrated) + Grafana (anonymous auth, pre-loaded dashboard)
- `src/agenticu/cli.py` — `agenticu {server, migrate, check}` using stdlib argparse
- Added CLI entry point to `pyproject.toml`

### Phase 3: Security Hardening
- **Memory leak fix** — in-memory `TraceStore` now has `max_traces=1000` with oldest-trace eviction
- **CORS lockdown** — default changed from `["*"]` to `["http://localhost:3000"]`, configurable
- **API key auth** — optional `Authorization: Bearer <key>` middleware (skips `/health` and `/metrics`)

### Phase 4: Community Files
- `CONTRIBUTING.md` — dev setup, test/lint commands, PR process
- `CODE_OF_CONDUCT.md` — Contributor Covenant
- `CHANGELOG.md` — track changes per release
- GitHub issue/PR templates — bug_report, feature_request, PR checklist
- `MANIFEST.in` — includes schema.sql for `agenticu migrate`

### Phase 5: Test Gaps (79 tests, up from 54)
- 25 new tests across 5 files covering storage, escalation, config, processor, exporter
- Fixed 4 bugs discovered by new tests:
  - Config env var `_set_from_env` didn't nest under `agenticu` key
  - `TraceProcessor._seen_span_ids` was class-level (shared across instances)
  - OTel exporter called async storage methods from sync context — added `_insert_span_sync`
  - OTel exporter didn't extract `failure_mode` from span attributes

### Phase 6: Launch Readiness
- Fixed GitHub URLs (`yourname` → `agenticu`)
- Revamped README with MAST paper reference, full feature table, CLI/Docker docs, architecture diagram
- `twine check --strict` passed on both wheel and sdist
- Fresh-venv install test: imports, CLI, decorators, all 14 playbooks, API server — all green

### Phase 7: Upgrade — From Reactive Classification to Proactive, Causal Diagnosis

Implemented the three capabilities from `01-remodel-agenticu.md` that no
observability platform does today:

**1. PROMAS-style Forecaster** (`src/agenticu/forecast/`)
- `TransitionModel` learns `P(failure | source_agent → target_agent)` from
  collected traces via a counting estimator over the handoff graph
- `Forecaster.forecast_at_handoff()` predicts failure probability *ahead of
  time* and emits a `ForecastResult` with most-likely MAST mode + confidence
- Threshold-based early-intervention signal ready for alerting

**2. Causal Attribution Layer** (`src/agenticu/attribution/`)
- `CausalAttributor.attribute()` walks the trace (parent chain, falling back to
  chronological order) and finds the agent whose action *introduced* the error
- Returns `AttributionResult` with `root_agent_id`, confidence, and the full
  `attribution_chain` — so recovery targets the right agent, not the one holding
  the bag
- Detects decision-rationale errors and degraded handoff state snapshots

**3. Root-Cause-Targeted Recovery**
- `RecoveryAttempt` now carries `root_agent_id`; `PlaybookRunner.run()` accepts
  and routes recovery to the root-cause agent
- `EscalationService` payload includes `root_agent_id`
- Inline `@trace(classifier=..., store=..., attributor=...)` now: classify →
  attribute → playbook → retry

**Supporting fixes:**
- `Receiver` now uses the propagated `agenticu.trace_id` attribute (correctly
  nested across handoffs) instead of the raw OTel context trace_id, and converts
  OTel nanosecond timestamps to `datetime` (fixes a `query_traces` sort crash)
- `trace` decorator sets the OTel `agenticu.agent_id` attribute from `span_ctx`
  (the decorated agent) rather than the outer context

**New tests:** `test_forecaster.py` (9), `test_attribution.py` (8), plus a
full forecast+attribution integration test. **Total: 97 passing.**

**Demo:** `examples/forecast_attribution_demo.py` — forecasts a failure before a
handoff, runs a 3-agent pipeline where `agent_b` corrupts state, and correctly
attributes the root cause to `agent_b` (not `agent_c` which surfaced it).

### Phase 8: Outcome Tracking + Real Playbooks + Documentation Audit

**Outcome Tracking Feedback Loop**
- `OutcomeTracker` (`src/agenticu/forecast/outcome_tracker.py`): background polling
  loop that auto-calls `TransitionModel.learn()` when enough new traces accumulate
- Auto-classifies new failures and feeds them into `SignatureDB` as training examples
  (confidence threshold ≥ 0.8)
- Wired into FastAPI lifespan — starts with server, stops on shutdown
- `/api/v1/outcome-tracker` status endpoint

**All 14 Playbooks Converted From Stubs to Real**
- Every playbook now queries the trace store for actual context: fetches `task_spec`,
  prior outputs, agent IDs, decision rationales, and peer agent results
- Returns structured `RecoveryAction(payload=...)` with the retrieved data
- Complete list with what each playbook retrieves:
  - `disobey_task_spec` / `disobey_role_spec` — task_spec + active agents
  - `step_repetition` — duplicate output detection
  - `loss_of_history` — actual prior span outputs
  - `unaware_of_termination` — task_spec + last output completion check
  - `conversation_reset` — prior conversation content
  - `task_derailment` — task_spec + prior output for re-anchoring
  - `fail_to_ask_clarification` — task_spec + last input
  - `information_withholding` — all agent outputs per agent
  - `ignored_other_agent_input` — most recent peer agent output
  - `reasoning_action_mismatch` — decision rationale vs actual action
  - `premature_termination` — completed step count + task_spec
  - `no_incomplete_verification` — quality checks on last output
  - `incorrect_verification` — contradiction detection in last output

**Inline Recovery Persistence**
- Both sync and async inline recovery paths now create and store `RecoveryAttempt`
  records with `root_agent_id`, so inline recovery is visible in metrics

**Interception Demo**
- `examples/forecast_interception_demo.py` — shows real-time failure prevention:
  forecast predicts 75% P(failure), interceptor sanitizes state before the handoff,
  downstream agent succeeds instead of crashing

**Documentation Fixes**
- Architecture tree and project structure updated to include `forecast/`,
  `attribution/`, and their test files
- Test count corrected to 97 throughout
- `severity` → `status` in tag specification
- `auto_recover=True` removed (no such parameter)

### Phase 9: TUI Ops Console + npm Distribution + OpenTofu AWS

**Textual TUI (`agenticu tui`)**
- `src/agenticu/tui/client.py` — async httpx client covering all 11 API endpoints,
  config-aware (host/port/api-key from `config.yaml` + env), clean `TUIError` mapping
- `src/agenticu/tui/app.py` — 6-tab ops console: Dashboard (auto-refresh health,
  recovery rate, tracker status), Traces (+ per-handoff forecasts), Failures,
  Forecast, Attribution, Recover (mode-validated trigger)
- `agenticu tui [--server URL] [--api-key KEY]` subcommand; `python -m agenticu.tui`
- Ships via new `tui` extra: `pip install "agenticu[tui]"`
- Server side: `Forecaster` + `CausalAttributor` now wired into `agenticu server`
  so `/forecast*` and `/attribution` are live (previously 404)

**npm distribution**
- `package.json` (`agenticu`, bin → `bin/agenticu.js`): `npm install -g agenticu`
  puts `agenticu` on PATH; the Node shim checks Python ≥ 3.11, pip-installs
  `agenticu[tui]` on first run if missing, and forwards all args + exit codes
- Verified: `npm pack --dry-run` + end-to-end shim forwarding

**OpenTofu AWS prod stack (`infra/tofu/`)**
- ECS Fargate (API + Grafana) + RDS Postgres 17 + single ALB (`:80` API, `:8080` Grafana)
- ECR repo, Secrets Manager (DB password generated, API key), CloudWatch logs,
  S3 backend with native state locking, default-VPC (no NAT cost)
- `tofu init -backend=false` + `tofu validate` pass; deploy runbook in
  `infra/tofu/README.md` (state bucket → push → apply → migrate → TUI at ALB URL)

**New tests:** `test_tui_client.py` (10, respx-mocked) + headless Textual Pilot
smoke test. **Total: 107 passing.**

### What's Next (After Launch)
- Publish to PyPI: `python -m build && twine check --strict dist/* && twine upload dist/*` (unblocks `npm install -g agenticu` end-to-end)
- Publish to npmjs: `npm publish --access public` (needs npm account/token)
- AWS `tofu apply` (needs credentials; validates clean, plan is yours to run)
- Real-time alerting: PagerDuty/Slack integration for critical failure modes
- Failure prediction: ML model trained on MAST traces that predicts failure BEFORE it happens
- Multi-framework: LangChain, CrewAI, AutoGen, custom frameworks
- Agent benchmarking: run known failure scenarios → measure which agents handle them best

---

## Interview Narrative

> "The MAST taxonomy paper analyzed 1,600+ multi-agent execution traces and found agents fail 41-86.7% of the time in production — and 79% of failures come from just 2 causes. But nobody operationalized this knowledge. I built AgentICU: a drop-in observability SDK that instruments agents, classifies failures in real-time using the MAST taxonomy, runs 14 automated recovery playbooks, and escalates to humans when recovery fails. The entire system ships as a pip-installable package with CLI, Docker orchestration, a FastAPI API server, Prometheus metrics, Grafana dashboards, a Textual terminal ops console, npm + PyPI distribution, OpenTofu AWS infrastructure, and 107 passing tests. On top of that, AgentICU predicts failures *before* they complete using a learned Markov transition model (PROMAS-style), and when one does happen it traces the failure back through the handoff chain to the agent that actually caused it — so recovery targets the right agent. No observability platform does either of these, let alone both."

---

## Recruiter Signal

| What it proves | Why it matters |
|----------------|----------------|
| **Observability expertise** | The #1 missing skill in AI engineers — you stand out |
| **Distributed systems thinking** | Applied to the agent layer, not just microservices |
| **Research implementation** | Read a NeurIPS 2025 paper, built the tool it described |
| **Production engineering** | SDK, dashboard, alerts, escalation — real ops thinking |
| **Cybersecurity lens** | Monitoring + failure analysis = your blue-team background applied to AI |

---

## Extension Ideas (If Time Permits)

- **Real-time alerting:** PagerDuty/Slack integration for critical failure modes
- **Failure prediction:** ML model trained on MAST traces that predicts failure BEFORE it happens
- **Multi-framework:** LangChain, CrewAI, AutoGen, custom frameworks
- **Streaming traces:** Live failure dashboard with WebSocket updates
- **Agent benchmarking:** Run known failure scenarios → measure which agents handle them best

---

## Competitive Check

| Tool | Traces? | MAST Taxonomy? | Auto-Recovery? | CLI/Docker? | Verdict |
|------|---------|----------------|----------------|-------------|---------|
| Arize Phoenix | ✅ | ❌ | ❌ | ❌ | Observability only |
| LangFuse | ✅ | ❌ | ❌ | ❌ | Observability only |
| Braintrust | ✅ | ❌ | ❌ | ❌ | Evaluation only |
| MAST paper (GitHub) | ❌ | ✅ (taxonomy) | ❌ | ❌ | Research artifact |
| **AgentICU** | ✅ | ✅ (14 modes, real-time) | ✅ (14 playbooks) | ✅ | **Only end-to-end solution** |

---

## Sources

- arXiv:2503.13657 — "Why Do Multi-Agent LLM Systems Fail?" (MAST Failure Taxonomy, NeurIPS 2025) — primary source for taxonomy + failure rates
- arXiv:2604.10599 — "Rethinking Software Engineering for Agentic AI Systems" — accountability collapse framework
- Databricks AI Engineer World Fair — Sandipan Bhaumik on multi-agent orchestration anti-patterns
- Arize Phoenix, LangFuse, Braintrust — reference for existing observability patterns (gap = no MAST, no recovery)
