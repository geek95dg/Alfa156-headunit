/**
 * Okno wypadku (#crash-modal) — SMS po stłuczce, plan F „UI”.
 *
 * Dane: data.crash_sms z /ws (web_viewer._crash_sms_summary stanu
 * crash.sms_state z src/safety/crash_sms.py). app.js woła CrashModal.sync()
 * z _syncCrashState przy KAŻDEJ paczce danych, niezależnie od ekranu — okno
 * działa także na A2 (Android Auto), bo wisi na <body> (nie w #app, który
 * navigateTo() czyści) z z-index 300, nad nakładką AA, kamerą cofania i
 * klawiaturą. Jest na liście GESTURE_OVERLAYS w app.js, więc gesty z krawędzi
 * nie przełączają pod nim ekranu.
 *
 * Dlaczego tak:
 *  - Termin wysyłki trzyma TELEFON (agent Termux) — okno tylko pokazuje
 *    odliczanie z backendu (countdown_left_s, raz na sekundę) i przekazuje
 *    decyzję kierowcy: POST /api/crash/cancel | /api/crash/send_now |
 *    /api/crash/follow_up {event_id} (tylko z loopbacku, limit żądań na
 *    serwerze). „Jestem OK – wyślij SMS odwołujący” po wysłanym SMS-ie ma
 *    WŁASNĄ trasę: spóźnione stuknięcie w ANULUJ nigdy nie wyśle SMS-a
 *    odwołującego.
 *  - Poza kioskiem (telefon pasażera w sieci auta) okno jest tylko do
 *    odczytu: serwer i tak odmówi (403), więc zamiast przycisków jest
 *    napis, że anulować można tylko na ekranie w aucie.
 *  - Szkielet okna budowany jest RAZ na tryb (odliczanie / wynik); co sekundę
 *    zmieniają się tylko teksty (textContent). Pełne przerysowanie co sekundę
 *    zgubiłoby stuknięcie, które zaczęło się przed przerysowaniem.
 *  - Przycisk „ANULUJ – nic się nie stało” zajmuje ≥ 1/3 ekranu (62vw × 56vh)
 *    po lewej; prawa kolumna (19vw) jest oddzielona pustym pasem 15vw — tam,
 *    w kolejnej partii (plan H), trafi przycisk 112 (data-crash-112-slot).
 *  - Krótki pisk WebAudio co 5 s, dopóki odliczanie naprawdę trwa (zostało
 *    > 0 s; cichnie po anulowaniu, po wysyłce i gdy telefon przestał
 *    odpowiadać po terminie).
 *  - Po wyniku (wysłano / anulowano / brak telefonu …) okno pokazuje wynik
 *    i zamyka się po stuknięciu albo po 60 s. Tak samo „brak potwierdzenia
 *    z telefonu” (unconfirmed: termin minął, telefon milczy — mógł już
 *    wysłać). Wyjątek: telefon MOŻE trzymać zdarzenie mimo błędu
 *    uzbrajania (may_send) — wtedy okno mówi „SMS MOŻE zostać wysłany”,
 *    ma ANULUJ i nie zamyka się od przypadkowego stuknięcia.
 *  - Inline style (Tailwind jest prekompilowany — nowe klasy by nie istniały);
 *    wszystkie teksty przez textContent albo esc(); obsługa kliknięć jednym
 *    delegowanym listenerem po atrybutach data-* (bez JS w atrybutach).
 */
const CrashModal = (() => {
    const ACTIVE = ["armed", "pending", "sending"];
    const FINAL = ["sent", "partial", "failed", "cancelled", "failed_no_phone", "limited"];
    const COUNTDOWN = ["armed", "pending"];
    const EVENT_ID_RE = /^[0-9a-f]{8,32}$/;
    const BEEP_EVERY_MS = 5000;
    const LOOPBACK_HOSTS = ["localhost", "127.0.0.1", "::1", "[::1]"];
    const RESULT_CLOSE_MS = 60000;
    const TAP_GUARD_MS = 1500;
    const FORCED = {
        agent_not_ready: ["crash_forced_agent", "agent w telefonie nie jest gotowy"],
        no_verified_test: ["crash_forced_no_test", "brak potwierdzonego testowego SMS-a"],
        test_too_old: ["crash_forced_old_test", "testowy SMS starszy niż 30 dni"],
        sensors_not_streaming: ["crash_forced_sensors", "brak danych z czujników telefonu"],
        sensor_rate_low: ["crash_forced_rate", "za wolne próbkowanie czujników"],
        not_calibrated: ["crash_forced_calib", "czujniki telefonu nieskalibrowane"],
    };

    function esc(s) {
        return String(s == null ? "" : s)
            .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
    }

    function _t() {
        return (typeof App !== "undefined" && App && App.t) ? App.t.bind(App) : ((k, d) => d);
    }

    /** Pure: the payload as plain, checked values (never trusted as-is). */
    function normalize(cs) {
        if (!cs || typeof cs !== "object") return null;
        const state = typeof cs.state === "string" ? cs.state : "idle";
        if (ACTIVE.indexOf(state) < 0 && FINAL.indexOf(state) < 0) return null;
        const eid = typeof cs.event_id === "string" && EVENT_ID_RE.test(cs.event_id)
            ? cs.event_id : null;
        if (!eid) return null;
        const int = (v, hi) => (Number.isInteger(v) && v >= 0 && v <= hi ? v : null);
        const results = Array.isArray(cs.results) ? cs.results.slice(0, 3)
            .filter((r) => r && typeof r.state === "string") : [];
        return {
            state, eid,
            left: int(cs.countdown_left_s, 120),
            recipients: int(cs.recipients_n, 3) || 0,
            phoneOk: cs.phone_ok === true,
            dry: cs.dry_run !== false,
            reason: Object.prototype.hasOwnProperty.call(FORCED, cs.forced_dry_run_reason)
                ? cs.forced_dry_run_reason : "",
            error: typeof cs.error === "string" ? cs.error : "",
            modal: cs.modal === true,
            cancelPending: cs.cancel_pending === true,
            sendNowPending: cs.send_now_pending === true,
            canFollowUp: cs.can_follow_up === true,
            maySend: state === "failed_no_phone" && cs.may_send === true,
            unconfirmed: (state === "pending" || state === "sending") && cs.unconfirmed === true,
            cancelSms: cs.cancel_sms && typeof cs.cancel_sms.state === "string"
                ? cs.cancel_sms.state : null,
            sent: results.filter((r) => r.state === "sent" || r.state === "sent_dry").length,
            total: results.length,
        };
    }

    /** Pure: which skeleton — "result" (closable) for a final state and for
     *  "no confirmation from the phone", else "countdown". */
    function modeOf(v) {
        return FINAL.indexOf(v.state) >= 0 || v.unconfirmed ? "result" : "countdown";
    }

    /** Pure: the key a closed result is remembered under. */
    function dismissKey(v) {
        return v.eid + "|" + (v.unconfirmed ? "unconfirmed" : v.state);
    }

    /** Pure: is the window up? `dismissed` = dismissKey() of what the driver
     *  closed (only results can be closed — never a running countdown). */
    function shouldShow(cs, dismissed) {
        const v = normalize(cs);
        if (!v || !v.modal) return false;
        if (modeOf(v) === "result" && dismissed === dismissKey(v)) return false;
        return true;
    }

    /** Pure: may a tap outside the buttons close this view? Not while the
     *  phone may still send (may_send) and nothing was cancelled yet: a
     *  stray tap must not hide the only ANULUJ. */
    function closableByTap(v) {
        return modeOf(v) === "result" && !(v.maySend && !v.cancelPending);
    }

    /** Is this page the head unit's own kiosk? Only there do the buttons
     *  work (/api/crash/* is loopback only). */
    function isKiosk() {
        try {
            return typeof location !== "undefined"
                && LOOPBACK_HOSTS.indexOf(String(location.hostname)) >= 0;
        } catch (e) { return false; }
    }

    /** Pure: the texts of the window for a normalized payload. */
    function texts(v, t) {
        t = t || ((k, d) => d);
        const out = {};
        out.title = t("crash_title", "MOŻLIWY WYPADEK");
        out.recipients = t("crash_recipients", "odbiorcy SMS: {n}").replace("{n}", () => String(v.recipients));
        out.dry = v.dry ? t("crash_dry_run", "TRYB TESTOWY – SMS nie zostanie wysłany") : "";
        out.reason = v.reason
            ? t("crash_forced", "wymuszony tryb testowy: {reason}")
                .replace("{reason}", () => t(FORCED[v.reason][0], FORCED[v.reason][1])) : "";
        if (v.state === "sending") {
            out.count = "";
            out.label = t("crash_sending", "WYSYŁANIE SMS…");
        } else if (v.state === "armed" && v.left === 0) {
            // A resumed / late event: the phone gets its own 15 s once it
            // answers — nothing is being sent yet.
            out.count = "0";
            out.label = t("crash_phone_connecting", "Łączenie z telefonem…");
        } else {
            out.count = v.left == null ? "" : String(v.left);
            out.label = v.left === 0 ? t("crash_sending", "WYSYŁANIE SMS…")
                : t("crash_countdown_label", "SMS do bliskich za (s):");
        }
        if (v.state === "armed" && v.left === 0 && !v.cancelPending) {
            out.phone = t("crash_phone_late", "Po połączeniu telefon odczeka jeszcze 15 s – można anulować");
        } else if (v.cancelPending) {
            out.phone = v.phoneOk ? t("crash_cancelling", "Anulowanie…")
                : t("crash_cancel_no_phone", "Anulowanie – brak połączenia z telefonem; dotrze, gdy wróci");
        } else if (v.state === "armed" && !v.phoneOk) {
            out.phone = t("crash_phone_connecting", "Łączenie z telefonem…");
        } else if (v.phoneOk) {
            out.phone = t("crash_phone_ok", "Telefon w aucie trzyma termin – wyśle SMS sam, nawet bez BCM");
        } else {
            out.phone = t("crash_phone_lost", "Brak połączenia z telefonem – telefon wyśle SMS o czasie");
        }
        out.cancel = v.cancelPending ? t("crash_cancelling", "Anulowanie…")
            : t("crash_cancel", "ANULUJ – nic się nie stało");
        out.sendNow = v.sendNowPending ? t("crash_send_now_pending", "Wysyłam…")
            : t("crash_send_now", "Wyślij teraz");
        // Result view
        const n = String(v.total || v.recipients);
        const ok = String(v.sent);
        const results = {
            sent: t("crash_result_sent", "SMS wysłany ({ok} z {n})"),
            partial: t("crash_result_partial", "SMS wysłany tylko do {ok} z {n} odbiorców"),
            failed: t("crash_result_failed", "Nie udało się wysłać SMS-a"),
            cancelled: t("crash_result_cancelled", "Anulowano – SMS nie został wysłany"),
            failed_no_phone: t("crash_no_phone", "Brak połączenia z telefonem – SMS NIE zostanie wysłany"),
            limited: t("crash_result_limited", "Limit SMS-ów po stłuczce – tym razem SMS NIE zostanie wysłany"),
        };
        let result = results[v.state] || "";
        if (v.unconfirmed) {
            result = v.cancelPending
                ? t("crash_unconfirmed_cancel", "Anulowanie niepotwierdzone – telefon mógł już wysłać SMS")
                : t("crash_unconfirmed", "Brak potwierdzenia z telefonu – telefon mógł już wysłać SMS");
        } else if (v.state === "failed_no_phone" && v.maySend) {
            result = v.cancelPending
                ? t("crash_cancel_no_phone", "Anulowanie – brak połączenia z telefonem; dotrze, gdy wróci")
                : t("crash_no_phone_may_send", "Telefon nie odpowiada – SMS MOŻE zostać wysłany o czasie");
        } else if (v.cancelSms === "failed") {
            result = v.state === "cancelled"
                ? t("crash_result_cancel_sms_failed", "Anulowano – SMS odwołujący niepotwierdzony")
                : t("crash_result_follow_up_failed", "SMS wysłany – SMS odwołujący NIE wyszedł");
        } else if (v.state === "cancelled" && v.cancelSms) {
            result = t("crash_result_cancel_sms", "Anulowano – do odbiorców poszedł SMS odwołujący");
        } else if (v.state === "cancelled" && v.error === "no_phone") {
            result = t("crash_result_cancel_unconfirmed", "Anulowano – telefon jeszcze nie potwierdził");
        } else if (v.state === "failed" && v.error === "no_recipients") {
            result = t("crash_err_no_recipients", "Brak odbiorców – SMS NIE zostanie wysłany (Ustawienia → SMS po stłuczce)");
        } else if (v.state === "failed" && v.error === "crash_sms_off") {
            result = t("crash_err_off", "W telefonie wyłączony SMS po stłuczce – SMS NIE zostanie wysłany");
        } else if (v.state === "failed" && v.error === "rate_limited") {
            result = t("crash_err_phone_limit", "Telefon odmówił (limit SMS-ów) – SMS NIE zostanie wysłany");
        }
        out.result = result.replace("{ok}", () => ok).replace("{n}", () => n);
        out.resultDry = v.dry && (v.state === "sent" || v.state === "partial")
            ? t("crash_result_dry", "tryb testowy – nic naprawdę nie wysłano") : "";
        out.followUp = t("crash_follow_up", "Jestem OK – wyślij SMS odwołujący");
        // The result view's cancel: ANULUJ while the phone may still send,
        // "Jestem OK" wording once BCM's deadline is gone (it may have sent:
        // a cancel then means the cancel SMS — never just "silence it").
        out.resultCancel = v.unconfirmed ? out.followUp : t("crash_cancel", "ANULUJ – nic się nie stało");
        out.close = closableByTap(v) ? t("crash_tap_close", "Dotknij, aby zamknąć") : "";
        out.remote = t("crash_kiosk_only_note", "Anulować można tylko na ekranie w aucie");
        return out;
    }

    const BTN = "border:none;border-radius:18px;font-weight:900;cursor:pointer;"
        + "display:flex;align-items:center;justify-content:center;text-align:center;"
        + "touch-action:manipulation;-webkit-tap-highlight-color:transparent;";

    /** Pure: the countdown skeleton (dynamic parts are filled by _fill). */
    function countdownHtml(tx) {
        return `<div data-crash-mode="countdown" style="position:absolute;inset:0;display:flex;flex-direction:column;padding:2vh 2vw;box-sizing:border-box;gap:2vh">
            <div style="display:flex;align-items:center;gap:3vw;height:36vh;min-height:0">
                <div data-crash-count style="font-size:min(30vh,22vw);line-height:1;font-weight:900;color:#fff;min-width:22vw;text-align:center;font-variant-numeric:tabular-nums"></div>
                <div style="display:flex;flex-direction:column;gap:0.6vh;min-width:0;flex:1;max-height:100%;overflow:hidden;line-height:1.2">
                    <div data-crash-title style="font-size:4.6vh;font-weight:900;color:#fecaca;letter-spacing:1px">${esc(tx.title)}</div>
                    <div data-crash-label style="font-size:3.2vh;font-weight:700;color:#fff"></div>
                    <div data-crash-recipients style="font-size:2.8vh;color:#fca5a5"></div>
                    <div data-crash-phone style="font-size:2.6vh;color:#fde68a"></div>
                    <div data-crash-dry style="display:none;align-self:flex-start;font-size:2.6vh;font-weight:900;color:#111;background:#facc15;border-radius:8px;padding:0.3vh 1vw"></div>
                    <div data-crash-reason style="display:none;font-size:2.3vh;color:#fde68a"></div>
                </div>
            </div>
            <div style="display:flex;flex:1;min-height:0;gap:0">
                <button type="button" data-crash-action="cancel" style="${BTN}width:62vw;height:56vh;font-size:6vh;background:#16a34a;color:#fff;padding:2vh 2vw;box-shadow:0 0 0 4px rgba(255,255,255,0.25)"></button>
                <div data-crash-remote style="display:none;width:62vw;height:56vh;font-size:4vh;font-weight:700;color:#fde68a;align-items:center;justify-content:center;text-align:center;border:2px dashed #fca5a5;border-radius:18px;box-sizing:border-box;padding:2vh 2vw">${esc(tx.remote)}</div>
                <div data-crash-gap style="width:15vw;flex:none"></div>
                <div style="display:flex;flex-direction:column;width:19vw;gap:2vh;min-height:0">
                    <button type="button" data-crash-action="send_now" style="${BTN}height:18vh;font-size:3vh;background:#7f1d1d;color:#fff;border:2px solid #fca5a5;padding:1vh 1vw"></button>
                    <!-- Plan H (kolejna partia): tu trafi przycisk „PRZYTRZYMAJ 2 s –
                         ZADZWOŃ 112” — po przeciwnej stronie niż ANULUJ, z odstępem
                         ≥ 15% szerokości. Teraz miejsce jest tylko zarezerwowane. -->
                    <div data-crash-112-slot style="flex:1;min-height:0"></div>
                </div>
            </div>
        </div>`;
    }

    /** Pure: the result skeleton. */
    function resultHtml(tx) {
        return `<div data-crash-mode="result" style="position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;justify-content:center;padding:4vh 4vw;box-sizing:border-box;gap:3vh;text-align:center">
            <span class="material-symbols-outlined" data-crash-icon style="font-size:16vh;color:#fff"></span>
            <div data-crash-result style="font-size:5.5vh;font-weight:900;color:#fff;max-width:90vw"></div>
            <div data-crash-result-dry style="display:none;font-size:3vh;font-weight:900;color:#111;background:#facc15;border-radius:8px;padding:0.5vh 1.5vw"></div>
            <button type="button" data-crash-action="cancel" style="${BTN}display:none;font-size:4.4vh;background:#16a34a;color:#fff;padding:3vh 5vw;min-width:50vw;box-shadow:0 0 0 4px rgba(255,255,255,0.25)"></button>
            <button type="button" data-crash-action="follow_up" style="${BTN}display:none;font-size:3.4vh;background:#16a34a;color:#fff;padding:2.5vh 4vw"></button>
            <div data-crash-remote style="display:none;font-size:2.8vh;font-weight:700;color:#fde68a">${esc(tx.remote)}</div>
            <div data-crash-close style="font-size:2.8vh;color:#fecaca">${esc(tx.close)}</div>
        </div>`;
    }

    // ── DOM side (kiosk) ──────────────────────────────────────────────────
    let _el = null;
    let _mode = null;
    let _eid = null;
    let _view = null;
    let _dismissed = null;
    let _beepTimer = null;
    let _closeTimer = null;
    let _audio = null;
    const _tapAt = {};

    function isOpen() { return !!(_el && _el.isConnected !== false && _el.parentNode); }

    function _beep() {
        try {
            const Ctx = (typeof window !== "undefined") && (window.AudioContext || window.webkitAudioContext);
            if (!Ctx) return;
            if (!_audio) _audio = new Ctx();
            if (_audio.state === "suspended" && _audio.resume) _audio.resume();
            const osc = _audio.createOscillator();
            const gain = _audio.createGain();
            osc.frequency.value = 1320;
            gain.gain.value = 0.2;
            osc.connect(gain); gain.connect(_audio.destination);
            osc.start();
            osc.stop(_audio.currentTime + 0.18);
        } catch (e) { /* no audio — the window is still there */ }
    }

    function _setBeeping(on) {
        if (on && !_beepTimer) {
            _beep();
            _beepTimer = setInterval(_beep, BEEP_EVERY_MS);
        } else if (!on && _beepTimer) {
            clearInterval(_beepTimer);
            _beepTimer = null;
        }
    }

    function _close() {
        _setBeeping(false);
        if (_closeTimer) { clearTimeout(_closeTimer); _closeTimer = null; }
        if (_el && _el.parentNode) _el.parentNode.removeChild(_el);
        _el = null; _mode = null; _eid = null; _view = null;
    }

    function _dismiss() {
        if (_view && modeOf(_view) === "result") _dismissed = dismissKey(_view);
        _close();
    }

    const ROUTES = { cancel: "/api/crash/cancel", send_now: "/api/crash/send_now",
                     follow_up: "/api/crash/follow_up" };

    /** POST the driver's decision; resolves to the HTTP status (0 = no
     *  answer, null = swallowed double tap). */
    async function _post(action) {
        const v = _view;
        if (!v || !Object.prototype.hasOwnProperty.call(ROUTES, action)) return null;
        const now = Date.now();
        // Per event and action: a double tap is swallowed, a tap on the
        // NEXT event's window is not.
        const key = action + "|" + v.eid;
        if (_tapAt[key] && now - _tapAt[key] < TAP_GUARD_MS) return null;
        for (const k of Object.keys(_tapAt)) if (now - _tapAt[k] > TAP_GUARD_MS) delete _tapAt[k];
        _tapAt[key] = now;
        try {
            const res = await fetch(ROUTES[action], {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ event_id: v.eid }),
            });
            return res.status;
        } catch (e) { return 0; /* the backend state (cancel_pending) shows what happened */ }
    }

    function _onClick(e) {
        const target = e.target && e.target.closest ? e.target.closest("[data-crash-action]") : null;
        if (target) {
            e.preventDefault();
            const action = target.getAttribute("data-crash-action");
            if (action === "cancel" || action === "follow_up") {
                if (_view && (_view.cancelPending)) return;
                const t = _t();
                _post(action).then((status) => {
                    if (status === null || !_el || !target.isConnected) return;
                    // The label changes only on an accepted request; a
                    // refusal says why (the backend push then shows the rest).
                    if (status >= 200 && status < 300) {
                        target.textContent = t("crash_cancelling", "Anulowanie…");
                    } else if (status === 403) {
                        target.textContent = t("crash_kiosk_only_note", "Anulować można tylko na ekranie w aucie");
                    } else if (status === 429) {
                        target.textContent = t("crash_wait", "Chwilę — spróbuj za kilka sekund");
                    }
                });
            } else if (action === "send_now") {
                _post("send_now");
            }
            return;
        }
        // A tap anywhere else closes a RESULT (never a running countdown,
        // nor the "SMS MAY still be sent" view before it was cancelled).
        // (Off the kiosk there is no ANULUJ to protect: any tap closes.)
        if (_view && (closableByTap(_view) || (!isKiosk() && modeOf(_view) === "result"))) {
            _dismiss();
        }
    }

    function _ensure(mode, tx) {
        if (!_el) {
            _el = document.createElement("div");
            _el.id = "crash-modal";
            _el.setAttribute("role", "alertdialog");
            _el.setAttribute("aria-modal", "true");
            _el.style.cssText = "position:fixed;inset:0;z-index:300;background:#450a0a;"
                + "color:#fff;overflow:hidden;user-select:none;-webkit-user-select:none;"
                + "touch-action:manipulation";
            _el.addEventListener("click", _onClick);
            // Nothing under the window may see a touch (AA overlay, gestures).
            _el.addEventListener("touchstart", (e) => e.stopPropagation(), { passive: true });
            document.body.appendChild(_el);
        }
        if (_mode !== mode) {
            _el.innerHTML = mode === "result" ? resultHtml(tx) : countdownHtml(tx);
            _mode = mode;
        }
    }

    function _text(sel, value) {
        const node = _el && _el.querySelector(sel);
        if (node && node.textContent !== value) node.textContent = value;
        return node;
    }

    function _shown(sel, on) {
        const node = _el && _el.querySelector(sel);
        if (node) node.style.display = on ? "" : "none";
        return node;
    }

    function _fill(v, tx) {
        const kiosk = isKiosk();
        _shown("[data-crash-remote]", !kiosk);
        const remote = _el && _el.querySelector("[data-crash-remote]");
        if (remote && !kiosk && _mode === "countdown") remote.style.display = "flex";
        if (_mode === "countdown") {
            _text("[data-crash-count]", tx.count);
            _text("[data-crash-label]", tx.label);
            _text("[data-crash-recipients]", tx.recipients);
            _text("[data-crash-phone]", tx.phone);
            _shown("[data-crash-dry]", !!tx.dry);
            _text("[data-crash-dry]", tx.dry);
            _shown("[data-crash-reason]", !!tx.reason);
            _text("[data-crash-reason]", tx.reason);
            const cancel = _text("[data-crash-action='cancel']", tx.cancel);
            if (cancel) {
                cancel.style.opacity = v.cancelPending ? "0.7" : "1";
                cancel.style.display = kiosk ? "flex" : "none";
            }
            const sendNow = _text("[data-crash-action='send_now']", tx.sendNow);
            if (sendNow) {
                const on = kiosk && COUNTDOWN.indexOf(v.state) >= 0 && !v.cancelPending;
                sendNow.style.visibility = on ? "visible" : "hidden";
            }
        } else {
            const icons = { sent: "mark_email_read", partial: "warning", failed: "error",
                            cancelled: "check_circle", failed_no_phone: "phonelink_erase",
                            limited: "block" };
            _text("[data-crash-icon]", v.unconfirmed ? "help" : (v.maySend ? "phonelink_erase"
                : icons[v.state] || "info"));
            _text("[data-crash-result]", tx.result);
            _shown("[data-crash-result-dry]", !!tx.resultDry);
            _text("[data-crash-result-dry]", tx.resultDry);
            const rc = _shown("[data-crash-action='cancel']",
                              kiosk && (v.maySend || v.unconfirmed) && !v.cancelPending);
            if (rc && rc.getAttribute("data-label") !== tx.resultCancel) {
                rc.setAttribute("data-label", tx.resultCancel);
                rc.textContent = tx.resultCancel;
            }
            const fu = _shown("[data-crash-action='follow_up']",
                              kiosk && v.canFollowUp && !v.cancelPending);
            if (fu) fu.textContent = tx.followUp;
            _shown("[data-crash-close]", !!tx.close);
            _text("[data-crash-close]", tx.close);
        }
    }

    /** Called by app.js on every data push (any screen). */
    function sync(cs) {
        if (typeof document === "undefined") return;
        if (!shouldShow(cs, _dismissed)) {
            if (_el) _close();
            return;
        }
        const v = normalize(cs);
        const tx = texts(v, _t());
        const mode = modeOf(v);
        if (_eid !== v.eid || (_view && (_view.state !== v.state
                                         || _view.unconfirmed !== v.unconfirmed))) {
            // A new event, or a new result of this one (e.g. "Jestem OK" →
            // cancel SMS): its own 60 s.
            if (_eid !== v.eid) _dismissed = null;
            if (_closeTimer) { clearTimeout(_closeTimer); _closeTimer = null; }
        }
        _ensure(mode, tx);
        _eid = v.eid;
        _view = v;
        _fill(v, tx);
        // Only while time is really left: a countdown stuck at 0 (the phone
        // stopped answering) must not beep over Android Auto for minutes.
        _setBeeping(mode === "countdown" && COUNTDOWN.indexOf(v.state) >= 0 && !v.cancelPending
                    && v.left !== null && v.left > 0);
        if (mode === "result" && !_closeTimer) {
            _closeTimer = setTimeout(() => { _closeTimer = null; _dismiss(); }, RESULT_CLOSE_MS);
        } else if (mode !== "result" && _closeTimer) {
            clearTimeout(_closeTimer);
            _closeTimer = null;
        }
    }

    return {
        sync, isOpen, normalize, shouldShow, texts, countdownHtml, resultHtml, esc,
        modeOf, closableByTap, isKiosk, ROUTES,
        BEEP_EVERY_MS, RESULT_CLOSE_MS,
        /** Test hooks. */
        _beeping: () => !!_beepTimer,
        _close,
    };
})();

if (typeof module !== "undefined" && module.exports) module.exports = CrashModal;
