"""Main dashboard renderer — PyGame window on x86, framebuffer on OPi.

Manages the render loop, demo data generation, keyboard input,
and coordinates all dashboard sub-components (gauges, trip, status bar,
overlays, settings).
"""

import math
import os
import time
import threading
import pygame

from src.core.config import BCMConfig
from src.core.event_bus import EventBus
from src.core.logger import get_logger
from src.dashboard.themes import THEMES
from src.dashboard.themes.theme_base import ThemeBase
from src.dashboard.gauges import draw_gauge
from src.dashboard.trip_computer import TripComputer
from src.dashboard.status_bar import StatusBar
from src.dashboard.overlays import ParkingOverlay, IcingAlert
from src.dashboard.settings_screen import SettingsScreen

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

            time.sleep(0.1)


class DashboardRenderer:
    """Main dashboard renderer with PyGame render loop."""

    def __init__(self, config: BCMConfig, event_bus: EventBus) -> None:
        self.config = config
        self.bus = event_bus
        self._running = False

        # Load theme
        theme_name = config.get("display.dashboard.theme", "classic_alfa")
        theme_cls = THEMES.get(theme_name, THEMES["classic_alfa"])
        self.theme: ThemeBase = theme_cls()

        # Sub-components
        self.trip = TripComputer()
        self.status_bar = StatusBar()
        self.parking_overlay = ParkingOverlay()
        self.icing_alert = IcingAlert()
        self.settings = SettingsScreen(config)

        # Display settings
        self.width = config.get("display.dashboard.width", 800)
        self.height = config.get("display.dashboard.height", 480)
        self.fps = config.get("display.dashboard.fps", 15)

        # Current gauge values
        self._rpm = 0.0
        self._speed = 0.0
        self._coolant_temp = 0.0
        self._fuel_level = 50.0
        self._fuel_rate = 0.0
        self._ext_temp: float | None = None

        # Subscribe to events
        self._subscribe_events()

    def _subscribe_events(self) -> None:
        self.bus.subscribe("obd.rpm", self._on_rpm)
        self.bus.subscribe("obd.speed", self._on_speed)
        self.bus.subscribe("obd.coolant_temp", self._on_coolant_temp)
        self.bus.subscribe("obd.fuel_level", self._on_fuel_level)
        self.bus.subscribe("obd.fuel_rate", self._on_fuel_rate)
        self.bus.subscribe("obd.battery_voltage", self._on_battery)
        self.bus.subscribe("env.temperature", self._on_ext_temp)
        self.bus.subscribe("parking.distances", self._on_parking)
        self.bus.subscribe("power.reverse_gear", self._on_reverse)

    def _on_rpm(self, topic: str, value: float, ts: float) -> None:
        self._rpm = value
        self.trip.rpm = value

    def _on_speed(self, topic: str, value: float, ts: float) -> None:
        self._speed = value
        self.trip.update(value, self._fuel_rate)

    def _on_coolant_temp(self, topic: str, value: float, ts: float) -> None:
        self._coolant_temp = value
        self.trip.coolant_temp = value

    def _on_fuel_level(self, topic: str, value: float, ts: float) -> None:
        self._fuel_level = value
        self.trip.fuel_level_pct = value

    def _on_fuel_rate(self, topic: str, value: float, ts: float) -> None:
        self._fuel_rate = value

    def _on_battery(self, topic: str, value: float, ts: float) -> None:
        self.trip.battery_voltage = value

    def _on_ext_temp(self, topic: str, value: float, ts: float) -> None:
        self._ext_temp = value
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

    def _switch_theme(self, theme_name: str) -> None:
        theme_cls = THEMES.get(theme_name)
        if theme_cls:
            self.theme = theme_cls()
            log.info("Theme switched to: %s", theme_name)

    def _handle_keyboard(self, event: pygame.event.Event) -> bool:
        """Handle keyboard input. Returns True if quit requested."""
        if event.type == pygame.QUIT:
            return True

        if event.type != pygame.KEYDOWN:
            return False

        if event.key == pygame.K_ESCAPE:
            if self.settings.active:
                self.settings.save()
                self.settings.toggle()
                # Apply theme change if needed
                new_theme = self.config.get("display.dashboard.theme")
                if new_theme != self.theme.name:
                    self._switch_theme(new_theme)
            else:
                return True

        elif event.key == pygame.K_HOME or event.key == pygame.K_h:
            if self.settings.active:
                self.settings.save()
                new_theme = self.config.get("display.dashboard.theme")
                if new_theme != self.theme.name:
                    self._switch_theme(new_theme)
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
                # Switch settings page (BACK toggles between General ↔ SWC)
                self.settings.switch_page(1)

        else:
            # Dashboard keyboard overrides (demo mode)
            if event.key == pygame.K_UP:
                self._rpm = min(5500, self._rpm + 200)
                self.bus.publish("obd.rpm", self._rpm)
            elif event.key == pygame.K_DOWN:
                self._rpm = max(0, self._rpm - 200)
                self.bus.publish("obd.rpm", self._rpm)
            elif event.key == pygame.K_r:
                # Toggle reverse mode
                self.parking_overlay.active = not self.parking_overlay.active
                self.bus.publish("power.reverse_gear", self.parking_overlay.active)
            elif event.key == pygame.K_t:
                # Cycle temperature for testing
                if self._ext_temp is None:
                    self._ext_temp = 10.0
                self._ext_temp -= 3.0
                self.bus.publish("env.temperature", self._ext_temp)
            elif event.key == pygame.K_i:
                # Trigger icing alert
                self.icing_alert.trigger(5.0)

        return False

    def _draw_frame(self, surface: pygame.Surface) -> None:
        """Draw one complete dashboard frame."""
        theme = self.theme

        # Background
        surface.fill(theme.bg_color)

        # Status bar
        self.status_bar.draw(surface, theme)

        # Speed unit based on config
        speed_unit = self.config.get("units.speed", "km/h")
        speed_val = self._speed
        if speed_unit == "mph":
            speed_val = self._speed * 0.621371

        # Temp unit
        temp_unit = "\u00b0" + self.config.get("units.temperature", "C")
        temp_val = self._coolant_temp
        if self.config.get("units.temperature") == "F":
            temp_val = self._coolant_temp * 9 / 5 + 32

        # Gauges
        draw_gauge(surface, theme, theme.rpm_gauge, theme.rpm_rect,
                   self._rpm, 0, 5500, "RPM", "rpm", redzone_start=4500)
        draw_gauge(surface, theme, theme.speed_gauge, theme.speed_rect,
                   speed_val, 0, 220, "SPEED", speed_unit)
        draw_gauge(surface, theme, theme.temp_gauge, theme.temp_rect,
                   temp_val, 40, 130, "COOLANT", temp_unit, redzone_start=100)
        draw_gauge(surface, theme, theme.fuel_gauge, theme.fuel_rect,
                   self._fuel_level, 0, 100, "FUEL", "%")

        # Trip computer section
        self._draw_trip(surface, theme)

        # Overlays (drawn last, on top)
        self.parking_overlay.draw(surface, theme)
        self.icing_alert.draw(surface, theme)
        self.settings.draw(surface, theme)

    def _draw_trip(self, surface: pygame.Surface, theme: ThemeBase) -> None:
        """Draw the trip computer section at the bottom."""
        x, y, w, h = theme.trip_rect

        # Background
        pygame.draw.rect(surface, theme.trip_bg, (x, y, w, h), border_radius=4)

        try:
            font_label = pygame.font.SysFont(theme.font_name, theme.trip_font_size)
            font_value = pygame.font.SysFont(theme.font_name, theme.trip_value_size)
        except Exception:
            font_label = pygame.font.Font(None, theme.trip_font_size)
            font_value = pygame.font.Font(None, theme.trip_value_size)

        # Trip data items
        items = [
            ("TRIP", f"{self.trip.distance_km:.1f} km"),
            ("AVG SPD", f"{self.trip.avg_speed:.0f} km/h"),
            ("FUEL USED", f"{self.trip.fuel_used_l:.2f} L"),
            ("AVG CONS", f"{self.trip.avg_consumption:.1f} L/100"),
            ("INST CONS", f"{self.trip.instant_consumption:.1f} L/100"),
            ("RANGE", f"{self.trip.estimated_range_km:.0f} km"),
            ("TIME", self.trip.trip_time_str),
            ("BATT", f"{self.trip.battery_voltage:.1f}V"),
        ]

        col_w = w // 4
        row_h = h // 2
        padding = 10

        for idx, (label, value) in enumerate(items):
            col = idx % 4
            row = idx // 4
            ix = x + col * col_w + padding
            iy = y + row * row_h + 6

            lbl_surf = font_label.render(label, True, theme.trip_text)
            surface.blit(lbl_surf, (ix, iy))

            val_surf = font_value.render(value, True, theme.trip_value_color)
            surface.blit(val_surf, (ix, iy + theme.trip_font_size + 2))

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

        self._running = True
        log.info("Dashboard renderer started (%dx%d @ %d FPS, theme: %s)",
                 self.width, self.height, self.fps, self.theme.name)

        while self._running:
            # Handle events
            for event in pygame.event.get():
                if self._handle_keyboard(event):
                    self._running = False

            # Draw
            self._draw_frame(screen)
            pygame.display.flip()
            clock.tick(self.fps)

        pygame.quit()
        log.info("Dashboard renderer stopped")

    def stop(self) -> None:
        self._running = False


def start_dashboard(config: BCMConfig, event_bus: EventBus, **kwargs) -> None:
    """Entry point called from main.py to start the dashboard module."""
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
