"""Language-specific command definitions — Polish and English.

Each language defines:
    - wake_word: phrase to activate voice listening
    - commands: mapping of spoken phrase → action event name
    - announcements: TTS strings for BCM alerts
"""

from typing import Any


# Action constants (published to event bus)
ACTION_SHOW_TEMPERATURE = "voice.cmd.show_temperature"
ACTION_TURN_ON_RADIO = "voice.cmd.turn_on_radio"
ACTION_NEXT_TRACK = "voice.cmd.next_track"
ACTION_PREV_TRACK = "voice.cmd.prev_track"
ACTION_VOLUME_UP = "input.volume_up"
ACTION_VOLUME_DOWN = "input.volume_down"
ACTION_SHOW_CONSUMPTION = "voice.cmd.show_consumption"
ACTION_CAR_STATUS = "voice.cmd.car_status"
ACTION_START_RECORDING = "voice.cmd.start_recording"
ACTION_STOP_RECORDING = "voice.cmd.stop_recording"
ACTION_CHANGE_LANGUAGE = "voice.cmd.change_language"
ACTION_CHANGE_THEME = "voice.cmd.change_theme"


LANGUAGES: dict[str, dict[str, Any]] = {
    "pl": {
        "name": "Polski",
        "code": "pl",
        "wake_word": "hej komputer",
        "vosk_model": "vosk-model-small-pl",
        "commands": {
            "pokaż temperaturę": ACTION_SHOW_TEMPERATURE,
            "pokaz temperature": ACTION_SHOW_TEMPERATURE,  # without diacritics
            "włącz radio": ACTION_TURN_ON_RADIO,
            "wlacz radio": ACTION_TURN_ON_RADIO,
            "następny utwór": ACTION_NEXT_TRACK,
            "nastepny utwor": ACTION_NEXT_TRACK,
            "poprzedni utwór": ACTION_PREV_TRACK,
            "poprzedni utwor": ACTION_PREV_TRACK,
            "głośniej": ACTION_VOLUME_UP,
            "glosniej": ACTION_VOLUME_UP,
            "ciszej": ACTION_VOLUME_DOWN,
            "pokaż zużycie": ACTION_SHOW_CONSUMPTION,
            "pokaz zuzycie": ACTION_SHOW_CONSUMPTION,
            "status samochodu": ACTION_CAR_STATUS,
            "nagrywaj": ACTION_START_RECORDING,
            "zatrzymaj nagrywanie": ACTION_STOP_RECORDING,
            "zmień język": ACTION_CHANGE_LANGUAGE,
            "zmien jezyk": ACTION_CHANGE_LANGUAGE,
            "zmień styl": ACTION_CHANGE_THEME,
            "zmien styl": ACTION_CHANGE_THEME,
        },
        "announcements": {
            "icing_warning": "Uwaga, temperatura spada poniżej zera, możliwy lód na drodze",
            "engine_overheat": "Uwaga, wysoka temperatura silnika",
            "low_fuel": "Niski poziom paliwa",
            "service_reminder": "Zbliża się termin przeglądu",
        },
        "responses": {
            "wake_ack": "Słucham",
            "command_ok": "Wykonuję",
            "command_unknown": "Nie rozumiem polecenia",
            "timeout": "Czas minął",
        },
    },
    "en": {
        "name": "English",
        "code": "en",
        "wake_word": "hey computer",
        "vosk_model": "vosk-model-small-en-us",
        "commands": {
            "show temperature": ACTION_SHOW_TEMPERATURE,
            "turn on radio": ACTION_TURN_ON_RADIO,
            "next track": ACTION_NEXT_TRACK,
            "previous track": ACTION_PREV_TRACK,
            "volume up": ACTION_VOLUME_UP,
            "volume down": ACTION_VOLUME_DOWN,
            "show consumption": ACTION_SHOW_CONSUMPTION,
            "car status": ACTION_CAR_STATUS,
            "start recording": ACTION_START_RECORDING,
            "stop recording": ACTION_STOP_RECORDING,
            "change language": ACTION_CHANGE_LANGUAGE,
            "change theme": ACTION_CHANGE_THEME,
        },
        "announcements": {
            "icing_warning": "Warning, temperature below zero, possible ice on road",
            "engine_overheat": "Warning, engine temperature high",
            "low_fuel": "Low fuel level",
            "service_reminder": "Service due soon",
        },
        "responses": {
            "wake_ack": "Listening",
            "command_ok": "Done",
            "command_unknown": "Command not recognized",
            "timeout": "Timed out",
        },
    },
}


def get_language(code: str) -> dict[str, Any]:
    """Get language definition by code ('pl' or 'en')."""
    return LANGUAGES.get(code, LANGUAGES["en"])


def get_wake_word(lang_code: str) -> str:
    """Get wake word for a language."""
    return get_language(lang_code)["wake_word"]


def get_commands(lang_code: str) -> dict[str, str]:
    """Get command→action mapping for a language."""
    return get_language(lang_code)["commands"]


def get_announcement(lang_code: str, key: str) -> str:
    """Get a TTS announcement string."""
    return get_language(lang_code)["announcements"].get(key, key)


def get_response(lang_code: str, key: str) -> str:
    """Get a TTS response string."""
    return get_language(lang_code)["responses"].get(key, key)
