# Test Results — Enterprise v2 (and v1 legacy)

Generated from suites **actually run in the Muse sandbox** on
**2026-10-22 (UTC)**. Every number below is copied from a real run; known
sandbox limitations are stated where they affected how a suite was run.

## Environment

| Tool | Version |
|---|---|
| JDK | Temurin OpenJDK 21.0.12.1+1 LTS (`java -version`) |
| Maven | Apache Maven 3.9.9 |
| Python | 3.12.3 (FastAPI 0.159.1 in the ai-risk-service venv) |
| Node / npm | v24.20.0 / 10.9.4 |
| OS | Linux sandbox VM (no Docker, no Kafka broker available) |

> **Sandbox network note (important, honest):** this sandbox's permission
> `other_tcp` is set to *Deny*, which blocks **outbound TCP connections
> initiated by Java processes** — even to `127.0.0.1` (the interceptor
> returns a plain-text notice instead of an HTTP response). Consequences:
> (1) Maven dependencies were fetched with `curl` into the local
> `~/.m2/repository` and all Maven runs below use **offline mode**
> (`mvn -o`); the commands are identical to a normal `mvn test` once
> dependencies are cached. (2) Java tests use MockMvc /
> context-bound WebTestClient (no real sockets). (3) In the integration
> smoke, the gateway's own HTTP subscription to the control plane could
> not connect, so the config event was delivered through the gateway's
> internal event-ingress endpoint, which exercises the *same*
> `applyEvent` path as its Kafka consumer. In any normal environment
> (laptop, CI, Docker) none of these workarounds are needed.

## Results summary

| Suite | Command | Run | Passed | Failed |
|---|---|---|---|---|
| Java — flag-common (JUnit 5) | `mvn -o test -pl flag-common` | 8 | 8 | 0 |
| Java — control-plane-service (JUnit 5, SpringBootTest + MockMvc) | `mvn -o test -pl control-plane-service` | 6 | 6 | 0 |
| Java — streaming-gateway-service (JUnit 5, StepVerifier + WebTestClient) | `mvn -o test -pl streaming-gateway-service -am` | 3 | 3 | 0 |
| **Java — full reactor** | `mvn -o test` (in `enterprise/`) | **17** | **17** | **0** |
| Python — ai-risk-service unit tests (unittest) | `.venv/bin/python -m unittest discover -s tests` | 10 | 10 | 0 |
| Python — ai-risk-service API tests (pytest, FastAPI TestClient) | `.venv/bin/python -m pytest tests/test_api.py -q` | 2 | 2 | 0 |
| Python — v1 legacy suite (unittest, unchanged) | `python3 -m unittest discover -s tests` (repo root) | 32 | 32 | 0 |
| React — frontend unit tests (Vitest) | `npm test` (in `enterprise/frontend`) | 5 | 5 | 0 |
| React — frontend production build | `npm run build` | — | **success** | — |

Full-reactor Maven footer from the final verification run:
`Tests run: 8 / 6 / 3, Failures: 0, Errors: 0 — BUILD SUCCESS`.

Frontend build artifacts: `dist/index.html` 0.42 kB,
JS bundle 150.32 kB (gzip 48.48 kB), CSS 1.81 kB.

## What the tests cover

- **flag-common**: SHA-256 bucket stability/range, monotonic rollout
  inclusion, 0%/100% edges, rollout distribution (~50% within 44–56%),
  kill switch beating targets, target match, rule operators + ordering,
  FLAG_NOT_FOUND.
- **control-plane**: create/version/audit, rollout patching, kill switch
  evaluation, rollback as a new forward version, **streaming event
  publication on mutation**, approved `FlagCommandEvent` application
  (actor `risk-agent-approved-by:<approver>`), snapshot + actuator
  endpoints over MockMvc. Persistence: Spring Data JPA on H2.
- **streaming-gateway**: SSE stream emits **snapshot first, then a live
  delta** when a flag event is applied; `/api/config` serves the
  last-known-good snapshot with `stale=true` after source disconnect;
  SSE content type.
- **ai-risk-service**: healthy -> CONTINUE (capped +25%), error spike ->
  ROLLBACK, low sample -> HOLD, moderate regression -> HOLD; guarded
  execution: proposal alone publishes nothing, wrong token publishes
  nothing (403 over HTTP), approved proposal publishes exactly one
  `flag-commands` event, double approval refused, HOLD not executable,
  reject marks proposal and publishes nothing.
- **v1 legacy**: the original 32 tests, untouched and still passing.
- **frontend utils**: SSE delta application, snapshot merge, kill-switch
  labelling, risk tones, rollout clamping.

## Integration smoke (sandbox profile, real processes)

Started from the built jars/venv on 2026-10-22 ~01:01–01:05 UTC:
control-plane (:8080), streaming-gateway (:8081), ai-risk-service
(:8090, `COMMAND_TRANSPORT=http`), plus the built frontend `dist/`
served statically (:4173). All health checks passed.

Verified end-to-end:
1. Control plane seeded `checkout-redesign` at 10% and `legacy-search`
   kill-switched; snapshot reported `configVersion=3`.
2. `PATCH rollout -> 30%` on the control plane (flag v2, config v4).
3. The config event was applied by the gateway; an open **SSE stream
   received the snapshot event and then the `flag-config` delta
   containing the 30% rollout** (see sandbox network note above for why
   the event was delivered via the gateway's internal ingress endpoint
   instead of its HTTP subscription).
4. AI risk flow: spike metrics -> proposal -> recommendation
   **ROLLBACK (confidence 0.90)** -> approve with the one-time token ->
   command event -> control plane flag went to **0% (v3)**, and the
   audit log contains the `risk-agent-approved-by:akshay` entry.
5. Frontend `dist/` served with HTTP 200 and the correct page title.
6. All services were stopped after the smoke; ports confirmed closed.

## Not run in this sandbox (designed, code written)

Kafka as a live broker, Postgres as the live database, Docker Compose
and Kubernetes deployments — no Docker/broker exists in this sandbox.
The Kafka producer/consumer code, JPA prod profile (Postgres),
Dockerfiles, Compose file and K8s manifests are in `enterprise/infra/`
and the service repos for execution in a normal environment.
