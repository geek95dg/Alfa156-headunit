"""Module ``weather_alerts``: weather warnings while driving.

Runs the pure rule engine (src/weather/alerts.py) over:

* ``weather.current`` — unless it is demo data ("Milan, IT" before the
  first real fetch must never warn about anything) or older than
  :data:`CURRENT_MAX_AGE_S` (offline for hours: no "teraz" from stale data),
  or — with a GPS fix — fetched more than 30 km from the car (a city
  searched on A4 is not "teraz" for the driver);
* the 3-hour slots at the car's position — ``WeatherManager.forecast_at``
  for "now" and every 3 h up to ``lookahead_h`` (the manager answers from
  its own slots when the car is within 30 km of them, else one cached,
  rate-limited request per 0.1° cell). Without a GPS fix: the manager's
  slots as they are (the default city, or a searched one — said in docs);
* the route ahead when a destination is set (``trip.route`` waypoints with
  their ETA, minus the time since the plan) — "na trasie".

Publishes:

* ``weather.alert`` — the active alerts (list, most severe first; [] when
  none) — A4 strip, the top-bar icon, small_viewer;
* ``system.notifications`` through publish_notification (key
  ``weather_<kind>``, the toast replaces an older one of the same kind) —
  only when :class:`~src.weather.alerts.AlertAnnouncer` says so (new,
  escalated, or after ``cooldown_min``);
* ``voice.announce`` (src/audio/announce_api.py, category ``weather``) for
  warnings and dangers outside ``quiet_hours`` (a danger is spoken even
  then). Nothing speaks it until the voice module (stage 6) exists.

The kiosk icing popup (app.js _checkIcingAlert) stays disabled at the
owner's request: the warning is a toast + voice only.

Needs ``modules.weather`` (catalog ``requires``). If the weather module is
somehow not running anyway, ``weather._internals`` never appears: the
module logs ONE warning and keeps evaluating ``weather.current`` only.
"""

from __future__ import annotations

import math
import threading
import time
from typing import Any, Callable, Optional

from src.audio import announce_api
from src.core.logger import get_logger
from src.core.notifications import publish_notification
from src.weather import alerts as engine
from src.weather.weather import NEAR_KM, _distance_km, _plausible_fix, valid_coords

log = get_logger("weather.alerts")

TOPIC = "weather.alert"
#: Re-evaluate at least this often (expiry, ETA along the route, cooldowns);
#: new weather / a new route wake the loop sooner.
EVAL_INTERVAL_S = 300.0
#: weather.current older than this is not "teraz" any more.
CURRENT_MAX_AGE_S = 2 * 3600.0
#: "It rained recently" for the 0 °C crossing rule.
RECENT_RAIN_S = 3 * 3600.0
#: Route points used at most (the planner samples 8).
ROUTE_POINTS_MAX = 8
#: A plan older than this is not "the route ahead" any more.
ROUTE_MAX_AGE_S = 12 * 3600.0
_TTL_BY_SEVERITY = {"info": 10.0, "warning": 20.0, "danger": 30.0}
_PRIORITY_BY_SEVERITY = {"info": "low", "warning": "normal", "danger": "high"}
_ICON_BY_KIND = {"icing": "ac_unit", "snow": "weather_snowy", "rain": "rainy",
                 "storm": "thunderstorm", "wind": "air", "fog": "foggy"}


class WeatherAlerts:
    """Runtime of the warnings (thread, bus, announcements)."""

    def __init__(self, event_bus, config=None, *,
                 clock: Callable[[], float] = time.monotonic,
                 wall: Callable[[], float] = time.time,
                 localtime: Callable[[float], Any] = time.localtime):
        self._bus = event_bus
        raw = config.get("weather_alerts", {}) if config is not None else {}
        self.cfg = engine.load_config(raw, warn=log.warning)
        self._announcer = engine.AlertAnnouncer(self.cfg, clock=clock)
        self._clock = clock
        self._wall = wall
        self._localtime = localtime
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._last_rain_mono: Optional[float] = None
        self._published: Optional[list] = None
        self._published_key: Optional[list] = None
        self._warned_no_manager = False
        self._lock = threading.Lock()

    # ── lifecycle ──────────────────────────────────────────────────────
    def start(self) -> None:
        # Wake on weather.lon, not weather.current: WeatherManager publishes
        # current → … → lat → lon, so waking on current could pair a searched
        # city's weather with the OLD coordinates and pass the 30 km check.
        self._bus.subscribe("weather.lon", self._on_change)
        self._bus.subscribe("trip.route", self._on_change)
        self._thread = threading.Thread(target=self._run, name="weather-alerts", daemon=True)
        self._thread.start()
        log.info("Weather alerts started (lookahead %g h, cooldown %g min)",
                 self.cfg.lookahead_h, self.cfg.cooldown_min)

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        for topic in ("weather.lon", "trip.route"):
            try:
                self._bus.unsubscribe(topic, self._on_change)
            except Exception:
                pass
        if self._thread is not None:
            self._thread.join(timeout=5)

    def _on_change(self, topic, value, timestamp) -> None:
        # Bus callbacks run in the publisher's thread (weather poller, trip
        # planner): only wake the loop — forecast_at may block on network.
        self._wake.set()

    def _run(self) -> None:
        while not self._stop.is_set():
            self._wake.clear()
            try:
                self.evaluate_once()
            except Exception:
                log.exception("weather alerts evaluation failed")
            self._wake.wait(EVAL_INTERVAL_S)

    # ── inputs ─────────────────────────────────────────────────────────
    def _last(self, topic: str) -> tuple[Any, Optional[float]]:
        try:
            last = self._bus.get_last(topic)
        except Exception:
            return None, None
        if not last:
            return None, None
        return last[0], last[1] if isinstance(last[1], (int, float)) else None

    def _manager(self) -> Any:
        value, _ = self._last("weather._internals")
        manager = value.get("manager") if isinstance(value, dict) else None
        if manager is None and not self._warned_no_manager:
            self._warned_no_manager = True
            log.warning("weather_alerts: moduł weather nie działa — ostrzeżenia tylko "
                        "z bieżącej pogody (bez prognozy i trasy)")
        return manager

    def _current(self, now: float) -> Optional[dict]:
        # Only real data: the demo ("Milan, IT") is published BEFORE its
        # status says demo, so "no status yet" counts as demo too.
        status, _ = self._last("weather.status")
        if not isinstance(status, dict) or status.get("source") not in ("live", "cache"):
            return None
        current, ts = self._last("weather.current")
        if not isinstance(current, dict) or ts is None:
            return None
        if not 0 <= now - ts <= CURRENT_MAX_AGE_S:
            return None
        # A city searched on A4 (or the default one) far from the car is
        # not "teraz" for the driver: with a GPS fix, only weather fetched
        # within NEAR_KM of it counts.
        fix = _plausible_fix(self._last("gps.position")[0])
        place = valid_coords(self._last("weather.lat")[0], self._last("weather.lon")[0])
        if fix is not None and place is not None and _distance_km(fix, place) > NEAR_KM:
            return None
        return current

    def _here_slots(self, manager: Any, now: float) -> list:
        if manager is None:
            return []
        fix = _plausible_fix(self._last("gps.position")[0])
        if fix is None:
            try:
                slots, _coords = manager.slots
            except Exception:
                return []
            return slots if isinstance(slots, list) else []
        out, seen = [], set()
        steps = int(self.cfg.lookahead_h // 3) + 1
        for i in range(steps):
            try:
                slot = manager.forecast_at(fix[0], fix[1], i * 180.0)
            except Exception:
                slot = None
            ts = slot.get("slot_ts") if isinstance(slot, dict) else None
            if ts is not None and ts not in seen:
                seen.add(ts)
                out.append(slot)
        return out

    def _route(self, manager: Any, now: float) -> list:
        """``(slot, eta_min)`` for the route points still ahead."""
        if manager is None or not self.cfg.route:
            return []
        dest, _ = self._last("trip.destination")
        plan, _ = self._last("trip.route")
        if not dest or not isinstance(plan, dict):
            return []
        points = plan.get("waypoints")
        # TripComputer.get_plan_dict publishes the route duration as
        # ``eta_min`` (``duration_min`` kept as a fallback). A cleared or
        # failed plan has eta_min 0 — nothing to look ahead on.
        duration = engine._num(plan.get("eta_min", plan.get("duration_min")), 0, 7 * 24 * 60)
        computed = engine._num(plan.get("computed_at"), 1e9, 1e10)
        if not isinstance(points, list) or len(points) < 2 or not duration \
                or computed is None or not 0 <= now - computed <= ROUTE_MAX_AGE_S:
            return []
        points = points[:ROUTE_POINTS_MAX]
        elapsed = (now - computed) / 60.0
        out = []
        for i, point in enumerate(points[1:], start=1):   # [0] = the start: "here"
            if not isinstance(point, dict):
                continue
            eta = duration / (len(points) - 1) * i - elapsed
            if eta < 0:
                continue          # presumably already passed
            try:
                slot = manager.forecast_at(point.get("lat"), point.get("lon"), eta)
            except Exception:
                slot = None
            if isinstance(slot, dict):
                out.append((slot, eta))
        return out

    # ── one pass ───────────────────────────────────────────────────────
    def evaluate_once(self) -> list:
        """Evaluate, publish weather.alert, announce what is due. Returns
        the active alerts."""
        with self._lock:
            now = self._wall()
            current = self._current(now)
            mono = self._clock()
            if current is not None and engine.rain_now(current):
                self._last_rain_mono = mono
            recent = self._last_rain_mono is not None and \
                0 <= mono - self._last_rain_mono <= RECENT_RAIN_S
            manager = self._manager()
            active = engine.evaluate(current, self._here_slots(manager, now), now=now,
                                     cfg=self.cfg, route=self._route(manager, now),
                                     recent_rain=recent)
            # Compare a stable projection: valid_until / eta_min drift on
            # every pass, which would republish the topic every 5 minutes.
            # Republish anyway when the published list is about to expire
            # (web_viewer / small_viewer drop expired entries).
            key = [(a["kind"], a["severity"], a["where"], a["title"], a["text"])
                   for a in active]
            expiring = any(a["valid_until"] - now < EVAL_INTERVAL_S * 2
                           for a in (self._published or []))
            if self._published is None or key != self._published_key or expiring:
                self._published = active
                self._published_key = key
                self._bus.publish(TOPIC, [dict(a) for a in active])
            self._announce(self._announcer.due(active), now)
            return active

    def _announce(self, due: list, now: float) -> None:
        if not due:
            return
        try:
            lt = self._localtime(now)
            minute = int(lt.tm_hour) * 60 + int(lt.tm_min)
        except Exception:
            minute = 12 * 60
        for alert in due:
            sev = alert["severity"]
            publish_notification(self._bus, alert["title"], alert["text"],
                                 severity=sev, icon=_ICON_BY_KIND.get(alert["kind"], "warning"),
                                 ttl=_TTL_BY_SEVERITY.get(sev, 10.0),
                                 key=f"weather_{alert['kind']}", now=now)
            if self._announcer.speak(alert, minute):
                ttl = max(60.0, min(announce_api.MAX_TTL_S, alert["valid_until"] - now))
                announce_api.request_announcement(
                    self._bus, "weather", f"{alert['title']}. {alert['text']}",
                    priority=_PRIORITY_BY_SEVERITY.get(sev, "normal"),
                    key=f"weather_{alert['kind']}",
                    ttl_s=ttl if math.isfinite(ttl) else announce_api.DEFAULT_TTL_S,
                    now=now)
            log.info("Weather alert: %s (%s, %s)", alert["kind"], sev, alert["where"])


def start_weather_alerts(config=None, event_bus=None, hal=None, **kwargs):
    """Module entry point — called by main.py's module registry."""
    module = WeatherAlerts(event_bus, config)
    module.start()
    return module
