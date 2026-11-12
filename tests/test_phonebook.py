"""PBAP phonebook sync (src/multimedia/phonebook.py): settle wait and start.

The pull waits ``bluetooth.phonebook_settle_sec`` after bt.connected so the
Android Auto RFCOMM bootstrap has the link to itself (15 s in the test
config, 3 s in code = the old fixed delay). ``_sync`` is driven directly with
a fake clock/sleep; the D-Bus part is replaced by a recorder, so nothing
touches BlueZ, obexd or a session bus, and the cache dir is tmp_path.
"""

from pathlib import Path
from types import SimpleNamespace

import pytest

from src.core import modules_catalog
from src.core.config import BCMConfig
from src.core.event_bus import EventBus
from src.multimedia import phonebook as pb

REPO = Path(__file__).resolve().parent.parent
PHONE = "AA:BB:CC:DD:EE:01"


@pytest.fixture(autouse=True)
def cache_in_tmp(tmp_path, monkeypatch):
    monkeypatch.setattr(pb, "CACHE_DIR", str(tmp_path))


class FakeTime:
    def __init__(self):
        self.t = 100.0
        self.on_sleep = None

    def clock(self):
        return self.t

    def sleep(self, seconds):
        self.t += seconds
        if self.on_sleep:
            self.on_sleep(self.t)


def make(settle):
    ft = FakeTime()
    sync = pb.PhonebookSync(EventBus(), settle_sec=settle, sleep=ft.sleep, clock=ft.clock)
    pulls = []
    sync._ensure_session_bus = lambda: pulls.append(ft.t)   # None = stop after this
    return sync, ft, pulls


class TestSettle:
    def test_default_keeps_the_old_3_seconds(self):
        sync, ft, pulls = make(pb.DEFAULT_SETTLE_S)
        sync._sync(PHONE)
        assert pulls == [pytest.approx(103.0)]

    def test_long_settle_is_waited_out(self):
        sync, ft, pulls = make(15)
        sync._sync(PHONE)
        assert pulls == [pytest.approx(115.0)]

    def test_disconnect_during_settle_cancels_the_pull(self):
        sync, ft, pulls = make(15)
        ft.on_sleep = lambda t: t >= 105 and sync._on_disconnected(
            "bt.disconnected", {"address": PHONE}, 0)
        sync._sync(PHONE)
        assert pulls == []
        assert ft.t < 106                          # left right away, no full wait

    def test_reconnect_during_settle_leaves_one_pull(self):
        sync, ft, pulls = make(15)

        def reconnect(t):
            if t >= 105 and not hasattr(ft, "done"):
                ft.done = True
                sync._on_disconnected("bt.disconnected", {"address": PHONE}, 0)
                with sync._lock:                   # what a new _sync() does first
                    sync._active_addr = PHONE
                    sync._stop_flag = False
                    sync._sync_gen += 1

        ft.on_sleep = reconnect
        sync._sync(PHONE)
        assert pulls == []                         # the newer sync owns the pull

    @pytest.mark.parametrize("value, expected", [
        (None, 3.0), (15, 15.0), (0, 0.0), (2.5, 2.5), (-5, 0.0), (999, 120.0),
        (True, 3.0), ("15", 3.0), (float("nan"), 3.0), (float("inf"), 3.0),
    ])
    def test_settle_from_config(self, value, expected):
        cfg = SimpleNamespace(get=lambda key, default=None: value)
        assert pb.settle_from_config(cfg) == expected

    def test_settle_without_config(self):
        assert pb.settle_from_config(None) == pb.DEFAULT_SETTLE_S


class TestStartFromConfigs:
    @staticmethod
    def _cfg(name):
        return BCMConfig(str(REPO / "config" / name), "x86", env={})

    def test_test_config_starts_phonebook_with_the_aa_settle(self):
        cfg = self._cfg("bcm_config_test.yaml")
        # main.py: `if _runs("phonebook")` — phonebook requires bluetooth
        assert modules_catalog.is_enabled(cfg, "bluetooth") is True
        assert modules_catalog.is_enabled(cfg, "phonebook") is True
        bus = EventBus()
        sync = pb.start_phonebook_sync(bus, cfg)
        assert sync._settle_sec == 15.0
        assert cfg.get("network.phone_tether.settle_sec") == 15     # kept in step
        assert sync._on_connected in bus._subscribers["bt.connected"]

    def test_production_config_keeps_the_3_second_wait(self):
        cfg = self._cfg("bcm_config.yaml")
        assert pb.start_phonebook_sync(EventBus(), cfg)._settle_sec == pb.DEFAULT_SETTLE_S

    def test_main_passes_the_config(self):
        assert "start_phonebook_sync(event_bus, config)" in (REPO / "main.py").read_text()
