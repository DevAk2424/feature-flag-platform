"""Control plane HTTP API (stdlib http.server only).

Run:  python3 -m featureflags.server [--port 8080]
Demo API key (documented, not a real secret): demo-api-key-12345
Send it as header ``x-api-key`` on every /v1 request. Override with
the FEATUREFLAG_API_KEY environment variable.
"""
from __future__ import annotations

import argparse
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

from .engine import EvaluationContext, evaluate
from .risk_agent import RiskAgent
from .store import FlagStore

API_KEY = os.environ.get("FEATUREFLAG_API_KEY", "demo-api-key-12345")
STATIC_DIR = Path(__file__).parent / "static"

SEED_FLAGS = [
    {"key": "checkout-redesign", "description": "New checkout flow",
     "variations": {"on": True, "off": False},
     "fallthrough_variation": "on", "fallthrough_percentage": 10.0,
     "rules": [{"id": "beta-users", "variation": "on",
                "clauses": [{"attribute": "segment", "operator": "in", "values": ["beta"]}]}],
     "tags": ["checkout"]},
    {"key": "ai-recommendations", "description": "Agentic AI recommendations",
     "variations": {"on": True, "off": False},
     "fallthrough_variation": "on", "fallthrough_percentage": 50.0,
     "tags": ["ai"]},
    {"key": "legacy-search", "description": "Legacy search backend (kill-switched)",
     "enabled": False, "variations": {"on": True, "off": False},
     "fallthrough_variation": "on", "fallthrough_percentage": 100.0,
     "tags": ["search"]},
]


def seed(store: FlagStore) -> FlagStore:
    for data in SEED_FLAGS:
        if store.get_flag(data["key"]) is None:
            store.create_flag(data, actor="seed")
    return store


def make_handler(store: FlagStore, agent: RiskAgent, api_key: str):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        # -- plumbing ------------------------------------------------
        def log_message(self, *args):  # keep tests/demo output clean
            pass

        def _send(self, code: int, body=None, content_type="application/json", headers=None):
            raw = b"" if body is None else (
                body if isinstance(body, bytes) else json.dumps(body).encode())
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(raw)))
            for k, v in (headers or {}).items():
                self.send_header(k, v)
            self.end_headers()
            if raw:
                self.wfile.write(raw)

        def _body(self) -> dict:
            length = int(self.headers.get("Content-Length") or 0)
            if not length:
                return {}
            try:
                return json.loads(self.rfile.read(length).decode() or "{}")
            except ValueError:
                return {}

        def _authed(self) -> bool:
            if self.headers.get("x-api-key") == api_key:
                return True
            self._send(401, {"error": "missing or invalid x-api-key"})
            return False

        def _actor(self, body: dict) -> str:
            return body.get("actor") or self.headers.get("x-actor") or "api"

        # -- routing ---------------------------------------------------
        def do_GET(self):
            parsed = urlparse(self.path)
            path, qs = parsed.path, parse_qs(parsed.query)
            if path in ("/", "/index.html"):
                return self._static("index.html", "text/html; charset=utf-8")
            if path.startswith("/static/"):
                name = path.split("/", 2)[2]
                ctype = "text/css" if name.endswith(".css") else "application/javascript"
                return self._static(name, ctype)
            if path == "/health":
                return self._send(200, {"status": "ok", "config_version": store.config_version})
            if not path.startswith("/v1/"):
                return self._send(404, {"error": "not found"})
            if not self._authed():
                return
            parts = [p for p in path.split("/") if p]  # e.g. ['v1','flags','x']
            try:
                if parts == ["v1", "flags"]:
                    return self._send(200, {"flags": [f.to_dict() for f in store.list_flags()]})
                if parts == ["v1", "config"]:
                    snap = store.snapshot(qs.get("env", ["prod"])[0])
                    etag = f'"{snap["version"]}"'
                    client_ver = qs.get("version", [None])[0]
                    if (self.headers.get("If-None-Match") == etag
                            or (client_ver is not None and int(client_ver) == snap["version"])):
                        return self._send(304, b"", headers={"ETag": etag})
                    return self._send(200, snap, headers={"ETag": etag})
                if parts == ["v1", "audit"]:
                    return self._send(200, {"audit": store.audit_log(qs.get("flag_key", [None])[0])})
                if parts == ["v1", "risk", "proposals"]:
                    return self._send(200, {"proposals": [p.public_dict() for p in agent.list_proposals()]})
                if len(parts) == 3 and parts[:2] == ["v1", "flags"]:
                    flag = store.get_flag(parts[2])
                    return self._send(200, flag.to_dict()) if flag else self._send(404, {"error": "flag not found"})
                if len(parts) == 4 and parts[:2] == ["v1", "flags"] and parts[3] == "history":
                    hist = store.history(parts[2])
                    return self._send(200, {"history": {str(k): v for k, v in hist.items()}})
                if len(parts) == 4 and parts[:2] == ["v1", "flags"] and parts[3] == "metrics":
                    return self._send(200, {"metrics": store.all_metrics(parts[2]),
                                            "latest": store.latest_metrics(parts[2])})
            except Exception as exc:
                return self._send(400, {"error": str(exc)})
            return self._send(404, {"error": "not found"})

        def do_POST(self):
            parsed = urlparse(self.path)
            path = parsed.path
            if not path.startswith("/v1/") or not self._authed():
                if path.startswith("/v1/"):
                    return
                return self._send(404, {"error": "not found"})
            body, parts = self._body(), [p for p in path.split("/") if p]
            actor = self._actor(body)
            try:
                if parts == ["v1", "flags"]:
                    flag = store.create_flag(body, actor=actor)
                    return self._send(201, flag.to_dict())
                if len(parts) == 4 and parts[:2] == ["v1", "flags"] and parts[3] == "rollback":
                    flag = store.rollback(parts[2], int(body["to_version"]), actor=actor)
                    return self._send(200, flag.to_dict())
                if len(parts) == 4 and parts[:2] == ["v1", "flags"] and parts[3] == "metrics":
                    row = store.ingest_metrics(parts[2], body)
                    return self._send(201, row)
                if parts == ["v1", "metrics"]:
                    row = store.ingest_metrics(body["flag_key"], body)
                    return self._send(201, row)
                if len(parts) == 4 and parts[:2] == ["v1", "flags"] and parts[3] == "evaluate":
                    flag = store.get_flag(parts[2])
                    ctx = EvaluationContext(body.get("user_key", "anonymous"),
                                            body.get("attributes", {}))
                    return self._send(200, evaluate(flag, ctx).to_dict())
                if parts == ["v1", "risk", "proposals"]:
                    proposal = agent.create_proposal(body["flag_key"], body.get("metrics"))
                    return self._send(201, proposal.public_dict())
                if parts == ["v1", "risk", "analyze"]:
                    rec = agent.analyze(body["flag_key"], body.get("metrics"))
                    return self._send(200, rec.to_dict())
                if (len(parts) == 5 and parts[:3] == ["v1", "risk", "proposals"]
                        and parts[4] == "approve"):
                    flag = agent.approve(parts[3], body.get("approver", "unknown"),
                                         body.get("approval_token", ""))
                    return self._send(200, {"status": "EXECUTED", "flag": flag.to_dict()})
                if (len(parts) == 5 and parts[:3] == ["v1", "risk", "proposals"]
                        and parts[4] == "reject"):
                    p = agent.reject(parts[3], body.get("approver", "unknown"))
                    return self._send(200, p.public_dict())
            except PermissionError as exc:
                return self._send(403, {"error": str(exc)})
            except (KeyError, ValueError) as exc:
                return self._send(400, {"error": str(exc)})
            return self._send(404, {"error": "not found"})

        def do_PUT(self):
            self._update()

        def do_PATCH(self):
            self._update()

        def _update(self):
            parsed = urlparse(self.path)
            parts = [p for p in parsed.path.split("/") if p]
            if len(parts) != 3 or parts[:2] != ["v1", "flags"] or not self._authed():
                if not parsed.path.startswith("/v1/"):
                    self._send(404, {"error": "not found"})
                return
            body = self._body()
            actor = self._actor(body)
            try:
                if "fallthrough_percentage" in body and len(body) <= 3:
                    flag = store.patch_rollout(parts[2], float(body["fallthrough_percentage"]), actor=actor)
                elif set(body) <= {"enabled", "actor"} and "enabled" in body:
                    flag = store.set_enabled(parts[2], bool(body["enabled"]), actor=actor)
                else:
                    flag = store.update_flag(parts[2], body, actor=actor)
                return self._send(200, flag.to_dict())
            except (KeyError, ValueError) as exc:
                return self._send(400, {"error": str(exc)})

        def do_DELETE(self):
            parsed = urlparse(self.path)
            parts = [p for p in parsed.path.split("/") if p]
            if len(parts) == 3 and parts[:2] == ["v1", "flags"] and self._authed():
                try:
                    store.delete_flag(parts[2], actor=self.headers.get("x-actor", "api"))
                    return self._send(200, {"deleted": parts[2]})
                except KeyError as exc:
                    return self._send(400, {"error": str(exc)})
            if not parsed.path.startswith("/v1/"):
                return self._send(404, {"error": "not found"})

        def _static(self, name: str, content_type: str):
            file = STATIC_DIR / name
            if not file.is_file():
                return self._send(404, {"error": "not found"})
            return self._send(200, file.read_bytes(), content_type=content_type)

    return Handler


def create_server(host: str = "127.0.0.1", port: int = 8080,
                  store: FlagStore | None = None, api_key: str = API_KEY,
                  with_seed: bool = True) -> ThreadingHTTPServer:
    store = store or FlagStore()
    if with_seed:
        seed(store)
    agent = RiskAgent(store)
    server = ThreadingHTTPServer((host, port), make_handler(store, agent, api_key))
    server.store = store  # type: ignore[attr-defined]
    server.agent = agent  # type: ignore[attr-defined]
    return server


def main() -> None:
    ap = argparse.ArgumentParser(description="Feature Flag Control Plane")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8080)
    args = ap.parse_args()
    server = create_server(args.host, args.port)
    print(f"Feature Flag Control Plane on http://{args.host}:{args.port} "
          f"(dashboard at /, demo API key: {API_KEY})")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()


if __name__ == "__main__":
    main()
