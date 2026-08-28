"""Tests for AgentConfig database and auto-register settings."""
from vanna.core.agent.config import AgentConfig, DatabaseConfig


def test_database_config_defaults_to_none():
    config = AgentConfig()
    assert config.database is None


def test_database_config_accepts_url():
    config = AgentConfig(database=DatabaseConfig(url="sqlite:///Chinook.sqlite"))
    assert config.database.url == "sqlite:///Chinook.sqlite"


def test_auto_register_tools_defaults_true():
    assert AgentConfig().auto_register_tools is True


def test_auto_register_tools_can_disable():
    assert AgentConfig(auto_register_tools=False).auto_register_tools is False
