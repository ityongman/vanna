"""Tests for the database URL scheme -> SqlRunner factory."""
import pytest

from vanna.integrations.databases.factory import (
    SUPPORTED_SCHEMES,
    _parse_url,
    create_sql_runner,
)


def test_supported_schemes_contains_core_dbs():
    for scheme in ("sqlite", "mysql", "postgresql", "postgres", "mssql",
                   "oracle", "duckdb", "clickhouse", "hive", "presto"):
        assert scheme in SUPPORTED_SCHEMES


def test_sqlite_relative_path():
    runner = create_sql_runner("sqlite:///Chinook.sqlite")
    assert runner.database_path == "Chinook.sqlite"


def test_sqlite_absolute_path():
    runner = create_sql_runner("sqlite:////data/chinook.db")
    assert runner.database_path == "/data/chinook.db"


def test_duckdb_memory():
    # DuckDBRunner requires duckdb; skip if not installed
    pytest.importorskip("duckdb")
    runner = create_sql_runner("duckdb:///:memory:")
    assert runner.database_path == ":memory:"


def test_unknown_scheme_raises_with_supported_list():
    with pytest.raises(ValueError) as exc_info:
        create_sql_runner("mongodb://localhost/db")
    assert "sqlite" in str(exc_info.value)
    assert "create the runner explicitly" in str(exc_info.value)


def test_missing_scheme_raises():
    with pytest.raises(ValueError):
        create_sql_runner("not-a-url")


def test_parse_url_mysql():
    parsed = _parse_url("mysql://user:p%40ss@localhost:3307/chinook")
    assert parsed["host"] == "localhost"
    assert parsed["port"] == 3307
    assert parsed["user"] == "user"
    assert parsed["password"] == "p@ss"  # percent-decoded
    assert parsed["database"] == "chinook"


def test_parse_url_query_params():
    parsed = _parse_url("mssql://sa:pwd@host:1433/master?driver=ODBC+Driver+18")
    assert parsed["query"]["driver"] == "ODBC Driver 18"


def test_mysql_runner_created():
    # MySQLRunner requires pymysql; skip if not installed
    pytest.importorskip("pymysql")
    runner = create_sql_runner("mysql://user:pwd@localhost:3306/chinook")
    assert runner is not None
