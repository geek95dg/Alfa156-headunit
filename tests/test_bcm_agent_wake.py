"""Budzenie komputera w aucie podczerwienią (plan E) in the Termux agent
(tools/car_phone/termux/bcm_agent.py: ``WAKE <kod>`` SMS, ``--wake``,
:func:`wake_ir`, the NEC pattern) and the Termux:Widget script ``wake.sh``.

No Termux here: every phone command goes through a fake runner that refuses
anything unexpected (the parking guard's, plus ``termux-infrared-transmit``),
state lives in tmp_path, nothing can send a real SMS or an IR frame.

Covers: the NEC pattern (bit order, inverse, 3 frames 108 ms apart, decoded
back by an independent Python decoder AND by the firmware's own decoder in
sensor_hub/wake_logic.h compiled with g++), the fixed argv, the toggle, the
phone-side rate limit (per minute, hour, day; a failed transmit only counts
for the cooldown), the file lock between the agent and ``--wake``, the SMS
command with TOTP (wrong / replayed codes, unknown senders, the toggles —
WAKE works with the parking guard off, PARK commands then do not; with the
guard off BCM sends no whitelist, so the tests push exactly what BCM sends
and set the numbers on the phone, and without them the agent warns once),
the GSM-7 replies, the config hash compatibility (a false ``remote_session`` is
invisible to the hash, ``wake_*`` count only while it is on), the CLI exit
codes and ``bash -n`` of wake.sh.
"""

from __future__ import annotations

import io
import json
import logging
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from tests import test_bcm_agent_park as park

A = park.A
OWNER, OWNER2, STRANGER = park.OWNER, park.OWNER2, park.STRANGER
REPO = park.REPO
WAKE_SH = REPO / "tools" / "car_phone" / "termux" / "wake.sh"
WAKE_LOGIC = REPO / "arduino" / "sensor_hub" / "wake_logic.h"
ADDR, CMD = 0x7A15, 0x56


# ── the NEC pattern ──────────────────────────────────────────────────────

def decode_nec(durations):
    """Independent decoder: (address, command, inverse) per frame."""
    frames, i = [], 0
    while i < len(durations):
        assert durations[i] == 9000 and durations[i + 1] == 4500
        bits = 0
        for b in range(32):
            mark, space = durations[i + 2 + 2 * b], durations[i + 3 + 2 * b]
            assert mark == 562 and space in (562, 1687)
            bits |= (space == 1687) << b
        assert durations[i + 66] == 562
        frames.append((bits & 0xFFFF, (bits >> 16) & 0xFF, (bits >> 24) & 0xFF))
        i += 67
        if i < len(durations):
            i += 1                        # the gap between frames
    return frames


class TestNecPattern:
    def test_frame_layout_and_values(self):
        frame = A.nec_frame(ADDR, CMD)
        assert len(frame) == 67 and frame[:2] == [9000, 4500] and frame[-1] == 562
        assert decode_nec(frame) == [(ADDR, CMD, CMD ^ 0xFF)]

    @pytest.mark.parametrize("addr, cmd", [(0, 0), (0xFFFF, 0xFF), (0x00FF, 0x01), (0x1234, 0xA5)])
    def test_round_trip(self, addr, cmd):
        assert decode_nec(A.nec_pattern(addr, cmd)) == [(addr, cmd, cmd ^ 0xFF)] * 3

    def test_three_frames_108_ms_apart(self):
        pat = A.nec_pattern(ADDR, CMD)
        assert len(pat) == 3 * 67 + 2
        frame = A.nec_frame(ADDR, CMD)
        assert sum(pat[:68]) == 108000 and sum(pat[68:136]) == 108000
        assert pat[67] == 108000 - sum(frame) and pat[67] > 30000   # >> any NEC space
        assert sum(pat) < 400000           # far under ConsumerIrManager's 2 s

    @pytest.mark.parametrize("addr, cmd", [(-1, 0), (0x10000, 0), (0, 256), (0, -1),
                                           (True, 0), (0, False), ("1", 0), (1.0, 0),
                                           (None, 0), (0, [1])])
    def test_only_integers_in_range(self, addr, cmd):
        assert A.nec_pattern(addr, cmd) is None

    def test_argv_is_fixed(self):
        argv = A.ir_argv(A.nec_pattern(ADDR, CMD))
        assert argv[:3] == ["termux-infrared-transmit", "-f", "38000"] and len(argv) == 4
        assert re.fullmatch(r"[0-9]+(,[0-9]+)*", argv[3])
        for bad in ([], [0], [1, "2"], [True], [1] * 401, "9000,4500", [300000]):
            with pytest.raises(ValueError):
                A.ir_argv(bad)

    def test_the_firmware_decoder_accepts_it(self, tmp_path):
        """The agent's pattern through sensor_hub/wake_logic.h itself (the
        same necEdge the pin-change interrupt calls): 3 frames → 3 decoded
        frames with the private code → exactly ONE wake request."""
        gxx = shutil.which("g++")
        if not gxx:
            pytest.skip("g++ not available")
        src = tmp_path / "decode.cpp"
        src.write_text('#include "wake_logic.h"\n#include <cstdio>\n'
                       'int main() { NecDecoder d; necInit(d); WakeLogic w; uint32_t wt = '
                       'wakeBoot(w, 0); PwrLogic p; pwrInit(p, true, 0); WakeIn in = WakeIn(); '
                       'WakeOut o; wt += 2000; wakeStep(w, p, wt, 0, in, o);\n'
                       'unsigned long v; uint32_t t = 4000000000UL; bool mark = true; '
                       'int frames = 0, pairs = 0; necEdge(d, false, t - 50000);\n'
                       'while (scanf("%lu", &v) == 1) { necEdge(d, mark, t); t += v; '
                       'mark = !mark; if (d.ready) { frames++; '
                       'if (wakeIrFrame(w, d.addr, d.cmd, wt + frames * 108)) pairs++; '
                       'printf("%04x %02x\\n", d.addr, d.cmd); d.ready = false; } }\n'
                       'necEdge(d, mark, t); if (d.ready) { frames++; if (wakeIrFrame(w, '
                       'd.addr, d.cmd, wt + frames * 108)) pairs++; printf("%04x %02x\\n", '
                       'd.addr, d.cmd); }\nprintf("frames=%d pairs=%d\\n", frames, pairs); '
                       'return 0; }\n', encoding="utf-8")
        exe = tmp_path / "decode"
        build = subprocess.run([gxx, "-std=c++17", "-Wall", "-Werror", f"-I{WAKE_LOGIC.parent}",
                                "-o", str(exe), str(src)], capture_output=True, text=True,
                               timeout=120)
        assert build.returncode == 0, build.stderr
        pattern = A.nec_pattern(ADDR, CMD)
        run = subprocess.run([str(exe)], input=" ".join(map(str, pattern)),
                             capture_output=True, text=True, timeout=60)
        assert run.returncode == 0, run.stderr
        lines = run.stdout.split()
        assert lines.count("7a15") == 3 and lines.count("56") == 3
        assert "frames=3" in run.stdout and "pairs=1" in run.stdout
        # The defaults on both sides are the same code.
        assert (A.WAKE_DEFAULTS["wake_ir_address"], A.WAKE_DEFAULTS["wake_ir_command"]) == \
            (ADDR, CMD)


# ── wake_ir: toggle, rate limit, lock ────────────────────────────────────

class Tx:
    def __init__(self, ok=True, why=""):
        self.calls = []
        self.ok, self.why = ok, why

    def __call__(self, pattern):
        self.calls.append(list(pattern))
        return self.ok, self.why


def _cfg(on=True, **wake):
    cfg = A.default_config()
    cfg["toggles"]["remote_session"] = on
    cfg.update(wake)
    return cfg


class TestWakeIr:
    def test_off_sends_nothing(self, tmp_path):
        tx = Tx()
        assert A.wake_ir(str(tmp_path), tx, _cfg(False), park.T0, "sms") == "off"
        assert tx.calls == [] and not (tmp_path / A.WAKE_FILE).exists()

    def test_sent_and_recorded(self, tmp_path):
        tx = Tx()
        assert A.wake_ir(str(tmp_path), tx, _cfg(), park.T0, "local") == "sent"
        assert tx.calls == [A.nec_pattern(ADDR, CMD)]
        st = json.loads((tmp_path / A.WAKE_FILE).read_text())
        assert st["sent"] == [park.T0] and st["last"] == {"wall": int(park.T0),
                                                          "result": "sent", "source": "local"}
        assert oct((tmp_path / A.WAKE_FILE).stat().st_mode & 0o777) == "0o600"

    def test_custom_code_from_config(self, tmp_path):
        tx = Tx()
        A.wake_ir(str(tmp_path), tx, _cfg(wake_ir_address=0x1234, wake_ir_command=0x9A),
                  park.T0, "sms")
        assert decode_nec(tx.calls[0])[0] == (0x1234, 0x9A, 0x65)

    @pytest.mark.parametrize("bad", [{"wake_ir_address": "0x7A15"}, {"wake_ir_command": 300},
                                     {"wake_ir_address": None}])
    def test_bad_code_is_not_sent(self, tmp_path, bad):
        tx = Tx()
        assert A.wake_ir(str(tmp_path), tx, _cfg(**bad), park.T0, "sms") == "failed"
        assert tx.calls == []

    def test_rate_limits(self, tmp_path):
        tx, d, t = Tx(), str(tmp_path), park.T0
        assert A.wake_ir(d, tx, _cfg(), t, "sms") == "sent"
        assert A.wake_ir(d, tx, _cfg(), t + 30, "sms") == "rate"          # 1 per minute
        assert A.wake_ir(d, tx, _cfg(), t + 61, "sms") == "sent"
        assert A.wake_ir(d, tx, _cfg(), t + 122, "sms") == "sent"
        assert A.wake_ir(d, tx, _cfg(), t + 183, "sms") == "rate"         # 3 per hour
        assert len(tx.calls) == 3
        for i in range(3):
            assert A.wake_ir(d, tx, _cfg(), t + 3700 + 61 * i, "sms") == "sent"
        assert A.wake_ir(d, tx, _cfg(), t + 9000, "sms") == "rate"        # 6 per day
        assert A.wake_ir(d, tx, _cfg(), t + 86401, "sms") == "sent"       # a day later
        assert len(tx.calls) == 7

    def test_failed_transmit_counts_for_the_cooldown_only(self, tmp_path):
        d, t = str(tmp_path), park.T0
        broken = Tx(ok=False, why="No infrared emitter")
        assert A.wake_ir(d, broken, _cfg(), t, "sms") == "failed"
        assert A.wake_ir(d, broken, _cfg(), t + 10, "sms") == "rate"
        assert A.wake_ir(d, Tx(ok=False, why="no_ir"), _cfg(), t + 61, "sms") == "no_ir"
        ok = Tx()
        for i in range(3):
            assert A.wake_ir(d, ok, _cfg(), t + 122 + 61 * i, "sms") == "sent"

    def test_garbage_state_file_is_ignored(self, tmp_path):
        (tmp_path / A.WAKE_FILE).write_text('{"tries": ["x", 1e400, null], "sent": "no"}')
        assert A.wake_ir(str(tmp_path), Tx(), _cfg(), park.T0, "sms") == "sent"
        (tmp_path / A.WAKE_FILE).write_text("not json")
        assert A.wake_ir(str(tmp_path), Tx(), _cfg(), park.T0 + 100, "sms") == "sent"

    def test_clock_jump_back_does_not_unlock(self, tmp_path):
        d, t = str(tmp_path), park.T0
        A.wake_ir(d, Tx(), _cfg(), t, "sms")
        assert A.wake_ir(d, Tx(), _cfg(), t - 20, "sms") == "rate"

    def test_lock_held_by_another_process_is_busy(self, tmp_path):
        fcntl = pytest.importorskip("fcntl")
        fd = os.open(tmp_path / A.WAKE_LOCK_FILE, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            tx = Tx()
            assert A.wake_ir(str(tmp_path), tx, _cfg(), park.T0, "local",
                             lock_wait_s=0.2) == "busy"
            assert tx.calls == []
        finally:
            os.close(fd)
        assert A.wake_ir(str(tmp_path), Tx(), _cfg(), park.T0, "local") == "sent"

    def test_transmit_that_raises_does_not_escape(self, tmp_path):
        def boom(pattern):
            raise RuntimeError("binder died")
        assert A.wake_ir(str(tmp_path), boom, _cfg(), park.T0, "sms") == "failed"


class TestPhoneTransmit:
    def _phone(self, rc=0, out="", err=""):
        calls = []

        def runner(argv, stdin, timeout):
            calls.append((list(argv), stdin, timeout))
            return rc, out, err
        return A.Phone(runner, lambda: 0.0), calls

    def test_success_is_rc0_and_no_output(self):
        phone, calls = self._phone()
        assert phone.ir_transmit(A.nec_pattern(ADDR, CMD)) == (True, "")
        argv, stdin, timeout = calls[0]
        assert argv[:3] == ["termux-infrared-transmit", "-f", "38000"] and stdin is None
        assert 0 < timeout <= 20

    def test_text_on_output_is_a_failure(self):
        phone, _ = self._phone(out="No infrared emitter found\n")
        ok, why = phone.ir_transmit(A.nec_pattern(ADDR, CMD))
        assert ok is False and "infrared" in why

    def test_missing_api_and_bad_pattern(self):
        phone, calls = self._phone(rc=A.RC_MISSING)
        assert phone.ir_transmit(A.nec_pattern(ADDR, CMD)) == (False, "no_ir")
        phone, calls = self._phone()
        assert phone.ir_transmit(["9000; rm -rf /"]) == (False, "bad_pattern") and calls == []


# ── the SMS command ──────────────────────────────────────────────────────

class WakeRunner(park.Runner):
    """The parking guard's fake phone plus the IR transmitter."""

    def __init__(self, clock):
        super().__init__(clock)
        self.ir = []
        self.ir_out = ""

    def __call__(self, argv, stdin, timeout):
        if argv and argv[0] == "termux-infrared-transmit":
            assert argv[:3] == ["termux-infrared-transmit", "-f", "38000"] and len(argv) == 4
            assert re.fullmatch(r"[0-9,]+", argv[3]) and stdin is None
            self.calls.append(list(argv))
            self.ir.append(argv[3])
            return 0, self.ir_out, ""
        return super().__call__(argv, stdin, timeout)


TOGGLES_WAKE_ONLY = {"crash_sms": True, "parking_guard": False, "cabin_watch": False,
                     "call112": False, "remote_session": True}


@pytest.fixture
def wrunner(clock):
    return WakeRunner(clock)


def bcm_wake_only_config():
    """What BCM really pushes with ``modules.remote_session`` on and
    ``modules.parking_guard`` off (car_phone_agent.desired_config): the
    toggle and the IR code, and NO park_* keys — the WAKE whitelist then has
    to come from the phone itself (``--park-numbers``)."""
    from src.core.config import BCMConfig
    from src.network import car_phone_agent as cpa
    cfg = BCMConfig(config_path=str(REPO / "config" / "bcm_config_test.yaml"),
                    platform_override="x86", local_path=None, env={})
    for name in ("car_phone", "car_phone_agent", "input", "remote_session"):
        cfg.set(f"modules.{name}", True)
    cfg.set("modules.parking_guard", False)
    desired = cpa.desired_config(cfg)
    assert desired["toggles"]["remote_session"] is True
    assert desired["toggles"]["parking_guard"] is False
    assert not [k for k in desired if k.startswith("park_")], desired
    return desired


def wake_only_env(tmp_path, clock, wrunner, spawn, numbers=True):
    env = park.Env(tmp_path, clock, wrunner, spawn, toggles=TOGGLES_WAKE_ONLY)
    status, out = env.peer.req("PUT", "/v1/config", bcm_wake_only_config())
    assert status == 200, out
    assert env.agent.config["park_numbers"] == []       # nothing from BCM
    if numbers:
        assert A.write_park_numbers(env.dir, f"{OWNER},{OWNER2}", out=io.StringIO()) == 0
    return env


@pytest.fixture
def wenv(tmp_path, clock, wrunner, spawn):
    return wake_only_env(tmp_path, clock, wrunner, spawn)


clock = park.clock
spawn = park.spawn


class TestWakeSms:
    def test_wake_with_the_parking_guard_off(self, wenv):
        wenv.sms_in(f"wake {wenv.code()}")
        wenv.step()
        assert len(wenv.runner.ir) == 1
        assert decode_nec([int(v) for v in wenv.runner.ir[0].split(",")])[0][:2] == (ADDR, CMD)
        wenv.send()
        assert wenv.runner.sms == [(OWNER, "ALFA 156: BUDZENIE wyslane")]
        assert wenv.view()["state"] == "off"            # the alarm itself stays off

    def test_without_numbers_on_the_phone_it_warns_once(self, tmp_path, clock, wrunner, spawn,
                                                        caplog):
        """The parking guard off: BCM sends no park_numbers, none set on the
        phone — WAKE cannot work. Not silently: one warning naming the fix,
        and the inbox is never read (no code used up)."""
        env = wake_only_env(tmp_path, clock, wrunner, spawn, numbers=False)
        with caplog.at_level(logging.WARNING, logger="bcm_agent"):
            for _ in range(3):
                env.sms_in(f"WAKE {env.code()}")
                env.step()
                env.clock.advance(31)
        assert env.runner.progs("termux-sms-list") == []
        assert env.runner.ir == [] and env.runner.sms == []
        warned = [r.getMessage() for r in caplog.records
                  if "no numbers for SMS commands" in r.getMessage()]
        assert len(warned) == 1 and "--park-numbers" in warned[0]
        assert env.view()["numbers_n"] == 0
        # Set on the phone → the next SMS works.
        assert A.write_park_numbers(env.dir, OWNER, out=io.StringIO()) == 0
        env.sms_in(f"WAKE {env.code()}")
        env.step()
        assert len(env.runner.ir) == 1

    def test_park_commands_are_ignored_while_the_guard_is_off(self, wenv):
        wenv.sms_in(f"PARK ON {wenv.code()}")
        wenv.step()
        wenv.send()
        assert wenv.runner.sms == [] and wenv.guard.st["totp_last"] is None   # code not used
        assert wenv.view()["state"] == "off"

    def test_wake_is_ignored_while_its_toggle_is_off(self, tmp_path, clock, wrunner, spawn):
        env = park.Env(tmp_path, clock, wrunner, spawn)       # parking_guard on, no wake
        env.sms_in(f"WAKE {env.code()}")
        env.step()
        env.send()
        assert env.runner.ir == [] and env.runner.sms == []
        assert env.guard.st["totp_last"] is None

    def test_unknown_sender_and_wrong_code(self, wenv):
        wenv.sms_in(f"WAKE {wenv.code()}", number=STRANGER)
        wenv.step()
        assert wenv.runner.ir == [] and wenv.guard.st["totp_last"] is None
        wenv.sms_in("WAKE 000000")
        wenv.step()
        wenv.send()
        assert wenv.runner.ir == []
        assert wenv.runner.sms_texts() == ["ALFA 156: POSTOJ zly albo zuzyty kod."]

    def test_replayed_code_is_refused(self, wenv):
        code = wenv.code()
        wenv.sms_in(f"WAKE {code}")
        wenv.step()
        wenv.clock.advance(150)                          # past the reply cooldown
        wenv.sms_in(f"WAKE {code}")
        wenv.step()
        wenv.send()
        assert len(wenv.runner.ir) == 1
        assert wenv.runner.sms_texts()[-1] == "ALFA 156: POSTOJ zly albo zuzyty kod."

    def test_second_wake_within_a_minute_is_limited(self, wenv):
        wenv.sms_in(f"WAKE {wenv.code()}", number=OWNER)
        wenv.step()
        wenv.clock.advance(31)                           # next TOTP step, same minute
        wenv.sms_in(f"WAKE {wenv.code()}", number=OWNER2)
        wenv.step()
        wenv.send()
        assert len(wenv.runner.ir) == 1
        assert sorted(wenv.runner.sms) == [
            (OWNER, "ALFA 156: BUDZENIE wyslane"),
            (OWNER2, "ALFA 156: BUDZENIE odrzucone - limit (1 na minute, 3 na godzine, "
                     "6 na dobe)")]

    def test_transmit_failure_is_reported(self, wenv):
        wenv.runner.ir_out = "No infrared emitter found"
        wenv.sms_in(f"WAKE {wenv.code()}")
        wenv.step()
        wenv.send()
        assert wenv.runner.sms_texts() == [
            "ALFA 156: BUDZENIE nieudane - brak nadajnika IR albo blad Termux:API"]

    def test_replies_are_gsm7(self):
        for result in A.WAKE_RESULTS:
            text = A.wake_reply_text("ALFA 156", result)
            assert set(text) <= park.GSM7, (result, text)
            assert A.sms_segments(text) == 1

    def test_command_parser(self):
        assert A.parse_park_command("wake 123 456") == ("wake", "123456")
        assert A.parse_park_command("WAKE123456") == ("wake", "123456")
        for bad in ("WAKE", "WAKE 12345", "WAKE 1234567", "WAKEUP 123456", "BUDZ 123456"):
            assert A.parse_park_command(bad) is None


# ── config hash compatibility ────────────────────────────────────────────

class TestConfigHash:
    def test_false_toggle_is_invisible(self):
        old_form = A.default_config()
        old_form["toggles"] = {k: False for k in ("crash_sms", "parking_guard", "cabin_watch",
                                                   "call112")}
        old_form = {k: v for k, v in old_form.items() if not k.startswith("wake_")}
        new, _ = A.normalize_config(A.default_config(), strict=False)
        assert new["toggles"]["remote_session"] is False
        assert A.config_hash(new) == A.config_hash(old_form)
        # an agent <= 1.3.0 sees the toggles without remote_session too
        changed = dict(new, wake_ir_address=1)
        assert A.config_hash(changed) == A.config_hash(new)   # wake_* off the hash

    def test_wake_keys_count_while_on(self):
        on, _ = A.normalize_config(dict(A.default_config(), toggles=TOGGLES_WAKE_ONLY), strict=True)
        other, _ = A.normalize_config(dict(A.default_config(), toggles=TOGGLES_WAKE_ONLY,
                                           wake_ir_command=0x57), strict=True)
        off, _ = A.normalize_config(A.default_config(), strict=True)
        assert len({A.config_hash(on), A.config_hash(other), A.config_hash(off)}) == 3

    @pytest.mark.parametrize("bad", [{"wake_ir_address": -1}, {"wake_ir_address": 65536},
                                     {"wake_ir_command": 256}, {"wake_ir_command": True},
                                     {"wake_ir_address": "31253"}, {"wake_ir_command": 1.5}])
    def test_bad_wake_config_is_refused(self, bad):
        norm, err = A.normalize_config(dict(A.default_config(), **bad), strict=True)
        assert norm is None and "wake_ir_" in err

    def test_host_and_agent_agree(self):
        from src.network import car_phone_agent as cpa
        from src.core.config import BCMConfig
        cfg = BCMConfig(config_path=str(REPO / "config" / "bcm_config_test.yaml"),
                        platform_override="x86", local_path=None, env={})
        for on in (False, True):
            for name in ("car_phone", "car_phone_agent", "input", "remote_session"):
                cfg.set(f"modules.{name}", on if name == "remote_session" else True)
            desired = cpa.desired_config(cfg)
            assert ("remote_session" in desired["toggles"]) is on
            assert ("wake_ir_address" in desired) is on
            norm, err = A.normalize_config(desired, strict=True)
            assert err == "" and cpa.config_hash(desired) == A.config_hash(norm)
        assert (desired["wake_ir_address"], desired["wake_ir_command"]) == (ADDR, CMD)


# ── --wake and wake.sh ───────────────────────────────────────────────────

class TestCli:
    def _write_config(self, d, on):
        cfg = dict(A.default_config(), toggles=dict(A.default_config()["toggles"],
                                                     remote_session=on))
        os.makedirs(d, exist_ok=True)
        Path(d, "config.json").write_text(json.dumps(cfg))

    def test_exit_codes(self, tmp_path, capsys):
        d = str(tmp_path / "st")
        self._write_config(d, True)
        tx = Tx()
        assert A.run_wake(d, transmit=tx, wall=lambda: park.T0) == 0
        assert "wyslane" in capsys.readouterr().out and len(tx.calls) == 1
        assert A.run_wake(d, transmit=tx, wall=lambda: park.T0 + 5) == 4
        self._write_config(d, False)
        assert A.run_wake(d, transmit=tx, wall=lambda: park.T0 + 500) == 3
        assert len(tx.calls) == 1
        self._write_config(d, True)
        assert A.run_wake(d, transmit=Tx(ok=False, why="x"), wall=lambda: park.T0 + 600) == 6

    def test_without_config_it_is_off(self, tmp_path):
        tx = Tx()
        assert A.run_wake(str(tmp_path), transmit=tx, wall=lambda: park.T0) == 3
        assert tx.calls == []

    def test_main_flag(self, tmp_path, monkeypatch):
        seen = []
        monkeypatch.setattr(A, "run_wake", lambda d: seen.append(d) or 0)
        assert A.main(["--state-dir", str(tmp_path / "st"), "--wake"]) == 0
        assert seen == [str(tmp_path / "st")]

    def test_wake_sh_syntax_and_fixed_text(self):
        for sh in ("bash", "dash"):
            if shutil.which(sh):
                res = subprocess.run([sh, "-n", str(WAKE_SH)], capture_output=True, text=True,
                                     timeout=30)
                assert res.returncode == 0, res.stderr
        text = WAKE_SH.read_text(encoding="utf-8")
        code = "\n".join(ln for ln in text.splitlines() if not ln.lstrip().startswith("#"))
        assert 'python "$AGENT" --state-dir "$STATE_DIR" --wake' in code
        # nothing from outside reaches a command: no positional args, no eval
        assert not re.search(r'\$[@*1-9]|\beval\b|\$\(', code)
        assert "termux-toast" in code
        for rc in (0, 3, 4, 5):
            assert re.search(rf"^\s*{rc}\) msg=\"BCM: [A-Za-z .()_-]+\" ;;$", code, flags=re.M)
        assert code.count("exit") == 1 and code.rstrip().endswith('exit "$rc"')

    def test_exit_codes_match_wake_sh(self):
        text = WAKE_SH.read_text(encoding="utf-8")
        assert A.WAKE_EXIT["sent"] == 0 and "0) msg=\"BCM: budzenie wyslane\"" in text
        assert A.WAKE_EXIT["off"] == 3 and A.WAKE_EXIT["rate"] == 4 and A.WAKE_EXIT["busy"] == 5
