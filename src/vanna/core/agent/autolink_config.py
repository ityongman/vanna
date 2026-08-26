"""
AutoLink configuration.

Controls the AutoLink schema linking pipeline: retrieval of relevant schema
columns from a SchemaVectorStore and their injection into the LLM system
prompt. Disabled by default so existing behavior is unchanged unless the
pipeline is explicitly enabled.
"""

from pydantic import BaseModel, Field


class AutoLinkConfig(BaseModel):
    """Configuration for AutoLink schema linking.

    Defaults to disabled: set ``enabled=True`` and pass a ``SchemaVectorStore``
    to the ``Agent`` to turn the pipeline on.
    """

    enabled: bool = Field(
        default=False,
        description="Master switch for AutoLink schema linking",
    )
    database_name: str = Field(
        default="default",
        description="Database whose ingested schema is searched",
    )
    top_k: int = Field(
        default=20,
        gt=0,
        description="Number of relevant columns retrieved per question",
    )
    vector_store_backend: str = Field(
        default="faiss",
        description=(
            'Schema vector store backend selector: "faiss" (default, '
            'development), "chroma", "milvus", or "qdrant"'
        ),
    )
    include_relations: bool = Field(
        default=True,
        description=(
            "Inject join conditions (PK/FK relations) into the prompt and "
            "complete the columns on both sides of each relation"
        ),
    )
    heuristic_id_completion: bool = Field(
        default=True,
        description=(
            "Heuristic completion of *id/*name/*code columns when the store "
            "provides no PK/FK relations for the involved tables "
            "(AutoLink add_id fallback)"
        ),
    )
