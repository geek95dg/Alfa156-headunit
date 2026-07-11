"""YAML configuration loader with platform auto-detection."""

import platform
import copy
from pathlib import Path
from typing import Any, Optional

import yaml


DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent.parent.parent / "config" / "bcm_config.yaml"


def _detect_platform() -> str:
    """Detect whether we're running on x86, Orange Pi 5 Pro/Plus, or OPi PC.

    Detection order:
      1. armv7l with Allwinner H3 → opi_pc (Orange Pi PC 1.2, bench rig)
      2. aarch64 (RK3588 / RK3588S / etc.) → opi (Orange Pi 5 Pro / 5 Plus,
         production)
      3. Fallback → x86 (development / simulation)
    """
    machine = platform.machine().lower()
    if machine in ("aarch64", "armv7l", "armv8l"):
        # Distinguish OPi PC (H3, armv7l) from OPi 5 Pro / 5 Plus (aarch64)
        if machine == "armv7l" and _is_allwinner_h3():
            return "opi_pc"
        return "opi"
    return "x86"


def _is_allwinner_h3() -> bool:
    """Check if running on Allwinner H3 SoC (Orange Pi PC / PC Plus / One)."""
    try:
        dt_model = Path("/proc/device-tree/model")
        if dt_model.exists():
            model = dt_model.read_text().lower()
            if "orange pi pc" in model or "sun8i-h3" in model:
                return True
        # Fallback: check /proc/cpuinfo for sun8i
        cpuinfo = Path("/proc/cpuinfo")
        if cpuinfo.exists():
            text = cpuinfo.read_text().lower()
            if "sun8i" in text or "allwinner" in text:
                return True
    except Exception:
        pass
    return False


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge override into base, returning a new dict."""
    result = copy.deepcopy(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


class BCMConfig:
    """Loads and provides access to the BCM configuration.

    Usage:
        cfg = BCMConfig()                           # auto-detect platform
        cfg = BCMConfig(platform_override="x86")    # force platform
        cfg = BCMConfig(config_path="other.yaml")   # custom config file

        value = cfg.get("display.dashboard.width")  # dot-notation access
        value = cfg["display"]["dashboard"]["width"] # dict-style access
    """

    def __init__(
        self,
        config_path: Optional[str] = None,
        platform_override: Optional[str] = None,
    ):
        if config_path:
            path = Path(config_path)
        else:
            path = self._pick_default_config(platform_override)
        if not path.exists():
            raise FileNotFoundError(f"Config file not found: {path}")

        with open(path, "r") as f:
            self._data: dict = yaml.safe_load(f) or {}

        # Resolve platform
        self._data.setdefault("system", {})
        if platform_override:
            self._data["system"]["platform"] = platform_override
        elif self._data.get("system", {}).get("platform") in ("auto", None):
            self._data["system"]["platform"] = _detect_platform()

        self.platform: str = self._data["system"]["platform"]
        self.config_path: Path = path.resolve()

    def get(self, dotpath: str, default: Any = None) -> Any:
        """Access a nested config value using dot notation.

        Example: cfg.get("display.dashboard.width") -> 800
        """
        keys = dotpath.split(".")
        node = self._data
        for key in keys:
            if isinstance(node, dict) and key in node:
                node = node[key]
            else:
                return default
        return node

    def set(self, dotpath: str, value: Any) -> None:
        """Set a nested config value using dot notation (in-memory only)."""
        keys = dotpath.split(".")
        node = self._data
        for key in keys[:-1]:
            if key not in node or not isinstance(node[key], dict):
                node[key] = {}
            node = node[key]
        node[keys[-1]] = value

    def save(self, path: Optional[str] = None) -> None:
        """Persist current config back to YAML file."""
        out = Path(path) if path else self.config_path
        out.parent.mkdir(parents=True, exist_ok=True)
        with open(out, "w") as f:
            yaml.dump(self._data, f, default_flow_style=False, sort_keys=False)

    @staticmethod
    def _pick_default_config(platform_override: Optional[str]) -> Path:
        """No --config given: pick the YAML matching the platform.

        A bench rig booted without --config used to silently load the
        x86-targeted bcm_config.yaml (wrong GPIO/serial values). Now the
        opi_pc-specific file is selected automatically when the hardware
        (or an explicit override) says opi_pc.
        """
        plat = platform_override or _detect_platform()
        if plat == "opi_pc":
            candidate = DEFAULT_CONFIG_PATH.parent / "bcm_config_opi_pc.yaml"
            if candidate.exists():
                return candidate
        return DEFAULT_CONFIG_PATH

    def is_module_enabled(self, module_name: str) -> bool:
        """Check if a module is enabled in the config.

        Reads ``modules.<name>``. Falls back to the legacy
        ``modules_v85.<name>`` block (pre-v8.5.2 configs kept the v8.5
        modules there, but no code ever read it — so alarm, crash_detect,
        battery etc. were silently disabled). ``battery`` was historically
        spelled ``battery_backup`` in that block.
        """
        val = self.get(f"modules.{module_name}")
        if val is None:
            legacy_name = {"battery": "battery_backup"}.get(module_name, module_name)
            val = self.get(f"modules_v85.{legacy_name}")
        return bool(val)

    @property
    def data(self) -> dict:
        """Return the raw config dict (read-only copy)."""
        return copy.deepcopy(self._data)

    def __getitem__(self, key: str) -> Any:
        return self._data[key]

    def __contains__(self, key: str) -> bool:
        return key in self._data

    def __repr__(self) -> str:
        return f"BCMConfig(platform={self.platform!r}, path={self.config_path})"
