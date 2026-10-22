"""Core evaluation engine.

Design intent:
- Evaluation is a pure, deterministic function of (flag, user context).
  That is what lets SDKs evaluate locally with no network call, and lets
  the same user get the same answer on every instance / process.
- Bucketing uses SHA-256 over ``flag_key.salt.user_key`` mapped to
  0..9999. SHA-256 is in the stdlib everywhere, is stable across
  processes (unlike Python's salted ``hash()``), and distributes well.
- Rollout inclusion is monotonic: a user in at 10% is still in at 25%
  because inclusion is ``bucket < percentage * 100``.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field, asdict
from typing import Any

BUCKET_COUNT = 10_000  # 0..9999, so 1 bucket = 0.01%

# Evaluation reasons (stable strings, part of the public contract)
FLAG_NOT_FOUND = "FLAG_NOT_FOUND"
KILL_SWITCH = "KILL_SWITCH"
TARGET_MATCH = "TARGET_MATCH"
RULE_MATCH = "RULE_MATCH"
FALLOUT_ROLLOUT = "FALLOUT_ROLLOUT"
FALLOUT_OFF = "FALLOUT_OFF"


def compute_bucket(flag_key: str, salt: str, user_key: str) -> int:
    """Deterministic bucket in [0, 9999] for a user on a flag."""
    material = f"{flag_key}.{salt}.{user_key}".encode("utf-8")
    digest = hashlib.sha256(material).hexdigest()
    return int(digest[:8], 16) % BUCKET_COUNT


def bucket_in_rollout(bucket: int, percentage: float) -> bool:
    """Monotonic inclusion check: raising % never drops an included user."""
    if percentage <= 0:
        return False
    if percentage >= 100:
        return True
    return bucket < int(percentage * 100)


@dataclass
class Clause:
    attribute: str
    operator: str  # equals, not_equals, in, not_in, startsWith, endsWith,
    #                contains, gt, gte, lt, lte, regex, exists, not_exists
    values: list[Any] = field(default_factory=list)

    def matches(self, context: "EvaluationContext") -> bool:
        actual = context.get(self.attribute)
        op = self.operator
        if op == "exists":
            return actual is not None
        if op == "not_exists":
            return actual is None
        if actual is None:
            return False
        vals = self.values
        try:
            if op == "equals":
                return any(actual == v for v in vals)
            if op == "not_equals":
                return all(actual != v for v in vals)
            if op == "in":
                return actual in vals
            if op == "not_in":
                return actual not in vals
            if op == "startsWith":
                return isinstance(actual, str) and any(actual.startswith(str(v)) for v in vals)
            if op == "endsWith":
                return isinstance(actual, str) and any(actual.endswith(str(v)) for v in vals)
            if op == "contains":
                return any(v in actual for v in vals) if hasattr(actual, "__contains__") else False
            if op == "gt":
                return any(actual > v for v in vals)
            if op == "gte":
                return any(actual >= v for v in vals)
            if op == "lt":
                return any(actual < v for v in vals)
            if op == "lte":
                return any(actual <= v for v in vals)
            if op == "regex":
                return isinstance(actual, str) and any(re.search(str(v), actual) for v in vals)
        except TypeError:
            return False
        return False

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Clause":
        return cls(attribute=d["attribute"], operator=d["operator"],
                   values=list(d.get("values", [])))


@dataclass
class Rule:
    id: str
    variation: str
    clauses: list[Clause] = field(default_factory=list)
    rollout_percentage: float = 100.0  # rule can itself be rolled out

    def matches(self, context: "EvaluationContext") -> bool:
        return all(c.matches(context) for c in self.clauses)

    def to_dict(self) -> dict:
        return {"id": self.id, "variation": self.variation,
                "clauses": [c.to_dict() for c in self.clauses],
                "rollout_percentage": self.rollout_percentage}

    @classmethod
    def from_dict(cls, d: dict) -> "Rule":
        return cls(id=d["id"], variation=d["variation"],
                   clauses=[Clause.from_dict(c) for c in d.get("clauses", [])],
                   rollout_percentage=d.get("rollout_percentage", 100.0))


@dataclass
class Target:
    """Explicit allow-list style targeting for specific user keys."""
    values: list[str]  # user keys
    variation: str

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Target":
        return cls(values=list(d.get("values", [])), variation=d["variation"])


@dataclass
class Flag:
    key: str
    enabled: bool = True  # False == kill switch engaged
    version: int = 1  # monotonic, incremented by the service layer on writes
    # variation name -> value served (e.g. {"on": True, "off": False})
    variations: dict[str, Any] = field(default_factory=lambda: {"on": True, "off": False})
    off_variation: str = "off"
    fallthrough_variation: str = "on"
    fallthrough_percentage: float = 100.0
    rules: list[Rule] = field(default_factory=list)
    targets: list[Target] = field(default_factory=list)
    salt: str = ""  # defaults to flag key in __post_init__
    description: str = ""
    environment: str = "prod"
    tags: list[str] = field(default_factory=list)

    def __post_init__(self):
        if not self.salt:
            self.salt = self.key

    def to_dict(self) -> dict:
        d = asdict(self)
        d["rules"] = [r.to_dict() for r in self.rules]
        d["targets"] = [t.to_dict() for t in self.targets]
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Flag":
        return cls(
            key=d["key"], enabled=d.get("enabled", True), version=d.get("version", 1),
            variations=d.get("variations", {"on": True, "off": False}),
            off_variation=d.get("off_variation", "off"),
            fallthrough_variation=d.get("fallthrough_variation", "on"),
            fallthrough_percentage=d.get("fallthrough_percentage", 100.0),
            rules=[Rule.from_dict(r) for r in d.get("rules", [])],
            targets=[Target.from_dict(t) for t in d.get("targets", [])],
            salt=d.get("salt", ""), description=d.get("description", ""),
            environment=d.get("environment", "prod"), tags=list(d.get("tags", [])),
        )


@dataclass
class EvaluationContext:
    user_key: str
    attributes: dict[str, Any] = field(default_factory=dict)

    def get(self, attribute: str) -> Any:
        if attribute in ("key", "user_key", "userKey"):
            return self.user_key
        return self.attributes.get(attribute)


@dataclass
class EvaluationResult:
    flag_key: str
    variation: str | None
    value: Any
    reason: str
    flag_version: int | None = None
    rule_id: str | None = None
    bucket: int | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def evaluate(flag: Flag | None, context: EvaluationContext,
             default: Any = False) -> EvaluationResult:
    """Evaluate a flag for a context. Order is part of the contract:

    not-found -> kill switch -> explicit targets -> rules (in order)
    -> fallthrough rollout.
    """
    if flag is None:
        return EvaluationResult("", None, default, FLAG_NOT_FOUND)
    bucket = compute_bucket(flag.key, flag.salt, context.user_key)
    off_value = flag.variations.get(flag.off_variation, default)
    if not flag.enabled:
        return EvaluationResult(flag.key, flag.off_variation, off_value,
                                KILL_SWITCH, flag.version, bucket=bucket)
    for target in flag.targets:
        if context.user_key in target.values:
            return EvaluationResult(flag.key, target.variation,
                                    flag.variations.get(target.variation, default),
                                    TARGET_MATCH, flag.version, bucket=bucket)
    for rule in flag.rules:
        if rule.matches(context):
            if bucket_in_rollout(bucket, rule.rollout_percentage):
                return EvaluationResult(flag.key, rule.variation,
                                        flag.variations.get(rule.variation, default),
                                        RULE_MATCH, flag.version, rule_id=rule.id,
                                        bucket=bucket)
    if bucket_in_rollout(bucket, flag.fallthrough_percentage):
        return EvaluationResult(flag.key, flag.fallthrough_variation,
                                flag.variations.get(flag.fallthrough_variation, default),
                                FALLOUT_ROLLOUT, flag.version, bucket=bucket)
    return EvaluationResult(flag.key, flag.off_variation, off_value,
                            FALLOUT_OFF, flag.version, bucket=bucket)
