"""
Debate Strategy
===============

The flagship strategy of Agent Council. In a debate, all agents respond
to the task, then see each other's responses and argue/refine across
multiple rounds. A moderator synthesizes the final answer.

Flow:
    1. **Round 1** — Each agent responds to the task independently
    2. **Round 2..N** — Each agent sees ALL previous responses and
       can agree, disagree, refine, or change their position
    3. **Moderation** — The moderator sees the entire debate and
       produces a unified final answer

This strategy produces the highest quality answers because it:
    - Forces models to consider perspectives they might have missed
    - Catches errors through cross-examination
    - Builds consensus on well-reasoned points
    - Identifies genuine disagreements that need highlighting

Configuration:
    Set ``debate_rounds`` in the council preset to control how many
    rounds of debate occur. More rounds = better quality but slower.
    Recommended: 2 rounds for quick tasks, 3 for important decisions.
"""

from __future__ import annotations

from typing import AsyncGenerator

from council.agent import Agent
from council.lm_studio import LMStudioClient
from council.models import CouncilEvent, EventType
from council.strategies.base import BaseStrategy


class DebateStrategy(BaseStrategy):
    """
    Multi-round debate strategy.

    Agents take turns responding, with each subsequent round having
    access to all previous responses. The debate continues for the
    configured number of rounds before the moderator synthesizes.

    Example debate flow (2 rounds, 3 agents):
        Round 1: Analyst → Creative → Devil's Advocate (independent)
        Round 2: Analyst → Creative → Devil's Advocate (seeing Round 1)
        Final:   Moderator synthesizes all 6 responses
    """

    async def execute(
        self, task: str, **kwargs
    ) -> AsyncGenerator[CouncilEvent, None]:
        """
        Execute a multi-round debate.

        Args:
            task: The user's question or task.
            **kwargs:
                debate_rounds (int): Number of debate rounds. Default: 2.

        Yields:
            CouncilEvent objects for real-time streaming.
        """
        debate_rounds = kwargs.get("debate_rounds", 2)

        # Stores all messages across all rounds for context building
        # Each entry: {"role": agent_role, "content": response_text, "round": round_num}
        all_messages: list[dict[str, str]] = []

        # ---- Run debate rounds ----
        for round_num in range(1, debate_rounds + 1):
            # Signal round start
            yield CouncilEvent(
                type=EventType.ROUND_START,
                round=round_num,
                content=f"Round {round_num} of {debate_rounds}",
                metadata={"total_rounds": debate_rounds},
            )

            # Each agent takes their turn in this round
            for agent in self.agents:
                # Build messages with appropriate context
                # Round 1: just the task
                # Round 2+: task + all previous messages
                history = all_messages if round_num > 1 else None
                messages = agent.build_messages(
                    task=task,
                    history=history,
                    round_num=round_num,
                )

                # Stream the agent's response
                full_response = ""
                async for event in self._stream_agent_response(
                    agent, messages, round_num
                ):
                    if event.type == EventType.AGENT_DONE:
                        full_response = event.content
                    yield event

                # Record this message for future rounds
                all_messages.append({
                    "role": agent.role,
                    "content": full_response,
                    "round": round_num,
                })

            # Signal round complete
            yield CouncilEvent(
                type=EventType.ROUND_DONE,
                round=round_num,
                content=f"Round {round_num} complete",
            )

        # ---- Moderator synthesis ----
        yield CouncilEvent(
            type=EventType.MODERATOR_START,
            agent="Moderator",
            content="Synthesizing debate...",
        )

        # Build moderator messages with full debate context
        moderator_messages = self.moderator.build_moderator_messages(
            task=task,
            all_messages=all_messages,
            strategy="debate",
        )

        # Stream moderator response
        full_moderator_response = ""
        async for event in self._stream_agent_response(
            self.moderator, moderator_messages, round_num=0
        ):
            # Remap agent events to moderator events
            if event.type == EventType.AGENT_CHUNK:
                event.type = EventType.MODERATOR_CHUNK
                event.agent = "Moderator"
                full_moderator_response += event.content
            elif event.type == EventType.AGENT_DONE:
                event.type = EventType.MODERATOR_DONE
                event.agent = "Moderator"
                full_moderator_response = event.content
            elif event.type == EventType.AGENT_START:
                continue  # Already sent MODERATOR_START
            yield event

        # Signal council session complete
        yield CouncilEvent(
            type=EventType.COUNCIL_DONE,
            content="Council session complete",
            metadata={
                "total_rounds": debate_rounds,
                "total_agents": len(self.agents),
                "total_messages": len(all_messages),
            },
        )
