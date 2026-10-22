"""AI release-risk agent (deterministic, explainable, guarded).

This is a rules-based agent, not an LLM call: release decisions must be
reproducible and auditable, so the same metrics always produce the same
recommendation, with the numbers and reasons attached.

Guarded execution contract (the important part):
- ``analyze`` / ``create_proposal`` NEVER mutate a flag.
- A proposal carries a one-time ``approval_token``. Only
  ``approve(proposal_id, approver, approval_token)`` with the matching
  token applies it, and it applies through ``FlagStore`` so the change
  is versioned and audit-logged like any human change.
- Rollout increases are capped at ``MAX_STEP_INCREASE`` per approval.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field, asdict
from typing import Any

from .store import FlagStore

CONTINUE = "CONTINUE_ROLLOUT"
HOLD = "HOLD"
ROLLBACK_REC = "ROLLBACK"

MIN_SAMPLE_SIZE = 100
MAX_STEP_INCREASE = 25.0

# thresholds
ERROR_ROLLBACK_DELTA = 0.05      # +5pp error rate alone -> rollback
ERROR_SEVERE_DELTA = 0.02
LATENCY_SEVERE_MS = 150.0
SUCCESS_SEVERE_DELTA = -0.05
ERROR_MODERATE_DELTA = 0.005
LATENCY_MODERATE_MS = 50.0
SUCCESS_MODERATE_DELTA = -0.02


@dataclass
class Recommendation:
    flag_key: str
    action: str  # CONTINUE_ROLLOUT | HOLD | ROLLBACK
    reasons: list[str]
    confidence: float  # 0..1
    metrics_used: dict[str, Any]
    suggested_percentage: float | None = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Proposal:
    id: str
    flag_key: str
    recommendation: Recommendation
    approval_token: str
    status: str = "PENDING"  # PENDING | EXECUTED | REJECTED
    created_at: float = field(default_factory=time.time)
    executed_by: str | None = None

    def public_dict(self) -> dict:
        d = asdict(self)
        d["recommendation"] = self.recommendation.to_dict()
        return d


def _num(metrics: dict, name: str, default: float = 0.0) -> float:
    try:
        return float(metrics.get(name, default))
    except (TypeError, ValueError):
        return default


def analyze_metrics(flag_key: str, metrics: dict) -> Recommendation:
    """Pure analysis: metrics dict vs its embedded baseline.

    Expected keys: sample_size, error_rate, baseline_error_rate,
    latency_p95_ms, baseline_latency_p95_ms, success_rate,
    baseline_success_rate, current_rollout_percentage.
    """
    sample = int(_num(metrics, "sample_size", 0))
    err_delta = _num(metrics, "error_rate") - _num(metrics, "baseline_error_rate")
    lat_delta = _num(metrics, "latency_p95_ms") - _num(metrics, "baseline_latency_p95_ms")
    suc_delta = _num(metrics, "success_rate", 1.0) - _num(metrics, "baseline_success_rate", 1.0)
    current_pct = _num(metrics, "current_rollout_percentage", 0.0)
    used = {
        "sample_size": sample, "error_rate_delta": round(err_delta, 4),
        "latency_p95_delta_ms": round(lat_delta, 1),
        "success_rate_delta": round(suc_delta, 4),
        "current_rollout_percentage": current_pct,
    }
    if sample < MIN_SAMPLE_SIZE:
        return Recommendation(flag_key, HOLD,
                              [f"Insufficient data: sample_size={sample} < "
                               f"minimum {MIN_SAMPLE_SIZE}; cannot judge risk."],
                              0.40, used, suggested_percentage=current_pct)
    severe: list[str] = []
    if err_delta >= ERROR_SEVERE_DELTA:
        severe.append(f"error_rate up {err_delta:.1%} vs baseline")
    if lat_delta >= LATENCY_SEVERE_MS:
        severe.append(f"latency p95 up {lat_delta:.0f}ms vs baseline")
    if suc_delta <= SUCCESS_SEVERE_DELTA:
        severe.append(f"success rate down {abs(suc_delta):.1%} vs baseline")
    if err_delta >= ERROR_ROLLBACK_DELTA or len(severe) >= 2:
        return Recommendation(flag_key, ROLLBACK_REC,
                              [f"Severe regression: {s}" for s in severe] or
                              [f"error_rate up {err_delta:.1%} vs baseline"],
                              0.90, used, suggested_percentage=0.0)
    moderate: list[str] = []
    if err_delta >= ERROR_MODERATE_DELTA:
        moderate.append(f"error_rate up {err_delta:.2%} vs baseline")
    if lat_delta >= LATENCY_MODERATE_MS:
        moderate.append(f"latency p95 up {lat_delta:.0f}ms vs baseline")
    if suc_delta <= SUCCESS_MODERATE_DELTA:
        moderate.append(f"success rate down {abs(suc_delta):.2%} vs baseline")
    if moderate:
        return Recommendation(flag_key, HOLD,
                              [f"Moderate regression, hold rollout: {m}" for m in moderate],
                              0.65, used, suggested_percentage=current_pct)
    nxt = min(current_pct + MAX_STEP_INCREASE, 100.0)
    return Recommendation(flag_key, CONTINUE,
                          ["All guardrail metrics within tolerance vs baseline "
                           f"(error {err_delta:+.2%}, latency {lat_delta:+.0f}ms, "
                           f"success {suc_delta:+.2%})."],
                          0.85 if sample >= 1000 else 0.75, used,
                          suggested_percentage=nxt)


class RiskAgent:
    def __init__(self, store: FlagStore) -> None:
        self.store = store
        self._proposals: dict[str, Proposal] = {}

    def analyze(self, flag_key: str, metrics: dict | None = None) -> Recommendation:
        if metrics is None:
            metrics = self.store.latest_metrics(flag_key) or {}
        flag = self.store.get_flag(flag_key)
        if flag is not None and "current_rollout_percentage" not in metrics:
            metrics = {**metrics, "current_rollout_percentage": flag.fallthrough_percentage}
        return analyze_metrics(flag_key, metrics)

    def create_proposal(self, flag_key: str, metrics: dict | None = None) -> Proposal:
        """Create a proposal. Deliberately performs NO flag mutation."""
        rec = self.analyze(flag_key, metrics)
        # Guardrail: cap any suggested increase at +MAX_STEP_INCREASE
        flag = self.store.get_flag(flag_key)
        if flag and rec.action == CONTINUE and rec.suggested_percentage is not None:
            rec.suggested_percentage = min(rec.suggested_percentage,
                                           flag.fallthrough_percentage + MAX_STEP_INCREASE, 100.0)
        proposal = Proposal(id=uuid.uuid4().hex[:12], flag_key=flag_key,
                            recommendation=rec, approval_token=uuid.uuid4().hex)
        self._proposals[proposal.id] = proposal
        return proposal

    def get_proposal(self, proposal_id: str) -> Proposal | None:
        return self._proposals.get(proposal_id)

    def list_proposals(self) -> list[Proposal]:
        return list(self._proposals.values())

    def approve(self, proposal_id: str, approver: str, approval_token: str):
        """Apply an approved proposal through the service layer.

        Raises PermissionError on a missing/wrong token, ValueError for
        a HOLD (no action) or an already-executed proposal.
        """
        proposal = self._proposals.get(proposal_id)
        if proposal is None:
            raise KeyError(f"proposal not found: {proposal_id}")
        if proposal.status == "EXECUTED":
            raise ValueError("proposal already executed")
        if not approval_token or approval_token != proposal.approval_token:
            raise PermissionError("invalid or missing approval token")
        rec = proposal.recommendation
        if rec.action == HOLD:
            raise ValueError("HOLD proposal has no action to execute")
        actor = f"risk-agent-approved-by:{approver}"
        if rec.action == ROLLBACK_REC:
            flag = self.store.patch_rollout(proposal.flag_key, 0.0, actor=actor)
        elif rec.action == CONTINUE:
            flag = self.store.patch_rollout(proposal.flag_key,
                                            float(rec.suggested_percentage), actor=actor)
        else:  # pragma: no cover - defensive
            raise ValueError(f"unknown recommendation {rec.action}")
        proposal.status = "EXECUTED"
        proposal.executed_by = approver
        return flag

    def reject(self, proposal_id: str, approver: str) -> Proposal:
        proposal = self._proposals.get(proposal_id)
        if proposal is None:
            raise KeyError(f"proposal not found: {proposal_id}")
        proposal.status = "REJECTED"
        proposal.executed_by = approver
        return proposal
