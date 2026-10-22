import sys, os, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from risk_engine import analyze_metrics, CONTINUE, HOLD, ROLLBACK
from metrics_consumer import InProcessMetricsConsumer
from command_publisher import InMemoryCommandPublisher
from service import RiskService

HEALTHY = {"sample_size": 5000, "error_rate": 0.011, "baseline_error_rate": 0.010,
           "latency_p95_ms": 210, "baseline_latency_p95_ms": 200,
           "success_rate": 0.99, "baseline_success_rate": 0.99, "current_rollout_percentage": 10}
SPIKE = dict(HEALTHY, error_rate=0.09)
LOW = dict(HEALTHY, sample_size=42)

def make():
    pub = InMemoryCommandPublisher(); svc = RiskService(InProcessMetricsConsumer(), pub); return svc, pub

class EngineTest(unittest.TestCase):
    def test_healthy_continues_capped_plus25(self):
        r = analyze_metrics("checkout-redesign", HEALTHY)
        self.assertEqual(CONTINUE, r.action); self.assertEqual(35.0, r.suggested_percentage); self.assertGreaterEqual(r.confidence, 0.8)
    def test_error_spike_rolls_back(self):
        r = analyze_metrics("checkout-redesign", SPIKE)
        self.assertEqual(ROLLBACK, r.action); self.assertEqual(0.0, r.suggested_percentage)
    def test_low_sample_holds(self):
        r = analyze_metrics("checkout-redesign", LOW)
        self.assertEqual(HOLD, r.action); self.assertIn("Insufficient data", r.reasons[0])
    def test_moderate_regression_holds(self):
        r = analyze_metrics("f", dict(HEALTHY, latency_p95_ms=290))
        self.assertEqual(HOLD, r.action)

class GuardedExecutionTest(unittest.TestCase):
    def test_proposal_alone_publishes_nothing(self):
        svc, pub = make(); svc.ingest("checkout-redesign", SPIKE)
        p = svc.create_proposal("checkout-redesign")
        self.assertEqual([], pub.events); self.assertEqual("PENDING", p.status)
    def test_wrong_token_publishes_nothing(self):
        svc, pub = make(); svc.ingest("checkout-redesign", SPIKE)
        p = svc.create_proposal("checkout-redesign")
        with self.assertRaises(PermissionError): svc.approve(p.id, "akshay", "wrong")
        self.assertEqual([], pub.events)
    def test_approved_rollback_publishes_command_event(self):
        svc, pub = make(); svc.ingest("checkout-redesign", SPIKE)
        p = svc.create_proposal("checkout-redesign")
        out = svc.approve(p.id, "akshay", p.approval_token)
        self.assertEqual(1, len(pub.events))
        ev = pub.events[0]
        self.assertEqual("SET_ROLLOUT", ev["type"]); self.assertEqual(0.0, ev["targetRolloutPercentage"])
        self.assertEqual("akshay", ev["actor"]); self.assertEqual(p.id, ev["proposalId"])
        self.assertEqual("EXECUTED", out["proposal"]["status"])
    def test_double_approval_refused(self):
        svc, pub = make(); svc.ingest("checkout-redesign", SPIKE)
        p = svc.create_proposal("checkout-redesign"); svc.approve(p.id, "akshay", p.approval_token)
        with self.assertRaises(ValueError): svc.approve(p.id, "akshay", p.approval_token)
        self.assertEqual(1, len(pub.events))
    def test_hold_proposal_not_executable(self):
        svc, pub = make(); svc.ingest("checkout-redesign", LOW)
        p = svc.create_proposal("checkout-redesign")
        with self.assertRaises(ValueError): svc.approve(p.id, "akshay", p.approval_token)
        self.assertEqual([], pub.events)
    def test_reject_marks_proposal(self):
        svc, pub = make(); svc.ingest("checkout-redesign", HEALTHY)
        p = svc.create_proposal("checkout-redesign"); svc.reject(p.id, "akshay")
        self.assertEqual("REJECTED", p.status); self.assertEqual([], pub.events)

if __name__ == "__main__": unittest.main()
