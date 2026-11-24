// Settings screen: the "Czujniki telefonu" row (data.phone_sensors,
// src/sensors/phone_sensors.py via web_viewer._phone_sensors_summary) and
// its "Test" button, for tests/test_frontend_gestures.py. Loads the real
// settings.js in a node vm with DOM stubs; plain node + assert.
// Exits non-zero on failure, prints "ok" on success.
"use strict";
const assert = require("assert");
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const WEB = path.join(__dirname, "..", "..", "src", "dashboard", "web", "js");

const screens = {};
const fetches = [];
const slots = { "[data-phone-sensors-slot]": { innerHTML: "<untouched>" } };
let fetchReply = { status: 202, body: { ok: true, started: true, duration_s: 10 } };
const ctx = {
    console, setTimeout, clearTimeout, Promise, JSON, Math, Date, Object, String, Number,
    Array, isFinite,
    setInterval: () => 0, clearInterval() {},
    localStorage: { getItem: () => null, setItem() {} },
    fetch: async (url, opts) => {
        fetches.push([url, opts && opts.method]);
        return { ok: fetchReply.status < 300, status: fetchReply.status,
                 json: async () => fetchReply.body };
    },
    App: {
        registerScreen(name, impl) { screens[name] = impl; },
        getConfig: () => ({ theme: "modern", language: "pl", speed_unit: "km/h", temp_unit: "C" }),
        getTheme: () => "modern",
        t: (key, fallback) => fallback || key,
        navigateTo() {},
    },
    AppBar: { render: () => "" },
    NavBar: { render: () => "" },
    DataStore: { getAll: () => ({}) },
    document: {
        getElementById: () => null, body: {},
        createElement: () => ({ style: {}, querySelector: () => null, addEventListener() {},
                                remove() {} }),
        querySelector: (sel) => slots[sel] || null,
        querySelectorAll: () => [],
    },
};
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(path.join(WEB, "screens", "settings.js"), "utf8"), ctx,
                { filename: "settings.js" });
vm.runInContext("this.__Settings = Settings;", ctx);
const Settings = ctx.__Settings;
const t = (k, d) => d;

const PS = {
    state: "streaming", mode: "combined", error: "", rate_hz: 99.6, calib_ok: true,
    types: { accel: { subscribed: true, active: true, hz: 99.6 },
             gyro: { subscribed: true, active: true, hz: 98.2 },
             light: { subscribed: true, active: true, hz: 0.4 } },
    lux: 123.4, lux_age_s: 75,
    close: { code: null, reason: "", channel: "" },
    test: { running: false, result: null },
    forward: { ok: true, error: "" },
};

// ── the row ──────────────────────────────────────────────────────────────
let html = Settings.sensorsRowHtml(PS, t);
assert.ok(html.includes("Czujniki telefonu") && html.includes(">działa<"), html);
assert.ok(html.includes("akcelerometr 100 Hz") && html.includes("żyroskop 98 Hz"), html);
assert.ok(html.includes("światło: 123 lx (1 min temu)"), html);
assert.ok(html.includes("data-sensors-test") && html.includes(">Test<"), html);
assert.ok(!/class="[^"]*\b(flex|gap-|px-|py-|text-\[)/.test(html.replace(/material-symbols-outlined/g, "")),
          "only inline styles: " + html);
// Light-only (accelerometer stream failed, light still works): amber, lux shown.
html = Settings.sensorsRowHtml(Object.assign({}, PS, {
    state: "stale", mode: "split",
    types: { accel: { subscribed: false, active: false, hz: 0 },
             gyro: { subscribed: false, active: false, hz: 0 },
             light: { subscribed: true, active: true, hz: 0.2 } },
    lux_age_s: 4 }), t);
assert.ok(html.includes("brak akcelerometru") && html.includes("akcelerometr —"), html);
assert.ok(html.includes("światło: 123 lx (4 s temu)"), html);
assert.ok(html.includes("osobne połączenie dla każdego czujnika"), html);
// No light reading yet.
html = Settings.sensorsRowHtml(Object.assign({}, PS, { lux: null, lux_age_s: null }), t);
assert.ok(html.includes("światło: brak odczytu"), html);
// Forward missing / down.
html = Settings.sensorsRowHtml(Object.assign({}, PS, { state: "waiting_forward",
                                                       forward: { ok: false, error: "missing" } }), t);
assert.ok(html.includes("czeka na telefon") && html.includes("włącz modules.phone_sensors"), html);
html = Settings.sensorsRowHtml(Object.assign({}, PS, { state: "waiting_forward",
                                                       forward: { ok: false, error: "adb: x" } }), t);
assert.ok(html.includes("forward „sensors” nie działa"), html);
html = Settings.sensorsRowHtml(Object.assign({}, PS, { state: "waiting_forward", forward: null }), t);
assert.ok(html.includes("włącz moduł „Telefon w aucie”"), html);
// Running test: button disabled, message.
html = Settings.sensorsRowHtml(Object.assign({}, PS, { test: { running: true, result: null } }), t);
assert.ok(html.includes("disabled") && html.includes("testuję… (10 s)"), html);
// Verdicts with what to do.
const result = (verdict, hint, extra) => Object.assign({}, PS, { test: { running: false, result: Object.assign({
    ts: 1.7e9, verdict, hint, frames: { accel: 1000, gyro: 990, light: 0 },
    hz: { accel: 100, gyro: 99, light: 0 }, lux_min: null, lux_max: null, duration_s: 10 }, extra || {}) } });
html = Settings.sensorsRowHtml(result("no_light", "light"), t);
assert.ok(html.includes('data-sensors-verdict="no_light"') && html.includes("test: brak odczytów światła"), html);
assert.ok(html.includes("zaznacz czujnik światła") && html.includes("pracę w tle"), html);
assert.ok(html.includes("ramki w 10 s: akcelerometr 1000, żyroskop 990, światło 0"), html);
html = Settings.sensorsRowHtml(result("ok", "", { frames: { accel: 1000, gyro: 0, light: 12 },
                                                  lux_min: 80, lux_max: 140.6 }), t);
assert.ok(html.includes("test: wszystko działa") && html.includes("światło 80–141 lx"), html);
assert.ok(!html.includes("data-sensors-hint"), html);
// Steady light (on-change sensor, no frame in 10 s): ok with the last reading.
html = Settings.sensorsRowHtml(result("ok", "", { light_steady: true, lux: 321.4, lux_age_s: 38.2 }), t);
assert.ok(html.includes("test: wszystko działa") && html.includes("światło stałe — ostatni odczyt 321 lx, 38 s temu"), html);
// Light refused for good: the row says so, the verdict hint too.
html = Settings.sensorsRowHtml(Object.assign(result("no_light", "light_refused"), {
    types: Object.assign({}, PS.types, { light: { subscribed: false, active: false, hz: 0, refused: true } }) }), t);
assert.ok(html.includes("BCM nie prosi o niego aż do restartu") && html.includes("sprawdź go w SensorServer"), html);
html = Settings.sensorsRowHtml(result("no_forward", "restart"), t);
assert.ok(html.includes("zrestartuj BCM"), html);
html = Settings.sensorsRowHtml(result("no_forward", "car_phone"), t);
assert.ok(html.includes("włącz moduł „Telefon w aucie”"), html);
html = Settings.sensorsRowHtml(result("low_rate", "rate"), t);
assert.ok(html.includes("10000 µs"), html);
// No payload = module off: no row.
assert.strictEqual(Settings.sensorsRowHtml(null, t), "");
assert.strictEqual(Settings.sensorsRowHtml("x", t), "");
// Garbage escaped.
html = Settings.sensorsRowHtml({ state: "<script>x</script>", error: "<img src=x>",
                                 types: { accel: { hz: "<b>", subscribed: true } },
                                 lux: "<i>", forward: { ok: false, error: "<svg>" },
                                 test: { running: false, result: { verdict: "<x>", hint: "<y>" } } }, t);
assert.ok(!html.includes("<script>") && !html.includes("<img") && !html.includes("<svg") && !html.includes("<b>"), html);
html = Settings.sensorsRowHtml(Object.assign({}, PS, { state: "error", error: '<img src=x onerror=alert(1)>' }), t);
assert.ok(!html.includes("<img") && html.includes("&lt;img"), html);

// ── the whole screen + update() ─────────────────────────────────────────
const settings = screens.settings;
const container = { innerHTML: "" };
settings.render(container, "modern", { phone_sensors: PS });
assert.ok(container.innerHTML.includes("data-phone-sensors-slot") && container.innerHTML.includes('data-phone-sensors="streaming"'),
          "row rendered");
const slot = slots["[data-phone-sensors-slot]"];
settings.update({ phone_sensors: Object.assign({}, PS, { lux_age_s: 76 }) });
assert.strictEqual(slot.innerHTML, "<untouched>", "age within the same 5 s step: not redrawn");
settings.update({ phone_sensors: Object.assign({}, PS, { lux_age_s: 81 }) });
assert.ok(slot.innerHTML.includes("Czujniki telefonu"), slot.innerHTML);

// ── "Test": one POST, the answer shown ──────────────────────────────────
(async () => {
    await Settings.sensorsTest();
    await Settings.sensorsTest();                           // double tap swallowed
    const posts = fetches.filter(([url]) => url === "/api/phone_sensors/test");
    assert.deepStrictEqual(posts, [["/api/phone_sensors/test", "POST"]]);
    assert.ok(Settings._sensorsTest.msg.startsWith("testuję"), Settings._sensorsTest.msg);
    Settings._sensorsTest.at = 0;
    fetchReply = { status: 429, body: { ok: false, error: "too many requests" } };
    await Settings.sensorsTest();
    assert.ok(Settings._sensorsTest.msg.includes("spróbuj za kilka sekund"), Settings._sensorsTest.msg);
    Settings._sensorsTest.at = 0;
    fetchReply = { status: 409, body: { ok: false, error: "disabled" } };
    await Settings.sensorsTest();
    assert.ok(Settings._sensorsTest.msg.includes("nie działa"), Settings._sensorsTest.msg);
    Settings._sensorsTest.at = 0;
    fetchReply = { status: 403, body: { ok: false, error: "forbidden" } };
    await Settings.sensorsTest();
    assert.ok(Settings._sensorsTest.msg.includes("tylko z ekranu"), Settings._sensorsTest.msg);
    console.log("ok");
})().catch((e) => { console.error(e); process.exit(1); });
