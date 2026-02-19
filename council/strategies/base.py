"""
Base Strategy
=============

Abstract base class for all council strategies. Each strategy defines
how agents interact during a council session.

A strategy is responsible for:
    1. Determining the order in which agents speak
    2. What context each agent receives
    3. How many rounds of interaction occur
    4. When the moderator is called for final synthesis

All strategies are implemented as async generators that yield
``CouncilEvent`` objects for real-time streaming.
"""

from __future__ import annotations

import abc
from typing import AsyncGenerator

from council.agent import Agent
from council.lm_studio import LMStudioClient
from council.models import AgentMessage, CouncilEvent


class BaseStrategy(abc.ABC):
    """
    Abstract base class for council collaboration strategies.

    Subclasses must implement the ``execute()`` method, which is an
    async generator that orchestrates the agent interactions and yields
    events for real-time streaming.

    Attributes:
        client: LM Studio API client for sending chat requests
        agents: List of Agent objects participating in the council
        moderator: The moderator Agent for final synthesis
        temperature: Sampling temperature for model responses
        max_tokens: Maximum tokens per response
    """

    def __init__(
        self,
        client: LMStudioClient,
        agents: list[Agent],
        moderator: Agent,
        temperature: float = 0.7,
        max_tokens: int = 2048,
    ):
        """
        Initialize the strategy.

        Args:
            client: LM Studio API client
            agents: List of agents participating in the council
            moderator: The moderator agent for final synthesis
            temperature: Sampling temperature (0.0-1.0)
            max_tokens: Max tokens per agent response
        """
        self.client = client
        self.agents = agents
        self.moderator = moderator
        self.temperature = temperature
        self.max_tokens = max_tokens

    @abc.abstractmethod
    async def execute(
        self, task: str, **kwargs
    ) -> AsyncGenerator[CouncilEvent, None]:
        """
        Execute the strategy for the given task.

        This is the main entry point for running a council session.
        It should yield ``CouncilEvent`` objects as the session progresses,
        enabling real-time streaming to the UI.

        Args:
            task: The user's question or task for the council.
            **kwargs: Strategy-specific parameters (e.g., debate_rounds).

        Yields:
            CouncilEvent objects representing the session progress.
        """
        ...  # pragma: no cover

    async def _stream_agent_response(
        self,
        agent: Agent,
        messages: list[dict[str, str]],
        round_num: int = 1,
    ) -> AsyncGenerator[CouncilEvent, None]:
        """
        Stream a single agent's response, yielding events for each chunk.

        This helper method handles:
            1. Ensuring the agent's model is loaded
            2. Emitting AGENT_START event
            3. Streaming response chunks as AGENT_CHUNK events
            4. Emitting AGENT_DONE event with the full response

        Args:
            agent: The agent whose turn it is to respond
            messages: The chat messages to send to the model
            round_num: Current round number (for event metadata)

        Yields:
            CouncilEvent objects (AGENT_START, AGENT_CHUNK, AGENT_DONE)
        """
        from council.models import EventType

        # Ensure model is loaded
        yield CouncilEvent(
            type=EventType.MODEL_LOADING,
            agent=agent.role,
            content=f"Loading model {agent.model_identifier}...",
            metadata={"model": agent.model_identifier},
        )

        await self.client.ensure_model_loaded(agent.model_identifier)

        yield CouncilEvent(
            type=EventType.MODEL_LOADED,
            agent=agent.role,
            content=f"Model {agent.model_identifier} ready",
            metadata={"model": agent.model_identifier},
        )

        # Signal agent is starting
        yield CouncilEvent(
            type=EventType.AGENT_START,
            agent=agent.role,
            round=round_num,
            metadata={"model": agent.model_key},
        )

        # Stream the response
        full_response = ""
        has_error = False
        try:
            async for chunk in self.client.chat_stream(
                model_identifier=agent.model_identifier,
                messages=messages,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
            ):
                # Detect error messages from chat_stream's error handler
                if chunk.startswith("\n\n[Error:") or chunk.startswith("[Error:"):
                    has_error = True
                full_response += chunk
                yield CouncilEvent(
                    type=EventType.AGENT_CHUNK,
                    agent=agent.role,
                    round=round_num,
                    content=chunk,
                )

            # Fallback: if streaming produced no/clearly-truncated text,
            # try one non-stream call.
            normalized_streamed = full_response.strip()
            streamed_lower = normalized_streamed.lower()
            looks_truncated = (
                not normalized_streamed
                or normalized_streamed in {"<think>", "</think>", "<think></think>"}
                or (len(normalized_streamed) < 32 and "<think>" in streamed_lower)
            )
            if not has_error and looks_truncated:
                fallback_response = await self.client.chat_once(
                    model_identifier=agent.model_identifier,
                    messages=messages,
                    temperature=self.temperature,
                    max_tokens=self.max_tokens,
                )
                if fallback_response:
                    # If fallback starts with streamed content, append only the missing tail.
                    content_to_emit = fallback_response
                    if normalized_streamed and fallback_response.startswith(full_response):
                        content_to_emit = fallback_response[len(full_response):]
                    elif normalized_streamed:
                        # Replace visibly-truncated streamed output with full fallback.
                        content_to_emit = "\n" + fallback_response

                    full_response = fallback_response
                    yield CouncilEvent(
                        type=EventType.AGENT_CHUNK,
                        agent=agent.role,
                        round=round_num,
                        content=content_to_emit,
                    )
        except Exception as e:
            has_error = True
            error_msg = f"[Error: {agent.role} failed — {str(e)}]"
            full_response = error_msg
            yield CouncilEvent(
                type=EventType.AGENT_CHUNK,
                agent=agent.role,
                round=round_num,
                content=error_msg,
            )

        # Signal agent is done
        yield CouncilEvent(
            type=EventType.AGENT_DONE,
            agent=agent.role,
            round=round_num,
            content=full_response,
            metadata={"model": agent.model_key, "error": has_error},
        )
