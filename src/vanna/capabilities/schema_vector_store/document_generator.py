"""
Column-level document generator for the schema vector store pipeline.

Generates one document per column (matching AutoLink's granularity), with
optional LLM-generated semantic descriptions and optional sample values.
When no description is available and LLM generation is disabled or fails,
documents degrade to plain column name + type (never blocking ingestion).
"""

import json
import logging
import re
from typing import TYPE_CHECKING, List, Optional, Tuple

from .models import SchemaColumn, SchemaRelation, SchemaTable

if TYPE_CHECKING:
    from vanna.core.llm import LlmService

logger = logging.getLogger(__name__)

_DOCUMENT_TEMPLATE = (
    "column name: {column}\n"
    "column type: {data_type}\n"
    "table name: {table}\n"
    "description: {description}"
)


class SchemaDocumentGenerator:
    """Generates column-level documents from schema tables.

    Description resolution priority per column:
      1. Explicit description provided on the SchemaColumn
      2. LLM-generated description (when an LlmService is provided and enabled)
      3. None - degrade to a plain column name + type document
    """

    def __init__(
        self,
        llm_service: Optional["LlmService"] = None,
        llm_description_enabled: bool = False,
    ):
        """Initialize the generator.

        Args:
            llm_service: Optional LlmService used to generate column
                descriptions for columns that lack one.
            llm_description_enabled: Whether LLM description generation is
                enabled. Has no effect when llm_service is None.
        """
        self.llm_service = llm_service
        self.llm_description_enabled = llm_description_enabled

    async def generate(
        self,
        tables: List[SchemaTable],
        relations: Optional[List[SchemaRelation]] = None,
    ) -> List[str]:
        """Generate column-level documents (one per column, in column order)."""
        pairs = await self.generate_column_documents(tables)
        return [text for _, text in pairs]

    async def generate_column_documents(
        self, tables: List[SchemaTable]
    ) -> List[Tuple[SchemaColumn, str]]:
        """Generate (column, document) pairs for every column of every table.

        Returns:
            Ordered list of (SchemaColumn, document_text) tuples.
        """
        # Collect columns missing a description up-front for batch LLM calls.
        missing: List[Tuple[SchemaTable, SchemaColumn]] = []
        for table in tables:
            for column in table.columns:
                if not column.description:
                    missing.append((table, column))

        if (
            missing
            and self.llm_service is not None
            and self.llm_description_enabled
        ):
            try:
                await self._generate_descriptions(missing)
            except Exception as e:  # noqa: BLE001 - degrade, never block
                logger.warning(
                    f"LLM column description generation failed, degrading to "
                    f"plain column/type documents: {e}"
                )

        pairs: List[Tuple[SchemaColumn, str]] = []
        for table in tables:
            for column in table.columns:
                pairs.append((column, self.format_column_document(column)))
        return pairs

    def format_column_document(self, column: SchemaColumn) -> str:
        """Format a single column document."""
        return _DOCUMENT_TEMPLATE.format(
            column=column.column_name,
            data_type=column.data_type,
            table=column.table_name,
            description=column.description or "",
        )

    async def _generate_descriptions(
        self, missing: List[Tuple[SchemaTable, SchemaColumn]]
    ) -> None:
        """Batch-generate descriptions for columns that lack one.

        Descriptions are written back onto the SchemaColumn objects so that
        subsequent formatting picks them up.
        """
        # Lazy imports avoid a circular import with vanna.core at module load.
        from vanna.core.llm import LlmMessage, LlmRequest
        from vanna.core.user import User

        description_user = User(
            id="schema_document_generator",
            email="system@vanna.local",
        )

        # Batch per table to keep prompts small and coherent.
        by_table: dict = {}
        for table, column in missing:
            by_table.setdefault(table.table_name, (table, []))[1].append(column)

        for table_name, (table, columns) in by_table.items():
            column_lines = "\n".join(
                f"- {c.column_name} ({c.data_type})" for c in columns
            )
            system_prompt = (
                "You are a database documentation assistant. Given a table name "
                "and a list of columns, write a short (one sentence) description "
                "for each column. Respond ONLY with a JSON object mapping each "
                "column name to its description string."
            )
            user_message = (
                f"Table: {table_name}\n"
                f"Columns:\n{column_lines}\n\n"
                'Respond as JSON, e.g. {{"column_name": "description"}}'
            )
            request = LlmRequest(
                messages=[LlmMessage(role="user", content=user_message)],
                user=description_user,
                system_prompt=system_prompt,
                temperature=0.1,
            )
            response = await self.llm_service.send_request(request)
            content = (response.content or "").strip()
            if not content:
                continue
            try:
                parsed = json.loads(self._extract_json(content))
            except (ValueError, json.JSONDecodeError):
                logger.warning(
                    f"Could not parse LLM descriptions for table '{table_name}'; "
                    "degrading to plain column/type documents"
                )
                continue
            if not isinstance(parsed, dict):
                continue
            for column in columns:
                description = parsed.get(column.column_name)
                if isinstance(description, str) and description.strip():
                    column.description = description.strip()

    @staticmethod
    def _extract_json(content: str) -> str:
        """Extract a JSON object from an LLM response (strip code fences)."""
        fence_match = re.search(r"```(?:json)?\s*(.*?)\s*```", content, re.DOTALL)
        if fence_match:
            return fence_match.group(1)
        brace_start = content.find("{")
        brace_end = content.rfind("}")
        if brace_start >= 0 and brace_end > brace_start:
            return content[brace_start : brace_end + 1]
        return content
