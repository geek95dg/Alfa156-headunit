"""Online services BCM uses (OpenWeatherMap, OpenRouteService, TomTom):
is the key set, what did the last request answer, and a one-click test.

Why this exists
---------------
After months in the car "internet does not work" could mean four different
things — no uplink, an uplink without internet, a missing key, a wrong or not
yet activated key — and the UI showed none of them: weather silently stayed
on demo data, the route planner swallowed every 4xx. This module is the one
place that remembers, per service, the outcome of the last real request
(weather fetch, route plan, traffic incidents, or the Settings "Test"
button) so the Settings row "Internet i usługi" can say which one it is.

Security rules (inputs from the network are untrusted, keys are secrets):

* keys are only ever reported as presence booleans (:func:`key_presence`);
  they never appear in a result, a log line or an exception text we keep —
  results carry a fixed ``result`` code and an integer HTTP status only;
* TomTom wants its key in the URL; OpenWeatherMap too. urllib does not put
  the URL into ``HTTPError``/``URLError`` text, and we do not keep that text
  anyway (only :func:`classify_error`'s fixed code);
* every request has a short timeout and reads at most :data:`MAX_BODY`
  bytes; the test runs in a worker thread (web_viewer), never on the bus.

Result codes (``RESULTS``): ``untested`` (nothing tried since start),
``ok``, ``http`` (the service answered with an error status — ``http_code``
says which: 401/403 = wrong or not yet active key, 429 = request limit),
``network`` (no answer: DNS, TCP, TLS, timeout), ``no_key``,
``bad_response`` (answered 200 with something that is not the expected JSON).
"""

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request
from typing import Any, Callable, Optional
from urllib.parse import urlencode

from src.core.logger import get_logger

log = get_logger("network.net_services")

SERVICES = ("owm", "ors", "tomtom")
RESULTS = ("untested", "ok", "http", "network", "no_key", "bad_response")
#: Where each service's key lives in the config (SECRET_ENV_MAP fills them
#: from /etc/bcm/bcm.env) and the env variable the driver has to set.
KEY_PATHS = {"owm": "weather.api_key", "ors": "travel.openrouteservice_key",
             "tomtom": "travel.tomtom_key"}
KEY_VARS = {"owm": "BCM_OWM_API_KEY", "ors": "BCM_ORS_API_KEY",
            "tomtom": "BCM_TOMTOM_API_KEY"}
#: Who made the request a result comes from (shown in diagnostics only).
SOURCES = ("", "test", "weather", "route", "incidents", "search", "traffic")
TIMEOUT_S = 8.0
#: The test bodies are tiny; anything larger is cut (a hostile or broken
#: endpoint must not make us read megabytes).
MAX_BODY = 256 * 1024

OWM_WEATHER = "https://api.openweathermap.org/data/2.5/weather"
ORS_GEOCODE = "https://api.openrouteservice.org/geocode/search"
TOMTOM_INCIDENTS = "https://api.tomtom.com/traffic/services/5/incidentDetails"

#: Fallback test point (Kraków) when the config has no default location.
DEFAULT_LAT, DEFAULT_LON = 50.06, 19.94

_lock = threading.Lock()
_status: dict[str, dict[str, Any]] = {}


def _blank() -> dict[str, Any]:
    return {"result": "untested", "http_code": None, "at": None, "source": ""}


def reset() -> None:
    """Forget every recorded result (process start; tests)."""
    with _lock:
        _status.clear()
        for name in SERVICES:
            _status[name] = _blank()


reset()


def _http_code(value: Any) -> Optional[int]:
    if isinstance(value, bool) or not isinstance(value, int) or not 100 <= value <= 599:
        return None
    return value


def record(service: str, result: str, http_code: Optional[int] = None,
           source: str = "", at: Optional[float] = None) -> None:
    """Remember the outcome of one request to ``service``. Unknown values
    are ignored / folded (a caller bug must not reach the UI)."""
    if service not in SERVICES:
        return
    if result not in RESULTS:
        result = "network"
    entry = {"result": result, "http_code": _http_code(http_code) if result == "http" else None,
             "at": float(at) if isinstance(at, (int, float)) else time.time(),
             "source": source if source in SOURCES else ""}
    with _lock:
        prev = _status.get(service)
        _status[service] = entry
    if prev is None or (prev.get("result"), prev.get("http_code")) != \
            (entry["result"], entry["http_code"]):
        if result in ("ok", "untested"):
            log.info("Service %s: %s (%s)", service, result, entry["source"] or "-")
        else:
            # Name and code only — never the key or the URL.
            log.warning("Service %s: %s%s (%s)", service, result,
                        f" {entry['http_code']}" if entry["http_code"] else "",
                        entry["source"] or "-")


def snapshot() -> dict[str, dict[str, Any]]:
    """Copy of the recorded results, ``{service: {result, http_code, at, source}}``."""
    with _lock:
        return {k: dict(v) for k, v in _status.items()}


def _cfg(config: Any, dotpath: str, default: Any = None) -> Any:
    if config is None:
        return default
    getter = getattr(config, "get", None)
    if callable(getter):
        try:
            value = getter(dotpath)
        except Exception:
            value = None
        if value is not None:
            return value
    node = config
    for part in dotpath.split("."):
        if not isinstance(node, dict) or part not in node:
            return default
        node = node[part]
    return node


def _key(config: Any, service: str) -> str:
    value = _cfg(config, KEY_PATHS[service], "")
    return value.strip() if isinstance(value, str) else ""


def key_presence(config: Any) -> dict[str, bool]:
    """``{service: key set?}`` — the only thing about keys that leaves BCM."""
    return {name: bool(_key(config, name)) for name in SERVICES}


def classify_error(exc: BaseException) -> tuple[str, Optional[int]]:
    """An exception from a request → ``(result, http_code)``. Never text."""
    if isinstance(exc, urllib.error.HTTPError):
        return "http", _http_code(getattr(exc, "code", None))
    status = getattr(getattr(exc, "response", None), "status_code", None)
    if _http_code(status) is not None:              # requests.HTTPError
        return "http", status
    return "network", None


def default_http(method: str, url: str, headers: dict[str, str],
                 timeout: float) -> tuple[Optional[int], bytes]:
    """One request → ``(HTTP status, body)``; raises on no answer.

    An error status (4xx/5xx) is returned, not raised: the caller decides.
    """
    req = urllib.request.Request(url, method=method,
                                 headers=dict({"User-Agent": "BCM/1.0"}, **headers))
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return int(getattr(resp, "status", 200) or 200), resp.read(MAX_BODY)
    except urllib.error.HTTPError as e:
        return int(e.code), b""


HttpFn = Callable[[str, str, dict, float], tuple[Optional[int], bytes]]


def _request(service: str, http: HttpFn, method: str, url: str,
             headers: dict[str, str], check: Callable[[Any], bool]) -> dict[str, Any]:
    try:
        status, body = http(method, url, headers, TIMEOUT_S)
    except Exception as e:
        result, code = classify_error(e)
        return {"result": result, "http_code": code}
    code = _http_code(status)
    if code is None or code >= 300:
        return {"result": "http", "http_code": code}
    try:
        data = json.loads((body or b"").decode("utf-8", "replace"))
    except ValueError:
        return {"result": "bad_response", "http_code": None}
    return {"result": "ok" if check(data) else "bad_response", "http_code": None}


def check_owm(key: str, lat: float, lon: float, http: HttpFn = default_http) -> dict[str, Any]:
    """Current weather for one point (1 request of the free plan)."""
    if not key:
        return {"result": "no_key", "http_code": None}
    query = urlencode({"lat": f"{lat:.4f}", "lon": f"{lon:.4f}", "appid": key,
                       "units": "metric"})
    return _request("owm", http, "GET", f"{OWM_WEATHER}?{query}", {},
                    lambda d: isinstance(d, dict) and isinstance(d.get("main"), dict))


def check_ors(key: str, http: HttpFn = default_http) -> dict[str, Any]:
    """One geocode lookup; the key goes in the Authorization header."""
    if not key:
        return {"result": "no_key", "http_code": None}
    query = urlencode({"text": "Kraków", "size": 1})
    return _request("ors", http, "GET", f"{ORS_GEOCODE}?{query}",
                    {"Authorization": key, "Accept": "application/json"},
                    lambda d: isinstance(d, dict) and isinstance(d.get("features"), list))


def check_tomtom(key: str, lat: float, lon: float,
                http: HttpFn = default_http) -> dict[str, Any]:
    """Incidents in a ~10 × 7 km box around the point (TomTom's key is a
    query parameter — it never leaves this function in any form)."""
    if not key:
        return {"result": "no_key", "http_code": None}
    bbox = f"{lon - 0.05:.4f},{lat - 0.03:.4f},{lon + 0.05:.4f},{lat + 0.03:.4f}"
    query = urlencode({"key": key, "bbox": bbox, "fields": "{incidents{type}}",
                       "language": "pl-PL", "timeValidityFilter": "present"})
    return _request("tomtom", http, "GET", f"{TOMTOM_INCIDENTS}?{query}", {},
                    lambda d: isinstance(d, dict) and isinstance(d.get("incidents", []), list))


def _test_point(config: Any, bus: Any = None) -> tuple[float, float]:
    """Last GPS position if there is one, else weather.default_lat/lon."""
    from src.weather.weather import valid_coords
    if bus is not None:
        try:
            last = bus.get_last("gps.position")
        except Exception:
            last = None
        if last and isinstance(last[0], dict) and last[0].get("fix", True) is not False:
            coords = valid_coords(last[0].get("lat"), last[0].get("lon"))
            if coords and coords != (0.0, 0.0):
                return coords
    coords = valid_coords(_cfg(config, "weather.default_lat", DEFAULT_LAT),
                          _cfg(config, "weather.default_lon", DEFAULT_LON))
    return coords or (DEFAULT_LAT, DEFAULT_LON)


def run_test(config: Any, probe: Any = None, bus: Any = None,
             http: HttpFn = default_http) -> dict[str, Any]:
    """The Settings "Test": internet probe (forced) + one request per
    service whose key is set. Blocking (up to ~30 s) — call it from a
    worker thread. Returns ``{probe, services, keys, at}``; the results are
    also :func:`record`-ed, so the row shows them afterwards."""
    started = time.time()
    probe_res = None
    if probe is not None:
        try:
            probe_res = probe.check(force=True)
        except Exception as e:
            log.warning("Internet probe failed: %s", type(e).__name__)
    lat, lon = _test_point(config, bus)
    keys = key_presence(config)
    results: dict[str, dict[str, Any]] = {}
    for name, fn in (("owm", lambda k: check_owm(k, lat, lon, http)),
                     ("ors", lambda k: check_ors(k, http)),
                     ("tomtom", lambda k: check_tomtom(k, lat, lon, http))):
        key = _key(config, name)
        if not key:
            # No request, and the previous real result (if any) stays: a
            # missing key is shown by the row's own "klucz: nie".
            results[name] = {"result": "no_key", "http_code": None}
            continue
        res = fn(key)
        results[name] = res
        record(name, res["result"], res.get("http_code"), source="test")
    out = {"probe": probe_res, "services": results, "keys": keys,
           "at": started, "took_s": round(time.time() - started, 1)}
    if bus is not None:
        try:
            bus.publish("net.test_result", out)
        except Exception:
            log.debug("publishing net.test_result failed", exc_info=True)
    log.info("Internet/services test: internet=%s, %s", None if probe_res is None
             else probe_res.get("ok"),
             ", ".join(f"{k}={v['result']}{' ' + str(v['http_code']) if v.get('http_code') else ''}"
                       for k, v in results.items()))
    return out
