"""
Agent
=====

An Agent wraps a model with a specific role and persona (system prompt).
During a council session, each agent responds to the task from its unique
perspective, shaped by its persona.

For example, an "Analyst" agent might have a persona like:
    "You are a sharp analytical thinker. Break down problems logically..."

While a "Devil's Advocate" agent might have:
    "You are a critical skeptic. Question assumptions, point out flaws..."

The same underlying model can play different roles with different personas.

Usage:
    >>> agent = Agent(
    ...     role="Analyst",
    ...     model_key="phi4-mini",
    ...     model_identifier="phi-4-mini-reasoning",
    ...     persona="You are a sharp analytical thinker..."
    ... )
    >>> messages = agent.build_messages("What database should I use?", history=[])
"""

from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


class Agent:
    """
    Represents a single agent in a council.

    An agent is the combination of:
        - A **model** (the LLM running in LM Studio)
        - A **role** (display name like "Analyst" or "Reviewer")
        - A **persona** (system prompt that shapes the model's behavior)

    The agent doesn't directly call the LLM — instead it builds the
    message payload that gets sent to the LM Studio client by the engine.

    Attributes:
        role: Display name for this agent (e.g., "Analyst")
        model_key: Config key referencing the model (e.g., "phi4-mini")
        model_identifier: LM Studio model ID (e.g., "phi-4-mini-reasoning")
        persona: System prompt defining this agent's personality/behavior
    """

    def __init__(
        self,
        role: str,
        model_key: str,
        model_identifier: str,
        persona: str,
    ):
        """
        Initialize an Agent.

        Args:
            role: Display name for the agent role
            model_key: Key referencing the model in config.yaml
            model_identifier: The actual model ID used in LM Studio API calls
            persona: System prompt that defines how this agent behaves
        """
        self.role = role
        self.model_key = model_key
        self.model_identifier = model_identifier
        self.persona = persona

    def build_messages(
        self,
        task: str,
        history: list[dict[str, str]] | None = None,
        round_num: int = 1,
        strategy_context: str = "",
        max_history_tokens: int = 2000,
    ) -> list[dict[str, str]]:
        """
        Build the chat messages payload for this agent's turn.

        Constructs the system prompt + conversation history + current task
        into the format expected by the OpenAI chat API.

        For the first round, the agent just sees the task.
        For subsequent rounds (in debate mode), the agent also sees
        what other agents said in previous rounds.

        History is automatically truncated to stay within context limits.
        Each agent's previous response is capped so the total prompt
        doesn't overflow the model's context window.

        Args:
            task: The user's original task/question.
            history: Previous messages from other agents (for debate context).
                     Each dict has "role" (agent role name) and "content" keys.
            round_num: Current round number (1-indexed).
            strategy_context: Additional context from the strategy
                              (e.g., "You are reviewing the following code...").
            max_history_tokens: Approximate max characters (÷4 for tokens) to
                                include from history. Defaults to 2000 chars
                                per agent response (~500 tokens each).

        Returns:
            List of message dicts in OpenAI chat format:
            [{"role": "system", "content": "..."}, {"role": "user", "content": "..."}]
        """
        messages = []

        # System prompt: persona + council context
        system_content = self.persona

        if round_num > 1:
            system_content += (
                f"\n\nThis is round {round_num} of a multi-round discussion. "
                f"You have seen other agents' responses from previous rounds. "
                f"Consider their points carefully. You may agree, disagree, "
                f"or refine your position. Be specific about what you agree or "
                f"disagree with and why."
            )

        messages.append({"role": "system", "content": system_content})

        # For round 1: just the task
        if round_num == 1:
            user_content = f"Task: {task}"
            if strategy_context:
                user_content = f"{strategy_context}\n\n{user_content}"
            messages.append({"role": "user", "content": user_content})
        else:
            # For subsequent rounds: task + TRUNCATED history from previous rounds
            user_content = f"Original Task: {task}\n\n"
            user_content += "=== Previous Discussion (summarized if long) ===\n\n"

            if history:
                # Calculate per-agent character budget to avoid context overflow
                # Reserve ~500 chars for task + instructions, rest split among agents
                per_agent_budget = max(400, max_history_tokens // max(len(history), 1))

                for msg in history:
                    content = msg['content']
                    # Truncate long responses to keep context manageable
                    if len(content) > per_agent_budget:
                        content = content[:per_agent_budget] + "\n[...response truncated for context limit...]"

                    user_content += f"**{msg['role']}** (Round {msg.get('round', '?')}) said:\n{content}\n\n"

            user_content += (
                "=== Your Turn ===\n"
                "Based on the discussion above, provide your response. "
                "Address specific points made by other agents. "
                "You can agree, disagree, add nuance, or change your position."
            )

            if strategy_context:
                user_content = f"{strategy_context}\n\n{user_content}"

            messages.append({"role": "user", "content": user_content})

        return messages

    def build_moderator_messages(
        self,
        task: str,
        all_messages: list[dict[str, str]],
        strategy: str = "debate",
        max_history_tokens: int = 3000,
    ) -> list[dict[str, str]]:
        """
        Build the messages for the moderator's final synthesis.

        The moderator sees the entire debate/discussion and produces
        a unified final answer.

        History is automatically truncated to stay within context limits.
        Each agent's response is capped so the total prompt fits within
        the moderator model's context window.

        Args:
            task: The original task/question.
            all_messages: All agent messages from all rounds.
                          Each dict has "role", "content", and "round" keys.
            strategy: The strategy used (affects moderator instructions).
            max_history_tokens: Approximate max characters to include from
                                all discussion history. Defaults to 3000 chars.

        Returns:
            List of message dicts in OpenAI chat format.
        """
        messages = []

        # Moderator system prompt
        messages.append({"role": "system", "content": self.persona})

        # Build the discussion context with truncation
        user_content = f"Original Task: {task}\n\n"
        user_content += "=== Council Discussion (summarized if long) ===\n\n"

        # Calculate per-agent character budget
        per_agent_budget = max(400, max_history_tokens // max(len(all_messages), 1))

        current_round = 0
        for msg in all_messages:
            msg_round = msg.get("round", 1)
            if msg_round != current_round:
                current_round = msg_round
                user_content += f"--- Round {current_round} ---\n\n"

            content = msg['content']
            # Truncate long responses to keep context manageable
            if len(content) > per_agent_budget:
                content = content[:per_agent_budget] + "\n[...response truncated for context limit...]"

            user_content += f"**{msg['role']}** said:\n{content}\n\n"

        user_content += (
            "=== Your Task as Moderator ===\n"
            "Synthesize the above discussion into a clear, comprehensive final answer. "
            "Highlight key areas of agreement and disagreement. "
            "Provide a definitive recommendation or conclusion. "
            "Make your response well-structured and actionable."
        )

        messages.append({"role": "user", "content": user_content})

        return messages

    def __repr__(self) -> str:
        return f"Agent(role='{self.role}', model='{self.model_key}')"
