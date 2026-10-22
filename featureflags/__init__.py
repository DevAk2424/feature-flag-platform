"""Distributed Feature Flag and Release Control Platform.

A LaunchDarkly-style reference implementation in pure Python stdlib:
evaluation engine, control plane API, local-evaluation SDK, and a
guarded AI release-risk agent.
"""
from .engine import (Flag, Rule, Clause, Target, EvaluationContext,
                     EvaluationResult, evaluate, compute_bucket)
from .store import FlagStore
from .risk_agent import RiskAgent, analyze_metrics
from .sdk import FeatureFlagClient

__all__ = ["Flag", "Rule", "Clause", "Target", "EvaluationContext",
           "EvaluationResult", "evaluate", "compute_bucket", "FlagStore",
           "RiskAgent", "analyze_metrics", "FeatureFlagClient"]
__version__ = "1.0.0"
