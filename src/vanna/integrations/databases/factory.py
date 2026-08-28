"""Database URL scheme -> SqlRunner factory.

Creates the appropriate SqlRunner implementation from a connection URL,
e.g. "sqlite:///Chinook.sqlite" -> SqliteRunner(database_path="Chinook.sqlite").
All Runner classes are imported lazily inside the handlers so importing
this module never triggers optional driver imports (pymysql, oracledb, ...).
"""

from typing import Any, Dict
from urllib.parse import parse_qsl, unquote, urlparse

from vanna.capabilities.sql_runner import SqlRunner

SUPPORTED_SCHEMES = [
    "sqlite",
    "duckdb",
    "mysql",
    "postgresql",
    "postgres",
    "mssql",
    "oracle",
    "clickhouse",
    "hive",
    "presto",
]


def _parse_url(url: str) -> Dict[str, Any]:
    """Parse a standard database URL into its components.

    Percent-encoding in user/password is decoded; query string becomes a dict.
    """
    parsed = urlparse(url)
    return {
        "host": parsed.hostname,
        "port": parsed.port,
        "user": unquote(parsed.username) if parsed.username else None,
        "password": unquote(parsed.password) if parsed.password else None,
        "database": parsed.path.lstrip("/"),
        "query": dict(parse_qsl(parsed.query)),
    }


def _file_path(url: str) -> str:
    """Extract the file path from sqlite/duckdb URLs.

    Convention (same as SQLAlchemy):
    - 3 slashes -> relative path: sqlite:///foo.db => "foo.db"
    - 4 slashes -> absolute path: sqlite:////abs/foo.db => "/abs/foo.db"
    """
    rest = url.split("://", 1)[1]
    if rest.startswith("//"):
        return rest[1:]
    return rest.lstrip("/")


def _create_sqlite(url: str) -> SqlRunner:
    from vanna.integrations.databases.relational.sqlite.sql_runner import (
        SqliteRunner,
    )

    return SqliteRunner(database_path=_file_path(url))


def _create_duckdb(url: str) -> SqlRunner:
    from vanna.integrations.databases.relational.duckdb.sql_runner import (
        DuckDBRunner,
    )

    return DuckDBRunner(database_path=_file_path(url))


def _create_mysql(url: str) -> SqlRunner:
    from vanna.integrations.databases.relational.mysql.sql_runner import (
        MySQLRunner,
    )

    p = _parse_url(url)
    missing = [
        k for k in ("host", "database", "user", "password") if not p[k]
    ]
    if missing:
        raise ValueError(
            f"MySQL URL is missing required components: {missing}. "
            "Expected format: mysql://user:password@host:3306/database"
        )
    return MySQLRunner(
        host=p["host"],
        database=p["database"],
        user=p["user"],
        password=p["password"],
        port=p["port"] or 3306,
    )


def _create_postgres(url: str) -> SqlRunner:
    from vanna.integrations.databases.relational.postgres.sql_runner import (
        PostgresRunner,
    )

    # psycopg accepts "postgresql://user:pwd@host:port/db" DSNs directly.
    return PostgresRunner(connection_string=url)


def _create_mssql(url: str) -> SqlRunner:
    from vanna.integrations.databases.relational.mssql.sql_runner import (
        MSSQLRunner,
    )

    p = _parse_url(url)
    driver = p["query"].get("driver", "ODBC Driver 17 for SQL Server")
    parts = [
        f"DRIVER={{{driver}}}",
        f"SERVER={p['host']},{p['port'] or 1433}",
        f"DATABASE={p['database']}",
    ]
    if p["user"]:
        parts += [f"UID={p['user']}", f"PWD={p['password'] or ''}"]
    else:
        parts.append("Trusted_Connection=yes")
    return MSSQLRunner(odbc_conn_str=";".join(parts))


def _create_oracle(url: str) -> SqlRunner:
    from vanna.integrations.databases.relational.oracle.sql_runner import (
        OracleRunner,
    )

    p = _parse_url(url)
    if not p["user"] or p["password"] is None or not p["host"]:
        raise ValueError(
            "Oracle URL is missing required components. "
            "Expected format: oracle://user:password@host:1521/sid"
        )
    dsn = f"{p['host']}:{p['port'] or 1521}/{p['database']}"
    return OracleRunner(user=p["user"], password=p["password"], dsn=dsn)


def _create_clickhouse(url: str) -> SqlRunner:
    from vanna.integrations.databases.warehouse.clickhouse.sql_runner import (
        ClickHouseRunner,
    )

    p = _parse_url(url)
    missing = [
        k for k in ("host", "database", "user", "password") if not p[k]
    ]
    if missing:
        raise ValueError(
            f"ClickHouse URL is missing required components: {missing}. "
            "Expected format: clickhouse://user:password@host:8123/database"
        )
    return ClickHouseRunner(
        host=p["host"],
        database=p["database"],
        user=p["user"],
        password=p["password"],
        port=p["port"] or 8123,
    )


def _create_hive(url: str) -> SqlRunner:
    from vanna.integrations.databases.warehouse.hive.sql_runner import (
        HiveRunner,
    )

    p = _parse_url(url)
    if not p["host"]:
        raise ValueError(
            "Hive URL is missing host. "
            "Expected format: hive://user:password@host:10000/database"
        )
    return HiveRunner(
        host=p["host"],
        database=p["database"] or "default",
        user=p["user"],
        password=p["password"],
        port=p["port"] or 10000,
    )


def _create_presto(url: str) -> SqlRunner:
    from vanna.integrations.databases.warehouse.presto.sql_runner import (
        PrestoRunner,
    )

    p = _parse_url(url)
    if not p["host"]:
        raise ValueError(
            "Presto URL is missing host. "
            "Expected format: presto://user@host:443/catalog/schema?protocol=https"
        )
    path_parts = [seg for seg in p["database"].split("/") if seg]
    catalog = path_parts[0] if path_parts else "hive"
    schema = path_parts[1] if len(path_parts) > 1 else "default"
    return PrestoRunner(
        host=p["host"],
        catalog=catalog,
        schema=schema,
        user=p["user"],
        password=p["password"],
        port=p["port"] or 443,
        protocol=p["query"].get("protocol", "https"),
    )


_HANDLERS = {
    "sqlite": _create_sqlite,
    "duckdb": _create_duckdb,
    "mysql": _create_mysql,
    "postgresql": _create_postgres,
    "postgres": _create_postgres,
    "mssql": _create_mssql,
    "oracle": _create_oracle,
    "clickhouse": _create_clickhouse,
    "hive": _create_hive,
    "presto": _create_presto,
}


def create_sql_runner(url: str) -> SqlRunner:
    """Create a SqlRunner from a database URL.

    Args:
        url: Database URL whose scheme selects the runner, e.g.
            "sqlite:///Chinook.sqlite".

    Returns:
        A SqlRunner instance for the given URL.

    Raises:
        ValueError: If the scheme is not supported. For engines with
            credential-file/project-based auth (BigQuery, Snowflake,
            Databricks), create the runner explicitly and pass it to
            ``Agent(sql_runner=...)``.
    """
    if "://" not in url:
        raise ValueError(
            f"Invalid database URL '{url}': no scheme found. "
            f"Supported schemes: {', '.join(SUPPORTED_SCHEMES)}"
        )
    scheme = url.split("://", 1)[0].lower()
    handler = _HANDLERS.get(scheme)
    if handler is None:
        raise ValueError(
            f"Unsupported database scheme '{scheme}'. "
            f"Supported schemes: {', '.join(SUPPORTED_SCHEMES)}. "
            "For other engines, create the runner explicitly and pass it "
            "via Agent(sql_runner=...)."
        )
    return handler(url)
