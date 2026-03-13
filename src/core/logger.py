"""Structured logging with per-module log levels."""

import logging
import sys
from pathlib import Path
from typing import Optional


_LOG_FORMAT = "%(asctime)s [%(levelname)-8s] %(name)-20s %(message)s"
_LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
_initialized = False


def setup_logging(
    level: str = "INFO",
    log_file: Optional[str] = None,
    module_levels: Optional[dict[str, str]] = None,
) -> logging.Logger:
    """Initialize the BCM logging system.

    Args:
        level: Default log level (DEBUG, INFO, WARNING, ERROR, CRITICAL).
        log_file: Optional path to a log file. Parent dirs are created automatically.
        module_levels: Optional dict mapping module names to log levels,
                       e.g. {"bcm.obd": "DEBUG", "bcm.dashboard": "WARNING"}.

    Returns:
        The root "bcm" logger.
    """
    global _initialized

    root_logger = logging.getLogger("bcm")
    numeric_level = getattr(logging, level.upper(), logging.INFO)
    root_logger.setLevel(numeric_level)

    if _initialized:
        return root_logger
    _initialized = True

    formatter = logging.Formatter(_LOG_FORMAT, datefmt=_LOG_DATE_FORMAT)

    # Console handler
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(formatter)
    root_logger.addHandler(console)

    # File handler (optional)
    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_path)
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)

    # Per-module log levels
    if module_levels:
        for module_name, mod_level in module_levels.items():
            mod_logger = logging.getLogger(f"bcm.{module_name}")
            mod_logger.setLevel(getattr(logging, mod_level.upper(), numeric_level))

    return root_logger


def get_logger(module_name: str) -> logging.Logger:
    """Get a child logger under the bcm namespace.

    Usage:
        log = get_logger("obd")       # returns logger "bcm.obd"
        log = get_logger("dashboard")  # returns logger "bcm.dashboard"
    """
    return logging.getLogger(f"bcm.{module_name}")
