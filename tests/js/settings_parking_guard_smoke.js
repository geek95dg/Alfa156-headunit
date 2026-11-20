// Settings screen: the "Postój" row (data.parking_guard from the dashboard
// payload = web_viewer._parking_guard_summary of park.state,
// src/safety/parking_guard.py), for tests/test_frontend_gestures.py. Loads
// the real screens/settings.js in a node vm with DOM stubs; plain node +
// assert, no packages. Exits non-zero on failure, prints "ok" on success.
"use strict";
const assert = require("assert");
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const WEB = path.join(__dirname, "..", "..", "src", "dashboard", "web", "js");

let screen = null;
const fetches = [];
let fetchAnswer = { ok: true, status: 200, body: { ok: true } };
const codeInput = { value: "" };
const parkMsg = { textContent: "" };
const listeners = {};
const slots = { "[data-parking-guard-slot]": { innerHTML: "<untouched>" },
                "[data-car-phone-agent-slot]": { innerHTML: "<untouched>" },
                "[data-car-phone-slot]": { innerHTML: "<untouched>" },
                "[data-tether-slot]": { innerHTML: "<untouched>" },
                "[data-gps-slot]": { innerHTML: "<untouched>" },
                "[data-park-code]": codeInput,
                "[data-park-msg]": parkMsg };
const ctx = {
    console, setTimeout, clearTimeout, Promise, JSON, Math, Date, Object, String, Number,
    isFinite,
    setInterval: () => 0, clearInterval() {},
    fetch: async (url, opts) => {
        fetches.push([url, opts && opts.method, opts && opts.body]);
        const a = fetchAnswer;
        return { ok: a.ok, status: a.status, json: async () => a.body };
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
        querySelectorAll: () => [],
        addEventListener: (type, fn) => { (listeners[type] = listeners[type] || []).push(fn); },
        activeElement: null,
    },
};
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(path.join(WEB, "screens", "settings.js"), "utf8"), ctx,
                { filename: "settings.js" });
vm.runInContext("this.__Settings = Settings;", ctx);
const Settings = ctx.__Settings;
const t = (k, d) => d;

const SINCE = new Date(2026, 10, 19, 3, 12, 0).getTime() / 1000;
const ARMED = {
    state: "armed", since: SINCE, by: "power", arm_at: null, last_event: null,
    battery_pct: 64, power: "unplugged", log_only: false, light: false, sensor: "ok",
    totp_ready: true, numbers_n: 2, home_set: false, alarms_today: 0,
    owner_connected: false, owner_known: true, disarm_pending: false, error: "", cmd: null,
};
const row = (over) => Settings.parkingGuardRowHtml(Object.assign({}, ARMED, over || {}), t);

// ── the row on its own ───────────────────────────────────────────────────
let html = row();
assert.ok(html.includes("Postój") && html.includes(">local_parking<"), html);
assert.ok(html.includes("uzbrojony") && html.includes("od 19.11 03:12") && html.includes("bateria 64%"), html);
assert.ok(html.includes('data-park-state="armed"'), html);
assert.ok(!/class="[^"]*\b(flex|gap-|px-|py-|text-\[)/.test(html.replace(/material-symbols-outlined/g, "")),
          "only inline styles: " + html);
// armed, owner not connected: code field + Rozbrój (data-* only, no inline handler)
assert.ok(/<input data-park-code type="tel" inputmode="numeric" maxlength="6"/.test(html), html);
assert.ok(html.includes("data-park-disarm") && html.includes(">Rozbrój<"), html);
assert.ok(!html.includes("onclick"), "delegated listeners only: " + html);
assert.ok(!html.includes("data-park-arm"), html);
// owner connected: Rozbrój without a code
html = row({ owner_connected: true });
assert.ok(html.includes("data-park-disarm") && !html.includes("data-park-code"), html);
// every state has its label; Uzbrój only when disarmed, Rozbrój when armed-ish
const LABELS = {
    unknown: "brak danych z telefonu", off: "wyłączony w telefonie", disarmed: "rozbrojony",
    arming: "uzbrajanie", armed: "uzbrojony", alarm: "ALARM", log_only: "tylko log, bez SMS",
};
for (const [state, label] of Object.entries(LABELS)) {
    html = row({ state });
    assert.ok(html.includes(label), state + ": " + html);
    assert.strictEqual(html.includes("data-park-arm"), state === "disarmed", state);
    assert.strictEqual(html.includes("data-park-disarm"),
                       ["arming", "armed", "alarm", "log_only"].indexOf(state) >= 0, state);
}
assert.ok(row({ state: "alarm" }).includes("#dc2626"));
// arming: when
html = row({ state: "arming", arm_at: SINCE + 120 });
assert.ok(html.includes("uzbroi się o 03:14"), html);
// the last event, logged-only marked
html = row({ last_event: { kind: "tilt", ts: SINCE + 3600, value: 1.2, logged_only: true } });
assert.ok(html.includes("Ostatnie zdarzenie: przechył 19.11 04:12 (tylko log)"), html);
html = row({ last_event: { kind: "power", ts: SINCE, logged_only: false } });
assert.ok(html.includes("zasilanie bez telefonu właściciela") && !html.includes("tylko log"), html);
assert.ok(!row({ last_event: { kind: "<img>", ts: SINCE } }).includes("Ostatnie zdarzenie"));
// what is missing — what to do
assert.ok(row({ totp_ready: false }).includes("--park-setup"));
assert.ok(row({ numbers_n: 0 }).includes("parking_guard.numbers"));
assert.ok(row({ owner_known: false }).includes("parking_guard.owner_macs"));
assert.ok(row({ state: "unknown", error: "agent_outdated" }).includes("≥ 1.2.0"));
assert.ok(row({ state: "unknown", error: "no_agent" }).includes("Agent w telefonie"));
assert.ok(!row({ error: "<b>raw</b>" }).includes("<b>"));
// the outcome of the last command (from the module)
assert.ok(row({ cmd: { action: "disarm", ok: false, error: "bad_code", ts: SINCE } }).includes("zły kod"));
assert.ok(row({ cmd: { action: "disarm", ok: false, error: "code_used", ts: SINCE } }).includes("już użyty"));
assert.ok(row({ state: "disarmed", cmd: { action: "disarm", ok: true, error: "", ts: SINCE } }).includes("rozbrojono"));
assert.ok(row({ cmd: { action: "x", ok: true } }).indexOf("rozbrojono") < 0);
// type checks and escaping
html = row({ battery_pct: "64", since: "x", light: "yes" });
assert.ok(!html.includes("bateria") && !html.includes(" od ") && !html.includes("oszczędzanie"), html);
html = Settings.parkingGuardRowHtml({ state: "<img src=x onerror=alert(1)>" }, t);
assert.ok(!html.includes("<img") && html.includes('data-park-state="unknown"'), html);
// entry window: motion seen, the alarm goes out at this time without the owner's proof
html = row({ entry_until: SINCE + 3600 });
assert.ok(html.includes("wykryto ruch — alarm bez rozbrojenia o 04:12"), html);
assert.ok(!row({ state: "disarmed", entry_until: SINCE }).includes("wykryto ruch"));
// no payload = module not running: no row
assert.strictEqual(Settings.parkingGuardRowHtml(undefined, t), "");
assert.strictEqual(Settings.parkingGuardRowHtml(null), "");
assert.strictEqual(Settings.parkingGuardRowHtml("armed", t), "");

// ── the whole screen and update() ────────────────────────────────────────
assert.ok(screen && typeof screen.render === "function");
const container = { innerHTML: "" };
// The listener comes with the first render even WITHOUT a payload: the row
// may first appear through update() when the module publishes later.
screen.render(container, "modern", { aa_status: "running" });
assert.ok(listeners.click && listeners.click.length === 1, "one delegated listener");
screen.render(container, "modern", { parking_guard: ARMED });
assert.ok(container.innerHTML.includes('data-park-state="armed"'), "row rendered");
assert.strictEqual(listeners.click.length, 1, "still one");
screen.render(container, "modern", { parking_guard: ARMED });
assert.strictEqual(listeners.click.length, 1, "installed once");
screen.render(container, "modern", { aa_status: "running" });
assert.ok(/data-parking-guard-slot style="display:contents"><\/div>/.test(container.innerHTML));
const slot = slots["[data-parking-guard-slot]"];
screen.render(container, "modern", { parking_guard: ARMED });
screen.update({ parking_guard: ARMED });
assert.strictEqual(slot.innerHTML, "<untouched>", "same payload: nothing redrawn");
screen.update({ parking_guard: Object.assign({}, ARMED, { state: "alarm" }) });
assert.ok(slot.innerHTML.includes('data-park-state="alarm"'), slot.innerHTML);
assert.strictEqual(slots["[data-car-phone-agent-slot]"].innerHTML, "<untouched>");
// not redrawn while the driver types the code (the field has focus)
const typed = { value: "1234" };
const fresh = { value: "" };                       // the field after a redraw
slot.querySelector = (sel) => (sel !== "[data-park-code]" ? null
    : slot.innerHTML === "<typing>" ? typed : fresh);
slot.innerHTML = "<typing>";
ctx.document.activeElement = typed;
screen.update({ parking_guard: Object.assign({}, ARMED, { battery_pct: 63 }) });
assert.strictEqual(slot.innerHTML, "<typing>");
// a half-typed code in an UNFOCUSED field does not freeze the row on a
// stale state (e.g. still ALARM after the phone disarmed); the digits are
// carried over into the redrawn field
ctx.document.activeElement = null;
screen.update({ parking_guard: Object.assign({}, ARMED, { state: "disarmed", by: "owner_bt" }) });
assert.ok(slot.innerHTML.includes('data-park-state="disarmed"'), slot.innerHTML);
assert.strictEqual(fresh.value, "1234", "typed digits survive the redraw");
slot.innerHTML = "<typing>";
typed.value = "";
fresh.value = "";
screen.update({ parking_guard: Object.assign({}, ARMED, { battery_pct: 63 }) });
assert.ok(slot.innerHTML.includes("bateria 63%"), slot.innerHTML);
assert.strictEqual(fresh.value, "", "nothing typed: nothing carried over");
delete slot.querySelector;
screen.update(undefined);                                    // never throws

// ── the buttons: delegated click, the code only in the body ──────────────
(async () => {
    const click = (attr) => {
        const el = { hasAttribute: (a) => a === attr, closest: () => el };
        listeners.click.forEach((fn) => fn({ target: el }));
    };
    const posts = () => fetches.filter(([url]) => url.startsWith("/api/parking_guard/"));
    codeInput.value = "12 34";                              // not 6 digits: nothing sent
    click("data-park-disarm");
    await new Promise((r) => setTimeout(r, 0));
    assert.strictEqual(posts().length, 0);
    assert.ok(parkMsg.textContent.includes("6 cyfr"), parkMsg.textContent);
    codeInput.value = "246 810";
    click("data-park-disarm");
    await new Promise((r) => setTimeout(r, 0));
    assert.deepStrictEqual(posts()[0], ["/api/parking_guard/disarm", "POST", '{"code":"246810"}']);
    assert.strictEqual(codeInput.value, "", "the code is not kept in the page");
    click("data-park-disarm");                              // double tap swallowed
    await new Promise((r) => setTimeout(r, 0));
    assert.strictEqual(posts().length, 1);
    Settings._park.sentAt = 0;
    fetchAnswer = { ok: false, status: 409, body: { ok: false, error: "owner_required" } };
    slots["[data-park-code]"] = null;                       // owner connected: no field
    click("data-park-disarm");
    await new Promise((r) => setTimeout(r, 5));
    assert.deepStrictEqual(posts()[1], ["/api/parking_guard/disarm", "POST", "{}"]);
    assert.ok(parkMsg.textContent.includes("połącz telefon właściciela"), parkMsg.textContent);
    Settings._park.sentAt = 0;
    fetchAnswer = { ok: true, status: 200, body: { ok: true } };
    click("data-park-arm");
    await new Promise((r) => setTimeout(r, 5));
    assert.deepStrictEqual(posts()[2], ["/api/parking_guard/arm", "POST", "{}"]);
    assert.ok(parkMsg.textContent.includes("przekazano"), parkMsg.textContent);
    Settings._park.sentAt = 0;
    fetchAnswer = { ok: false, status: 403, body: { ok: false, error: "forbidden" } };
    click("data-park-arm");
    await new Promise((r) => setTimeout(r, 5));
    assert.ok(parkMsg.textContent.includes("Tylko z ekranu w aucie"), parkMsg.textContent);
    console.log("ok");
})().catch((e) => { console.error(e); process.exit(1); });
