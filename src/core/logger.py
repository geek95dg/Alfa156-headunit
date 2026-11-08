"""Structured logging with per-module log levels."""

import contextlib
import functools
import logging
import logging.handlers
import sys
import time
from pathlib import Path
from typing import Optional, Union


_LOG_FORMAT = "%(asctime)s [%(levelname)-8s] %(name)-20s %(message)s"
_LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
_initialized = False

# Log file rotation defaults (system.log_max_mb / system.log_backups).
# The car has no buffered supply and a DEBUG log used to grow without
# bound on the root filesystem; 5 MB x (1 + 3 backups) caps it at ~20 MB.
DEFAULT_LOG_MAX_MB = 5
DEFAULT_LOG_BACKUPS = 3
_MAX_LOG_MAX_MB = 1024
_MAX_LOG_BACKUPS = 50


def _level_value(level: Union[str, int, None], fallback: int) -> int:
    """Map "DEBUG"/"info"/10 to a logging level; anything else → fallback."""
    if isinstance(level, bool):
        return fallback
    if isinstance(level, int):
        return level
    if isinstance(level, str):
        value = getattr(logging, level.strip().upper(), None)
        if isinstance(value, int):
            return value
    return fallback


def _sane_rotation(max_mb, backups) -> tuple[int, int]:
    """Validate rotation settings from YAML; bad values fall back to defaults.

    backupCount must be >= 1: with 0, RotatingFileHandler never actually
    rotates and the file keeps growing.
    """
    try:
        mb = float(max_mb)
        if isinstance(max_mb, bool) or not 0 < mb <= _MAX_LOG_MAX_MB:
            raise ValueError
    except (TypeError, ValueError):
        mb = DEFAULT_LOG_MAX_MB
    try:
        count = int(backups)
        if isinstance(backups, bool) or not 1 <= count <= _MAX_LOG_BACKUPS:
            raise ValueError
    except (TypeError, ValueError):
        count = DEFAULT_LOG_BACKUPS
    return int(mb * 1024 * 1024), count


class _FailSafeRotatingFileHandler(logging.handlers.RotatingFileHandler):
    """RotatingFileHandler that switches itself off after the first I/O error.

    With ``delay=True`` the file is only opened on the first record, so an
    unwritable log (root remounted read-only after an fsck error, disk full,
    permissions) surfaces in ``emit()``, not in setup_logging(). The stock
    ``handleError`` then prints a multi-line traceback to stderr for *every*
    record — under DEBUG that floods the size-capped journal, pushes the
    useful lines out and costs CPU. Instead: disable this handler, log one
    warning through the remaining handlers (console → journal keeps getting
    everything) and stay off until the next start.

    Errors that are not ``OSError`` (e.g. a bad %-format in one log call)
    are specific to that record and keep the stock behaviour — they must not
    switch file logging off.
    """

    _DISABLED_LEVEL = logging.CRITICAL + 1

    def handleError(self, record: logging.LogRecord) -> None:
        exc = sys.exc_info()[1]
        if not isinstance(exc, OSError):
            super().handleError(record)
            return
        if self.level >= self._DISABLED_LEVEL:
            return
        # Disable first: the warning below goes through the "bcm" logger,
        # and Logger.callHandlers skips a handler whose level is above the
        # record's — so it cannot come back here.
        self.setLevel(self._DISABLED_LEVEL)
        stream, self.stream = self.stream, None
        if stream is not None:
            with contextlib.suppress(Exception):
                stream.close()
        logging.getLogger("bcm.logger").warning(
            "Log file %s unavailable (%s) — file logging disabled until restart, "
            "console/journal only", self.baseFilename, exc)


def setup_logging(
    level: str = "INFO",
    log_file: Optional[str] = None,
    module_levels: Optional[dict[str, str]] = None,
    max_mb: float = DEFAULT_LOG_MAX_MB,
    backups: int = DEFAULT_LOG_BACKUPS,
) -> logging.Logger:
    """Initialize the BCM logging system.

    Args:
        level: Default log level (DEBUG, INFO, WARNING, ERROR, CRITICAL).
        log_file: Optional path to a log file. Parent dirs are created
                  automatically. The file rotates at ``max_mb`` megabytes,
                  keeping ``backups`` old copies (``bcm.log.1`` …).
        module_levels: Optional dict mapping module names (relative to the
                       "bcm" logger) to log levels, e.g.
                       {"multimedia.bluetooth": "DEBUG", "dashboard": "WARNING"}.
                       Invalid entries are ignored.
        max_mb: Rotation size of the log file in MB (system.log_max_mb).
        backups: Number of rotated files kept (system.log_backups).

    Returns:
        The root "bcm" logger.
    """
    global _initialized

    root_logger = logging.getLogger("bcm")
    numeric_level = _level_value(level, logging.INFO)
    root_logger.setLevel(numeric_level)

    if _initialized:
        return root_logger
    _initialized = True

    formatter = logging.Formatter(_LOG_FORMAT, datefmt=_LOG_DATE_FORMAT)

    # Console handler (journald captures stdout under systemd)
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(formatter)
    root_logger.addHandler(console)

    # File handler (optional). delay=True: the file is opened on the first
    # record, not at start-up. A log-file problem (read-only FS, full disk)
    # must not stop BCM — the journal still gets everything. Problems at
    # setup are caught below; problems at write time disable the handler
    # after one warning (_FailSafeRotatingFileHandler).
    if log_file:
        try:
            log_path = Path(log_file)
            log_path.parent.mkdir(parents=True, exist_ok=True)
            max_bytes, backup_count = _sane_rotation(max_mb, backups)
            file_handler = _FailSafeRotatingFileHandler(
                log_path, maxBytes=max_bytes, backupCount=backup_count,
                encoding="utf-8", delay=True,
            )
            file_handler.setFormatter(formatter)
            root_logger.addHandler(file_handler)
        except OSError as e:
            root_logger.warning("Log file %s unavailable (%s) — logging to stdout only",
                                log_file, e)

    # Per-module log levels
    if isinstance(module_levels, dict):
        for module_name, mod_level in module_levels.items():
            if not isinstance(module_name, str) or not module_name.strip():
                continue
            mod_logger = logging.getLogger(f"bcm.{module_name.strip()}")
            mod_logger.setLevel(_level_value(mod_level, numeric_level))

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
