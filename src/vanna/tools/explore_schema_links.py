"""
Schema link exploration tool (AutoLink).

Lets the LLM actively explore database schema inside the tool-calling loop
(porting AutoLink's ``complete_schema.py`` exploration role): inspect a
table's columns, look up a column, or run a semantic search over the
ingested schema, with join conditions for the tables involved. The store
is accessed via ``ToolContext.schema_vector_store``, populated by the
Agent, so the tool stays backend-agnostic.
"""

import logging
from typing import TYPE_CHECKING, List, Optional, Type

from pydantic import BaseModel, Field

from vanna.core.tool import Tool, ToolContext, ToolResult
from vanna.components import StatusBarUpdateComponent, UiComponent

if TYPE_CHECKING:
    from vanna.capabilities.schema_vector_store import (
        SchemaColumn,
        SchemaRelation,
        SchemaVectorStore,
    )

logger = logging.getLogger(__name__)

# Generous top_k when enumerating a table's / column's occurrences.
_ENUMERATION_TOP_K = 50


class ExploreSchemaLinksParams(BaseModel):
    """Parameters for schema link exploration."""

    table_name: Optional[str] = Field(
        default=None,
        description="Explore the columns and join relationships of this table",
    )
    column_name: Optional[str] = Field(
        default=None,
        description="Look up a column by name (case-insensitive)",
    )
    search_query: Optional[str] = Field(
        default=None,
        description=(
            "Natural language question used to semantically retrieve the "
            "relevant schema columns"
        ),
    )


class ExploreSchemaLinksTool(Tool[ExploreSchemaLinksParams]):
    """Tool for exploring schema links via the SchemaVectorStore."""

    @property
    def name(self) -> str:
        return "explore_schema_links"

    @property
    def description(self) -> str:
        return (
            "Explore database schema links: retrieve the columns of a table, "
            "look up a column by name, or search the schema semantically; "
            "returns the matching columns and their join conditions"
        )

    def get_args_schema(self) -> Type[ExploreSchemaLinksParams]:
        return ExploreSchemaLinksParams

    async def execute(
        self, context: ToolContext, args: ExploreSchemaLinksParams
    ) -> ToolResult:
        """Explore the schema store and return a formatted subset."""
        store = context.schema_vector_store
        if store is None:
            message = (
                "Schema exploration is unavailable: no schema vector store "
                "is configured for this agent."
            )
            return ToolResult(
                success=False,
                result_for_llm=message,
                ui_component=self._status_component(
                    status="idle",
                    message="Schema exploration unavailable",
                    detail="No schema vector store configured",
                ),
                error="schema_vector_store is not configured",
            )

        if not (args.table_name or args.column_name or args.search_query):
            message = (
                "Provide at least one of table_name, column_name, or "
                "search_query to explore the schema."
            )
            return ToolResult(
                success=False,
                result_for_llm=message,
                ui_component=self._status_component(
                    status="idle",
                    message="Nothing to explore",
                    detail="Missing table_name / column_name / search_query",
                ),
                error="no exploration argument provided",
            )

        database_name = context.metadata.get("autolink_database_name", "default")

        try:
            columns, relations, summary = await self._explore(
                store, database_name, args
            )
        except Exception as e:  # noqa: BLE001 - degrade to a friendly error
            logger.warning(f"Schema exploration failed: {e}")
            message = (
                f"Schema exploration failed with an error: {e}. "
                "Try a different table_name, column_name, or search_query."
            )
            return ToolResult(
                success=False,
                result_for_llm=message,
                ui_component=self._status_component(
                    status="error",
                    message="Schema exploration failed",
                    detail=str(e),
                ),
                error=str(e),
            )

        if not columns:
            message = (
                f"No schema information found in database '{database_name}' "
                f"for {summary}."
            )
            return ToolResult(
                success=True,
                result_for_llm=message,
                ui_component=self._status_component(
                    status="idle",
                    message="No schema matches",
                    detail=summary,
                ),
            )

        result_text = self._format_result(database_name, columns, relations)
        return ToolResult(
            success=True,
            result_for_llm=result_text,
            ui_component=self._status_component(
                status="success",
                message=f"Explored {len(columns)} column(s)",
                detail=summary,
            ),
        )

    async def _explore(
        self,
        store: "SchemaVectorStore",
        database_name: str,
        args: ExploreSchemaLinksParams,
    ) -> tuple[List["SchemaColumn"], List["SchemaRelation"], str]:
        """Run the exploration and return (columns, relations, summary)."""
        if args.search_query:
            summary = f"search_query='{args.search_query}'"
            results = await store.search(
                query=args.search_query,
                database_name=database_name,
                top_k=_ENUMERATION_TOP_K,
            )
            columns = [r.column for r in results]
        elif args.table_name and args.column_name:
            summary = f"column '{args.table_name}.{args.column_name}'"
            column = await store.get_column_by_name(
                args.column_name, args.table_name, database_name
            )
            columns = [column] if column is not None else []
        elif args.table_name:
            summary = f"table_name='{args.table_name}'"
            results = await store.search(
                query=args.table_name,
                database_name=database_name,
                top_k=_ENUMERATION_TOP_K,
            )
            lowered = args.table_name.lower()
            columns = [
                r.column
                for r in results
                if r.column.table_name.lower() == lowered
            ]
        else:  # column_name only
            summary = f"column_name='{args.column_name}'"
            results = await store.search(
                query=args.column_name,
                database_name=database_name,
                top_k=_ENUMERATION_TOP_K,
            )
            lowered = args.column_name.lower()
            columns = [
                r.column
                for r in results
                if r.column.column_name.lower() == lowered
            ]

        # Deduplicate while preserving order.
        seen = set()
        unique_columns = []
        for column in columns:
            key = (column.table_name, column.column_name)
            if key not in seen:
                seen.add(key)
                unique_columns.append(column)
        columns = unique_columns

        relations: List["SchemaRelation"] = []
        if columns:
            table_names = list({c.table_name for c in columns})
            relations = await store.get_relations(table_names, database_name)

        return columns, relations, summary

    def _format_result(
        self,
        database_name: str,
        columns: List["SchemaColumn"],
        relations: List["SchemaRelation"],
    ) -> str:
        """Format the exploration result for the LLM."""
        lines = [f"Schema exploration results (database '{database_name}'):", ""]

        for column in columns:
            line = f"- {column.table_name}.{column.column_name} ({column.data_type})"
            if column.description:
                line += f": {column.description}"
            lines.append(line)

        if relations:
            lines.append("")
            lines.append("Join conditions:")
            for relation in relations:
                lines.append(
                    f"- {relation.from_table}.{relation.from_column} = "
                    f"{relation.to_table}.{relation.to_column}"
                )

        return "\n".join(lines)

    @staticmethod
    def _status_component(
        status: str, message: str, detail: str
    ) -> UiComponent:
        return UiComponent(
            rich_component=StatusBarUpdateComponent(
                status=status, message=message, detail=detail
            ),
            simple_component=None,
        )
