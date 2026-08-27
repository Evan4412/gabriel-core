"""Gabriel policy layer: PEEL (Policy Enforcement & Evaluation Layer).

The gatekeeper that ensures every command is authorized before execution.

Implements:
- Policy resources (Effect, PolicyStatement, Policy)
- PolicyEngine (evaluates requests against policies)
- PEEL (enforces policies before command dispatch)
"""

from gabriel.policy.engine import EvaluationRequest, PolicyEngine
from gabriel.policy.exceptions import (
    PolicyError,
    UnauthorizedError,
)
from gabriel.policy.models import Effect, Policy, PolicyStatement
from gabriel.policy.orm import PolicyORM
from gabriel.policy.peel import PEEL
from gabriel.policy.repository import PolicyRepository
from gabriel.policy.service import PolicyService

__all__ = [
    # Models
    "Effect",
    "PolicyStatement",
    "Policy",
    "PolicyORM",
    "PolicyRepository",
    "PolicyService",
    # Engine
    "PolicyEngine",
    "EvaluationRequest",
    # PEEL
    "PEEL",
    # Exceptions
    "PolicyError",
    "UnauthorizedError",
]
