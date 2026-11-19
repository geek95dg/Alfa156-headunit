/**
 * Przytrzymaj, aby potwierdzić — przycisk „PRZYTRZYMAJ 2 s – ZADZWOŃ 112”
 * i „Rozłącz” (1 s) w oknie wypadku (plan H; components/crash_modal.js).
 *
 * Dlaczego tak:
 *  - Po uderzeniu ekran dotyka się przypadkiem: kolanem, łokciem, ręką
 *    szukającą oparcia. Zwykłe stuknięcie w „112” mogłoby zadzwonić — dlatego
 *    akcja wymaga PRZYTRZYMANIA przez hold_ms (2000) z pierścieniem postępu,
 *    a przez arm_delay_ms (700) od pojawienia się przycisku nie reaguje wcale
 *    (palec, który właśnie zamknął co innego, nie trafi w 112).
 *  - Puszczenie, pointercancel, utrata przechwycenia (lostpointercapture) albo
 *    zjechanie palcem poza przycisk = zero, od nowa.
 *  - Po wyzwoleniu przycisk jest zablokowany (stan „fired”), aż właściciel
 *    wywoła rearm() — drugi palec ani powtórny timer nie wyzwolą drugi raz.
 *  - Spóźniony timer (przeglądarka zdławiła timery, timer z poprzedniego
 *    przytrzymania) nic nie robi: każde przytrzymanie ma swój żeton, a timer
 *    sprawdza też, czy naprawdę minęło hold_ms.
 *  - Menu długiego dotknięcia Chromium (kiosk) jak w screens/android_auto.js:
 *    touch-action:none, preventDefault na pointerdown/touchstart/contextmenu,
 *    setPointerCapture — inaczej po ~0,5 s przeglądarka anuluje wskaźnik
 *    (pointercancel) i przytrzymanie 2 s nigdy by się nie udało.
 *
 * Czysta logika (createHold) nie dotyka DOM — tests/js/hold_eval.js uruchamia
 * ją w zwykłym node ze sztucznym zegarem i timerami (jak gestures.js).
 * attach(el, opts) podpina ją pod element. Ładowany przed crash_modal.js
 * (index.html), dostępny jako window.BCMHold.
 */
(function (root) {
    "use strict";

    const HOLD_MS = 2000;
    const ARM_DELAY_MS = 700;
    const TICK_MS = 50;

    function _int(v, lo, hi, dflt) {
        return typeof v === "number" && isFinite(v) && v >= lo && v <= hi ? Math.round(v) : dflt;
    }

    /**
     * Maszyna stanów przytrzymania (bez DOM).
     *
     * opts: holdMs, armDelayMs, now() (ms), setTimeout/clearTimeout,
     * setInterval/clearInterval (wstrzykiwane w testach), onProgress(frac),
     * onFire(), onReset(reason).
     *
     * Metody: press(pointerId) → "holding" | "not_armed" | "busy" | "fired";
     * release(id), cancel(id), leave(id); rearm(delayMs) — po wyzwoleniu
     * (albo gdy żądanie się nie udało) przycisk znów działa po delayMs;
     * destroy(); state(); progress() 0..1; armed().
     */
    function createHold(opts) {
        const o = opts || {};
        const holdMs = _int(o.holdMs, 300, 10000, HOLD_MS);
        const armDelayMs = _int(o.armDelayMs, 0, 10000, ARM_DELAY_MS);
        const now = typeof o.now === "function" ? o.now : () => Date.now();
        const setT = o.setTimeout || ((fn, ms) => setTimeout(fn, ms));
        const clearT = o.clearTimeout || ((id) => clearTimeout(id));
        const setI = o.setInterval || ((fn, ms) => setInterval(fn, ms));
        const clearI = o.clearInterval || ((id) => clearInterval(id));
        const onProgress = typeof o.onProgress === "function" ? o.onProgress : () => {};
        const onFire = typeof o.onFire === "function" ? o.onFire : () => {};
        const onReset = typeof o.onReset === "function" ? o.onReset : () => {};

        let armedAt = now() + armDelayMs;
        let state = "idle";            // idle | holding | fired | dead
        let pointer = null;
        let startAt = 0;
        let token = 0;
        let timer = null;
        let ticker = null;

        function _stopTimers() {
            if (timer !== null) { clearT(timer); timer = null; }
            if (ticker !== null) { clearI(ticker); ticker = null; }
        }

        function progress() {
            if (state === "fired") return 1;
            if (state !== "holding") return 0;
            return Math.max(0, Math.min(1, (now() - startAt) / holdMs));
        }

        function _due(my) {
            // Spóźniony / cudzy timer: inne przytrzymanie albo już puszczone.
            if (my !== token || state !== "holding") return;
            const held = now() - startAt;
            if (held < holdMs) {
                // Timer odpalił za wcześnie (zegar ≠ timery): poczekaj resztę.
                timer = setT(() => _due(my), holdMs - held);
                return;
            }
            _stopTimers();
            state = "fired";
            token += 1;
            onProgress(1);
            onFire();
        }

        function press(id) {
            if (state === "dead") return "dead";
            if (state === "fired") return "fired";
            if (state === "holding") return "busy";       // drugi palec
            if (now() < armedAt) return "not_armed";
            state = "holding";
            pointer = id === undefined ? null : id;
            startAt = now();
            token += 1;
            const my = token;
            timer = setT(() => _due(my), holdMs);
            ticker = setI(() => {
                if (my === token && state === "holding") onProgress(progress());
            }, TICK_MS);
            onProgress(0);
            return "holding";
        }

        function _reset(id, reason) {
            if (state !== "holding") return false;
            if (id !== undefined && id !== null && pointer !== null && id !== pointer) return false;
            _stopTimers();
            token += 1;
            state = "idle";
            pointer = null;
            onProgress(0);
            onReset(reason);
            return true;
        }

        return {
            press,
            release: (id) => _reset(id, "released"),
            cancel: (id) => _reset(id, "cancelled"),
            leave: (id) => _reset(id, "left"),
            rearm(delayMs) {
                if (state === "dead") return;
                _stopTimers();
                token += 1;
                state = "idle";
                pointer = null;
                armedAt = now() + _int(delayMs, 0, 10000, 0);
                onProgress(0);
            },
            destroy() {
                _stopTimers();
                token += 1;
                state = "dead";
            },
            state: () => state,
            progress,
            armed: () => state !== "dead" && now() >= armedAt,
            holdMs,
            armDelayMs,
        };
    }

    /**
     * Podpina przytrzymanie pod element (pointer events). Zwraca
     * { hold, detach() }. Element dostaje touch-action:none i brak
     * zaznaczania; kliknięcie (click) z niego nie idzie dalej, więc nic pod
     * spodem (np. „dotknij, aby zamknąć”) nie zareaguje na przytrzymanie.
     */
    function attach(el, opts) {
        const h = createHold(opts);
        if (!el || typeof el.addEventListener !== "function") return { hold: h, detach() { h.destroy(); } };
        try {
            el.style.touchAction = "none";
            el.style.userSelect = "none";
            el.style.webkitUserSelect = "none";
            el.style.webkitTouchCallout = "none";
        } catch (e) { /* stub element */ }

        function inside(e) {
            if (typeof el.getBoundingClientRect !== "function") return true;
            const b = el.getBoundingClientRect();
            return e.clientX >= b.left && e.clientX <= b.right
                && e.clientY >= b.top && e.clientY <= b.bottom;
        }
        const onDown = (e) => {
            if (e.pointerType === "mouse" && e.button !== 0) return;
            if (e.cancelable) e.preventDefault();
            e.stopPropagation();
            if (h.press(e.pointerId) === "holding") {
                try { el.setPointerCapture(e.pointerId); } catch (err) { /* works without */ }
            }
        };
        const onMove = (e) => {
            if (h.state() === "holding" && !inside(e)) h.leave(e.pointerId);
        };
        const onUp = (e) => {
            if (e.cancelable) e.preventDefault();
            h.release(e.pointerId);
        };
        const onCancel = (e) => { h.cancel(e.pointerId); };
        // Bez przechwycenia (setPointerCapture się nie udał) palec, który
        // zjechał z przycisku, daje pointerleave; z przechwyceniem — dopiero
        // po puszczeniu (wtedy to już nic nie zmienia).
        const onLeave = (e) => { h.leave(e.pointerId); };
        const noDefault = (e) => { if (e.cancelable) e.preventDefault(); };
        const swallow = (e) => { if (e.cancelable) e.preventDefault(); e.stopPropagation(); };
        const pairs = [["pointerdown", onDown], ["pointermove", onMove], ["pointerup", onUp],
                       ["pointercancel", onCancel], ["lostpointercapture", onCancel],
                       ["pointerleave", onLeave], ["contextmenu", noDefault],
                       ["click", swallow]];
        for (const [type, fn] of pairs) el.addEventListener(type, fn);
        el.addEventListener("touchstart", noDefault, { passive: false });
        return {
            hold: h,
            detach() {
                for (const [type, fn] of pairs) el.removeEventListener(type, fn);
                el.removeEventListener("touchstart", noDefault, { passive: false });
                h.destroy();
            },
        };
    }

    const api = { createHold, attach, HOLD_MS, ARM_DELAY_MS, TICK_MS };
    if (typeof module !== "undefined" && module.exports) module.exports = api;
    if (root) root.BCMHold = api;
})(typeof window !== "undefined" ? window : null);
