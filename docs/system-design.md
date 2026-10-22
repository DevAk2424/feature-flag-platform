# System Design — Distributed Feature Flag and Release Control Platform

A LaunchDarkly-style system: a control plane owns flag configuration; SDKs embedded in
application instances evaluate flags locally; releases are rolled out gradually,
observed, and — when metrics regress — held or rolled back under human-approved,
agent-recommended control.

Labels used below: **[Implemented]** = real code in this repo. **[Design note]** = the
production-scale extension, deliberately not built in a stdlib reference implementation.

---

## 1. Low-latency evaluation in SDKs — [Implemented]

**Problem.** A flag check sits on hot request paths. A network call per check adds
latency, cost, and a hard dependency on the control plane.

**Design.** Evaluation (`featureflags/engine.py:evaluate`) is a pure, deterministic
function of `(flag config, user context)`: kill switch → explicit targets → ordered
targeting rules → fallthrough rollout. The SDK (`featureflags/sdk.py`) holds the whole
config in memory, so `evaluate()` is dict lookup + SHA-256 bucketing + rule matching —
microseconds, zero I/O, and safe to call per request / per user.

**Trade-off.** Config is eventually consistent (bounded by poll interval). Flags are
the right place for that trade: a few seconds of propagation lag buys independence
from control-plane latency and outages.

## 2. Configuration propagation & cache invalidation — [Implemented] + [Design note]

**Implemented.** SDKs poll `GET /v1/config?env=prod`. The snapshot carries a global
`version` and is served with an `ETag`; `If-None-Match` (or `?version=`) returns
**304** when the client is current, so steady-state polling is cheap. The SDK applies
a snapshot **only if its version is strictly greater** than the held version — a
stale / replayed / out-of-order response can never roll a client backwards.

**Design note (push).** Polling is the simple, robust baseline. At scale, add a
streaming channel (SSE or WebSocket "config changed, new version = N" notifications,
with polling as fallback and jittered reconnects) to cut propagation from seconds to
sub-second without changing the version contract — the version check, not the
transport, is the correctness mechanism.

## 3. High availability during control-plane outages — [Implemented]

The SDK keeps a **last-known-good cache** (in memory, optionally persisted to a JSON
file so a restarted process can evaluate before its first successful poll). When
polling fails, evaluation continues from the stale cache, `client.stale` is set, and
nothing raises into the host application. When the control plane returns, the next
poll resyncs by version. This is tested directly (`test_stale_cache_after_control_plane_down`).

**Design note.** In production the control plane itself is replicated behind a load
balancer with the flag store in a replicated datastore; snapshots can additionally be
published to a CDN / object storage so SDKs can fetch config even if the API tier is
fully down (read path decoupled from write path).

## 4. Percentage rollouts, targeting & stable hashing — [Implemented]

- **Bucketing:** `SHA-256(flag_key + "." + salt + "." + user_key)` → first 32 bits →
  bucket `0..9999`. Deterministic across processes and languages (unlike Python's
  salted `hash()`), needs no per-user assignment storage, and distributes uniformly
  (tested: 50% rollout lands within tolerance over 4,000 users).
- **Monotonic rollouts:** inclusion is `bucket < percentage × 100`, so raising
  10% → 25% → 50% only ever *adds* users. Tested by asserting set inclusion across
  increasing percentages — the property that makes gradual rollouts safe.
- **Salt** per flag decorrelates assignments: the same user landing in "checkout"
  says nothing about "recommendations", and two flags at 10% don't expose the same
  10% of users unless intended.
- **Targeting:** ordered rules of clauses over user attributes — `equals`, `in`,
  `startsWith`, `contains`, numeric `gt/gte/lt/lte`, `regex`, existence — plus
  explicit user allow-lists ("targets", segment-style rules included as a rule over
  a `segment` attribute). First matching rule wins; rules can themselves be rolled
  out. Every result carries a **reason** (`KILL_SWITCH`, `TARGET_MATCH`,
  `RULE_MATCH`, `FALLOUT_ROLLOUT`, `FLAG_NOT_FOUND`), which is what makes
  "why did this user see this?" answerable in support and in audits.

## 5. Version consistency, rollback & auditability — [Implemented]

- Every write through the service layer (`featureflags/store.py`) increments the
  flag's **monotonic version** and the global config version, and stores a full
  snapshot in per-flag history.
- **Rollback = forward write:** restoring version *N* creates version *N+k* whose
  payload is the old snapshot. Rolling numbers backwards would break the SDK version
  guard (clients ignore older versions), so "backwards in content, forwards in
  version" is the only consistent semantics — and it keeps rollback itself auditable
  and reversible.
- **Audit log:** every mutation records actor, timestamp, action, old value, new
  value, and resulting version (`GET /v1/audit`). Risk-agent executions are audited
  under `risk-agent-approved-by:<approver>`, so automated and human changes are
  distinguishable in the same log.

## 6. AI release-risk agent + guarded execution — [Implemented]

**Inputs.** Per-flag metrics ingested via `POST /v1/.../metrics`: error rate, p95
latency, success/conversion rate, each against a baseline (control / pre-rollout),
plus sample size.

**Decision rules (deterministic & explainable — deliberately no LLM in this path):**

| Condition | Recommendation |
|---|---|
| sample < 100 | `HOLD` — insufficient data (acting on noise is worse than waiting) |
| error Δ ≥ +5pp, or ≥ 2 severe signals (error Δ ≥ +2pp, latency Δ ≥ +150ms, success Δ ≤ −5pp) | `ROLLBACK` (suggested rollout 0%) |
| any moderate regression (error Δ ≥ +0.5pp, latency Δ ≥ +50ms, success Δ ≤ −2pp) | `HOLD` at current % |
| all within tolerance | `CONTINUE_ROLLOUT` at current + 25% (capped at 100%) |

Every recommendation includes reasons, a confidence, and the exact deltas used —
a release decision must be reproducible in a postmortem, which an opaque model
score is not.

**Guarded execution.** Analysis never mutates state. It creates a **proposal**
carrying a one-time approval token. `approve(proposal_id, approver, token)` is the
only execution path; it (a) requires the matching token, (b) refuses HOLDs and
double-execution, (c) caps increases at **+25% per approval**, (d) applies through
the same `FlagStore` used by human API calls, so agent actions get versions,
history, and audit entries for free. Kill-switch / rollback suggestions get no
shortcut around approval either.

**Design note.** In production you'd add: per-environment approval policies
(e.g. two approvers for prod rollbacks), proposal expiry, metric-source signing,
and alerting on proposal creation (PagerDuty/Slack) — policy around the same
proposal primitive.

## 7. Scaling notes — [Design note]

- **Snapshot distribution:** config is small and read-heavy — publish versioned
  snapshots to object storage + CDN; SDKs fetch from edge, control plane stays
  off the hot path entirely.
- **Store:** replace the in-memory store with PostgreSQL (flags/history/audit,
  transactional version bumps) or a Redis-backed read model fed from Postgres.
- **Change events:** mutations emit to Kafka (audit stream, cache busting,
  downstream analytics, warehouse export) instead of only an in-process list.
- **Metrics pipeline:** ingest via a collector (e.g. OpenTelemetry → Kafka →
  ClickHouse), with the risk agent reading windowed aggregates per flag/variation.
- **Evaluation at edge / serverless:** the engine's purity ports directly — same
  bucketing contract evaluated in a worker close to the user.
- **Multi-region:** flags are small, append-friendly data: active-active replication
  with version + last-writer metadata, regional read replicas, global write
  failover runbook.

## 8. Mapping to a Java / Spring Boot production version

Same modules, idiomatic Java — the design (contracts, versions, reasons, guardrails)
does not change:

| This repo (Python) | Spring Boot production |
|---|---|
| `engine.py` (pure evaluation, SHA-256 bucketing) | `flag-engine` library module: immutable `Flag` records, `EvaluationEngine` service, identical bucketing spec (cross-language test vectors) |
| `store.py` (service layer) | `@Service FlagService` over Spring Data JPA (PostgreSQL): `@Version` optimistic locking for monotonic versions, history + audit tables, `@Transactional` writes |
| `server.py` (`http.server`) | `@RestController` APIs, Spring Security filter for API keys / OAuth2, ETag via `ShallowEtagHeaderFilter` / explicit `ResponseEntity` |
| `sdk.py` (poller + cache) | Java SDK jar: scheduled poller / SSE client, `ConcurrentHashMap` last-known-good cache, identical stale/version semantics |
| `risk_agent.py` | `risk-agent` service: scheduled metric evaluation, proposal entities + approval endpoints, Spring events → Kafka audit stream |
| `static/` dashboard | React/Angular SPA calling the same REST API |
| `unittest` suite | JUnit 5 + Testcontainers (Postgres/Kafka) + contract tests sharing hashing test vectors with the Python version |

The deliberate lesson of the portfolio: **the language is interchangeable; the
contracts — stable bucketing, monotonic versions, forward rollback, proposal-gated
automation — are the product.**
