# ReconcileFlow Agent

> Agentic retail payment reconciliation: upload an **orders** file and a
> **settlements** file, and an LLM-assisted agent reconciles them, decides what
> to do about each mismatch, emails the right stakeholder, and records a full
> audit trail — with circuit breaking, retries, idempotency, and structured
> telemetry throughout.

[![CI](https://github.com/your-org/retail-reconciliation-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/your-org/retail-reconciliation-agent/actions/workflows/ci.yml)

---

> **Status:** scaffolding in progress. This README is filled out fully in Phase 7.
> See [PLAN.md](PLAN.md) for the delivery plan and [PRD.md](PRD.md) for requirements.

## Quick start (preview)

```bash
uv sync --extra dev
cp .env.example .env        # defaults run fully offline (MOCK_LLM=true, NOTIFIER=mock)
uv run reconcile demo       # run the agent against bundled sample data
uv run reconcile serve      # then open http://localhost:8000
uv run pytest               # run the test suite
```

## What this is

A compact but production-shaped agentic system that demonstrates:

- **Deterministic reconciliation** of orders vs settlements (no LLM in the
  matching path).
- An **LLM planner** that selects a controlled next action per exception.
- **Email notifications** routed to the correct party (store manager / payment
  gateway / bank / admin).
- **Resilience**: retries with backoff, a circuit breaker, and idempotent
  re-runs.
- **Observability**: structured JSON logs with a correlating `run_id`, an
  append-only audit trail, an incident log, and a `/metrics` endpoint.

Full documentation lands in Phase 7. For now, the authoritative design lives in
[PLAN.md](PLAN.md) and [PRD.md](PRD.md).
