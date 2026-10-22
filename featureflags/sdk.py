"""Client SDK: poll the control plane, evaluate locally.

High-availability contract:
- ``evaluate()`` never touches the network and never raises for a
  missing flag or a dead control plane; it serves the last-known-good
  cache and reports ``stale`` truthfully.
- The cache is only replaced when the incoming config version is
  strictly greater than the held version (version-based invalidation,
  backed by ETag/If-None-Match on the wire).
- An optional JSON file cache lets a restarted process evaluate
  immediately, before its first successful poll.
"""
from __future__ import annotations

import json
import os
import threading
import urllib.request
import urllib.error
from typing import Any

from .engine import Flag, EvaluationContext, EvaluationResult, evaluate as _eval

DEFAULT_API_KEY = "demo-api-key-12345"


class FeatureFlagClient:
    def __init__(self, base_url: str = "http://127.0.0.1:8080",
                 api_key: str = DEFAULT_API_KEY, env: str = "prod",
                 cache_file: str | None = None, poll_interval: float = 5.0,
                 timeout: float = 2.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.env = env
        self.cache_file = cache_file
        self.poll_interval = poll_interval
        self.timeout = timeout
        self._flags: dict[str, Flag] = {}
        self.config_version = -1
        self.stale = True  # nothing fresh yet
        self.last_error: str | None = None
        self._etag: str | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        if cache_file and os.path.exists(cache_file):
            try:
                with open(cache_file, encoding="utf-8") as fh:
                    self.load_snapshot(json.load(fh))
            except (OSError, ValueError):
                pass  # a corrupt cache must never crash the host app

    # ---- cache -----------------------------------------------------
    def load_snapshot(self, snapshot: dict) -> bool:
        """Replace cache only if the snapshot version is newer."""
        version = int(snapshot.get("version", 0))
        if version < self.config_version:
            return False
        self._flags = {d["key"]: Flag.from_dict(d) for d in snapshot.get("flags", [])}
        self.config_version = version
        return True

    def _persist(self, snapshot: dict) -> None:
        if not self.cache_file:
            return
        try:
            with open(self.cache_file, "w", encoding="utf-8") as fh:
                json.dump(snapshot, fh)
        except OSError:
            pass

    # ---- polling -----------------------------------------------------
    def poll_once(self) -> bool:
        """One fetch. Returns True if a newer config was applied.

        On any failure: keeps the old cache, marks stale, returns False.
        """
        url = f"{self.base_url}/v1/config?env={self.env}"
        req = urllib.request.Request(url, headers={"x-api-key": self.api_key})
        if self._etag:
            req.add_header("If-None-Match", self._etag)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                self._etag = resp.headers.get("ETag", self._etag)
                snapshot = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code == 304:  # already current
                self.stale = False
                return False
            self.stale = True
            self.last_error = f"HTTP {exc.code}"
            return False
        except Exception as exc:  # control plane down -> serve stale
            self.stale = True
            self.last_error = str(exc)
            return False
        applied = self.load_snapshot(snapshot)
        self.stale = False
        self.last_error = None
        if applied:
            self._etag = f'"{snapshot.get("version")}"'
            self._persist(snapshot)
        return applied

    def start_polling(self) -> None:
        self.poll_once()
        if self._thread and self._thread.is_alive():
            return

        def _loop():
            while not self._stop.wait(self.poll_interval):
                self.poll_once()

        self._thread = threading.Thread(target=_loop, daemon=True, name="ff-poller")
        self._thread.start()

    def stop_polling(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2.0)

    # ---- evaluation (local only) --------------------------------------
    def evaluate(self, flag_key: str, user_key: str,
                 attributes: dict[str, Any] | None = None,
                 default: Any = False) -> EvaluationResult:
        flag = self._flags.get(flag_key)
        ctx = EvaluationContext(user_key=user_key, attributes=attributes or {})
        result = _eval(flag, ctx, default=default)
        if flag is None:
            result.flag_key = flag_key
        return result

    def is_enabled(self, flag_key: str, user_key: str,
                   attributes: dict[str, Any] | None = None) -> bool:
        return bool(self.evaluate(flag_key, user_key, attributes).value)

    def get_value(self, flag_key: str, user_key: str,
                  attributes: dict[str, Any] | None = None, default: Any = False) -> Any:
        return self.evaluate(flag_key, user_key, attributes, default=default).value
