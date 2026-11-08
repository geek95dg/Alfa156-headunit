"""Touch injection into the Android Auto canvas (Xvfb :99) via xdotool.

On x86 autoapp renders into a headless Xvfb display and the kiosk shows it as
an MJPEG stream. Touches on the kiosk therefore have to be replayed into that
X display as synthetic mouse events. ``/aa/touch`` used to run
``xdotool ... click 1`` for every touch, so AA only ever saw taps: lists could
not be scrolled and the map could not be dragged.

openDsh's ``InputDevice::handleMouseEvent`` maps Qt ``MouseButtonPress`` to
PRESS, ``MouseMove`` *with the left button held* to DRAG and
``MouseButtonRelease`` to RELEASE (it also forwards a release that has no
matching press). So a drag is simply ``mousedown`` → ``mousemove``… →
``mouseup`` on :99. This module turns the browser's down/move/up/cancel/tap
stream into exactly that, with the guarantees a 24/7 car unit needs:

* every input is validated (action enum, finite numbers, clamped to the
  canvas) — it comes from a browser, i.e. from the network;
* one worker thread and one bounded queue, so a flood of moves cannot spawn
  unbounded xdotool processes; stale moves are coalesced and, on overflow,
  dropped — ``down``/``up`` never are, otherwise AA would see a finger that
  never lifts;
* a button state machine (a second ``down`` releases the first; ``move``
  only while the button is down; ``up`` without ``down`` is dropped so the
  phone never gets a stray RELEASE; ``cancel`` and disconnect release only
  act on the client that pressed the button);
* a stuck-button watchdog: if the client vanishes mid-drag (tab crash, Wi-Fi
  drop without a WebSocket close) the button is released after
  ``stuck_timeout`` seconds without events;
* a missing xdotool is logged once and disables injection instead of raising
  on every touch.

Commands are argv lists (never a shell) run with ``DISPLAY=:99`` and a 2 s
timeout.
"""

from __future__ import annotations

import math
import os
import subprocess
import threading
import time
from collections import deque
from typing import Any, Callable, Hashable, Optional

from src.core.logger import get_logger

log = get_logger("multimedia.aa_input")

#: Actions a client may submit.
ACTIONS = frozenset({"down", "move", "up", "cancel", "tap"})

#: Internal action queued by :meth:`AATouchInjector.release` (never accepted
#: from a client — ``submit()`` only takes :data:`ACTIONS`).
_RELEASE = "_release"

#: Per-command xdotool timeout. A wedged X server must not wedge the worker.
XDOTOOL_TIMEOUT_S = 2.0

#: Used until ``size_fn`` returns something sane (and if it ever raises).
_DEFAULT_SIZE = (1024, 600)

#: Upper bound for a canvas dimension; anything larger is a config typo.
_MAX_DIMENSION = 16384


def _unit(value: Any) -> Optional[float]:
    """Return ``value`` clamped to 0..1, or None if it is not a finite number.

    ``bool`` is an ``int`` subclass, but ``True`` is not a coordinate.
    Python's json parses an integer of any length, and ``float()`` of one
    with ~400 digits raises OverflowError — caught here, so ``submit()`` and
    ``to_pixels()`` keep their "never raises" contract on hostile input.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        value = float(value)
    except (OverflowError, ValueError):
        return None
    if not math.isfinite(value):
        return None
    return min(1.0, max(0.0, value))


class _Event:
    """One queued injection request (pixels already resolved)."""

    __slots__ = ("action", "x", "y", "client", "epoch")

    def __init__(self, action: str, x: int, y: int,
                 client: Optional[Hashable], epoch: int) -> None:
        self.action = action
        self.x = x
        self.y = y
        self.client = client
        self.epoch = epoch


class AATouchInjector:
    """Serialises browser touch events into xdotool calls on the AA display.

    Args:
        size_fn: returns the AA canvas ``(width, height)`` in pixels — the
            same helper that sizes Xvfb and the MJPEG capture, so relative
            coordinates map 1:1.
        display: X display autoapp renders into.
        runner: ``subprocess.run`` compatible callable (test seam).
        clock: monotonic clock (test seam for the stuck-button watchdog).
        stuck_timeout: seconds without any event while the button is down
            after which the button is released.
        max_queue: queue bound; on overflow the oldest queued move is dropped.
        autostart: start the worker thread now. Tests pass False and drive
            the queue with :meth:`process_pending`.
    """

    def __init__(self, size_fn: Callable[[], tuple[int, int]],
                 display: str = ":99",
                 runner: Callable[..., Any] = subprocess.run,
                 clock: Callable[[], float] = time.monotonic,
                 stuck_timeout: float = 3.0,
                 max_queue: int = 64,
                 autostart: bool = True) -> None:
        self._size_fn = size_fn
        self._display = display
        self._runner = runner
        self._clock = clock
        self._stuck_timeout = float(stuck_timeout)
        self._max_queue = max(4, int(max_queue))
        self._queue: deque[_Event] = deque()
        self._cond = threading.Condition()
        self._last_size = _DEFAULT_SIZE

        # Button state — only ever changed while holding self._cond.
        self._button_down = False
        self._owner: Optional[Hashable] = None
        self._last_event = clock()
        # reset() bumps the epoch: queued and in-flight events from before an
        # AA restart must not touch (or record state for) the new X server.
        self._epoch = 0

        self._available = True
        self._warned_missing = False
        self._stopped = False
        self._thread: Optional[threading.Thread] = None
        if autostart:
            self._thread = threading.Thread(
                target=self._worker, daemon=True, name="aa-touch-injector")
            self._thread.start()

    # ── public API ────────────────────────────────────────────────────────

    @property
    def available(self) -> bool:
        """False once xdotool turned out to be missing (until :meth:`reset`)."""
        return self._available

    @property
    def button_down(self) -> bool:
        return self._button_down

    def submit(self, action: Any, rel_x: Any = None, rel_y: Any = None,
               client: Optional[Hashable] = None) -> bool:
        """Queue one touch event. Never raises; False means rejected.

        ``rel_x``/``rel_y`` are fractions of the canvas (0..1; values outside
        are clamped). ``cancel`` needs no coordinates.
        """
        if not isinstance(action, str) or action not in ACTIONS:
            return False
        if action == "cancel":
            px = py = 0
        else:
            pixels = self.to_pixels(rel_x, rel_y)
            if pixels is None:
                return False
            px, py = pixels

        with self._cond:
            if self._stopped or not self._available:
                return False
            event = _Event(action, px, py, client, self._epoch)
            queue = self._queue
            if (action == "move" and queue and queue[-1].action == "move"
                    and queue[-1].client == client):
                # Only the newest position of a drag matters; replaying every
                # intermediate point would just lag behind the finger.
                queue[-1] = event
            else:
                if len(queue) >= self._max_queue and not self._drop_oldest_move():
                    # Queue full of down/up/tap — a misbehaving client. Refuse
                    # the new event rather than grow without bound; the stuck
                    # watchdog cleans up a button left down.
                    log.debug("AA touch queue full — dropping %s", action)
                    return False
                queue.append(event)
            self._cond.notify()
        return True

    def to_pixels(self, rel_x: Any, rel_y: Any) -> Optional[tuple[int, int]]:
        """Canvas pixel for a relative point, or None if not finite numbers.

        Clamped to ``0..w-1`` / ``0..h-1``: ``int()`` floors, so 1.0 would
        otherwise land one pixel past the edge.
        """
        rx, ry = _unit(rel_x), _unit(rel_y)
        if rx is None or ry is None:
            return None
        w, h = self._size()
        return min(w - 1, int(rx * w)), min(h - 1, int(ry * h))

    def release(self, client: Optional[Hashable]) -> None:
        """Release the button if ``client`` pressed it (e.g. WS disconnect).

        Queued behind the client's pending events, so it acts after them. A
        button held by another client is left alone.
        """
        with self._cond:
            if self._stopped:
                return
            # Server-generated (one per connection), so it may exceed the
            # bound by one instead of being dropped.
            self._queue.append(_Event(_RELEASE, 0, 0, client, self._epoch))
            self._cond.notify()

    def reset(self) -> None:
        """Forget queue and button state — the AA X server is restarting.

        No xdotool call: the old display is going away and the new one starts
        with no button pressed. Availability is re-checked on the next event,
        so installing xdotool takes effect at the next AA restart.
        """
        with self._cond:
            self._epoch += 1
            self._queue.clear()
            self._button_down = False
            self._owner = None
            self._available = True
            self._cond.notify_all()

    def process_pending(self) -> int:
        """Run queued events in the calling thread, then the stuck check.

        Test hook for ``autostart=False``. Returns the number of events run.
        """
        count = 0
        while True:
            with self._cond:
                event = self._queue.popleft() if self._queue else None
            if event is None:
                break
            self._execute(event)
            count += 1
        self._check_stuck()
        return count

    def stop(self) -> None:
        """Stop the worker; release the button if it is still down."""
        with self._cond:
            self._stopped = True
            self._queue.clear()
            self._cond.notify_all()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=XDOTOOL_TIMEOUT_S + 1)
        if self._button_down and self._available:
            self._run(["mouseup", "1"])
            with self._cond:
                self._button_down = False
                self._owner = None

    # ── worker ────────────────────────────────────────────────────────────

    def _worker(self) -> None:
        while True:
            with self._cond:
                while not self._queue and not self._stopped:
                    wait = self._stuck_wait()
                    if wait is not None and wait <= 0:
                        break
                    self._cond.wait(wait)
                if self._stopped:
                    return
                event = self._queue.popleft() if self._queue else None
            try:
                if event is None:
                    self._check_stuck()
                else:
                    self._execute(event)
            except Exception:
                # The worker must outlive any surprise — it is the only one.
                log.exception("AA touch worker error")

    def _stuck_wait(self) -> Optional[float]:
        """Seconds until the stuck watchdog is due (None: nothing to watch)."""
        if not self._button_down or not self._available:
            return None
        return self._stuck_timeout - (self._clock() - self._last_event)

    def _drop_oldest_move(self) -> bool:
        for i, queued in enumerate(self._queue):
            if queued.action == "move":
                del self._queue[i]
                return True
        return False

    def _execute(self, event: _Event) -> None:
        with self._cond:
            if event.epoch != self._epoch or not self._available:
                return
            down = self._button_down
            owner = self._owner

        x, y = str(event.x), str(event.y)
        move = ["mousemove", "--screen", "0", x, y]
        commands: list[list[str]] = []
        action = event.action
        if action == "down":
            if down:
                commands.append(["mouseup", "1"])  # never two presses in a row
            commands.append(move + ["mousedown", "1"])
            new_state = (True, event.client)
        elif action == "move":
            if not down:
                return  # a hover is meaningless to AA; only drags matter
            commands.append(move)
            new_state = (True, owner)
        elif action == "up":
            if not down:
                return  # autoapp would forward a stray RELEASE to the phone
            commands.append(move + ["mouseup", "1"])
            new_state = (False, None)
        elif action == "tap":
            if down:
                commands.append(["mouseup", "1"])
            commands.append(move + ["click", "1"])
            new_state = (False, None)
        elif action == "cancel":
            # Owner-aware, unlike up/move (a down sent over the HTTP fallback
            # may be finished by an up over the WebSocket). A2's unmount
            # always sends a safety "cancel"; leaving A2 on the kiosk must
            # not drop a drag a second viewer (phone browser on /#a2) is
            # doing. A cancel from another client is ignored — a button
            # really left down is still freed by its owner's disconnect or
            # by the stuck watchdog.
            if not down or (owner is not None and event.client != owner):
                return
            commands.append(["mouseup", "1"])
            new_state = (False, None)
        elif action == _RELEASE:
            if not down or owner != event.client:
                return
            commands.append(["mouseup", "1"])
            new_state = (False, None)
        else:  # pragma: no cover - submit() validates
            return

        for args in commands:
            if not self._run(args):
                return  # xdotool missing: state is unchanged (and moot)

        with self._cond:
            if event.epoch == self._epoch:
                self._button_down, self._owner = new_state
                self._last_event = self._clock()

    def _check_stuck(self) -> None:
        with self._cond:
            if not self._button_down or not self._available:
                return
            held = self._clock() - self._last_event
            # "<", not "<=": _stuck_wait() reports due at equality, and the
            # worker must not spin on a check that keeps declining.
            if held < self._stuck_timeout:
                return
            epoch = self._epoch
        log.warning("AA touch: button down %.1fs without events — releasing", held)
        self._run(["mouseup", "1"])
        with self._cond:
            if epoch == self._epoch:
                self._button_down = False
                self._owner = None

    # ── helpers ───────────────────────────────────────────────────────────

    def _size(self) -> tuple[int, int]:
        try:
            w, h = self._size_fn()
            w, h = int(w), int(h)
            if 0 < w <= _MAX_DIMENSION and 0 < h <= _MAX_DIMENSION:
                self._last_size = (w, h)
        except Exception:
            log.debug("AA canvas size lookup failed", exc_info=True)
        return self._last_size

    def _run(self, args: list[str]) -> bool:
        """Run one xdotool command. False only if xdotool is missing."""
        argv = ["xdotool", *args]
        try:
            result = self._runner(
                argv,
                env={**os.environ, "DISPLAY": self._display},
                timeout=XDOTOOL_TIMEOUT_S,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
        except FileNotFoundError:
            self._mark_unavailable()
            return False
        except subprocess.TimeoutExpired:
            log.debug("xdotool %s timed out on %s", args[0], self._display)
            return True
        except Exception as e:
            log.debug("xdotool %s failed: %s", args[0], e)
            return True
        returncode = getattr(result, "returncode", 0)
        if returncode:
            log.debug("xdotool %s exited with %s", args[0], returncode)
        return True

    def _mark_unavailable(self) -> None:
        with self._cond:
            self._available = False
            self._queue.clear()
            self._button_down = False
            self._owner = None
            warn = not self._warned_missing
            self._warned_missing = True
        if warn:
            log.warning("xdotool not installed — Android Auto touch input is "
                        "disabled (apt install xdotool)")
