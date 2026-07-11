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
