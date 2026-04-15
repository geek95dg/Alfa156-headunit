"""Tests for Audio System & PipeWire Integration (Part 6)."""

import time
import pytest

from src.core.event_bus import EventBus
from src.core.config import BCMConfig
from src.audio.pipewire_ctrl import (
    PipeWireController, EQ_PRESETS, EQ_FREQUENCIES, _run_cmd,
)
from src.audio.source_manager import (
    SourceManager, AudioSource, SOURCE_LABELS, SOURCE_ORDER,
)
from src.audio.ducking import (
    DuckingManager, Priority, DUCK_LEVELS, SOURCE_BOOST, FADE_BACK_DURATION,
)
from src.audio.volume import VolumeController, VOLUME_STEP, VOLUME_MIN, VOLUME_MAX


# ---------------------------------------------------------------------------
# PipeWire Controller tests
# ---------------------------------------------------------------------------

class TestPipeWireController:
    def setup_method(self):
        self.bus = EventBus()
        self.config = BCMConfig(platform_override="x86")

    def test_eq_presets_defined(self):
        for name in ["flat", "rock", "jazz", "bass_boost", "custom"]:
            assert name in EQ_PRESETS
            assert len(EQ_PRESETS[name]) == 10

    def test_eq_frequencies(self):
        assert len(EQ_FREQUENCIES) == 10
        assert EQ_FREQUENCIES[0] == 31
        assert EQ_FREQUENCIES[-1] == 16000

    def test_apply_eq_preset(self):
        pw = PipeWireController(self.config, self.bus)
        received = {}

        def capture(topic, value, ts):
            received[topic] = value

        self.bus.subscribe("audio.eq_changed", capture)

        assert pw.apply_eq_preset("rock")
        assert pw.current_eq_preset == "rock"
        assert "audio.eq_changed" in received
        assert received["audio.eq_changed"]["preset"] == "rock"

    def test_apply_invalid_preset(self):
        pw = PipeWireController(self.config, self.bus)
        assert not pw.apply_eq_preset("nonexistent")

    def test_set_volume_simulated(self):
        pw = PipeWireController(self.config, self.bus)
        received = {}

        def capture(topic, value, ts):
            received[topic] = value

        self.bus.subscribe("audio.volume_changed", capture)

        assert pw.set_volume(50)
        assert received.get("audio.volume_changed") == 50

    def test_set_volume_clamping(self):
        pw = PipeWireController(self.config, self.bus)
        assert pw.set_volume(150)  # Clamped to 100
        assert pw.set_volume(-10)  # Clamped to 0

    def test_set_mute_simulated(self):
        pw = PipeWireController(self.config, self.bus)
        received = {}

        def capture(topic, value, ts):
            received[topic] = value

        self.bus.subscribe("audio.mute_changed", capture)

        assert pw.set_mute(True)
        assert received.get("audio.mute_changed") is True

    def test_list_sinks_simulated(self):
        pw = PipeWireController(self.config, self.bus)
        if not pw.available:
            sinks = pw.list_sinks()
            assert len(sinks) == 1
            assert sinks[0]["name"] == "simulated_sink"


# ---------------------------------------------------------------------------
# Source Manager tests
# ---------------------------------------------------------------------------

class TestSourceManager:
    def setup_method(self):
        self.bus = EventBus()
        self.mgr = SourceManager(self.bus)

    def test_default_source(self):
        assert self.mgr.current == AudioSource.BLUETOOTH

    def test_source_labels_defined(self):
        for source in AudioSource:
            assert source in SOURCE_LABELS

    def test_switch_to_available(self):
        assert self.mgr.switch_to(AudioSource.BLUETOOTH)
        assert self.mgr.current == AudioSource.BLUETOOTH

    def test_switch_publishes_event(self):
        received = {}

        def capture(topic, value, ts):
            received[topic] = value

        self.bus.subscribe("audio.source_changed", capture)
        self.bus.subscribe("audio.source_label", capture)

        self.mgr.switch_to(AudioSource.BLUETOOTH)
        assert received.get("audio.source_changed") == "bluetooth"
        assert received.get("audio.source_label") == "BT Audio"

    def test_switch_to_unavailable(self):
        # FM radio not in available set by default
        assert not self.mgr.switch_to(AudioSource.FM_RADIO)

    def test_add_source(self):
        self.mgr.add_source(AudioSource.FM_RADIO)
        assert self.mgr.switch_to(AudioSource.FM_RADIO)
        assert self.mgr.current == AudioSource.FM_RADIO

    def test_cycle_next(self):
        self.mgr.add_source(AudioSource.ANDROID_AUTO)
        # Start at bluetooth, cycle should go to next available
        initial = self.mgr.current
        next_src = self.mgr.cycle_next()
        assert next_src != initial or len(self.mgr.available_sources) == 1

    def test_remove_source_fallback(self):
        self.mgr.add_source(AudioSource.FM_RADIO)
        self.mgr.switch_to(AudioSource.FM_RADIO)
        self.mgr.remove_source(AudioSource.FM_RADIO)
        # Should fall back to bluetooth
        assert self.mgr.current == AudioSource.BLUETOOTH

    def test_media_button_cycles(self):
        self.mgr.add_source(AudioSource.ANDROID_AUTO)
        initial = self.mgr.current
        self.bus.publish("input.media_button", True)
        assert self.mgr.current != initial or len(self.mgr.available_sources) == 1

    def test_available_sources(self):
        available = self.mgr.available_sources
        assert AudioSource.BLUETOOTH in available

    def test_current_label(self):
        assert self.mgr.current_label == "BT Audio"


# ---------------------------------------------------------------------------
# Ducking Manager tests
# ---------------------------------------------------------------------------

class TestDuckingManager:
    def setup_method(self):
        self.bus = EventBus()
        self.ducking = DuckingManager(self.bus)

    def test_initial_state(self):
        assert self.ducking.current_duck_db == 0.0
        assert len(self.ducking.active_priorities) == 0
        assert self.ducking.highest_priority is None

    def test_duck_levels_defined(self):
        for p in Priority:
            assert p in DUCK_LEVELS

    def test_source_boost_defined(self):
        for p in Priority:
            assert p in SOURCE_BOOST

    def test_activate_parking(self):
        self.ducking.activate(Priority.PARKING)
        assert Priority.PARKING in self.ducking.active_priorities
        assert self.ducking.current_duck_db == -18.0
        assert self.ducking.highest_priority == Priority.PARKING

    def test_activate_voice(self):
        self.ducking.activate(Priority.VOICE)
        assert self.ducking.current_duck_db == -12.0

    def test_activate_phone(self):
        self.ducking.activate(Priority.PHONE)
        assert self.ducking.current_duck_db == -15.0

    def test_highest_priority_wins(self):
        self.ducking.activate(Priority.PHONE)    # -15dB
        self.ducking.activate(Priority.PARKING)  # -18dB (higher priority)
        assert self.ducking.current_duck_db == -18.0
        assert self.ducking.highest_priority == Priority.PARKING

    def test_deactivate_recalculates(self):
        self.ducking.activate(Priority.PARKING)  # -18dB
        self.ducking.activate(Priority.PHONE)    # -15dB
        self.ducking.deactivate(Priority.PARKING)
        # Phone still active — should be -15dB
        assert self.ducking.current_duck_db == -15.0

    def test_publishes_duck_events(self):
        received = {}

        def capture(topic, value, ts):
            received[topic] = value

        self.bus.subscribe("audio.duck_level", capture)
        self.bus.subscribe("audio.music_gain", capture)
        self.bus.subscribe("audio.priority_source_boost", capture)

        self.ducking.activate(Priority.VOICE)
        assert received.get("audio.duck_level") == -12.0
        assert received.get("audio.music_gain") == -12.0
        assert received.get("audio.priority_source_boost") == 3.0

    def test_event_triggers_parking(self):
        self.bus.publish("parking.active", True)
        assert Priority.PARKING in self.ducking.active_priorities

        self.bus.publish("parking.active", False)
        assert Priority.PARKING not in self.ducking.active_priorities

    def test_event_triggers_voice(self):
        self.bus.publish("audio.voice_announcement", True)
        assert Priority.VOICE in self.ducking.active_priorities

    def test_event_triggers_phone(self):
        self.bus.publish("audio.phone_call", True)
        assert Priority.PHONE in self.ducking.active_priorities

    def test_priority_ordering(self):
        assert Priority.PARKING < Priority.VOICE < Priority.PHONE < Priority.MUSIC


# ---------------------------------------------------------------------------
# Volume Controller tests
# ---------------------------------------------------------------------------

class TestVolumeController:
    def setup_method(self):
        self.bus = EventBus()
        self.config = BCMConfig(platform_override="x86")
        self.pw = PipeWireController(self.config, self.bus)

    def test_initial_volume(self):
        vol = VolumeController(self.pw, self.bus, initial_volume=70)
        assert vol.volume == 70

    def test_set_volume(self):
        vol = VolumeController(self.pw, self.bus, initial_volume=50)
        vol.set_volume(80)
        assert vol.volume == 80

    def test_volume_clamping(self):
        vol = VolumeController(self.pw, self.bus, initial_volume=50)
        vol.set_volume(150)
        assert vol.volume == VOLUME_MAX
        vol.set_volume(-10)
        assert vol.volume == VOLUME_MIN

    def test_volume_publishes_event(self):
        received = {}

        def capture(topic, value, ts):
            received[topic] = value

        self.bus.subscribe("audio.volume", capture)
        vol = VolumeController(self.pw, self.bus, initial_volume=60)
        assert received.get("audio.volume") == 60

        vol.set_volume(75)
        assert received.get("audio.volume") == 75

    def test_volume_up_event(self):
        vol = VolumeController(self.pw, self.bus, initial_volume=50)
        self.bus.publish("input.volume_up", None)
        assert vol.volume == 50 + VOLUME_STEP

    def test_volume_down_event(self):
        vol = VolumeController(self.pw, self.bus, initial_volume=50)
        self.bus.publish("input.volume_down", None)
        assert vol.volume == 50 - VOLUME_STEP

    def test_volume_up_custom_step(self):
        vol = VolumeController(self.pw, self.bus, initial_volume=50)
        self.bus.publish("input.volume_up", 10)
        assert vol.volume == 60

    def test_no_change_same_volume(self):
        vol = VolumeController(self.pw, self.bus, initial_volume=50)
        count = [0]

        def capture(topic, value, ts):
            count[0] += 1

        self.bus.subscribe("audio.volume", capture)
        count[0] = 0  # Reset after init publish
        vol.set_volume(50)  # Same value
        assert count[0] == 0  # No event published

    def test_volume_constants(self):
        assert VOLUME_MIN == 0
        assert VOLUME_MAX == 100
        assert VOLUME_STEP > 0
