# Changelog

All notable changes to this project are documented here.

## [0.1.0] — 2026-10-16

First public release.

### Added
- Agent instrumentation SDK: `@trace`, `@tool_call`, `@handoff`, `@decision`
  decorators emitting OpenTelemetry spans
- MAST classifier: 14 failure modes across Specification / Coordination /
  Verification, with pattern-matching (fast) and embedding-similarity (deep) paths
- PROMAS-style forecaster: Markov transition model predicting failure probability
  at each handoff, plus an `OutcomeTracker` feedback loop
- Causal attribution: traces a failure back through the handoff chain to the
  root-cause agent
- Recovery playbook engine: 14 playbooks returning structured `RecoveryAction`,
  with retry, cooldown, and Slack / PagerDuty escalation
- Inline recovery via `@trace(classifier=..., store=..., attributor=...)`
- FastAPI server: traces, failures, recovery, forecast, attribution, metrics
- Textual TUI ops console (`agenticu tui`, `tui` extra)
- CLI: `agenticu server | migrate | check | tui`
- PostgreSQL schema (spans, failures, recovery_attempts) plus an in-memory store
  with `max_traces` eviction
- Prometheus metrics (`agenticu_failures_total`, `agenticu_recovery_total`,
  `agenticu_recovery_success_total`, `agenticu_agent_spans_total`) and a bundled
  Grafana dashboard, auto-provisioned through Docker Compose
- npm distribution (Node bin shim), Docker + Compose stack, OpenTofu AWS stack
  (ECS Fargate + RDS + ALB)
- Optional API-key auth middleware; CORS locked down by default
- `Release` workflow publishing wheel + sdist to PyPI via Trusted Publishing (OIDC)

### Changed
- `schema.sql` now ships inside the package (`agenticu/schema.sql`); `agenticu
  migrate` uses the bundled schema by default, so migrations work after
  `pip install`
- Playbooks return `RecoveryAction` (structured) instead of a bare `bool`
- Grafana dashboard and alerts reference `_total`-suffixed counter names

### Fixed
- `/metrics` serves Prometheus text exposition instead of a JSON-escaped string
- TUI client maps every transport failure (connect error, timeout) to `TUIError`
- Inline recovery honours `@trace(max_retries=...)` and persists attempts via
  `TraceStore.insert_recovery` (previously it bypassed PostgreSQL and always
  retried exactly once)
- `@trace` records span ids as hex strings so causal attribution can match
  stored spans
- Config env-var overrides nest under `agenticu`; `TraceProcessor` dedup set is
  per-instance; the OTel exporter converts nanosecond timestamps

### Removed
- Dead code: never-incremented Prometheus counters, unused helpers and fixtures
