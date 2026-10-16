from __future__ import annotations

import os
from pathlib import Path

import pytest

from agenticu.api.config import load_config


@pytest.fixture(autouse=True)
def _clear_env():
    for key in list(os.environ):
        if key.startswith("AGENTICU_"):
            del os.environ[key]


def test_default_config():
    cfg = load_config(path="/nonexistent/config.yaml")
    assert cfg["agenticu"]["api"]["host"] == "0.0.0.0"
    assert cfg["agenticu"]["api"]["port"] == 8000
    assert cfg["agenticu"]["api"]["cors_origins"] == ["http://localhost:3000"]


def test_env_override_port_is_coerced_to_int():
    os.environ["AGENTICU__API__PORT"] = "9000"
    cfg = load_config(path="/nonexistent/config.yaml")
    assert cfg["agenticu"]["api"]["port"] == 9000


def test_env_override_bool_and_numeric_types():
    os.environ["AGENTICU__CLASSIFIER__ENABLED"] = "false"
    os.environ["AGENTICU__CLASSIFIER__SIMILARITY_THRESHOLD"] = "0.9"
    os.environ["AGENTICU__RECOVERY__MAX_RETRIES"] = "7"
    cfg = load_config(path="/nonexistent/config.yaml")
    clf = cfg["agenticu"]["classifier"]
    assert clf["enabled"] is False
    assert clf["similarity_threshold"] == 0.9
    assert cfg["agenticu"]["recovery"]["max_retries"] == 7


def test_defaults_are_not_mutated_between_loads(tmp_path: Path):
    cfg_file = tmp_path / "c.yaml"
    cfg_file.write_text("agenticu:\n  api:\n    port: 3000\n")
    load_config(path=str(cfg_file))
    cfg = load_config(path="/nonexistent/config.yaml")
    assert cfg["agenticu"]["api"]["port"] == 8000


def test_config_path_env_var_is_not_a_nested_override():
    os.environ["AGENTICU_CONFIG"] = "/nonexistent/config.yaml"
    cfg = load_config()
    assert "config" not in cfg["agenticu"]


def test_env_deep_override():
    os.environ["AGENTICU__STORAGE__DSN"] = "postgresql://test:test@host:5432/db"
    cfg = load_config(path="/nonexistent/config.yaml")
    assert cfg["agenticu"]["storage"]["dsn"] == "postgresql://test:test@host:5432/db"


def test_file_loading(tmp_path: Path):
    cfg_file = tmp_path / "test_config.yaml"
    cfg_file.write_text("agenticu:\n  api:\n    port: 3000\n")
    cfg = load_config(path=str(cfg_file))
    assert cfg["agenticu"]["api"]["port"] == 3000


def test_classifier_defaults():
    cfg = load_config(path="/nonexistent/config.yaml")
    clf = cfg["agenticu"]["classifier"]
    assert clf["enabled"] is True
    assert clf["fast_path_only"] is False
    assert clf["similarity_threshold"] == 0.75
