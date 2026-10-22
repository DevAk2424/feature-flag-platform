"""Metrics ingestion: streaming consumer abstraction.

Production consumes the `flag-metrics` Kafka topic. The sandbox uses the
HTTP ingest endpoint (POST /metrics) which feeds the same in-process
consumer, so the risk engine never cares which transport delivered a sample.
"""
from __future__ import annotations
import os
from collections import deque

class InProcessMetricsConsumer:
    def __init__(self): self._latest: dict[str, dict] = {}; self._history: dict[str, deque] = {}
    def on_metrics(self, flag_key: str, metrics: dict):
        self._latest[flag_key] = metrics
        self._history.setdefault(flag_key, deque(maxlen=500)).append(metrics)
    def latest(self, flag_key: str): return self._latest.get(flag_key)
    def history(self, flag_key: str): return list(self._history.get(flag_key, []))

class KafkaMetricsConsumer:
    """Production consumer for `flag-metrics` (requires kafka-python)."""
    def __init__(self, sink: InProcessMetricsConsumer, bootstrap: str | None = None):
        try:
            from kafka import KafkaConsumer  # type: ignore
        except ImportError as e:
            raise RuntimeError("kafka-python not installed; see requirements.txt / prod profile") from e
        self._sink = sink
        self._consumer = KafkaConsumer("flag-metrics", bootstrap_servers=bootstrap or os.environ.get("KAFKA_BOOTSTRAP", "localhost:9092"),
                                       value_deserializer=lambda b: __import__("json").loads(b.decode()))
    def run_forever(self):
        for msg in self._consumer:
            payload = msg.value
            self._sink.on_metrics(payload["flag_key"], payload.get("metrics", {}))
