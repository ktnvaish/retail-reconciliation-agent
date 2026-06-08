# Product Requirements Document (PRD) — v2

## Product Name

**ReconcileFlow Agent**

> Status: **v2 (refined)** · Last updated: 2026-06-08
> This version closes the open design questions in v1. Resolved decisions are
> summarised in [Appendix A — Decision Log](#appendix-a--decision-log). Where a
> requirement changed from v1, the change is called out inline as **(v2)**.

---

## 1. Overview

ReconcileFlow Agent is an agentic reconciliation system that processes two
tabular files:

1. **Orders file** containing order-level payment expectations (one row per
   payment obligation).
2. **Settlements file** containing actual settlement entries received from
   payment gateways or bank statements.

The system reconciles expected vs actual payments **deterministically**,
identifies mismatches, uses an **LLM-based planner** to choose the next best
action for each exception, sends email notifications to the relevant party,
records a complete audit trail, emits structured telemetry, and creates
incidents for unrecoverable failures. It is a compact agentic prototype suitable
for a coding assignment or internal proof of concept.

The system is **deterministic where correctness matters** (matching, amounts,
audit, incident severity) and **agentic where judgement helps** (action
selection, fuzzy-match proposals, email drafting, explanations).

---

## 2. Problem Statement

Finance and operations teams manually reconcile daily order payments against
bank or payment-gateway settlements. The process is slow, repetitive,
error-prone, and depends on human judgement for exception handling.

The product automates this workflow by:

- reading uploaded spreadsheets,
- performing deterministic reconciliation,
- deciding what action to take for each mismatch,
- sending communications automatically,
- storing audit history,
- emitting telemetry for every critical event,
- and notifying administrators when the agent cannot self-resolve an error.

---

## 3. Goals

The system should:

- accept two files (`.xlsx` or `.csv`) via **CLI or web upload**, **(v2)**
- reconcile multiple payment modes for the same order,
- identify matched, partially matched, excess, duplicate, and unmatched obligations,
- use an LLM to decide the next action for exceptions,
- send emails to the correct stakeholder,
- store an audit trail for every decision and action,
- emit telemetry for observability and debugging,
- create incidents for unrecoverable failures,
- notify administrators when human intervention is required,
- support rerun of the same input without duplicate side effects.
- **be deployable as a single container to Azure Container Apps** for a hosted
  demo (real Groq + real Resend), with secrets supplied via platform env/secrets.

---

## 4. Non-Goals

Out of scope for this version:

- GST filing
- voice calls / SMS
- real bank API integrations
- real payment-gateway integrations
- **a managed / networked database** — a single-file **SQLite** database and
  JSON files provide persistence. **(v2 — deployment:** hosting the _app_ as a
  single-replica container on **Azure Container Apps** IS in scope; a
  managed/networked DB is not; hosted state is **ephemeral** by design — §15.)
- multi-user dashboard
- multi-tenant access control / authentication
- real-time streaming
- **multi-replica / auto-scaling / production-grade** deployment — the demo runs
  as a single replica; horizontal scale would require Postgres

---

## 5. Users

### Primary User

Finance-operations analyst or accountant who uploads daily order and settlement
files (web upload or CLI).

### Secondary User

Engineering reviewer or interviewer evaluating system design, agentic reasoning,
observability, and code quality.

### Operational User

Administrator who receives incident notifications when the agent cannot
self-recover.

---

## 6. Core User Journey

1. User provides `orders.xlsx`/`.csv` and `settlements.xlsx`/`.csv` **via the
   web upload page or the CLI**. **(v2)**
2. System parses and validates both files (schema, types, duplicates, empties).
3. System converts order rows into payment **obligations** (§7.2).
4. System matches obligations against settlements **deterministically** (§7.4).
5. System identifies exceptions (§7.5).
6. Planner agent decides the next action for each exception (§7.6).
7. Email is sent to the relevant party (§7.7).
8. Verifier checks whether each exception is resolved or still open (§7.8).
9. Audit trail is updated (§7.10).
10. Telemetry events are emitted throughout (§7.9).
11. If a step cannot be recovered, an incident is created and the admin is
    notified through a **durable, non-email-only channel** (§7.11–§7.12).

---

## 7. Functional Requirements

### 7.1 File Input

The system must accept two input files (`.xlsx` or `.csv`):

- orders file,
- settlements file.

Submitted via **web upload (multipart) or CLI path argument**. **(v2)**

Validation must cover:

- file existence and readability,
- file format / MIME (`.xlsx`, `.csv` only),
- **file-size cap (default 5 MB) and row-count cap (default 50,000 rows)**, **(v2)**
- required columns present,
- data-type consistency (dates, decimals, enums),
- duplicate-row handling (see §7.4 `DUPLICATE`),
- empty-file handling.

Validation failures that prevent processing create an **incident** (§7.11) and
are surfaced with row numbers in the UI/CLI.

---

### 7.2 Orders Processing

Each **row** in the orders file is one **payment obligation**. An order
(`order_id`) may span multiple rows (e.g. part CARD, part CASH, part UPI), and
each such row is a separate expected obligation.

Required and conditional columns **(v2 — enriched with join keys and enums)**:

| Column              | Type              | Required    | Notes                                                                                     |
| ------------------- | ----------------- | ----------- | ----------------------------------------------------------------------------------------- |
| `order_id`          | str               | yes         | Repeated across an order's payment rows; **not** unique                                   |
| `order_date`        | date `YYYY-MM-DD` | yes         | Used for age / SLA                                                                        |
| `store_id`          | str               | yes         |                                                                                           |
| `amount`            | decimal           | yes         | Order **gross total**; identical on every row of the same order                           |
| `payment_type`      | enum              | yes         | `CASH \| UPI \| CARD \| NETBANKING \| WALLET`                                             |
| `payment_amount`    | decimal           | yes         | This obligation's amount                                                                  |
| `payment_gateway`   | enum/null         | conditional | Required when `payment_type != CASH`; one of `RAZORPAY \| PAYU \| CASHFREE`               |
| `gateway_txn_id`    | str/null          | conditional | Required when `payment_type != CASH`; **unique per online obligation** — primary join key |
| `responsible_party` | enum/null         | no          | Optional **override** role: `STORE_MANAGER \| PAYMENT_GATEWAY \| BANK \| ADMIN` (§9.4)    |
| `status`            | enum              | yes         | `PLACED \| CANCELLED` — only `PLACED` obligations are reconciled                          |
| `customer_name`     | str               | no          |                                                                                           |
| `customer_email`    | str               | no          |                                                                                           |

**Obligation-sum validation (v2):** for each `order_id`, the system validates
`sum(payment_amount) == amount` within tolerance. A mismatch raises an
**order-level** `ORDER_SUM_MISMATCH` data-quality exception
(`expected_amount = amount`, `actual_amount = sum(payment_amount)`; `status`
reuses `EXCESS` when rows over-sum and `PARTIALLY_MATCHED` when they under-sum;
the authoritative discriminator is `reason = ORDER_SUM_MISMATCH`), routed to the
Store Manager. This check is **independent of settlement matching** — the
individual obligations are still reconciled normally.

Example: Order `O1001`, `amount = 1000`, rows `CARD = 600` and `CASH = 400`
→ two obligations; sum check passes.

---

### 7.3 Settlement Processing

Each row is one actual money-received entry from a bank or payment gateway.

Required and optional columns **(v2 — adds settlement identity and join keys)**:

| Column            | Type     | Required | Notes                                                        |
| ----------------- | -------- | -------- | ------------------------------------------------------------ |
| `settlement_id`   | str      | yes      | **Unique within file** — identity for idempotency/dedup      |
| `settlement_date` | date     | yes      |                                                              |
| `gateway_txn_id`  | str/null | no       | **Preferred join key** when present                          |
| `order_id`        | str/null | no       | **Secondary join key**; may be blank (drives unmatched flow) |
| `reference_id`    | str/null | no       | Bank/PG reference (e.g. UTR) — retained for traceability     |
| `payment_type`    | enum     | yes      | Same enum as orders                                          |
| `amount`          | decimal  | yes      | Gross amount received                                        |
| `fee`             | decimal  | no       | Default `0`                                                  |
| `net_amount`      | decimal  | yes      | `amount - fee`                                               |
| `source`          | enum     | yes      | `BANK \| RAZORPAY \| PAYU \| CASHFREE`                       |

---

### 7.4 Reconciliation Engine

The engine reconciles obligations against settlements using **deterministic**
rules only. **The LLM is never in the matching path** (§10).

#### 7.4a Matching algorithm **(v2 — newly specified)**

1. Filter to obligations with `status = PLACED`. Skip `CANCELLED`.
2. Build a settlement index keyed by `gateway_txn_id` (skip nulls).
3. For each online obligation (`payment_type != CASH`) with a `gateway_txn_id`,
   look it up → candidate pair.
4. Build a settlement index of remaining settlements keyed by
   `(order_id, payment_type)` (skip null `order_id`).
5. For each still-unmatched obligation, look up by `(order_id, payment_type)`
   → candidate pair (disambiguates split payments on the same order).
6. For each candidate pair, compare amounts within `amount_tolerance` to assign
   the final status (below).
7. Anything still unmatched on either side flows to the exception pipeline
   (§7.5). Residual unmatched orders **and** settlements may first be offered to
   the optional LLM fuzzy-match step (§7.6) before final classification.

The matcher is **SLA-blind**; SLA only influences the planner (§7.6).

#### 7.4b Status definitions **(v2 — all five now defined)**

Each obligation is classified as exactly one:

| Status              | Definition                                                                                                                    |
| ------------------- | ----------------------------------------------------------------------------------------------------------------------------- |
| `MATCHED`           | Exactly one settlement satisfies the obligation and `\|expected − actual\| ≤ amount_tolerance`.                               |
| `PARTIALLY_MATCHED` | Matched by key, but settled **less** than expected (`actual < expected − tolerance`).                                         |
| `EXCESS`            | Matched by key, but settled **more** than expected (`actual > expected + tolerance`).                                         |
| `DUPLICATE`         | A duplicate `settlement_id` in the file, **or** two distinct settlements satisfy the same obligation key (double settlement). |
| `UNMATCHED`         | An obligation with no settlement, **or** a settlement with no obligation (`UNMATCHED_SETTLEMENT`).                            |

---

### 7.5 Exception Generation

For every non-`MATCHED` obligation (and every unmatched settlement), the system
creates an exception record containing:

- `order_id` (when applicable),
- `settlement_id` (when applicable),
- `payment_type`,
- `expected_amount`,
- `actual_amount`,
- `status` (§7.4b),
- `reason` (taxonomy below),
- `age_days` (§7.8 / §9.6),
- `responsible_party` (resolved role, §9.4),
- `sla_status` (`WITHIN_SLA \| BREACHED \| NA`),
- `mismatch_key` (idempotency key, §7.14).

#### 7.5a Mismatch reason taxonomy & recipient routing **(v2)**

| `reason`               | Trigger                                                                                                                           | Default recipient role(s)              |
| ---------------------- | --------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------- |
| `CASH_MISSING`         | `CASH`, `PLACED`, no settlement                                                                                                   | `STORE_MANAGER`                        |
| `ONLINE_MISSING`       | online obligation, no settlement, SLA breached                                                                                    | `PAYMENT_GATEWAY` (order's gateway)    |
| `AMOUNT_SHORT`         | `PARTIALLY_MATCHED`                                                                                                               | `PAYMENT_GATEWAY` + `STORE_MANAGER`    |
| `AMOUNT_EXCESS`        | `EXCESS` (over-settled)                                                                                                           | `PAYMENT_GATEWAY` + `STORE_MANAGER`    |
| `DUPLICATE_SETTLEMENT` | `DUPLICATE`                                                                                                                       | `PAYMENT_GATEWAY` + `BANK`             |
| `UNMATCHED_SETTLEMENT` | settlement with no obligation (fuzzy step rejected)                                                                               | `BANK` + `PAYMENT_GATEWAY`             |
| `ORDER_SUM_MISMATCH`   | order-level data-quality: `sum(payment_amount) != amount` (`status` reuses `EXCESS`/`PARTIALLY_MATCHED`; independent of matching) | `STORE_MANAGER`                        |
| `LATE_SETTLEMENT`      | online obligation unmatched but **still within** grace                                                                            | `PAYMENT_GATEWAY` (planner may `WAIT`) |
| `FUZZY_MATCH_REVIEW`   | LLM proposed a pairing with `0.5 ≤ confidence < 0.85`                                                                             | `ADMIN`                                |

A row's `responsible_party` value, when present, **overrides** the default role
for that obligation's exceptions (§9.4).

---

### 7.6 Agentic Planner

An LLM-based planner receives each exception and selects the next action from a
**controlled allow-list**:

- `WAIT`
- `EMAIL_STORE_MANAGER`
- `EMAIL_PG`
- `EMAIL_BANK`
- `ESCALATE`
- `REQUEST_RECHECK`

**Action semantics (v2 — newly specified):**

| Action                                            | Meaning                                                                                                                              | Re-evaluation                                                |
| ------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------ |
| `WAIT`                                            | Defer; no email. **Allowed only when `sla_status = WITHIN_SLA`.**                                                                    | Re-evaluated on the next run, or once the SLA grace elapses. |
| `EMAIL_STORE_MANAGER` / `EMAIL_PG` / `EMAIL_BANK` | Dispatch a drafted email to that recipient role.                                                                                     | Verifier (§7.8) on next run.                                 |
| `ESCALATE`                                        | Route the exception to the **Admin** queue (email Admin + mark exception `ESCALATED`). **An escalation is NOT an incident** (§7.11). | Manual / next run.                                           |
| `REQUEST_RECHECK`                                 | Ask the responsible party to re-verify / re-upload; sends a `recheck`-tagged email and marks the exception `AWAITING_RECHECK`.       | On next run with updated input.                              |

**Decision inputs:** exception data, configured business rules (§9), SLA status
(§9.6), responsible-party mapping (§9.4), historical cases from the audit/
notification history (cross-run state is available via SQLite — §8.5), and
current workflow state.

**Guardrails:**

- The planner **must not** modify reconciliation results or financial records.
- LLM output is parsed into a **Pydantic** model. If the LLM returns an action
  outside the allow-list (or malformed output), the system applies a
  deterministic fallback of **`ESCALATE`**, writes an audit entry, and emits
  telemetry — never a silent failure. **(v2)**
- **LLM call budget (v2):** a per-run cap (`max_llm_calls`, default 200) bounds
  cost; classification is **batched** and results are **cached by
  `mismatch_key`** so identical exceptions are not re-classified.
- The planner supports iterative re-planning after the verifier reports an
  outcome.

**Optional fuzzy-match step:** when residual unmatched orders _and_ settlements
exist, the planner may ask the LLM to propose pairings with a confidence score.
A deterministic node then auto-applies pairings with `confidence ≥ 0.85`, emits
a `FUZZY_MATCH_REVIEW` exception (→ Admin) for `0.5 ≤ confidence < 0.85`, and
discards the rest.

---

### 7.7 Communication Agent

When the planner selects an email action, the system sends a notification.

- Recipients are **configurable** in `config/settings.yaml` (store manager,
  per-gateway PG ops, bank, admin) — never hardcoded (§14).
- Email content is generated via **LLM-assisted drafting** with a deterministic
  **template fallback** if the LLM is unavailable.
- Email bodies are **plain text only** (no HTML-injection surface; LLM output is
  untrusted — §14).
- Every send attempt is recorded as `sent | failed | skipped` with the reason
  (§8.4). Email failure for one exception **must not** abort the run (§9.8).
- **Dry-run mode** (`dry_run=true` / `--dry-run`) short-circuits the real
  notifier so demos/tests never email real addresses. **(v2 — promoted to a
  functional requirement and acceptance item)**

---

### 7.8 Verifier Agent

After an action, the system verifies whether each exception is resolved or still
open.

For the prototype, verification is based on:

- **updated settlement input on rerun** — an exception is `RESOLVED` if the
  obligation now `MATCHED`,
- explicit success response from an action, or
- unchanged exception status → remains `OPEN`.

Open exceptions persist in SQLite (§8.5), so a later run can resolve them — this
also feeds the planner's "historical cases" input (§7.6).

`age_days` is computed as `as_of_date − order_date`, where `as_of_date` defaults
to today but is **overridable** (`--as-of`) for deterministic tests. **(v2)**

---

### 7.9 Telemetry and Observability

The system emits structured telemetry (JSON) for all major stages:

- workflow start / end,
- reconciliation start / end,
- exception creation,
- planner invocation / completion,
- tool invocation and tool success/failure,
- LLM prompt sent / response received / timeout,
- retries,
- circuit-breaker state changes,
- incident creation,
- admin notification.

Every workflow execution generates a unique **`run_id`** (UUID).

Every telemetry event includes at minimum: `run_id`, `timestamp`, `event_type`,
`component`, `entity_id` (when applicable), `status`, and `error_details` (when
applicable).

Telemetry must let a reviewer answer: why an action was taken, which tool
failed, what the LLM responded, how many retries occurred, why an exception
escalated, and whether a failure recovered automatically.

---

### 7.10 Audit Trail

An append-only audit entry is written for every significant event: file upload,
validation failure, reconciliation result, planner decision, email send attempt,
send success/failure, verification result, retry attempt, incident creation, and
admin notification.

Each audit record includes **(v2 — `reason` restored to match §7.10 prose)**:

- `timestamp`, `run_id`, `order_id` (nullable), `event_type`, `action`,
  `reason`, `status`, `details`.

Stored in the SQLite `audit_log` table (§8.5).

---

### 7.11 Incident Management

The system **must never silently fail.** Any failure that cannot be
automatically recovered creates an **incident** — an unrecoverable **system**
failure that prevents successful completion of a workflow step.

> **Incident vs ESCALATE (v2):** An **incident** is a _system_ failure (bad
> input, LLM/email exhausted, planner crash, config corruption). An
> **`ESCALATE`** is a _business_ action routing a valid exception to a human.
> They are **distinct** and tracked separately.

Examples: invalid input files, missing mandatory columns, LLM unavailable after
retries, email delivery failure after retries + open circuit breaker, planner
execution failure, configuration corruption, unsupported payment type.

Each incident contains: `incident_id`, `run_id`, `severity`
(`LOW \| MEDIUM \| HIGH \| CRITICAL`), `status` (`OPEN \| IN_PROGRESS \|
RESOLVED`), `failure_type`, `root_cause`, `timestamp`,
`remediation_recommendation`.

Severity is assigned by **deterministic rules**, never by the LLM (§10).

**Persistence (v2):** incidents are written as **JSON** under
`data/runtime/incidents/<incident_id>.json` **and** appended to
`data/runtime/incidents.jsonl`.

Row-level failures do **not** stop the run — the system continues processing
other valid records and raises a per-record incident (§12, §9.8).

---

### 7.12 Administrator Notification

When the system cannot recover, administrators are notified automatically
through a **durable channel that does not depend on the failing component**:

**Notification path (v2):** on every incident the system **always**

1. appends the incident to `data/runtime/incidents.jsonl`, and
2. prints a structured error to the console (stderr); CLI exits non-zero,

then **best-effort** emails the admin. If the admin email itself fails (e.g.
SMTP is the failing component), steps 1–2 still guarantee a durable record, so
the admin is never silently unreachable.

Notification content includes: `incident_id`, `run_id`, `order_id` (when
applicable), failure summary, failure timestamp, recovery attempts performed,
and recommended remediation. Secrets are never included (§14).

Triggers: repeated LLM failures, repeated email failures, invalid input
structure, workflow execution failure, configuration failure, incident creation.

---

### 7.13 Self-Healing and Recovery

The system attempts automatic recovery before escalating to an incident:

1. **retry** (transient errors only),
2. **exponential backoff**,
3. **alternate execution path** where applicable (e.g. template email when LLM
   drafting fails; mock/secondary notifier),
4. **circuit breaker** to stop hammering a failing dependency,
5. **escalation to an incident** after retries / breaker exhaustion.

Example: SMTP failure → retry → retry → retry → circuit opens
(`skipped:circuit_open`) → incident created → admin notified (§7.12).

Transient vs permanent errors are distinguished: permanent (4xx-class) errors
raise immediately without retry.

---

### 7.14 Idempotency

Re-processing the same inputs must not duplicate actions or audit side effects.

**Keys (v2 — newly specified):**

- **Action/notification key:** `mismatch_key = sha1(reason | order_id |
settlement_id | payment_type | recipient_role)`. A **unique index on
  `(mismatch_key, recipient_email)`** in `notification_log` makes
  "don't double-notify" a database invariant.
- **Run-level key:** `input_hash = sha256(orders_bytes + settlements_bytes)`. A
  rerun with the same `input_hash` reuses prior decisions; duplicate sends are
  recorded as `status="skipped" reason="duplicate"`.

Application-side checks run first (cheap); the DB constraint is the backstop.

---

## 8. Data Model

### 8.1 Order Row (obligation)

`order_id`, `order_date`, `store_id`, `amount`, `payment_type`,
`payment_amount`, `payment_gateway?`, `gateway_txn_id?`, `responsible_party?`,
`status`, `customer_name?`, `customer_email?`

### 8.2 Settlement Row

`settlement_id`, `settlement_date`, `gateway_txn_id?`, `order_id?`,
`reference_id?`, `payment_type`, `amount`, `fee?`, `net_amount`, `source`

### 8.3 Exception Record

`order_id?`, `settlement_id?`, `payment_type`, `expected_amount`,
`actual_amount`, `status`, `reason`, `age_days`, `responsible_party`,
`sla_status`, `mismatch_key`

### 8.4 Audit / Notification Records

- **Audit:** `timestamp`, `run_id`, `order_id?`, `event_type`, `action`,
  `reason`, `status`, `details`
- **Notification:** `id`, `run_id`, `mismatch_key`, `recipient_role`,
  `recipient_email`, `channel`, `status` (`sent \| failed \| skipped`), `error?`,
  `sent_at` — **unique index on `(mismatch_key, recipient_email)`**

### 8.5 Persistence schema (SQLite + JSON) **(v2)**

| Store              | Backing                        | Purpose                                                                                                                         |
| ------------------ | ------------------------------ | ------------------------------------------------------------------------------------------------------------------------------- |
| `run_log`          | SQLite                         | One row per run: `id`, `started_at`, `finished_at`, `status`, `input_hash`, `orders_count`, `settlements_count`, `summary_json` |
| `audit_log`        | SQLite                         | Append-only event stream (§8.4)                                                                                                 |
| `notification_log` | SQLite                         | One row per email attempt; unique `(mismatch_key, recipient_email)`                                                             |
| `exception_log`    | SQLite                         | Open/resolved exception lifecycle across runs (feeds verifier §7.8 + planner history §7.6); see §8.7                            |
| incidents          | JSON files + `incidents.jsonl` | One file per incident (§7.11)                                                                                                   |
| mock outbox        | `mock_outbox.jsonl`            | Emails captured in mock/dry-run mode                                                                                            |

### 8.6 Incident Record

`incident_id`, `run_id`, `severity`, `status`, `failure_type`, `root_cause`,
`timestamp`, `remediation_recommendation`

### 8.7 Exception Lifecycle Record **(v2)**

`mismatch_key` (pk), `run_id`, `reason`, `status`
(`open \| resolved \| escalated \| awaiting_recheck`), `first_seen`, `last_seen`.
Persisted in the SQLite `exception_log` (§8.5) so the verifier (§7.8) and the
planner's historical-cases input (§7.6) can track exceptions across runs.

---

## 9. Business Rules

1. Reconciliation must be **deterministic** (no LLM in the matching path).
2. The LLM is used **only** for planning, fuzzy-match proposals, message
   drafting, and explanations.
3. Financial matching must not depend on LLM output.
4. **Recipient resolution (v2):** the mismatch reason derives the **default**
   recipient role (§7.5a); an order row's `responsible_party`, when present,
   **overrides** it. Cash exceptions default to Store Manager; online-payment
   exceptions default to Payment Gateway / Bank.
5. Online-payment exceptions route to the order's payment gateway (or bank for
   settlement-side anomalies).
6. **SLA (v2):** if an online obligation is unmatched but still **within** its
   per-payment-type grace window, the planner may choose `WAIT`. After the grace
   window it becomes `ONLINE_MISSING` / `LATE_SETTLEMENT` and is emailed.
7. High-risk actions (auto-applied fuzzy matches, escalations) must be audited
   with rationale.
8. Email failure for one exception must not break the run.
9. The system must be safely rerunnable on the same input (§7.14).
10. Any unrecoverable failure must create an incident and notify the admin
    (§7.11–§7.12).

### 9.6 SLA model **(v2 — newly specified)**

Per-payment-type grace days in `config/settings.yaml`, e.g.
`CASH: 1, UPI: 1, CARD: 2, NETBANKING: 2, WALLET: 1`.
`age_days = as_of_date − order_date`;
`sla_status = WITHIN_SLA` if `age_days ≤ grace[payment_type]`, else `BREACHED`
(`NA` for cash deposits with no SLA configured). The matcher ignores SLA; only
the planner uses it (rule 6).

---

## 10. LLM Requirements

The LLM **is** used for: fuzzy-match proposals, action recommendation, email
drafting, short natural-language explanations, and classification support
(severity hinting).

The LLM is **never** used for: amount calculation, final match decision, audit
write logic, incident severity assignment, or business-rule enforcement.

The LLM sits behind a **provider abstraction** (`get_llm()`), so the backend can
switch models without touching business logic. The default provider is **Groq**
(free tier); a `MOCK_LLM=true` path returns canned, schema-valid responses so the
full pipeline runs **offline** in tests. **(v2)** All structured LLM output is
validated by Pydantic before use.

---

## 11. Success Metrics

The system is successful if it can: reconcile clean test files correctly; detect
missing cash and missing gateway settlements; recommend the correct action per
exception; send the correct email to the correct recipient; write an accurate
audit log; emit useful telemetry; generate incidents on unrecoverable failures;
notify the admin on escalation; and run end-to-end from the CLI with minimal
manual intervention.

Quality metrics: reconciliation accuracy, exception-classification accuracy,
email delivery success rate, audit completeness, telemetry coverage, incident
creation correctness, admin-notification success rate, idempotent-rerun success
rate.

---

## 12. Error Handling Requirements

The system must gracefully handle malformed files, missing columns, duplicate
order IDs, empty files, email-service failure, LLM timeout, invalid config,
unsupported payment type, and tool-execution failure.

For each failure the system must: log the error (no secrets), write an audit
entry, emit telemetry, retry where appropriate, **continue processing other
valid records**, and create an incident if the failure cannot be recovered.

---

## 13. Observability Requirements

The system provides structured logs, a run summary, and counters:
exception counts, action counts, email success/failure counts, retry counts,
incident counts, LLM call counts, and error traces.

A final run summary shows: total orders processed, total settlements processed,
matched obligations, unmatched obligations, actions taken, emails sent, emails
failed, incidents created, and audit entries written. Exposed via the CLI
summary and `GET /metrics`.

---

## 14. Security and Safety Requirements

- API keys and SMTP credentials live in **environment variables**, never the repo
  (`.env.example` only).
- Contact details live in `config/settings.yaml`, never hardcoded.
- Secrets are never written to logs, telemetry, or admin notifications.
- LLM prompts avoid unnecessary sensitive data; LLM output is treated as
  untrusted and validated by Pydantic; email bodies are plain text only.
- Uploads are size- and MIME-capped (§7.1) and parsed in memory.
- SQL goes through the SQLAlchemy ORM (no string concatenation).
- **Dry-run mode** prevents demos from emailing real addresses.
- **Hosted demo:** cloud secrets (`GROQ_API_KEY`, `RESEND_API_KEY`) live in
  **Azure Container Apps secrets** (env-injected), never in the image or repo;
  recipients are fixed by config/`RECIPIENT_*` env (users cannot make the agent
  email arbitrary addresses); the optional `DEMO_ACCESS_KEY` gates
  `POST /reconcile`; `MAX_LLM_CALLS` + upload caps bound spend; the container
  runs as **non-root**.
- **Recipient overrides:** `RECIPIENT_*` env vars take precedence over
  `config/settings.yaml`, so real demo inboxes are configured per-deployment
  without committing personal addresses to a public repo.

---

## 15. Tech Stack **(v2 — locked, aligned with PLAN.md)**

- Python 3.11+, packaged/managed with **uv** (lockfile committed)
- **FastAPI** (web upload + `/metrics` + `/runs/{id}`) and **Typer** CLI
  (`serve`, `run`, `demo`, `init-db`)
- **pandas** + **openpyxl** for `.xlsx`/`.csv`
- **Pydantic v2** for domain models and LLM-output validation
- **LangGraph** for the agent state machine
- **Groq** (`langchain-groq`) as the default LLM behind a provider abstraction;
  `MOCK_LLM` offline path
- **Resend** (default) / **SMTP** / **Mock** notifiers, swappable via config
- **SQLite** + **SQLAlchemy 2** for `run_log` / `audit_log` / `notification_log`
- **JSON / JSONL** for incidents and the mock outbox
- **structlog** (JSON logs, `run_id` contextvar)
- **tenacity** (retry) + **pybreaker** (circuit breaker)
- **YAML** for non-secret config
- **pytest** with `FakeListChatModel` + `MockNotifier` (offline tests)
- **ruff** + **mypy --strict**, GitHub Actions CI
- **Docker** (multi-stage `python:3.11-slim` + uv, non-root) for cloud/local parity
- **Azure Container Apps** (single replica) + **Azure Container Registry** for the
  hosted demo; **Resend** is the hosted notifier (HTTPS, no SMTP port-25 block)
- App binds `0.0.0.0:$PORT`; all writable state under a single `DATA_DIR`
  (ephemeral on the hosted demo by design)

---

## 16. Repository Deliverables

- source code,
- README (10-minute setup + run + test on-ramp),
- sample order & settlement files (`.xlsx` + `.csv`),
- sample config file (`config/settings.yaml`),
- tests (unit / integration / e2e),
- audit output example,
- incident output example (JSON),
- telemetry / log output example,
- `.env.example`,
- **`Dockerfile` + `.dockerignore`** and **`docs/deployment.md`** (Azure Container
  Apps deploy guide),
- **hosted demo URL** in the README for click-and-use evaluation.

---

## 17. Acceptance Criteria

The project is complete when:

1. two files can be **uploaded via the web page or passed via CLI**,
2. the system parses and validates them (with row-level errors),
3. reconciliation runs deterministically and classifies all five match statuses
   plus the order-level `ORDER_SUM_MISMATCH` data-quality check,
4. unmatched / partial / excess / duplicate cases are detected,
5. the LLM planner recommends an allow-listed action per exception (off-list →
   `ESCALATE` fallback),
6. emails are drafted and sent to the correct recipient (template fallback when
   the LLM is down),
7. audit logs are written for every significant event,
8. telemetry is emitted for each major step with a correlating `run_id`,
9. unrecoverable failures create incidents (JSON),
10. incidents trigger admin notification via the durable channel (§7.12),
11. **rerunning the same data produces zero duplicate emails** (`skipped:
duplicate`),
12. **dry-run mode** sends nothing real,
13. the README explains how to run and test the project,
14. the app **builds and runs as a container** (`docker run` serves `/healthz`
    and the upload UI; honours `$PORT`; runs non-root),
15. the project is **deployed to Azure Container Apps** with a reachable HTTPS
    URL, secrets set as Container Apps secrets, and one real Resend email
    delivered to a demo inbox from the hosted instance.

---

## 18. Final Product Definition

ReconcileFlow Agent is a small agentic finance-operations system that turns
uploaded order and settlement spreadsheets into automated reconciliation
decisions, email communication, telemetry, audit-ready outcomes, and
incident-based escalation when recovery is not possible. It is **deterministic
where correctness matters** and **agentic where reasoning and decision-making add
value**.

---

## Appendix A — Decision Log

Design choices resolved in v2 (previously ambiguous or missing in v1):

| #   | Question                  | Decision                                                                                                                                                                                                          |
| --- | ------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | Order↔settlement join key | Settlements carry `settlement_id`, `order_id`, `gateway_txn_id`; match `gateway_txn_id` → `(order_id, payment_type)`; leftovers drive the unmatched flow (§7.4a).                                                 |
| 2   | Persistence mechanism     | **SQLite** for `run/audit/notification`; **JSON/JSONL** for incidents & mock outbox. Non-goal reworded to "no server DB" (§4, §8.5).                                                                              |
| 3   | User interface            | **CLI + minimal FastAPI web upload** (§6, §7.1).                                                                                                                                                                  |
| 4   | Tech stack                | Adopt the locked stack: uv, FastAPI, LangGraph, structlog, tenacity, pybreaker (§15).                                                                                                                             |
| 5   | LLM provider              | **Groq** default behind a provider abstraction + offline `MOCK_LLM` path (§10).                                                                                                                                   |
| 6   | ESCALATE vs Incident      | **Distinct:** ESCALATE = business routing to Admin; Incident = unrecoverable system failure (§7.11).                                                                                                              |
| 7   | Recipient source of truth | Rules derive the default role; `responsible_party` **overrides** when present (§9.4).                                                                                                                             |
| 8   | SLA & late settlement     | **Config per-payment-type grace days**; planner may `WAIT` within grace; flag late after; deterministic `as_of_date` (§9.6, §7.8).                                                                                |
| 9   | Admin-notify fallback     | **Always** write incident JSONL + console error; email is best-effort (§7.12).                                                                                                                                    |
| 10  | Obligation-sum validation | **Yes** — order-level `ORDER_SUM_MISMATCH` when `sum(payment_amount) != amount`; `status` reuses `EXCESS`/`PARTIALLY_MATCHED` (over/under), `reason` is authoritative; independent of settlement matching (§7.2). |
| 11  | Deployment target         | **Azure Container Apps** (single replica) + ACR; container binds `$PORT`, external HTTPS ingress, `/healthz` probe (PLAN §6.7, Phase 8).                                                                          |
| 12  | Hosted notifier & email   | **Resend** real delivery to configured demo inboxes; `RECIPIENT_*` env overrides keep real addresses out of the repo (§14, §15).                                                                                  |
| 13  | Hosted persistence        | **Ephemeral** (resets on restart) — acceptable for the demo; durability via mounted Azure Files is documented future work (§4, §15).                                                                              |
| 14  | Hosted-demo hardening     | Fixed recipients, optional `DEMO_ACCESS_KEY` gate, `MAX_LLM_CALLS` + upload caps, non-root container, secrets in Container Apps (§14).                                                                            |
| 15  | Real Groq in hosted demo  | LLM key server-side in Container Apps secrets (the reason to host); `MOCK_LLM` remains for offline tests (§10, §15).                                                                                              |

### Other gaps fixed inline

- `PARTIALLY_MATCHED`, `EXCESS`, `DUPLICATE` now defined (§7.4b).
- `payment_type`, `payment_gateway`, `status`, `source`, `responsible_party`,
  severity, and action values are now enumerated.
- `reason` restored to the Audit Record schema (§7.10, §8.4).
- Idempotency keys specified (`mismatch_key`, `input_hash`) (§7.14).
- Off-list LLM action → deterministic `ESCALATE` fallback (§7.6).
- LLM per-run call budget + classification caching (§7.6).
- Input size / row-count caps (§7.1).
- `age_days` clock defined via overridable `as_of_date` (§7.8).
- Dry-run promoted to a functional + acceptance requirement (§7.7, §17).

---

_End of PRD v2._
