"""Generic SQL query execution tool with dependency injection."""

from typing import Any, Dict, List, Optional, Type, cast
import uuid
from vanna.core.tool import Tool, ToolContext, ToolResult
from vanna.components import (
    UiComponent,
    DataFrameComponent,
    NotificationComponent,
    ComponentType,
    SimpleTextComponent,
)
from vanna.capabilities.sql_runner import SqlRunner, RunSqlToolArgs
from vanna.capabilities.file_system import FileSystem
from vanna.integrations.local import LocalFileSystem


class RunSqlTool(Tool[RunSqlToolArgs]):
    """Tool that executes SQL queries using an injected SqlRunner implementation."""

    def __init__(
        self,
        sql_runner: Optional[SqlRunner] = None,
        file_system: Optional[FileSystem] = None,
        custom_tool_name: Optional[str] = None,
        custom_tool_description: Optional[str] = None,
    ):
        """Initialize the tool with an optional SqlRunner implementation.

        Args:
            sql_runner: Optional bound SqlRunner; per-request context.sql_runner
                (business routing) takes precedence at execution time. When both
                are None the tool reports a configuration error.
            file_system: FileSystem implementation for saving results (defaults to LocalFileSystem)
            custom_tool_name: Optional custom name for the tool (overrides default "run_sql")
            custom_tool_description: Optional custom description for the tool (overrides default description)
        """
        self.sql_runner = sql_runner
        self.file_system = file_system or LocalFileSystem()
        self._custom_name = custom_tool_name
        self._custom_description = custom_tool_description

    @property
    def name(self) -> str:
        return self._custom_name if self._custom_name else "run_sql"

    @property
    def description(self) -> str:
        return (
            self._custom_description
            if self._custom_description
            else "Execute SQL queries against the configured database"
        )

    def get_args_schema(self) -> Type[RunSqlToolArgs]:
        return RunSqlToolArgs

    async def execute(self, context: ToolContext, args: RunSqlToolArgs) -> ToolResult:
        """Execute a SQL query using the injected SqlRunner."""
        try:
            # SqlRunner 解析优先级（三层防线，每层语义清晰）：
            # 1. context.sql_runner —— 请求级路由（多业务模式）：
            #    Agent._send_message 按 business_id 惰性创建并注入
            #    （_get_or_create_sql_runner + ToolContext）。
            #    business_id 缺失/未匹配在进入工具前已被拦截报错，
            #    因此多业务请求走到这里时 context.sql_runner 必然有效。
            # 2. self.sql_runner —— 构造绑定（SDK 单库模式）：
            #    Agent.__init__ 从 config.database 派生的全局兜底。
            #    server 多业务启动时为 None（设计使然，非 bug）。
            # 3. 双 None —— 报配置错误，绝不静默执行。
            runner = context.sql_runner or self.sql_runner
            if runner is None:
                raise ValueError(
                    "run_sql: no SqlRunner available; the request carried no "
                    "business_id or the agent was built without a database"
                )
            df = await runner.run_sql(args, context)

            # Determine query type
            query_type = args.sql.strip().upper().split()[0]

            if query_type == "SELECT":
                # Handle SELECT queries with results
                if df.empty:
                    result = "Query executed successfully. No rows returned."
                    ui_component = UiComponent(
                        rich_component=DataFrameComponent(
                            rows=[],
                            columns=[],
                            title="Query Results",
                            description="No rows returned",
                        ),
                        simple_component=SimpleTextComponent(text=result),
                    )
                    metadata = {
                        "row_count": 0,
                        "columns": [],
                        "query_type": query_type,
                        "results": [],
                    }
                else:
                    # Convert DataFrame to records
                    results_data = df.to_dict("records")
                    columns = df.columns.tolist()
                    row_count = len(df)

                    # Write DataFrame to CSV file for downstream tools
                    file_id = str(uuid.uuid4())[:8]
                    filename = f"query_results_{file_id}.csv"
                    csv_content = df.to_csv(index=False)
                    await self.file_system.write_file(
                        filename, csv_content, context, overwrite=True
                    )

                    # Build result text for LLM.
                    # Small results are passed in full; large results are truncated
                    # on row boundaries (never mid-row) and the LLM is explicitly
                    # told the total row count plus how to fetch the rest, so it
                    # does not mistake the preview for the complete dataset.
                    preview_char_limit = 8000
                    if len(csv_content) <= preview_char_limit:
                        results_preview = csv_content
                    else:
                        # Truncate on row boundaries so every previewed row stays complete
                        lines = csv_content.splitlines(keepends=True)
                        header = lines[0] if lines else ""
                        preview_lines = [header]
                        char_count = len(header)
                        for line in lines[1:]:
                            if char_count + len(line) > preview_char_limit:
                                break
                            preview_lines.append(line)
                            char_count += len(line)
                        preview_rows = len(preview_lines) - 1
                        results_preview = (
                            "".join(preview_lines)
                            + f"\n(SHOWING ONLY FIRST {preview_rows} OF {row_count} ROWS. "
                            + "FOR LARGE RESULTS YOU DO NOT NEED TO SUMMARIZE THESE RESULTS OR PROVIDE OBSERVATIONS. THE NEXT STEP SHOULD BE A VISUALIZE_DATA CALL. "
                            + "TO SEE MORE ROWS, RUN THE QUERY AGAIN WITH LIMIT/OFFSET.)"
                        )

                    result = f"{results_preview}\n\nResults saved to file: {filename}\n\n**IMPORTANT: FOR VISUALIZE_DATA USE FILENAME: {filename}**"

                    # Create DataFrame component for UI
                    dataframe_component = DataFrameComponent.from_records(
                        records=cast(List[Dict[str, Any]], results_data),
                        title="Query Results",
                        description=f"SQL query returned {row_count} rows with {len(columns)} columns",
                    )

                    ui_component = UiComponent(
                        rich_component=dataframe_component,
                        simple_component=SimpleTextComponent(text=result),
                    )

                    metadata = {
                        "row_count": row_count,
                        "columns": columns,
                        "query_type": query_type,
                        "results": results_data,
                        "output_file": filename,
                    }
            else:
                # For non-SELECT queries (INSERT, UPDATE, DELETE, etc.)
                # The SqlRunner should return a DataFrame with affected row count
                rows_affected = len(df) if not df.empty else 0
                result = (
                    f"Query executed successfully. {rows_affected} row(s) affected."
                )

                metadata = {"rows_affected": rows_affected, "query_type": query_type}
                ui_component = UiComponent(
                    rich_component=NotificationComponent(
                        type=ComponentType.NOTIFICATION, level="success", message=result
                    ),
                    simple_component=SimpleTextComponent(text=result),
                )

            return ToolResult(
                success=True,
                result_for_llm=result,
                ui_component=ui_component,
                metadata=metadata,
            )

        except Exception as e:
            error_message = f"Error executing query: {str(e)}"
            return ToolResult(
                success=False,
                result_for_llm=error_message,
                ui_component=UiComponent(
                    rich_component=NotificationComponent(
                        type=ComponentType.NOTIFICATION,
                        level="error",
                        message=error_message,
                    ),
                    simple_component=SimpleTextComponent(text=error_message),
                ),
                error=str(e),
                metadata={"error_type": "sql_error"},
            )
