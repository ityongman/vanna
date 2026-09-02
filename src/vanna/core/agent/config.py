"""
Agent configuration.

This module contains configuration models that control agent behavior.
"""

from typing import Dict, Optional

from pydantic import BaseModel, Field

from .autolink_config import AutoLinkConfig


class DatabaseConfig(BaseModel):
    """Target database configuration for text-to-SQL.

    The URL scheme determines which SqlRunner implementation is created
    (e.g. "sqlite:///Chinook.sqlite" -> SqliteRunner).
    """

    url: str = Field(description="Database URL, e.g. sqlite:///Chinook.sqlite")


class BusinessConfig(BaseModel):
    """Configuration for a single business's storage.

    Bundles a relational database (for querying business data) with a
    schema vector store namespace (for table/column embeddings). Each
    business gets its own database connection and schema index.
    """

    id: str = Field(description="Business identifier, e.g. 'business_a'")
    database_url: str = Field(
        description="Business relational database URL, e.g. mysql://user:pwd@host/db"
    )
    database_name: str = Field(
        default="",
        description=(
            "Schema vector store namespace. Defaults to id when empty. "
            "Used by DDL import and AutoLink schema retrieval."
        ),
    )

    def effective_database_name(self) -> str:
        """Return the schema namespace (falls back to id)."""
        return self.database_name or self.id


class AuditConfig(BaseModel):
    """Configuration for audit logging."""

    enabled: bool = Field(default=True, description="Enable audit logging")
    log_tool_invocations: bool = Field(
        default=True, description="Log tool invocations with parameters"
    )
    log_tool_results: bool = Field(
        default=True, description="Log tool execution results"
    )
    log_ai_responses: bool = Field(
        default=True, description="Log AI-generated responses"
    )
    include_full_ai_responses: bool = Field(
        default=False,
        description="Include full AI response text in logs (privacy concern)",
    )
    sanitize_tool_parameters: bool = Field(
        default=True, description="Sanitize sensitive parameters (passwords, tokens)"
    )


class AgentConfig(BaseModel):
    """Configuration for agent behavior."""

    max_tool_iterations: int = Field(default=10, gt=0)
    stream_responses: bool = Field(default=True)
    auto_save_conversations: bool = Field(default=True)
    include_thinking_indicators: bool = Field(default=True)
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    max_tokens: Optional[int] = Field(default=None, gt=0)
    audit_config: AuditConfig = Field(default_factory=AuditConfig)
    autolink_config: AutoLinkConfig = Field(
        default_factory=AutoLinkConfig,
        description="AutoLink schema linking configuration (disabled by default)",
    )
    database: Optional[DatabaseConfig] = Field(
        default=None,
        description="Target database; when set, a SqlRunner is derived from the "
        "URL scheme and run_sql/visualize_data tools are auto-registered",
    )
    businesses: Dict[str, BusinessConfig] = Field(
        default_factory=dict,
        description=(
            "Multi-business configurations keyed by business_id. "
            "When set, requests with a matching business_id metadata "
            "will route to the corresponding database and schema namespace."
        ),
    )
    auto_register_tools: bool = Field(
        default=True,
        description="Auto-register built-in tools based on injected capabilities "
        "(agent_memory, schema_vector_store, sql_runner)",
    )
