"""Dashboard UI translations — Polish and English.

All dashboard-visible strings are defined here. The renderer reads
config language setting and passes the lang code to t().
"""

from typing import Any

STRINGS: dict[str, dict[str, str]] = {
    "pl": {
        # Screen titles
        "screen.a1": "A1: GŁÓWNY",
        "screen.a2": "A2: SPALANIE",
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

        # Days of week
        "mon": "PON", "tue": "WT", "wed": "ŚR", "thu": "CZW",
        "fri": "PT", "sat": "SOB", "sun": "NIE",

        # Months
        "jan": "STY", "feb": "LUT", "mar": "MAR", "apr": "KWI",
        "may": "MAJ", "jun": "CZE", "jul": "LIP", "aug": "SIE",
        "sep": "WRZ", "oct": "PAŹ", "nov": "LIS", "dec": "GRU",
    },
    "en": {
        # Screen titles
        "screen.a1": "A1: MAIN",
        "screen.a2": "A2: CONSUMPTION",
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
