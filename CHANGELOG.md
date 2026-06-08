# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Initial project scaffold: `uv`-managed Python 3.11 project with `src/` layout.
- Tooling: `ruff` (lint + format), `mypy --strict`, `pytest` + coverage,
  pre-commit hooks, and GitHub Actions CI.
- Domain models and enumerations (`models/domain.py`) with exact `Decimal` money
  and a stable `mismatch_key` helper.
- Pydantic-settings configuration (env) plus YAML business config with
  `RECIPIENT_*` environment overrides.
- Structured JSON logging (`structlog`) with `run_id` context binding.
- SQLAlchemy ORM models and SQLite engine/session setup (`run_log`, `audit_log`,
  `notification_log`, `exception_log`) with a DB-enforced notification
  idempotency constraint.
- Orders/settlements file parsers (`.xlsx` + `.csv`) with row-level validation
  errors.
- Deterministic sample-data generator and committed sample files covering every
  reconciliation outcome.

### Reconciliation core
- Obligation builder with per-order sum validation (`ORDER_SUM_MISMATCH`).
- Deterministic matcher: key matching (`gateway_txn_id`, then
  `(order_id, payment_type)`), amount comparison (matched / short / excess /
  duplicate), and leftover classification (cash/online missing, late, unmatched
  settlement).
- SLA evaluation (per-payment-type grace, overridable as-of date).
- Routing rules mapping each exception to recipient roles + emails with a
  `responsible_party` override, plus stable `mismatch_key` computation.

### Notifications, resilience & incidents
- Notifier protocol with mock / Resend / SMTP implementations and a factory.
- `NotificationService`: idempotent, retried (tenacity), circuit-broken
  (pybreaker) email dispatch that records every attempt.
- Audit repository (run lifecycle, append-only typed events with telemetry,
  cross-run exception lifecycle) and idempotency helpers (`input_hash`,
  notification dedupe).
- Incident management: failure taxonomy, deterministic severity, JSON/JSONL
  store, and a durable admin notifier (console always, email best-effort).

### Agent
- LLM client abstraction with a deterministic offline mock and a Groq-backed
  implementation (retries + per-run call budget + template fallback).
- LangGraph state machine: reconcile → (optional fuzzy match) → classify →
  decide → dispatch → verify, with dependencies injected into nodes.
- Planner guardrails (action allow-list + `ESCALATE` fallback, WAIT only within
  SLA) and a cross-run verifier that resolves stale exceptions.
- `ReconciliationAgent` orchestration with run lifecycle, incident-on-failure,
  dry-run mode, and a rich `RunOutcome` for the UI/CLI.

### API, UI & CLI
- FastAPI app with a minimal Jinja2 web UI (upload page, results page with
  summary cards, exception table, and expandable email previews).
- Endpoints: `GET /`, `POST /reconcile`, `POST /demo`, `GET /runs/{id}`,
  `GET /metrics`, `GET /healthz`, with per-request id binding and upload caps.
- Optional `DEMO_ACCESS_KEY` gate and a 5 MB upload limit for safe public hosting.
- Typer CLI: `serve`, `run`, `demo`, `init-db` (also runnable via
  `python -m reconcile`).
