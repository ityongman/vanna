"""
Agent implementations.

This package contains agent implementations and utilities.
"""

import logging
from dataclasses import dataclass
from typing import List, Optional

from vanna.core import Agent, AgentConfig, Tool, ToolRegistry
from vanna.core.llm.base import LlmService
from vanna.core.storage import ConversationStore
from vanna.core.user import User
from vanna.core.user.request_context import RequestContext
from vanna.core.user.resolver import UserResolver
from vanna.capabilities.agent_memory import AgentMemory
from vanna.capabilities.schema_vector_store import SchemaVectorStore
from vanna.capabilities.sql_runner import SqlRunner
from vanna.integrations.local.agent_memory.in_memory import DemoAgentMemory

logger = logging.getLogger(__name__)


def _default_agent_memory() -> AgentMemory:
    """Create the default agent memory.

    Prefers the FAISS-backed implementation (persisted to
    ./data/vector_db/memory) when faiss-cpu is installed; falls back to
    the zero-dependency in-memory demo implementation otherwise.
    """
    try:
        from vanna.integrations.vector.faiss import FAISSAgentMemory

        memory: AgentMemory = FAISSAgentMemory()
        print(
            "[agents] Using FAISS agent memory "
            "(persisted to ./data/vector_db/memory)"
        )
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
        )


@dataclass
class VectorStoreSettings:
    """Resolved vector-store settings (from ``storage.project.vector_db``).

    One declaration derives both stores: FAISSAgentMemory (agent memory)
    and FAISSSchemaVectorStore (schema indices).
    """

    backend: Optional[str] = None
    memory_index_path: Optional[str] = None
    schema_persist_dir: Optional[str] = None


def create_basic_agent(
    llm_service: LlmService,
    config: Optional[AgentConfig] = None,
    tool_registry: Optional[ToolRegistry] = None,
    user_resolver: Optional[UserResolver] = None,
    agent_memory: Optional[AgentMemory] = None,
    schema_vector_store: Optional[SchemaVectorStore] = None,
    sql_runner: Optional[SqlRunner] = None,
    extra_tools: Optional[List[Tool]] = None,
    vector_store: Optional[VectorStoreSettings] = None,
    embedding_model_path: Optional[str] = None,
    conversation_store: Optional[ConversationStore] = None,
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
        sql_runner: Optional SqlRunner for text-to-SQL; when omitted it is
            derived from ``config.database`` (URL-scheme factory)
        extra_tools: Optional additional tools to register on the agent
        vector_store: Optional resolved vector-store settings; only
            backend="faiss" is wired here, any other value logs a warning
            and falls back to the defaults
        embedding_model_path: Optional local path to a downloaded
            SentenceTransformer model directory; forwarded to the derived
            FAISSSchemaVectorStore (only applied when currently used)
        conversation_store: Optional conversation store; when omitted the
            Agent falls back to SQLiteConversationStore at
            ./data/db/conversations.db

    Returns:
        Configured Agent instance
    """
    backend = vector_store.backend if vector_store else None
    if backend and backend != "faiss":
        logger.warning(
            "VECTOR_BACKEND %r is not supported (only 'faiss' is wired in "
            "create_basic_agent); falling back to default stores",
            backend,
        )
    if config is None:
        config = AgentConfig(
            stream_responses=True,
            include_thinking_indicators=True,
        )

    if tool_registry is None:
        tool_registry = ToolRegistry()

    if user_resolver is None:
        user_resolver = _DefaultUserResolver()

    # vector_store: one declaration derives both stores ("faiss").
    if agent_memory is None:
        if backend == "faiss":
            try:
                from vanna.integrations.vector.faiss import FAISSAgentMemory

                agent_memory = FAISSAgentMemory(
                    index_path=vector_store.memory_index_path
                )
            except ImportError:
                agent_memory = _default_agent_memory()
        else:
            agent_memory = _default_agent_memory()

    if schema_vector_store is None and backend == "faiss":
        try:
            from vanna.integrations.vector.faiss import FAISSSchemaVectorStore

            kwargs: dict = {"embedding_model_path": embedding_model_path}
            if vector_store.schema_persist_dir:
                kwargs["persist_dir"] = vector_store.schema_persist_dir
            schema_vector_store = FAISSSchemaVectorStore(**kwargs)
        except ImportError:
            logger.info("faiss extras unavailable; schema_vector_store not derived")

    return Agent(
        llm_service=llm_service,
        tool_registry=tool_registry,
        user_resolver=user_resolver,
        agent_memory=agent_memory,
        config=config,
        schema_vector_store=schema_vector_store,
        sql_runner=sql_runner,
        extra_tools=extra_tools or [],
        conversation_store=conversation_store,
    )


__all__: list[str] = ["create_basic_agent"]
