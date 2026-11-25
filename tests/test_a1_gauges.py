"""A1 side bars payload (web_viewer._a1_gauges): only fresh, real sources;
the refuel-log estimate as a fallback for fuel; "none" otherwise — never the
old payload defaults (fuel 50 %, coolant 0 °C)."""

from src.dashboard.web_viewer import (A1_COOLANT_FRESH_S, A1_FUEL_FRESH_S,
                                      _a1_gauges)

NOW = 1_800_000_000.0
LOG = {"running": True, "fuel_left_est_l": 29.0, "tank_capacity_l": 58.0}


def test_no_source_is_none():
    g = _a1_gauges(None, None, False, None, NOW)
    assert g == {"fuel": {"source": "none", "pct": None, "litres": None},
                 "coolant": {"source": "none", "c": None}}


def test_fresh_sensor_values():
    g = _a1_gauges((61.4, NOW - 5), (88.6, NOW - 1), False, LOG, NOW)
    assert g["fuel"] == {"source": "sensor", "pct": 61, "litres": None}
    assert g["coolant"] == {"source": "sensor", "c": 89}


def test_simulation_marks_demo():
    g = _a1_gauges((40, NOW), (70, NOW), True, None, NOW)
    assert g["fuel"]["source"] == "demo" and g["coolant"]["source"] == "demo"


def test_stale_sensor_falls_back_to_estimate():
    g = _a1_gauges((80, NOW - A1_FUEL_FRESH_S - 1),
                   (90, NOW - A1_COOLANT_FRESH_S - 1), False, LOG, NOW)
    assert g["fuel"] == {"source": "estimate", "pct": 50, "litres": 29.0}
    assert g["coolant"]["source"] == "none"


def test_estimate_needs_running_log_and_tank():
    for log in (None, {"running": False, "fuel_left_est_l": 10, "tank_capacity_l": 58},
                {"running": True, "fuel_left_est_l": None, "tank_capacity_l": 58},
                {"running": True, "fuel_left_est_l": 10, "tank_capacity_l": 0},
                {"running": True, "fuel_left_est_l": True, "tank_capacity_l": 58}):
        assert _a1_gauges(None, None, False, log, NOW)["fuel"]["source"] == "none", log


def test_garbage_and_out_of_range_rejected():
    bad = [("50", NOW), (True, NOW), (float("nan"), NOW), (150, NOW), (-1, NOW),
           (50, NOW + 10), (50, "x"), (50,), "50"]
    for last in bad:
        assert _a1_gauges(last, None, False, None, NOW)["fuel"]["source"] == "none", last
    for last in [(200, NOW), (-60, NOW), (float("inf"), NOW)]:
        assert _a1_gauges(None, last, False, None, NOW)["coolant"]["source"] == "none", last


def test_payload_has_a1_gauges():
    """Wired into /api/data: a fresh coolant reading shows, the fuel_level
    default of 50 never does."""
    from src.core.event_bus import EventBus
    from src.dashboard.web_viewer import WebViewer

    bus = EventBus()
    viewer = WebViewer(host="127.0.0.1", port=5099, event_bus=bus, config=None)
    data = viewer._get_dashboard_data()
    assert data["a1_gauges"]["fuel"]["source"] == "none"
    assert data["a1_gauges"]["coolant"]["source"] == "none"
    bus.publish("obd.coolant_temp", 91.2)
    data = viewer._get_dashboard_data()
    assert data["a1_gauges"]["coolant"] == {"source": "sensor", "c": 91}


# ── A5 / A7: data.live (web_viewer._live_metrics) ──────────────────────────

def _getter(values):
    return lambda topic: values.get(topic)


def test_live_metrics_empty_is_all_none():
    from src.dashboard.web_viewer import _live_metrics
    out = _live_metrics(_getter({}), False, NOW)
    assert out and all(v is None for v in out.values()), out


def test_live_metrics_sources_and_freshness():
    from src.dashboard.web_viewer import _live_metrics
    out = _live_metrics(_getter({
        "gps.speed": (72.4, NOW - 2),
        "obd.coolant_temp": (90, NOW - 600),          # stale
        "arduino.battery_voltage": (12.71, NOW - 5),
        "obd.battery_voltage": (13.9, NOW - 1),        # lower priority than batt
        "phone.g_force": ({"peak_h_g": 0.42, "calib_ok": True}, NOW - 1),
        "service.tpms_pressures": ([2.3, 2.3, 2.2, 2.2], NOW - 10),
        "performance.timer_result": (11.84, NOW - 99999),
    }), False, NOW)
    assert out["speed"] == {"v": 72.4, "src": "gps"}
    assert out["coolant"] is None
    assert out["battery_v"] == {"v": 12.71, "src": "batt"}
    assert out["g_h"] == {"v": 0.42, "src": "phone"}
    assert out["tpms"] == {"v": [2.3, 2.3, 2.2, 2.2], "src": "tpms"}
    assert out["timer_last"] == {"v": 11.8, "src": "gps"}


def test_live_metrics_rejects_placeholders_and_garbage():
    from src.dashboard.web_viewer import _live_metrics
    out = _live_metrics(_getter({
        "service.tpms_pressures": ([0, 0, 0, 0], NOW),   # the old default
        "phone.g_force": ({"peak_h_g": 0.5, "calib_ok": False}, NOW),
        "obd.rpm": ("900", NOW),
        "obd.speed": (float("nan"), NOW),
        "obd.boost": (True, NOW),
        "service.km_remaining": (4500, NOW + 60),         # timestamp in the future
    }), False, NOW)
    for k in ("tpms", "g_h", "rpm", "speed", "boost", "service_km"):
        assert out[k] is None, k


def test_live_metrics_obd_marked_demo_in_simulation():
    from src.dashboard.web_viewer import _live_metrics
    out = _live_metrics(_getter({"obd.rpm": (2200, NOW), "gps.speed": (50, NOW)}), True, NOW)
    assert out["rpm"]["src"] == "demo"
    assert out["speed"]["src"] == "gps", "GPS is real even with the simulator on"
