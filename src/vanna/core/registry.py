"""
Tool registry for the Vanna Agents framework.

This module provides the ToolRegistry class for managing and executing tools.
"""

import time
from typing import TYPE_CHECKING, Any, Dict, List, Optional, TypeVar, Union

from .tool import Tool, ToolCall, ToolContext, ToolRejection, ToolResult, ToolSchema

if TYPE_CHECKING:
    from .audit import AuditLogger
    from .agent.config import AuditConfig
    from .user import User

T = TypeVar("T")


class ToolRegistry:
    """Registry for managing tools."""

    def __init__(
        self,
        audit_logger: Optional["AuditLogger"] = None,
        audit_config: Optional["AuditConfig"] = None,
    ) -> None:
        self._tools: Dict[str, Tool[Any]] = {}
        self.audit_logger = audit_logger
        if audit_config is not None:
            self.audit_config = audit_config
        else:
            from .agent.config import AuditConfig

            self.audit_config = AuditConfig()

    def register(self, tool: Tool[Any]) -> None:
        """Register a tool.

        Args:
            tool: The tool to register

        Raises:
            ValueError: If a tool with the same name is already registered
        """
        if tool.name in self._tools:
            raise ValueError(f"Tool '{tool.name}' already registered")
        self._tools[tool.name] = tool

    async def get_tool(self, name: str) -> Optional[Tool[Any]]:
        """Get a tool by name."""
        return self._tools.get(name)

    async def list_tools(self) -> List[str]:
        """List all registered tool names."""
        return list(self._tools.keys())

    async def get_schemas(self) -> List[ToolSchema]:
        """Get schemas for all registered tools."""
        return [tool.get_schema() for tool in self._tools.values()]

    async def transform_args(
        self,
        tool: Tool[T],
        args: T,
        user: "User",
        context: ToolContext,
    ) -> Union[T, ToolRejection]:
        """Transform and validate tool arguments based on user context.

        This method allows per-user transformation of tool arguments, such as:
        - Applying row-level security (RLS) to SQL queries
        - Scoping options based on user metadata
        - Validating required arguments are present
        - Redacting sensitive fields

        The default implementation performs no transformation (NoOp).
        Subclasses can override this method to implement custom transformation logic.

        Args:
            tool: The tool being executed
            args: Already Pydantic-validated arguments
            user: The user executing the tool
            context: Full execution context

        Returns:
            Either:
            - Transformed arguments (may be unchanged if no transformation needed)
            - ToolRejection with explanation of why args were rejected
        """
        return args  # Default: no transformation (NoOp)

    async def execute(
        self,
        tool_call: ToolCall,
        context: ToolContext,
    ) -> ToolResult:
        """Execute a tool call with validation."""
        tool = await self.get_tool(tool_call.name)
        if not tool:
            msg = f"Tool '{tool_call.name}' not found"
            return ToolResult(
                success=False,
                result_for_llm=msg,
                ui_component=None,
                error=msg,
            )

        # Validate and parse arguments
        try:
            args_model = tool.get_args_schema()
            validated_args = args_model.model_validate(tool_call.arguments)
        except Exception as e:
            msg = f"Invalid arguments: {str(e)}"
            return ToolResult(
                success=False,
                result_for_llm=msg,
                ui_component=None,
                error=msg,
            )

        # Transform/validate arguments based on user context
        transform_result = await self.transform_args(
            tool=tool,
            args=validated_args,
            user=context.user,
            context=context,
        )

        if isinstance(transform_result, ToolRejection):
            return ToolResult(
                success=False,
                result_for_llm=transform_result.reason,
                ui_component=None,
                error=transform_result.reason,
            )

        # Use transformed arguments for execution
        final_args = transform_result

        # Audit tool invocation
        if (
            self.audit_logger
            and self.audit_config
            and self.audit_config.log_tool_invocations
        ):
            await self.audit_logger.log_tool_invocation(
                user=context.user,
                tool_call=tool_call,
                context=context,
                sanitize_parameters=self.audit_config.sanitize_tool_parameters,
            )

        # Execute tool with context-first signature
        try:
            start_time = time.perf_counter()
            result = await tool.execute(context, final_args)
            execution_time_ms = (time.perf_counter() - start_time) * 1000

            # Add execution time to metadata
            result.metadata["execution_time_ms"] = execution_time_ms

            # Audit tool result
            if (
                self.audit_logger
                and self.audit_config
                and self.audit_config.log_tool_results
            ):
                await self.audit_logger.log_tool_result(
                    user=context.user,
                    tool_call=tool_call,
                    result=result,
                    context=context,
                )

            return result
        except Exception as e:
            msg = f"Execution failed: {str(e)}"
            return ToolResult(
                success=False,
                result_for_llm=msg,
                ui_component=None,
                error=msg,
            )