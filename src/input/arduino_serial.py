"""Arduino serial data reader — parses telemetry and vehicle signals.

The Arduino sends HID keycodes for button presses (handled by evdev/arduino_hid),
but also sends plain-text serial data for sensors and vehicle status:

    Inputs (Arduino reads):
        LIGHT:XXX          — LDR light sensor (ADC 0-1023)
        DOOR:FL=1,FR=0,RL=0,RR=0,BONNET=0,TRUNK=0  — door/panel states
        HBRAKE:1           — handbrake engaged (1) or released (0)
        IGN:1              — ignition/ACC 12V detected
        PWR:RUNNING        — M910q state as seen by sensor_hub
        PWRACT:SHORT       — power-button pulse just sent
        RAIN:1             — rain sensor triggered
        TEMP:23.5          — DS18B20 external temperature
        PARK:FL=123,FR=45,RL=200,RR=180  — parking sensor distances (cm)
        CRUISE:1           — cruise control active
        IMMO:1             — immobilizer recognized key
        AIRBAG:1           — airbag system OK (0=fault)
        BATT:12650,-3400   — buffer bank (sensor_hub FEATURE_BATT_*):
                             voltage in mV, optional current in mA
                             (+ charging, - discharging). Volts are accepted
                             only WITH a decimal point (BATT:12.65, the form
                             the older docs, ZASILANIE_BUFOROWANE.md §13.4,
                             used); an integer is always mV, so a truncated
                             "BATT:12" is 0.012 V and rejected, not 12 V.

    Debug (logged only):
        SWC:..., MUSIC:..., STALK:...

Which port
----------
``arduino.sensor_hub_port`` (config, e.g. ``/dev/ttyBCM_SENSOR`` from
``config/udev/99-bcm-sensor-hub.rules``) is used as-is and nothing is probed.
Left empty, ``arduino.probe_ports`` (default true = the historical behaviour)
opens /dev/ttyACM0..1 and /dev/ttyUSB0..2 one by one and takes the first that
opens. Probing has costs, which is why the test config turns it off: opening
a CH340 Nano asserts DTR and RESETS it, and it can grab a port another module
owns (K-Line adapter, GPS receiver, central-lock Nano). Ports configured for
ENABLED modules (central_lock, location, obd, esp32_display) are therefore
skipped by their real path (udev symlinks resolved), at start-up and again
before every reconnect (re-plugging renumbers ttyUSB*, and an owner's udev
symlink may now point at the probed node). The GPS port counts only when
``hardware.gps.source`` really opens it (``serial``, or ``auto`` on a non-x86
platform — the rule of src/location/gps.py). Ports of disabled modules are
still probed — that keeps the production config's behaviour unchanged.

Stability
---------
The reader is an outer reconnect loop: a lost or not-yet-present port is
retried with backoff 1 → 30 s (it used to end the thread for good on the first
serial error), the port stays open between reads, and
``arduino.sensor_hub_connected`` (bool) is published on every change. The
backoff starts over only after a session that stayed up for
:data:`STABLE_SESSION_S`: a CH340 Nano resets on every open (DTR) and prints
its banner, so "it sent a line" proves nothing about a port that drops a few
seconds after each open. The probed port is NOT re-probed on reconnect:
re-probing every 30 s would keep resetting the other Nanos through DTR. For a
port that survives re-plugging, use the udev symlink.

Security: everything from the serial line is untrusted. Lines are length
capped, numeric fields are parsed with strict patterns and range-checked, and
serial text reaches the log only as a truncated ``repr`` (no control
characters, no fake log lines); unknown and unparsable lines are additionally
rate-limited.
"""

import os
import re
import threading
import time
from typing import Any, Callable, Iterable, Optional

from src.core.event_bus import EventBus
from src.core.logger import get_logger

log = get_logger("input.arduino_serial")

try:
    import serial
    _SERIAL_AVAILABLE = True
except ImportError:
    _SERIAL_AVAILABLE = False


ARDUINO_SERIAL_PORTS = [
    "/dev/ttyACM0",
    "/dev/ttyACM1",
    "/dev/ttyUSB0",
    "/dev/ttyUSB1",
    "/dev/ttyUSB2",
]
BAUD_RATE = 115200
READ_TIMEOUT_S = 1.0        # readline() timeout — also bounds how long stop() waits
MAX_LINE_BYTES = 256        # the longest real line (DOOR:...) is ~45 bytes
RECONNECT_MIN_S = 1.0       # first retry after a lost port (re-plugged cable)
RECONNECT_MAX_S = 30.0      # then back off to twice a minute
STABLE_SESSION_S = 60.0     # a session at least this long resets the backoff
LOST_LOG_S = 300.0          # at most one "lost" / "connected" line per 5 min each
NOISE_LOG_S = 60.0          # unknown / unparsable lines: one debug line per minute
LOG_TEXT_MAX = 64           # serial text in the log: repr of at most this many chars

# BATT: plausibility. A 12 V bank outside 5-20 V, or more than 100 A through
# the shunt, is a broken divider, a floating pin or line noise — not a value
# worth acting on.
BATT_V_MIN = 5.0
BATT_V_MAX = 20.0
BATT_A_MAX = 100.0
BATT_REJECT_LOG_S = 60.0    # at most one debug line per minute about bad BATT:

# BATT:<mV>[,<mA>] or BATT:<V.v>[,<mA>] — bounded digits, so no
# float("1e400") / "nan" style surprises can come through. Volts need the
# decimal point: the firmware sends integer mV, and a line cut short by
# noise ("BATT:12" from "BATT:12650") must not read as a healthy 12 V.
_BATT_RE = re.compile(
    r"(?:(?P<mv>[+-]?\d{1,6})|(?P<v>[+-]?\d{1,2}\.\d{1,4}))"
    r"(?:\s*,\s*(?P<ma>[+-]?\d{1,7}(?:\.\d{1,3})?))?")
# Validates a configured port: printable ASCII under /dev/ (by-id / by-path
# names contain ':'), same rule as hardware.gps.port in src/location/gps.py.
_SERIAL_PORT_RE = re.compile(r"/dev/[!-~]{1,235}")

# Ports owned by other modules — skipped by the probe while the module is on.
# (module name, config key holding its port)
_OWNED_PORT_KEYS = (
    ("central_lock", "central_lock.port"),
    ("location", "hardware.gps.port"),
    ("obd", "serial.kline.port_x86"),
    ("obd", "serial.kline.port_opi"),
    ("esp32_display", "esp32_display.port"),
)


# ── pure helpers (tested directly) ─────────────────────────────────────────


def parse_batt(payload: str) -> tuple[float, Optional[float]]:
    """``BATT:`` payload → (volts, amps or None).

    ``12650`` → 12.65 V; ``12650,-3400`` → 12.65 V, -3.4 A; ``12.65`` →
    12.65 V (volts only with a decimal point; ``12`` is 12 mV → rejected).

    Raises:
        ValueError: not a BATT payload, or outside the plausible range.
    """
    m = _BATT_RE.fullmatch(payload.strip())
    if not m:
        raise ValueError("not <mV>[,<mA>]")
    if m.group("v") is not None:
        volts = float(m.group("v"))
    else:
        volts = int(m.group("mv")) / 1000.0
    if not BATT_V_MIN <= volts <= BATT_V_MAX:
        raise ValueError(f"{volts:.3f} V outside {BATT_V_MIN:g}-{BATT_V_MAX:g} V")
    amps: Optional[float] = None
    if m.group("ma") is not None:
        amps = float(m.group("ma")) / 1000.0
        if abs(amps) > BATT_A_MAX:
            raise ValueError(f"{amps:.3f} A beyond ±{BATT_A_MAX:g} A")
        amps = round(amps, 3)
    return round(volts, 3), amps


def _valid_serial_port(port: Any) -> bool:
    """Is ``port`` an absolute path under /dev/ (without '..')?"""
    return (isinstance(port, str) and bool(_SERIAL_PORT_RE.fullmatch(port))
            and ".." not in port.split("/"))


def _cfg_get(config: Any, dotpath: str, default: Any = None) -> Any:
    """Read ``a.b.c`` from a BCMConfig (dotted ``get``) or nested dicts."""
    if config is None:
        return default
    getter = getattr(config, "get", None)
    if callable(getter) and not isinstance(config, dict):
        try:
            value = getter(dotpath)
        except Exception:
            value = None
        if value is not None:
            return value
    node = config
    for key in dotpath.split("."):
        if isinstance(node, dict) and key in node:
            node = node[key]
        else:
            return default
    return node


def _module_enabled(config: Any, name: str) -> bool:
    checker = getattr(config, "is_module_enabled", None)
    if callable(checker):
        try:
            return bool(checker(name))
        except Exception:
            return False
    return bool(_cfg_get(config, f"modules.{name}", False))


def _as_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        text = value.strip().lower()
        if text in ("1", "true", "yes", "on"):
            return True
        if text in ("0", "false", "no", "off"):
            return False
    if value is not None:
        log.warning("arduino.probe_ports=%r is not a boolean — using %s", value, default)
    return default


def _gps_opens_serial(config: Any) -> bool:
    """Does the location module open ``hardware.gps.port`` at all?

    Mirrors ``_resolve_sources`` in src/location/gps.py (kept quiet here —
    gps.py logs bad values itself): ``auto`` (also a missing key) means the
    demo route on x86 and the serial receiver elsewhere; a name or list
    opens the port only when it names ``serial``. With ``[udp, tcp]`` (the
    phone as GPS) the port is a leftover default and the probe may use it.
    """
    value = _cfg_get(config, "hardware.gps.source", "auto")
    platform = _cfg_get(config, "system.platform", "x86")
    if not isinstance(platform, str):
        platform = "x86"
    if value is None or (isinstance(value, str) and value.strip().lower() in ("", "auto")):
        items = ["auto"]
    elif isinstance(value, str):
        items = [v.strip().lower() for v in value.split(",") if v.strip()]
    elif isinstance(value, (list, tuple)):
        items = [v.strip().lower() for v in value if isinstance(v, str)]
    else:
        return False
    if items == ["auto"]:
        return platform != "x86"
    return "serial" in items


def owned_serial_ports(config: Any) -> list[str]:
    """Ports that enabled modules use, for the probe to keep away from.

    Only ENABLED modules count: a port in a disabled module's block is a
    config default nobody opens, and skipping it would change which port
    the production config (all those modules off) finds. The GPS port counts
    only when the GPS really reads it (:func:`_gps_opens_serial`).
    """
    ports: list[str] = []
    for module, key in _OWNED_PORT_KEYS:
        port = _cfg_get(config, key)
        if not (isinstance(port, str) and port and _module_enabled(config, module)):
            continue
        if module == "location" and not _gps_opens_serial(config):
            continue
        ports.append(port)
    return ports


def _realpaths(paths: Optional[Iterable[str]]) -> set[str]:
    out: set[str] = set()
    for p in paths or ():
        if isinstance(p, str) and p:
            try:
                out.add(os.path.realpath(p))
            except (OSError, ValueError):
                continue
    return out


def find_arduino_serial(exclude: Optional[Iterable[str]] = None,
                        serial_factory: Optional[Callable[..., Any]] = None
                        ) -> Optional[str]:
    """Probe :data:`ARDUINO_SERIAL_PORTS`; the first one that opens wins.

    Args:
        exclude: ports never to touch (compared by real path, so a udev
            symlink such as /dev/ttyUSB_kline also hides /dev/ttyUSB2).
        serial_factory: ``factory(port, baud, timeout=...)``; default
            ``serial.Serial``.

    Every open asserts DTR, which resets a CH340 Nano — this runs once at
    start-up, never in the reconnect loop.
    """
    if serial_factory is None:
        if not _SERIAL_AVAILABLE:
            return None
        serial_factory = serial.Serial
    skip = _realpaths(exclude)
    for port in ARDUINO_SERIAL_PORTS:
        if skip and os.path.realpath(port) in skip:
            log.debug("Arduino probe: %s belongs to another module — skipped", port)
            continue
        try:
            s = serial_factory(port, BAUD_RATE, timeout=0.5)
            s.close()
            return port
        except Exception:       # SerialException is an OSError; fakes may differ
            continue
    return None


class _LogLimiter:
    """At most one log line per ``interval`` seconds (injected clock); the
    next line that gets through says how many were held back. A broken
    divider repeats every 2 s and a flapping port every few seconds — 24/7
    that would bury everything else in the journal.

    The caller still passes untrusted text as ``%r`` of a truncated string.
    """

    def __init__(self, clock: Callable[[], float], interval: float) -> None:
        self._clock = clock
        self._interval = interval
        self._at: Optional[float] = None
        self._suppressed = 0

    def __call__(self, level: Callable[..., None], fmt: str, *args: Any) -> bool:
        now = self._clock()
        if self._at is not None and now - self._at < self._interval:
            self._suppressed += 1
            return False
        more = (f" (+{self._suppressed} more since last report)"
                if self._suppressed else "")
        level(fmt + "%s", *args, more)
        self._at = now
        self._suppressed = 0
        return True


class ArduinoSerialListener:
    """Reads serial data from Arduino and publishes to event bus.

    Publishes:
        arduino.light_level  — int (0-1023 ADC)
        arduino.battery_voltage — float, V (BATT:, plausible values only)
        arduino.battery_current — float, A (+ charging), only when BATT:
                                  carries it (INA226 variant)
        arduino.sensor_hub_connected — bool, on every change of the port state
        vehicle.doors        — dict {fl, fr, rl, rr, bonnet, trunk} bool
        vehicle.handbrake    — bool
        vehicle.ignition_raw — bool (raw 12V detection from Arduino)
        vehicle.rain         — bool
        vehicle.ext_temp_raw — float (DS18B20 reading)
        vehicle.parking_raw  — dict {fl, fr, rl, rr} int (cm)
        vehicle.cruise       — bool
        vehicle.immo_ok      — bool
        vehicle.airbag_ok    — bool
        vehicle.fuel_raw     — int
        vehicle.power_state  — str (RUNNING / SLEEP / OFF / UNKNOWN)
    """

    def __init__(self, event_bus: EventBus, config: Any = None, *,
                 port: Optional[str] = None,
                 probe: Optional[bool] = None,
                 exclude: Optional[Iterable[str]] = None,
                 serial_factory: Optional[Callable[..., Any]] = None,
                 clock: Callable[[], float] = time.monotonic) -> None:
        """Args (explicit arguments win over ``config``):
            config: BCMConfig or dict — ``arduino.sensor_hub_port``,
                ``arduino.probe_ports`` and the ports of enabled modules.
            port: fixed port; when set, nothing is probed.
            probe: probe the usual ports when no port is configured
                (default ``arduino.probe_ports``, else True).
            exclude: ports the probe must skip (default: those of enabled
                modules, see :func:`owned_serial_ports`).
            serial_factory: ``factory(port, baud, timeout=...)`` returning an
                object with ``readline(size)`` and ``close()``; tests pass a
                fake, default ``serial.Serial``.
            clock: monotonic time source (session length for the backoff,
                log rate limiting).
        """
        self._bus = event_bus
        self._running = False
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._clock = clock
        self._serial_factory = serial_factory
        self._connected: Optional[bool] = None
        self._batt_log = _LogLimiter(clock, BATT_REJECT_LOG_S)
        self._noise_log = _LogLimiter(clock, NOISE_LOG_S)
        self._lost_log = _LogLimiter(clock, LOST_LOG_S)
        # Separate limiter: a burst of INFO "connected" lines must not use up
        # the window of the "lost" WARNING (or the other way round).
        self._connected_log = _LogLimiter(clock, LOST_LOG_S)

        if port is None:
            port = _cfg_get(config, "arduino.sensor_hub_port", "")
        if probe is None:
            probe = _as_bool(_cfg_get(config, "arduino.probe_ports", True), True)
        if exclude is None:
            exclude = owned_serial_ports(config)
        exclude = [p for p in exclude if isinstance(p, str) and p]
        # Kept for _open(): the owners' symlinks are resolved again before
        # every reconnect, not only by the start-up probe.
        self._exclude: list[str] = exclude

        self._port: Optional[str] = None
        self._port_source = "none"
        if port:
            if _valid_serial_port(port):
                self._port = port
                self._port_source = "config"
            else:
                log.error("arduino.sensor_hub_port=%r is not a /dev/… path — "
                          "Arduino serial disabled", port)
        elif probe:
            # Looked up through the module at call time (tests monkeypatch
            # it), and called with no arguments when there is nothing to
            # pass — the historical call.
            kwargs: dict[str, Any] = {}
            if exclude:
                kwargs["exclude"] = exclude
            if serial_factory is not None:
                kwargs["serial_factory"] = serial_factory
            self._port = find_arduino_serial(**kwargs)
            if self._port:
                self._port_source = "probe"
        else:
            log.info("Arduino serial: arduino.sensor_hub_port is empty and "
                     "arduino.probe_ports is off — sensors disabled")

    @property
    def available(self) -> bool:
        return self._port is not None

    @property
    def port(self) -> Optional[str]:
        return self._port

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._stop_event.clear()

        if self.available:
            self._thread = threading.Thread(target=self._listen_loop, daemon=True,
                                            name="arduino-serial")
            self._thread.start()
            log.info("Arduino serial listener started: %s (%s)",
                     self._port, self._port_source)
        else:
            log.info("Arduino serial: no port found (sensors disabled)")

    def stop(self) -> None:
        self._running = False
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=READ_TIMEOUT_S + 1.0)
            self._thread = None

    # ── reader ─────────────────────────────────────────────────────────────

    def _open(self) -> Any:
        """Open the port; OSError (→ backoff) when it cannot or must not be.

        A PROBED port is checked against the other modules' ports again here:
        re-plugging renumbers ttyUSB*, so the node found at start-up may now
        be the K-Line adapter or the GPS (their udev symlinks follow the
        device). Opening it would reset that device through DTR and feed its
        bytes to this parser. A configured port is the operator's explicit
        choice and is used as-is, as at start-up.
        """
        if self._port_source == "probe" and self._exclude:
            if os.path.realpath(self._port) in _realpaths(self._exclude):
                raise OSError(f"{self._port} now belongs to another module")
        factory = self._serial_factory
        if factory is None:
            if not _SERIAL_AVAILABLE:
                raise OSError("pyserial is not installed")
            factory = serial.Serial
        return factory(self._port, BAUD_RATE, timeout=READ_TIMEOUT_S)

    def _set_connected(self, connected: bool) -> None:
        if connected != self._connected:
            self._connected = connected
            self._bus.publish("arduino.sensor_hub_connected", connected)

    def _listen_loop(self) -> None:
        """Open → read until error → close → wait (1 → 30 s) → reopen.

        The delay grows on every failed or short session and goes back to
        the minimum only after a session that stayed open for
        :data:`STABLE_SESSION_S` (by the injected clock). "Delivered a line"
        is not enough: a CH340 Nano resets on every open and prints its
        banner, so a port that dies seconds after each open would otherwise
        be hammered every second forever. A healthy link that drops (cable
        re-plugged) still comes back within a second.
        """
        delay = RECONNECT_MIN_S
        failures = 0
        while self._running:
            try:
                ser = self._open()
            except Exception as e:      # SerialException, OSError, missing node
                self._set_connected(False)
                level = log.warning if failures == 0 else log.debug
                level("Arduino serial %s unavailable: %s — retrying in %.0f s",
                      self._port, e, delay)
                failures += 1
                if self._stop_event.wait(delay):
                    break
                delay = min(delay * 2, RECONNECT_MAX_S)
                continue

            self._set_connected(True)
            if failures:
                # Every short session counts as a failure now, so a flapping
                # port would log this at INFO on each reopen (~2500 lines a
                # day at the 30 s cap) — rate-limited like "lost".
                self._connected_log(log.info, "Arduino serial %s connected", self._port)
            opened_at = self._clock()
            try:
                while self._running:
                    raw = ser.readline(MAX_LINE_BYTES)
                    if not raw:
                        continue            # read timeout — port still open
                    line = raw.decode("utf-8", errors="ignore").strip()
                    if not line:
                        continue
                    self._parse_line(line)
            except Exception as e:
                self._lost_log(log.warning, "Arduino serial %s lost: %s — reconnecting",
                               self._port, e)
            finally:
                try:
                    ser.close()
                except Exception:
                    pass
                self._set_connected(False)

            if not self._running:
                break
            if self._clock() - opened_at >= STABLE_SESSION_S:
                delay = RECONNECT_MIN_S
                failures = 0
            else:
                failures += 1
            if self._stop_event.wait(delay):
                break
            delay = min(delay * 2, RECONNECT_MAX_S)

    # ── parser ─────────────────────────────────────────────────────────────

    def _parse_line(self, line: str) -> None:
        """Parse one line (untrusted; at most :data:`MAX_LINE_BYTES`).

        Whatever is logged is ``repr`` of the first :data:`LOG_TEXT_MAX`
        characters, so control characters or a fake "ERROR ..." line cannot
        reach the journal verbatim; unknown and unparsable lines are also
        rate-limited (a Nano spewing garbage at 115200 baud would flood it).
        """
        try:
            if line.startswith("LIGHT:"):
                self._bus.publish("arduino.light_level", int(line[6:]))

            elif line.startswith("DOOR:"):
                self._parse_doors(line[5:])

            elif line.startswith("HBRAKE:"):
                self._bus.publish("vehicle.handbrake", line[7:] == "1")

            elif line.startswith("IGN:"):
                self._bus.publish("vehicle.ignition_raw", line[4:] == "1")

            elif line.startswith("RAIN:"):
                self._bus.publish("vehicle.rain", line[5:] == "1")

            elif line.startswith("TEMP:"):
                self._bus.publish("vehicle.ext_temp_raw", float(line[5:]))

            elif line.startswith("PARK:"):
                self._parse_parking(line[5:])

            elif line.startswith("CRUISE:"):
                self._bus.publish("vehicle.cruise", line[7:] == "1")

            elif line.startswith("IMMO:"):
                self._bus.publish("vehicle.immo_ok", line[5:] == "1")

            elif line.startswith("AIRBAG:"):
                self._bus.publish("vehicle.airbag_ok", line[7:] == "1")

            elif line.startswith("FUEL:"):
                self._bus.publish("vehicle.fuel_raw", int(line[5:]))

            elif line.startswith("BATT:"):
                self._parse_batt(line)

            elif line.startswith("PWR:"):
                # Stan M910q raportowany przez sensor_hub (FEATURE_PWRBTN):
                # RUNNING / SLEEP / OFF / UNKNOWN.
                self._bus.publish("vehicle.power_state", line[4:])

            elif line.startswith(("SWC:", "MUSIC:", "STALK:", "PWRACT:")):
                log.debug("Arduino: %r", line[:LOG_TEXT_MAX])

            else:
                self._noise_log(log.debug, "Arduino unknown line: %r",
                                line[:LOG_TEXT_MAX])

        except (ValueError, IndexError) as e:
            # The exception text quotes the payload with repr() itself; the
            # type name is enough next to our own cut repr.
            self._noise_log(log.debug, "Arduino parse error (%s): %r",
                            type(e).__name__, line[:LOG_TEXT_MAX])

    def _parse_batt(self, line: str) -> None:
        """BATT:<mV>[,<mA>] (or BATT:<V>) → arduino.battery_voltage/_current.

        Implausible or malformed lines publish NOTHING — a battery monitor
        fed one bogus 3 V sample would raise a false "critical". The firmware
        also prints ``BATT: INA226 nie odpowiada`` once at boot when the
        sensor is missing; that lands here as well (and BCM sees the bank
        go stale).
        """
        try:
            volts, amps = parse_batt(line[5:])
        except ValueError as e:
            self._log_batt_reject(line, str(e))
            return
        # Current FIRST: src/power/battery.py evaluates on the voltage
        # event, and should see the current from the same line, not the
        # one from 2 s earlier (charging is detected from either).
        if amps is not None:
            self._bus.publish("arduino.battery_current", amps)
        self._bus.publish("arduino.battery_voltage", volts)

    def _log_batt_reject(self, line: str, reason: str) -> None:
        """One debug line per :data:`BATT_REJECT_LOG_S` — a broken divider
        repeats every 2 s and must not flood the log."""
        self._batt_log(log.debug, "Arduino BATT ignored (%s): %r",
                       reason, line[:LOG_TEXT_MAX])

    def _parse_doors(self, payload: str) -> None:
        """Parse DOOR:FL=1,FR=0,RL=0,RR=0,BONNET=0,TRUNK=0"""
        doors = {}
        for pair in payload.split(","):
            if "=" in pair:
                key, val = pair.split("=", 1)
                doors[key.strip().lower()] = val.strip() == "1"
        self._bus.publish("vehicle.doors", doors)

    def _parse_parking(self, payload: str) -> None:
        """Parse PARK:FL=123,FR=45,RL=200,RR=180 (distances in cm)"""
        distances = {}
        for pair in payload.split(","):
            if "=" in pair:
                key, val = pair.split("=", 1)
                try:
                    distances[key.strip().lower()] = int(val.strip())
                except ValueError:
                    distances[key.strip().lower()] = 999
        self._bus.publish("vehicle.parking_raw", distances)
