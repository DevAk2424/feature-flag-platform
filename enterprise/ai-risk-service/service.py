"""Guarded execution service layer.

Contract (the important part):
- analyze()/create_proposal() NEVER change a flag and NEVER publish a command.
- approve() requires the proposal's one-time approval token; only then is a
  FlagCommandEvent published to the control plane stream.
- Rollout increases are capped at +MAX_STEP_INCREASE per approval.
- HOLD proposals have no executable action.
"""
from __future__ import annotations
import time, uuid
from risk_engine import analyze_metrics, Proposal, Recommendation, CONTINUE, HOLD, ROLLBACK, MAX_STEP_INCREASE

class RiskService:
    def __init__(self, metrics_consumer, command_publisher):
        self.metrics = metrics_consumer; self.commands = command_publisher
        self._proposals: dict[str, Proposal] = {}
    def ingest(self, flag_key, metrics): self.metrics.on_metrics(flag_key, metrics)
    def analyze(self, flag_key, metrics=None) -> Recommendation:
        return analyze_metrics(flag_key, metrics or self.metrics.latest(flag_key) or {})
    def create_proposal(self, flag_key, metrics=None) -> Proposal:
        rec = self.analyze(flag_key, metrics)
        m = metrics or self.metrics.latest(flag_key) or {}
        if rec.action == CONTINUE and rec.suggested_percentage is not None:
            current = float(m.get("current_rollout_percentage", 0.0))
            rec.suggested_percentage = min(rec.suggested_percentage, current + MAX_STEP_INCREASE, 100.0)
        p = Proposal(id=uuid.uuid4().hex[:12], flag_key=flag_key, recommendation=rec,
                     approval_token=uuid.uuid4().hex)
        self._proposals[p.id] = p; return p
    def get_proposal(self, pid): return self._proposals.get(pid)
    def list_proposals(self): return list(self._proposals.values())
    def approve(self, pid, approver, approval_token):
        p = self._proposals.get(pid)
        if p is None: raise KeyError(f"proposal not found: {pid}")
        if p.status == "EXECUTED": raise ValueError("proposal already executed")
        if not approval_token or approval_token != p.approval_token:
            raise PermissionError("invalid or missing approval token")
        rec = p.recommendation
        if rec.action == HOLD: raise ValueError("HOLD proposal has no action to execute")
        target = 0.0 if rec.action == ROLLBACK else float(rec.suggested_percentage)
        event = {"commandId": uuid.uuid4().hex, "type": "SET_ROLLOUT", "flagKey": p.flag_key,
                 "targetRolloutPercentage": target, "targetEnabled": None,
                 "actor": approver, "proposalId": p.id, "timestampEpochMs": int(time.time()*1000)}
        self.commands.publish(event)   # the ONLY place a command leaves this service
        p.status = "EXECUTED"; p.executed_by = approver
        return {"proposal": p.public_dict(), "command_event": event}
    def reject(self, pid, approver):
        p = self._proposals.get(pid)
        if p is None: raise KeyError(f"proposal not found: {pid}")
        p.status = "REJECTED"; p.executed_by = approver; return p
