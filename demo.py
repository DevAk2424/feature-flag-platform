#!/usr/bin/env python3
"""End-to-end demo: seed -> evaluate -> bad metrics -> agent proposal
-> (nothing changes) -> approve -> rollback + audit.

Run:  python3 demo.py
Uses the service layer directly (no server needed); server + SDK are
exercised in the test suite and the smoke commands in the README.
"""
from featureflags.engine import EvaluationContext, evaluate
from featureflags.store import FlagStore
from featureflags.risk_agent import RiskAgent


def main() -> None:
    store = FlagStore()
    agent = RiskAgent(store)

    print("== Seeding flags ==")
    store.create_flag({"key": "checkout-redesign", "description": "New checkout",
                       "fallthrough_percentage": 10,
                       "rules": [{"id": "beta", "variation": "on",
                                  "clauses": [{"attribute": "segment", "operator": "in",
                                               "values": ["beta"]}]}]}, actor="demo")
    store.create_flag({"key": "ai-recommendations", "fallthrough_percentage": 50}, actor="demo")
    store.create_flag({"key": "legacy-search", "enabled": False,
                       "fallthrough_percentage": 100}, actor="demo")
    for f in store.list_flags():
        print(f"  {f.key:<20} enabled={f.enabled} rollout={f.fallthrough_percentage}% v{f.version}")

    print("\n== Evaluating users (checkout-redesign, 10% rollout) ==")
    flag = store.get_flag("checkout-redesign")
    for user, attrs in [("user-1", {}), ("user-7", {}),
                        ("beta-ana", {"segment": "beta"}), ("user-99", {})]:
        r = evaluate(flag, EvaluationContext(user, attrs))
        print(f"  {user:<10} segment={attrs.get('segment', '-'):<5} -> "
              f"value={r.value} reason={r.reason} bucket={r.bucket}")
    r = evaluate(store.get_flag("legacy-search"), EvaluationContext("user-1"))
    print(f"  legacy-search (kill-switched) -> value={r.value} reason={r.reason}")

    print("\n== Simulating a bad release: metrics for checkout-redesign ==")
    bad_metrics = {"sample_size": 8200, "error_rate": 0.094, "baseline_error_rate": 0.011,
                   "latency_p95_ms": 640, "baseline_latency_p95_ms": 210,
                   "success_rate": 0.891, "baseline_success_rate": 0.978,
                   "current_rollout_percentage": 10}
    store.ingest_metrics("checkout-redesign", bad_metrics)
    for k, v in bad_metrics.items():
        print(f"  {k}: {v}")

    print("\n== AI release-risk agent ==")
    proposal = agent.create_proposal("checkout-redesign")
    rec = proposal.recommendation
    print(f"  Recommendation: {rec.action} (confidence {rec.confidence:.0%})")
    for reason in rec.reasons:
        print(f"    - {reason}")
    print(f"  Proposal {proposal.id} status={proposal.status} "
          f"(suggested rollout: {rec.suggested_percentage}%)")
    before = store.get_flag("checkout-redesign")
    print(f"  GUARD CHECK: flag is still at {before.fallthrough_percentage}% v{before.version} "
          "-- a proposal alone changes nothing.")

    print("\n== Human approves the proposal ==")
    updated = agent.approve(proposal.id, approver="akshay", approval_token=proposal.approval_token)
    print(f"  After approval: rollout={updated.fallthrough_percentage}% v{updated.version} "
          f"status={proposal.status}")

    print("\n== Audit log (checkout-redesign) ==")
    for e in store.audit_log("checkout-redesign"):
        print(f"  v{e['version']} {e['action']:<10} by {e['actor']}")
    print("\nDemo complete.")


if __name__ == "__main__":
    main()
