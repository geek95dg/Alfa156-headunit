// screens/weather.js for tests/test_frontend_gestures.py: place names from the
// geocoder (upstream data) and the city / condition from the weather payload
// never become markup; a search result is picked through data-weather-idx and
// one delegated click listener (no result text in an inline handler), and only
// finite, in-range coordinates reach Leaflet and POST /api/weather/location.
// Loads the real file in a node vm with DOM stubs; plain node + assert, no
// packages. Exits non-zero on failure, prints "ok" on success.
"use strict";
const assert = require("assert");
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const WEB = path.join(__dirname, "..", "..", "src", "dashboard", "web", "js");
const EVIL = '<img src=x onerror="alert(1)">';

function element() {
    const attrs = {};
    const listeners = {};
    return {
        innerHTML: "", textContent: "", value: "x", style: {}, children: [],
        getAttribute: (k) => (k in attrs ? attrs[k] : null),
        setAttribute: (k, v) => { attrs[k] = String(v); },
        addEventListener: (type, fn) => { (listeners[type] = listeners[type] || []).push(fn); },
        listeners,
    };
}
const els = { "weather-search-results": element(), "weather-search-input": element(),
              "weather-city": element(), "weather-condition": element(),
              "weather-temp": element() };
const fetches = [];
const views = [];
const screens = {};
const ctx = {
    console: { log() {}, error() {}, warn() {} },
    // select()'s 10 s "never stuck on Loading" fallback would hold node open.
    setTimeout: (fn, ms) => (ms >= 1000 ? 0 : setTimeout(fn, ms)),
    clearTimeout, Promise, JSON, Math, Date, Object, String, Number, Array,
    setInterval: () => 0, clearInterval() {},
    fetch: async (url, opts) => {
        fetches.push({ url, body: opts && opts.body ? JSON.parse(opts.body) : undefined });
        return { ok: true, json: async () => ({ ok: true }) };
    },
    App: {
        registerScreen(name, impl) { screens[name] = impl; },
        getTheme: () => "modern",
        getCurrentScreen: () => "a4",
        getConfig: () => ({ theme: "modern", language: "pl" }),
        t: (key, fallback) => fallback || key,
        navigateTo() {},
    },
    AppBar: { render: () => "" },
    NavBar: { render: () => "" },
    DataStore: { get: () => 0, getAll: () => ({}), subscribe() {}, unsubscribe() {} },
    document: { getElementById: (id) => els[id] || null, querySelector: () => null,
                createElement: () => element(), body: {} },
};
ctx.window = { _weatherMap: { setView: (pos, z) => views.push(pos) }, _weatherMarker: null };
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(path.join(WEB, "screens", "weather.js"), "utf8"), ctx,
                { filename: "weather.js" });
vm.runInContext("this.__WS = WeatherSearch;", ctx);
const WS = ctx.__WS;

// ── the result list ──────────────────────────────────────────────────────
WS._results = [
    { name: EVIL, state: EVIL, country: "PL<script>", lat: 54.5, lon: 18.5 },
    { name: "Gdańsk", state: "", country: "PL", lat: "x", lon: 18.6 },
    { name: "Bad", country: "PL", lat: 91, lon: 18.6 },
    null,
];
WS._showResults();
const list = els["weather-search-results"];
let html = list.innerHTML;
assert.ok(!html.includes("<img") && !html.includes("<script"), html);
assert.ok(html.includes("&lt;img src=x onerror=&quot;alert(1)&quot;&gt;"), html);
assert.ok(html.includes("PL&lt;script&gt;"), html);
assert.ok(!/onclick/i.test(html), "no inline handlers in the list: " + html);
for (const i of [0, 1, 2, 3]) assert.ok(html.includes(`data-weather-idx="${i}"`), html);
assert.strictEqual(list.style.display, "block");
assert.strictEqual(list.listeners.click.length, 1, "one delegated listener");
WS._showResults();                                    // re-render: no second listener
assert.strictEqual(list.listeners.click.length, 1);

(async () => {
    // A click inside row 0 (its child span): select(0) through the listener.
    const row = { getAttribute: (k) => (k === "data-weather-idx" ? "0" : null) };
    const span = { closest: (sel) => (sel === "[data-weather-idx]" ? row : null) };
    list.listeners.click[0]({ target: span });
    await new Promise((r) => setTimeout(r, 0));
    assert.deepStrictEqual(Array.from(views[0]), [54.5, 18.5]);   // vm-realm array
    assert.strictEqual(els["weather-city"].textContent, EVIL + ", PL<script>", "textContent only");
    assert.deepStrictEqual(fetches[0], { url: "/api/weather/location",
        body: { lat: 54.5, lon: 18.5, city: EVIL + ", PL<script>" } });

    // Not a number / out of range / not a result: nothing moves, nothing sent.
    for (const idx of [1, 2, 3, 99, "0", -1, 0.5]) {
        await WS.select(idx);
    }
    assert.strictEqual(fetches.length, 1, JSON.stringify(fetches));
    assert.strictEqual(views.length, 1);
    // A click outside any row is ignored.
    list.listeners.click[0]({ target: { closest: () => null } });
    list.listeners.click[0]({ target: null });
    await new Promise((r) => setTimeout(r, 0));
    assert.strictEqual(fetches.length, 1);

    // ── the screen: city / condition from the payload are escaped ───────
    for (const theme of ["heritage", "modern", "autodelta"]) {
        const box = { innerHTML: "" };
        screens.a4.render(box, theme, { weather_city: EVIL, weather_condition: "<b>rain</b>" });
        assert.ok(!box.innerHTML.includes("<img") && !box.innerHTML.includes("<b>rain"),
                  theme + ": " + box.innerHTML);
        assert.ok(box.innerHTML.includes("&lt;b&gt;rain&lt;/b&gt;"), theme);
    }
    console.log("ok");
})().catch((e) => { console.error(e); process.exit(1); });
