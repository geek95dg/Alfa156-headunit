"""Structured logging with per-module log levels."""

import functools
import logging
import sys
import time
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


def log_call(logger: logging.Logger):
    """Decorator that logs function entry, exit, duration, and exceptions.

    Usage:
        log = get_logger("multimedia.bluetooth")

        @log_call(log)
        def connect(self, address):
            ...
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            # Build argument summary (skip 'self')
            call_args = []
            start_idx = 1 if args and hasattr(args[0], '__class__') else 0
            for a in args[start_idx:]:
                call_args.append(repr(a)[:50])
            for k, v in kwargs.items():
                call_args.append(f"{k}={repr(v)[:50]}")
            arg_str = ", ".join(call_args)

            logger.debug("%s(%s) called", func.__name__, arg_str)
            t0 = time.monotonic()
            try:
                result = func(*args, **kwargs)
                elapsed = (time.monotonic() - t0) * 1000
                logger.debug("%s(%s) returned %s (%.1fms)",
                             func.__name__, arg_str,
                             repr(result)[:80], elapsed)
                return result
            except Exception as exc:
                elapsed = (time.monotonic() - t0) * 1000
                logger.error("%s(%s) raised %s: %s (%.1fms)",
                             func.__name__, arg_str,
                             type(exc).__name__, exc, elapsed)
                raise
        return wrapper
    return decorator
