"""Tests for AgentConfig database and auto-register settings."""
from vanna.core.agent.config import AgentConfig, DatabaseConfig


def test_database_config_defaults_to_none():
    config = AgentConfig()
    assert config.database is None


def test_database_config_accepts_url():
    config = AgentConfig(database=DatabaseConfig(url="sqlite:///Chinook.sqlite"))
    assert config.database.url == "sqlite:///Chinook.sqlite"
    assert config.database.to_url() == "sqlite:///Chinook.sqlite"


def test_database_config_legacy_url_wins_over_structured_fields():
    """A legacy url takes precedence so existing app.json keeps working."""
    db = DatabaseConfig(url="sqlite:///legacy.db", type="mysql", host="other")
    assert db.to_url() == "sqlite:///legacy.db"


def test_database_config_sqlite_structured_relative_path():
    db = DatabaseConfig(type="sqlite", path="data/db/a.db")
    assert db.to_url() == "sqlite:///data/db/a.db"


def test_database_config_sqlite_absolute_path_keeps_four_slashes():
    db = DatabaseConfig(type="sqlite", path="/var/db/a.db")
    assert db.to_url() == "sqlite:////var/db/a.db"


def test_database_config_duckdb_memory():
    assert DatabaseConfig(type="duckdb", path=":memory:").to_url() == "duckdb:///:memory:"


def test_database_config_server_assembles_url_with_default_port():
    db = DatabaseConfig(
        type="postgresql", host="db.internal", user="u", password="p", database="shop"
    )
    assert db.to_url() == "postgresql://u:p@db.internal:5432/shop"


def test_database_config_server_respects_explicit_port():
    db = DatabaseConfig(
        type="mysql", host="h", port=3307, user="u", password="p", database="d"
    )
    assert db.to_url() == "mysql://u:p@h:3307/d"


def test_database_config_percent_encodes_credentials():
    db = DatabaseConfig(
        type="mysql", host="h", user="user@corp", password="p@ss/wd", database="d"
    )
    assert db.to_url() == "mysql://user%40corp:p%40ss%2Fwd@h:3306/d"


def test_database_config_without_user_omits_auth():
    db = DatabaseConfig(type="mssql", host="h", database="master")
    assert db.to_url() == "mssql://h:1433/master"


def test_database_config_query_params_are_appended():
    db = DatabaseConfig(
        type="mssql",
        host="h",
        database="master",
        query={"driver": "ODBC Driver 18"},
    )
    assert db.to_url() == "mssql://h:1433/master?driver=ODBC%20Driver%2018"


def test_database_config_empty_yields_empty_url():
    """No url and no type -> empty, so the factory raises its own error."""
    assert DatabaseConfig().to_url() == ""


def test_auto_register_tools_defaults_true():
    assert AgentConfig().auto_register_tools is True


def test_auto_register_tools_can_disable():
    assert AgentConfig(auto_register_tools=False).auto_register_tools is False
