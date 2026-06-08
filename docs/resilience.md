# Resilience & recovery

The system is designed to **never fail silently**. It tries to recover
automatically and, when it cannot, records a durable incident and notifies an
administrator.

## Retry (tenacity)

`reconcile.notifications.retry.call_with_retry` wraps both email and LLM calls:

- `stop_after_attempt(3)`
- exponential backoff (`min`/`max` seconds from config)
- retries only on the configured *transient* exception type

Transient vs permanent is explicit:

- **Transient** (`TransientNotifyError`, `LLMTransientError`) — network errors,
  timeouts, 5xx → retried.
- **Permanent** (`PermanentNotifyError`) — auth/4xx/validation → raised
  immediately, no wasted retries.

## Circuit breaker (pybreaker)

`reconcile.notifications.circuit_breaker` wraps the notifier in a breaker
(`fail_max`, `reset_timeout` from config). On repeated failures it **opens**, and
further calls short-circuit immediately, returning
`SendResult(status=SKIPPED, reason="circuit_open")` instead of hammering a dead
provider. State changes are logged as structured events and surfaced at
`GET /metrics`.

```text
send → send → send (3 transient failures) → breaker OPENS
next send → skipped:circuit_open (no provider call)
```

## Idempotency

Two levels:

- **Notification level** — `notification_log` has a unique index on
  `(mismatch_key, recipient_email)`. Before sending, the service checks for a
  prior successful send and returns `skipped:duplicate` if found. The DB
  constraint is the backstop. Re-running the same files sends **zero** new
  emails.
- **Run level** — `input_hash = sha256(orders + settlements)` is stored on the
  run, so an identical pair of files is detectable.

## Incidents vs. escalations

These are deliberately distinct:

- An **escalation** (`ESCALATE`) is a *business* action — a valid exception
  routed to the admin for a human decision.
- An **incident** is an *unrecoverable system failure* — bad input, a planner
  crash, exhausted retries with an open breaker. Incidents are written as
  `data/runtime/incidents/<id>.json` **and** appended to `incidents.jsonl`.

Incident severity is assigned by **deterministic rules**
(`reconcile.incidents.severity`), never by the LLM.

## Durable administrator notification

On every incident the admin is reached through a channel that does **not** depend
on the failing component:

1. the incident is written to `incidents.jsonl` (durable), and
2. a structured line is printed to stderr,

**then** a best-effort email is attempted. If email is the thing that's broken,
steps 1–2 still guarantee the admin has a record.

## Self-healing example

```text
SMTP send fails (transient)
  → retry → retry → retry        (tenacity)
  → breaker opens                (pybreaker)
  → send returns skipped:circuit_open
  → incident created             (deterministic severity)
  → admin notified durably       (jsonl + stderr, email best-effort)
```

## Dry run

`--dry-run` (CLI) or the dry-run toggle (UI) computes everything — exceptions,
decisions, drafted emails — but the dispatch step returns `skipped:dry_run`
without sending, so a demo can never email a real address by accident.
