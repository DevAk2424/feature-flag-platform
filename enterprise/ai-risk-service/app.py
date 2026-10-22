"""AI release-risk microservice (FastAPI).

Run:  uvicorn app:app --port 8090     (sandbox)
      CONTROL_PLANE_URL=http://control-plane:8080 COMMAND_TRANSPORT=http ...
Streaming design: metrics arrive on the flag-metrics stream (Kafka in prod,
HTTP ingest here in sandbox); decisions leave ONLY as flag-commands stream
events after human approval. This service holds no flag state of its own.
"""
from __future__ import annotations
import os
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from risk_engine import analyze_metrics
from metrics_consumer import InProcessMetricsConsumer
from command_publisher import InMemoryCommandPublisher, HttpCommandPublisher
from service import RiskService

def _publisher():
    if os.environ.get("COMMAND_TRANSPORT", "http") == "memory":
        return InMemoryCommandPublisher()
    return HttpCommandPublisher()

app = FastAPI(title="ai-risk-service", version="2.0.0")
svc = RiskService(InProcessMetricsConsumer(), _publisher())

class MetricsIn(BaseModel):
    flag_key: str; metrics: dict
class AnalyzeIn(BaseModel):
    metrics: dict | None = None
class ApproveIn(BaseModel):
    approver: str; approval_token: str
class RejectIn(BaseModel):
    approver: str

@app.get("/health")
def health(): return {"status": "ok", "service": "ai-risk-service"}

@app.post("/metrics")
def ingest(body: MetricsIn):
    svc.ingest(body.flag_key, body.metrics); return {"ingested": body.flag_key}

@app.get("/flags/{flag_key}/recommendation")
def recommendation(flag_key: str): return svc.analyze(flag_key).to_dict()

@app.post("/flags/{flag_key}/analyze")
def analyze(flag_key: str, body: AnalyzeIn): return svc.analyze(flag_key, body.metrics).to_dict()

@app.post("/proposals")
def create_proposal(body: MetricsIn):
    if body.metrics: svc.ingest(body.flag_key, body.metrics)
    return svc.create_proposal(body.flag_key).public_dict()

@app.get("/proposals")
def list_proposals(): return [p.public_dict() for p in svc.list_proposals()]

@app.get("/proposals/{proposal_id}")
def get_proposal(proposal_id: str):
    p = svc.get_proposal(proposal_id)
    if not p: raise HTTPException(404, "proposal not found")
    return p.public_dict()

@app.post("/proposals/{proposal_id}/approve")
def approve(proposal_id: str, body: ApproveIn):
    try: return svc.approve(proposal_id, body.approver, body.approval_token)
    except KeyError as e: raise HTTPException(404, str(e))
    except PermissionError as e: raise HTTPException(403, str(e))
    except ValueError as e: raise HTTPException(400, str(e))

@app.post("/proposals/{proposal_id}/reject")
def reject(proposal_id: str, body: RejectIn):
    try: return svc.reject(proposal_id, body.approver).public_dict()
    except KeyError as e: raise HTTPException(404, str(e))
