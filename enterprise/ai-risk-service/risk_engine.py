"""Deterministic, explainable release-risk engine (ported from v1).

Release decisions must be reproducible and auditable, so this is a rules
engine, not an LLM call: same metrics in -> same recommendation out, with
the numbers and reasons attached.
"""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
import time, uuid

CONTINUE = "CONTINUE_ROLLOUT"; HOLD = "HOLD"; ROLLBACK = "ROLLBACK"
MIN_SAMPLE_SIZE = 100
MAX_STEP_INCREASE = 25.0
ERROR_ROLLBACK_DELTA = 0.05; ERROR_SEVERE_DELTA = 0.02
LATENCY_SEVERE_MS = 150.0; SUCCESS_SEVERE_DELTA = -0.05
ERROR_MODERATE_DELTA = 0.005; LATENCY_MODERATE_MS = 50.0; SUCCESS_MODERATE_DELTA = -0.02

@dataclass
class Recommendation:
    flag_key: str; action: str; reasons: list; confidence: float
    metrics_used: dict; suggested_percentage: float | None = None
    def to_dict(self): return asdict(self)

@dataclass
class Proposal:
    id: str; flag_key: str; recommendation: Recommendation; approval_token: str
    status: str = "PENDING"; created_at: float = field(default_factory=time.time)
    executed_by: str | None = None
    def public_dict(self):
        d = asdict(self); d["recommendation"] = self.recommendation.to_dict(); return d

def _num(metrics, name, default=0.0):
    try: return float(metrics.get(name, default))
    except (TypeError, ValueError): return default

def analyze_metrics(flag_key, metrics):
    sample = int(_num(metrics, "sample_size", 0))
    err_delta = _num(metrics, "error_rate") - _num(metrics, "baseline_error_rate")
    lat_delta = _num(metrics, "latency_p95_ms") - _num(metrics, "baseline_latency_p95_ms")
    suc_delta = _num(metrics, "success_rate", 1.0) - _num(metrics, "baseline_success_rate", 1.0)
    current_pct = _num(metrics, "current_rollout_percentage", 0.0)
    used = {"sample_size": sample, "error_rate_delta": round(err_delta, 4),
            "latency_p95_delta_ms": round(lat_delta, 1), "success_rate_delta": round(suc_delta, 4),
            "current_rollout_percentage": current_pct}
    if sample < MIN_SAMPLE_SIZE:
        return Recommendation(flag_key, HOLD,
            [f"Insufficient data: sample_size={sample} < minimum {MIN_SAMPLE_SIZE}; cannot judge risk."],
            0.40, used, suggested_percentage=current_pct)
    severe = []
    if err_delta >= ERROR_SEVERE_DELTA: severe.append(f"error_rate up {err_delta:.1%} vs baseline")
    if lat_delta >= LATENCY_SEVERE_MS: severe.append(f"latency p95 up {lat_delta:.0f}ms vs baseline")
    if suc_delta <= SUCCESS_SEVERE_DELTA: severe.append(f"success rate down {abs(suc_delta):.1%} vs baseline")
    if err_delta >= ERROR_ROLLBACK_DELTA or len(severe) >= 2:
        return Recommendation(flag_key, ROLLBACK,
            [f"Severe regression: {s}" for s in severe] or [f"error_rate up {err_delta:.1%} vs baseline"],
            0.90, used, suggested_percentage=0.0)
    moderate = []
    if err_delta >= ERROR_MODERATE_DELTA: moderate.append(f"error_rate up {err_delta:.2%} vs baseline")
    if lat_delta >= LATENCY_MODERATE_MS: moderate.append(f"latency p95 up {lat_delta:.0f}ms vs baseline")
    if suc_delta <= SUCCESS_MODERATE_DELTA: moderate.append(f"success rate down {abs(suc_delta):.2%} vs baseline")
    if moderate:
        return Recommendation(flag_key, HOLD, [f"Moderate regression, hold rollout: {m}" for m in moderate],
            0.65, used, suggested_percentage=current_pct)
    nxt = min(current_pct + MAX_STEP_INCREASE, 100.0)
    return Recommendation(flag_key, CONTINUE,
        [f"All guardrail metrics within tolerance vs baseline (error {err_delta:+.2%}, latency {lat_delta:+.0f}ms, success {suc_delta:+.2%})."],
        0.85 if sample >= 1000 else 0.75, used, suggested_percentage=nxt)
