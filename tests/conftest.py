"""Shared pytest fixtures for the BCM test suite.

Keeps the suite hermetic: no test should ever talk to real hardware
(bluetoothctl, serial ports) or sleep in retry loops.
"""

import pytest


@pytest.fixture(autouse=True)
def no_bluetooth_hardware(monkeypatch):
    """Neutralize BluetoothManager's hardware probing.

    The real ``_check_availability`` retries ``bluetoothctl show`` 5 times
    with ``time.sleep(2)`` between attempts and spawns auto-connect
    threads — in CI that hangs every test that constructs a
    BluetoothManager. Replace it with a no-op that marks Bluetooth as
    unavailable, which is the honest state on a test machine.
    """
    from src.multimedia.bluetooth import BluetoothManager

    def _fake_check_availability(self) -> None:
        self._available = False

    monkeypatch.setattr(
        BluetoothManager, "_check_availability", _fake_check_availability
    )


class OpenAutoSandbox:
    """Stand-in for subprocess, sleeping and kill() inside openauto.py.

    OpenAutoController.restart() and its helpers run ``pgrep -f autoapp``,
    ``fuser 5000/tcp`` + SIGKILL, ``bluetoothctl power off/on`` and
    ``hciconfig down/up``, and sleep ~10 s. On a developer machine (or the
    car) a test calling the real thing would kill processes and power-cycle
    Bluetooth. With this sandbox every command is recorded instead of run:

    * ``run()`` returns exit code 1 with empty output ("nothing found")
      unless ``handler(argv, kwargs)`` returns a CompletedProcess;
    * ``Popen()`` raises FileNotFoundError (no Xvfb, WM or autoapp launch);
    * ``kill(pid, sig)`` replaces ``OpenAutoController._kill_pid`` and only
      records; the real one stays reachable as ``real_kill_pid``;
    * sleeps are capped at 10 ms (not zero, so a stray polling loop cannot
      spin a core).
    """

    def __init__(self, real_kill_pid) -> None:
        import subprocess as _sp
        import time as _time
        from types import SimpleNamespace

        self.calls: list[list[str]] = []
        self.kills: list[tuple[int, int]] = []
        self.handler = None
        self.real_kill_pid = real_kill_pid
        self.subprocess = SimpleNamespace(
            run=self.run, Popen=self.popen,
            PIPE=_sp.PIPE, STDOUT=_sp.STDOUT, DEVNULL=_sp.DEVNULL,
            TimeoutExpired=_sp.TimeoutExpired,
            CompletedProcess=_sp.CompletedProcess,
            CalledProcessError=_sp.CalledProcessError,
        )
        sleep = lambda seconds: _time.sleep(min(max(float(seconds), 0.0), 0.01))
        self.time = SimpleNamespace(
            time=_time.time, monotonic=_time.monotonic, sleep=sleep)

    def run(self, argv, *args, **kwargs):
        import subprocess as _sp
        assert not kwargs.get("shell"), "shell=True is never allowed"
        argv = list(argv)
        self.calls.append(argv)
        if self.handler is not None:
            result = self.handler(argv, kwargs)
            if result is not None:
                return result
        empty = "" if kwargs.get("text") else b""
        return _sp.CompletedProcess(argv, 1, stdout=empty, stderr=empty)

    def popen(self, argv, *args, **kwargs):
        assert not kwargs.get("shell"), "shell=True is never allowed"
        self.calls.append(list(argv))
        raise FileNotFoundError(argv[0])

    def kill(self, pid, sig) -> bool:
        self.kills.append((pid, sig))
        return True

    def ran(self, *prefix: str) -> bool:
        """True if a recorded argv starts with ``prefix``."""
        return any(call[:len(prefix)] == list(prefix) for call in self.calls)


@pytest.fixture(autouse=True)
def openauto_sandbox(monkeypatch):
    """Keep every test away from real processes in src.multimedia.openauto.

    Autouse for the same reason as ``no_bluetooth_hardware``: nothing in the
    suite may kill processes or touch Bluetooth, and a forgotten mock must
    not be able to. Only names inside the openauto module are replaced, so
    other modules' subprocess/time are untouched. Request the fixture by
    name to inspect ``calls``/``kills`` or set ``handler``.
    """
    from src.multimedia import openauto

    sandbox = OpenAutoSandbox(openauto.OpenAutoController._kill_pid)
    monkeypatch.setattr(openauto, "subprocess", sandbox.subprocess)
    monkeypatch.setattr(openauto, "time", sandbox.time)
    monkeypatch.setattr(openauto.OpenAutoController, "_kill_pid",
                        staticmethod(sandbox.kill))
    return sandbox
