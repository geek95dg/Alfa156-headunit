"""Short user notifications for the dashboard (topic ``system.notifications``).

web_viewer has always put ``system.notifications`` into the dashboard
payload (``notifications``), but nothing ever published that topic, so the
kiosk had no way to tell the driver "this did not work, and why". This is
the single publisher: a small, bounded list of short-lived entries, which
the kiosk shows as toasts (web/js/components/notifications.js).

Entry: ``{id, key, severity, icon, title, desc, ts, ttl}``. ``id`` is unique
across BCM restarts (the kiosk page may outlive one) so the UI can show each
entry exactly once; ``key`` deduplicates (a repeated message replaces the old
entry instead of filling the list). Text is sanitised here because the UI
must never have to trust it — and it renders it with textContent anyway.
"""

from __future__ import annotations

import itertools
import re
import threading
import time
from typing import Any, Optional

TOPIC = "system.notifications"
MAX_ENTRIES = 5
DEFAULT_TTL_S = 8.0
MAX_TTL_S = 60.0
_MAX_TITLE = 80
_MAX_DESC = 200
_MAX_KEY = 64
SEVERITIES = ("info", "warning", "danger")
_ICON_RE = re.compile(r"^[a-z0-9_]{1,40}$")
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f-\x9f​-‏ -‮⁦-⁩]")

_lock = threading.Lock()
_counter = itertools.count(1)


def clean_text(value: Any, limit: int) -> str:
    """Printable, single-line, at most ``limit`` characters."""
    text = _CONTROL_RE.sub(" ", str(value if value is not None else ""))
    text = " ".join(text.split())
    return text[:limit]


def _expired(entry: dict, now: float) -> bool:
    try:
        return float(entry.get("ts", 0)) + float(entry.get("ttl", 0)) < now
    except (TypeError, ValueError):
        return True


def active_notifications(value: Any, now: Optional[float] = None) -> list[dict]:
    """The not-yet-expired entries of a ``system.notifications`` value.

    Never raises; anything that is not a list of dicts yields ``[]``. Used by
    web_viewer so the payload does not keep stale entries forever (the topic
    is only republished when something new is announced).
    """
    if not isinstance(value, list):
        return []
    now = time.time() if now is None else now
    return [e for e in value if isinstance(e, dict) and not _expired(e, now)][-MAX_ENTRIES:]


def publish_notification(event_bus: Any, title: str, desc: str = "", *,
                         severity: str = "warning", icon: str = "info",
                         ttl: float = DEFAULT_TTL_S, key: Optional[str] = None,
                         now: Optional[float] = None) -> Optional[dict]:
    """Announce one notification; returns the entry (None without a bus).

    Thread-safe: the read-modify-publish of the list happens under one lock,
    so two modules announcing at once cannot drop each other's entry.
    """
    if event_bus is None:
        return None
    now = time.time() if now is None else now
    try:
        ttl = min(MAX_TTL_S, max(1.0, float(ttl)))
    except (TypeError, ValueError):
        ttl = DEFAULT_TTL_S
    key_s = clean_text(key, _MAX_KEY) if key else ""
    entry = {
        "id": f"{int(now * 1000)}-{next(_counter)}",
        "key": key_s,
        "severity": severity if severity in SEVERITIES else "info",
        "icon": icon if isinstance(icon, str) and _ICON_RE.match(icon) else "info",
        "title": clean_text(title, _MAX_TITLE),
        "desc": clean_text(desc, _MAX_DESC),
        "ts": now,
        "ttl": ttl,
    }
    with _lock:
        last = event_bus.get_last(TOPIC)
        current = active_notifications(last[0] if last else [], now)
        if key_s:
            current = [e for e in current if e.get("key") != key_s]
        entries = (current + [entry])[-MAX_ENTRIES:]
        event_bus.publish(TOPIC, entries)
    return entry
