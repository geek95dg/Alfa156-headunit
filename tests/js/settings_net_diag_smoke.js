// Settings screen: the "Internet i usługi" row (data.net_diag,
// modules.net_diag), the "bez internetu" state of the car phone / phone
// internet rows, the trip plan error banner and the weather "dane
// przykładowe" line, for tests/test_frontend_gestures.py. Loads the real
// screens in a node vm with DOM stubs; plain node + assert, no packages.
// Exits non-zero on failure, prints "ok" on success.
"use strict";
const assert = require("assert");
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const WEB = path.join(__dirname, "..", "..", "src", "dashboard", "web", "js");

const screens = {};
const fetches = [];
const tripHost = { children: [], querySelector: () => null,
                   appendChild(el) { this.children.push(el); } };
const slots = { "[data-net-diag-slot]": { innerHTML: "<untouched>" },
                "#app .screen-container": tripHost };
let fetchReply = { status: 202, body: { ok: true, started: true } };
const ctx = {
    console, setTimeout, clearTimeout, Promise, JSON, Math, Date, Object, String, Number,
    Array, isFinite,
    setInterval: () => 0, clearInterval() {},
    // Travel Plan overlay on, so trip.update() draws it into tripHost.
    localStorage: { getItem: (k) => (k === "bcm.travelPlan" ? "1" : null), setItem() {} },
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
for (const f of ["settings.js", "trip.js", "weather.js"]) {
    vm.runInContext(fs.readFileSync(path.join(WEB, "screens", f), "utf8"), ctx, { filename: f });
}
vm.runInContext("this.__Settings = Settings;", ctx);
const Settings = ctx.__Settings;
const t = (k, d) => d;
const SECRET = "SeCrEt-KeY";

const ND = {
    uplink: { kind: "usb", iface: "usb0", internet: false },
    probe: { ok: false, iface: "usb0", dns_ok: false, https_ok: false, error: "dns", checked_at: 1.7e9 },
    services: {
        owm: { key_set: true, result: "http", http_code: 401, at: 1.7e9 },
        ors: { key_set: false, result: "untested", http_code: null, at: null },
        tomtom: { key_set: true, result: "ok", http_code: null, at: 1.7e9 },
    },
    test: { running: false, at: null },
};

// ── the row ──────────────────────────────────────────────────────────────
let html = Settings.netDiagRowHtml(ND, t);
assert.ok(html.includes("Internet i usługi"), html);
assert.ok(html.includes("USB z telefonu") && html.includes("(usb0)"), html);
assert.ok(html.includes("internet: nie") && html.includes("DNS nie działa"), html);
assert.ok(html.includes("data-net-checked") && html.includes("sprawdzono "), html);
assert.ok(html.includes("błąd 401 — zły albo nieaktywny klucz"), html);
assert.ok(html.includes("klucz: nie") && html.includes("BCM_ORS_API_KEY"), html);
assert.ok(html.includes('data-net-service="tomtom" data-net-result="ok"'), html);
assert.ok(html.includes('data-net-service="ors" data-net-result="no_key"'), html);
assert.ok(html.includes("data-net-test") && html.includes(">Test<"), html);
assert.ok(!/class="[^"]*\b(flex|gap-|px-|py-|text-\[)/.test(html.replace(/material-symbols-outlined/g, "")),
          "only inline styles: " + html);
// Result texts.
assert.strictEqual(Settings.netResultText("http", 429, t), "błąd 429 — wyczerpany limit zapytań");
assert.strictEqual(Settings.netResultText("http", 500, t), "błąd HTTP 500");
assert.strictEqual(Settings.netResultText("network", null, t), "błąd sieci");
assert.strictEqual(Settings.netResultText(undefined, null, t), "nie testowano");
assert.strictEqual(Settings.netResultText("http", "<x>", t), "błąd HTTP ?");
// Other uplink kinds, the probe OK.
html = Settings.netDiagRowHtml(Object.assign({}, ND, {
    uplink: { kind: "bt", iface: "bnep0", internet: true },
    probe: { ok: true, iface: "bnep0", error: "" } }), t);
assert.ok(html.includes("Bluetooth z telefonu") && html.includes("internet: tak"), html);
// Running test: button disabled, message.
html = Settings.netDiagRowHtml(Object.assign({}, ND, { test: { running: true, at: null } }), t);
assert.ok(html.includes("disabled") && html.includes("testuję…"), html);
// No payload = module off: no row.
assert.strictEqual(Settings.netDiagRowHtml(null, t), "");
assert.strictEqual(Settings.netDiagRowHtml("x", t), "");
// Garbage escaped, never a key value (the payload has none — and nothing
// from it is drawn unescaped).
html = Settings.netDiagRowHtml({ uplink: { kind: "<b>", iface: '"><script>x</script>' },
                                 probe: { ok: "yes", error: "<i>" },
                                 services: { owm: { key_set: true, result: "<img>", http_code: SECRET } },
                                 test: {} }, t);
assert.ok(!html.includes("<script>") && !html.includes("<img") && !html.includes(SECRET), html);
assert.ok(html.includes("jeszcze nie sprawdzono"), html);

// ── "bez internetu" on the phone rows ───────────────────────────────────
html = Settings.carPhoneRowHtml({ state: "connected", ip: "192.168.42.10", iface: "usb0",
                                  internet: false, route_iface: "usb0", hint: "no_internet" }, t);
assert.ok(html.includes("połączono, bez internetu"), html);
assert.ok(html.includes("dane komórkowe wyłączone albo operator blokuje tethering"), html);
html = Settings.tetherRowHtml({ state: "connected", ip: "192.168.44.2", iface: "bnep0",
                                internet: false, route_iface: "<b>wlan0</b>", hint: "route_other" }, t);
assert.ok(html.includes("połączono, bez internetu") && html.includes("trasa domyślna idzie przez"), html);
assert.ok(!html.includes("<b>wlan0") && html.includes("&lt;b&gt;wlan0"), html);
html = Settings.carPhoneRowHtml({ state: "connected", ip: "1.2.3.4", internet: true }, t);
assert.ok(html.includes(">połączono<") && html.includes("internet"), html);
html = Settings.carPhoneRowHtml({ state: "connected", ip: "1.2.3.4", internet: null }, t);
assert.ok(!html.includes("bez internetu"), html);

// ── the whole screen + update() ─────────────────────────────────────────
const settings = screens.settings;
const container = { innerHTML: "" };
settings.render(container, "modern", { net_diag: ND });
assert.ok(container.innerHTML.includes("data-net-diag-slot") && container.innerHTML.includes("data-net-diag "),
          "row rendered");
settings.render(container, "modern", { net_diag: null });
assert.ok(/data-net-diag-slot style="display:contents"><\/div>/.test(container.innerHTML));
const slot = slots["[data-net-diag-slot]"];
settings.update({ net_diag: null });
assert.strictEqual(slot.innerHTML, "<untouched>", "same payload: nothing redrawn");
settings.update({ net_diag: ND });
assert.ok(slot.innerHTML.includes("błąd 401"), slot.innerHTML);

// ── trip.js: plan error + approximate hint ──────────────────────────────
const trip = screens.a3;
assert.ok(trip, "trip screen registered");
const plan401 = { destination_name: "Gdynia, PL", error: "route_unavailable",
                  service_errors: [{ service: "ors", result: "http", http_code: 401 },
                                   { service: "tomtom", result: "network", http_code: null }] };
trip.update({ trip_plan: plan401, trip_planning: false });
let overlay = tripHost.children[tripHost.children.length - 1];
assert.ok(overlay && overlay.innerHTML.includes("data-trip-error"), "error banner");
assert.ok(overlay.innerHTML.includes("OpenRouteService: błąd 401 — zły albo nieaktywny klucz (BCM_ORS_API_KEY w /etc/bcm/bcm.env)"),
          overlay.innerHTML);
assert.ok(overlay.innerHTML.includes("TomTom: brak połączenia z serwerem"), overlay.innerHTML);
trip.update({ trip_plan: { destination_name: "Gdynia, PL", approximate: true, distance_km: 300 },
              trip_planning: false });
overlay = tripHost.children[tripHost.children.length - 1];
assert.ok(overlay.innerHTML.includes("BCM_ORS_API_KEY do /etc/bcm/bcm.env"), overlay.innerHTML);
assert.ok(!overlay.innerHTML.includes("config/bcm_config.yaml"), "old wrong hint gone");
assert.ok(!overlay.innerHTML.includes("data-trip-error"), overlay.innerHTML);

// ── weather.js: demo placeholder instead of Milan ───────────────────────
const weather = screens.a4;
const wc = { innerHTML: "" };
weather.render(wc, "heritage", { weather_city: "Milan, IT", weather_temp: 22,
                                 weather_status: { source: "demo", last_error: "http", http_code: 401 } });
assert.ok(!wc.innerHTML.includes("Milan"), "no Milan while demo");
assert.ok(wc.innerHTML.includes("brak prawdziwych danych pogody"), wc.innerHTML);
assert.ok(wc.innerHTML.includes("dane przykładowe — błąd 401 — zły albo nieaktywny klucz"), wc.innerHTML);
weather.render(wc, "modern", { weather_city: "Milan, IT",
                               weather_status: { source: "demo", last_error: "no_key" } });
assert.ok(!wc.innerHTML.includes("Milan") && wc.innerHTML.includes("brak klucza"), wc.innerHTML);
weather.render(wc, "autodelta", { weather_city: "Kraków, PL",
                                  weather_status: { source: "live", last_error: "" } });
assert.ok(wc.innerHTML.includes("Kraków, PL") && !wc.innerHTML.includes("dane przykładowe"));
weather.render(wc, "heritage", { weather_city: "", weather_status: null });
assert.ok(!wc.innerHTML.includes("Milan"), "no hardcoded Milan fallback");

// ── weather.js search: error codes shown, not a silent empty list ───────
const WS = vm.runInContext("WeatherSearch", ctx);
assert.ok(WS.errorText({ error: "no_key" }).includes("BCM_OWM_API_KEY"));
assert.ok(WS.errorText({ error: "http", http_code: 401 }).includes("błąd 401"));
assert.ok(WS.errorText({ error: "http", http_code: 500 }).includes("HTTP 500"));
assert.ok(WS.errorText({ error: "network" }).includes("brak połączenia"));
assert.strictEqual(WS.errorText(null), "");
{
    const box = { style: {}, attrs: {}, setAttribute(k, v) { this.attrs[k] = v; } };
    const el = { style: {}, innerHTML: "x", children: [], appendChild(c) { this.children.push(c); } };
    const oldGet = ctx.document.getElementById, oldCreate = ctx.document.createElement;
    ctx.document.getElementById = (id) => (id === "weather-search-results" ? el : null);
    ctx.document.createElement = () => box;
    WS._results = [];
    WS._error = { error: "http", http_code: 401 };
    WS._showResults();
    assert.strictEqual(el.style.display, "block");
    assert.ok(box.textContent.includes("błąd 401"), box.textContent);
    WS._error = null;
    WS._showResults();
    assert.strictEqual(el.style.display, "none");
    ctx.document.getElementById = oldGet;
    ctx.document.createElement = oldCreate;
}

// ── "Test": one POST, the answer shown ──────────────────────────────────
(async () => {
    await Settings.netTest();
    await Settings.netTest();                               // double tap swallowed
    const posts = fetches.filter(([url]) => url === "/api/net/test");
    assert.deepStrictEqual(posts, [["/api/net/test", "POST"]]);
    assert.ok(Settings._netTest.msg.startsWith("testuję"), Settings._netTest.msg);
    Settings._netTest.at = 0;
    fetchReply = { status: 429, body: { ok: false, error: "too many requests" } };
    await Settings.netTest();
    assert.ok(Settings._netTest.msg.includes("spróbuj za kilka sekund"), Settings._netTest.msg);
    console.log("ok");
})().catch((e) => { console.error(e); process.exit(1); });
