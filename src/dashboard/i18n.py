"""Dashboard UI translations — Polish and English.

All dashboard-visible strings are defined here. The renderer reads
config language setting and passes the lang code to t().
"""

from typing import Any

STRINGS: dict[str, dict[str, str]] = {
    "pl": {
        # Screen titles (v8.5)
        "screen.a1": "A1: GŁÓWNY",
        "screen.a2": "A2: ANDROID AUTO",
        "screen.a3": "A3: PODRÓŻ",
        "screen.a4": "A4: POGODA",
        "screen.a5": "A5: SERWIS",
        "screen.a6": "A6: NAGRANIA DVR",
        "screen.a7": "A7: PERFORMANCE",
        "screen.settings": "USTAWIENIA",
        # Legacy screen titles
        "screen.b1": "B1: KLIMAT",
        "screen.b2": "B2: PALIWO",
        "screen.c1": "C1: TRIP",
        "screen.c2": "C2: SERWIS",

        # Units
        "km/h": "km/h",
        "mph": "mph",
        "rpm": "RPM",
        "rpm_x1000": "RPM x1000",
        "l_100km": "L/100KM",
        "bar": "BAR",
        "km": "km",
        "liters": "L",
        "hours": "H",
        "pct": "%",

        # A1: Main
        "instant_cons": "SPALANIE CHW.",
        "speed": "PRĘDKOŚĆ",

        # A2: Consumption
        "avg_consumption": "ŚR. SPALANIE",
        "inst_consumption": "CHW. SPALANIE",
        "boost": "DOŁADOWANIE",
        "trip_dist": "DYSTANS",
        "trip_time": "CZAS PODRÓŻY",
        "fuel_used": "ZUŻYTE PALIWO",

        # B1: Climate
        "ext_temp": "TEMP ZEW.",
        "defrost": "ODLADZANIE SZYBY",
        "auto_air": "KLIMAT AUTO",
        "active": "AKTYWNE",
        "inactive": "NIEAKTYWNE",

        # B2: Fuel
        "range": "ZASIĘG",
        "avg_used": "ŚR. ZUŻYCIE",
        "reserve_active": "REZERWA AKTYWNA",
        "reserve_off": "REZERWA",

        # C1: Trip
        "distance": "DYSTANS",
        "time": "CZAS",
        "avg_fuel": "ŚR. SPALANIE",
        "long_push_reset": "DŁUGI PUSH → RESET TRIP",

        # C2: Service
        "engine_oil": "OLEJ SILNIKA",
        "tires": "OPONY",
        "tire_pressure": "CIŚNIENIE",
        "service_interval": "PRZEGLĄD",
        "oil_level": "POZIOM OLEJU",
        "oil_wear": "ZUŻYCIE OLEJU",
        "long_push_confirm": "DŁUGI PUSH → POTWIERDŹ SERWIS",
        "ok": "OK",
        "no_sensor": "BRAK CZUJNIKA",
        "pressure_ok": "CIŚNIENIE OK",
        "not_available": "N/D",
        "tpms_future": "TPMS (W PRZYSZŁOŚCI)",

        # Status bar / gear
        "gear_n": "N",
        "gear_r": "R",

        # Overlays
        "parking": "PARKOWANIE",
        "reverse_no_camera": "BRAK KAMERY COFANIA",
        "reverse_camera_hint": "Podłącz kamerę USB do portu",
        "reverse_closest": "NAJBLIŻEJ",
        "icing_title": "UWAGA OBLODZENIE",
        "icing_msg": "Temperatura spada poniżej 3°C",
        "icing_msg2": "Możliwy lód na drodze",

        # Settings
        "settings_title": "USTAWIENIA BCM",
        "swc_title": "MAPOWANIE PRZYCISKÓW SWC",
        "settings_nav": "GÓRA/DÓŁ: Nawiguj | LEWO/PRAWO: Zmień | BACK: Str. SWC | HOME: Zapisz",
        "swc_nav": "GÓRA/DÓŁ: Nawiguj | LEWO/PRAWO: Zmień | BACK: Ogólne | HOME: Zapisz",

        # v8 Frontend — UI labels
        "theme": "MOTYW",
        "language": "JĘZYK",
        "speed_units": "JEDNOSTKI PRĘDKOŚCI",
        "temp_units": "JEDNOSTKI TEMPERATURY",
        "back_to_dash": "Powrót do panelu",
        "engine_temp": "TEMP. SILNIKA",
        "fuel_level": "POZIOM PALIWA",
        "coolant": "PŁYN CHŁODNICZY",
        "fuel": "PALIWO",
        "oil_press": "CIŚN. OLEJU",
        "battery": "AKUMULATOR",
        "notifications": "POWIADOMIENIA",
        "system_notifications": "POWIADOMIENIA SYSTEMOWE",
        "now_playing": "TERAZ GRANE",
        "avg_speed": "ŚR. PRĘDKOŚĆ",
        "drive_time": "CZAS JAZDY",
        "voltage": "NAPIĘCIE",
        "est_range": "ZASIĘG SZACUNKOWY",
        "optimal": "OPTYMALNY",
        "hot": "GORĄCY",
        "warming": "ROZGRZEWANIE",
        "trip_title": "PODRÓŻ A2",
        "consumption": "SPALANIE",
        "fuel_consumption": "ZUŻYCIE PALIWA (L/100km)",
        "driving_style": "STYL JAZDY",
        "current_session": "BIEŻĄCA SESJA",
        "trip_analytics": "ANALIZA PODRÓŻY",
        "weather": "POGODA",
        "forecast": "PROGNOZA",
        "wind": "WIATR",
        "humidity": "WILGOTNOŚĆ",
        "feels_like": "Odczuwalna",
        "gps_active": "GPS AKTYWNY",
        "live_tracking": "ŚLEDZENIE NA ŻYWO",
        "system_status": "STATUS SYSTEMU",
        "all_ok": "WSZYSTKO OK",
        "warning": "OSTRZEŻENIE",
        "engine": "SILNIK",
        "oil_life": "ŻYWOTNOŚĆ OLEJU",
        "diagnostics": "DIAGNOSTYKA",
        "next_service": "NASTĘPNY PRZEGLĄD",
        "vehicle": "POJAZD",
        "eco": "EKO",
        "normal": "NORMALNY",
        "dynamic": "DYNAMICZNY",
        "sport": "SPORT",
        # v8.5 new screens
        "android_auto": "Android Auto",
        "connect_aa": "Podłącz telefon przez USB lub WiFi",
        "dvr": "Nagrania DVR",
        "dvr_export": "Eksport na USB",
        "dvr_front": "Przód",
        "dvr_rear": "Tył",
        "performance_title": "Performance",
        "boost": "DOŁADOWANIE",
        "timer_0_100": "0-100 km/h",
        "best_time": "Najlepszy",
        "peak_boost": "Szczyt boost",
        "g_force": "G-FORCE",
        "dtc_read": "Odczytaj",
        "dtc_clear": "Wyczyść",
        "dtc_none": "Brak kodów błędów",
        "dtc_reading": "Odczytywanie...",
        "dtc_cleared": "Kody wyczyszczone",
        "dtc_confirm": "Wyczyścić kody błędów z ECU?",
        "dtc_error": "Błąd odczytu",
        "dvr_empty": "Brak nagrań",
        "dvr_export_done": "Eksport rozpoczęty",
        "weather_search": "Szukaj lokalizacji...",

        # Days of week
        "mon": "PON", "tue": "WT", "wed": "ŚR", "thu": "CZW",
        "fri": "PT", "sat": "SOB", "sun": "NIE",

        # Months
        "jan": "STY", "feb": "LUT", "mar": "MAR", "apr": "KWI",
        "may": "MAJ", "jun": "CZE", "jul": "LIP", "aug": "SIE",
        "sep": "WRZ", "oct": "PAŹ", "nov": "LIS", "dec": "GRU",
    },
    "en": {
        # Screen titles (v8.5)
        "screen.a1": "A1: MAIN",
        "screen.a2": "A2: ANDROID AUTO",
        "screen.a3": "A3: TRIP",
        "screen.a4": "A4: WEATHER",
        "screen.a5": "A5: SERVICE",
        "screen.a6": "A6: DVR RECORDINGS",
        "screen.a7": "A7: PERFORMANCE",
        "screen.settings": "SETTINGS",
        # Legacy screen titles
        "screen.b1": "B1: CLIMATE",
        "screen.b2": "B2: FUEL",
        "screen.c1": "C1: TRIP",
        "screen.c2": "C2: SERVICE",

        # Units
        "km/h": "km/h",
        "mph": "mph",
        "rpm": "RPM",
        "rpm_x1000": "RPM x1000",
        "l_100km": "L/100KM",
        "bar": "BAR",
        "km": "km",
        "liters": "L",
        "hours": "H",
        "pct": "%",

        # A1: Main
        "instant_cons": "INST. CONS.",
        "speed": "SPEED",

        # A2: Consumption
        "avg_consumption": "AVG CONSUMPTION",
        "inst_consumption": "INST. CONSUMPTION",
        "boost": "BOOST",
        "trip_dist": "TRIP DIST.",
        "trip_time": "TRIP TIME",
        "fuel_used": "FUEL USED",

        # B1: Climate
        "ext_temp": "EXT. TEMP",
        "defrost": "WINDSHIELD DE-FROST",
        "auto_air": "AUTO AIR",
        "active": "ACTIVE",
        "inactive": "INACTIVE",

        # B2: Fuel
        "range": "RANGE",
        "avg_used": "AVG USED",
        "reserve_active": "RESERVE ACTIVE",
        "reserve_off": "RESERVE",

        # C1: Trip
        "distance": "DISTANCE",
        "time": "TIME",
        "avg_fuel": "AVG CONSUMPTION",
        "long_push_reset": "LONG PUSH → RESET TRIP",

        # C2: Service
        "engine_oil": "ENGINE OIL",
        "tires": "TIRES",
        "tire_pressure": "PRESSURE",
        "service_interval": "SERVICE",
        "oil_level": "OIL LEVEL",
        "oil_wear": "OIL WEAR",
        "long_push_confirm": "LONG PUSH → CONFIRM SERVICE",
        "ok": "OK",
        "no_sensor": "NO SENSOR",
        "pressure_ok": "PRESSURE OK",
        "not_available": "N/A",
        "tpms_future": "TPMS (FUTURE)",

        # Status bar / gear
        "gear_n": "N",
        "gear_r": "R",

        # Overlays
        "parking": "PARKING",
        "reverse_no_camera": "NO REVERSE CAMERA",
        "reverse_camera_hint": "Connect USB camera to port",
        "reverse_closest": "CLOSEST",
        "icing_title": "ICING WARNING",
        "icing_msg": "Temperature dropping below 3°C",
        "icing_msg2": "Possible ice on road",

        # Settings
        "settings_title": "BCM SETTINGS",
        "swc_title": "SWC BUTTON MAPPING",
        "settings_nav": "UP/DOWN: Navigate | LEFT/RIGHT: Change | BACK: SWC Page | HOME: Save & Close",
        "swc_nav": "UP/DOWN: Navigate | LEFT/RIGHT: Remap | BACK: General | HOME: Save & Close",

        # v8 Frontend — UI labels
        "theme": "THEME",
        "language": "LANGUAGE",
        "speed_units": "SPEED UNITS",
        "temp_units": "TEMP UNITS",
        "back_to_dash": "Back to Dashboard",
        "engine_temp": "ENGINE TEMP",
        "fuel_level": "FUEL LEVEL",
        "coolant": "COOLANT",
        "fuel": "FUEL",
        "oil_press": "OIL PRESS",
        "battery": "BATTERY",
        "notifications": "NOTIFICATIONS",
        "system_notifications": "SYSTEM NOTIFICATIONS",
        "now_playing": "NOW PLAYING",
        "avg_speed": "AVG SPEED",
        "drive_time": "DRIVE TIME",
        "voltage": "VOLTAGE",
        "est_range": "EST. RANGE",
        "optimal": "OPTIMAL",
        "hot": "HOT",
        "warming": "WARMING",
        "trip_title": "TRIP A2",
        "consumption": "CONSUMPTION",
        "fuel_consumption": "FUEL CONSUMPTION (L/100km)",
        "driving_style": "DRIVING STYLE",
        "current_session": "CURRENT SESSION",
        "trip_analytics": "TRIP ANALYTICS",
        "weather": "WEATHER",
        "forecast": "FORECAST",
        "wind": "WIND",
        "humidity": "HUMIDITY",
        "feels_like": "Feels like",
        "gps_active": "GPS ACTIVE",
        "live_tracking": "LIVE TRACKING",
        "system_status": "SYSTEM STATUS",
        "all_ok": "ALL OK",
        "warning": "WARNING",
        "engine": "ENGINE",
        "oil_life": "OIL LIFE",
        "diagnostics": "DIAGNOSTICS",
        "next_service": "NEXT SERVICE",
        "vehicle": "VEHICLE",
        "eco": "ECO",
        "normal": "NORMAL",
        "dynamic": "DYNAMIC",
        "sport": "SPORT",
        # v8.5 new screens
        "android_auto": "Android Auto",
        "connect_aa": "Connect your phone via USB or WiFi",
        "dvr": "DVR Recordings",
        "dvr_export": "Export to USB",
        "dvr_front": "Front",
        "dvr_rear": "Rear",
        "performance_title": "Performance",
        "boost": "BOOST",
        "timer_0_100": "0-100 km/h",
        "best_time": "Best",
        "peak_boost": "Peak Boost",
        "g_force": "G-FORCE",
        "dtc_read": "Read",
        "dtc_clear": "Clear",
        "dtc_none": "No error codes",
        "dtc_reading": "Reading...",
        "dtc_cleared": "Codes cleared",
        "dtc_confirm": "Clear all error codes from ECU?",
        "dtc_error": "Read failed",
        "dvr_empty": "No recordings found",
        "dvr_export_done": "Export started",
        "weather_search": "Search location...",

        # Days
        "mon": "MON", "tue": "TUE", "wed": "WED", "thu": "THU",
        "fri": "FRI", "sat": "SAT", "sun": "SUN",

        # Months
        "jan": "JAN", "feb": "FEB", "mar": "MAR", "apr": "APR",
        "may": "MAY", "jun": "JUN", "jul": "JUL", "aug": "AUG",
        "sep": "SEP", "oct": "OCT", "nov": "NOV", "dec": "DEC",
    },
}

# Day/month key lists for easy date formatting
_DAY_KEYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
_MONTH_KEYS = ["jan", "feb", "mar", "apr", "may", "jun",
               "jul", "aug", "sep", "oct", "nov", "dec"]


def t(key: str, lang: str = "pl") -> str:
    """Get translated string for key in given language."""
    return STRINGS.get(lang, STRINGS["pl"]).get(key, key)


def format_date(lang: str = "pl") -> str:
    """Format current date as 'CZW 14 MAR 2026' style."""
    import time as _time
    now = _time.localtime()
    day_key = _DAY_KEYS[now.tm_wday]
    month_key = _MONTH_KEYS[now.tm_mon - 1]
    return f"{t(day_key, lang)} {now.tm_mday} {t(month_key, lang)} {now.tm_year}"
