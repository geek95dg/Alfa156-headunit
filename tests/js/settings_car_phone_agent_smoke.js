// Settings screen: the "Agent w telefonie" row (data.car_phone_agent from the
// dashboard payload = web_viewer._car_phone_agent_summary of
// net.car_phone_agent, src/network/car_phone_agent.py), for
// tests/test_frontend_gestures.py. Loads the real screens/settings.js in a
// node vm with DOM stubs; plain node + assert, no packages. Exits non-zero on
// failure, prints "ok" on success.
"use strict";
const assert = require("assert");
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const WEB = path.join(__dirname, "..", "..", "src", "dashboard", "web", "js");

let screen = null;
const fetches = [];
const codeInput = { value: "" };
const pairMsg = { textContent: "" };
const slots = { "[data-car-phone-slot]": { innerHTML: "<untouched>" },
                "[data-car-phone-agent-slot]": { innerHTML: "<untouched>" },
                "[data-tether-slot]": { innerHTML: "<untouched>" },
                "[data-gps-slot]": { innerHTML: "<untouched>" },
                "[data-car-phone-agent-code]": codeInput,
                "[data-car-phone-agent-msg]": pairMsg };
const ctx = {
    console, setTimeout, clearTimeout, Promise, JSON, Math, Date, Object, String, Number,
    isFinite,
    setInterval: () => 0, clearInterval() {},
    fetch: async (url, opts) => {
        fetches.push([url, opts && opts.method, opts && opts.body]);
        return { ok: true, json: async () => ({}) };
    },
    App: {
        registerScreen(name, impl) { if (name === "settings") screen = impl; },
        getConfig: () => ({ theme: "modern", language: "pl", speed_unit: "km/h", temp_unit: "C" }),
        t: (key, fallback) => fallback || key,
        navigateTo() {},
    },
    AppBar: { render: () => "" },
    document: {
        getElementById: () => null, createElement: () => ({ style: {} }), body: {},
        querySelector: (sel) => slots[sel] || null,
        activeElement: null,
    },
};
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(path.join(WEB, "screens", "settings.js"), "utf8"), ctx,
                { filename: "settings.js" });
vm.runInContext("this.__Settings = Settings;", ctx);
const Settings = ctx.__Settings;
const t = (k, d) => d;

// 14:03 local time of the node process (the row formats with the kiosk's clock).
const LAST = new Date(2026, 10, 12, 14, 3, 0).getTime() / 1000;
const OK = {
    state: "ok", paired: true, pairing: false, version: "1.0.0", sim_ready: true,
    last_ok_ts: LAST, last_sent_ts: null, reason: "", error: "",
};

// ── the row on its own ───────────────────────────────────────────────────
let html = Settings.carPhoneAgentRowHtml(OK, t);
assert.ok(html.includes("Agent w telefonie") && html.includes(">sms<"), html);
assert.ok(html.includes("działa"), html);
assert.ok(html.includes("v1.0.0 · SIM · kontakt 14:03"), html);
assert.ok(html.includes('data-car-phone-agent-state="ok"'), html);
assert.ok(!html.includes("data-car-phone-agent-pair"), "no pairing button while paired");
assert.ok(!html.includes("data-car-phone-agent-hint"), "no hint while fine: " + html);
assert.ok(!/class="[^"]*\b(flex|gap-|px-|py-|text-\[)/.test(html.replace(/material-symbols-outlined/g, "")),
          "only inline styles in the new row: " + html);

// Every state has a label; the pairing form ONLY while unpaired (or an
// answering agent that does not know our secret — below).
const LABELS = {
    disabled: "wyłączony", no_secret: "brak sekretu", waiting_forward: "czeka na telefon",
    unpaired: "niesparowany", error: "błąd — ponowię", bad_signature: "obca odpowiedź",
};
for (const [state, label] of Object.entries(LABELS)) {
    html = Settings.carPhoneAgentRowHtml(Object.assign({}, OK, { state, paired: null }), t);
    assert.ok(html.includes(label), state + ": " + html);
    assert.strictEqual(html.includes("data-car-phone-agent-pair"), state === "unpaired",
                       state + ": " + html);
    assert.strictEqual(html.includes("data-car-phone-agent-code"), state === "unpaired");
    assert.strictEqual(html.includes('onclick="Settings.carPhoneAgentPair(this)"'), state === "unpaired");
}
// The form: a numeric code field, "Sparuj"; no data in the inline handler.
html = Settings.carPhoneAgentRowHtml({ state: "unpaired" }, t);
assert.ok(/<input data-car-phone-agent-code type="tel" inputmode="numeric" maxlength="10"/.test(html), html);
assert.ok(html.includes('data-confirm="0"') && html.includes(">Sparuj<"), html);
// After a proven pairing: "Sparuj mimo to" with the confirmation flag.
html = Settings.carPhoneAgentRowHtml({ state: "error", reason: "agent_reset", needs_confirm: true }, t);
assert.ok(html.includes('data-confirm="1"') && html.includes("Sparuj mimo to"), html);
assert.ok(html.includes("inna aplikacja"), html);
// An answering agent with another secret / a wrong code: the form stays.
for (const reason of ["secret_mismatch", "agent_reset", "pairing_closed", "bad_code"]) {
    assert.ok(Settings.carPhoneAgentRowHtml({ state: "error", reason }, t).includes("data-car-phone-agent-code"), reason);
}
for (const reason of ["clock_skew", "no_answer", "http", "storage"]) {
    assert.ok(!Settings.carPhoneAgentRowHtml({ state: "error", reason }, t).includes("data-car-phone-agent-code"), reason);
}
assert.ok(!Settings.carPhoneAgentRowHtml({ state: "ok", reason: "config_refused" }, t).includes("data-car-phone-agent-code"));

// What to do: by reason first, then by state — never the raw error text.
const HINTS = {
    pairing_closed: "--pair", bad_code: "zły kod", secret_mismatch: "inny sekret",
    agent_reset: "porcie 8765", clock_skew: "zegar telefonu", no_answer: "bcm_agent.py działa",
};
for (const [reason, text] of Object.entries(HINTS)) {
    html = Settings.carPhoneAgentRowHtml({ state: "error", reason, error: "raw socket text" }, t);
    assert.ok(html.includes(text), reason + ": " + html);
    assert.ok(!html.includes("raw socket text"), html);
}
// The agent works, but its config lags: said so even with state ok.
assert.ok(Settings.carPhoneAgentRowHtml(Object.assign({}, OK, { reason: "config_pending" }), t).includes("starą konfigurację"));
assert.ok(Settings.carPhoneAgentRowHtml(Object.assign({}, OK, { reason: "config_refused" }), t).includes("odrzucił konfigurację"));
assert.ok(Settings.carPhoneAgentRowHtml({ state: "unpaired" }, t).includes("bcm_agent.py --pair"));
assert.ok(Settings.carPhoneAgentRowHtml({ state: "no_secret" }, t).includes("BCM_CAR_PHONE_AGENT_SECRET"));
assert.ok(Settings.carPhoneAgentRowHtml({ state: "bad_signature" }, t).includes("odpowiada coś innego"));
// an error without a known reason: label only, no made-up hint
assert.ok(!Settings.carPhoneAgentRowHtml({ state: "error", reason: "http" }, t)
    .includes("data-car-phone-agent-hint"));
assert.ok(!Settings.carPhoneAgentRowHtml({ state: "error", reason: "<b>x</b>" }, t).includes("<b>"));

// Facts are type-checked: wrong types draw nothing.
html = Settings.carPhoneAgentRowHtml(Object.assign({}, OK, {
    version: "1.0<img src=x>", sim_ready: "true", last_ok_ts: "1763000000" }), t);
assert.ok(!html.includes("v1.0") && !html.includes("SIM") && !html.includes("kontakt"), html);
assert.ok(!html.includes("<img"), html);
html = Settings.carPhoneAgentRowHtml(Object.assign({}, OK, { sim_ready: false }), t);
assert.ok(html.includes("brak SIM"), html);

// No payload = module not running (production): no row at all.
assert.strictEqual(Settings.carPhoneAgentRowHtml(undefined, t), "");
assert.strictEqual(Settings.carPhoneAgentRowHtml(null), "");
assert.strictEqual(Settings.carPhoneAgentRowHtml("ok", t), "");

// Everything is escaped.
html = Settings.carPhoneAgentRowHtml({ state: "<img src=x onerror=alert(1)>" }, t);
assert.ok(!html.includes("<img"), html);
assert.ok(html.includes("&lt;img src=x onerror=alert(1)&gt;"), html);

// ── the whole screen shows it ────────────────────────────────────────────
assert.ok(screen && typeof screen.render === "function");
const container = { innerHTML: "" };
screen.render(container, "modern", { aa_status: "connected", car_phone_agent: OK });
assert.ok(container.innerHTML.includes('data-car-phone-agent-state="ok"'), "row rendered");
assert.ok(container.innerHTML.includes("data-car-phone-agent-slot"));
for (const data of [{ aa_status: "running" }, { aa_status: "running", car_phone_agent: null }]) {
    screen.render(container, "modern", data);
    assert.ok(!container.innerHTML.includes("data-car-phone-agent-state"), container.innerHTML);
    assert.ok(/data-car-phone-agent-slot style="display:contents"><\/div>/.test(container.innerHTML));
}

// ── update(): only the row, only on change ──────────────────────────────
const slot = slots["[data-car-phone-agent-slot]"];
screen.render(container, "modern", { car_phone_agent: { state: "unpaired" } });
const rendered = container.innerHTML;
screen.update({ car_phone_agent: { state: "unpaired" } });
assert.strictEqual(slot.innerHTML, "<untouched>", "same payload: nothing redrawn");
screen.update({ car_phone_agent: OK });
assert.ok(slot.innerHTML.includes('data-car-phone-agent-state="ok"'), slot.innerHTML);
assert.strictEqual(container.innerHTML, rendered, "the screen itself is not re-rendered");
assert.strictEqual(slots["[data-car-phone-slot]"].innerHTML, "<untouched>", "other rows untouched");
screen.update({ car_phone_agent: null });
assert.strictEqual(slot.innerHTML, "");
screen.update(undefined);                                   // never throws

// While the driver types the code the row is not redrawn (the OSK writes
// into that very input); it catches up once the field is empty again.
const typed = { value: "48151" };
slot.querySelector = (sel) => (sel === "[data-car-phone-agent-code]" ? typed : null);
slot.innerHTML = "<typing>";
screen.update({ car_phone_agent: { state: "unpaired", reason: "bad_code" } });
assert.strictEqual(slot.innerHTML, "<typing>", "not redrawn while typing");
typed.value = "";
screen.update({ car_phone_agent: { state: "unpaired", reason: "bad_code" } });
assert.ok(slot.innerHTML.includes("zły kod"), slot.innerHTML);
delete slot.querySelector;

// ── "Sparuj": the code + confirmation only, double taps swallowed ───────
(async () => {
    const pairs = () => fetches.filter(([url]) => url === "/api/car_phone_agent/pair");
    codeInput.value = "12345";                              // too short: nothing sent
    await Settings.carPhoneAgentPair({ dataset: { confirm: "0" } });
    assert.deepStrictEqual(pairs(), []);
    assert.ok(pairMsg.textContent.includes("10 cyfr"), pairMsg.textContent);
    codeInput.value = "4815162342";
    await Settings.carPhoneAgentPair({ dataset: { confirm: "1" } });
    await Settings.carPhoneAgentPair({ dataset: { confirm: "1" } });
    assert.deepStrictEqual(pairs(), [["/api/car_phone_agent/pair", "POST",
                                      JSON.stringify({ code: "4815162342", confirm: true })]]);
    assert.strictEqual(codeInput.value, "", "cleared after a sent request");
    console.log("ok");
})().catch((e) => { console.error(e); process.exit(1); });
