"""
Tests for tool registry execution and transform_args (including row-level security).
"""

import pytest
from pydantic import BaseModel, Field
from typing import Type, TypeVar, Union

from vanna.core.tool import (
    Tool,
    ToolContext,
    ToolResult,
    ToolCall,
    ToolRejection,
    ToolSchema,
)
from vanna.core.user import User
from vanna.core.registry import ToolRegistry
from vanna.components import UiComponent, SimpleTextComponent
from vanna.integrations.local.agent_memory import DemoAgentMemory

T = TypeVar("T")


class SimpleToolArgs(BaseModel):
    """Simple args for testing."""

    message: str = Field(description="A message")


class MockTool(Tool[SimpleToolArgs]):
    """Mock tool for testing."""

    def __init__(self, tool_name: str = "mock_tool"):
        self._tool_name = tool_name

    @property
    def name(self) -> str:
        return self._tool_name

    @property
    def description(self) -> str:
        return f"A mock tool for testing: {self._tool_name}"

    def get_args_schema(self) -> Type[SimpleToolArgs]:
        return SimpleToolArgs

    async def execute(self, context: ToolContext, args: SimpleToolArgs) -> ToolResult:
        return ToolResult(
            success=True, result_for_llm=f"Mock tool executed: {args.message}"
        )


@pytest.fixture
def agent_memory():
    """Agent memory for testing."""
    return DemoAgentMemory(max_items=100)


@pytest.fixture
def admin_user():
    """User with the admin role."""
    return User(
        id="admin_1",
        username="admin",
        email="admin@example.com",
        metadata={"role": "admin"},
    )


@pytest.fixture
def regular_user():
    """User with no special role."""
    return User(
        id="user_1",
        username="user",
        email="user@example.com",
    )


@pytest.fixture
def analyst_user():
    """User with the analyst role."""
    return User(
        id="analyst_1",
        username="analyst",
        email="analyst@example.com",
        metadata={"role": "analyst"},
    )


@pytest.mark.asyncio
async def test_tool_not_found(agent_memory):
    """Test execution of non-existent tool."""
    print("\n=== Tool Not Found Test ===")

    registry = ToolRegistry()

    user = User(id="user", username="user")
    context = ToolContext(
        user=user,
        conversation_id="test_conv",
        request_id="test_req",
        agent_memory=agent_memory,
    )

    tool_call = ToolCall(
        id="call_1", name="nonexistent_tool", arguments={"message": "test"}
    )

    result = await registry.execute(tool_call, context)

    print(f"✓ Non-existent tool handled gracefully")
    print(f"  Error: {result.error}")

    assert result.success is False
    assert "not found" in result.result_for_llm.lower()


@pytest.mark.asyncio
async def test_duplicate_tool_registration():
    """Test that registering the same tool twice raises error."""
    print("\n=== Duplicate Registration Test ===")

    registry = ToolRegistry()
    tool = MockTool("duplicate_tool")

    # First registration should succeed
    registry.register(tool)
    print(f"✓ First registration succeeded")

    # Second registration should fail
    with pytest.raises(ValueError, match="already registered"):
        registry.register(tool)

    print(f"✓ Duplicate registration properly rejected")


@pytest.mark.asyncio
async def test_list_tools():
    """Test listing all registered tools."""
    print("\n=== List Tools Test ===")

    registry = ToolRegistry()

    registry.register(MockTool("tool1"))
    registry.register(MockTool("tool2"))
    registry.register(MockTool("tool3"))

    tools = await registry.list_tools()

    print(f"✓ Listed {len(tools)} tools")
    print(f"  Tools: {tools}")

    assert len(tools) == 3
    assert "tool1" in tools
    assert "tool2" in tools
    assert "tool3" in tools


# ============================================================================
# transform_args Tests
# ============================================================================


@pytest.mark.asyncio
async def test_transform_args_default_no_transformation(regular_user, agent_memory):
    """Test that default transform_args implementation returns args unchanged."""
    print("\n=== Default transform_args (NoOp) Test ===")

    registry = ToolRegistry()
    tool = MockTool("test_tool")
    registry.register(tool)

    context = ToolContext(
        user=regular_user,
        conversation_id="test_conv",
        request_id="test_req",
        agent_memory=agent_memory,
    )

    # Test the transform_args method directly
    original_args = SimpleToolArgs(message="original message")
    transformed_args = await registry.transform_args(
        tool=tool,
        args=original_args,
        user=regular_user,
        context=context,
    )

    print(f"✓ Default transform_args returns args unchanged")
    print(f"  Original: {original_args.message}")
    print(f"  Transformed: {transformed_args.message}")

    assert transformed_args == original_args
    assert transformed_args.message == "original message"
    assert not isinstance(transformed_args, ToolRejection)


class CustomTransformRegistry(ToolRegistry):
    """Custom registry that modifies arguments."""

    async def transform_args(
        self,
        tool: Tool[T],
        args: T,
        user: User,
        context: ToolContext,
    ) -> Union[T, ToolRejection]:
        """Custom transform that appends user info to message."""
        if isinstance(args, SimpleToolArgs):
            # Modify the args by appending user info
            modified_args = SimpleToolArgs(
                message=f"{args.message} [user: {user.username}]"
            )
            return modified_args
        return args


@pytest.mark.asyncio
async def test_transform_args_custom_modification(regular_user, agent_memory):
    """Test custom transform_args that modifies arguments."""
    print("\n=== Custom transform_args Modification Test ===")

    registry = CustomTransformRegistry()
    tool = MockTool("test_tool")
    registry.register(tool)

    context = ToolContext(
        user=regular_user,
        conversation_id="test_conv",
        request_id="test_req",
        agent_memory=agent_memory,
    )

    # Execute tool - args should be transformed
    tool_call = ToolCall(
        id="call_1",
        name="test_tool",
        arguments={"message": "hello"},
    )

    result = await registry.execute(tool_call, context)

    print(f"✓ Tool executed with transformed args")
    print(f"  Result: {result.result_for_llm}")

    assert result.success is True
    assert "hello [user: user]" in result.result_for_llm
    assert "Mock tool executed" in result.result_for_llm


class RejectionRegistry(ToolRegistry):
    """Custom registry that rejects certain arguments."""

    async def transform_args(
        self,
        tool: Tool[T],
        args: T,
        user: User,
        context: ToolContext,
    ) -> Union[T, ToolRejection]:
        """Reject args containing 'forbidden' keyword."""
        if isinstance(args, SimpleToolArgs):
            if "forbidden" in args.message.lower():
                return ToolRejection(
                    reason=f"Message contains forbidden keyword. User '{user.username}' is not allowed to use this word."
                )
        return args


@pytest.mark.asyncio
async def test_transform_args_rejection(regular_user, agent_memory):
    """Test transform_args returning ToolRejection."""
    print("\n=== transform_args Rejection Test ===")

    registry = RejectionRegistry()
    tool = MockTool("test_tool")
    registry.register(tool)

    context = ToolContext(
        user=regular_user,
        conversation_id="test_conv",
        request_id="test_req",
        agent_memory=agent_memory,
    )

    # Execute tool with forbidden word
    tool_call = ToolCall(
        id="call_1",
        name="test_tool",
        arguments={"message": "this is forbidden"},
    )

    result = await registry.execute(tool_call, context)

    print(f"✓ Tool execution rejected by transform_args")
    print(f"  Error: {result.error}")

    assert result.success is False
    assert "forbidden keyword" in result.result_for_llm
    assert "not allowed" in result.result_for_llm
    assert "user" in result.result_for_llm


@pytest.mark.asyncio
async def test_transform_args_allows_approved_content(regular_user, agent_memory):
    """Test that transform_args allows approved content."""
    print("\n=== transform_args Allows Approved Content Test ===")

    registry = RejectionRegistry()
    tool = MockTool("test_tool")
    registry.register(tool)

    context = ToolContext(
        user=regular_user,
        conversation_id="test_conv",
        request_id="test_req",
        agent_memory=agent_memory,
    )

    # Execute tool with approved message
    tool_call = ToolCall(
        id="call_1",
        name="test_tool",
        arguments={"message": "this is allowed"},
    )

    result = await registry.execute(tool_call, context)

    print(f"✓ Tool execution allowed for approved content")
    print(f"  Result: {result.result_for_llm}")

    assert result.success is True
    assert "Mock tool executed" in result.result_for_llm
    assert "this is allowed" in result.result_for_llm


class RowLevelSecurityRegistry(ToolRegistry):
    """Custom registry that applies row-level security transformations."""

    async def transform_args(
        self,
        tool: Tool[T],
        args: T,
        user: User,
        context: ToolContext,
    ) -> Union[T, ToolRejection]:
        """Apply RLS by modifying SQL queries based on user role."""
        if isinstance(args, SimpleToolArgs):
            # Simulate SQL query transformation for RLS
            if "SELECT" in args.message.upper():
                # Add WHERE clause based on user role
                role = user.metadata.get("role")
                if role == "admin":
                    # Admins see everything - no modification needed
                    return args
                elif role == "analyst":
                    # Analysts see filtered data
                    modified_message = args.message + " WHERE department='analytics'"
                    return SimpleToolArgs(message=modified_message)
                else:
                    # Regular users see even more restricted data
                    modified_message = args.message + f" WHERE user_id='{user.id}'"
                    return SimpleToolArgs(message=modified_message)
        return args


@pytest.mark.asyncio
async def test_transform_args_row_level_security(
    admin_user, analyst_user, regular_user, agent_memory
):
    """Test transform_args implementing row-level security."""
    print("\n=== Row-Level Security Test ===")

    registry = RowLevelSecurityRegistry()
    tool = MockTool("sql_tool")
    registry.register(tool)

    base_query = "SELECT * FROM users"

    # Test admin user - no modification
    admin_context = ToolContext(
        user=admin_user,
        conversation_id="test_conv",
        request_id="test_req_1",
        agent_memory=agent_memory,
    )

    tool_call = ToolCall(
        id="call_1",
        name="sql_tool",
        arguments={"message": base_query},
    )

    result = await registry.execute(tool_call, admin_context)
    print(f"✓ Admin query: {result.result_for_llm}")
    assert result.success is True
    assert "WHERE" not in result.result_for_llm

    # Test analyst user - department filter
    analyst_context = ToolContext(
        user=analyst_user,
        conversation_id="test_conv",
        request_id="test_req_2",
        agent_memory=agent_memory,
    )

    result = await registry.execute(tool_call, analyst_context)
    print(f"✓ Analyst query: {result.result_for_llm}")
    assert result.success is True
    assert "WHERE department='analytics'" in result.result_for_llm

    # Test regular user - user_id filter
    regular_context = ToolContext(
        user=regular_user,
        conversation_id="test_conv",
        request_id="test_req_3",
        agent_memory=agent_memory,
    )

    result = await registry.execute(tool_call, regular_context)
    print(f"✓ Regular user query: {result.result_for_llm}")
    assert result.success is True
    assert f"WHERE user_id='{regular_user.id}'" in result.result_for_llm


@pytest.mark.asyncio
async def test_transform_args_called_during_execution(regular_user, agent_memory):
    """Test that transform_args is called during tool execution flow."""
    print("\n=== transform_args Called During Execution Test ===")

    class InstrumentedRegistry(ToolRegistry):
        def __init__(self):
            super().__init__()
            self.transform_called = False
            self.transform_call_count = 0

        async def transform_args(self, tool, args, user, context):
            self.transform_called = True
            self.transform_call_count += 1
            return await super().transform_args(tool, args, user, context)

    registry = InstrumentedRegistry()
    tool = MockTool("test_tool")
    registry.register(tool)

    context = ToolContext(
        user=regular_user,
        conversation_id="test_conv",
        request_id="test_req",
        agent_memory=agent_memory,
    )

    tool_call = ToolCall(
        id="call_1",
        name="test_tool",
        arguments={"message": "test"},
    )

    result = await registry.execute(tool_call, context)

    print(f"✓ transform_args was called during execution")
    print(f"  Called: {registry.transform_called}")
    print(f"  Call count: {registry.transform_call_count}")

    assert result.success is True
    assert registry.transform_called is True
    assert registry.transform_call_count == 1


@pytest.mark.asyncio
async def test_transform_args_receives_correct_parameters(regular_user, agent_memory):
    """Test that transform_args receives correct parameters."""
    print("\n=== transform_args Parameter Validation Test ===")

    class ParameterCheckRegistry(ToolRegistry):
        def __init__(self):
            super().__init__()
            self.received_tool = None
            self.received_args = None
            self.received_user = None
            self.received_context = None

        async def transform_args(self, tool, args, user, context):
            self.received_tool = tool
            self.received_args = args
            self.received_user = user
            self.received_context = context
            return await super().transform_args(tool, args, user, context)

    registry = ParameterCheckRegistry()
    tool = MockTool("test_tool")
    registry.register(tool)

    context = ToolContext(
        user=regular_user,
        conversation_id="test_conv_123",
        request_id="test_req_456",
        agent_memory=agent_memory,
    )

    tool_call = ToolCall(
        id="call_1",
        name="test_tool",
        arguments={"message": "test message"},
    )

    result = await registry.execute(tool_call, context)

    print(f"✓ transform_args received correct parameters")
    print(f"  Tool name: {registry.received_tool.name}")
    print(f"  Args message: {registry.received_args.message}")
    print(f"  User: {registry.received_user.username}")
    print(f"  Context conv_id: {registry.received_context.conversation_id}")

    assert result.success is True
    assert registry.received_tool is not None
    assert registry.received_tool.name == "test_tool"
    assert registry.received_args is not None
    assert registry.received_args.message == "test message"
    assert registry.received_user is not None
    assert registry.received_user.id == regular_user.id
    assert registry.received_context is not None
    assert registry.received_context.conversation_id == "test_conv_123"


@pytest.mark.asyncio
async def test_transform_args_called_during_agent_send_message():
    """Test that transform_args is called during Agent.send_message workflow."""
    print("\n=== transform_args in Agent.send_message Test ===")

    # Import necessary components
    from vanna import Agent
    from vanna.core.user.resolver import UserResolver
    from vanna.core.user.request_context import RequestContext
    from vanna.core.llm import LlmService, LlmRequest, LlmResponse, LlmMessage
    from vanna.core.agent.config import AgentConfig

    # Create a custom registry that tracks transform_args calls
    class InstrumentedAgentRegistry(ToolRegistry):
        def __init__(self):
            super().__init__()
            self.transform_calls = []

        async def transform_args(self, tool, args, user, context):
            # Track that transform_args was called
            self.transform_calls.append(
                {
                    "tool_name": tool.name,
                    "args": args,
                    "user_id": user.id,
                    "conversation_id": context.conversation_id,
                }
            )
            # Apply a transformation to verify it's used
            if isinstance(args, SimpleToolArgs):
                modified_args = SimpleToolArgs(message=f"{args.message} [transformed]")
                return modified_args
            return args

    # Create a simple user resolver
    class TestUserResolver(UserResolver):
        async def resolve_user(self, request_context: RequestContext) -> User:
            return User(
                id="test_user_123",
                username="test_user",
                email="test@example.com",
            )

    # Create a mock LLM service that calls a tool
    class MockLlmService(LlmService):
        async def send_request(self, request: LlmRequest) -> LlmResponse:
            # Return a response that calls our mock tool
            return LlmResponse(
                content="I'll use the mock tool",
                tool_calls=[
                    ToolCall(
                        id="call_123",
                        name="mock_tool",
                        arguments={"message": "test message"},
                    )
                ],
                raw_response=None,
            )

        async def stream_request(self, request: LlmRequest):
            # Yield a single chunk with tool call
            from vanna.core.llm import LlmStreamChunk

            yield LlmStreamChunk(
                content="I'll use the mock tool",
                tool_calls=[
                    ToolCall(
                        id="call_123",
                        name="mock_tool",
                        arguments={"message": "test message"},
                    )
                ],
                raw_chunk=None,
            )

        async def validate_tools(self, tools: list[ToolSchema]) -> None:
            # No validation needed for this test
            pass

    # Set up the agent
    instrumented_registry = InstrumentedAgentRegistry()
    tool = MockTool("mock_tool")
    instrumented_registry.register(tool)

    agent_memory = DemoAgentMemory(max_items=100)

    agent = Agent(
        llm_service=MockLlmService(),
        tool_registry=instrumented_registry,
        user_resolver=TestUserResolver(),
        agent_memory=agent_memory,
        config=AgentConfig(),
    )

    # Send a message through the agent
    request_context = RequestContext(cookies={}, headers={})
    components = []

    async for component in agent.send_message(request_context, "test message"):
        components.append(component)

    print(f"✓ Agent.send_message completed")
    print(f"  Transform calls: {len(instrumented_registry.transform_calls)}")
    print(f"  Components received: {len(components)}")

    # Verify that transform_args was called
    assert len(instrumented_registry.transform_calls) > 0, (
        "transform_args should be called during Agent.send_message"
    )

    # Check the first transform call
    first_call = instrumented_registry.transform_calls[0]
    assert first_call["tool_name"] == "mock_tool"
    assert first_call["user_id"] == "test_user_123"
    assert first_call["conversation_id"] is not None

    print(f"  ✓ transform_args was called with correct parameters")
    print(f"    Tool: {first_call['tool_name']}")
    print(f"    User: {first_call['user_id']}")
    print(
        f"    Total transform_args calls: {len(instrumented_registry.transform_calls)}"
    )

    # Verify that the args passed to transform_args have the expected message
    assert first_call["args"].message == "test message"
    print(f"    Original args message: {first_call['args'].message}")

    print(
        f"  ✓ All checks passed - transform_args is called during Agent.send_message workflow"
    )
