import sys, os
os.environ["COMMAND_TRANSPORT"] = "memory"
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from fastapi.testclient import TestClient
from app import app
client = TestClient(app)
SPIKE = {"sample_size": 5000, "error_rate": 0.09, "baseline_error_rate": 0.010,
         "latency_p95_ms": 210, "baseline_latency_p95_ms": 200,
         "success_rate": 0.99, "baseline_success_rate": 0.99, "current_rollout_percentage": 10}
def test_health(): assert client.get("/health").json()["status"] == "ok"
def test_proposal_flow_over_http():
    r = client.post("/proposals", json={"flag_key": "checkout-redesign", "metrics": SPIKE})
    assert r.status_code == 200, r.text
    p = r.json(); assert p["recommendation"]["action"] == "ROLLBACK"
    bad = client.post(f"/proposals/{p['id']}/approve", json={"approver": "akshay", "approval_token": "nope"})
    assert bad.status_code == 403
    ok = client.post(f"/proposals/{p['id']}/approve", json={"approver": "akshay", "approval_token": p["approval_token"]})
    assert ok.status_code == 200, ok.text
    assert ok.json()["command_event"]["targetRolloutPercentage"] == 0.0
