"""
Council Engine
==============

The main orchestrator that ties everything together. The engine:
    1. Reads the configuration to set up councils
    2. Creates Agent objects from config presets
    3. Selects the appropriate strategy (debate/pipeline/vote)
    4. Manages model loading/unloading in LM Studio
    5. Executes the strategy and streams events to the caller

This is the primary interface for running council sessions, used by
both the WebSocket server and any programmatic API calls.

Usage:
    >>> from council import CouncilEngine, load_config
    >>> config = load_config("config.yaml")
    >>> engine = CouncilEngine(config)
    >>>
    >>> # Stream a council session
    >>> async for event in engine.run("general", "Should I use React or Vue?"):
    ...     print(event.type, event.content)
"""

from __future__ import annotations

import logging
from typing import Any, AsyncGenerator, Optional

from council.agent import Agent
from council.config import CouncilConfig
from council.lm_studio import LMStudioClient
from council.models import (
    AgentConfig,
    CouncilEvent,
    CouncilPreset,
    EventType,
    ModeratorConfig,
    StrategyType,
)
from council.strategies import (
    BaseStrategy,
    DebateStrategy,
    PipelineStrategy,
    VoteStrategy,
)

logger = logging.getLogger(__name__)

# Maps strategy types to their implementation classes
STRATEGY_MAP: dict[StrategyType, type[BaseStrategy]] = {
    StrategyType.DEBATE: DebateStrategy,
    StrategyType.PIPELINE: PipelineStrategy,
    StrategyType.VOTE: VoteStrategy,
}


class CouncilEngine:
    """
    Main orchestrator for running council sessions.

    The engine is the central coordinator that:
        - Resolves council presets from configuration
        - Creates Agent instances with the right models and personas
        - Selects and initializes the appropriate strategy
        - Manages the LM Studio client lifecycle
        - Streams events as the council session progresses

    Attributes:
        config: The loaded council configuration
        client: LM Studio API client

    Example:
        >>> engine = CouncilEngine(config)
        >>> async for event in engine.run("general", "Best database for my app?"):
        ...     if event.type == EventType.AGENT_CHUNK:
        ...         print(event.content, end="")
    """

    def __init__(self, config: CouncilConfig):
        """
        Initialize the council engine.

        Args:
            config: Loaded and validated council configuration
        """
        self.config = config
        self.client = LMStudioClient(
            base_url=config.lm_studio.base_url,
            api_key=config.lm_studio.api_key,
        )

    async def close(self):
        """Clean up resources (HTTP connections, etc.)."""
        await self.client.close()

    def _resolve_model_identifier(self, model_key: str) -> str:
        """
        Look up the LM Studio model identifier from a config model key.

        Args:
            model_key: The key used in config.yaml (e.g., "phi4-mini")

        Returns:
            The LM Studio model identifier (e.g., "phi-4-mini-reasoning")

        Raises:
            KeyError: If the model key is not found in configuration
        """
        if model_key not in self.config.models:
            raise KeyError(
                f"Model '{model_key}' not found in configuration. "
                f"Available models: {list(self.config.models.keys())}"
            )
        return self.config.models[model_key].identifier

    def _create_agents(
        self,
        agent_configs: list[AgentConfig],
        model_overrides: Optional[dict[str, str]] = None,
    ) -> list[Agent]:
        """
        Create Agent objects from a list of agent configurations.

        Args:
            agent_configs: List of AgentConfig from a council preset
            model_overrides: Optional dict mapping agent index (as string)
                             to a model key to swap for that agent

        Returns:
            List of initialized Agent objects
        """
        agents = []
        for idx, ac in enumerate(agent_configs):
            # Check if the user overrode this agent's model
            model_key = ac.model
            if model_overrides and str(idx) in model_overrides:
                override_key = model_overrides[str(idx)]
                if override_key in self.config.models:
                    logger.info(
                        f"Model override: agent '{ac.role}' "
                        f"changed from '{model_key}' to '{override_key}'"
                    )
                    model_key = override_key

            model_identifier = self._resolve_model_identifier(model_key)
            agents.append(
                Agent(
                    role=ac.role,
                    model_key=model_key,
                    model_identifier=model_identifier,
                    persona=ac.persona,
                )
            )
        return agents

    def _create_moderator(
        self,
        moderator_config: ModeratorConfig,
        model_overrides: Optional[dict[str, str]] = None,
    ) -> Agent:
        """
        Create a moderator Agent from configuration.

        Args:
            moderator_config: Moderator configuration from a council preset
            model_overrides: Optional dict; if it contains a "moderator" key,
                             that model key will be used instead

        Returns:
            An Agent configured as the moderator
        """
        model_key = moderator_config.model
        if model_overrides and "moderator" in model_overrides:
            override_key = model_overrides["moderator"]
            if override_key in self.config.models:
                logger.info(
                    f"Model override: moderator changed from "
                    f"'{model_key}' to '{override_key}'"
                )
                model_key = override_key

        model_identifier = self._resolve_model_identifier(model_key)
        return Agent(
            role="Moderator",
            model_key=model_key,
            model_identifier=model_identifier,
            persona=moderator_config.persona,
        )

    def _create_strategy(
        self,
        preset: CouncilPreset,
        agents: list[Agent],
        moderator: Agent,
        temperature: float,
        max_tokens: int,
    ) -> BaseStrategy:
        """
        Create the appropriate strategy instance for a council preset.

        Args:
            preset: The council preset configuration
            agents: List of Agent objects
            moderator: The moderator Agent
            temperature: Sampling temperature
            max_tokens: Maximum tokens per response

        Returns:
            An initialized strategy object

        Raises:
            ValueError: If the strategy type is unknown
        """
        strategy_class = STRATEGY_MAP.get(preset.strategy)
        if strategy_class is None:
            raise ValueError(
                f"Unknown strategy '{preset.strategy}'. "
                f"Available: {list(STRATEGY_MAP.keys())}"
            )

        return strategy_class(
            client=self.client,
            agents=agents,
            moderator=moderator,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    async def run(
        self,
        council_key: str,
        task: str,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        debate_rounds: Optional[int] = None,
        model_overrides: Optional[dict[str, str]] = None,
    ) -> AsyncGenerator[CouncilEvent, None]:
        """
        Run a council session and stream events in real-time.

        This is the main entry point for executing a council session.
        It resolves the council preset, creates agents, selects the
        strategy, and streams events as the session progresses.

        Args:
            council_key: Key of the council preset (e.g., "general", "coding")
            task: The user's question or task for the council
            temperature: Override default temperature (optional)
            max_tokens: Override default max_tokens (optional)
            debate_rounds: Override default debate rounds (optional)
            model_overrides: Dict mapping agent index (as string) or "moderator"
                             to a model key from config. Allows swapping models
                             for individual agents per session. (optional)

        Yields:
            CouncilEvent objects for real-time streaming to the UI.

        Raises:
            KeyError: If the council_key is not found in configuration
            ValueError: If the council has invalid configuration

        Example:
            >>> async for event in engine.run("general", "Best JS framework?"):
            ...     if event.type == EventType.AGENT_CHUNK:
            ...         print(event.content, end="", flush=True)
            ...     elif event.type == EventType.MODERATOR_DONE:
            ...         print(f"\\n\\nFinal Answer: {event.content}")
        """
        # Resolve council preset
        if council_key not in self.config.councils:
            yield CouncilEvent(
                type=EventType.ERROR,
                content=f"Council '{council_key}' not found. "
                        f"Available: {list(self.config.councils.keys())}",
            )
            return

        preset = self.config.councils[council_key]

        # Apply defaults for optional parameters
        temp = temperature if temperature is not None else self.config.defaults.temperature
        tokens = max_tokens if max_tokens is not None else self.config.defaults.max_tokens
        rounds = debate_rounds if debate_rounds is not None else preset.debate_rounds

        # Status update
        yield CouncilEvent(
            type=EventType.STATUS,
            content=f"Starting {preset.name} ({preset.strategy.value} strategy)",
            metadata={
                "council": council_key,
                "strategy": preset.strategy.value,
                "agents": [a.role for a in preset.agents],
                "debate_rounds": rounds,
            },
        )

        try:
            # Create agents and moderator (applying model overrides if provided)
            agents = self._create_agents(preset.agents, model_overrides)

            if preset.moderator is None:
                yield CouncilEvent(
                    type=EventType.ERROR,
                    content=f"Council '{council_key}' has no moderator configured.",
                )
                return

            moderator = self._create_moderator(preset.moderator, model_overrides)

            # Create and execute strategy
            strategy = self._create_strategy(preset, agents, moderator, temp, tokens)

            async for event in strategy.execute(task, debate_rounds=rounds):
                yield event

        except KeyError as e:
            yield CouncilEvent(
                type=EventType.ERROR,
                content=f"Configuration error: {str(e)}",
            )
        except Exception as e:
            logger.exception(f"Council session error: {e}")
            yield CouncilEvent(
                type=EventType.ERROR,
                content=f"Unexpected error: {str(e)}",
            )

    async def get_available_councils(self) -> dict[str, dict]:
        """
        Get information about all available council presets.

        Returns:
            Dictionary mapping council keys to their display info.

        Example:
            >>> councils = await engine.get_available_councils()
            >>> for key, info in councils.items():
            ...     print(f"{info['name']}: {info['description']}")
        """
        result = {}
        for key, preset in self.config.councils.items():
            result[key] = {
                "name": preset.name,
                "description": preset.description,
                "strategy": preset.strategy.value,
                "debate_rounds": preset.debate_rounds,
                "agents": [
                    {"role": a.role, "model": a.model}
                    for a in preset.agents
                ],
                "moderator_model": preset.moderator.model if preset.moderator else None,
            }
        return result

    async def get_available_models(self) -> dict[str, dict]:
        """
        Get information about all configured models.

        Returns:
            Dictionary mapping model keys to their info.
        """
        result = {}
        for key, model in self.config.models.items():
            result[key] = {
                "name": model.name,
                "identifier": model.identifier,
                "strengths": model.strengths,
                "size": model.size,
                "context_length": model.context_length,
            }
        return result

    async def check_lm_studio(self) -> dict[str, Any]:
        """
        Check LM Studio connectivity and status.

        Returns:
            Dictionary with health check info:
            - connected (bool): Whether LM Studio is reachable
            - models (list): Currently available models
        """
        connected = await self.client.health_check()
        models = []
        if connected:
            models = await self.client.list_models()
        return {
            "connected": connected,
            "models": [m.get("id", "unknown") for m in models],
        }
