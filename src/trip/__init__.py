"""Trip planning and route computation.

The ``src.trip`` package contains the RoutePlanner responsible for
computing driving routes, weather forecasts along the route, road
incident lookups, and fuel consumption estimates.

It is intentionally kept separate from ``src.dashboard.trip_computer``
(the live trip statistics aggregator) so the HTTP-heavy planning
work can be tested in isolation.
"""
