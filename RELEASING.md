# Releasing AgentICU

## 1. Pre-flight

```bash
pip install -e ".[all,dev]"
ruff check src tests
ruff format --check src tests
pytest tests/ -q
```

Bump the version in `pyproject.toml`, `package.json`, and `src/agenticu/__init__.py`,
then add a `CHANGELOG.md` entry.

## 2. Build and validate locally

```bash
python -m build
twine check --strict dist/*
```

## 3. Publish to PyPI (Trusted Publishing)

Publishing runs from `.github/workflows/release.yaml` when a GitHub **release**
is published — no API tokens are stored.

One-time setup on PyPI:

1. Sign in to <https://pypi.org> (the project does not need to exist yet —
   add a **pending publisher** under Account → Publishing).
2. Fill in:
   - **Owner:** `Anandhasasidharan`
   - **Repository:** `AGENTICU`
   - **Workflow name:** `release.yaml`
   - **Environment name:** `pypi`
3. Save.

Then cut a release:

```bash
git tag v0.1.0
git push origin v0.1.0
gh release create v0.1.0 --title "v0.1.0" --generate-notes
```

The `Release` workflow builds the wheel + sdist, runs `twine check --strict`,
and uploads to PyPI.

## 4. Publish to npm

```bash
npm adduser            # one-time
npm publish --access public
```

## 5. Deploy to AWS (OpenTofu)

Requires the AWS CLI, Docker, and OpenTofu installed locally. See
[`infra/tofu/README.md`](infra/tofu/README.md) for the full runbook (state
bucket → push image → `tofu apply` → `agenticu migrate`).

## 6. Verify

```bash
pip install "agenticu[tui]"        # from PyPI
agenticu --help
agenticu tui --server <url>
```
