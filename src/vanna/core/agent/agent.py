"""
Agent implementation for the Vanna Agents framework.

This module provides the main Agent class that orchestrates the interaction
between LLM services, tools, and conversation storage.
"""

import traceback
import uuid
from typing import TYPE_CHECKING, AsyncGenerator, Dict, List, Optional

from vanna.components import (
    UiComponent,
    SimpleTextComponent,
    RichTextComponent,
    StatusBarUpdateComponent,
    TaskTrackerUpdateComponent,
    ChatInputUpdateComponent,
    StatusCardComponent,
    Task,
)
from .config import AgentConfig
from vanna.core.storage import ConversationStore
from vanna.core.llm import LlmService
from vanna.core.system_prompt import SystemPromptBuilder
from vanna.core.storage import Conversation, Message
from vanna.core.llm import LlmMessage, LlmRequest, LlmResponse
from vanna.core.tool import Tool, ToolCall, ToolContext, ToolResult, ToolSchema
from vanna.core.user import User
from vanna.core.registry import ToolRegistry
from vanna.core.system_prompt import DefaultSystemPromptBuilder
from vanna.core.lifecycle import LifecycleHook
from vanna.core.middleware import LlmMiddleware
from vanna.core.workflow import WorkflowHandler, DefaultWorkflowHandler
from vanna.core.recovery import ErrorRecoveryStrategy, RecoveryActionType
from vanna.core.enricher import ToolContextEnricher
from vanna.core.enhancer import (
    LlmContextEnhancer,
    DefaultLlmContextEnhancer,
    AutoLinkSchemaEnhancer,
    LlmContextEnhancerChain,
)
from vanna.core.filter import ConversationFilter
from vanna.core.observability import ObservabilityProvider
from vanna.core.user.resolver import UserResolver
from vanna.core.user.request_context import RequestContext
from vanna.core.audit import AuditLogger
from vanna.capabilities.agent_memory import AgentMemory
from vanna.capabilities.schema_vector_store import SchemaVectorStore
from vanna.capabilities.sql_runner import SqlRunner

import logging

logger = logging.getLogger(__name__)

logger.info("Loaded vanna.core.agent.agent module")

if TYPE_CHECKING:
    pass


class Agent:
    """Main agent implementation.

    The Agent class orchestrates LLM interactions, tool execution, and conversation
    management. It provides 7 extensibility points for customization:

    - lifecycle_hooks: Hook into message and tool execution lifecycle
    - llm_middlewares: Intercept and transform LLM requests/responses
    - error_recovery_strategy: Handle errors with retry logic
    - context_enrichers: Add data to tool execution context
    - llm_context_enhancer: Enhance LLM system prompts and messages with context
    - conversation_filters: Filter conversation history before LLM calls
    - observability_provider: Reserved for future telemetry (currently no-op)

    Example:
        agent = Agent(
            llm_service=AnthropicLlmService(api_key="..."),
            tool_registry=registry,
            conversation_store=store,
            lifecycle_hooks=[QuotaCheckHook()],
            llm_middlewares=[CachingMiddleware()],
            llm_context_enhancer=DefaultLlmContextEnhancer(agent_memory),
        )
    """

    def __init__(
        self,
        llm_service: LlmService,
        tool_registry: ToolRegistry,
        user_resolver: UserResolver,
        agent_memory: AgentMemory,
        conversation_store: Optional[ConversationStore] = None,
        config: AgentConfig = AgentConfig(),
        system_prompt_builder: SystemPromptBuilder = DefaultSystemPromptBuilder(),
        lifecycle_hooks: List[LifecycleHook] = [],
        llm_middlewares: List[LlmMiddleware] = [],
        workflow_handler: Optional[WorkflowHandler] = None,
        error_recovery_strategy: Optional[ErrorRecoveryStrategy] = None,
        context_enrichers: List[ToolContextEnricher] = [],
        llm_context_enhancer: Optional[LlmContextEnhancer] = None,
        conversation_filters: List[ConversationFilter] = [],
        observability_provider: Optional[ObservabilityProvider] = None,
        audit_logger: Optional[AuditLogger] = None,
        schema_vector_store: Optional[SchemaVectorStore] = None,
        sql_runner: Optional[SqlRunner] = None,
        extra_tools: List[Tool] = [],
    ):
        self.llm_service = llm_service
        self.tool_registry = tool_registry
        self.user_resolver = user_resolver
        self.agent_memory = agent_memory

        # Import here to avoid circular dependency
        if conversation_store is None:
            from vanna.integrations.local import SQLiteConversationStore

            conversation_store = SQLiteConversationStore()

        self.conversation_store = conversation_store
        self.config = config
        self.system_prompt_builder = system_prompt_builder
        self.lifecycle_hooks = lifecycle_hooks
        self.llm_middlewares = llm_middlewares

        # Use DefaultWorkflowHandler if none provided
        if workflow_handler is None:
            workflow_handler = DefaultWorkflowHandler()
        self.workflow_handler = workflow_handler

        self.error_recovery_strategy = error_recovery_strategy
        self.context_enrichers = context_enrichers

        # Use DefaultLlmContextEnhancer if none provided
        if llm_context_enhancer is None:
            llm_context_enhancer = DefaultLlmContextEnhancer(agent_memory)

        # AutoLink schema enhancement: append AutoLinkSchemaEnhancer to the
        # enhancer chain when enabled and a store is available (injection
        # point 2 of the AutoLink integration plan).
        if config.autolink_config.enabled and schema_vector_store is not None:
            llm_context_enhancer = LlmContextEnhancerChain(
                [
                    llm_context_enhancer,
                    AutoLinkSchemaEnhancer(
                        schema_vector_store=schema_vector_store,
                        config=config.autolink_config,
                    ),
                ]
            )
        elif config.autolink_config.enabled:
            logger.info(
                "AutoLink is enabled but no schema_vector_store was provided; "
                "schema enhancement is disabled"
            )
        self.llm_context_enhancer = llm_context_enhancer
        self.schema_vector_store = schema_vector_store

        self.conversation_filters = conversation_filters
        # Reserved for future telemetry; no business tracking calls are made.
        self.observability_provider = observability_provider
        self.audit_logger = audit_logger

        # Resolve the SQL runner: explicit instance wins (test mocks), else
        # derive from config.database via the URL-scheme factory.
        # 注意：这是 SDK 单库路径（构造绑定的全局兜底 runner）。
        # server 多业务启动只传 businesses 不传 database，这里保持
        # sql_runner=None——真正的 runner 由请求按 business_id 惰性
        # 创建（见 _get_or_create_sql_runner 与 _send_message），
        # 执行时经 ToolContext.sql_runner 优先消费（见 RunSqlTool.execute）。
        if sql_runner is None and config.database is not None:
            from vanna.integrations.databases.factory import create_sql_runner

            sql_runner = create_sql_runner(config.database.url)
        self.sql_runner = sql_runner
        self.extra_tools = list(extra_tools)
        # 业务路由的 runner 缓存：business_id -> SqlRunner（首次请求创建后复用）
        self._business_sql_runners: Dict[str, SqlRunner] = {}

        # Wire audit logger into tool registry
        if self.audit_logger and self.config.audit_config.enabled:
            self.tool_registry.audit_logger = self.audit_logger
            self.tool_registry.audit_config = self.config.audit_config

        self._auto_register_tools()
        logger.info("Initialized Agent")

    def _auto_register_tools(self) -> None:
        """Register built-in tools based on injected capabilities.

        - agent_memory         -> memory tools (few-shot learning loop)
        - schema_vector_store  -> explore_schema_links (AutoLink)
        - sql_runner           -> run_sql + visualize_data (text-to-SQL)
        - extra_tools          -> registered as-is
        Tools already present in the registry are never overwritten.
        """
        if not self.config.auto_register_tools:
            return

        # Category 1: vector-db tools (bound at runtime via ToolContext).
        from vanna.tools.agent_memory import (
            SaveQuestionToolArgsTool,
            SaveTextMemoryTool,
            SearchSavedCorrectToolUsesTool,
        )

        for tool in (
            SearchSavedCorrectToolUsesTool(),
            SaveQuestionToolArgsTool(),
            SaveTextMemoryTool(),
        ):
            self._register_if_absent(tool)

        if self.schema_vector_store is not None:
            from vanna.tools.explore_schema_links import ExploreSchemaLinksTool

            self._register_if_absent(ExploreSchemaLinksTool())

        # Category 2: database tools (text-to-SQL). Register when a bound
        # runner exists OR businesses are configured (per-request routing
        # supplies the runner via ToolContext.sql_runner).
        # 注意：工具注册与 runner 绑定是解耦的——多业务模式下这里
        # RunSqlTool(sql_runner=None) 也会注册（注册只是声明"有此能力"，
        # 供 LLM 生成 tool_call 用），执行时才通过请求级
        # ToolContext.sql_runner（按 business_id 路由）或构造绑定的
        # 兜底 runner 解析，详见 RunSqlTool.execute 的优先级注释。
        if self.sql_runner is not None or self.config.businesses:
            from vanna.tools.run_sql import RunSqlTool
            from vanna.tools.visualize_data import VisualizeDataTool

            self._register_if_absent(RunSqlTool(sql_runner=self.sql_runner))
            # VisualizeDataTool 是 text-to-SQL 能力链的配套工具，用于可视化查询结果
            self._register_if_absent(VisualizeDataTool())
        else:
            logger.warning(
                "No sql_runner provided and no config.database set; "
                "text-to-SQL is unavailable (run_sql/visualize_data not registered)"
            )

        # Category 3: extra tools passed by the caller.
        for tool in self.extra_tools:
            self._register_if_absent(tool)

    def _register_if_absent(self, tool: Tool) -> None:
        """Register a tool, silently skipping names already present."""
        try:
            self.tool_registry.register(tool)
        except ValueError:
            logger.debug("Tool '%s' already registered; keeping existing", tool.name)

    def _get_or_create_sql_runner(self, business: "BusinessConfig") -> SqlRunner:
        """Get or create a cached SqlRunner for a business configuration.

        多业务模式的 runner 创建入口：首次请求该 business 时按
        database.url 派生并缓存，后续复用；创建结果注入请求级
        ToolContext.sql_runner，供 RunSqlTool 执行时消费。
        """
        if business.id not in self._business_sql_runners:
            from vanna.integrations.databases.factory import create_sql_runner

            self._business_sql_runners[business.id] = create_sql_runner(
                business.database.url
            )
            logger.info("Created SqlRunner for business '%s'", business.id)
        return self._business_sql_runners[business.id]

    async def send_message(
        self,
        request_context: RequestContext,
        message: str,
        *,
        conversation_id: Optional[str] = None,
    ) -> AsyncGenerator[UiComponent, None]:
        """
        Process a user message and yield UI components with error handling.

        Args:
            request_context: Request context for user resolution (includes metadata)
            message: User's message content
            conversation_id: Optional conversation ID; if None, creates new conversation

        Yields:
            UiComponent instances for UI updates
        """
        try:
            # Delegate to internal method
            async for component in self._send_message(
                request_context, message, conversation_id=conversation_id
            ):
                yield component
        except Exception as e:
            # Log full stack trace
            stack_trace = traceback.format_exc()
            logger.error(
                f"Error in send_message (conversation_id={conversation_id}): {e}\n{stack_trace}",
                exc_info=True,
            )

            # Yield error component to UI. ValueError carries intentional
            # routing/validation messages; other errors stay generic.
            if isinstance(e, ValueError):
                error_description = str(e)
            else:
                error_description = (
                    "An unexpected error occurred while processing your "
                    "message. Please try again."
                )
            if conversation_id:
                error_description += f"\n\nConversation ID: {conversation_id}"

            yield UiComponent(
                rich_component=StatusCardComponent(
                    title="Error Processing Message",
                    status="error",
                    description=error_description,
                    icon="⚠️",
                ),
                simple_component=SimpleTextComponent(
                    text=f"Error: An unexpected error occurred. Please try again.{f' (Conversation ID: {conversation_id})' if conversation_id else ''}"
                ),
            )

            # Update status bar to show error state
            yield UiComponent(  # type: ignore
                rich_component=StatusBarUpdateComponent(
                    status="error",
                    message="Error occurred",
                    detail="An unexpected error occurred while processing your message",
                )
            )

            # Re-enable chat input so user can try again
            yield UiComponent(  # type: ignore
                rich_component=ChatInputUpdateComponent(
                    placeholder="Try again...", disabled=False
                )
            )

    async def _send_message(
        self,
        request_context: RequestContext,
        message: str,
        *,
        conversation_id: Optional[str] = None,
    ) -> AsyncGenerator[UiComponent, None]:
        """
        Internal method to process a user message and yield UI components.

        Args:
            request_context: Request context for user resolution (includes metadata)
            message: User's message content
            conversation_id: Optional conversation ID; if None, creates new conversation

        Yields:
            UiComponent instances for UI updates
        """
        # Resolve user from request context
        user = await self.user_resolver.resolve_user(request_context)

        # Check if this is a starter UI request (empty message or explicit metadata flag)
        is_starter_request = (not message.strip()) or request_context.metadata.get(
            "starter_ui_request", False
        )

        if is_starter_request and self.workflow_handler:
            try:
                # Load or create conversation for context
                if conversation_id is None:
                    conversation_id = str(uuid.uuid4())

                conversation = await self.conversation_store.get_conversation(
                    conversation_id, user
                )
                if not conversation:
                    # Create empty conversation (will be saved if workflow produces components)
                    conversation = Conversation(
                        id=conversation_id, user=user, messages=[]
                    )

                # Get starter UI from workflow handler
                components = await self.workflow_handler.get_starter_ui(
                    self, user, conversation
                )

                if components:
                    # Yield the starter UI components
                    for component in components:
                        yield component

                    # Yield finalization components
                    yield UiComponent(  # type: ignore
                        rich_component=StatusBarUpdateComponent(
                            status="idle",
                            message="Ready",
                            detail="Choose an option or type a message",
                        )
                    )
                    yield UiComponent(  # type: ignore
                        rich_component=ChatInputUpdateComponent(
                            placeholder="Ask a question...", disabled=False
                        )
                    )

                # Save the conversation if it was newly created
                if self.config.auto_save_conversations:
                    await self.conversation_store.update_conversation(conversation)

                return  # Exit without calling LLM

            except Exception as e:
                logger.error(f"Error generating starter UI: {e}", exc_info=True)
                # Fall through to normal processing on error

        # Don't process actual empty messages (that aren't starter requests)
        if not message.strip():
            return

        # Run before_message hooks
        modified_message = message
        for hook in self.lifecycle_hooks:
            hook_result = await hook.before_message(user, modified_message)
            if hook_result is not None:
                modified_message = hook_result

        # Use the potentially modified message
        message = modified_message

        # Generate conversation ID and request ID if not provided
        if conversation_id is None:
            conversation_id = str(uuid.uuid4())

        request_id = str(uuid.uuid4())

        # Update status to working
        yield UiComponent(  # type: ignore
            rich_component=StatusBarUpdateComponent(
                status="working",
                message="Processing your request...",
                detail="Analyzing query",
            )
        )

        # Load or create conversation (but don't add message yet)
        conversation = await self.conversation_store.get_conversation(
            conversation_id, user
        )

        is_new_conversation = conversation is None

        if not conversation:
            # Create empty conversation (will add message after workflow handler check)
            conversation = Conversation(id=conversation_id, user=user, messages=[])

        # Try workflow handler before adding message to conversation
        if self.workflow_handler:
            try:
                workflow_result = await self.workflow_handler.try_handle(
                    self, user, conversation, message
                )

                if workflow_result.should_skip_llm:
                    # Workflow handled the message, short-circuit LLM

                    # Apply conversation mutation if provided
                    if workflow_result.conversation_mutation:
                        await workflow_result.conversation_mutation(conversation)

                    # Stream components
                    if workflow_result.components:
                        if isinstance(workflow_result.components, list):
                            for component in workflow_result.components:
                                yield component
                        else:
                            # AsyncGenerator
                            async for component in workflow_result.components:
                                yield component

                    # Finalize response (status bar + chat input)
                    yield UiComponent(  # type: ignore
                        rich_component=StatusBarUpdateComponent(
                            status="idle",
                            message="Workflow complete",
                            detail="Ready for next message",
                        )
                    )
                    yield UiComponent(  # type: ignore
                        rich_component=ChatInputUpdateComponent(
                            placeholder="Ask a question...", disabled=False
                        )
                    )

                    # Save conversation if auto-save enabled
                    if self.config.auto_save_conversations:
                        await self.conversation_store.update_conversation(conversation)

                    # Exit without calling LLM
                    return

            except Exception as e:
                logger.error(f"Error in workflow handler: {e}", exc_info=True)
                # Fall through to normal LLM processing on error

        # Persist new conversation to store before adding message
        if is_new_conversation:
            await self.conversation_store.update_conversation(conversation)

        # Not triggered, add user message to conversation now
        conversation.add_message(Message(role="user", content=message))

        # Add initial task
        context_task = Task(
            title="Load conversation context",
            description="Reading message history and user context",
            status="pending",
        )
        yield UiComponent(  # type: ignore
            rich_component=TaskTrackerUpdateComponent.add_task(context_task)
        )

        context_metadata: dict = {}
        context_sql_runner = None

        # Business routing: resolve sql_runner and autolink_database_name
        # from request metadata business_id. When businesses are configured
        # there is no fallback route — a missing or unknown business_id is
        # an error (fail fast instead of querying the wrong database).
        business_id = request_context.metadata.get("business_id")
        if self.config.businesses:
            if not business_id:
                raise ValueError(
                    "business_id is required: this agent routes requests by "
                    "business; set business_id in the chat request"
                )
            business = self.config.businesses.get(business_id)
            if business is None:
                raise ValueError(
                    f"business_id '{business_id}' not found or disabled; "
                    f"available: {', '.join(sorted(self.config.businesses))}"
                )
            context_sql_runner = self._get_or_create_sql_runner(business)
            context_metadata["autolink_database_name"] = (
                business.effective_database_name()
            )
            logger.info(
                "Business routing: business_id=%s, database_name=%s",
                business_id,
                business.effective_database_name(),
            )
        elif self.schema_vector_store is not None:
            context_metadata["autolink_database_name"] = (
                self.config.autolink_config.database_name
            )

        context = ToolContext(
            user=user,
            conversation_id=conversation_id,
            request_id=request_id,
            agent_memory=self.agent_memory,
            schema_vector_store=self.schema_vector_store,
            sql_runner=context_sql_runner,
            observability_provider=self.observability_provider,
            metadata=context_metadata,
        )

        # Enrich context with additional data
        for enricher in self.context_enrichers:
            context = await enricher.enrich_context(context)

        # Get available tools
        tool_schemas = await self.tool_registry.get_schemas()

        # Update task status to completed
        yield UiComponent(  # type: ignore
            rich_component=TaskTrackerUpdateComponent.update_task(
                context_task.id, status="completed"
            )
        )

        # Build system prompt
        system_prompt = await self.system_prompt_builder.build_system_prompt(
            user, tool_schemas
        )

        # Enhance system prompt with LLM context enhancer. metadata carries
        # the per-request autolink_database_name (business routing) so schema
        # retrieval hits the same namespace that DDL import wrote to.
        if self.llm_context_enhancer and system_prompt is not None:
            system_prompt = await self.llm_context_enhancer.enhance_system_prompt(
                system_prompt, message, user, metadata=context_metadata
            )

        # Build LLM request
        request = await self._build_llm_request(
            conversation, tool_schemas, user, system_prompt
        )

        # Process with tool loop
        tool_iterations = 0

        while tool_iterations < self.config.max_tool_iterations:
            if self.config.include_thinking_indicators and tool_iterations == 0:
                # TODO: Yield thinking indicator
                pass

            # Get LLM response
            if self.config.stream_responses:
                response = await self._handle_streaming_response(request)
            else:
                response = await self._send_llm_request(request)

            # Handle tool calls
            if response.is_tool_call():
                tool_iterations += 1

                # First, add the assistant message with tool_calls to the conversation
                # This is required for OpenAI API - tool messages must follow assistant messages with tool_calls
                assistant_message = Message(
                    role="assistant",
                    content=response.content or "",  # Ensure content is not None
                    tool_calls=response.tool_calls,
                )
                conversation.add_message(assistant_message)

                if response.content is not None:
                    # Yield any partial content from the assistant before tool execution
                    yield UiComponent(
                        rich_component=RichTextComponent(
                            content=response.content, markdown=True
                        ),
                        simple_component=SimpleTextComponent(text=response.content),
                    )

                    # Update status to executing tools
                    yield UiComponent(  # type: ignore
                        rich_component=StatusBarUpdateComponent(
                            status="working",
                            message="Executing tools...",
                            detail=f"Running {len(response.tool_calls or [])} tools",
                        )
                    )

                # Collect all tool results first
                tool_results = []
                for i, tool_call in enumerate(response.tool_calls or []):
                    # Add task for this tool execution
                    tool_task = Task(
                        title=f"Execute {tool_call.name}",
                        description=f"Running tool with provided arguments",
                        status="in_progress",
                    )
                    yield UiComponent(  # type: ignore
                        rich_component=TaskTrackerUpdateComponent.add_task(tool_task)
                    )

                    response_str = response.content

                    # Use primitive StatusCard instead of semantic ToolExecutionComponent
                    tool_status_card = StatusCardComponent(
                        title=f"Executing {tool_call.name}",
                        status="running",
                        description=f"Running tool with {len(tool_call.arguments)} arguments",
                        icon="⚙️",
                        metadata=tool_call.arguments,
                    )

                    yield UiComponent(
                        rich_component=tool_status_card,
                        simple_component=SimpleTextComponent(text=response_str or ""),
                    )

                    # Run before_tool hooks
                    tool = await self.tool_registry.get_tool(tool_call.name)
                    if tool:
                        for hook in self.lifecycle_hooks:
                            await hook.before_tool(tool, context)

                    # Execute tool
                    result = await self.tool_registry.execute(tool_call, context)

                    # Run after_tool hooks
                    for hook in self.lifecycle_hooks:
                        modified_result = await hook.after_tool(result)
                        if modified_result is not None:
                            result = modified_result

                    # Update status card to show completion
                    final_status = "success" if result.success else "error"
                    final_description = (
                        f"Tool completed successfully"
                        if result.success
                        else f"Tool failed: {result.error or 'Unknown error'}"
                    )

                    yield UiComponent(
                        rich_component=tool_status_card.set_status(
                            final_status, final_description
                        ),
                        simple_component=SimpleTextComponent(text=final_description),
                    )

                    # Update tool task to completed
                    yield UiComponent(  # type: ignore
                        rich_component=TaskTrackerUpdateComponent.update_task(
                            tool_task.id,
                            status="completed",
                            detail=f"Tool {'completed successfully' if result.success else 'return an error'}",
                        )
                    )

                    # Yield tool result
                    if result.ui_component:
                        yield result.ui_component

                    # Collect tool result data
                    tool_results.append(
                        {
                            "tool_call_id": tool_call.id,
                            "content": (
                                result.result_for_llm
                                if result.success
                                else result.error or "Tool execution failed"
                            ),
                        }
                    )

                # Add tool responses to conversation
                # For APIs that need all tool results in one message, this helps
                for tool_result in tool_results:
                    tool_response_message = Message(
                        role="tool",
                        content=tool_result["content"],
                        tool_call_id=tool_result["tool_call_id"],
                    )
                    conversation.add_message(tool_response_message)

                # Rebuild request with tool responses
                request = await self._build_llm_request(
                    conversation, tool_schemas, user, system_prompt
                )
            else:
                # Update status to idle and set completion message
                yield UiComponent(  # type: ignore
                    rich_component=StatusBarUpdateComponent(
                        status="idle",
                        message="Response complete",
                        detail="Ready for next message",
                    )
                )

                # Update chat input placeholder
                yield UiComponent(  # type: ignore
                    rich_component=ChatInputUpdateComponent(
                        placeholder="Ask a follow-up question...", disabled=False
                    )
                )

                # Yield final text response
                if response.content:
                    # Add assistant response to conversation
                    conversation.add_message(
                        Message(role="assistant", content=response.content)
                    )
                    yield UiComponent(
                        rich_component=RichTextComponent(
                            content=response.content, markdown=True
                        ),
                        simple_component=SimpleTextComponent(text=response.content),
                    )
                break

        # Check if we hit the tool iteration limit
        if tool_iterations >= self.config.max_tool_iterations:
            # The loop exited due to hitting the limit, not due to a natural completion
            logger.warning(
                f"Tool iteration limit reached: {tool_iterations}/{self.config.max_tool_iterations}"
            )

            # Update status bar to show warning
            yield UiComponent(  # type: ignore
                rich_component=StatusBarUpdateComponent(
                    status="warning",
                    message="Tool limit reached",
                    detail=f"Stopped after {tool_iterations} tool executions. The task may be incomplete.",
                )
            )

            # Provide detailed warning message to user
            warning_message = f"""⚠️ **Tool Execution Limit Reached**

The agent stopped after executing {tool_iterations} tools (the configured maximum). The task may not be fully complete.

You can:
- Ask me to continue where I left off
- Adjust the `max_tool_iterations` setting if you need more tool calls
- Break the task into smaller steps"""

            yield UiComponent(
                rich_component=RichTextComponent(
                    content=warning_message, markdown=True
                ),
                simple_component=SimpleTextComponent(
                    text=f"Tool limit reached after {tool_iterations} executions. Task may be incomplete."
                ),
            )

            # Update chat input to suggest follow-up
            yield UiComponent(  # type: ignore
                rich_component=ChatInputUpdateComponent(
                    placeholder="Continue the task or ask me something else...",
                    disabled=False,
                )
            )

        # Save conversation if configured
        if self.config.auto_save_conversations:
            await self.conversation_store.update_conversation(conversation)

        # Run after_message hooks
        for hook in self.lifecycle_hooks:
            await hook.after_message(conversation)

    async def get_available_tools(self, user: User) -> List[ToolSchema]:
        """Get tools available to the user."""
        return await self.tool_registry.get_schemas()

    async def _build_llm_request(
        self,
        conversation: Conversation,
        tool_schemas: List[ToolSchema],
        user: User,
        system_prompt: Optional[str] = None,
    ) -> LlmRequest:
        """Build LLM request from conversation and tools."""
        # Apply conversation filters
        filtered_messages = conversation.messages
        for filter in self.conversation_filters:
            filtered_messages = await filter.filter_messages(filtered_messages)

        messages = []
        for msg in filtered_messages:
            llm_msg = LlmMessage(
                role=msg.role,
                content=msg.content,
                tool_calls=msg.tool_calls,
                tool_call_id=msg.tool_call_id,
            )
            messages.append(llm_msg)

        # Enhance messages with LLM context enhancer
        if self.llm_context_enhancer:
            messages = await self.llm_context_enhancer.enhance_user_messages(
                messages, user
            )

        return LlmRequest(
            messages=messages,
            tools=tool_schemas if tool_schemas else None,
            user=user,
            temperature=self.config.temperature,
            max_tokens=self.config.max_tokens,
            stream=self.config.stream_responses,
            system_prompt=system_prompt,
        )

    async def _send_llm_request(self, request: LlmRequest) -> LlmResponse:
        """Send LLM request with middleware."""
        # Apply before_llm_request middlewares
        for middleware in self.llm_middlewares:
            request = await middleware.before_llm_request(request)

        # Send request
        response = await self.llm_service.send_request(request)

        # Apply after_llm_response middlewares
        for middleware in self.llm_middlewares:
            response = await middleware.after_llm_response(request, response)

        return response

    async def _handle_streaming_response(self, request: LlmRequest) -> LlmResponse:
        """Handle streaming response from LLM."""
        # Apply before_llm_request middlewares
        for middleware in self.llm_middlewares:
            request = await middleware.before_llm_request(request)

        accumulated_content = ""
        accumulated_tool_calls = []

        async for chunk in self.llm_service.stream_request(request):
            if chunk.content:
                accumulated_content += chunk.content
                # Could yield intermediate TextChunk here

            if chunk.tool_calls:
                accumulated_tool_calls.extend(chunk.tool_calls)

        response = LlmResponse(
            content=accumulated_content if accumulated_content else None,
            tool_calls=accumulated_tool_calls if accumulated_tool_calls else None,
        )

        # Apply after_llm_response middlewares
        for middleware in self.llm_middlewares:
            response = await middleware.after_llm_response(request, response)

        return response
