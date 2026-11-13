/**
 * Settings Screen — Theme, Language, Units, Bluetooth, WiFi, SWC Mapping.
 * Theme-aware via CSS custom properties (--card-bg, --card-border, etc.).
 * SWC uses a learn mode: press "Configure" then press a button on the pod.
 */

const Settings = {
    _btPaired: [],
    _btDiscovered: [],
    _btScanning: false,
    _swcMapping: null,
    _swcAllButtons: [],
    _swcActions: [],
    _swcLearning: null,
    _swcLearnTimer: null,
    _radio: { bt: { available: false, powered: false },
              wifi: { available: false, running: false, ssid: "" } },
    _radioBusy: false,
    // Editable Android Auto wireless / Wi-Fi AP credentials. Loaded
    // from /api/wifi/config on first render of the AA Wireless card.
    _wifi: { ssid: "", password: "", channel: 6,
             loaded: false, saving: false, showPwd: false,
             restartRequired: false, status: "",
             internet_share_available: false },

    // Module on/off toggles (modules.* — GET/POST /api/modules; the list
    // carries requires/hardware/available/blocked_by/needs/would_stop from
    // src/core/modules_catalog.py). `confirm` is the open question before a
    // toggle with consequences (dependencies off / dependents running) —
    // nothing is ever switched on or off in cascade without it. `statusName`:
    // the module the last status line is about (drawn under its row).
    _modules: { list: [], loaded: false, status: "", statusName: null,
                restartRequired: false, confirm: null, busy: false },
    // Settings → Moduły headings, in this order ("" = modules without a group).
    _moduleGroups: [
        ["", "modules_group_core", "Podstawowe"],
        ["telefon_w_aucie", "modules_group_telefon_w_aucie", "Telefon w aucie"],
        ["bezpieczenstwo", "modules_group_bezpieczenstwo", "Bezpieczeństwo"],
        ["zasilanie", "modules_group_zasilanie", "Zasilanie i wybudzanie"],
    ],

    // Android Auto settings & control
    _aa: { autoRestart: true, loaded: false, restarting: false },

    // Internet from the phone (Bluetooth PAN, src/network/phone_tether.py).
    // data.phone_tether = {state, ip, iface, hint} from the dashboard payload,
    // or null while the module is not running (production config: no row).
    _tetherColors: {
        connected: "#16a34a",                       // green-600, as _toggle()
        connecting: "var(--color-primary)",
        no_nap: "#d97706",                          // amber: user action needed
        failed: "#dc2626",
        unavailable: "#dc2626",
    },

    _esc(s) {
        // Text from nmcli/the network — escape before it goes into innerHTML.
        return String(s == null ? "" : s)
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#39;");
    },

    _tetherRetryAt: 0,

    /** "Ponów" in the failed state: ask the backend to retry now. The server
     *  rate-limits too (429); this only swallows double taps. The row itself
     *  changes through update() when net.phone_tether does. */
    async tetherRetry() {
        const now = Date.now();
        if (now - Settings._tetherRetryAt < 3000) return;
        Settings._tetherRetryAt = now;
        try {
            await fetch("/api/phone_tether/retry", { method: "POST" });
        } catch (e) { /* offline kiosk: the backend retries on its own */ }
    },

    /** One info row "Internet z telefonu: <stan> <ip>"; '' without a payload
     *  (module not running). Inline styles only (Tailwind is precompiled —
     *  new utility classes would not exist). */
    tetherRowHtml(pt, t) {
        t = t || ((k, d) => d);
        if (!pt || typeof pt !== "object") return "";
        const state = typeof pt.state === "string" ? pt.state : "unknown";
        const labels = {
            disabled: t("tether_disabled", "wyłączony"),
            unavailable: t("tether_unavailable", "brak NetworkManagera"),
            waiting_phone: t("tether_waiting_phone", "czeka na telefon"),
            no_nap: t("tether_no_nap", "włącz tethering Bluetooth w telefonie"),
            connecting: t("tether_connecting", "łączenie…"),
            connected: t("tether_connected", "połączono"),
            failed: t("tether_failed", "błąd — ponowię"),
        };
        const label = Object.prototype.hasOwnProperty.call(labels, state)
            ? labels[state] : state;
        const color = Settings._tetherColors[state] || "var(--text-dim)";
        const ip = (state === "connected" && pt.ip)
            ? ` <span style="color:var(--text-mid);font-family:monospace">${Settings._esc(pt.ip)}</span>` : "";
        const iface = (state === "connected" && pt.iface)
            ? ` <span style="color:var(--text-dim)">(${Settings._esc(pt.iface)})</span>` : "";
        // A failed `connection up` mostly means tethering is off on the phone
        // (Android refuses BNEP instead of hiding NAP) — say what to check,
        // never the raw nmcli error.
        const hint = (state === "failed" && pt.hint === "check_tethering")
            ? `<span style="color:var(--text-mid);flex-basis:100%;padding-left:24px">${Settings._esc(
                t("tether_failed_hint", "sprawdź „Tethering przez Bluetooth” w telefonie"))}</span>` : "";
        const retry = state === "failed"
            ? `<button data-tether-retry onclick="Settings.tetherRetry()" style="margin-left:auto;padding:4px 10px;border-radius:8px;font-size:11px;font-weight:700;background:var(--card-border);color:var(--text-mid);border:none">${Settings._esc(t("tether_retry", "Ponów"))}</button>` : "";
        return `<div data-tether-state="${Settings._esc(state)}" style="display:flex;flex-wrap:wrap;align-items:center;gap:4px 8px;padding:8px 12px;border-radius:12px;background:var(--card-bg);border:1px solid var(--card-border);font-size:11px;line-height:1.3">
            <span class="material-symbols-outlined" style="font-size:16px;color:${color}">wifi_tethering</span>
            <span style="color:var(--text-dim);font-weight:700">${Settings._esc(t("phone_tether", "Internet z telefonu"))}:</span>
            <span style="color:${color};font-weight:700">${Settings._esc(label)}</span>${ip}${iface}${retry}${hint}
        </div>`;
    },

    // The phone mounted in the car (USB/adb, src/network/car_phone.py).
    // data.car_phone = web_viewer._car_phone_summary(net.car_phone), or null
    // while the module is not running (production config: no row).
    _carPhoneColors: {
        connected: "#16a34a",
        tethering: "var(--color-primary)",
        no_device: "#d97706",                       // amber: plug in / unlock
        unauthorized: "#d97706",
        no_adb: "#dc2626",
        adb_error: "#dc2626",
        failed: "#dc2626",
    },
    _carPhoneRetryAt: 0,

    /** "Ponów" in the car phone row (POST /api/car_phone/retry; the server
     *  rate-limits too — 429 — this only swallows double taps). */
    async carPhoneRetry() {
        const now = Date.now();
        if (now - Settings._carPhoneRetryAt < 3000) return;
        Settings._carPhoneRetryAt = now;
        try {
            await fetch("/api/car_phone/retry", { method: "POST" });
        } catch (e) { /* offline kiosk: the backend retries on its own */ }
    },

    /** One info row "Telefon w aucie: <stan> <ip> · 78% 31 °C · GPS · hotspot"
     *  plus, for a known problem, what to do (never the raw adb/nmcli
     *  error). '' without a payload. Inline styles only (Tailwind is
     *  precompiled); every value goes through _esc and numbers are checked
     *  for type before they are drawn. */
    carPhoneRowHtml(cp, t) {
        t = t || ((k, d) => d);
        if (!cp || typeof cp !== "object") return "";
        const esc = Settings._esc;
        const state = typeof cp.state === "string" ? cp.state : "unknown";
        const labels = {
            disabled: t("car_phone_disabled", "wyłączony"),
            no_adb: t("car_phone_no_adb", "brak adb"),
            adb_error: t("car_phone_adb_error", "błąd adb — ponowię"),
            no_device: t("car_phone_no_device", "brak telefonu na USB"),
            unauthorized: t("car_phone_unauthorized", "zezwól na debugowanie USB"),
            tethering: t("car_phone_tethering", "włączam tethering USB…"),
            connected: t("car_phone_connected", "połączono"),
            failed: t("car_phone_failed", "błąd — ponowię"),
        };
        const label = Object.prototype.hasOwnProperty.call(labels, state) ? labels[state] : state;
        const color = Settings._carPhoneColors[state] || "var(--text-dim)";
        const mono = (v) => `<span style="color:var(--text-mid);font-family:monospace">${esc(v)}</span>`;
        const dim = (v) => `<span style="color:var(--text-dim)">${esc(v)}</span>`;
        const parts = [];
        if (state === "connected" && cp.ip) {
            parts.push(mono(cp.ip) + (cp.iface ? " " + dim(`(${cp.iface})`) : ""));
        }
        const facts = [];
        if (Number.isInteger(cp.battery_pct) && cp.battery_pct >= 0 && cp.battery_pct <= 100) {
            const plug = cp.charging === true ? " ⚡" : (cp.full === true ? " ✓" : "");
            facts.push(`${cp.battery_pct}%${plug}`);
        }
        // heat: the module's own hysteresis (warn/critical_temp_c from the
        // config) — the row does not second-guess the thresholds.
        const hot = cp.heat === "warning" || cp.heat === "danger";
        if (typeof cp.temp_c === "number" && isFinite(cp.temp_c)) {
            facts.push(`${Math.round(cp.temp_c)} °C`);
        }
        if (cp.gps_forward === true) facts.push(t("car_phone_gps", "GPS"));
        if (cp.hotspot_active === true) {
            const n = Number.isInteger(cp.hotspot_clients) ? ` (${cp.hotspot_clients})` : "";
            facts.push(t("car_phone_hotspot_on", "hotspot") + n);
        } else if (cp.hotspot_active === false) {
            facts.push(t("car_phone_hotspot_off", "hotspot wył."));
        }
        if (facts.length) {
            parts.push(`<span style="color:${hot ? "#dc2626" : "var(--text-mid)"}">${esc(facts.join(" · "))}</span>`);
        }
        const hints = {
            authorize: t("car_phone_hint_authorize", "odblokuj telefon i zaznacz „Zawsze zezwalaj” dla debugowania USB"),
            pin_serial: t("car_phone_hint_pin_serial", "kilka telefonów na USB — wpisz network.car_phone.serial"),
            tether_blocked: t("car_phone_hint_tether_blocked", "telefon nie włącza tetheringu USB — włącz go ręcznie albo sprawdź operatora"),
            aa_usb_probe: t("car_phone_hint_aa_usb_probe", "autoapp przełącza telefon w tryb Android Auto — przebuduj z BCM_AA_USB=0"),
            install_adb: t("car_phone_hint_install_adb", "zainstaluj adb: sudo apt install adb"),
        };
        const hintText = (typeof cp.hint === "string" && Object.prototype.hasOwnProperty.call(hints, cp.hint))
            ? hints[cp.hint] : "";
        const hint = hintText
            ? `<span data-car-phone-hint style="color:var(--text-mid);flex-basis:100%;padding-left:24px">${esc(hintText)}</span>` : "";
        const retry = (state === "failed" || state === "adb_error")
            ? `<button data-car-phone-retry onclick="Settings.carPhoneRetry()" style="margin-left:auto;padding:4px 10px;border-radius:8px;font-size:11px;font-weight:700;background:var(--card-border);color:var(--text-mid);border:none">${esc(t("car_phone_retry", "Ponów"))}</button>` : "";
        return `<div data-car-phone-state="${esc(state)}" style="display:flex;flex-wrap:wrap;align-items:center;gap:4px 8px;padding:8px 12px;border-radius:12px;background:var(--card-bg);border:1px solid var(--card-border);font-size:11px;line-height:1.3">
            <span class="material-symbols-outlined" style="font-size:16px;color:${color}">phone_android</span>
            <span style="color:var(--text-dim);font-weight:700">${esc(t("car_phone", "Telefon w aucie"))}:</span>
            <span style="color:${color};font-weight:700">${esc(label)}</span>${parts.length ? " " + parts.join(" ") : ""}${retry}${hint}
        </div>`;
    },

    // The Termux agent on the car phone (src/network/car_phone_agent.py).
    // data.car_phone_agent = web_viewer._car_phone_agent_summary(...), or
    // null while the module is not running (production config: no row).
    _carPhoneAgentColors: {
        ok: "#16a34a",
        waiting_forward: "var(--color-primary)",
        unpaired: "#d97706",                        // amber: user action needed
        no_secret: "#d97706",
        error: "#dc2626",
        bad_signature: "#dc2626",
    },
    _carPhoneAgentPairAt: 0,
    // Reasons after which a (re)pair can help — the code input is shown.
    _carPhoneAgentPairReasons: ["secret_mismatch", "agent_reset", "pairing_closed", "bad_code"],

    /** Is the pairing form shown for this payload? Unpaired, or an agent
     *  that answers but does not know our secret. */
    carPhoneAgentCanPair(ag) {
        if (!ag || typeof ag !== "object") return false;
        if (ag.state === "unpaired") return true;
        return ag.state === "error" && typeof ag.reason === "string"
            && Settings._carPhoneAgentPairReasons.indexOf(ag.reason) >= 0;
    },

    /** "Sparuj": the one-time code the phone printed (python
     *  ~/bcm_agent/bcm_agent.py --pair) goes to POST /api/car_phone_agent/pair
     *  (loopback only, rate-limited on the server). Only the code and the
     *  confirmation flag travel — the secret never passes through the
     *  browser. The button's data-confirm marks "Sparuj mimo to". Double
     *  taps are swallowed; the outcome shows in the row via update(). */
    async carPhoneAgentPair(btn) {
        const t = (typeof App !== "undefined" && App.t) ? App.t.bind(App) : ((k, d) => d);
        const input = document.querySelector("[data-car-phone-agent-code]");
        const msg = document.querySelector("[data-car-phone-agent-msg]");
        const say = (text) => { if (msg) msg.textContent = text; };
        const code = input && typeof input.value === "string" ? input.value.replace(/\s+/g, "") : "";
        if (!/^[0-9]{10}$/.test(code)) {
            say(t("car_phone_agent_code_hint", "wpisz 10 cyfr kodu z telefonu"));
            return;
        }
        const now = Date.now();
        if (now - Settings._carPhoneAgentPairAt < 3000) return;
        Settings._carPhoneAgentPairAt = now;
        const confirm = !!(btn && btn.dataset && btn.dataset.confirm === "1");
        try {
            const res = await fetch("/api/car_phone_agent/pair", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ code, confirm }),
            });
            let out = {};
            try { out = await res.json(); } catch (e) { /* not JSON */ }
            if (res.ok) {
                if (input) input.value = "";   // lets update() redraw the row again
                say(t("car_phone_agent_pairing", "paruję…"));
            } else {
                const errors = {
                    confirm_needed: t("car_phone_agent_err_confirm", "potwierdź: Sparuj mimo to"),
                    already_paired: t("car_phone_agent_err_paired", "już sparowany"),
                    no_forward: t("car_phone_agent_err_no_forward", "telefon niepodłączony"),
                    untrusted: t("car_phone_agent_err_untrusted", "na porcie odpowiada coś innego"),
                    "too many requests": t("car_phone_agent_err_wait", "chwilę — spróbuj za kilka sekund"),
                };
                const key = out && typeof out.error === "string" ? out.error : "";
                say(Object.prototype.hasOwnProperty.call(errors, key)
                    ? errors[key] : t("car_phone_agent_err", "nie udało się — spróbuj ponownie"));
            }
        } catch (e) { say(t("car_phone_agent_err", "nie udało się — spróbuj ponownie")); }
    },

    /** While the driver types the code, the row must not be redrawn (the
     *  OSK writes into the very input element it attached to). */
    carPhoneAgentTyping(slot) {
        const input = slot && slot.querySelector ? slot.querySelector("[data-car-phone-agent-code]") : null;
        if (!input) return false;
        return document.activeElement === input || (typeof input.value === "string" && input.value !== "");
    },

    /** One info row "Agent w telefonie: <stan> · v1.0.0 · SIM · kontakt 14:03"
     *  plus, for a known problem, what to do (never the raw error text) and
     *  "Sparuj" only while the agent is unpaired. '' without a payload.
     *  Inline styles only (Tailwind is precompiled); every value is escaped
     *  and numbers are type-checked before they are drawn. */
    carPhoneAgentRowHtml(ag, t) {
        t = t || ((k, d) => d);
        if (!ag || typeof ag !== "object") return "";
        const esc = Settings._esc;
        const state = typeof ag.state === "string" ? ag.state : "unknown";
        const labels = {
            disabled: t("car_phone_agent_disabled", "wyłączony"),
            no_secret: t("car_phone_agent_no_secret", "brak sekretu"),
            waiting_forward: t("car_phone_agent_waiting_forward", "czeka na telefon"),
            unpaired: t("car_phone_agent_unpaired", "niesparowany"),
            ok: t("car_phone_agent_ok", "działa"),
            error: t("car_phone_agent_error", "błąd — ponowię"),
            bad_signature: t("car_phone_agent_bad_signature", "obca odpowiedź — nie ufam"),
        };
        const label = Object.prototype.hasOwnProperty.call(labels, state) ? labels[state] : state;
        const color = Settings._carPhoneAgentColors[state] || "var(--text-dim)";
        const facts = [];
        if (typeof ag.version === "string" && /^[0-9A-Za-z.+-]{1,16}$/.test(ag.version)) {
            facts.push("v" + ag.version);
        }
        if (ag.sim_ready === true) facts.push(t("car_phone_agent_sim_ok", "SIM"));
        else if (ag.sim_ready === false) facts.push(t("car_phone_agent_sim_missing", "brak SIM"));
        if (typeof ag.last_ok_ts === "number" && isFinite(ag.last_ok_ts) && ag.last_ok_ts > 0) {
            const d = new Date(ag.last_ok_ts * 1000);
            const hm = String(d.getHours()).padStart(2, "0") + ":" + String(d.getMinutes()).padStart(2, "0");
            facts.push(t("car_phone_agent_last", "kontakt") + " " + hm);
        }
        const factsHtml = facts.length
            ? ` <span style="color:var(--text-mid)">${esc(facts.join(" · "))}</span>` : "";
        // What to do: by the module's reason code first, then by state.
        const hints = {
            no_secret: t("car_phone_agent_hint_no_secret", "wpisz BCM_CAR_PHONE_AGENT_SECRET do /etc/bcm/bcm.env i zrestartuj BCM"),
            unpaired: t("car_phone_agent_hint_unpaired", "w Termuxie: python ~/bcm_agent/bcm_agent.py --pair, wpisz kod i Sparuj"),
            bad_signature: t("car_phone_agent_hint_bad_signature", "na porcie agenta odpowiada coś innego — sprawdź telefon"),
            pairing_closed: t("car_phone_agent_hint_pairing_closed", "brak kodu w telefonie — wygeneruj nowy: python ~/bcm_agent/bcm_agent.py --pair"),
            bad_code: t("car_phone_agent_hint_bad_code", "zły kod — sprawdź: cat ~/.config/bcm_agent/PAIRING"),
            secret_mismatch: t("car_phone_agent_hint_secret_mismatch", "agent ma inny sekret — wygeneruj kod w telefonie (--pair) i sparuj ponownie"),
            agent_reset: t("car_phone_agent_hint_agent_reset", "agent nie zna już sekretu — jeśli nie reinstalowałeś Termuxa, na porcie 8765 odpowiada inna aplikacja; sprawdź telefon"),
            clock_skew: t("car_phone_agent_hint_clock_skew", "zegar telefonu i BCM różni się o ponad minutę"),
            no_answer: t("car_phone_agent_hint_no_answer", "agent nie odpowiada — czy Termux z bcm_agent.py działa?"),
            config_pending: t("car_phone_agent_hint_config_pending", "telefon ma starą konfigurację — ponowię"),
            config_refused: t("car_phone_agent_hint_config_refused", "agent odrzucił konfigurację — sprawdź crash_detection.sms"),
        };
        const has = (k) => typeof k === "string" && k !== "" && Object.prototype.hasOwnProperty.call(hints, k);
        let hintText = "";
        if (has(ag.reason)) hintText = hints[ag.reason];
        else if (state !== "error" && has(state)) hintText = hints[state];
        const hint = hintText
            ? `<span data-car-phone-agent-hint style="color:var(--text-mid);flex-basis:100%;padding-left:24px">${esc(hintText)}</span>` : "";
        // The pairing form: code input + "Sparuj" ("Sparuj mimo to" after a
        // proven pairing — needs_confirm). No data in the inline handler;
        // the confirmation flag is a fixed data attribute.
        let pair = "";
        if (Settings.carPhoneAgentCanPair(ag)) {
            const confirm = ag.needs_confirm === true;
            const btnLabel = confirm ? t("car_phone_agent_pair_anyway", "Sparuj mimo to")
                : t("car_phone_agent_pair", "Sparuj");
            pair = `<span data-car-phone-agent-form style="flex-basis:100%;display:flex;flex-wrap:wrap;align-items:center;gap:6px;padding-left:24px">
                <input data-car-phone-agent-code type="tel" inputmode="numeric" maxlength="10" autocomplete="off" placeholder="${esc(t("car_phone_agent_code", "kod z telefonu"))}" style="width:130px;padding:6px 8px;border-radius:8px;font-size:13px;letter-spacing:1px;background:var(--color-surface);color:var(--text-primary);border:1px solid var(--card-border)">
                <button data-car-phone-agent-pair data-confirm="${confirm ? "1" : "0"}" onclick="Settings.carPhoneAgentPair(this)" style="padding:7px 14px;border-radius:8px;font-size:12px;font-weight:700;background:${confirm ? "#d97706" : "var(--card-border)"};color:${confirm ? "#fff" : "var(--text-mid)"};border:none">${esc(btnLabel)}</button>
                <span data-car-phone-agent-msg style="color:var(--text-mid)"></span>
            </span>`;
        }
        return `<div data-car-phone-agent-state="${esc(state)}" style="display:flex;flex-wrap:wrap;align-items:center;gap:4px 8px;padding:8px 12px;border-radius:12px;background:var(--card-bg);border:1px solid var(--card-border);font-size:11px;line-height:1.3">
            <span class="material-symbols-outlined" style="font-size:16px;color:${color}">sms</span>
            <span style="color:var(--text-dim);font-weight:700">${esc(t("car_phone_agent", "Agent w telefonie"))}:</span>
            <span style="color:${color};font-weight:700">${esc(label)}</span>${factsHtml}${hint}${pair}
        </div>`;
    },

    // SMS po stłuczce (src/safety/crash_sms.py). data.crash_sms =
    // web_viewer._crash_sms_summary(crash.sms_state), or null while the
    // module is not running (production config: no section at all). Phone
    // numbers are NEVER in the payload: the editor fetches them from the
    // loopback-only GET /api/crash/recipients.
    _crash: { recipients: ["", "", ""], loaded: false, loading: false, msg: "",
              testArmAt: 0, testMsg: "", saveAt: 0, listening: false },
    // The on-screen keyboard has no "+": the field holds the digits after it.
    _crashDigitsRe: /^[1-9][0-9]{7,14}$/,
    _crashTestArmMs: 6000,
    // The confirming tap must come this long after the arming one: a
    // bounced / double tap (two clicks a few ms apart) must not send a REAL
    // SMS to everybody.
    _crashTestMinGapMs: 700,

    /** Pure: the typed fields → {numbers: ["+48…"], bad: index|-1, reason}.
     *  Spaces and dashes are dropped, a leading "+" or "00" is accepted,
     *  empty fields are skipped; at most 3 (there are only 3 fields).
     *  Exactly 9 digits is refused (reason "no_cc"): that is a Polish number
     *  typed without 48, and "+" + those digits would be another country
     *  (601234567 → +60 Malaysia). A "48" number must have 9 digits after
     *  it. The server checks the same. */
    crashParseRecipients(fields) {
        const numbers = [];
        const list = Array.isArray(fields) ? fields.slice(0, 3) : [];
        for (let i = 0; i < list.length; i++) {
            let v = typeof list[i] === "string" ? list[i].replace(/[\s-]/g, "") : "";
            if (!v) continue;
            if (v.startsWith("+")) v = v.slice(1);
            else if (v.startsWith("00")) v = v.slice(2);
            if (!Settings._crashDigitsRe.test(v)) return { numbers: [], bad: i, reason: "" };
            if (v.length === 9) return { numbers: [], bad: i, reason: "no_cc" };
            if (v.startsWith("48") && v.length !== 11) return { numbers: [], bad: i, reason: "" };
            const num = "+" + v;
            if (numbers.indexOf(num) < 0) numbers.push(num);
        }
        return { numbers, bad: -1, reason: "" };
    },

    /** Pure: a saved number as the field shows it (the "+" is printed in
     *  front of the field): "+48601234567" → "48 601 234 567", so the
     *  country code is visible; others as plain digits. */
    crashFieldText(num) {
        if (typeof num !== "string") return "";
        const d = num.replace(/^\+/, "");
        if (!/^[0-9]{1,15}$/.test(d)) return "";
        const m = d.match(/^48([0-9]{3})([0-9]{3})([0-9]{3})$/);
        return m ? `48 ${m[1]} ${m[2]} ${m[3]}` : d;
    },

    /** Fetch the recipients once per Settings visit (kiosk only — the
     *  route refuses network clients). */
    async crashLoad(force) {
        const c = Settings._crash;
        if ((c.loaded && !force) || c.loading) return;
        c.loading = true;
        try {
            const res = await fetch("/api/crash/recipients");
            if (res.ok) {
                const data = await res.json();
                const list = Array.isArray(data.recipients) ? data.recipients : [];
                c.recipients = [0, 1, 2].map((i) => Settings.crashFieldText(list[i]));
                c.loaded = true;
                Settings._crashFillInputs();
            }
        } catch (e) { /* offline kiosk — the fields stay empty */ }
        c.loading = false;
    },

    _crashFillInputs() {
        if (typeof document === "undefined") return;
        document.querySelectorAll("[data-crash-rcpt]").forEach((input) => {
            const i = Number(input.getAttribute("data-crash-rcpt"));
            if (Number.isInteger(i) && i >= 0 && i < 3 && document.activeElement !== input) {
                input.value = Settings._crash.recipients[i] || "";
            }
        });
    },

    _crashSay(sel, text) {
        const node = typeof document !== "undefined" ? document.querySelector(sel) : null;
        if (node) node.textContent = text;
    },

    /** "Zapisz odbiorców": validated here and again on the server. */
    async crashSaveRecipients() {
        const t = (typeof App !== "undefined" && App.t) ? App.t.bind(App) : ((k, d) => d);
        const c = Settings._crash;
        const now = Date.now();
        if (now - c.saveAt < 1500) return;
        c.saveAt = now;
        const parsed = Settings.crashParseRecipients(c.recipients);
        const badMsg = (i, reason) => (reason === "no_cc"
            ? t("crash_rcpt_no_cc", "Numer {i}: dopisz 48 na początku (np. 48601234567)")
            : t("crash_rcpt_bad", "Numer {i}: wpisz numer z kierunkowym kraju, np. 48601234567"))
            .replace("{i}", () => String(i + 1));
        if (parsed.bad >= 0) {
            c.msg = badMsg(parsed.bad, parsed.reason);
            Settings._crashSay("[data-crash-msg]", c.msg);
            return;
        }
        try {
            const res = await fetch("/api/crash/recipients", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ recipients: parsed.numbers }),
            });
            let out = {};
            try { out = await res.json(); } catch (e) { /* not JSON */ }
            if (res.ok) {
                c.msg = out.persisted === false
                    ? t("crash_rcpt_not_persisted", "Zapisano, ale nie na dysku — po restarcie znikną")
                    : t("crash_rcpt_saved", "Zapisano ({n})").replace("{n}", () => String(parsed.numbers.length));
            } else if (res.status === 403) {
                c.msg = t("crash_kiosk_only", "Tylko z ekranu w aucie");
            } else if (res.status === 429) {
                c.msg = t("crash_wait", "Chwilę — spróbuj za kilka sekund");
            } else if (out && out.error === "bad_number" && Number.isInteger(out.index)
                       && out.index >= 0 && out.index < 3) {
                c.msg = badMsg(out.index, out.hint === "no_cc" ? "no_cc" : "");
            } else {
                c.msg = t("crash_rcpt_refused", "Nie zapisano — sprawdź numery");
            }
        } catch (e) {
            c.msg = t("crash_rcpt_refused", "Nie zapisano — sprawdź numery");
        }
        Settings._crashSay("[data-crash-msg]", c.msg);
    },

    /** "Wyślij testowy SMS": two taps (the first arms for 6 s) because it
     *  sends a REAL SMS to every recipient — that is the point: only a
     *  test confirmed in "wysłane" lets crash SMS leave test mode. */
    async crashTest() {
        const t = (typeof App !== "undefined" && App.t) ? App.t.bind(App) : ((k, d) => d);
        const c = Settings._crash;
        const now = Date.now();
        if (!c.testArmAt || now - c.testArmAt > Settings._crashTestArmMs) {
            c.testArmAt = now;
            c.testMsg = "";
            Settings._crashRedrawRow();
            // Back to "Wyślij testowy SMS" when the confirmation lapses.
            setTimeout(() => Settings._crashRedrawRow(), Settings._crashTestArmMs + 50);
            return;
        }
        // A bounce of the arming tap is not a confirmation.
        if (now - c.testArmAt < Settings._crashTestMinGapMs) return;
        c.testArmAt = 0;
        c.testMsg = t("crash_test_sending", "wysyłam…");
        Settings._crashRedrawRow();
        try {
            const res = await fetch("/api/crash/test", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ confirm: true }),
            });
            let out = {};
            try { out = await res.json(); } catch (e) { /* not JSON */ }
            const errors = {
                no_recipients: t("crash_test_no_recipients", "najpierw zapisz odbiorców"),
                not_running: t("crash_test_no_agent", "agent w telefonie nie działa"),
                busy: t("crash_test_busy", "test już w drodze"),
                config_pending: t("crash_test_config_pending", "telefon nie ma jeszcze nowych odbiorców — spróbuj za chwilę"),
                "too many requests": t("crash_wait", "Chwilę — spróbuj za kilka sekund"),
            };
            const key = out && typeof out.error === "string" ? out.error : "";
            if (res.ok) c.testMsg = t("crash_test_queued", "przekazano do telefonu");
            else if (res.status === 403) c.testMsg = t("crash_kiosk_only", "Tylko z ekranu w aucie");
            else c.testMsg = Object.prototype.hasOwnProperty.call(errors, key)
                ? errors[key] : t("crash_test_failed", "nie udało się");
        } catch (e) {
            c.testMsg = t("crash_test_failed", "nie udało się");
        }
        Settings._crashRedrawRow();
    },

    _crashRedrawRow() {
        if (typeof document === "undefined") return;
        const slot = document.querySelector("[data-crash-sms-slot]");
        const data = (typeof DataStore !== "undefined" && DataStore.getAll) ? DataStore.getAll() : {};
        const t = (typeof App !== "undefined" && App.t) ? App.t.bind(App) : ((k, d) => d);
        if (slot) slot.innerHTML = Settings.crashSmsRowHtml(data && data.crash_sms, t);
    },

    /** One delegated listener set for the section (data-* attributes, no
     *  data in inline handlers). Installed once on document. */
    crashListen() {
        const c = Settings._crash;
        if (c.listening || typeof document === "undefined" || !document.addEventListener) return;
        c.listening = true;
        document.addEventListener("click", (e) => {
            const el = e.target && e.target.closest ? e.target.closest("[data-crash-save],[data-crash-test]") : null;
            if (!el) return;
            if (el.hasAttribute("data-crash-save")) Settings.crashSaveRecipients();
            else Settings.crashTest();
        });
        document.addEventListener("input", (e) => {
            const el = e.target;
            if (!el || !el.getAttribute) return;
            const i = Number(el.getAttribute("data-crash-rcpt"));
            if (el.hasAttribute("data-crash-rcpt") && Number.isInteger(i) && i >= 0 && i < 3) {
                Settings._crash.recipients[i] = String(el.value || "").slice(0, 20);
            }
        });
    },

    _crashFmtTime(ts) {
        if (typeof ts !== "number" || !isFinite(ts) || ts <= 0) return "";
        const d = new Date(ts * 1000);
        const p2 = (n) => String(n).padStart(2, "0");
        return `${p2(d.getDate())}.${p2(d.getMonth() + 1)} ${p2(d.getHours())}:${p2(d.getMinutes())}`;
    },

    /** The status row "SMS po stłuczce: tryb testowy · odbiorcy: 2" plus why
     *  test mode is forced, the last test and "Wyślij testowy SMS". '' without
     *  a payload. Inline styles; every value escaped / type-checked. */
    crashSmsRowHtml(cs, t) {
        t = t || ((k, d) => d);
        if (!cs || typeof cs !== "object") return "";
        const esc = Settings._esc;
        const c = Settings._crash;
        const dry = cs.dry_run !== false;
        const color = dry ? "#d97706" : "#16a34a";
        const label = dry ? t("crash_mode_dry", "tryb testowy (SMS nie wychodzą)")
            : t("crash_mode_real", "prawdziwe SMS-y");
        const n = Number.isInteger(cs.recipients_n) && cs.recipients_n >= 0 && cs.recipients_n <= 3
            ? cs.recipients_n : 0;
        const reasons = {
            agent_not_ready: t("crash_forced_agent", "agent w telefonie nie jest gotowy"),
            no_verified_test: t("crash_forced_no_test", "brak potwierdzonego testowego SMS-a"),
            test_too_old: t("crash_forced_old_test", "testowy SMS starszy niż 30 dni"),
            sensors_not_streaming: t("crash_forced_sensors", "brak danych z czujników telefonu"),
            sensor_rate_low: t("crash_forced_rate", "za wolne próbkowanie czujników"),
            not_calibrated: t("crash_forced_calib", "czujniki telefonu nieskalibrowane"),
        };
        const reason = typeof cs.forced_dry_run_reason === "string"
            && Object.prototype.hasOwnProperty.call(reasons, cs.forced_dry_run_reason)
            ? `<span data-crash-reason style="color:#d97706;flex-basis:100%;padding-left:24px">${esc(
                t("crash_forced", "wymuszony tryb testowy: {reason}")
                    .replace("{reason}", () => reasons[cs.forced_dry_run_reason]))}</span>` : "";
        const test = cs.test && typeof cs.test === "object" ? cs.test : {};
        let testText;
        const verifiedAt = Settings._crashFmtTime(test.last_verified_ts);
        if (test.request === "sending" || test.request === "queued") {
            testText = t("crash_test_sending", "wysyłam…");
        } else if (test.state === "pending") {
            testText = t("crash_test_pending", "test w toku — telefon sprawdza wysłane");
        } else if (verifiedAt) {
            testText = t("crash_test_verified", "ostatni potwierdzony test: {when}").replace("{when}", () => verifiedAt);
        } else if (test.state === "failed" || test.state === "partial") {
            testText = t("crash_test_last_failed", "ostatni test nie doszedł do wszystkich");
        } else {
            testText = t("crash_test_none", "brak potwierdzonego testu");
        }
        const armed = c.testArmAt && Date.now() - c.testArmAt <= Settings._crashTestArmMs;
        const btnLabel = armed
            ? t("crash_test_confirm", "Na pewno? PRAWDZIWY SMS do {n} odbiorców").replace("{n}", () => String(n))
            : t("crash_test_send", "Wyślij testowy SMS");
        const testBtn = n > 0
            ? `<button type="button" data-crash-test data-armed="${armed ? "1" : "0"}" style="padding:7px 14px;border-radius:8px;font-size:12px;font-weight:700;border:none;background:${armed ? "#dc2626" : "var(--card-border)"};color:${armed ? "#fff" : "var(--text-mid)"}">${esc(btnLabel)}</button>` : "";
        return `<div data-crash-sms-row data-crash-dry="${dry ? "1" : "0"}" style="display:flex;flex-wrap:wrap;align-items:center;gap:4px 8px;padding:8px 12px;border-radius:12px;background:var(--card-bg);border:1px solid var(--card-border);font-size:11px;line-height:1.3">
            <span class="material-symbols-outlined" style="font-size:16px;color:${color}">car_crash</span>
            <span style="color:var(--text-dim);font-weight:700">${esc(t("crash_sms", "SMS po stłuczce"))}:</span>
            <span style="color:${color};font-weight:700">${esc(label)}</span>
            <span style="color:var(--text-mid)">${esc(t("crash_recipients", "odbiorcy SMS: {n}").replace("{n}", () => String(n)))}</span>${reason}
            <span data-crash-test-state style="color:var(--text-mid);flex-basis:100%;padding-left:24px">${esc(testText)}</span>
            <span style="flex-basis:100%;display:flex;flex-wrap:wrap;align-items:center;gap:6px;padding-left:24px">${testBtn}<span data-crash-test-msg style="color:var(--text-mid)">${esc(c.testMsg)}</span></span>
        </div>`;
    },

    /** The recipients editor (3 fields, the "+" is printed — the OSK has
     *  none). Drawn by render() only, never by update(): typing must not be
     *  clobbered by a data push. '' without a payload. */
    crashEditorHtml(cs, t) {
        t = t || ((k, d) => d);
        if (!cs || typeof cs !== "object") return "";
        const esc = Settings._esc;
        const fields = [0, 1, 2].map((i) => `<label style="display:flex;align-items:center;gap:4px">
                <span style="color:var(--text-dim);font-size:13px;font-weight:700">${esc(String(i + 1))}. +</span>
                <input data-crash-rcpt="${i}" type="tel" inputmode="numeric" maxlength="20" autocomplete="off" value="${esc(Settings._crash.recipients[i] || "")}" placeholder="${esc(t("crash_rcpt_placeholder", "np. 48601234567"))}" style="width:150px;padding:6px 8px;border-radius:8px;font-size:13px;letter-spacing:1px;background:var(--color-surface);color:var(--text-primary);border:1px solid var(--card-border)">
            </label>`).join("");
        return `<div data-crash-editor style="display:flex;flex-direction:column;gap:6px;padding:8px 12px;border-radius:12px;background:var(--card-bg);border:1px solid var(--card-border);font-size:11px;line-height:1.3">
            <span style="color:var(--text-dim);font-weight:700">${esc(t("crash_rcpt_title", "Odbiorcy SMS po stłuczce (najwyżej 3, z kierunkowym kraju)"))}</span>
            <div style="display:flex;flex-wrap:wrap;gap:6px 12px">${fields}</div>
            <div style="display:flex;flex-wrap:wrap;align-items:center;gap:8px">
                <button type="button" data-crash-save style="padding:7px 14px;border-radius:8px;font-size:12px;font-weight:700;border:none;background:var(--color-primary);color:#fff">${esc(t("crash_rcpt_save", "Zapisz odbiorców"))}</button>
                <span data-crash-msg style="color:var(--text-mid)">${esc(Settings._crash.msg)}</span>
            </div>
        </div>`;
    },

    /** One info row "GPS: <źródło> <stan> <nadawca>" from data.gps_state
     *  (web_viewer._gps_state_summary of gps.source_state), plus — while
     *  there is no fix — where the phone should send its NMEA: the head
     *  unit's bnep0 address from data.phone_tether (Bluetooth PAN reaches
     *  every app on the phone; 10.0.0.1 of wireless AA does not). '' without
     *  a payload (location module off). Inline styles only; every value is
     *  escaped (the sender address comes from the network). */
    gpsRowHtml(gs, pt, t) {
        t = t || ((k, d) => d);
        if (!gs || typeof gs !== "object") return "";
        const esc = Settings._esc;
        const fix = gs.state === "fix";
        const color = fix ? "#16a34a" : "#d97706";
        const names = { udp: "UDP", tcp: "TCP", serial: t("gps_src_serial", "port szeregowy"),
                        demo: t("gps_src_demo", "demo") };
        const source = (typeof gs.source === "string" ? gs.source : "").split(",")
            .filter(Boolean).map((n) => names[n] || n).join(" + ") || "—";
        const label = fix ? t("gps_state_fix", "jest pozycja") : t("gps_state_no_fix", "brak pozycji");
        const peer = (fix && gs.peer)
            ? ` <span style="color:var(--text-dim)">${esc(t("gps_peer", "od"))}</span> <span style="color:var(--text-mid);font-family:monospace">${esc(gs.peer)}</span>` : "";
        let hint = "";
        if (!fix) {
            const ip = (pt && typeof pt === "object" && pt.state === "connected" && pt.ip)
                ? String(pt.ip) : t("gps_hint_no_ip", "<IP bnep0 z „Internet z telefonu”>");
            const parts = [];
            if (Number.isInteger(gs.udp_port)) {
                // Function replacements: "$&" in a value must stay literal.
                parts.push(t("gps_hint_udp", "Wyślij NMEA na {addr}:{port} (UDP)")
                    .replace("{addr}", () => ip).replace("{port}", () => String(gs.udp_port)));
            }
            if (Number.isInteger(gs.tcp_port)) {
                parts.push(t("gps_hint_tcp", "uruchom serwer NMEA TCP na porcie {port}")
                    .replace("{port}", () => String(gs.tcp_port)));
            }
            if (parts.length) {
                hint = `<span data-gps-hint style="color:var(--text-mid);flex-basis:100%;padding-left:24px">${esc(
                    parts.join(" " + t("gps_hint_or", "albo") + " "))}</span>`;
            }
        }
        return `<div data-gps-state="${esc(fix ? "fix" : "no_fix")}" style="display:flex;flex-wrap:wrap;align-items:center;gap:4px 8px;padding:8px 12px;border-radius:12px;background:var(--card-bg);border:1px solid var(--card-border);font-size:11px;line-height:1.3">
            <span class="material-symbols-outlined" style="font-size:16px;color:${color}">${fix ? "gps_fixed" : "gps_not_fixed"}</span>
            <span style="color:var(--text-dim);font-weight:700">${esc(t("gps_row", "GPS"))}:</span>
            <span style="color:var(--text-mid)">${esc(source)}</span>
            <span style="color:${color};font-weight:700">${esc(label)}</span>${peer}${hint}
        </div>`;
    },

    async aaLoad(force) {
        if (Settings._aa.loaded && !force) return;
        try {
            const res = await fetch("/api/aa/config");
            const data = await res.json();
            Settings._aa.autoRestart = !!data.auto_restart;
            Settings._aa.loaded = true;
            App.navigateTo("settings");
        } catch (e) {}
    },

    async toggleAAAutoRestart() {
        const next = !Settings._aa.autoRestart;
        Settings._aa.autoRestart = next;
        App.navigateTo("settings");
        try {
            await fetch("/api/aa/config", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ auto_restart: next }),
            });
        } catch (e) {
            Settings._aa.autoRestart = !next;
            App.navigateTo("settings");
        }
    },

    async restartAA() {
        Settings._aa.restarting = true;
        App.navigateTo("settings");
        try {
            await fetch("/api/aa/restart", { method: "POST" });
        } catch (e) {}
        setTimeout(() => {
            Settings._aa.restarting = false;
            App.navigateTo("settings");
        }, 3000);
    },

    async modulesLoad(force) {
        if (Settings._modules.loaded && !force) return;
        try {
            const res = await fetch("/api/modules");
            const data = await res.json();
            Settings._modules.list = Array.isArray(data.modules) ? data.modules : [];
            Settings._modules.restartRequired = !!data.restart_required;
            Settings._modules.loaded = true;
            Settings._modulesRedraw(false);
        } catch (e) { /* keep last known state */ }
    },

    _t() {
        return (App.t ? App.t.bind(App) : (k, d) => d);
    },

    /** Redraw only the Moduły card. A full App.navigateTo("settings")
     *  rebuilds .content-area and puts its scroll back at the top — the card
     *  sits near the bottom of Settings, so on the 1024x600 panel the
     *  question (and the save status) would be drawn below the screen while
     *  the tapped checkbox just flips back. Same pattern as update() for
     *  [data-tether-slot]. `reveal`: after an action, scroll the question /
     *  status (drawn under the tapped row) into view by the smallest amount.
     *  Without the card in the DOM (the driver left Settings while a
     *  request was in flight) the state is only kept for the next visit —
     *  never pull the driver back to Settings. */
    _modulesRedraw(reveal) {
        const slot = document.querySelector("[data-modules-card]");
        if (!slot) {
            if (App.getCurrentScreen && App.getCurrentScreen() === "settings") {
                App.navigateTo("settings");
            }
            return;
        }
        slot.innerHTML = Settings.modulesCardHtml(Settings._modules, Settings._t());
        if (!reveal) return;
        const el = slot.querySelector("[data-module-question]")
            || slot.querySelector("[data-modules-status]");
        if (el && typeof el.scrollIntoView === "function") el.scrollIntoView({ block: "nearest" });
    },

    /** Checkbox changed. A toggle with consequences opens a question under
     *  the module's row instead of saving: switching on a module whose
     *  dependencies do not run, or switching off one that others need.
     *  Everything else is saved at once. The checkbox is redrawn from the
     *  list, so until the driver confirms it shows the saved state. */
    async moduleToggle(name, enabled) {
        const mods = Settings._modules;
        const m = mods.list.find(x => x && x.name === name);
        if (!m || typeof enabled !== "boolean") return;
        const t = Settings._t();
        if (enabled && m.available === false) {
            mods.status = t("module_unavailable", "niedostępny w tej wersji");
            mods.statusName = name;
            Settings._modulesRedraw(true);
            return;
        }
        const blocked = Array.isArray(m.blocked_by) ? m.blocked_by : [];
        if (enabled && blocked.length) {
            mods.confirm = { name, action: "enable", blocked,
                             needs: Array.isArray(m.needs) ? m.needs : null };
            Settings._modulesRedraw(true);
            return;
        }
        const stops = Array.isArray(m.would_stop) ? m.would_stop : [];
        if (!enabled && stops.length) {
            mods.confirm = { name, action: "disable", stops };
            Settings._modulesRedraw(true);
            return;
        }
        mods.confirm = null;
        await Settings._modulePost({ name, enabled });
    },

    /** "Włącz z zależnościami" in the row of a module that is ON but does
     *  not run (a dependency is off, or on but itself blocked): the same
     *  question as for enabling, listing what the server says has to be
     *  switched on (`needs`). Nothing is saved before the driver confirms. */
    moduleFixDeps(name) {
        const mods = Settings._modules;
        const m = mods.list.find(x => x && x.name === name);
        if (!m || !m.enabled || m.runs || !Array.isArray(m.needs) || !m.needs.length) return;
        mods.confirm = { name, action: "enable", already: true,
                         blocked: Array.isArray(m.blocked_by) ? m.blocked_by : [],
                         needs: m.needs };
        Settings._modulesRedraw(true);
    },

    /** Answer to the open question: "deps" (enable with dependencies),
     *  "only" (save this toggle alone), "disable", or "cancel". */
    async moduleConfirm(choice) {
        const c = Settings._modules.confirm;
        Settings._modules.confirm = null;
        if (!c || choice === "cancel") {
            Settings._modulesRedraw(false);
            return;
        }
        if (c.action === "enable" && (choice === "deps" || choice === "only")) {
            const withDeps = choice === "deps" && Array.isArray(c.needs) && c.needs.length > 0;
            await Settings._modulePost({ name: c.name, enabled: true, with_deps: withDeps });
        } else if (c.action === "disable" && choice === "disable") {
            await Settings._modulePost({ name: c.name, enabled: false });
        } else {
            Settings._modulesRedraw(false);
        }
    },

    async _modulePost(body) {
        const mods = Settings._modules;
        if (mods.busy) return;               // double tap while saving
        mods.busy = true;
        const t = Settings._t();
        try {
            const res = await fetch("/api/modules", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(body),
            });
            let data = {};
            try { data = await res.json(); } catch (e) { /* non-JSON error page */ }
            if (res.ok && data && data.ok) {
                if (Array.isArray(data.modules)) {
                    mods.list = data.modules;
                } else {
                    const m = mods.list.find(x => x && x.name === body.name);
                    if (m) m.enabled = body.enabled;
                }
                mods.restartRequired = !!data.restart_required;
                let msg = data.restart_required
                    ? t("module_saved_restart", "Zapisano — wymaga restartu BCM")
                    : t("module_saved", "Zapisano");
                if (Array.isArray(data.enabled_also) && data.enabled_also.length) {
                    msg += " — " + t("module_enabled_also", "włączono też: {deps}")
                        .replace("{deps}", () => data.enabled_also.map(String).join(", "));
                }
                if (data.persisted === false) {
                    msg += " — " + t("module_not_persisted",
                        "nie zapisano w local.yaml — zmiana zniknie po restarcie");
                }
                mods.status = msg;
            } else {
                mods.status = (data && typeof data.error === "string")
                    ? data.error : ("HTTP " + res.status);
            }
        } catch (e) {
            mods.status = "error: " + e;
        }
        mods.statusName = typeof body.name === "string" ? body.name : null;
        mods.busy = false;
        Settings._modulesRedraw(true);
    },

    /** name -> module of the list (a Map: a module called "__proto__" or
     *  "constructor" must not reach Object.prototype). */
    _moduleIndex(list) {
        const byName = new Map();
        if (Array.isArray(list)) {
            list.forEach(m => { if (m && typeof m.name === "string") byName.set(m.name, m); });
        }
        return byName;
    },

    /** One dependency as the driver should read it. A dependency that is
     *  switched ON but does not run is not "off" — telling the driver to
     *  enable it would send them to the wrong toggle; its own dependency is
     *  the cause (the row of that module says which). */
    _moduleDepLabel(name, byName, t) {
        const d = byName ? byName.get(String(name)) : undefined;
        if (d && d.available === false) {
            return `${name} (${t("module_unavailable", "niedostępny w tej wersji")})`;
        }
        if (d && d.enabled && !d.runs) {
            return `${name} (${t("module_dep_blocked", "włączony, ale nie działa")})`;
        }
        return String(name);
    },

    /** "a, b lub c" for requirement groups ([["a"], ["b", "c"]]); with
     *  `byName` (see _moduleIndex) each name says why it does not run. */
    _moduleGroupsText(groups, t, byName) {
        if (!Array.isArray(groups)) return "";
        const or = " " + t("module_or", "lub") + " ";
        const label = byName ? (n => Settings._moduleDepLabel(n, byName, t)) : String;
        return groups.filter(Array.isArray)
            .map(g => g.map(label).join(or))
            .filter(Boolean).join(", ");
    },

    /** One module: checkbox (data-module, never inline data in JS), name,
     *  description, hardware note, requirements, and why it will not start /
     *  that it needs a restart. For a module that is on but blocked it shows
     *  the server's `needs` (what actually has to be switched on — for a
     *  chain that is the root, not the direct dependency) with a "Włącz z
     *  zależnościami" button. `byName`: the whole list (_moduleIndex), for
     *  the dependency labels. Every value escaped; inline styles only. */
    moduleRowHtml(m, t, byName) {
        t = t || ((k, d) => d);
        if (!m || typeof m !== "object" || typeof m.name !== "string") return "";
        const esc = Settings._esc;
        const unavailable = m.available === false;
        // A planned module cannot be switched on; one that is on anyway
        // (hand-edited local.yaml) can still be switched off.
        const disabled = unavailable && !m.enabled;
        const req = [];
        if (Array.isArray(m.requires)) m.requires.forEach(n => req.push([n]));
        if (Array.isArray(m.requires_any)) m.requires_any.forEach(g => req.push(g));
        const lines = [];
        if (m.hardware) {
            lines.push(`<span data-module-hw style="color:var(--text-mid)">${esc(t("module_hardware", "Sprzęt"))}: ${esc(m.hardware)}</span>`);
        }
        if (req.length) {
            lines.push(`<span style="color:var(--text-dim)">${esc(t("module_requires", "wymaga"))}: ${esc(Settings._moduleGroupsText(req, t))}</span>`);
        }
        let fix = "";
        if (unavailable) {
            lines.push(`<span data-module-unavailable style="color:var(--text-dim);font-style:italic">${esc(t("module_unavailable", "niedostępny w tej wersji"))}</span>`);
        } else if (m.enabled && !m.runs && m.reason === "cycle") {
            lines.push(`<span data-module-blocked style="color:#d97706;font-weight:700">${esc(t("module_cycle", "nie wystartuje — błąd katalogu modułów"))}</span>`);
        } else if (m.enabled && !m.runs && Array.isArray(m.needs) && m.needs.length) {
            lines.push(`<span data-module-blocked style="color:#d97706;font-weight:700">${esc(t("module_blocked_needs", "nie wystartuje — trzeba włączyć"))}: ${esc(m.needs.map(String).join(", "))}</span>`);
            // The name travels in a data attribute, never inside the JS.
            fix = `<button type="button" data-module-fix="${esc(m.name)}" onclick="Settings.moduleFixDeps(this.dataset.moduleFix)" style="align-self:flex-start;margin-top:2px;padding:4px 10px;border-radius:8px;font-size:10px;font-weight:700;border:none;background:var(--color-primary);color:#fff">${esc(t("module_enable_with_deps", "Włącz z zależnościami"))}</button>`;
        } else if (m.enabled && !m.runs && Array.isArray(m.blocked_by) && m.blocked_by.length) {
            lines.push(`<span data-module-blocked style="color:#d97706;font-weight:700">${esc(t("module_blocked", "nie wystartuje — brak"))}: ${esc(Settings._moduleGroupsText(m.blocked_by, t, byName))}</span>`);
        }
        if (m.restart_pending) {
            lines.push(`<span data-module-restart style="color:var(--color-primary);font-weight:700">${esc(t("module_restart_pending", "wymaga restartu BCM"))}</span>`);
        }
        // The fix button sits outside the <label>: a tap on it must not
        // also toggle the checkbox.
        return `<div data-module-cell="${esc(m.name)}" style="display:flex;flex-direction:column;border-bottom:1px solid var(--card-border);padding:4px 0;min-width:0">
        <label data-module-row="${esc(m.name)}" style="display:flex;align-items:flex-start;gap:8px;cursor:${disabled ? "default" : "pointer"};opacity:${disabled ? "0.6" : "1"}">
            <input type="checkbox" data-module="${esc(m.name)}" ${m.enabled ? "checked" : ""} ${disabled ? "disabled" : ""}
                style="margin-top:2px;flex:none" onchange="Settings.moduleToggle(this.dataset.module, this.checked)">
            <span style="display:flex;flex-direction:column;gap:1px;min-width:0;flex:1;font-size:9px;line-height:1.3">
                <span style="display:flex;gap:6px;align-items:baseline;min-width:0">
                    <span style="font-size:11px;font-weight:700;color:var(--color-on-surface);flex:none">${esc(m.name)}</span>
                    <span style="color:var(--text-dim);margin-left:auto;text-align:right;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;min-width:0">${esc(m.description)}</span>
                </span>
                ${lines.join("")}
            </span>
        </label>${fix ? `<span style="padding-left:21px">${fix}</span>` : ""}
        </div>`;
    },

    /** The open question (see moduleToggle), or ''. Buttons carry fixed
     *  choice words only — the module name is never part of the JS.
     *  `byName` (_moduleIndex) marks dependencies that are on but blocked. */
    moduleConfirmHtml(c, t, byName) {
        t = t || ((k, d) => d);
        if (!c || typeof c !== "object" || typeof c.name !== "string") return "";
        const esc = Settings._esc;
        const btn = (choice, label, primary) =>
            `<button type="button" data-module-confirm="${choice}" onclick="Settings.moduleConfirm('${choice}')" style="padding:6px 12px;border-radius:8px;font-size:11px;font-weight:700;border:none;${primary ? "background:var(--color-primary);color:#fff" : "background:var(--card-border);color:var(--text-mid)"}">${esc(label)}</button>`;
        const sub = (key, fallback, deps) => t(key, fallback)
            .replace("{name}", () => c.name).replace("{deps}", () => deps);
        let text = "";
        let buttons = "";
        if (c.action === "enable") {
            const missing = Settings._moduleGroupsText(c.blocked, t, byName);
            text = esc(sub("module_needs_title", "„{name}” wymaga modułów, które nie działają: {deps}.", missing));
            if (Array.isArray(c.needs) && c.needs.length) {
                text += " " + esc(sub("module_enable_also", "Włączyć też: {deps}?", c.needs.map(String).join(", ")));
                buttons = btn("deps", t("module_enable_with_deps", "Włącz z zależnościami"), true);
                // Already on (the row's fix button): "only this one" would change nothing.
                if (!c.already) buttons += btn("only", t("module_enable_only", "Tylko ten moduł"), false);
            } else {
                text += " " + esc(sub("module_deps_unavailable",
                    "Potrzebne moduły nie są dostępne w tej wersji — „{name}” nie wystartuje.", ""));
                if (!c.already) buttons = btn("only", t("module_enable_anyway", "Zapisz mimo to"), false);
            }
        } else if (c.action === "disable") {
            const stops = Array.isArray(c.stops) ? c.stops.map(String).join(", ") : "";
            text = esc(sub("module_disable_stops", "Wyłączenie „{name}” zatrzyma też: {deps}.", stops));
            buttons = btn("disable", t("module_disable", "Wyłącz"), true);
        } else {
            return "";
        }
        buttons += btn("cancel", t("module_cancel", "Anuluj"), false);
        return `<div data-module-question="${esc(c.action)}" style="margin:4px 0 8px 0;padding:8px 12px;border-radius:12px;border:1px solid #d97706;background:var(--card-bg);font-size:11px;line-height:1.4;color:var(--color-on-surface)">
            <p style="margin:0 0 8px 0">${text}</p>
            <div style="display:flex;flex-wrap:wrap;gap:8px">${buttons}</div>
        </div>`;
    },

    /** Body of the Moduły card: restart banner, the module list grouped by
     *  catalog ``group``, and the open question / last save status. Those
     *  two are drawn right under the grid line of the module they are about
     *  (across both columns), so they appear next to the checkbox the
     *  driver just tapped instead of at the top of a card taller than the
     *  screen; without a module they go to the top of the card. */
    modulesCardHtml(state, t) {
        t = t || ((k, d) => d);
        const esc = Settings._esc;
        state = state || {};
        const list = Array.isArray(state.list) ? state.list.filter(m => m && typeof m.name === "string") : [];
        const byName = Settings._moduleIndex(list);
        const confirm = state.confirm && typeof state.confirm === "object"
            && typeof state.confirm.name === "string" ? state.confirm : null;
        const statusHtml = state.status
            ? `<p data-modules-status style="margin:4px 0 8px 0;font-size:10px;color:var(--color-primary)">${esc(state.status)}</p>`
            : "";
        const statusName = statusHtml && typeof state.statusName === "string"
            && byName.has(state.statusName) ? state.statusName : null;
        const confirmName = confirm && byName.has(confirm.name) ? confirm.name : null;
        let html = "";
        if (state.restartRequired) {
            html += `<p data-modules-restart style="margin:0 0 8px 0;padding:6px 10px;border-radius:8px;background:var(--card-border);color:var(--color-primary);font-size:11px;font-weight:700">${esc(t("module_restart_pending", "wymaga restartu BCM"))}</p>`;
        }
        if (statusHtml && statusName === null) html += statusHtml;
        if (confirm && confirmName === null) html += Settings.moduleConfirmHtml(confirm, t, byName);
        const notesFor = (name) => {
            let h = "";
            if (name === confirmName) h += Settings.moduleConfirmHtml(confirm, t, byName);
            if (name === statusName) h += statusHtml;
            return h ? `<div data-module-notes="${esc(name)}" style="grid-column:1/-1;min-width:0">${h}</div>` : "";
        };
        const known = Settings._moduleGroups.map(g => g[0]);
        const groups = Settings._moduleGroups.slice();
        list.forEach(m => {
            const g = typeof m.group === "string" ? m.group : "";
            if (!known.includes(g)) { known.push(g); groups.push([g, "", g]); }
        });
        groups.forEach(([key, tkey, fallback]) => {
            const items = list.filter(m => (typeof m.group === "string" ? m.group : "") === key);
            if (!items.length) return;
            const cells = [];
            items.forEach((m, i) => {
                cells.push(Settings.moduleRowHtml(m, t, byName));
                // End of a grid line (2 columns) or of the group: the notes
                // of both modules on this line, so no row is pushed aside.
                if (i % 2 === 1 || i === items.length - 1) {
                    items.slice(i - (i % 2), i + 1).forEach(x => cells.push(notesFor(x.name)));
                }
            });
            html += `<p data-module-group="${esc(key)}" style="margin:8px 0 2px 0;font-size:9px;font-weight:700;letter-spacing:0.08em;text-transform:uppercase;color:var(--text-dim)">${esc(tkey ? t(tkey, fallback) : fallback)}</p>
                <div style="display:grid;grid-template-columns:repeat(2,minmax(0,1fr));column-gap:16px">${cells.join("")}</div>`;
        });
        return html;
    },

    async radioRefresh() {
        try {
            const res = await fetch("/api/radio/status");
            Settings._radio = await res.json();
        } catch (e) { /* keep last known state */ }
    },

    async toggleBT() {
        if (Settings._radioBusy) return;
        Settings._radioBusy = true;
        const next = !Settings._radio.bt.powered;
        // Optimistic UI flip so the toggle visibly responds while the
        // backend works (rfkill + bluetoothctl can take ~1s).
        Settings._radio.bt.powered = next;
        App.navigateTo("settings");
        try {
            const res = await fetch("/api/radio/bt", {
                method: "POST",
                headers: {"Content-Type": "application/json"},
                body: JSON.stringify({enabled: next}),
            });
            const d = await res.json();
            Settings._radio.bt.powered = !!d.powered;
        } catch (e) {
            Settings._radio.bt.powered = !next;
        }
        Settings._radioBusy = false;
        await Settings.radioRefresh();
        App.navigateTo("settings");
    },

    async toggleWiFi() {
        if (Settings._radioBusy) return;
        Settings._radioBusy = true;
        const next = !Settings._radio.wifi.running;
        Settings._radio.wifi.running = next;
        App.navigateTo("settings");
        try {
            const res = await fetch("/api/radio/wifi", {
                method: "POST",
                headers: {"Content-Type": "application/json"},
                body: JSON.stringify({enabled: next}),
            });
            const d = await res.json();
            Settings._radio.wifi.running = !!d.running;
        } catch (e) {
            Settings._radio.wifi.running = !next;
        }
        Settings._radioBusy = false;
        // Toggling resolves any pending "restart needed" state.
        Settings._wifi.restartRequired = false;
        await Settings.radioRefresh();
        App.navigateTo("settings");
    },

    _wifiFetchedAt: 0,
    async wifiLoad(force) {
        // Throttle: this is invoked from render() and would otherwise
        // re-fire every time the JSON response triggers another
        // navigateTo("settings") → render() → wifiLoad() cycle. Cap
        // it at one refresh per 3 s (same gate as radioRefresh), or
        // pass force=true on user actions that need fresh values.
        const now = Date.now();
        if (!force && now - Settings._wifiFetchedAt < 3000) return;
        Settings._wifiFetchedAt = now;
        try {
            const res = await fetch("/api/wifi/config");
            if (!res.ok) return;
            const d = await res.json();
            Settings._wifi.ssid = d.ssid || "";
            Settings._wifi.password = d.password || "";
            Settings._wifi.channel = d.channel || 6;
            Settings._wifi.mode = d.mode || "p2p_go";
            Settings._wifi.live_ssid = d.live_ssid || "";
            Settings._wifi.live_password = d.live_password || "";
            Settings._wifi.live_bssid = d.live_bssid || "";
            Settings._wifi.alfa_net_enabled = d.alfa_net_enabled !== false;
            Settings._wifi.alfa_net_ssid = d.alfa_net_ssid || "ALFA-NET";
            Settings._wifi.alfa_net_password = d.alfa_net_password || "";
            Settings._wifi.internet_share_available =
                d.internet_share_available === true;
            Settings._wifi.loaded = true;
            App.navigateTo("settings");
        } catch (e) {}
    },

    wifiUpdate(field, value) {
        if (field === "channel") {
            const n = parseInt(value, 10);
            Settings._wifi.channel = Number.isFinite(n) ? n : value;
        } else {
            Settings._wifi[field] = value;
        }
    },

    wifiTogglePwd() {
        Settings._wifi.showPwd = !Settings._wifi.showPwd;
        App.navigateTo("settings");
    },

    async wifiSave() {
        const ssid = (Settings._wifi.ssid || "").trim();
        const pwd = Settings._wifi.password || "";
        const ch = parseInt(Settings._wifi.channel, 10);
        const valid5 = new Set([36, 40, 44, 48, 149, 153, 157, 161, 165]);
        if (!ssid || ssid.length > 32) {
            Settings._wifi.status = "SSID required (1-32 chars)";
            App.navigateTo("settings");
            return;
        }
        if (pwd.length < 8 || pwd.length > 63) {
            Settings._wifi.status = "Password must be 8-63 chars";
            App.navigateTo("settings");
            return;
        }
        if (!Number.isFinite(ch) || !((ch >= 1 && ch <= 13) || valid5.has(ch))) {
            Settings._wifi.status = "Channel must be 1-13 or 36-165 (5 GHz)";
            App.navigateTo("settings");
            return;
        }
        // ALFA-NET secondary AP — only validate when changed from defaults.
        const anSsid = (Settings._wifi.alfa_net_ssid || "").trim();
        const anPwd = Settings._wifi.alfa_net_password || "";
        if (anPwd && (anPwd.length < 8 || anPwd.length > 63)) {
            Settings._wifi.status = "ALFA-NET password must be 8-63 chars";
            App.navigateTo("settings");
            return;
        }
        Settings._wifi.saving = true;
        Settings._wifi.status = "";
        App.navigateTo("settings");
        try {
            const res = await fetch("/api/wifi/config", {
                method: "POST",
                headers: {"Content-Type": "application/json"},
                body: JSON.stringify({
                    ssid, password: pwd, channel: ch,
                    alfa_net_enabled: !!Settings._wifi.alfa_net_enabled,
                    alfa_net_ssid: anSsid,
                    alfa_net_password: anPwd,
                }),
            });
            const d = await res.json();
            if (d.ok === false || d.error) {
                Settings._wifi.status = d.error || "Save failed";
            } else {
                Settings._wifi.restartRequired = !!d.restart_required;
                const apply = d.restart_required ? " — toggle Wi-Fi AP to apply" : "";
                // The change is live in both cases below, but would quietly
                // revert on the next BCM restart — say so instead of "Saved".
                // Strict checks: an older server without these fields = saved.
                if (Array.isArray(d.env_managed) && d.env_managed.length) {
                    Settings._wifi.status = "Applied until restart — password is " +
                        "managed by /etc/bcm/bcm.env" + apply;
                } else if (d.persisted === false) {
                    Settings._wifi.status = "Applied, but NOT saved (lost on restart)" + apply;
                } else {
                    Settings._wifi.status = "Saved" + apply;
                }
            }
        } catch (e) {
            Settings._wifi.status = "Save failed (network)";
        }
        Settings._wifi.saving = false;
        await Settings.radioRefresh();
        App.navigateTo("settings");
    },

    async setUnit(type, value) {
        const body = {};
        if (type === "speed") body.speed_unit = value;
        else if (type === "temp") body.temp_unit = value;
        try {
            await fetch("/api/config", { method: "POST", headers: {"Content-Type":"application/json"}, body: JSON.stringify(body) });
            App.navigateTo("settings");
        } catch (e) {}
    },

    async btMakeDiscoverable() {
        try {
            await fetch("/bt/discoverable", { method: "POST" });
        } catch (e) {}
        await Settings.btRefresh();
    },

    async btScan() {
        Settings._btScanning = true;
        App.navigateTo("settings");
        try {
            await fetch("/bt/scan", { method: "POST" });
        } catch (e) {}
        // Server-side scan runs ~15 s; refresh once at 10 s for early
        // discovered devices and again at 16 s to clear the spinner.
        setTimeout(() => Settings.btRefresh(), 10000);
        setTimeout(() => Settings.btRefresh(), 16000);
    },

    async btConnect(addr) {
        try {
            await fetch(`/bt/connect/${addr}`, { method: "POST" });
        } catch (e) {}
        await Settings.btRefresh();
    },

    async btDisconnect() {
        try {
            await fetch("/bt/disconnect", { method: "POST" });
        } catch (e) {}
        await Settings.btRefresh();
    },

    async btPair(addr) {
        console.log("[BT] Pairing:", addr);
        Settings._startPairingPoll();
        try {
            await fetch(`/bt/pair/${addr}`, { method: "POST" });
            console.log("[BT] Pair request completed");
        } catch (e) {
            console.error("[BT] Pair request failed:", e);
        }
        await Settings.btRefresh();
    },

    _pairingPopupVisible: false,
    _pairingPoll: null,
    _pairingPollCount: 0,

    _startPairingPoll() {
        if (Settings._pairingPoll) clearInterval(Settings._pairingPoll);
        Settings._pairingPollCount = 0;
        Settings._pairingPoll = setInterval(async () => {
            Settings._pairingPollCount++;
            if (Settings._pairingPollCount > 60) {
                clearInterval(Settings._pairingPoll);
                Settings._pairingPoll = null;
                Settings._hidePairingPopup();
                Settings.btRefresh();
                return;
            }
            try {
                const res = await fetch("/bt/pairing");
                const data = await res.json();
                if (data.pending && data.request) {
                    Settings._showPairingPopup(data.request);
                } else if (Settings._pairingPopupVisible) {
                    clearInterval(Settings._pairingPoll);
                    Settings._pairingPoll = null;
                    Settings._hidePairingPopup();
                    Settings.btRefresh();
                }
            } catch (e) {}
        }, 500);
    },

    _showPairingPopup(req) {
        if (Settings._pairingPopupVisible) return;
        Settings._pairingPopupVisible = true;
        const t = (App && App.t) ? App.t.bind(App) : (k, d) => d;
        let overlay = document.getElementById("bt-pairing-overlay");
        if (!overlay) {
            overlay = document.createElement("div");
            overlay.id = "bt-pairing-overlay";
            document.body.appendChild(overlay);
        }
        overlay.className = "fixed inset-0 z-[200] flex items-center justify-center";
        overlay.style.background = "rgba(0,0,0,0.85)";
        overlay.innerHTML = `<div style="background:var(--card-bg);border:1px solid var(--card-border)" class="rounded-2xl p-6 w-[360px] shadow-2xl text-center" style="color:var(--text-primary)">
            <span class="material-symbols-outlined text-4xl text-blue-400 mb-3">bluetooth</span>
            <h3 class="text-lg font-bold mb-2" style="color:var(--text-primary)">${t("bt_pair_confirm","Confirm Pairing")}</h3>
            <p class="text-sm mb-4" style="color:var(--text-dim)">${Settings._esc(req.address)}</p>
            <div class="rounded-xl py-4 px-6 mb-4" style="background:var(--color-surface)">
                <span class="text-3xl font-mono font-bold tracking-[0.3em]" style="color:var(--text-primary)">${Settings._esc(req.passkey || "------")}</span>
            </div>
            <p class="text-[10px] mb-4" style="color:var(--text-dim)">${t("bt_pair_match","Does this code match your device?")}</p>
            <div class="flex gap-3 justify-center">
                <button class="px-6 py-2 rounded-lg text-sm font-bold" style="background:var(--card-border);color:var(--text-mid)" onclick="Settings.btPairingRespond(false)">${t("reject","Reject")}</button>
                <button class="px-6 py-2 bg-green-600 rounded-lg text-sm font-bold text-white hover:bg-green-500" onclick="Settings.btPairingRespond(true)">${t("answer","Accept")}</button>
            </div>
        </div>`;
    },

    _hidePairingPopup() {
        Settings._pairingPopupVisible = false;
        const overlay = document.getElementById("bt-pairing-overlay");
        if (overlay) overlay.remove();
    },

    async btPairingRespond(accept) {
        console.log("[BT] Pairing response:", accept);
        try {
            await fetch("/bt/pairing/confirm", {
                method: "POST",
                headers: {"Content-Type": "application/json"},
                body: JSON.stringify({accept}),
            });
        } catch (e) {}
        if (Settings._pairingPoll) clearInterval(Settings._pairingPoll);
        Settings._hidePairingPopup();
        setTimeout(() => Settings.btRefresh(), 1000);
    },

    async btRemove(addr) {
        try { await fetch(`/bt/remove/${addr}`, { method: "POST" }); } catch (e) {}
        setTimeout(() => Settings.btRefresh(), 1000);
    },

    async btRefresh() {
        try {
            const res = await fetch("/bt/devices");
            const data = await res.json();
            Settings._btPaired = data.paired || [];
            Settings._btDiscovered = data.discovered || [];
            Settings._btScanning = false;
            App.navigateTo("settings");
        } catch (e) {
            Settings._btScanning = false;
        }
    },

    async swcLoad() {
        try {
            const res = await fetch("/api/config/swc");
            const data = await res.json();
            Settings._swcMapping = data.mapping || {};
            Settings._swcAllButtons = data.all_buttons || [];
            Settings._swcActions = data.actions || [];
        } catch (e) {
            console.error("[SWC] Load failed:", e);
        }
    },

    async swcSave() {
        if (!Settings._swcMapping) return;
        try {
            await fetch("/api/config/swc", {
                method: "POST",
                headers: {"Content-Type": "application/json"},
                body: JSON.stringify({ mapping: Settings._swcMapping }),
            });
        } catch (e) {
            console.error("[SWC] Save failed:", e);
        }
    },

    swcLearnStart(action, pod) {
        Settings._swcLearning = { action, pod };
        App.navigateTo("settings");
        fetch("/api/config/swc/learn", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({ action, pod }),
        });
        if (Settings._swcLearnTimer) clearInterval(Settings._swcLearnTimer);
        Settings._swcLearnTimer = setInterval(async () => {
            try {
                const res = await fetch("/api/config/swc/learn");
                const data = await res.json();
                if (!data.active) {
                    clearInterval(Settings._swcLearnTimer);
                    Settings._swcLearnTimer = null;
                    if (data.result && Settings._swcMapping) {
                        if (!Settings._swcMapping[action]) Settings._swcMapping[action] = ["", ""];
                        Settings._swcMapping[action][pod] = data.result;
                    }
                    Settings._swcLearning = null;
                    App.navigateTo("settings");
                }
            } catch (e) {}
        }, 500);
    },

    swcLearnCancel() {
        if (Settings._swcLearnTimer) clearInterval(Settings._swcLearnTimer);
        Settings._swcLearnTimer = null;
        Settings._swcLearning = null;
        App.navigateTo("settings");
    },
};

App.registerScreen("settings", (() => {
    let _radioFetchedAt = 0;
    // Last phone_tether / GPS payload drawn; update() redraws only those rows.
    let _tetherKey = "null";
    let _gpsKey = "null";
    let _carPhoneKey = "null";
    let _agentKey = "null";

    function _tetherKeyOf(data) {
        return JSON.stringify((data && data.phone_tether) || null);
    }

    function _carPhoneKeyOf(data) {
        return JSON.stringify((data && data.car_phone) || null);
    }

    function _agentKeyOf(data) {
        return JSON.stringify((data && data.car_phone_agent) || null);
    }

    /** What the crash SMS row shows (not the countdown — the window does). */
    let _crashKey = "null";
    function _crashKeyOf(data) {
        const cs = data && data.crash_sms;
        if (!cs || typeof cs !== "object") return "null";
        return JSON.stringify([cs.dry_run, cs.forced_dry_run_reason, cs.recipients_n, cs.test]);
    }

    /** What the GPS row shows: gps_state without last_ts (it changes with
     *  every fix, the row does not show it) + the bnep0 IP of the hint. */
    function _gpsKeyOf(data) {
        const gs = data && data.gps_state;
        if (!gs || typeof gs !== "object") return "null";
        const pt = data.phone_tether;
        return JSON.stringify([gs.source, gs.state, gs.peer, gs.udp_port, gs.tcp_port,
            pt && pt.state === "connected" ? pt.ip : ""]);
    }

    /** Live data while Settings is open: only the phone-internet, car phone,
     *  phone agent and GPS rows change here (state / IP appear while the driver watches). Never a full
     *  re-render — that would reset the scroll position and the OSK. */
    function update(data) {
        const t = App.t.bind(App);
        const key = _tetherKeyOf(data);
        if (key !== _tetherKey) {
            const slot = document.querySelector("[data-tether-slot]");
            if (slot) {
                _tetherKey = key;
                slot.innerHTML = Settings.tetherRowHtml(data && data.phone_tether, t);
            }
        }
        const carKey = _carPhoneKeyOf(data);
        if (carKey !== _carPhoneKey) {
            const slot = document.querySelector("[data-car-phone-slot]");
            if (slot) {
                _carPhoneKey = carKey;
                slot.innerHTML = Settings.carPhoneRowHtml(data && data.car_phone, t);
            }
        }
        const agentKey = _agentKeyOf(data);
        if (agentKey !== _agentKey) {
            const slot = document.querySelector("[data-car-phone-agent-slot]");
            // Not while the driver types the pairing code (retried on the
            // next update: _agentKey stays old).
            if (slot && !Settings.carPhoneAgentTyping(slot)) {
                _agentKey = agentKey;
                slot.innerHTML = Settings.carPhoneAgentRowHtml(data && data.car_phone_agent, t);
            }
        }
        const crashKey = _crashKeyOf(data);
        if (crashKey !== _crashKey) {
            const slot = document.querySelector("[data-crash-sms-slot]");
            if (slot) {
                _crashKey = crashKey;
                slot.innerHTML = Settings.crashSmsRowHtml(data && data.crash_sms, t);
            }
        }
        const gpsKey = _gpsKeyOf(data);
        if (gpsKey !== _gpsKey) {
            const slot = document.querySelector("[data-gps-slot]");
            if (slot) {
                _gpsKey = gpsKey;
                slot.innerHTML = Settings.gpsRowHtml(data && data.gps_state,
                                                     data && data.phone_tether, t);
            }
        }
    }

    function render(container, theme, data) {
        const config = App.getConfig();
        const t = App.t.bind(App);
        _tetherKey = _tetherKeyOf(data);
        _gpsKey = _gpsKeyOf(data);
        _carPhoneKey = _carPhoneKeyOf(data);
        _agentKey = _agentKeyOf(data);
        _crashKey = _crashKeyOf(data);
        const paired = Settings._btPaired;
        const discovered = Settings._btDiscovered;
        const scanning = Settings._btScanning;

        // Refresh radio status (BT power + WiFi AP) at most once every
        // 3s while the user is poking at settings — guarantees the
        // toggles reflect reality after rfkill/systemctl side-effects
        // settle without spamming the API on every keystroke re-render.
        const now = Date.now();
        if (now - _radioFetchedAt > 3000) {
            _radioFetchedAt = now;
            Settings.radioRefresh().then(() => App.navigateTo("settings"));
        }
        Settings.wifiLoad();
        Settings.modulesLoad();
        Settings.aaLoad();
        if (data && data.crash_sms) {
            Settings.crashListen();
            Settings.crashLoad();
        }

        container.innerHTML = `<div class="screen-container" style="background:var(--color-surface);color:var(--color-on-surface)">
            ${AppBar.render(theme, data)}
            <main class="content-area p-4 overflow-y-auto">
                <div class="grid grid-cols-2 gap-3">
                    <!-- Left column -->
                    <div class="flex flex-col gap-3">
                        <!-- Theme -->
                        <div class="rounded-xl p-3" style="background:var(--card-bg);border:1px solid var(--card-border)">
                            <p class="text-[10px] font-bold uppercase tracking-wider mb-2" style="color:var(--text-dim)">${t("theme")}</p>
                            <div class="flex gap-2">
                                ${_themeBtn("heritage", "Heritage", config.theme)}
                                ${_themeBtn("modern", "Modern", config.theme)}
                                ${_themeBtn("autodelta", "Autodelta", config.theme)}
                            </div>
                        </div>
                        <!-- Language + Units -->
                        <div class="rounded-xl p-3 flex gap-6" style="background:var(--card-bg);border:1px solid var(--card-border)">
                            <div>
                                <p class="text-[10px] font-bold uppercase tracking-wider mb-2" style="color:var(--text-dim)">${t("language")}</p>
                                <div class="flex gap-2">
                                    ${_langBtn("pl", "PL", config.language)}
                                    ${_langBtn("en", "EN", config.language)}
                                </div>
                            </div>
                            <div>
                                <p class="text-[10px] font-bold uppercase tracking-wider mb-2" style="color:var(--text-dim)">${t("speed_units")}</p>
                                <div class="flex gap-2">
                                    ${_unitBtn("km/h", "km/h", config.speed_unit, "speed")}
                                    ${_unitBtn("mph", "mph", config.speed_unit, "speed")}
                                </div>
                            </div>
                            <div>
                                <p class="text-[10px] font-bold uppercase tracking-wider mb-2" style="color:var(--text-dim)">${t("temp_units")}</p>
                                <div class="flex gap-2">
                                    ${_unitBtn("C", "\u00b0C", config.temp_unit, "temp")}
                                    ${_unitBtn("F", "\u00b0F", config.temp_unit, "temp")}
                                </div>
                            </div>
                        </div>
                        <!-- Internet from the phone (BT PAN). display:contents: an
                             empty slot (module off) adds no flex gap; update()
                             swaps its content. -->
                        <div data-tether-slot style="display:contents">${Settings.tetherRowHtml(data && data.phone_tether, t)}</div>
                        <!-- The phone mounted in the car (USB, adb) — same slot idea. -->
                        <div data-car-phone-slot style="display:contents">${Settings.carPhoneRowHtml(data && data.car_phone, t)}</div>
                        <!-- The Termux agent on that phone (pairing, health) — same slot idea. -->
                        <div data-car-phone-agent-slot style="display:contents">${Settings.carPhoneAgentRowHtml(data && data.car_phone_agent, t)}</div>
                        <!-- SMS po stłuczce: status + testowy SMS (update() swaps it)
                             and the recipients editor (render() only). -->
                        <div data-crash-sms-slot style="display:contents">${Settings.crashSmsRowHtml(data && data.crash_sms, t)}</div>
                        <div data-crash-editor-slot style="display:contents">${Settings.crashEditorHtml(data && data.crash_sms, t)}</div>
                        <!-- GPS source / fix + where to send NMEA (same slot idea). -->
                        <div data-gps-slot style="display:contents">${Settings.gpsRowHtml(data && data.gps_state, data && data.phone_tether, t)}</div>
                        <!-- Wi-Fi Hotspot / ALFA-NET network access. The live
                             Android Auto P2P-GO credentials used to show here,
                             but wpa_supplicant regenerates them every boot and
                             the phone receives them automatically over BT during
                             AA pairing — surfacing them here just confused, so
                             the read-only "Live AP" block was dropped. -->
                        <div class="rounded-xl p-3" style="background:var(--card-bg);border:1px solid var(--card-border)">
                            <p class="text-[10px] font-bold uppercase tracking-wider mb-2" style="color:var(--text-dim)">${t("wifi_hotspot","Wi-Fi Hotspot")}</p>
                            <p class="text-[9px] font-bold uppercase tracking-wider mb-1" style="color:var(--text-dim)">${t("defaults","Defaults (used in hostapd mode)")}</p>
                            <div class="space-y-2">
                                <div class="flex items-center gap-2">
                                    <label class="text-[9px] uppercase w-16" style="color:var(--text-dim)">SSID</label>
                                    <input type="text" maxlength="32" value="${_attrEsc(Settings._wifi.ssid)}"
                                        onfocus="OnScreenKeyboard.attach(this)"
                                        oninput="Settings.wifiUpdate('ssid', this.value)"
                                        class="flex-1 px-2 py-1 rounded text-xs"
                                        style="background:var(--color-surface);color:var(--text-primary);border:1px solid var(--card-border)">
                                </div>
                                <div class="flex items-center gap-2">
                                    <label class="text-[9px] uppercase w-16" style="color:var(--text-dim)">${t("password","Password")}</label>
                                    <input type="${Settings._wifi.showPwd ? 'text' : 'password'}" maxlength="63" value="${_attrEsc(Settings._wifi.password)}"
                                        onfocus="OnScreenKeyboard.attach(this)"
                                        oninput="Settings.wifiUpdate('password', this.value)"
                                        class="flex-1 px-2 py-1 rounded text-xs"
                                        style="background:var(--color-surface);color:var(--text-primary);border:1px solid var(--card-border)">
                                    <button onclick="Settings.wifiTogglePwd()"
                                        class="px-2 py-1 text-[9px] font-bold rounded"
                                        style="background:var(--card-border);color:var(--text-mid)">${Settings._wifi.showPwd ? t("hide","Hide") : t("show","Show")}</button>
                                </div>
                                <div class="flex items-center gap-2">
                                    <label class="text-[9px] uppercase w-16" style="color:var(--text-dim)">${t("channel","Channel")}</label>
                                    <input type="number" min="1" max="165" value="${Settings._wifi.channel}"
                                        oninput="Settings.wifiUpdate('channel', this.value)"
                                        class="w-16 px-2 py-1 rounded text-xs"
                                        style="background:var(--color-surface);color:var(--text-primary);border:1px solid var(--card-border)">
                                    <span class="text-[9px]" style="color:var(--text-dim)">${Settings._wifi.channel >= 36 ? "5 GHz" : "2.4 GHz"}</span>
                                    <button onclick="Settings.wifiSave()"
                                        ${Settings._wifi.saving ? 'disabled' : ''}
                                        class="ml-auto px-3 py-1 bg-green-600 text-white text-[10px] font-bold rounded hover:bg-green-500 ${Settings._wifi.saving ? 'opacity-50 cursor-not-allowed' : ''}">${Settings._wifi.saving ? t("saving","Saving...") : t("save","Save")}</button>
                                </div>
                                ${Settings._wifi.status ? `<p class="text-[10px]" style="color:var(--text-mid)">${Settings._wifi.status}</p>` : ""}
                                <!-- Internet Share (ALFA-NET secondary AP). Only viable on a
                                     second radio (USB WiFi dongle) — a second AP VIF on the
                                     MT7921 collapses the AA P2P-GO group — so the whole row is
                                     greyed out + disabled until BCM detects a spare radio. -->
                                <div class="pt-2 space-y-2 ${Settings._wifi.internet_share_available ? '' : 'opacity-50 cursor-not-allowed'}" style="border-top:1px solid var(--card-border)">
                                    <div class="flex items-center justify-between">
                                        <p class="text-[10px] font-bold uppercase tracking-wider" style="color:var(--text-dim)">${t("internet_share","Internet Share")}</p>
                                        <label class="inline-flex items-center gap-1 text-[9px]" style="color:var(--text-dim)">
                                            <input type="checkbox" ${Settings._wifi.alfa_net_enabled ? 'checked' : ''}
                                                ${Settings._wifi.internet_share_available ? '' : 'disabled'}
                                                oninput="Settings.wifiUpdate('alfa_net_enabled', this.checked)">
                                            ${t("enabled","Enabled")}
                                        </label>
                                    </div>
                                    ${Settings._wifi.internet_share_available ? `
                                    <div class="flex items-center gap-2">
                                        <label class="text-[9px] uppercase w-16" style="color:var(--text-dim)">SSID</label>
                                        <input type="text" maxlength="32" value="${_attrEsc(Settings._wifi.alfa_net_ssid || "ALFA-NET")}"
                                            onfocus="OnScreenKeyboard.attach(this)"
                                            oninput="Settings.wifiUpdate('alfa_net_ssid', this.value)"
                                            class="flex-1 px-2 py-1 rounded text-xs"
                                            style="background:var(--color-surface);color:var(--text-primary);border:1px solid var(--card-border)">
                                    </div>
                                    <div class="flex items-center gap-2">
                                        <label class="text-[9px] uppercase w-16" style="color:var(--text-dim)">${t("password","Password")}</label>
                                        <input type="${Settings._wifi.showAlfaPwd ? 'text' : 'password'}" maxlength="63" value="${_attrEsc(Settings._wifi.alfa_net_password || "")}"
                                            onfocus="OnScreenKeyboard.attach(this)"
                                            oninput="Settings.wifiUpdate('alfa_net_password', this.value)"
                                            class="flex-1 px-2 py-1 rounded text-xs"
                                            style="background:var(--color-surface);color:var(--text-primary);border:1px solid var(--card-border)">
                                        <button onclick="Settings._wifi.showAlfaPwd = !Settings._wifi.showAlfaPwd; App.navigateTo('settings')"
                                            class="px-2 py-1 text-[9px] font-bold rounded"
                                            style="background:var(--card-border);color:var(--text-mid)">${Settings._wifi.showAlfaPwd ? t("hide","Hide") : t("show","Show")}</button>
                                    </div>` : `
                                    <p class="text-[9px]" style="color:var(--text-dim)">${t("internet_share_needs_dongle","Plug a USB Wi-Fi dongle to enable internet sharing without dropping Android Auto.")}</p>`}
                                </div>
                                <div class="flex items-center justify-between pt-2" style="border-top:1px solid var(--card-border)">
                                    <p class="text-[10px]" style="color:var(--text-dim)">${
                                        Settings._wifi.restartRequired
                                            ? t("wifi_restart_needed","Toggle Wi-Fi AP to apply new credentials")
                                            : (Settings._radio.wifi && Settings._radio.wifi.running
                                                ? t("wifi_ap_on","On — phones can connect")
                                                : t("wifi_ap_off","Off — phones can't connect"))
                                    }</p>
                                    ${_toggle(Settings._radio.wifi && Settings._radio.wifi.running, "Settings.toggleWiFi()")}
                                </div>
                            </div>
                        </div>
                    </div>
                    <!-- Right column: Bluetooth -->
                    <div class="rounded-xl p-3 flex flex-col" style="background:var(--card-bg);border:1px solid var(--card-border)">
                        <div class="flex justify-between items-center mb-2">
                            <div class="flex items-center gap-2">
                                <p class="text-[10px] font-bold uppercase tracking-wider" style="color:var(--text-dim)">Bluetooth</p>
                                ${_toggle(Settings._radio.bt && Settings._radio.bt.powered, "Settings.toggleBT()")}
                            </div>
                            <div class="flex gap-1">
                                <button class="text-[9px] font-bold px-2 py-1 rounded hover:opacity-80 ${(Settings._radio.bt && Settings._radio.bt.powered) ? '' : 'opacity-50 cursor-not-allowed'}"
                                        style="background:var(--card-border);color:var(--text-mid)"
                                        ${(Settings._radio.bt && Settings._radio.bt.powered) ? 'onclick="Settings.btMakeDiscoverable()"' : 'disabled'}>
                                    ${t("bt_discoverable","Discoverable")}
                                </button>
                                <button class="text-[9px] font-bold px-2 py-1 rounded hover:opacity-80 ${(Settings._radio.bt && Settings._radio.bt.powered) ? '' : 'opacity-50 cursor-not-allowed'}"
                                        style="background:var(--card-border);color:var(--text-mid)"
                                        ${(Settings._radio.bt && Settings._radio.bt.powered) ? 'onclick="Settings.btScan()"' : 'disabled'}>
                                    ${scanning ? `<span class="animate-pulse">${t("bt_scanning","Scanning...")}</span>` : t("bt_scan", "Scan")}
                                </button>
                            </div>
                        </div>
                        <div class="flex-1 space-y-1 overflow-y-auto">
                            ${paired.length > 0 ? `
                                <p class="text-[8px] font-bold uppercase tracking-widest mt-1 mb-1" style="color:var(--text-dim)">${t("bt_paired","Paired")}</p>
                                ${paired.map(d => _renderDevice(d, "paired", t)).join("")}
                            ` : ""}
                            ${discovered.length > 0 ? `
                                <p class="text-[8px] font-bold uppercase tracking-widest mt-2 mb-1" style="color:var(--text-dim)">${t("bt_discovered","Discovered")}</p>
                                ${discovered.map(d => _renderDevice(d, "discovered", t)).join("")}
                            ` : ""}
                            ${paired.length === 0 && discovered.length === 0
                                ? `<p class="text-[10px] py-4 text-center" style="color:var(--text-dim)">${t("bt_no_devices", "No devices. Tap Scan.")}</p>`
                                : ""}
                        </div>
                    </div>
                </div>
                <!-- Audio / EQ -->
                <div class="rounded-xl p-3 mt-3 cursor-pointer hover:opacity-80" style="background:var(--card-bg);border:1px solid var(--card-border)" onclick="App.navigateTo('audio')">
                    <div class="flex items-center gap-3">
                        <span class="material-symbols-outlined" style="color:var(--color-primary)">equalizer</span>
                        <div>
                            <p class="text-sm font-bold" style="color:var(--color-on-surface)">Audio / Equalizer</p>
                            <p class="text-[10px]" style="color:var(--text-dim)">EQ presets, bass, treble, fader</p>
                        </div>
                        <span class="material-symbols-outlined ml-auto" style="color:var(--text-dim)">chevron_right</span>
                    </div>
                </div>
                <!-- SWC Button Mapping -->
                <div class="rounded-xl p-3 mt-3" style="background:var(--card-bg);border:1px solid var(--card-border)">
                    <p class="text-[10px] font-bold uppercase tracking-wider mb-2" style="color:var(--text-dim)">SWC Button Mapping</p>
                    ${_renderSwcTable()}
                </div>
                <!-- Module toggles (modules.* in bcm_config.yaml) -->
                <div class="rounded-xl p-3 mt-3" style="background:var(--card-bg);border:1px solid var(--card-border)">
                    <div class="flex items-center justify-between mb-2">
                        <p class="text-[10px] font-bold uppercase tracking-wider" style="color:var(--text-dim)">${t("modules", "Moduły")}</p>
                        <p class="text-[9px]" style="color:var(--text-dim)">${t("modules_hint", "Zmiany działają po restarcie BCM")}</p>
                    </div>
                    <div data-modules-card>${Settings.modulesCardHtml(Settings._modules, t)}</div>
                </div>
                <!-- System & Kiosk Control -->
                <div class="rounded-xl p-3 mt-3" style="background:var(--card-bg);border:1px solid var(--card-border)">
                    <div class="flex items-center justify-between mb-3 gap-2 flex-wrap">
                        <div>
                            <p class="text-[10px] font-bold uppercase tracking-wider" style="color:var(--text-dim)">${t("system_control", "SYSTEM I KIOSK")}</p>
                            <p class="text-[9px]" style="color:var(--text-dim)">${t("system_kiosk_desc", "Sterowanie procesami kiosku i Android Auto")}</p>
                        </div>
                        <div class="flex items-center gap-2">
                            <button class="px-3 py-1.5 rounded-lg text-xs font-bold hover:opacity-80 flex items-center gap-1.5 transition-opacity"
                                    style="background:var(--card-border);color:var(--text-mid)"
                                    onclick="App.restartKioskModal()">
                                <span class="material-symbols-outlined text-sm">restart_alt</span>
                                ${t("kiosk_restart", "Restart kiosku")}
                            </button>
                            <button class="px-3 py-1.5 bg-red-600 hover:bg-red-500 text-white rounded-lg text-xs font-bold flex items-center gap-1.5 shadow-md active:scale-95 transition-all"
                                    onclick="App.rebootSystemModal()"
                                    title="${t("system_reboot_desc", "Pełny reboot OS (np. przy braku karty dźwiękowej)")}">
                                <span class="material-symbols-outlined text-sm">power_settings_new</span>
                                ${t("system_reboot", "Restart komputera")}
                            </button>
                        </div>
                    </div>
                    <div class="grid grid-cols-2 gap-3 pt-2" style="border-top:1px solid var(--card-border)">
                        <!-- AA Auto-restart toggle -->
                        <div class="flex items-center justify-between p-2.5 rounded-lg" style="background:var(--color-surface)">
                            <div class="pr-2">
                                <p class="text-xs font-bold" style="color:var(--color-on-surface)">${t("aa_auto_restart", "Autorestart AA")}</p>
                                <p class="text-[9px]" style="color:var(--text-dim)">${t("aa_auto_restart_desc", "Automatycznie restartuj AA przy braku połączenia")}</p>
                            </div>
                            ${_toggle(Settings._aa.autoRestart, "Settings.toggleAAAutoRestart()")}
                        </div>

                        <!-- Manual AA restart button -->
                        <div class="flex items-center justify-between p-2.5 rounded-lg" style="background:var(--color-surface)">
                            <div>
                                <p class="text-xs font-bold" style="color:var(--color-on-surface)">${t("android_auto", "Android Auto")}</p>
                                <p class="text-[9px]" style="color:var(--text-dim)">Status: <span class="font-bold ${data.aa_status === 'connected' ? 'text-green-500' : data.aa_status === 'running' ? 'text-blue-400' : 'text-zinc-400'}">${data.aa_status || 'unavailable'}</span></p>
                            </div>
                            <button class="px-3 py-1.5 rounded-lg text-xs font-bold hover:opacity-80 flex items-center gap-1 transition-opacity"
                                    style="background:var(--card-border);color:var(--text-mid)"
                                    onclick="Settings.restartAA()"
                                    ${Settings._aa.restarting ? 'disabled' : ''}>
                                <span class="material-symbols-outlined text-sm ${Settings._aa.restarting ? 'animate-spin' : ''}">sync</span>
                                ${Settings._aa.restarting ? t("aa_restarting", "Restartowanie...") : t("aa_restart", "Restartuj AA")}
                            </button>
                        </div>
                    </div>
                </div>
                <button class="mt-3 px-4 py-2 rounded-lg text-xs font-bold hover:opacity-80" style="background:var(--card-border);color:var(--text-mid)" onclick="App.navigateTo('a1')">
                    \u2190 ${t("back_to_dash")}
                </button>
            </main>
        </div>`;
    }

    // A Bluetooth address as bluetoothctl prints it. Only such a value is
    // put into the inline onclick handlers below (hex digits and colons
    // cannot break out of the JavaScript string); anything else gets no
    // action buttons at all.
    const BT_MAC_RE = /^[0-9A-Fa-f]{2}(:[0-9A-Fa-f]{2}){5}$/;

    function _renderDevice(d, type, t) {
        // Device names come over the air: during a scan ANY device in range
        // picks its own name (no pairing needed) — escaped like all phone data.
        const esc = Settings._esc;
        const mac = typeof d.address === "string" && BT_MAC_RE.test(d.address) ? d.address : "";
        const isConnected = d.connected === true;
        const isPaired = type === "paired";
        const statusBadge = isConnected
            ? `<span class="text-[7px] font-bold px-1.5 py-0.5 rounded bg-green-600/20 text-green-400">${t("bt_connected","Connected")}</span>`
            : isPaired
                ? `<span class="text-[7px] font-bold px-1.5 py-0.5 rounded" style="background:var(--card-border);color:var(--text-dim)">${t("bt_paired","Paired")}</span>`
                : `<span class="text-[7px] font-bold px-1.5 py-0.5 rounded bg-blue-600/20 text-blue-400">New</span>`;

        let actions = "";
        if (!mac) {
            actions = "";
        } else if (type === "discovered") {
            actions = `<button class="text-[8px] font-bold px-2 py-1 rounded bg-blue-600 text-white hover:bg-blue-500" onclick="Settings.btPair('${mac}')">${t("bt_pair","Pair")}</button>`;
        } else if (isConnected) {
            actions = `<button class="text-[8px] font-bold px-2 py-1 rounded bg-red-600/20 text-red-400 hover:bg-red-600/30" onclick="Settings.btDisconnect()">${t("bt_disconnect","Disconnect")}</button>`;
        } else {
            actions = `<div class="flex gap-1">
                <button class="text-[8px] font-bold px-2 py-1 rounded bg-green-700 text-white hover:bg-green-600" onclick="Settings.btConnect('${mac}')">${t("bt_connect","Connect")}</button>
                <button class="text-[8px] font-bold px-1.5 py-1 rounded hover:opacity-80" style="background:var(--card-border);color:var(--text-mid)" onclick="Settings.btRemove('${mac}')" title="${t("bt_remove","Remove")}">
                    <span class="material-symbols-outlined" style="font-size:12px;">delete</span>
                </button>
            </div>`;
        }

        return `<div class="flex justify-between items-center p-2 rounded-lg ${isConnected ? 'border border-green-600/30' : ''}" style="background:color-mix(in srgb, var(--card-bg) 80%, var(--card-border))">
            <div class="flex items-center gap-2">
                <span class="material-symbols-outlined ${isConnected ? 'text-green-500' : ''}" style="font-size:16px;${isConnected ? '' : 'color:var(--text-dim)'}">bluetooth</span>
                <div>
                    <div class="flex items-center gap-2">
                        <p class="text-xs font-bold">${esc(d.name || d.address)}</p>
                        ${statusBadge}
                    </div>
                    <p class="text-[9px]" style="color:var(--text-dim)">${esc(d.address)}</p>
                </div>
            </div>
            ${actions}
        </div>`;
    }

    function _actionLabel(action) {
        const labels = {
            volume_up: "Volume Up", volume_down: "Volume Down", mute: "Mute",
            menu_up: "Menu Up", menu_down: "Menu Down", next_track: "Next Track",
            prev_track: "Prev Track", play_pause: "Play/Pause",
            phone_pickup: "Phone Pickup", phone_hangup: "Phone Hangup",
            bcm_power_toggle: "Power Toggle", voice_aa_trigger: "AA Voice",
            navigate_aa: "Open AA", home: "Home", back: "Back",
            source_cycle: "Source Cycle", brightness_cycle: "Brightness",
            crash_cancel: App.t("swc_crash_cancel", "Anuluj SMS po stłuczce"),
        };
        return labels[action] || action;
    }

    function _renderSwcTable() {
        const m = Settings._swcMapping;
        if (!m) {
            Settings.swcLoad().then(() => App.navigateTo("settings"));
            return '<p class="text-[10px]" style="color:var(--text-dim)">Loading...</p>';
        }
        const actions = Object.keys(m);
        const learning = Settings._swcLearning;
        let html = '<table class="w-full text-[10px]">';
        html += '<thead><tr class="uppercase tracking-wider" style="color:var(--text-dim)">';
        html += '<th class="text-left py-1 font-bold">Action</th>';
        html += '<th class="text-left py-1 font-bold">Pod 1</th>';
        html += '<th class="text-left py-1 font-bold">Pod 2</th></tr></thead>';
        html += '<tbody>';
        for (const action of actions) {
            const btns = m[action] || ["", ""];
            html += `<tr style="border-top:1px solid var(--card-border)">`;
            html += `<td class="py-1.5 font-bold" style="color:var(--text-mid)">${_actionLabel(action)}</td>`;
            for (let pod = 0; pod < 2; pod++) {
                const cur = btns[pod] || "";
                const isLearning = learning && learning.action === action && learning.pod === pod;
                if (isLearning) {
                    html += `<td class="py-1.5">
                        <span class="inline-flex items-center gap-1">
                            <span class="animate-pulse font-bold" style="color:var(--color-primary)">Press button...</span>
                            <button class="text-[9px] px-1.5 py-0.5 rounded font-bold hover:opacity-80"
                                    style="background:var(--card-border);color:var(--text-dim)"
                                    onclick="Settings.swcLearnCancel()">Cancel</button>
                        </span>
                    </td>`;
                } else {
                    html += `<td class="py-1.5">
                        <span class="inline-flex items-center gap-1">
                            <span class="font-bold" style="color:var(--color-on-surface)">${cur || "---"}</span>
                            <button class="text-[9px] px-1.5 py-0.5 rounded font-bold hover:opacity-80"
                                    style="background:var(--color-primary);color:#fff"
                                    onclick="Settings.swcLearnStart('${action}',${pod})">
                                <span class="material-symbols-outlined" style="font-size:11px;vertical-align:-1px">tune</span>
                            </button>
                        </span>
                    </td>`;
                }
            }
            html += '</tr>';
        }
        html += '</tbody></table>';
        return html;
    }

    function _attrEsc(s) {
        // Minimal HTML attribute escape — SSID/password come from the
        // user but are re-emitted as `value="..."` attributes via a
        // template literal, so unescaped quotes/ampersands would break
        // out of the attribute.
        return String(s == null ? "" : s)
            .replace(/&/g, "&amp;")
            .replace(/"/g, "&quot;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;");
    }

    function _toggle(on, onclick) {
        // Tailwind-styled iOS-like switch. The `data-on` attribute is
        // just a hook for tests / accessibility — the visual state is
        // driven by class swaps and the click handler is wired so the
        // toggle actually does something on baremetal.
        const wrap = on
            ? "background:#16a34a"   // green-600
            : "background:var(--card-border)";
        const knob = on ? "translate-x-4" : "translate-x-0";
        return `<button type="button" data-on="${on ? '1' : '0'}"
            class="relative inline-flex w-10 h-6 rounded-full p-0.5 transition-colors"
            style="${wrap}"
            onclick="${onclick}">
            <span class="block w-5 h-5 bg-white rounded-full transform transition-transform ${knob}"></span>
        </button>`;
    }

    function _themeBtn(v, label, current) {
        const isActive = v === current;
        const style = isActive
            ? `background:var(--color-primary);color:#fff;border:1px solid var(--color-primary)`
            : `background:var(--card-bg);color:var(--text-mid);border:1px solid var(--card-border)`;
        return `<button class="px-3 py-1.5 rounded-lg text-xs font-bold hover:opacity-80" style="${style}" onclick="App.setTheme('${v}')">${label}</button>`;
    }
    function _langBtn(v, label, current) {
        const isActive = v === current;
        const style = isActive
            ? `background:var(--color-primary);color:#fff`
            : `background:var(--card-border);color:var(--text-dim)`;
        return `<button class="px-2 py-1 rounded text-xs font-bold hover:opacity-80" style="${style}" onclick="App.setLang('${v}')">${label}</button>`;
    }
    function _unitBtn(v, label, current, type) {
        const isActive = v === current;
        const style = isActive
            ? `background:var(--color-primary);color:#fff`
            : `background:var(--card-border);color:var(--text-dim)`;
        return `<button class="px-2 py-1 rounded text-xs font-bold hover:opacity-80" style="${style}" onclick="Settings.setUnit('${type}','${v}')">${label}</button>`;
    }

    return { render, update };
})());
