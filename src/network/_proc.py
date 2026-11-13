"""Shared helpers for modules that drive command-line tools (nmcli, adb).

Why a separate module
---------------------
``phone_tether`` (Bluetooth PAN through nmcli) was the first module that
parses the output of system tools; ``car_phone`` (USB tethering, GPS forward
and battery of the phone in the car, through adb + nmcli) needs exactly the
same rules. Keeping one copy means one place where they are enforced:

* every command is an **argv list** with a **timeout** — never a shell, so
  nothing from the bus, the config or the device can turn into shell syntax;
* the tool runs with ``LC_ALL=C`` — its field values are compared, and a
  translated "połączono" would never equal "connected";
* running a tool **never raises**: a missing binary is exit 127 (and ONE
  warning, not one per pass of a 30 s loop), a hung one is exit 124, any
  other failure exit 1 — the caller turns those into a state, the worker
  thread keeps going;
* text that ends up in the UI or the log is cleaned of control characters
  and cut to :data:`ERROR_MAX` characters (``clean_error``);
* numbers from the config are validated and clamped (``_number``) — a typo
  in ``local.yaml`` must not become a zero-second busy loop.

Nothing here keeps state except the "already warned" set of :func:`_run`'s
default missing-binary warning.
"""

from __future__ import annotations

import ipaddress
import logging
import math
import os
import re
import subprocess
import threading
from typing import Any, Callable, Mapping, Optional, Sequence

from src.core.logger import get_logger

log = get_logger("network.proc")

#: Longest error text kept for the UI / log (one line).
ERROR_MAX = 200
#: Default timeout of a read-only probe (``nmcli -t …``, ``adb devices``).
PROBE_TIMEOUT_S = 8.0
#: Exit status reported when the binary does not exist (as a shell would).
RC_MISSING = 127
#: Exit status reported when the command hit its timeout (as ``timeout(1)``).
RC_TIMEOUT = 124
#: Exit status reported for an argv that is not a non-empty list of strings —
#: the runner is never called with it.
RC_BAD_ARGV = 2
#: Longest RAW stderr kept for a caller that parses it (``raw_stderr``).
RAW_STDERR_MAX = 4096
#: Kernel interface name (as reported for GENERAL.IP-IFACE).
IFACE_RE = re.compile(r"^[A-Za-z0-9_.-]{1,15}$")

_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]+")

# Default "binary missing" warning: once per program per process.
_missing_lock = threading.Lock()
_missing_warned: set[str] = set()


# ── text ───────────────────────────────────────────────────────────────────

def clean_error(text: Any) -> str:
    """One line, no control characters, at most :data:`ERROR_MAX` chars."""
    if not text:
        return ""
    s = _CONTROL_RE.sub(" ", str(text))
    s = " ".join(s.split())
    return s[:ERROR_MAX]


def split_terse(line: str) -> list[str]:
    """Split one ``nmcli -t`` line on *unescaped* ``:``.

    Terse output escapes ``:`` and ``\\`` inside values with a backslash —
    a Bluetooth device's name IS its address (``AA\\:BB\\:…``).
    """
    fields: list[str] = []
    cur: list[str] = []
    it = iter(line)
    for ch in it:
        if ch == "\\":
            nxt = next(it, "")
            cur.append(nxt)
        elif ch == ":":
            fields.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    fields.append("".join(cur))
    return fields


def parse_ip_status(text: str) -> dict[str, Any]:
    """``GENERAL.IP-IFACE,IP4.ADDRESS,IP4.GATEWAY`` → iface/ip/prefix/gateway.

    Parsed by content, not position, because a multi-address device prints
    ``a/24 | b/16`` on one line in some nmcli versions and one per line in
    others. Every value is validated — they end up in the UI.
    """
    status: dict[str, Any] = {"iface": "", "ip": "", "prefix": None, "gateway": ""}
    for line in (text or "").splitlines():
        for field in split_terse(line):
            for token in field.split("|"):
                token = token.strip()
                if not token or token == "--":
                    continue
                if "/" in token:
                    if status["ip"]:
                        continue
                    try:
                        iface = ipaddress.IPv4Interface(token)
                    except ValueError:
                        continue
                    status["ip"] = str(iface.ip)
                    status["prefix"] = iface.network.prefixlen
                    continue
                try:
                    gateway = ipaddress.IPv4Address(token)
                except ValueError:
                    if not status["iface"] and IFACE_RE.fullmatch(token):
                        status["iface"] = token
                    continue
                if not status["gateway"]:
                    status["gateway"] = str(gateway)
    return status


# ── config ─────────────────────────────────────────────────────────────────

def _cfg_get(config: Any, dotpath: str, default: Any = None) -> Any:
    """Read ``a.b.c`` from a BCMConfig (dotted ``get``) or nested dicts."""
    if config is None:
        return default
    getter = getattr(config, "get", None)
    if callable(getter):
        try:
            value = getter(dotpath)
        except Exception:
            value = None
        if value is not None:
            return value
    node = config
    for key in dotpath.split("."):
        if isinstance(node, dict) and key in node:
            node = node[key]
        else:
            return default
    return node


def _number(prefix: str, value: Any, default: float, lo: float, hi: float, name: str,
            logger: Optional[logging.Logger] = None) -> float:
    """A finite number within ``[lo, hi]`` (clamped), else ``default``.

    ``prefix`` is the config block the value came from
    (``network.phone_tether``) — the warning names the full key, so the
    driver knows which line of ``local.yaml`` to fix. ``bool`` is rejected on
    purpose: YAML turns ``yes`` into True, and True would pass as 1.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)) \
            or not math.isfinite(value):
        if value is not None:
            (logger or log).warning("%s.%s=%r is not a number — using %s",
                                    prefix, name, value, default)
        return default
    return min(max(value, lo), hi)


# ── running a tool ─────────────────────────────────────────────────────────

def proc_env(extra: Optional[Mapping[str, str]] = None) -> dict[str, str]:
    """Environment for a tool whose output we parse: untranslated (``LC_ALL=C``,
    no ``LANGUAGE``), plus ``extra`` (e.g. ``HOME`` for adb's key)."""
    env = dict(os.environ)
    env["LC_ALL"] = "C"
    env.pop("LANGUAGE", None)
    if extra:
        env.update(extra)
    return env


def _warn_missing_default(prog: str) -> None:
    with _missing_lock:
        if prog in _missing_warned:
            return
        _missing_warned.add(prog)
    log.warning("%s is not installed — the module that needs it stays idle", prog)


def _run(runner: Callable[..., Any], argv: Sequence[str],
         timeout: float = PROBE_TIMEOUT_S, *,
         env_extra: Optional[Mapping[str, str]] = None,
         on_missing: Optional[Callable[[str], None]] = None,
         raw_stderr: bool = False) -> tuple[int, str, str]:
    """Run one command. Never raises; returns ``(rc, stdout, cleaned stderr)``.

    Args:
        runner: ``subprocess.run`` compatible (the test seam).
        argv: the command as a list of strings — never a shell string. Anything
            else is refused with :data:`RC_BAD_ARGV` without calling ``runner``.
        timeout: seconds; a hung tool is killed and reported as
            :data:`RC_TIMEOUT`.
        env_extra: variables added to :func:`proc_env`.
        on_missing: called with the program name when the binary does not
            exist (:data:`RC_MISSING`); the caller logs its own warning ONCE.
            Without it a generic warning is logged once per program.
        raw_stderr: return stderr as the tool wrote it (lines kept, only cut
            to :data:`RAW_STDERR_MAX` characters) instead of cleaned. For a
            caller that PARSES stderr line by line — ``adb shell svc usb
            getFunctions`` prints its answer there, after whatever warnings
            the ROM's linker emits; joined into one 200-character line the
            answer would be lost. The caller must still pass any of it
            through :func:`clean_error` before it reaches the UI or the log.
    """
    if isinstance(argv, (str, bytes)) or not isinstance(argv, (list, tuple)) or not argv \
            or not all(isinstance(a, str) for a in argv):
        return RC_BAD_ARGV, "", "invalid command (expected a list of strings)"
    argv = list(argv)
    prog = argv[0]
    try:
        result = runner(argv, capture_output=True, text=True, errors="replace",
                        timeout=timeout, env=proc_env(env_extra))
    except FileNotFoundError:
        if on_missing is not None:
            try:
                on_missing(prog)
            except Exception:
                log.debug("on_missing callback failed", exc_info=True)
        else:
            _warn_missing_default(prog)
        return RC_MISSING, "", f"{prog} not installed"
    except subprocess.TimeoutExpired:
        return RC_TIMEOUT, "", f"{prog} timed out after {int(timeout)} s"
    except Exception as e:
        return 1, "", clean_error(f"{prog}: {e}")
    rc = getattr(result, "returncode", 1)
    out = getattr(result, "stdout", "") or ""
    err = getattr(result, "stderr", "") or ""
    if not isinstance(out, str):
        out = out.decode("utf-8", "replace") if isinstance(out, (bytes, bytearray)) else str(out)
    if not isinstance(err, str):
        err = err.decode("utf-8", "replace") if isinstance(err, (bytes, bytearray)) else str(err)
    # bool is an int subclass — a fake returning True must not read as rc 1.
    if isinstance(rc, bool) or not isinstance(rc, int):
        rc = 1
    if raw_stderr:
        return rc, out, err[:RAW_STDERR_MAX]
    return rc, out, clean_error(err)
