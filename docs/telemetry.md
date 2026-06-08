# Telemetry & observability

Everything the agent does is observable three ways: **structured logs** (live),
the **audit trail** (durable, queryable), and **metrics** (aggregate).

## Structured logs

`reconcile.logging_setup` configures [structlog](https://www.structlog.org/) to
emit one JSON object per line to stdout. A `run_id` is bound for the duration of
each run (and each HTTP request) via context vars, so every line is correlatable.

```bash
uv run reconcile demo 2>&1 | jq -c 'select(.run_id) | {run_id, event, component}'
```

Every line includes at least: `timestamp`, `level`, `event`, `run_id`, and
`component`.

## Audit trail

`reconcile.audit.repository.AuditRepository` writes a typed row to `audit_log`
for each significant step — and emits a matching log line, so the audit table and
the log stream never drift. Columns:

| Column | Meaning |
|---|---|
| `run_id` | Correlates to the run |
| `ts` | Event time (UTC) |
| `order_id` | Affected order (nullable) |
| `event_type` | e.g. `reconcile_completed`, `exception_decided`, `notification_dispatched` |
| `action` | Planner action (when applicable) |
| `reason` | Exception reason (when applicable) |
| `status` | Outcome/severity (when applicable) |
| `details` | JSON blob with step-specific context |

Inspect a run over HTTP:

```bash
curl localhost:8000/runs/<run_id> | jq
```

## Metrics

`GET /metrics` returns an aggregate snapshot drawn from the database and the live
services:

```json
{
  "runs_total": 3,
  "exceptions_by_reason": { "CASH_MISSING": 1, "AMOUNT_SHORT": 1, "...": 1 },
  "notifications": { "SENT": 11, "SKIPPED": 11 },
  "incidents": { "OPEN": 0 },
  "circuit_breaker": { "state": "closed", "fail_count": 0 }
}
```

These counts reconcile with the database: `notifications` mirrors
`notification_log`, `exceptions_by_reason` mirrors `exception_log`, and
`incidents` mirrors `incidents.jsonl`.

## Run summary

Each run returns (and persists on `run_log.summary_json`) a compact summary:

```json
{
  "matched": 7,
  "exceptions_total": 8,
  "exceptions_by_reason": { "...": 1 },
  "actions": { "EMAIL_PG": 4, "WAIT": 1, "EMAIL_STORE_MANAGER": 2 },
  "notifications": { "SENT": 11 },
  "fuzzy_auto_applied": 1,
  "resolved": 0
}
```

## Optional: LangSmith tracing

Set `LANGSMITH_TRACING=true` and `LANGSMITH_API_KEY` to trace LLM calls in
[LangSmith](https://smith.langchain.com/). It is off by default and never
required.
