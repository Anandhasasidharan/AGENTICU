from __future__ import annotations

import copy
import os
from pathlib import Path
from typing import Any

import yaml

DEFAULT_CONFIG_PATH = Path("config.yaml")

DEFAULT_CONFIG: dict[str, Any] = {
    "agenticu": {
        "storage": {
            "dsn": "postgresql://localhost:5432/agenticu",
            "pool_size": 10,
            "max_overflow": 20,
        },
        "collector": {
            "otlp_endpoint": "http://localhost:4317",
            "batch_size": 100,
            "flush_interval_seconds": 5,
        },
        "classifier": {
            "enabled": True,
            "fast_path_only": False,
            "model_name": "sentence-transformers/all-MiniLM-L6-v2",
            "similarity_threshold": 0.75,
        },
        "recovery": {
            "auto_recover": True,
            "max_retries": 2,
            "escalate_after": 2,
            "cooldown_seconds": 30,
        },
        "escalation": {
            "slack_webhook": "",
            "pagerduty_key": "",
            "pagerduty_service_id": "",
        },
        "api": {
            "host": "0.0.0.0",
            "port": 8000,
            "cors_origins": ["http://localhost:3000"],
            "api_key": "",
        },
    }
}


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    cfg: dict[str, Any] = copy.deepcopy(DEFAULT_CONFIG)
    path = path or os.environ.get("AGENTICU_CONFIG", str(DEFAULT_CONFIG_PATH))
    p = Path(path)
    if p.exists():
        with open(p) as f:
            overrides = yaml.safe_load(f) or {}
        _deep_merge(cfg, overrides)
    for key in os.environ:
        if key.startswith("AGENTICU_") and key != "AGENTICU_CONFIG":
            env_key = key.removeprefix("AGENTICU_").lower().lstrip("_")
            _set_from_env(cfg.setdefault("agenticu", {}), env_key, os.environ[key])
    return cfg


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> None:
    for key, value in override.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value


def _set_from_env(cfg: dict[str, Any], env_key: str, value: str) -> None:
    parts = env_key.split("__")
    target = cfg
    for part in parts[:-1]:
        target = target.setdefault(part, {})
    key = parts[-1]
    existing = target.get(key)
    target[key] = _coerce(value, existing)


def _coerce(value: str, existing: Any) -> Any:
    """Coerce an env-var string to the type of the existing default value."""
    if isinstance(existing, bool):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    if isinstance(existing, int):
        try:
            return int(value)
        except ValueError:
            return value
    if isinstance(existing, float):
        try:
            return float(value)
        except ValueError:
            return value
    if existing is None:
        return _infer(value)
    return value


def _infer(value: str) -> Any:
    """Infer a type for an env var that has no matching default."""
    low = value.strip().lower()
    if low in {"true", "false"}:
        return low == "true"
    for cast in (int, float):
        try:
            return cast(value)
        except ValueError:
            pass
    return value
