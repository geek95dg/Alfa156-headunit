"""TomTom traffic incidents while driving (modules.traffic_alerts).

* src/trip/traffic.py — bbox maths (box ahead, route corridor, TomTom's
  10 000 km² cap), the ahead / on-route filter with bearings (and the
  other carriageway), parsing of a hand-written incidentDetails answer
  (no network) with hostile fields, dedupe / escalation / the 2-minute gap,
  the daily budget (persistence, UTC day rollover, corrupt file), backoff
  (429, 401, network), Polish text.
* src/trip/traffic_alerts.py — the runtime on a real EventBus with a fake
  HTTP function and clock: polls only while driving, every poll_min,
  traffic.alert / traffic.status / notification / voice.announce, backoff,
  budget, no key, route corridor, the key never in the status.
* web_viewer / small_viewer glue, catalog entry.
"""

import json
import math
import os

import pytest

from src.audio import announce_api
from src.core.event_bus import EventBus
from src.core.notifications import TOPIC as NOTIF_TOPIC
from src.trip import traffic as tr
from src.trip import traffic_alerts as ta

NOW = 1_800_000_000.0          # 2027-01-15 08:00 UTC
HOME = (52.0, 19.0)            # a point in central Poland (no real place)
KEY = "SECRET-TOMTOM-KEY-123"


class FakeClock:
    def __init__(self, t=10_000.0):
        self.t = t

    def __call__(self):
        return self.t

    def advance(self, seconds):
        self.t += seconds


def north(km, origin=HOME):
    return tr.destination(origin, 0.0, km)


def raw_incident(iid="inc-1", cat=6, point=None, line=None, **props):
    """One incidentDetails entry as TomTom sends it ([lon, lat] order)."""
    if line is not None:
        geometry = {"type": "LineString", "coordinates": [[p[1], p[0]] for p in line]}
    else:
        p = point or north(3)
        geometry = {"type": "Point", "coordinates": [p[1], p[0]]}
    base = {"id": iid, "iconCategory": cat, "magnitudeOfDelay": 2,
            "events": [{"description": "Korek", "code": 101, "iconCategory": cat}],
            "from": "Węzeł Północ", "to": "Węzeł Południe", "length": 2300.0,
            "delay": 600, "roadNumbers": ["S8"]}
    base.update(props)
    return {"type": "Feature", "properties": base, "geometry": geometry}


def parsed(**kw):
    inc = tr.parse_incident(raw_incident(**kw))
    assert inc is not None
    return inc


# ── geometry ────────────────────────────────────────────────────────────

def test_destination_and_bearing_round_trip():
    for brg in (0, 45, 90, 180, 270, 359):
        p = tr.destination(HOME, brg, 10.0)
        assert tr.haversine_km(HOME, p) == pytest.approx(10.0, abs=1e-6)
        assert tr.angle_diff(tr.bearing_deg(HOME, p), brg) < 0.1
    assert tr.angle_diff(350, 10) == 20
    assert tr.angle_diff(0, 180) == 180


def test_box_ahead_north_is_10_km_ahead_and_3_km_wide():
    min_lat, min_lon, max_lat, max_lon = tr.box_ahead(HOME, 0.0, 10.0)
    assert (max_lat - HOME[0]) * 111.2 == pytest.approx(10.0, abs=0.1)
    assert (HOME[0] - min_lat) * 111.2 == pytest.approx(tr.BEHIND_KM, abs=0.05)
    width = (max_lon - min_lon) * 111.32 * math.cos(math.radians(HOME[0]))
    assert width == pytest.approx(2 * tr.HALF_WIDTH_KM, abs=0.05)
    assert tr.bbox_area_km2((min_lat, min_lon, max_lat, max_lon)) == pytest.approx(31.5, rel=0.03)


def test_box_ahead_east_and_diagonal():
    min_lat, min_lon, max_lat, max_lon = tr.box_ahead(HOME, 90.0, 10.0)
    km_lon = 111.32 * math.cos(math.radians(HOME[0]))
    assert (max_lon - HOME[1]) * km_lon == pytest.approx(10.0, abs=0.1)
    assert (max_lat - min_lat) * 111.32 == pytest.approx(3.0, abs=0.05)
    # Diagonal: the axis-aligned box is bigger than the rectangle, still
    # far below TomTom's 10 000 km² even at the largest lookahead.
    box = tr.box_ahead(HOME, 45.0, 50.0)
    assert 30 * 3 < tr.bbox_area_km2(box) < tr.MAX_BBOX_KM2


def route_north_then_east():
    """10 km north in 1 km steps, then 10 km east."""
    pts = [north(k) for k in range(0, 11)]
    corner = pts[-1]
    pts += [tr.destination(corner, 90.0, k) for k in range(1, 11)]
    return pts


def test_route_ahead_starts_at_the_car_and_stops_at_lookahead():
    route = route_north_then_east()
    car = north(3.1)
    ahead = tr.route_ahead(route, car, 10.0)
    assert ahead[0][2] == 0.0
    assert tr.haversine_km(car, ahead[0][:2]) < 0.01        # the car projected on the route
    assert ahead[-1][2] == 10.0                             # cut at exactly 10 km
    assert len(ahead) == 12                                 # car, 7 + 3 vertices, the cut
    # The car 5 km off the route: it left it — no corridor.
    assert tr.route_ahead(route, tr.destination(car, 270.0, 5.0), 10.0) is None
    assert tr.route_ahead(route[:1], car, 10.0) is None
    corridor = tr.route_corridor(ahead)
    assert corridor[0] < car[0] and corridor[2] > route[10][0]
    assert tr.bbox_area_km2(corridor) < 200


def test_route_ahead_with_sparse_vertices():
    """A straight motorway with vertices 3 km apart: the car 1.4 km past a
    vertex. A jam behind the car is not "ahead"; one ahead is measured from
    the car, not from the vertex behind it."""
    route = [north(k) for k in range(0, 31, 3)]
    car = north(4.4)
    ahead = tr.route_ahead(route, car, 10.0)
    assert ahead[0][2] == 0.0 and tr.haversine_km(car, ahead[0][:2]) < 0.01
    behind = parsed(iid="behind", point=north(3.5))
    front = parsed(iid="front", point=north(5.3))
    got = tr.select_ahead([behind, front], car, 0.0, 10.0, ahead)
    assert ids(got) == ["front"]
    assert got[0]["distance_km"] == pytest.approx(0.9, abs=0.02)
    # Vertices 5 km apart, the car halfway: still on the route.
    sparse = [north(k) for k in range(0, 31, 5)]
    assert tr.route_ahead(sparse, north(7.5), 10.0) is not None
    # One long last segment does not stretch the corridor past ahead_km.
    long_seg = [HOME, north(300)]
    a = tr.route_ahead(long_seg, north(1), 10.0)
    assert a[-1][2] == 10.0 and tr.haversine_km(a[-1][:2], north(11)) < 0.05
    assert tr.bbox_area_km2(tr.route_corridor(a)) < 100


def test_clean_route_drops_garbage():
    geo = [(52.0, 19.0), [52.1, 19.1], ("x", 1), (91, 0), (0.0, 0.0), (float("nan"), 1), None,
           (True, 19.0)]
    assert tr.clean_route(geo) == [(52.0, 19.0), (52.1, 19.1)]
    assert tr.clean_route("nope") == []


# ── ahead filter ────────────────────────────────────────────────────────

def ids(incs):
    return [i["id"] for i in incs]


def test_ahead_filter_by_bearing_and_distance():
    incs = [
        parsed(iid="north5", point=north(5)),
        parsed(iid="south5", point=tr.destination(HOME, 180, 5)),
        parsed(iid="ne50", point=tr.destination(HOME, 50, 5)),
        parsed(iid="ne70", point=tr.destination(HOME, 70, 5)),
        parsed(iid="far", point=north(12)),
        parsed(iid="near80", point=tr.destination(HOME, 80, 0.2)),
        parsed(iid="near120", point=tr.destination(HOME, 120, 0.2)),
    ]
    out = tr.select_ahead(incs, HOME, 0.0, 10.0)
    assert ids(out) == ["near80", "north5", "ne50"]        # nearest first
    assert out[1]["distance_km"] == pytest.approx(5.0, abs=0.01)
    assert all(i["on_route"] is False for i in out)
    # Heading wraps around 0: 340° still sees the north one, not ne50 (70°).
    assert "north5" in ids(tr.select_ahead(incs, HOME, 340.0, 10.0))
    assert "ne50" not in ids(tr.select_ahead(incs, HOME, 340.0, 10.0))
    # Without a heading (and no route) nothing can be "ahead".
    assert tr.select_ahead(incs, HOME, None, 10.0) == []


def test_ahead_filter_skips_the_other_carriageway():
    start = north(3)
    with_us = parsed(iid="with", line=[start, north(4)])
    against = parsed(iid="against", line=[north(4), start])
    assert ids(tr.select_ahead([with_us, against], HOME, 0.0, 10.0)) == ["with"]


def test_route_mode_keeps_only_what_is_on_the_route():
    route = route_north_then_east()
    ahead = tr.route_ahead(route, HOME, 15.0)
    corner = route[10]
    after_turn = parsed(iid="after_turn", point=tr.destination(corner, 90, 2))
    off_route = parsed(iid="off", point=tr.destination(north(5), 90, 1.0))
    beyond = parsed(iid="beyond", point=tr.destination(corner, 90, 8))
    opposite = parsed(iid="opp", line=[tr.destination(corner, 90, 3),
                                       tr.destination(corner, 90, 2)])
    out = tr.select_ahead([after_turn, off_route, beyond, opposite], HOME, 0.0, 15.0, ahead)
    # after the turn: bearing ~80° from the car would fail ±60°, but it is
    # on the route, 12 km along it; "beyond" is 18 km along (> 15).
    assert ids(out) == ["after_turn"]
    assert out[0]["on_route"] is True
    assert out[0]["distance_km"] == pytest.approx(12.0, abs=0.1)


# ── parsing ─────────────────────────────────────────────────────────────

def fixture_answer():
    """A hand-written answer in the incidentDetails v5 shape."""
    line = [north(3), north(3.5), north(5)]
    return {"incidents": [
        raw_incident("jam-s8", 6, line=line, delay=612, length=2048.5,
                     roadNumbers=["S8", "E67", "<b>x</b>", 7, "A" * 30],
                     description_extra="ignored"),
        raw_incident("acc-1", 1, point=north(6), magnitudeOfDelay=7, delay=-5,
                     roadNumbers="S8", events=[{"description": "Wypadek‮\n\x00z  ofiarami " + "x" * 200}],
                     **{"from": "A\x1bB", "to": 5}),
        raw_incident("jam-s8", 6, point=north(4)),                 # duplicate id
        raw_incident("<script>", 6),                               # bad id
        raw_incident("rain", 4),                                   # category not asked for
        raw_incident("boolcat", True),
        {"type": "Feature", "properties": {"id": "nogeo", "iconCategory": 6}},
        {"properties": {"id": "badgeo", "iconCategory": 6},
         "geometry": {"type": "Point", "coordinates": [500, 52]}},
        {"properties": {"id": "poly", "iconCategory": 6},
         "geometry": {"type": "Polygon", "coordinates": [[19, 52]]}},
        "not a dict",
        None,
    ]}


def test_parse_fixture_strictly():
    out = tr.parse_incidents(fixture_answer())
    assert ids(out) == ["jam-s8", "acc-1"]
    jam, acc = out
    assert jam["category"] == 6 and jam["kind"] == "jam" and jam["magnitude"] == 2
    assert jam["delay_s"] == 612 and jam["length_m"] == 2048
    assert jam["roads"] == ["S8", "E67"]
    assert (jam["lat"], jam["lon"]) == pytest.approx(north(3))
    assert jam["dir_deg"] == pytest.approx(0.0, abs=0.5)
    assert jam["from"] == "Węzeł Północ" and jam["to"] == "Węzeł Południe"
    assert jam["key"].startswith("traffic_") and len(jam["key"]) == 24
    assert acc["magnitude"] == 0 and acc["delay_s"] is None and acc["roads"] == []
    assert acc["dir_deg"] is None
    assert "\n" not in acc["description"] and "\x00" not in acc["description"]
    assert "‮" not in acc["description"] and len(acc["description"]) <= 100
    assert acc["from"] == "A B" and acc["to"] == ""


def test_parse_rejects_wrong_shapes_and_caps():
    assert tr.parse_incidents(None) is None
    assert tr.parse_incidents([]) is None
    assert tr.parse_incidents({"incidents": "x"}) is None
    assert tr.parse_incidents({"incidents": []}) == []
    many = {"incidents": [raw_incident(f"i{n}") for n in range(tr.MAX_INCIDENTS + 50)]}
    assert len(tr.parse_incidents(many)) == tr.MAX_INCIDENTS
    long_line = raw_incident("long", line=[north(k / 100) for k in range(2000)])
    assert tr.parse_incident(long_line) is not None


# ── announcements ───────────────────────────────────────────────────────

def ahead_of(*incs, km=3.0):
    return [dict(i, distance_km=km, on_route=False) for i in incs]


def test_announcer_new_once_then_escalation():
    clock = FakeClock()
    ann = tr.IncidentAnnouncer(180, clock=clock)
    jam = parsed(iid="j", delay=600)
    assert ann.due(ahead_of(jam)) == (ahead_of(jam)[0], False)
    clock.advance(600)
    assert ann.due(ahead_of(jam)) is None                    # same, not again
    worse = dict(jam, magnitude=3)
    due = ann.due(ahead_of(worse))
    assert due is not None and due[1] is True                # escalation
    clock.advance(600)
    longer = dict(worse, delay_s=jam["delay_s"] + 250)       # ×1.4 and only +4 min
    assert ann.due(ahead_of(longer)) is None
    much_longer = dict(worse, delay_s=1200)                  # +10 min and ×2
    assert ann.due(ahead_of(much_longer))[1] is True


def test_announcer_gap_and_pending():
    clock = FakeClock()
    ann = tr.IncidentAnnouncer(180, clock=clock)
    a, b = parsed(iid="a"), parsed(iid="b")
    both = ahead_of(a, b)
    assert ann.due(both)[0]["id"] == "a"
    clock.advance(60)
    assert ann.due(both) is None                             # < 2 min
    clock.advance(61)
    assert ann.due(both)[0]["id"] == "b"                     # pending one now
    clock.advance(200)
    assert ann.due(both) is None


def test_announcer_thresholds_and_forgetting():
    clock = FakeClock()
    ann = tr.IncidentAnnouncer(180, clock=clock)
    small_jam = parsed(iid="small", delay=60, magnitudeOfDelay=1)
    assert ann.due(ahead_of(small_jam)) is None
    acc = parsed(iid="acc", cat=1, delay=None, magnitudeOfDelay=0)
    assert ann.due(ahead_of(acc)) is not None                # accidents always
    closed = parsed(iid="closed", cat=8, delay=None, magnitudeOfDelay=4)
    assert tr.worth_announcing(closed, 180)
    assert tr.worth_announcing(parsed(iid="major", delay=None, magnitudeOfDelay=3), 180)
    clock.advance(tr.FORGET_S + 1)
    assert ann.due([]) is None
    assert ann.due(ahead_of(acc)) is not None                # forgotten → new again


# ── budget and backoff ──────────────────────────────────────────────────

def test_budget_counts_persists_and_rolls_over(tmp_path):
    path = tmp_path / "data" / "traffic_budget.json"
    wall = [NOW]
    b = tr.DailyBudget(path, 3, wall=lambda: wall[0])
    assert [b.try_consume() for _ in range(4)] == [True, True, True, False]
    assert b.remaining() == 0
    assert json.loads(path.read_text()) == {"day": "2027-01-15", "used": 3}
    assert oct(os.stat(path).st_mode & 0o777) == "0o600"
    again = tr.DailyBudget(path, 3, wall=lambda: wall[0])       # restart
    assert again.used == 3 and not again.try_consume()
    wall[0] = NOW + 16 * 3600                                   # next UTC day
    assert again.remaining() == 3 and again.try_consume()
    assert json.loads(path.read_text()) == {"day": "2027-01-16", "used": 1}


def test_budget_clock_going_back_does_not_reset(tmp_path):
    path = tmp_path / "b.json"
    wall = [NOW]
    b = tr.DailyBudget(path, 3, wall=lambda: wall[0])
    assert b.try_consume() and b.try_consume()
    wall[0] = NOW - 2 * 86400                                   # RTC jumped back
    assert b.remaining() == 1
    again = tr.DailyBudget(path, 3, wall=lambda: wall[0])       # restart, clock still back
    assert again.used == 2 and again.remaining() == 1
    wall[0] = NOW + 86400                                       # a later day: fresh budget
    assert again.remaining() == 3
    # A file dated far in the future (RTC far off when written) is ignored.
    path.write_text(json.dumps({"day": "2031-01-01", "used": 3}))
    wall[0] = NOW
    assert tr.DailyBudget(path, 3, wall=lambda: wall[0]).remaining() == 3


@pytest.mark.parametrize("content", [b"{not json", b"[1,2]", b'{"day": "2027-01-15", "used": -4}',
                                     b'{"day": "2027-01-15", "used": true}',
                                     b'{"day": "2027-01-14", "used": 5}', b"\xff\xfe",
                                     b'{"day": "2027-01-15", "used": 1}' + b" " * 5000])
def test_budget_ignores_bad_files(tmp_path, content):
    path = tmp_path / "b.json"
    path.write_bytes(content)
    warnings = []
    b = tr.DailyBudget(path, 5, wall=lambda: NOW, warn=warnings.append)
    assert b.used == 0 and b.try_consume()


def test_budget_survives_unwritable_path(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    warnings = []
    b = tr.DailyBudget(blocker / "sub" / "b.json", 2, wall=lambda: NOW, warn=warnings.append)
    assert b.try_consume() and b.try_consume() and not b.try_consume()
    assert warnings


def test_backoff_schedule():
    clock = FakeClock()
    bo = tr.Backoff(clock)
    assert [bo.failure() for _ in range(7)] == [60, 120, 240, 480, 960, 1800, 1800]
    assert bo.active()
    bo.success()
    assert not bo.active() and bo.remaining_s() == 0
    assert [bo.failure(429) for _ in range(5)] == [900, 1800, 3600, 7200, 7200]
    bo.success()
    assert bo.failure(403) == 3600 and bo.remaining_s() == 3600
    clock.advance(3601)
    assert not bo.active()


# ── text ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("km,words", [
    (0.04, "za 100 metrów"), (0.5, "za 500 metrów"), (1.0, "za kilometr"),
    (2.2, "za 2 kilometry"), (3.0, "za 3 kilometry"), (5.0, "za 5 kilometrów"),
    (12.0, "za 12 kilometrów"), (22.0, "za 22 kilometry"), (25.0, "za 25 kilometrów"),
])
def test_distance_words(km, words):
    assert tr.distance_words(km) == words


@pytest.mark.parametrize("delay,words", [
    (None, ""), (30, ""), (60, "opóźnienie około minuty"), (600, "opóźnienie około 10 minut"),
    (125, "opóźnienie około 2 minut"), (3600, "opóźnienie około godziny"),
    (5400, "opóźnienie około 2 godzin"),
])
def test_delay_words(delay, words):
    assert tr.delay_words(delay) == words


def test_speech_and_notification_text():
    jam = dict(parsed(iid="j", delay=600), distance_km=3.2)
    assert tr.speech_text(jam) == \
        "Uwaga, korek za 3 kilometry na drodze S8, opóźnienie około 10 minut."
    assert tr.speech_text(jam, escalation=True).startswith("Aktualizacja, korek za 3")
    closed = dict(parsed(iid="c", cat=8, delay=None, roadNumbers=[]), distance_km=1.6)
    assert tr.speech_text(closed) == "Uwaga, droga zamknięta za 2 kilometry."
    title, text = tr.notification_texts(jam)
    assert title == "Korek za 3,2 km"
    assert text == "S8 · opóźnienie ok. 10 min · długość 2,3 km · Węzeł Północ → Węzeł Południe"
    req = announce_api.make_request("traffic", tr.speech_text(jam), key=jam["key"], now=NOW)
    assert req is not None and req["key"] == jam["key"]       # key passes the voice regex


def test_load_config_defaults_and_bad_values():
    assert tr.load_config(None) == tr.TrafficConfig()
    warnings = []
    cfg = tr.load_config({"poll_min": 1, "daily_budget": "lots", "lookahead_km": 20,
                          "min_delay_s": True, "voice": False}, warn=warnings.append)
    assert cfg.poll_min == 5.0 and cfg.daily_budget == 300 and cfg.lookahead_km == 20.0
    assert cfg.min_delay_s == 180.0 and cfg.voice is False and len(warnings) == 3


# ── runtime ─────────────────────────────────────────────────────────────

class Cfg:
    def __init__(self, data):
        self._data = data

    def get(self, key, default=None):
        node = self._data
        for part in key.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node


class FakeHttp:
    def __init__(self, answer=None):
        self.calls = []
        self.answers = []
        self.default = answer if answer is not None else {"incidents": []}

    def __call__(self, params):
        self.calls.append(dict(params))
        if self.answers:
            return self.answers.pop(0)
        return self.default, None


@pytest.fixture(autouse=True)
def bus_time(monkeypatch):
    monkeypatch.setattr("src.core.event_bus.time.time", lambda: NOW)


def make(tmp_path, answer=None, key=KEY, block=None, extra=None):
    bus = EventBus()
    clock = FakeClock()
    start = clock.t
    http = FakeHttp(answer)
    data = {"travel": {"tomtom_key": key},
            "traffic_alerts": dict({"state_path": str(tmp_path / "budget.json")}, **(block or {}))}
    data.update(extra or {})
    mod = ta.TrafficAlerts(bus, Cfg(data), clock=clock,
                           wall=lambda: NOW + clock.t - start, http=http)
    bus.subscribe("gps.position", mod._on_position)
    out = {"alerts": [], "voice": [], "status": []}
    bus.subscribe(ta.TOPIC, lambda t, v, ts: out["alerts"].append(v))
    bus.subscribe(announce_api.TOPIC, lambda t, v, ts: out["voice"].append(v))
    bus.subscribe(ta.STATUS_TOPIC, lambda t, v, ts: out["status"].append(v))
    return bus, mod, clock, http, out


def drive(bus, mod, clock, seconds, speed=60.0, heading=0.0, pos=HOME, step=5.0):
    """Feed positions every ``step`` s (moving north at ``speed``) and tick."""
    lat, lon = pos
    t = 0.0
    while t < seconds:
        bus.publish("gps.position", {"lat": lat, "lon": lon, "speed": speed,
                                     "heading": heading, "fix": True})
        mod.tick()
        clock.advance(step)
        t += step
    return lat, lon


def jam_answer(km=3.0, iid="jam-s8", **kw):
    return {"incidents": [raw_incident(iid, 6, point=north(km), **kw)]}


def notifs(bus):
    last = bus.get_last(NOTIF_TOPIC)
    return last[0] if last else []


def test_no_polls_while_parked_or_slow(tmp_path):
    bus, mod, clock, http, out = make(tmp_path)
    drive(bus, mod, clock, 120, speed=10.0)
    assert http.calls == []
    assert out["status"][-1]["state"] == "idle"
    drive(bus, mod, clock, 25, speed=60.0)                   # < 30 s fast
    assert http.calls == []


def test_driving_polls_announces_and_publishes(tmp_path):
    bus, mod, clock, http, out = make(tmp_path, answer=jam_answer())
    drive(bus, mod, clock, 40)
    assert len(http.calls) == 1
    params = http.calls[0]
    assert params["key"] == KEY and params["language"] == "pl-PL"
    assert params["categoryFilter"] == tr.CATEGORY_FILTER
    min_lon, min_lat, max_lon, max_lat = map(float, params["bbox"].split(","))
    assert min_lat < HOME[0] < max_lat and min_lon < HOME[1] < max_lon
    assert (max_lat - HOME[0]) * 111.2 == pytest.approx(10.0, abs=0.2)
    items = out["alerts"][-1]
    assert len(items) == 1 and items[0]["kind"] == "jam" and items[0]["on_route"] is False
    assert items[0]["distance_km"] == pytest.approx(3.0, abs=0.1)
    assert items[0]["delay_min"] == 10
    key = tr.incident_key("jam-s8")
    assert [n["key"] for n in notifs(bus)] == [key]
    assert len(out["voice"]) == 1
    v = out["voice"][0]
    assert v["category"] == "traffic" and v["key"] == key
    assert v["text"] == "Uwaga, korek za 3 kilometry na drodze S8, opóźnienie około 10 minut."
    status = out["status"][-1]
    assert status["state"] == "driving" and status["mode"] == "ahead"
    assert status["used"] == 1 and status["budget"] == 300
    assert KEY not in json.dumps(out["status"]) and KEY not in json.dumps(out["alerts"])
    # Within poll_min: no new request; after it: one more, no repeat announcement.
    drive(bus, mod, clock, 200)
    assert len(http.calls) == 1
    drive(bus, mod, clock, 120)
    assert len(http.calls) == 2 and len(out["voice"]) == 1


def test_incident_behind_is_dropped_after_passing(tmp_path):
    bus, mod, clock, http, out = make(tmp_path, answer=jam_answer(km=1.0))
    drive(bus, mod, clock, 40)
    assert out["alerts"][-1]
    drive(bus, mod, clock, 10, pos=north(2.0))               # passed it
    assert out["alerts"][-1] == []


def test_voice_off_and_min_delay(tmp_path):
    bus, mod, clock, http, out = make(tmp_path, answer=jam_answer(delay=120),
                                      block={"voice": False, "min_delay_s": 300})
    drive(bus, mod, clock, 40)
    assert out["alerts"][-1] and notifs(bus) == [] and out["voice"] == []
    bus2, mod2, clock2, _h, out2 = make(tmp_path / "b", answer=jam_answer(delay=900),
                                        block={"voice": False})
    drive(bus2, mod2, clock2, 40)
    assert notifs(bus2) and out2["voice"] == []


def test_429_backoff(tmp_path):
    bus, mod, clock, http, out = make(tmp_path)
    http.answers = [(None, {"service": "tomtom", "result": "http", "http_code": 429})]
    drive(bus, mod, clock, 40)
    assert len(http.calls) == 1
    status = out["status"][-1]
    assert status["state"] == "backoff" and status["error"] == {"result": "http", "http_code": 429}
    drive(bus, mod, clock, 800)                              # < 15 min
    assert len(http.calls) == 1
    drive(bus, mod, clock, 120)
    assert len(http.calls) == 2 and out["status"][-1]["state"] == "driving"
    assert out["status"][-1]["error"] is None


def test_bad_answer_counts_as_error(tmp_path):
    bus, mod, clock, http, out = make(tmp_path, answer={"weird": 1})
    drive(bus, mod, clock, 40)
    assert out["status"][-1]["error"] == {"result": "bad_response", "http_code": None}


def test_daily_budget_stops_polls_and_persists(tmp_path):
    bus, mod, clock, http, out = make(tmp_path, block={"daily_budget": 2, "poll_min": 2})
    drive(bus, mod, clock, 30 + 2 * 125)
    assert len(http.calls) == 2
    assert out["status"][-1]["state"] == "budget"
    saved = json.loads((tmp_path / "budget.json").read_text())
    assert saved["used"] == 2
    _b, mod2, clock2, http2, _o = make(tmp_path, block={"daily_budget": 2})
    drive(_b, mod2, clock2, 60)
    assert http2.calls == []                                  # restart keeps the count


def test_no_key_stays_idle(tmp_path):
    bus, mod, clock, http, out = make(tmp_path, key="")
    mod.start()
    try:
        drive(bus, mod, clock, 60)
    finally:
        mod.stop()
    assert http.calls == [] and out["status"][-1]["state"] == "no_key"


def test_route_corridor_used_with_destination(tmp_path):
    route = route_north_then_east()
    corner = route[10]
    answer = {"incidents": [raw_incident("turn", 1, point=tr.destination(corner, 90, 2)),
                            raw_incident("side", 6, point=tr.destination(north(5), 90, 1.0))]}
    bus, mod, clock, http, out = make(tmp_path, answer=answer, block={"lookahead_km": 15})
    bus.publish("trip.destination", {"name": "X"})
    bus.publish("trip.route", {"geometry": route, "computed_at": NOW, "error": None})
    drive(bus, mod, clock, 40)
    assert out["status"][-1]["mode"] == "route"
    min_lon, min_lat, max_lon, max_lat = map(float, http.calls[0]["bbox"].split(","))
    assert max_lon > tr.destination(corner, 90, 4)[1]        # covers the turn
    items = out["alerts"][-1]
    assert [i["kind"] for i in items] == ["accident"] and items[0]["on_route"] is True
    # A stale plan is not a route any more: back to the box ahead.
    bus.publish("trip.route", {"geometry": route, "computed_at": NOW - 13 * 3600})
    drive(bus, mod, clock, 400)
    assert out["status"][-1]["mode"] == "ahead"


def test_approximate_plan_is_not_a_route(tmp_path):
    """The planner's straight-line fallback (no ORS key) is not a road: the
    box ahead is used and an incident off that line is still announced."""
    dest = tr.destination(HOME, 45.0, 300.0)
    answer = {"incidents": [raw_incident("jam", 6, point=tr.destination(HOME, 10.0, 3.0))]}
    bus, mod, clock, http, out = make(tmp_path, answer=answer)
    bus.publish("trip.destination", {"name": "X"})
    bus.publish("trip.route", {"geometry": [HOME, dest], "computed_at": NOW, "error": None,
                               "approximate": True})
    drive(bus, mod, clock, 40)
    assert len(http.calls) == 1 and out["status"][-1]["mode"] == "ahead"
    assert [i["kind"] for i in out["alerts"][-1]] == ["jam"]


def test_oversized_corridor_falls_back_to_box(tmp_path, monkeypatch, caplog):
    route = route_north_then_east()
    answer = {"incidents": [raw_incident("jam", 6, point=tr.destination(HOME, 5.0, 3.0))]}
    bus, mod, clock, http, out = make(tmp_path, answer=answer, block={"lookahead_km": 15})
    # The corridor (10 km north + 5 km east, widened) is about 100 km², the
    # box ahead about 50: only the corridor is "too big".
    monkeypatch.setattr(tr, "MAX_BBOX_KM2", 80.0)
    bus.publish("trip.destination", {"name": "X"})
    bus.publish("trip.route", {"geometry": route, "computed_at": NOW, "error": None})
    with caplog.at_level("WARNING"):
        drive(bus, mod, clock, 40)
    assert len(http.calls) == 1 and out["status"][-1]["mode"] == "ahead"
    assert [i["kind"] for i in out["alerts"][-1]] == ["jam"]
    warns = [r for r in caplog.records if "korytarz" in r.getMessage()]
    assert len(warns) == 1


def test_first_poll_right_after_a_new_trip(tmp_path):
    bus, mod, clock, http, out = make(tmp_path)
    drive(bus, mod, clock, 40)
    assert len(http.calls) == 1
    drive(bus, mod, clock, 650, speed=0.0)                   # 10+ min stop: trip over
    assert out["status"][-1]["state"] == "idle"
    calls = len(http.calls)
    drive(bus, mod, clock, 40)                               # new trip
    assert len(http.calls) == calls + 1


def test_driving_ends_after_long_stop_or_lost_gps(tmp_path):
    bus, mod, clock, http, out = make(tmp_path)
    drive(bus, mod, clock, 40)
    drive(bus, mod, clock, 500, speed=0.0)                   # jam: still driving
    assert out["status"][-1]["state"] == "driving"
    drive(bus, mod, clock, 200, speed=0.0)
    assert out["status"][-1]["state"] == "idle"
    calls = len(http.calls)
    drive(bus, mod, clock, 200)                              # next poll_min slot
    clock.advance(ta.POSITION_MAX_AGE_S + 10)                # GPS gone
    mod.tick()
    assert out["status"][-1]["state"] == "idle"
    assert len(http.calls) == calls + 1


def test_heading_from_movement_when_receiver_has_none(tmp_path):
    bus, mod, clock, http, out = make(tmp_path, answer=jam_answer())
    lat_lon = [north(k * 0.08) for k in range(12)]
    for p in lat_lon:
        bus.publish("gps.position", {"lat": p[0], "lon": p[1], "speed": 60.0, "heading": None})
        mod.tick()
        clock.advance(5)
    assert len(http.calls) == 1 and out["alerts"][-1]


def test_bad_gps_payloads_are_ignored(tmp_path):
    bus, mod, clock, http, out = make(tmp_path)
    for bad in (None, "x", {"lat": "52", "lon": 19}, {"lat": 0.0, "lon": 0.0, "speed": 60},
                {"lat": 52, "lon": 19, "speed": float("inf")}, {"lat": 52, "lon": 19, "fix": False},
                {"lat": 52, "lon": 19, "speed": True}):
        for _ in range(10):
            bus.publish("gps.position", bad)
            clock.advance(5)
            mod.tick()
    assert http.calls == []


def test_route_planner_off_warns_once(tmp_path, caplog):
    caplog.set_level("WARNING")
    bus, mod, clock, http, out = make(tmp_path, answer=jam_answer(),
                                      extra={"modules": {"route_planner": False}})
    drive(bus, mod, clock, 40)
    assert sum("planer tras wyłączony" in r.getMessage() for r in caplog.records) == 1
    assert out["alerts"][-1]


def test_real_http_path_never_logs_the_key(tmp_path, monkeypatch, caplog):
    """Without a fake: route_planner._http_call with source "traffic"."""
    import sys
    import types
    from src.network import net_services

    class Resp:
        status_code = 429
        text = "Over quota"

    fake = types.SimpleNamespace(get=lambda url, **kw: Resp(), post=None)
    monkeypatch.setitem(sys.modules, "requests", fake)
    caplog.set_level("DEBUG")
    bus = EventBus()
    clock = FakeClock()
    mod = ta.TrafficAlerts(bus, Cfg({"travel": {"tomtom_key": KEY},
                                     "traffic_alerts": {"state_path": str(tmp_path / "b.json")}}),
                           clock=clock, wall=lambda: NOW)
    bus.subscribe("gps.position", mod._on_position)
    try:
        drive(bus, mod, clock, 40)
        assert net_services.snapshot()["tomtom"]["source"] == "traffic"
    finally:
        net_services.reset()                                 # module-global state
    assert KEY not in caplog.text
    assert bus.get_last(ta.STATUS_TOPIC)[0]["error"]["http_code"] == 429


# ── glue ────────────────────────────────────────────────────────────────

def test_web_viewer_summary_validates():
    from src.dashboard.web_viewer import _traffic_alerts_summary as summary
    assert summary([{"kind": "jam"}], None) is None
    good = {"kind": "jam", "title": "Korek\nza 3 km", "text": "S8", "distance_km": 3.0,
            "delay_min": 10, "on_route": True, "valid_until": NOW + 60}
    bad = [dict(good, kind="<img>"), dict(good, valid_until=NOW - 1),
           dict(good, distance_km=True), dict(good, distance_km=1e9), "x"]
    status = {"state": "driving", "mode": "route", "used": 3, "budget": 300, "poll_min": 5,
              "last_ok": NOW, "error": {"result": "http", "http_code": 429},
              "backoff_until": None, "key": KEY}
    out = summary(bad + [dict(good, delay_min=-1)], status, now=NOW)
    assert out["items"] == [{"kind": "jam", "title": "Korek za 3 km", "text": "S8",
                             "distance_km": 3.0, "delay_min": None, "on_route": True}]
    assert out["state"] == "driving" and out["used"] == 3
    assert out["error"] == {"service": "tomtom", "result": "http", "http_code": 429}
    assert KEY not in json.dumps(out)
    assert summary("x", {"state": "evil", "used": True})["state"] == "idle"


def test_small_viewer_shows_the_nearest(monkeypatch):
    from src.dashboard.small_viewer import SmallDisplayServer
    monkeypatch.setattr("src.dashboard.web_viewer.time.time", lambda: NOW)
    bus = EventBus()
    srv = SmallDisplayServer(event_bus=bus)
    bus.publish(ta.TOPIC, [{"kind": "jam", "title": "Korek za 3 km", "text": "S8",
                            "distance_km": 3.0, "valid_until": NOW + 60}])
    assert not [n for n in srv._get_data().get("notifications", []) if n["type"] == "traffic"]
    bus.publish(ta.STATUS_TOPIC, {"state": "driving"})
    traffic = [n for n in srv._get_data()["notifications"] if n["type"] == "traffic"]
    assert traffic and traffic[0]["text"] == "Korek za 3 km — S8"


def test_catalog_entry():
    from src.core import modules_catalog as mc
    info = mc.MODULES["traffic_alerts"]
    assert info["default"] is False and info["requires"] == ("location",)
    assert info["entry"] == ("src.trip.traffic_alerts", "start_traffic_alerts")
    assert callable(ta.start_traffic_alerts)


# ── learned routes (A), narrow box on unknown roads (B), voice only for
#    serious incidents (D) ─────────────────────────────────────────────────

from src.trip import known_routes as kr  # noqa: E402


def _line(origin, bearing, km, step=0.1):
    return [tr.destination(origin, bearing, i * step) for i in range(int(km / step) + 1)]


def _east_turn_route():
    """A past trip: 5 km north, then 8 km east."""
    first = _line(HOME, 0.0, 5.0)
    return first + _line(first[-1], 90.0, 8.0)[1:]


def _make_db(path, trips):
    import sqlite3
    db = sqlite3.connect(str(path))
    db.execute("CREATE TABLE tracks (id INTEGER PRIMARY KEY, trip_id INTEGER, ts REAL, "
               "lat REAL, lon REAL, speed REAL, heading REAL, altitude REAL)")
    db.execute("CREATE TABLE trips (id INTEGER PRIMARY KEY, start_ts REAL, end_ts REAL, "
               "distance_km REAL, avg_speed REAL, max_speed REAL)")
    for tid, pts in enumerate(trips, 1):
        db.execute("INSERT INTO trips VALUES (?,?,?,?,?,?)", (tid, 0, 100, kr.trace_km(pts), 50, 90))
        for n, p in enumerate(pts):
            db.execute("INSERT INTO tracks (trip_id, ts, lat, lon) VALUES (?,?,?,?)",
                       (tid, float(n), p[0], p[1]))
    db.commit()
    db.close()


class TestKnownRoutes:
    def test_match_same_direction_and_reverse(self):
        route = _east_turn_route()
        trace = _line(HOME, 0.0, 3.0)
        assert kr.match(trace, [route]) == [route]
        back = [tr.destination(route[-1], 270.0, i * 0.1) for i in range(31)]
        assert kr.match(back, [route]) == [route[::-1]]

    def test_no_match_short_or_elsewhere(self):
        route = _east_turn_route()
        assert kr.match(_line(HOME, 0.0, 1.0), [route]) == []          # < 2 km
        assert kr.match(_line(HOME, 45.0, 3.0), [route]) == []         # other road

    def test_load_routes_read_only_and_missing(self, tmp_path):
        db = tmp_path / "t.db"
        _make_db(db, [_east_turn_route(), _line(HOME, 0.0, 1.0)])     # 2nd too short
        before = db.read_bytes()
        routes = kr.load_routes(str(db))
        assert len(routes) == 1 and db.read_bytes() == before
        assert kr.load_routes(str(tmp_path / "none.db")) == []

    def test_heading_stable(self):
        assert kr.heading_stable(_line(HOME, 0.0, 2.0), 0.0) is True
        zig = _line(HOME, 0.0, 0.5) + _line(tr.destination(HOME, 0.0, 0.5), 90.0, 0.6)[1:]
        assert kr.heading_stable(zig, 0.0) is False
        assert kr.heading_stable(_line(HOME, 0.0, 0.3), 0.0) is None


def _drive_line(bus, mod, clock, points, speed=60.0, step=6.0):
    for a, b in zip(points, points[1:]):
        bus.publish("gps.position", {"lat": b[0], "lon": b[1], "speed": speed,
                                     "heading": tr.bearing_deg(a, b), "fix": True})
        mod.tick()
        clock.advance(step)
    return points[-1]


def test_learned_route_keeps_only_incidents_on_it(tmp_path):
    db = tmp_path / "gps.db"
    route = _east_turn_route()
    _make_db(db, [route])
    corner = route[50]
    on_route = tr.destination(corner, 90.0, 2.0)          # after the turn east
    beside = tr.destination(corner, 0.0, 1.0)             # straight on: not our way
    answer = {"incidents": [raw_incident("on", 6, point=on_route, delay=900),
                            raw_incident("off", 6, point=beside, delay=900)]}
    bus, mod, clock, http, out = make(tmp_path, answer=answer,
                                      extra={"tracking": {"db_path": str(db)}})
    _drive_line(bus, mod, clock, route[:41])              # 4 km north
    status = out["status"][-1]
    assert status["mode"] == "learned"
    ids = [i["key"] for i in out["alerts"][-1]]
    assert ids == [tr.incident_key("on")]
    assert out["alerts"][-1][0]["on_route"] is True


def test_learning_off_uses_narrow_box(tmp_path):
    db = tmp_path / "gps.db"
    route = _east_turn_route()
    _make_db(db, [route])
    corner = route[50]
    beside = tr.destination(corner, 0.0, 1.0)
    answer = {"incidents": [raw_incident("off", 6, point=beside, delay=900)]}
    bus, mod, clock, http, out = make(tmp_path, answer=answer, block={"learn_routes": False},
                                      extra={"tracking": {"db_path": str(db)}})
    _drive_line(bus, mod, clock, route[:41], speed=100.0)
    assert out["status"][-1]["mode"] == "ahead"
    assert [i["key"] for i in out["alerts"][-1]] == [tr.incident_key("off")]


def test_unknown_road_lateral_and_town_reach(tmp_path):
    side = tr.destination(north(3.0), 90.0, 1.0)          # 1 km beside the line ahead
    far = north(6.5)                                      # straight ahead, 4.5 km away
    answer = {"incidents": [raw_incident("side", 6, point=side, delay=900),
                            raw_incident("far", 6, point=far, delay=900)]}
    bus, mod, clock, http, out = make(tmp_path, answer=answer)
    _drive_line(bus, mod, clock, _line(HOME, 0.0, 2.0), speed=50.0)   # town speed
    assert out["alerts"][-1] == []                        # side: lateral, far: 3 km reach
    assert ta.unknown_lookahead_km(50, 10) == 3.0
    assert ta.unknown_lookahead_km(100, 10) == 10.0
    assert ta.unknown_lookahead_km(None, 10) == 3.0


def test_minor_incident_toast_without_voice(tmp_path):
    bus, mod, clock, http, out = make(tmp_path, answer=jam_answer(delay=300))
    drive(bus, mod, clock, 40)
    assert notifs(bus) and out["voice"] == []
    bus2, mod2, clock2, _h, out2 = make(tmp_path / "b", answer=jam_answer(delay=300),
                                        block={"voice_min_delay_s": 240})
    drive(bus2, mod2, clock2, 40)
    assert len(out2["voice"]) == 1


def test_voice_worthy():
    assert tr.voice_worthy({"category": 8, "magnitude": 1, "delay_s": None}, 600)
    assert tr.voice_worthy({"category": 6, "magnitude": 3, "delay_s": 60}, 600)
    assert not tr.voice_worthy({"category": 6, "magnitude": 2, "delay_s": 300}, 600)
    assert tr.voice_worthy({"category": 6, "magnitude": 2, "delay_s": 600}, 600)
