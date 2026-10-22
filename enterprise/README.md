# Enterprise v2 — inside this folder

The v2 enterprise implementation lives here, alongside the v1 Python
reference implementation (repo root, unchanged). v1 stays runnable and its
32 tests still pass; v2 is the microservices evolution of the same design.

| Folder | Stack | Role |
|---|---|---|
| `flag-common/` | Java 21 library | Domain model, SHA-256 bucketing, evaluation engine (ported from v1) |
| `control-plane-service/` | Java 21, Spring Boot (MVC + JPA) | Flag CRUD, versioning, history, audit; publishes `flag-config-events` |
| `streaming-gateway-service/` | Java 21, Spring Boot WebFlux | Consumes config events; SSE stream (snapshot + deltas + heartbeat) to clients; last-known-good |
| `ai-risk-service/` | Python 3.12, FastAPI | Risk engine + guarded proposals; emits `flag-commands` events only after human approval |
| `frontend/` | React 18 + Vite | Dashboard on the SSE stream; rollout/kill-switch commands; risk panel; audit view |
| `infra/` | Docker Compose, Kubernetes, Prometheus | Local/prod deployment, observability |

Streaming-first: config propagation is Kafka topics + SSE, not REST polling.
REST remains only for management commands and bootstrap snapshots — see
`../docs/system-design.md` for the full design and the honest
implemented-vs-production-designed split, and `../TEST_RESULTS.md` for the
test evidence from the sandbox run.
