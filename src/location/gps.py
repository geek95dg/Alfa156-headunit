"""GPS/GNSS module — NMEA parsing for NEO-6M/NEO-M8N or demo simulation.

On OrangePi: reads UART serial from GPS module, parses NMEA sentences.
On x86: generates a simulated driving route through Milan for demo/testing.

Publishes to event bus:
    gps.position  — dict with lat, lon, alt
    gps.speed     — float km/h
    gps.heading   — float degrees (0=N)
    gps.fix       — bool
    gps.satellites — int
"""

import math
import time
import logging
import threading

log = logging.getLogger(__name__)


class NMEAParser:
    """Parse standard NMEA 0183 sentences ($GPGGA, $GPRMC, $GPGSV)."""

    def __init__(self):
        self.lat = 0.0
        self.lon = 0.0
        self.alt = 0.0
        self.speed_knots = 0.0
        self.heading = 0.0
        self.fix = False
        self.satellites = 0

    def parse(self, sentence: str) -> bool:
        """Parse a single NMEA sentence. Returns True if valid."""
        sentence = sentence.strip()
        if not sentence.startswith("$"):
            return False

        # Verify checksum
        if "*" in sentence:
            body, chk_str = sentence[1:].split("*", 1)
            try:
                expected = int(chk_str, 16)
                computed = 0
                for ch in body:
                    computed ^= ord(ch)
                if computed != expected:
                    return False
            except ValueError:
                return False
        else:
            body = sentence[1:]

        parts = body.split(",")
        msg_type = parts[0]

        if msg_type in ("GPGGA", "GNGGA"):
            return self._parse_gga(parts)
        elif msg_type in ("GPRMC", "GNRMC"):
            return self._parse_rmc(parts)
        elif msg_type in ("GPGSV", "GNGSV"):
            return self._parse_gsv(parts)
        return False

    def _parse_gga(self, parts: list) -> bool:
        """Parse GGA — fix data, position, altitude, satellites."""
        try:
            if len(parts) < 10:
                return False
            # Fix quality (0=invalid, 1=GPS, 2=DGPS)
            fix_q = int(parts[6]) if parts[6] else 0
            self.fix = fix_q > 0
            if not self.fix:
                return True

            self.lat = self._nmea_to_decimal(parts[2], parts[3])
            self.lon = self._nmea_to_decimal(parts[4], parts[5])
            self.alt = float(parts[9]) if parts[9] else 0.0
            self.satellites = int(parts[7]) if parts[7] else 0
            return True
        except (ValueError, IndexError):
            return False

    def _parse_rmc(self, parts: list) -> bool:
        """Parse RMC — speed, heading, date/time."""
        try:
            if len(parts) < 10:
                return False
            status = parts[2]
            self.fix = (status == "A")
            if not self.fix:
                return True

            self.lat = self._nmea_to_decimal(parts[3], parts[4])
            self.lon = self._nmea_to_decimal(parts[5], parts[6])
            self.speed_knots = float(parts[7]) if parts[7] else 0.0
            self.heading = float(parts[8]) if parts[8] else 0.0
            return True
        except (ValueError, IndexError):
            return False

    def _parse_gsv(self, parts: list) -> bool:
        """Parse GSV — satellites in view."""
        try:
            if len(parts) >= 4:
                self.satellites = int(parts[3]) if parts[3] else 0
            return True
        except (ValueError, IndexError):
            return False

    @staticmethod
    def _nmea_to_decimal(coord: str, direction: str) -> float:
        """Convert NMEA coordinate (DDMM.MMMM) to decimal degrees."""
        if not coord:
            return 0.0
        # Find the degree/minute split
        dot_pos = coord.index(".")
        deg_len = dot_pos - 2
        degrees = float(coord[:deg_len])
        minutes = float(coord[deg_len:])
        decimal = degrees + minutes / 60.0
        if direction in ("S", "W"):
            decimal = -decimal
        return decimal

    @property
    def speed_kmh(self) -> float:
        """Speed in km/h (converted from knots)."""
        return self.speed_knots * 1.852


class DemoGPSGenerator:
    """Simulated GPS generating a driving route through Milan.

    Route: Via Alessandro Volta → Arco della Pace → Central Milan loop.
    """

    # Milan route waypoints (lat, lon)
    ROUTE = [
        (45.4773, 9.1815),  # Via Alessandro Volta
        (45.4755, 9.1750),  # Toward Parco Sempione
        (45.4740, 9.1720),  # Arco della Pace
        (45.4710, 9.1700),  # Via Dante approach
        (45.4660, 9.1870),  # Piazza del Duomo area
        (45.4630, 9.1920),  # Via Torino
        (45.4680, 9.1960),  # Piazza San Babila
        (45.4720, 9.1950),  # Corso Buenos Aires
        (45.4760, 9.2000),  # Viale Monza
        (45.4800, 9.1950),  # North loop
        (45.4790, 9.1880),  # Heading west
        (45.4773, 9.1815),  # Back to start
    ]

    def __init__(self):
        self._idx = 0
        self._frac = 0.0
        self._speed = 45.0  # km/h base speed

    def tick(self) -> dict:
        """Advance simulation, return GPS data dict."""
        n = len(self.ROUTE)
        p1 = self.ROUTE[self._idx % n]
        p2 = self.ROUTE[(self._idx + 1) % n]

        # Interpolate position
        lat = p1[0] + (p2[0] - p1[0]) * self._frac
        lon = p1[1] + (p2[1] - p1[1]) * self._frac

        # Heading from p1 to p2
        dlat = p2[0] - p1[0]
        dlon = p2[1] - p1[1]
        heading = math.degrees(math.atan2(dlon, dlat)) % 360

        # Vary speed slightly
        speed = self._speed + 10 * math.sin(time.time() * 0.3)

        # Advance along segment
        self._frac += 0.02
        if self._frac >= 1.0:
            self._frac = 0.0
            self._idx = (self._idx + 1) % n

        return {
            "lat": round(lat, 6),
            "lon": round(lon, 6),
            "alt": 120.0,
            "speed": max(0, round(speed, 1)),
            "heading": round(heading, 1),
            "fix": True,
            "satellites": 8,
        }


class GPSManager:
    """Manages GPS hardware (UART) or demo simulation.

    Args:
        event_bus: EventBus instance for publishing position data.
        config: BCM config dict with hardware.gps settings.
        platform: "opi" for real hardware, "x86" for demo.
    """

    def __init__(self, event_bus, config: dict, platform: str = "x86"):
        self._bus = event_bus
        self._config = config
        self._platform = platform
        self._running = False
        self._thread = None
        self._parser = NMEAParser()
        self._demo = DemoGPSGenerator() if platform == "x86" else None
        self._serial = None

    def start(self):
        """Start GPS reading in background thread."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True,
                                        name="gps-reader")
        self._thread.start()
        log.info("GPSManager started (platform=%s)", self._platform)

    def stop(self):
        """Stop GPS reading."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=3)
        if self._serial:
            try:
                self._serial.close()
            except Exception:
                pass
        log.info("GPSManager stopped")

    def _run(self):
        """Main GPS reading loop."""
        if self._platform == "x86":
            self._run_demo()
        else:
            self._run_serial()

    def _run_demo(self):
        """Demo mode: simulate driving through Milan."""
        while self._running:
            data = self._demo.tick()
            self._publish(data)
            time.sleep(1.0)

    def _run_serial(self):
        """Real hardware: read NMEA from serial port."""
        gps_cfg = self._config.get("hardware", {}).get("gps", {})
        port = gps_cfg.get("port", "/dev/ttyUSB0")
        baudrate = gps_cfg.get("baudrate", 9600)

        try:
            import serial
            self._serial = serial.Serial(port, baudrate, timeout=2)
            log.info("GPS serial opened: %s @ %d", port, baudrate)
        except Exception as e:
            log.error("Failed to open GPS serial %s: %s", port, e)
            log.info("Falling back to demo GPS")
            self._run_demo()
            return

        while self._running:
            try:
                line = self._serial.readline().decode("ascii", errors="ignore")
                if line and self._parser.parse(line):
                    self._publish({
                        "lat": round(self._parser.lat, 6),
                        "lon": round(self._parser.lon, 6),
                        "alt": round(self._parser.alt, 1),
                        "speed": round(self._parser.speed_kmh, 1),
                        "heading": round(self._parser.heading, 1),
                        "fix": self._parser.fix,
                        "satellites": self._parser.satellites,
                    })
            except Exception as e:
                log.warning("GPS read error: %s", e)
                time.sleep(1)

    def _publish(self, data: dict):
        """Publish GPS data to event bus."""
        self._bus.publish("gps.position", {"lat": data["lat"], "lon": data["lon"],
                                            "alt": data.get("alt", 0)})
        self._bus.publish("gps.speed", data["speed"])
        self._bus.publish("gps.heading", data["heading"])
        self._bus.publish("gps.fix", data["fix"])
        self._bus.publish("gps.satellites", data.get("satellites", 0))


def start_location(config, event_bus, hal, **kwargs):
    """Module entry point — called by main.py module registry."""
    platform = config.get("system", {}).get("platform", "x86")
    gps = GPSManager(event_bus, config, platform)
    gps.start()
    return gps
