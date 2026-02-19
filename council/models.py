"""
Data Models & Schemas
=====================

Pydantic models that define the data structures used throughout Agent Council.
These models ensure type safety, validation, and provide clear documentation
of the data flowing through the system.

Key Models:
    - ``ModelInfo``: Represents an LLM model available in LM Studio
    - ``AgentConfig``: Configuration for a single agent (model + role + persona)
    - ``CouncilPreset``: A pre-configured council setup (agents + strategy)
    - ``AgentMessage``: A single message from an agent during a session
    - ``CouncilResult``: The complete result of a council session
    - ``CouncilEvent``: A real-time streaming event sent via WebSocket
"""

from __future__ import annotations

import enum
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


# =============================================================================
# Enums
# =============================================================================


class EventType(str, enum.Enum):
    """
    Types of real-time events sent to the frontend via WebSocket.

    These events allow the UI to show the debate unfolding in real-time,
    including when agents start/finish speaking, round boundaries, and
    the moderator's final synthesis.
    """

    # Round lifecycle
    ROUND_START = "round_start"          # A new debate round is beginning
    ROUND_DONE = "round_done"            # A debate round has completed

    # Agent lifecycle (per-agent within a round)
    AGENT_START = "agent_start"          # An agent is about to respond
    AGENT_CHUNK = "agent_chunk"          # A streaming text chunk from an agent
    AGENT_DONE = "agent_done"            # An agent has finished responding

    # Moderator lifecycle
    MODERATOR_START = "moderator_start"  # The moderator is synthesizing
    MODERATOR_CHUNK = "moderator_chunk"  # A streaming chunk from the moderator
    MODERATOR_DONE = "moderator_done"    # The moderator has finished

    # Session lifecycle
    COUNCIL_DONE = "council_done"        # The entire council session is complete
    ERROR = "error"                      # An error occurred

    # Model management
    MODEL_LOADING = "model_loading"      # A model is being loaded in LM Studio
    MODEL_LOADED = "model_loaded"        # A model has finished loading
    MODEL_UNLOADING = "model_unloading"  # A model is being unloaded
    MODEL_UNLOADED = "model_unloaded"    # A model has been unloaded

    # Status/info
    STATUS = "status"                    # General status update message


class StrategyType(str, enum.Enum):
    """Available council collaboration strategies."""

    DEBATE = "debate"       # Multi-round debate: agents argue and refine
    PIPELINE = "pipeline"   # Sequential: each agent builds on the previous
    VOTE = "vote"           # Independent responses + consensus


# =============================================================================
# Model Configuration
# =============================================================================


class ModelInfo(BaseModel):
    """
    Represents an LLM model available in LM Studio.

    Attributes:
        name: Human-readable display name (e.g., "Phi-4 Mini Reasoning")
        identifier: LM Studio model identifier used in API calls
        strengths: List of tags describing what this model excels at
        context_length: Maximum context window in tokens
        size: Parameter count as a string (e.g., "3.8B", "7B")
    """

    name: str
    identifier: str
    strengths: list[str] = Field(default_factory=list)
    context_length: int = 4096
    size: str = ""


class AgentConfig(BaseModel):
    """
    Configuration for a single agent in a council.

    An agent is a model + role + persona. The persona is a system prompt
    that gives the model a specific personality and instructions for how
    to behave during the council session.

    Attributes:
        model: Key referencing a model in the config's models section
        role: Display name for this agent (e.g., "Analyst", "Devil's Advocate")
        persona: System prompt that defines this agent's behavior
    """

    model: str
    role: str
    persona: str


class ModeratorConfig(BaseModel):
    """
    Configuration for the council moderator.

    The moderator is a special agent that synthesizes the debate/discussion
    into a final unified answer after all rounds are complete.

    Attributes:
        model: Key referencing a model in the config's models section
        persona: System prompt for the moderator's synthesis behavior
    """

    model: str
    persona: str


class CouncilPreset(BaseModel):
    """
    A pre-configured council setup.

    Presets define which agents participate, what strategy to use,
    and how the council should operate. Users can select a preset
    from the UI or create custom configurations.

    Attributes:
        name: Display name (e.g., "General Council")
        description: What this council is best suited for
        strategy: The collaboration strategy to use
        debate_rounds: Number of debate rounds (only for debate strategy)
        agents: List of agent configurations
        moderator: Configuration for the moderator agent
    """

    name: str
    description: str = ""
    strategy: StrategyType = StrategyType.DEBATE
    debate_rounds: int = 2
    agents: list[AgentConfig] = Field(default_factory=list)
    moderator: Optional[ModeratorConfig] = None


# =============================================================================
# Runtime Messages & Results
# =============================================================================


class AgentMessage(BaseModel):
    """
    A single message produced by an agent during a council session.

    Captures who said what, in which round, enabling the full debate
    history to be tracked and displayed.

    Attributes:
        agent_role: The role name of the agent (e.g., "Analyst")
        agent_model: The model key used by this agent
        round: Which round this message was produced in (1-indexed)
        content: The full text content of the agent's response
        timestamp: When this message was produced
    """

    agent_role: str
    agent_model: str
    round: int = 1
    content: str = ""
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class CouncilResult(BaseModel):
    """
    The complete result of a council session.

    Contains the full debate history (all agent messages across all rounds)
    plus the moderator's final synthesized answer.

    Attributes:
        task: The original task/question submitted to the council
        council_name: Which council preset was used
        strategy: Which strategy was used
        messages: All agent messages in chronological order
        moderator_response: The moderator's final synthesis
        total_rounds: How many rounds the debate went through
        timestamp: When the session started
    """

    task: str
    council_name: str
    strategy: StrategyType
    messages: list[AgentMessage] = Field(default_factory=list)
    moderator_response: str = ""
    total_rounds: int = 0
    timestamp: datetime = Field(default_factory=datetime.utcnow)


# =============================================================================
# WebSocket Events
# =============================================================================


class CouncilEvent(BaseModel):
    """
    A real-time event sent to the frontend via WebSocket.

    Events are emitted as the council session progresses, allowing
    the UI to display the debate unfolding in real-time with streaming.

    Attributes:
        type: The event type (see EventType enum)
        agent: Which agent this event relates to (if applicable)
        round: Which round this event belongs to (if applicable)
        content: Text content (for chunk events, this is a token/piece)
        timestamp: When this event was emitted
        metadata: Optional extra data (e.g., model name, error details)
    """

    type: EventType
    agent: str = ""
    round: int = 0
    content: str = ""
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    metadata: dict[str, Any] = Field(default_factory=dict)

    def to_dict(self) -> dict:
        """Convert to a JSON-serializable dictionary for WebSocket transmission."""
        return {
            "type": self.type.value,
            "agent": self.agent,
            "round": self.round,
            "content": self.content,
            "timestamp": self.timestamp.isoformat(),
            "metadata": self.metadata,
        }
