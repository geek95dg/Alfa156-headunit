/**
 * Baner „Wybudzono” (#wake-banner) — sesja po zdalnym wybudzeniu, plan E
 * (wersja z buforem, modules.remote_session).
 *
 * Dane: data.remote_session z /ws = web_viewer._remote_session_summary
 * tematu power.remote_session z src/power/remote_session.py. app.js woła
 * WakeBanner.sync(data.remote_session) przy KAŻDEJ paczce danych, na każdym
 * ekranie (także A2 — Android Auto).
 *
 * Dlaczego tak:
 *  - Komputer obudził Nano #2 (drzwi kierowcy, podczerwień z telefonu
 *    w aucie, wejście EXT) i po dzierżawie sam go uśpi. Kierowca, który
 *    akurat siedzi w aucie, musi to WIDZIEĆ i móc zmienić — stąd baner
 *    globalny jak okno wypadku, ale NIE modalny: pasek u dołu ekranu, reszta
 *    ekranu (AA, ekrany BCM, gesty) działa dalej, więc NIE jest na liście
 *    GESTURE_OVERLAYS w app.js.
 *  - „Wybudzono: telefon — uśpienie za mm:ss [Nie usypiaj 30 min]
 *    [Uśpij teraz]”: POST /api/remote_session/hold | /sleep (tylko
 *    z loopbacku, limit na serwerze; treść żądania to pusty obiekt — krok
 *    i budżet ustala backend). Poza kioskiem (telefon pasażera w sieci
 *    auta) tylko napis — serwer i tak odmówi (403).
 *  - Odliczanie: backend podaje lease_left_s w chwili budowania paczki;
 *    baner zakotwicza je na zegarze monotonicznym (performance.now) i sam
 *    odświeża tekst co sekundę — paczki mogą przychodzić rzadziej. Gdy
 *    wcześniej niż dzierżawa sesję skończy bezczynność (idle_left_s, po
 *    „Nie usypiaj”), baner odlicza do NIEJ z dopiskiem „bez użycia” —
 *    kierowca widzi, kiedy komputer naprawdę zaśnie.
 *  - Dotyk ekranu w kiosku to używanie: w trakcie sesji każde pointerdown
 *    (co najwyżej raz na 5 s) idzie do backendu jako {"type":"activity"}
 *    po /ws/input (DataStore.sendActivity) i odsuwa uśpienie po
 *    bezczynności. Tylko kiosk — serwer i tak liczy wyłącznie loopback.
 *  - Położenie: bottom 72 px — NAD paskiem nawigacji (#bcm-navbar, h-14,
 *    wysuwany od dołu) i poza dolną strefą gestu (EDGE_PX = 40 px w
 *    gestures.js), więc baner nie zasłania przycisków paska i nie zjada
 *    przeciągnięcia od dolnej krawędzi. Bez stopPropagation na touchstart:
 *    app.js sam przepuszcza stuknięcia w przyciski nad paskiem.
 *  - z-index 250: nad zwykłą treścią, nakładką ściemniania (190), kamerą
 *    cofania i klawiaturą (200), POD oknem wypadku (300) i powiadomieniami
 *    (400). Szkielet budowany raz na tryb (sesja / usypianie); co sekundę
 *    zmienia się tylko tekst (textContent) — przerysowanie zgubiłoby
 *    stuknięcie.
 *  - Inline style (Tailwind jest prekompilowany), wszystkie teksty przez
 *    textContent albo esc(), kliknięcia jednym delegowanym listenerem po
 *    atrybutach data-* (bez JS w atrybutach).
 */
const WakeBanner = (() => {
    "use strict";
    const ID = "wake-banner";
    const Z_INDEX = 250;
    const REASONS = ["ir", "door", "ext"];
    const LOOPBACK_HOSTS = ["localhost", "127.0.0.1", "::1", "[::1]"];
    const ROUTES = { hold: "/api/remote_session/hold", sleep: "/api/remote_session/sleep" };
    const TAP_GUARD_MS = 1500;
    const ACTIVITY_PING_MS = 5000;
    const BOTTOM_PX = 72;
    const CMD_SHOW_S = 30;
    const ENDED_SHOWN = ["released", "idle", "lease_end"];
    let _el = null;
    let _mode = null;          // "session|<krok>" | "ending" | null — klucz szkieletu
    let _view = null;
    let _endAt = null;         // performance.now() ms, końca dzierżawy
    let _timer = null;
    let _lastTap = {};
    let _lastPing = 0;
    let _pingBound = false;

    function esc(s) {
        return String(s == null ? "" : s)
            .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
    }

    function _t() {
        return (typeof App !== "undefined" && App && App.t) ? App.t.bind(App) : ((k, d) => d);
    }

    function _now() {
        return (typeof performance !== "undefined" && performance.now) ? performance.now() : Date.now();
    }

    function _kiosk() {
        const host = (typeof location !== "undefined" && location.hostname) || "";
        return LOOPBACK_HOSTS.indexOf(host) >= 0;
    }

    /** Pure: the payload as plain, checked values; null = no banner. */
    function normalize(rs) {
        if (!rs || typeof rs !== "object") return null;
        const int = (v, hi) => (Number.isInteger(v) && v >= 0 && v <= hi ? v : null);
        const state = rs.state;
        if (state !== "session" && state !== "ending") return null;
        if (state === "ending" && ENDED_SHOWN.indexOf(rs.ended) < 0) return null;
        const cmd = rs.cmd && typeof rs.cmd === "object" ? rs.cmd : null;
        const lease = int(rs.lease_left_s, 5400);
        const idle = state === "session" ? int(rs.idle_left_s, 5400) : null;
        // Idle suspend before the lease end: count down to it.
        const idleFirst = idle !== null && (lease === null || idle < lease);
        return {
            state,
            reason: REASONS.indexOf(rs.reason) >= 0 ? rs.reason : "",
            left: idleFirst ? idle : lease,
            idleFirst,
            sleeping: state === "ending" || rs.sleep_pending === true,
            canHold: state === "session" && rs.can_hold === true && rs.sleep_pending !== true,
            step: int(rs.hold_step_min, 60) || 0,
            cmdError: cmd && cmd.ok === false && typeof cmd.error === "string"
                && typeof cmd.ts === "number" && isFinite(cmd.ts)
                && (Date.now() / 1000 - cmd.ts) < CMD_SHOW_S ? cmd.action : null,
        };
    }

    /** Pure: mm:ss of whole seconds ("—" when unknown). */
    function fmtLeft(s) {
        if (!Number.isInteger(s) || s < 0) return "—";
        const m = Math.floor(s / 60);
        const r = s % 60;
        return String(m).padStart(2, "0") + ":" + String(r).padStart(2, "0");
    }

    /** Pure: the texts for a view. */
    function texts(v, t, leftS) {
        const reason = {
            ir: t("wake_r_ir", "telefon"),
            door: t("wake_r_door", "drzwi"),
            ext: t("wake_r_ext", "wejście EXT"),
        }[v.reason] || t("wake_r_unknown", "z zewnątrz");
        const head = t("wake_title", "Wybudzono") + ": " + reason;
        if (v.sleeping) return { line: head + " — " + t("wake_sleeping", "usypianie…"), note: "" };
        const note = v.cmdError === "hold" ? t("wake_hold_failed", "nie udało się przedłużyć — spróbuj ponownie")
            : (v.cmdError === "sleep" || v.cmdError === "idle"
                ? t("wake_sleep_failed", "nie udało się uśpić — komputer zaśnie po dzierżawie") : "");
        const unused = v.idleFirst ? " (" + t("wake_if_unused", "bez użycia") + ")" : "";
        return { line: head + " — " + t("wake_until", "uśpienie za") + " " + fmtLeft(leftS) + unused, note };
    }

    function _leftNow() {
        if (_endAt === null) return null;
        return Math.max(0, Math.ceil((_endAt - _now()) / 1000));
    }

    function _skeleton(mode, v, t) {
        const btn = "min-height:44px;padding:0 16px;border-radius:12px;font-size:14px;font-weight:700;"
            + "border:none;cursor:pointer;white-space:nowrap;touch-action:manipulation";
        let buttons = "";
        if (mode === "session") {
            if (!_kiosk()) {
                buttons = `<span style="font-size:12px;color:#fde68a">${esc(t("wake_kiosk_only", "Sterowanie tylko na ekranie w aucie"))}</span>`;
            } else {
                buttons = `<button type="button" data-wake-action="hold" style="${btn};background:#f59e0b;color:#111827">${esc(t("wake_hold", "Nie usypiaj") + " " + (v.step || 30) + " min")}</button>`
                    + `<button type="button" data-wake-action="sleep" style="${btn};background:#374151;color:#fff">${esc(t("wake_sleep_now", "Uśpij teraz"))}</button>`;
            }
        }
        return `<span class="material-symbols-outlined" style="font-size:24px;color:#fbbf24">power_settings_new</span>`
            + `<div style="flex:1;min-width:0;display:flex;flex-direction:column;gap:2px">`
            + `<span data-wake-line style="font-size:15px;font-weight:700;white-space:nowrap;overflow:hidden;text-overflow:ellipsis"></span>`
            + `<span data-wake-note style="font-size:12px;color:#fca5a5"></span></div>`
            + `<div style="display:flex;gap:8px;align-items:center">${buttons}</div>`;
    }

    function _text(sel, value) {
        const node = _el && _el.querySelector(sel);
        if (node && node.textContent !== value) node.textContent = value;
    }

    function _render() {
        if (!_el || !_view) return;
        const t = _t();
        const tx = texts(_view, t, _leftNow());
        _text("[data-wake-line]", tx.line);
        _text("[data-wake-note]", tx.note);
        const hold = _el.querySelector("[data-wake-action='hold']");
        if (hold) hold.style.display = _view.canHold ? "" : "none";
    }

    async function _post(action) {
        if (!Object.prototype.hasOwnProperty.call(ROUTES, action)) return 0;
        const now = Date.now();
        if (_lastTap[action] && now - _lastTap[action] < TAP_GUARD_MS) return null;
        _lastTap[action] = now;
        try {
            const res = await fetch(ROUTES[action], {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: "{}",
            });
            return res.status;
        } catch (e) { return 0; /* the backend state (cmd) shows what happened */ }
    }

    function _onClick(e) {
        const target = e.target && e.target.closest ? e.target.closest("[data-wake-action]") : null;
        if (!target || !_el || !_el.contains(target)) return;
        const action = target.getAttribute("data-wake-action");
        if (action === "hold" || action === "sleep") _post(action);
    }

    /** Any touch on the kiosk during a session = use (throttled ping). */
    function _onPointer() {
        if (!_view || _view.sleeping || !_kiosk()) return;
        const now = Date.now();
        if (_lastPing && now - _lastPing >= 0 && now - _lastPing < ACTIVITY_PING_MS) return;
        try {
            // Only a ping that left counts for the throttle: with /ws/input
            // down the next touch tries again.
            if (typeof DataStore !== "undefined" && DataStore && DataStore.sendActivity
                && DataStore.sendActivity()) {
                _lastPing = now;
            }
        } catch (e) { /* best effort */ }
    }

    function _bindPing(on) {
        if (typeof document === "undefined" || on === _pingBound) return;
        _pingBound = on;
        // Capture + passive: sees every touch first, never delays or
        // cancels it (the screen under the banner keeps working).
        if (on) document.addEventListener("pointerdown", _onPointer, { capture: true, passive: true });
        else document.removeEventListener("pointerdown", _onPointer, { capture: true });
    }

    function _remove() {
        _bindPing(false);
        if (_el && _el.parentNode) _el.parentNode.removeChild(_el);
        _el = null;
        _mode = null;
        _view = null;
        _endAt = null;
        if (_timer) { clearInterval(_timer); _timer = null; }
    }

    /** Apply data.remote_session (null/undefined = module off = no banner). */
    function sync(rs) {
        if (typeof document === "undefined" || !document.body) return;
        const v = normalize(rs);
        if (!v) { _remove(); return; }
        const t = _t();
        // The hold label carries the step (it shrinks with the budget).
        const mode = v.sleeping ? "ending" : "session|" + v.step;
        if (!_el || !_el.parentNode) {
            _el = document.getElementById(ID) || document.createElement("div");
            _el.id = ID;
            _el.setAttribute("role", "status");
            _el.style.cssText = "position:fixed;left:12px;right:12px;bottom:" + BOTTOM_PX + "px;z-index:" + Z_INDEX + ";"
                + "display:flex;align-items:center;gap:12px;padding:8px 12px;border-radius:16px;"
                + "background:rgba(30,27,75,0.96);color:#fff;border:1px solid #f59e0b;"
                + "box-shadow:0 4px 24px rgba(0,0,0,0.5);user-select:none;-webkit-user-select:none";
            _el.addEventListener("click", _onClick);
            document.body.appendChild(_el);
            _mode = null;
        }
        if (_mode !== mode) {
            _el.innerHTML = _skeleton(v.sleeping ? "ending" : "session", v, t);
            _mode = mode;
        }
        _view = v;
        _bindPing(true);
        _endAt = v.left === null ? null : _now() + v.left * 1000;
        if (!_timer && typeof setInterval === "function") _timer = setInterval(_render, 1000);
        _render();
    }

    return { sync, normalize, texts, fmtLeft, Z_INDEX, ID, BOTTOM_PX, ACTIVITY_PING_MS };
})();

if (typeof window !== "undefined") window.WakeBanner = WakeBanner;
if (typeof module !== "undefined" && module.exports) module.exports = WakeBanner;
