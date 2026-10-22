import unittest
from featureflags.engine import (Flag, Rule, Clause, Target, EvaluationContext,
                                  evaluate, compute_bucket, KILL_SWITCH, RULE_MATCH,
                                  TARGET_MATCH, FALLOUT_ROLLOUT, FLAG_NOT_FOUND)


def ctx(user, **attrs):
    return EvaluationContext(user, attrs)


class TestHashingAndRollout(unittest.TestCase):
    def test_bucket_stable_and_in_range(self):
        b1 = compute_bucket("checkout-redesign", "salt1", "user-42")
        b2 = compute_bucket("checkout-redesign", "salt1", "user-42")
        self.assertEqual(b1, b2)
        self.assertTrue(0 <= b1 <= 9999)

    def test_bucket_differs_by_user_and_salt(self):
        buckets = {compute_bucket("f", "s", f"user-{i}") for i in range(200)}
        self.assertGreater(len(buckets), 150)  # good spread, not degenerate
        self.assertNotEqual(compute_bucket("f", "s1", "u"), compute_bucket("f", "s2", "u"))

    def test_rollout_monotonic_inclusion(self):
        flag = Flag(key="f")
        users = [f"user-{i}" for i in range(2000)]
        prev = set()
        for pct in (5, 10, 25, 50, 80, 100):
            flag.fallthrough_percentage = pct
            current = {u for u in users if evaluate(flag, ctx(u)).value}
            self.assertTrue(prev.issubset(current),
                            f"users dropped out when rollout rose to {pct}%")
            prev = current

    def test_rollout_approximates_percentage(self):
        flag = Flag(key="f", fallthrough_percentage=50)
        users = [f"user-{i}" for i in range(4000)]
        hits = sum(1 for u in users if evaluate(flag, ctx(u)).value)
        self.assertTrue(0.42 < hits / len(users) < 0.58)

    def test_percentage_edges(self):
        flag0 = Flag(key="f", fallthrough_percentage=0)
        flag100 = Flag(key="f", fallthrough_percentage=100)
        for i in range(200):
            self.assertFalse(evaluate(flag0, ctx(f"u{i}")).value)
            self.assertTrue(evaluate(flag100, ctx(f"u{i}")).value)


class TestEvaluation(unittest.TestCase):
    def test_kill_switch_overrides_everything(self):
        flag = Flag(key="f", enabled=False,
                    targets=[Target(["u1"], "on")],
                    rules=[Rule("r", "on", [Clause("segment", "in", ["beta"])])])
        r = evaluate(flag, ctx("u1", segment="beta"))
        self.assertEqual(r.reason, KILL_SWITCH)
        self.assertFalse(r.value)

    def test_flag_not_found(self):
        r = evaluate(None, ctx("u1"))
        self.assertEqual(r.reason, FLAG_NOT_FOUND)
        self.assertFalse(r.value)

    def test_target_match(self):
        flag = Flag(key="f", fallthrough_percentage=0, targets=[Target(["vip-1"], "on")])
        self.assertEqual(evaluate(flag, ctx("vip-1")).reason, TARGET_MATCH)
        self.assertTrue(evaluate(flag, ctx("vip-1")).value)
        self.assertFalse(evaluate(flag, ctx("other")).value)

    def test_fallthrough_reason(self):
        flag = Flag(key="f", fallthrough_percentage=100)
        self.assertEqual(evaluate(flag, ctx("anyone")).reason, FALLOUT_ROLLOUT)


class TestTargetingOperators(unittest.TestCase):
    def flag_with(self, clause):
        return Flag(key="f", fallthrough_percentage=0,
                    rules=[Rule("r1", "on", [clause])])

    def check(self, clause, attrs, expected):
        r = evaluate(self.flag_with(clause), ctx("u", **attrs))
        self.assertEqual(bool(r.value), expected, f"{clause} vs {attrs}")
        if expected:
            self.assertEqual(r.reason, RULE_MATCH)

    def test_equals_and_in(self):
        self.check(Clause("plan", "equals", ["pro"]), {"plan": "pro"}, True)
        self.check(Clause("plan", "equals", ["pro"]), {"plan": "free"}, False)
        self.check(Clause("segment", "in", ["beta", "staff"]), {"segment": "staff"}, True)
        self.check(Clause("segment", "not_in", ["blocked"]), {"segment": "ok"}, True)

    def test_string_operators(self):
        self.check(Clause("email", "endsWith", ["@example.com"]), {"email": "a@example.com"}, True)
        self.check(Clause("email", "startsWith", ["admin"]), {"email": "admin1"}, True)
        self.check(Clause("country", "contains", ["land"]), {"country": "Finland"}, True)
        self.check(Clause("email", "regex", [r"@example\.(com|org)$"]), {"email": "a@example.org"}, True)
        self.check(Clause("email", "regex", [r"^admin"]), {"email": "user@example.org"}, False)

    def test_numeric_operators(self):
        self.check(Clause("age", "gt", [18]), {"age": 21}, True)
        self.check(Clause("age", "gt", [18]), {"age": 12}, False)
        self.check(Clause("age", "lte", [65]), {"age": 65}, True)
        self.check(Clause("version", "gte", [3]), {"version": 2}, False)

    def test_user_key_clause_and_rule_order(self):
        flag = Flag(key="f", fallthrough_percentage=0, variations={"on": True, "off": False, "alt": "ALT"},
                    rules=[Rule("first", "alt", [Clause("key", "equals", ["u1"])]),
                           Rule("second", "on", [Clause("key", "equals", ["u1"])])])
        r = evaluate(flag, ctx("u1"))
        self.assertEqual(r.variation, "alt")  # first matching rule wins
        self.assertEqual(r.rule_id, "first")


if __name__ == "__main__":
    unittest.main()
