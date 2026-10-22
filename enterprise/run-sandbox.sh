#!/usr/bin/env bash
# Run Enterprise v2 in the sandbox profile (no Docker / Kafka needed).
# Java services use H2 + the in-process streaming bus; the gateway subscribes
# to the control plane's internal SSE event feed; the AI service uses the
# HTTP command transport. Production uses the `prod` profile (Kafka + Postgres)
# via infra/docker-compose.yml instead.
set -euo pipefail
export JAVA_HOME="${JAVA_HOME:-$HOME/workspace/tools/jdk21}"
export PATH="$JAVA_HOME/bin:$PATH"
cd "$(dirname "$0")"
mvn -o -q package -DskipTests || mvn -q package -DskipTests
java -jar control-plane-service/target/control-plane-service-2.0.0.jar &
java -jar streaming-gateway-service/target/streaming-gateway-service-2.0.0.jar &
(cd ai-risk-service && COMMAND_TRANSPORT=http CONTROL_PLANE_URL=http://localhost:8080 .venv/bin/uvicorn app:app --port 8090 &)
echo "Control plane :8080 · Gateway :8081 · AI :8090 · Frontend: (cd frontend && npm run dev) :5173"
wait
