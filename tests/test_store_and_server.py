import http.client
import json
import threading
import unittest

from featureflags.store import FlagStore
from featureflags.server import create_server

KEY = {"x-api-key": "demo-api-key-12345", "Content-Type": "application/json"}


class TestStore(unittest.TestCase):
    def setUp(self):
        self.store = FlagStore()
        self.store.create_flag({"key": "f1", "fallthrough_percentage": 10}, actor="alice")

    def test_version_increments_on_every_write(self):
        self.assertEqual(self.store.get_flag("f1").version, 1)
        self.store.patch_rollout("f1", 25, actor="bob")
        self.assertEqual(self.store.get_flag("f1").version, 2)
        self.store.set_enabled("f1", False, actor="bob")
        self.assertEqual(self.store.get_flag("f1").version, 3)

    def test_audit_records_actor_old_new(self):
        self.store.patch_rollout("f1", 40, actor="carol")
        log = self.store.audit_log("f1")
        self.assertGreaterEqual(len(log), 2)
        last = log[-1]
        self.assertEqual(last["actor"], "carol")
        self.assertEqual(last["old_value"]["fallthrough_percentage"], 10)
        self.assertEqual(last["new_value"]["fallthrough_percentage"], 40.0)

    def test_rollback_restores_old_content_as_new_version(self):
        self.store.patch_rollout("f1", 90, actor="a")
        rolled = self.store.rollback("f1", to_version=1, actor="a")
        self.assertEqual(rolled.fallthrough_percentage, 10)
        self.assertEqual(rolled.version, 3)  # forward-moving, not back to 1
        actions = [e["action"] for e in self.store.audit_log("f1")]
        self.assertIn("ROLLBACK", actions)

    def test_snapshot_version_increases(self):
        v1 = self.store.snapshot()["version"]
        self.store.patch_rollout("f1", 15, actor="a")
        self.assertGreater(self.store.snapshot()["version"], v1)


class TestServer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = create_server("127.0.0.1", 0)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown(); cls.server.server_close()

    def req(self, method, path, body=None, headers=KEY):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request(method, path, json.dumps(body) if body is not None else None, headers)
        resp = conn.getresponse()
        raw = resp.read().decode()
        conn.close()
        return resp.status, (json.loads(raw) if raw else {}), resp.getheader("ETag")

    def test_health_and_dashboard(self):
        status, body, _ = self.req("GET", "/health", headers={})
        self.assertEqual((status, body["status"]), (200, "ok"))
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request("GET", "/")
        resp = conn.getresponse(); html = resp.read().decode(); conn.close()
        self.assertEqual(resp.status, 200)
        self.assertIn("Release Control", html)

    def test_auth_required(self):
        status, _, _ = self.req("GET", "/v1/flags", headers={})
        self.assertEqual(status, 401)

    def test_crud_toggle_and_rollout(self):
        status, flag, _ = self.req("POST", "/v1/flags",
                                   {"key": "api-flag", "fallthrough_percentage": 5})
        self.assertEqual(status, 201)
        self.assertEqual(flag["version"], 1)
        status, flag, _ = self.req("PATCH", "/v1/flags/api-flag", {"fallthrough_percentage": 30})
        self.assertEqual((status, flag["fallthrough_percentage"], flag["version"]), (200, 30.0, 2))
        status, flag, _ = self.req("PATCH", "/v1/flags/api-flag", {"enabled": False})
        self.assertFalse(flag["enabled"])

    def test_config_etag_304(self):
        status, snap, etag = self.req("GET", "/v1/config?env=prod")
        self.assertEqual(status, 200)
        self.assertTrue(etag)
        status, _, _ = self.req("GET", "/v1/config?env=prod",
                                headers={**KEY, "If-None-Match": etag})
        self.assertEqual(status, 304)
        status, _, _ = self.req("GET", f"/v1/config?env=prod&version={snap['version']}")
        self.assertEqual(status, 304)

    def test_metrics_rollback_audit_endpoints(self):
        self.req("POST", "/v1/flags", {"key": "m-flag", "fallthrough_percentage": 10})
        self.req("PATCH", "/v1/flags/m-flag", {"fallthrough_percentage": 80})
        status, row, _ = self.req("POST", "/v1/flags/m-flag/metrics",
                                  {"sample_size": 500, "error_rate": 0.01})
        self.assertEqual(status, 201)
        status, flag, _ = self.req("POST", "/v1/flags/m-flag/rollback", {"to_version": 1})
        self.assertEqual((status, flag["fallthrough_percentage"]), (200, 10))
        status, body, _ = self.req("GET", "/v1/audit?flag_key=m-flag")
        self.assertTrue(any(e["action"] == "ROLLBACK" for e in body["audit"]))


if __name__ == "__main__":
    unittest.main()
