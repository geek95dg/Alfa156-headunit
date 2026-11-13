"""Static checks for the shell scripts in config/scripts/.

These scripts run as root on the car's head unit (full setup, power-loss
hardening, NAT), so the suite NEVER executes them: it only parses them
(``bash -n``), lints the ones held to the shellcheck gate, and pins the
regressions that once made the box slow to boot or put it at risk of not
booting at all (``fsck.mode=skip`` with hard power cuts, a 30 s sleep in
bcm-nat.service, NAT into the phone's own BT PAN link, ...).
"""

import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SCRIPTS = REPO / "config" / "scripts"
SYSTEMD = REPO / "config" / "systemd"

SHELL_SCRIPTS = sorted(SCRIPTS.glob("*.sh"))

# Held to ``shellcheck -S warning``. Older scripts predate the gate: they
# are still linted when shellcheck is installed, but as non-strict xfail so
# CI reports them without going red. Move a script here once it is clean.
SHELLCHECK_STRICT = {"bcm-harden.sh", "bcm-nat.sh"}


def _read(name: str) -> str:
    return (SCRIPTS / name).read_text(encoding="utf-8")


def _code_lines(text: str) -> list[str]:
    """Non-empty lines that are not pure comments."""
    return [l for l in text.splitlines() if l.strip() and not l.strip().startswith("#")]


def _total(text: str) -> int:
    m = re.search(r"^TOTAL=(\d+)\s*$", text, flags=re.M)
    assert m, "no TOTAL=N line"
    return int(m.group(1))


def _step_numbers(text: str) -> list[int]:
    return [int(n) for n in re.findall(r'^\s*step\s+(\d+)\s+"', text, flags=re.M)]


def _function_body(text: str, name: str) -> str:
    m = re.search(rf"^{re.escape(name)}\(\)\s*\{{\n(.*?)^\}}", text, flags=re.M | re.S)
    assert m, f"function {name}() not found"
    return m.group(1)


# ─── Every script parses ────────────────────────────────────────────────


def test_scripts_found():
    names = {p.name for p in SHELL_SCRIPTS}
    assert {"setup-x86.sh", "bcm-harden.sh", "bcm-nat.sh", "apply-fixes.sh", "cleanup-x86.sh"} <= names
    assert SHELLCHECK_STRICT <= names


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash not installed")
@pytest.mark.parametrize("script", SHELL_SCRIPTS, ids=lambda p: p.name)
def test_bash_syntax(script):
    # -n: read and parse only, nothing is executed.
    res = subprocess.run(["bash", "-n", str(script)], capture_output=True, text=True, timeout=30)
    assert res.returncode == 0, res.stderr


def _shellcheck_params():
    for path in SHELL_SCRIPTS:
        marks = []
        if path.name not in SHELLCHECK_STRICT:
            marks.append(pytest.mark.xfail(reason="legacy script, not yet held to shellcheck", strict=False))
        yield pytest.param(path, marks=marks, id=path.name)


@pytest.mark.skipif(shutil.which("shellcheck") is None, reason="shellcheck not installed")
@pytest.mark.parametrize("script", list(_shellcheck_params()))
def test_shellcheck(script):
    res = subprocess.run(
        ["shellcheck", "-S", "warning", str(script)], capture_output=True, text=True, timeout=120
    )
    assert res.returncode == 0, res.stdout + res.stderr


# ─── Units: the head unit runs the tracked test config ──────────────────


class TestUnits:
    def test_headunit_unit_uses_test_config_and_env_file(self):
        unit = (SYSTEMD / "bcm-headunit-x86.service").read_text(encoding="utf-8")
        assert "Environment=BCM_CONFIG=config/bcm_config_test.yaml" in unit
        assert "EnvironmentFile=-/etc/bcm/bcm.env" in unit
        exec_start = [l for l in unit.splitlines() if l.startswith("ExecStart=")]
        assert len(exec_start) == 1
        assert "bcm_config_test.yaml" in exec_start[0]
        assert "bcm_config_temp.yaml" not in exec_start[0]

    def test_watcher_unit_uses_test_config_and_env_file(self):
        unit = (SYSTEMD / "bcm-ignition-watcher.service").read_text(encoding="utf-8")
        assert "Environment=BCM_CONFIG=config/bcm_config_test.yaml" in unit
        assert "EnvironmentFile=-/etc/bcm/bcm.env" in unit
        # The watcher starts the head unit by this exact name ...
        assert "--service bcm-headunit.service" in unit

    def test_headunit_installed_under_the_name_the_watcher_starts(self):
        # ... so both installers must use it.
        target = "/etc/systemd/system/bcm-headunit.service"
        setup = _read("setup-x86.sh")
        assert f'bcm-headunit-x86.service" {target}' in setup
        harden = _read("bcm-harden.sh")
        assert re.search(r'bcm-headunit-x86\.service"\s+' + re.escape(target), harden)

    def test_timesync_files_exist(self):
        assert (SYSTEMD / "bcm-timesync.service").is_file()
        assert (SYSTEMD / "bcm-timesync.timer").is_file()
        assert (SCRIPTS / "bcm-timesync.sh").is_file()


# ─── setup-x86.sh ──────────────────────────────────────────────────────


class TestSetupX86:
    text = _read("setup-x86.sh")

    def test_never_skips_fsck(self):
        # Every ignition-off is a hard power cut on this car; skipping fsck
        # lets ext4 damage pile up until the box does not boot.
        assert "fsck.mode=skip" not in self.text
        grub_line = [l for l in self.text.splitlines() if l.startswith("GRUB_CMDLINE_LINUX_DEFAULT=")]
        assert len(grub_line) == 1
        assert "fsck.repair=yes" in grub_line[0]

    def test_total_matches_step_calls(self):
        total = _total(self.text)
        assert total == 15
        assert _step_numbers(self.text) == list(range(1, total + 1))

    def test_runs_hardening_without_units(self):
        assert re.search(r'bcm-harden\.sh"?\s+--no-units', self.text)

    def test_installs_and_enables_timesync(self):
        assert 'bcm-timesync.sh" /usr/local/bin/bcm-timesync.sh' in self.text
        assert 'bcm-timesync.service" /etc/systemd/system/bcm-timesync.service' in self.text
        assert 'bcm-timesync.timer" /etc/systemd/system/bcm-timesync.timer' in self.text
        assert "systemctl enable --now bcm-timesync.timer" in self.text

    def test_cleanup_step_removes_timers(self):
        assert "rm -f /etc/systemd/system/bcm-*.timer" in self.text
        assert re.search(r"for timer in [^\n]*bcm-timesync\.timer", self.text)

    def test_nat_helper_comes_from_repo(self):
        assert 'config/scripts/bcm-nat.sh" /usr/local/bin/bcm-nat.sh' in self.text
        assert "NATEOF" not in self.text
        assert "cat > /usr/local/bin/bcm-nat.sh" not in self.text

    def test_smoke_test_uses_unit_config(self):
        assert "${BCM_CONFIG:-config/bcm_config_test.yaml}" in self.text
        assert "--config config/bcm_config.yaml" not in self.text

    def test_nm_unmanaged_devices_is_one_key_in_one_file(self):
        """NetworkManager does not merge ``[keyfile] unmanaged-devices=`` from
        several conf.d files — the one parsed last wins. With the Wi-Fi rule
        in bcm-unmanage-wifi.conf and the p2p-* rule in bcm-unmanage-p2p.conf
        the p2p-* rule was ignored (``-wifi`` sorts after ``-p2p``), so NM kept
        toggling the P2P-GO group link. One file, one ';'-separated value."""
        values = [l.strip() for l in _code_lines(self.text)
                  if l.strip().startswith("unmanaged-devices=")]
        assert values == ["unmanaged-devices=interface-name:$WIFI_IFACE;interface-name:p2p-*"]
        written = re.findall(r"(?:cat\s*>|tee(?:\s+-a)?)\s+(/etc/NetworkManager/conf\.d/[^\s<]+)",
                             self.text)
        assert written == ["/etc/NetworkManager/conf.d/bcm-unmanage-wifi.conf"], written
        # A re-run on a car that still has the old second file removes it
        # before the merged one is written (phase 9, not only the phase-1 cleanup).
        phase9 = self.text[self.text.index('step 9 "'):self.text.index('step 10 "')]
        rm_at = phase9.index("rm -f /etc/NetworkManager/conf.d/bcm-unmanage-p2p.conf")
        assert rm_at < phase9.index("cat > /etc/NetworkManager/conf.d/bcm-unmanage-wifi.conf")

    def test_no_other_script_writes_unmanaged_devices(self):
        """A second writer would bring back the "last file wins" problem."""
        for script in SHELL_SCRIPTS:
            if script.name == "setup-x86.sh":
                continue
            lines = _code_lines(script.read_text(encoding="utf-8"))
            assert not any("unmanaged-devices=" in l for l in lines), script.name
            # the old p2p file may only ever be removed
            for l in lines:
                if "bcm-unmanage-p2p.conf" in l:
                    assert l.strip().startswith("rm -f "), (script.name, l)


# ─── apply-fixes.sh ────────────────────────────────────────────────────


class TestApplyFixes:
    text = _read("apply-fixes.sh")

    def test_no_boot_blocking_sleep(self):
        assert "sleep 30" not in self.text
        assert not [l for l in _code_lines(self.text) if l.startswith("ExecStartPost=")]

    def test_nat_helper_comes_from_repo(self):
        assert 'config/scripts/bcm-nat.sh" /usr/local/bin/bcm-nat.sh' in self.text
        assert "NATEOF" not in self.text

    def test_late_nat_timer_like_setup(self):
        assert "cat > /etc/systemd/system/bcm-nat-late.timer" in self.text
        assert "cat > /etc/systemd/system/bcm-nat-late.service" in self.text
        assert "systemctl enable bcm-nat-late.timer" in self.text
        assert "OnBootSec=30s" in self.text


# ─── bcm-nat.sh ────────────────────────────────────────────────────────


class TestBcmNat:
    text = _read("bcm-nat.sh")

    def test_never_treats_phone_or_container_links_as_uplink(self):
        body = _function_body(self.text, "is_uplink_candidate")
        for pattern in ("lo", '"$AP_IFACE"', "p2p-*", "bnep*", "docker*", "veth*"):
            assert pattern in body, pattern
        # Both uplink sources go through the filter.
        assert self.text.count("is_uplink_candidate ") >= 2

    def test_keeps_default_route_detection(self):
        # LTE (cdc_ether) reports operstate=unknown: default route is what finds it.
        assert "ip -4 route show default" in self.text
        assert "up | unknown)" in self.text

    def test_idempotent_rules(self):
        assert self.text.count("iptables -t nat -C") == self.text.count("iptables -t nat -A")
        assert self.text.count("iptables -C FORWARD") == self.text.count("iptables -A FORWARD")

    def test_no_ls_parsing(self):
        assert "$(ls" not in self.text


# ─── bcm-harden.sh ─────────────────────────────────────────────────────

# Functions that are allowed to change the system directly. Each of them
# checks DRY_RUN first (asserted below), so routing every change through
# them is what makes --dry-run trustworthy.
_HARDEN_HELPERS = {"run", "run_quiet", "atomic_replace", "cleanup_work"}
_MUTATING = {
    "apt", "apt-get", "chmod", "chown", "cp", "dd", "dpkg", "grub-mkconfig", "install",
    "iptables", "journalctl", "ln", "mkdir", "modprobe", "mount", "mv", "nmcli", "rm",
    "sysctl", "tee", "timedatectl", "touch", "truncate", "tune2fs", "umount",
    "update-grub", "update-initramfs", "usermod",
}
_READONLY_SYSTEMCTL = {"is-enabled", "is-active", "list-unit-files", "show", "cat", "status"}
_PREFIX_WORDS = re.compile(r"(?:if|then|else|elif|do|while|until|time|exec|!|\{|\()(?=\s|$)")
_ENV_PREFIX = re.compile(r"\w+=(?:\"[^\"]*\"|\S*)\s+")
_HEREDOC = re.compile(r"(?<!<)<<(?!<)-?\s*['\"]?(\w+)['\"]?")
_SYSTEM_REDIRECT = re.compile(r">>?\s*\"?/(?:etc|boot|usr|var|lib|opt)/")


def _logical_lines(text):
    """Yield (enclosing function or None, line) with heredoc bodies,
    comment lines and line continuations taken care of."""
    func = None
    heredoc_end = None
    buf = ""
    for raw in text.splitlines():
        if heredoc_end is not None:
            if raw.strip() == heredoc_end:
                heredoc_end = None
            continue
        if not buf and raw.strip().startswith("#"):
            continue
        if raw.rstrip().endswith("\\"):
            buf += raw.rstrip()[:-1] + " "
            continue
        line, buf = buf + raw, ""
        m = re.match(r"^(\w+)\(\)\s*\{(.*)$", line)
        if m:
            func, rest = m.group(1), m.group(2)
            if rest.rstrip().endswith("}"):  # one-line function
                yield func, rest
                func = None
            continue
        if line.startswith("}"):
            func = None
            continue
        hd = _HEREDOC.search(line)
        if hd:
            heredoc_end = hd.group(1)
        yield func, line


def _commands(line):
    """First word (and the rest) of every simple command on a line,
    including those inside $(...). Single-quoted text is dropped (awk/sed
    programs, printf formats); double-quoted text does not split commands."""
    s = re.sub(r"'[^']*'", "''", line)
    outside = re.sub(r'"[^"]*"', lambda m: '"' + "x" * (len(m.group()) - 2) + '"', s)
    starts = [0]
    starts += [m.end() for m in re.finditer(r"&&|\|\||\||;", outside)]
    starts += [m.end() for m in re.finditer(r"\$\(", s)]
    for start in starts:
        seg = s[start:]
        while True:
            seg = seg.lstrip()
            m = _PREFIX_WORDS.match(seg) or _ENV_PREFIX.match(seg)
            if not m:
                break
            seg = seg[m.end():]
        m = re.match(r"[A-Za-z0-9_./-]+", seg)
        if m:
            yield m.group(0), seg[m.end():].split()


def _violations(text):
    found = []
    for func, line in _logical_lines(text):
        if func in _HARDEN_HELPERS:
            continue
        stripped = re.sub(r"'[^']*'", "''", line)
        if _SYSTEM_REDIRECT.search(stripped):
            found.append(line.strip())
            continue
        for word, rest in _commands(line):
            nxt = rest[0] if rest else ""
            if (
                word in _MUTATING
                or (word == "systemctl" and nxt not in _READONLY_SYSTEMCTL)
                or (word == "snap" and nxt != "list")
                or (word == "sed" and any(a == "-i" or a.startswith("--in-place") for a in rest))
            ):
                found.append(line.strip())
                break
    return found


class TestBcmHarden:
    text = _read("bcm-harden.sh")

    def test_strict_mode(self):
        assert re.search(r"^set -euo pipefail$", self.text, flags=re.M)

    def test_flags(self):
        body = _function_body(self.text, "parse_args")
        assert re.search(r"--dry-run\b[^)]*\)\s*DRY_RUN=1", body)
        assert re.search(r"--no-units\)\s*NO_UNITS=1", body)
        # Unknown flags are rejected, not silently ignored.
        assert "exit 2" in body

    def test_total_matches_step_calls(self):
        total = _total(self.text)
        assert total == 10
        assert _step_numbers(self.text) == list(range(1, total + 1))

    @pytest.mark.parametrize("helper", ["run", "run_quiet", "atomic_replace"])
    def test_helpers_check_dry_run_before_acting(self, helper):
        body = _function_body(self.text, helper)
        guard = body.index('if [ "$DRY_RUN" = 1 ]; then')
        # The line that actually runs something: the bare "$@" (run, run_quiet)
        # or the first install (atomic_replace).
        pattern = r'^\s*"\$@"' if helper != "atomic_replace" else r"\binstall "
        act = re.search(pattern, body, flags=re.M).start()
        assert guard < body.index("return 0", guard) < act

    def test_every_change_goes_through_dry_run_aware_helpers(self):
        assert _violations(self.text) == []

    def test_violation_detector_catches_direct_calls(self):
        # Guard the guard: the detector must flag what it is meant to flag.
        sample = "\n".join([
            "f() {",
            "    systemctl mask foo.service",
            "    x=1 && rm -f /etc/foo",
            '    state="$(systemctl is-enabled foo || true)"',
            "    sed -i 's/a/b/' /etc/default/grub",
            "    echo hi > /etc/motd",
            "    cat <<'EOF'",
            "rm -rf / (heredoc text, ignored)",
            "EOF",
            "    run systemctl restart foo",
            "}",
        ])
        assert _violations(sample) == [
            "systemctl mask foo.service",
            "x=1 && rm -f /etc/foo",
            "sed -i 's/a/b/' /etc/default/grub",
            "echo hi > /etc/motd",
        ]

    def test_power_loss_settings(self):
        for needle in (
            "/etc/systemd/journald.conf.d/10-bcm-volatile.conf",
            "Storage=volatile",
            "RuntimeMaxUse=64M",
            "RuntimeMaxFileSize=8M",
            "/etc/sysctl.d/90-bcm-powerloss.conf",
            "vm.dirty_expire_centisecs = 500",
            "vm.dirty_writeback_centisecs = 100",
            "run_quiet sysctl --system",
        ):
            assert needle in self.text, needle

    def test_fstab_is_verified_backed_up_and_ext4_only(self):
        body = _function_body(self.text, "step_fstab")
        assert '$2 == "/"' in body and "$1 !~ /^#/" in body
        assert "!= ext4" in body
        verify = body.index('findmnt --verify --tab-file "$cand"')
        backup = body.index("/etc/fstab.bcm-$STAMP.bak")
        replace = body.index('atomic_replace "$cand" "$fstab"')
        assert verify < backup < replace
        assert 'run mount -o "$remount" /' in body

    def test_grub_edits_only_the_default_cmdline(self):
        body = _function_body(self.text, "step_grub")
        assert "/etc/default/grub.bcm-$STAMP.bak" in body
        assert "run update-grub" in body and "run grub-mkconfig" in body
        line_fn = _function_body(self.text, "grub_new_line")
        assert "fsck.mode=skip) ;;" in line_fn
        assert "fsck.repair=yes" in line_fn

    def test_secrets_file_is_never_overwritten_or_printed(self):
        body = _function_body(self.text, "step_units_and_env")
        exists = body.index('elif [ -f "$ENV_FILE" ]; then')
        scaffold = body.index('atomic_replace "$BCM_DIR/config/bcm.env.example" "$ENV_FILE" 0600')
        assert exists < scaffold
        assert 'run chmod 600 "$ENV_FILE"' in body
        assert 'run chown root:root "$ENV_FILE"' in body
        assert 'cat "$ENV_FILE"' not in self.text
        assert not re.search(r"show_diff[^\n]*ENV_FILE", self.text)

    def test_apt_and_cloudinit_leave_markers_for_cleanup(self):
        body = _function_body(self.text, "step_boot")
        assert "run systemctl mask NetworkManager-wait-online.service" in body
        assert 'run systemctl disable --now "$u"' in body
        # Marker first, so a power cut mid-way never leaves a disabled unit
        # that cleanup-x86.sh does not know about.
        assert body.index('update_marker "$APT_MARKER"') < body.index('run systemctl disable --now "$u"')
        assert body.index('write_file "$CLOUDINIT_MARKER"') < body.index("run touch /etc/cloud/cloud-init.disabled")
        # Snaps are only reported.
        assert "snap remove" not in self.text and "purge snapd" not in self.text

    def test_reminds_about_bios_power_on(self):
        assert "After Power Loss -> Power On" in self.text

    @pytest.mark.parametrize("step, var", [("step_fstab", "fstab"), ("step_grub", "grub")])
    def test_system_file_swap_refuses_symlinks_caps_mode_and_syncs_backup(self, step, var):
        body = _function_body(self.text, step)
        # stat -c '%a' on a symlink reports 777: the link is refused before
        # anything reads its mode or copies it.
        refuse = body.index(f'if [ -L "${var}" ]; then')
        assert refuse < body.index(f'if [ ! -f "${var}" ]; then')
        assert refuse < body.index(f"stat -c '%a' \"${var}\"")
        # Mode never wider than 0644 (update-grub sources /etc/default/grub as root).
        assert "cap_mode" in body and '"0$mode"' not in body
        # Backup (fsync'ed inside backup_file) strictly before the swap.
        assert body.index(f'backup_file "${var}" "$backup"') < body.index(f'atomic_replace "$cand" "${var}" "$mode"')
        assert "run cp -a" not in body

    def test_backup_is_synced_before_it_is_recorded(self):
        body = _function_body(self.text, "backup_file")
        copy = body.index('run cp -a "$src" "$backup"')
        sync = body.index('run sync "$backup"')
        assert copy < sync < body.index('record_backup "$backup"')

    def test_etc_bcm_is_root_owned_and_not_writable_by_others(self):
        # systemd loads bcm.env into two root services: whoever can write the
        # directory can swap the file (LD_PRELOAD, PYTHONPATH).
        body = _function_body(self.text, "step_units_and_env")
        assert "[ -L /etc/bcm ]" in body
        assert "stat -c '%u %a' /etc/bcm" in body
        assert "run chown root:root /etc/bcm" in body
        assert "run chmod go-w /etc/bcm" in body
        assert "8#022" in body
        assert body.index("run chmod go-w /etc/bcm") < body.index('atomic_replace "$BCM_DIR/config/bcm.env.example"')

    def test_warns_before_switching_unit_away_from_temp_config(self):
        units = _function_body(self.text, "step_units_and_env")
        assert units.index("check_config_migration") < units.index("bcm-headunit-x86.service")
        check = _function_body(self.text, "check_config_migration")
        for needle in (
            "/etc/systemd/system/bcm-headunit.service",
            "bcm_config_temp\\.yaml",
            "config/local.yaml",
            "tools/migrate_local_config.py --source config/bcm_config_temp.yaml"
            " --base config/bcm_config_test.yaml --out config/local.yaml",
            "--write",
            "BCM_CONFIG=config/bcm_config_temp.yaml",
            "MIGRATION_PENDING=1",
        ):
            assert needle in check, needle
        # bcm.env is only grep -q'ed, never printed.
        assert re.search(r'grep -Eq [^\n]*"\$ENV_FILE"', check)
        assert "MIGRATION_PENDING" in _function_body(self.text, "step_summary")
        # The flags the hint suggests are the tool's real ones.
        tool = (REPO / "tools" / "migrate_local_config.py").read_text(encoding="utf-8")
        for flag in ("--source", "--base", "--out", "--write"):
            assert f'"{flag}"' in tool, flag

    def test_header_says_cleanup_is_a_full_uninstall(self):
        header = self.text.split("set -euo pipefail", 1)[0]
        assert "PEŁNA deinstalacja" in header
        for needle in (
            "systemctl unmask NetworkManager-wait-online.service",
            "/etc/bcm/.harden-apt-disabled",
            "rm /etc/cloud/cloud-init.disabled",
            "systemctl restart systemd-journald",
            "sysctl --system",
        ):
            assert needle in header, needle


# ─── bcm-harden.sh pure functions, executed in isolation ────────────────
#
# Only these function bodies are extracted and sourced: they compute new
# fstab options / a GRUB line / a file mode from their arguments and touch
# nothing. The full script is never executed.

_PURE_FUNCS = ("fstab_new_options", "grub_new_line", "cap_mode")
_SETUP_GRUB_LINE = next(
    l for l in _read("setup-x86.sh").splitlines() if l.startswith("GRUB_CMDLINE_LINUX_DEFAULT=")
)


@pytest.fixture(scope="module")
def harden_pure_lib(tmp_path_factory):
    text = _read("bcm-harden.sh")
    src = "".join(f"{name}() {{\n{_function_body(text, name)}}}\n" for name in _PURE_FUNCS)
    # Guard the isolation: nothing extracted may change the system.
    assert _violations(src) == []
    assert not re.search(r"\b(run|run_quiet|atomic_replace|write_file|install_file)\b", src)
    path = tmp_path_factory.mktemp("harden-pure") / "pure.sh"
    path.write_text(src, encoding="utf-8")
    return path


def _call(lib, func, *args):
    """Run one pure function under the script's own strict mode; args go
    in as argv, never spliced into the command string."""
    res = subprocess.run(
        ["bash", "-c", 'set -euo pipefail; source "$1"; shift; "$@"', "bash", str(lib), func, *args],
        capture_output=True, text=True, timeout=10, cwd=lib.parent,
    )
    return res.returncode, res.stdout.rstrip("\n"), res.stderr


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash not installed")
class TestHardenPureFunctions:
    @pytest.mark.parametrize("opts, commit, expected", [
        ("defaults", "", "defaults,noatime"),
        ("errors=remount-ro", "", "errors=remount-ro,noatime"),
        ("defaults,relatime", "", "defaults,noatime"),
        ("rw,strictatime,atime,errors=remount-ro", "", "rw,errors=remount-ro,noatime"),
        ("noatime,errors=remount-ro", "", "noatime,errors=remount-ro"),
        ("defaults,,noatime", "", "defaults,noatime"),
        # commit= is left alone unless BCM_COMMIT_SEC asks for it ...
        ("defaults,commit=30", "", "defaults,commit=30,noatime"),
        # ... and then replaced in place, exactly once.
        ("defaults,commit=30", "5", "defaults,commit=5,noatime"),
        ("defaults,commit=30,commit=60", "5", "defaults,commit=5,noatime"),
        ("defaults", "5", "defaults,noatime,commit=5"),
    ])
    def test_fstab_new_options(self, harden_pure_lib, opts, commit, expected):
        rc, out, err = _call(harden_pure_lib, "fstab_new_options", opts, commit)
        assert rc == 0, err
        assert out == expected
        if "errors=remount-ro" in opts:
            assert "errors=remount-ro" in out.split(",")
        assert out.split(",").count("noatime") == 1
        # Idempotent: a second run (the next bcm-harden.sh) changes nothing.
        rc, again, err = _call(harden_pure_lib, "fstab_new_options", out, commit)
        assert rc == 0, err
        assert again == out

    @pytest.mark.parametrize("line, expected", [
        ('GRUB_CMDLINE_LINUX_DEFAULT="quiet splash fsck.mode=skip"',
         'GRUB_CMDLINE_LINUX_DEFAULT="quiet splash fsck.repair=yes"'),
        ('GRUB_CMDLINE_LINUX_DEFAULT="quiet fsck.mode=skip console=tty2"',
         'GRUB_CMDLINE_LINUX_DEFAULT="quiet console=tty2 fsck.repair=yes"'),
        ('GRUB_CMDLINE_LINUX_DEFAULT="quiet fsck.repair=preen"',
         'GRUB_CMDLINE_LINUX_DEFAULT="quiet fsck.repair=yes"'),
        ('GRUB_CMDLINE_LINUX_DEFAULT="fsck.repair=no quiet fsck.repair=preen"',
         'GRUB_CMDLINE_LINUX_DEFAULT="fsck.repair=yes quiet"'),
        ("GRUB_CMDLINE_LINUX_DEFAULT='quiet fsck.mode=skip'",
         "GRUB_CMDLINE_LINUX_DEFAULT='quiet fsck.repair=yes'"),
        ('GRUB_CMDLINE_LINUX_DEFAULT=""', 'GRUB_CMDLINE_LINUX_DEFAULT="fsck.repair=yes"'),
        # Whole words only: look-alike options stay.
        ('GRUB_CMDLINE_LINUX_DEFAULT="quiet fsck.mode=force fsck.mode=skipx"',
         'GRUB_CMDLINE_LINUX_DEFAULT="quiet fsck.mode=force fsck.mode=skipx fsck.repair=yes"'),
        # Copied literally: no variable, glob or backslash expansion.
        ('GRUB_CMDLINE_LINUX_DEFAULT="$EXTRA quiet x=* a\\b fsck.mode=skip"',
         'GRUB_CMDLINE_LINUX_DEFAULT="$EXTRA quiet x=* a\\b fsck.repair=yes"'),
        # What setup-x86.sh writes is already final.
        (_SETUP_GRUB_LINE, _SETUP_GRUB_LINE),
    ])
    def test_grub_new_line(self, harden_pure_lib, line, expected):
        rc, out, err = _call(harden_pure_lib, "grub_new_line", line)
        assert rc == 0, err
        assert out == expected
        assert "fsck.mode=skip " not in out and 'fsck.mode=skip"' not in out
        assert out.count("fsck.repair=") == 1
        rc, again, err = _call(harden_pure_lib, "grub_new_line", out)
        assert rc == 0, err
        assert again == out

    @pytest.mark.parametrize("line", [
        "GRUB_CMDLINE_LINUX_DEFAULT=quiet",            # unquoted
        'GRUB_CMDLINE_LINUX_DEFAULT="quiet',           # unterminated
        "GRUB_CMDLINE_LINUX_DEFAULT=\"quiet'",         # mismatched quotes
        'GRUB_CMDLINE_LINUX_DEFAULT="a"b"',            # quote inside
        'GRUB_CMDLINE_LINUX_DEFAULT="',                # lone quote
        'GRUB_CMDLINE_LINUX="quiet fsck.mode=skip"',   # not the DEFAULT line
    ])
    def test_grub_new_line_refuses_what_it_cannot_parse(self, harden_pure_lib, line):
        # Refusal (exit 1, no output) leaves /etc/default/grub untouched.
        rc, out, _ = _call(harden_pure_lib, "grub_new_line", line)
        assert rc == 1
        assert out == ""

    @pytest.mark.parametrize("mode, expected", [
        ("644", "0644"), ("0644", "0644"), ("600", "0600"), ("440", "0440"),
        ("777", "0644"), ("666", "0644"), ("755", "0644"), ("4755", "0644"),
        ("", "0644"), ("abc", "0644"), ("8", "0644"),
    ])
    def test_cap_mode(self, harden_pure_lib, mode, expected):
        rc, out, err = _call(harden_pure_lib, "cap_mode", mode)
        assert rc == 0, err
        assert out == expected


# ─── cleanup-x86.sh reverts exactly what bcm-harden.sh did ──────────────


class TestCleanup:
    text = _read("cleanup-x86.sh")
    harden = _read("bcm-harden.sh")

    @pytest.mark.parametrize("var", ["APT_MARKER", "CLOUDINIT_MARKER"])
    def test_marker_paths_match_harden(self, var):
        def value(text):
            m = re.search(rf"^{var}=(\S+)$", text, flags=re.M)
            assert m, var
            return m.group(1)

        assert value(self.text) == value(self.harden)

    def test_apt_units_match_harden(self):
        # cleanup re-enables only names on its own allow-list: a unit added
        # to bcm-harden.sh but not here would stay disabled for good.
        harden = re.search(r"^APT_UNITS=\(([^)]*)\)\s*$", self.harden, flags=re.M)
        cleanup = re.search(r'^APT_UNITS="([^"]*)"\s*$', self.text, flags=re.M)
        assert harden and cleanup
        assert set(harden.group(1).split()) == set(cleanup.group(1).split())
        assert harden.group(1).split()

    @pytest.mark.parametrize("var", ["JOURNALD_DROPIN", "SYSCTL_DROPIN"])
    def test_removes_the_dropins_harden_writes(self, var):
        m = re.search(rf"^{var}=(\S+)$", self.harden, flags=re.M)
        assert m, var
        assert f"rm -f {m.group(1)}" in self.text

    def test_removes_timesync_and_nat(self):
        assert "rm -f /usr/local/bin/bcm-timesync.sh" in self.text
        assert "rm -f /usr/local/bin/bcm-nat.sh" in self.text
        assert "rm -f /etc/systemd/system/bcm-*.service" in self.text
        assert "rm -f /etc/systemd/system/bcm-*.timer" in self.text
        assert re.search(r"for timer in [^\n]*bcm-timesync\.timer[^\n]*bcm-nat-late\.timer", self.text)
        assert "systemctl unmask NetworkManager-wait-online.service" in self.text

    def test_removes_the_unmanaged_device_rules_setup_writes(self):
        # Every NetworkManager / networkd file setup-x86.sh writes (or used to
        # write) for the Wi-Fi card and p2p-*: left behind, the card stays
        # unmanaged after a cleanup without a reinstall.
        setup = _read("setup-x86.sh")
        written = set(re.findall(r"cat > (/etc/(?:NetworkManager/conf\.d|systemd/network)/\S+)",
                                 setup))
        assert written == {"/etc/NetworkManager/conf.d/bcm-unmanage-wifi.conf",
                           "/etc/systemd/network/00-bcm-p2p.network"}
        for path in written | {"/etc/NetworkManager/conf.d/bcm-unmanage-p2p.conf"}:
            assert f"rm -f {path}" in _code_lines(self.text), path

    def test_reenables_only_under_markers(self):
        apt_if = self.text.index('if [ -f "$APT_MARKER" ]; then')
        apt_end = self.text.index("\nfi\n", apt_if)
        enable = self.text.index('systemctl enable --now "$unit"')
        assert apt_if < enable < apt_end
        ci_if = self.text.index('if [ -f "$CLOUDINIT_MARKER" ]; then')
        ci_end = self.text.index("\nfi\n", ci_if)
        assert ci_if < self.text.index("rm -f /etc/cloud/cloud-init.disabled") < ci_end

    def test_leaves_fstab_grub_and_secrets_alone(self):
        for line in _code_lines(self.text):
            if line.lstrip().startswith("echo"):
                continue
            assert "bcm.env" not in line, line
            assert "/etc/fstab" not in line or line.lstrip().startswith("for "), line
            assert "/etc/default/grub" not in line or line.lstrip().startswith("for "), line
            assert "update-grub" not in line, line
        assert "/etc/fstab.bcm-*.bak" in self.text
        assert "/etc/default/grub.bcm-*.bak" in self.text


def test_docs_never_put_fsck_skip_on_the_kernel_command_line():
    # Manual install guides are copied verbatim; a GRUB line with
    # fsck.mode=skip there would undo bcm-harden.sh on the next install.
    # Prose that merely names the option is fine; Archive/ is history.
    docs = [REPO / "README.md", *sorted((REPO / "docs").rglob("*.md"))]
    offenders = []
    for path in docs:
        rel = path.relative_to(REPO)
        if "Archive" in rel.parts or not path.is_file():
            continue
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if "GRUB_CMDLINE" in line and "fsck.mode=skip" in line:
                offenders.append(f"{rel}:{n}")
    assert offenders == []


def test_setup_and_cleanup_never_delete_bcm_env():
    for name in ("setup-x86.sh", "cleanup-x86.sh", "apply-fixes.sh", "bcm-harden.sh"):
        for line in _code_lines(_read(name)):
            assert not re.search(r"\brm\b[^\n]*bcm\.env", line), f"{name}: {line}"


# ─── Etap 2a: oFono / WirePlumber / D-Bus policy, audio diagnostics ─────

WIREPLUMBER_DROPIN = REPO / "config" / "wireplumber" / "wireplumber.conf.d" / "51-bcm-hfp-ofono.conf"
AUDIO_DIAG = REPO / "tools" / "bcm-audio-diag.sh"


@pytest.mark.parametrize("name", ["setup-x86.sh", "apply-fixes.sh"])
class TestOfonoInstall:
    def test_dbus_policy_heredoc_for_the_session_user(self, name):
        text = _read(name)
        assert "cat > /etc/dbus-1/system.d/bcm-ofono-pipewire.conf <<EOF" in text
        assert '<policy user="$BCM_USER">' in text
        assert '<allow send_destination="org.ofono"/>' in text
        assert "HandsfreeAudioAgent" in text            # the XML comment says why
        # the user name is validated before it is templated into XML
        assert '[[ "$BCM_USER" =~ ^[A-Za-z_][A-Za-z0-9_.-]*$ ]]' in text

    def test_ofono_install_is_checked_not_silenced(self, name):
        code = "\n".join(_code_lines(_read(name)))
        assert not re.search(r"\bofono\b[^\n]*2>/dev/null \|\| true", code.replace(
            "systemctl enable ofono 2>/dev/null || true", "").replace(
            "systemctl restart ofono 2>/dev/null || true", ""))
        assert "command -v ofonod" in code
        assert "apt-get install -y ofono || true" in code

    def test_wireplumber_version_is_checked(self, name):
        text = _read(name)
        assert "wireplumber --version" in text
        assert '"$WP_MINOR" -lt 5' in text

    def test_installs_the_wireplumber_dropin(self, name):
        assert "51-bcm-hfp-ofono.conf\" \\\n    /etc/wireplumber/wireplumber.conf.d/51-bcm-hfp-ofono.conf" in _read(name)

    def test_restarts_user_audio_services(self, name):
        assert ('systemctl --user -M "$BCM_USER@" restart wireplumber pipewire pipewire-pulse'
                in _read(name))


class TestApplyFixesAudio:
    text = _read("apply-fixes.sh")

    def test_headunit_restarted_after_the_audio_stack(self):
        user = self.text.index('systemctl --user -M "$BCM_USER@" restart')
        sinks = self.text.index("wpctl status --name 2>/dev/null | grep -q 'alsa_output\\.'")
        headunit = self.text.index("systemctl try-restart bcm-headunit.service")
        assert user < sinks < headunit   # EQ child is not supervised; sinks first

    def test_never_starts_a_stopped_headunit(self):
        code = "\n".join(_code_lines(self.text))
        assert "systemctl restart bcm-headunit" not in code
        assert "systemctl start bcm-headunit" not in code

    def test_sink_wait_is_bounded(self):
        assert "for _ in $(seq 1 10); do" in self.text and "sleep 0.5" in self.text

    def test_session_user_detection(self):
        assert "--autologin" in self.text and 'BCM_USER=${BCM_USER:-abner}' in self.text

    def test_step_numbers_are_consistent(self):
        steps = re.findall(r'^echo "==> (\d+)/(\d+) ', self.text, flags=re.M)
        assert [int(n) for n, _ in steps] == list(range(1, len(steps) + 1))
        assert {int(total) for _, total in steps} == {len(steps)}


def test_wireplumber_dropin_pins_msbc_off():
    lines = _code_lines(WIREPLUMBER_DROPIN.read_text(encoding="utf-8"))
    assert any(re.fullmatch(r"\s*bluez5\.enable-msbc\s*=\s*false\s*", l) for l in lines)
    assert any('bluez5.hfphsp-backend = "ofono"' in l for l in lines)


class TestAudioDiag:
    text = AUDIO_DIAG.read_text(encoding="utf-8")

    @pytest.mark.skipif(shutil.which("bash") is None, reason="bash not installed")
    def test_bash_syntax(self):
        res = subprocess.run(["bash", "-n", str(AUDIO_DIAG)], capture_output=True, text=True,
                             timeout=30)
        assert res.returncode == 0, res.stderr

    def test_never_prints_the_wifi_section(self):
        assert '$0=="[Audio]"||$0=="[Input]"' in self.text
        assert "[WiFi]" not in "\n".join(_code_lines(self.text))

    def test_state_changes_only_after_confirmation(self):
        code = _code_lines(self.text)
        first_confirm = next(i for i, l in enumerate(code) if 'confirm "Wykonać test A' in l)
        for i, line in enumerate(code):
            if re.search(r"set-mute|set-sink-input-mute", line):
                assert i > first_confirm, line
        joined = "\n".join(code)
        for forbidden in ("set-default", "set-profile", "systemctl restart", "systemctl stop",
                          "rm -", "tee /etc", "> /etc"):
            assert forbidden not in joined, forbidden

    def test_mute_is_always_undone(self):
        block = self._test_a_block()
        # the trap is armed BEFORE anything is muted (Ctrl-C mid-loop)
        assert block.index("trap restore_mute EXIT") < block.index('set_mute "$id" 1')
        assert "trap 'restore_mute; exit 130' INT TERM" in block
        assert 'pactl set-sink-input-mute "$1" "$2"' in block
        assert 'wpctl set-mute "$1" "$2"' in block

    def test_runs_pipewire_tools_in_the_user_session(self):
        # LC_ALL=C: pactl/wpctl output is parsed; sudo keeps LANG/LC_*.
        assert 'U=(sudo -u "$BCM_USER" LC_ALL=C "XDG_RUNTIME_DIR=/run/user/$U_UID")' in self.text
        assert 'U=(env LC_ALL=C "XDG_RUNTIME_DIR=/run/user/$U_UID")' in self.text
        assert 'eval' not in "\n".join(_code_lines(self.text))

    # ── Test A, run for real with a fake wpctl (no PipeWire touched) ──────

    def _test_a_block(self):
        start = self.text.index('if confirm "Wykonać test A teraz?"; then')
        return self.text[start:self.text.index('hdr "Test B:')]

    def _run_test_a(self, tmp_path, pw_nodes_out, fail_on=""):
        log = tmp_path / "calls.log"
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        wpctl = bin_dir / "wpctl"
        # Records every call; optionally "presses Ctrl-C" (SIGINT to the
        # script) when it sees a given argument string.
        wpctl.write_text(
            "#!/bin/bash\n"
            f'echo "$*" >> "{log}"\n'
            f'if [ -n "{fail_on}" ] && [ "$*" = "{fail_on}" ]; then kill -INT $PPID; fi\n'
        )
        wpctl.chmod(0o755)
        prelude = (
            "set -u\n"
            f'PATH="{bin_dir}:$PATH"\n'
            "U=(env)\n"
            "confirm() { return 0; }\n"
            'have() { [ "$1" = wpctl ] || [ "$1" = python3 ]; }\n'
            f"pw_nodes() {{ printf '{pw_nodes_out}'; }}\n"
            "sleep() { :; }\n"
            'info() { echo "INFO $*"; }\nok() { echo "OK $*"; }\nwarn() { echo "WARN $*"; }\n'
        )
        res = subprocess.run(["bash", "-c", prelude + self._test_a_block() + "echo END\n"],
                             capture_output=True, text=True, timeout=30)
        calls = log.read_text().splitlines() if log.exists() else []
        return res, calls

    @pytest.mark.skipif(shutil.which("bash") is None, reason="bash not installed")
    def test_test_a_mutes_numeric_ids_only_and_restores(self, tmp_path):
        # an empty line / junk id (what the localised pactl parse produced)
        # must never reach wpctl
        res, calls = self._run_test_a(tmp_path, "42\\tautoapp\\n\\tx\\nabc\\ty\\n7\\tz\\n")
        assert res.returncode == 0, res.stderr
        assert calls == ["set-mute 42 1", "set-mute 7 1", "set-mute 42 0", "set-mute 7 0"]
        assert "END" in res.stdout and "OK odciszone" in res.stdout

    @pytest.mark.skipif(shutil.which("bash") is None, reason="bash not installed")
    def test_test_a_without_streams_draws_no_conclusion(self, tmp_path):
        res, calls = self._run_test_a(tmp_path, "\\t\\n")
        assert res.returncode == 0, res.stderr
        assert calls == []
        assert "test pominięty" in res.stdout
        assert "pętla bufora" not in res.stdout and "Brzęczało dalej" not in res.stdout

    @pytest.mark.skipif(shutil.which("bash") is None, reason="bash not installed")
    def test_test_a_ctrl_c_mid_loop_unmutes(self, tmp_path):
        res, calls = self._run_test_a(tmp_path, "42\\ta\\n7\\tb\\n9\\tc\\n",
                                      fail_on="set-mute 7 1")
        assert res.returncode == 130
        assert "END" not in res.stdout
        assert calls[:2] == ["set-mute 42 1", "set-mute 7 1"]
        assert "set-mute 9 1" not in calls
        assert sorted(calls[2:]) == ["set-mute 42 0", "set-mute 7 0"]


# ─── Telefon w aucie (plan C): autoapp wireless-only, adb, timesync marker ──

# A minimal App::waitForDevice in the layout of openDsh/openauto (develop,
# openauto/App.cpp) — only what the patch looks at, not the real source.
_APP_CPP = """\
void App::waitForDevice(bool enumerate)
{
    this->waitForUSBDevice();
    this->waitForWirelessDevice();

    if(enumerate)
    {
        strand_.dispatch([this, self = this->shared_from_this()]() {
            this->enumerateDevices();
        });
    }
}

void App::waitForUSBDevice()
{
    usbHub_->start(std::move(promise));
}
"""


@pytest.fixture(scope="module")
def autoapp_patch_lib(tmp_path_factory):
    """log/warn/die + patch_aa_wireless_only() from install-openauto.sh,
    sourced on their own: the patch only edits the file it is given."""
    text = _read("install-openauto.sh")
    helpers = "\n".join(l for l in text.splitlines()
                        if re.match(r"^(log|warn|die)\(\)\s", l))
    src = helpers + "\n" + "patch_aa_wireless_only() {\n" + \
        _function_body(text, "patch_aa_wireless_only") + "}\n"
    # no command in it may touch anything but the file (messages may name them)
    assert not re.search(r"^\s*(apt-get|git|make|cmake|install|rm|systemctl)\b",
                         _function_body(text, "patch_aa_wireless_only"), flags=re.M)
    path = tmp_path_factory.mktemp("autoapp-patch") / "lib.sh"
    path.write_text(src, encoding="utf-8")
    return path


def _patch(lib, target):
    res = subprocess.run(
        ["bash", "-c", 'set -euo pipefail; WORK=/nonexistent; source "$1"; '
                       'patch_aa_wireless_only "$2"', "bash", str(lib), str(target)],
        capture_output=True, text=True, timeout=10, cwd=target.parent)
    return res.returncode, res.stdout + res.stderr


class TestInstallOpenautoUsbPatch:
    text = _read("install-openauto.sh")

    def test_gate_defaults_to_wireless_only_and_is_validated(self):
        assert 'BCM_AA_USB="${BCM_AA_USB:-0}"' in self.text
        assert re.search(r'case "\$BCM_AA_USB" in\s+0\|1\) ;;\s+\*\) die ', self.text)
        assert 'if [[ "$BCM_AA_USB" == "0" ]]; then\n    patch_aa_wireless_only openauto/App.cpp' \
            in self.text

    def test_patch_comes_before_the_openauto_build(self):
        build = self.text.index('log "Buduję openauto"')
        patch = self.text.index("patch_aa_wireless_only openauto/App.cpp")
        cmake = self.text.index("cmake ..", build)
        assert build < patch < cmake

    def test_header_explains_why_and_the_force_rebuild(self):
        header = self.text.split("set -euo pipefail", 1)[0]
        assert "AOAP" in header and "car_phone" in header
        assert "--force" in header and "BCM_AA_USB=1" in header

    def test_mode_is_recorded_and_checked_without_force(self):
        assert 'echo "BCM_AA_USB=$BCM_AA_USB" > "$MODE_FILE"' in self.text
        early = self.text[self.text.index('if [[ -x "$BIN" && $FORCE -eq 0 ]]'):]
        early = early[:early.index("exit 0")]
        assert '"$MODE_FILE"' in early and "--force" in early

    @pytest.mark.skipif(shutil.which("bash") is None, reason="bash not installed")
    def test_patch_comments_out_both_usb_calls_once(self, autoapp_patch_lib, tmp_path):
        target = tmp_path / "App.cpp"
        target.write_text(_APP_CPP)
        rc, out = _patch(autoapp_patch_lib, target)
        assert rc == 0, out
        patched = target.read_text()
        assert "this->waitForUSBDevice();" not in patched
        assert "this->enumerateDevices();" not in patched
        assert "this->waitForWirelessDevice();" in patched          # wireless stays
        assert "void App::waitForUSBDevice()" in patched            # definition untouched
        assert patched.count("BCM_AA_USB=0") == 2
        # idempotent: a second run changes nothing and says so
        rc, out = _patch(autoapp_patch_lib, target)
        assert rc == 0 and "już nałożona" in out
        assert target.read_text() == patched

    @pytest.mark.skipif(shutil.which("bash") is None, reason="bash not installed")
    @pytest.mark.parametrize("source", [
        _APP_CPP.replace("    this->waitForUSBDevice();\n", ""),            # upstream moved it
        _APP_CPP.replace("this->enumerateDevices();", "enumerate_all();"),
        _APP_CPP.replace("    this->waitForUSBDevice();\n",
                         "    this->waitForUSBDevice();\n    this->waitForUSBDevice();\n"),
        _APP_CPP.replace("    this->waitForUSBDevice();\n",
                         "    /* BCM_AA_USB=0: half */\n"),                # half-patched
    ], ids=["usb-call-missing", "enumerate-missing", "usb-call-twice", "half-patched"])
    def test_patch_fails_loudly_and_leaves_the_file(self, autoapp_patch_lib, tmp_path, source):
        target = tmp_path / "App.cpp"
        target.write_text(source)
        rc, out = _patch(autoapp_patch_lib, target)
        assert rc != 0 and "[błąd]" in out
        assert target.read_text() == source                       # never half-applied

    @pytest.mark.skipif(shutil.which("bash") is None, reason="bash not installed")
    def test_missing_file_fails(self, autoapp_patch_lib, tmp_path):
        rc, out = _patch(autoapp_patch_lib, tmp_path / "nope.cpp")
        assert rc != 0 and "BCM_AA_USB=1" in out


@pytest.mark.parametrize("name", ["setup-x86.sh", "apply-fixes.sh"])
class TestAdbInstall:
    def test_single_checked_package(self, name):
        code = "\n".join(_code_lines(_read(name)))
        assert "apt-get install -y adb || true" in code
        assert "command -v adb >/dev/null 2>&1" in code
        assert re.search(r"adb is NOT installed", code)
        # never hidden in a bulk list or silenced (messages may name the fix)
        for line in code.splitlines():
            if line.strip().startswith("apt-get") and re.search(r"\badb\b", line):
                assert line.strip() == "apt-get install -y adb || true", line
        assert "adb tcpip" not in code

    def test_nm_dropins_are_documented_not_written(self, name):
        code = "\n".join(_code_lines(_read(name)))
        assert "bcm-connectivity.conf" not in code
        assert "no-auto-default" not in code


def test_harden_only_reports_adb():
    text = _read("bcm-harden.sh")
    body = _function_body(text, "step_nm_bluetooth")
    assert "command -v adb" in body
    # report only: no apt command (run/run_quiet or bare) for adb anywhere
    assert not re.search(r"^\s*(run\s+|run_quiet\s+)?apt-get[^\n]*\badb\b", text, flags=re.M)


def test_apply_fixes_installs_the_timesync_script_only_if_present():
    text = _read("apply-fixes.sh")
    assert ('if [ -f /usr/local/bin/bcm-timesync.sh ]; then\n'
            '    install -m 0755 "$BCM_DIR/config/scripts/bcm-timesync.sh" '
            '/usr/local/bin/bcm-timesync.sh') in text


class TestTimesyncMarker:
    text = _read("bcm-timesync.sh")

    def test_marker_on_every_success_never_offline(self):
        assert "OK_MARKER=/run/bcm-timesync.ok" in self.text
        within = self.text.index("leaving it alone")
        corrected = self.text.index("clock corrected by")
        offline = self.text.index("no uplink to read a Date header")
        assert self.text.index("mark_ok", within) < self.text.index("exit 0", within)
        assert self.text.index("mark_ok", corrected) < self.text.index("exit 0", corrected)
        assert "mark_ok" not in self.text[offline:]

    @pytest.mark.skipif(shutil.which("bash") is None, reason="bash not installed")
    def test_mark_ok_writes_boottime_and_epoch(self, tmp_path):
        from src.network.car_phone import read_timesync_marker
        lib = tmp_path / "lib.sh"
        lib.write_text("mark_ok() {\n" + _function_body(self.text, "mark_ok") + "}\n")
        marker = tmp_path / "ok"
        res = subprocess.run(["bash", "-c", 'set -u; OK_MARKER="$2"; source "$1"; mark_ok',
                              "bash", str(lib), str(marker)],
                             capture_output=True, text=True, timeout=10)
        assert res.returncode == 0, res.stderr
        up, epoch = marker.read_text().split()
        assert up.isdigit() and epoch.isdigit() and int(epoch) > 1_700_000_000
        assert read_timesync_marker(str(marker)) == float(up)    # what car_phone reads
        assert not (tmp_path / "ok.tmp").exists()
