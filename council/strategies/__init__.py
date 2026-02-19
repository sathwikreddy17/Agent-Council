"""
Council Strategies
==================

Strategy implementations that define how agents collaborate in a council session.

Available strategies:
    - ``DebateStrategy``: Multi-round debate where agents argue and refine
    - ``PipelineStrategy``: Sequential handoff where each agent builds on the previous
    - ``VoteStrategy``: Independent responses followed by moderator consensus

Each strategy is an async generator that yields ``CouncilEvent`` objects,
enabling real-time streaming to the frontend.
"""

from council.strategies.base import BaseStrategy
from council.strategies.debate import DebateStrategy
from council.strategies.pipeline import PipelineStrategy
from council.strategies.vote import VoteStrategy

__all__ = [
    "BaseStrategy",
    "DebateStrategy",
    "PipelineStrategy",
    "VoteStrategy",
]
