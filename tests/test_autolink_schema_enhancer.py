"""
Unit tests for AutoLinkSchemaEnhancer and the enhancer chain wiring.
"""

import logging

import pytest

from vanna.capabilities.schema_vector_store import (
    SchemaColumn,
    SchemaRelation,
    SchemaSearchResult,
    SchemaTable,
    SchemaVectorStore,
)
from vanna.core.agent.autolink_config import AutoLinkConfig
from vanna.core.enhancer import (
    AutoLinkSchemaEnhancer,
    LlmContextEnhancerChain,
)
from vanna.core.user import User

SYSTEM_PROMPT = "You are a data analyst assistant."
QUESTION = "show me customer emails"


def make_user() -> User:
    return User(id="u1", email="u1@example.com", group_memberships=[])


def column(table, name, data_type="INTEGER", description=None):
    return SchemaColumn(
        column_name=name,
        table_name=table,
        data_type=data_type,
        description=description,
    )


def result(col, rank=1, similarity=0.9):
    return SchemaSearchResult(column=col, similarity_score=similarity, rank=rank)


class FakeSchemaVectorStore(SchemaVectorStore):
    """In-memory SchemaVectorStore double with canned data."""

    def __init__(self, search_results=(), relations=(), fail_search=False):
        self.search_results = list(search_results)
        self.relations = list(relations)
        self.fail_search = fail_search
        self.search_calls = []

    async def ingest_schema(self, tables, relations, database_name):
        raise NotImplementedError("not used in tests")

    async def search(self, query, database_name, top_k=20):
        self.search_calls.append((query, database_name, top_k))
        if self.fail_search:
            raise RuntimeError("vector backend down")
        return self.search_results[:top_k]

    async def get_column_by_name(self, column_name, table_name, database_name):
        for col in self._all_columns():
            if col.table_name == table_name and col.column_name == column_name:
                return col
        for col in self._all_columns():
            if (
                col.table_name.lower() == table_name.lower()
                and col.column_name.lower() == column_name.lower()
            ):
                return col
        return None

    async def get_relations(self, table_names, database_name):
        lowered = {t.lower() for t in table_names}
        return [
            r
            for r in self.relations
            if r.from_table.lower() in lowered or r.to_table.lower() in lowered
        ]

    def _all_columns(self):
        columns = [r.column for r in self.search_results]
        for rel in self.relations:
            columns.append(column(rel.from_table, rel.from_column))
            columns.append(column(rel.to_table, rel.to_column))
        return columns


# ---------------------------------------------------------------------------
# Config defaults
# ---------------------------------------------------------------------------


class TestAutoLinkConfig:
    def test_disabled_by_default(self):
        config = AutoLinkConfig()
        assert config.enabled is False
        assert config.database_name == "default"
        assert config.top_k == 20
        assert config.vector_store_backend == "faiss"
        assert config.include_relations is True
        assert config.heuristic_id_completion is True


# ---------------------------------------------------------------------------
# AutoLinkSchemaEnhancer
# ---------------------------------------------------------------------------


class TestAutoLinkSchemaEnhancer:
    @pytest.mark.asyncio
    async def test_no_store_is_noop(self):
        enhancer = AutoLinkSchemaEnhancer()
        enhanced = await enhancer.enhance_system_prompt(
            SYSTEM_PROMPT, QUESTION, make_user()
        )
        assert enhanced == SYSTEM_PROMPT

    @pytest.mark.asyncio
    async def test_empty_message_is_noop(self):
        store = FakeSchemaVectorStore(search_results=[result(column("customers", "email"))])
        enhancer = AutoLinkSchemaEnhancer(schema_vector_store=store)
        enhanced = await enhancer.enhance_system_prompt(SYSTEM_PROMPT, "  ", make_user())
        assert enhanced == SYSTEM_PROMPT
        assert store.search_calls == []

    @pytest.mark.asyncio
    async def test_injects_retrieved_columns(self):
        email = column("customers", "email", "VARCHAR", "Customer email address")
        store = FakeSchemaVectorStore(search_results=[result(email, rank=1)])
        enhancer = AutoLinkSchemaEnhancer(schema_vector_store=store)

        enhanced = await enhancer.enhance_system_prompt(
            SYSTEM_PROMPT, QUESTION, make_user()
        )

        assert enhanced.startswith(SYSTEM_PROMPT)
        assert "## Relevant Schema Context (AutoLink)" in enhanced
        assert "Table: customers" in enhanced
        assert "- email (VARCHAR): Customer email address" in enhanced
        # search used the config defaults
        assert store.search_calls == [(QUESTION, "default", 20)]

    @pytest.mark.asyncio
    async def test_empty_search_results_is_noop(self):
        store = FakeSchemaVectorStore(search_results=[])
        enhancer = AutoLinkSchemaEnhancer(schema_vector_store=store)

        enhanced = await enhancer.enhance_system_prompt(
            SYSTEM_PROMPT, QUESTION, make_user()
        )
        assert enhanced == SYSTEM_PROMPT

    @pytest.mark.asyncio
    async def test_search_failure_degrades_to_original(self, caplog):
        store = FakeSchemaVectorStore(fail_search=True)
        enhancer = AutoLinkSchemaEnhancer(schema_vector_store=store)

        with caplog.at_level(logging.WARNING):
            enhanced = await enhancer.enhance_system_prompt(
                SYSTEM_PROMPT, QUESTION, make_user()
            )

        assert enhanced == SYSTEM_PROMPT
        assert any("AutoLink schema enhancement failed" in m for m in caplog.messages)

    @pytest.mark.asyncio
    async def test_pk_fk_completion_and_join_conditions(self):
        # Retrieved: orders.customer_id. Relation completes customers.id.
        customer_id = column("orders", "customer_id")
        relation = SchemaRelation(
            from_table="orders",
            from_column="customer_id",
            to_table="customers",
            to_column="id",
        )
        store = FakeSchemaVectorStore(
            search_results=[result(customer_id, rank=1)],
            relations=[relation],
        )
        enhancer = AutoLinkSchemaEnhancer(schema_vector_store=store)

        enhanced = await enhancer.enhance_system_prompt(
            SYSTEM_PROMPT, QUESTION, make_user()
        )

        # Join conditions from DDL-parsed relations.
        assert "Join conditions (from foreign keys):" in enhanced
        assert "- orders.customer_id = customers.id" in enhanced
        # The completed side is present in the column list.
        assert "Table: customers" in enhanced
        assert "- id" in enhanced

    @pytest.mark.asyncio
    async def test_heuristic_fallback_infers_id_relation(self):
        # No relations: customer_id triggers the add_id heuristic, which
        # resolves customers.id via get_column_by_name.
        class HeuristicStore(FakeSchemaVectorStore):
            def _all_columns(self):
                return [
                    column("orders", "customer_id"),
                    column("customers", "id"),
                ]

        store = HeuristicStore(
            search_results=[result(column("orders", "customer_id"), rank=1)]
        )
        enhancer = AutoLinkSchemaEnhancer(schema_vector_store=store)

        enhanced = await enhancer.enhance_system_prompt(
            SYSTEM_PROMPT, QUESTION, make_user()
        )

        assert "Table: customers" in enhanced
        assert "- id" in enhanced
        assert "Possible join conditions (inferred, verify before use):" in enhanced
        assert "- orders.customer_id = customers.id" in enhanced

    @pytest.mark.asyncio
    async def test_heuristic_disabled_no_completion(self):
        class HeuristicStore(FakeSchemaVectorStore):
            def _all_columns(self):
                return [
                    column("orders", "customer_id"),
                    column("customers", "id"),
                ]

        store = HeuristicStore(search_results=[result(column("orders", "customer_id"))])
        config = AutoLinkConfig(heuristic_id_completion=False)
        enhancer = AutoLinkSchemaEnhancer(schema_vector_store=store, config=config)

        enhanced = await enhancer.enhance_system_prompt(
            SYSTEM_PROMPT, QUESTION, make_user()
        )

        assert "Table: customers" not in enhanced
        assert "inferred" not in enhanced

    @pytest.mark.asyncio
    async def test_include_relations_false_skips_join_section(self):
        customer_id = column("orders", "customer_id")
        relation = SchemaRelation(
            from_table="orders",
            from_column="customer_id",
            to_table="customers",
            to_column="id",
        )
        store = FakeSchemaVectorStore(
            search_results=[result(customer_id, rank=1)],
            relations=[relation],
        )
        config = AutoLinkConfig(include_relations=False)
        enhancer = AutoLinkSchemaEnhancer(schema_vector_store=store, config=config)

        enhanced = await enhancer.enhance_system_prompt(
            SYSTEM_PROMPT, QUESTION, make_user()
        )

        assert "Join conditions" not in enhanced
        assert "Table: customers" not in enhanced
        # Retrieved columns are still injected.
        assert "Table: orders" in enhanced

    @pytest.mark.asyncio
    async def test_user_messages_not_modified(self):
        store = FakeSchemaVectorStore(search_results=[result(column("t", "c"))])
        enhancer = AutoLinkSchemaEnhancer(schema_vector_store=store)

        messages = []
        enhanced_messages = await enhancer.enhance_user_messages(messages, make_user())
        assert enhanced_messages == messages


# ---------------------------------------------------------------------------
# Enhancer chain + Agent wiring
# ---------------------------------------------------------------------------


class TestEnhancerChainAndAgentWiring:
    @pytest.mark.asyncio
    async def test_chain_applies_both_enhancers(self):
        class SuffixEnhancer(AutoLinkSchemaEnhancer):
            async def enhance_system_prompt(self, system_prompt, user_message, user):
                return system_prompt + "\n[suffix]"

        store = FakeSchemaVectorStore(search_results=[result(column("t", "c"))])
        chain = LlmContextEnhancerChain(
            [SuffixEnhancer(), AutoLinkSchemaEnhancer(schema_vector_store=store)]
        )

        enhanced = await chain.enhance_system_prompt(
            SYSTEM_PROMPT, QUESTION, make_user()
        )

        assert "[suffix]" in enhanced
        assert "## Relevant Schema Context (AutoLink)" in enhanced

    def test_agent_wires_chain_when_enabled(self):
        from vanna.core import Agent, AgentConfig, ToolRegistry
        from vanna.integrations.local.agent_memory.in_memory import DemoAgentMemory
        from vanna.core.user.resolver import UserResolver
        from vanna.core.user.request_context import RequestContext

        class FakeResolver(UserResolver):
            async def resolve_user(self, request_context):
                return make_user()

        store = FakeSchemaVectorStore()
        config = AgentConfig(autolink_config=AutoLinkConfig(enabled=True))

        agent = Agent(
            llm_service=None,
            tool_registry=ToolRegistry(),
            user_resolver=FakeResolver(),
            agent_memory=DemoAgentMemory(),
            config=config,
            schema_vector_store=store,
        )

        assert agent.schema_vector_store is store
        assert isinstance(agent.llm_context_enhancer, LlmContextEnhancerChain)
        assert len(agent.llm_context_enhancer.enhancers) == 2

    def test_agent_default_not_chained_when_disabled(self):
        from vanna.core import Agent, AgentConfig, ToolRegistry
        from vanna.integrations.local.agent_memory.in_memory import DemoAgentMemory
        from vanna.core.user.resolver import UserResolver
        from vanna.core.user.request_context import RequestContext

        class FakeResolver(UserResolver):
            async def resolve_user(self, request_context):
                return make_user()

        agent = Agent(
            llm_service=None,
            tool_registry=ToolRegistry(),
            user_resolver=FakeResolver(),
            agent_memory=DemoAgentMemory(),
            schema_vector_store=FakeSchemaVectorStore(),
        )

        assert not isinstance(agent.llm_context_enhancer, LlmContextEnhancerChain)

    def test_agent_enabled_without_store_logs_info(self, caplog):
        from vanna.core import Agent, AgentConfig, ToolRegistry
        from vanna.integrations.local.agent_memory.in_memory import DemoAgentMemory
        from vanna.core.user.resolver import UserResolver
        from vanna.core.user.request_context import RequestContext

        class FakeResolver(UserResolver):
            async def resolve_user(self, request_context):
                return make_user()

        config = AgentConfig(autolink_config=AutoLinkConfig(enabled=True))

        with caplog.at_level(logging.INFO):
            agent = Agent(
                llm_service=None,
                tool_registry=ToolRegistry(),
                user_resolver=FakeResolver(),
                agent_memory=DemoAgentMemory(),
                config=config,
            )

        assert agent.schema_vector_store is None
        assert not isinstance(agent.llm_context_enhancer, LlmContextEnhancerChain)
        assert any("schema_vector_store" in m for m in caplog.messages)


# ---------------------------------------------------------------------------
# System prompt AUTO-LINK section (injection point 3)
# ---------------------------------------------------------------------------


class TestSystemPromptAutoLinkSection:
    @pytest.mark.asyncio
    async def test_explore_tool_triggers_autolink_section(self):
        from vanna.core.system_prompt import DefaultSystemPromptBuilder
        from vanna.core.tool import ToolSchema

        builder = DefaultSystemPromptBuilder()
        schemas = [
            ToolSchema(
                name="explore_schema_links",
                description="Explore schema links",
                parameters={},
            )
        ]

        prompt = await builder.build_system_prompt(make_user(), schemas)

        assert "AUTO-LINK SCHEMA EXPLORATION:" in prompt
        assert "explore_schema_links" in prompt

    @pytest.mark.asyncio
    async def test_no_explore_tool_no_autolink_section(self):
        from vanna.core.system_prompt import DefaultSystemPromptBuilder
        from vanna.core.tool import ToolSchema

        builder = DefaultSystemPromptBuilder()
        schemas = [
            ToolSchema(name="run_sql", description="Run SQL", parameters={})
        ]

        prompt = await builder.build_system_prompt(make_user(), schemas)

        assert "AUTO-LINK SCHEMA EXPLORATION:" not in prompt
