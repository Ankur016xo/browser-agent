"""
Lightweight logging setup using Python standard library logging.
"""
import logging
import sys
from browser_agent.config import get_config


def setup_logging() -> logging.Logger:
    """Configure and return the root logger based on config."""
    config = get_config()
    log_config = config["logging"]

    level = getattr(logging, log_config["level"])
    fmt = log_config["format"]

    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    if hasattr(sys.stderr, "reconfigure"):
        try:
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    # Clear existing handlers
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    # Console handler
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(level)
    handler.setFormatter(logging.Formatter(fmt))
    root_logger.addHandler(handler)

    # Reduce noise from third-party loggers
    logging.getLogger("playwright").setLevel(logging.WARNING)
    logging.getLogger("ollama").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)

    return root_logger


def get_logger(name: str) -> logging.Logger:
    """Get a logger for a specific module."""
    return logging.getLogger(name)