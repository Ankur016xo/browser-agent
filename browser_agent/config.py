"""
Configuration loading using stdlib tomllib with manual validation.
Environment variable overrides supported for key settings.
"""
import os
import sys
import tomllib
from pathlib import Path
from typing import Any


def _get_env_override(key: str, default: Any = None) -> Any:
    """Get environment variable override, with type conversion."""
    env_key = f"BROWSER_AGENT_{key.upper().replace('.', '_')}"
    value = os.environ.get(env_key)
    if value is None:
        return default
    # Try to convert to int, float, bool
    if value.lower() in ("true", "false"):
        return value.lower() == "true"
    try:
        if "." in value:
            return float(value)
        return int(value)
    except ValueError:
        return value


def _deep_merge(base: dict, override: dict) -> dict:
    """Deep merge override dict into base dict."""
    result = base.copy()
    for k, v in override.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = _deep_merge(result[k], v)
        else:
            result[k] = v
    return result


def load_config(config_path: str | Path | None = None) -> dict:
    """
    Load configuration from config.toml with environment variable overrides.

    Priority: defaults < config.toml < environment variables
    """
    # Default configuration
    config = {
        "ollama": {
            "url": "http://localhost:11434",
            "model": "qwen2.5vl:3b",
            "timeout": 30.0,
        },
        "browser": {
            "headless": False,
            "viewport_width": 1280,
            "viewport_height": 800,
            "start_url": "https://duckduckgo.com",
            "page_load_timeout": 2000,
            "step_wait_timeout": 1000,
        },
        "agent": {
            "max_steps": 10,
            "screenshot_path": "agent_screen.png",
            "screenshot_quality": 80,
        },
        "logging": {
            "level": "INFO",
            "format": "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        },
    }

    # Load from config.toml if exists
    if config_path is None:
        # Look for config.toml in current dir, then parent dirs
        current = Path.cwd()
        for path in [current, *current.parents]:
            candidate = path / "config.toml"
            if candidate.exists():
                config_path = candidate
                break

    if config_path and Path(config_path).exists():
        with open(config_path, "rb") as f:
            file_config = tomllib.load(f)
        config = _deep_merge(config, file_config)

    # Apply environment variable overrides
    env_overrides = {
        "ollama": {
            "url": _get_env_override("ollama.url"),
            "model": _get_env_override("ollama.model"),
            "timeout": _get_env_override("ollama.timeout"),
        },
        "browser": {
            "headless": _get_env_override("browser.headless"),
            "viewport_width": _get_env_override("browser.viewport_width"),
            "viewport_height": _get_env_override("browser.viewport_height"),
            "start_url": _get_env_override("browser.start_url"),
            "page_load_timeout": _get_env_override("browser.page_load_timeout"),
            "step_wait_timeout": _get_env_override("browser.step_wait_timeout"),
        },
        "agent": {
            "max_steps": _get_env_override("agent.max_steps"),
            "screenshot_path": _get_env_override("agent.screenshot_path"),
            "screenshot_quality": _get_env_override("agent.screenshot_quality"),
        },
        "logging": {
            "level": _get_env_override("logging.level"),
            "format": _get_env_override("logging.format"),
        },
    }

    # Filter out None values
    def _filter_none(d: dict) -> dict:
        return {k: v for k, v in d.items() if v is not None}

    env_overrides = {k: _filter_none(v) for k, v in env_overrides.items()}
    env_overrides = {k: v for k, v in env_overrides.items() if v}

    config = _deep_merge(config, env_overrides)

    return config


def validate_config(config: dict) -> dict:
    """Validate configuration values, raise ValueError if invalid."""
    # Validate ollama
    ollama = config.get("ollama", {})
    if not isinstance(ollama.get("url"), str) or not ollama["url"].startswith("http"):
        raise ValueError("ollama.url must be a valid HTTP URL")
    if not isinstance(ollama.get("model"), str) or not ollama["model"]:
        raise ValueError("ollama.model must be a non-empty string")
    if not isinstance(ollama.get("timeout"), (int, float)) or ollama["timeout"] <= 0:
        raise ValueError("ollama.timeout must be a positive number")

    # Validate browser
    browser = config.get("browser", {})
    if not isinstance(browser.get("headless"), bool):
        raise ValueError("browser.headless must be a boolean")
    for dim in ("viewport_width", "viewport_height"):
        val = browser.get(dim)
        if not isinstance(val, int) or val <= 0:
            raise ValueError(f"browser.{dim} must be a positive integer")
    if not isinstance(browser.get("start_url"), str) or not browser["start_url"].startswith("http"):
        raise ValueError("browser.start_url must be a valid HTTP URL")
    for timeout in ("page_load_timeout", "step_wait_timeout"):
        val = browser.get(timeout)
        if not isinstance(val, (int, float)) or val < 0:
            raise ValueError(f"browser.{timeout} must be a non-negative number")

    # Validate agent
    agent = config.get("agent", {})
    if not isinstance(agent.get("max_steps"), int) or agent["max_steps"] <= 0:
        raise ValueError("agent.max_steps must be a positive integer")
    if not isinstance(agent.get("screenshot_path"), str) or not agent["screenshot_path"]:
        raise ValueError("agent.screenshot_path must be a non-empty string")
    quality = agent.get("screenshot_quality")
    if not isinstance(quality, int) or not (1 <= quality <= 100):
        raise ValueError("agent.screenshot_quality must be an integer between 1 and 100")

    # Validate logging
    logging = config.get("logging", {})
    valid_levels = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")
    if logging.get("level") not in valid_levels:
        raise ValueError(f"logging.level must be one of {valid_levels}")
    if not isinstance(logging.get("format"), str):
        raise ValueError("logging.format must be a string")

    return config


# Global config instance (loaded once)
_config: dict | None = None


def get_config() -> dict:
    """Get global configuration (loads on first call)."""
    global _config
    if _config is None:
        _config = validate_config(load_config())
    return _config


def reset_config() -> None:
    """Reset global config (mainly for testing)."""
    global _config
    _config = None
