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
