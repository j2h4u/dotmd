"""Structured logging setup for dotMD."""

from __future__ import annotations

import logging
import sys

_FMT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
_DATEFMT = "%Y-%m-%d %H:%M:%S"


def _make_handler(level: int) -> logging.StreamHandler:
    h = logging.StreamHandler(sys.stderr)
    h.setLevel(level)
    h.setFormatter(logging.Formatter(_FMT, datefmt=_DATEFMT))
    return h


def setup_logging(verbose: bool = False) -> logging.Logger:
    """Configure consistent logging across dotMD and third-party loggers.

    Must be called *after* FastMCP is imported — FastMCP.__init__ installs a
    RichHandler on the root logger, which this function removes.
    """
    level = logging.DEBUG if verbose else logging.INFO

    # Root logger: uniform format for mcp/*, uvicorn/*, and anything else.
    # Clear existing handlers (removes RichHandler installed by FastMCP).
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(level)
    root.addHandler(_make_handler(level))

    # dotmd logger: own handler + propagate=False prevents double-logging via root.
    logger = logging.getLogger("dotmd")
    logger.handlers.clear()
    logger.setLevel(level)
    logger.propagate = False
    logger.addHandler(_make_handler(level))

    return logger
