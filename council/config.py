"""
Configuration Loader
====================

Loads and validates the YAML configuration file (``config.yaml``) that defines
all available models, council presets, and default settings.

The config file is the central place to:
    - Define which LM Studio models are available
    - Create council presets with specific agents, roles, and strategies
    - Set default parameters (temperature, max tokens, etc.)

Usage:
    >>> from council.config import load_config
    >>> config = load_config("config.yaml")
    >>> print(config.councils["general"].name)
    "General Council"
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Optional

import yaml
from pydantic import BaseModel, Field

from council.models import (
    AgentConfig,
    CouncilPreset,
    ModelInfo,
    ModeratorConfig,
    StrategyType,
)


class LMStudioConfig(BaseModel):
    """
    LM Studio connection settings.

    Attributes:
        base_url: The base URL for LM Studio's API server
        api_key: API key (LM Studio uses a dummy key, defaults to "lm-studio")
    """

    base_url: str = "http://localhost:1234/v1"
    api_key: str = "lm-studio"


class DefaultsConfig(BaseModel):
    """
    Default parameters applied to all council sessions unless overridden.

    Attributes:
        temperature: Sampling temperature (0.0 = deterministic, 1.0 = creative)
        max_tokens: Maximum tokens per agent response
        council: Default council preset to use
    """

    temperature: float = 0.7
    max_tokens: int = 2048
    council: str = "general"


class CouncilConfig(BaseModel):
    """
    Top-level configuration container.

    This is the root object that holds all configuration loaded from
    ``config.yaml``. It contains LM Studio connection info, all model
    definitions, all council presets, and default settings.

    Attributes:
        lm_studio: LM Studio connection configuration
        models: Dictionary of available models (key → ModelInfo)
        councils: Dictionary of council presets (key → CouncilPreset)
        defaults: Default parameters for council sessions
    """

    lm_studio: LMStudioConfig = Field(default_factory=LMStudioConfig)
    models: dict[str, ModelInfo] = Field(default_factory=dict)
    councils: dict[str, CouncilPreset] = Field(default_factory=dict)
    defaults: DefaultsConfig = Field(default_factory=DefaultsConfig)


def load_config(config_path: str = "config.yaml") -> CouncilConfig:
    """
    Load and validate the council configuration from a YAML file.

    Reads the YAML file, parses the model definitions, council presets
    (including agent and moderator configs), and returns a fully validated
    ``CouncilConfig`` object.

    Args:
        config_path: Path to the YAML configuration file.
                     Defaults to "config.yaml" in the current directory.

    Returns:
        A validated ``CouncilConfig`` object.

    Raises:
        FileNotFoundError: If the config file doesn't exist.
        yaml.YAMLError: If the YAML is malformed.
        pydantic.ValidationError: If the config doesn't match the expected schema.

    Example:
        >>> config = load_config("config.yaml")
        >>> config.lm_studio.base_url
        'http://localhost:1234/v1'
        >>> len(config.models)
        8
    """
    config_file = Path(config_path)
    if not config_file.exists():
        raise FileNotFoundError(
            f"Configuration file not found: {config_path}\n"
            f"Expected location: {config_file.absolute()}\n"
            f"Please create a config.yaml file. See README.md for details."
        )

    with open(config_file, "r") as f:
        raw = yaml.safe_load(f)

    # Parse LM Studio config
    lm_studio = LMStudioConfig(**(raw.get("lm_studio", {})))

    # Parse model definitions
    models: dict[str, ModelInfo] = {}
    for key, model_data in raw.get("models", {}).items():
        models[key] = ModelInfo(**model_data)

    # Parse council presets
    councils: dict[str, CouncilPreset] = {}
    for key, council_data in raw.get("councils", {}).items():
        # Parse agents
        agents = [
            AgentConfig(**agent_data)
            for agent_data in council_data.get("agents", [])
        ]

        # Parse moderator
        moderator = None
        if "moderator" in council_data:
            moderator = ModeratorConfig(**council_data["moderator"])

        # Parse strategy
        strategy = StrategyType(council_data.get("strategy", "debate"))

        councils[key] = CouncilPreset(
            name=council_data.get("name", key),
            description=council_data.get("description", ""),
            strategy=strategy,
            debate_rounds=council_data.get("debate_rounds", 2),
            agents=agents,
            moderator=moderator,
        )

    # Parse defaults
    defaults = DefaultsConfig(**(raw.get("defaults", {})))

    return CouncilConfig(
        lm_studio=lm_studio,
        models=models,
        councils=councils,
        defaults=defaults,
    )
