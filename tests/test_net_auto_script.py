"""config/scripts/bcm-net-auto.sh against fake nmcli / ip / systemctl.

The M910q case from the car: a static-IP Ethernet profile whose default
route is pinned as ``ipv4.routes "0.0.0.0/0 GW 100"`` (wins over every
other uplink, even with no internet behind the cable). The script must turn
it into a plain gateway with metric 900, keep the address, turn on NM's
connectivity check, leave BCM's own profiles alone, and undo it all.
"""

import json
import os
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "config" / "scripts" / "bcm-net-auto.sh"

pytestmark = pytest.mark.skipif(shutil.which("bash") is None, reason="no bash")

# Fake NetworkManager: profiles in a JSON file, every call logged.
FAKE_NMCLI = r'''#!/usr/bin/env python3
import json, os, sys
db_path = os.environ["FAKE_NM_DB"]
db = json.load(open(db_path))
open(os.environ["FAKE_NM_LOG"], "a").write(json.dumps(sys.argv[1:]) + "\n")
a = sys.argv[1:]
def save(): json.dump(db, open(db_path, "w"))
if a[:3] == ["-t", "-f", "RUNNING"]:
    print("running"); sys.exit(0)
if a[:1] == ["-g"] and a[2:4] == ["connection", "show"] and "uuid" not in a:
    fields = a[1].split(",")
    for u, p in db.items():
        if "--active" in a and not p.get("GENERAL.DEVICES"):
            continue
        vals = {"UUID": u, "TYPE": p["type"], "DEVICE": p.get("GENERAL.DEVICES", "")}
        print(":".join(vals[f] for f in fields))
    sys.exit(0)
if a[:1] == ["-g"] and a[2:4] == ["connection", "show"]:
    p = db[a[5]]
    for f in a[1].split(","):
        print(p.get(f, ""))
    sys.exit(0)
if a[:3] == ["connection", "modify", "uuid"]:
    p = db[a[3]]; rest = a[4:]
    for k, v in zip(rest[::2], rest[1::2]):
        if k.startswith("-"):
            items = [r.strip() for r in p.get(k[1:], "").split(",") if r.strip()]
            p[k[1:]] = ", ".join(r for r in items if r != v)
        else:
            p[k] = v
    save(); sys.exit(0)
if a[:2] == ["-g", "GENERAL.STATE"]:
    print("100 (connected)"); sys.exit(0)
sys.exit(0)
'''


@pytest.fixture
def env(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "nmcli").write_text(FAKE_NMCLI)
    (bin_dir / "ip").write_text("#!/bin/sh\necho 'default via 192.168.1.1 dev eno1 proto static metric 100'\n")
    for name in ("systemctl", "sleep"):
        (bin_dir / name).write_text("#!/bin/sh\nexit 0\n")
    for f in bin_dir.iterdir():
        f.chmod(0o755)
    db = {
        "u-eth": {"type": "802-3-ethernet", "connection.id": "Eth static", "ipv4.method": "manual",
                  "ipv4.route-metric": "-1", "ipv4.never-default": "no", "ipv4.gateway": "",
                  "ipv4.routes": "0.0.0.0/0 192.168.1.1 100, 10.9.0.0/16 192.168.1.254",
                  "GENERAL.DEVICES": "eno1"},
        "u-bcm": {"type": "802-3-ethernet", "connection.id": "bcm-car-phone",
                  "ipv4.method": "manual", "ipv4.route-metric": "650"},
        "u-dhcp": {"type": "802-3-ethernet", "connection.id": "Wired 2", "ipv4.method": "auto",
                   "ipv4.route-metric": "-1"},
        "u-wifi": {"type": "802-11-wireless", "connection.id": "ALFA-NET", "ipv4.method": "shared"},
    }
    (tmp_path / "db.json").write_text(json.dumps(db))
    (tmp_path / "interfaces").write_text("auto lo\niface lo inet loopback\n")
    e = dict(os.environ, PATH=f"{bin_dir}:{os.environ['PATH']}",
             FAKE_NM_DB=str(tmp_path / "db.json"), FAKE_NM_LOG=str(tmp_path / "log"),
             BCM_NET_STATE_DIR=str(tmp_path / "state"), BCM_NM_CONF_DIR=str(tmp_path / "nm"),
             BCM_IFACES_FILE=str(tmp_path / "interfaces"), BCM_NETPLAN_DIR=str(tmp_path / "netplan"),
             BCM_NET_ALLOW_NONROOT="1")
    return tmp_path, e


def _run(env, *args):
    tmp, e = env
    res = subprocess.run(["bash", str(SCRIPT), *args], env=e, capture_output=True,
                         text=True, timeout=60)
    assert res.returncode == 0, res.stderr + res.stdout
    db = json.loads((tmp / "db.json").read_text())
    return res.stdout + res.stderr, db


def test_dry_run_changes_nothing(env):
    tmp, _ = env
    before = (tmp / "db.json").read_text()
    out, _ = _run(env, "--dry-run")
    assert "[dry-run] nmcli connection modify uuid u-eth" in out
    assert (tmp / "db.json").read_text() == before
    assert not (tmp / "nm").exists() and not (tmp / "state").exists()


def test_apply_and_undo(env):
    tmp, _ = env
    out, db = _run(env)
    eth = db["u-eth"]
    # Pinned default route → plain gateway with the worst metric.
    assert eth["ipv4.gateway"] == "192.168.1.1"
    assert eth["ipv4.route-metric"] == "900"
    assert eth["ipv4.routes"] == "10.9.0.0/16 192.168.1.254", "other static routes stay"
    assert eth["ipv4.method"] == "manual", "the static address stays"
    # BCM's profile, DHCP ethernet and Wi-Fi untouched.
    assert db["u-bcm"]["ipv4.route-metric"] == "650"
    assert db["u-dhcp"]["ipv4.route-metric"] == "-1"
    assert "ipv4.route-metric" not in db["u-wifi"]
    conn = (tmp / "nm" / "bcm-connectivity.conf").read_text()
    assert "[connectivity]" in conn and "interval=60" in conn and "uri=http" in conn
    assert "rndis_host" in (tmp / "nm" / "bcm-no-auto-default.conf").read_text()
    assert (tmp / "state" / "net-auto.state").stat().st_mode & 0o777 == 0o600

    # Second run: idempotent, the saved "before" is not overwritten.
    state1 = (tmp / "state" / "net-auto.state").read_text()
    _run(env)
    assert (tmp / "state" / "net-auto.state").read_text() == state1

    _, db = _run(env, "--undo")
    eth = db["u-eth"]
    assert eth["ipv4.route-metric"] == "-1"
    assert eth["ipv4.gateway"] == ""
    assert eth["ipv4.routes"].startswith("0.0.0.0/0 192.168.1.1 100")
    assert not (tmp / "nm" / "bcm-connectivity.conf").exists()


def test_eth_no_default(env):
    _, db = _run(env, "--eth-no-default")
    assert db["u-eth"]["ipv4.never-default"] == "yes"


def test_ifupdown_gateway_gets_metric(env):
    tmp, _ = env
    (tmp / "interfaces").write_text(textwrap.dedent("""\
        auto eno1
        iface eno1 inet static
            address 192.168.1.50/24
            gateway 192.168.1.1
        """))
    _run(env)
    text = (tmp / "interfaces").read_text()
    assert "    gateway 192.168.1.1\n    metric 900\n" in text
    assert (tmp / "interfaces.bcm-net-auto.bak").exists()
    _run(env)  # idempotent
    assert (tmp / "interfaces").read_text().count("metric 900") == 1


def test_bad_option_and_metric():
    res = subprocess.run(["bash", str(SCRIPT), "--eth-metric", "x;rm"], capture_output=True, text=True)
    assert res.returncode == 2
