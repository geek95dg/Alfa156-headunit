"""AATouchInjector — browser touch stream → xdotool argv on the AA display.

Everything runs with a fake runner (no xdotool, no X server) and, apart from
the worker-thread test, ``autostart=False`` + ``process_pending()``, so the
order and content of every command is deterministic.
"""

import subprocess
import threading
import time

import pytest

from src.multimedia.aa_input import AATouchInjector

W, H = 1024, 600
XDO = ["xdotool"]


class FakeRunner:
    """Records argv + kwargs; optionally raises."""

    def __init__(self, exc=None):
        self.calls = []
        self.kwargs = []
        self.exc = exc

    def __call__(self, argv, **kwargs):
        self.calls.append(list(argv))
        self.kwargs.append(kwargs)
        if self.exc is not None:
            raise self.exc
        return subprocess.CompletedProcess(argv, 0)


class FakeClock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now


def make(runner=None, clock=None, **kw):
    runner = runner or FakeRunner()
    inj = AATouchInjector(lambda: (W, H), runner=runner,
                          clock=clock or FakeClock(), autostart=False, **kw)
    return inj, runner


def move(x, y):
    return XDO + ["mousemove", "--screen", "0", str(x), str(y)]


class TestSequences:
    def test_drag_coalesces_moves(self):
        inj, run = make()
        assert inj.submit("down", 0.1, 0.1, client="a")
        for i in range(10):
            assert inj.submit("move", 0.1 + i * 0.05, 0.2, client="a")
        assert inj.submit("up", 0.6, 0.2, client="a")
        assert inj.process_pending() == 3
        assert run.calls == [
            move(102, 60) + ["mousedown", "1"],
            move(int((0.1 + 9 * 0.05) * W), 120),
            move(614, 120) + ["mouseup", "1"],
        ]
        assert inj.button_down is False

    def test_moves_of_different_clients_are_not_merged(self):
        inj, run = make()
        inj.submit("down", 0.5, 0.5, client="a")
        inj.submit("move", 0.6, 0.5, client="a")
        inj.submit("move", 0.7, 0.5, client="b")
        inj.submit("move", 0.8, 0.5, client="b")
        inj.process_pending()
        assert len(run.calls) == 3   # down, a's move, b's last move

    def test_tap_argv_ends_with_click(self):
        inj, run = make()
        assert inj.submit("tap", 0.5, 0.5)
        inj.process_pending()
        assert run.calls == [move(512, 300) + ["click", "1"]]
        assert run.calls[0][-2:] == ["click", "1"]

    def test_down_while_down_releases_first(self):
        inj, run = make()
        inj.submit("down", 0.1, 0.1)
        inj.submit("down", 0.2, 0.2)
        inj.process_pending()
        assert run.calls[1] == XDO + ["mouseup", "1"]
        assert run.calls[2][-2:] == ["mousedown", "1"]
        assert inj.button_down is True

    def test_move_and_up_without_down_are_dropped(self):
        inj, run = make()
        inj.submit("move", 0.5, 0.5)
        inj.submit("up", 0.5, 0.5)
        inj.submit("cancel")
        inj.process_pending()
        # autoapp forwards a bare release to the phone — never send one.
        assert run.calls == []

    def test_cancel_releases_button(self):
        inj, run = make()
        inj.submit("down", 0.5, 0.5)
        inj.submit("cancel", None, None)
        inj.process_pending()
        assert run.calls[-1] == XDO + ["mouseup", "1"]
        assert inj.button_down is False


class TestValidation:
    def test_clamping_to_last_pixel(self):
        inj, run = make()
        inj.submit("tap", 1.5, -0.2)
        inj.submit("tap", 1.0, 1.0)
        inj.process_pending()
        assert run.calls[0] == move(W - 1, 0) + ["click", "1"]
        assert run.calls[1] == move(W - 1, H - 1) + ["click", "1"]

    @pytest.mark.parametrize("x, y", [
        (float("nan"), 0.5), (0.5, float("inf")), ("0.5", 0.5),
        (None, 0.5), (True, 0.5), ([0.5], 0.5), ({}, 0.5),
        (10 ** 400, 0.5), (0.5, -(10 ** 400)),   # float() → OverflowError
    ])
    def test_bad_coordinates_rejected(self, x, y):
        inj, run = make()
        assert inj.to_pixels(x, y) is None
        assert inj.submit("tap", x, y) is False
        assert inj.process_pending() == 0
        assert run.calls == []

    @pytest.mark.parametrize("action", ["click", "DOWN", "", None, 3, "_release", ["tap"]])
    def test_bad_action_rejected(self, action):
        inj, run = make()
        assert inj.submit(action, 0.5, 0.5) is False
        inj.process_pending()
        assert run.calls == []

    def test_argv_lists_display_and_timeout_no_shell(self):
        inj, run = make()
        inj.submit("tap", 0.5, 0.5)
        inj.process_pending()
        assert isinstance(run.calls[0], list)
        assert all(isinstance(a, str) for a in run.calls[0])
        kw = run.kwargs[0]
        assert kw.get("shell") in (None, False)
        assert kw["env"]["DISPLAY"] == ":99"
        assert kw["timeout"] == 2.0

    def test_broken_size_fn_falls_back(self):
        def boom():
            raise RuntimeError("no config")
        run = FakeRunner()
        inj = AATouchInjector(boom, runner=run, clock=FakeClock(), autostart=False)
        assert inj.submit("tap", 1.0, 1.0)
        inj.process_pending()
        assert run.calls[0][4:6] == ["1023", "599"]


class TestOwnershipAndSafety:
    def test_release_by_owner_sends_mouseup(self):
        inj, run = make()
        inj.submit("down", 0.5, 0.5, client="ws1")
        inj.process_pending()
        inj.release("ws1")
        inj.process_pending()
        assert run.calls[-1] == XDO + ["mouseup", "1"]
        assert inj.button_down is False

    def test_release_by_other_client_does_nothing(self):
        inj, run = make()
        inj.submit("down", 0.5, 0.5, client="ws1")
        inj.process_pending()
        before = len(run.calls)
        inj.release("ws2")
        inj.process_pending()
        assert len(run.calls) == before
        assert inj.button_down is True

    def test_cancel_by_other_client_does_nothing(self):
        # A2 unmount on the kiosk must not drop a second viewer's drag.
        inj, run = make()
        inj.submit("down", 0.5, 0.5, client="phone")
        inj.process_pending()
        before = len(run.calls)
        assert inj.submit("cancel", client="kiosk")
        inj.process_pending()
        assert len(run.calls) == before
        assert inj.button_down is True
        inj.submit("cancel", client="phone")
        inj.process_pending()
        assert run.calls[-1] == XDO + ["mouseup", "1"]
        assert inj.button_down is False

    def test_up_from_other_client_still_releases(self):
        # down over the HTTP fallback, up over the WebSocket once it is back
        inj, run = make()
        inj.submit("down", 0.5, 0.5, client="http")
        inj.submit("up", 0.6, 0.5, client="ws1")
        inj.process_pending()
        assert run.calls[-1][-2:] == ["mouseup", "1"]
        assert inj.button_down is False

    def test_stuck_watchdog_releases_after_timeout(self):
        clock = FakeClock()
        inj, run = make(clock=clock, stuck_timeout=3.0)
        inj.submit("down", 0.5, 0.5)
        inj.process_pending()
        clock.now += 2.9
        inj.process_pending()
        assert inj.button_down is True
        assert len(run.calls) == 1
        clock.now += 0.2
        inj.process_pending()
        assert run.calls[-1] == XDO + ["mouseup", "1"]
        assert inj.button_down is False

    def test_events_keep_the_watchdog_away(self):
        clock = FakeClock()
        inj, run = make(clock=clock, stuck_timeout=3.0)
        inj.submit("down", 0.5, 0.5)
        inj.process_pending()
        for _ in range(5):   # a long press with the page's 1 s heartbeat
            clock.now += 1.0
            inj.submit("move", 0.5, 0.5)
            inj.process_pending()
        assert inj.button_down is True

    def test_reset_drops_queue_and_state_without_commands(self):
        inj, run = make()
        inj.submit("down", 0.5, 0.5)
        inj.process_pending()
        inj.submit("move", 0.6, 0.6)
        inj.reset()
        assert inj.process_pending() == 0
        assert inj.button_down is False
        assert len(run.calls) == 1

    def test_overflow_drops_oldest_moves_never_down_up(self):
        inj, run = make(max_queue=4)
        assert inj.submit("down", 0.1, 0.1, client="a")
        assert inj.submit("move", 0.2, 0.1, client="a")
        assert inj.submit("tap", 0.3, 0.1, client="b")
        assert inj.submit("move", 0.4, 0.1, client="a")
        # Full: the oldest move (0.2) makes room for the up.
        assert inj.submit("up", 0.5, 0.1, client="a")
        inj.process_pending()
        actions = [c[-2:] for c in run.calls]
        assert ["mousedown", "1"] in actions
        assert ["mouseup", "1"] in actions
        assert move(int(0.2 * W), 60) not in run.calls

    def test_overflow_without_moves_refuses_new_event(self):
        inj, run = make(max_queue=4)
        for _ in range(4):
            assert inj.submit("tap", 0.5, 0.5)
        assert inj.submit("tap", 0.5, 0.5) is False


class TestMissingXdotool:
    def test_missing_xdotool_does_not_raise_and_disables(self, caplog):
        run = FakeRunner(exc=FileNotFoundError("xdotool"))
        inj, _ = make(runner=run)
        assert inj.submit("tap", 0.5, 0.5)
        inj.process_pending()             # must not raise
        assert inj.available is False
        assert inj.submit("tap", 0.5, 0.5) is False
        assert len(run.calls) == 1
        warnings = [r for r in caplog.records if "xdotool not installed" in r.getMessage()]
        assert len(warnings) == 1

    def test_reset_rechecks_availability(self):
        run = FakeRunner(exc=FileNotFoundError("xdotool"))
        inj, _ = make(runner=run)
        inj.submit("tap", 0.5, 0.5)
        inj.process_pending()
        inj.reset()
        assert inj.available is True
        assert inj.submit("tap", 0.5, 0.5) is True

    def test_timeout_is_swallowed(self):
        run = FakeRunner(exc=subprocess.TimeoutExpired(["xdotool"], 2))
        inj, _ = make(runner=run)
        inj.submit("down", 0.5, 0.5)
        inj.process_pending()
        assert inj.available is True


class TestWorkerThread:
    def test_worker_runs_events_and_stops(self):
        run = FakeRunner()
        done = threading.Event()

        def runner(argv, **kw):
            run(argv, **kw)
            if argv[-2:] == ["mouseup", "1"]:
                done.set()
            return subprocess.CompletedProcess(argv, 0)

        inj = AATouchInjector(lambda: (W, H), runner=runner)
        try:
            inj.submit("down", 0.5, 0.5, client="x")
            inj.submit("move", 0.6, 0.5, client="x")
            inj.submit("up", 0.7, 0.5, client="x")
            assert done.wait(5)
        finally:
            inj.stop()
        assert run.calls[0][-2:] == ["mousedown", "1"]
        assert run.calls[-1][-2:] == ["mouseup", "1"]
        assert inj.submit("tap", 0.5, 0.5) is False   # stopped

    def test_worker_watchdog_with_real_clock(self):
        released = threading.Event()

        def runner(argv, **kw):
            if argv == ["xdotool", "mouseup", "1"]:
                released.set()
            return subprocess.CompletedProcess(argv, 0)

        inj = AATouchInjector(lambda: (W, H), runner=runner, stuck_timeout=0.2)
        try:
            inj.submit("down", 0.5, 0.5)
            t0 = time.monotonic()
            assert released.wait(5)
            assert time.monotonic() - t0 >= 0.15
        finally:
            inj.stop()

    def test_stop_releases_pressed_button(self):
        calls = []
        inj = AATouchInjector(lambda: (W, H), autostart=False, clock=FakeClock(),
                              runner=lambda argv, **kw: calls.append(argv))
        inj.submit("down", 0.5, 0.5)
        inj.process_pending()
        inj.stop()
        assert calls[-1] == ["xdotool", "mouseup", "1"]
