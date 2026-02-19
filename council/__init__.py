"""
Agent Council — A Multi-Agent AI Debate & Collaboration System
==============================================================

This package provides the core engine for running councils of AI agents
that debate, collaborate, and synthesize answers using local LLMs via LM Studio.

Main Components:
    - ``LMStudioClient``: Manages communication with LM Studio's API
    - ``Agent``: Wraps a model with a role and persona
    - ``CouncilEngine``: Orchestrates agent collaboration strategies
    - ``Config``: Loads and validates YAML configuration

Quick Start:
    >>> from council import CouncilEngine, load_config
    >>> config = load_config("config.yaml")
    >>> engine = CouncilEngine(config)
    >>> result = await engine.run("general", "What is the best database?")

See README.md for full documentation.
"""

from council.config import load_config, CouncilConfig
from council.engine import CouncilEngine
from council.agent import Agent
from council.lm_studio import LMStudioClient
from council.models import (
    AgentMessage,
    CouncilResult,
    CouncilEvent,
    EventType,
    ModelInfo,
    AgentConfig,
    CouncilPreset,
)

__all__ = [
    "load_config",
    "CouncilConfig",
    "CouncilEngine",
    "Agent",
    "LMStudioClient",
    "AgentMessage",
    "CouncilResult",
    "CouncilEvent",
    "EventType",
    "ModelInfo",
    "AgentConfig",
    "CouncilPreset",
]

__version__ = "1.0.0"
