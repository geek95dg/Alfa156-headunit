"""Module ``traffic_alerts``: TomTom traffic incidents while driving.

The route planner asks TomTom once per plan and never again, and
small_viewer read a ``traffic.alert`` nobody published. This module polls
``incidentDetails`` (v5) while the car is moving and tells the driver about
what lies ahead:

* **when** — only while driving: GPS speed above :data:`DRIVE_KMH` for
  :data:`DRIVE_AFTER_S` (a jam does not end it: driving ends after
  :data:`STOP_AFTER_S` below the threshold, or without GPS for
  :data:`POSITION_MAX_AGE_S`); every ``poll_min`` minutes (default 5, at
  least 2), the first request right after driving starts;
* **where**, in this order:

  1. a destination set (``trip.route`` from the route planner): a corridor
     along the next ``lookahead_km`` of the route;
  2. no destination, but the car repeats a past trip (``learn_routes``,
     src/trip/known_routes.py — the last few km match a trip from the
     tracker's database): the rest of that trip (up to 3 of them) is used
     like a planned route — only incidents ON it count;
  3. otherwise (an unknown road) a box ahead of the car, turned with its
     heading; only incidents within :data:`LATERAL_KM` of the line ahead,
     and the reach depends on speed (:func:`unknown_lookahead_km`) and on
     whether the car keeps its course — in town with turns every few
     hundred metres only the next :data:`UNSTABLE_LOOKAHEAD_KM`.

  The planner's straight-line fallback (``approximate``, no ORS key) is
  not a road and counts as no route;
* **how much** — a hard daily budget (``daily_budget``, default 300, saved in
  ``state_path`` so a restart does not reset it; the free key allows about
  2500 a day, shared with the planner and the Settings test) and a pause
  after errors (longer after 429 and 401/403);
* **what** — between polls the cached incidents are re-filtered against
  the current position every :data:`TICK_S`: only those ahead (±60° of the
  heading, closer than ``lookahead_km``) or on the route; the other
  carriageway is ignored.

Publishes ``traffic.alert`` (list for the route screen and small_viewer;
``[]`` when nothing is ahead), ``traffic.status`` (state, budget used,
last error — never the key), a toast through publish_notification (key
``traffic_<hash of the id>``) and — only for closures, accidents, TomTom
"major" and delays of ``voice_min_delay_s`` or more — a ``voice.announce``
request (category ``traffic``); only for new incidents and escalations, at
most one every 2 minutes.

Needs ``modules.location`` (catalog ``requires``). The route planner is
optional: without it (or without a destination) only the box ahead is used —
logged once. Without ``travel.tomtom_key`` (``BCM_TOMTOM_API_KEY`` in
/etc/bcm/bcm.env) the module logs one warning and stays idle.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Callable, Optional

from src.audio import announce_api
from src.core.logger import get_logger
from src.core.notifications import publish_notification
from src.trip import known_routes
from src.trip import traffic as engine

log = get_logger("trip.traffic")

TOPIC = "traffic.alert"
STATUS_TOPIC = "traffic.status"
#: Re-filter the cached incidents (and maybe poll) this often.
TICK_S = 5.0
#: "Driving": faster than this for at least DRIVE_AFTER_S …
DRIVE_KMH = 15.0
DRIVE_AFTER_S = 30.0
#: … until slower for this long (standing in the jam we warned about is
#: still the trip) or without a position for POSITION_MAX_AGE_S.
STOP_AFTER_S = 600.0
POSITION_MAX_AGE_S = 120.0
#: Below this speed the receiver's heading is noise: take the course from
#: the last positions instead.
HEADING_MIN_KMH = 5.0
#: A plan older than this is not "the route ahead" any more.
ROUTE_MAX_AGE_S = 12 * 3600.0
#: How many incidents the screen gets at most.
MAX_PUBLISHED = 8
#: Toast lifetime and how long a spoken warning may wait in the queue
#: (after that the car has passed the place).
TOAST_TTL_S = 20.0
VOICE_TTL_S = 180.0
MAX_SPEED_KMH = 400.0
DEFAULT_STATE_PATH = "data/traffic_budget.json"
#: Unknown road: incidents farther sideways from the line ahead are on
#: other roads.
LATERAL_KM = 0.6
#: Unknown road and the course keeps changing: only this far ahead.
UNSTABLE_LOOKAHEAD_KM = 3.0
#: Learned trips are re-read from the tracker database this often.
ROUTES_REFRESH_S = 1800.0
#: An early request after the area changed (trip recognised) at most this often.
MODE_REPOLL_S = 600.0
#: Trace of the current trip kept for matching (points every 100 m).
TRACE_MAX_POINTS = 60


def unknown_lookahead_km(speed_kmh: Optional[float], cap_km: float) -> float:
    """How far ahead to look on an unknown road: 3 km in town (≤ 50 km/h),
    growing with speed to ``cap_km`` (about 10 km at 100 km/h)."""
    v = speed_kmh or 0.0
    return max(UNSTABLE_LOOKAHEAD_KM, min(cap_km, (v - 30.0) * 0.15))
_ICONS = {"other": "warning", "accident": "car_crash", "jam": "traffic", "lane": "warning",
          "closed": "block", "works": "construction", "wind": "air", "flood": "flood"}


class TrafficAlerts:
    """Runtime of the traffic warnings (thread, bus, announcements)."""

    def __init__(self, event_bus, config=None, *,
                 clock: Callable[[], float] = time.monotonic,
                 wall: Callable[[], float] = time.time,
                 http: Optional[Callable[..., tuple]] = None):
        self._bus = event_bus
        get = config.get if config is not None else (lambda _k, d=None: d)
        self.cfg = engine.load_config(get("traffic_alerts", {}), warn=log.warning)
        self._key = str(get("travel.tomtom_key", "") or "").strip()
        self._clock = clock
        self._wall = wall
        self._http = http
        self._budget = engine.DailyBudget(get("traffic_alerts.state_path", DEFAULT_STATE_PATH)
                                          or DEFAULT_STATE_PATH,
                                          self.cfg.daily_budget, wall=wall, warn=log.warning)
        self._backoff = engine.Backoff(clock)
        self._announcer = engine.IncidentAnnouncer(self.cfg.min_delay_s, clock=clock)
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        # GPS state (written by the bus callback, read by the loop)
        self._pos: Optional[tuple[float, float]] = None
        self._pos_at: Optional[float] = None
        self._heading: Optional[float] = None
        self._anchor: Optional[tuple[float, float, float]] = None   # lat, lon, mono
        self._fast_since: Optional[float] = None
        self._last_fast: Optional[float] = None
        self._driving = False
        self._speed: Optional[float] = None
        # The current trip, thinned (known_routes.SAMPLE_KM), for matching.
        self._trace: list[tuple[float, float]] = []
        # learned trips (read in the loop thread, never on the bus thread)
        self._db_path = str(get("tracking.db_path", "data/gps_tracks.db") or "")
        self._known: list = []
        self._known_at: Optional[float] = None
        self._match_len = -1
        self._matched_tail: Optional[tuple[float, float]] = None
        self._matched: list = []
        self._filter_mode = ""
        self._mode_poll_at: Optional[float] = None
        # polling state
        self._next_poll: Optional[float] = None
        self._incidents: list[dict] = []
        self._fetched_wall: Optional[float] = None
        self._last_ok: Optional[float] = None
        self._last_error: Optional[dict] = None
        self._mode = ""
        self._route_cache: tuple[Any, list] = (None, [])
        self._published_key: Optional[list] = None
        self._status_key: Optional[tuple] = None
        self._budget_warned_day = ""
        self._warned_no_planner = False
        self._warned_corridor: Any = None
        planner_on = True
        try:
            from src.core.modules_catalog import is_enabled
            planner_on = config is None or is_enabled(config, "route_planner") is not False
        except Exception:
            pass
        if not planner_on:
            self._warned_no_planner = True
            log.warning("traffic_alerts: planer tras wyłączony — utrudnienia tylko "
                        "przed autem (bez korytarza wzdłuż trasy)")

    # ── lifecycle ──────────────────────────────────────────────────────
    def start(self) -> None:
        if not self._key:
            log.warning("traffic_alerts: brak klucza TomTom (BCM_TOMTOM_API_KEY w "
                        "/etc/bcm/bcm.env) — utrudnienia nie będą sprawdzane")
        self._bus.subscribe("gps.position", self._on_position)
        self._thread = threading.Thread(target=self._run, name="traffic-alerts", daemon=True)
        self._thread.start()
        log.info("Traffic alerts started (co %g min, limit %d/dobę, %g km naprzód)",
                 self.cfg.poll_min, self.cfg.daily_budget, self.cfg.lookahead_km)

    def stop(self) -> None:
        self._stop.set()
        try:
            self._bus.unsubscribe("gps.position", self._on_position)
        except Exception:
            pass
        if self._thread is not None:
            self._thread.join(timeout=10)

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception:
                log.exception("traffic alerts tick failed")
            self._stop.wait(TICK_S)

    # ── GPS ────────────────────────────────────────────────────────────
    def _on_position(self, topic: str, value: Any, timestamp: float) -> None:
        """``gps.position`` (speed km/h, heading °): validated and recorded —
        nothing else on the publisher's thread."""
        if not isinstance(value, dict) or value.get("fix", True) is False:
            return
        pos = engine.valid_point(value.get("lat"), value.get("lon"))
        if pos is None:
            return
        speed = engine._num(value.get("speed"), 0.0, MAX_SPEED_KMH)
        heading = engine._num(value.get("heading"), 0.0, 360.0)
        now = self._clock()
        with self._lock:
            self._pos, self._pos_at = pos, now
            self._speed = speed
            if not self._trace or engine.haversine_km(self._trace[-1], pos) \
                    >= known_routes.SAMPLE_KM:
                self._trace.append(pos)
                del self._trace[:-TRACE_MAX_POINTS]
            # Course from movement: the receiver's heading is missing or
            # random when slow; 50 m of travel gives a usable bearing.
            if self._anchor is None or now - self._anchor[2] > 60.0:
                self._anchor = (pos[0], pos[1], now)
            elif engine.haversine_km((self._anchor[0], self._anchor[1]), pos) >= 0.05:
                self._heading = engine.bearing_deg((self._anchor[0], self._anchor[1]), pos)
                self._anchor = (pos[0], pos[1], now)
            if heading is not None and speed is not None and speed >= HEADING_MIN_KMH:
                self._heading = heading % 360.0
            if speed is not None and speed > DRIVE_KMH:
                self._last_fast = now
                if self._fast_since is None:
                    self._fast_since = now
                if now - self._fast_since >= DRIVE_AFTER_S and not self._driving:
                    self._driving = True
                    # The trace of a new trip starts here (the last one may
                    # end anywhere: a stale tail would match the wrong trip).
                    self._trace = self._trace[-3:]
                    # A new trip: ask right away (backoff and budget still
                    # apply), not on the schedule left over from the last one.
                    self._next_poll = None
            elif speed is not None:
                self._fast_since = None

    def _gps(self, now: float) -> tuple[Optional[tuple[float, float]], Optional[float], bool]:
        """(position, heading, driving) — None position when stale."""
        with self._lock:
            fresh = self._pos_at is not None and 0 <= now - self._pos_at <= POSITION_MAX_AGE_S
            if self._driving and (not fresh or self._last_fast is None
                                  or not 0 <= now - self._last_fast <= STOP_AFTER_S):
                self._driving = False
                self._fast_since = None
            if not fresh:
                return None, None, self._driving
            return self._pos, self._heading, self._driving

    # ── route ──────────────────────────────────────────────────────────
    def _route(self, now_wall: float) -> list[tuple[float, float]]:
        """The planned route's geometry, or [] (no destination, stale or
        failed plan, route planner off)."""
        try:
            dest = self._bus.get_last("trip.destination")
            plan = self._bus.get_last("trip.route")
        except Exception:
            return []
        dest = dest[0] if dest else None
        plan = plan[0] if plan else None
        if not dest or not isinstance(plan, dict) or plan.get("error"):
            return []
        # The planner's fallback without an ORS key is a straight line from
        # start to destination, not a road: filtering "on the route" against
        # it would drop real incidents. Use the box ahead instead.
        if plan.get("approximate"):
            return []
        computed = engine._num(plan.get("computed_at"), 1e9, 1e10)
        if computed is None or not 0 <= now_wall - computed <= ROUTE_MAX_AGE_S:
            return []
        cached_at, cached = self._route_cache
        if cached_at != computed:
            cached = engine.clean_route(plan.get("geometry"))
            self._route_cache = (computed, cached)
        return cached

    # ── one pass ───────────────────────────────────────────────────────
    def tick(self) -> list[dict]:
        """Maybe poll, re-filter, publish, announce. Returns what is ahead."""
        now = self._clock()
        wall = self._wall()
        pos, heading, driving = self._gps(now)
        route = self._route(wall)
        ahead_route = engine.route_ahead(route, pos, self.cfg.lookahead_km) \
            if pos is not None and route else None
        if ahead_route and not self._corridor_ok(ahead_route):
            # Neither poll nor filter by a corridor TomTom would refuse:
            # the box ahead is queried and filtered the same way instead.
            ahead_route = None
        routes = [ahead_route] if ahead_route else []
        mode = "route" if routes else ""
        if not routes and pos is not None and driving:
            routes = self._learned_ahead(pos, now)
            mode = "learned" if routes else ""
        with self._lock:
            speed, trace = self._speed, list(self._trace)
        reach = self.cfg.lookahead_km
        if not routes:
            mode = "ahead"
            reach = unknown_lookahead_km(speed, self.cfg.lookahead_km)
            if known_routes.heading_stable(trace, heading) is False:
                reach = min(reach, UNSTABLE_LOOKAHEAD_KM)
        if mode != self._filter_mode:
            # The last answer covered a different area (e.g. the box ahead
            # before the trip was recognised): ask again for the new one —
            # once per change, budget and backoff still apply.
            # A match flapping on/off must not burn the budget: at most one
            # such early request every MODE_REPOLL_S.
            if mode in ("route", "learned") and driving and (
                    self._mode_poll_at is None
                    or not 0 <= now - self._mode_poll_at < MODE_REPOLL_S):
                self._mode_poll_at = now
                self._next_poll = None
            self._filter_mode = mode
        if driving and pos is not None and self._key and self._poll_due(now):
            self._poll(pos, heading, routes, mode, now, wall)
        ahead: list[dict] = []
        ttl = 2 * self.cfg.poll_min * 60.0
        if pos is not None and self._fetched_wall is not None \
                and 0 <= wall - self._fetched_wall <= ttl:
            ahead = self._select(pos, heading, routes, reach)
        valid_until = (self._fetched_wall or wall) + ttl
        items = [self._item(inc, valid_until) for inc in ahead[:MAX_PUBLISHED]]
        key = [(i["key"], i["distance_km"], i["delay_min"], i["kind"]) for i in items]
        if key != self._published_key:
            self._published_key = key
            self._bus.publish(TOPIC, items)
        if driving and ahead:
            due = self._announcer.due(ahead)
            if due is not None:
                self._announce(due[0], due[1], wall)
        self._publish_status(driving, pos is not None, heading, wall)
        return ahead

    def _select(self, pos, heading, routes, reach: float) -> list[dict]:
        """Incidents ahead: on any of ``routes`` (planned or learned), or —
        without one — in the narrow box ahead up to ``reach`` km."""
        if not routes:
            return engine.select_ahead(self._incidents, pos, heading, reach,
                                       lateral_km=LATERAL_KM)
        best: dict[str, dict] = {}
        for route in routes:
            for inc in engine.select_ahead(self._incidents, pos, heading,
                                           self.cfg.lookahead_km, route):
                old = best.get(inc["id"])
                if old is None or inc["distance_km"] < old["distance_km"]:
                    best[inc["id"]] = inc
        return sorted(best.values(), key=lambda i: i["distance_km"])

    def _learned_ahead(self, pos, now: float) -> list:
        """The rest of the past trips the car is repeating, as route-ahead
        polylines (at most known_routes.MAX_MATCHES), or []."""
        if not self.cfg.learn_routes:
            return []
        if self._known_at is None or not 0 <= now - self._known_at <= ROUTES_REFRESH_S:
            self._known_at = now
            try:
                self._known = known_routes.load_routes(self._db_path)
            except Exception:
                log.exception("traffic_alerts: reading past trips failed")
                self._known = []
            self._match_len = -1
            log.info("traffic_alerts: %d przejazdów do rozpoznawania trasy", len(self._known))
        if not self._known:
            return []
        with self._lock:
            trace = list(self._trace)
        # Matching is the costly part: only when the trace grew (100 m).
        if len(trace) != self._match_len or (trace and self._matched_tail != trace[-1]):
            self._match_len = len(trace)
            self._matched_tail = trace[-1] if trace else None
            self._matched = known_routes.match(trace, self._known)
        out = []
        for line in self._matched:
            ahead = engine.route_ahead(line, pos, self.cfg.lookahead_km)
            if ahead and self._bbox_small(ahead):
                out.append(ahead)
        return out

    @staticmethod
    def _bbox_small(ahead) -> bool:
        box = engine.route_corridor(ahead)
        return box is not None and engine.bbox_area_km2(box) <= engine.MAX_BBOX_KM2

    def _corridor_ok(self, ahead_route) -> bool:
        bbox = engine.route_corridor(ahead_route)
        if bbox is not None and engine.bbox_area_km2(bbox) <= engine.MAX_BBOX_KM2:
            return True
        plan_id = self._route_cache[0]
        if self._warned_corridor != plan_id:
            self._warned_corridor = plan_id
            log.warning("traffic_alerts: korytarz trasy za duży dla TomTom — "
                        "sprawdzam obszar przed autem")
        return False

    def _poll_due(self, now: float) -> bool:
        if self._backoff.active():
            return False
        return self._next_poll is None or now >= self._next_poll

    def _poll(self, pos, heading, routes, mode: str, now: float, wall: float) -> None:
        if routes:
            # One request covers every route: the box around all of them,
            # or — when that is too big for TomTom — the first (nearest
            # planned / most recent learned) only.
            bbox = engine.bbox_of([(p[0], p[1]) for r in routes for p in r],
                                  engine.HALF_WIDTH_KM)
            if bbox is None or engine.bbox_area_km2(bbox) > engine.MAX_BBOX_KM2:
                bbox = engine.route_corridor(routes[0])
        elif heading is not None:
            bbox, mode = engine.box_ahead(pos, heading, self.cfg.lookahead_km), "ahead"
        else:
            self._mode = "no_heading"
            return
        if bbox is None or engine.bbox_area_km2(bbox) > engine.MAX_BBOX_KM2:
            # Cannot happen for box_ahead (fixed size) nor for a corridor
            # (checked in tick); say so instead of failing silently.
            self._mode = "bad_bbox"
            return
        if not self._budget.try_consume():
            day = time.strftime("%Y-%m-%d", time.gmtime(wall))
            if self._budget_warned_day != day:
                self._budget_warned_day = day
                log.warning("traffic_alerts: dzienny limit %d zapytań TomTom wykorzystany — "
                            "wznowienie po północy UTC", self._budget.limit)
            self._next_poll = now + self.cfg.poll_min * 60.0
            return
        self._mode = mode
        self._next_poll = now + self.cfg.poll_min * 60.0
        params = {
            "key": self._key,
            # TomTom wants minLon,minLat,maxLon,maxLat
            "bbox": "{:.5f},{:.5f},{:.5f},{:.5f}".format(bbox[1], bbox[0], bbox[3], bbox[2]),
            "fields": engine.FIELDS,
            "language": "pl-PL",
            "categoryFilter": engine.CATEGORY_FILTER,
            "timeValidityFilter": "present",
        }
        data, err = self._request(params)
        if err is None:
            parsed = engine.parse_incidents(data)
            if parsed is None:
                err = {"service": "tomtom", "result": "bad_response", "http_code": None}
            else:
                self._backoff.success()
                self._incidents = parsed
                self._fetched_wall = wall
                self._last_ok = wall
                self._last_error = None
                return
        code = err.get("http_code") if isinstance(err.get("http_code"), int) else None
        pause = self._backoff.failure(code)
        self._last_error = {"result": err.get("result") if err.get("result") in
                            ("http", "network", "bad_response") else "network",
                            "http_code": code}
        log.warning("traffic_alerts: TomTom %s%s — przerwa %.0f min",
                    self._last_error["result"], f" {code}" if code else "", pause / 60.0)

    def _request(self, params: dict) -> tuple[Any, Optional[dict]]:
        if self._http is not None:
            return self._http(params)
        from src.trip.route_planner import TOMTOM_INCIDENTS, _http_call
        # _http_call never logs the query string (the key is in it).
        return _http_call("GET", TOMTOM_INCIDENTS, params=params, timeout=8.0,
                          service="tomtom", source="traffic")

    # ── output ─────────────────────────────────────────────────────────
    @staticmethod
    def _item(inc: dict, valid_until: float) -> dict:
        title, text = engine.notification_texts(inc)
        delay = inc.get("delay_s")
        return {
            "key": inc["key"],
            "kind": inc["kind"],
            "category": inc["category"],
            "magnitude": inc["magnitude"],
            "title": title,
            "text": text,
            "roads": list(inc.get("roads") or []),
            "distance_km": round(float(inc["distance_km"]), 1),
            "delay_min": int(round(delay / 60.0)) if isinstance(delay, int) else None,
            "on_route": bool(inc.get("on_route")),
            "valid_until": valid_until,
        }

    def _announce(self, inc: dict, escalation: bool, wall: float) -> None:
        title, text = engine.notification_texts(inc)
        severe = inc.get("category") in engine.ALWAYS_ANNOUNCE or inc.get("magnitude") == 3
        publish_notification(self._bus, title, text, severity="danger" if severe else "warning",
                             icon=_ICONS.get(inc["kind"], "traffic"), ttl=TOAST_TTL_S,
                             key=inc["key"], now=wall)
        if self.cfg.voice and engine.voice_worthy(inc, self.cfg.voice_min_delay_s):
            announce_api.request_announcement(
                self._bus, "traffic", engine.speech_text(inc, escalation),
                priority="high" if severe else "normal", key=inc["key"],
                ttl_s=VOICE_TTL_S, now=wall)
        log.info("Traffic: %s %.1f km ahead (%s)%s", inc["kind"], inc["distance_km"],
                 self._mode or ("route" if inc.get("on_route") else "ahead"),
                 " — escalation" if escalation else "")

    def _publish_status(self, driving: bool, has_pos: bool, heading, wall: float) -> None:
        if not self._key:
            state = "no_key"
        elif self._budget.remaining() <= 0:
            state = "budget"
        elif self._backoff.active():
            state = "backoff"
        elif not driving:
            state = "idle"
        elif not has_pos or (heading is None and self._mode == "no_heading"):
            state = "no_heading"
        else:
            state = "driving"
        backoff_until = wall + self._backoff.remaining_s() if state == "backoff" else None
        status = {
            "state": state,
            "mode": self._filter_mode if self._mode in ("route", "learned", "ahead") else "",
            "used": self._budget.used,
            "budget": self._budget.limit,
            "poll_min": self.cfg.poll_min,
            "last_ok": self._last_ok,
            "error": dict(self._last_error) if self._last_error else None,
            "backoff_until": round(backoff_until) if backoff_until is not None else None,
            "count": len(self._published_key or []),
        }
        key = tuple(sorted((k, str(v)) for k, v in status.items()))
        if key != self._status_key:
            self._status_key = key
            self._bus.publish(STATUS_TOPIC, status)


def start_traffic_alerts(config=None, event_bus=None, hal=None, **kwargs):
    """Module entry point — called by main.py's module registry."""
    module = TrafficAlerts(event_bus, config)
    module.start()
    return module
