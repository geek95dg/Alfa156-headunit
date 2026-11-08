"""Which interfaces the Wi-Fi AP may NAT through (src/multimedia/wifi_ap.py).

The phone's own Bluetooth internet (bnep*, src/network/phone_tether.py) must
never become the AA AP's uplink — the phone is that AP's client, so its
traffic would go out through the car and straight back to the phone. Same
rule as config/scripts/bcm-nat.sh. ALFA-NET (passengers) may share it, as it
always could, unless wifi.alfa_net.share_phone_internet is false. The NAT
paths run against a fake /sys/class/net, a fake ``open`` and a recording
``subprocess``; nothing is executed.
"""

import io
import subprocess
from types import SimpleNamespace

import pytest

from src.multimedia import wifi_ap
from src.multimedia.wifi_ap import _is_uplink_candidate

AP = "wlp2s0"


@pytest.mark.parametrize("name, ap, expected", [
    ("eth0", AP, True),
    ("enp0s31f6", AP, True),
    ("wwx0c5b8f279a64", AP, True),          # LTE (cdc_ether)
    ("usb0", AP, True),
    ("wlx00c0ca123456", AP, True),           # a USB Wi-Fi dongle as client
    ("lo", AP, False),
    (AP, AP, False),                          # the AP itself
    ("p2p-wlp2s0-0", AP, False),              # Wi-Fi Direct group = phone side
    ("p2p-dev-wlp2s0", AP, False),
    ("bnep0", AP, False),                     # internet FROM the phone
    ("bnep12", AP, False),
    ("docker0", AP, False),
    ("veth1a2b3c", AP, False),
    ("eth0", None, True),                     # AP iface unknown yet
    ("lo", None, False),
    ("", AP, False),
    ("eth0;reboot", AP, False),               # not a kernel name
    ("a" * 16, AP, False),                    # longer than IFNAMSIZ-1
    ("eth 0", AP, False),
    (None, AP, False),
])
def test_is_uplink_candidate(name, ap, expected):
    assert _is_uplink_candidate(name, ap) is expected


@pytest.mark.parametrize("name, expected", [
    ("bnep0", True), ("eth0", True), ("p2p-wlp2s0-0", False), ("docker0", False),
    ("lo", False), (AP, False), ("bnep0;x", False),
])
def test_allow_pan_only_lets_bnep_through(name, expected):
    assert _is_uplink_candidate(name, AP, allow_pan=True) is expected


def test_rule_matches_bcm_nat_sh():
    """The shell copy of the rule excludes the same prefixes."""
    from pathlib import Path
    text = (Path(__file__).resolve().parent.parent / "config" / "scripts" / "bcm-nat.sh").read_text()
    for prefix in wifi_ap._NON_UPLINK_PREFIXES:
        assert f"{prefix}*" in text


IFACES = {
    "lo": "unknown", "eth0": "up", "wwx0c5b8f279a64": "up", "bnep0": "up",
    "docker0": "up", "veth9": "up", "p2p-wlp2s0-0": "up", "wlp2s0": "up",
    "wlx00c0ca123456": "up", "usb0": "down",
}


@pytest.fixture
def fake_net(monkeypatch):
    rules = []

    def fake_open(path, mode="r", *a, **kw):
        if path == "/proc/sys/net/ipv4/ip_forward":
            return io.StringIO()
        name = path.split("/")[4]
        if path.endswith("/operstate") and name in IFACES:
            return io.StringIO(IFACES[name] + "\n")
        raise OSError(path)

    def fake_run(argv, *a, **kw):
        assert not kw.get("shell")
        if argv[0] == "iptables" and "-C" in argv:
            return subprocess.CompletedProcess(argv, 1)     # rule not present yet
        rules.append(list(argv))
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(wifi_ap, "open", fake_open, raising=False)
    monkeypatch.setattr(wifi_ap, "os", SimpleNamespace(listdir=lambda p: sorted(IFACES)))
    monkeypatch.setattr(wifi_ap, "subprocess", SimpleNamespace(
        run=fake_run, CalledProcessError=subprocess.CalledProcessError))
    return rules


def _manager(iface, **settings):
    mgr = object.__new__(wifi_ap.WiFiAPManager)
    mgr._interface = iface
    mgr._config = SimpleNamespace(get=lambda key, default=None: settings.get(key, default))
    return mgr


def _uplinks(rules):
    return {r[r.index("-o") + 1] for r in rules if "POSTROUTING" in r}


def test_enable_internet_sharing_skips_phone_and_container_ifaces(fake_net):
    _manager("p2p-wlp2s0-0")._enable_internet_sharing()
    assert _uplinks(fake_net) == {"eth0", "wwx0c5b8f279a64", "wlp2s0", "wlx00c0ca123456"}


def test_add_nat_for_alfa_net_shares_pan_but_not_wifi_or_containers(fake_net):
    _manager(AP)._add_nat_for("wlx00c0ca123456")
    assert _uplinks(fake_net) == {"eth0", "wwx0c5b8f279a64", "bnep0"}


def test_add_nat_for_alfa_net_without_phone_internet(fake_net):
    _manager(AP, **{"wifi.alfa_net.share_phone_internet": False})._add_nat_for(
        "wlx00c0ca123456")
    assert _uplinks(fake_net) == {"eth0", "wwx0c5b8f279a64"}
