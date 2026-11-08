"""Mic router (src/audio/mic_router.py) and the PipeWire call-route checks.

Everything runs against a fake PipeWire: a runner that answers ``pw-dump``
with canned JSON and applies ``wpctl set-default`` / ``set-profile`` /
``pw-cli create-node`` to that in-memory graph. Nothing is executed, no
thread is started (``tick()`` is driven directly), and sleeps are no-ops.
"""

import json
import logging
import subprocess

import pytest

from src.audio import mic_router as mr
from src.audio import pipewire_ctrl as pc
from src.audio.mic_router import (
    AEC_REF_SINK_NAME,
    AEC_SOURCE_NAME,
    NULL_MIC_NAME,
    MicRouter,
    PwGraph,
    aec_mode,
    autoapp_snapshot,
    build_aec_conf,
    is_mic_candidate,
    pick_duplex_profile,
    pick_output_only_profile,
    select_mic,
)
from src.core.event_bus import EventBus

USB_CARD = 40
PCI_CARD = 41
MIC_CARD = 42
USB_SINK = "alsa_output.usb-Generic_USB_Audio-00.analog-stereo"
USB_IN = "alsa_input.usb-Generic_USB_Audio-00.mono-fallback"
DEDICATED_MIC = "alsa_input.usb-C-Media_USB_Mic-00.mono-fallback"

USB_PROFILES = [
    {"index": 0, "name": "off", "available": "yes", "priority": 0},
    {"index": 1, "name": "output:analog-stereo+input:mono-fallback", "available": "yes",
     "priority": 6500},
    {"index": 2, "name": "output:analog-stereo", "available": "yes", "priority": 6500},
    {"index": 3, "name": "input:mono-fallback", "available": "yes", "priority": 1},
    {"index": 4, "name": "output:iec958-stereo", "available": "no", "priority": 9000},
    {"index": 5, "name": "pro-audio", "available": "yes", "priority": 1},
]


class FakePipeWire:
    """In-memory PipeWire graph behind a subprocess.run-compatible runner."""

    def __init__(self):
        self.calls = []
        self.next_id = 100
        self.nodes = {}        # id -> props
        self.devices = {}      # id -> {"props", "profiles", "profile"}
        self.links = []        # (out, in)
        self.defaults = {}     # metadata key -> name
        self.fail_dump = False
        self.fail_cmd = set()  # argv[0:2] tuples that return rc 1
        self.null_mic_appears = True

    # graph building ----------------------------------------------------
    def add_node(self, name, media_class, device=None, nid=None, **extra):
        nid = nid if nid is not None else self._id()
        props = {"node.name": name, "media.class": media_class}
        if device is not None:
            props["device.id"] = device
        props.update(extra)
        self.nodes[nid] = props
        return nid

    def add_card(self, dev_id, profile, profiles=USB_PROFILES, inputs=(), outputs=()):
        self.devices[dev_id] = {"props": {"device.api": "alsa", "media.class": "Audio/Device"},
                                "profiles": [dict(p) for p in profiles], "profile": profile,
                                "inputs": list(inputs), "outputs": list(outputs)}
        self._sync_card_nodes(dev_id)

    def _sync_card_nodes(self, dev_id):
        dev = self.devices[dev_id]
        for nid in [n for n, p in self.nodes.items() if p.get("device.id") == dev_id]:
            del self.nodes[nid]
        if "output:" in dev["profile"]:
            for name in dev["outputs"]:
                self.add_node(name, "Audio/Sink", device=dev_id)
        if "input:" in dev["profile"]:
            for name in dev["inputs"]:
                self.add_node(name, "Audio/Source", device=dev_id)

    def _id(self):
        self.next_id += 1
        return self.next_id

    def dump(self):
        objs = []
        for nid, props in self.nodes.items():
            objs.append({"id": nid, "type": "PipeWire:Interface:Node",
                         "info": {"props": dict(props)}})
        for did, dev in self.devices.items():
            objs.append({"id": did, "type": "PipeWire:Interface:Device",
                         "info": {"props": dev["props"],
                                  "params": {"EnumProfile": dev["profiles"],
                                             "Profile": [{"index": 0, "name": dev["profile"]}]}}})
        for i, (o, n) in enumerate(self.links):
            objs.append({"id": 900 + i, "type": "PipeWire:Interface:Link",
                         "info": {"output-node-id": o, "input-node-id": n, "state": "active"}})
        objs.append({"id": 30, "type": "PipeWire:Interface:Metadata",
                     "props": {"metadata.name": "default"},
                     "metadata": [{"subject": 0, "key": k, "type": "Spa:String:JSON",
                                   "value": {"name": v}} for k, v in self.defaults.items()]})
        return json.dumps(objs)

    # runner ------------------------------------------------------------
    def __call__(self, argv, **kwargs):
        assert not kwargs.get("shell"), "shell=True is never allowed"
        assert isinstance(argv, list)
        self.calls.append(list(argv))
        if tuple(argv[:2]) in self.fail_cmd or tuple(argv[:1]) in self.fail_cmd:
            return subprocess.CompletedProcess(argv, 1, "", "refused")
        if argv == ["pw-dump"]:
            if self.fail_dump:
                return subprocess.CompletedProcess(argv, 1, "", "no pipewire")
            return subprocess.CompletedProcess(argv, 0, self.dump(), "")
        if argv[:2] == ["wpctl", "set-default"]:
            nid = int(argv[2])
            props = self.nodes[nid]
            # wpctl 0.5.8: exact media.class match only (exit 3 otherwise)
            if props["media.class"] not in ("Audio/Sink", "Audio/Source", "Video/Source"):
                return subprocess.CompletedProcess(argv, 3, "", "not a device node")
            key = "default.audio.source" if "Source" in props["media.class"] else "default.audio.sink"
            self.defaults[key] = props["node.name"]
            return subprocess.CompletedProcess(argv, 0, "", "")
        if argv[0] == "pw-metadata":
            assert argv[1:5] == ["-n", "default", "0", "default.configured.audio.source"]
            assert argv[6] == "Spa:String:JSON"
            # WirePlumber applies the configured default (virtual sources allowed)
            self.defaults["default.audio.source"] = json.loads(argv[5])["name"]
            return subprocess.CompletedProcess(argv, 0, "", "")
        if argv[:2] == ["wpctl", "set-profile"]:
            dev = self.devices[int(argv[2])]
            dev["profile"] = next(p["name"] for p in dev["profiles"] if p["index"] == int(argv[3]))
            self._sync_card_nodes(int(argv[2]))
            return subprocess.CompletedProcess(argv, 0, "", "")
        if argv[:3] == ["pw-cli", "create-node", "adapter"]:
            if self.null_mic_appears:
                self.add_node(NULL_MIC_NAME, "Audio/Source/Virtual")
            return subprocess.CompletedProcess(argv, 0, "", "")
        return subprocess.CompletedProcess(argv, 0, "", "")

    def ran(self, *prefix):
        return [c for c in self.calls if c[:len(prefix)] == list(prefix)]


class FakeController:
    def __init__(self, sink):
        self.hardware_sink = sink
        self.refreshed = 0
        self.eq_targets = []

    def refresh_hw_sink_id(self):
        self.refreshed += 1
        return "77"

    def set_eq_output_target(self, target):
        self.eq_targets.append(target)
        return True


class Cfg(dict):
    def get(self, key, default=None):
        return super().get(key, default)


class FakeProc:
    def __init__(self):
        self.terminated = False
        self.code = None

    def poll(self):
        return self.code

    def terminate(self):
        self.terminated = True
        self.code = -15

    def wait(self, timeout=None):
        return self.code

    def kill(self):
        self.code = -9


@pytest.fixture
def pw():
    fake = FakePipeWire()
    fake.add_card(USB_CARD, "output:analog-stereo+input:mono-fallback",
                  inputs=[USB_IN], outputs=[USB_SINK])
    fake.add_node("bcm_eq_sink", "Audio/Sink")
    fake.defaults["default.audio.sink"] = "bcm_eq_sink"
    fake.defaults["default.audio.source"] = USB_IN   # the floating input
    return fake


def make_router(pw, bus=None, controller="usb", aec_lib=None, popen=None, tmp_path=None, **cfg):
    config = Cfg({"audio.mic_router": True, "audio.mic_phone": "",
                  "audio.mic_echo_cancel": False, "audio.mic_disable_unused_inputs": True})
    config.update({f"audio.{k}": v for k, v in cfg.items()})
    ctrl = FakeController(USB_SINK) if controller == "usb" else controller
    clock = iter(range(0, 10_000))
    router = MicRouter(config, bus or EventBus(), controller=ctrl, runner=pw,
                       clock=lambda: float(next(clock)), sleep=lambda s: None,
                       popen=popen or (lambda *a, **k: pytest.fail("AEC child started")),
                       aec_lib_finder=lambda: aec_lib,
                       aec_conf_path=str((tmp_path / "aec.conf") if tmp_path else "/nonexistent/aec.conf"))
    return router, ctrl


def record(bus, topic):
    seen = []
    bus.subscribe(topic, lambda t, v, ts: seen.append(v))
    return seen


# ── pure rules ────────────────────────────────────────────────────────────

class TestCandidates:
    @pytest.mark.parametrize("props, ok", [
        ({"node.name": USB_IN, "media.class": "Audio/Source"}, True),
        ({"node.name": "bluez_input.AA_BB.0", "media.class": "Audio/Source"}, False),
        ({"node.name": "alsa_input.usb-x.monitor", "media.class": "Audio/Source"}, False),
        ({"node.name": "alsa_output.usb-x.analog-stereo.monitor", "media.class": "Audio/Source"}, False),
        ({"node.name": NULL_MIC_NAME, "media.class": "Audio/Source/Virtual"}, False),
        ({"node.name": AEC_SOURCE_NAME, "media.class": "Audio/Source"}, False),
        ({"node.name": "alsa_input.virtual", "media.class": "Audio/Source", "node.virtual": True}, False),
        ({"node.name": USB_IN, "media.class": "Audio/Sink"}, False),
        ({"node.name": USB_IN, "media.class": "Stream/Input/Audio"}, False),
    ])
    def test_is_mic_candidate(self, props, ok):
        assert is_mic_candidate(props) is ok

    def test_selection_ignores_bluez_monitor_and_virtual(self, pw):
        pw.add_node("bluez_input.11_22.0", "Audio/Source")
        pw.add_node("alsa_input.usb-fake.monitor", "Audio/Source")
        pw.add_node(NULL_MIC_NAME, "Audio/Source/Virtual")
        graph = PwGraph.from_text(pw.dump())
        nid = select_mic(graph, "alsa_input.usb-", graph.device_of(graph.node_id(USB_SINK)))
        assert graph.node_name(nid) == USB_IN
        assert select_mic(graph, "bluez", None) is None
        assert select_mic(graph, "", None) is None

    def test_dedicated_mic_beats_the_output_cards_input(self, pw):
        pw.add_card(MIC_CARD, "input:mono-fallback", inputs=[DEDICATED_MIC])
        graph = PwGraph.from_text(pw.dump())
        out_dev = graph.device_of(graph.node_id(USB_SINK))
        assert graph.node_name(select_mic(graph, "alsa_input.usb-", out_dev)) == DEDICATED_MIC

    def test_profile_choice_output_only_keeps_output_and_skips_unavailable(self):
        current = "output:analog-stereo+input:mono-fallback"
        assert pick_output_only_profile(USB_PROFILES, current)["index"] == 2
        # no exact match: best available output-only (iec958 is available=no)
        only_iec = [p for p in USB_PROFILES if p["index"] in (1, 4)]
        assert pick_output_only_profile(only_iec, current) is None
        assert pick_duplex_profile(USB_PROFILES, "output:analog-stereo")["index"] == 1

    def test_aec_mode(self):
        assert aec_mode(False) == "off"
        assert aec_mode(None) == "off"
        assert aec_mode("auto") == "auto"
        assert aec_mode(True) == "on"
        assert aec_mode("true") == "on"
        assert aec_mode("rubbish") == "off"

    def test_graph_parses_defaults_profiles_and_garbage(self, pw):
        graph = PwGraph.from_text(pw.dump())
        assert graph.default_source == USB_IN
        assert graph.devices[USB_CARD]["profile"].startswith("output:")
        assert len(graph.devices[USB_CARD]["profiles"]) == len(USB_PROFILES)
        assert PwGraph.from_text("not json").nodes == {}
        assert PwGraph.from_text('{"a": 1}').nodes == {}

    def test_aec_conf_targets(self):
        conf = build_aec_conf(DEDICATED_MIC, USB_SINK)
        assert f'target.object = "{DEDICATED_MIC}"' in conf
        assert f'target.object = "{USB_SINK}"' in conf
        assert f'node.name = "{AEC_SOURCE_NAME}"' in conf
        assert f'node.name = "{AEC_REF_SINK_NAME}"' in conf
        assert "library.name = aec/libspa-aec-webrtc" in conf


# ── router passes ─────────────────────────────────────────────────────────

class TestNoMic:
    def test_creates_null_mic_once_and_makes_it_default(self, pw):
        bus = EventBus()
        states = record(bus, "audio.mic_state")
        sources = record(bus, "audio.input_source")
        router, _ = make_router(pw, bus)
        assert router.tick() is True
        assert pw.defaults["default.audio.source"] == NULL_MIC_NAME
        create = pw.ran("pw-cli", "create-node", "adapter")
        assert len(create) == 1
        props = create[0][3]
        for part in ("factory.name=support.null-audio-sink", f"node.name={NULL_MIC_NAME}",
                     "media.class=Audio/Source/Virtual", "object.linger=true",
                     "audio.position=[MONO]"):
            assert part in props
        assert states == [{"state": "none", "source": NULL_MIC_NAME, "aec": False}]
        assert sources == [NULL_MIC_NAME]

        # wpctl refuses Audio/Source/Virtual, so the metadata key is set directly
        assert pw.ran("wpctl", "set-default") == []
        assert pw.ran("pw-metadata") == [[
            "pw-metadata", "-n", "default", "0", "default.configured.audio.source",
            json.dumps({"name": NULL_MIC_NAME}), "Spa:String:JSON"]]

        router.tick()
        router.tick()
        assert len(pw.ran("pw-cli", "create-node")) == 1      # never a duplicate
        assert len(pw.ran("pw-metadata")) == 1                # no drift, no re-assert
        assert len(states) == 1                               # published only on change

    def test_existing_null_mic_is_reused(self, pw):
        pw.add_node(NULL_MIC_NAME, "Audio/Source/Virtual")
        router, _ = make_router(pw)
        router.tick()
        assert pw.ran("pw-cli") == []
        assert pw.defaults["default.audio.source"] == NULL_MIC_NAME

    def test_configured_mic_missing_falls_back_to_silence(self, pw, caplog):
        router, _ = make_router(pw, mic_phone="alsa_input.usb-Nonexistent")
        with caplog.at_level(logging.WARNING, logger="bcm.audio.mic_router"):
            router.tick()
            router.tick()
        assert router.state["state"] == "none"
        assert sum("no input matches" in r.message for r in caplog.records) == 1

    def test_null_mic_that_cannot_be_created_is_an_error_not_a_loop(self, pw):
        pw.fail_cmd.add(("pw-cli", "create-node"))
        router, _ = make_router(pw)
        router.tick()
        router.tick()
        assert router.state["state"] == "error"
        assert len(pw.ran("pw-cli")) == 1

    def test_null_mic_failure_is_retried_after_a_delay(self, pw, caplog):
        # e.g. pw-cli during a PipeWire/WirePlumber restart: must heal by
        # itself, not stay "error" (= monitor fallback) until BCM restarts.
        pw.fail_cmd.add(("pw-cli", "create-node"))
        now = [0.0]
        router, _ = make_router(pw)
        router._clock = lambda: now[0]
        with caplog.at_level(logging.DEBUG, logger="bcm.audio.mic_router"):
            router.tick()
            assert router.state["state"] == "error"
            now[0] = mr.NULL_RETRY_S - 1
            router.tick()
            assert len(pw.ran("pw-cli")) == 1              # not before the delay
            now[0] = mr.NULL_RETRY_S + 1
            router.tick()
            assert len(pw.ran("pw-cli")) == 2              # retried, failed again
            now[0] += mr.NULL_RETRY_S + 1                  # backoff doubled: not yet
            router.tick()
            assert len(pw.ran("pw-cli")) == 2
            pw.fail_cmd.clear()
            now[0] += mr.NULL_RETRY_S * 2
            router.tick()
        assert len(pw.ran("pw-cli")) == 3
        assert router.state == {"state": "none", "source": NULL_MIC_NAME, "aec": False}
        assert pw.defaults["default.audio.source"] == NULL_MIC_NAME
        errors = [r for r in caplog.records if r.levelno >= logging.ERROR]
        assert len(errors) == 1                            # logged once
        assert router._null_retry_at is None and router._null_backoff == mr.NULL_RETRY_S

    def test_drift_is_reasserted(self, pw):
        router, _ = make_router(pw)
        router.tick()
        pw.defaults["default.audio.source"] = USB_IN      # WirePlumber/user moved it
        router.tick()
        assert pw.defaults["default.audio.source"] == NULL_MIC_NAME
        assert len(pw.ran("pw-metadata")) == 2

    def test_real_mic_uses_wpctl(self, pw):
        pw.defaults["default.audio.source"] = NULL_MIC_NAME
        router, _ = make_router(pw, mic_phone="alsa_input.usb-Generic")
        router.tick()
        usb_in = next(n for n, p in pw.nodes.items() if p["node.name"] == USB_IN)
        assert pw.ran("wpctl", "set-default") == [["wpctl", "set-default", str(usb_in)]]
        assert pw.ran("pw-metadata") == []


class TestMicFound:
    def test_mic_on_output_card_keeps_its_profile(self, pw):
        router, ctrl = make_router(pw, mic_phone="alsa_input.usb-Generic")
        router.tick()
        assert pw.ran("wpctl", "set-profile") == []
        assert pw.defaults["default.audio.source"] == USB_IN
        assert router.state == {"state": "ok", "source": USB_IN, "aec": False}

    def test_mic_on_another_card_makes_output_card_output_only(self, pw):
        pw.add_card(MIC_CARD, "input:mono-fallback", inputs=[DEDICATED_MIC])
        router, ctrl = make_router(pw, mic_phone="C-Media")
        router.tick()
        assert pw.ran("wpctl", "set-profile") == [["wpctl", "set-profile", str(USB_CARD), "2"]]
        assert pw.devices[USB_CARD]["profile"] == "output:analog-stereo"
        assert ctrl.refreshed >= 1                            # stale _hw_sink_id refreshed
        assert pw.defaults["default.audio.source"] == DEDICATED_MIC
        router.tick()
        assert len(pw.ran("wpctl", "set-profile")) == 1       # once

    def test_profile_switch_waits_for_output_setup(self, pw):
        import threading
        pw.add_card(MIC_CARD, "input:mono-fallback", inputs=[DEDICATED_MIC])
        ctrl = FakeController(USB_SINK)
        ctrl.output_configured = threading.Event()        # prepare_output still running
        router, _ = make_router(pw, controller=ctrl, mic_phone="C-Media")
        router.tick()
        assert pw.ran("wpctl", "set-profile") == []       # would race its unmute/volume
        assert pw.defaults["default.audio.source"] == DEDICATED_MIC   # mic still chosen
        ctrl.output_configured.set()
        router.tick()
        assert pw.ran("wpctl", "set-profile") == [["wpctl", "set-profile", str(USB_CARD), "2"]]

    def test_disable_unused_inputs_off_leaves_profile(self, pw):
        pw.add_card(MIC_CARD, "input:mono-fallback", inputs=[DEDICATED_MIC])
        router, _ = make_router(pw, mic_phone="C-Media", mic_disable_unused_inputs=False)
        router.tick()
        assert pw.ran("wpctl", "set-profile") == []

    def test_output_only_card_gets_its_input_back_once_when_mic_missing(self, pw):
        # A previous run (dedicated mic present) left the card output-only;
        # WirePlumber persisted that. Now the mic is in the card's own jack.
        pw.add_card(USB_CARD, "output:analog-stereo", inputs=[USB_IN], outputs=[USB_SINK])
        router, _ = make_router(pw, mic_phone="alsa_input.usb-Generic")
        router.tick()
        assert pw.ran("wpctl", "set-profile") == [["wpctl", "set-profile", str(USB_CARD), "1"]]
        router.tick()                                         # input is back -> mic found
        assert router.state["state"] == "ok"
        assert len(pw.ran("wpctl", "set-profile")) == 1

    def test_unplug_and_replug(self, pw):
        pw.add_card(MIC_CARD, "input:mono-fallback", inputs=[DEDICATED_MIC])
        bus = EventBus()
        states = record(bus, "audio.mic_state")
        router, _ = make_router(pw, bus, mic_phone="C-Media")
        router.tick()
        mic_nodes = [n for n, p in pw.nodes.items() if p["node.name"] == DEDICATED_MIC]
        for n in mic_nodes:
            del pw.nodes[n]
        router.tick()
        assert pw.defaults["default.audio.source"] == NULL_MIC_NAME
        pw.add_node(DEDICATED_MIC, "Audio/Source", device=MIC_CARD)
        router.tick()
        assert pw.defaults["default.audio.source"] == DEDICATED_MIC
        assert [s["state"] for s in states] == ["ok", "none", "ok"]
        # unplugged: the output card got its input back once (the mic might
        # be in its jack now); replugged: output-only again. Bounded.
        assert [c[3] for c in pw.ran("wpctl", "set-profile")] == ["2", "1", "2"]
        assert pw.devices[USB_CARD]["profile"] == "output:analog-stereo"

    def test_set_default_retries_then_errors(self, pw):
        pw.fail_cmd.add(("wpctl", "set-default"))
        pw.defaults["default.audio.source"] = USB_SINK + ".monitor"
        router, _ = make_router(pw, mic_phone="alsa_input.usb-Generic")
        router.tick()
        assert len(pw.ran("wpctl", "set-default")) == mr.SET_DEFAULT_ATTEMPTS
        assert router.state["state"] == "error"


class TestAec:
    def test_auto_without_library_stays_off(self, pw):
        router, ctrl = make_router(pw, mic_phone="alsa_input.usb-Generic",
                                   mic_echo_cancel="auto", aec_lib=None)
        router.tick()                                         # popen would pytest.fail
        assert router.state == {"state": "ok", "source": USB_IN, "aec": False}
        assert AEC_REF_SINK_NAME not in ctrl.eq_targets

    def test_failure_falls_back_to_raw_mic_with_one_error(self, pw, tmp_path, caplog):
        procs = []

        def popen(argv, **kw):
            assert argv[:2] == ["pipewire", "-c"]
            assert not kw.get("shell")
            procs.append(FakeProc())
            return procs[-1]

        router, ctrl = make_router(pw, mic_phone="alsa_input.usb-Generic", mic_echo_cancel=True,
                                   popen=popen, tmp_path=tmp_path)
        with caplog.at_level(logging.ERROR, logger="bcm.audio.mic_router"):
            router.tick()
            router.tick()
        assert len(procs) == 1 and procs[0].terminated        # killed, not retried
        assert pw.defaults["default.audio.source"] == USB_IN  # raw mic
        assert router.state == {"state": "ok", "source": USB_IN, "aec": False}
        assert AEC_REF_SINK_NAME not in ctrl.eq_targets       # EQ never retargeted
        assert sum("Echo cancellation unavailable" in r.message for r in caplog.records) == 1
        assert USB_IN in (tmp_path / "aec.conf").read_text()

    def test_success_retargets_eq_and_uses_clean_source(self, pw, tmp_path):
        def popen(argv, **kw):
            pw.add_node(AEC_SOURCE_NAME, "Audio/Source")
            pw.add_node(AEC_REF_SINK_NAME, "Audio/Sink")
            return FakeProc()

        router, ctrl = make_router(pw, mic_phone="alsa_input.usb-Generic", mic_echo_cancel="auto",
                                   aec_lib="/usr/lib/x/spa-0.2/aec/libspa-aec-webrtc.so",
                                   popen=popen, tmp_path=tmp_path)
        router.tick()
        assert ctrl.eq_targets[-1] == AEC_REF_SINK_NAME
        assert pw.defaults["default.audio.source"] == AEC_SOURCE_NAME
        assert router.state == {"state": "ok", "source": AEC_SOURCE_NAME, "aec": True}
        router.stop()
        assert ctrl.eq_targets[-1] is None                    # EQ back on the hw sink


class TestStop:
    def test_stop_does_not_wait_for_a_stuck_pass(self, pw, tmp_path):
        import threading
        import time as _time

        proc = FakeProc()
        router, ctrl = make_router(pw, mic_phone="alsa_input.usb-Generic", tmp_path=tmp_path)
        router._aec_proc, router._aec_mic = proc, USB_IN
        held, release = threading.Event(), threading.Event()

        def stuck_pass():                     # a tick blocked in pw-dump
            with router._lock:
                held.set()
                release.wait(5)

        t = threading.Thread(target=stuck_pass, daemon=True)
        t.start()
        assert held.wait(2)
        started = _time.monotonic()
        router.stop(restore_eq=False)
        assert _time.monotonic() - started < 1.0
        assert proc.terminated and router._aec_proc is None
        assert ctrl.eq_targets == []                      # no EQ restart on shutdown
        release.set()
        t.join(2)
        assert router.tick() is False                     # stopped: nothing runs

    def test_stop_with_restore_hands_eq_back(self, pw):
        router, ctrl = make_router(pw)
        router.stop()
        assert ctrl.eq_targets == [None]

    def test_pass_interrupted_by_stop_touches_nothing(self, pw):
        router, _ = make_router(pw)
        real = pw.__call__

        def runner(argv, **kw):
            if argv == ["pw-dump"]:
                router._stop.set()            # stop() arrives during pw-dump
            return real(argv, **kw)

        router._runner = runner
        assert router.tick() is False
        assert pw.ran("pw-cli") == [] and pw.ran("pw-metadata") == []
        assert router.state is None

    def test_null_mic_poll_ends_on_stop(self, pw):
        pw.null_mic_appears = False
        router, _ = make_router(pw)
        dumps = []
        real = pw.__call__

        def runner(argv, **kw):
            if argv == ["pw-dump"]:
                dumps.append(1)
                if len(dumps) == 3:
                    router._stop.set()
            return real(argv, **kw)

        router._runner = runner
        router.tick()
        assert len(dumps) <= 4                            # not 1 + SET_DEFAULT_ATTEMPTS
        assert router.state is None                       # no "error" published

    def test_aec_start_after_stop_never_spawns(self, pw, tmp_path):
        router, _ = make_router(pw, mic_phone="alsa_input.usb-Generic", mic_echo_cancel=True,
                                tmp_path=tmp_path)            # popen would pytest.fail
        router._stop.set()
        assert router._ensure_aec(USB_IN, USB_SINK) is False


class TestLifecycle:
    def test_disabled_router_does_nothing(self, pw):
        bus = EventBus()
        router, _ = make_router(pw, bus, mic_router=False)
        assert router.start() is False
        assert router.tick() is False
        assert pw.calls == []
        assert "multimedia.openauto_status" not in bus._subscribers
        assert bus.get_last("audio.mic_state") is None

    def test_default_config_keeps_router_off(self):
        router = MicRouter(Cfg(), EventBus(), runner=lambda *a, **k: pytest.fail("ran"))
        assert router.enabled is False and router.start() is False

    def test_pipewire_down_reports_error_after_a_few_rounds(self, pw):
        pw.fail_dump = True
        bus = EventBus()
        states = record(bus, "audio.mic_state")
        router, _ = make_router(pw, bus)
        for _ in range(mr.ERROR_AFTER_FAILURES - 1):
            assert router.tick() is False
        assert states == []
        router.tick()
        assert states == [{"state": "error", "source": "", "aec": False}]

    def test_missing_tool_never_raises(self):
        def runner(argv, **kw):
            raise FileNotFoundError(argv[0])
        router = MicRouter(Cfg({"audio.mic_router": True}), EventBus(), runner=runner,
                           sleep=lambda s: None)
        assert router.tick() is False

    def test_snapshot_on_connect(self, pw):
        app = pw.add_node("autoapp-out", "Stream/Output/Audio",
                          **{"application.process.binary": "autoapp"})
        rec = pw.add_node("autoapp-in", "Stream/Input/Audio",
                          **{"application.name": "autoapp"})
        eq = next(n for n, p in pw.nodes.items() if p["node.name"] == "bcm_eq_sink")
        usb_in = next(n for n, p in pw.nodes.items() if p["node.name"] == USB_IN)
        pw.links += [(app, eq), (usb_in, rec)]
        bus = EventBus()
        diags = record(bus, "audio.diag")
        router, _ = make_router(pw, bus)
        snap = router.log_snapshot()
        assert snap["default_source"] == USB_IN
        streams = {s["name"]: s for s in snap["autoapp_streams"]}
        assert streams["autoapp-out"]["to"] == ["bcm_eq_sink"]
        assert streams["autoapp-in"]["from"] == [USB_IN]
        assert diags and diags[0]["default_sink"] == "bcm_eq_sink"
        assert autoapp_snapshot(PwGraph([]))["autoapp_streams"] == []


# ── PipeWireController: calls are verified, never linked ─────────────────

class TestCallRoute:
    def _sco_dump(self, linked=True):
        fake = FakePipeWire()
        down = fake.add_node("bluez_input.11_22.0", "Stream/Output/Audio",
                             **{"api.bluez5.profile": "headset-audio-gateway"})
        up = fake.add_node("bluez_output.11_22.1", "Stream/Input/Audio",
                           **{"api.bluez5.profile": "headset-audio-gateway"})
        eq = fake.add_node("bcm_eq_sink", "Audio/Sink")
        mic = fake.add_node(NULL_MIC_NAME, "Audio/Source/Virtual")
        if linked:
            fake.links += [(down, eq), (mic, up)]
        return fake

    def test_call_route_pure(self):
        route = pc._call_route(json.loads(self._sco_dump().dump()))
        assert route["downlink"] == "bluez_input.11_22.0"
        assert route["uplink"] == "bluez_output.11_22.1"
        assert route["linked"] is True
        assert route["downlink_peers"] == ["bcm_eq_sink"]
        assert route["uplink_peers"] == [NULL_MIC_NAME]
        assert pc._call_route([])["linked"] is False

    @pytest.mark.parametrize("linked", [True, False])
    def test_check_publishes_and_never_links(self, monkeypatch, caplog, linked):
        fake = self._sco_dump(linked)

        def run_cmd(cmd, timeout=5.0):
            res = fake(list(cmd))
            return res.returncode, res.stdout, res.stderr

        monkeypatch.setattr(pc, "_run_cmd", run_cmd)
        monkeypatch.setattr(pc.time, "sleep", lambda s: None)
        bus = EventBus()
        routes = record(bus, "audio.call_route")
        ctrl = pc.PipeWireController(Cfg(), bus)
        ctrl._available = True
        with caplog.at_level(logging.WARNING, logger="bcm.audio.pipewire"):
            route = ctrl._check_call_route(wait_s=0.0)
        assert routes == [route]
        assert route["linked"] is linked
        assert all(c[0] != "pw-link" for c in fake.calls)
        assert any("NOT fully linked" in r.message for r in caplog.records) is (not linked)

    def test_call_state_active_starts_one_worker(self, monkeypatch):
        import threading
        bus = EventBus()
        ctrl = pc.PipeWireController(Cfg(), bus)
        ctrl._available = True
        started = []
        done = threading.Event()

        def check():
            started.append(1)
            done.set()

        monkeypatch.setattr(ctrl, "_check_call_route", check)
        bus.publish("bt.call_state", "ringing")
        assert started == []
        assert ctrl._call_check_lock.acquire(blocking=False)   # busy: a check runs
        bus.publish("bt.call_state", "active")
        assert started == []
        ctrl._call_check_lock.release()
        bus.publish("bt.call_state", "active")
        assert done.wait(2.0) and started == [1]

    @pytest.mark.parametrize("props, a2dp", [
        ({"api.bluez5.profile": "a2dp-source"}, True),
        ({"api.bluez5.profile": "headset-audio-gateway"}, False),
        ({"api.bluez5.profile": "headset-head-unit"}, False),
        ({"factory.name": "api.bluez5.a2dp.source"}, True),
        ({"factory.name": "api.bluez5.sco.source"}, False),
        ({"node.name": "bluez_input.11_22.a2dp-source"}, True),
        ({"node.name": "bluez_input.11_22.0"}, False),          # unknown: not touched
    ])
    def test_a2dp_filter(self, props, a2dp):
        assert pc._is_a2dp_node(props) is a2dp

    def test_link_bt_sources_skips_sco(self, monkeypatch):
        ctrl = pc.PipeWireController(Cfg(), EventBus())
        ctrl._hw_sink = USB_SINK
        monkeypatch.setattr(ctrl, "_list_source_nodes", lambda: [
            {"id": "1", "name": "bluez_input.11_22.0",
             "props": {"api.bluez5.profile": "headset-audio-gateway"}},
            {"id": "2", "name": "bluez_input.11_22.2",
             "props": {"api.bluez5.profile": "a2dp-source"}},
        ])
        linked = []
        monkeypatch.setattr(ctrl, "_link_stereo", lambda s, t: linked.append((s, t)))
        ctrl._link_bt_sources()
        assert linked == [("bluez_input.11_22.2", USB_SINK)]

    def test_enum_profiles_parsing(self):
        info = {"params": {"EnumProfile": [
            {"index": 1, "name": "a2dp-sink", "priority": 10},
            {"index": True, "name": "bogus"},
            {"name": "no-index"},
            "garbage",
        ]}}
        assert pc._parse_enum_profiles(info) == [
            {"index": 1, "name": "a2dp-sink", "available": "unknown", "priority": 10,
             "description": ""}]
        assert pc._parse_enum_profiles(None) == []

    def test_eq_retarget_and_no_restart_while_stopping(self, monkeypatch):
        ctrl = pc.PipeWireController(Cfg(), EventBus())
        applied = []
        monkeypatch.setattr(ctrl, "_apply_eq_dsp", lambda gains: applied.append(ctrl._eq_target_override))
        ctrl._available = True
        assert ctrl.set_eq_output_target(AEC_REF_SINK_NAME) is True
        assert ctrl.set_eq_output_target(AEC_REF_SINK_NAME) is False
        assert applied == [AEC_REF_SINK_NAME]
        monkeypatch.undo()
        ctrl._stopping = True
        popen = []
        monkeypatch.setattr(pc.subprocess, "Popen", lambda *a, **k: popen.append(a))
        ctrl._apply_eq_dsp([0] * 10)
        assert popen == []                                    # no orphan EQ child

    def test_refresh_hw_sink_id(self, monkeypatch):
        ctrl = pc.PipeWireController(Cfg({"audio.hw_volume": 85}), EventBus())
        ctrl._available = True
        ctrl._hw_sink, ctrl._hw_sink_id = USB_SINK, "50"
        monkeypatch.setattr(ctrl, "list_sink_nodes", lambda: [{"id": "61", "name": USB_SINK}])
        ran = []
        monkeypatch.setattr(pc, "_run_cmd", lambda argv, timeout=5.0: (ran.append(argv), (0, "", ""))[1])
        assert ctrl.refresh_hw_sink_id() == "61"
        assert ctrl._hw_sink_id == "61"
        # the startup unmute/level may have hit the dead node: re-applied on the new one
        assert ran == [["wpctl", "set-mute", "61", "0"], ["wpctl", "set-volume", "61", "0.85"]]
        ran.clear()
        assert ctrl.refresh_hw_sink_id() == "61"          # unchanged: nothing re-applied
        assert ran == []

    def test_refresh_respects_force_unmute_off(self, monkeypatch):
        ctrl = pc.PipeWireController(Cfg({"audio.force_unmute": False}), EventBus())
        ctrl._available = True
        ctrl._hw_sink, ctrl._hw_sink_id = USB_SINK, "50"
        monkeypatch.setattr(ctrl, "list_sink_nodes", lambda: [{"id": "62", "name": USB_SINK}])
        ran = []
        monkeypatch.setattr(pc, "_run_cmd", lambda argv, timeout=5.0: (ran.append(argv), (0, "", ""))[1])
        ctrl.refresh_hw_sink_id()
        assert ran == [["wpctl", "set-volume", "62", "1.00"]]

    def test_output_configured_is_set_even_if_setup_fails(self, monkeypatch):
        ctrl = pc.PipeWireController(Cfg(), EventBus())

        def boom():
            raise RuntimeError("wpctl exploded")

        monkeypatch.setattr(ctrl, "prepare_output", boom)
        assert not ctrl.output_configured.is_set()
        with pytest.raises(RuntimeError):
            ctrl._configure_output()
        assert ctrl.output_configured.is_set()          # the router never waits forever


# ── volume.py: a router that cannot start must not hold AA back ──────────

class TestStartAudioRouterFailure:
    def _start(self, monkeypatch, cfg):
        from unittest import mock
        from src.audio import volume

        pw_ctrl = mock.MagicMock(available=False, hardware_sink=None)
        monkeypatch.setattr(volume, "PipeWireController", lambda c, b: pw_ctrl)

        def broken(*a, **k):
            raise RuntimeError("no router today")

        monkeypatch.setattr(mr, "MicRouter", broken)
        bus = EventBus()
        volume.start_audio(Cfg(dict({"audio.spectrum_enabled": False}, **cfg)), bus)
        return bus

    def test_publishes_error_state_when_enabled(self, monkeypatch):
        bus = self._start(monkeypatch, {"audio.mic_router": True})
        assert bus.get_last("audio.mic_state")[0] == {"state": "error", "source": "", "aec": False}

    def test_silent_when_router_disabled(self, monkeypatch):
        bus = self._start(monkeypatch, {"audio.mic_router": False})
        assert bus.get_last("audio.mic_state") is None
