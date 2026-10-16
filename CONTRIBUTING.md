# Contributing to AgentICU

Thanks for your interest! AgentICU is in early alpha — every contribution counts.

## Development Setup

```bash
git clone https://github.com/Anandhasasidharan/AGENTICU
cd AGENTICU
python -m venv venv && source venv/bin/activate
pip install -e ".[dev,classifier,postgres]"
```

## Running Tests

```bash
pytest tests/ -v
```

All tests use in-memory storage by default — no database required.

## Code Style

- Ruff linting with line-length 100
- Python 3.11+ type annotations everywhere
- No external dependencies beyond project scope
- Install the git hooks once: `pre-commit install` (runs `ruff check --fix`
  and `ruff format` on every commit — same gates CI enforces)

## Maintenance Commands

```bash
ruff check src tests          # lint (must be clean)
ruff format --check src tests # formatting gate (same as CI)
pytest tests/ -v              # full suite (in-memory store, no DB needed)
vulture src tests --min-confidence 100  # dead-code scan (60% hits are
                                        # framework false positives: FastAPI/
                                        # Textual handlers, dataclass fields,
                                        # pytest fixtures — verify before deleting)
pip-audit                     # dependency vulnerability scan
```

## Pull Request Process

1. Open an issue first for non-trivial changes
2. Ensure all tests pass and lint is clean
3. Update CHANGELOG.md under "Unreleased"
4. PRs need one review before merging
