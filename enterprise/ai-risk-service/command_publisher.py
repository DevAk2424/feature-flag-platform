"""Command-event publishing: how an APPROVED proposal reaches the control plane.

The AI service never writes the flag database. It emits a FlagCommandEvent
onto the `flag-commands` stream; the control plane consumes it and applies
the change through its own service layer (versioned + audit-logged).
Transports: Kafka in production; HTTP POST to the control plane's streaming
command ingress in the sandbox profile; in-memory for tests.
"""
from __future__ import annotations
import json, os, urllib.request

class InMemoryCommandPublisher:
    def __init__(self): self.events = []
    def publish(self, event: dict): self.events.append(event)

class HttpCommandPublisher:
    """Sandbox transport: POST the command event to the control plane."""
    def __init__(self, base_url: str | None = None):
        self.base_url = (base_url or os.environ.get("CONTROL_PLANE_URL", "http://localhost:8080")).rstrip("/")
    def publish(self, event: dict):
        req = urllib.request.Request(self.base_url + "/internal/commands",
            data=json.dumps(event).encode(), headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode())

class KafkaCommandPublisher:
    """Production transport: Kafka topic `flag-commands` (requires kafka-python)."""
    def __init__(self, bootstrap: str | None = None):
        try:
            from kafka import KafkaProducer  # type: ignore
        except ImportError as e:
            raise RuntimeError("kafka-python not installed; use prod profile with requirements-prod or the HTTP sandbox transport") from e
        self._producer = KafkaProducer(bootstrap_servers=bootstrap or os.environ.get("KAFKA_BOOTSTRAP", "localhost:9092"),
                                       value_serializer=lambda v: json.dumps(v).encode())
    def publish(self, event: dict):
        self._producer.send("flag-commands", key=event["flagKey"].encode(), value=event)
        self._producer.flush()
