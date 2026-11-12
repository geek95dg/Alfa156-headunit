"""The phone mounted in the car: USB tethering, GPS forward, battery, clock,
hotspot status over adb + nmcli (src/network/car_phone.py).

Everything runs against a scripted phone and NetworkManager: a
``subprocess.run`` compatible fake (:class:`FakePhone`) that answers exactly
the adb / nmcli / timedatectl / systemctl commands the module is allowed to
run and RECORDS any other argv as unexpected (an exception would be
swallowed by ``_proc._run``, which never raises — so every test checks
``fake.unexpected == []`` at teardown), plus a fake clock for monotonic,
wall and boot time. ``tick()`` is driven directly; no thread is started
except in the lifecycle test, whose runner is the same fake. sysfs (AOAP)
and the bcm-timesync marker are files under ``tmp_path``.
"""

import subprocess
import time
from pathlib import Path

import pytest

import main
from src.core import modules_catalog
from src.core import notifications
from src.core.config import BCMConfig
from src.core.event_bus import EventBus
from src.network import car_phone as cp
from src.network.car_phone import (
    CarPhone,
    aoap_present,
    mask_serial,
    parse_battery,
    parse_build_epoch,
    parse_devices,
    parse_epoch,
    parse_functions,
    parse_hotspot,
    prepare_private_dir,
    read_timesync_marker,
)

REPO = Path(__file__).resolve().parent.parent
SER = "1a2b3c4d"
SER2 = "9z8y7x6w"
CON = "bcm-car-phone"
WALL0 = 1767225600.0            # 2026-01-01 00:00:00 UTC

DEVICES = ["adb", "devices", "-l"]
ACTIVE = ["nmcli", "-t", "-f", "NAME,DEVICE,STATE", "connection", "show", "--active"]
SHOW = ["nmcli", "-g", CarPhone.PROFILE_FIELDS, "connection", "show", "id", CON]
ADD = ["nmcli", "connection", "add", "type", "ethernet", "con-name", CON, "ifname", "*",
       "match.driver", "rndis_host cdc_ncm", "ipv4.method", "auto",
       "ipv4.route-metric", "650", "ipv6.method", "disabled",
       "connection.autoconnect", "yes"]
UP = ["nmcli", "--wait", "30", "connection", "up", "id", CON]
DEVSHOW = ["nmcli", "-g", "GENERAL.IP-IFACE,IP4.ADDRESS,IP4.GATEWAY", "device", "show", "usb0"]
TIMESYNC = ["systemctl", "start", "--no-block", "bcm-timesync.service"]


def adb(serial, *words):
    return ["adb", "-s", serial, *words]


GETF = adb(SER, "shell", "svc", "usb", "getFunctions")
SETF = adb(SER, "shell", "svc", "usb", "setFunctions", "rndis")
FWD_LIST = adb(SER, "forward", "--list")
FWD = adb(SER, "forward", "tcp:50000", "tcp:50000")
BATT = adb(SER, "shell", "dumpsys", "battery")
DATE = adb(SER, "shell", "date", "+%s")
BUILD = adb(SER, "shell", "getprop", "ro.build.date.utc")
#: ROM build time of the fake phone: 200 days before WALL0.
BUILD0 = int(WALL0) - 200 * 86400
TETH = adb(SER, "shell", "dumpsys", "tethering")
TETH_OLD = adb(SER, "shell", "dumpsys", "connectivity", "tethering")


def dev_line(serial=SER, state="device", usb="1-2"):
    tail = f" usb:{usb} product:begonia model:Redmi_Note_8_Pro device:begonia " \
           f"transport_id:3" if usb else " transport_id:7"
    return f"{serial:<22} {state}{tail}"


def devices_text(*lines, daemon=False):
    head = []
    if daemon:
        head = ["* daemon not running; starting now at tcp:5037",
                "* daemon started successfully"]
    return "\n".join(head + ["List of devices attached", *lines, ""]) + "\n"


BATTERY = """Current Battery Service state:
  AC powered: false
  USB powered: true
  Wireless powered: false
  Max charging current: 500000
  status: 2
  health: 2
  present: true
  level: 78
  scale: 100
  voltage: 4123
  temperature: 312
  technology: Li-poly
"""


def battery(temp_tenths=312, level=78, status=2, health=2, extra=""):
    return (BATTERY.replace("temperature: 312", f"temperature: {temp_tenths}")
            .replace("level: 78", f"level: {level}")
            .replace("status: 2", f"status: {status}")
            .replace("health: 2", f"health: {health}") + extra)


TETHERING_ON = """Tethering:
  Configuration:
    tetherableUsbRegexs: [rndis\\d]
  Tether state:
    rndis0 - TetheredState - lastError = 0
    wlan1 - TetheredState - lastError = 0
  Connected clients: 2
"""
TETHERING_OFF = """Tethering:
  Tether state:
    rndis0 - TetheredState - lastError = 0
    wlan1 - AvailableState - lastError = 0
"""


class FakeClock:
    def __init__(self):
        self.t = 1000.0
        self.wall_offset = WALL0 - 1000.0
        self.boot_offset = 0.0

    def mono(self):
        return self.t

    def wall(self):
        return self.t + self.wall_offset

    def boot(self):
        return self.t + self.boot_offset

    def advance(self, seconds):
        self.t += seconds


class FakePhone:
    """adb + nmcli + timedatectl + systemctl behind a subprocess.run runner."""

    def __init__(self):
        self.calls = []
        self.kwargs = []
        self.unexpected = []
        # adb
        self.adb_missing = False
        self.adb_timeout = False
        self.devices = devices_text(dev_line())
        self.functions = "mtp,adb"          # what getFunctions prints (to stderr)
        self.functions_stream = "stderr"
        self.functions_noise = ""           # stderr lines before the answer
        self.set_effect = "link"            # link | func | refuse
        self.forwards = set()
        self.forward_err = ""
        self.battery = battery()
        self.battery_rc = 0
        self.date = str(int(WALL0))
        self.build = str(BUILD0)
        self.build_rc = 0
        # The private adb server socket every adb call must name.
        self.adb_socket = None
        self.tethering = TETHERING_ON
        self.connectivity_tethering = ""
        # NetworkManager
        self.nm_missing = False
        self.link = None                    # None | "activated" | "activating"
        self.profile = None                 # dict or None (exit 10)
        self.up_results = []
        self.dev_show = "usb0\n192.168.42.100/24\n192.168.42.129\n"
        # timedatectl
        self.set_time_rc = 0

    # helpers for tests
    def ran(self, argv):
        return argv in self.calls

    def count(self, argv):
        return sum(1 for c in self.calls if c == argv)

    def all_words(self):
        return [w for c in self.calls for w in c]

    @staticmethod
    def _res(argv, rc, out="", err=""):
        return subprocess.CompletedProcess(argv, rc, stdout=out, stderr=err)

    def __call__(self, argv, *args, **kwargs):
        assert not kwargs.get("shell"), "shell=True is never allowed"
        assert isinstance(argv, list) and all(isinstance(a, str) for a in argv), argv
        assert kwargs.get("timeout"), f"no timeout for {argv}"
        self.calls.append(list(argv))
        self.kwargs.append(kwargs)
        prog = argv[0]
        if argv == TIMESYNC:
            return self._res(argv, 0)
        if prog == "adb":
            return self._adb(argv, kwargs)
        if prog == "nmcli":
            return self._nmcli(argv)
        if argv[:2] == ["timedatectl", "set-time"] and len(argv) == 3:
            return self._res(argv, self.set_time_rc,
                             err="" if self.set_time_rc == 0 else "Failed to set time")
        self.unexpected.append(list(argv))
        return self._res(argv, 99)

    def _adb(self, argv, kwargs):
        env = kwargs.get("env") or {}
        assert env.get("LC_ALL") == "C" and env.get("HOME") == "/root", "adb env"
        # Never the default TCP server on 127.0.0.1:5037 (any local user).
        assert self.adb_socket is not None and \
            env.get("ADB_SERVER_SOCKET") == f"localfilesystem:{self.adb_socket}", env.get(
                "ADB_SERVER_SOCKET")
        if self.adb_missing:
            raise FileNotFoundError("adb")
        if self.adb_timeout:
            raise subprocess.TimeoutExpired(argv, kwargs["timeout"])
        if argv == DEVICES:
            return self._res(argv, 0, self.devices)
        serial = argv[2] if argv[1] == "-s" else None
        rest = argv[3:]
        if serial is None:
            self.unexpected.append(list(argv))
            return self._res(argv, 99)
        if rest == ["shell", "svc", "usb", "getFunctions"]:
            if self.functions_stream == "stderr":
                return self._res(argv, 0, "", self.functions_noise + self.functions + "\n")
            return self._res(argv, 0, self.functions + "\n", "")
        if rest[:4] == ["shell", "svc", "usb", "setFunctions"] and len(rest) == 5:
            if self.set_effect in ("link", "func"):
                self.functions = f"{rest[4]},adb"
            if self.set_effect == "link":
                self.link = "activated"
            return self._res(argv, 0)
        if rest == ["forward", "--list"]:
            return self._res(argv, 0, "".join(f"{line}\n" for line in sorted(self.forwards)))
        if rest[:1] == ["forward"] and len(rest) == 3 and rest[1].startswith("tcp:"):
            if self.forward_err:
                return self._res(argv, 1, err=self.forward_err)
            self.forwards.add(f"{serial} {rest[1]} {rest[2]}")
            return self._res(argv, 0, rest[1].split(":")[1] + "\n")
        if rest == ["shell", "dumpsys", "battery"]:
            return self._res(argv, self.battery_rc, self.battery)
        if rest == ["shell", "date", "+%s"]:
            return self._res(argv, 0, self.date + "\n")
        if rest == ["shell", "getprop", "ro.build.date.utc"]:
            return self._res(argv, self.build_rc, self.build + "\n")
        if rest == ["shell", "dumpsys", "tethering"]:
            return self._res(argv, 0, self.tethering)
        if rest == ["shell", "dumpsys", "connectivity", "tethering"]:
            return self._res(argv, 0, self.connectivity_tethering)
        self.unexpected.append(list(argv))
        return self._res(argv, 99)

    def _nmcli(self, argv):
        if self.nm_missing:
            raise FileNotFoundError("nmcli")
        if argv == ACTIVE:
            rows = ["Wired connection 1:enp0s31f6:activated"]
            if self.link:
                rows.append(f"{CON}:usb0:{self.link}")
            return self._res(argv, 0, "\n".join(rows) + "\n")
        if argv == DEVSHOW:
            return self._res(argv, 0, self.dev_show)
        if argv == SHOW:
            if self.profile is None:
                return self._res(argv, 10, err=f"Error: {CON} - no such connection profile.\n")
            p = self.profile
            return self._res(argv, 0, "\n".join([p["type"], p["match"], p["v4"], p["metric"],
                                                 p["v6"], p["auto"]]) + "\n")
        if argv[:3] == ["nmcli", "connection", "add"]:
            vals = dict(zip(argv[3::2], argv[4::2]))
            self.profile = {"type": "802-3-ethernet", "match": vals["match.driver"],
                            "v4": vals["ipv4.method"], "metric": vals["ipv4.route-metric"],
                            "v6": vals["ipv6.method"], "auto": vals["connection.autoconnect"]}
            return self._res(argv, 0)
        if argv[:5] == ["nmcli", "connection", "modify", "id", CON]:
            keymap = {"match.driver": "match", "ipv4.method": "v4", "ipv4.route-metric": "metric",
                      "ipv6.method": "v6", "connection.autoconnect": "auto"}
            for key, value in zip(argv[5::2], argv[6::2]):
                self.profile[keymap[key]] = value
            return self._res(argv, 0)
        if argv == UP:
            rc, err = self.up_results.pop(0) if self.up_results else (0, "")
            if rc == 0:
                self.link = "activated"
            return self._res(argv, rc, err=err)
        self.unexpected.append(list(argv))
        return self._res(argv, 99)


GOOD_PROFILE = {"type": "802-3-ethernet", "match": "rndis_host cdc_ncm", "v4": "auto",
                "metric": "650", "v6": "disabled", "auto": "yes"}


@pytest.fixture
def env(tmp_path):
    usb = tmp_path / "usb"
    usb.mkdir()
    adb_dir = tmp_path / "run" / "bcm-adb"      # created by the module
    made = []

    def make(settings=None, *, hotspot=False, fake=None, clock=None, bus=None,
             config_extra=None, real_notify=False):
        section = {"time_sync": False}
        section.update(settings or {})
        config = {"network": {"car_phone": section},
                  "hardware": {"gps": {"tcp": {"port": 50000}}}}
        if hotspot:
            config["modules"] = {"car_phone_hotspot": True}
        if config_extra:
            config.update(config_extra)
        fake = fake or FakePhone()
        fake.adb_socket = str(adb_dir / cp.ADB_SOCKET_NAME)
        clock = clock or FakeClock()
        bus = bus or EventBus()
        published = []
        notes = []
        bus.subscribe(cp.TOPIC, lambda t, v, ts: published.append(v))
        kwargs = {}
        if not real_notify:
            kwargs["notify"] = lambda bus_, title, desc, **kw: notes.append(dict(kw, title=title,
                                                                              desc=desc))
        phone = CarPhone(config, bus, runner=fake, clock=clock.mono, wall_clock=clock.wall,
                         boot_clock=clock.boot, usb_root=str(usb),
                         marker_path=str(tmp_path / "timesync.ok"),
                         adb_socket_dir=str(adb_dir), **kwargs)
        bus.subscribe(cp.RETRY_TOPIC, phone._on_retry_cmd)
        made.append(fake)
        return phone, fake, clock, bus, published, notes

    make.usb = usb
    make.marker = tmp_path / "timesync.ok"
    make.adb_dir = adb_dir
    yield make
    for fake in made:
        assert fake.unexpected == [], f"unexpected commands: {fake.unexpected}"


def connect_fully(make_env, **kw):
    """A phone that tethers on the first setFunctions; NM link up."""
    phone, fake, clock, bus, published, notes = make_env(**kw)
    fake.profile = dict(GOOD_PROFILE)
    return phone, fake, clock, bus, published, notes


def aoap_device(root, name="1-2", vid="18d1", pid="2d01"):
    d = root / name
    d.mkdir()
    (d / "idVendor").write_text(vid + "\n")
    (d / "idProduct").write_text(pid + "\n")


# ── pure helpers ──────────────────────────────────────────────────────────

class TestParseDevices:
    def test_daemon_lines_header_and_states(self):
        text = devices_text(dev_line(), dev_line(SER2, "unauthorized", "1-3"),
                            "emulator-5554          offline",
                            "ABCDEF12               no permissions (user in plugdev group; "
                            "are your udev rules wrong?); see [http://developer.android.com/"
                            "tools/device.html] usb:1-4 transport_id:9",
                            daemon=True)
        devs = parse_devices(text)
        assert devs == [
            {"serial": SER, "state": "device", "usb": True},
            {"serial": SER2, "state": "unauthorized", "usb": True},
            {"serial": "emulator-5554", "state": "offline", "usb": False},
            {"serial": "ABCDEF12", "state": "no_permissions", "usb": True},
        ]

    @pytest.mark.parametrize("line", [
        "$(reboot)              device usb:1-1",
        "-s                     device usb:1-1",
        "a;b                    device usb:1-1",
        "adb server version (41) doesn't match this client (39); killing...",
        "error: protocol fault",
        "x" * 80 + " device usb:1-1",
        "1a2b                   DEVICE!! usb:1-1",
    ])
    def test_hostile_or_foreign_lines_are_dropped(self, line):
        assert parse_devices(devices_text(line)) == []

    def test_network_transport_is_not_usb(self):
        devs = parse_devices(devices_text("192.168.1.5:5555       device product:x transport_id:4"))
        assert devs == [{"serial": "192.168.1.5:5555", "state": "device", "usb": False}]

    def test_mask_serial(self):
        assert mask_serial(SER) == "1a…4d"
        assert mask_serial("abcd") == "…"
        assert mask_serial("") == "" and mask_serial(None) == ""


class TestParseFunctions:
    def test_from_stderr_or_stdout(self):
        assert parse_functions("", "rndis,adb") == {"rndis", "adb"}
        assert parse_functions("mtp,adb\n", "") == {"mtp", "adb"}

    @pytest.mark.parametrize("text", ["", "Error: rndis not supported", "rndis, adb",
                                      "RNDIS,ADB", "rndis;reboot"])
    def test_anything_else_is_unknown(self, text):
        assert parse_functions(text, text) is None


class TestParseBattery:
    def test_full_dump(self):
        assert parse_battery(BATTERY) == {
            "battery_pct": 78, "temp_c": 31.2, "charging": True, "full": False,
            "plugged": "usb", "health": "good", "overheat": False, "overridden": False}

    def test_full_and_overheat(self):
        data = parse_battery(battery(temp_tenths=515, status=5, health=3))
        assert data["full"] is True and data["charging"] is False
        assert data["health"] == "overheat" and data["overheat"] is True
        assert data["temp_c"] == 51.5

    def test_updates_stopped_only_sets_the_flag(self):
        text = BATTERY.replace("Current Battery Service state:\n",
                               "Current Battery Service state:\n"
                               "  (UPDATES STOPPED -- use 'reset' to restart)\n")
        data = parse_battery(text)
        assert data["overridden"] is True and data["battery_pct"] == 78

    @pytest.mark.parametrize("text", [
        "", "garbage\n\x00\x01", "level: 150\ntemperature: 9999\nstatus: x\n",
        "  level: -5\n  temperature: abc\n", "level: 78 percent\n",
        "xlevel: 50\n", "level:\n",
    ])
    def test_garbage_gives_none_not_an_exception(self, text):
        data = parse_battery(text)
        assert data["battery_pct"] is None and data["temp_c"] is None
        assert data["charging"] is None and data["plugged"] is None

    def test_unplugged_and_scale(self):
        text = (BATTERY.replace("USB powered: true", "USB powered: false")
                .replace("scale: 100", "scale: 200").replace("level: 78", "level: 100"))
        data = parse_battery(text)
        assert data["plugged"] == "" and data["battery_pct"] == 50


class TestParseHotspot:
    def test_active_with_clients(self):
        assert parse_hotspot(TETHERING_ON) == (True, 2)

    def test_usb_only_is_not_the_hotspot(self):
        assert parse_hotspot(TETHERING_OFF) == (False, None)

    @pytest.mark.parametrize("text", ["", "Can't find service: tethering\n",
                                      "Tethering:\n  something new: yes\n", "wlan1 on\n"])
    def test_unknown_format_is_none(self, text):
        assert parse_hotspot(text) == (None, None)


class TestParseEpoch:
    @pytest.mark.parametrize("text, expected", [
        ("1767225600\n", 1767225600), (" 1767225600 ", 1767225600),
        ("1600000000", None),          # 2020: before the sane range
        ("17672256000", None), ("12345", None), ("", None), ("1767225600; reboot", None),
        ("-1767225600", None), ("1767225600.5", None),
    ])
    def test_values(self, text, expected):
        assert parse_epoch(text) == expected


class TestParseBuildEpoch:
    @pytest.mark.parametrize("text, expected", [
        ("1735000000\n", 1735000000), ("999999999", None), ("1000000000", 1000000000),
        ("", None), ("\n", None), ("1735000000 x", None), ("-1735000000", None),
        ("17350000000", None), ("4102444801", None),
    ])
    def test_values(self, text, expected):
        assert parse_build_epoch(text) == expected


class TestPrivateAdbDir:
    def test_created_0700(self, tmp_path):
        d = tmp_path / "run" / "bcm-adb"
        assert prepare_private_dir(str(d)) == ""
        assert d.is_dir() and (d.stat().st_mode & 0o777) == 0o700

    def test_loose_mode_is_tightened(self, tmp_path):
        d = tmp_path / "bcm-adb"
        d.mkdir(mode=0o755)
        d.chmod(0o755)
        assert prepare_private_dir(str(d)) == ""
        assert (d.stat().st_mode & 0o777) == 0o700

    def test_symlink_and_file_are_refused(self, tmp_path):
        real = tmp_path / "elsewhere"
        real.mkdir(mode=0o700)
        link = tmp_path / "bcm-adb"
        link.symlink_to(real)
        assert "not a directory" in prepare_private_dir(str(link))
        f = tmp_path / "file"
        f.write_text("x")
        assert prepare_private_dir(str(f))      # an error text, never ""

    def test_foreign_owner_is_refused(self, tmp_path, monkeypatch):
        d = tmp_path / "bcm-adb"
        d.mkdir(mode=0o700)
        monkeypatch.setattr(cp.os, "geteuid", lambda: d.stat().st_uid + 1)
        assert "belongs to uid" in prepare_private_dir(str(d))

    def test_env_names_the_private_socket(self):
        assert cp.ADB_ENV == {"HOME": "/root",
                              "ADB_SERVER_SOCKET": "localfilesystem:/run/bcm-adb/adb.sock"}

    def test_every_adb_call_uses_it(self, env):
        phone, fake, clock, bus, published, notes = connect_fully(
            env, settings={"time_sync": True}, hotspot=True)
        fake.date = str(int(WALL0) + 18000)
        phone.tick()
        clock.advance(10)
        phone.tick()
        adb_calls = [(c, kw) for c, kw in zip(fake.calls, fake.kwargs) if c[0] == "adb"]
        assert len({tuple(c[3:5]) for c, _ in adb_calls}) >= 5     # devices, forward, shell…
        want = f"localfilesystem:{env.adb_dir}/{cp.ADB_SOCKET_NAME}"
        assert all(kw["env"]["ADB_SERVER_SOCKET"] == want for _, kw in adb_calls)
        assert (env.adb_dir.stat().st_mode & 0o777) == 0o700

    def test_no_private_dir_means_no_adb_at_all(self, env, caplog):
        env.adb_dir.parent.mkdir(parents=True)
        env.adb_dir.write_text("not a directory")
        phone, fake, clock, bus, published, notes = env()
        with caplog.at_level("WARNING", logger="bcm.network.car_phone"):
            assert phone.tick() == "adb_error"
        assert not [c for c in fake.calls if c[0] == "adb"]
        assert phone.state["error"].startswith("adb not started: cannot prepare ")
        assert phone._adb_retry_at > clock.mono()            # backs off like any adb error
        env.adb_dir.unlink()
        clock.advance(phone._adb_retry_at - clock.mono())
        phone.tick()
        assert fake.ran(DEVICES) and env.adb_dir.is_dir()


class TestSysfsAndMarker:
    def test_aoap_detection(self, tmp_path):
        assert aoap_present(str(tmp_path)) is False
        d = tmp_path / "1-1"
        d.mkdir()
        (d / "idVendor").write_text("2717\n")         # Xiaomi in normal mode
        (d / "idProduct").write_text("ff48\n")
        assert aoap_present(str(tmp_path)) is False
        aoap_device(tmp_path, "1-2", "18d1", "2d00")
        assert aoap_present(str(tmp_path)) is True

    def test_missing_root_is_not_aoap(self, tmp_path):
        assert aoap_present(str(tmp_path / "nope")) is False

    def test_marker(self, tmp_path):
        m = tmp_path / "ok"
        assert read_timesync_marker(str(m)) is None
        m.write_text("1234 1767225600\n")
        assert read_timesync_marker(str(m)) == 1234.0
        m.write_text("garbage\n")
        assert read_timesync_marker(str(m)) is None


# ── adb states ────────────────────────────────────────────────────────────

class TestAdbStates:
    def test_adb_missing(self, env, caplog):
        phone, fake, clock, bus, published, notes = env()
        fake.adb_missing = True
        with caplog.at_level("WARNING", logger="bcm.network.car_phone"):
            for _ in range(3):
                assert phone.tick() == "no_adb"
                clock.advance(30)
        state = phone.state
        assert state["hint"] == "install_adb" and state["adb"] == "missing"
        warnings = [r for r in caplog.records if "adb not installed" in r.getMessage()]
        assert len(warnings) == 1                         # once, not every 30 s
        assert len(published) == 1                        # publish on change only
        assert fake.count(DEVICES) == 3                   # re-checked: apt install shows up

    def test_adb_timeout_backs_off(self, env):
        phone, fake, clock, bus, published, notes = env()
        fake.adb_timeout = True
        assert phone.tick() == "adb_error"
        assert fake.kwargs[0]["timeout"] == cp.FIRST_ADB_TIMEOUT_S     # may start the server
        assert "timed out" in phone.state["error"]
        clock.advance(5)
        assert phone.tick() == "adb_error"
        assert fake.count(DEVICES) == 1                   # backoff (15 s)
        clock.advance(11)
        phone.tick()
        assert fake.count(DEVICES) == 2
        clock.advance(16)
        phone.tick()
        assert fake.count(DEVICES) == 2                   # doubled to 30 s
        fake.adb_timeout = False
        clock.advance(15)
        assert phone.tick() != "adb_error"
        devices_calls = [k["timeout"] for c, k in zip(fake.calls, fake.kwargs) if c == DEVICES]
        assert devices_calls[-1] == cp.FIRST_ADB_TIMEOUT_S    # first after an error
        clock.advance(30)
        phone.tick()
        devices_calls = [k["timeout"] for c, k in zip(fake.calls, fake.kwargs) if c == DEVICES]
        assert devices_calls[-1] == cp.PROBE_TIMEOUT_S

    def test_no_device(self, env):
        phone, fake, clock, bus, published, notes = env()
        fake.devices = devices_text(daemon=True)
        assert phone.tick() == "no_device"
        assert phone.state["adb"] == "" and phone.state["serial"] == ""
        assert not any(c[:2] == ["adb", "-s"] for c in fake.calls)

    def test_unauthorized(self, env):
        phone, fake, clock, bus, published, notes = env()
        fake.devices = devices_text(dev_line(state="unauthorized"))
        assert phone.tick() == "unauthorized"
        assert phone.state["hint"] == "authorize" and phone.state["adb"] == "unauthorized"
        assert not any(c[:2] == ["adb", "-s"] for c in fake.calls)

    def test_offline(self, env):
        phone, fake, clock, bus, published, notes = env()
        fake.devices = devices_text(dev_line(state="offline"))
        assert phone.tick() == "no_device"
        assert phone.state["adb"] == "offline" and "offline" in phone.state["error"]
        assert not any(c[:2] == ["adb", "-s"] for c in fake.calls)

    def test_no_permissions(self, env):
        phone, fake, clock, bus, published, notes = env()
        fake.devices = devices_text(f"{SER}  no permissions (user in plugdev group); see "
                                    f"[http://x] usb:1-2 transport_id:1")
        assert phone.tick() == "no_device"
        assert phone.state["adb"] == "no_permissions"

    def test_two_phones_without_serial(self, env):
        phone, fake, clock, bus, published, notes = env()
        fake.devices = devices_text(dev_line(), dev_line(SER2, usb="1-3"))
        assert phone.tick() == "failed"
        assert phone.state["hint"] == "pin_serial"
        assert not any(c[:2] == ["adb", "-s"] for c in fake.calls)

    def test_two_phones_one_unauthorized_picks_the_ready_one(self, env):
        phone, fake, clock, bus, published, notes = connect_fully(env)
        fake.devices = devices_text(dev_line(), dev_line(SER2, "unauthorized", "1-3"))
        phone.tick()
        assert phone.state["serial"] == mask_serial(SER)
        assert not any(SER2 in c for c in fake.calls[1:])

    def test_pinned_serial_picks_it_among_two(self, env):
        phone, fake, clock, bus, published, notes = connect_fully(env, settings={"serial": SER2})
        fake.devices = devices_text(dev_line(), dev_line(SER2, usb="1-3"))
        phone.tick()
        assert phone.state["serial"] == mask_serial(SER2)
        assert not any(c[:3] == ["adb", "-s", SER] for c in fake.calls)

    def test_pinned_serial_absent(self, env):
        phone, fake, clock, bus, published, notes = env({"serial": SER2})
        assert phone.tick() == "no_device"
        assert "not connected" in phone.state["error"]
        assert not any(c[:2] == ["adb", "-s"] for c in fake.calls)

    def test_network_devices_are_never_picked(self, env):
        phone, fake, clock, bus, published, notes = env()
        fake.devices = devices_text("192.168.1.5:5555       device product:x transport_id:4")
        assert phone.tick() == "no_device"
        assert "network" in phone.state["error"]
        assert not any(c[:2] == ["adb", "-s"] for c in fake.calls)


# ── nothing from the config or the device reaches argv unchecked ─────────

class TestInjection:
    @pytest.mark.parametrize("serial", ["x; reboot", "-s", "$(id)", "a b", "--help", 12345,
                                        ["SER"], "x" * 70])
    def test_bad_serial_never_reaches_argv(self, env, serial):
        phone, fake, clock, bus, published, notes = env({"serial": serial})
        fake.devices = devices_text(dev_line(), daemon=True)
        assert phone.tick() == "failed"
        assert "invalid network.car_phone.serial" in phone.state["error"]
        assert not any(c[:2] == ["adb", "-s"] for c in fake.calls)
        assert str(serial) not in fake.all_words()

    @pytest.mark.parametrize("key", ["gps_remote_port", "gps_local_port"])
    @pytest.mark.parametrize("value", ["50000; reboot", 70000, -1, 5.5, True, "tcp:1"])
    def test_bad_port_falls_back_and_never_reaches_argv(self, env, key, value):
        phone, fake, clock, bus, published, notes = connect_fully(env, settings={key: value})
        phone.tick()
        assert fake.ran(FWD)                               # the defaults
        assert all(str(value) not in w for w in fake.all_words())

    def test_bad_function_and_method_fall_back(self, env):
        phone, fake, clock, bus, published, notes = env({"usb_function": "rndis;reboot",
                                                         "tether_method": "su"})
        assert phone._usb_function == "rndis" and phone._tether_method == "svc_usb"

    def test_hostile_serial_from_adb_output_is_skipped(self, env):
        phone, fake, clock, bus, published, notes = env()
        fake.devices = devices_text("$(reboot)  device usb:1-1", "a;b  device usb:1-2")
        assert phone.tick() == "no_device"
        assert not any(c[:2] == ["adb", "-s"] for c in fake.calls)

    def test_bad_con_name_falls_back(self, env):
        phone, fake, clock, bus, published, notes = env({"con_name": "--x; rm"})
        assert phone.con_name == CON

    def test_numbers_are_clamped(self, env):
        phone, fake, clock, bus, published, notes = env({"check_sec": 0, "battery_sec": "x",
                                                         "critical_temp_c": 10,
                                                         "warn_temp_c": 45})
        assert phone._check_sec == 5 and phone._battery_sec == 60
        assert phone._crit_c == 45                       # critical >= warn


# ── tethering ─────────────────────────────────────────────────────────────

class TestTethering:
    def test_profile_created_then_setfunctions_then_connected(self, env):
        phone, fake, clock, bus, published, notes = env()
        assert phone.tick() == "tethering"
        assert fake.ran(ADD) and fake.ran(GETF) and fake.ran(SETF)
        assert fake.profile["match"] == "rndis_host cdc_ncm"     # not cdc_ether
        clock.advance(10)
        assert phone.tick() == "connected"
        state = phone.state
        assert state["ip"] == "192.168.42.100" and state["prefix"] == 24
        assert state["gateway"] == "192.168.42.129" and state["iface"] == "usb0"
        assert fake.count(TIMESYNC) == 1

    def test_getfunctions_on_stderr_means_no_setfunctions(self, env):
        phone, fake, clock, bus, published, notes = connect_fully(env)
        fake.functions = "rndis,adb"
        fake.functions_stream = "stderr"
        assert phone.tick() == "tethering"
        assert fake.ran(GETF) and not fake.ran(SETF)

    def test_getfunctions_answer_after_linker_warnings(self, env):
        # A ROM's linker warns on stderr before the answer; the answer is
        # its own (last) line and must still be found — else setFunctions
        # would be re-issued and end in a false tether_blocked.
        phone, fake, clock, bus, published, notes = connect_fully(env)
        fake.functions = "rndis,adb"
        fake.functions_noise = ("WARNING: linker: /system/bin/app_process64: unsupported "
                                "flags DT_FLAGS_1=0x8000001 " + "x" * 300 + "\n"
                                "WARNING: linker: Warning: \"libfoo.so\" unused DT entry\n")
        for _ in range(4):
            phone.tick()
            clock.advance(10)
        assert fake.ran(GETF) and not fake.ran(SETF)
        assert phone.state["hint"] != cp.HINT_TETHER_BLOCKED
        assert fake.ran(UP)                 # function there, link missing: connection up

    def test_getfunctions_on_stdout_too(self, env):
        phone, fake, clock, bus, published, notes = connect_fully(env)
        fake.functions = "rndis,adb"
        fake.functions_stream = "stdout"
        phone.tick()
        assert not fake.ran(SETF)

    def test_settle_window_asks_nothing(self, env):
        phone, fake, clock, bus, published, notes = connect_fully(env)
        fake.set_effect = "refuse"
        phone.tick()
        n = len(fake.calls)
        clock.advance(5)
        assert phone.tick() == "tethering"
        assert fake.count(GETF) == 1 and fake.count(SETF) == 1
        assert len(fake.calls) > n                         # devices/NM/forward still read
        assert 4 <= phone.next_wait() <= 5.01

    def test_tether_blocked_after_three_attempts(self, env):
        phone, fake, clock, bus, published, notes = connect_fully(env)
        fake.set_effect = "refuse"
        for _ in range(3):
            assert phone.tick() == "tethering"
            clock.advance(10)
        assert phone.tick() == "failed"
        assert phone.state["hint"] == "tether_blocked"
        assert fake.count(SETF) == 3
        clock.advance(5)
        assert phone.tick() == "failed"                   # backoff: nothing new
        assert fake.count(SETF) == 3
        # Settings "Ponów" drops the backoff and the counter
        bus.publish(cp.RETRY_TOPIC, {"serial": "x; reboot"})
        fake.set_effect = "link"
        assert phone.tick() == "tethering"
        assert fake.count(SETF) == 4
        clock.advance(10)
        assert phone.tick() == "connected"

    def test_attempts_survive_the_phone_dropping_off_usb(self, env):
        phone, fake, clock, bus, published, notes = connect_fully(env)
        fake.set_effect = "refuse"
        present = fake.devices
        for _ in range(3):
            phone.tick()
            clock.advance(5)
            fake.devices = devices_text()                  # re-enumerating
            phone.tick()
            clock.advance(5)
            fake.devices = present
        assert phone.tick() == "failed" and phone.state["hint"] == "tether_blocked"
        assert fake.count(SETF) == 3

    def test_function_present_but_no_link_one_up_then_backoff(self, env):
        phone, fake, clock, bus, published, notes = connect_fully(env)
        fake.functions = "rndis,adb"
        fake.up_results = [(4, "Error: Connection activation failed: no device"),
                           (4, "Error: again")]
        assert phone.tick() == "tethering"               # NM gets settle_sec to autoconnect
        assert not fake.ran(UP)
        clock.advance(10)
        assert phone.tick() == "failed"
        assert fake.count(UP) == 1
        assert [k["timeout"] for c, k in zip(fake.calls, fake.kwargs) if c == UP] == [45.0]
        clock.advance(10)
        phone.tick()
        assert fake.count(UP) == 1                        # backoff 15 s
        clock.advance(6)
        phone.tick()
        assert fake.count(UP) == 2                        # one per backoff period
        clock.advance(31)
        assert phone.tick() == "connected"
        assert fake.count(UP) == 3

    def test_link_active_is_connected_regardless_of_adb(self, env):
        phone, fake, clock, bus, published, notes = env()
        fake.link = "activated"
        fake.devices = devices_text(dev_line(state="unauthorized"))
        assert phone.tick() == "connected"
        assert phone.state["adb"] == "unauthorized"
        fake.adb_missing = True
        assert phone.tick() == "connected"
        assert phone.state["adb"] == "missing"

    def test_activating_link_is_tethering(self, env):
        phone, fake, clock, bus, published, notes = connect_fully(env)
        fake.link = "activating"
        assert phone.tick() == "tethering"
        assert not fake.ran(GETF)

    def test_tether_method_none_never_sets_functions(self, env):
        phone, fake, clock, bus, published, notes = connect_fully(
            env, settings={"tether_method": "none"})
        assert phone.tick() == "tethering"
        assert not fake.ran(GETF) and not fake.ran(SETF)
        fake.link = "activated"
        assert phone.tick() == "connected"

    def test_ncm_function(self, env):
        phone, fake, clock, bus, published, notes = connect_fully(
            env, settings={"usb_function": "ncm"})
        phone.tick()
        assert fake.ran(adb(SER, "shell", "svc", "usb", "setFunctions", "ncm"))

    def test_nmcli_missing_is_a_failure_with_backoff(self, env):
        phone, fake, clock, bus, published, notes = env()
        fake.nm_missing = True
        assert phone.tick() == "failed"
        assert "NetworkManager" in phone.state["error"]
        assert not fake.ran(SETF)
        assert fake.ran(FWD)                               # GPS still works without NM

    def test_timesync_exactly_once_per_edge(self, env):
        phone, fake, clock, bus, published, notes = connect_fully(env)
        fake.link = "activated"
        for _ in range(3):
            assert phone.tick() == "connected"
            clock.advance(30)
        assert fake.count(TIMESYNC) == 1
        fake.link = None
        fake.functions = "rndis,adb"
        assert phone.tick() == "tethering"
        fake.link = "activated"
        assert phone.tick() == "connected"
        phone.tick()
        assert fake.count(TIMESYNC) == 2

    def test_no_timesync_when_disabled(self, env):
        phone, fake, clock, bus, published, notes = connect_fully(
            env, settings={"trigger_timesync": False})
        fake.link = "activated"
        phone.tick()
        assert fake.count(TIMESYNC) == 0


class TestProfile:
    def test_drift_is_fixed(self, env):
        phone, fake, clock, bus, published, notes = env()
        fake.profile = dict(GOOD_PROFILE, match="rndis_host,cdc_ether", metric="100",
                            auto="no")
        phone.tick()
        mods = [c for c in fake.calls if c[:3] == ["nmcli", "connection", "modify"]]
        assert mods == [["nmcli", "connection", "modify", "id", CON,
                         "match.driver", "rndis_host cdc_ncm", "ipv4.route-metric", "650",
                         "connection.autoconnect", "yes"]]
        assert not fake.ran(ADD)

    def test_comma_separated_readback_is_not_drift(self, env):
        phone, fake, clock, bus, published, notes = env()
        fake.profile = dict(GOOD_PROFILE, match="rndis_host,cdc_ncm")
        phone.tick()
        assert not any(c[:3] == ["nmcli", "connection", "modify"] for c in fake.calls)

    def test_foreign_profile_type_is_never_touched(self, env):
        phone, fake, clock, bus, published, notes = env()
        fake.profile = dict(GOOD_PROFILE, type="bluetooth")
        assert phone.tick() == "failed"
        assert "type bluetooth" in phone.state["error"]
        assert not any(c[:3] == ["nmcli", "connection", "modify"] for c in fake.calls)
        assert not fake.ran(SETF)

    def test_custom_metric(self, env):
        phone, fake, clock, bus, published, notes = env({"route_metric": 600})
        phone.tick()
        add = [c for c in fake.calls if c[:3] == ["nmcli", "connection", "add"]][0]
        assert add[add.index("ipv4.route-metric") + 1] == "600"


class TestAoap:
    def test_accessory_mode_means_aa_usb_probe(self, env):
        phone, fake, clock, bus, published, notes = connect_fully(env)
        aoap_device(env.usb)
        assert phone.tick() == "failed"
        assert phone.state["hint"] == "aa_usb_probe"
        assert not fake.ran(SETF)                          # never fight autoapp
        assert fake.ran(FWD) and fake.ran(BATT)            # the rest still works

    def test_with_a_link_it_is_connected(self, env):
        phone, fake, clock, bus, published, notes = connect_fully(env)
        aoap_device(env.usb)
        fake.link = "activated"
        assert phone.tick() == "connected"


# ── GPS forward ───────────────────────────────────────────────────────────

class TestForward:
    def test_created_once_and_recreated_after_an_adb_restart(self, env):
        phone, fake, clock, bus, published, notes = connect_fully(env)
        fake.link = "activated"
        phone.tick()
        assert fake.count(FWD) == 1
        assert phone.state["gps_forward"] is True and phone.state["gps_port"] == 50000
        clock.advance(30)
        phone.tick()
        assert fake.count(FWD) == 1 and fake.count(FWD_LIST) == 2
        fake.forwards.clear()                              # adb server restarted
        clock.advance(30)
        phone.tick()
        assert fake.count(FWD) == 2
        never = {"--remove-all", "wait-for-usb-device", "tcpip", "su", "reboot"}
        assert never.isdisjoint(fake.all_words())

    def test_other_forward_lines_do_not_count(self, env):
        phone, fake, clock, bus, published, notes = connect_fully(env)
        fake.forwards = {f"{SER} tcp:50000 tcp:8765", f"{SER2} tcp:50000 tcp:50000"}
        phone.tick()
        assert fake.count(FWD) == 1

    def test_local_port_follows_the_gps_config(self, env):
        phone, fake, clock, bus, published, notes = connect_fully(
            env, settings={"gps_remote_port": 50001},
            config_extra={"hardware": {"gps": {"tcp": {"port": 50555}}}})
        phone.tick()
        assert fake.ran(adb(SER, "forward", "tcp:50555", "tcp:50001"))
        assert phone.state["gps_port"] == 50555

    def test_cannot_bind(self, env, caplog):
        phone, fake, clock, bus, published, notes = connect_fully(env)
        fake.link = "activated"
        fake.forward_err = "error: cannot bind listener: Address already in use"
        with caplog.at_level("WARNING", logger="bcm.network.car_phone"):
            phone.tick()
            clock.advance(30)
            phone.tick()
        state = phone.state
        assert state["gps_forward"] is False and state["gps_port"] is None
        assert "in use" in state["error"] and state["state"] == "connected"
        assert len([r for r in caplog.records if "in use" in r.getMessage()]) == 1

    def test_disabled_forward(self, env):
        phone, fake, clock, bus, published, notes = connect_fully(
            env, settings={"gps_forward": False})
        phone.tick()
        assert not fake.ran(FWD_LIST) and not fake.ran(FWD)
        assert phone.state["gps_forward"] is False


# ── battery and heat ──────────────────────────────────────────────────────

class TestBattery:
    def test_read_on_appearance_then_every_battery_sec(self, env):
        phone, fake, clock, bus, published, notes = connect_fully(env)
        fake.link = "activated"
        phone.tick()
        assert fake.count(BATT) == 1
        state = phone.state
        assert state["battery_pct"] == 78 and state["temp_c"] == 31.2
        assert state["charging"] is True and state["plugged"] == "usb"
        clock.advance(30)
        phone.tick()
        assert fake.count(BATT) == 1
        clock.advance(30)
        phone.tick()
        assert fake.count(BATT) == 2

    def test_garbage_and_failures_keep_running(self, env):
        phone, fake, clock, bus, published, notes = connect_fully(env)
        fake.battery = "\x00garbage\nlevel: 300\n"
        phone.tick()
        assert phone.state["battery_pct"] is None
        fake.battery_rc = 1
        clock.advance(60)
        phone.tick()
        assert phone.state["battery_pct"] is None

    def test_updates_stopped_is_flagged_never_reset(self, env):
        phone, fake, clock, bus, published, notes = connect_fully(env)
        fake.battery = "  (UPDATES STOPPED -- use 'reset' to restart)\n" + BATTERY
        phone.tick()
        assert phone.state["overridden"] is True
        assert "reset" not in fake.all_words()

    def test_phone_gone_clears_its_data(self, env):
        phone, fake, clock, bus, published, notes = connect_fully(env)
        fake.set_effect = "refuse"
        phone.tick()
        assert phone.state["battery_pct"] == 78
        fake.devices = devices_text()
        assert phone.tick() == "no_device"
        assert phone.state["battery_pct"] is None and phone.state["gps_forward"] is False

    def test_link_outlives_adb_but_the_phone_data_goes(self, env):
        phone, fake, clock, bus, published, notes = connect_fully(env)
        fake.link = "activated"
        phone.tick()
        fake.devices = devices_text()
        assert phone.tick() == "connected"                 # the cable still carries data
        assert phone.state["battery_pct"] is None and phone.state["gps_forward"] is False
        assert phone.state["adb"] == ""


class TestHeat:
    def _set(self, fake, celsius):
        fake.battery = battery(temp_tenths=int(celsius * 10))

    def test_hysteresis_and_dedupe(self, env):
        phone, fake, clock, bus, published, notes = connect_fully(
            env, settings={"battery_sec": 15})
        fake.link = "activated"
        self._set(fake, 46)
        phone.tick()
        assert [n["severity"] for n in notes] == ["warning"]
        assert notes[0]["key"] == "car_phone_heat" and notes[0]["icon"] == "device_thermostat"
        assert notes[0]["ttl"] == 60 and "46" in notes[0]["desc"]
        assert phone.state["heat"] == "warning"
        for _ in range(3):                                 # 45 s: no repeat
            clock.advance(15)
            phone.tick()
        assert len(notes) == 1
        clock.advance(15)                                  # 60 s: re-announced
        phone.tick()
        assert len(notes) == 2
        self._set(fake, 51)                                # escalation: at once
        clock.advance(15)
        phone.tick()
        assert notes[-1]["severity"] == "danger" and len(notes) == 3
        self._set(fake, 43)                                # below warn, above warn-3
        clock.advance(15)
        phone.tick()
        assert phone.state["heat"] == "warning" and len(notes) == 3
        self._set(fake, 41.9)                              # cleared
        clock.advance(15)
        phone.tick()
        assert phone.state["heat"] is None
        self._set(fake, 45)
        clock.advance(15)
        phone.tick()
        assert notes[-1]["severity"] == "warning" and len(notes) == 4

    def test_android_overheat_health_is_danger(self, env):
        phone, fake, clock, bus, published, notes = connect_fully(env)
        fake.battery = battery(temp_tenths=400, health=3)
        phone.tick()
        assert notes[-1]["severity"] == "danger"

    def test_real_notification_is_one_entry_per_key(self, env):
        phone, fake, clock, bus, published, notes = connect_fully(
            env, settings={"battery_sec": 15}, real_notify=True)
        self._set(fake, 47)
        phone.tick()
        clock.advance(60)
        phone.tick()
        entries = bus.get_last(notifications.TOPIC)[0]
        heat = [e for e in entries if e["key"] == "car_phone_heat"]
        assert len(heat) == 1 and heat[0]["severity"] == "warning"
        assert heat[0]["icon"] == "device_thermostat"


# ── clock (plan D1) ───────────────────────────────────────────────────────

def _set_time_calls(fake):
    return [c for c in fake.calls if c[:2] == ["timedatectl", "set-time"]]


class TestTimeSync:
    def test_drift_sets_the_clock(self, env):
        phone, fake, clock, bus, published, notes = connect_fully(
            env, settings={"time_sync": True})
        fake.date = str(int(WALL0) + 3600 * 5)
        phone.tick()
        assert _set_time_calls(fake) == [["timedatectl", "set-time", f"@{int(WALL0) + 18000}"]]
        assert phone.state["time_synced_at"] is not None
        clock.advance(30)
        phone.tick()
        assert fake.count(DATE) == 1                       # at most every 10 min
        clock.advance(cp.TIME_CHECK_S)
        phone.tick()
        assert fake.count(DATE) == 2

    def test_small_drift_is_left_alone(self, env):
        phone, fake, clock, bus, published, notes = connect_fully(
            env, settings={"time_sync": True})
        fake.date = str(int(WALL0) + 10)
        phone.tick()
        assert fake.ran(DATE) and _set_time_calls(fake) == []

    @pytest.mark.parametrize("value", ["1600000000", "garbage", "17672256000", "",
                                       "1767225600; reboot"])
    def test_insane_phone_clock_is_never_used(self, env, value):
        phone, fake, clock, bus, published, notes = connect_fully(
            env, settings={"time_sync": True})
        fake.date = value
        phone.tick()
        assert _set_time_calls(fake) == []

    def test_fresh_bcm_timesync_wins(self, env):
        phone, fake, clock, bus, published, notes = connect_fully(
            env, settings={"time_sync": True})
        clock.boot_offset = 0.0
        env.marker.write_text(f"{int(clock.boot()) - 100} {int(WALL0)}\n")
        fake.date = str(int(WALL0) + 18000)
        phone.tick()
        assert not fake.ran(DATE)

    def test_stale_bcm_timesync_lets_the_phone_in(self, env):
        phone, fake, clock, bus, published, notes = connect_fully(
            env, settings={"time_sync": True})
        clock.boot_offset = 100000.0                     # a unit up for a day
        env.marker.write_text(f"{int(clock.boot()) - 5000} {int(WALL0)}\n")
        fake.date = str(int(WALL0) + 18000)
        phone.tick()
        assert fake.ran(DATE) and len(_set_time_calls(fake)) == 1

    @pytest.mark.parametrize("age", [3599, 3650, 4400])
    def test_marker_just_past_the_hour_still_wins(self, env, age):
        # bcm-timesync.timer fires every hour, give or take its accuracy and
        # curl's run time: a marker 3600-3670 s old is a HEALTHY internet sync.
        phone, fake, clock, bus, published, notes = connect_fully(
            env, settings={"time_sync": True})
        clock.boot_offset = 100000.0
        env.marker.write_text(f"{int(clock.boot()) - age} {int(WALL0)}\n")
        fake.date = str(int(WALL0) + 18000)
        phone.tick()
        assert not fake.ran(DATE) and _set_time_calls(fake) == []

    def test_phone_at_its_build_time_fallback_is_never_used(self, env, caplog):
        # Battery run flat on a long stop, switched on by hand: Android starts
        # the clock at the ROM's build time. Setting ours from it would step
        # the head unit back by months (and write the RTC).
        phone, fake, clock, bus, published, notes = connect_fully(
            env, settings={"time_sync": True})
        fake.date = str(BUILD0 + 3600)
        with caplog.at_level("WARNING", logger="bcm.network.car_phone"):
            phone.tick()
            for _ in range(3):                              # also never "confirmed"
                clock.advance(cp.TIME_CHECK_S)
                fake.date = str(int(fake.date) + int(cp.TIME_CHECK_S))
                phone.tick()
        assert fake.count(DATE) == 4 and _set_time_calls(fake) == []
        assert fake.count(BUILD) == 1                       # once per appearance
        assert len([r for r in caplog.records if "ROM build time" in r.getMessage()]) == 1
        # NITZ/NTP answered: an ordinary (forward) drift is used again.
        clock.advance(cp.TIME_CHECK_S)
        fake.date = str(int(clock.wall()) + 3 * 3600)
        phone.tick()
        assert len(_set_time_calls(fake)) == 1

    def test_build_time_is_reread_after_the_phone_reappears(self, env):
        phone, fake, clock, bus, published, notes = connect_fully(
            env, settings={"time_sync": True})
        fake.date = str(int(WALL0) + 18000)
        fake.build = ""                                     # property missing
        phone.tick()
        assert fake.count(BUILD) == 1 and _set_time_calls(fake) == []
        fake.devices = devices_text()
        clock.advance(30)
        phone.tick()
        fake.devices = devices_text(dev_line())
        fake.build = str(BUILD0)
        clock.advance(30)
        phone.tick()
        assert fake.count(BUILD) == 2 and len(_set_time_calls(fake)) == 1

    def test_unreadable_build_time_is_not_trusted(self, env):
        phone, fake, clock, bus, published, notes = connect_fully(
            env, settings={"time_sync": True})
        fake.date = str(int(WALL0) + 18000)
        fake.build_rc = 1
        phone.tick()
        assert _set_time_calls(fake) == []

    def test_unconfirmed_step_back_is_refused(self, env):
        phone, fake, clock, bus, published, notes = connect_fully(
            env, settings={"time_sync": True})
        fake.date = str(int(clock.wall()) - 2 * 3600)       # phone 2 h behind us
        phone.tick()
        assert fake.ran(DATE) and _set_time_calls(fake) == []
        # 10 min later the phone has corrected itself (NITZ): drift gone.
        clock.advance(cp.TIME_CHECK_S)
        fake.date = str(int(clock.wall()) + 2)
        phone.tick()
        assert _set_time_calls(fake) == []
        # A different big drift each time is never "confirmed" either.
        for behind in (5 * 3600, 3 * 3600, 7 * 3600):
            clock.advance(cp.TIME_CHECK_S)
            fake.date = str(int(clock.wall()) - behind)
            phone.tick()
        assert _set_time_calls(fake) == []

    def test_confirmed_step_back_is_applied(self, env):
        phone, fake, clock, bus, published, notes = connect_fully(
            env, settings={"time_sync": True})
        fake.date = str(int(clock.wall()) - 2 * 3600)
        phone.tick()
        assert _set_time_calls(fake) == []
        clock.advance(cp.TIME_CHECK_S)
        fake.date = str(int(clock.wall()) - 2 * 3600 + 3)   # same drift (±5 s)
        phone.tick()
        assert _set_time_calls(fake) == [["timedatectl", "set-time", f"@{fake.date}"]]
        assert phone.state["time_synced_at"] is not None

    def test_pending_step_back_is_dropped_when_the_phone_goes(self, env):
        phone, fake, clock, bus, published, notes = connect_fully(
            env, settings={"time_sync": True})
        fake.date = str(int(clock.wall()) - 2 * 3600)
        phone.tick()
        fake.devices = devices_text()
        clock.advance(30)
        phone.tick()
        fake.devices = devices_text(dev_line())             # back (rebooted?)
        clock.advance(30)
        fake.date = str(int(clock.wall()) - 2 * 3600)
        phone.tick()
        assert fake.count(DATE) == 2 and _set_time_calls(fake) == []

    def test_small_step_back_needs_no_confirmation(self, env):
        phone, fake, clock, bus, published, notes = connect_fully(
            env, settings={"time_sync": True})
        fake.date = str(int(clock.wall()) - 600)            # 10 min fast here
        phone.tick()
        assert len(_set_time_calls(fake)) == 1

    def test_set_time_failure_warns_once(self, env, caplog):
        phone, fake, clock, bus, published, notes = connect_fully(
            env, settings={"time_sync": True})
        fake.date = str(int(WALL0) + 18000)
        fake.set_time_rc = 1
        with caplog.at_level("WARNING", logger="bcm.network.car_phone"):
            phone.tick()
            clock.advance(cp.TIME_CHECK_S)
            phone.tick()
        assert len(_set_time_calls(fake)) == 2
        assert len([r for r in caplog.records if "clock from the phone failed" in
                    r.getMessage()]) == 1
        assert phone.state["time_synced_at"] is None

    def test_off_never_asks(self, env):
        phone, fake, clock, bus, published, notes = connect_fully(env)
        phone.tick()
        assert not fake.ran(DATE)


# ── hotspot status (plan D2) ──────────────────────────────────────────────

class TestHotspot:
    def test_only_with_its_module_toggle(self, env):
        phone, fake, clock, bus, published, notes = connect_fully(env)
        phone.tick()
        assert not fake.ran(TETH)
        assert phone.state["hotspot_active"] is None

    def test_active_and_clients(self, env):
        phone, fake, clock, bus, published, notes = connect_fully(env, hotspot=True)
        phone.tick()
        assert phone.state["hotspot_active"] is True and phone.state["hotspot_clients"] == 2
        fake.tethering = TETHERING_OFF
        clock.advance(60)
        phone.tick()
        assert phone.state["hotspot_active"] is False
        assert phone.state["hotspot_clients"] is None

    def test_unknown_format_and_old_android_fallback(self, env):
        phone, fake, clock, bus, published, notes = connect_fully(env, hotspot=True)
        fake.tethering = "Can't find service: tethering\n"
        fake.connectivity_tethering = "garbage\n"
        phone.tick()
        assert phone.state["hotspot_active"] is None
        assert fake.ran(TETH) and fake.ran(TETH_OLD)
        fake.connectivity_tethering = TETHERING_OFF
        clock.advance(60)
        phone.tick()
        assert phone.state["hotspot_active"] is False
        clock.advance(60)
        n = fake.count(TETH)
        phone.tick()
        assert fake.count(TETH) == n                      # the working one is remembered

    def test_hotspot_toggle_must_be_true(self, env):
        phone, fake, clock, bus, published, notes = env(
            config_extra={"modules": {"car_phone_hotspot": "yes"}})
        assert phone._hotspot is False


# ── publication, scheduling, lifecycle ────────────────────────────────────

class TestPublication:
    def test_only_on_change_and_since(self, env):
        phone, fake, clock, bus, published, notes = connect_fully(env)
        fake.link = "activated"
        phone.tick()
        first = len(published)
        since = phone.state["since"]
        for _ in range(3):
            clock.advance(30)
            phone.tick()
        assert len(published) == first
        assert phone.state["since"] == since
        fake.battery = battery(level=77)
        clock.advance(30)
        phone.tick()
        assert len(published) == first + 1                 # battery changed
        assert phone.state["since"] == since               # same state

    def test_payload_keys_and_types(self, env):
        phone, fake, clock, bus, published, notes = connect_fully(env)
        fake.link = "activated"
        phone.tick()
        state = published[-1]
        assert set(state) == {
            "state", "adb", "serial", "iface", "ip", "prefix", "gateway", "gps_forward",
            "gps_port", "battery_pct", "temp_c", "charging", "full", "plugged", "health",
            "overridden", "hotspot_active", "hotspot_clients", "heat", "time_synced_at",
            "error", "hint", "since"}
        assert state["serial"] == "1a…4d" and SER not in str(state)
        assert state["state"] in cp.STATES and state["hint"] in cp.HINTS
        assert state["adb"] in cp.ADB_STATES

    def test_errors_are_cleaned_and_cut(self, env):
        phone, fake, clock, bus, published, notes = connect_fully(env)
        fake.functions = "rndis,adb"
        fake.up_results = [(4, "Error:\x1b[31m " + "x" * 500 + "\n")]
        phone.tick()
        clock.advance(10)
        phone.tick()
        err = phone.state["error"]
        assert len(err) <= 200 and "\x1b" not in err and "\n" not in err

    def test_next_wait(self, env):
        phone, fake, clock, bus, published, notes = connect_fully(env)
        fake.link = "activated"
        phone.tick()
        assert phone.next_wait() == 30
        phone2, fake2, clock2, *_ = connect_fully(env, settings={"battery_sec": 15})
        fake2.link = "activated"
        phone2.tick()
        assert phone2.next_wait() == 15


class TestLifecycle:
    def test_disabled_object_never_calls_the_runner(self, env):
        phone, fake, clock, bus, published, notes = env()
        phone.stop()
        assert phone.tick() == "disabled"
        assert fake.calls == []
        assert published[-1]["state"] == "disabled"

    def test_start_runs_a_pass_in_its_thread_and_stop_does_not_wait(self, tmp_path):
        fake = FakePhone()
        fake.adb_missing = True
        fake.adb_socket = str(tmp_path / "adb" / cp.ADB_SOCKET_NAME)
        bus = EventBus()
        states = []
        bus.subscribe(cp.TOPIC, lambda t, v, ts: states.append(v["state"]))
        phone = CarPhone({"network": {"car_phone": {"check_sec": 5}}}, bus, runner=fake,
                         usb_root="/nonexistent-usb-root", marker_path="/nonexistent-marker",
                         adb_socket_dir=str(tmp_path / "adb"))
        t0 = time.monotonic()
        phone.start()
        assert time.monotonic() - t0 < 1.0               # no I/O in start()
        deadline = time.monotonic() + 5
        while "no_adb" not in states and time.monotonic() < deadline:
            time.sleep(0.01)
        assert "no_adb" in states
        phone.stop()
        phone._thread.join(timeout=5)
        assert not phone._thread.is_alive()
        assert states[-1] == "disabled"
        assert fake.unexpected == []

    def test_shutdown_event_stops_it(self, tmp_path):
        bus = EventBus()
        fake = FakePhone()
        fake.adb_missing = True
        fake.adb_socket = str(tmp_path / "adb" / cp.ADB_SOCKET_NAME)
        phone = CarPhone({}, bus, runner=fake, usb_root="/nonexistent-usb-root",
                         marker_path="/nonexistent-marker", adb_socket_dir=str(tmp_path / "adb"))
        phone.start()
        bus.publish("power.shutting_down", True)
        phone._thread.join(timeout=5)
        assert not phone._thread.is_alive()

    def test_retry_callback_does_no_io(self, env):
        phone, fake, clock, bus, published, notes = env()
        bus.publish(cp.RETRY_TOPIC, True)
        assert fake.calls == []


class TestRegistration:
    def test_catalog_entry(self):
        info = modules_catalog.MODULES["car_phone"]
        assert info["entry"] == ("src.network.car_phone", "start_car_phone")
        assert info["default"] is False and not info.get("planned")
        assert info["group"] == "telefon_w_aucie"
        hot = modules_catalog.MODULES["car_phone_hotspot"]
        assert hot["requires"] == ("car_phone",) and not hot.get("planned")
        assert hot["default"] is False
        names = list(modules_catalog.MODULES)
        assert names.index("car_phone") == names.index("phone_tether") + 1

    @pytest.mark.parametrize("cfg_name", ["bcm_config.yaml", "bcm_config_test.yaml"])
    def test_off_in_both_configs(self, cfg_name):
        cfg = BCMConfig(config_path=str(REPO / "config" / cfg_name), platform_override="x86",
                        local_path=None, env={})
        assert modules_catalog.is_enabled(cfg, "car_phone") is False
        assert modules_catalog.is_enabled(cfg, "car_phone_hotspot") is False
        states = main.plan_modules(cfg)
        assert "car_phone" not in [n for n, _ in main.registry_to_start(states)]

    def test_entry_point_is_never_called_when_off(self, monkeypatch):
        called = []
        monkeypatch.setitem(main.MODULE_REGISTRY["car_phone"], "start",
                            lambda **kw: called.append(kw))
        cfg = BCMConfig(config_path=str(REPO / "config" / "bcm_config.yaml"),
                        platform_override="x86", local_path=None, env={})
        main.start_modules(main.registry_to_start(main.plan_modules(cfg)), cfg, EventBus(), None)
        assert called == []

    def test_switched_on_it_starts(self, monkeypatch):
        called = []
        monkeypatch.setitem(main.MODULE_REGISTRY["car_phone"], "start",
                            lambda **kw: called.append(kw))
        cfg = BCMConfig(config_path=str(REPO / "config" / "bcm_config.yaml"),
                        platform_override="x86", local_path=None, env={})
        cfg.set("modules.car_phone", True)
        to_start = main.registry_to_start(main.plan_modules(cfg))
        assert "car_phone" in [n for n, _ in to_start]
        main.start_modules([(n, i) for n, i in to_start if n == "car_phone"], cfg,
                           EventBus(), None)
        assert len(called) == 1

    def test_test_config_block_is_read(self):
        cfg = BCMConfig(config_path=str(REPO / "config" / "bcm_config_test.yaml"),
                        platform_override="x86", local_path=None, env={})
        phone = CarPhone(cfg, EventBus(), runner=FakePhone())
        assert phone.con_name == CON and phone._metric == 650
        assert phone._tether_method == "svc_usb" and phone._usb_function == "rndis"
        assert phone._check_sec == 30 and phone._retry_sec == 15
        assert phone._max_retry_sec == 300 and phone._settle_sec == 10
        assert phone.gps_local_port == 50000 and phone._gps_remote == 50000
        assert phone._battery_sec == 60 and phone._warn_c == 45 and phone._crit_c == 50
        assert phone._time_sync is True and phone._drift_s == 30
        assert phone._hotspot is False

    def test_code_defaults(self):
        phone = CarPhone({}, EventBus(), runner=FakePhone())
        assert phone.con_name == CON and phone._metric == 650
        assert phone.gps_local_port == 50000 and phone._gps_forward is True
        assert phone._time_sync is True and phone._trigger_timesync is True
