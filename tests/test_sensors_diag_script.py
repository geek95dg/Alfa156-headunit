"""tools/bcm-sensors-diag.sh against a fake adb (read-only diagnosis of the
BCM → adb forward → SensorServer chain)."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "tools" / "bcm-sensors-diag.sh"

pytestmark = pytest.mark.skipif(shutil.which("bash") is None or os.geteuid() != 0,
                                reason="needs bash and root (the script refuses otherwise)")

FAKE_ADB = r'''#!/bin/sh
# Drop "-s SERIAL".
[ "$1" = "-s" ] && shift 2
case "$1" in
  devices) printf 'List of devices attached\nABCD1234\tdevice\n' ;;
  forward) [ -n "$FAKE_FORWARD" ] && printf 'ABCD1234 tcp:951 tcp:8080\n' ;;
  shell)
    shift
    case "$*" in
      *"pm list packages"*) echo "package:github.umer0586.sensorserver" ;;
      *pidof*) [ -n "$FAKE_RUNNING" ] && echo 1234 || exit 1 ;;
      *proc/net/tcp*) printf '  sl  local_address rem_address   st\n   0: %s:1F90 00000000:0000 0A\n' "$FAKE_LISTEN" ;;
    esac ;;
esac
'''


def _run(tmp_path, **env):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    (bin_dir / "adb").write_text(FAKE_ADB)
    (bin_dir / "journalctl").write_text("#!/bin/sh\nexit 0\n")
    for f in bin_dir.iterdir():
        f.chmod(0o755)
    e = dict(os.environ, PATH=f"{bin_dir}:{os.environ['PATH']}", **env)
    res = subprocess.run(["bash", str(SCRIPT), "951", "8080"], env=e,
                         capture_output=True, text=True, timeout=60)
    assert res.returncode == 0, res.stderr
    return res.stdout


def test_syntax():
    assert subprocess.run(["bash", "-n", str(SCRIPT)]).returncode == 0


def test_healthy_phone_side_but_no_listener_on_m910q(tmp_path):
    out = _run(tmp_path, FAKE_FORWARD="1", FAKE_RUNNING="1", FAKE_LISTEN="0100007F")
    assert "OK     forward jest" in out
    assert "aplikacja działa" in out
    assert "127.0.0.1:8080 (Local Host)" in out
    # Nothing really listens on 127.0.0.1:951 here: the probe says so.
    assert "odmowa połączenia" in out or "zamyka połączenie" in out


def test_ipv6_only_listener_is_named(tmp_path):
    out = _run(tmp_path, FAKE_LISTEN="0" * 24 + "01000000")      # ::1
    assert "brak forwardu" in out
    assert "NIE działa" in out
    assert "TYLKO na IPv6 ::1" in out


def test_never_writes():
    text = SCRIPT.read_text()
    for cmd in ("forward tcp:", "forward --remove", "am start", "pm grant", "setprop", "settings put"):
        assert cmd not in text, cmd
