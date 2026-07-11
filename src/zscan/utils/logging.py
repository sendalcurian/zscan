"""Logging configuration for zscan.

This module provides consistent logging setup across the package.
"""

from __future__ import annotations

import logging
from pathlib import Path

from rich.logging import RichHandler


def setup_logging(
    level: int = logging.INFO,
    log_file: str | Path | None = None,
    rich_tracebacks: bool = True,
) -> None:
    """Configure logging for zscan.

    Sets up console logging with Rich formatting and optional file output.

    Args:
        level: Logging level (default: INFO).
        log_file: Optional path to a log file.
        rich_tracebacks: Whether to use Rich tracebacks (default: True).
    """
    # Clear existing handlers
    root = logging.getLogger()
    root.handlers.clear()

    # Console handler with Rich
    console_handler = RichHandler(
        rich_tracebacks=rich_tracebacks,
        show_path=False,
        markup=True,
    )
    console_handler.setLevel(level)

    # Format
    fmt = "%(message)s"
    datefmt = "[%X]"
    console_handler.setFormatter(logging.Formatter(fmt, datefmt=datefmt))
    root.addHandler(console_handler)

    # File handler if specified
    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)

        file_handler = logging.FileHandler(log_path)
        file_handler.setLevel(level)
        file_fmt = "%(asctime)s | %(name)s | %(levelname)s | %(message)s"
        file_handler.setFormatter(logging.Formatter(file_fmt))
        root.addHandler(file_handler)

    root.setLevel(level)


def get_logger(name: str) -> logging.Logger:
    """Get a logger instance for a module.

    Args:
        name: Logger name (typically __name__).

    Returns:
        Configured Logger instance.
    """
    return logging.getLogger(name)
