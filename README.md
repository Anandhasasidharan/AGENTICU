# AgentICU — Multi-Agent Observability & Auto-Recovery

[![Tests](https://github.com/Anandhasasidharan/AGENTICU/actions/workflows/ci.yml/badge.svg)](https://github.com/Anandhasasidharan/AGENTICU/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/agenticu)](https://pypi.org/project/agenticu/)
[![Python](https://img.shields.io/pypi/pyversions/agenticu)](https://pypi.org/project/agenticu/)

Instrument multi-agent LLM systems with Python decorators. AgentICU captures OpenTelemetry traces, classifies error spans using experimental rules for the 14 **MAST** failure modes, and records what happens when an agent applies a recovery playbook. Configure a webhook to escalate repeated recovery failures.

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

### Send traces to a running server

Start a local server with SQLite. Run migrations once before starting the server
and again after upgrading AgentICU.

```bash
agenticu migrate
agenticu server
```

Run your decorated agent in a separate terminal with one environment setting.

```bash
AGENTICU_SERVER_URL=http://localhost:8000 python your_agent.py
```

The SDK installs a batched OpenTelemetry exporter when the first decorated
agent runs. Set `AGENTICU__API__KEY` in the agent environment if the server
requires a bearer token. For a custom tracer provider, register
`agenticu.AgentICUHTTPExporter` with that provider. OpenTelemetry-compatible
clients can also POST traces directly to `/v1/traces`.

The server validates a batch before queuing it for classification and storage.
The bounded in-process queue returns HTTP 503 when full and drains during a
graceful shutdown. Accepted traces may take a moment to become queryable, and
a crash can lose batches still in the queue. The server classifies error spans
with the MAST rules and records their category and severity. Forecast and
attribution endpoints use persisted traces.

### Apply recovery in your agent

Pass an `on_failure` callback to `@trace`. It gets a `RecoveryAction` with
instructions, a target agent, and any available playbook payload. Apply the
directive to your application's state before the SDK retries the function.

```python
from agenticu import trace

state = {"skip_completed_steps": False}

def apply_recovery(action):
    state["skip_completed_steps"] = True
    return action.should_retry

@trace(agent_id="planner", on_failure=apply_recovery)
def run_planner():
    if not state["skip_completed_steps"]:
        raise RuntimeError("Agent kept repeating the same step")
    return "Proceed with the next step"
```

Return `True` or `False` to decide whether to retry, or `None` to use the
playbook's recommendation. Pass a `TraceStore` to the decorator when
playbooks need local checkpoints. Configure `auto_recover`, `max_retries`,
and `escalate_after` in the agent and server environments. The SDK sends
outcomes with the trace. Use `GET /api/v1/recovery-attempts?trace_id=...` to
inspect attempts and `GET /api/v1/metrics/recovery` for strategy success rates.
Set an escalation webhook to receive traces after repeated failures.

## Features

| Feature | Description |
|---------|-------------|
| **Decorators** | `@trace`, `@tool_call`, `@handoff`, `@decision` — framework-agnostic OTel instrumentation |
| **MAST Classifier** | Experimental rule-based detection across 14 failure modes |
| **PROMAS Forecaster** | Markov transition model learns from your traces and predicts failure probability *before* each handoff |
| **Causal Attribution** | Traces a failure back through the handoff/decision chain to the **root-cause agent**, not just the one holding the bag |
| **Auto-Recovery** | 14 playbooks provide structured directives to an SDK `on_failure` callback |
| **Recovery Outcomes** | The SDK reports actual retry results. The API shows outcomes and success rates by mode and strategy. |
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
    MAST Classifier (experimental rules on error spans)
               │
               ▼
    Causal Attribution Layer (traces failure back through handoff chain to root-cause agent)
               │
               ▼
    Recovery Playbook Engine (targets the actual root-cause agent) ──► Escalation
               │
               ▼
    Outcome Tracking — stores recovery results and refreshes forecasting
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

**All 14 classifier modes are experimental.** Each scored below 0.50 F1 on
the public trace-level benchmark. The rules can recognize explicit failure
messages such as the one in the recovery example. See the per-mode scores,
confusion summary, and evaluation method. [Classifier validation](docs/classifier-validation.md)

| Category | Modes | % of Failures |
|----------|-------|---------------|
| Specification | DisobeyTaskSpec, DisobeyRoleSpec, StepRepetition, LossOfHistory, UnawareOfTermination | 44.2% |
| Coordination | ConversationReset, FailToAskClarification, TaskDerailment, InformationWithholding, IgnoredOtherAgentInput, ReasoningActionMismatch | 32.3% |
| Verification | PrematureTermination, NoVerification, IncorrectVerification | 23.5% |

## CLI

```bash
# Apply SQLite migrations and start the local API server
agenticu migrate
agenticu server

# Use the same PostgreSQL DSN for migrations and the API server
export AGENTICU__STORAGE__DSN=postgresql://user:pass@localhost:5432/agenticu
agenticu migrate
agenticu server

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
- **Recover** — prepare a recovery directive for a trace and failure mode

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

## End-to-end LangGraph demo

Start the API, PostgreSQL, Prometheus, and Grafana. Compose runs the schema
migrations before starting the API on port 8000.

```bash
docker compose up --build -d
pip install -e ".[demo]"
python examples/langgraph_recovery_demo.py --server http://localhost:8000
```

The LangGraph workflow repeats a completed step. Its SDK hook applies the
Step Repetition directive and resumes from the saved checkpoint. The demo
queries the stored MAST 1.3 failure and recovered outcome, then opens the
Textual app headlessly and confirms that the trace appears in the Failures tab.
The console prints the trace ID so you can inspect it in `agenticu tui` as well.
The workflow uses deterministic steps and requires no LLM API key.

Run the same check as part of pytest with the Compose stack running.

```bash
pip install -e ".[demo,dev]"
TEST_AGENTICU_COMPOSE_URL=http://localhost:8000 pytest tests/
```

## API

| Route | Method | Description |
|-------|--------|-------------|
| `/health` | GET | Health check |
| `/v1/traces` | POST | OTLP/HTTP trace ingestion, protobuf or JSON |
| `/ingest` | POST | Debug JSON ingestion, e.g. `{"spans":[{"trace_id":"demo","span_id":"first"}]}` |
| `/api/v1/traces` | GET | List traces (filter: agent_id, status) |
| `/api/v1/traces/{id}` | GET | Get trace detail |
| `/api/v1/failures` | GET | List failures (filter: mode, agent) |
| `/api/v1/recover` | POST | Prepare a recovery directive for a failure |
| `/api/v1/forecast` | GET | Predict failure probability for a handoff (source/target agents) |
| `/api/v1/forecast/trace` | GET | Forecast failure probability at every handoff in a trace |
| `/api/v1/attribution` | GET | Attribute a failure to its root-cause agent |
| `/api/v1/recovery-attempts` | GET | Recorded attempts and outcomes (filter by trace ID) |
| `/api/v1/metrics/recovery` | GET | Success rates by strategy and MAST mode |
| `/metrics` | GET | Prometheus metrics |

## Configuration

See `config.yaml`. Override settings with `AGENTICU__{SECTION}__{KEY}`.
The CLI uses SQLite at `agenticu.db` by default. A nonempty
`AGENTICU__STORAGE__DSN` selects PostgreSQL and requires the `postgres` extra.
Set both the DSN and `AGENTICU__STORAGE__SQLITE_PATH` to empty strings to use
in-memory storage. Docker Compose runs migrations in a one-shot service before
starting the API.

## Development

```bash
git clone https://github.com/Anandhasasidharan/AGENTICU
cd agenticu
pip install -e ".[dev,all]"
pytest tests/ -v
```

## License

MIT
