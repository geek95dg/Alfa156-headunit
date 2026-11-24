"""Dziennik tankowań (``modules.fuel_log``): spalanie, koszt i zasięg bez OBD.

Kierowca po tankowaniu wpisuje na ekranie A3 („Zatankowano”): litry
(wymagane), cenę za litr (opcjonalnie), stan licznika (opcjonalnie) i czy
zatankował do pełna (domyślnie tak). Auto testowe nie ma OBD z przepływem
paliwa, więc to jest JEDYNE prawdziwe źródło spalania — wcześniej ekran
pokazywał zera, a planer trasy liczył paliwo ze stałych 7 l/100 km.

Metoda „od pełna do pełna”
--------------------------
Spalanie da się policzyć dopiero między DWOMA tankowaniami do pełna: ile
weszło do baku przy drugim (plus wszystkie częściowe tankowania pomiędzy),
tyle auto spaliło na dystansie między nimi. Pierwsze tankowanie do pełna
tylko otwiera dziennik („brak danych do spalania — zatankuj do pełna
jeszcze raz”). Tankowanie częściowe przed pierwszym pełnym nic nie daje.

Dystans przedziału:
* licznik — gdy oba końce mają stan licznika (różnica > 0); dokładny;
* GPS — w przeciwnym razie suma odcinków między punktami rejestratora
  (``tracking``) z czasem między tankowaniami (src/location/tracker.py
  ``distance_between``) — także gdy tankowanie wpisano w trakcie jazdy.
  GPS ZANIŻA dystans: punkt co ``tracking.interval_sec`` to cięciwy zamiast
  łuków na zakrętach, a początek jazdy przed pierwszym fixem w ogóle nie
  trafia do trasy (zwykle 1–5 %). Dlatego przedziały, które mają OBA
  pomiary (licznik i GPS), wyznaczają współczynnik kalibracji
  ``Σ licznik / Σ GPS``, przycięty do 0,9–1,1 (większa różnica to nie błąd
  pomiaru, tylko dziura w zapisie tras — np. moduł był wyłączony), i nim
  mnożony jest dystans z samego GPS. Przedział o stosunku spoza 0,5–2,0
  w ogóle nie wchodzi do kalibracji.

Przedział krótszy niż ``fuel_log.min_interval_km`` (domyślnie 20 km) albo
ze spalaniem spoza 2–30 l/100 km jest pokazany, ale nie wchodzi do średnich
— to prawie zawsze literówka albo brak zapisu tras, a jedna taka liczba
zepsułaby średnią na miesiące.

Przechowywanie
--------------
Osobny plik SQLite (``fuel_log.db_path``, domyślnie ``data/fuel_log.db``),
nie ``data/gps_tracks.db``: tankowania to kilka wierszy na miesiąc, cenne
latami (średnie), a bazę tras można chcieć skasować (prywatność, miejsce)
— nie może to zabrać historii tankowań. Dystans GPS jest i tak czytany
przez obiekt rejestratora (``tracking._internals``), pod jego blokadą.
WAL + ``synchronous=NORMAL`` jak w rejestratorze (twarde cięcie zasilania
przy każdym zgaszeniu silnika). Schemat: ``CREATE TABLE IF NOT EXISTS``
+ tabela ``schema_version``; baza z NOWSZEJ wersji (powrót do starszego
BCM) jest tylko czytana — zapis mógłby ją uszkodzić.

Publikuje ``fuel.stats`` (po starcie, po każdej zmianie, po końcu trasy
i co :data:`TICK_S` — przybywa km od tankowania) i ``fuel_log._internals``
(``{"fuel_log": FuelLog}``) dla tras web_viewer.
"""

from __future__ import annotations

import math
import os
import re
import sqlite3
import threading
import time
from typing import Any, Callable, Optional

from src.core.logger import get_logger
from src.core.notifications import publish_notification

log = get_logger("fuel_log")

SCHEMA_VERSION = 1
#: Granice wpisu. Litry: bak 58 l + zapas (kanister, inny bak) — ponad 120
#: to na pewno literówka (np. 455 zamiast 45,5).
LITRES_MIN, LITRES_MAX = 1.0, 120.0
#: Cena za litr w zł; 0 nie ma sensu (koszt wyszedłby 0), > 30 to literówka.
PRICE_MIN, PRICE_MAX = 0.01, 30.0
ODOMETER_MAX = 2_000_000
NOTE_MAX = 80
#: Litry ponad pojemność baku + tyle → ostrzeżenie (wpis zostaje).
OVER_TANK_MARGIN_L = 5.0
#: Domyślna ``fuel_log.min_interval_km``.
MIN_INTERVAL_KM = 20.0
#: Spalanie przedziału poza tym zakresem nie wchodzi do średnich.
L100_MIN, L100_MAX = 2.0, 30.0
#: Kalibracja GPS: przycięcie współczynnika i zakres przedziałów do niej.
CALIB_MIN, CALIB_MAX = 0.9, 1.1
CALIB_RATIO_MIN, CALIB_RATIO_MAX = 0.5, 2.0
#: Domyślna pojemność baku (Alfa 156 1.9 JTD), gdy
#: ``fuel_sender.tank_capacity_litres`` brak albo bez sensu.
DEFAULT_TANK_L = 58.0
TANK_MIN_L, TANK_MAX_L = 20.0, 150.0
#: Tyle ostatnich tankowań idzie w ``fuel.stats`` (lista na A3).
RECENT_COUNT = 5
#: Pozycja GPS starsza niż tyle nie trafia do wpisu.
GPS_FRESH_S = 60.0
#: Co ile sekund przeliczyć ``km_since_full`` w trakcie jazdy.
TICK_S = 60.0
MAX_LIST_LIMIT = 500

STATS_TOPIC = "fuel.stats"
INTERNALS_TOPIC = "fuel_log._internals"

_NUM_RE = re.compile(r"\s*([0-9]{1,7})(?:[.,]([0-9]{1,3}))?\s*")
_CTRL_RE = re.compile(r"[\x00-\x1f\x7f]")

# Notification texts for "no average yet" (same wording as i18n fuel_* keys).
_STATUS_TEXT_PL = {
    "need_second_full": "brak danych do spalania — zatankuj do pełna jeszcze raz",
    "no_distance": "brak dystansu — wpisz stan licznika przy następnym tankowaniu",
    "intervals_skipped": "odcinki pominięte (za krótkie lub nierealne spalanie) — "
                         "zatankuj do pełna po dłuższej jeździe",
}


def _finite(value: Any) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        # A 400-digit JSON integer is valid JSON but overflows float(): it
        # must be "out of range" (400), not an uncaught 500.
        value = float(value)
    except (OverflowError, ValueError):
        return None
    return value if math.isfinite(value) else None


def parse_number(value: Any) -> Optional[float]:
    """Number from JSON: int/float, or a string with ``,`` or ``.``.

    Strings come from the touch keyboard ("45,5"); anything else (exponents,
    signs, several separators, bool) is not a number here.
    """
    if isinstance(value, str):
        m = _NUM_RE.fullmatch(value)
        if not m:
            return None
        return float(m.group(1) + ("." + m.group(2) if m.group(2) else ""))
    return _finite(value)


def _blank(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def tank_capacity(config: Any) -> float:
    """``fuel_sender.tank_capacity_litres`` (20–150 l), else 58 l."""
    raw = config.get("fuel_sender.tank_capacity_litres", None) if config is not None else None
    cap = parse_number(raw)
    if cap is None or not TANK_MIN_L <= cap <= TANK_MAX_L:
        if raw is not None:
            log.warning("fuel_sender.tank_capacity_litres=%r poza %g–%g l — przyjmuję %g l",
                        raw, TANK_MIN_L, TANK_MAX_L, DEFAULT_TANK_L)
        return DEFAULT_TANK_L
    return cap


def validate_refuel(data: Any, previous: Optional[dict] = None,
                    tank_l: float = DEFAULT_TANK_L) -> tuple[Optional[dict], str, list]:
    """Untrusted JSON body → ``(clean, error, warnings)``.

    ``error`` is '' when ``clean`` is usable, else a code the UI translates:
    ``bad_request``, ``litres_required``, ``litres_range``, ``price_range``,
    ``odometer_range``, ``odometer_backwards`` (smaller than the previous
    entry's — saved only with ``confirm_odometer: true``: the old entry may
    be the typo), ``bad_full``, ``note_too_long``.
    """
    if not isinstance(data, dict):
        return None, "bad_request", []
    warnings: list = []
    if _blank(data.get("litres")):
        return None, "litres_required", []
    litres = parse_number(data.get("litres"))
    if litres is None or not LITRES_MIN <= litres <= LITRES_MAX:
        return None, "litres_range", []
    if litres > tank_l + OVER_TANK_MARGIN_L:
        warnings.append("litres_over_tank")
    price = None
    if not _blank(data.get("price_per_l")):
        price = parse_number(data.get("price_per_l"))
        if price is None or not PRICE_MIN <= price <= PRICE_MAX:
            return None, "price_range", []
    odometer = None
    if not _blank(data.get("odometer_km")):
        odometer = parse_number(data.get("odometer_km"))
        if odometer is None or not 0 <= odometer <= ODOMETER_MAX:
            return None, "odometer_range", []
        prev_odo = _finite((previous or {}).get("odometer_km"))
        if prev_odo is not None and odometer < prev_odo:
            if data.get("confirm_odometer") is not True:
                return None, "odometer_backwards", []
            warnings.append("odometer_backwards")
    full = data.get("full", True)
    if not isinstance(full, bool):
        return None, "bad_full", []
    note = data.get("note")
    if _blank(note):
        note = None
    elif not isinstance(note, str):
        return None, "bad_request", []
    else:
        note = _CTRL_RE.sub(" ", note).strip()
        if len(note) > NOTE_MAX:
            return None, "note_too_long", []
    return ({"litres": round(litres, 3),
             "price_per_l": round(price, 3) if price is not None else None,
             "odometer_km": round(odometer, 1) if odometer is not None else None,
             "full": full, "note": note}, "", warnings)


# ── interval maths (pure) ────────────────────────────────────────────────

def _clamp(value: float, lo: float, hi: float) -> float:
    return min(hi, max(lo, value))


def compute_stats(rows: list, gps_distance: Optional[Callable[[float, Optional[float]],
                                                                Optional[float]]],
                  tank_l: float = DEFAULT_TANK_L,
                  min_interval_km: float = MIN_INTERVAL_KM) -> dict:
    """Statistics from all refuels (oldest first). See the module docstring.

    ``gps_distance(start_ts, end_ts_or_None)`` → km or None (no tracker).
    Returns the ``fuel.stats`` payload without ``updated_at``.
    """
    gps = gps_distance if gps_distance is not None else (lambda a, b: None)
    fulls = [i for i, r in enumerate(rows) if r.get("full")]
    raw: list = []
    for a, b in zip(fulls, fulls[1:]):
        ra, rb = rows[a], rows[b]
        inside = rows[a + 1:b + 1]
        litres = sum(r["litres"] for r in inside)
        odo_a, odo_b = _finite(ra.get("odometer_km")), _finite(rb.get("odometer_km"))
        odo_km = odo_b - odo_a if odo_a is not None and odo_b is not None \
            and odo_b - odo_a > 0 else None
        gps_km = _finite(gps(ra["ts"], rb["ts"]))
        priced = all(r.get("price_per_l") is not None for r in inside)
        cost = sum(r["litres"] * r["price_per_l"] for r in inside) if priced else None
        raw.append({"end_id": rb["id"], "start_ts": ra["ts"], "end_ts": rb["ts"],
                    "litres": litres, "odo_km": odo_km,
                    "gps_km": gps_km if gps_km and gps_km > 0 else None, "cost": cost})

    # GPS calibration from intervals that have both measurements.
    sum_odo = sum_gps = 0.0
    samples = 0
    for iv in raw:
        if iv["odo_km"] and iv["gps_km"] and iv["odo_km"] >= min_interval_km:
            ratio = iv["odo_km"] / iv["gps_km"]
            if CALIB_RATIO_MIN <= ratio <= CALIB_RATIO_MAX:
                sum_odo += iv["odo_km"]
                sum_gps += iv["gps_km"]
                samples += 1
    factor = _clamp(sum_odo / sum_gps, CALIB_MIN, CALIB_MAX) if samples else 1.0

    intervals: dict = {}
    usable: list = []
    for iv in raw:
        if iv["odo_km"] is not None:
            dist, source = iv["odo_km"], "odometer"
        elif iv["gps_km"] is not None:
            dist, source = iv["gps_km"] * factor, "gps"
        else:
            dist, source = None, "none"
        l100 = iv["litres"] / dist * 100.0 if dist else None
        ok = bool(dist and dist >= min_interval_km and l100 is not None
                  and L100_MIN <= l100 <= L100_MAX)
        info = {"km": round(dist, 1) if dist else None, "source": source,
                "litres": round(iv["litres"], 2),
                "l100": round(l100, 2) if l100 is not None else None,
                "cost": round(iv["cost"], 2) if iv["cost"] is not None else None,
                "usable": ok}
        intervals[iv["end_id"]] = info
        if ok:
            usable.append((info, iv["litres"], dist, iv["cost"]))

    avg_last = usable[-1][0]["l100"] if usable else None
    total_l = sum(u[1] for u in usable)
    total_km = sum(u[2] for u in usable)
    avg_overall = round(total_l / total_km * 100.0, 2) if total_km > 0 else None
    priced = [u for u in usable if u[3] is not None]
    priced_km = sum(u[2] for u in priced)
    cost_per_100 = round(sum(u[3] for u in priced) / priced_km * 100.0, 2) \
        if priced_km > 0 else None

    km_since = used = left = rng = None
    if fulls:
        last_full = rows[fulls[-1]]
        g = _finite(gps(last_full["ts"], None))
        if g is not None:
            km_since = round(max(0.0, g) * factor, 1)
        added = sum(r["litres"] for r in rows[fulls[-1] + 1:])
        avg = avg_overall if avg_overall is not None else avg_last
        if km_since is not None and avg is not None:
            used = round(km_since * avg / 100.0, 1)
            left = round(_clamp(tank_l - used + added, 0.0, tank_l), 1)
            rng = round(left / avg * 100.0) if avg > 0 else None

    # Each "no average" case gets its own status: telling the driver to fill
    # up "once more" after the third full fill (all intervals unusable) lies.
    if not rows:
        status = "empty"
    elif avg_overall is None and avg_last is None:
        if not fulls:
            status = "need_first_full"
        elif len(fulls) == 1:
            status = "need_second_full"
        elif all(intervals.get(rows[b]["id"], {}).get("source") == "none"
                 for b in fulls[1:]):
            status = "no_distance"
        else:
            status = "intervals_skipped"
    else:
        status = "ok"

    recent = []
    for r in reversed(rows[-RECENT_COUNT:]):
        recent.append({"id": r["id"], "ts": r["ts"], "litres": r["litres"],
                       "price_per_l": r.get("price_per_l"),
                       "odometer_km": r.get("odometer_km"), "full": bool(r.get("full")),
                       "interval": intervals.get(r["id"])})
    last = rows[-1] if rows else None
    return {
        "status": status,
        "count": len(rows),
        "avg_l100_last": avg_last,
        "avg_l100_overall": avg_overall,
        "cost_per_100km": cost_per_100,
        "km_since_full": km_since,
        "litres_used_est": used,
        "fuel_left_est_l": left,
        "est_range_km": rng,
        "tank_capacity_l": tank_l,
        "calibration": {"factor": round(factor, 4), "samples": samples},
        "gps_available": gps_distance is not None,
        "last_refuel": ({"id": last["id"], "ts": last["ts"], "litres": last["litres"],
                         "price_per_l": last.get("price_per_l"),
                         "odometer_km": last.get("odometer_km"),
                         "full": bool(last.get("full"))} if last else None),
        "recent": recent,
        "intervals": intervals,
    }


# ── the module ───────────────────────────────────────────────────────────

_COLUMNS = "id, ts, litres, price_per_l, odometer_km, full, lat, lon, note"


def _row(r) -> dict:
    return {"id": r[0], "ts": r[1], "litres": r[2], "price_per_l": r[3],
            "odometer_km": r[4], "full": bool(r[5]), "lat": r[6], "lon": r[7],
            "note": r[8]}


class FuelLog:
    """Refuel storage + ``fuel.stats`` publication.

    Args:
        event_bus: EventBus (``tracking.trip_ended`` in; ``fuel.stats`` out).
        config: dotted ``get`` (``fuel_log.*``, ``fuel_sender.tank_capacity_litres``).
        wall_clock: epoch seconds stored with every refuel (and compared
            with the tracker's trip times, which use the same clock).
        clock: monotonic seconds (GPS freshness).
    """

    def __init__(self, event_bus, config=None,
                 wall_clock: Callable[[], float] = time.time,
                 clock: Callable[[], float] = time.monotonic):
        self.bus = event_bus
        cfg = (lambda k, d: config.get(k, d)) if config is not None else (lambda k, d: d)
        self.db_path = str(cfg("fuel_log.db_path", "data/fuel_log.db"))
        mik = parse_number(cfg("fuel_log.min_interval_km", MIN_INTERVAL_KM))
        self.min_interval_km = mik if mik is not None and 1 <= mik <= 1000 else MIN_INTERVAL_KM
        self.tank_l = tank_capacity(config)
        self._wall = wall_clock
        self._clock = clock
        self._lock = threading.Lock()
        self._db: Optional[sqlite3.Connection] = None
        self._readonly = False
        self._stop_evt = threading.Event()
        # Set from bus callbacks; the tick thread recomputes. Stats read SQLite
        # and the tracker (its lock), which must not run inside a callback.
        self._dirty = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._warned_no_tracker = False
        self._init_db()

    # ── storage ──────────────────────────────────────────────────────────

    def _init_db(self) -> None:
        db_dir = os.path.dirname(self.db_path)
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)
        self._db = sqlite3.connect(self.db_path, check_same_thread=False, timeout=2.0)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA synchronous=NORMAL")
        self._db.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL)")
        row = self._db.execute("SELECT MAX(version) FROM schema_version").fetchone()
        version = row[0] if row else None
        if version is not None and version > SCHEMA_VERSION:
            # A newer BCM wrote this file; writing with the old schema could
            # break it for that version. Read what we understand, write nothing.
            self._readonly = True
            log.error("Dziennik tankowań %s ma schemat v%d (ten BCM zna v%d) — tylko odczyt",
                      self.db_path, version, SCHEMA_VERSION)
            return
        self._db.execute("""CREATE TABLE IF NOT EXISTS refuels (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts REAL NOT NULL,
            litres REAL NOT NULL,
            price_per_l REAL,
            odometer_km REAL,
            full INTEGER NOT NULL DEFAULT 1,
            lat REAL, lon REAL,
            note TEXT
        )""")
        self._db.execute("CREATE INDEX IF NOT EXISTS idx_refuels_ts ON refuels(ts)")
        if version is None:
            self._db.execute("INSERT INTO schema_version (version) VALUES (?)",
                             (SCHEMA_VERSION,))
        self._db.commit()
        # Refuels carry the fill-up position: owner-only like the weather cache
        # (not os.umask: it is process-wide and other threads create files).
        # The -wal/-shm files exist now and live as long as the connection.
        self._restrict_files()

    def _restrict_files(self) -> None:
        """chmod 0600 the DB and its WAL/SHM (a file left 0644 by an older run)."""
        for suffix in ("", "-wal", "-shm"):
            path = self.db_path + suffix
            try:
                if os.path.exists(path):
                    os.chmod(path, 0o600)
            except OSError as e:
                log.debug("Dziennik tankowań: chmod %s nieudany: %s", path, e)

    def _rows(self) -> list:
        """All refuels, oldest first (caller holds the lock)."""
        if self._db is None:
            return []
        cur = self._db.execute(f"SELECT {_COLUMNS} FROM refuels ORDER BY ts, id")
        return [_row(r) for r in cur.fetchall()]

    def list_refuels(self, limit: int = 50) -> list:
        """Newest first; ``limit`` clamped to 1..500."""
        try:
            limit = int(limit)
        except (TypeError, ValueError, OverflowError):
            limit = 50
        limit = min(max(limit, 1), MAX_LIST_LIMIT)
        with self._lock:
            if self._db is None:
                return []
            cur = self._db.execute(
                f"SELECT {_COLUMNS} FROM refuels ORDER BY ts DESC, id DESC LIMIT ?", (limit,))
            return [_row(r) for r in cur.fetchall()]

    def _position(self) -> tuple[Optional[float], Optional[float]]:
        """Fresh GPS position for the entry (where the car was filled), or None."""
        last = self.bus.get_last("gps.position") if self.bus is not None else None
        if not last or not isinstance(last[0], dict) or last[0].get("fix") is False:
            return None, None
        if not 0 <= self._wall() - last[1] <= GPS_FRESH_S:
            return None, None
        lat, lon = _finite(last[0].get("lat")), _finite(last[0].get("lon"))
        if lat is None or lon is None or abs(lat) > 90 or abs(lon) > 180:
            return None, None
        return round(lat, 6), round(lon, 6)

    def add(self, data: Any) -> dict:
        """Validate and store one refuel. ``{"ok", "refuel"|"error", "warnings"}``."""
        with self._lock:
            if self._db is None:
                return {"ok": False, "error": "not_running"}
            if self._readonly:
                return {"ok": False, "error": "read_only"}
            rows = self._rows()
            prev_odo = next((r for r in reversed(rows) if r["odometer_km"] is not None), None)
            clean, error, warnings = validate_refuel(data, prev_odo, self.tank_l)
            if error:
                return {"ok": False, "error": error}
            now = self._wall()
            ts = float(now)
            if rows and ts <= rows[-1]["ts"]:
                # Entries must stay in time order (intervals and GPS distance
                # depend on it); a wall clock that went back (no time sync
                # yet) gets the entry right after the previous one.
                if now < rows[-1]["ts"]:
                    warnings.append("clock_behind")
                    log.warning("Zegar systemowy cofnięty względem ostatniego tankowania — "
                                "wpis dostaje czas tuż po poprzednim")
                ts = rows[-1]["ts"] + 1.0
            lat, lon = self._position()
            try:
                cur = self._db.execute(
                    "INSERT INTO refuels (ts, litres, price_per_l, odometer_km, full, lat, lon, note)"
                    " VALUES (?,?,?,?,?,?,?,?)",
                    (ts, clean["litres"], clean["price_per_l"], clean["odometer_km"],
                     1 if clean["full"] else 0, lat, lon, clean["note"]))
                self._db.commit()
            except sqlite3.Error as e:
                log.warning("Dziennik tankowań: zapis nieudany: %s", e)
                return {"ok": False, "error": "db_error"}
            refuel = {"id": cur.lastrowid, "ts": ts, **clean}
        log.info("Tankowanie: %.2f l%s%s", clean["litres"],
                 " do pełna" if clean["full"] else " (częściowe)",
                 f", {clean['price_per_l']:.2f} zł/l" if clean["price_per_l"] else "")
        stats = self.publish_stats()
        self._announce(refuel, stats)
        return {"ok": True, "refuel": refuel, "warnings": warnings}

    def delete(self, refuel_id: Any) -> dict:
        """Delete the NEWEST entry (the undo for a typo). Older ones stay:
        each change in the middle silently rewrites the intervals around it."""
        if isinstance(refuel_id, bool) or not isinstance(refuel_id, int):
            return {"ok": False, "error": "bad_request"}
        with self._lock:
            if self._db is None:
                return {"ok": False, "error": "not_running"}
            if self._readonly:
                return {"ok": False, "error": "read_only"}
            row = self._db.execute(
                "SELECT id FROM refuels ORDER BY ts DESC, id DESC LIMIT 1").fetchone()
            if row is None or row[0] != refuel_id:
                exists = self._db.execute("SELECT 1 FROM refuels WHERE id=?",
                                          (refuel_id,)).fetchone()
                return {"ok": False, "error": "not_last" if exists else "not_found"}
            try:
                self._db.execute("DELETE FROM refuels WHERE id=?", (refuel_id,))
                self._db.commit()
            except sqlite3.Error as e:
                log.warning("Dziennik tankowań: usuwanie nieudane: %s", e)
                return {"ok": False, "error": "db_error"}
        log.info("Tankowanie %d usunięte", refuel_id)
        self.publish_stats()
        return {"ok": True}

    # ── statistics ───────────────────────────────────────────────────────

    def _gps_distance(self) -> Optional[Callable]:
        tracker = None
        last = self.bus.get_last("tracking._internals") if self.bus is not None else None
        if last and isinstance(last[0], dict):
            tracker = last[0].get("tracker")
        fn = getattr(tracker, "distance_between", None)
        if fn is None:
            if not self._warned_no_tracker:
                self._warned_no_tracker = True
                log.warning("Dziennik tankowań: rejestrator tras (modules.tracking) nie "
                            "działa — spalanie tylko z przedziałów ze stanem licznika")
            return None

        def safe(a, b):
            try:
                return fn(a, b)
            except Exception as e:      # a broken trips DB must not stop the stats
                log.debug("distance_between failed: %s", e)
                return None
        return safe

    def stats(self) -> dict:
        with self._lock:
            rows = self._rows()
        # Outside our lock: the tracker takes its own.
        result = compute_stats(rows, self._gps_distance(), self.tank_l, self.min_interval_km)
        result["updated_at"] = self._wall()
        result["read_only"] = self._readonly
        return result

    def publish_stats(self) -> Optional[dict]:
        try:
            result = self.stats()
        except Exception:
            log.exception("Dziennik tankowań: liczenie statystyk nieudane")
            return None
        if self.bus is not None:
            # Without the per-interval map: it grows with every refuel and
            # nobody on the bus needs it (``recent`` carries the last five).
            self.bus.publish(STATS_TOPIC, {k: v for k, v in result.items() if k != "intervals"})
        return result

    def _announce(self, refuel: dict, stats: Optional[dict]) -> None:
        if not refuel.get("full") or not stats:
            return
        info = (stats.get("intervals") or {}).get(refuel["id"])
        if info and info.get("usable"):
            desc = f"{info['l100']:.1f} l/100 km na {info['km']:.0f} km".replace(".", ",")
            publish_notification(self.bus, "Spalanie od poprzedniego tankowania", desc,
                                 severity="info", icon="local_gas_station", key="fuel_log")
        elif stats.get("status") in _STATUS_TEXT_PL:
            publish_notification(self.bus, "Zapisano tankowanie do pełna",
                                 _STATUS_TEXT_PL[stats["status"]],
                                 severity="info", icon="local_gas_station", key="fuel_log")

    # ── lifecycle ────────────────────────────────────────────────────────

    def _on_trip_ended(self, topic, value, ts=None) -> None:
        # Only a flag: on a synchronous bus this runs on the tracker's thread,
        # and publish_stats() would call back into the tracker (its lock).
        self._dirty.set()

    def _tick_loop(self) -> None:
        while not self._stop_evt.is_set():
            self._dirty.wait(TICK_S)
            self._dirty.clear()
            if self._stop_evt.is_set():
                return
            self.publish_stats()

    def start(self) -> None:
        self.bus.subscribe("tracking.trip_ended", self._on_trip_ended)
        self.publish_stats()
        if self._thread is None or not self._thread.is_alive():
            self._stop_evt.clear()
            self._thread = threading.Thread(target=self._tick_loop, daemon=True,
                                            name="fuel-log-tick")
            self._thread.start()
        log.info("Dziennik tankowań uruchomiony (%s, bak %g l)", self.db_path, self.tank_l)

    def stop(self) -> None:
        self._stop_evt.set()
        self._dirty.set()          # wake the tick thread so it exits now
        try:
            self.bus.unsubscribe("tracking.trip_ended", self._on_trip_ended)
        except Exception:
            pass
        if self._thread is not None:
            self._thread.join(timeout=2)
            self._thread = None
        with self._lock:
            if self._db is not None:
                self._db.close()
                self._db = None


def get_fuel_log(event_bus) -> Optional[FuelLog]:
    """The running FuelLog (``fuel_log._internals``), or None."""
    last = event_bus.get_last(INTERNALS_TOPIC) if event_bus is not None else None
    if last and isinstance(last[0], dict):
        obj = last[0].get("fuel_log")
        if isinstance(obj, FuelLog):
            return obj
    return None


def start_fuel_log(config=None, event_bus=None, hal=None, **kwargs):
    fuel_log = FuelLog(event_bus, config=config)
    fuel_log.start()
    event_bus.publish(INTERNALS_TOPIC, {"fuel_log": fuel_log})
    return fuel_log
