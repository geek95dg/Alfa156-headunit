"""tools/car_phone/autoboot: the car phone turns itself on when power comes
back (docs/PRZYGOTOWANIE_TELEFONU.md §16.1).

The charger-mode script runs against fake setprop/sleep and a fake battery
file: it reboots only at >= 5 %, waits (bounded) below it, and treats junk
as 0 %. The rc file and the patcher are checked statically: only the
"on charger" trigger, the service is disabled/oneshot, and the patcher
backs up the boot partition before anything is written.
"""

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

DIR = Path(__file__).resolve().parent.parent / "tools" / "car_phone" / "autoboot"

pytestmark = pytest.mark.skipif(shutil.which("sh") is None, reason="no sh")


@pytest.mark.parametrize("name", ["bcm_autoboot.sh", "patch_boot.sh"])
def test_syntax(name):
    assert subprocess.run(["sh", "-n", str(DIR / name)]).returncode == 0


def _run(tmp_path, capacity):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    log = tmp_path / "calls"
    (bin_dir / "setprop").write_text(f'#!/bin/sh\necho "setprop $*" >> {log}\n')
    # Each sleep "charges" the battery by 2 % (from the file's value).
    (bin_dir / "sleep").write_text(
        f'#!/bin/sh\necho "sleep $*" >> {log}\n'
        f'c=$(cat {tmp_path}/cap); case "$c" in *[!0-9]*|"") c=0;; esac\n'
        f'echo $((c+2)) > {tmp_path}/cap\n')
    for f in bin_dir.iterdir():
        f.chmod(0o755)
    (tmp_path / "cap").write_text(capacity)
    env = dict(os.environ, PATH=f"{bin_dir}:{os.environ['PATH']}",
               BCM_AUTOBOOT_CAP=str(tmp_path / "cap"))
    res = subprocess.run(["sh", str(DIR / "bcm_autoboot.sh")], env=env,
                         capture_output=True, text=True, timeout=30)
    assert res.returncode == 0, res.stderr
    assert res.stderr == "", "no noise when /dev/kmsg is not writable"
    return log.read_text() if log.exists() else ""


def test_reboots_at_once_when_charged(tmp_path):
    calls = _run(tmp_path, "57")
    assert calls.strip() == "setprop sys.powerctl reboot"


def test_waits_below_threshold_then_reboots(tmp_path):
    calls = _run(tmp_path, "1").splitlines()
    assert calls[-1] == "setprop sys.powerctl reboot"
    assert calls.count("sleep 15") == 2, calls     # 1 → 3 → 5 %


def test_junk_capacity_is_zero(tmp_path):
    calls = _run(tmp_path, "abc").splitlines()
    assert calls[0] == "sleep 15" and calls[-1] == "setprop sys.powerctl reboot"


def test_wait_is_bounded():
    text = (DIR / "bcm_autoboot.sh").read_text()
    assert "MAX_WAIT_S=7200" in text and "MIN_PCT=5" in text


def test_rc_only_charger_mode():
    rc = (DIR / "bcm-autoboot.rc").read_text()
    code = [ln.strip() for ln in rc.splitlines() if ln.strip() and not ln.strip().startswith("#")]
    triggers = [ln for ln in code if ln.startswith("on ")]
    assert triggers == ["on charger"], triggers
    assert "disabled" in code and "oneshot" in code
    assert "seclabel u:r:magisk:s0" in code
    assert any(ln.startswith("service bcm_autoboot ") and "${MAGISKTMP}/bcm_autoboot.sh" in ln
               for ln in code)


def test_patcher_backs_up_before_writing():
    text = (DIR / "patch_boot.sh").read_text()
    backup = text.index('dd if="$BOOT" of="$BACKUP"')
    first_flash = text.index('flash "$WORK/new-boot.img"')
    assert backup < first_flash
    assert "--dry-run" in text and "--restore" in text
    assert "cmp -s" in text, "the write is verified"
    assert re.search(r'exists \.backup/\.magisk', text), "only a Magisk-patched boot"
