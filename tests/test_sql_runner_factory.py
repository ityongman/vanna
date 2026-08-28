"""Tests for the database URL scheme -> SqlRunner factory."""
import sys
from unittest.mock import MagicMock

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


MSSQL_MODULE = "vanna.integrations.databases.relational.mssql.sql_runner"
ORACLE_MODULE = "vanna.integrations.databases.relational.oracle.sql_runner"
HIVE_MODULE = "vanna.integrations.databases.warehouse.hive.sql_runner"
PRESTO_MODULE = "vanna.integrations.databases.warehouse.presto.sql_runner"
CLICKHOUSE_MODULE = "vanna.integrations.databases.warehouse.clickhouse.sql_runner"


def _patch_runner(monkeypatch, module_path, class_name):
    """Patch a lazily-imported Runner class with a MagicMock and return it."""
    mock_cls = MagicMock()
    fake_module = MagicMock()
    setattr(fake_module, class_name, mock_cls)
    monkeypatch.setitem(sys.modules, module_path, fake_module)
    return mock_cls


def test_mssql_builds_odbc_conn_str(monkeypatch):
    mock_cls = _patch_runner(monkeypatch, MSSQL_MODULE, "MSSQLRunner")
    runner = create_sql_runner(
        "mssql://sa:pwd@dbhost:1433/master?driver=ODBC+Driver+18"
    )
    conn_str = mock_cls.call_args.kwargs["odbc_conn_str"]
    assert "DRIVER={ODBC Driver 18}" in conn_str
    assert "SERVER=dbhost,1433" in conn_str
    assert "DATABASE=master" in conn_str
    assert "UID=sa" in conn_str and "PWD=pwd" in conn_str
    assert runner is mock_cls.return_value


def test_mssql_trusted_connection_when_no_user(monkeypatch):
    mock_cls = _patch_runner(monkeypatch, MSSQL_MODULE, "MSSQLRunner")
    create_sql_runner("mssql://dbhost/master")
    conn_str = mock_cls.call_args.kwargs["odbc_conn_str"]
    assert "Trusted_Connection=yes" in conn_str
    assert "UID=" not in conn_str


def test_mssql_default_driver_when_no_query(monkeypatch):
    mock_cls = _patch_runner(monkeypatch, MSSQL_MODULE, "MSSQLRunner")
    create_sql_runner("mssql://sa:pwd@dbhost/master")
    assert "DRIVER={ODBC Driver 17 for SQL Server}" in mock_cls.call_args.kwargs["odbc_conn_str"]


def test_mssql_missing_host_raises(monkeypatch):
    with pytest.raises(ValueError, match="MSSQL URL is missing host"):
        create_sql_runner("mssql://sa:pwd@/master")


def test_oracle_dsn_format(monkeypatch):
    mock_cls = _patch_runner(monkeypatch, ORACLE_MODULE, "OracleRunner")
    create_sql_runner("oracle://scott:tiger@orahost:1521/orcl")
    kwargs = mock_cls.call_args.kwargs
    assert kwargs["user"] == "scott"
    assert kwargs["password"] == "tiger"
    assert kwargs["dsn"] == "orahost:1521/orcl"


def test_oracle_default_port_1521(monkeypatch):
    mock_cls = _patch_runner(monkeypatch, ORACLE_MODULE, "OracleRunner")
    create_sql_runner("oracle://scott:tiger@orahost/orcl")
    assert mock_cls.call_args.kwargs["dsn"] == "orahost:1521/orcl"


def test_hive_defaults(monkeypatch):
    mock_cls = _patch_runner(monkeypatch, HIVE_MODULE, "HiveRunner")
    create_sql_runner("hive://hivehost")
    kwargs = mock_cls.call_args.kwargs
    assert kwargs["host"] == "hivehost"
    assert kwargs["database"] == "default"
    assert kwargs["port"] == 10000


def test_hive_full_url(monkeypatch):
    mock_cls = _patch_runner(monkeypatch, HIVE_MODULE, "HiveRunner")
    create_sql_runner("hive://u:p@hivehost:10001/mydb")
    kwargs = mock_cls.call_args.kwargs
    assert kwargs["database"] == "mydb"
    assert kwargs["port"] == 10001
    assert kwargs["user"] == "u" and kwargs["password"] == "p"


def test_presto_catalog_schema_parsing(monkeypatch):
    mock_cls = _patch_runner(monkeypatch, PRESTO_MODULE, "PrestoRunner")
    create_sql_runner("presto://alice@prestohost:8080/tpch/tiny")
    kwargs = mock_cls.call_args.kwargs
    assert kwargs["catalog"] == "tpch"
    assert kwargs["schema"] == "tiny"
    assert kwargs["user"] == "alice"
    assert kwargs["port"] == 8080


def test_presto_defaults(monkeypatch):
    mock_cls = _patch_runner(monkeypatch, PRESTO_MODULE, "PrestoRunner")
    create_sql_runner("presto://prestohost")
    kwargs = mock_cls.call_args.kwargs
    assert kwargs["catalog"] == "hive"
    assert kwargs["schema"] == "default"
    assert kwargs["port"] == 443
    assert kwargs["protocol"] == "https"


def test_clickhouse_full_url(monkeypatch):
    mock_cls = _patch_runner(monkeypatch, CLICKHOUSE_MODULE, "ClickHouseRunner")
    create_sql_runner("clickhouse://default:secret@chhost:9440/default")
    kwargs = mock_cls.call_args.kwargs
    assert kwargs["host"] == "chhost"
    assert kwargs["port"] == 9440
    assert kwargs["user"] == "default" and kwargs["password"] == "secret"


def test_clickhouse_missing_password_raises():
    with pytest.raises(ValueError, match="missing required components"):
        create_sql_runner("clickhouse://default@chhost/default")


def test_mysql_missing_password_raises():
    with pytest.raises(ValueError, match="missing required components"):
        create_sql_runner("mysql://user@host/db")
