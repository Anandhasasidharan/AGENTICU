# AgentICU — Multi-Agent Observability & Auto-Recovery

[![Tests](https://github.com/agenticu/agenticu/actions/workflows/ci.yml/badge.svg)](https://github.com/agenticu/agenticu/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/agenticu)](https://pypi.org/project/agenticu/)
[![Python](https://img.shields.io/pypi/pyversions/agenticu)](https://pypi.org/project/agenticu/)

Instrument multi-agent LLM systems with zero code changes. AgentICU captures structured traces via OpenTelemetry, classifies failures in real-time using the **MAST taxonomy** (14 failure modes across 3 categories), runs automated recovery playbooks, and escalates when recovery fails.

Based on the MAST paper (NeurIPS 2025 Spotlight) — analysis of 1,642 agent traces across 7 frameworks found a 41–86.7% failure rate, with **79% of failures** caused by specification ambiguity (44.2%) and coordination breakdowns (32.3%).

## Quickstart

```bash
pip install "agenticu[tui]"
```

or, if you prefer npm (requires Python >= 3.11 on PATH):

```bash
npm install -g agenticu
```

| Method | Command | Notes |
|--------|---------|-------|
| pip | `pip install "agenticu[tui]"` | Full install incl. terminal UI |
| pip (slim) | `pip install agenticu` | No TUI; add `[tui]`, `[classifier]`, `[postgres]` as needed |
| npm | `npm install -g agenticu` | Shim that pip-installs `agenticu[tui]` on first run |
| docker | `docker compose up` | App + PostgreSQL + Grafana locally |
| cloud | `tofu -chdir=infra/tofu apply` | AWS: ECS + RDS + ALB + Grafana (see `infra/tofu/README.md`) |

Decorate any agent function — the `@trace` decorator emits OpenTelemetry spans automatically:

```python
from agenticu import trace, tool_call

@trace(agent_id="researcher")
async def research_topic(query: str) -> str:
    results = await search_web(query)
    return await summarize(results)

@tool_call(return_snapshot=True)
async def search_web(query: str) -> str:
    """Simulate a search tool."""
    return f"Results for: {query}"
```

Enable **inline auto-recovery** by passing a classifier and store:

```python
from agenticu import trace
from agenticu.classification.classifier import Classifier
from agenticu.collector.storage import TraceStore

@trace(agent_id="researcher", classifier=Classifier(fast_path_only=True), store=TraceStore())
async def robust_agent(query: str) -> str:
    # If this raises, AgentICU classifies the error,
    # runs the matching recovery playbook, and retries
    return await query_database(query)
```

## Features

| Feature | Description |
|---------|-------------|
| **Decorators** | `@trace`, `@tool_call`, `@handoff`, `@decision` — framework-agnostic OTel instrumentation |
| **MAST Classifier** | 14 failure modes across Specification (5), Coordination (6), Verification (3) |
| **PROMAS Forecaster** | Markov transition model learns from your traces and predicts failure probability *before* each handoff |
| **Causal Attribution** | Traces a failure back through the handoff/decision chain to the **root-cause agent**, not just the one holding the bag |
| **Auto-Recovery** | 14 playbooks — structured `RecoveryAction` with retry logic, routed to the root-cause agent |
| **Inline Recovery** | `@trace(classifier=..., store=..., attributor=...)` — catch, classify, attribute, playbook, retry in one decorator |
| **API Server** | FastAPI — query traces, list failures, trigger recovery, forecast, attribute, Prometheus metrics |
| **CLI** | `agenticu server`, `agenticu migrate`, `agenticu check`, `agenticu tui` |
| **TUI Ops Console** | Textual terminal UI — dashboard, traces, failures, forecast, attribution, one-key recovery (`pip install "agenticu[tui]"`) |
| **npm Install** | `npm install -g agenticu` — Node shim that installs the Python package on first run |
| **Docker** | `docker compose up` — app + PostgreSQL + Grafana |
| **OpenTofu / AWS** | `infra/tofu/` — ECS Fargate + RDS Postgres + ALB + Grafana, S3 backend with native locking |
| **Escalation** | Slack / PagerDuty when auto-recovery fails (includes root-cause agent) |
| **Grafana Dashboard** | Pre-built dashboard JSON importable into Grafana |

## Architecture

```
Existing traces (Langfuse / Phoenix / raw OTel) — includes @decision rationale
               │
               ▼
    AgentICU Adapter Layer (OTel exporter)
               │
               ├──────────────► PROMAS-style Forecaster (predicts failure probability ahead of time)
               │
               ▼
    MAST Classifier (pattern-matching + embedding similarity, both active)
               │
               ▼
    Causal Attribution Layer (traces failure back through handoff chain to root-cause agent)
               │
               ▼
    Recovery Playbook Engine (targets the actual root-cause agent) ──► Escalation
               │
               ▼
    Outcome Tracking — feeds back into both the forecaster and the classifier
```

### PROMAS Forecaster

Learns transition dynamics from your own collected traces and predicts the
probability of reaching an error state *before* a handoff completes:

```python
from agenticu import Forecaster, TransitionModel
from agenticu.collector.storage import TraceStore

store = TraceStore()
# ... collect traces ...

model = TransitionModel()
await model.learn(store)            # rebuild transition matrix from history
forecaster = Forecaster(model, threshold=0.3)

result = await forecaster.forecast_at_handoff("researcher", "writer")
print(result.failure_probability)   # 0.0–1.0
print(result.predicted_mode)        # most likely MAST mode
print(result.threshold_exceeded)    # trigger early intervention
```

### Causal Attribution

When a failure is detected, trace it back through the handoff/decision chain to
the agent that actually *caused* it — critical for pointing the recovery
playbook at the right target:

```python
from agenticu import CausalAttributor
from agenticu.collector.storage import TraceStore

store = TraceStore()
attributor = CausalAttributor(store)

result = await attributor.attribute(trace_id, failure_span_id)
print(result.root_agent_id)         # "agent_b" — the true root cause
print(result.attribution_chain)     # ["agent_a", "agent_b", "agent_c"]
print(result.confidence)            # 0.0–1.0
```

## MAST Failure Taxonomy

| Category | Modes | % of Failures |
|----------|-------|---------------|
| Specification | DisobeyTaskSpec, DisobeyRoleSpec, StepRepetition, LossOfHistory, UnawareOfTermination | 44.2% |
| Coordination | ConversationReset, FailToAskClarification, TaskDerailment, InformationWithholding, IgnoredOtherAgentInput, ReasoningActionMismatch | 32.3% |
| Verification | PrematureTermination, NoVerification, IncorrectVerification | 23.5% |

## CLI

```bash
# Start the API server
agenticu server

# Apply PostgreSQL schema
agenticu migrate --dsn postgresql://user:pass@localhost:5432/agenticu

# Health check
agenticu check

# Launch the terminal UI ops console (dashboard, traces, failures,
# forecast, attribution, recovery) — talks to the server above
agenticu tui
agenticu tui --server http://prod-host --api-key <key>
```

## TUI

`agenticu tui` opens a full ops console in your terminal (requires the `tui`
extra: `pip install "agenticu[tui]"`, included in the npm install):

- **Dashboard** — server health, recovery success rate, OutcomeTracker status (auto-refreshes)
- **Traces** — filterable span table + trace detail with per-handoff forecasts
- **Failures** — filter by MAST mode / agent
- **Forecast** — predict P(failure) for any `source → target` handoff
- **Attribution** — trace a failure back to its root-cause agent
- **Recover** — trigger a recovery playbook for a trace + failure mode

## AWS Deploy (OpenTofu)

```bash
cd infra/tofu
tofu init && tofu plan -var="container_image=<ECR>:latest" -out=tfplan
tofu apply tfplan
```

Provisions ECS Fargate (API + Grafana), RDS Postgres, ALB, ECR, Secrets
Manager entries, and CloudWatch log groups. Full steps (state bucket, image
push, DB migrate, TUI against prod, teardown, cost notes) are in
[`infra/tofu/README.md`](infra/tofu/README.md).

## Docker

```bash
docker compose up
# Starts: agenticu on :8000, PostgreSQL, Prometheus on :9090, Grafana on :3000
# The Grafana datasource + AgentICU dashboard are auto-provisioned.
```

## API

| Route | Method | Description |
|-------|--------|-------------|
| `/health` | GET | Health check |
| `/api/v1/traces` | GET | List traces (filter: agent_id, status) |
| `/api/v1/traces/{id}` | GET | Get trace detail |
| `/api/v1/failures` | GET | List failures (filter: mode, agent) |
| `/api/v1/recover` | POST | Trigger recovery for a failure |
| `/api/v1/forecast` | GET | Predict failure probability for a handoff (source/target agents) |
| `/api/v1/forecast/trace` | GET | Forecast failure probability at every handoff in a trace |
| `/api/v1/attribution` | GET | Attribute a failure to its root-cause agent |
| `/api/v1/metrics/recovery` | GET | Recovery success metrics |
| `/metrics` | GET | Prometheus metrics |

## Configuration

See `config.yaml`. Override via environment variables (`AGENTICU__{SECTION}__{KEY}`).

## Development

```bash
git clone https://github.com/agenticu/agenticu
cd agenticu
pip install -e ".[dev,all]"
pytest tests/ -v
```

## License

MIT
