"""src/audio/spectrum.py — DSP, capture argv and the capture lifecycle.

No real PipeWire: the capture child is a fake process whose stdout is a real
os.pipe (so select() and os.read() behave as in the car); subprocess.Popen,
shutil.which and _pipewire_env are replaced.
"""

import math
import os
import threading
import time

import pytest

np = pytest.importorskip("numpy")

from src.audio import spectrum as sp  # noqa: E402
from src.audio import pipewire_ctrl  # noqa: E402
from src.core.event_bus import EventBus  # noqa: E402


# ── DSP ──────────────────────────────────────────────────────────────────

def _sine(freq, amp=1.0, n=sp.FRAME_SIZE, rate=sp.SAMPLE_RATE):
    t = np.arange(n) / rate
    return amp * np.sin(2 * np.pi * freq * t)


def _centres():
    e = sp.band_edges_hz()
    return [math.sqrt(e[i] * e[i + 1]) for i in range(sp.SPECTRUM_BANDS)]


class TestBands:
    def test_edges_log_spaced_30_to_16k(self):
        e = sp.band_edges_hz()
        assert len(e) == 17
        assert e[0] == pytest.approx(30.0) and e[-1] == pytest.approx(16000.0)
        ratios = [e[i + 1] / e[i] for i in range(16)]
        assert max(ratios) == pytest.approx(min(ratios))

    @pytest.mark.parametrize("frame", [1024, 2048, 4096, 8192])
    def test_bins_no_dc_no_overlap_at_least_one(self, frame):
        bins = sp.band_bins(frame, sp.SAMPLE_RATE)
        assert len(bins) == 16
        assert bins[0][0] >= 1                         # never the DC bin
        for lo, hi in bins:
            assert hi > lo                             # >= 1 bin per band
            assert hi <= frame // 2 + 1
        for (_, hi), (lo, _) in zip(bins, bins[1:]):
            assert lo >= hi                            # no overlap

    def test_bins_follow_edges_at_default_frame(self):
        df = sp.SAMPLE_RATE / sp.FRAME_SIZE
        edges = sp.band_edges_hz()
        for i, (lo, hi) in enumerate(sp.band_bins()):
            # Every bin centre lies inside its band at 4096 points.
            assert edges[i] <= lo * df < edges[i + 1]
            assert (hi - 1) * df < edges[i + 1]
        assert sp.band_bins()[-1][1] * df <= 16000 + df

    @pytest.mark.parametrize("band", range(16))
    def test_sine_at_band_centre_lights_that_band(self, band):
        dsp = sp.SpectrumDSP()
        db = dsp.band_db(_sine(_centres()[band], 0.5))
        assert int(np.argmax(db)) == band
        lvl = dsp.db_to_level(db)
        assert lvl[band] > 0.8
        far = [i for i in range(16) if abs(i - band) > 2]
        assert all(lvl[i] < lvl[band] - 0.3 for i in far)

    def test_full_scale_sine_reads_0_dbfs_and_scaling(self):
        dsp = sp.SpectrumDSP(db_floor=-70, db_ceiling=0)
        b = 9
        f = _centres()[b]
        assert dsp.band_db(_sine(f, 1.0))[b] == pytest.approx(0.0, abs=0.6)
        assert dsp.band_db(_sine(f, 0.1))[b] == pytest.approx(-20.0, abs=0.6)
        lv = dsp.db_to_level(np.array([-80.0, -70.0, -35.0, 0.0, 6.0]))
        assert list(lv) == pytest.approx([0.0, 0.0, 0.5, 1.0, 1.0])

    def test_no_per_frame_normalisation(self):
        """A quiet passage must look quiet (no AGC to the frame peak)."""
        dsp = sp.SpectrumDSP()
        f = _centres()[8]
        loud = dsp.db_to_level(dsp.band_db(_sine(f, 1.0)))[8]
        quiet = dsp.db_to_level(dsp.band_db(_sine(f, 0.01)))[8]
        assert loud > quiet + 0.4

    def test_silence_is_exact_zero(self):
        dsp = sp.SpectrumDSP()
        for _ in range(5):
            lv = dsp.feed(np.zeros(sp.FRAME_SIZE), 0.05)
        assert list(lv) == [0.0] * 16

    def test_garbage_samples_do_not_poison(self):
        dsp = sp.SpectrumDSP()
        x = np.full(sp.FRAME_SIZE, np.nan)
        x[::2] = np.inf
        lv = dsp.feed(x, 0.05)
        assert np.all(np.isfinite(lv))

    def test_attack_fast_release_slow_time_based(self):
        dsp = sp.SpectrumDSP()
        dsp.smooth(np.ones(16), 0.05)
        up = dsp.levels[0]
        assert up > 0.8
        dsp.levels = np.ones(16)
        dsp.smooth(np.zeros(16), 0.05)
        assert 0.7 < dsp.levels[0] < 0.95
        # Two half steps == one full step: depends on time, not call count.
        a, b = sp.SpectrumDSP(), sp.SpectrumDSP()
        a.levels = np.ones(16)
        b.levels = np.ones(16)
        a.smooth(np.zeros(16), 0.1)
        b.smooth(np.zeros(16), 0.05)
        b.smooth(np.zeros(16), 0.05)
        assert a.levels[0] == pytest.approx(b.levels[0])

    def test_tilt_is_around_1k(self):
        flat = sp.SpectrumDSP(tilt_db_per_oct=0.0)
        tilt = sp.SpectrumDSP(tilt_db_per_oct=3.0)
        x = _sine(_centres()[15], 0.5)
        assert tilt.band_db(x)[15] > flat.band_db(x)[15] + 10
        x = _sine(_centres()[0], 0.5)
        assert tilt.band_db(x)[0] < flat.band_db(x)[0] - 10

    def test_bad_window_falls_back(self):
        dsp = sp.SpectrumDSP(db_floor=0, db_ceiling=-10)
        assert (dsp.db_floor, dsp.db_ceiling) == (sp.DEFAULT_DB_FLOOR, sp.DEFAULT_DB_CEILING)


# ── capture argv ─────────────────────────────────────────────────────────

class TestArgv:
    def test_pw_record_targets_sink_monitor(self):
        argv = sp.capture_argv("pw-record", "bcm_eq_sink")
        assert argv[0] == "pw-record"
        assert argv[argv.index("--target") + 1] == "bcm_eq_sink"
        props = argv[argv.index("-P") + 1]
        for p in ("stream.capture.sink=true", "node.name=bcm_spectrum",
                  "node.passive=true"):
            assert p in props
        assert "0" not in argv                         # never "--target 0" (= do not link)
        assert argv[argv.index("--rate") + 1] == "48000"
        assert argv[argv.index("--channels") + 1] == "2"
        assert argv[argv.index("--format") + 1] == "f32"
        assert argv[-1] == "-"

    def test_parec_uses_dot_monitor(self):
        argv = sp.capture_argv("parec", "alsa_output.pci-0000_00_1f.3.analog-stereo")
        assert argv[:3] == ["parec", "-d", "alsa_output.pci-0000_00_1f.3.analog-stereo.monitor"]
        assert "--rate=48000" in argv and "--channels=2" in argv
        assert "--format=float32le" in argv
        # Not moved to another source when the EQ sink goes away.
        assert "--no-move" in argv

    def test_unknown_tool(self):
        with pytest.raises(ValueError):
            sp.capture_argv("arecord", "x")


# ── fakes ────────────────────────────────────────────────────────────────

class FakeProc:
    """A capture child: stdout is the read end of a real pipe."""

    def __init__(self, argv, **kw):
        self.argv = argv
        self.kw = kw
        r, w = os.pipe()
        self.stdout = os.fdopen(r, "rb", buffering=0)
        self._w = w
        self.rc = None
        self.terminated = 0
        self.killed = 0
        self.ignore_term = False
        self.pid = 4242

    def write(self, data: bytes):
        os.write(self._w, data)

    def eof(self):
        if self._w is not None:
            os.close(self._w)
            self._w = None

    def poll(self):
        return self.rc

    def terminate(self):
        self.terminated += 1
        if not self.ignore_term:
            self.rc = -15
            self.eof()

    def kill(self):
        self.killed += 1
        self.rc = -9
        self.eof()

    def wait(self, timeout=None):
        if self.rc is None:
            import subprocess
            raise subprocess.TimeoutExpired(self.argv, timeout)
        return self.rc


class FakePW:
    def __init__(self, sink="bcm_eq_sink", node_id="77", available=True):
        self.available = available
        self.sink = sink
        self.nodes = {sink: node_id} if sink else {}
        self.list_calls = 0

    def music_sink(self):
        return self.sink

    def list_sink_nodes(self):
        self.list_calls += 1
        return [{"id": i, "name": n} for n, i in self.nodes.items()]


def _wait(cond, timeout=5.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.01)
    return False


@pytest.fixture
def rig(monkeypatch):
    monkeypatch.setattr(pipewire_ctrl, "_pipewire_env",
                        lambda: {"XDG_RUNTIME_DIR": "/run/user/1000", "MARK": "pwenv"})
    monkeypatch.setattr(sp, "BACKOFF_MIN_S", 0.01)
    monkeypatch.setattr(sp, "BACKOFF_MAX_S", 0.05)
    monkeypatch.setattr(sp, "TARGET_POLL_S", 0.02)
    monkeypatch.setattr(sp, "TARGET_POLL_MAX_S", 0.05)
    monkeypatch.setattr(sp, "RETARGET_DEBOUNCE_S", 0.1)
    monkeypatch.setattr(sp, "NODE_CHECK_MIN_S", 0.1)
    monkeypatch.setattr(sp, "STALL_RESTART_S", 0.6)
    bus = EventBus()
    procs = []
    state = {"tools": ("pw-record", "parec")}

    def popen(argv, **kw):
        p = FakeProc(argv, **kw)
        procs.append(p)
        return p

    def make(pw=None, config=None):
        a = sp.SpectrumAnalyzer(bus, controller=pw if pw is not None else FakePW(),
                                config=config)
        a._popen = popen
        a._which = lambda t: f"/usr/bin/{t}" if t in state["tools"] else None
        return a

    made = []

    def factory(*a, **k):
        an = make(*a, **k)
        made.append(an)
        return an

    yield bus, procs, factory, state
    for an in made:
        an.stop()
    for p in procs:
        p.eof()
        try:
            p.stdout.close()
        except OSError:
            pass


def _pcm(freq, seconds=0.2, amp=0.5):
    n = int(sp.SAMPLE_RATE * seconds)
    t = np.arange(n) / sp.SAMPLE_RATE
    mono = (amp * np.sin(2 * np.pi * freq * t)).astype("<f4")
    return np.repeat(mono, 2).tobytes()             # interleaved stereo


class TestLifecycle:
    def test_launch_env_target_and_real_data(self, rig):
        bus, procs, make, _ = rig
        an = make()
        an.start()
        assert _wait(lambda: procs)
        p = procs[0]
        assert p.kw["env"]["MARK"] == "pwenv"             # reaches the user session
        assert p.argv[0] == "pw-record"
        assert p.argv[p.argv.index("--target") + 1] == "bcm_eq_sink"
        assert bus.get_last("audio.spectrum_state")[0]["mode"] == "real"
        band = 10
        p.write(_pcm(_centres()[band], 0.3))
        assert _wait(lambda: (bus.get_last("audio.spectrum") or ([0] * 16, 0))[0][band] > 0.5)
        vals = bus.get_last("audio.spectrum")[0]
        assert len(vals) == 16
        assert all(v == round(v, 2) for v in vals)
        assert int(np.argmax(vals)) == band

    def test_hw_sink_without_eq(self, rig):
        _, procs, make, _ = rig
        pw = FakePW(sink="alsa_output.pci-0000_00_1f.3.analog-stereo")
        make(pw).start()
        assert _wait(lambda: procs)
        assert procs[0].argv[procs[0].argv.index("--target") + 1] == pw.sink

    def test_waits_for_target_node(self, rig):
        bus, procs, make, _ = rig
        pw = FakePW()
        pw.nodes = {}
        make(pw).start()
        assert _wait(lambda: (bus.get_last("audio.spectrum_state") or ({},))[0].get("mode") == "waiting")
        time.sleep(0.1)
        assert procs == []                                # no race with the EQ start
        assert bus.get_last("audio.spectrum")[0] == [0.0] * 16
        pw.nodes = {"bcm_eq_sink": "80"}
        assert _wait(lambda: procs)

    def test_relaunch_after_eof(self, rig):
        _, procs, make, _ = rig
        make().start()
        assert _wait(lambda: procs)
        procs[0].write(_pcm(100, 0.1))
        time.sleep(0.05)
        procs[0].rc = 0
        procs[0].eof()
        assert _wait(lambda: len(procs) >= 2)
        assert procs[0].stdout.closed                     # old pipe released

    def test_relaunch_when_eq_node_replaced(self, rig):
        _, procs, make, _ = rig
        pw = FakePW()
        make(pw).start()
        assert _wait(lambda: procs)
        procs[0].write(_pcm(100, 0.1))
        time.sleep(0.05)
        pw.nodes = {"bcm_eq_sink": "99"}                  # EQ chain restarted
        assert _wait(lambda: len(procs) >= 2, 3)
        assert procs[0].terminated >= 1                   # old child reaped

    def test_relaunch_after_stall(self, rig):
        _, procs, make, _ = rig
        make().start()
        assert _wait(lambda: procs)
        assert _wait(lambda: len(procs) >= 2, 3)          # STALL_RESTART_S = 0.6
        assert procs[0].terminated >= 1

    def test_retarget_when_eq_goes_away(self, rig):
        _, procs, make, _ = rig
        pw = FakePW()
        pw.nodes["alsa_output.x"] = "5"
        make(pw).start()
        assert _wait(lambda: procs)
        pw.sink = "alsa_output.x"
        assert _wait(lambda: len(procs) >= 2, 3)
        assert procs[1].argv[procs[1].argv.index("--target") + 1] == "alsa_output.x"

    def test_short_target_blip_is_not_a_retarget(self, rig):
        """The EQ restart briefly reads as "hardware sink" — no relaunch."""
        _, procs, make, _ = rig
        pw = FakePW()
        make(pw).start()
        assert _wait(lambda: procs)
        stop = threading.Event()

        def feed():                                   # keep data flowing
            while not stop.is_set():
                try:
                    procs[0].write(_pcm(100, 0.02))
                except OSError:
                    return
                time.sleep(0.02)

        t = threading.Thread(target=feed, daemon=True)
        t.start()
        pw.sink = "alsa_output.x"
        time.sleep(0.03)
        pw.sink = "bcm_eq_sink"
        time.sleep(0.3)
        stop.set()
        t.join(1)
        assert len(procs) == 1

    def test_falls_back_to_parec_when_pw_record_dies(self, rig):
        _, procs, make, _ = rig
        make().start()
        assert _wait(lambda: procs)
        procs[0].rc = 1
        procs[0].eof()                                    # no data at all
        assert _wait(lambda: len(procs) >= 2)
        assert procs[1].argv[0] == "parec"
        assert procs[1].argv[2] == "bcm_eq_sink.monitor"

    def test_live_node_check_while_data_flows(self, rig, monkeypatch):
        """A moved stream keeps delivering data: only the node id tells."""
        monkeypatch.setattr(sp, "NODE_CHECK_MAX_S", 0.3)
        _, procs, make, state = rig
        state["tools"] = ("parec",)
        pw = FakePW()
        make(pw).start()
        assert _wait(lambda: procs)
        stop = threading.Event()

        def feed():
            while not stop.is_set():
                try:
                    procs[0].write(_pcm(100, 0.02))
                except OSError:
                    return
                time.sleep(0.02)

        t = threading.Thread(target=feed, daemon=True)
        t.start()
        time.sleep(0.1)
        pw.nodes = {"bcm_eq_sink": "99"}                  # EQ restarted, data still flows
        try:
            assert _wait(lambda: len(procs) >= 2, 3)
        finally:
            stop.set()
            t.join(1)
        assert procs[0].terminated >= 1

    def test_no_pw_dump_while_pw_record_data_flows(self, rig, monkeypatch):
        """pw-record (node.dont-reconnect) is not re-checked during music:
        a full pw-dump every 15 s was load on the audio graph for nothing."""
        monkeypatch.setattr(sp, "NODE_CHECK_MAX_S", 0.1)
        _, procs, make, _ = rig
        pw = FakePW()
        make(pw).start()
        assert _wait(lambda: procs)
        stop = threading.Event()

        def feed():
            while not stop.is_set():
                try:
                    procs[0].write(_pcm(100, 0.02))
                except OSError:
                    return
                time.sleep(0.02)

        t = threading.Thread(target=feed, daemon=True)
        t.start()
        try:
            time.sleep(0.2)
            calls = pw.list_calls
            time.sleep(0.8)
            assert pw.list_calls == calls, "no node listing while data flows"
            assert len(procs) == 1
        finally:
            stop.set()
            t.join(1)

    def test_eof_after_node_replaced_keeps_pw_record(self, rig):
        """pw-record ends because its node went away in a pause — not a tool failure."""
        _, procs, make, _ = rig
        pw = FakePW()
        make(pw).start()
        assert _wait(lambda: procs)
        pw.nodes = {"bcm_eq_sink": "99"}
        procs[0].rc = 0
        procs[0].eof()                                    # no data at all
        assert _wait(lambda: len(procs) >= 2)
        assert procs[1].argv[0] == "pw-record"

    def test_back_to_pw_record_after_node_replaced(self, rig):
        _, procs, make, _ = rig
        pw = FakePW()
        make(pw).start()
        assert _wait(lambda: procs)
        procs[0].rc = 1
        procs[0].eof()                                    # pw-record broken
        assert _wait(lambda: len(procs) >= 2)
        assert procs[1].argv[0] == "parec"
        procs[1].write(_pcm(100, 0.05))
        time.sleep(0.05)
        pw.nodes = {"bcm_eq_sink": "99"}                  # EQ chain restarted
        procs[1].rc = 0
        procs[1].eof()                                    # parec --no-move ends
        assert _wait(lambda: len(procs) >= 3)
        assert procs[2].argv[0] == "pw-record"

    def test_routine_relaunch_does_not_grow_backoff(self, rig):
        _, procs, make, _ = rig
        an = make()
        an.start()
        assert _wait(lambda: len(procs) >= 3, 5)          # two pause stalls
        assert an._backoff == sp.BACKOFF_MIN_S

    def test_pw_give_up_measured_from_current_outage(self, rig, monkeypatch):
        _, _, make, _ = rig
        pw = FakePW()
        an = make(pw)
        t = [1000.0]
        an._clock = lambda: t[0]
        assert an._simulated_reason() is None
        t[0] += 500.0
        pw.available = False                              # outage starts late
        assert an._simulated_reason() is None             # grace, not instant
        t[0] += sp.PW_GIVE_UP_S
        assert an._simulated_reason() == "PipeWire did not come up"
        pw.available = True
        assert an._simulated_reason() is None

    def test_stop_terminates_waits_kills_joins(self, rig):
        _, procs, make, _ = rig
        an = make()
        an.start()
        assert _wait(lambda: procs)
        p = procs[0]
        p.ignore_term = True                              # stubborn child
        t = an._thread
        an.stop()
        assert p.terminated >= 1 and p.killed >= 1
        assert not t.is_alive()
        assert an._proc is None
        n = len(procs)
        time.sleep(0.1)
        assert len(procs) == n                            # nothing relaunched

    def test_silence_publishes_zeros(self, rig):
        bus, procs, make, _ = rig
        make().start()
        assert _wait(lambda: procs)
        procs[0].write(np.zeros(sp.SAMPLE_RATE // 5 * 2, dtype="<f4").tobytes())
        time.sleep(0.2)
        assert bus.get_last("audio.spectrum")[0] == [0.0] * 16

    def test_config_db_floor(self, rig):
        _, _, make, _ = rig
        an = make(config={"audio.spectrum_db_floor": -50.0, "audio.spectrum_db_ceiling": -5,
                          "audio.spectrum_tilt_db_per_oct": "junk"})
        assert (an._db_floor, an._db_ceiling, an._tilt) == (-50.0, -5.0, 0.0)


class TestSimulated:
    def test_only_without_capture_tools(self, rig, caplog):
        bus, procs, make, state = rig
        state["tools"] = ()
        bus.publish("bt.media_playing", True)
        make().start()
        assert _wait(lambda: (bus.get_last("audio.spectrum_state") or ({},))[0].get("mode") == "simulated")
        assert procs == []
        assert "pw-record" in bus.get_last("audio.spectrum_state")[0]["reason"]
        assert _wait(lambda: any((bus.get_last("audio.spectrum") or ([0],))[0]))

    def test_without_numpy(self, rig, monkeypatch):
        bus, procs, make, _ = rig
        monkeypatch.setattr(sp, "HAS_NUMPY", False)
        make().start()
        assert _wait(lambda: (bus.get_last("audio.spectrum_state") or ({},))[0].get("mode") == "simulated")
        assert procs == []

    def test_real_mode_ignores_media_playing(self, rig):
        """No fake bars tied to bt.media_playing while capturing for real."""
        bus, procs, make, _ = rig
        bus.publish("bt.media_playing", True)
        make().start()
        assert _wait(lambda: procs)
        time.sleep(0.3)
        assert bus.get_last("audio.spectrum_state")[0]["mode"] == "real"
        assert bus.get_last("audio.spectrum")[0] == [0.0] * 16

    def test_pipewire_late_is_waiting_not_simulated(self, rig):
        bus, procs, make, _ = rig
        pw = FakePW(available=False)
        make(pw).start()
        assert _wait(lambda: (bus.get_last("audio.spectrum_state") or ({},))[0].get("mode") == "waiting")
        pw.available = True
        assert _wait(lambda: procs)

    def test_pipewire_never_up_goes_simulated_and_back(self, rig, monkeypatch):
        bus, procs, make, _ = rig
        monkeypatch.setattr(sp, "PW_GIVE_UP_S", 0.1)
        monkeypatch.setattr(sp, "SIMULATED_RECHECK_S", 0.05)
        pw = FakePW(available=False)
        make(pw).start()
        assert _wait(lambda: (bus.get_last("audio.spectrum_state") or ({},))[0].get("mode") == "simulated")
        pw.available = True
        assert _wait(lambda: procs)
        assert bus.get_last("audio.spectrum_state")[0]["mode"] == "real"


# ── controller hook ──────────────────────────────────────────────────────

class TestMusicSink:
    def _ctrl(self, monkeypatch):
        monkeypatch.setattr(pipewire_ctrl, "_run_cmd", lambda *a, **k: (1, "", ""))
        cfg = {"audio.eq_dsp_enabled": True}
        c = pipewire_ctrl.PipeWireController(type("C", (), {"get": lambda s, k, d=None: cfg.get(k, d)})(),
                                             EventBus())
        c._hw_sink = "alsa_output.hw"
        return c

    def test_eq_alive(self, monkeypatch):
        c = self._ctrl(monkeypatch)
        c._eq_proc = type("P", (), {"poll": lambda s: None})()
        assert c.music_sink() == "bcm_eq_sink"

    def test_eq_dead_or_off(self, monkeypatch):
        c = self._ctrl(monkeypatch)
        assert c.music_sink() == "alsa_output.hw"
        c._eq_proc = type("P", (), {"poll": lambda s: 1})()
        assert c.music_sink() == "alsa_output.hw"


def test_start_audio_hands_controller_to_spectrum(monkeypatch):
    from unittest import mock
    from src.audio import volume

    pw_ctrl = mock.MagicMock(available=False, hardware_sink=None)
    monkeypatch.setattr(volume, "PipeWireController", lambda c, b: pw_ctrl)
    seen = {}

    class Spy:
        def __init__(self, bus, controller=None, config=None):
            seen["controller"] = controller
            seen["config"] = config

        def start(self):
            seen["started"] = True

        def stop(self):
            seen["stopped"] = True

    monkeypatch.setattr(volume, "SpectrumAnalyzer", Spy)
    cfg = {"audio.mic_router": False}
    conf = type("C", (), {"get": lambda s, k, d=None: cfg.get(k, d)})()
    bus = EventBus()
    volume.start_audio(conf, bus)
    assert seen["controller"] is pw_ctrl and seen["config"] is conf and seen["started"]
    bus.publish("power.shutting_down", True)
    assert _wait(lambda: seen.get("stopped"))



class TestReviewFixes:
    def test_real_failure_drops_the_bars(self, rig):
        """A child that breaks by itself (node intact) zeroes the bars
        instead of freezing the last frame through the backoff."""
        bus, procs, make, _ = rig
        make().start()
        assert _wait(lambda: procs)
        procs[0].write(_pcm(100, 0.2))
        assert _wait(lambda: any(bus.get_last("audio.spectrum")[0])
                     if bus.get_last("audio.spectrum") else False)
        procs[0].rc = 1
        procs[0].eof()                                    # breaks, node still there
        assert _wait(lambda: bus.get_last("audio.spectrum")[0] == [0.0] * 16)

    def test_listing_hiccup_does_not_kill_capture(self, rig, monkeypatch):
        """pw-dump + wpctl failing once (empty list) is "could not list",
        not "node gone"."""
        monkeypatch.setattr(sp, "NODE_CHECK_MAX_S", 0.1)  # live check often
        _, procs, make, state = rig
        state["tools"] = ("parec",)       # the live check runs for parec only
        pw = FakePW()
        an = make(pw)
        an.start()
        assert _wait(lambda: procs)
        stop = threading.Event()

        def feed():
            while not stop.is_set():
                try:
                    procs[0].write(_pcm(100, 0.02))
                except OSError:
                    return
                time.sleep(0.02)

        t = threading.Thread(target=feed, daemon=True)
        t.start()
        try:
            pw.nodes = {}                                 # listing fails
            calls = pw.list_calls
            assert _wait(lambda: pw.list_calls >= calls + 3, 3)
            assert len(procs) == 1 and procs[0].terminated == 0
            assert an.state["mode"] == "real"
        finally:
            stop.set()
            t.join(1)

    def test_node_id_distinguishes_unknown_from_absent(self, rig):
        _, _, make, _ = rig
        pw = FakePW()
        an = make(pw)
        assert an._node_id("bcm_eq_sink") == "77"
        assert an._node_id("other") is None
        pw.nodes = {}
        assert an._node_id("bcm_eq_sink") is sp._NODE_UNKNOWN

        def boom():
            raise RuntimeError("pw-dump")
        pw.list_sink_nodes = boom
        assert an._node_id("bcm_eq_sink") is sp._NODE_UNKNOWN

    def test_restart_after_stop_timeout_leaves_one_loop(self, rig):
        """stop() that gave up on a stuck thread, then start(): the old
        thread must exit instead of running a second capture loop."""
        _, procs, make, _ = rig
        pw = FakePW()
        gate = threading.Event()
        entered = threading.Event()
        real = pw.list_sink_nodes

        def slow():
            if not gate.is_set():
                entered.set()
                gate.wait(5)                              # stuck "pw-dump"
            return real()
        pw.list_sink_nodes = slow
        an = make(pw)
        an.start()
        assert entered.wait(3)
        old = an._thread
        an.stop(timeout=0.05)
        assert old.is_alive()                             # gave up waiting
        an.start()
        new = an._thread
        assert new is not old
        gate.set()
        old.join(3)
        assert not old.is_alive()                         # superseded thread left
        assert _wait(lambda: procs)
        assert new.is_alive() and an._owner is new
