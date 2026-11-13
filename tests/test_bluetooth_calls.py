"""oFono call tracking (src/multimedia/bluetooth.py).

The mapping and the tracker are pure; the D-Bus side is only exercised with
a fake ``dbus`` module (dbus-python is not installed in the test venv, which
is also how the "no D-Bus" degradation is checked).
"""

import logging
import sys
import threading
import types

import pytest

from src.core.event_bus import EventBus
from src.multimedia import bluetooth as bt
from src.multimedia.bluetooth import (
    BluetoothManager,
    OfonoCallTracker,
    aggregate_calls,
    map_ofono_call_state,
    sanitize_call_text,
)

MODEM = "/hfp/org/bluez/hci0/dev_11_22_33_44_55_66"
CALL1 = MODEM + "/voicecall01"
CALL2 = MODEM + "/voicecall02"


class _Cfg(dict):
    def get(self, key, default=None):
        return super().get(key, default)


def _recorder(bus):
    events = []
    for topic in ("bt.call_state", "bt.call_info", "bt.call_incoming", "bt.call_ended",
                  "bt.hfp_active", "audio.phone_call"):
        bus.subscribe(topic, lambda t, v, ts: events.append((t, v)))
    return events


class TestMapping:
    @pytest.mark.parametrize("state, expected", [
        ("incoming", "incoming"), ("waiting", "incoming"),
        ("dialing", "ringing"), ("alerting", "ringing"),
        ("active", "active"), ("held", "active"),
        ("disconnected", None), ("", None), (None, None), (5, None), ("ACTIVE", "active"),
    ])
    def test_state_map(self, state, expected):
        assert map_ofono_call_state(state) == expected

    def test_no_calls_is_idle(self):
        assert aggregate_calls({}) == ("idle", {})
        assert aggregate_calls({CALL1: {"State": "disconnected"}}) == ("idle", {})

    def test_waiting_call_wins_over_active(self):
        state, info = aggregate_calls({
            CALL1: {"State": "active", "LineIdentification": "+48111", "Name": "A"},
            CALL2: {"State": "waiting", "LineIdentification": "+48222", "Name": "B"},
        })
        assert state == "incoming"
        assert info == {"number": "+48222", "name": "B"}

    def test_outgoing_wins_over_held(self):
        state, info = aggregate_calls({
            CALL1: {"State": "held", "LineIdentification": "+48111"},
            CALL2: {"State": "alerting", "LineIdentification": "+48222"},
        })
        assert (state, info["number"]) == ("ringing", "+48222")


class TestSanitize:
    def test_control_and_bidi_characters_removed(self):
        assert sanitize_call_text("Ala\x00\x1b[31m‮Ma\nKota", 64) == "Ala [31m Ma Kota"

    def test_length_cap(self):
        assert len(sanitize_call_text("9" * 500, 32)) == 32

    @pytest.mark.parametrize("value", [None, b"\xff\xfe", bytearray(b"x")])
    def test_non_text(self, value):
        assert sanitize_call_text(value, 32) == ""

    def test_html_is_kept_as_text_the_ui_escapes_it(self):
        # Not stripped here (a name may legitimately contain "<"), the UI
        # renders it escaped; only its length is bounded.
        assert sanitize_call_text("<img src=x onerror=alert(1)>", 64).startswith("<img")

    def test_info_is_sanitized(self):
        _, info = aggregate_calls({CALL1: {"State": "incoming",
                                           "LineIdentification": "+48\x07" + "1" * 100,
                                           "Name": "‮evil"}})
        assert len(info["number"]) == 32 and "\x07" not in info["number"]
        assert info["name"] == "evil"


class TestTracker:
    def setup_method(self):
        self.bus = EventBus()
        self.events = _recorder(self.bus)
        self.tracker = OfonoCallTracker(self.bus)

    def test_incoming_answered_hung_up(self):
        self.tracker.call_added(CALL1, {"State": "incoming", "LineIdentification": "+48600",
                                        "Name": "Jan"})
        assert ("bt.call_state", "incoming") in self.events
        assert ("bt.call_incoming", True) in self.events
        assert ("bt.call_info", {"number": "+48600", "name": "Jan"}) in self.events
        self.events.clear()

        self.tracker.call_property_changed(CALL1, "State", "active")
        assert self.events == [("bt.call_info", {"number": "+48600", "name": "Jan"}),
                               ("bt.call_state", "active")]
        self.events.clear()

        self.tracker.call_removed(CALL1)
        assert ("bt.call_state", "idle") in self.events
        assert ("bt.call_info", {}) in self.events
        assert ("bt.call_ended", True) in self.events
        assert self.tracker.state == "idle"

    def test_only_last_removal_ends_the_call(self):
        self.tracker.call_added(CALL1, {"State": "active", "LineIdentification": "1"})
        self.tracker.call_added(CALL2, {"State": "waiting", "LineIdentification": "2"})
        assert self.tracker.state == "incoming"
        self.events.clear()
        self.tracker.call_removed(CALL2)
        assert self.tracker.state == "active"
        assert ("bt.call_ended", True) not in self.events
        self.tracker.call_removed(CALL1)
        assert ("bt.call_ended", True) in self.events

    def test_call_started_on_the_phone_is_ringing_not_incoming(self):
        self.tracker.call_added(CALL1, {"State": "dialing", "LineIdentification": "112"})
        assert ("bt.call_state", "ringing") in self.events
        assert ("bt.call_incoming", True) not in self.events
        # hfp_active / phone_call are derived by BluetoothManager (one owner)
        assert not any(t in ("bt.hfp_active", "audio.phone_call") for t, _ in self.events)

    def test_name_arriving_later_republishes_info_only(self):
        self.tracker.call_added(CALL1, {"State": "incoming", "LineIdentification": "+48600"})
        self.events.clear()
        self.tracker.call_property_changed(CALL1, "Name", "Jan")
        assert self.events == [("bt.call_info", {"number": "+48600", "name": "Jan"})]

    def test_irrelevant_or_unknown_changes_are_ignored(self):
        self.tracker.call_property_changed(CALL1, "State", "active")   # never added
        self.tracker.call_added(CALL1, {"State": "active"})
        self.events.clear()
        self.tracker.call_property_changed(CALL1, "Multiparty", True)
        assert self.events == []

    def test_modem_removed_ends_its_calls(self):
        self.tracker.modem_added(MODEM, {"Interfaces": [bt.OFONO_VCM_IFACE]})
        assert self.tracker.has_voice_modem()
        self.tracker.call_added(CALL1, {"State": "active"})
        self.tracker.modem_removed(MODEM)
        assert self.tracker.state == "idle"
        assert ("bt.call_ended", True) in self.events
        assert not self.tracker.has_voice_modem()

    def test_voice_manager_disappearing_ends_calls(self):
        self.tracker.modem_added(MODEM, {"Interfaces": [bt.OFONO_VCM_IFACE]})
        self.tracker.call_added(CALL1, {"State": "active"})
        self.tracker.modem_property_changed(MODEM, "Interfaces", ["org.ofono.Handsfree"])
        assert self.tracker.state == "idle"

    def test_seed_and_reset(self):
        self.tracker.seed([(MODEM, {"Interfaces": [bt.OFONO_VCM_IFACE]})],
                          {MODEM: [(CALL1, {"State": "held", "LineIdentification": "5"})]})
        assert self.tracker.state == "active"
        self.tracker.reset()
        assert self.tracker.state == "idle"
        assert ("bt.call_ended", True) in self.events

    def test_reconcile_undoes_a_wrong_optimistic_publish(self):
        self.tracker.live = True
        self.tracker.call_added(CALL1, {"State": "active", "LineIdentification": "7"})
        self.bus.publish("bt.call_state", "idle")      # hangup tapped, oFono refused
        self.events.clear()
        self.tracker.reconcile()
        assert self.events[-1] == ("bt.call_state", "active")
        self.events.clear()
        self.tracker.reconcile()                       # agrees now: silent
        assert self.events == []


    def test_reconcile_is_a_noop_when_not_live(self):
        # monitor thread failed (no GLib / no system bus): the tracker says
        # "idle" for a call oFono's blocking Dial really started
        self.bus.publish("bt.call_state", "ringing")
        self.events.clear()
        self.tracker.reconcile()
        assert self.events == []


class TestManagerIntegration:
    def test_incoming_and_ended_drive_ducking(self):
        bus = EventBus()
        mgr = BluetoothManager(_Cfg(), bus)
        phone_call = []
        bus.subscribe("audio.phone_call", lambda t, v, ts: phone_call.append(v))
        tracker = OfonoCallTracker(bus)
        tracker.call_added(CALL1, {"State": "incoming"})
        assert mgr.hfp_active is True
        tracker.call_removed(CALL1)
        assert phone_call == [True, False]              # no duplicate toggles
        assert mgr.hfp_active is False

    def test_call_started_on_the_phone_sets_hfp_active(self):
        bus = EventBus()
        mgr = BluetoothManager(_Cfg(), bus)
        events = _recorder(bus)
        tracker = OfonoCallTracker(bus)
        tracker.call_added(CALL1, {"State": "dialing", "LineIdentification": "112"})
        assert mgr.hfp_active is True                   # web_viewer reads this
        assert ("bt.hfp_active", True) in events and ("audio.phone_call", True) in events
        tracker.call_property_changed(CALL1, "State", "active")
        assert [v for t, v in events if t == "bt.hfp_active"] == [True]
        tracker.call_removed(CALL1)
        assert mgr.hfp_active is False
        assert [v for t, v in events if t == "audio.phone_call"] == [True, False]

    def test_reconciled_idle_after_failed_answer_unducks(self):
        bus = EventBus()
        mgr = BluetoothManager(_Cfg(), bus)
        mgr._init_hfp_commands()
        tracker = OfonoCallTracker(bus)
        tracker.live = True
        bus.publish("bt.cmd.answer", True)              # provisional "active"
        assert bus.get_last("audio.phone_call")[0] is True
        tracker.reconcile()                             # oFono: no call at all
        assert bus.get_last("bt.call_state")[0] == "idle"
        assert bus.get_last("audio.phone_call")[0] is False
        assert mgr.hfp_active is False

    def test_reconcile_scheduled_only_with_a_live_monitor(self, monkeypatch):
        mgr = BluetoothManager(_Cfg(), EventBus())
        timers = []

        class _Timer:
            def __init__(self, delay, fn):
                timers.append(fn)
                self.daemon = False

            def start(self):
                pass

        monkeypatch.setattr(bt.threading, "Timer", _Timer)
        mgr._call_tracker = OfonoCallTracker(mgr._event_bus)
        mgr._schedule_call_reconcile()
        assert timers == []
        mgr._call_tracker.live = True
        mgr._schedule_call_reconcile()
        assert len(timers) == 1

    @pytest.mark.parametrize("raw, expected", [
        ("+48 600-123-456", "+48600123456"),
        ("(22) 123.45.67", "221234567"),
        ("*100#", "*100#"),
        (112, "112"),
        ("", ""), ("   ", ""), (None, ""), (True, ""), ({"n": 1}, ""),
        ("600\nINFO forged log line", ""),
        ("abc", ""), ("1" * 33, ""), ("1 " * 200, ""),
    ])
    def test_normalize_dial_number(self, raw, expected):
        assert bt.normalize_dial_number(raw) == expected

    def test_dial_refuses_garbage_and_publishes_clean_number(self):
        bus = EventBus()
        BluetoothManager(_Cfg(), bus)._init_hfp_commands()
        events = _recorder(bus)
        bus.publish("bt.cmd.dial", "600\r\nfake")
        assert events == []
        bus.publish("bt.cmd.dial", "+48 600 123 456")
        assert ("bt.call_info", {"number": "+48600123456", "name": ""}) in events
        assert ("bt.call_state", "ringing") in events

    def test_monitor_absent_without_dbus(self):
        assert bt.HAS_DBUS is False            # the test venv has no dbus-python
        mgr = BluetoothManager(_Cfg(), EventBus())
        assert mgr._start_ofono_monitor() is False
        assert mgr._call_tracker is None
        mgr._schedule_call_reconcile()         # no tracker: no timer, no error

    def test_monitor_survives_missing_glib(self, monkeypatch, caplog):
        # HAS_DBUS claims yes, but the imports inside the thread fail.
        monkeypatch.setattr(bt, "HAS_DBUS", True)
        monkeypatch.setitem(sys.modules, "dbus", None)
        mgr = BluetoothManager(_Cfg(), EventBus())
        with caplog.at_level(logging.WARNING, logger="bcm.multimedia.bluetooth"):
            assert mgr._start_ofono_monitor() is True
            for t in threading.enumerate():
                if t.name == "bt-ofono-monitor":
                    t.join(2.0)
        assert any("oFono call monitor unavailable" in r.message for r in caplog.records)
        assert mgr._call_tracker is not None
        assert mgr._call_tracker.live is False          # never fed: no reconcile


class TestMonitorWiring:
    def test_receivers_only_accept_ofono_and_live_follows_the_loop(self, monkeypatch):
        mgr = BluetoothManager(_Cfg(), EventBus())     # built before D-Bus is "there"
        receivers, live_in_loop = [], []

        class Bus:
            def add_signal_receiver(self, handler, **kw):
                receivers.append(kw)

            def watch_name_owner(self, name, callback):
                assert name == bt.OFONO_SERVICE
                callback("")                             # ofonod not running

        class Loop:
            def run(self):
                live_in_loop.append(mgr._call_tracker.live)

        dbus_mod = types.ModuleType("dbus")
        dbus_mod.SystemBus = Bus
        mainloop = types.ModuleType("dbus.mainloop")
        glib = types.ModuleType("dbus.mainloop.glib")
        glib.DBusGMainLoop = lambda set_as_default=False: None
        dbus_mod.mainloop, mainloop.glib = mainloop, glib
        gi = types.ModuleType("gi")
        repo = types.ModuleType("gi.repository")
        repo.GLib = types.SimpleNamespace(MainLoop=Loop)
        gi.repository = repo
        for name, mod in (("dbus", dbus_mod), ("dbus.mainloop", mainloop),
                          ("dbus.mainloop.glib", glib), ("gi", gi), ("gi.repository", repo)):
            monkeypatch.setitem(sys.modules, name, mod)
        monkeypatch.setattr(bt, "HAS_DBUS", True)

        assert mgr._start_ofono_monitor() is True
        for t in threading.enumerate():
            if t.name == "bt-ofono-monitor":
                t.join(2.0)
        # every receiver is bound to org.ofono's owner: a local process
        # cannot fake CallAdded / PropertyChanged
        assert len(receivers) == 7                       # + VoiceCallManager.PropertyChanged
        assert all(kw.get("bus_name") == bt.OFONO_SERVICE for kw in receivers)
        assert live_in_loop == [True]
        assert mgr._call_tracker.live is False            # loop ended


class _FakeDBusException(Exception):
    def get_dbus_name(self):
        return "org.freedesktop.DBus.Error.ServiceUnknown"


def _fake_dbus(calls, modems, call_list, fail=False):
    """A dbus module stand-in that answers oFono's Manager/VoiceCallManager."""
    mod = types.ModuleType("dbus")
    mod.DBusException = _FakeDBusException

    class Bus:
        def get_object(self, service, path):
            if fail:
                raise _FakeDBusException("no ofono")
            return path

    class Interface:
        def __init__(self, obj, iface):
            self.obj, self.iface = obj, iface

        def __getattr__(self, method):
            def call(*args, **kwargs):
                calls.append((self.iface, self.obj, method, args))
                if method == "GetModems":
                    return modems
                if method == "GetCalls":
                    return call_list
                return None
            return call

    mod.SystemBus = Bus
    mod.Interface = Interface
    return mod


class TestHfpCommands:
    def _mgr(self):
        return BluetoothManager(_Cfg(), EventBus())

    def test_answer_waiting_call_uses_hold_and_answer(self, monkeypatch):
        calls = []
        monkeypatch.setitem(sys.modules, "dbus", _fake_dbus(
            calls, [(MODEM, {"Interfaces": [bt.OFONO_VCM_IFACE]})],
            [(CALL1, {"State": "active"}), (CALL2, {"State": "waiting"})]))
        self._mgr()._hfp_answer_dbus()
        assert (bt.OFONO_VCM_IFACE, MODEM, "HoldAndAnswer", ()) in calls

    def test_answer_incoming_call(self, monkeypatch):
        calls = []
        monkeypatch.setitem(sys.modules, "dbus", _fake_dbus(
            calls, [(MODEM, {"Interfaces": [bt.OFONO_VCM_IFACE]})],
            [(CALL1, {"State": "incoming"})]))
        self._mgr()._hfp_answer_dbus()
        assert ("org.ofono.VoiceCall", CALL1, "Answer", ()) in calls

    def test_errors_are_warnings_once(self, monkeypatch, caplog):
        monkeypatch.setitem(sys.modules, "dbus", _fake_dbus([], [], [], fail=True))
        mgr = self._mgr()
        with caplog.at_level(logging.WARNING, logger="bcm.multimedia.bluetooth"):
            mgr._hfp_dial_dbus("112")
            mgr._hfp_hangup_dbus()
        hits = [r for r in caplog.records if "rozmowy nie trafią do headunitu" in r.message]
        assert len(hits) == 1

    def test_no_voice_modem_warns_once(self, monkeypatch, caplog):
        monkeypatch.setitem(sys.modules, "dbus", _fake_dbus(
            [], [(MODEM, {"Interfaces": ["org.ofono.Handsfree"]})], []))
        mgr = self._mgr()
        with caplog.at_level(logging.WARNING, logger="bcm.multimedia.bluetooth"):
            mgr._hfp_hangup_dbus()
            mgr._hfp_hangup_dbus()
        assert sum("VoiceCallManager" in r.message for r in caplog.records) == 1


# ── Emergency numbers (POST /api/phone/dial from the network, 0f) ────────

class TestEmergencyNumbers:
    @pytest.mark.parametrize("number", [
        "112", "+112", "+48 112", "+48112", "0048112", "*31#112", "#31#112", "*31#+48112",
        "112#", "911", "+1 911", "997", "998", "999", "984", "985", "986", "987",
        "1 1 2", "112\n",                      # normalised exactly as the dial is
        # caller-ID codes with an info field (Android's GsmMmiCode dials the rest)
        "*31*#112", "*31*1#112", "#31*#112", "*31*0#112", "*31*#*31#112", "*#31#+48112",
        "**61*600123456**20#112",
    ])
    def test_builtin_and_its_disguises(self, number):
        assert bt.is_emergency_number(number) is True

    @pytest.mark.parametrize("number", [
        "600123456", "+48600123112", "1120", "11", "9112345", "*100#", "*31#", "", None,
        "abc", ["112"], "**21*0700123456#", "*31*#600123456", "*#06#",
    ])
    def test_not_emergency(self, number):
        assert bt.is_emergency_number(number) is False

    def test_extra_list_from_ofono(self):
        assert bt.is_emergency_number("118") is False
        assert bt.is_emergency_number("118", frozenset({"118", "08"})) is True
        assert bt.is_emergency_number("+81 118", {"118"}) is True

    @pytest.mark.parametrize("value, expected", [
        (["112", "08", " 911 "], {"112", "08", "911"}),
        (["1", "123456789", "11a", None, 112, "<b>"], set()),
        ("112", set()), (None, set()), ({"112": 1}, set()),
        ([str(100 + i) for i in range(100)], 32),
    ])
    def test_clean_emergency_numbers(self, value, expected):
        got = bt.clean_emergency_numbers(value)
        assert (len(got) == expected) if isinstance(expected, int) else (got == expected)

    def test_tracker_keeps_them_per_modem(self):
        tracker = OfonoCallTracker(EventBus())
        tracker.set_emergency_numbers(MODEM, ["112", "08"])
        tracker.vcm_property_changed("/hfp/other", "EmergencyNumbers", ["118"])
        tracker.vcm_property_changed(MODEM, "Calls", ["x"])            # ignored
        assert tracker.emergency_numbers() == {"112", "08", "118"}
        tracker.modem_removed("/hfp/other")
        assert tracker.emergency_numbers() == {"112", "08"}
        tracker.seed([], {})
        assert tracker.emergency_numbers() == frozenset()

    def test_manager_without_monitor_knows_none(self):
        mgr = BluetoothManager(_Cfg(), EventBus())
        assert mgr.emergency_numbers() == frozenset()
        mgr._call_tracker = OfonoCallTracker(mgr._event_bus)
        mgr._call_tracker.set_emergency_numbers(MODEM, ["08"])
        assert mgr.emergency_numbers() == {"08"}

    def test_monitor_seed_reads_emergency_numbers(self, monkeypatch):
        mgr = BluetoothManager(_Cfg(), EventBus())
        calls = []
        dbus_mod = _fake_dbus(calls, [(MODEM, {"Interfaces": [bt.OFONO_VCM_IFACE]})], [])
        base_interface = dbus_mod.Interface

        class Interface(base_interface):
            def __getattr__(self, method):
                if method == "GetProperties":
                    return lambda **kw: {"EmergencyNumbers": ["112", "08"]}
                return base_interface.__getattr__(self, method)

        dbus_mod.Interface = Interface

        class Bus(dbus_mod.SystemBus):
            def add_signal_receiver(self, handler, **kw):
                pass

            def watch_name_owner(self, name, callback):
                callback(":1.42")                        # ofonod is running: seed

        dbus_mod.SystemBus = Bus
        mainloop = types.ModuleType("dbus.mainloop")
        glib = types.ModuleType("dbus.mainloop.glib")
        glib.DBusGMainLoop = lambda set_as_default=False: None
        dbus_mod.mainloop, mainloop.glib = mainloop, glib
        gi = types.ModuleType("gi")
        repo = types.ModuleType("gi.repository")
        repo.GLib = types.SimpleNamespace(MainLoop=lambda: types.SimpleNamespace(run=lambda: None))
        gi.repository = repo
        for name, mod in (("dbus", dbus_mod), ("dbus.mainloop", mainloop),
                          ("dbus.mainloop.glib", glib), ("gi", gi), ("gi.repository", repo)):
            monkeypatch.setitem(sys.modules, name, mod)
        monkeypatch.setattr(bt, "HAS_DBUS", True)
        assert mgr._start_ofono_monitor() is True
        for t in threading.enumerate():
            if t.name == "bt-ofono-monitor":
                t.join(2.0)
        assert mgr.emergency_numbers() == {"112", "08"}


# ── Dialling off the event-bus thread + bt.dial_result (0f) ──────────────

class _DialDBus:
    """A dbus stand-in for Dial: GetModems/Dial can block or fail, and every
    call records the thread it ran on."""

    def __init__(self, modems=None, dial_error=None, block=None, modems_error=None,
                 hangup_errors=()):
        self.modems = [(MODEM, {"Interfaces": [bt.OFONO_VCM_IFACE]})] if modems is None else modems
        self.dial_error = dial_error
        self.modems_error = modems_error
        self.hangup_errors = list(hangup_errors)     # raised by HangupAll, in order
        self.block = block
        self.calls = []
        fake = self

        mod = types.ModuleType("dbus")
        mod.DBusException = _NamedDBusException

        class Bus:
            def get_object(self, service, path):
                return path

        class Interface:
            def __init__(self, obj, iface):
                self.obj, self.iface = obj, iface

            def __getattr__(self, method):
                def call(*args, **kwargs):
                    fake.calls.append((method, args, threading.current_thread().name, kwargs))
                    if fake.block is not None:
                        assert fake.block.wait(5.0)
                    if method == "GetModems":
                        if fake.modems_error:
                            raise _NamedDBusException(fake.modems_error)
                        return fake.modems
                    if method == "Dial" and fake.dial_error:
                        raise _NamedDBusException(fake.dial_error)
                    if method == "HangupAll" and fake.hangup_errors:
                        raise _NamedDBusException(fake.hangup_errors.pop(0))
                    if method == "GetCalls":
                        return []
                    return None
                return call

        mod.SystemBus = Bus
        mod.Interface = Interface
        self.module = mod


class _NamedDBusException(Exception):
    def __init__(self, name="org.ofono.Error.Failed"):
        super().__init__(name)
        self._name = name

    def get_dbus_name(self):
        return self._name


def _dial_env(monkeypatch, fake=None, has_dbus=True):
    bus = EventBus()
    mgr = BluetoothManager(_Cfg(), bus)
    mgr._init_hfp_commands()
    if fake is not None:
        monkeypatch.setitem(sys.modules, "dbus", fake.module)
    monkeypatch.setattr(bt, "HAS_DBUS", has_dbus)
    results, notes = [], []
    bus.subscribe("bt.dial_result", lambda t, v, ts: results.append(v))
    bus.subscribe("system.notifications", lambda t, v, ts: notes.append(v))
    return bus, mgr, results, notes


def _join_calls(mgr, timeout=5.0):
    """Wait until the bt-call worker has run everything queued so far."""
    waiter = threading.Thread(target=mgr._call_queue.join, daemon=True)
    waiter.start()
    waiter.join(timeout)
    assert not waiter.is_alive(), "bt-call worker stuck"


class TestDialWorker:
    def test_the_bus_callback_returns_before_any_dbus_call(self, monkeypatch):
        gate = threading.Event()
        fake = _DialDBus(block=gate)
        bus, mgr, results, notes = _dial_env(monkeypatch, fake)
        events = _recorder(bus)
        bus.publish("bt.cmd.dial", "+48 600 123 456")   # sync bus: runs the callback here
        # Returned while GetModems is still blocked: no D-Bus on this thread.
        assert ("bt.call_state", "ringing") in events
        assert results == []
        gate.set()
        _join_calls(mgr)
        assert [c[0] for c in fake.calls] == ["GetModems", "Dial"]
        assert {c[2] for c in fake.calls} == {"bt-call"}
        assert fake.calls[1][1][0] == "+48600123456"
        assert results[-1]["ok"] is True and results[-1]["path"] == "hfp"
        assert results[-1]["error"] is None
        assert mgr._dial_busy is False

    def test_second_dial_while_one_is_in_flight_is_busy(self, monkeypatch):
        gate = threading.Event()
        fake = _DialDBus(block=gate)
        bus, mgr, results, notes = _dial_env(monkeypatch, fake)
        bus.publish("bt.cmd.dial", "600123456")
        events = _recorder(bus)
        bus.publish("bt.cmd.dial", "112")
        assert results == [{"ok": False, "path": "hfp", "error": "busy",
                            "ts": results[0]["ts"]}]
        assert events == []                              # the first call's state stays
        assert notes[-1][-1]["key"] == "dial_result"
        gate.set()
        _join_calls(mgr)
        assert [c[1][0] for c in fake.calls if c[0] == "Dial"] == ["600123456"]
        assert results[-1]["ok"] is True
        bus.publish("bt.cmd.dial", "600123457")          # free again
        _join_calls(mgr)
        assert results[-1]["ok"] is True

    def test_no_modem(self, monkeypatch):
        fake = _DialDBus(modems=[(MODEM, {"Interfaces": ["org.ofono.Handsfree"]})])
        bus, mgr, results, notes = _dial_env(monkeypatch, fake)
        bus.publish("bt.cmd.dial", "600123456")
        _join_calls(mgr)
        assert results[-1]["ok"] is False and results[-1]["error"] == "no_modem"
        entry = notes[-1][-1]
        assert entry["key"] == "dial_result" and "HFP" in entry["desc"]
        # The provisional "ringing" is taken back (no live monitor here).
        assert bus.get_last("bt.call_state")[0] == "idle"
        assert bus.get_last("bt.call_info")[0] == {}
        assert bus.get_last("bt.hfp_active")[0] is False
        assert mgr._dial_busy is False

    @pytest.mark.parametrize("name, registration, expected", [
        ("org.ofono.Error.Failed", None, "dbus"),
        ("org.ofono.Error.Failed", "searching", "netdown"),
        ("org.ofono.Error.Failed", "registered", "dbus"),
        ("org.ofono.Error.InProgress", None, "busy"),
        ("org.ofono.Error.InvalidFormat", None, "invalid"),
        # oFono's manager_dial: -ENETDOWN (modem not online) -> NotAvailable
        ("org.ofono.Error.NotAvailable", None, "netdown"),
    ])
    def test_dbus_errors(self, monkeypatch, name, registration, expected):
        fake = _DialDBus(dial_error=name)
        bus, mgr, results, notes = _dial_env(monkeypatch, fake)
        if registration:
            bus.publish("bt.phone_status", {"registration": registration})
        bus.publish("bt.cmd.dial", "600123456")
        _join_calls(mgr)
        assert results[-1] == {"ok": False, "path": "hfp", "error": expected,
                               "ts": results[-1]["ts"]}
        assert bus.get_last("bt.call_state")[0] == "idle"

    @pytest.mark.parametrize("name", ["org.freedesktop.DBus.Error.NoReply",
                                      "org.freedesktop.DBus.Error.Timeout"])
    def test_no_reply_to_dial_is_unknown_not_failed(self, monkeypatch, name):
        # Android answers ATD only once the call is DIALING: the call may be
        # going out — no "try again" toast, no revert of the overlay.
        fake = _DialDBus(dial_error=name)
        bus, mgr, results, notes = _dial_env(monkeypatch, fake)
        bus.publish("bt.phone_status", {"registration": "denied"})
        bus.publish("bt.cmd.dial", "600123456")
        _join_calls(mgr)
        assert results[-1] == {"ok": None, "path": "hfp", "error": "unknown",
                               "ts": results[-1]["ts"]}
        assert notes == []
        assert bus.get_last("bt.call_state")[0] == "ringing"
        assert mgr._dial_busy is False

    def test_no_reply_to_dial_with_a_live_monitor_reconciles_later(self, monkeypatch):
        fake = _DialDBus(dial_error="org.freedesktop.DBus.Error.NoReply")
        bus, mgr, results, notes = _dial_env(monkeypatch, fake)
        tracker = OfonoCallTracker(bus)
        tracker.live = True
        mgr._call_tracker = tracker
        now, later = [], []
        monkeypatch.setattr(tracker, "reconcile", lambda: now.append(True))
        monkeypatch.setattr(mgr, "_schedule_call_reconcile", lambda *a: later.append(True))
        bus.publish("bt.cmd.dial", "600123456")
        _join_calls(mgr)
        assert now == [] and later == [True]

    def test_no_reply_before_dial_was_sent_is_a_failure(self, monkeypatch):
        fake = _DialDBus(modems_error="org.freedesktop.DBus.Error.NoReply")
        bus, mgr, results, notes = _dial_env(monkeypatch, fake)
        bus.publish("bt.cmd.dial", "600123456")
        _join_calls(mgr)
        assert results[-1]["ok"] is False and results[-1]["error"] == "dbus"
        assert [c[0] for c in fake.calls] == ["GetModems"]
        assert bus.get_last("bt.call_state")[0] == "idle"

    def test_dial_waits_up_to_15_s(self, monkeypatch):
        fake = _DialDBus()
        bus, mgr, results, notes = _dial_env(monkeypatch, fake)
        bus.publish("bt.cmd.dial", "600123456")
        _join_calls(mgr)
        dial = [c for c in fake.calls if c[0] == "Dial"][0]
        assert dial[3] == {"timeout": 15.0}

    def test_without_dbus_python(self, monkeypatch):
        bus, mgr, results, notes = _dial_env(monkeypatch, None, has_dbus=False)
        bus.publish("bt.cmd.dial", "600123456")
        _join_calls(mgr)
        assert results[-1]["error"] == "dbus"
        assert bus.get_last("bt.call_state")[0] == "idle"

    def test_invalid_number_on_the_bus(self, monkeypatch):
        bus, mgr, results, notes = _dial_env(monkeypatch, _DialDBus())
        events = _recorder(bus)
        bus.publish("bt.cmd.dial", "600\r\nfake")
        assert results[-1]["error"] == "invalid" and events == []
        assert mgr._dial_busy is False

    def test_a_call_that_came_in_meanwhile_is_not_touched(self, monkeypatch):
        gate = threading.Event()
        fake = _DialDBus(modems=[], block=gate)
        bus, mgr, results, notes = _dial_env(monkeypatch, fake)
        bus.publish("bt.cmd.dial", "600123456")
        bus.publish("bt.call_info", {"number": "+48500111222", "name": "Ania"})
        bus.publish("bt.call_state", "incoming")
        gate.set()
        _join_calls(mgr)
        assert results[-1]["error"] == "no_modem"
        assert bus.get_last("bt.call_state")[0] == "incoming"

    def test_live_monitor_reconciles_instead(self, monkeypatch):
        fake = _DialDBus(modems=[])
        bus, mgr, results, notes = _dial_env(monkeypatch, fake)
        tracker = OfonoCallTracker(bus)
        tracker.live = True
        mgr._call_tracker = tracker
        seen = []
        monkeypatch.setattr(tracker, "reconcile", lambda: seen.append(True))
        bus.publish("bt.cmd.dial", "600123456")
        _join_calls(mgr)
        assert seen == [True]

    def test_a_worker_that_cannot_start_frees_the_slot(self, monkeypatch):
        bus, mgr, results, notes = _dial_env(monkeypatch, _DialDBus())

        def boom():
            raise RuntimeError("can't start new thread")

        mgr._spawn_call_thread = boom
        bus.publish("bt.cmd.dial", "600123456")
        assert results[-1]["error"] == "dbus" and mgr._dial_busy is False
        assert bus.get_last("bt.call_state")[0] == "idle"

    def test_dial_error_of(self):
        assert bt.dial_error_of(None) == "dbus"
        assert bt.dial_error_of("org.ofono.Error.NotRegistered") == "netdown"
        assert bt.dial_error_of("org.ofono.Error.NotAvailable") == "netdown"
        assert bt.dial_error_of("org.ofono.Error.InvalidArguments") == "invalid"
        assert bt.dial_error_of("org.freedesktop.DBus.Error.NoReply") == "unknown"
        assert bt.dial_error_of("org.freedesktop.DBus.Error.NoReply",
                                dial_sent=False) == "dbus"


# ── One serial bt-call worker for dial / answer / hangup (0f, plan H) ────

class TestCallWorker:
    def test_hangup_during_a_pending_dial_ends_the_new_call(self, monkeypatch):
        # Before the worker, the bus thread was blocked in Dial and the
        # hang-up queued behind it; it must still run AFTER the Dial (oFono
        # refuses HangupAll while a Dial is pending) — not get lost.
        gate = threading.Event()
        fake = _DialDBus(block=gate)
        bus, mgr, results, notes = _dial_env(monkeypatch, fake)
        bus.publish("bt.cmd.dial", "112")                # kiosk tap
        bus.publish("bt.cmd.hangup", True)               # driver: no, hang up
        # The bus thread did not wait for D-Bus: the UI is idle already.
        assert bus.get_last("bt.call_state")[0] == "idle"
        gate.set()
        _join_calls(mgr)
        methods = [c[0] for c in fake.calls]
        assert methods == ["GetModems", "Dial", "GetModems", "HangupAll"]
        assert {c[2] for c in fake.calls} == {"bt-call"}
        assert results[-1]["ok"] is True
        assert bus.get_last("bt.call_state")[0] == "idle"   # dial OK changes nothing

    def test_answer_and_hangup_do_not_block_the_bus_thread(self, monkeypatch):
        gate = threading.Event()
        fake = _DialDBus(block=gate)
        bus, mgr, results, notes = _dial_env(monkeypatch, fake)
        events = _recorder(bus)
        bus.publish("bt.cmd.answer", True)
        bus.publish("bt.cmd.hangup", True)
        assert ("bt.call_state", "active") in events and ("bt.call_state", "idle") in events
        assert fake.calls in ([], [("GetModems", (), "bt-call", {"timeout": 5.0})])
        gate.set()
        _join_calls(mgr)
        assert [c[0] for c in fake.calls] == ["GetModems", "GetCalls", "GetModems", "HangupAll"]
        assert {c[2] for c in fake.calls} == {"bt-call"}

    def test_hangup_retries_while_ofono_is_in_progress(self, monkeypatch):
        fake = _DialDBus(hangup_errors=["org.ofono.Error.InProgress"] * 2)
        bus, mgr, results, notes = _dial_env(monkeypatch, fake)
        pauses = []
        mgr._call_sleep = pauses.append
        bus.publish("bt.cmd.hangup", True)
        _join_calls(mgr)
        assert [c[0] for c in fake.calls].count("HangupAll") == 3
        assert pauses == [1.0, 1.0]

    def test_hangup_retries_are_bounded(self, monkeypatch, caplog):
        fake = _DialDBus(hangup_errors=["org.ofono.Error.InProgress"] * 10)
        bus, mgr, results, notes = _dial_env(monkeypatch, fake)
        mgr._call_sleep = lambda s: None
        with caplog.at_level(logging.WARNING, logger="bcm.multimedia.bluetooth"):
            bus.publish("bt.cmd.hangup", True)
            _join_calls(mgr)
        assert [c[0] for c in fake.calls].count("HangupAll") == bt._HANGUP_TRIES
        assert any("InProgress" in r.getMessage() for r in caplog.records)

    def test_other_hangup_errors_are_not_retried(self, monkeypatch):
        fake = _DialDBus(hangup_errors=["org.ofono.Error.Failed"])
        bus, mgr, results, notes = _dial_env(monkeypatch, fake)
        mgr._call_sleep = lambda s: pytest.fail("no retry for Failed")
        bus.publish("bt.cmd.hangup", True)
        _join_calls(mgr)
        assert [c[0] for c in fake.calls].count("HangupAll") == 1

    def test_without_dbus_python_no_worker_for_answer_and_hangup(self, monkeypatch):
        bus, mgr, results, notes = _dial_env(monkeypatch, None, has_dbus=False)
        mgr._spawn_call_thread = lambda: pytest.fail("no thread needed")
        bus.publish("bt.cmd.answer", True)
        bus.publish("bt.cmd.hangup", True)
        assert bus.get_last("bt.call_state")[0] == "idle"

    def test_a_full_queue_drops_instead_of_blocking(self, monkeypatch):
        gate = threading.Event()
        fake = _DialDBus(block=gate)
        bus, mgr, results, notes = _dial_env(monkeypatch, fake)
        try:
            for _ in range(bt._CALL_QUEUE_MAX + 5):       # SWC button mashed
                bus.publish("bt.cmd.hangup", True)        # returns at once
            # The dial cannot be queued: refused, the slot is free again.
            bus.publish("bt.cmd.dial", "600123456")
            assert results[-1]["error"] == "dbus" and mgr._dial_busy is False
        finally:
            gate.set()
        _join_calls(mgr)

    def test_the_idle_worker_exits_and_a_new_one_starts(self, monkeypatch):
        monkeypatch.setattr(bt, "_CALL_WORKER_IDLE_S", 0.05)
        fake = _DialDBus()
        bus, mgr, results, notes = _dial_env(monkeypatch, fake)
        bus.publish("bt.cmd.hangup", True)
        _join_calls(mgr)
        first = mgr._call_worker
        first.join(2.0)
        assert not first.is_alive() and mgr._call_worker is None
        bus.publish("bt.cmd.hangup", True)
        _join_calls(mgr)
        assert [c[0] for c in fake.calls].count("HangupAll") == 2
