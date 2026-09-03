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


class SchemaVectorConfig(BaseModel):
    """Schema vector store configuration for a business.

    ``backend`` selects the vector store instance: ``None`` inherits the
    project-level vector_db (shared store, namespaced indices); a non-null
    value references a dedicated instance declared by the server config.
    """

    namespace: str = Field(
        description=(
            "Vector store namespace for this business; DDL import and "
            "AutoLink schema retrieval both use it"
        ),
    )
    backend: Optional[str] = Field(
        default=None,
        description=(
            "Vector backend instance key; None inherits the project-level "
            "active vector_db instance"
        ),
    )
    embedding_model_path: Optional[str] = Field(
        default=None,
        description=(
            "Local path to a downloaded SentenceTransformer model directory; "
            "only applied by FAISS-backed stores"
        ),
    )


class BusinessConfig(BaseModel):
    """Configuration for a single business's storage.

    Bundles a relational database (for querying business data) with a
    schema vector store namespace (for table/column embeddings). Each
    business gets its own database connection and schema index.

    ``enabled`` defaults to True; disabled entries are validated but not
    loaded (no SqlRunner, hidden from the DDL import page).
    """

    id: str = Field(description="Business identifier, e.g. 'business_a'")
    enabled: bool = Field(
        default=True,
        description="Whether this business is loaded; disabled entries are reserved",
    )
    database: DatabaseConfig = Field(
        description="Business relational database, e.g. mysql://user:pwd@host/db",
    )
    schema_vector: SchemaVectorConfig = Field(
        description="Schema vector store configuration (namespace/backend/embedding)",
    )

    def effective_database_name(self) -> str:
        """Return the schema namespace used for retrieval and DDL import."""
        return self.schema_vector.namespace


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
            "When set, requests must carry a matching business_id in "
            "metadata; unmatched requests are rejected (no fallback routing)."
        ),
    )
    auto_register_tools: bool = Field(
        default=True,
        description="Auto-register built-in tools based on injected capabilities "
        "(agent_memory, schema_vector_store, sql_runner)",
    )
