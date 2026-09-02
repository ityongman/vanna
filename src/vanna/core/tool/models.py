"""
Tool domain models.

This module contains data models for tool execution.
"""

from typing import TYPE_CHECKING, Any, Dict, Optional

from pydantic import BaseModel, Field

# Import at runtime for Pydantic model resolution
from vanna.capabilities.agent_memory import AgentMemory
from vanna.capabilities.schema_vector_store import SchemaVectorStore
from vanna.capabilities.sql_runner import SqlRunner

if TYPE_CHECKING:
    from ..components import UiComponent
    from ..user.models import User
    from ..observability import ObservabilityProvider


class ToolCall(BaseModel):
    """Represents a tool call from the LLM."""

    id: str = Field(description="Unique identifier for this tool call")
    name: str = Field(description="Name of the tool to execute")
    arguments: Dict[str, Any] = Field(description="Raw arguments from LLM")


class ToolContext(BaseModel):
    """Context passed to all tool executions."""

    user: "User"  # Forward reference to avoid circular import
    conversation_id: str
    request_id: str = Field(description="Unique request identifier for tracing")
    agent_memory: AgentMemory = Field(
        description="Agent memory for tool usage learning"
    )
    schema_vector_store: Optional[SchemaVectorStore] = Field(
        default=None,
        description="Optional schema vector store for schema linking (AutoLink)",
    )
    sql_runner: Optional[SqlRunner] = Field(
        default=None,
        description=(
            "Per-request SQL runner override for business routing. "
            "When set, RunSqlTool uses this instead of its bound runner."
        ),
    )
    metadata: Dict[str, Any] = Field(default_factory=dict)
    # Reserved for future use; not yet implemented (预留暂未实现).
    observability_provider: Optional["ObservabilityProvider"] = Field(
        default=None,
        description="Reserved for future use; not yet implemented",
    )

    class Config:
        arbitrary_types_allowed = True


class ToolResult(BaseModel):
    """Result from tool execution.

    Changes:
    - `result_for_llm`: string that will be sent back to the LLM.
    - `ui_component`: optional UI payload for rendering in clients.
    """

    success: bool = Field(description="Whether execution succeeded")
    result_for_llm: str = Field(description="String content to send back to the LLM")
    ui_component: Optional["UiComponent"] = Field(
        default=None, description="Optional UI component for rendering"
    )
    error: Optional[str] = Field(default=None, description="Error message if failed")
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ToolSchema(BaseModel):
    """Schema describing a tool for LLM consumption."""

    name: str = Field(description="Tool name")
    description: str = Field(description="What this tool does")
    parameters: Dict[str, Any] = Field(description="JSON Schema of parameters")


class ToolRejection(BaseModel):
    """Indicates tool execution should be rejected with a message.

    Used by transform_args to reject tool execution when arguments
    cannot be appropriately transformed for the user's context.
    """

    reason: str = Field(
        description="Explanation of why the tool execution was rejected"
    )
