"""
Vote Strategy
=============

Simple consensus strategy where all agents respond independently
(without seeing each other's answers), and the moderator determines
the consensus or picks the best answer.

Flow:
    1. All agents respond to the task **independently** (no cross-talk)
    2. The moderator sees all responses and:
       - Identifies areas of agreement
       - Notes disagreements
       - Picks the best answer or synthesizes a consensus

This strategy is best for:
    - Factual questions where you want to cross-check accuracy
    - Quick decisions where debate rounds would be overkill
    - Getting diverse perspectives without debate bias

It's the fastest strategy since there's only one round and no
inter-agent context building.
"""

from __future__ import annotations

from typing import AsyncGenerator

from council.agent import Agent
from council.lm_studio import LMStudioClient
from council.models import CouncilEvent, EventType
from council.strategies.base import BaseStrategy


class VoteStrategy(BaseStrategy):
    """
    Independent voting strategy with moderator consensus.

    All agents respond independently to the task (they don't see each
    other's responses). The moderator then analyzes all responses to
    find consensus or select the best answer.
    """

    async def execute(
        self, task: str, **kwargs
    ) -> AsyncGenerator[CouncilEvent, None]:
        """
        Execute independent voting.

        Args:
            task: The user's question or task.

        Yields:
            CouncilEvent objects for real-time streaming.
        """
        all_messages: list[dict[str, str]] = []

        yield CouncilEvent(
            type=EventType.ROUND_START,
            round=1,
            content="Collecting independent votes",
            metadata={"total_agents": len(self.agents)},
        )

        # Each agent responds independently (no history shared)
        for agent in self.agents:
            messages = agent.build_messages(
                task=task,
                history=None,  # No history — independent responses
                round_num=1,
            )

            full_response = ""
            async for event in self._stream_agent_response(
                agent, messages, round_num=1
            ):
                if event.type == EventType.AGENT_DONE:
                    full_response = event.content
                yield event

            all_messages.append({
                "role": agent.role,
                "content": full_response,
                "round": 1,
            })

        yield CouncilEvent(
            type=EventType.ROUND_DONE,
            round=1,
            content="All votes collected",
        )

        # ---- Moderator consensus ----
        yield CouncilEvent(
            type=EventType.MODERATOR_START,
            agent="Moderator",
            content="Analyzing votes and building consensus...",
        )

        # Custom moderator prompt for voting
        moderator_messages = self.moderator.build_moderator_messages(
            task=task,
            all_messages=all_messages,
            strategy="vote",
        )

        full_moderator_response = ""
        async for event in self._stream_agent_response(
            self.moderator, moderator_messages, round_num=0
        ):
            if event.type == EventType.AGENT_CHUNK:
                event.type = EventType.MODERATOR_CHUNK
                event.agent = "Moderator"
                full_moderator_response += event.content
            elif event.type == EventType.AGENT_DONE:
                event.type = EventType.MODERATOR_DONE
                event.agent = "Moderator"
                full_moderator_response = event.content
            elif event.type == EventType.AGENT_START:
                continue
            yield event

        yield CouncilEvent(
            type=EventType.COUNCIL_DONE,
            content="Voting session complete",
            metadata={
                "total_agents": len(self.agents),
                "total_messages": len(all_messages),
            },
        )
