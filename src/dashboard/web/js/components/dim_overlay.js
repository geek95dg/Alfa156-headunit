/**
 * Programowe ściemnianie ekranu (#bcm-dim-overlay) — modules.auto_brightness,
 * plan D3.
 *
 * Dane: data.display_dim z /ws = web_viewer._display_dim_summary tematu
 * display.dim z src/power/brightness.py: {level, brightness_pct}. app.js woła
 * DimOverlay.sync(data.display_dim) przy KAŻDEJ paczce danych, na każdym
 * ekranie (także A2 — Android Auto).
 *
 * Dlaczego tak:
 *  - Ekran w aucie testowym jest zasilany z USB i nie ma żadnego sterowania
 *    jasnością, więc backend „css” przyciemnia OBRAZ: JEDNA czarna nakładka
 *    na całe okno z opacity = level. 100 % jasności = brak nakładki.
 *  - z-index 190 (DimOverlay.Z_INDEX): nad zwykłą treścią ekranów (w tym
 *    obrazem AA), ale POD wszystkim, co musi być w pełni jasne:
 *      kamera cofania  #reverse-overlay  z-index 200 (w #app, który nie
 *                      tworzy własnego kontekstu nakładania),
 *      okno wypadku    #crash-modal      z-index 300 (na <body>; w nim widok
 *                      rozmowy z 112 i panel dla dyspozytora),
 *    a także klawiatura ekranowa i okna potwierdzeń (200), powiadomienia
 *    (400) i splash (9999). Test w Chromium sprawdza tę kolejność.
 *  - pointer-events:none — nakładka nigdy nie zabiera dotyku (AA, przyciski).
 *  - Przejście opacity 1 s: zmiana jasności jest płynna, bez mignięć.
 *  - level ograniczony do 0..MAX_LEVEL (0,9) także tutaj: zły payload może
 *    przyciemnić, nigdy wyczernić ekranu. Brak danych (moduł wyłączony —
 *    produkcja), level 0 (np. tryb DDC/CI) albo śmieci = nakładka usunięta.
 *  - Tailwind jest prekompilowany: tylko style inline.
 */
const DimOverlay = (() => {
    "use strict";
    const ID = "bcm-dim-overlay";
    const Z_INDEX = 190;
    const MAX_LEVEL = 0.9;
    let _el = null;
    let _level = 0;

    /** Opacity for a payload, or 0 = no overlay. Never throws. */
    function levelOf(dim) {
        if (!dim || typeof dim !== "object") return 0;
        const v = dim.level;
        if (typeof v !== "number" || !isFinite(v) || v <= 0.001) return 0;
        return Math.min(MAX_LEVEL, v);
    }

    function _remove() {
        if (_el && _el.parentNode) _el.parentNode.removeChild(_el);
        _el = null;
        _level = 0;
    }

    /** Apply data.display_dim (null/undefined = module off = no overlay). */
    function sync(dim) {
        if (typeof document === "undefined" || !document.body) return;
        const level = levelOf(dim);
        if (level <= 0) {
            _remove();
            return;
        }
        if (!_el || !_el.parentNode) {
            _el = document.getElementById(ID) || document.createElement("div");
            _el.id = ID;
            _el.setAttribute("aria-hidden", "true");
            _el.style.cssText = "position:fixed;inset:0;z-index:" + Z_INDEX + ";"
                + "background:#000;pointer-events:none;opacity:0;"
                + "transition:opacity 1s linear";
            document.body.appendChild(_el);
            _level = 0;
            // Start from 0 so the first value fades in too (next frame).
            const el = _el;
            const target = String(level);
            const raf = typeof requestAnimationFrame === "function"
                ? requestAnimationFrame : ((fn) => setTimeout(fn, 16));
            raf(() => { if (el === _el) el.style.opacity = target; });
            _level = level;
            return;
        }
        if (level !== _level) {
            _el.style.opacity = String(level);
            _level = level;
        }
    }

    return { sync, levelOf, Z_INDEX, MAX_LEVEL, ID };
})();

if (typeof window !== "undefined") window.DimOverlay = DimOverlay;
if (typeof module !== "undefined" && module.exports) module.exports = DimOverlay;
