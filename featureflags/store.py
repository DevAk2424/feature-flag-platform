"""Service layer: flag CRUD, versioning, history, audit log, metrics.

Every mutation goes through here, whether it arrives via the HTTP API,
the demo, or an *approved* risk-agent proposal. That single funnel is
what guarantees: version increments, a history snapshot for rollback,
and an audit entry for every change.
"""
from __future__ import annotations

import copy
import threading
import time
import uuid
from typing import Any

from .engine import Flag


def _now() -> float:
    return time.time()


class FlagStore:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._flags: dict[str, Flag] = {}
        # key -> {version: flag-dict snapshot at that version}
        self._history: dict[str, dict[int, dict]] = {}
        self._audit: list[dict] = []
        self._metrics: dict[str, list[dict]] = {}
        self.config_version = 0  # global, increments on any flag mutation

    # ---- helpers -------------------------------------------------
    def _record(self, actor: str, action: str, flag_key: str,
                old: Any, new: Any, version: int | None) -> dict:
        entry = {
            "id": uuid.uuid4().hex[:12],
            "timestamp": _now(),
            "actor": actor or "system",
            "action": action,
            "flag_key": flag_key,
            "old_value": copy.deepcopy(old),
            "new_value": copy.deepcopy(new),
            "version": version,
        }
        self._audit.append(entry)
        return entry

    def _commit(self, actor: str, action: str, flag: Flag, old_dict: dict | None) -> Flag:
        flag.version = (old_dict["version"] + 1) if old_dict else 1
        if old_dict is None:
            flag.version = max(flag.version, 1)
            # creation: if caller supplied a version >1 keep monotonic start at 1
            flag.version = 1
        self._flags[flag.key] = flag
        self._history.setdefault(flag.key, {})[flag.version] = flag.to_dict()
        self.config_version += 1
        self._record(actor, action, flag.key, old_dict, flag.to_dict(), flag.version)
        return flag

    # ---- CRUD ----------------------------------------------------
    def create_flag(self, data: dict, actor: str = "system") -> Flag:
        with self._lock:
            if data["key"] in self._flags:
                raise KeyError(f"flag already exists: {data['key']}")
            data = copy.deepcopy(data)
            data["version"] = 1
            flag = Flag.from_dict(data)
            return copy.deepcopy(self._commit(actor, "CREATE", flag, None))

    def get_flag(self, key: str) -> Flag | None:
        with self._lock:
            f = self._flags.get(key)
            return copy.deepcopy(f) if f else None

    def list_flags(self, env: str | None = None) -> list[Flag]:
        with self._lock:
            flags = [copy.deepcopy(f) for f in self._flags.values()
                     if env is None or f.environment == env]
            return sorted(flags, key=lambda f: f.key)

    def update_flag(self, key: str, data: dict, actor: str = "system") -> Flag:
        """Full or partial update; version always increments."""
        with self._lock:
            existing = self._flags.get(key)
            if existing is None:
                raise KeyError(f"flag not found: {key}")
            old = existing.to_dict()
            merged = {**old, **copy.deepcopy(data), "key": key}
            flag = Flag.from_dict(merged)
            return copy.deepcopy(self._commit(actor, "UPDATE", flag, old))

    def patch_rollout(self, key: str, percentage: float, actor: str = "system") -> Flag:
        if not 0 <= percentage <= 100:
            raise ValueError("percentage must be between 0 and 100")
        return self.update_flag(key, {"fallthrough_percentage": float(percentage)},
                                actor=actor)

    def set_enabled(self, key: str, enabled: bool, actor: str = "system") -> Flag:
        with self._lock:
            existing = self._flags.get(key)
            if existing is None:
                raise KeyError(f"flag not found: {key}")
            old = existing.to_dict()
            flag = Flag.from_dict({**old, "enabled": bool(enabled)})
            action = "ENABLE" if enabled else "KILL_SWITCH"
            return copy.deepcopy(self._commit(actor, action, flag, old))

    def delete_flag(self, key: str, actor: str = "system") -> None:
        with self._lock:
            existing = self._flags.pop(key, None)
            if existing is None:
                raise KeyError(f"flag not found: {key}")
            self.config_version += 1
            self._record(actor, "DELETE", key, existing.to_dict(), None, existing.version)

    # ---- snapshot / rollback / audit -----------------------------
    def snapshot(self, env: str = "prod") -> dict:
        with self._lock:
            return {
                "env": env,
                "version": self.config_version,
                "generated_at": _now(),
                "flags": [f.to_dict() for f in self.list_flags(env)],
            }

    def history(self, key: str) -> dict[int, dict]:
        with self._lock:
            return copy.deepcopy(self._history.get(key, {}))

    def rollback(self, key: str, to_version: int, actor: str = "system") -> Flag:
        """Restore content from a previous version, as a NEW version.

        Rolling the version number backwards would break SDK cache
        invalidation (clients ignore older versions), so rollback is a
        forward-moving write whose payload is the old snapshot.
        """
        with self._lock:
            existing = self._flags.get(key)
            if existing is None:
                raise KeyError(f"flag not found: {key}")
            snap = self._history.get(key, {}).get(int(to_version))
            if snap is None:
                raise KeyError(f"version {to_version} not found for {key}")
            old = existing.to_dict()
            restored = Flag.from_dict(copy.deepcopy(snap))
            result = self._commit(actor, "ROLLBACK", restored, old)
            # annotate the newest audit entry with the source version
            self._audit[-1]["rolled_back_to_version"] = int(to_version)
            return copy.deepcopy(result)

    def audit_log(self, flag_key: str | None = None) -> list[dict]:
        with self._lock:
            rows = self._audit
            if flag_key:
                rows = [r for r in rows if r["flag_key"] == flag_key]
            return copy.deepcopy(rows)

    # ---- metrics ---------------------------------------------------
    def ingest_metrics(self, flag_key: str, metrics: dict) -> dict:
        with self._lock:
            if flag_key not in self._flags:
                raise KeyError(f"flag not found: {flag_key}")
            row = {"flag_key": flag_key, "timestamp": _now(), **copy.deepcopy(metrics)}
            self._metrics.setdefault(flag_key, []).append(row)
            return copy.deepcopy(row)

    def latest_metrics(self, flag_key: str) -> dict | None:
        with self._lock:
            rows = self._metrics.get(flag_key, [])
            return copy.deepcopy(rows[-1]) if rows else None

    def all_metrics(self, flag_key: str) -> list[dict]:
        with self._lock:
            return copy.deepcopy(self._metrics.get(flag_key, []))
