# Changelog

All notable changes to this project are documented here.

## Unreleased

### Added
- Initial project scaffold (SDK, collector, classifier, recovery, API)
- 14 MAST failure mode playbooks (specification, coordination, verification)
- Inline recovery via `@trace(classifier=..., store=...)` decorator
- CLI: `agenticu server`, `agenticu migrate`, `agenticu check`
- Dockerfile + docker-compose.yml (app, postgres, grafana)
- PostgreSQL schema (spans, failures, recovery_attempts)
- CORS lockdown with configurable origins
- Optional API key authentication middleware
- In-memory trace store with max-traces eviction guard
- CONTRIBUTING.md, CODE_OF_CONDUCT.md, issue/PR templates

### Added
- Textual TUI ops console (`agenticu tui`, `tui` extra): dashboard, traces,
  failures, forecast, attribution, recovery trigger
- npm distribution (`npm install -g agenticu` via Node bin shim)
- OpenTofu AWS prod stack (`infra/tofu/`): ECS Fargate + RDS + ALB + Grafana
- `category` field on trace API responses (wired from `FAILURE_CATEGORY_MAP`)
- Pre-commit hooks (ruff check + format) and ruff lint/format gates in CI
- `pre-commit` and `vulture` in the `dev` extra

### Changed
- Playbooks return `RecoveryAction` (structured) instead of bare `bool`

### Removed
- Dead code: never-incremented Prometheus counters in API routes, unused
  `MetricsTracker` helpers, `TransitionModel`/`Forecaster` leftovers superseded
  by `OutcomeTracker`, incomplete `get_failure_examples` helper, unused test
  fixtures/helpers
- Zero lint errors repo-wide (`ruff check` + `ruff format` baselined)
