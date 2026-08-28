"""
Agent implementations.

This package contains agent implementations and utilities.
"""

from typing import Optional

from vanna.core import Agent, AgentConfig, ToolRegistry
from vanna.core.llm.base import LlmService
from vanna.core.user import User
from vanna.core.user.request_context import RequestContext
from vanna.core.user.resolver import UserResolver
from vanna.capabilities.agent_memory import AgentMemory
from vanna.capabilities.schema_vector_store import SchemaVectorStore
from vanna.integrations.local.agent_memory.in_memory import DemoAgentMemory


def _default_agent_memory() -> AgentMemory:
    """Create the default agent memory.

    Prefers the FAISS-backed implementation (persisted to ./faiss_index)
    when faiss-cpu is installed; falls back to the zero-dependency
    in-memory demo implementation otherwise.
    """
    try:
        from vanna.integrations.vector.faiss import FAISSAgentMemory

        memory: AgentMemory = FAISSAgentMemory()
        print("[agents] Using FAISS agent memory (persisted to ./faiss_index)")
        return memory
    except Exception:
        print("[agents] faiss unavailable; using in-memory demo agent memory")
        return DemoAgentMemory()


class _DefaultUserResolver(UserResolver):
    """Default user resolver that returns a hardcoded anonymous user.

    Used when no authentication is needed (demo/development mode).
    """

    async def resolve_user(self, request_context: RequestContext) -> User:
        return User(
            id="default_user",
            username="anonymous",
            email="anonymous@example.com",
            permissions=[],
        )


def create_basic_agent(
    llm_service: LlmService,
    config: Optional[AgentConfig] = None,
    tool_registry: Optional[ToolRegistry] = None,
    user_resolver: Optional[UserResolver] = None,
    agent_memory: Optional[AgentMemory] = None,
    schema_vector_store: Optional[SchemaVectorStore] = None,
) -> Agent:
    """Create a basic agent with sensible defaults for development.

    Args:
        llm_service: LLM service implementation to use
        config: Optional agent configuration (defaults to streaming + thinking indicators)
        tool_registry: Optional tool registry (defaults to empty registry)
        user_resolver: Optional user resolver (defaults to anonymous user)
        agent_memory: Optional agent memory (defaults to FAISS-backed when
            faiss-cpu is installed, otherwise the in-memory demo implementation)
        schema_vector_store: Optional schema vector store for AutoLink schema
            linking (e.g. FAISSSchemaVectorStore). Combined with
            ``config.autolink_config.enabled=True`` it activates the AutoLink
            retrieval and enhancement pipeline.

    Returns:
        Configured Agent instance
    """
    if config is None:
        config = AgentConfig(
            stream_responses=True,
            include_thinking_indicators=True,
        )

    if tool_registry is None:
        tool_registry = ToolRegistry()

    if user_resolver is None:
        user_resolver = _DefaultUserResolver()

    if agent_memory is None:
        agent_memory = _default_agent_memory()

    return Agent(
        llm_service=llm_service,
        tool_registry=tool_registry,
        user_resolver=user_resolver,
        agent_memory=agent_memory,
        config=config,
        schema_vector_store=schema_vector_store,
    )


__all__: list[str] = ["create_basic_agent"]
