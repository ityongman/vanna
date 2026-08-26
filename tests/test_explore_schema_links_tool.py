"""
Unit tests for ExploreSchemaLinksTool.
"""

import pytest

from vanna.capabilities.schema_vector_store import (
    SchemaColumn,
    SchemaRelation,
    SchemaSearchResult,
    SchemaVectorStore,
)
from vanna.core.tool import ToolContext
from vanna.core.user import User
from vanna.integrations.local.agent_memory.in_memory import DemoAgentMemory
from vanna.tools.explore_schema_links import (
    ExploreSchemaLinksParams,
    ExploreSchemaLinksTool,
)


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

    def __init__(self, search_results=(), relations=(), fail=False):
        self.search_results = list(search_results)
        self.relations = list(relations)
        self.fail = fail
        self.columns = [
            r.column for r in self.search_results
        ] + [
            c
            for rel in self.relations
            for c in (
                column(rel.from_table, rel.from_column),
                column(rel.to_table, rel.to_column),
            )
        ]

    async def ingest_schema(self, tables, relations, database_name):
        raise NotImplementedError("not used in tests")

    async def search(self, query, database_name, top_k=20):
        if self.fail:
            raise RuntimeError("vector backend down")
        return self.search_results[:top_k]

    async def get_column_by_name(self, column_name, table_name, database_name):
        for col in self.columns:
            if col.table_name.lower() == table_name.lower() and col.column_name.lower() == column_name.lower():
                return col
        return None

    async def get_relations(self, table_names, database_name):
        lowered = {t.lower() for t in table_names}
        return [
            r
            for r in self.relations
            if r.from_table.lower() in lowered or r.to_table.lower() in lowered
        ]


def make_context(store, database_name="sales_db"):
    return ToolContext(
        user=User(id="u1", email="u1@example.com", group_memberships=[]),
        conversation_id="c1",
        request_id="r1",
        agent_memory=DemoAgentMemory(),
        schema_vector_store=store,
        metadata={"autolink_database_name": database_name},
    )


@pytest.fixture
def tool():
    return ExploreSchemaLinksTool()


@pytest.fixture
def sales_store():
    """customers.email, orders.customer_id retrieved + orders->customers FK."""
    relation = SchemaRelation(
        from_table="orders",
        from_column="customer_id",
        to_table="customers",
        to_column="id",
    )
    return FakeSchemaVectorStore(
        search_results=[
            result(column("orders", "customer_id"), rank=1),
            result(column("customers", "email", "VARCHAR", "Customer email"), rank=2),
        ],
        relations=[relation],
    )


# ---------------------------------------------------------------------------
# Tool schema / registry
# ---------------------------------------------------------------------------


class TestToolSchema:
    def test_name_and_description(self, tool):
        assert tool.name == "explore_schema_links"
        assert "schema" in tool.description.lower()

    def test_args_schema_shape(self, tool):
        schema = tool.get_args_schema()
        assert schema is ExploreSchemaLinksParams
        properties = schema.model_json_schema()["properties"]
        assert set(properties) == {"table_name", "column_name", "search_query"}
        # All parameters optional.
        assert ExploreSchemaLinksParams() == ExploreSchemaLinksParams(
            table_name=None, column_name=None, search_query=None
        )

    @pytest.mark.asyncio
    async def test_registered_in_tool_registry(self, tool):
        from vanna.core import ToolRegistry

        registry = ToolRegistry()
        registry.register_local_tool(tool, access_groups=[])
        user = User(id="u1", email="u1@example.com", group_memberships=[])

        schemas = await registry.get_schemas(user)
        names = [s.name for s in schemas]
        assert "explore_schema_links" in names


# ---------------------------------------------------------------------------
# Tool execution
# ---------------------------------------------------------------------------


class TestExploreSchemaLinksTool:
    @pytest.mark.asyncio
    async def test_explore_by_table_name(self, tool, sales_store):
        context = make_context(sales_store)
        result = await tool.execute(
            context, ExploreSchemaLinksParams(table_name="orders")
        )

        assert result.success is True
        assert "orders.customer_id" in result.result_for_llm
        # Only the explored table's columns are listed...
        assert "customers.email" not in result.result_for_llm
        # ...but its join conditions link to related tables.
        assert "- orders.customer_id = customers.id" in result.result_for_llm

    @pytest.mark.asyncio
    async def test_explore_by_search_query(self, tool, sales_store):
        context = make_context(sales_store)
        result = await tool.execute(
            context, ExploreSchemaLinksParams(search_query="sales by region")
        )

        assert result.success is True
        text = result.result_for_llm
        assert "orders.customer_id" in text
        assert "customers.email (VARCHAR): Customer email" in text
        assert "Join conditions:" in text

    @pytest.mark.asyncio
    async def test_explore_by_column_name(self, tool, sales_store):
        context = make_context(sales_store)
        result = await tool.execute(
            context, ExploreSchemaLinksParams(column_name="EMAIL")
        )

        assert result.success is True
        assert "customers.email" in result.result_for_llm

    @pytest.mark.asyncio
    async def test_explore_by_table_and_column(self, tool, sales_store):
        context = make_context(sales_store)
        result = await tool.execute(
            context,
            ExploreSchemaLinksParams(table_name="customers", column_name="email"),
        )

        assert result.success is True
        assert "customers.email" in result.result_for_llm

    @pytest.mark.asyncio
    async def test_no_schema_matches_returns_friendly_message(self, tool):
        store = FakeSchemaVectorStore(search_results=[], relations=[])
        context = make_context(store)

        result = await tool.execute(
            context, ExploreSchemaLinksParams(table_name="nope")
        )

        assert result.success is True
        assert "No schema information found" in result.result_for_llm

    @pytest.mark.asyncio
    async def test_no_store_configured(self, tool):
        context = make_context(None)

        result = await tool.execute(
            context, ExploreSchemaLinksParams(table_name="orders")
        )

        assert result.success is False
        assert "no schema vector store" in result.result_for_llm.lower()
        assert result.error is not None

    @pytest.mark.asyncio
    async def test_no_arguments_provided(self, tool, sales_store):
        context = make_context(sales_store)

        result = await tool.execute(context, ExploreSchemaLinksParams())

        assert result.success is False
        assert "table_name" in result.result_for_llm

    @pytest.mark.asyncio
    async def test_store_failure_returns_friendly_error(self, tool):
        store = FakeSchemaVectorStore(fail=True)
        context = make_context(store)

        result = await tool.execute(
            context, ExploreSchemaLinksParams(search_query="anything")
        )

        assert result.success is False
        assert "failed" in result.result_for_llm.lower()

    @pytest.mark.asyncio
    async def test_database_name_taken_from_context_metadata(self, tool):
        class TrackingStore(FakeSchemaVectorStore):
            def __init__(self):
                super().__init__(search_results=[])
                self.databases = []

            async def search(self, query, database_name, top_k=20):
                self.databases.append(database_name)
                return []

        store = TrackingStore()
        context = make_context(store, database_name="hr_db")

        await tool.execute(context, ExploreSchemaLinksParams(search_query="salaries"))

        assert store.databases == ["hr_db"]
