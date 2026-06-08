# Contributing

Thanks for taking a look! This is a compact, reviewable agentic prototype, so the
contribution workflow is intentionally simple.

## Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) (`pip install uv`)

## Setup

```bash
uv sync --extra dev          # create .venv and install all deps
cp .env.example .env         # fill in keys, or keep MOCK_LLM=true / NOTIFIER=mock
uv run pre-commit install    # enable git hooks (ruff + mypy on commit)
```

## Everyday commands

| Task | Command |
|------|---------|
| Run the web app | `uv run reconcile serve` |
| Run the demo (mock email) | `uv run reconcile demo --notifier mock` |
| Run tests | `uv run pytest` |
| Lint | `uv run ruff check .` |
| Format | `uv run ruff format .` |
| Type-check | `uv run mypy src` |
| All checks (as CI runs them) | `uv run ruff check . && uv run mypy src && uv run pytest` |

## Conventions

- **Determinism first.** The reconciliation/matching path must never depend on
  LLM output. The LLM is only for planning, fuzzy-match proposals, email
  drafting, and explanations.
- **Typed everywhere.** `mypy --strict` must pass; prefer Pydantic models at
  boundaries.
- **Tests with every change.** Unit tests live in `tests/unit/`, cross-component
  tests in `tests/integration/`, full-pipeline tests in `tests/e2e/`.
- **No secrets in the repo.** Configuration of contacts lives in
  `config/settings.yaml`; secrets live in `.env` / platform secrets only.
- **Conventional-ish commits.** Use clear, imperative subjects
  (e.g. `feat: add settlement matcher`, `fix: handle empty orders file`).

## Pull requests

1. Branch from `main`.
2. Ensure `ruff`, `mypy`, and `pytest` all pass locally.
3. Update `CHANGELOG.md` under `[Unreleased]`.
4. Open a PR using the template; describe the change and how you tested it.
