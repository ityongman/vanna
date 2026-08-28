"""
Tests for agent memory tools.
"""

import pytest
import uuid
from vanna.tools.agent_memory import (
    SearchSavedCorrectToolUsesTool,
    SearchSavedCorrectToolUsesParams,
)
from vanna.core.tool import ToolContext
from vanna.core.user import User
from vanna.integrations.local.agent_memory import DemoAgentMemory
from vanna.core.rich_component import ComponentType


@pytest.fixture
def demo_agent_memory():
    """Create a demo agent memory instance."""
    return DemoAgentMemory(max_items=100)


@pytest.fixture
def search_tool():
    """Create a search tool instance."""
    return SearchSavedCorrectToolUsesTool()


class TestMemoryToolDetailedResults:
    """Test memory tool detailed results feature."""

    @pytest.mark.asyncio
    async def test_search_returns_detailed_results(
        self, search_tool, demo_agent_memory
    ):
        """Test that the search tool shows detailed memory results in a collapsible card."""
        # Create context without any UI feature flags
        context = ToolContext(
            user=User(id="user", email="user@example.com"),
            conversation_id=str(uuid.uuid4()),
            request_id=str(uuid.uuid4()),
            agent_memory=demo_agent_memory,
        )

        # Save some memories
        await demo_agent_memory.save_tool_usage(
            question="What is the total sales?",
            tool_name="run_sql",
            args={"query": "SELECT SUM(total) FROM invoices"},
            context=context,
            success=True,
        )

        # Search for similar patterns
        search_params = SearchSavedCorrectToolUsesParams(
            question="What are the total sales?", limit=10, similarity_threshold=0.5
        )

        result = await search_tool.execute(context, search_params)

        # Verify result
        assert result.success is True
        assert result.ui_component is not None
        assert result.ui_component.rich_component is not None

        # Check that it's a CardComponent (detailed view)
        assert result.ui_component.rich_component.type == ComponentType.CARD

        # Check collapsible properties
        card = result.ui_component.rich_component
        assert card.collapsible is True
        assert card.collapsed is True  # Should start collapsed

        # Verify content includes detailed information
        assert "Retrieved memories passed to LLM" in card.content
        assert "run_sql" in card.content
        assert "similarity:" in card.content.lower()
        assert "Question:" in card.content
        assert "Arguments:" in card.content

    @pytest.mark.asyncio
    async def test_search_returns_detailed_results_for_all_users(
        self, search_tool, demo_agent_memory
    ):
        """Test that the search tool shows detailed results regardless of user."""
        # Create context without any UI feature flags
        context = ToolContext(
            user=User(id="user", email="user@example.com"),
            conversation_id=str(uuid.uuid4()),
            request_id=str(uuid.uuid4()),
            agent_memory=demo_agent_memory,
        )

        # Save some memories
        await demo_agent_memory.save_tool_usage(
            question="What is the total sales?",
            tool_name="run_sql",
            args={"query": "SELECT SUM(total) FROM invoices"},
            context=context,
            success=True,
        )

        # Search for similar patterns
        search_params = SearchSavedCorrectToolUsesParams(
            question="What are the total sales?", limit=10, similarity_threshold=0.5
        )

        result = await search_tool.execute(context, search_params)

        # Verify result
        assert result.success is True
        assert result.ui_component is not None
        assert result.ui_component.rich_component is not None

        # Check that it's a CardComponent (detailed view)
        assert result.ui_component.rich_component.type == ComponentType.CARD

        # Verify it shows success message
        card = result.ui_component.rich_component
        assert "Retrieved memories passed to LLM" in card.content

    @pytest.mark.asyncio
    async def test_detailed_results_include_all_memory_fields(
        self, search_tool, demo_agent_memory
    ):
        """Test that detailed results include all relevant memory fields."""
        # Create context without any UI feature flags
        context = ToolContext(
            user=User(id="user", email="user@example.com"),
            conversation_id=str(uuid.uuid4()),
            request_id=str(uuid.uuid4()),
            agent_memory=demo_agent_memory,
        )

        # Save a memory
        await demo_agent_memory.save_tool_usage(
            question="Show me customer names",
            tool_name="run_sql",
            args={"query": "SELECT name FROM customers"},
            context=context,
            success=True,
        )

        # Search for it
        search_params = SearchSavedCorrectToolUsesParams(
            question="Show customer names", limit=10, similarity_threshold=0.3
        )

        result = await search_tool.execute(context, search_params)

        # Verify detailed content
        card = result.ui_component.rich_component
        content = card.content

        # Check for all expected fields
        assert "Question:" in content
        assert "Show me customer names" in content
        assert "Arguments:" in content
        assert "run_sql" in content
        assert "similarity:" in content.lower()

        # Timestamp and ID should be included if available
        # (DemoAgentMemory might not set these, but the code should handle them)

    @pytest.mark.asyncio
    async def test_no_results_shows_card(
        self, search_tool, demo_agent_memory
    ):
        """Test that no results shows a card with 0 results for all users."""
        context = ToolContext(
            user=User(id="user", email="user@example.com"),
            conversation_id=str(uuid.uuid4()),
            request_id=str(uuid.uuid4()),
            agent_memory=demo_agent_memory,
        )

        search_params = SearchSavedCorrectToolUsesParams(
            question="This query will not match anything",
            limit=10,
            similarity_threshold=0.99,
        )

        result = await search_tool.execute(context, search_params)

        assert result.success is True
        assert "No similar tool usage patterns found" in result.result_for_llm
        # All users should see a card showing 0 results
        assert result.ui_component.rich_component.type == ComponentType.CARD
        assert "0 Results" in result.ui_component.rich_component.title
        assert result.ui_component.rich_component.collapsible is True

    @pytest.mark.asyncio
    async def test_llm_result_consistent_regardless_of_user(
        self, search_tool, demo_agent_memory
    ):
        """Test that the LLM receives the same information regardless of user."""
        # Save a memory
        context = ToolContext(
            user=User(id="user", email="user@example.com"),
            conversation_id=str(uuid.uuid4()),
            request_id=str(uuid.uuid4()),
            agent_memory=demo_agent_memory,
        )

        await demo_agent_memory.save_tool_usage(
            question="Count all records",
            tool_name="run_sql",
            args={"query": "SELECT COUNT(*) FROM table"},
            context=context,
            success=True,
        )

        search_params = SearchSavedCorrectToolUsesParams(
            question="Count records", limit=10, similarity_threshold=0.3
        )

        result = await search_tool.execute(context, search_params)

        assert result.success is True
        assert "Found" in result.result_for_llm
        assert "similar tool usage pattern" in result.result_for_llm
        # Detailed card view for all users
        assert result.ui_component.rich_component.type == ComponentType.CARD


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
