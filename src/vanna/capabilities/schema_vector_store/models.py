"""
Schema vector store domain models.

These models describe database schema metadata (tables, columns, relations)
used by the AutoLink schema ingestion and retrieval pipeline.
"""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class SchemaColumn(BaseModel):
    """Metadata for a single database column."""

    column_name: str = Field(description="Name of the column")
    table_name: str = Field(description="Name of the table this column belongs to")
    data_type: str = Field(default="", description="Column data type (e.g. INTEGER)")
    description: Optional[str] = Field(
        default=None, description="Optional semantic description of the column"
    )
    sample_values: List[str] = Field(
        default_factory=list,
        description="Optional sampled values from the column",
    )


class SchemaTable(BaseModel):
    """Metadata for a database table."""

    table_name: str = Field(description="Name of the table")
    database_name: str = Field(
        default="default", description="Name of the database this table belongs to"
    )
    columns: List[SchemaColumn] = Field(
        default_factory=list, description="Columns of the table"
    )
    primary_keys: List[str] = Field(
        default_factory=list, description="Primary key column names"
    )
    foreign_keys: List[Dict[str, Any]] = Field(
        default_factory=list,
        description=(
            "Foreign key constraints as dicts: "
            "{'column', 'ref_table', 'ref_column'}"
        ),
    )


class SchemaRelation(BaseModel):
    """A relation between two columns (primary/foreign key)."""

    from_table: str = Field(description="Table containing the source column")
    from_column: str = Field(description="Source column name")
    to_table: str = Field(description="Table containing the target column")
    to_column: str = Field(description="Target column name")
    relation_type: str = Field(
        default="fk",
        description='Relation type: "pk" (self primary key) or "fk" (foreign key)',
    )


class SchemaSearchResult(BaseModel):
    """A single schema retrieval result."""

    column: SchemaColumn = Field(description="The matched column")
    similarity_score: float = Field(description="Similarity score (higher is better)")
    rank: int = Field(description="Rank of this result (1-based)")
