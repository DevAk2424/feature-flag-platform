# Distributed Feature Flag and Release Control Platform

A LaunchDarkly-style feature-flag platform built by **Akshay K** as a system-design
portfolio project: flag configuration is distributed to application instances, evaluated
locally at low latency, rolled out gradually, kill-switched instantly, and guarded by an
**AI release-risk agent** that recommends rollout / hold / rollback — but can only act
through a human-approved, audit-logged proposal.

Implemented in **Python 3.12 standard library only** (no pip dependencies), so it runs
and tests anywhere. See `docs/system-design.md` for the deep dive and how the same
modules map to a Java / Spring Boot production version.

## Architecture

```
                        +-------------------------------+
        dashboard ----> |        Control Plane          |
        (static JS)     |  featureflags/server.py       |
                        |  ThreadingHTTPServer, REST    |
                        +-------+---------------+-------+
                                |               |
                         FlagStore         RiskAgent
                     (versions, history,   (analyze ->
                      audit, metrics)       proposal -> approve)
                                |
                    GET /v1/config?env=prod   (version + ETag, 304)
                                |
                        +-------v---------------+
                        |   SDK (sdk.py)        |   in every app instance
                        |  poll -> local cache  |
                        |  evaluate(): NO       |
                        |  network, stale-safe  |
                        +-------+---------------+
                                |
                        engine.evaluate()
                     hashing / rules / rollout
```

Components:

| Module | Responsibility |
|---|---|
| `featureflags/engine.py` | Pure evaluation: stable SHA-256 bucketing, % rollouts, targeting rules, kill switch, evaluation reasons |
| `featureflags/store.py` | Service layer: CRUD, monotonic versions, history snapshots, rollback, audit log, metrics |
| `featureflags/server.py` | Control-plane REST API + dashboard hosting |
| `featureflags/sdk.py` | Client SDK: polling, ETag/version cache invalidation, last-known-good offline evaluation |
| `featureflags/risk_agent.py` | Deterministic release-risk analysis + guarded proposals |
| `featureflags/static/` | Dashboard (flag list, rollout + kill-switch controls, risk panel, audit view) |
| `demo.py` | Scripted end-to-end story (see below) |
| `tests/` | 32 unittest tests (stdlib only) |

## Quick start

```bash
# Run the control plane + dashboard
python3 -m featureflags.server --port 8080
# Dashboard:  http://127.0.0.1:8080/
# Health:     http://127.0.0.1:8080/health

# Run the demo (separate terminal / no server needed)
python3 demo.py

# Run the tests
python3 -m unittest discover -s tests -v
```

**Demo API key** (documented demo credential, not a real secret): `demo-api-key-12345`,
sent as the `x-api-key` header on every `/v1` request. Override with the
`FEATUREFLAG_API_KEY` environment variable.

## API examples

```bash
KEY="x-api-key: demo-api-key-12345"
BASE=http://127.0.0.1:8080

# List flags / create a flag
curl -H "$KEY" $BASE/v1/flags
curl -X POST -H "$KEY" -H 'Content-Type: application/json' $BASE/v1/flags \
  -d '{"key":"new-checkout","fallthrough_percentage":5}'

# Gradual rollout + kill switch (every write bumps version + audit)
curl -X PATCH -H "$KEY" $BASE/v1/flags/new-checkout -d '{"fallthrough_percentage":25}'
curl -X PATCH -H "$KEY" $BASE/v1/flags/new-checkout -d '{"enabled":false}'

# Versioned config snapshot for SDKs (ETag / 304 supported)
curl -H "$KEY" "$BASE/v1/config?env=prod"
curl -H "$KEY" -H 'If-None-Match: "3"' "$BASE/v1/config?env=prod"   # -> 304 when current

# Roll back to a previous version (restored as a NEW version)
curl -X POST -H "$KEY" $BASE/v1/flags/new-checkout/rollback -d '{"to_version":1}'

# Audit log
curl -H "$KEY" "$BASE/v1/audit?flag_key=new-checkout"

# Ingest metrics, then ask the risk agent for a proposal
curl -X POST -H "$KEY" $BASE/v1/flags/new-checkout/metrics \
  -d '{"sample_size":5000,"error_rate":0.09,"baseline_error_rate":0.01,
       "latency_p95_ms":520,"baseline_latency_p95_ms":200,
       "success_rate":0.90,"baseline_success_rate":0.98}'
curl -X POST -H "$KEY" $BASE/v1/risk/proposals -d '{"flag_key":"new-checkout"}'
# -> proposal {id, approval_token, recommendation}. Nothing has changed yet.
curl -X POST -H "$KEY" $BASE/v1/risk/proposals/<id>/approve \
  -d '{"approver":"your-name","approval_token":"<token-from-proposal>"}'
```

## SDK usage

```python
from featureflags.sdk import FeatureFlagClient

client = FeatureFlagClient("http://127.0.0.1:8080", cache_file="ff-cache.json")
client.start_polling()                      # background poller thread

if client.is_enabled("checkout-redesign", user_id,
                     {"segment": "beta", "plan": "pro"}):
    new_checkout()
# If the control plane dies, evaluate() keeps working from the
# last-known-good cache and client.stale becomes True.
```

## Design decisions (summary)

- **Local evaluation, not remote calls** — evaluation is a pure function, so SDKs are
  fast, cheap, and outage-proof; the network is only for config distribution.
- **Stable hashing over user assignment tables** — SHA-256 bucketing needs no stored
  per-user state and is monotonic: raising a rollout % never drops an included user.
- **Rollback is a forward write** — restoring an old snapshot as a new version keeps
  version-based cache invalidation correct (clients ignore older versions).
- **The risk agent proposes, humans dispose** — no direct mutation path exists from
  analysis to flags; approval requires the proposal's token and is rate-capped
  (+25% max per step) and audit-logged under the approver's name.
- **Deterministic agent, no LLM in the decision path** — release decisions must be
  reproducible and explainable: every recommendation ships its reasons, confidence,
  and the exact deltas used.
- **Stdlib-only reference implementation** — the point is the design; the mapping to
  Spring Boot / Redis / Kafka / CDN distribution is documented in
  `docs/system-design.md`.

## Demo story (`python3 demo.py`)

Seeds `checkout-redesign` (10% rollout, beta rule), `ai-recommendations` (50%) and
kill-switched `legacy-search`; evaluates several users; ingests a bad release's
metrics; the agent recommends **ROLLBACK** as a pending proposal; the flag provably
does not change; a human approves with the token; the rollout goes to 0% as a new
version with a `risk-agent-approved-by:...` audit entry.

## Limitations (honest)

In-memory store (no persistence across restarts, file cache covers SDK side only),
polling rather than push streaming, single-node control plane, demo-grade API-key
auth. These are deliberate for a reference implementation; production replacements
are spelled out in `docs/system-design.md`.
