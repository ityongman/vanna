"""
Audit event models.

This module contains data models for audit logging events.
"""

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from .._compat import StrEnum


class AuditEventType(StrEnum):
    """Types of audit events."""

    # Tool execution events
    TOOL_INVOCATION = "tool_invocation"
    TOOL_RESULT = "tool_result"

    # Conversation events
    MESSAGE_RECEIVED = "message_received"
    AI_RESPONSE_GENERATED = "ai_response_generated"
    CONVERSATION_CREATED = "conversation_created"

    # Security events
    AUTHENTICATION_ATTEMPT = "authentication_attempt"


class AuditEvent(BaseModel):
    """Base audit event with common fields."""

    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    event_type: AuditEventType
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    # User context
    user_id: str
    username: Optional[str] = None
    user_email: Optional[str] = None

    # Request context
    conversation_id: str
    request_id: str
    remote_addr: Optional[str] = None

    # Event-specific data
    details: Dict[str, Any] = Field(default_factory=dict)

    # Privacy/redaction markers
    contains_pii: bool = False
    redacted_fields: List[str] = Field(default_factory=list)


class ToolInvocationEvent(AuditEvent):
    """Audit event for actual tool executions."""

    event_type: AuditEventType = AuditEventType.TOOL_INVOCATION
    tool_call_id: str
    tool_name: str

    # Parameters with sanitization support
    parameters: Dict[str, Any] = Field(default_factory=dict)
    parameters_sanitized: bool = False


class ToolResultEvent(AuditEvent):
    """Audit event for tool execution results."""

    event_type: AuditEventType = AuditEventType.TOOL_RESULT
    tool_call_id: str
    tool_name: str
    success: bool
    error: Optional[str] = None
    execution_time_ms: float = 0.0

    # Result metadata (without full content for size)
    result_size_bytes: Optional[int] = None
    ui_component_type: Optional[str] = None


class AiResponseEvent(AuditEvent):
    """Audit event for AI-generated responses."""

    event_type: AuditEventType = AuditEventType.AI_RESPONSE_GENERATED

    # Response metadata
    response_length_chars: int
    response_length_tokens: Optional[int] = None

    # Full text (optional, configurable)
    response_text: Optional[str] = None
    response_hash: str  # SHA256 for integrity verification

    # Model info
    model_name: Optional[str] = None
    temperature: Optional[float] = None

    # Tool calls in response
    tool_calls_count: int = 0
    tool_names: List[str] = Field(default_factory=list)
