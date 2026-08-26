"""
AutoLink schema enhancement for LLM context.

Retrieves the schema columns most relevant to the user's question from a
SchemaVectorStore and injects them (plus join conditions) into the system
prompt. This ports AutoLink's ``retrieve_topk_schema.py`` retrieval logic;
key-column completion prefers DDL-parsed PK/FK relations and falls back to
the ``add_id.py`` heuristics (*id / *name / *code) only when no relations
are available.

Every failure degrades silently to the original prompt (warning log only),
never blocking the conversation.
"""

import logging
from typing import TYPE_CHECKING, Dict, List, Optional, Tuple

from ..agent.autolink_config import AutoLinkConfig
from .base import LlmContextEnhancer
from vanna.capabilities.schema_vector_store import SchemaRelation

if TYPE_CHECKING:
    from ..user.models import User
    from ..llm.models import LlmMessage
    from ...capabilities.schema_vector_store import SchemaColumn, SchemaVectorStore

logger = logging.getLogger(__name__)

# Column-name suffixes that hint at a referenced entity (AutoLink add_id).
_HEURISTIC_SUFFIXES = ("_id", "_name", "_code")

_RELATION_SECTION_HEADER = "Join conditions (from foreign keys):"
_INFERRED_SECTION_HEADER = "Possible join conditions (inferred, verify before use):"


def _heuristic_base(column_name: str) -> Optional[str]:
    """Return the referenced-entity base noun for *id/*name/*code columns.

    ``customer_id`` -> ``customer``; ``id`` itself returns ``None``.
    """
    lowered = column_name.lower()
    for suffix in _HEURISTIC_SUFFIXES:
        if lowered.endswith(suffix) and len(lowered) > len(suffix):
            return column_name[: -len(suffix)]
    return None


def _plural_candidates(base: str) -> List[str]:
    """Guess referenced table names from a base noun (customer -> customer/customers)."""
    return [base, base + "s", base + "es"]


class AutoLinkSchemaEnhancer(LlmContextEnhancer):
    """Injects relevant schema columns into the system prompt (AutoLink).

    Note:
        The enhancer itself does not check ``AutoLinkConfig.enabled`` —
        constructing it directly expresses the intent to enhance. The
        ``Agent`` checks the flag when deciding whether to add it to the
        enhancer chain.
    """

    def __init__(
        self,
        schema_vector_store: Optional["SchemaVectorStore"] = None,
        config: Optional[AutoLinkConfig] = None,
    ):
        """Initialize with a schema vector store and optional settings.

        Args:
            schema_vector_store: Store searched for relevant columns. When
                ``None``, enhancement is a no-op.
            config: Optional settings (top_k, database_name, relations,
                heuristics). Defaults to ``AutoLinkConfig()``.
        """
        self.schema_vector_store = schema_vector_store
        self.config = config if config is not None else AutoLinkConfig()

    async def enhance_system_prompt(
        self, system_prompt: str, user_message: str, user: "User"
    ) -> str:
        """Enhance the system prompt with schema context for the question."""
        if self.schema_vector_store is None:
            return system_prompt
        if not user_message or not user_message.strip():
            return system_prompt

        try:
            section = await self._build_schema_section(user_message)
        except Exception as e:  # noqa: BLE001 - degrade, never block
            logger.warning(
                f"AutoLink schema enhancement failed, using original prompt: {e}"
            )
            return system_prompt

        if not section:
            return system_prompt
        return system_prompt + section

    async def enhance_user_messages(
        self, messages: list["LlmMessage"], user: "User"
    ) -> list["LlmMessage"]:
        """User messages are not modified by schema enhancement."""
        return messages

    async def _build_schema_section(self, user_message: str) -> str:
        """Retrieve relevant columns and format the prompt section."""
        results = await self.schema_vector_store.search(
            query=user_message,
            database_name=self.config.database_name,
            top_k=self.config.top_k,
        )
        if not results:
            return ""

        columns: Dict[Tuple[str, str], "SchemaColumn"] = {}
        for result in results:
            column = result.column
            columns.setdefault((column.table_name, column.column_name), column)

        relations: List[SchemaRelation] = []
        inferred: List[SchemaRelation] = []
        if self.config.include_relations:
            relations, inferred = await self._complete_key_columns(columns)

        return self._format_section(columns, relations, inferred)

    async def _complete_key_columns(
        self, columns: Dict[Tuple[str, str], "SchemaColumn"]
    ) -> Tuple[List[SchemaRelation], List[SchemaRelation]]:
        """Key-column completion (AutoLink add_id semantics).

        PK/FK relations take priority: both sides of every relation touching
        the retrieved tables are completed via ``get_column_by_name``. Only
        when the store returns no relations at all does the *id/*name/*code
        heuristic run. Returns ``(relations, inferred_relations)``.
        """
        table_names = sorted({table for table, _name in columns})
        relations = await self.schema_vector_store.get_relations(
            table_names, self.config.database_name
        )

        if relations:
            for relation in relations:
                for table_name, column_name in (
                    (relation.from_table, relation.from_column),
                    (relation.to_table, relation.to_column),
                ):
                    if (table_name, column_name) in columns:
                        continue
                    column = await self.schema_vector_store.get_column_by_name(
                        column_name, table_name, self.config.database_name
                    )
                    if column is not None:
                        columns[(table_name, column_name)] = column
            return relations, []

        inferred: List[SchemaRelation] = []
        if not self.config.heuristic_id_completion:
            return [], inferred

        seen: set = set()
        for (table_name, column_name), _column in list(columns.items()):
            base = _heuristic_base(column_name)
            if base is None:
                continue
            for candidate_table in _plural_candidates(base):
                ref = await self.schema_vector_store.get_column_by_name(
                    "id", candidate_table, self.config.database_name
                )
                if ref is None:
                    continue
                if (candidate_table, "id") not in columns:
                    columns[(candidate_table, "id")] = ref
                # Only *_id columns assert a join; *_name/*code columns just
                # surface the referenced table's id for the LLM to consider.
                if column_name.lower().endswith("_id"):
                    key = (table_name, column_name, candidate_table, "id")
                    if key not in seen:
                        seen.add(key)
                        inferred.append(
                            SchemaRelation(
                                from_table=table_name,
                                from_column=column_name,
                                to_table=candidate_table,
                                to_column="id",
                                relation_type="fk",
                            )
                        )
                break
        return [], inferred

    def _format_section(
        self,
        columns: Dict[Tuple[str, str], "SchemaColumn"],
        relations: List[SchemaRelation],
        inferred: List[SchemaRelation],
    ) -> str:
        """Format the retrieved schema as a system prompt section."""
        tables: Dict[str, List["SchemaColumn"]] = {}
        for (_table_name, _column_name), column in columns.items():
            tables.setdefault(column.table_name, []).append(column)

        lines = [
            "",
            "## Relevant Schema Context (AutoLink)",
            "",
            "The following database schema columns are the most relevant to "
            "the user's question:",
            "",
        ]
        for table_name, table_columns in tables.items():
            lines.append(f"Table: {table_name}")
            for column in table_columns:
                line = f"- {column.column_name} ({column.data_type})"
                if column.description:
                    line += f": {column.description}"
                lines.append(line)
            lines.append("")

        if relations:
            lines.append(_RELATION_SECTION_HEADER)
            for relation in relations:
                lines.append(
                    f"- {relation.from_table}.{relation.from_column} = "
                    f"{relation.to_table}.{relation.to_column}"
                )
            lines.append("")

        if inferred:
            lines.append(_INFERRED_SECTION_HEADER)
            for relation in inferred:
                lines.append(
                    f"- {relation.from_table}.{relation.from_column} = "
                    f"{relation.to_table}.{relation.to_column}"
                )
            lines.append("")

        return "\n".join(lines)
