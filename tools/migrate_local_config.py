#!/usr/bin/env python3
"""Move the car's hand/BCM-modified config into a local overlay.

Until now BCM rewrote its base YAML in place (``config/bcm_config_temp.yaml``
on the car): every UI change and every Bluetooth connect ended up there,
together with Wi-Fi Direct ``*_runtime`` credentials and API keys. The new
scheme keeps the base file pristine and writes only the differences to the
git-ignored ``config/local.yaml``. This tool computes that difference once
for an existing device file:

    # dry run (default) — shows what would be written, writes nothing
    python3 tools/migrate_local_config.py --source /root/bcm_config_temp.yaml.device \\
        --base config/bcm_config_test.yaml
    # write config/local.yaml (mode 0600)
    python3 tools/migrate_local_config.py --source ... --base ... --write

Every overridden value is put in one of four groups:

WRITE     goes to the overlay.
REVIEW    goes to the overlay, but is hardware-specific (audio sink, GPIO,
          serial ports, blinker monitor) — check it matches this car.
DROPPED   never migrated: ``*_runtime`` state, ``system.platform``,
          placeholders (``PASTE_...``, ``XXXX``), ``--exclude`` paths and
          secrets. A secret is reported with the bcm.env variable it belongs
          in; its value is never printed.
SKIPPED   the base wins for features the new base enables on purpose
          (weather, route planner, location, tracking, phonebook, network,
          phone tether) — an old ``false`` would silently switch them off.
          Only that direction is skipped: a feature the device has on and
          the base off is migrated (WRITE) like any other value.
          ``--keep-source PATH`` keeps the device value anyway.

The difference and the never-persist rules are the very functions
``src/core/config.py`` uses when BCM saves the overlay, so the result is
exactly what BCM itself would have written.

Exit codes: 0 = OK (plan shown or file written), 1 = error, 2 = nothing to
migrate.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    # Run as a plain script (python tools/migrate_local_config.py): make the
    # `src` package importable without installing anything.
    sys.path.insert(0, str(REPO_ROOT))

import yaml  # noqa: E402

from src.core.config import (  # noqa: E402
    LOCAL_FILE_MODE,
    SECRET_ENV_MAP,
    compute_overlay,
    deep_merge,
    default_local_path,
    get_path,
    iter_leaves,
    prune_overlay,
    read_overlay_file,
    render_overlay,
    set_path,
)
from src.core.fsutil import atomic_write_bytes, atomic_write_text  # noqa: E402

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_NOTHING = 2

DEFAULT_BASE = REPO_ROOT / "config" / "bcm_config_test.yaml"

#: Modules the new base enables deliberately — an old `false` must not win
#: over a base `true` (the opposite direction is migrated normally).
SKIP_BASE_WINS = (
    "modules.weather",
    "modules.route_planner",
    "modules.location",
    "modules.tracking",
    "modules.phonebook",
    "modules.network",
    "modules.phone_tether",
)

#: Hardware-specific values — migrated, but listed for a human to check.
REVIEW_PATHS = (
    "audio.sink",
    "modules.blinker_monitor",
    "gpio",
    "serial",
)

_DOTPATH_RE = re.compile(r"^[A-Za-z0-9_-]+(\.[A-Za-z0-9_-]+)*$")
_SENSITIVE_NAME_RE = re.compile(r"(key|pass|token|secret|psk)", re.IGNORECASE)
_HEX32_RE = re.compile(r"^[0-9a-fA-F]{32}$")


class _Parser(argparse.ArgumentParser):
    """argparse exits with 2 on usage errors; 2 means "nothing to migrate"
    here, so report usage errors as 1."""

    def error(self, message: str):  # type: ignore[override]
        self.print_usage(sys.stderr)
        print(f"{self.prog}: error: {message}", file=sys.stderr)
        raise SystemExit(EXIT_ERROR)


def parse_args(argv: Optional[list[str]]) -> argparse.Namespace:
    p = _Parser(
        prog="migrate_local_config.py",
        description="Compute config/local.yaml from a device-modified config YAML "
                    "(dry run unless --write).",
    )
    p.add_argument("--source", required=True, type=Path,
                   help="device's modified config (e.g. a copy of bcm_config_temp.yaml)")
    p.add_argument("--base", type=Path, default=DEFAULT_BASE,
                   help="base config BCM will run with (default: config/bcm_config_test.yaml)")
    p.add_argument("--out", type=Path, default=None,
                   help="overlay to write (default: local.yaml next to --base)")
    p.add_argument("--write", action="store_true",
                   help="actually write --out (default: dry run)")
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--force", action="store_true",
                      help="overwrite an existing --out (old file kept as .bak)")
    mode.add_argument("--merge-existing", action="store_true",
                      help="merge into an existing --out; its values win")
    p.add_argument("--exclude", action="append", default=[], metavar="DOTPATH",
                   help="do not migrate this path (and everything below it); repeatable")
    p.add_argument("--keep-source", action="append", default=[], metavar="DOTPATH",
                   help="keep the device value for a SKIPPED path; repeatable")
    p.add_argument("--json", action="store_true", help="machine-readable report on stdout")
    return p.parse_args(argv)


# ── Classification ────────────────────────────────────────────────────────

def _covers(prefix: str, dotpath: str) -> bool:
    return dotpath == prefix or dotpath.startswith(prefix + ".")


def _covered_by_any(prefixes, dotpath: str) -> bool:
    return any(_covers(p, dotpath) for p in prefixes)


def _secret_for(dotpath: str) -> Optional[str]:
    """Dot-path of the SECRET_ENV_MAP entry covering ``dotpath``, if any."""
    for secret in SECRET_ENV_MAP:
        if _covers(secret, dotpath):
            return secret
    return None


def is_placeholder(value: Any) -> bool:
    """Template filler that must never be migrated (``PASTE_ORS_KEY_HERE``, ``XXXX``)."""
    if not isinstance(value, str):
        return False
    v = value.strip().upper()
    return v.startswith("PASTE_") or (len(v) >= 3 and set(v) == {"X"})


def is_sensitive(dotpath: str, value: Any) -> bool:
    """Values never printed: secrets, anything that looks like a key/password,
    and 32-hex tokens (the OWM key format)."""
    if _secret_for(dotpath):
        return True
    if _SENSITIVE_NAME_RE.search(dotpath.rsplit(".", 1)[-1]):
        return True
    return isinstance(value, str) and bool(_HEX32_RE.match(value.strip()))


def redacted(value: Any) -> str:
    return f"<redacted, {len(str(value))} chars>"


def safe_value(dotpath: str, value: Any) -> Any:
    """The value itself, or a redaction marker for sensitive ones."""
    if is_sensitive(dotpath, value):
        return redacted(value)
    return value


def _dropped_reason(dotpath: str, value: Any) -> dict:
    """Why a never-persisted path is dropped (no secret value in the result)."""
    secret = _secret_for(dotpath)
    if secret is not None:
        if not str(value).strip():
            return {"path": dotpath, "reason": "empty value"}
        if is_placeholder(value):
            return {"path": dotpath, "reason": "placeholder value"}
        var = SECRET_ENV_MAP[secret]
        return {
            "path": dotpath, "env_var": var, "value": redacted(value),
            "reason": f"secret: put into /etc/bcm/bcm.env as {var}, "
                      f"and ROTATE if it was ever committed",
        }
    if dotpath == "system.platform":
        return {"path": dotpath, "reason": "resolved at start-up (--platform)"}
    return {"path": dotpath, "reason": "runtime state (*_runtime), regenerated by BCM"}


def build_plan(source: dict, base: dict, *, excludes=(), keep_source=()) -> dict:
    """Classify every value in ``source`` that differs from ``base``.

    Returns a dict with lists ``write``/``review``/``dropped``/``skipped``
    (display-safe: sensitive values redacted) and ``overlay`` — the actual
    data to write (WRITE + REVIEW).
    """
    raw_overlay = compute_overlay(base, source)
    # Same never-persist rule (and the same code) as BCMConfig.save(), with
    # every SECRET_ENV_MAP path treated as env-provided: on the car secrets
    # belong in /etc/bcm/bcm.env, not in the overlay.
    pruned, never = prune_overlay(raw_overlay, SECRET_ENV_MAP)

    plan: dict = {"write": [], "review": [], "dropped": [], "skipped": [], "overlay": {}}
    for dotpath in never:
        plan["dropped"].append(_dropped_reason(dotpath, get_path(raw_overlay, dotpath)))

    for dotpath, value in iter_leaves(pruned):
        if is_placeholder(value):
            plan["dropped"].append({"path": dotpath, "reason": "placeholder value"})
            continue
        if _covered_by_any(excludes, dotpath):
            plan["dropped"].append({"path": dotpath, "reason": "excluded (--exclude)"})
            continue
        # "Base wins" only in the direction it exists for: the device has a
        # feature off that the new base turns on. A device `true` over a
        # base `false` is a feature the user enabled — migrating that is
        # exactly right (skipping it would silently switch weather & co. off).
        if (_covered_by_any(SKIP_BASE_WINS, dotpath)
                and not _covered_by_any(keep_source, dotpath)
                and not value and get_path(base, dotpath)):
            plan["skipped"].append({
                "path": dotpath,
                "source": safe_value(dotpath, value),
                "base": safe_value(dotpath, get_path(base, dotpath)),
            })
            continue
        group = "review" if _covered_by_any(REVIEW_PATHS, dotpath) else "write"
        plan[group].append({"path": dotpath, "value": safe_value(dotpath, value)})
        set_path(plan["overlay"], dotpath, value)
    return plan


# ── I/O ───────────────────────────────────────────────────────────────────

def _load_yaml_mapping(path: Path, what: str) -> dict:
    """Load a YAML mapping or raise ValueError with a value-free message.

    yaml error messages quote the offending line, which may hold a secret —
    only the position is reported.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        raise ValueError(f"cannot read {what} {path}: {e}") from None
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as e:
        mark = getattr(e, "problem_mark", None)
        where = f" (line {mark.line + 1}, column {mark.column + 1})" if mark else ""
        raise ValueError(f"{what} {path} is not valid YAML{where}") from None
    if not isinstance(data, dict):
        raise ValueError(f"{what} {path} must contain a mapping at the top level")
    return data


def _fmt(value: Any) -> str:
    if isinstance(value, str) and value.startswith("<redacted"):
        return value
    return json.dumps(value, ensure_ascii=False)


def print_report(plan: dict, args: argparse.Namespace, out: Path, out_exists: bool) -> None:
    print(f"Source: {args.source}")
    print(f"Base:   {args.base}")
    print(f"Out:    {out} ({'exists' if out_exists else 'absent'})")
    print()
    print(f"WRITE ({len(plan['write'])}):")
    for item in plan["write"]:
        print(f"  {item['path']} = {_fmt(item['value'])}")
    print(f"REVIEW ({len(plan['review'])}) — written, check that they match this car:")
    for item in plan["review"]:
        print(f"  {item['path']} = {_fmt(item['value'])}")
    print(f"DROPPED ({len(plan['dropped'])}) — not migrated:")
    for item in plan["dropped"]:
        suffix = f" ({item['value']})" if "value" in item else ""
        print(f"  {item['path']} — {item['reason']}{suffix}")
    print(f"SKIPPED ({len(plan['skipped'])}) — base wins (keep the device value with "
          f"--keep-source PATH):")
    for item in plan["skipped"]:
        print(f"  {item['path']}: device {_fmt(item['source'])}, base {_fmt(item['base'])}")
    print()


def main(argv: Optional[list[str]] = None) -> int:
    try:
        args = parse_args(argv)
    except SystemExit as e:  # --help (0) or a usage error (1)
        return e.code if isinstance(e.code, int) else EXIT_ERROR
    for dotpath in (*args.exclude, *args.keep_source):
        if not _DOTPATH_RE.match(dotpath):
            print(f"error: invalid dot-path {dotpath!r}", file=sys.stderr)
            return EXIT_ERROR

    out: Path = args.out if args.out is not None else default_local_path(args.base)
    try:
        if out.resolve() in (args.base.resolve(), args.source.resolve()):
            print("error: --out must not be the base or the source file", file=sys.stderr)
            return EXIT_ERROR
        source = _load_yaml_mapping(args.source, "source")
        base = _load_yaml_mapping(args.base, "base")
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return EXIT_ERROR

    plan = build_plan(source, base, excludes=args.exclude, keep_source=args.keep_source)
    overlay = plan["overlay"]
    out_exists = out.exists()

    existing: dict = {}
    existing_raw = b""
    if out_exists and (args.merge_existing or args.force):
        status, data, reason, existing_raw = read_overlay_file(out)
        if args.merge_existing:
            if status != "ok":
                print(f"error: cannot merge into {out}: {reason}", file=sys.stderr)
                return EXIT_ERROR
            existing = data or {}
        elif status != "ok":
            existing_raw = b""  # do not keep a broken file as the backup

    final = deep_merge(overlay, existing) if existing else overlay
    result: dict = {
        "source": str(args.source), "base": str(args.base), "out": str(out),
        "out_exists": out_exists, "dry_run": not args.write, "written": False,
        **{k: plan[k] for k in ("write", "review", "dropped", "skipped")},
    }

    def finish(code: int, message: str = "", *, stream=sys.stdout) -> int:
        if args.json:
            result["exit_code"] = code
            if message:
                result["message"] = message
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print_report(plan, args, out, out_exists)
            if message:
                print(message, file=stream)
        return code

    if not overlay:
        return finish(EXIT_NOTHING, "Nothing to migrate — the source matches the base "
                                    "(apart from dropped/skipped values).")

    if out_exists and not (args.force or args.merge_existing):
        msg = (f"{out} already exists — use --merge-existing (existing values win) "
               f"or --force (overwrite, old file kept as .bak).")
        if args.write:
            return finish(EXIT_ERROR, f"error: {msg}", stream=sys.stderr)
        return finish(EXIT_OK, f"Dry run — nothing written. Note: --write would refuse: {msg}")

    if not args.write:
        return finish(EXIT_OK, f"Dry run — nothing written. Re-run with --write to create {out} "
                               f"(mode 0600).")

    try:
        if existing_raw:
            atomic_write_bytes(out.with_name(out.name + ".bak"), existing_raw,
                               mode=LOCAL_FILE_MODE)
        # Record the base the difference was computed against: BCM refuses
        # to rewrite an overlay under a different base (rollback safety).
        atomic_write_text(out, render_overlay(final, base_name=args.base.name),
                          mode=LOCAL_FILE_MODE)
    except OSError as e:
        return finish(EXIT_ERROR, f"error: writing {out} failed: {e}", stream=sys.stderr)
    result["written"] = True
    return finish(EXIT_OK, f"Wrote {out} (mode 0600). Move the DROPPED secrets to "
                           f"/etc/bcm/bcm.env, then restart bcm-headunit.")


if __name__ == "__main__":
    sys.exit(main())
