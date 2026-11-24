"""Spoken announcements (plan Partia 12, stage 6): modules.voice_announce.

* src/audio/voice_announce.py — queue (priority, dedupe, staleness, rate
  limit, call deferral), playback argv/env/target, the worker step and the
  audio.voice_announcement signal around it;
* src/audio/tts.py — Piper → espeak-ng fallback, text on stdin (never in
  argv), private temp files, the phrase cache;
* src/audio/pipewire_ctrl.py MusicDucker — audio.music_gain applied to the
  EQ output stream (or the music streams), restore on stop / crash;
* web_viewer — /api/config fields, the payload summary, POST /api/voice/test;
* install scripts — install-piper.sh with SHA-256 verification.

No process is started and no PipeWire is touched: every runner is a fake.
"""

from __future__ import annotations

import json
import os
import re
import stat
import subprocess
import threading
import wave
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.audio import announce_api
from src.audio import pipewire_ctrl as pwc
from src.audio import tts
from src.audio import voice_announce as va
from src.core import modules_catalog
from src.core.config import BCMConfig
from src.core.event_bus import EventBus

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "config" / "scripts"
SECRET = "sk-THIS-MUST-NEVER-LEAK-123"


class FakeClock:
    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t

    def advance(self, dt):
        self.t += dt


WALL0 = 1.8e9


def _req(category="weather", text="Uwaga, oblodzenie.", priority="normal", key=None,
         now=WALL0, ttl_s=300):
    r = announce_api.make_request(category, text, priority=priority, key=key, now=now,
                                  ttl_s=ttl_s)
    assert r is not None
    return r


def _queue(**over):
    s = va.Settings(**over)
    clock, wall = FakeClock(), FakeClock(WALL0)
    return va.AnnounceQueue(s, clock=clock, wall=wall), clock, wall


# ── queue ────────────────────────────────────────────────────────────────

class TestQueue:
    def test_danger_first_then_fifo(self):
        q, clock, _ = _queue(min_gap_s=0, max_per_min=20)
        q.offer(_req(text="a", priority="low"))
        q.offer(_req(text="b", priority="normal"))
        q.offer(_req(text="c", priority="high"))
        q.offer(_req(text="d", priority="normal"))
        order = []
        while (item := q.next(blocked=False)) is not None:
            order.append(item.req["text"])
            q.mark_spoken(item)
        assert order == ["c", "b", "d", "a"]

    def test_same_key_within_window_is_not_spoken_twice(self):
        q, clock, _ = _queue(dedupe_s=300, min_gap_s=0)
        assert q.offer(_req(key="weather_ice")) == "queued"
        q.mark_spoken(q.next(False))
        clock.advance(299)
        assert q.offer(_req(key="weather_ice")) == "duplicate"
        clock.advance(2)
        assert q.offer(_req(key="weather_ice")) == "queued"

    def test_without_key_the_text_dedupes(self):
        q, clock, _ = _queue(min_gap_s=0)
        q.offer(_req(text="Korek na S8."))
        q.mark_spoken(q.next(False))
        assert q.offer(_req(text="Korek na S8.")) == "duplicate"
        assert q.offer(_req(text="Korek na A4.")) == "queued"

    def test_newer_request_replaces_the_queued_one_and_keeps_priority(self):
        q, _, _ = _queue()
        q.offer(_req(key="traffic_x", text="stare", priority="high"))
        assert q.offer(_req(key="traffic_x", text="nowe", priority="low")) == "replaced"
        assert len(q) == 1
        item = q.next(False)
        assert item.req["text"] == "nowe" and item.req["priority"] == "high"

    def test_stale_items_are_dropped(self):
        q, clock, _ = _queue(max_age_s=60)
        q.offer(_req())
        clock.advance(61)
        assert q.next(False) is None and len(q) == 0 and q.dropped == 1

    def test_producer_expiry_is_honoured(self):
        q, _, wall = _queue()
        q.offer(_req(ttl_s=10))
        wall.advance(11)
        assert q.next(False) is None

    def test_rate_limit_per_minute_and_gap_high_exempt(self):
        q, clock, _ = _queue(max_per_min=2, min_gap_s=3, max_age_s=300)
        for i in range(4):
            q.offer(_req(text=f"n{i}"))
        q.mark_spoken(q.next(False))
        assert q.next(False) is None            # min gap
        clock.advance(3)
        q.mark_spoken(q.next(False))
        clock.advance(3)
        assert q.next(False) is None            # 2 per minute used
        q.offer(_req(text="niebezpieczne", priority="high"))
        item = q.next(False)
        assert item is not None and item.req["priority"] == "high"
        q.mark_spoken(item)
        clock.advance(58)                       # only the high one is in the last minute
        assert q.next(False) is not None

    def test_call_defers_then_drops(self):
        q, clock, _ = _queue(call_defer_s=45, max_age_s=60)
        q.offer(_req(text="a"))
        assert q.next(blocked=True) is None and len(q) == 1
        clock.advance(30)
        assert q.next(blocked=True) is None and len(q) == 1
        clock.advance(16)
        assert q.next(blocked=True) is None and len(q) == 0

    def test_short_call_then_spoken(self):
        q, clock, _ = _queue(call_defer_s=45)
        q.offer(_req(text="a"))
        assert q.next(blocked=True) is None
        clock.advance(20)
        item = q.next(blocked=False)
        assert item is not None and item.req["text"] == "a"

    def test_full_queue_drops_the_least_important(self):
        q, _, _ = _queue(max_queue=2)
        q.offer(_req(text="a", priority="low"))
        q.offer(_req(text="b", priority="normal"))
        assert q.offer(_req(text="c", priority="high")) == "queued"
        assert sorted(i.req["text"] for i in q._items) == ["b", "c"]
        assert q.offer(_req(text="d", priority="low")) == "full"


# ── settings / offer ─────────────────────────────────────────────────────

def _cfg(**values):
    cfg = BCMConfig(platform_override="x86", local_path=None, env={})
    cfg.save = lambda path=None: None
    for k, v in values.items():
        cfg.set(k.replace("__", "."), v)
    return cfg


class TestSettings:
    def test_bounds(self):
        cfg = _cfg(voice_announce__volume=500, voice_announce__max_age_s=1,
                   voice_announce__call_defer_s=999, voice_announce__max_per_min="x")
        s = va.load_settings(cfg.get)
        assert s.volume == 100 and s.max_age_s == 10 and s.call_defer_s == 10
        assert s.max_per_min == va.DEFAULTS["max_per_min"]

    def test_defaults_without_block(self):
        s = va.load_settings(_cfg().get)
        assert s.enabled is True and s.categories == {"weather": True, "traffic": True,
                                                       "system": True}


class FakeSynth:
    def __init__(self, engine="piper", path="/x/phrase.wav", fail=False):
        self._engine = engine
        self.path = path
        self.fail = fail
        self.texts = []

    def engine(self):
        return self._engine

    def synthesize(self, text):
        self.texts.append(text)
        if self._engine == "none":
            return None, "no_engine"
        return (None, "synth_failed") if self.fail else (self.path, self._engine)

    def chime(self):
        return "/x/chime.wav"


class FakePlayer:
    def __init__(self, result="ok", on_play=None):
        self.result = result
        self.played = []
        self.on_play = on_play
        self.stopped = 0

    def backend(self):
        return "pw-play"

    def begin(self):
        pass

    def play(self, path, target, volume):
        self.played.append((path, target, volume))
        if self.on_play:
            self.on_play()
        if isinstance(self.result, Exception):
            raise self.result
        return self.result

    def stop(self):
        self.stopped += 1


class FakePW:
    available = True

    def voice_sink(self):
        return "alsa_output.usb-DAC.analog-stereo"


def _announcer(cfg=None, synth=None, player=None, bus=None):
    bus = bus or EventBus()
    clock, wall = FakeClock(), FakeClock(WALL0)
    mod = va.VoiceAnnouncer(bus, cfg or _cfg(), synth=synth or FakeSynth(),
                            player=player or FakePlayer(), clock=clock, wall=wall,
                            sleep=lambda s: None, ducker_factory=lambda pw, b: None)
    events = []
    bus.subscribe(va.VOICE_TOPIC, lambda t, v, ts: events.append(v))
    return SimpleNamespace(mod=mod, bus=bus, clock=clock, wall=wall, events=events)


class TestOffer:
    def test_invalid_and_test_category_from_the_bus(self):
        a = _announcer()
        assert a.mod.offer({"text": "x"}) == "invalid"
        assert a.mod.offer(_req(category="test")) == "invalid"
        assert a.mod.offer("garbage") == "invalid"

    def test_category_switch_and_runtime_off(self):
        a = _announcer(_cfg(voice_announce__categories={"weather": False}))
        assert a.mod.offer(_req(category="weather")) == "category_off"
        assert a.mod.offer(_req(category="traffic", text="t")) == "queued"
        b = _announcer(_cfg(voice_announce__enabled=False))
        assert b.mod.offer(_req()) == "disabled"

    def test_config_changed_applies_live_and_clears(self):
        cfg = _cfg()
        a = _announcer(cfg)
        a.mod.start()
        try:
            a.mod.offer(_req())
            cfg.set("voice_announce.enabled", False)
            a.bus.publish("config.changed", {"voice_enabled": False})
            assert len(a.mod.queue) == 0 and a.mod.offer(_req(text="x")) == "disabled"
        finally:
            a.mod.stop()


# ── the worker step ──────────────────────────────────────────────────────

class TestStep:
    def test_speaks_with_ducking_signal_around_playback(self):
        a = _announcer()
        a.bus.publish("audio._internals", {"pipewire": FakePW()})
        a.mod.offer(_req(text="Uwaga, ślisko."))
        assert a.mod.step() is True
        assert a.events == [True, False]
        chime, phrase = a.mod.player.played
        assert chime[0] == "/x/chime.wav" and phrase[0] == "/x/phrase.wav"
        assert phrase[1] == "alsa_output.usb-DAC.analog-stereo" and phrase[2] == 0.8
        assert a.mod.status()["last_result"] == "spoken"

    def test_ducking_released_even_when_the_player_crashes(self):
        a = _announcer(player=FakePlayer(result=RuntimeError("boom")))
        a.mod.offer(_req())
        with pytest.raises(RuntimeError):
            a.mod.step()
        assert a.events == [True, False]

    def test_never_during_a_call(self):
        a = _announcer()
        a.mod.start()
        try:
            a.bus.publish("bt.call_state", "active")
            a.mod.offer(_req())
            assert a.mod.step() is False and a.mod.player.played == []
            assert a.mod.speak_test() == "call_active"
            a.bus.publish("bt.call_state", "idle")
            assert a.mod.step() is True and a.events[-2:] == [True, False]
        finally:
            a.mod.stop()

    def test_call_starting_mid_phrase_stops_the_player_and_requeues(self):
        holder = {}

        def on_play():
            holder["a"].bus.publish("audio.phone_call", True)
        player = FakePlayer(result="interrupted", on_play=on_play)
        a = _announcer(player=player)
        holder["a"] = a
        a.mod.start()
        try:
            a.mod.offer(_req())
            a.mod.step()
            assert player.stopped >= 1 and len(a.mod.queue) == 1
            assert a.events[-1] is False
        finally:
            a.mod.stop()

    def test_call_starting_in_chime_is_never_played_over(self):
        class ChimeCall(FakeSynth):
            def chime(self):
                holder["a"].bus.publish("bt.call_state", "ringing")
                return "/x/chime.wav"
        holder = {}
        a = _announcer(synth=ChimeCall())
        holder["a"] = a
        a.mod.start()
        try:
            a.mod.offer(_req())
            assert a.mod.step() is True
            assert a.mod.player.played == [] and len(a.mod.queue) == 1
            assert True not in a.events
        finally:
            a.mod.stop()

    def test_call_after_begin_interrupts_the_real_player(self, tmp_path):
        popened = []
        player = va.Player(popen=lambda *a, **k: popened.append(a) or None,
                           which=lambda n: "/usr/bin/" + n, env=lambda: {})
        a = _announcer(player=player)
        a.mod.start()
        try:
            player.begin()
            a.bus.publish("audio.phone_call", True)   # not _speaking yet
            wav = tmp_path / "p.wav"
            _wav(wav)
            assert player.play(str(wav), None, 1) == "interrupted" and popened == []
        finally:
            a.mod.stop()

    def test_shutdown_never_blocks_the_bus(self, monkeypatch):
        a = _announcer()
        gate = threading.Event()
        monkeypatch.setattr(a.mod, "stop", lambda: gate.wait(5))
        t0 = __import__("time").monotonic()
        a.mod._on_shutdown("power.shutting_down", True, 0.0)
        assert __import__("time").monotonic() - t0 < 1.0 and a.mod.player.stopped == 1
        gate.set()

    def test_quiet_when_parking(self):
        a = _announcer()
        a.mod.start()
        try:
            a.bus.publish("parking.active", True)
            a.mod.offer(_req())
            assert a.mod.step() is False
        finally:
            a.mod.stop()

    def test_no_engine_degrades_to_one_notification(self):
        a = _announcer(synth=FakeSynth(engine="none"))
        a.mod.offer(_req(text="a"))
        a.mod.offer(_req(text="b"))
        a.mod.step()
        a.clock.advance(10)
        a.mod.step()
        notes = a.bus.get_last("system.notifications")[0]
        assert [n["key"] for n in notes] == ["voice_no_engine"]
        assert a.events == [] and a.mod.status()["last_result"] == "no_engine"
        assert a.mod.speak_test() == "no_engine"

    def test_speak_test_is_a_fixed_phrase_even_when_disabled(self):
        synth = FakeSynth()
        a = _announcer(_cfg(voice_announce__enabled=False), synth=synth)
        assert a.mod.speak_test() == "queued"
        a.mod.step()
        assert synth.texts == [va.TEST_PHRASE]

    def test_status_has_no_text(self):
        a = _announcer()
        a.mod.offer(_req(text=SECRET))
        assert SECRET not in json.dumps(a.mod.status())


# ── synthesis ────────────────────────────────────────────────────────────

def _wav(path, seconds=0.1):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(22050)
        w.writeframes(b"\x00\x00" * int(22050 * seconds))


class FakeTTSRunner:
    """Writes a WAV to the path after -w / --output_file; records argv+stdin."""

    def __init__(self, fail=()):
        self.calls = []
        self.fail = set(fail)

    def __call__(self, argv, data, timeout):
        self.calls.append((list(argv), data, timeout))
        name = "piper" if argv[0].endswith("piper") else "espeak"
        if name in self.fail:
            return 1, "error"
        flag = "--output_file" if name == "piper" else "-w"
        _wav(argv[argv.index(flag) + 1])
        return 0, ""


@pytest.fixture
def piper_files(tmp_path):
    binary = tmp_path / "piper" / "piper"
    binary.parent.mkdir()
    binary.write_text("#!/bin/sh\n")
    binary.chmod(0o755)
    model = tmp_path / "voice.onnx"
    model.write_bytes(b"x")
    (tmp_path / "voice.onnx.json").write_text("{}")
    return str(binary), str(model)


def _synth(tmp_path, piper_files=None, runner=None, espeak=True, **kw):
    pb, model = piper_files or ("/nonexistent/piper", "/nonexistent/m.onnx")
    return tts.Synthesizer(piper_bin=pb, model=model, cache_dir=str(tmp_path / "voice_cache"),
                           runner=runner or FakeTTSRunner(),
                           which=lambda n: "/usr/bin/espeak-ng" if espeak else None, **kw)


class TestSynthesis:
    TEXT = "Uwaga --help $(rm -rf /) <speak>oblodzenie</speak>"

    def test_text_goes_to_stdin_never_argv(self, tmp_path, piper_files):
        runner = FakeTTSRunner()
        s = _synth(tmp_path, piper_files, runner)
        path, engine = s.synthesize(self.TEXT)
        assert engine == "piper" and path and tts.wav_ok(path)
        argv, data, timeout = runner.calls[0]
        assert argv[:3] == [piper_files[0], "--model", piper_files[1]]
        joined = " ".join(argv)
        for word in ("Uwaga", "oblodzenie", "help", "rm"):
            assert word not in joined
        text = data.decode()
        assert "oblodzenie" in text and "<" not in text and ">" not in text
        assert text.endswith("\n") and timeout <= 120

    def test_output_is_private(self, tmp_path, piper_files):
        s = _synth(tmp_path, piper_files)
        path, _ = s.synthesize("Test.")
        assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
        assert stat.S_IMODE(os.stat(tmp_path / "voice_cache").st_mode) == 0o700

    def test_fallback_to_espeak_when_piper_fails(self, tmp_path, piper_files):
        runner = FakeTTSRunner(fail={"piper"})
        s = _synth(tmp_path, piper_files, runner)
        path, engine = s.synthesize("Test.")
        assert engine == "espeak" and path
        argv, data, _ = runner.calls[1]
        assert argv[:3] == ["/usr/bin/espeak-ng", "-v", "pl"] and "--stdin" in argv
        assert b"Test." in data and "Test." not in argv
        # no temporary files left behind
        assert not [p for p in os.listdir(tmp_path / "voice_cache") if p.startswith(".tts.")]

    def test_espeak_only_without_piper_model(self, tmp_path):
        s = _synth(tmp_path)
        assert s.engine() == "espeak"
        assert s.synthesize("Test.")[1] == "espeak"

    def test_no_engine(self, tmp_path):
        s = _synth(tmp_path, espeak=False)
        assert s.engine() == "none"
        assert s.synthesize("Test.") == (None, "no_engine")

    def test_piper_needs_the_model_json(self, tmp_path, piper_files):
        os.unlink(piper_files[1] + ".json")
        assert _synth(tmp_path, piper_files, espeak=False).engine() == "none"

    def test_cache_hit_does_not_run_again(self, tmp_path, piper_files):
        runner = FakeTTSRunner()
        s = _synth(tmp_path, piper_files, runner)
        p1, _ = s.synthesize("Ten sam tekst.")
        p2, _ = s.synthesize("Ten sam tekst.")
        assert p1 == p2 and len(runner.calls) == 1

    def test_cache_is_bounded(self, tmp_path, piper_files):
        s = _synth(tmp_path, piper_files)
        s.cache_max_bytes = 6000
        for i in range(5):
            s.synthesize(f"Zdanie {i}.")
        total = sum(os.path.getsize(tmp_path / "voice_cache" / n) for n in os.listdir(tmp_path / "voice_cache"))
        assert total <= 6000

    def test_bad_output_is_rejected(self, tmp_path, piper_files):
        def runner(argv, data, timeout):
            Path(argv[argv.index("--output_file") + 1]).write_bytes(b"not a wav" * 100)
            return 0, ""
        s = _synth(tmp_path, piper_files, runner, espeak=False)
        assert s.synthesize("Test.") == (None, "synth_failed")

    def test_tts_text(self):
        assert tts.tts_text("a\x00b\nc  <d>") == "a b c d"
        assert len(tts.tts_text("x" * 1000)) == tts.MAX_TTS_TEXT
        assert tts.tts_text(None) == ""

    def test_child_env_has_no_secrets(self, monkeypatch):
        monkeypatch.setenv("BCM_OWM_API_KEY", SECRET)
        assert SECRET not in json.dumps(tts._child_env())

    def test_chime_is_a_valid_wav(self, tmp_path):
        s = _synth(tmp_path)
        path = s.chime()
        assert tts.wav_ok(path) and 0.2 < tts.wav_duration(path) < 0.5


# ── playback ─────────────────────────────────────────────────────────────

class FakeProc:
    def __init__(self, rc=0):
        self.rc = rc
        self.terminated = False

    def wait(self, timeout=None):
        return self.rc

    def terminate(self):
        self.terminated = True

    def kill(self):
        pass


class TestPlayer:
    def test_pw_play_argv_env_target(self, tmp_path, monkeypatch):
        monkeypatch.setenv("BCM_TOMTOM_API_KEY", SECRET)
        monkeypatch.setattr(pwc, "_pipewire_env",
                            lambda: dict(os.environ, XDG_RUNTIME_DIR="/run/user/1000"))
        calls = []

        def popen(argv, **kw):
            calls.append((argv, kw))
            return FakeProc()
        wav = tmp_path / "p.wav"
        _wav(wav)
        player = va.Player(popen=popen, which=lambda n: "/usr/bin/" + n)
        assert player.play(str(wav), "alsa_output.usb-DAC", 0.75) == "ok"
        argv, kw = calls[0]
        assert argv[0] == "pw-play" and argv[-1] == str(wav)
        assert argv[argv.index("--target") + 1] == "alsa_output.usb-DAC"
        assert "bcm_eq_sink" not in argv
        assert argv[argv.index("--volume") + 1] == "0.75"
        assert argv[argv.index("--media-role") + 1] == "Notification"
        assert "node.name = bcm_voice" in argv[argv.index("-P") + 1]
        assert kw["env"]["XDG_RUNTIME_DIR"] == "/run/user/1000"
        assert SECRET not in json.dumps(kw["env"])

    def test_paplay_fallback_and_none(self, tmp_path):
        argv = va.Player.argv("paplay", "/x.wav", "sink", 0.5)
        assert argv[0] == "paplay" and "--device=sink" in argv and "--volume=32768" in argv
        assert va.Player(which=lambda n: None).play("/x.wav", None, 1) == "no_player"

    def test_timeout_kills(self, tmp_path):
        class Hang(FakeProc):
            def wait(self, timeout=None):
                if not self.terminated:
                    raise subprocess.TimeoutExpired("pw-play", timeout)
                return -15
        proc = Hang()
        wav = tmp_path / "p.wav"
        _wav(wav)
        player = va.Player(popen=lambda *a, **k: proc, which=lambda n: "/usr/bin/" + n,
                           env=lambda: {})
        assert player.play(str(wav), None, 1) == "failed" and proc.terminated


# ── real ducking ─────────────────────────────────────────────────────────

def _node(oid, name, cls="Stream/Output/Audio", **props):
    p = {"node.name": name, "media.class": cls}
    p.update(props)
    return {"id": oid, "type": "PipeWire:Interface:Node", "info": {"props": p}}


class FakeRunner:
    def __init__(self, objects):
        self.objects = objects
        self.calls = []
        self.fail_ids = set()

    def __call__(self, cmd, timeout=5.0):
        self.calls.append(list(cmd))
        if cmd[0] == "pw-dump":
            return 0, json.dumps(self.objects), ""
        if cmd[:2] == ["wpctl", "set-volume"] and cmd[2] in self.fail_ids:
            return 1, "", "no such node"
        return 0, "", ""

    def volumes(self):
        return [c[2:] for c in self.calls if c[:2] == ["wpctl", "set-volume"]]


class FakeController:
    def __init__(self, eq=True):
        self.available = True
        self.eq = eq
        self.output_configured = threading.Event()
        self.output_configured.set()

    def music_sink(self):
        return pwc.EQ_SINK_NAME if self.eq else "alsa_output.usb"


GRAPH = [
    _node(40, "bcm_eq_sink", cls="Audio/Sink"),
    _node(41, pwc.EQ_OUTPUT_NODE),
    _node(50, "mpv"),
    _node(51, "bcm_voice", **{"media.role": "Notification"}),
    _node(52, "bluez_call", **{"media.role": "Phone"}),
    _node(53, "alsa_output.usb", cls="Audio/Sink"),
    _node(54, "bcm_aec_playback"),
]


def _ducker(tmp_path, eq=True, objects=GRAPH):
    runner = FakeRunner(objects)
    bus = EventBus()
    d = pwc.MusicDucker(FakeController(eq), bus, runner=runner,
                        state_path=str(tmp_path / "duck.json"), clock=FakeClock())
    return d, runner, bus


class TestDucking:
    def test_db_to_gain(self):
        assert pwc.db_to_gain(0) == 1.0
        assert abs(pwc.db_to_gain(-12) - 0.2512) < 1e-3
        for bad in (None, "x", True, float("nan"), float("inf")):
            assert pwc.db_to_gain(bad) == 1.0
        assert pwc.db_to_gain(5) == 1.0

    def test_targets_eq_and_streams(self):
        assert pwc.duck_targets(GRAPH, True) == [("41", pwc.EQ_OUTPUT_NODE)]
        # Streams mode: BCM's own bcm_* streams (chain output, AEC playback) stay.
        assert pwc.duck_targets(GRAPH, False) == [("50", "mpv")]

    def test_apply_then_restore_sequence(self, tmp_path):
        d, runner, _ = _ducker(tmp_path)
        d.apply(0.25)
        assert runner.calls[0] == ["pw-dump"]
        assert runner.volumes() == [["41", "0.630"]]
        assert json.loads((tmp_path / "duck.json").read_text()) == {"names": [pwc.EQ_OUTPUT_NODE]}
        d.apply(0.5)                                    # fade step: cached id
        assert runner.calls.count(["pw-dump"]) == 1
        d.apply(1.0)
        assert runner.volumes()[-1] == ["41", "1.000"]
        assert not (tmp_path / "duck.json").exists() and d.applied_gain == 1.0

    def test_user_volume_is_never_touched(self, tmp_path):
        d, runner, _ = _ducker(tmp_path, eq=False)
        d.apply(0.25)
        d.apply(1.0)
        flat = json.dumps(runner.calls)
        assert "@DEFAULT_AUDIO_SINK@" not in flat
        assert ["51", "0.630"] not in runner.volumes() and ["52", "0.630"] not in runner.volumes()
        assert ["50", "0.630"] in runner.volumes() and ["50", "1.000"] in runner.volumes()

    def test_vanished_node_is_resolved_again(self, tmp_path):
        d, runner, _ = _ducker(tmp_path)
        d.apply(0.25)
        runner.fail_ids.add("41")
        d.apply(0.3)
        d.apply(0.35)
        assert runner.calls.count(["pw-dump"]) == 2

    def test_bus_sequence_with_worker_and_stop_restores(self, tmp_path):
        d, runner, bus = _ducker(tmp_path)
        d.start()
        try:
            bus.publish("audio.music_gain", -12.0)
            for _ in range(200):
                if ["41", "0.631"] in runner.volumes():
                    break
                threading.Event().wait(0.01)
            assert ["41", "0.631"] in runner.volumes()
        finally:
            d.stop()
        assert runner.volumes()[-1] == ["41", "1.000"]
        assert not (tmp_path / "duck.json").exists()

    def test_call_forces_full_volume(self, tmp_path):
        d, runner, bus = _ducker(tmp_path)
        d.start()
        try:
            bus.publish("bt.call_state", "active")
            bus.publish("audio.music_gain", -15.0)
            threading.Event().wait(0.2)
            assert not [v for v in runner.volumes() if v[1] != "1.000"]
        finally:
            d.stop()

    def test_startup_restores_what_a_crash_left(self, tmp_path):
        (tmp_path / "duck.json").write_text(json.dumps({"names": ["mpv", "bad name!"]}))
        d, runner, _ = _ducker(tmp_path, eq=False)
        d.restore_leftovers()
        assert sorted(runner.volumes()) == [["41", "1.000"], ["50", "1.000"]]
        assert not (tmp_path / "duck.json").exists()

    def test_wpctl_gets_the_cubic_scale(self, tmp_path):
        d, runner, _ = _ducker(tmp_path)
        for db, sent in ((-12.0, "0.631"), (-18.0, "0.501"), (-15.0, "0.562")):
            runner.calls.clear()
            d.apply(pwc.db_to_gain(db))
            arg = runner.volumes()[-1][1]
            assert arg == sent
            assert abs(float(arg) ** 3 - pwc.db_to_gain(db)) < 1e-3
        d.apply(1.0)
        assert runner.volumes()[-1] == ["41", "1.000"]

    def test_internal_streams_are_not_ducked(self):
        targets = dict(pwc.duck_targets(GRAPH, False))
        assert "54" not in targets and "51" not in targets and "52" not in targets

    def test_failed_restore_is_retried(self, tmp_path, monkeypatch):
        monkeypatch.setattr(pwc, "DUCK_RESTORE_BACKOFF_S", (0.05, 0.05, 0.05))
        d, runner, bus = _ducker(tmp_path)
        d.start()
        try:
            bus.publish("audio.music_gain", -12.0)
            for _ in range(200):
                if ["41", "0.631"] in runner.volumes():
                    break
                threading.Event().wait(0.01)
            runner.fail_ids.add("41")                     # busy PipeWire
            bus.publish("audio.music_gain", 0.0)
            for _ in range(100):
                if runner.volumes().count(["41", "1.000"]) >= 1:
                    break
                threading.Event().wait(0.01)
            threading.Event().wait(0.02)
            assert (tmp_path / "duck.json").exists()      # kept while it fails
            runner.fail_ids.clear()
            for _ in range(300):
                if not (tmp_path / "duck.json").exists():
                    break
                threading.Event().wait(0.01)
            assert not (tmp_path / "duck.json").exists()
            assert runner.volumes()[-1] == ["41", "1.000"]
            assert runner.volumes().count(["41", "1.000"]) >= 2
        finally:
            d.stop()

    def test_failed_restore_of_a_vanished_node_ends(self, tmp_path):
        d, runner, _ = _ducker(tmp_path, eq=False)
        d.apply(0.25)
        runner.fail_ids.update({"41", "50"})
        assert d.restore_all() is False
        assert (tmp_path / "duck.json").exists()
        runner.objects = [o for o in GRAPH if o["id"] not in (41, 50)]   # both gone
        d._retry_restore()
        assert d._retry_pause() is None and not (tmp_path / "duck.json").exists()

    def test_retries_are_bounded(self, tmp_path):
        d, runner, _ = _ducker(tmp_path)
        d.apply(0.25)
        runner.fail_ids.add("41")
        d.restore_all()
        n = 0
        while d._retry_pause() is not None:
            d._retry_restore()
            n += 1
            assert n <= len(pwc.DUCK_RESTORE_BACKOFF_S)
        assert n == len(pwc.DUCK_RESTORE_BACKOFF_S)
        assert (tmp_path / "duck.json").exists()          # left for the next start

    def test_phone_fade_back_is_ignored(self, tmp_path):
        from src.audio.ducking import DuckingManager
        d, runner, bus = _ducker(tmp_path)
        DuckingManager(bus)
        d.start()
        try:
            bus.publish("audio.phone_call", True)
            bus.publish("audio.phone_call", False)        # fade-back from -15 dB (1 s)
            threading.Event().wait(1.3)
            assert not [v for v in runner.volumes() if v[1] != "1.000"]
            bus.publish("parking.active", True)           # a real duck again
            for _ in range(200):
                if ["41", "0.501"] in runner.volumes():
                    break
                threading.Event().wait(0.01)
            assert ["41", "0.501"] in runner.volumes()
        finally:
            d.stop()

    def test_leftovers_restored_when_module_off(self, tmp_path):
        from src.audio import volume
        state = tmp_path / "duck.json"
        state.write_text(json.dumps({"names": ["mpv"]}))
        runner = FakeRunner(GRAPH)
        t = pwc.restore_duck_leftovers(FakeController(False), EventBus(), runner=runner,
                                       state_path=str(state))
        t.join(5)
        assert sorted(runner.volumes()) == [["41", "1.000"], ["50", "1.000"]]
        assert not state.exists()
        # No state file: nothing runs at all (production start unchanged).
        runner2 = FakeRunner(GRAPH)
        assert pwc.restore_duck_leftovers(FakeController(), EventBus(), runner=runner2,
                                          state_path=str(state)) is None
        assert runner2.calls == []
        # start_audio's hook: only while the module is OFF.
        seen = []
        import src.audio.pipewire_ctrl as real
        orig = real.restore_duck_leftovers
        try:
            real.restore_duck_leftovers = lambda pw, bus: seen.append(pw) or None
            volume._restore_duck_leftovers(_cfg(modules__voice_announce=True), "pw", EventBus())
            assert seen == []
            volume._restore_duck_leftovers(_cfg(modules__voice_announce=False), "pw", EventBus())
            assert seen == ["pw"]
        finally:
            real.restore_duck_leftovers = orig

    def test_with_ducking_manager_voice_end_fades_back(self, tmp_path):
        from src.audio.ducking import DuckingManager
        d, runner, bus = _ducker(tmp_path)
        DuckingManager(bus)
        gains = []
        bus.subscribe("audio.music_gain", lambda t, v, ts: gains.append(v))
        bus.publish(va.VOICE_TOPIC, True)
        assert gains[-1] == -12.0
        d.apply(pwc.db_to_gain(gains[-1]))
        bus.publish(va.VOICE_TOPIC, False)
        for _ in range(300):
            if gains and gains[-1] == 0.0:
                break
            threading.Event().wait(0.01)
        assert gains[-1] == 0.0 and len(gains) > 5          # the existing smooth fade
        d.apply(pwc.db_to_gain(gains[-1]))
        assert runner.volumes()[-1] == ["41", "1.000"]


# ── catalog / web ────────────────────────────────────────────────────────

def test_catalog_entry():
    info = modules_catalog.MODULES["voice_announce"]
    assert info["default"] is False and info["requires"] == ("audio",)
    assert info["entry"] == ("src.audio.voice_announce", "start_voice_announce")
    st = modules_catalog.resolve(modules_catalog.MODULES,
                                 {**{n: False for n in modules_catalog.MODULES},
                                  "voice_announce": True}, set())
    assert st["voice_announce"].runs is False


class TestWeb:
    @pytest.fixture
    def web(self, monkeypatch):
        from src.dashboard.web_viewer import WebViewer
        bus = EventBus()
        cfg = _cfg(modules__voice_announce=True)
        viewer = WebViewer(host="127.0.0.1", port=5098, event_bus=bus, config=cfg)
        calls = []
        fake = SimpleNamespace(speak_test=lambda: calls.append(1) or "queued")
        monkeypatch.setattr(va, "get_voice_announcer", lambda: fake)
        return SimpleNamespace(bus=bus, cfg=cfg, viewer=viewer, calls=calls, fake=fake,
                               client=viewer._build_app().test_client())

    def test_config_fields(self):
        from src.dashboard import web_viewer as wv
        ups, err = wv._validate_config_update({"voice_enabled": False, "voice_volume": 55.0,
                                               "voice_cat_traffic": True})
        assert err is None
        assert ("voice_volume", "voice_announce.volume", 55) in ups
        for bad in ({"voice_volume": 5}, {"voice_volume": True}, {"voice_volume": "80"},
                    {"voice_enabled": "yes"}, {"voice_cat_weather": 1}):
            assert wv._validate_config_update(bad)[1] is not None

    def test_config_post_reaches_the_module(self, web):
        cfg = web.cfg
        mod = va.VoiceAnnouncer(web.bus, cfg, synth=FakeSynth(), player=FakePlayer(),
                                ducker_factory=lambda pw, b: None)
        web.bus.subscribe("config.changed", mod._on_config_changed)
        res = web.client.post("/api/config", json={"voice_volume": 40,
                                                   "voice_cat_weather": False})
        assert res.status_code == 200
        assert mod.settings.volume == 40 and mod.settings.categories["weather"] is False

    def test_summary_whitelists(self):
        from src.dashboard import web_viewer as wv
        assert wv._voice_summary(None) is None
        out = wv._voice_summary({"enabled": True, "volume": 80, "engine": "<img>",
                                 "player": "pw-play", "queue": -1, "text": SECRET,
                                 "categories": {"weather": True, "x": True},
                                 "last_result": "spoken", "ducking": "eq"})
        assert out["engine"] == "none" and out["queue"] == 0
        assert out["categories"] == {"weather": True, "traffic": False, "system": False}
        assert SECRET not in json.dumps(out)

    def test_payload_carries_the_status(self, web):
        web.bus.publish(va.STATUS_TOPIC, {"enabled": True, "volume": 70, "engine": "espeak"})
        data = web.viewer._get_dashboard_data()
        assert data["voice_announce"]["engine"] == "espeak"

    def test_test_route(self, web):
        res = web.client.post("/api/voice/test", json={"text": SECRET})
        assert res.status_code == 202 and web.calls == [1]
        res = web.client.post("/api/voice/test")
        assert res.status_code == 429 and int(res.headers["Retry-After"]) >= 1

    @pytest.mark.parametrize("addr, base", [
        ("10.0.0.5", "http://localhost"),
        ("127.0.0.1", "http://evil.example:5002"),
    ])
    def test_test_route_kiosk_only(self, web, addr, base):
        res = web.client.post("/api/voice/test", environ_base={"REMOTE_ADDR": addr},
                              base_url=base)
        assert res.status_code == 403 and web.calls == []

    def test_test_route_not_running_and_errors(self, web, monkeypatch):
        monkeypatch.setattr(va, "get_voice_announcer", lambda: None)
        assert web.client.post("/api/voice/test").status_code == 409
        monkeypatch.setattr(va, "get_voice_announcer",
                            lambda: SimpleNamespace(speak_test=lambda: "no_engine"))
        web.viewer._voice_test_last = None
        res = web.client.post("/api/voice/test")
        assert res.status_code == 409 and res.get_json()["error"] == "no_engine"


# ── install scripts ──────────────────────────────────────────────────────

class TestScripts:
    def test_syntax(self):
        for name in ("install-piper.sh", "setup-x86.sh", "apply-fixes.sh", "cleanup-x86.sh"):
            res = subprocess.run(["bash", "-n", str(SCRIPTS / name)], capture_output=True)
            assert res.returncode == 0, res.stderr

    def test_installer_verifies_every_file(self):
        code = (SCRIPTS / "install-piper.sh").read_text()
        assert "sha256sum" in code and 'if [ "$got" != "$want" ]' in code
        assert "no SHA-256 listed" in code
        assert "--proto '=https'" in code
        assert re.search(r"grep -qE '\^/\|\(\^\|/\)\\\.\\\.", code)    # path traversal guard
        assert "exit 0" in code.splitlines()[-1]
        # every download goes through fetch_verified
        curl_lines = [ln for ln in code.splitlines() if ln.strip().startswith("if ! curl")]
        assert len(curl_lines) == 1
        assert code.count("fetch_verified \"") == 2

    def test_hash_list_holds_only_real_lines(self):
        lines = [ln for ln in (SCRIPTS / "piper-sha256.txt").read_text().splitlines()
                 if ln and not ln.startswith("#")]
        assert lines == ["a50cb45f355b7af1f6d758c1b360717877ba0a398cc8cbe6d2a7a3a26e225992"
                         "  piper_linux_x86_64.tar.gz"]

    def test_no_secrets_or_private_data(self):
        for name in ("install-piper.sh", "piper-sha256.txt"):
            text = (SCRIPTS / name).read_text()
            assert not re.search(r"(api[_-]?key|token|password)\s*=", text, re.I)
            assert not re.search(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", text)

    def test_callers(self):
        for name in ("setup-x86.sh", "apply-fixes.sh"):
            code = (SCRIPTS / name).read_text()
            assert "apt-get install -y espeak-ng || true" in code
            assert "command -v espeak-ng >/dev/null 2>&1" in code
            assert 'bash "$BCM_DIR/config/scripts/install-piper.sh" ||' in code
        assert "rm -rf /opt/bcm/piper" in (SCRIPTS / "cleanup-x86.sh").read_text()
        assert "/piper/" in (ROOT / ".gitignore").read_text()

    def test_config_defaults_match_the_installer(self):
        code = (SCRIPTS / "install-piper.sh").read_text()
        assert "VOICE=pl_PL-gosia-medium" in code
        assert tts.DEFAULT_MODEL == "/opt/bcm/piper/voices/pl_PL-gosia-medium.onnx"
        assert tts.DEFAULT_PIPER_BIN == "/opt/bcm/piper/piper/piper"
        test_cfg = (ROOT / "config" / "bcm_config_test.yaml").read_text()
        assert f"model: {tts.DEFAULT_MODEL}" in test_cfg
        assert f"piper_bin: {tts.DEFAULT_PIPER_BIN}" in test_cfg
