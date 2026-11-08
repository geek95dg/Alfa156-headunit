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
        assert len(receivers) == 6
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
