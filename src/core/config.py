"""YAML configuration loader with platform auto-detection."""

import os
import platform
import copy
from pathlib import Path
from typing import Any, Optional

import yaml


DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent.parent.parent / "config" / "bcm_config.yaml"


def _detect_platform() -> str:
    """Detect whether we're running on x86 or Orange Pi (arm64)."""
    machine = platform.machine().lower()
    if machine in ("aarch64", "armv7l", "armv8l"):
        return "opi"
    return "x86"


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
        path = Path(config_path) if config_path else DEFAULT_CONFIG_PATH
        if not path.exists():
            raise FileNotFoundError(f"Config file not found: {path}")

        with open(path, "r") as f:
            self._data: dict = yaml.safe_load(f) or {}

        # Resolve platform
        if platform_override:
            self._data["system"]["platform"] = platform_override
        elif self._data.get("system", {}).get("platform") == "auto":
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

    def is_module_enabled(self, module_name: str) -> bool:
        """Check if a module is enabled in the config."""
        return bool(self.get(f"modules.{module_name}", False))

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
