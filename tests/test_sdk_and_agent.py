import threading
import unittest

from featureflags.store import FlagStore
from featureflags.server import create_server
from featureflags.sdk import FeatureFlagClient
from featureflags.risk_agent import (RiskAgent, analyze_metrics,
                                     CONTINUE, HOLD, ROLLBACK_REC)

HEALTHY = {"sample_size": 5000, "error_rate": 0.011, "baseline_error_rate": 0.010,
           "latency_p95_ms": 210, "baseline_latency_p95_ms": 200,
           "success_rate": 0.981, "baseline_success_rate": 0.980,
           "current_rollout_percentage": 25}
BAD = {"sample_size": 5000, "error_rate": 0.09, "baseline_error_rate": 0.010,
       "latency_p95_ms": 520, "baseline_latency_p95_ms": 200,
       "success_rate": 0.90, "baseline_success_rate": 0.980,
       "current_rollout_percentage": 50}
LOW_SAMPLE = {**HEALTHY, "sample_size": 12}


class TestRiskAgentDecisions(unittest.TestCase):
    def test_healthy_continues_with_capped_step(self):
        rec = analyze_metrics("f", dict(HEALTHY))
        self.assertEqual(rec.action, CONTINUE)
        self.assertEqual(rec.suggested_percentage, 50)  # 25 + max step 25
        self.assertTrue(rec.reasons)

    def test_error_spike_recommends_rollback(self):
        rec = analyze_metrics("f", dict(BAD))
        self.assertEqual(rec.action, ROLLBACK_REC)
        self.assertEqual(rec.suggested_percentage, 0.0)
        self.assertGreaterEqual(rec.confidence, 0.8)

    def test_low_sample_holds(self):
        rec = analyze_metrics("f", dict(LOW_SAMPLE))
        self.assertEqual(rec.action, HOLD)
        self.assertIn("Insufficient", rec.reasons[0])


class TestGuardedExecution(unittest.TestCase):
    def setUp(self):
        self.store = FlagStore()
        self.store.create_flag({"key": "guarded", "fallthrough_percentage": 50}, actor="test")
        self.agent = RiskAgent(self.store)

    def test_proposal_alone_changes_nothing(self):
        proposal = self.agent.create_proposal("guarded", dict(BAD))
        self.assertEqual(proposal.recommendation.action, ROLLBACK_REC)
        self.assertEqual(self.store.get_flag("guarded").fallthrough_percentage, 50)

    def test_wrong_token_rejected(self):
        proposal = self.agent.create_proposal("guarded", dict(BAD))
        with self.assertRaises(PermissionError):
            self.agent.approve(proposal.id, "sam", "wrong-token")
        self.assertEqual(self.store.get_flag("guarded").fallthrough_percentage, 50)

    def test_approved_rollback_applies_and_is_audited(self):
        v_before = self.store.get_flag("guarded").version
        proposal = self.agent.create_proposal("guarded", dict(BAD))
        flag = self.agent.approve(proposal.id, "sam", proposal.approval_token)
        self.assertEqual(flag.fallthrough_percentage, 0.0)
        self.assertGreater(flag.version, v_before)
        actors = [e["actor"] for e in self.store.audit_log("guarded")]
        self.assertTrue(any("risk-agent-approved-by:sam" in a for a in actors))

    def test_approved_continue_respects_max_step(self):
        self.store.patch_rollout("guarded", 10, actor="test")
        proposal = self.agent.create_proposal("guarded", {**HEALTHY, "current_rollout_percentage": 10})
        flag = self.agent.approve(proposal.id, "sam", proposal.approval_token)
        self.assertEqual(flag.fallthrough_percentage, 35)  # 10 + 25 cap, no more


class TestSDKOffline(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = create_server("127.0.0.1", 0)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = f"http://127.0.0.1:{cls.port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown(); cls.server.server_close()

    def test_poll_then_evaluate_locally(self):
        client = FeatureFlagClient(self.url)
        self.assertTrue(client.poll_once())
        self.assertFalse(client.stale)
        # seeded flag: legacy-search is kill-switched
        self.assertFalse(client.is_enabled("legacy-search", "anyone"))
        self.assertTrue(client.evaluate("nope", "u").reason == "FLAG_NOT_FOUND")

    def test_stale_cache_after_control_plane_down(self):
        client = FeatureFlagClient(self.url)
        client.poll_once()
        # point the client at a dead port: polling must fail soft
        client.base_url = "http://127.0.0.1:1"
        self.assertFalse(client.poll_once())
        self.assertTrue(client.stale)
        # evaluation still works from last-known-good cache, never crashes
        result = client.evaluate("checkout-redesign", "user-1")
        self.assertIn(result.reason, ("FALLOUT_ROLLOUT", "FALLOUT_OFF", "RULE_MATCH"))

    def test_version_guard_ignores_older_snapshot(self):
        client = FeatureFlagClient(self.url)
        client.poll_once()
        v = client.config_version
        self.assertFalse(client.load_snapshot({"version": v - 1, "flags": []}))
        self.assertEqual(client.config_version, v)
        self.assertTrue(client.is_enabled("ai-recommendations", self._in_user()))

    @staticmethod
    def _in_user():
        from featureflags.engine import compute_bucket
        for i in range(500):
            if compute_bucket("ai-recommendations", "ai-recommendations", f"user-{i}") < 5000:
                return f"user-{i}"
        return "user-0"


if __name__ == "__main__":
    unittest.main()
