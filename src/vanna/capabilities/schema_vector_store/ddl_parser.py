"""
DDL parser for the schema vector store ingestion pipeline.

Parses DDL statements (from a DDL.csv file or raw text) into structured
SchemaTable / SchemaRelation metadata using sqlparse, with dialect-tolerant
parsing (SQLite / PostgreSQL / MySQL / Spark) and per-table error isolation:
a table that fails to parse is skipped with a warning, the rest continue.
"""

import csv
import logging
import re
import sqlite3
from pathlib import Path
from typing import List, Optional, Tuple, Union

from .models import SchemaColumn, SchemaRelation, SchemaTable

logger = logging.getLogger(__name__)

# System tables that should never be ingested (AutoLink SKIP_TABLES semantics).
SKIP_TABLES = {
    "sqlite_sequence",
    "sqlite_master",
    "sqlite_stat1",
    "sqlite_stat4",
    "information_schema",
}

# Keywords that terminate a column's data type and start a constraint.
_CONSTRAINT_KEYWORDS = {
    "NOT",
    "NULL",
    "PRIMARY",
    "FOREIGN",
    "UNIQUE",
    "KEY",
    "REFERENCES",
    "DEFAULT",
    "CHECK",
    "CONSTRAINT",
    "AUTO_INCREMENT",
    "AUTOINCREMENT",
    "COLLATE",
    "COMMENT",
    "GENERATED",
    "IDENTITY",
    "ON",
    "AS",
    "ENCODE",
    "DISTKEY",
    "SORTKEY",
}

_CREATE_TABLE_RE = re.compile(
    r"CREATE\s+(?:TEMP\s+|TEMPORARY\s+|GLOBAL\s+|LOCAL\s+|EXTERNAL\s+)?"
    r"TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?",
    re.IGNORECASE,
)
_PRIMARY_KEY_RE = re.compile(r"^PRIMARY\s+KEY\s*\(([^)]*)\)", re.IGNORECASE)
_FOREIGN_KEY_RE = re.compile(
    r"^(?:CONSTRAINT\s+\S+\s+)?FOREIGN\s+KEY\s*\(([^)]*)\)\s*"
    r"REFERENCES\s+([\w.\"`\[\]]+)\s*(?:\(([^)]*)\))?",
    re.IGNORECASE,
)
_CONSTRAINT_PK_RE = re.compile(r"^CONSTRAINT\s+\S+\s+PRIMARY\s+KEY\s*\(([^)]*)\)", re.IGNORECASE)
_INLINE_REFERENCES_RE = re.compile(
    r"REFERENCES\s+([\w.\"`\[\]]+)\s*(?:\(([^)]*)\))?", re.IGNORECASE
)


def _strip_identifier(identifier: str) -> str:
    """Remove surrounding quoting (double quotes, backticks, brackets)."""
    identifier = identifier.strip()
    if len(identifier) >= 2:
        if identifier[0] == identifier[-1] and identifier[0] in ('"', "`"):
            return identifier[1:-1]
        if identifier.startswith("[") and identifier.endswith("]"):
            return identifier[1:-1]
    return identifier


def _split_create_table_statements(text: str) -> List[str]:
    """Split DDL text at each CREATE TABLE keyword outside string literals.

    Tolerant of missing semicolons and of stray semicolons inside
    parentheses: every CREATE TABLE keyword starts a new statement, so a
    broken table cannot swallow the next one.
    """
    starts: List[int] = []
    in_string = False
    quote_char = ""
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if in_string:
            if ch == quote_char:
                # Escaped quote ('' or "") does not end the literal.
                if i + 1 < n and text[i + 1] == quote_char:
                    i += 2
                    continue
                in_string = False
            i += 1
            continue
        if ch in ("'", '"'):
            in_string = True
            quote_char = ch
            i += 1
            continue
        if ch in ("c", "C") and text[i : i + 6].upper() == "CREATE":
            preceded_by_word = i > 0 and (
                text[i - 1].isalnum() or text[i - 1] in "_$"
            )
            if not preceded_by_word:
                boundary = re.match(
                    r"CREATE\s+(?:TEMP\s+|TEMPORARY\s+|GLOBAL\s+|LOCAL\s+|EXTERNAL\s+)?"
                    r"TABLE\b",
                    text[i:],
                    re.IGNORECASE,
                )
                if boundary:
                    starts.append(i)
                    i += boundary.end()
                    continue
        i += 1

    if not starts:
        return []
    statements = []
    for idx, start in enumerate(starts):
        end = starts[idx + 1] if idx + 1 < len(starts) else n
        statements.append(text[start:end])
    return statements


def _split_top_level(text: str) -> List[str]:
    """Split on commas that are not nested in parentheses or string literals."""
    parts: List[str] = []
    current: List[str] = []
    depth = 0
    in_string = False
    quote_char = ""
    i = 0
    while i < len(text):
        ch = text[i]
        if in_string:
            current.append(ch)
            if ch == quote_char:
                # Escaped quote ('' or "") ends with a doubled character.
                if i + 1 < len(text) and text[i + 1] == quote_char:
                    current.append(text[i + 1])
                    i += 1
                else:
                    in_string = False
            i += 1
            continue
        if ch in ("'", '"'):
            in_string = True
            quote_char = ch
            current.append(ch)
        elif ch == "(":
            depth += 1
            current.append(ch)
        elif ch == ")":
            depth -= 1
            current.append(ch)
        elif ch == "," and depth == 0:
            parts.append("".join(current).strip())
            current = []
        else:
            current.append(ch)
        i += 1
    tail = "".join(current).strip()
    if tail:
        parts.append(tail)
    return [p for p in parts if p]


def _extract_table_name(statement: str) -> Optional[str]:
    """Extract the table name from a CREATE TABLE statement."""
    match = _CREATE_TABLE_RE.search(statement)
    if not match:
        return None
    rest = statement[match.end():].lstrip()
    # Identifier may be schema-qualified and quoted in several dialects.
    ident_match = re.match(
        r'((?:[\w$]+\s*\.\s*)?(?:"[^"]+"|`[^`]+`|\[[^\]]+\]|[\w$]+))',
        rest,
    )
    if not ident_match:
        return None
    raw = ident_match.group(1)
    # Prefer the last component of schema-qualified names.
    parts = re.split(r"\s*\.\s*", raw)
    return _strip_identifier(parts[-1])


def _parse_column_definition(
    definition: str, table_name: str
) -> Optional[SchemaColumn]:
    """Parse a single column definition into a SchemaColumn."""
    match = re.match(
        r'^(\[[^\]]+\]|"[^"]+"|`[^`]+`|[\w$]+)\s*(.*)$',
        definition.strip(),
        re.DOTALL,
    )
    if not match:
        return None
    column_name = _strip_identifier(match.group(1))
    if not column_name:
        return None
    rest = match.group(2).strip()

    # Accumulate type tokens until a constraint keyword is reached.
    type_tokens: List[str] = []
    remaining = rest
    while remaining:
        if remaining.startswith("(") and type_tokens:
            # Type arguments, e.g. VARCHAR(50) / DECIMAL(10, 2).
            depth = 0
            end = -1
            for i, ch in enumerate(remaining):
                if ch == "(":
                    depth += 1
                elif ch == ")":
                    depth -= 1
                    if depth == 0:
                        end = i
                        break
            if end < 0:
                type_tokens.append(remaining)
                remaining = ""
            else:
                type_tokens.append(remaining[: end + 1])
                remaining = remaining[end + 1 :].strip()
            continue
        word_match = re.match(r"^([\w$]+)\s*(.*)$", remaining, re.DOTALL)
        if not word_match:
            break
        if word_match.group(1).upper() in _CONSTRAINT_KEYWORDS:
            break
        type_tokens.append(word_match.group(1))
        remaining = word_match.group(2).strip()

    data_type = " ".join(type_tokens).strip()
    # Normalize spacing around type arguments: "DECIMAL (10, 2)" -> "DECIMAL(10,2)".
    data_type = re.sub(r"\s*\(\s*", "(", data_type)
    data_type = re.sub(r"\s*\)\s*", ")", data_type)
    data_type = re.sub(r"\s*,\s*", ",", data_type)
    return SchemaColumn(
        column_name=column_name,
        table_name=table_name,
        data_type=data_type,
    )


class DdlParser:
    """Parser that turns DDL text (or DDL.csv rows) into schema metadata.

    The parser is tolerant: tables that fail to parse are skipped with a
    warning and do not affect the remaining tables.
    """

    def parse_csv(
        self,
        csv_path: Union[str, Path],
        database_name: str = "default",
    ) -> Tuple[List[SchemaTable], List[SchemaRelation]]:
        """Parse a DDL.csv file.

        The CSV may contain a header (e.g. database_id, table_name, ddl) or be
        headerless (one row per table). The DDL column is auto-detected as the
        field containing CREATE TABLE statements.

        Args:
            csv_path: Path to the DDL.csv file.
            database_name: Default database name when the CSV has none.

        Returns:
            (tables, relations) parsed from the file.
        """
        path = Path(csv_path)
        if not path.exists():
            logger.error(f"DDL.csv not found: {csv_path}")
            return [], []

        with open(path, newline="", encoding="utf-8") as f:
            rows = list(csv.reader(f))

        if not rows:
            return [], []

        first_row_lower = [cell.lower() for cell in rows[0]]
        has_create = any("create table" in cell.replace("  ", " ") for cell in first_row_lower)
        if has_create:
            # Headerless file: each row may hold a DDL statement.
            data_rows = rows
            fieldnames: Optional[List[str]] = None
        else:
            fieldnames = [name.strip() for name in rows[0]]
            data_rows = rows[1:]

        tables: List[SchemaTable] = []
        relations: List[SchemaRelation] = []

        for row in data_rows:
            if not any(cell.strip() for cell in row):
                continue
            if fieldnames and len(fieldnames) == len(row):
                record = dict(zip(fieldnames, row))
                ddl_texts = [
                    value.strip()
                    for value in record.values()
                    if value and "create table" in value.lower()
                ]
                db_name = (
                    next(
                        (
                            record[key].strip()
                            for key in (
                                "database_id",
                                "database",
                                "database_name",
                                "db",
                                "db_id",
                            )
                            if record.get(key, "").strip()
                        ),
                        database_name,
                    )
                )
                table_hint = next(
                    (
                        record[key].strip()
                        for key in ("table_name", "table", "table_fullname")
                        if record.get(key, "").strip()
                    ),
                    None,
                )
            else:
                # Headerless or ragged row: join cells and parse every statement.
                ddl_texts = [
                    "\n".join(row)
                ] if any("create table" in cell.lower() for cell in row) else []
                db_name = database_name
                table_hint = None

            for ddl_text in ddl_texts:
                parsed_tables, parsed_relations = self.parse_ddl(
                    ddl_text, database_name=db_name, table_name_hint=table_hint
                )
                tables.extend(parsed_tables)
                relations.extend(parsed_relations)

        return tables, relations

    def parse_ddl(
        self,
        ddl_text: str,
        database_name: str = "default",
        table_name_hint: Optional[str] = None,
    ) -> Tuple[List[SchemaTable], List[SchemaRelation]]:
        """Parse raw DDL text containing one or more CREATE TABLE statements.

        Args:
            ddl_text: DDL statements (separated by ';').
            database_name: Database name attached to parsed tables.
            table_name_hint: Optional expected table name (from CSV metadata).

        Returns:
            (tables, relations) parsed from the text.
        """
        tables: List[SchemaTable] = []
        relations: List[SchemaRelation] = []
        if not ddl_text or not ddl_text.strip():
            return tables, relations

        for text in _split_create_table_statements(ddl_text):
            text = text.strip().rstrip(";").strip()
            if not text:
                continue
            if not _CREATE_TABLE_RE.search(text):
                continue
            try:
                table, table_relations = self._parse_create_table(
                    text, database_name, table_name_hint
                )
            except Exception as e:  # noqa: BLE001 - per-table error isolation
                name = table_name_hint or _extract_table_name(text) or "<unknown>"
                logger.warning(f"Failed to parse DDL for table '{name}': {e}")
                continue
            if table is None:
                continue
            if table.table_name.lower() in SKIP_TABLES:
                logger.info(f"Skipping system table: {table.table_name}")
                continue
            tables.append(table)
            relations.extend(table_relations)

        return tables, relations

    def parse_sqlite_schema(
        self, connection: sqlite3.Connection, database_name: str = "default"
    ) -> Tuple[List[SchemaTable], List[SchemaRelation]]:
        """Convenience: parse schema DDL directly from a SQLite connection."""
        ddl_rows = connection.execute(
            "SELECT sql FROM sqlite_master WHERE sql IS NOT NULL"
        ).fetchall()
        ddl_text = ";\n".join(row[0] for row in ddl_rows)
        return self.parse_ddl(ddl_text, database_name=database_name)

    def _parse_create_table(
        self,
        statement: str,
        database_name: str,
        table_name_hint: Optional[str] = None,
    ) -> Tuple[Optional[SchemaTable], List[SchemaRelation]]:
        """Parse a single CREATE TABLE statement."""
        table_name = _extract_table_name(statement)
        if not table_name:
            if table_name_hint:
                table_name = table_name_hint
            else:
                raise ValueError("Could not extract table name from DDL")

        # Extract the parenthesized body of the statement.
        first_paren = statement.find("(")
        if first_paren < 0:
            raise ValueError(f"No column definitions found for table '{table_name}'")
        depth = 0
        last_paren = -1
        for i in range(first_paren, len(statement)):
            if statement[i] == "(":
                depth += 1
            elif statement[i] == ")":
                depth -= 1
                if depth == 0:
                    last_paren = i
                    break
        if last_paren < 0:
            raise ValueError(f"Unbalanced parentheses in DDL for table '{table_name}'")
        body = statement[first_paren + 1 : last_paren]

        columns: List[SchemaColumn] = []
        primary_keys: List[str] = []
        foreign_keys: List[dict] = []
        relations: List[SchemaRelation] = []

        for definition in _split_top_level(body):
            normalized = definition.strip()
            upper = normalized.upper()

            pk_match = _PRIMARY_KEY_RE.match(normalized) or _CONSTRAINT_PK_RE.match(
                normalized
            )
            if pk_match:
                pk_columns = [
                    _strip_identifier(col.strip())
                    for col in pk_match.group(1).split(",")
                    if col.strip()
                ]
                primary_keys.extend(pk_columns)
                continue

            fk_match = _FOREIGN_KEY_RE.match(normalized)
            if fk_match:
                fk_column = _strip_identifier(fk_match.group(1).strip())
                ref_table = _strip_identifier(fk_match.group(2).split(".")[-1])
                ref_column = (
                    _strip_identifier(fk_match.group(3).strip())
                    if fk_match.group(3)
                    else None
                )
                if fk_column and ref_table:
                    foreign_keys.append(
                        {
                            "column": fk_column,
                            "ref_table": ref_table,
                            "ref_column": ref_column,
                        }
                    )
                    relations.append(
                        SchemaRelation(
                            from_table=table_name,
                            from_column=fk_column,
                            to_table=ref_table,
                            to_column=ref_column
                            or (primary_keys[0] if primary_keys else "id"),
                            relation_type="fk",
                        )
                    )
                continue

            # Other table-level definitions to skip: UNIQUE / KEY / INDEX / CHECK.
            if re.match(
                r"^(?:CONSTRAINT\s+\S+\s+)?(UNIQUE|KEY|INDEX|CHECK|FULLTEXT|SPATIAL)\b",
                normalized,
                re.IGNORECASE,
            ):
                continue

            column = _parse_column_definition(normalized, table_name)
            if column is None:
                logger.warning(
                    f"Skipping unparsable column definition in table '{table_name}': "
                    f"{normalized[:80]}"
                )
                continue
            columns.append(column)

            # Inline PRIMARY KEY / REFERENCES constraints.
            if re.search(r"\bPRIMARY\s+KEY\b", normalized, re.IGNORECASE):
                primary_keys.append(column.column_name)
            inline_ref = _INLINE_REFERENCES_RE.search(normalized)
            if inline_ref:
                ref_table = _strip_identifier(inline_ref.group(1).split(".")[-1])
                ref_column = (
                    _strip_identifier(inline_ref.group(2).strip())
                    if inline_ref.group(2)
                    else None
                )
                foreign_keys.append(
                    {
                        "column": column.column_name,
                        "ref_table": ref_table,
                        "ref_column": ref_column,
                    }
                )
                relations.append(
                    SchemaRelation(
                        from_table=table_name,
                        from_column=column.column_name,
                        to_table=ref_table,
                        to_column=ref_column or "id",
                        relation_type="fk",
                    )
                )

        if not columns:
            raise ValueError(f"No columns parsed for table '{table_name}'")

        table = SchemaTable(
            table_name=table_name,
            database_name=database_name,
            columns=columns,
            primary_keys=primary_keys,
            foreign_keys=foreign_keys,
        )
        return table, relations
