// Settings screen: the "Traccar" row (data.traccar = web_viewer._traccar_summary
// of traccar.state, src/network/traccar.py) and "Ostatni postój"
// (data.last_park = web_viewer._last_park_summary of park.last_position),
// for tests/test_frontend_gestures.py. Loads the real screens/settings.js in a
// node vm with DOM stubs; plain node + assert, no packages. Exits non-zero on
// failure, prints "ok" on success.
"use strict";
const assert = require("assert");
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const WEB = path.join(__dirname, "..", "..", "src", "dashboard", "web", "js");

let screen = null;
const listeners = {};
const fetches = [];
const slots = { "[data-traccar-slot]": { innerHTML: "<untouched>" },
                "[data-last-park-slot]": { innerHTML: "<untouched>" },
                "[data-traccar-msg]": { textContent: "" } };
const ctx = {
    console, setTimeout, clearTimeout, Promise, JSON, Math, Date, Object, String, Number,
    isFinite, Array,
    setInterval: () => 0, clearInterval() {},
    fetch: async (url, opts) => {
        fetches.push([url, opts]);
        return { ok: true, status: 200, json: async () => ({ ok: true }) };
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

const TS = new Date(2026, 10, 19, 3, 12, 0).getTime() / 1000;
const AGENT = { enabled: true, configured: true, id_fp: "a1b2c3d4", mode: "park", queue_n: 0,
                last_sent_ts: TS, last_ok_ts: TS, last_error: "", last_http: 200, dropped: 0,
                paused_low_battery: false };
const OK = { url_ok: true, url_host: "example.org", id_set: true, id_fp: "a1b2c3d4",
             agent: AGENT, cmd: null, error: "" };
const row = (over, agent) => Settings.traccarRowHtml(
    Object.assign({}, OK, over || {}, agent ? { agent: Object.assign({}, AGENT, agent) } : {}), t);

// ── the Traccar row ──────────────────────────────────────────────────────
let html = row();
assert.ok(html.includes("Traccar") && html.includes('data-traccar-state="ok"'), html);
assert.ok(html.includes("działa") && html.includes("example.org") && html.includes("postój"), html);
assert.ok(html.includes("ostatni punkt: 19.11 03:12"), html);
assert.ok(html.includes("data-traccar-send") && html.includes("Wyślij pozycję teraz"), html);
assert.ok(!html.includes("onclick"), "delegated listener, no inline handlers");
assert.ok(!/class="[^"]*\b(flex|gap-|px-|py-|text-\[)/.test(html.replace(/material-symbols-outlined/g, "")),
          "only inline styles: " + html);
// queue and errors
html = row({}, { queue_n: 12, last_error: "unknown_device" });
assert.ok(html.includes('data-traccar-state="error"') && html.includes("w kolejce: 12"), html);
assert.ok(html.includes("Traccar nie zna identyfikatora"), html);
assert.ok(row({}, { last_error: "redirect" }).includes("auth_request off;"));
assert.ok(row({}, { paused_low_battery: true }).includes("bateria &lt; 10% — tylko alarmy"));
assert.ok(row({}, { mode: "drive" }).includes("jazda"));
// not configured: no button, hints where to put what
html = row({ url_ok: false, url_host: "", id_set: false, id_fp: "" });
assert.ok(html.includes('data-traccar-state="not_configured"') && !html.includes("data-traccar-send"), html);
assert.ok(html.includes("traccar.url") && html.includes("BCM_TRACCAR_DEVICE_ID"), html);
// agent states
assert.ok(row({ error: "no_agent", agent: null }).includes("brak agenta w telefonie"));
assert.ok(row({ error: "agent_outdated", agent: null }).includes("≥ 1.6.0"));
assert.ok(row({ agent: null }).includes("brak danych z telefonu"));
assert.ok(row({}, { configured: false }).includes("czeka na konfigurację"));
assert.ok(row({}, { id_fp: "ffffffff" }).includes("inny identyfikator"));
// command outcome
assert.ok(row({ cmd: { state: "sent", error: "", ts: TS } }).includes("telefon przyjął"));
assert.ok(row({ cmd: { state: "failed", error: "rate_limited", ts: TS } }).includes("telefon odmówił (rate_limited)"));
// escaping: hostile strings from a broken payload never become markup
html = row({ url_host: "<img src=x onerror=alert(1)>", cmd: { state: "failed", error: "<b>x</b>" } },
           { last_error: "<script>" });
assert.ok(!html.includes("<img") && !html.includes("<b>") && !html.includes("<script>"), html);
assert.ok(html.includes("&lt;img"), html);
// no payload = module not running: no row
assert.strictEqual(Settings.traccarRowHtml(null, t), "");
assert.strictEqual(Settings.traccarRowHtml("x", t), "");

// ── the "Ostatni postój" row ─────────────────────────────────────────────
const LP = { lat: 50.06143, lon: 19.93658, ts: TS, reason: "still",
             osm_url: "https://www.openstreetmap.org/?mlat=50.061430&mlon=19.936580#map=17/50.061430/19.936580",
             geo_url: "geo:50.061430,19.936580" };
html = Settings.lastParkRowHtml(LP, t);
assert.ok(html.includes("Ostatni postój") && html.includes("19.11 03:12"), html);
assert.ok(html.includes("50.06143, 19.93658") && html.includes("openstreetmap.org/?mlat=50.061430"), html);
assert.ok(!html.includes("<a ") && !html.includes("href"), "no navigation away from the kiosk: " + html);
// a foreign URL is not shown, bad numbers = no row
assert.ok(!Settings.lastParkRowHtml(Object.assign({}, LP, { osm_url: "javascript:alert(1)" }), t)
    .includes("javascript"));
assert.strictEqual(Settings.lastParkRowHtml(Object.assign({}, LP, { lat: "50" }), t), "");
assert.strictEqual(Settings.lastParkRowHtml(Object.assign({}, LP, { lon: 999 }), t), "");
assert.strictEqual(Settings.lastParkRowHtml(null, t), "");

// ── render + update + the button ─────────────────────────────────────────
assert.ok(screen && typeof screen.render === "function");
const container = { innerHTML: "" };
screen.render(container, "modern", { traccar: OK, last_park: LP });
assert.ok(container.innerHTML.includes("data-traccar-slot") && container.innerHTML.includes("data-last-park-slot"));
assert.ok(container.innerHTML.includes('data-traccar-state="ok"'));
const before = (listeners.click || []).length;
screen.render(container, "modern", { traccar: OK, last_park: LP });
assert.strictEqual((listeners.click || []).length, before, "listener installed once");
screen.update({ traccar: Object.assign({}, OK, { agent: Object.assign({}, AGENT, { queue_n: 3 }) }),
                last_park: LP });
assert.ok(slots["[data-traccar-slot]"].innerHTML.includes("w kolejce: 3"));
assert.ok(slots["[data-last-park-slot]"].innerHTML.includes("Ostatni postój"));
screen.update({});
assert.strictEqual(slots["[data-traccar-slot]"].innerHTML, "");
// The delegated click → one POST with an empty JSON object, nothing else.
const target = { closest: (sel) => (sel.includes("data-traccar-send") ? {} : null) };
for (const fn of listeners.click) fn({ target });
setTimeout(() => {
    const sent = fetches.filter(([u]) => u === "/api/traccar/send");
    assert.strictEqual(sent.length, 1, JSON.stringify(fetches));
    assert.strictEqual(sent[0][1].method, "POST");
    assert.strictEqual(sent[0][1].body, "{}");
    console.log("ok");
    process.exit(0);
}, 50);
