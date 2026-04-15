"""Unit tests for src.trip.route_planner pure helpers.

These tests intentionally avoid touching the network or any real
API keys — they exercise only the side-effect-free functions
(`estimate_fuel`, `sample_waypoints`, `_haversine_km`,
`_bounding_box`) and a minimal stubbed RoutePlanner to make sure
the straight-line fallback returns a plausible plan when no ORS
key is configured.
"""

from __future__ import annotations

import math

from src.trip.route_planner import (
    RoutePlanner,
    estimate_fuel,
    sample_waypoints,
    _haversine_km,
    _bounding_box,
    WAYPOINT_COUNT,
)


# ---------------------------------------------------------------------- #
# estimate_fuel                                                          #
# ---------------------------------------------------------------------- #


def test_estimate_fuel_zero_distance():
    assert estimate_fuel(0.0, 7.0) == 0.0


def test_estimate_fuel_basic():
    assert estimate_fuel(100.0, 7.0) == 7.0
    assert estimate_fuel(150.0, 6.0) == 9.0


def test_estimate_fuel_falls_back_on_missing_average():
    # avg_l100 <= 0 should use the 7.0 L/100km default
    assert estimate_fuel(100.0, 0.0) == 7.0
    assert estimate_fuel(100.0, -1.0) == 7.0


# ---------------------------------------------------------------------- #
# sample_waypoints                                                       #
# ---------------------------------------------------------------------- #


def test_sample_waypoints_preserves_endpoints():
    geom = [(i, i) for i in range(20)]
    samples = sample_waypoints(geom, 5)
    assert len(samples) == 5
    assert samples[0] == (0, 0)
    assert samples[-1] == (19, 19)


def test_sample_waypoints_short_route():
    # Fewer points than requested — return all
    geom = [(0, 0), (1, 1), (2, 2)]
    assert sample_waypoints(geom, 8) == geom


def test_sample_waypoints_empty_geometry():
    assert sample_waypoints([], WAYPOINT_COUNT) == []


# ---------------------------------------------------------------------- #
# _haversine_km                                                          #
# ---------------------------------------------------------------------- #


def test_haversine_warsaw_gdynia():
    # Warsaw → Gdynia should be ~300 km (great-circle)
    dist = _haversine_km((52.2297, 21.0122), (54.5189, 18.5305))
    assert 280 < dist < 330


def test_haversine_zero_distance():
    assert _haversine_km((52.0, 21.0), (52.0, 21.0)) == 0.0


# ---------------------------------------------------------------------- #
# _bounding_box                                                          #
# ---------------------------------------------------------------------- #


def test_bounding_box_basic():
    geom = [(1.0, 10.0), (3.0, 20.0), (2.0, 15.0)]
    assert _bounding_box(geom) == (1.0, 10.0, 3.0, 20.0)


def test_bounding_box_empty():
    assert _bounding_box([]) == (0.0, 0.0, 0.0, 0.0)


# ---------------------------------------------------------------------- #
# RoutePlanner fallback behaviour                                        #
# ---------------------------------------------------------------------- #


class _StubConfig:
    """Minimal config stub — mimics BCMConfig.get()."""

    def __init__(self, **overrides):
        self._data = overrides

    def get(self, key, default=None):
        return self._data.get(key, default)


def test_planner_straight_line_fallback_without_keys():
    cfg = _StubConfig()  # no ORS or TomTom key
    planner = RoutePlanner(cfg)
    plan = planner.plan(
        start=(52.2297, 21.0122),   # Warsaw
        dest=(54.5189, 18.5305),    # Gdynia
        avg_consumption=6.0,
    )
    # Straight-line distance should match _haversine_km ±5 km
    expected = _haversine_km((52.2297, 21.0122), (54.5189, 18.5305))
    assert math.isclose(plan["distance_km"], expected, rel_tol=0.05)
    # Fuel estimate should follow estimate_fuel()
    assert math.isclose(
        plan["predicted_fuel_l"],
        estimate_fuel(plan["distance_km"], 6.0),
        rel_tol=0.01,
    )
    # Incidents list is empty because no TomTom key
    assert plan["incidents"] == []
    # Two-point "polyline" with start and end
    assert len(plan["geometry"]) == 2
