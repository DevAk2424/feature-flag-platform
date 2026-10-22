# Observability

- Every Java service exposes Spring Boot Actuator: `/actuator/health`,
  `/actuator/metrics`, `/actuator/prometheus` (micrometer registry).
- `infra/prometheus/prometheus.yml` scrapes both Java services.
- Suggested alerts: gateway `stale=true` for > 60s (control plane / broker
  outage — clients are on last-known-good), config version lag between
  control plane and gateway, AI proposal approval rate anomalies.
- Audit log (control plane `/api/audit`) is the system of record for who
  changed what, including `risk-agent-approved-by:<approver>` entries.
- Structured event IDs: every FlagConfigEvent and FlagCommandEvent carries a
  unique id + config version, so a change can be traced dashboard -> gateway
  stream -> control plane audit -> AI proposal.
