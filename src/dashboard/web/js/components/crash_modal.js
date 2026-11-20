/**
 * Okno wypadku (#crash-modal) — SMS po stłuczce (plan F „UI”) i „Zadzwoń
 * 112” (plan H).
 *
 * Dane: data.crash_sms z /ws (web_viewer._crash_sms_summary stanu
 * crash.sms_state z src/safety/crash_sms.py) i data.call112
 * (web_viewer._call112_summary stanu crash.call112_state z
 * src/safety/call112.py). app.js woła CrashModal.sync(crash_sms, call112)
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
 *    po lewej; prawa kolumna (19vw) jest oddzielona pustym pasem 15vw — w niej
 *    (data-crash-112-slot) czerwony „PRZYTRZYMAJ 2 s – ZADZWOŃ 112”: po
 *    przeciwnej stronie niż ANULUJ, z odstępem ≥ 15% szerokości.
 *  - 112 ZAWSZE ręcznie: przytrzymanie (components/hold.js: hold_ms 2000,
 *    nieaktywny przez arm_delay_ms 700 od pojawienia się, zero po puszczeniu,
 *    pointercancel albo zjechaniu palcem), potem POST /api/crash/call112 bez
 *    numeru (numer wybiera backend: 112, a w trybie testowym numer testowy).
 *    Napis mówi, którą drogą: „telefon główny” (HFP) albo „telefon w aucie,
 *    głośnik”; w trybie testowym „TEST – dzwoni na +48...567”. Gdy żadna
 *    droga nie działa: „Zadzwoń 112 ze swojego telefonu”.
 *  - Widok „panel” (data-crash-mode="panel"): u góry pasek (Zamknij / Wróć
 *    albo „Rozłącz” przytrzymaniem 1 s po lewej; stan „Łączenie / Rozmowa
 *    mm:ss”, droga i „Jeśli połączenie było przypadkowe – nie rozłączaj
 *    się…” w środku; 112 albo „Odbierz” po prawej), pod nim panel dla
 *    dyspozytora: pozycja „52,22968 N 21,01223 E” i w stopniach, minutach,
 *    sekundach, wiek fixa i satelity (albo „ostatnia znana pozycja sprzed X
 *    min”), kierunek i prędkość przed uderzeniem, godzina, opis auta
 *    i gotowe zdanie do przeczytania — czcionka ≥ 48 px. Bez odwrotnego
 *    geokodowania. Panel jest dostępny od otwarcia okna („Pozycja dla 112”),
 *    a w trakcie rozmowy (i gdy telefon dzwoni) pokazuje się sam.
 *  - W trakcie rozmowy z 112 pisk odliczania milknie (BCM przy drodze
 *    „telefon w aucie” wycisza też swoje media — robi to backend), ale
 *    trwające odliczanie SMS-a zostaje widoczne („· SMS do bliskich za X s”)
 *    i w prawej kolumnie paska jest stuknięciowe „ANULUJ SMS” (≥ 15%
 *    szerokości od „Rozłącz” po lewej) — przypadkowe 112 przy fałszywym
 *    alarmie nie może wysłać SMS-a bez wiedzy kierowcy.
 *  - Telefon główny bez mikrofonu w rozmowie (uplink: missing z
 *    audio.call_route): „Dyspozytor może Cię nie słyszeć” i przycisk 112
 *    wraca w trakcie rozmowy z drogą „telefon w aucie” (backend najpierw
 *    rozłącza rozmowę przez telefon główny).
 *  - „Rozłącz”, które nie zadziałało: backend po 10 s zdejmuje
 *    hangup_pending, a przycisk znów daje się przytrzymać (także po
 *    odmowie agenta i awaryjnie 12 s po wysłaniu).
 *  - Po ANULUJ (SMS odwołany przed wysyłką) okno 112 nie wraca samo na
 *    cały ekran po zamknięciu wyniku — tylko na „Pozycja dla 112” albo
 *    w trakcie rozmowy (backend i tak zamyka je 60 s później).
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
 *    Opis auta (local.yaml) i wszystko z backendu idzie tylko przez
 *    textContent.
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
    // ── „Zadzwoń 112” (plan H) ──
    const C112_STATES = ["idle", "dialing", "ringing", "active", "ended", "failed"];
    const C112_LIVE = ["dialing", "ringing", "active"];
    const C112_ROUTES = { call: "/api/crash/call112", hangup: "/api/crash/call112/hangup",
                          close: "/api/crash/call112/close", answer: "/api/phone/answer" };
    const HANGUP_HOLD_MS = 1000;
    const REARM_AFTER_MS = 1500;
    // "Rozłącz" accepted (2xx) but the call still live this long after:
    // the hold works again even without a backend push (it clears
    // hangup_pending after 10 s — call112.HANGUP_CONFIRM_S).
    const HANGUP_REARM_MS = 12000;
    const SAY_FONT_PX = 30;
    const SAY_MIN_FONT_PX = 18;
    const TEST_NUMBER_RE = /^\+[0-9]{2}\.\.\.[0-9]{3}$/;
    const PATH_LABEL = {
        hfp: ["c112_path_hfp", "telefon główny"],
        car_phone: ["c112_path_car", "telefon w aucie, głośnik"],
    };
    const REASON_TEXT = {
        off: ["c112_r_off", "wyłączona"],
        not_running: ["c112_r_not_running", "agent wyłączony"],
        not_connected: ["c112_r_not_connected", "telefon niepołączony"],
        no_modem: ["c112_r_no_modem", "brak HFP (oFono)"],
        no_network: ["c112_r_no_network", "brak zasięgu"],
        call_in_progress: ["c112_r_call", "trwa inna rozmowa"],
        no_mic: ["c112_r_no_mic", "brak mikrofonu"],
        no_number: ["c112_r_no_number", "brak numeru testowego"],
        not_ready: ["c112_r_not_ready", "agent niegotowy"],
        not_capable: ["c112_r_not_capable", "brak roota albo 112 wyłączone w telefonie"],
        mode_mismatch: ["c112_r_mode", "telefon w innym trybie (test / 112)"],
    };
    const ERROR_TEXT = {
        timeout: ["c112_e_timeout", "telefon główny nie potwierdził połączenia"],
        unknown: ["c112_e_timeout", "telefon główny nie potwierdził połączenia"],
        no_modem: ["c112_e_no_modem", "telefon główny nie jest połączony do rozmów"],
        netdown: ["c112_e_netdown", "brak zasięgu sieci"],
        busy: ["c112_e_busy", "telefon zajęty inną rozmową"],
        no_phone: ["c112_e_no_phone", "brak połączenia z telefonem w aucie"],
        not_running: ["c112_e_no_phone", "brak połączenia z telefonem w aucie"],
        su_missing: ["c112_e_root", "brak uprawnień roota w telefonie"],
        su_denied: ["c112_e_root", "brak uprawnień roota w telefonie"],
        no_root: ["c112_e_root", "brak uprawnień roota w telefonie"],
        am_failed: ["c112_e_am", "telefon odrzucił wybieranie"],
        no_call: ["c112_e_no_call", "połączenie się nie rozpoczęło"],
        mode_mismatch: ["c112_e_mode", "telefon w innym trybie (test / 112)"],
        call112_off: ["c112_e_off", "112 wyłączone w telefonie"],
        rate_limited: ["c112_e_limit", "limit połączeń w telefonie – spróbuj za minutę"],
    };
    const COMPASS = [["N", "północ", "płn."], ["NE", "północny wschód", "płn.-wsch."],
                     ["E", "wschód", "wsch."], ["SE", "południowy wschód", "płd.-wsch."],
                     ["S", "południe", "płd."], ["SW", "południowy zachód", "płd.-zach."],
                     ["W", "zachód", "zach."], ["NW", "północny zachód", "płn.-zach."]];

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

    /** Pure: the countdown skeleton (dynamic parts are filled by _fill).
     *  `tx112` (texts112) adds the 112 column in data-crash-112-slot. */
    function countdownHtml(tx, tx112) {
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
                    <!-- „PRZYTRZYMAJ 2 s – ZADZWOŃ 112” (plan H): po przeciwnej
                         stronie niż ANULUJ, z odstępem ≥ 15% szerokości. -->
                    <div data-crash-112-slot style="flex:1;min-height:0;display:flex;flex-direction:column">${tx112 ? c112ColumnHtml(tx112) : ""}</div>
                </div>
            </div>
        </div>`;
    }

    // ── „Zadzwoń 112”: czyste funkcje ──────────────────────────────────────

    /** Pure: data.call112 as plain, checked values, or null when there is
     *  nothing to show (no window and no live call). */
    function normalize112(c) {
        if (!c || typeof c !== "object") return null;
        const state = C112_STATES.indexOf(c.state) >= 0 ? c.state : "idle";
        const live = C112_LIVE.indexOf(state) >= 0;
        if (c.window !== true && !live) return null;
        const eid = typeof c.event_id === "string" && EVENT_ID_RE.test(c.event_id)
            ? c.event_id : null;
        if (!eid) return null;
        const int = (v, hi) => (Number.isInteger(v) && v >= 0 && v <= hi ? v : null);
        const num = (v, lo, hi) => (typeof v === "number" && isFinite(v) && v >= lo && v <= hi
            ? v : null);
        const path = Object.prototype.hasOwnProperty.call(PATH_LABEL, c.path) ? c.path : "";
        const offer = Object.prototype.hasOwnProperty.call(PATH_LABEL, c.offer) ? c.offer : "none";
        const reasons = c.reasons && typeof c.reasons === "object" ? c.reasons : {};
        const reason = (p) => (Object.prototype.hasOwnProperty.call(REASON_TEXT, reasons[p])
            ? reasons[p] : "");
        const d = c.dispatcher && typeof c.dispatcher === "object" ? c.dispatcher : null;
        let disp = null;
        if (d) {
            let lat = num(d.lat, -90, 90);
            let lon = num(d.lon, -180, 180);
            if (lat === null || lon === null) { lat = null; lon = null; }
            const veh = d.vehicle && typeof d.vehicle === "object" ? d.vehicle : {};
            const txt = (v, n) => (typeof v === "string" ? v.slice(0, n) : "");
            disp = {
                lat, lon,
                age: lat === null ? null : int(d.fix_age_s, 1e7),
                sats: lat === null ? null : int(d.sats, 255),
                heading: int(d.heading, 359),
                speed: int(d.speed_kmh, 400),
                eventTs: num(d.event_ts, 1, 4.1e9),
                label: txt(veh.label, 32), colour: txt(veh.colour, 20), plate: txt(veh.plate, 12),
            };
        }
        return {
            eid, state, live, path,
            error: typeof c.error === "string" ? c.error : "",
            duration: int(c.duration_s, 86400),
            unverified: c.unverified === true,
            // Path A without a microphone uplink to the dispatcher.
            uplinkLost: c.uplink === "missing" && path === "hfp",
            hangupPending: c.hangup_pending === true,
            offer, fallback: c.fallback === true && offer !== "none",
            reasons: { hfp: reason("hfp"), car_phone: reason("car_phone") },
            retry: int(c.retry_after_s, 3600) || 0,
            test: c.test_mode !== false,
            testNumber: typeof c.test_number === "string" && TEST_NUMBER_RE.test(c.test_number)
                ? c.test_number : "",
            holdMs: int(c.hold_ms, 10000) || 2000,
            armDelayMs: int(c.arm_delay_ms, 10000) || 700,
            incoming: c.incoming === true,
            dispatcher: disp,
        };
    }

    /** Pure: which view — "panel" (the 112 call / dispatcher view),
     *  "countdown"/"result" (the SMS window) with a 112 column when the 112
     *  window is open ("countdown112"/"result112"), or null (no window).
     *  `v` = normalize() of a SHOWN SMS window (or null), `w` =
     *  normalize112(), `panelOpen` = the driver asked for the panel,
     *  `smsCancelled` = the SMS of the SAME event was cancelled ("nic się
     *  nie stało"): once its result is closed the 112 panel does not take
     *  the whole screen by itself (only on request or during a call). */
    function pickMode(v, w, panelOpen, smsCancelled) {
        if (w && (w.live || w.incoming)) return "panel";
        if (v) {
            if (w && panelOpen) return "panel";
            const m = modeOf(v);
            return w ? m + "112" : m;
        }
        if (w && smsCancelled && !panelOpen) return null;
        return w ? "panel" : null;
    }

    /** Pure: may the 112 button be pressed now? During a live call only
     *  when the main phone's call has no microphone uplink and the car
     *  phone is offered as its replacement. */
    function canCall(w) {
        return !!w && w.offer !== "none" && w.retry === 0
            && (!w.live || (w.uplinkLost && w.fallback));
    }

    function _pad2(n) { return (n < 10 ? "0" : "") + n; }

    /** Pure: 52.229676 → "52,22968 N" (Polish decimal comma). */
    function fmtDec(v, pos, neg) {
        if (typeof v !== "number" || !isFinite(v)) return "";
        return Math.abs(v).toFixed(5).replace(".", ",") + " " + (v < 0 ? neg : pos);
    }

    /** Pure: 52.229676 → "52°13'46,8\" N". */
    function fmtDms(v, pos, neg) {
        if (typeof v !== "number" || !isFinite(v)) return "";
        const a = Math.abs(v);
        let d = Math.floor(a);
        let m = Math.floor((a - d) * 60);
        let sec = Math.round(((a - d) * 60 - m) * 600) / 10;
        if (sec >= 60) { sec = 0; m += 1; }
        if (m >= 60) { m = 0; d += 1; }
        const ss = sec.toFixed(1).padStart(4, "0").replace(".", ",");
        return `${d}°${_pad2(m)}'${ss}" ${v < 0 ? neg : pos}`;
    }

    /** Pure: heading in degrees → one of COMPASS (8 winds) or null. */
    function compass(h) {
        if (!Number.isInteger(h) || h < 0 || h > 359) return null;
        return COMPASS[Math.round(h / 45) % 8];
    }

    function _hhmm(ts) {
        if (typeof ts !== "number" || !isFinite(ts)) return "";
        const d = new Date(ts * 1000);
        return _pad2(d.getHours()) + ":" + _pad2(d.getMinutes());
    }

    function _age(s) {
        if (s < 120) return s + " s";
        if (s < 7200) return Math.floor(s / 60) + " min";
        return Math.floor(s / 3600) + " h";
    }

    function _mmss(s) {
        const m = Math.floor(s / 60);
        return (m < 100 ? _pad2(m) : String(m)) + ":" + _pad2(s % 60);
    }

    /** Pure: the dispatcher panel's texts (no reverse geocoding). The fix
     *  counts as current up to 30 s; older = "ostatnia znana pozycja". */
    function dispatcherTexts(d, t) {
        t = t || ((k, x) => x);
        const out = { pos: "", dms: "", fix: "", move: "", vehicle: "", say: "" };
        if (!d) return out;
        const has = d.lat !== null && d.lon !== null;
        const old = has && d.age !== null && d.age > 30;
        if (has) {
            out.pos = fmtDec(d.lat, "N", "S") + "  " + fmtDec(d.lon, "E", "W");
            out.dms = fmtDms(d.lat, "N", "S") + "  " + fmtDms(d.lon, "E", "W");
            if (old) {
                out.fix = t("c112_fix_old", "ostatnia znana pozycja sprzed {age}")
                    .replace("{age}", () => _age(d.age));
            } else {
                out.fix = t("c112_fix", "GPS {age} temu").replace("{age}", () => _age(d.age || 0))
                    + (d.sats !== null ? t("c112_fix_sats", ", {n} sat.").replace("{n}", () => String(d.sats)) : "");
            }
        } else {
            out.pos = t("c112_no_pos", "brak pozycji GPS");
        }
        const c = compass(d.heading);
        const time = _hhmm(d.eventTs);
        const moveParts = [];
        if (c) moveParts.push(c[2]);
        if (d.speed !== null) moveParts.push(d.speed + " km/h");
        let move = moveParts.length ? t("c112_before", "przed: ") + moveParts.join(", ") : "";
        if (time) move += (move ? " · " : "") + t("c112_at", "godz. ") + time;
        out.move = move;
        const label = d.label || "Alfa Romeo 156";
        out.vehicle = [label, d.colour, d.plate].filter(Boolean).join(" · ");
        // The sentence is read to a Polish 112 dispatcher: always Polish,
        // whatever the UI language (not translated on purpose).
        let say = "Zgłaszam wypadek drogowy" + (time ? " o " + time : "") + ". ";
        say += "Samochód osobowy " + label
            + (d.colour ? ", kolor: " + d.colour : "")
            + (d.plate ? ", numer rejestracyjny " + d.plate : "") + ". ";
        if (has) {
            say += (old ? "Ostatnia znana pozycja GPS" : "Pozycja GPS") + ": "
                + fmtDec(d.lat, "N", "S") + ", " + fmtDec(d.lon, "E", "W") + ".";
        } else {
            say += "Pozycja GPS nieznana.";
        }
        const before = [];
        if (c) before.push("kierunek " + c[1]);
        if (d.speed !== null) before.push(d.speed + " km/h");
        if (before.length) say += " Przed zdarzeniem: " + before.join(", ") + ".";
        out.say = say;
        return out;
    }

    /** Pure: every text of the 112 part for a normalize112() value.
     *  `smsLeft` = seconds left of a running SMS countdown (or null). */
    function texts112(w, t, smsLeft) {
        t = t || ((k, d) => d);
        const out = {};
        const secs = String(Math.round(w.holdMs / 100) / 10).replace(".", ",");
        out.holdLabel = w.test
            ? t("c112_hold_test", "PRZYTRZYMAJ {s} s – TEST").replace("{s}", () => secs)
            : t("c112_hold", "PRZYTRZYMAJ {s} s – ZADZWOŃ 112").replace("{s}", () => secs);
        const pl = PATH_LABEL[w.offer];
        let sub = pl ? t(pl[0], pl[1]) : "";
        if (w.fallback && sub) sub = t("c112_now_via", "teraz: {path}").replace("{path}", () => sub);
        if (w.test) {
            sub = t("c112_test_number", "TEST – dzwoni na {n}")
                .replace("{n}", () => w.testNumber || "…") + (sub ? " · " + sub : "");
        }
        out.holdSub = sub;
        out.holdFired = t("c112_dialing_short", "Łączenie…");
        out.none = t("c112_own_phone", "Zadzwoń 112 ze swojego telefonu");
        const why = [];
        for (const p of ["hfp", "car_phone"]) {
            const r = w.reasons[p];
            if (r && r !== "off") {
                why.push(t(PATH_LABEL[p][0], PATH_LABEL[p][1]) + ": " + t(REASON_TEXT[r][0], REASON_TEXT[r][1]));
            }
        }
        out.noneWhy = why.join("; ");
        out.retry = w.retry ? t("c112_retry", "Kolejne połączenie możliwe za {s} s")
            .replace("{s}", () => String(w.retry)) : "";
        const path = PATH_LABEL[w.path] ? t(PATH_LABEL[w.path][0], PATH_LABEL[w.path][1]) : "";
        out.path = path;
        out.title = t("crash_title", "MOŻLIWY WYPADEK");
        out.line = smsLeft !== null && smsLeft !== undefined
            ? t("c112_sms_in", "SMS do bliskich za {s} s").replace("{s}", () => String(smsLeft))
            : t("c112_panel_hint", "Pozycja dla dyspozytora 112 – poniżej");
        out.note = w.test ? t("c112_test_mode", "TRYB TESTOWY 112 – dzwoni na {n}")
            .replace("{n}", () => w.testNumber || "…") : "";
        if (w.live) {
            const pre = w.test ? t("c112_test_prefix", "TEST – ") : "";
            if (w.hangupPending) {
                out.title = t("c112_hanging_up", "Rozłączanie…");
            } else if (w.state === "active") {
                out.title = pre + t("c112_talking", "Rozmowa {t}").replace("{t}", () => _mmss(w.duration || 0));
            } else {
                out.title = pre + (w.test ? t("c112_connecting_test", "łączenie…")
                    : t("c112_connecting", "Łączenie z 112…"));
            }
            out.line = path + (w.unverified ? " " + t("c112_unverified", "(stanu rozmowy nie widać)") : "");
            if (smsLeft !== null && smsLeft !== undefined) {
                out.line += " · " + t("c112_sms_in", "SMS do bliskich za {s} s").replace("{s}", () => String(smsLeft));
            }
            out.note = t("c112_accidental", "Jeśli połączenie było przypadkowe – nie rozłączaj się, powiedz dyspozytorowi, że to pomyłka.");
            if (w.uplinkLost) {
                out.note = w.fallback && w.offer === "car_phone"
                    ? t("c112_no_uplink_fb", "Dyspozytor może Cię nie słyszeć (brak mikrofonu) – przytrzymaj 112: zadzwoni telefon w aucie")
                    : t("c112_no_uplink", "Dyspozytor może Cię nie słyszeć (brak mikrofonu w rozmowie)");
            }
        } else if (w.state === "failed") {
            out.title = t("c112_failed", "Nie połączono z 112");
            const e = ERROR_TEXT[w.error];
            out.line = (path ? path + ": " : "") + (e ? t(e[0], e[1]) : t("c112_e_other", "nie udało się"));
        } else if (w.state === "ended") {
            out.title = t("c112_ended", "Rozmowa zakończona") + (w.duration ? " (" + _mmss(w.duration) + ")" : "");
            out.line = path + (w.unverified
                ? " " + t("c112_unverified_end", "(stanu rozmowy nie widać – jeśli trwa, zakończ ją w telefonie)") : "");
        }
        out.smsCancel = t("c112_sms_cancel", "ANULUJ SMS – nic się nie stało");
        out.hangup = t("c112_hangup", "PRZYTRZYMAJ 1 s – ROZŁĄCZ");
        out.answer = t("c112_answer", "Odbierz – dzwoni telefon");
        out.close = t("c112_close", "Zamknij");
        out.back = t("c112_back", "Wróć");
        out.panel = t("c112_panel", "Pozycja dla 112");
        out.remote = t("c112_kiosk_only", "Dzwonić można tylko z ekranu w aucie");
        Object.assign(out, dispatcherTexts(w.dispatcher, t));
        return out;
    }

    const RING_C = 119.38;   // 2πr, r = 19

    /** Pure: a hold-to-confirm button (the ring fills while held). */
    function holdHtml(kind, label, sub, extraStyle) {
        return `<button type="button" data-c112-hold="${kind}" style="${BTN}touch-action:none;-webkit-touch-callout:none;flex-direction:column;gap:0.6vh;padding:1vh 0.8vw;${extraStyle}">
            <svg data-c112-ring viewBox="0 0 44 44" style="width:6.5vh;height:6.5vh;flex:none;pointer-events:none" aria-hidden="true"><circle cx="22" cy="22" r="19" fill="none" stroke="rgba(255,255,255,0.35)" stroke-width="5"></circle><circle data-c112-ring-fg cx="22" cy="22" r="19" fill="none" stroke="#fff" stroke-width="5" stroke-dasharray="${RING_C}" stroke-dashoffset="${RING_C}" transform="rotate(-90 22 22)"></circle></svg>
            <span data-c112-label style="pointer-events:none;line-height:1.15">${esc(label)}</span>
            <span data-c112-sub style="pointer-events:none;font-size:max(12px,0.72em);font-weight:700;line-height:1.15;color:#fee2e2">${esc(sub)}</span>
        </button>`;
    }

    /** Pure: the 112 column next to the SMS window (countdown / result):
     *  the 112 button, "no path" info and the "Pozycja dla 112" toggle. */
    function c112ColumnHtml(tx) {
        return `<div data-c112-col style="display:flex;flex-direction:column;gap:1.2vh;flex:1;min-height:0">
            ${holdHtml("call", tx.holdLabel, tx.holdSub, "flex:1;min-height:0;font-size:2.7vh;background:#dc2626;color:#fff;border:3px solid #fecaca")}
            <div data-c112-none style="display:none;flex:1;min-height:0;overflow:hidden;font-size:2.1vh;font-weight:700;color:#fde68a;text-align:center;border:2px dashed #fca5a5;border-radius:14px;padding:0.8vh 0.6vw;box-sizing:border-box"></div>
            <button type="button" data-c112-action="panel" style="${BTN}flex:none;height:8vh;font-size:2.2vh;background:#1f2937;color:#fff;border:2px solid #fca5a5;padding:0.5vh 0.6vw">${esc(tx.panel)}</button>
        </div>`;
    }

    /** Pure: the dispatcher panel (font ≥ 48 px but the read-out sentence). */
    function dispatcherHtml() {
        const row = "font-size:48px;line-height:1.1;font-weight:700;margin:0;";
        return `<div data-c112-panel style="flex:1;min-height:0;display:flex;flex-direction:column;gap:0.6vh;overflow:hidden;border-top:2px solid rgba(254,202,202,0.35);padding-top:0.6vh">
            <div data-c112-pos style="font-size:60px;line-height:1.08;font-weight:900;color:#fff;white-space:nowrap;font-variant-numeric:tabular-nums"></div>
            <div data-c112-dms style="${row}color:#fecaca;white-space:nowrap;font-variant-numeric:tabular-nums"></div>
            <div data-c112-fix style="${row}color:#fde68a"></div>
            <div data-c112-move style="${row}color:#fff"></div>
            <div data-c112-vehicle style="${row}color:#fff"></div>
            <div data-c112-say style="flex:1;min-height:0;overflow:hidden;font-size:${SAY_FONT_PX}px;line-height:1.2;color:#fecaca;font-style:italic"></div>
        </div>`;
    }

    /** Pure: the 112 / call view with the dispatcher panel. */
    function panelHtml(tx) {
        const side = `${BTN}width:100%;height:100%;font-size:3vh;color:#fff;padding:1vh 1vw;`;
        return `<div data-crash-mode="panel" style="position:absolute;inset:0;display:flex;flex-direction:column;padding:1.5vh 2vw;box-sizing:border-box;gap:1.2vh">
            <div data-c112-bar style="display:flex;align-items:stretch;height:19vh;flex:none">
                <div data-c112-left style="width:24vw;flex:none;display:flex">
                    <button type="button" data-c112-action="close" style="${side}background:#374151;border:2px solid #9ca3af">${esc(tx.close)}</button>
                    <button type="button" data-c112-action="back" style="${side}display:none;background:#374151;border:2px solid #9ca3af">${esc(tx.back)}</button>
                    ${holdHtml("hangup", tx.hangup, "", "display:none;width:100%;height:100%;font-size:3vh;background:#7f1d1d;color:#fff;border:3px solid #fca5a5")}
                </div>
                <div data-c112-status style="flex:1;min-width:0;padding:0 1.5vw;display:flex;flex-direction:column;justify-content:center;gap:0.5vh;overflow:hidden">
                    <div data-c112-title style="font-size:4.2vh;font-weight:900;color:#fecaca;line-height:1.1"></div>
                    <div data-c112-line style="font-size:2.8vh;font-weight:700;color:#fff;line-height:1.15"></div>
                    <div data-c112-note style="font-size:2.2vh;color:#fde68a;line-height:1.15"></div>
                </div>
                <div data-c112-col style="width:34vw;flex:none;display:flex;flex-direction:column;gap:1vh">
                    ${holdHtml("call", tx.holdLabel, tx.holdSub, "flex:1;min-height:0;font-size:3.3vh;background:#dc2626;color:#fff;border:3px solid #fecaca")}
                    <button type="button" data-crash-action="cancel" data-c112-sms-cancel style="${BTN}display:none;flex:1;min-height:0;font-size:3vh;background:#16a34a;color:#fff;border:3px solid #bbf7d0;padding:0.5vh 0.8vw">${esc(tx.smsCancel)}</button>
                    <button type="button" data-c112-action="answer" style="${BTN}display:none;flex:1;min-height:0;font-size:3.4vh;background:#16a34a;color:#fff;border:3px solid #bbf7d0">${esc(tx.answer)}</button>
                    <div data-c112-none style="display:none;flex:1;min-height:0;overflow:hidden;font-size:2.4vh;font-weight:700;color:#fde68a;text-align:center;border:2px dashed #fca5a5;border-radius:14px;padding:0.8vh 0.8vw;box-sizing:border-box;flex-direction:column;justify-content:center"></div>
                    <div data-crash-remote style="display:none;flex:1;font-size:2.4vh;font-weight:700;color:#fde68a;align-items:center;justify-content:center;text-align:center;border:2px dashed #fca5a5;border-radius:14px;box-sizing:border-box;padding:1vh 1vw">${esc(tx.remote)}</div>
                </div>
            </div>
            ${dispatcherHtml()}
        </div>`;
    }

    /** Pure: the result skeleton. `tx112` (texts112): the result on the
     *  left 62vw, the 112 column on the right, 15vw apart. */
    function resultHtml(tx, tx112) {
        const inner = `<span class="material-symbols-outlined" data-crash-icon style="font-size:16vh;color:#fff"></span>
            <div data-crash-result style="font-size:5.5vh;font-weight:900;color:#fff;max-width:100%"></div>
            <div data-crash-result-dry style="display:none;font-size:3vh;font-weight:900;color:#111;background:#facc15;border-radius:8px;padding:0.5vh 1.5vw"></div>
            <button type="button" data-crash-action="cancel" style="${BTN}display:none;font-size:4.4vh;background:#16a34a;color:#fff;padding:3vh 5vw;min-width:50vw;box-shadow:0 0 0 4px rgba(255,255,255,0.25)"></button>
            <button type="button" data-crash-action="follow_up" style="${BTN}display:none;font-size:3.4vh;background:#16a34a;color:#fff;padding:2.5vh 4vw"></button>
            <div data-crash-remote style="display:none;font-size:2.8vh;font-weight:700;color:#fde68a">${esc(tx.remote)}</div>
            <div data-crash-close style="font-size:2.8vh;color:#fecaca">${esc(tx.close)}</div>`;
        if (tx112) {
            return `<div data-crash-mode="result" style="position:absolute;inset:0;display:flex;padding:2vh 2vw;box-sizing:border-box">
            <div style="width:62vw;flex:none;min-width:0;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:3vh;text-align:center">${inner}</div>
            <div data-crash-gap style="width:15vw;flex:none"></div>
            <div style="width:19vw;flex:none;display:flex;flex-direction:column;min-height:0">${c112ColumnHtml(tx112)}</div>
        </div>`;
        }
        return `<div data-crash-mode="result" style="position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;justify-content:center;padding:4vh 4vw;box-sizing:border-box;gap:3vh;text-align:center">
            ${inner}
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
    // 112: the normalized payload, the event whose panel the driver opened,
    // the holds attached to the current skeleton, the last inputs (a closed
    // SMS result redraws at once with them).
    let _w = null;
    let _panel = false;
    let _panelEid = null;
    let _holds = {};
    let _shown = {};
    let _last = [null, null];
    let _sayText = null;
    // "Rozłącz" was accepted (2xx): {h, sawPending} until the hold is
    // re-armed (the backend showed hangup_pending and then dropped it while
    // the call is still live, or HANGUP_REARM_MS passed).
    let _hangupWait = null;

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

    function _detachHolds() {
        for (const k of Object.keys(_holds)) {
            try { _holds[k].detach(); } catch (e) { /* stub */ }
        }
        _holds = {};
        _shown = {};
    }

    function _close() {
        _setBeeping(false);
        if (_closeTimer) { clearTimeout(_closeTimer); _closeTimer = null; }
        _detachHolds();
        if (_el && _el.parentNode) _el.parentNode.removeChild(_el);
        _el = null; _mode = null; _eid = null; _view = null; _sayText = null;
    }

    function _dismiss() {
        if (_view && modeOf(_view) === "result") _dismissed = dismissKey(_view);
        _close();
        // The 112 window may still be open: draw it at once.
        if (_w) sync(_last[0], _last[1]);
    }

    const ROUTES = { cancel: "/api/crash/cancel", send_now: "/api/crash/send_now",
                     follow_up: "/api/crash/follow_up" };

    function _guard(key) {
        const now = Date.now();
        if (_tapAt[key] && now - _tapAt[key] < TAP_GUARD_MS) return false;
        for (const k of Object.keys(_tapAt)) if (now - _tapAt[k] > TAP_GUARD_MS) delete _tapAt[k];
        _tapAt[key] = now;
        return true;
    }

    /** POST the driver's decision; resolves to the HTTP status (0 = no
     *  answer, null = swallowed double tap). */
    async function _post(action) {
        const v = _view;
        if (!v || !Object.prototype.hasOwnProperty.call(ROUTES, action)) return null;
        // Per event and action: a double tap is swallowed, a tap on the
        // NEXT event's window is not.
        if (!_guard(action + "|" + v.eid)) return null;
        try {
            const res = await fetch(ROUTES[action], {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ event_id: v.eid }),
            });
            return res.status;
        } catch (e) { return 0; /* the backend state (cancel_pending) shows what happened */ }
    }

    /** POST a 112 action. Never a number: "call" and "hangup" send an
     *  empty object, "close" the event id. Resolves to {status, body}. */
    async function _post112(action) {
        const w = _w;
        if (!w || !Object.prototype.hasOwnProperty.call(C112_ROUTES, action)) return null;
        if (!_guard("c112|" + action + "|" + w.eid)) return null;
        try {
            const res = await fetch(C112_ROUTES[action], {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(action === "close" ? { event_id: w.eid } : {}),
            });
            let body = null;
            try { body = await res.json(); } catch (e) { body = null; }
            return { status: res.status, body };
        } catch (e) { return { status: 0, body: null }; }
    }

    function _onHoldFire(kind) {
        const h = _holds[kind];
        const btn = _el && _el.querySelector(`[data-c112-hold='${kind}'] [data-c112-label]`);
        if (btn && kind === "call") btn.textContent = texts112(_w, _t()).holdFired;
        if (kind === "hangup") _hangupWait = { h, sawPending: false };
        _post112(kind === "call" ? "call" : "hangup").then((r) => {
            const ok = r && r.status >= 200 && r.status < 300;
            if (ok && kind === "hangup" && h) {
                // A hang-up that did not take must not leave a dead button.
                setTimeout(() => {
                    if (_holds.hangup === h && _hangupWait && _hangupWait.h === h && _w && _w.live) {
                        _hangupWait = null;
                        h.hold.rearm(0);
                    }
                }, HANGUP_REARM_MS);
            }
            if (ok || !h) return;               // the backend push redraws the view
            if (kind === "hangup" && _hangupWait && _hangupWait.h === h) _hangupWait = null;
            const t = _t();
            if (btn && kind === "call" && r) {
                if (r.status === 429) {
                    const s = r.body && Number.isInteger(r.body.retry_after) ? r.body.retry_after : 60;
                    btn.textContent = t("c112_retry", "Kolejne połączenie możliwe za {s} s")
                        .replace("{s}", () => String(s));
                } else if (r.status === 403) {
                    btn.textContent = t("c112_kiosk_only", "Dzwonić można tylko z ekranu w aucie");
                } else {
                    btn.textContent = t("c112_failed", "Nie połączono z 112");
                }
            }
            setTimeout(() => {
                if (_holds[kind] === h) {
                    h.hold.rearm(0);
                    if (btn && kind === "call" && _w) btn.textContent = texts112(_w, _t()).holdLabel;
                }
            }, REARM_AFTER_MS);
        });
    }

    function _attachHolds() {
        _detachHolds();
        const H = (typeof BCMHold !== "undefined" && BCMHold)
            || (typeof window !== "undefined" && window.BCMHold) || null;
        if (!H || !_el || !_w) return;
        for (const node of _el.querySelectorAll("[data-c112-hold]")) {
            const kind = node.getAttribute("data-c112-hold");
            const fg = node.querySelector("[data-c112-ring-fg]");
            const binding = H.attach(node, {
                holdMs: kind === "hangup" ? HANGUP_HOLD_MS : _w.holdMs,
                armDelayMs: _w.armDelayMs,
                onProgress: (f) => { if (fg) fg.setAttribute("stroke-dashoffset", String(RING_C * (1 - f))); },
                onFire: () => _onHoldFire(kind),
            });
            _holds[kind] = binding;
        }
    }

    function _onClick(e) {
        const el = e.target;
        // The hold buttons work with pointer events only; a click from them
        // (or from the 112 column) never closes a result under them.
        if (el && el.closest && el.closest("[data-c112-hold]")) return;
        const c112 = el && el.closest ? el.closest("[data-c112-action]") : null;
        if (c112) {
            e.preventDefault();
            const action = c112.getAttribute("data-c112-action");
            if (action === "panel") { _panel = true; _panelEid = _w ? _w.eid : null; sync(_last[0], _last[1]); }
            else if (action === "back") { _panel = false; sync(_last[0], _last[1]); }
            else if (action === "close") {
                _panel = false;
                _post112("close");
            } else if (action === "answer") {
                if (_guard("c112|answer")) {
                    fetch(C112_ROUTES.answer, { method: "POST" }).catch(() => {});
                }
            }
            return;
        }
        const target = el && el.closest ? el.closest("[data-crash-action]") : null;
        // (the ANULUJ SMS of the panel sits in the 112 column: handled here)
        if (!target && el && el.closest && el.closest("[data-c112-col]")) return;
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
        if (_view && (_mode === "result" || _mode === "result112")
            && (closableByTap(_view) || (!isKiosk() && modeOf(_view) === "result"))) {
            _dismiss();
        }
    }

    function _skeleton(mode, tx, tx112) {
        if (mode === "panel") return panelHtml(tx112);
        if (mode === "countdown" || mode === "countdown112") return countdownHtml(tx, mode === "countdown112" ? tx112 : null);
        return resultHtml(tx, mode === "result112" ? tx112 : null);
    }

    function _ensure(mode, tx, tx112) {
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
            _detachHolds();
            _el.innerHTML = _skeleton(mode, tx, tx112);
            _mode = mode;
            _sayText = null;
            _attachHolds();
        }
    }

    function _text(sel, value) {
        const node = _el && _el.querySelector(sel);
        if (node && node.textContent !== value) node.textContent = value;
        return node;
    }

    function _shownEl(sel, on, display) {
        const node = _el && _el.querySelector(sel);
        if (node) node.style.display = on ? (display || "") : "none";
        return node;
    }

    function _fill(v, tx) {
        const kiosk = isKiosk();
        const remote = _el && _el.querySelector("[data-crash-mode='countdown'] > div > [data-crash-remote], [data-crash-mode='result'] [data-crash-remote]");
        if (remote) remote.style.display = kiosk ? "none" : (_mode.indexOf("countdown") === 0 ? "flex" : "");
        if (_mode === "countdown" || _mode === "countdown112") {
            _text("[data-crash-count]", tx.count);
            _text("[data-crash-label]", tx.label);
            _text("[data-crash-recipients]", tx.recipients);
            _text("[data-crash-phone]", tx.phone);
            _shownEl("[data-crash-dry]", !!tx.dry);
            _text("[data-crash-dry]", tx.dry);
            _shownEl("[data-crash-reason]", !!tx.reason);
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
            _shownEl("[data-crash-result-dry]", !!tx.resultDry);
            _text("[data-crash-result-dry]", tx.resultDry);
            const rc = _shownEl("[data-crash-mode='result'] [data-crash-action='cancel']",
                                kiosk && (v.maySend || v.unconfirmed) && !v.cancelPending);
            if (rc && rc.getAttribute("data-label") !== tx.resultCancel) {
                rc.setAttribute("data-label", tx.resultCancel);
                rc.textContent = tx.resultCancel;
            }
            const fu = _shownEl("[data-crash-action='follow_up']",
                                kiosk && v.canFollowUp && !v.cancelPending);
            if (fu) fu.textContent = tx.followUp;
            _shownEl("[data-crash-close]", !!tx.close);
            _text("[data-crash-close]", tx.close);
        }
    }

    /** Show / hide a hold button; a button that (re)appears is inactive for
     *  arm_delay_ms again — nothing that was under the finger fires it. */
    function _showHold(kind, on, display) {
        const node = _shownEl(`[data-c112-hold='${kind}']`, on, display);
        const h = _holds[kind];
        if (h && on && !_shown[kind]) h.hold.rearm(_w ? _w.armDelayMs : 700);
        if (h && !on && _shown[kind]) h.hold.rearm(0);
        _shown[kind] = !!(node && on);
        return node;
    }

    /** The 112 parts of the current skeleton (column or panel). */
    function _fill112(w, tx) {
        const kiosk = isKiosk();
        const can = kiosk && canCall(w);
        const callBtn = _showHold("call", can && !(_mode === "panel" && w.incoming), "flex");
        if (callBtn) {
            const h = _holds.call;
            if (!h || h.hold.state() !== "fired") _text("[data-c112-hold='call'] [data-c112-label]", tx.holdLabel);
            _text("[data-c112-hold='call'] [data-c112-sub]", tx.holdSub);
        }
        const none = _el.querySelector("[data-c112-none]");
        if (none) {
            const showNone = kiosk && !w.live && !can && !(_mode === "panel" && w.incoming);
            none.style.display = showNone ? "flex" : "none";
            if (showNone) {
                const msg = w.retry ? tx.retry : (tx.none + (tx.noneWhy ? " (" + tx.noneWhy + ")" : ""));
                if (none.textContent !== msg) none.textContent = msg;
            }
        }
        if (_mode !== "panel") return;
        // ── the panel view ──
        const smsView = !!_view;
        const forced = w.live || w.incoming;
        _shownEl("[data-c112-action='close']", kiosk && !forced && !smsView, "flex");
        _shownEl("[data-c112-action='back']", !forced && smsView, "flex");
        _showHold("hangup", kiosk && w.live, "flex");
        const hw = _hangupWait;
        if (hw && (!w.live || _holds.hangup !== hw.h)) {
            _hangupWait = null;
        } else if (hw) {
            if (w.hangupPending) hw.sawPending = true;
            else if (hw.sawPending) {
                // The backend gave the hang-up up (agent refused, or the
                // call is still up 10 s later): Rozłącz works again.
                _hangupWait = null;
                if (hw.h.hold.state() === "fired") hw.h.hold.rearm(0);
            }
        }
        // ANULUJ for a running SMS countdown during the call (tap).
        const smsC = _view && COUNTDOWN.indexOf(_view.state) >= 0 && !_view.cancelPending
            && !_view.unconfirmed;
        const sc = _shownEl("[data-c112-sms-cancel]", kiosk && w.live && smsC, "flex");
        if (sc && kiosk && w.live && smsC && !_shown.smsCancel) sc.textContent = tx.smsCancel;
        _shown.smsCancel = !!(sc && kiosk && w.live && smsC);
        _shownEl("[data-c112-action='answer']", kiosk && w.incoming && !w.live, "flex");
        _shownEl("[data-c112-col] [data-crash-remote]", !kiosk, "flex");
        _text("[data-c112-title]", tx.title);
        _text("[data-c112-line]", tx.line);
        _text("[data-c112-note]", tx.note);
        _text("[data-c112-pos]", tx.pos);
        _text("[data-c112-dms]", tx.dms);
        _text("[data-c112-fix]", tx.fix);
        _text("[data-c112-move]", tx.move);
        _text("[data-c112-vehicle]", tx.vehicle);
        const say = _el.querySelector("[data-c112-say]");
        if (say && _sayText !== tx.say) {
            _sayText = tx.say;
            say.textContent = tx.say ? "„" + tx.say + "”" : "";
            _fitSay(say);
        }
    }

    /** The read-out sentence shrinks (not below 18 px) until it fits. */
    function _fitSay(node) {
        let size = SAY_FONT_PX;
        node.style.fontSize = size + "px";
        for (let i = 0; i < 8 && node.scrollHeight > node.clientHeight + 1 && size > SAY_MIN_FONT_PX; i++) {
            size -= 2;
            node.style.fontSize = size + "px";
        }
    }

    /** Called by app.js on every data push (any screen): `cs` =
     *  data.crash_sms, `c112` = data.call112. */
    function sync(cs, c112) {
        if (typeof document === "undefined") return;
        _last = [cs, c112];
        const w = normalize112(c112);
        if (w && w.eid !== _panelEid) _panel = false;
        _w = w;
        const smsShown = shouldShow(cs, _dismissed);
        const v = smsShown ? normalize(cs) : null;
        const smsAll = normalize(cs);
        const smsCancelled = !!(w && smsAll && smsAll.eid === w.eid && smsAll.state === "cancelled");
        const mode = pickMode(v, w, _panel, smsCancelled);
        if (!mode) {
            if (_el) _close();
            return;
        }
        const t = _t();
        const tx = v ? texts(v, t) : null;
        const smsLeft = v && COUNTDOWN.indexOf(v.state) >= 0 && !v.cancelPending ? v.left : null;
        const tx112 = w ? texts112(w, t, smsLeft) : null;
        if (v && (_eid !== v.eid || (_view && (_view.state !== v.state
                                               || _view.unconfirmed !== v.unconfirmed)))) {
            // A new event, or a new result of this one (e.g. "Jestem OK" →
            // cancel SMS): its own 60 s.
            if (_eid !== v.eid) _dismissed = null;
            if (_closeTimer) { clearTimeout(_closeTimer); _closeTimer = null; }
        }
        _ensure(mode, tx, tx112);
        _eid = v ? v.eid : null;
        _view = v;
        if (v && mode !== "panel") _fill(v, tx);
        if (w) _fill112(w, tx112);
        // Only while time is really left: a countdown stuck at 0 (the phone
        // stopped answering) must not beep over Android Auto for minutes —
        // and never during a 112 call or while the phone rings.
        const counting = !!v && modeOf(v) === "countdown" && COUNTDOWN.indexOf(v.state) >= 0
            && !v.cancelPending && v.left !== null && v.left > 0;
        _setBeeping(counting && !(w && (w.live || w.incoming)));
        const result = !!v && modeOf(v) === "result" && mode !== "panel";
        if (result && !_closeTimer) {
            _closeTimer = setTimeout(() => { _closeTimer = null; _dismiss(); }, RESULT_CLOSE_MS);
        } else if (!result && _closeTimer) {
            clearTimeout(_closeTimer);
            _closeTimer = null;
        }
    }

    return {
        sync, isOpen, normalize, shouldShow, texts, countdownHtml, resultHtml, esc,
        modeOf, closableByTap, isKiosk, ROUTES,
        normalize112, pickMode, canCall, texts112, dispatcherTexts, fmtDec, fmtDms, compass,
        panelHtml, c112ColumnHtml, holdHtml, C112_ROUTES,
        BEEP_EVERY_MS, RESULT_CLOSE_MS, HANGUP_HOLD_MS,
        /** Test hooks. */
        _beeping: () => !!_beepTimer,
        _close,
        _mode: () => _mode,
    };
})();

if (typeof module !== "undefined" && module.exports) module.exports = CrashModal;
