"""Main dashboard renderer — PyGame window on x86, framebuffer on OPi.

Manages the render loop, screen navigation (A1–C2), demo data generation,
keyboard input, and coordinates all dashboard sub-components.
"""

import math
import os
import queue
import time
import threading
import pygame

from src.core.config import BCMConfig
from src.core.event_bus import EventBus
from src.core.logger import get_logger
from src.dashboard.themes import THEMES
from src.dashboard.themes.theme_base import ThemeBase
from src.dashboard.screens import (
    SCREEN_ORDER, SCREEN_CLASSES, DashboardData, BaseScreen,
)
from src.dashboard.trip_computer import TripComputer
from src.dashboard.status_bar import StatusBar
from src.dashboard.overlays import ParkingOverlay, IcingAlert
from src.dashboard.settings_screen import SettingsScreen
from src.dashboard.web_viewer import WebViewer
from src.dashboard.i18n import t

log = get_logger("dashboard")


class DemoDataGenerator:
    """Generates realistic simulated sensor data for x86 demo mode."""

    def __init__(self, event_bus: EventBus) -> None:
        self.bus = event_bus
        self._running = False
        self._thread: threading.Thread | None = None
        self._t = 0.0

    def start(self) -> None:
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        log.info("Demo data generator started")

    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=2)

    def _loop(self) -> None:
        while self._running:
            self._t += 0.1

            # RPM: sinusoidal with noise (idle ~850, cruising ~2500, occasional rev to 4500)
            rpm_base = 2200 + 1500 * math.sin(self._t * 0.3)
            rpm = max(750, min(5000, rpm_base + 100 * math.sin(self._t * 2.1)))
            self.bus.publish("obd.rpm", rpm)

            # Speed: roughly correlated with RPM
            speed = max(0, (rpm - 800) * 0.04 + 10 * math.sin(self._t * 0.15))
            self.bus.publish("obd.speed", speed)

            # Coolant temperature: slow rise from 60 to 90, stabilize
            temp = 60 + 30 * (1 - math.exp(-self._t * 0.02)) + 2 * math.sin(self._t * 0.05)
            self.bus.publish("obd.coolant_temp", temp)

            # Fuel rate: correlated with RPM
            fuel_rate = 1.0 + (rpm / 1000) * 2.5 + 0.5 * math.sin(self._t * 0.7)
            self.bus.publish("obd.fuel_rate", max(0.5, fuel_rate))

            # Fuel level: slowly decreasing
            fuel_level = max(5, 65 - self._t * 0.05)
            self.bus.publish("obd.fuel_level", fuel_level)

            # Battery voltage
            self.bus.publish("obd.battery_voltage", 13.8 + 0.3 * math.sin(self._t * 0.1))

            # Exterior temperature: slow sine wave crossing 3°C threshold
            ext_temp = 5 + 8 * math.sin(self._t * 0.02)
            self.bus.publish("env.temperature", ext_temp)

            # Boost pressure simulation (0-1.2 BAR, correlated with RPM)
            boost = max(0, (rpm - 1500) / 3000 * 1.2 + 0.1 * math.sin(self._t * 1.5))
            self.bus.publish("obd.boost", min(1.5, boost))

            time.sleep(0.1)


class DashboardRenderer:
    """Main dashboard renderer with screen-based navigation."""

    def __init__(self, config: BCMConfig, event_bus: EventBus) -> None:
        self.config = config
        self.bus = event_bus
        self._running = False

        # Load theme
        theme_name = config.get("display.dashboard.theme", "classic_alfa")
        theme_cls = THEMES.get(theme_name, THEMES["classic_alfa"])
        self.theme: ThemeBase = theme_cls()

        # Dashboard data (shared state for all screens)
        self.data = DashboardData()
        self.data.lang = config.get("language", "pl")
        self.data.speed_unit = config.get("units.speed", "km/h")
        self.data.temp_unit = config.get("units.temperature", "C")

        # Sub-components
        self.trip = TripComputer()
        self.status_bar = StatusBar()
        self.parking_overlay = ParkingOverlay()
        self.icing_alert = IcingAlert()
        self.settings = SettingsScreen(config)

        # Screen system
        self._screen_index = 0
        self._screens: dict[str, BaseScreen] = {}
        for screen_id, cls in SCREEN_CLASSES.items():
            self._screens[screen_id] = cls()

        # Display settings
        self.width = config.get("display.dashboard.width", 800)
        self.height = config.get("display.dashboard.height", 480)
        self.fps = config.get("display.dashboard.fps", 15)

        # Long press tracking
        self._long_press_start: float | None = None
        self._long_press_threshold = 2.0  # seconds

        # Queue for receiving input from event bus (browser WebSocket, BT remote, etc.)
        self._input_queue: queue.Queue[int] = queue.Queue()

        # Subscribe to events
        self._subscribe_events()

    @property
    def current_screen_id(self) -> str:
        return SCREEN_ORDER[self._screen_index]

    @property
    def current_screen(self) -> BaseScreen:
        return self._screens[self.current_screen_id]

    # Map key names (from browser/event bus) to PyGame key constants
    _KEYNAME_TO_PYGAME = {
        "up": pygame.K_UP,
        "down": pygame.K_DOWN,
        "left": pygame.K_LEFT,
        "right": pygame.K_RIGHT,
        "enter": pygame.K_RETURN,
        "home": pygame.K_HOME,
        "h": pygame.K_h,
        "backspace": pygame.K_BACKSPACE,
        "escape": pygame.K_ESCAPE,
        "r": pygame.K_r,
        "t": pygame.K_t,
        "i": pygame.K_i,
    }

    def _subscribe_events(self) -> None:
        self.bus.subscribe("obd.rpm", self._on_rpm)
        self.bus.subscribe("obd.speed", self._on_speed)
        self.bus.subscribe("obd.coolant_temp", self._on_coolant_temp)
        self.bus.subscribe("obd.fuel_level", self._on_fuel_level)
        self.bus.subscribe("obd.fuel_rate", self._on_fuel_rate)
        self.bus.subscribe("obd.battery_voltage", self._on_battery)
        self.bus.subscribe("obd.boost", self._on_boost)
        self.bus.subscribe("env.temperature", self._on_ext_temp)
        self.bus.subscribe("parking.distances", self._on_parking)
        self.bus.subscribe("power.reverse_gear", self._on_reverse)

        # Accept input from event bus (browser WebSocket, BT remote, etc.)
        self.bus.subscribe("input.raw_keyname", self._on_raw_keyname)

    def _on_raw_keyname(self, topic: str, value: str, ts: float) -> None:
        """Queue a key press from the event bus for processing in the main loop."""
        pg_key = self._KEYNAME_TO_PYGAME.get(value)
        if pg_key is not None:
            self._input_queue.put(pg_key)

    def _on_rpm(self, topic: str, value: float, ts: float) -> None:
        self.data.rpm = value
        self.trip.rpm = value

    def _on_speed(self, topic: str, value: float, ts: float) -> None:
        self.data.speed = value
        self.trip.update(value, self.data.fuel_rate)

    def _on_coolant_temp(self, topic: str, value: float, ts: float) -> None:
        self.data.coolant_temp = value
        self.trip.coolant_temp = value

    def _on_fuel_level(self, topic: str, value: float, ts: float) -> None:
        self.data.fuel_level = value
        self.trip.fuel_level_pct = value

    def _on_fuel_rate(self, topic: str, value: float, ts: float) -> None:
        self.data.fuel_rate = value

    def _on_battery(self, topic: str, value: float, ts: float) -> None:
        self.data.battery_voltage = value
        self.trip.battery_voltage = value

    def _on_boost(self, topic: str, value: float, ts: float) -> None:
        self.data.boost_bar = value

    def _on_ext_temp(self, topic: str, value: float, ts: float) -> None:
        self.data.ext_temp = value
        self.status_bar.temperature = value
        # Icing detection
        if value < 3.0:
            self.status_bar.icing_warning = True
            if not self.icing_alert.active:
                self.icing_alert.trigger(5.0)
        else:
            self.status_bar.icing_warning = False

    def _on_parking(self, topic: str, value: list, ts: float) -> None:
        if isinstance(value, list) and len(value) == 4:
            self.parking_overlay.distances = value

    def _on_reverse(self, topic: str, value: bool, ts: float) -> None:
        self.parking_overlay.active = bool(value)
        self.data.reverse = bool(value)
        self.data.gear = "R" if value else "N"
        if not value:
            self.parking_overlay.release_camera()

    def _switch_theme(self, theme_name: str) -> None:
        theme_cls = THEMES.get(theme_name)
        if theme_cls:
            self.theme = theme_cls()
            log.info("Theme switched to: %s", theme_name)

    def _update_data_from_trip(self) -> None:
        """Sync trip computer data into DashboardData."""
        self.data.trip_distance = self.trip.distance_km
        self.data.trip_time_str = self.trip.trip_time_str
        self.data.trip_fuel_used = self.trip.fuel_used_l
        self.data.avg_speed = self.trip.avg_speed
        self.data.avg_consumption = self.trip.avg_consumption
        self.data.instant_consumption = self.trip.instant_consumption
        self.data.estimated_range = self.trip.estimated_range_km

    def _update_lang_from_config(self) -> None:
        """Refresh language and unit settings from config."""
        self.data.lang = self.config.get("language", "pl")
        self.data.speed_unit = self.config.get("units.speed", "km/h")
        self.data.temp_unit = self.config.get("units.temperature", "C")

    def _navigate_screen(self, direction: int) -> None:
        """Switch to next (+1) or previous (-1) screen."""
        self._screen_index = (self._screen_index + direction) % len(SCREEN_ORDER)
        log.info("Screen: %s", self.current_screen_id)

    def _handle_keyboard(self, event: pygame.event.Event) -> bool:
        """Handle keyboard input. Returns True if quit requested."""
        if event.type == pygame.QUIT:
            return True

        if event.type == pygame.KEYDOWN:
            # Long press tracking for RETURN key
            if event.key == pygame.K_RETURN:
                self._long_press_start = time.time()

        if event.type == pygame.KEYUP:
            if event.key == pygame.K_RETURN and self._long_press_start:
                elapsed = time.time() - self._long_press_start
                self._long_press_start = None
                if elapsed >= self._long_press_threshold:
                    # Long press
                    result = self.current_screen.on_long_press(self.data)
                    if result == "trip.reset":
                        self.trip.reset()
                        log.info("Trip reset via long press")
                    elif result == "service.confirm":
                        log.info("Service confirmed via long press")
                        self.data.service_km = 15000
                return False

        if event.type != pygame.KEYDOWN:
            return False

        if event.key == pygame.K_ESCAPE:
            if self.settings.active:
                self.settings.save()
                self.settings.toggle()
                self._apply_config_changes()
            else:
                return True

        elif event.key == pygame.K_HOME or event.key == pygame.K_h:
            if self.settings.active:
                self.settings.save()
                self._apply_config_changes()
            self.settings.toggle()

        elif self.settings.active:
            if event.key == pygame.K_UP:
                self.settings.navigate(-1)
            elif event.key == pygame.K_DOWN:
                self.settings.navigate(1)
            elif event.key in (pygame.K_RIGHT, pygame.K_RETURN):
                self.settings.cycle_value(1)
            elif event.key == pygame.K_LEFT:
                self.settings.cycle_value(-1)
            elif event.key == pygame.K_BACKSPACE:
                self.settings.switch_page(1)

        else:
            # Screen navigation and demo controls
            if event.key == pygame.K_RIGHT:
                self._navigate_screen(1)
            elif event.key == pygame.K_LEFT:
                self._navigate_screen(-1)
            elif event.key == pygame.K_UP:
                self.data.rpm = min(5500, self.data.rpm + 200)
                self.bus.publish("obd.rpm", self.data.rpm)
            elif event.key == pygame.K_DOWN:
                self.data.rpm = max(0, self.data.rpm - 200)
                self.bus.publish("obd.rpm", self.data.rpm)
            elif event.key == pygame.K_r:
                self.parking_overlay.active = not self.parking_overlay.active
                self.data.reverse = self.parking_overlay.active
                self.data.gear = "R" if self.data.reverse else "N"
                if not self.parking_overlay.active:
                    self.parking_overlay.release_camera()
                self.bus.publish("power.reverse_gear", self.parking_overlay.active)
            elif event.key == pygame.K_t:
                if self.data.ext_temp is None:
                    self.data.ext_temp = 10.0
                self.data.ext_temp -= 3.0
                self.bus.publish("env.temperature", self.data.ext_temp)
            elif event.key == pygame.K_i:
                self.icing_alert.trigger(5.0)

        return False

    def _apply_config_changes(self) -> None:
        """Apply theme/language changes after settings close."""
        new_theme = self.config.get("display.dashboard.theme")
        if new_theme and new_theme != self.theme.name:
            self._switch_theme(new_theme)
        self._update_lang_from_config()

    def _draw_frame(self, surface: pygame.Surface) -> None:
        """Draw one complete dashboard frame."""
        theme = self.theme

        # Update data from trip computer
        self._update_data_from_trip()

        # Background
        surface.fill(theme.bg_color)

        # Status bar (with screen title)
        screen_title_key = f"screen.{self.current_screen_id}"
        self.status_bar.draw(surface, theme, self.data, screen_title_key)

        # Current screen content
        self.current_screen.draw(surface, theme, self.data)

        # Overlays (drawn last, on top)
        self.parking_overlay.draw(surface, theme, self.data.lang)
        self.icing_alert.draw(surface, theme, self.data.lang)
        self.settings.draw(surface, theme, self.data.lang)

    def run(self) -> None:
        """Main render loop (blocking). Call from main thread."""
        platform = self.config.platform

        # Initialize PyGame
        if platform == "opi":
            os.environ.setdefault("SDL_VIDEODRIVER", "fbcon")
            os.environ.setdefault("SDL_FBDEV", "/dev/fb0")

        pygame.init()
        pygame.font.init()

        if platform == "opi":
            screen = pygame.display.set_mode((self.width, self.height), pygame.FULLSCREEN)
            pygame.mouse.set_visible(False)
        else:
            screen = pygame.display.set_mode((self.width, self.height))

        pygame.display.set_caption("BCM v7 — Alfa Romeo 156 Dashboard")
        clock = pygame.time.Clock()

        # Start WebViewer for x86 — streams dashboard frames to browser
        web_viewer = None
        if platform == "x86":
            web_viewer = WebViewer(event_bus=self.bus)
            web_viewer.start()

        self._running = True
        log.info("Dashboard renderer started (%dx%d @ %d FPS, theme: %s, lang: %s)",
                 self.width, self.height, self.fps, self.theme.name, self.data.lang)
        log.info("Screen navigation: LEFT/RIGHT arrows | Settings: HOME | Screens: %s",
                 ", ".join(SCREEN_ORDER))

        while self._running:
            # Handle PyGame events (keyboard/mouse when display is real)
            for event in pygame.event.get():
                if self._handle_keyboard(event):
                    self._running = False

            # Handle event bus input (browser WebSocket, BT remote, etc.)
            while not self._input_queue.empty():
                try:
                    pg_key = self._input_queue.get_nowait()
                    synth = pygame.event.Event(pygame.KEYDOWN, key=pg_key)
                    if self._handle_keyboard(synth):
                        self._running = False
                except queue.Empty:
                    break

            # Draw
            self._draw_frame(screen)
            pygame.display.flip()

            if web_viewer:
                web_viewer.update_frame(screen)

            clock.tick(self.fps)

        if web_viewer:
            web_viewer.stop()
        pygame.quit()
        log.info("Dashboard renderer stopped")

    def stop(self) -> None:
        self._running = False


def start_dashboard(config: BCMConfig, event_bus: EventBus, **kwargs) -> DashboardRenderer:
    """Entry point called from main.py to start the dashboard module.

    Returns the renderer so callers can call renderer.stop() for clean shutdown.
    """
    renderer = DashboardRenderer(config, event_bus)

    # Start demo data generator on x86
    demo = None
    if config.platform == "x86":
        demo = DemoDataGenerator(event_bus)
        demo.start()

    try:
        renderer.run()
    finally:
        if demo:
            demo.stop()

    return renderer
