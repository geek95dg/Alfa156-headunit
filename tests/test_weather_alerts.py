"""Weather warnings (modules.weather_alerts).

* src/weather/alerts.py — the rule engine: one table row per kind and
  boundary, mild weather gives nothing, one alert per kind (the most
  severe, "teraz" before later), route points, untrusted input, Polish
  speakable text; config loading; AlertAnnouncer dedupe / escalation /
  cooldown with a fake clock; voice and quiet hours.
* src/audio/announce_api.py — the voice.announce contract.
* src/weather/weather_alerts.py — the runtime on a real EventBus with a
  fake WeatherManager: demo data never warns, weather.alert, notification
  dedupe (key weather_<kind>), voice requests, GPS / route forecasts.
* web_viewer / small_viewer / weather.py glue.
"""

import time

import pytest

from src.audio import announce_api
from src.core.event_bus import EventBus
from src.core.notifications import TOPIC as NOTIF_TOPIC
from src.weather import alerts as al
from src.weather import weather_alerts as wa

NOW = 1_800_000_000.0


class FakeClock:
    def __init__(self, t=5000.0):
        self.t = t

    def __call__(self):
        return self.t

    def advance(self, seconds):
        self.t += seconds


def cur(**kw):
    """weather.current as WeatherManager publishes it (wind in km/h)."""
    base = {"condition": "Clouds", "icon": "04d", "temp": 12.0, "feels_like": 11.0,
            "humidity": 60, "wind_speed": 10.0, "wind_deg": 180, "pressure": 1015,
            "weather_id": 803, "rain_1h": None, "snow_1h": None, "gust_kmh": None,
            "visibility_m": 10000}
    base.update(kw)
    return base


def slot(hours, **kw):
    """A 3-hour slot ``hours`` from NOW (weather.py _parse_slots keys)."""
    base = {"ts": int(NOW + hours * 3600), "temp": 12.0, "humidity": 60, "weather_id": 803,
            "icon": "04d", "rain_mm": 0.0, "snow_mm": 0.0, "wind_kmh": 10.0, "gust_kmh": 15.0,
            "visibility_m": 10000}
    base.update(kw)
    return base


def kinds(alerts):
    return {a["kind"]: a["severity"] for a in alerts}


def ev(current=None, slots=(), **kw):
    return al.evaluate(current, slots, now=NOW, **kw)


# ── the rule table ──────────────────────────────────────────────────────

RULES = [
    # (id, current, expected {kind: severity} — only the kinds listed are checked)
    ("mild", cur(), {}),
    # icing
    ("freezing rain 511 at +4", cur(temp=4.0, weather_id=511), {"icing": "danger"}),
    ("rain at 0", cur(temp=0.0, weather_id=500, humidity=95), {"icing": "danger"}),
    ("drizzle at -2", cur(temp=-2.0, weather_id=300), {"icing": "danger"}),
    ("rain at 0.5", cur(temp=0.5, weather_id=500), {"icing": "warning"}),
    ("rain at 2.0", cur(temp=2.0, weather_id=500), {"icing": "warning"}),
    ("rain at 2.1", cur(temp=2.1, weather_id=500), {"icing": None}),
    ("rain_1h only at 1", cur(temp=1.0, rain_1h=0.4), {"icing": "warning"}),
    ("snow at 1", cur(temp=1.0, weather_id=600), {"icing": "warning", "snow": "warning"}),
    ("mist at 1", cur(temp=1.0, weather_id=701, humidity=70), {"icing": "warning"}),
    ("humidity 90 at 2", cur(temp=2.0, humidity=90), {"icing": "warning"}),
    ("humidity 89 at 2", cur(temp=2.0, humidity=89), {"icing": None}),
    ("humidity 95 at 2.5", cur(temp=2.5, humidity=95), {"icing": None}),
    ("dry cold -5", cur(temp=-5.0, humidity=60, weather_id=800, icon="01d"), {"icing": None}),
    ("cold surface night 2.5", cur(temp=2.5, humidity=60, weather_id=800, icon="01n"),
     {"icing": "info"}),
    ("cold surface night 3.0", cur(temp=3.0, humidity=60, weather_id=801, icon="02n"),
     {"icing": "info"}),
    ("cold surface 3.1", cur(temp=3.1, humidity=60, weather_id=800, icon="01n"), {"icing": None}),
    ("clear day 2.5", cur(temp=2.5, humidity=60, weather_id=800, icon="01d"), {"icing": None}),
    ("clear night -1", cur(temp=-1.0, humidity=60, weather_id=800, icon="01n"), {"icing": None}),
    ("cloudy night 2.5", cur(temp=2.5, humidity=60, weather_id=804, icon="04n"),
     {"icing": None}),
    # snow
    ("light snow", cur(temp=-3, weather_id=600), {"snow": "warning"}),
    ("heavy snow 602", cur(temp=-3, weather_id=602), {"snow": "danger"}),
    ("snow 1h 1.0 = 3 mm/3h", cur(temp=-3, snow_1h=1.0), {"snow": "danger"}),
    ("snow 1h 0.9", cur(temp=-3, snow_1h=0.9), {"snow": "warning"}),
    # rain
    ("rain 1h 3.3 = 9.9/3h", cur(rain_1h=3.3, weather_id=501), {"rain": None}),
    ("rain 1h 3.34 ≥ 10/3h", cur(rain_1h=3.34, weather_id=501), {"rain": "warning"}),
    ("rain 1h 6.67 ≥ 20/3h", cur(rain_1h=6.67, weather_id=501), {"rain": "danger"}),
    ("heavy rain 502", cur(weather_id=502), {"rain": "warning"}),
    ("extreme rain 504", cur(weather_id=504), {"rain": "danger"}),
    ("moderate rain 501", cur(weather_id=501), {"rain": None}),
    # storm
    ("thunderstorm 211", cur(weather_id=211), {"storm": "warning"}),
    ("heavy thunderstorm 212", cur(weather_id=212), {"storm": "danger"}),
    ("storm with rain 201", cur(weather_id=201), {"storm": "warning"}),
    # wind (km/h in weather.current; thresholds in m/s)
    ("gust 54 km/h = 15 m/s", cur(gust_kmh=54.0), {"wind": "warning"}),
    ("gust 53.9 km/h", cur(gust_kmh=53.9), {"wind": None}),
    ("gust 90 km/h = 25 m/s", cur(gust_kmh=90.0), {"wind": "danger"}),
    ("wind 50.4 km/h = 14 m/s", cur(wind_speed=50.4), {"wind": "warning"}),
    ("wind 50 km/h", cur(wind_speed=50.0), {"wind": None}),
    # fog
    ("fog 741", cur(weather_id=741, visibility_m=None), {"fog": "warning"}),
    ("visibility 199", cur(visibility_m=199), {"fog": "warning"}),
    ("visibility 200", cur(visibility_m=200), {"fog": None}),
    ("visibility 49", cur(visibility_m=49), {"fog": "danger"}),
    ("visibility 50", cur(visibility_m=50), {"fog": "warning"}),
    ("mist 701 good visibility", cur(weather_id=701, visibility_m=3000), {"fog": None}),
]


@pytest.mark.parametrize("name,current,expected", RULES, ids=[r[0] for r in RULES])
def test_rule_table(name, current, expected):
    got = kinds(ev(current))
    if not expected:
        assert got == {}, got
    for kind, severity in expected.items():
        assert got.get(kind) == severity, (name, got)


def test_mild_weather_with_forecast_gives_nothing():
    slots = [slot(h, temp=10 + h) for h in (1, 4, 7, 10)]
    assert ev(cur(), slots) == []


def test_alert_shape_and_polish_speakable_text():
    [a] = ev(cur(temp=-1.4, weather_id=500))
    assert set(a) == {"id", "kind", "severity", "title", "text", "where", "valid_until", "eta_min"}
    assert a["id"] == "weather_icing" and a["where"] == "teraz"
    assert a["title"] == "Gołoledź"
    assert "minus 1 stopień" in a["text"] and "°" not in a["text"] and "~" not in a["text"]
    assert a["valid_until"] == pytest.approx(NOW + al.CURRENT_VALID_S)


def test_forecast_slot_where_and_text():
    [a] = ev(cur(), [slot(2, weather_id=212)])
    assert a["kind"] == "storm" and a["severity"] == "danger"
    assert a["where"] == "za ~2 h"
    assert "za około 2 godziny" in a["text"]
    assert a["valid_until"] == pytest.approx(NOW + 2 * 3600 + al.SLOT_VALID_S, abs=1)
    [a] = ev(cur(), [slot(5, weather_id=211)])
    assert a["where"] == "za ~5 h" and "za około 5 godzin" in a["text"]
    # A slot within 90 min of now is "teraz".
    [a] = ev(cur(), [slot(1.4, weather_id=211)])
    assert a["where"] == "teraz"


def test_lookahead_and_past_slots():
    assert ev(None, [slot(6, weather_id=211)])            # default lookahead 6 h
    assert ev(None, [slot(6.1, weather_id=211)]) == []
    assert ev(None, [slot(-1.4, weather_id=211)])         # current 3-hour period
    assert ev(None, [slot(-1.6, weather_id=211)]) == []
    # With current conditions a past slot does not count (OWM rain.3h is
    # the 3 h ENDING at dt: that rain may be over).
    assert ev(cur(), [slot(-0.5, weather_id=502, rain_mm=25.0)]) == []


def test_crossing_ignores_a_past_slot():
    slots = [slot(-0.5, temp=-1.0), slot(2, temp=-1.0, humidity=70, weather_id=800,
                                         icon="01n")]
    [a] = ev(cur(temp=3.0, weather_id=500), slots)
    assert (a["kind"], a["severity"], a["where"]) == ("icing", "warning", "za ~2 h")


def test_spoken_texts_match_the_trigger():
    [a] = ev(cur(wind_speed=55.0))                        # mean wind only, no gust
    assert a["kind"] == "wind" and a["text"].startswith("Silny wiatr do")
    [a] = ev(cur(gust_kmh=60.0))
    assert a["text"].startswith("Porywy wiatru do")
    [a] = ev(cur(weather_id=741))                         # code only, no visibility
    assert a["kind"] == "fog" and "widoczność" not in a["text"]
    [a] = ev(cur(visibility_m=150))
    assert "widoczność poniżej 200 metrów" in a["text"]
    cfg = al.load_config({"lookahead_h": 12})
    assert ev(None, [slot(11, weather_id=211)], cfg=cfg)


def test_one_alert_per_kind_most_severe_then_soonest():
    slots = [slot(2, gust_kmh=60.0), slot(5, gust_kmh=95.0)]
    [a] = ev(cur(gust_kmh=55.0), slots)
    assert a["severity"] == "danger" and a["where"] == "za ~5 h"
    [a] = ev(cur(gust_kmh=55.0), [slot(3, gust_kmh=60.0)])
    assert a["where"] == "teraz"                          # tie → the current one
    out = ev(cur(temp=0.0, weather_id=500, gust_kmh=60.0, visibility_m=150))
    assert [x["kind"] for x in out] == ["icing", "wind", "fog"]   # danger first, then kind order


def test_crossing_zero_after_rain():
    slots = [slot(2, temp=-1.0, humidity=70, weather_id=800, icon="01n")]
    # Raining now at 3 °C, below 0 in 2 h → warning "za ~2 h".
    [a] = ev(cur(temp=3.0, weather_id=500), slots)
    assert (a["kind"], a["severity"], a["where"]) == ("icing", "warning", "za ~2 h")
    assert "spadnie poniżej zera" in a["text"]
    # Dry: nothing.
    assert ev(cur(temp=3.0, humidity=60), slots) == []
    # It rained earlier (the runtime remembers it).
    assert kinds(ev(cur(temp=3.0, humidity=60), slots, recent_rain=True)) == {"icing": "warning"}
    # Crossing beyond 3 h does not count.
    late = [slot(4, temp=-1.0, humidity=70, weather_id=800, icon="01d")]
    assert ev(cur(temp=3.0, weather_id=500), late) == []
    # Rain forecast before the crossing counts as "after rain".
    wet = [slot(1.6, temp=1.5, weather_id=500, humidity=80),
           slot(2.9, temp=-0.5, humidity=70, weather_id=800, icon="01n")]
    assert kinds(ev(cur(temp=4.0), wet)).get("icing") == "warning"


def test_categories_switch_kinds_off():
    cfg = al.load_config({"categories": {"wind": False, "icing": False}})
    out = ev(cur(temp=0.0, weather_id=500, gust_kmh=95.0), cfg=cfg)
    assert kinds(out) == {}
    cfg = al.load_config({"categories": {"wind": False}})
    assert kinds(ev(cur(gust_kmh=95.0, weather_id=741), cfg=cfg)) == {"fog": "warning"}


def test_route_points():
    route = [(slot(3, weather_id=602, temp=-4.0), 130.0)]
    a, ice = ev(cur(), (), route=route)                   # snow at -4 is also icing
    assert (a["kind"], a["severity"], a["where"]) == ("snow", "danger", "na trasie")
    assert (ice["kind"], ice["severity"], ice["where"]) == ("icing", "warning", "na trasie")
    assert a["eta_min"] == 130.0
    # Same severity here and on the route → "here" wins.
    [a] = ev(cur(gust_kmh=60.0), (), route=[(slot(1, gust_kmh=60.0), 40.0)])
    assert a["where"] == "teraz"
    # route: false in the config → ignored; malformed entries are skipped.
    assert ev(cur(), (), route=route, cfg=al.load_config({"route": False})) == []
    assert ev(cur(), (), route=[None, (1,), ("x", 5), (slot(1), "x")]) == []


@pytest.mark.parametrize("bad", [
    None, "x", 5, [], {"temp": "1"}, {"temp": float("nan")}, {"temp": True},
    {"temp": 10 ** 400}, {"temp": -1, "weather_id": "500"}, {"weather_id": 10 ** 400},
    {"temp": 1, "humidity": -5, "icon": "<b>"}, {"temp": 1e308, "gust_kmh": float("inf")},
])
def test_untrusted_input_never_raises(bad):
    ev(bad, [bad, {"ts": "x"}, {"ts": NOW, "temp": None}, bad])
    ev(None, (), route=[(bad, 10.0)])


def test_plural_helpers():
    assert al.degrees_text(1) == "1 stopień"
    assert al.degrees_text(2.4) == "2 stopnie"
    assert al.degrees_text(5) == "5 stopni"
    assert al.degrees_text(-1.2) == "minus 1 stopień"
    assert al.degrees_text(-3) == "minus 3 stopnie"
    assert al.degrees_text(12) == "12 stopni"
    assert al.degrees_text(22) == "22 stopnie"
    assert al.degrees_text(0) == "0 stopni"
    assert al.hours_text(1) == "za około 1 godzinę"
    assert al.hours_text(3) == "za około 3 godziny"
    assert al.hours_text(5) == "za około 5 godzin"
    assert al.hours_text(0) == "za około 1 godzinę"


def test_dew_point():
    assert al.dew_point(20.0, 50.0) == pytest.approx(9.3, abs=0.2)
    assert al.dew_point(1.0, 100.0) == pytest.approx(1.0, abs=0.01)
    assert al.dew_point(1.0, 0) is None
    # Dew-point rule on its own (humidity rule moved out of the way).
    cfg = al.load_config({"icing_humidity_pct": 100})
    assert kinds(ev(cur(temp=1.0, humidity=94), cfg=cfg)) == {"icing": "warning"}
    assert kinds(ev(cur(temp=1.0, humidity=90), cfg=cfg)) == {}


# ── configuration ───────────────────────────────────────────────────────

def test_config_defaults_and_bounds():
    cfg = al.load_config(None)
    assert cfg == al.AlertConfig()
    assert (cfg.lookahead_h, cfg.cooldown_min, cfg.gust_ms) == (6.0, 60.0, 15.0)
    warnings = []
    cfg = al.load_config({"lookahead_h": 0, "cooldown_min": "x", "gust_ms": True,
                          "fog_visibility_m": float("nan"), "heavy_rain_mm_3h": 25,
                          "categories": {"wind": "no", "bogus": True, "fog": False},
                          "voice_min_severity": "loud", "quiet_hours": "25:00-6"},
                         warn=warnings.append)
    assert (cfg.lookahead_h, cfg.cooldown_min, cfg.gust_ms) == (6.0, 60.0, 15.0)
    assert cfg.fog_visibility_m == 200.0 and cfg.heavy_rain_mm_3h == 25.0
    assert cfg.enabled("wind") and not cfg.enabled("fog") and not cfg.enabled("bogus")
    assert cfg.voice_min_severity == "warning" and cfg.quiet_hours is None
    assert len(warnings) == 8, warnings
    cfg = al.load_config({"gust_ms": 30, "gust_danger_ms": 20}, warn=warnings.append)
    assert cfg.gust_danger_ms == 30
    assert al.load_config({"categories": "all"}).categories == {k: True for k in al.KINDS}


def test_quiet_hours():
    assert al.parse_quiet_hours("22:00-06:00") == (1320, 360)
    assert al.parse_quiet_hours(" 1:30 - 5:00 ") == (90, 300)
    for bad in ("", None, "22-6", "24:00-06:00", "10:00-10:00", 5):
        assert al.parse_quiet_hours(bad) is None
    q = (1320, 360)
    assert al.in_quiet_hours(q, 23 * 60) and al.in_quiet_hours(q, 0) and al.in_quiet_hours(q, 359)
    assert not al.in_quiet_hours(q, 360) and not al.in_quiet_hours(q, 12 * 60)
    q = (60, 300)
    assert al.in_quiet_hours(q, 60) and not al.in_quiet_hours(q, 300)
    assert not al.in_quiet_hours(None, 0)


# ── announcer: dedupe, escalation, cooldown ─────────────────────────────

def _a(kind, severity):
    return {"kind": kind, "severity": severity, "title": "t", "text": "x", "where": "teraz",
            "valid_until": NOW + 3600}


def test_announcer_dedupe_escalation_cooldown():
    clock = FakeClock()
    ann = al.AlertAnnouncer(al.load_config({"cooldown_min": 60}), clock=clock)
    assert len(ann.due([_a("icing", "info")])) == 1          # new
    assert ann.due([_a("icing", "info")]) == []              # still active
    clock.advance(60)
    assert len(ann.due([_a("icing", "warning")])) == 1       # escalation
    assert ann.due([_a("icing", "info")]) == []              # de-escalation: silent
    assert ann.due([_a("icing", "warning")]) == []           # back to the announced level
    assert len(ann.due([_a("icing", "danger")])) == 1        # escalates again
    assert len(ann.due([_a("wind", "warning")])) == 1        # other kinds independent
    assert ann.due([]) == []                                 # gone…
    clock.advance(30 * 60)
    assert ann.due([_a("icing", "danger")]) == []            # …back within the cooldown
    clock.advance(30 * 60)
    assert len(ann.due([_a("icing", "warning")])) == 1       # after the cooldown
    assert ann.due([_a("bogus", "danger"), _a("fog", "loud"), {}]) == []


def test_announcer_clock_backwards_reannounces():
    clock = FakeClock(10_000)
    ann = al.AlertAnnouncer(al.AlertConfig(), clock=clock)
    ann.due([_a("fog", "warning")])
    clock.t = 100                                            # clock reset (never with monotonic)
    assert len(ann.due([_a("fog", "warning")])) == 1


def test_voice_rules():
    cfg = al.load_config({"quiet_hours": "22:00-06:00"})
    ann = al.AlertAnnouncer(cfg, clock=FakeClock())
    noon, night = 12 * 60, 23 * 60
    assert ann.speak(_a("wind", "warning"), noon)
    assert not ann.speak(_a("wind", "warning"), night)       # quiet hours
    assert ann.speak(_a("icing", "danger"), night)           # danger even then
    assert not ann.speak(_a("icing", "info"), noon)          # below voice_min_severity
    ann = al.AlertAnnouncer(al.load_config({"voice_min_severity": "info"}), clock=FakeClock())
    assert ann.speak(_a("icing", "info"), noon)
    ann = al.AlertAnnouncer(al.load_config({"voice": False}), clock=FakeClock())
    assert not ann.speak(_a("icing", "danger"), noon)


# ── voice.announce contract ─────────────────────────────────────────────

def test_announce_request_contract():
    req = announce_api.make_request("weather", "Gołoledź.\nJedź\x00 ostrożnie", priority="high",
                                    key="weather_icing", ttl_s=99999, now=NOW)
    assert req["category"] == "weather" and req["priority"] == "high"
    assert req["text"] == "Gołoledź. Jedź ostrożnie"
    assert req["key"] == "weather_icing"
    assert req["expires_ts"] == NOW + announce_api.MAX_TTL_S
    assert announce_api.validate_request(req, now=NOW + 10) == req
    assert announce_api.validate_request(req, now=req["expires_ts"] + 1) is None
    assert announce_api.make_request("music", "x") is None
    assert announce_api.make_request("weather", "   ") is None
    r = announce_api.make_request("weather", "x" * 1000, priority="urgent", key="Bad Key!",
                                  ttl_s=float("nan"), now=NOW)
    assert len(r["text"]) == announce_api.MAX_TEXT and r["priority"] == "normal"
    assert r["key"] == "" and r["expires_ts"] == NOW + announce_api.DEFAULT_TTL_S
    for bad in (None, "x", {**req, "category": "x"}, {**req, "id": "<script>"},
                {**req, "text": 5}, {**req, "expires_ts": NOW + 10 ** 6},
                {**req, "ts": "x"}, {**req, "priority": "max"}):
        assert announce_api.validate_request(bad, now=NOW) is None, bad


def test_request_announcement_publishes():
    bus = EventBus()
    got = []
    bus.subscribe(announce_api.TOPIC, lambda t, v, ts: got.append(v))
    req = announce_api.request_announcement(bus, "weather", "Burza", key="weather_storm")
    assert got == [req]
    assert announce_api.request_announcement(None, "weather", "x") is None
    assert announce_api.request_announcement(bus, "nope", "x") is None and len(got) == 1


# ── runtime ─────────────────────────────────────────────────────────────

class FakeManager:
    def __init__(self, slots=(), coords=(50.06, 19.94)):
        self._slots = list(slots)
        self._coords = coords
        self.calls = []
        self.route = {}

    @property
    def slots(self):
        return [dict(s) for s in self._slots], self._coords

    def forecast_at(self, lat, lon, eta_min=0.0):
        self.calls.append((lat, lon, eta_min))
        key = (round(lat, 2), round(lon, 2))
        if key in self.route:
            out = dict(self.route[key])
            out["slot_ts"] = out.pop("ts")
            return out
        target = NOW + eta_min * 60
        best = min(self._slots, key=lambda s: abs(s["ts"] - target), default=None)
        if best is None or abs(best["ts"] - target) > 3 * 3600:
            return None
        out = dict(best)
        out["slot_ts"] = out.pop("ts")
        return out


class Cfg:
    def __init__(self, **block):
        self._block = block

    def get(self, key, default=None):
        return self._block if key == "weather_alerts" else default


def make(manager=None, status="live", current=None, block=None, localtime=None):
    bus = EventBus()
    clock = FakeClock()
    if status is not None:
        bus.publish("weather.status", {"source": status})
    if manager is not None:
        bus.publish("weather._internals", {"manager": manager})
    if current is not None:
        bus.publish("weather.current", current)
    mod = wa.WeatherAlerts(bus, Cfg(**(block or {})), clock=clock, wall=lambda: NOW,
                           localtime=localtime or (lambda t: time.struct_time(
                               (2026, 11, 23, 12, 0, 0, 0, 327, 0))))
    voice, alerts = [], []
    bus.subscribe(announce_api.TOPIC, lambda t, v, ts: voice.append(v))
    bus.subscribe(wa.TOPIC, lambda t, v, ts: alerts.append(v))
    return bus, mod, clock, voice, alerts


@pytest.fixture(autouse=True)
def bus_time(monkeypatch):
    """EventBus stamps get_last() with time.time(); make that NOW."""
    monkeypatch.setattr("src.core.event_bus.time.time", lambda: NOW)


def _notifs(bus):
    last = bus.get_last(NOTIF_TOPIC)
    return last[0] if last else []


def test_demo_or_missing_status_never_warns():
    icy = cur(temp=0.0, weather_id=500)
    for status in ("demo", None):
        bus, mod, _c, voice, alerts = make(FakeManager(), status=status, current=icy)
        assert mod.evaluate_once() == []
        assert voice == [] and _notifs(bus) == []


def test_alert_notification_voice_and_dedupe():
    bus, mod, clock, voice, alerts = make(FakeManager(), current=cur(temp=0.0, weather_id=500))
    out = mod.evaluate_once()
    assert kinds(out) == {"icing": "danger"}
    assert alerts == [out]
    [n] = _notifs(bus)
    assert n["key"] == "weather_icing" and n["severity"] == "danger" and n["icon"] == "ac_unit"
    assert n["title"] == "Gołoledź" and "stopni" in n["desc"]
    [v] = voice
    assert v["category"] == "weather" and v["priority"] == "high" and v["key"] == "weather_icing"
    assert v["text"].startswith("Gołoledź. Marznący opad")
    assert announce_api.validate_request(v, now=NOW) == v
    # Same weather again: no new toast, no new voice, weather.alert not republished.
    first_id = n["id"]
    clock.advance(600)
    mod.evaluate_once()
    assert [x["id"] for x in _notifs(bus)] == [first_id]
    assert len(voice) == 1 and len(alerts) == 1
    # After the cooldown: announced again (replacing the old toast, same key).
    clock.advance(3600)
    mod.evaluate_once()
    notifs = _notifs(bus)
    assert len(notifs) == 1 and notifs[0]["id"] != first_id
    assert len(voice) == 2


def test_escalation_reannounces_within_cooldown():
    bus, mod, clock, voice, _a = make(FakeManager(), current=cur(gust_kmh=60.0))
    mod.evaluate_once()
    assert len(voice) == 1 and voice[0]["priority"] == "normal"
    bus.publish("weather.current", cur(gust_kmh=100.0))
    clock.advance(60)
    out = mod.evaluate_once()
    assert kinds(out) == {"wind": "danger"}
    assert len(voice) == 2 and voice[1]["priority"] == "high"
    assert _notifs(bus)[-1]["severity"] == "danger" and len(_notifs(bus)) == 1


def test_info_is_a_toast_only_and_quiet_hours_mute_warnings():
    night = cur(temp=2.0, humidity=60, weather_id=800, icon="01n")
    bus, mod, *_rest = make(FakeManager(), current=night)
    voice = _rest[1]
    assert kinds(mod.evaluate_once()) == {"icing": "info"}
    assert len(_notifs(bus)) == 1 and voice == []
    at_23 = lambda t: time.struct_time((2026, 11, 23, 23, 10, 0, 0, 327, 0))  # noqa: E731
    bus, mod, _c, voice, _a = make(FakeManager(), current=cur(gust_kmh=60.0),
                                   block={"quiet_hours": "22:00-06:00"}, localtime=at_23)
    mod.evaluate_once()
    assert len(_notifs(bus)) == 1 and voice == []
    bus, mod, _c, voice, _a = make(FakeManager(), current=cur(gust_kmh=100.0),
                                   block={"quiet_hours": "22:00-06:00"}, localtime=at_23)
    mod.evaluate_once()
    assert len(voice) == 1                       # danger is spoken even then


def test_alert_cleared_publishes_empty_list():
    bus, mod, _c, _v, alerts = make(FakeManager(), current=cur(weather_id=741))
    mod.evaluate_once()
    bus.publish("weather.current", cur())
    mod.evaluate_once()
    assert [len(a) for a in alerts] == [1, 0]


def test_stale_current_is_ignored(monkeypatch):
    bus, mod, *_ = make(FakeManager())
    monkeypatch.setattr("src.core.event_bus.time.time", lambda: NOW - wa.CURRENT_MAX_AGE_S - 1)
    bus.publish("weather.current", cur(weather_id=741))
    assert mod.evaluate_once() == []


def test_current_for_a_far_place_is_not_teraz():
    bus, mod, *_ = make(FakeManager(), current=cur(weather_id=741))
    bus.publish("weather.lat", 50.06)
    bus.publish("weather.lon", 19.94)
    bus.publish("gps.position", {"lat": 50.2, "lon": 20.0, "fix": True})   # ~16 km
    assert kinds(mod.evaluate_once()) == {"fog": "warning"}
    bus.publish("gps.position", {"lat": 52.23, "lon": 21.01, "fix": True})  # searched Kraków, car in Warsaw
    assert mod.evaluate_once() == []


def test_without_weather_module_warns_once_and_uses_current(caplog):
    bus, mod, *_ = make(None, current=cur(weather_id=741))
    with caplog.at_level("WARNING"):
        assert kinds(mod.evaluate_once()) == {"fog": "warning"}
        mod.evaluate_once()
    assert sum("moduł weather nie działa" in r.getMessage() for r in caplog.records) == 1


def test_slots_without_gps_and_forecast_at_with_gps():
    manager = FakeManager([slot(2, weather_id=212), slot(5, temp=8.0)])
    bus, mod, *_ = make(manager, current=cur())
    [a] = mod.evaluate_once()
    assert (a["kind"], a["where"]) == ("storm", "za ~2 h")
    assert manager.calls == []                           # no fix: the manager's slots
    bus.publish("gps.position", {"lat": 52.23, "lon": 21.01, "fix": True})
    mod.evaluate_once()
    assert [c[:2] for c in manager.calls] == [(52.23, 21.01)] * 3
    assert [c[2] for c in manager.calls] == [0.0, 180.0, 360.0]
    # A 0,0 "fix" is no fix.
    manager.calls.clear()
    bus.publish("gps.position", {"lat": 0.0, "lon": 0.0})
    mod.evaluate_once()
    assert manager.calls == []


def test_route_ahead():
    manager = FakeManager([slot(1)])
    manager.route[(51.0, 20.0)] = slot(2, weather_id=602, temp=-3.0)
    bus, mod, *_ = make(manager, current=cur())
    plan = {"waypoints": [{"lat": 50.0, "lon": 19.9}, {"lat": 51.0, "lon": 20.0},
                          {"lat": 52.0, "lon": 21.0}],
            "eta_min": 240.0, "computed_at": NOW - 30 * 60}
    bus.publish("trip.route", plan)
    assert mod.evaluate_once() == []                      # no destination → no route
    bus.publish("trip.destination", {"lat": 52.0, "lon": 21.0, "name": "X"})
    a = mod.evaluate_once()[0]
    assert (a["kind"], a["severity"], a["where"]) == ("snow", "danger", "na trasie")
    route_calls = [c for c in manager.calls if c[:2] != (50.0, 19.9)]
    assert route_calls[0] == (51.0, 20.0, 90.0)          # 120 min ETA − 30 min elapsed
    assert route_calls[1] == (52.0, 21.0, 210.0)
    # An old plan is not "the route ahead".
    manager.calls.clear()
    bus.publish("trip.route", {**plan, "computed_at": NOW - wa.ROUTE_MAX_AGE_S - 1})
    assert mod.evaluate_once() == [] and manager.calls == []
    # route: false.
    bus2, mod2, *_ = make(manager, current=cur(), block={"route": False})
    bus2.publish("trip.destination", {"lat": 52.0})
    bus2.publish("trip.route", plan)
    assert mod2.evaluate_once() == []


def test_route_from_the_real_trip_computer_payload():
    """trip.route is TripComputer.get_plan_dict() — a key rename there
    (e.g. eta_min) must not silently switch route warnings off."""
    from src.dashboard.trip_computer import TripComputer
    tc = TripComputer()
    tc.route_eta_min = 240.0
    tc.route_waypoints = [{"lat": 50.0, "lon": 19.9}, {"lat": 51.0, "lon": 20.0},
                          {"lat": 52.0, "lon": 21.0}]
    tc.plan_computed_at = NOW - 30 * 60
    manager = FakeManager([slot(1)])
    manager.route[(51.0, 20.0)] = slot(2, weather_id=602, temp=-3.0)
    bus, mod, *_ = make(manager, current=cur())
    bus.publish("trip.destination", {"lat": 52.0, "lon": 21.0, "name": "X"})
    bus.publish("trip.route", tc.get_plan_dict())
    a = mod.evaluate_once()[0]
    assert (a["kind"], a["severity"], a["where"]) == ("snow", "danger", "na trasie")
    # A cleared plan (eta_min 0, computed_at 0) asks for nothing.
    manager.calls.clear()
    tc.route_eta_min, tc.plan_computed_at = 0.0, 0.0
    bus.publish("trip.route", tc.get_plan_dict())
    assert mod.evaluate_once() == [] and manager.calls == []


def test_weather_alert_not_republished_when_only_valid_until_drifts():
    bus, mod, *_ = make(FakeManager([]), current=cur(weather_id=741))
    seen = []
    bus.subscribe(wa.TOPIC, lambda t, v, ts: seen.append(v))
    mod.evaluate_once()
    mod._wall = lambda: NOW + 60          # valid_until moves on, nothing else
    mod.evaluate_once()
    assert len(seen) == 1
    # Close to expiry of the published list → republished (fresh valid_until).
    mod._wall = lambda: NOW + 3500
    mod._current = lambda now: cur(weather_id=741)
    mod.evaluate_once()
    assert len(seen) == 2 and seen[-1][0]["valid_until"] > NOW + 3600


def test_garbage_route_and_manager_errors_do_not_crash():
    class Broken(FakeManager):
        def forecast_at(self, *a):
            raise RuntimeError("boom")

        @property
        def slots(self):
            raise RuntimeError("boom")

    bus, mod, *_ = make(Broken(), current=cur(weather_id=741))
    bus.publish("trip.destination", {"x": 1})
    for plan in ("x", {"waypoints": "x"}, {"waypoints": [1, 2], "eta_min": "x"},
                 {"waypoints": [None, None], "eta_min": 10, "computed_at": NOW}):
        bus.publish("trip.route", plan)
        assert kinds(mod.evaluate_once()) == {"fog": "warning"}
    bus.publish("gps.position", {"lat": 50.0, "lon": 20.0})
    assert kinds(mod.evaluate_once()) == {"fog": "warning"}


def test_start_stop_thread():
    bus = EventBus()
    mod = wa.start_weather_alerts(Cfg(), bus)
    try:
        assert mod._thread.is_alive()
        bus.publish("weather.lon", 21.0)             # wakes the loop, nothing to say
    finally:
        mod.stop()
    assert not mod._thread.is_alive()


# ── glue ────────────────────────────────────────────────────────────────

def test_catalog_entry():
    from src.core.modules_catalog import MODULES
    e = MODULES["weather_alerts"]
    assert e["entry"] == ("src.weather.weather_alerts", "start_weather_alerts")
    assert e["requires"] == ("weather",) and e["default"] is False


def test_web_viewer_summary_sanitises():
    from src.dashboard import web_viewer as wv
    assert wv._weather_alerts_summary(None) is None
    assert wv._weather_alerts_summary("x") is None
    good = {"kind": "fog", "severity": "warning", "title": "Mgła\x00<b>", "where": "teraz",
            "text": "x" * 500, "valid_until": NOW + 60}
    out = wv._weather_alerts_summary([good, {**good, "kind": "<x>"}, {**good, "severity": "x"},
                                      {**good, "valid_until": NOW - 1}, {**good, "valid_until": "x"},
                                      None, 5] + [good] * 10, now=NOW)
    assert len(out) == wv._ALERTS_MAX
    assert out[0] == {"kind": "fog", "severity": "warning", "title": "Mgła <b>", "where": "teraz",
                      "text": "x" * 200, "valid_until": NOW + 60}


def test_weather_current_extras():
    from src.weather.weather import WeatherManager
    raw = {"wind": {"gust": 20}, "rain": {"1h": 2.5}, "snow": {"1h": "x"}, "visibility": 150}
    assert WeatherManager._current_extras(raw, {"id": 741}) == {
        "weather_id": 741, "rain_1h": 2.5, "snow_1h": None, "gust_kmh": 72.0, "visibility_m": 150}
    assert WeatherManager._current_extras({"wind": [], "visibility": True}, None) == {
        "weather_id": None, "rain_1h": None, "snow_1h": None, "gust_kmh": None,
        "visibility_m": None}


def test_small_viewer_shows_the_first_alert_title():
    import inspect
    from src.dashboard import small_viewer
    src = inspect.getsource(small_viewer)
    assert 'str(weather_alert)' not in src
    # Expired entries are skipped like on the big dashboard (the module may
    # have stopped and left its last list on the bus).
    assert "_weather_alerts_summary(weather_alert)" in src
