"""OSM Tile Map Renderer — downloads, caches, and renders OpenStreetMap tiles.

TileManager handles tile downloading with rate limiting and disk caching.
MapRenderer composes tiles into a PyGame surface with theme-specific color
filters and a GPS position marker.

Tile source: https://tile.openstreetmap.org/{z}/{x}/{y}.png
Cache: ~/.cache/bcm/tiles/{z}/{x}/{y}.png (persistent, ~100MB LRU)
"""

import logging
import math
import os
import threading
import time
import queue
from pathlib import Path

log = logging.getLogger(__name__)

TILE_SIZE = 256
CACHE_DIR = Path.home() / ".cache" / "bcm" / "tiles"
MAX_CACHE_MB = 100
USER_AGENT = "BCM-v7-Alfa156/1.0 (headunit; contact: github.com/geek95dg)"
MAX_REQUESTS_PER_SEC = 2
DEFAULT_ZOOM = 14


def lat_lon_to_tile(lat: float, lon: float, zoom: int) -> tuple[float, float]:
    """Convert GPS coordinates to fractional tile coordinates (x, y)."""
    n = 2 ** zoom
    x = (lon + 180.0) / 360.0 * n
    lat_rad = math.radians(lat)
    y = (1.0 - math.log(math.tan(lat_rad) + 1.0 / math.cos(lat_rad)) / math.pi) / 2.0 * n
    return x, y


def tile_to_lat_lon(x: int, y: int, zoom: int) -> tuple[float, float]:
    """Convert tile coordinates back to GPS (lat, lon) of the tile's NW corner."""
    n = 2 ** zoom
    lon = x / n * 360.0 - 180.0
    lat_rad = math.atan(math.sinh(math.pi * (1 - 2 * y / n)))
    lat = math.degrees(lat_rad)
    return lat, lon


class TileManager:
    """Downloads and caches OSM raster tiles.

    Thread-safe tile fetching with rate limiting (2 req/s) and persistent
    disk cache. Tiles are downloaded in background threads.
    """

    def __init__(self, cache_dir: Path = CACHE_DIR, max_concurrent: int = 2):
        self._cache_dir = cache_dir
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._download_queue: queue.Queue = queue.Queue()
        self._pending: set[tuple[int, int, int]] = set()
        self._lock = threading.Lock()
        self._last_request_time = 0.0
        self._rate_lock = threading.Lock()
        self._running = True

        # Start download workers
        self._workers = []
        for i in range(max_concurrent):
            t = threading.Thread(target=self._download_worker, daemon=True,
                                 name=f"tile-dl-{i}")
            t.start()
            self._workers.append(t)

        log.info("TileManager started (cache=%s, workers=%d)", cache_dir, max_concurrent)

    def stop(self):
        self._running = False

    def get_tile_path(self, z: int, x: int, y: int) -> Path:
        """Get the local cache path for a tile."""
        return self._cache_dir / str(z) / str(x) / f"{y}.png"

    def get_tile(self, z: int, x: int, y: int) -> Path | None:
        """Get a cached tile, or queue it for download. Returns path if cached."""
        path = self.get_tile_path(z, x, y)
        if path.exists():
            return path

        # Queue for download if not already pending
        key = (z, x, y)
        with self._lock:
            if key not in self._pending:
                self._pending.add(key)
                self._download_queue.put(key)
        return None

    def _download_worker(self):
        """Background worker that downloads tiles from the queue."""
        import urllib.request
        import urllib.error

        while self._running:
            try:
                z, x, y = self._download_queue.get(timeout=1)
            except queue.Empty:
                continue

            try:
                # Rate limiting
                with self._rate_lock:
                    elapsed = time.time() - self._last_request_time
                    wait = (1.0 / MAX_REQUESTS_PER_SEC) - elapsed
                    if wait > 0:
                        time.sleep(wait)
                    self._last_request_time = time.time()

                url = f"https://tile.openstreetmap.org/{z}/{x}/{y}.png"
                req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
                with urllib.request.urlopen(req, timeout=10) as resp:
                    data = resp.read()

                # Save to cache
                path = self.get_tile_path(z, x, y)
                path.parent.mkdir(parents=True, exist_ok=True)
                with open(path, "wb") as f:
                    f.write(data)

                log.debug("Tile downloaded: %d/%d/%d (%d bytes)", z, x, y, len(data))

            except Exception as e:
                log.debug("Tile download failed %d/%d/%d: %s", z, x, y, e)
            finally:
                with self._lock:
                    self._pending.discard((z, x, y))

    def cleanup_cache(self):
        """Remove oldest tiles if cache exceeds MAX_CACHE_MB."""
        try:
            tiles = list(self._cache_dir.rglob("*.png"))
            total_size = sum(f.stat().st_size for f in tiles)
            if total_size <= MAX_CACHE_MB * 1024 * 1024:
                return

            # Sort by access time, remove oldest
            tiles.sort(key=lambda f: f.stat().st_atime)
            removed = 0
            for f in tiles:
                if total_size <= MAX_CACHE_MB * 1024 * 1024 * 0.8:
                    break
                size = f.stat().st_size
                f.unlink()
                total_size -= size
                removed += 1

            if removed:
                log.info("Tile cache cleanup: removed %d tiles", removed)
        except Exception as e:
            log.debug("Tile cache cleanup error: %s", e)


class MapRenderer:
    """Renders OSM tiles into a PyGame surface with theme-specific filters.

    Composes a grid of tiles around the current GPS position, applies theme
    color tinting, and draws a GPS position marker.
    """

    # Theme color filters: (multiply_color, overlay_alpha, darken_factor)
    THEME_FILTERS = {
        "heritage": {"tint": (255, 191, 80), "darken": 0.5, "saturation": 0.3},
        "modern": {"tint": (180, 200, 220), "darken": 0.6, "saturation": 0.2},
        "autodelta": {"tint": (255, 140, 50), "darken": 0.4, "saturation": 0.1},
    }

    def __init__(self, tile_manager: TileManager, grid_cols: int = 4,
                 grid_rows: int = 3):
        self._tiles = tile_manager
        self._grid_cols = grid_cols
        self._grid_rows = grid_rows
        self._zoom = DEFAULT_ZOOM
        self._cached_surface = None
        self._cached_center = (0.0, 0.0)
        self._last_theme = None

    @property
    def zoom(self) -> int:
        return self._zoom

    @zoom.setter
    def zoom(self, value: int):
        self._zoom = max(1, min(18, value))
        self._cached_surface = None

    def render(self, surface, rect: tuple, lat: float, lon: float,
               heading: float, theme_name: str) -> None:
        """Render the map onto a PyGame surface within the given rect.

        Args:
            surface: Target PyGame surface.
            rect: (x, y, w, h) area to render into.
            lat, lon: Current GPS position.
            heading: GPS heading in degrees (0=North).
            theme_name: Theme name for color filtering.
        """
        import pygame

        x, y, w, h = rect
        if w <= 0 or h <= 0:
            return

        # Calculate tile coordinates
        tx, ty = lat_lon_to_tile(lat, lon, self._zoom)
        center_tile_x = int(tx)
        center_tile_y = int(ty)

        # Fractional offset within center tile
        frac_x = tx - center_tile_x
        frac_y = ty - center_tile_y

        # Create map surface (tile grid)
        cols = self._grid_cols
        rows = self._grid_rows
        map_w = cols * TILE_SIZE
        map_h = rows * TILE_SIZE
        map_surf = pygame.Surface((map_w, map_h))
        map_surf.fill((30, 30, 30))  # Dark fallback for missing tiles

        # Top-left tile offset to center the GPS position
        start_tx = center_tile_x - cols // 2
        start_ty = center_tile_y - rows // 2

        # Draw tiles
        tiles_loaded = 0
        for row in range(rows):
            for col in range(cols):
                tile_x = start_tx + col
                tile_y = start_ty + row
                path = self._tiles.get_tile(self._zoom, tile_x, tile_y)
                if path and path.exists():
                    try:
                        tile_surf = pygame.image.load(str(path))
                        map_surf.blit(tile_surf, (col * TILE_SIZE, row * TILE_SIZE))
                        tiles_loaded += 1
                    except Exception:
                        pass

        # Apply theme color filter
        self._apply_theme_filter(map_surf, theme_name)

        # Calculate pixel offset for sub-tile panning
        offset_x = int((frac_x - 0.5) * TILE_SIZE) + (cols // 2) * TILE_SIZE
        offset_y = int((frac_y - 0.5) * TILE_SIZE) + (rows // 2) * TILE_SIZE

        # Crop to target rect size, centered on GPS position
        src_x = offset_x - w // 2
        src_y = offset_y - h // 2
        src_x = max(0, min(map_w - w, src_x))
        src_y = max(0, min(map_h - h, src_y))

        # Blit the visible portion
        visible = map_surf.subsurface(pygame.Rect(src_x, src_y,
                                                   min(w, map_w - src_x),
                                                   min(h, map_h - src_y)))
        surface.blit(visible, (x, y))

        # Draw GPS marker at center
        marker_x = x + w // 2
        marker_y = y + h // 2
        self._draw_gps_marker(surface, marker_x, marker_y, heading, theme_name)

    def _apply_theme_filter(self, surface, theme_name: str) -> None:
        """Apply theme-specific color filter to the map surface."""
        import pygame

        filt = self.THEME_FILTERS.get(theme_name, self.THEME_FILTERS["heritage"])
        tint = filt["tint"]
        darken = filt["darken"]

        # Create a tint overlay
        overlay = pygame.Surface(surface.get_size())
        overlay.fill(tint)

        # Darken first
        dark = pygame.Surface(surface.get_size())
        dark.fill((0, 0, 0))
        dark.set_alpha(int((1.0 - darken) * 255))
        surface.blit(dark, (0, 0))

        # Apply tint with multiply-like effect
        overlay.set_alpha(60)
        surface.blit(overlay, (0, 0))

    def _draw_gps_marker(self, surface, cx: int, cy: int, heading: float,
                         theme_name: str) -> None:
        """Draw a GPS position marker with heading indicator."""
        import pygame

        # Accent colors per theme
        colors = {
            "heritage": (245, 158, 11),
            "modern": (59, 130, 246),
            "autodelta": (236, 91, 19),
        }
        color = colors.get(theme_name, (245, 158, 11))

        # Outer glow circle
        glow_surf = pygame.Surface((40, 40), pygame.SRCALPHA)
        pygame.draw.circle(glow_surf, (*color, 40), (20, 20), 18)
        surface.blit(glow_surf, (cx - 20, cy - 20))

        # Inner solid circle
        pygame.draw.circle(surface, color, (cx, cy), 6)
        pygame.draw.circle(surface, (255, 255, 255), (cx, cy), 4)

        # Heading arrow
        if heading is not None:
            angle_rad = math.radians(-heading + 90)  # Convert to screen coords
            arrow_len = 16
            end_x = cx + int(arrow_len * math.cos(angle_rad))
            end_y = cy - int(arrow_len * math.sin(angle_rad))
            pygame.draw.line(surface, color, (cx, cy), (end_x, end_y), 2)

    def render_static(self, width: int, height: int, lat: float, lon: float,
                      theme_name: str) -> bytes | None:
        """Render a static map image as PNG bytes (for PIL/mockup use).

        Returns PNG bytes or None if tiles are not yet cached.
        """
        try:
            from PIL import Image

            tx, ty = lat_lon_to_tile(lat, lon, self._zoom)
            center_tile_x = int(tx)
            center_tile_y = int(ty)
            frac_x = tx - center_tile_x
            frac_y = ty - center_tile_y

            cols = self._grid_cols
            rows = self._grid_rows
            map_w = cols * TILE_SIZE
            map_h = rows * TILE_SIZE

            img = Image.new("RGB", (map_w, map_h), (30, 30, 30))

            start_tx = center_tile_x - cols // 2
            start_ty = center_tile_y - rows // 2

            tiles_loaded = 0
            for row in range(rows):
                for col in range(cols):
                    tile_x = start_tx + col
                    tile_y = start_ty + row
                    path = self._tiles.get_tile(self._zoom, tile_x, tile_y)
                    if path and path.exists():
                        try:
                            tile_img = Image.open(path).convert("RGB")
                            img.paste(tile_img, (col * TILE_SIZE, row * TILE_SIZE))
                            tiles_loaded += 1
                        except Exception:
                            pass

            if tiles_loaded == 0:
                return None

            # Crop to target size centered on GPS position
            offset_x = int((frac_x - 0.5) * TILE_SIZE) + (cols // 2) * TILE_SIZE
            offset_y = int((frac_y - 0.5) * TILE_SIZE) + (rows // 2) * TILE_SIZE
            left = max(0, offset_x - width // 2)
            top = max(0, offset_y - height // 2)
            right = min(map_w, left + width)
            bottom = min(map_h, top + height)
            img = img.crop((left, top, right, bottom))

            import io
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            return buf.getvalue()

        except Exception as e:
            log.debug("Static map render failed: %s", e)
            return None
