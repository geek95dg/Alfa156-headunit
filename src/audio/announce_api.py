"""Contract of a spoken announcement request (topic ``voice.announce``).

Producers (weather warnings now, TomTom traffic and the voice module later)
publish ONE request per message on :data:`TOPIC`; the future
``voice_announce`` module (Piper / espeak-ng, priority queue, ducking)
subscribes and speaks them. Nothing subscribes yet — publishing costs
nothing and the producers do not have to change when the speaker arrives.

Request (a dict, built only by :func:`make_request`)::

    {
      "id":         "<ms>-<n>"      unique across restarts,
      "category":   one of CATEGORIES (a per-category on/off in the speaker),
      "priority":   "low" | "normal" | "high"  (high may interrupt the queue),
      "text":       Polish, single line, at most MAX_TEXT characters —
                    written to be READ ALOUD (no "°C", no abbreviations),
      "key":        dedupe key ("" = none): a newer request with the same key
                    replaces a queued older one instead of queueing twice,
      "ts":         wall-clock time of the request,
      "expires_ts": not spoken after this (a warning queued behind a phone
                    call must not be read out an hour later),
    }

Why a separate tiny module: the text comes from network data (weather
descriptions, later traffic incidents) — it is cleaned here once, so the
speaker can pass it to a TTS process without trusting the producer, and the
consumer re-validates with :func:`validate_request` (the bus may carry
anything).
"""

from __future__ import annotations

import itertools
import math
import re
import time
from typing import Any, Optional

from src.core.notifications import clean_text

TOPIC = "voice.announce"
CATEGORIES = ("weather", "traffic", "system", "test")
PRIORITIES = ("low", "normal", "high")
MAX_TEXT = 240
MAX_KEY = 64
DEFAULT_TTL_S = 300.0
MAX_TTL_S = 3600.0
_KEY_RE = re.compile(r"^[a-z0-9_.:-]{1,64}$")
_ID_RE = re.compile(r"^[0-9]{1,16}-[0-9]{1,12}$")

_counter = itertools.count(1)


def _finite(value: Any) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        value = float(value)
    except (OverflowError, ValueError):
        return None
    return value if math.isfinite(value) else None


def make_request(category: str, text: str, *, priority: str = "normal",
                 key: Optional[str] = None, ttl_s: float = DEFAULT_TTL_S,
                 now: Optional[float] = None) -> Optional[dict]:
    """A valid request, or None (unknown category, empty text)."""
    if category not in CATEGORIES:
        return None
    text_s = clean_text(text, MAX_TEXT)
    if not text_s:
        return None
    now = time.time() if now is None else now
    ttl = _finite(ttl_s)
    ttl = DEFAULT_TTL_S if ttl is None else min(MAX_TTL_S, max(1.0, ttl))
    key_s = key.lower() if isinstance(key, str) and _KEY_RE.match(key.lower()) else ""
    return {
        "id": f"{int(now * 1000)}-{next(_counter)}",
        "category": category,
        "priority": priority if priority in PRIORITIES else "normal",
        "text": text_s,
        "key": key_s,
        "ts": now,
        "expires_ts": now + ttl,
    }


def validate_request(value: Any, now: Optional[float] = None) -> Optional[dict]:
    """A request from the bus re-checked field by field; None if invalid
    or already expired. The consumer's only way to read one."""
    if not isinstance(value, dict):
        return None
    now = time.time() if now is None else now
    ts, expires = _finite(value.get("ts")), _finite(value.get("expires_ts"))
    rid = value.get("id")
    if ts is None or expires is None or expires < now or expires - ts > MAX_TTL_S + 1:
        return None
    if not isinstance(rid, str) or not _ID_RE.match(rid):
        return None
    if value.get("category") not in CATEGORIES or value.get("priority") not in PRIORITIES:
        return None
    text = clean_text(value.get("text"), MAX_TEXT) if isinstance(value.get("text"), str) else ""
    if not text:
        return None
    key = value.get("key")
    key = key if isinstance(key, str) and _KEY_RE.match(key) else ""
    return {"id": rid, "category": value["category"], "priority": value["priority"],
            "text": text, "key": key, "ts": ts, "expires_ts": expires}


def request_announcement(event_bus: Any, category: str, text: str, *,
                         priority: str = "normal", key: Optional[str] = None,
                         ttl_s: float = DEFAULT_TTL_S,
                         now: Optional[float] = None) -> Optional[dict]:
    """Build and publish one request; returns it (None = nothing sent)."""
    if event_bus is None:
        return None
    req = make_request(category, text, priority=priority, key=key, ttl_s=ttl_s, now=now)
    if req is not None:
        event_bus.publish(TOPIC, req)
    return req
