#!/usr/bin/env python3
"""Move the car's hand/BCM-modified config into a local overlay — or move
an existing overlay to a new base.

Until now BCM rewrote its base YAML in place (``config/bcm_config_temp.yaml``
on the car): every UI change and every Bluetooth connect ended up there,
together with Wi-Fi Direct ``*_runtime`` credentials and API keys. The new
scheme keeps the base file pristine and writes only the differences to the
git-ignored ``config/local.yaml``. This tool computes that difference once
for an existing device file:

    # dry run (default) — shows what would be written, writes nothing
    python3 tools/migrate_local_config.py --source /root/bcm_config_temp.yaml.device \\
        --base config/bcm_config.yaml
    # write config/local.yaml (mode 0600)
    python3 tools/migrate_local_config.py --source ... --base ... --write

Every overridden value is put in one of four groups:

WRITE     goes to the overlay.
REVIEW    goes to the overlay, but is hardware-specific (audio sink, GPIO,
          serial ports, blinker monitor) — check it matches this car.
DROPPED   never migrated: ``*_runtime`` state, ``system.platform``,
          placeholders (``PASTE_...``, ``XXXX``), ``--exclude`` paths,
          keys no code reads any more (the old crash detector's
          ``crash_detection.speed_drop_threshold`` & co.) and secrets. A
          secret is reported with the bcm.env variable it belongs in; its
          value is never printed.
SKIPPED   the base wins for features the new base enables on purpose
          (weather, route planner, location, tracking, phonebook, network,
          phone tether, crash detection) — an old ``false`` would silently
          switch them off.
          Only that direction is skipped: a feature the device has on and
          the base off is migrated (WRITE) like any other value.
          Likewise for values the new base changes on purpose
          (BASE_CHANGED_DEFAULTS, e.g. ``tracking.interval_sec`` 30 → 5 s):
          a device file still holding the OLD default never chose it, so
          the base wins; any other device value is a choice and migrated.
          ``--keep-source PATH`` keeps the device value anyway.

The difference and the never-persist rules are the very functions
``src/core/config.py`` uses when BCM saves the overlay, so the result is
exactly what BCM itself would have written.

Second mode — BASE CHANGE (bcm_config_test.yaml → bcm_config.yaml, 23.11):
when ``--source`` is itself an overlay BCM wrote (its header says
``# base: bcm_config_test.yaml``), only the values in it are considered —
the user's own choices — and each is compared with the NEW base:

    # dry run: what config/local.yaml becomes under bcm_config.yaml
    python3 tools/migrate_local_config.py --source config/local.yaml \
        --base config/bcm_config.yaml
    # rewrite it in place (old file kept as local.yaml.bcm_config_test.bak)
    python3 tools/migrate_local_config.py --source config/local.yaml \
        --base config/bcm_config.yaml --write

Values equal to the new base are dropped (they moved into the base), the
rest stays (runtime keys such as ``multimedia.last_bt_device`` included),
and the ``# base:`` header names the new base, so BCM saves again. The
old base is not read: a value the user never set must follow the new base.
BASE_DECISIONS lists the few values the new base sets on purpose against
the old overlay (``modules.phone_tether``: the car phone stays in the car)
— SKIPPED unless ``--keep-source``. SKIP_BASE_WINS and
BASE_CHANGED_DEFAULTS are about old device files and do not apply here.
A secret in the overlay (typed in the UI) would be dropped: --write refuses
until it is in /etc/bcm/bcm.env and ``--drop-secrets`` is given.

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
    overlay_base_name,
    prune_overlay,
    read_overlay_file,
    render_overlay,
    set_path,
)
from src.core.fsutil import atomic_write_bytes, atomic_write_text  # noqa: E402

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_NOTHING = 2

# The base the units run since 23.11 (the car's final config).
DEFAULT_BASE = REPO_ROOT / "config" / "bcm_config.yaml"

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
    # The test base turns crash detection on deliberately since #128 (it
    # collects the data the thresholds are tuned with, and crash_sms /
    # call112 need it). Every device bcm_config_temp.yaml still carries the
    # old default `crash_detect: false` — nobody chose it, so it must not
    # switch the detector off on a migrated car. --keep-source keeps it off.
    "modules.crash_detect",
)

#: Keys no code reads any more → why. Copying them into local.yaml would
#: only carry dead values along (and a start-up warning about them).
#: Must match ``LEGACY_KEYS`` in src/safety/crash_detect.py (a test checks
#: it); kept as a literal so the tool does not import the detector module.
DROP_OBSOLETE: dict = {
    "crash_detection.speed_drop_threshold": "no longer read (old crash detector)",
    "crash_detection.g_force_threshold": "no longer read (old crash detector)",
    "crash_detection.post_crash_record_sec": "no longer read (old crash detector)",
}

#: Values the new base changes on purpose → the OLD default(s) they replace.
#: The device file (bcm_config_temp.yaml) predates the change and still
#: carries the old default; copying it to local.yaml would silently undo
#: the change (stage 4: 30 s points made the GPX too coarse). A device
#: value that is NOT an old default was set by someone and is migrated.
BASE_CHANGED_DEFAULTS: dict = {
    "tracking.interval_sec": (30,),
}

#: Base change (overlay mode): new base file name → {dot-path: why}. These
#: values the new base sets deliberately; an override from the old overlay
#: would silently undo that decision, so it is SKIPPED (--keep-source keeps
#: it). Keep the reasons short: they are printed in the report.
BASE_DECISIONS: dict = {
    "bcm_config.yaml": {
        # Decision 23.11: the Redmi stays in the car and gives internet over
        # USB (car_phone); Bluetooth PAN from the driver's phone is only the
        # optional fallback, off in the final config.
        "modules.phone_tether": "decyzja 23.11: internet z Redmi po USB; "
                                "Bluetooth PAN tylko jako zapas",
    },
}

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
                   help="device's modified config (e.g. a copy of bcm_config_temp.yaml), "
                        "or an overlay BCM wrote for another base (config/local.yaml "
                        "with '# base: bcm_config_test.yaml') — then it is rewritten for --base")
    p.add_argument("--base", type=Path, default=DEFAULT_BASE,
                   help="base config BCM will run with (default: config/bcm_config.yaml)")
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
    p.add_argument("--drop-secrets", action="store_true",
                   help="base change only: allow --write although secrets (API keys, "
                        "passwords) from the overlay are dropped — put them into "
                        "/etc/bcm/bcm.env first")
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


def build_plan(source: dict, base: dict, *, excludes=(), keep_source=(),
               skip_base_wins=SKIP_BASE_WINS, changed_defaults=None,
               decisions=None) -> dict:
    """Classify every value in ``source`` that differs from ``base``.

    Returns a dict with lists ``write``/``review``/``dropped``/``skipped``
    (display-safe: sensitive values redacted) and ``overlay`` — the actual
    data to write (WRITE + REVIEW). ``skip_base_wins`` / ``changed_defaults``
    are the device-file rules (defaults: SKIP_BASE_WINS,
    BASE_CHANGED_DEFAULTS); ``decisions`` ({dot-path: reason}) skips any
    different value of these paths (base change, BASE_DECISIONS).
    """
    if changed_defaults is None:
        changed_defaults = BASE_CHANGED_DEFAULTS
    decisions = decisions or {}
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
        if _covered_by_any(DROP_OBSOLETE, dotpath):
            plan["dropped"].append({"path": dotpath,
                                    "reason": next(r for k, r in DROP_OBSOLETE.items()
                                                   if _covers(k, dotpath))})
            continue
        if _covered_by_any(excludes, dotpath):
            plan["dropped"].append({"path": dotpath, "reason": "excluded (--exclude)"})
            continue
        # "Base wins" only in the direction it exists for: the device has a
        # feature off that the new base turns on. A device `true` over a
        # base `false` is a feature the user enabled — migrating that is
        # exactly right (skipping it would silently switch weather & co. off).
        keep = _covered_by_any(keep_source, dotpath)
        base_value = get_path(base, dotpath)
        if dotpath in decisions and not keep:
            plan["skipped"].append({
                "path": dotpath,
                "source": safe_value(dotpath, value),
                "base": safe_value(dotpath, base_value),
                "reason": decisions[dotpath],
            })
            continue
        if (_covered_by_any(skip_base_wins, dotpath)
                and not keep and not value and base_value):
            plan["skipped"].append({
                "path": dotpath,
                "source": safe_value(dotpath, value),
                "base": safe_value(dotpath, base_value),
            })
            continue
        old_defaults = changed_defaults.get(dotpath)
        if (old_defaults is not None and not keep and not isinstance(value, bool)
                and value in old_defaults and base_value is not None):
            plan["skipped"].append({
                "path": dotpath,
                "source": safe_value(dotpath, value),
                "base": safe_value(dotpath, base_value),
                "reason": "old default; the new base changes it on purpose",
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


def print_report(plan: dict, args: argparse.Namespace, out: Path, out_exists: bool,
                 source_base: Optional[str] = None) -> None:
    print(f"Source: {args.source}"
          + (f" (overlay for base {source_base})" if source_base else ""))
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
        why = f" — {item['reason']}" if "reason" in item else ""
        print(f"  {item['path']}: device {_fmt(item['source'])}, base {_fmt(item['base'])}{why}")
    if "same" in plan:
        print(f"IN BASE ({len(plan['same'])}) — the new base already has this value, "
              f"dropped from the overlay:")
        for path in plan["same"]:
            print(f"  {path}")
    print()


def _base_change_backup(out: Path, old_base: str) -> Path:
    """``local.yaml.bcm_config_test.bak`` — named after the old base, so a
    later migration does not overwrite it and BCM's own ``local.yaml.bak``
    (its crash-recovery copy) stays what it is."""
    return out.with_name(f"{out.name}.{Path(old_base).stem}.bak")


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
        if out.resolve() == args.base.resolve():
            print("error: --out must not be the base file", file=sys.stderr)
            return EXIT_ERROR
        source = _load_yaml_mapping(args.source, "source")
        base = _load_yaml_mapping(args.base, "base")
        try:
            source_raw = args.source.read_bytes()
        except OSError as e:
            raise ValueError(f"cannot read source {args.source}: {e}") from None
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return EXIT_ERROR

    # An overlay BCM wrote records its base ("# base: NAME"); a device file
    # (a full config) never does. Overlay values are all deliberate choices,
    # so the device-file rules do not apply to them.
    source_base = overlay_base_name(source_raw)
    in_place = out.resolve() == args.source.resolve()
    if in_place and source_base is None:
        print("error: --out must not be the source file (only an overlay with a "
              "'# base:' header can be rewritten in place)", file=sys.stderr)
        return EXIT_ERROR
    if in_place and args.merge_existing:
        print("error: --merge-existing makes no sense when --out is the source "
              "(the source values are already all there)", file=sys.stderr)
        return EXIT_ERROR

    if source_base is not None:
        if source_base == args.base.name:
            print(f"{args.source} is already written for base {source_base} — "
                  f"nothing to migrate.")
            return EXIT_NOTHING
        # Overlay applied on the NEW base: the difference is exactly the
        # overlay values that still differ from it.
        plan = build_plan(deep_merge(base, source), base, excludes=args.exclude,
                          keep_source=args.keep_source, skip_base_wins=(),
                          changed_defaults={},
                          decisions=BASE_DECISIONS.get(args.base.name, {}))
        # Listed (not printed by value — the base holds the same) so the
        # dry run shows where each setting of the old overlay went.
        missing = object()
        plan["same"] = [p for p, v in iter_leaves(source)
                        if get_path(base, p, missing) == v]
    else:
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
        "source_base": source_base, "in_place": in_place,
        "out_exists": out_exists, "dry_run": not args.write, "written": False,
        **{k: plan[k] for k in ("write", "review", "dropped", "skipped")},
    }
    if "same" in plan:
        result["same"] = plan["same"]

    def finish(code: int, message: str = "", *, stream=sys.stdout) -> int:
        if args.json:
            result["exit_code"] = code
            if message:
                result["message"] = message
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            print_report(plan, args, out, out_exists, source_base)
            if message:
                print(message, file=stream)
        return code

    if not overlay and source_base is None:
        return finish(EXIT_NOTHING, "Nothing to migrate — the source matches the base "
                                    "(apart from dropped/skipped values).")
    # Base change with nothing left: still rewrite — an empty overlay with the
    # new "# base:" header is what lets BCM save again.

    # An overlay BCM wrote may legitimately hold a secret typed in the UI
    # (BCM only prunes secrets that really come from bcm.env). Dropping it
    # silently would leave the feature without its key after the rewrite —
    # so --write refuses until the user moved it to bcm.env and says so.
    # Only the variable names are printed, never a value.
    lost_secrets = sorted({d["env_var"] for d in plan["dropped"] if "env_var" in d})
    if source_base is not None and lost_secrets and not args.drop_secrets:
        msg = (f"the overlay holds secrets that the rewrite drops: {', '.join(lost_secrets)} "
               f"— put them into /etc/bcm/bcm.env first, then re-run with --drop-secrets.")
        if args.write:
            return finish(EXIT_ERROR, f"error: {msg}", stream=sys.stderr)
        return finish(EXIT_OK, f"Dry run — nothing written. Note: --write would refuse: {msg}")

    if in_place:
        if not args.write:
            return finish(EXIT_OK, f"Dry run — nothing written. Re-run with --write to "
                                   f"rewrite {out} for {args.base.name} (old file kept as "
                                   f"{_base_change_backup(out, source_base).name}).")
        try:
            # Byte copy of the old overlay first: the rollback (BCM_CONFIG back
            # to the old base) needs it, and BCM never touches this name.
            atomic_write_bytes(_base_change_backup(out, source_base), source_raw,
                               mode=LOCAL_FILE_MODE)
            atomic_write_text(out, render_overlay(final, base_name=args.base.name),
                              mode=LOCAL_FILE_MODE)
        except OSError as e:
            return finish(EXIT_ERROR, f"error: writing {out} failed: {e}", stream=sys.stderr)
        result["written"] = True
        return finish(EXIT_OK, f"Wrote {out} for {args.base.name} (mode 0600); the old file "
                               f"is {_base_change_backup(out, source_base).name}. Restart "
                               f"bcm-headunit.")

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
