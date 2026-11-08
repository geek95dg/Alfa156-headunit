"""Internet from the phone over Bluetooth PAN (src/network/phone_tether.py).

Everything runs against a scripted NetworkManager: a ``subprocess.run``
compatible fake that answers the nmcli commands the module uses from an
in-memory state, plus a fake monotonic clock. ``tick()`` is driven directly;
nothing is executed and no thread is started (except in the lifecycle test,
whose runner is the same fake).
"""

import subprocess
import time
from pathlib import Path

import pytest

from src.core import modules_catalog
from src.core.config import BCMConfig
from src.core.event_bus import EventBus
from src.network import phone_tether as pt
from src.network.phone_tether import (
    PhoneTether,
    clean_error,
    normalize_mac,
    parse_bt_devices,
    parse_ip_status,
    parse_profile,
    split_terse,
)

REPO = Path(__file__).resolve().parent.parent
PHONE = "AA:BB:CC:DD:EE:01"
OTHER = "AA:BB:CC:DD:EE:02"
CON = "bcm-phone-pan"

GENERAL = ["nmcli", "-t", "-f", "RUNNING", "general"]
DEVICES = ["nmcli", "-t", "-f", "DEVICE,TYPE,STATE", "device"]
SHOW = ["nmcli", "-g",
        "bluetooth.bdaddr,bluetooth.type,ipv4.route-metric,connection.autoconnect",
        "connection", "show", "id", CON]
UP = ["nmcli", "--wait", "30", "connection", "up", "id", CON]
TIMESYNC = ["systemctl", "start", "--no-block", "bcm-timesync.service"]


def add_argv(mac=PHONE, metric=750, con=CON, autoconnect="no"):
    return ["nmcli", "connection", "add", "type", "bluetooth",
            "con-name", con, "ifname", "*",
            "bluetooth.bdaddr", mac, "bluetooth.type", "panu",
            "ipv4.method", "auto", "ipv4.route-metric", str(metric),
            "ipv6.method", "disabled", "connection.autoconnect", autoconnect]


def status_argv(mac=PHONE):
    return ["nmcli", "-g", "GENERAL.IP-IFACE,IP4.ADDRESS,IP4.GATEWAY", "device", "show", mac]


def esc(value):
    return value.replace("\\", "\\\\").replace(":", "\\:")


class FakeClock:
    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t

    def advance(self, seconds):
        self.t += seconds


class FakeNM:
    """NetworkManager behind a subprocess.run-compatible runner."""

    def __init__(self):
        self.calls = []
        self.kwargs = []
        self.running = True
        self.missing = False               # nmcli not installed
        self.bt_devices = {}               # MAC -> device state
        self.profile = None                # {"bdaddr", "type", "metric"}
        self.up_results = []               # queue of (rc, stderr); default success
        self.status = ("bnep0", "192.168.44.23/24", "192.168.44.1")
        self.timesync_exc = None

    def __call__(self, argv, *args, **kwargs):
        assert not kwargs.get("shell"), "shell=True is never allowed"
        assert isinstance(argv, list) and all(isinstance(a, str) for a in argv)
        self.calls.append(list(argv))
        self.kwargs.append(kwargs)
        if argv == TIMESYNC:
            if self.timesync_exc is not None:
                raise self.timesync_exc
            return self._res(argv, 0)
        if self.missing:
            raise FileNotFoundError(argv[0])
        if argv == GENERAL:
            if not self.running:
                return self._res(argv, 8, err="Error: NetworkManager is not running.\n")
            return self._res(argv, 0, "running\n")
        if not self.running:
            return self._res(argv, 8, err="Error: NetworkManager is not running.\n")
        if argv == DEVICES:
            rows = ["lo:loopback:unmanaged", "wlp2s0:wifi:connected",
                    "p2p-dev-wlp2s0:wifi-p2p:disconnected"]
            rows += [f"{esc(mac)}:bt:{state}" for mac, state in self.bt_devices.items()]
            return self._res(argv, 0, "\n".join(rows) + "\n")
        if argv[:2] == ["nmcli", "-g"] and argv[3:6] == ["connection", "show", "id"]:
            if self.profile is None:
                return self._res(argv, 10, err=f"Error: {argv[6]} - no such connection profile.\n")
            p = self.profile
            return self._res(argv, 0, f"{esc(p['bdaddr'])}\n{p['type']}\n{p['metric']}\n"
                                      f"{p.get('autoconnect', 'no')}\n")
        if argv[:3] == ["nmcli", "connection", "add"]:
            vals = dict(zip(argv[3::2], argv[4::2]))
            self.profile = {"bdaddr": vals["bluetooth.bdaddr"], "type": vals["bluetooth.type"],
                            "metric": vals["ipv4.route-metric"],
                            "autoconnect": vals["connection.autoconnect"]}
            return self._res(argv, 0, f"Connection '{CON}' successfully added.\n")
        if argv[:4] == ["nmcli", "connection", "modify", "id"]:
            keymap = {"bluetooth.bdaddr": "bdaddr", "bluetooth.type": "type",
                      "ipv4.route-metric": "metric", "connection.autoconnect": "autoconnect"}
            for key, value in zip(argv[5::2], argv[6::2]):
                self.profile[keymap[key]] = value
            return self._res(argv, 0)
        if argv[:3] == ["nmcli", "--wait", "30"] and argv[3:5] == ["connection", "up"]:
            rc, err = self.up_results.pop(0) if self.up_results else (0, "")
            if rc == 0:
                self.bt_devices[self.profile["bdaddr"].upper()] = "connected"
                return self._res(argv, 0, "Connection successfully activated\n")
            return self._res(argv, rc, err=err)
        if argv[:2] == ["nmcli", "-g"] and argv[3:5] == ["device", "show"]:
            return self._res(argv, 0, "\n".join(self.status) + "\n")
        raise AssertionError(f"unexpected command: {argv}")

    @staticmethod
    def _res(argv, rc, out="", err=""):
        return subprocess.CompletedProcess(argv, rc, stdout=out, stderr=err)

    def nm_calls(self):
        return [c for c in self.calls if c[0] == "nmcli"]

    def ran(self, argv):
        return argv in self.calls

    def count(self, argv):
        return sum(1 for c in self.calls if c == argv)


def make(settings=None, last_bt="", bus=None, nm=None, clock=None):
    section = {"settle_sec": 0}
    section.update(settings or {})
    config = {"network": {"phone_tether": section},
              "multimedia": {"last_bt_device": last_bt}}
    bus = bus or EventBus()
    nm = nm or FakeNM()
    clock = clock or FakeClock()
    published = []
    bus.subscribe(pt.TOPIC, lambda t, v, ts: published.append(v))
    tether = PhoneTether(config, bus, runner=nm, clock=clock, wall_clock=lambda: 1.7e9)
    tether._bus.subscribe("bt.connected", tether._on_bt_connected)
    tether._bus.subscribe("bt.disconnected", tether._on_bt_disconnected)
    tether._bus.subscribe(pt.RETRY_TOPIC, tether._on_retry_cmd)
    return tether, bus, nm, clock, published


def phone_connected(bus, mac=PHONE):
    bus.publish("bt.connected", {"address": mac, "name": "Pixel"})


# ── pure helpers ──────────────────────────────────────────────────────────

class TestHelpers:
    @pytest.mark.parametrize("value, expected", [
        ("aa:bb:cc:dd:ee:01", PHONE),
        (" AA:BB:CC:DD:EE:01 ", PHONE),
        ("AA:BB:CC:DD:EE:0G", None),
        ("AA:BB:CC:DD:EE", None),
        ("AA-BB-CC-DD-EE-01", None),
        ("AA:BB:CC:DD:EE:01\n", PHONE),            # stripped, then fullmatch
        ("AA:BB:CC:DD:EE:01;rm -rf /", None),
        ("AA:BB:CC:DD:EE:01 --help", None),
        ("", None), (None, None), (123, None),
    ])
    def test_normalize_mac(self, value, expected):
        assert normalize_mac(value) == expected

    def test_split_terse_unescapes(self):
        assert split_terse("AA\\:BB\\:CC:bt:connected") == ["AA:BB:CC", "bt", "connected"]
        assert split_terse("a\\\\:b") == ["a\\", "b"]
        assert split_terse("") == [""]

    def test_parse_bt_devices_only_bt_rows_with_valid_mac(self):
        text = ("lo:loopback:unmanaged\n"
                f"{esc(PHONE.lower())}:bt:disconnected\n"
                f"{esc(OTHER)}:bt:connecting (prepare)\n"
                "bogus:bt:connected\n"
                "wlp2s0:wifi:connected\n")
        assert parse_bt_devices(text) == {PHONE: "disconnected", OTHER: "connecting (prepare)"}

    def test_parse_profile_multiline_and_single_line(self):
        assert parse_profile(f"{esc(PHONE)}\npanu\n750\nno\n") == (PHONE, "panu", "750", "no")
        assert parse_profile(f"{esc(PHONE)}:PANU:-1:yes") == (PHONE, "panu", "-1", "yes")
        assert parse_profile(f"{esc(PHONE)}\npanu\n") == (PHONE, "panu", "", "")
        assert parse_profile("") == ("", "", "", "")

    @pytest.mark.parametrize("text, expected", [
        ("bnep0\n192.168.44.23/24\n192.168.44.1\n",
         {"iface": "bnep0", "ip": "192.168.44.23", "prefix": 24, "gateway": "192.168.44.1"}),
        ("bnep1\n10.1.2.3/16 | 10.9.9.9/8\n10.1.0.1\n",
         {"iface": "bnep1", "ip": "10.1.2.3", "prefix": 16, "gateway": "10.1.0.1"}),
        ("bnep0\n\n\n", {"iface": "bnep0", "ip": "", "prefix": None, "gateway": ""}),
        ("--\n--\n--\n", {"iface": "", "ip": "", "prefix": None, "gateway": ""}),
        ("<script>\n999.1.1.1/99\nevil;rm\n",
         {"iface": "", "ip": "", "prefix": None, "gateway": ""}),
        ("", {"iface": "", "ip": "", "prefix": None, "gateway": ""}),
    ])
    def test_parse_ip_status(self, text, expected):
        assert parse_ip_status(text) == expected

    def test_clean_error(self):
        assert clean_error("Error:\nfoo\x1b[31m  bar\r\n") == "Error: foo [31m bar"
        assert len(clean_error("x" * 1000)) == 200
        assert clean_error(None) == ""


# ── reconciliation ────────────────────────────────────────────────────────

class TestTick:
    def test_nm_not_running_is_unavailable_and_nothing_is_added(self):
        tether, bus, nm, clock, published = make()
        nm.running = False
        phone_connected(bus)
        assert tether.tick() == "unavailable"
        assert nm.calls == [GENERAL]
        assert published[-1]["state"] == "unavailable"
        assert "not running" in published[-1]["error"]
        # slow re-check: nothing at all until the backoff has passed
        clock.advance(59)
        tether.tick()
        assert nm.calls == [GENERAL]
        clock.advance(1)
        tether.tick()
        assert nm.calls == [GENERAL, GENERAL]
        assert not any(c[:3] == ["nmcli", "connection", "add"] for c in nm.calls)

    def test_nmcli_missing_degrades_to_unavailable(self):
        tether, bus, nm, clock, published = make()
        nm.missing = True
        phone_connected(bus)
        assert tether.tick() == "unavailable"
        assert "not installed" in published[-1]["error"]

    def test_missing_profile_is_added_with_exact_argv_then_up(self):
        tether, bus, nm, clock, published = make()
        nm.bt_devices[PHONE] = "disconnected"
        phone_connected(bus)
        assert tether.tick() == "connected"
        assert nm.nm_calls() == [GENERAL, DEVICES, SHOW, add_argv(), UP, status_argv()]
        assert nm.profile == {"bdaddr": PHONE, "type": "panu", "metric": "750",
                              "autoconnect": "no"}
        last = published[-1]
        assert last == {"state": "connected", "iface": "bnep0", "ip": "192.168.44.23",
                        "prefix": 24, "gateway": "192.168.44.1", "mac": PHONE,
                        "error": "", "hint": "", "since": 1.7e9}
        assert [p["state"] for p in published] == ["connecting", "connected"]

    def test_every_call_has_a_timeout_and_no_shell(self):
        tether, bus, nm, clock, published = make()
        nm.bt_devices[PHONE] = "disconnected"
        phone_connected(bus)
        tether.tick()
        assert nm.kwargs and all("timeout" in kw and not kw.get("shell") for kw in nm.kwargs)
        up_kw = nm.kwargs[nm.calls.index(UP)]
        assert up_kw["timeout"] > 30           # longer than nmcli's own --wait
        assert up_kw["env"]["LC_ALL"] == "C"   # we compare untranslated values

    def test_different_bdaddr_is_modified(self):
        tether, bus, nm, clock, published = make()
        nm.profile = {"bdaddr": OTHER, "type": "panu", "metric": "750"}
        nm.bt_devices[PHONE] = "disconnected"
        phone_connected(bus)
        assert tether.tick() == "connected"
        assert ["nmcli", "connection", "modify", "id", CON, "bluetooth.bdaddr", PHONE] in nm.calls
        assert not any(c[:3] == ["nmcli", "connection", "add"] for c in nm.calls)
        assert nm.profile["bdaddr"] == PHONE

    def test_type_and_metric_are_corrected_too(self):
        tether, bus, nm, clock, published = make({"route_metric": 600})
        nm.profile = {"bdaddr": PHONE, "type": "dun", "metric": "-1"}
        nm.bt_devices[PHONE] = "disconnected"
        phone_connected(bus)
        tether.tick()
        assert ["nmcli", "connection", "modify", "id", CON, "bluetooth.type", "panu",
                "ipv4.route-metric", "600"] in nm.calls

    def test_autoconnect_is_off_by_default_and_corrected(self):
        tether, bus, nm, clock, published = make()
        nm.profile = {"bdaddr": PHONE, "type": "panu", "metric": "750", "autoconnect": "yes"}
        nm.bt_devices[PHONE] = "disconnected"
        phone_connected(bus)
        tether.tick()
        assert ["nmcli", "connection", "modify", "id", CON,
                "connection.autoconnect", "no"] in nm.calls

    def test_autoconnect_can_be_enabled(self):
        tether, bus, nm, clock, published = make({"autoconnect": True})
        nm.bt_devices[PHONE] = "disconnected"
        phone_connected(bus)
        tether.tick()
        assert add_argv(autoconnect="yes") in nm.calls

    def test_matching_profile_is_left_alone(self):
        tether, bus, nm, clock, published = make()
        nm.profile = {"bdaddr": PHONE, "type": "panu", "metric": "750"}
        nm.bt_devices[PHONE] = "disconnected"
        phone_connected(bus)
        tether.tick()
        assert nm.nm_calls() == [GENERAL, DEVICES, SHOW, UP, status_argv()]

    @pytest.mark.parametrize("pinned, bt_addr, last_bt", [
        ("AA:BB:CC:DD:EE:GG", PHONE, ""),               # bad pinned MAC
        ("AA:BB:CC:DD:EE:01; reboot", PHONE, ""),
        ("", "AA:BB:CC:DD:EE:01 --wait 0", ""),          # bad address on the bus
        ("", None, "$(reboot)"),                         # bad last_bt_device
        ("", None, ""),                                  # nothing known
    ])
    def test_invalid_mac_never_reaches_the_runner(self, pinned, bt_addr, last_bt):
        tether, bus, nm, clock, published = make({"mac": pinned}, last_bt=last_bt)
        nm.bt_devices[PHONE] = "disconnected"
        bus.publish("bt.connected", {"address": bt_addr, "name": "x"})
        for _ in range(3):
            assert tether.tick() == "failed"
            clock.advance(700)
        assert nm.calls == []
        assert published[-1]["state"] == "failed" and published[-1]["mac"] == ""

    def test_mac_falls_back_to_last_bt_device(self):
        tether, bus, nm, clock, published = make(last_bt=PHONE.lower())
        nm.bt_devices[PHONE] = "disconnected"
        bus.publish("bt.connected", {"name": "no address"})
        assert tether.tick() == "connected"
        assert add_argv() in nm.calls

    def test_pinned_mac_ignores_another_phone(self):
        tether, bus, nm, clock, published = make({"mac": OTHER.lower()})
        nm.bt_devices[PHONE] = "disconnected"
        phone_connected(bus, PHONE)
        assert tether.tick() == "waiting_phone"
        assert nm.calls == []
        assert published[-1]["mac"] == OTHER

    def test_no_nap_means_no_up_attempt(self):
        tether, bus, nm, clock, published = make()
        phone_connected(bus)                       # NM lists no bt device for it
        assert tether.tick() == "no_nap"
        assert nm.nm_calls() == [GENERAL, DEVICES]
        assert "tethering" in published[-1]["error"]
        # NAP shows up (tethering switched on) -> next pass connects
        nm.bt_devices[PHONE] = "disconnected"
        clock.advance(30)
        assert tether.tick() == "connected"

    def test_unavailable_device_counts_as_no_nap(self):
        tether, bus, nm, clock, published = make()
        nm.bt_devices[PHONE] = "unavailable"
        phone_connected(bus)
        assert tether.tick() == "no_nap"
        assert UP not in nm.calls

    def test_nm_already_connecting_is_not_disturbed(self):
        tether, bus, nm, clock, published = make()
        nm.bt_devices[PHONE] = "connecting (getting IP configuration)"
        phone_connected(bus)
        assert tether.tick() == "connecting"
        assert UP not in nm.calls and SHOW not in nm.calls

    @staticmethod
    def _attempt_times(tether, nm, clock, passes):
        attempts = []
        for _ in range(passes):                    # one pass every 30 s
            before = nm.count(UP)
            state = tether.tick()
            if nm.count(UP) > before:
                attempts.append(clock.t)
                assert state == "failed"
            clock.advance(30)
        return [b - a for a, b in zip(attempts, attempts[1:])]

    def test_tethering_off_on_android_retries_on_the_short_cap_with_hint(self):
        # Android keeps its NAP record while tethering is off: NM still
        # lists the device and `connection up` is refused (module docstring).
        tether, bus, nm, clock, published = make()
        nm.bt_devices[PHONE] = "disconnected"
        nm.up_results = [(4, "Error: Connection activation failed: NAP not available")] * 200
        phone_connected(bus)
        gaps = self._attempt_times(tether, nm, clock, 120)      # 1 h
        assert gaps[:4] == [60, 120, 120, 120]
        assert set(gaps[1:]) == {120}
        assert tether.retry_delay == 120
        last = published[-1]
        assert last["state"] == "failed" and last["hint"] == pt.HINT_CHECK_TETHERING
        assert last["error"].startswith("Error: Connection activation failed")
        assert nm.bt_devices[PHONE] == "disconnected"

        # Tethering switched on: the next attempt (<= 120 s later) connects
        # and the hint is gone.
        nm.up_results = []
        for _ in range(5):
            clock.advance(30)
            tether.tick()
        assert published[-1]["state"] == "connected" and published[-1]["hint"] == ""

    def test_retry_command_drops_the_backoff(self):
        tether, bus, nm, clock, published = make()
        nm.bt_devices[PHONE] = "disconnected"
        nm.up_results = [(4, "refused"), (4, "refused")]
        phone_connected(bus)
        assert tether.tick() == "failed"
        clock.advance(5)
        tether.tick()
        assert nm.count(UP) == 1                   # inside the 60 s backoff
        bus.publish(pt.RETRY_TOPIC, {"anything": "ignored"})
        tether.tick()
        assert nm.count(UP) == 2                   # at once
        bus.publish(pt.RETRY_TOPIC, True)
        assert tether.tick() == "connected"
        assert nm.count(UP) == 3

    def test_retry_command_keeps_the_settle_gate(self):
        tether, bus, nm, clock, published = make({"settle_sec": 15})
        nm.bt_devices[PHONE] = "disconnected"
        phone_connected(bus)
        assert tether.tick() == "connecting"
        bus.publish(pt.RETRY_TOPIC, True)
        assert tether.tick() == "connecting"
        assert UP not in nm.calls                  # AA bootstrap still protected

    def test_nm_unavailable_backs_off_up_to_max_retry_sec(self):
        tether, bus, nm, clock, published = make()
        nm.running = False
        phone_connected(bus)
        times = []
        for _ in range(120):
            before = nm.count(GENERAL)
            tether.tick()
            if nm.count(GENERAL) > before:
                times.append(clock.t)
            clock.advance(30)
        gaps = [b - a for a, b in zip(times, times[1:])]
        assert gaps[:5] == [60, 120, 240, 480, 600]

    def test_up_failure_doubles_backoff_to_cap_and_bt_connected_resets(self):
        tether, bus, nm, clock, published = make({"retry_sec": 60, "max_retry_sec": 600,
                                                  "max_retry_connected_sec": 600})
        nm.bt_devices[PHONE] = "disconnected"
        nm.up_results = [(4, "Error: Connection activation failed: NAP not available")] * 20
        phone_connected(bus)

        attempts = []
        for _ in range(240):                       # 2 h of 30 s passes
            before = nm.count(UP)
            state = tether.tick()
            if nm.count(UP) > before:
                attempts.append(clock.t)
                assert state == "failed"
            clock.advance(30)
        gaps = [b - a for a, b in zip(attempts, attempts[1:])]
        assert gaps[:6] == [60, 120, 240, 480, 600, 600]
        assert set(gaps[4:]) == {600}
        assert published[-1]["error"].startswith("Error: Connection activation failed")
        assert tether.retry_delay == 600

        # A new phone connection resets the backoff: attempt at once.
        phone_connected(bus)
        before = nm.count(UP)
        tether.tick()
        assert nm.count(UP) == before + 1
        assert tether.retry_delay == 120           # 60 used by this failure, doubled

    def test_settle_delay_after_connect(self):
        tether, bus, nm, clock, published = make({"settle_sec": 15})
        nm.bt_devices[PHONE] = "disconnected"
        phone_connected(bus)
        assert tether.tick() == "connecting"
        assert UP not in nm.calls and SHOW not in nm.calls     # BlueZ left alone
        assert tether.next_wait() == 15
        clock.advance(15)
        assert tether.tick() == "connected"

    def test_externally_connected_link_is_picked_up_during_backoff(self):
        tether, bus, nm, clock, published = make()
        nm.bt_devices[PHONE] = "disconnected"
        nm.up_results = [(4, "timeout")]
        phone_connected(bus)
        assert tether.tick() == "failed"
        nm.bt_devices[PHONE] = "connected"         # NM autoconnect succeeded
        clock.advance(30)                          # still inside the 60 s backoff
        assert tether.tick() == "connected"
        assert tether.retry_delay == 60            # success resets the backoff

    def test_bt_disconnected_means_waiting_phone(self):
        tether, bus, nm, clock, published = make()
        nm.bt_devices[PHONE] = "disconnected"
        phone_connected(bus)
        assert tether.tick() == "connected"
        calls = len(nm.calls)
        bus.publish("bt.disconnected", {"address": PHONE})
        assert tether.tick() == "waiting_phone"
        assert len(nm.calls) == calls              # NM tears the link down itself
        assert published[-1]["state"] == "waiting_phone"
        assert published[-1]["ip"] == ""

    def test_disconnect_of_another_device_is_ignored(self):
        tether, bus, nm, clock, published = make()
        nm.bt_devices[PHONE] = "disconnected"
        phone_connected(bus)
        tether.tick()
        bus.publish("bt.disconnected", {"address": OTHER})
        assert tether.tick() == "connected"

    def test_timesync_once_per_transition(self):
        tether, bus, nm, clock, published = make()
        nm.bt_devices[PHONE] = "disconnected"
        phone_connected(bus)
        tether.tick()
        assert nm.count(TIMESYNC) == 1
        for _ in range(3):
            clock.advance(30)
            assert tether.tick() == "connected"
        assert nm.count(TIMESYNC) == 1
        bus.publish("bt.disconnected", {"address": PHONE})
        tether.tick()
        nm.bt_devices[PHONE] = "disconnected"
        phone_connected(bus)
        assert tether.tick() == "connected"
        assert nm.count(TIMESYNC) == 2

    def test_timesync_errors_are_ignored_and_it_can_be_disabled(self):
        tether, bus, nm, clock, published = make()
        nm.timesync_exc = FileNotFoundError("systemctl")
        nm.bt_devices[PHONE] = "disconnected"
        phone_connected(bus)
        assert tether.tick() == "connected"

        tether2, bus2, nm2, _, _ = make({"trigger_timesync": False})
        nm2.bt_devices[PHONE] = "disconnected"
        phone_connected(bus2)
        assert tether2.tick() == "connected"
        assert nm2.count(TIMESYNC) == 0

    def test_publishes_only_on_change(self):
        tether, bus, nm, clock, published = make()
        nm.bt_devices[PHONE] = "disconnected"
        phone_connected(bus)
        tether.tick()
        n = len(published)
        for _ in range(5):
            clock.advance(30)
            tether.tick()
        assert len(published) == n
        nm.status = ("bnep0", "192.168.44.99/24", "192.168.44.1")   # new DHCP lease
        tether.tick()
        assert len(published) == n + 1 and published[-1]["ip"] == "192.168.44.99"

    def test_waiting_phone_without_any_bt_event(self):
        tether, bus, nm, clock, published = make()
        assert tether.tick() == "waiting_phone"
        assert nm.calls == []

    def test_invalid_con_name_falls_back_to_default(self):
        tether, *_ = make({"con_name": "--wait 0; reboot"})
        assert tether.con_name == CON
        tether, *_ = make({"con_name": "my-pan.1"})
        assert tether.con_name == "my-pan.1"

    def test_bad_numbers_fall_back_or_clamp(self):
        tether, *_ = make({"retry_sec": "x", "max_retry_sec": True, "check_sec": 1,
                           "route_metric": float("nan"), "max_retry_connected_sec": "y"})
        assert tether.retry_delay == 60
        assert tether._max_retry_sec == 600
        assert tether._max_retry_up_sec == 120
        assert tether._check_sec == 5
        assert tether._metric == 750
        # the up cap lives inside [retry_sec, max_retry_sec]
        tether, *_ = make({"max_retry_sec": 300, "max_retry_connected_sec": 900})
        assert tether._max_retry_up_sec == 300
        tether, *_ = make({"retry_sec": 90, "max_retry_connected_sec": 10})
        assert tether._max_retry_up_sec == 90


# ── start-up and lifecycle ────────────────────────────────────────────────

class TestLifecycle:
    def test_seed_from_bus_when_phone_connected_before_start(self):
        bus = EventBus()
        phone_connected(bus)
        tether, bus, nm, clock, published = make(bus=bus)
        nm.bt_devices[PHONE] = "disconnected"
        tether.seed_from_bus()
        assert tether.tick() == "connected"

    def test_seed_prefers_the_newer_disconnect(self):
        bus = EventBus()
        phone_connected(bus)
        time.sleep(0.002)
        bus.publish("bt.disconnected", {"address": PHONE})
        tether, bus, nm, clock, published = make(bus=bus)
        tether.seed_from_bus()
        assert tether.tick() == "waiting_phone"
        assert nm.calls == []

    def test_start_runs_a_pass_and_stop_publishes_disabled(self):
        bus = EventBus()
        nm = FakeNM()
        nm.running = False
        published = []
        bus.subscribe(pt.TOPIC, lambda t, v, ts: published.append(v["state"]))
        tether = PhoneTether({"network": {"phone_tether": {"check_sec": 5}}}, bus, runner=nm)
        phone_connected(bus)
        tether.start()
        deadline = time.monotonic() + 5
        while "unavailable" not in published and time.monotonic() < deadline:
            time.sleep(0.01)
        assert "unavailable" in published
        tether.stop()
        tether._thread.join(timeout=5)
        assert not tether._thread.is_alive()
        assert published[-1] == "disabled"

    def test_shutdown_event_stops_it(self):
        bus = EventBus()
        tether = PhoneTether({}, bus, runner=FakeNM())
        tether.start()
        bus.publish("power.shutting_down", True)
        tether._thread.join(timeout=5)
        assert not tether._thread.is_alive()


class TestRegistration:
    def test_catalog_entry_is_off_by_default(self):
        info = modules_catalog.MODULES["phone_tether"]
        assert info["entry"] == ("src.network.phone_tether", "start_phone_tether")
        assert info["default"] is False

    def test_production_off_test_config_on(self):
        prod = BCMConfig(config_path=str(REPO / "config" / "bcm_config.yaml"),
                         platform_override="x86")
        test = BCMConfig(config_path=str(REPO / "config" / "bcm_config_test.yaml"),
                         platform_override="x86")
        assert modules_catalog.is_enabled(prod, "phone_tether") is False
        assert modules_catalog.is_enabled(test, "phone_tether") is True

    def test_test_config_block_is_read(self):
        cfg = BCMConfig(config_path=str(REPO / "config" / "bcm_config_test.yaml"),
                        platform_override="x86")
        tether = PhoneTether(cfg, EventBus(), runner=FakeNM())
        assert tether.con_name == CON
        assert tether._metric == 750 and tether._check_sec == 30
        assert tether._max_retry_sec == 600 and tether._max_retry_up_sec == 120
        assert tether._settle_sec == 15 and tether._trigger_timesync is True
        assert tether._autoconnect is False
