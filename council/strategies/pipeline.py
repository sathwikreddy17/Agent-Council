"""
Pipeline Strategy
=================

Sequential processing strategy where each agent builds on the previous
agent's output. This is like an assembly line — each agent has a specific
role in the process.

Flow:
    1. **Agent 1** (e.g., Architect) — Creates the initial solution
    2. **Agent 2** (e.g., Reviewer) — Reviews and critiques Agent 1's work
    3. **Agent 3** (e.g., Optimizer) — Refines based on the review
    4. **Moderator** — Presents the final result with summary

This strategy is best for:
    - Code generation (architect → reviewer → optimizer)
    - Writing tasks (drafter → editor → polisher)
    - Any task with clear sequential steps

Unlike debate, each agent only sees the output of the PREVIOUS agent
(not all agents), making it a focused refinement process.
"""

from __future__ import annotations

from typing import AsyncGenerator

from council.agent import Agent
from council.lm_studio import LMStudioClient
from council.models import CouncilEvent, EventType
from council.strategies.base import BaseStrategy


class PipelineStrategy(BaseStrategy):
    """
    Sequential pipeline strategy.

    Each agent processes in order, receiving the previous agent's output
    as context. The chain builds progressively toward a refined result.
    """

    async def execute(
        self, task: str, **kwargs
    ) -> AsyncGenerator[CouncilEvent, None]:
        """
        Execute a sequential pipeline.

        Args:
            task: The user's question or task.

        Yields:
            CouncilEvent objects for real-time streaming.
        """
        all_messages: list[dict[str, str]] = []
        previous_output = ""

        # Signal single "round" for pipeline
        yield CouncilEvent(
            type=EventType.ROUND_START,
            round=1,
            content="Pipeline processing",
            metadata={"total_agents": len(self.agents)},
        )

        # Process each agent in sequence
        for step_num, agent in enumerate(self.agents, 1):
            # Build context based on position in pipeline
            if step_num == 1:
                # First agent: just the task
                strategy_context = (
                    f"You are step {step_num} of {len(self.agents)} in a pipeline. "
                    f"You are the first to respond. Create the initial solution."
                )
                messages = agent.build_messages(
                    task=task,
                    round_num=1,
                    strategy_context=strategy_context,
                )
            else:
                # Subsequent agents: task + previous agent's output
                strategy_context = (
                    f"You are step {step_num} of {len(self.agents)} in a pipeline. "
                    f"The previous agent ({self.agents[step_num - 2].role}) "
                    f"produced the following output. Build upon, review, or "
                    f"refine their work according to your role.\n\n"
                    f"Previous agent's output:\n{previous_output}"
                )
                messages = agent.build_messages(
                    task=task,
                    round_num=1,
                    strategy_context=strategy_context,
                )

            # Stream the agent's response
            full_response = ""
            async for event in self._stream_agent_response(
                agent, messages, round_num=step_num
            ):
                if event.type == EventType.AGENT_DONE:
                    full_response = event.content
                yield event

            # Store for next agent and moderator
            previous_output = full_response
            all_messages.append({
                "role": agent.role,
                "content": full_response,
                "round": step_num,
            })

        yield CouncilEvent(
            type=EventType.ROUND_DONE,
            round=1,
            content="Pipeline complete",
        )

        # ---- Moderator synthesis ----
        yield CouncilEvent(
            type=EventType.MODERATOR_START,
            agent="Moderator",
            content="Preparing final result...",
        )

        moderator_messages = self.moderator.build_moderator_messages(
            task=task,
            all_messages=all_messages,
            strategy="pipeline",
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
            content="Pipeline session complete",
            metadata={
                "total_steps": len(self.agents),
                "total_messages": len(all_messages),
            },
        )
