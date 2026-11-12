// Where the GPS stands, for tests/test_frontend_gestures.py (zgłoszenie A):
//  * screens/settings.js — the "GPS: <źródło> <stan> <nadawca>" row from
//    data.gps_state with the "send NMEA to <bnep0 IP>:10110" hint, and
//    update() redrawing only that row;
//  * screens/weather.js — the map badge follows data.gps_fix (it used to say
//    "GPS AKTYWNY" always);
//  * screens/trip.js — the travel plan says "start: domyślny (brak GPS)"
//    when the route starts from the fallback origin.
// Loads the real screen files in node vms with DOM stubs; plain node +
// assert, no packages. Exits non-zero on failure, prints "ok" on success.
"use strict";
const assert = require("assert");
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const WEB = path.join(__dirname, "..", "..", "src", "dashboard", "web", "js");
const t = (k, d) => d;

function load(file, extra) {
    const screens = {};
    const ctx = Object.assign({
        console, setTimeout, clearTimeout, Promise, JSON, Math, Date, Object, String,
        Number, Array,
        setInterval: () => 0, clearInterval() {},
        fetch: async () => ({ ok: true, json: async () => ({}) }),
        localStorage: { getItem: () => null, setItem() {} },
        App: {
            registerScreen(name, impl) { screens[name] = impl; },
            getConfig: () => ({ theme: "modern", language: "pl", speed_unit: "km/h", temp_unit: "C" }),
            getTheme: () => "heritage",
            t: (key, fallback) => fallback || key,
            navigateTo() {},
        },
        AppBar: { render: () => "" },
        NavBar: { render: () => "" },
        DataStore: { getAll: () => ({}), get: () => 0, subscribe() {}, unsubscribe() {} },
        document: {
            getElementById: () => null, createElement: () => ({ style: {} }), body: {},
            querySelector: () => null,
        },
    }, extra || {});
    vm.createContext(ctx);
    vm.runInContext(fs.readFileSync(path.join(WEB, "screens", file), "utf8"), ctx,
                    { filename: file });
    return { ctx, screens };
}

// ── Settings: the GPS row ────────────────────────────────────────────────
const slots = {};
const settings = load("settings.js", {
    document: {
        getElementById: () => null, createElement: () => ({ style: {} }), body: {},
        querySelector: (sel) => slots[sel] || null,
    },
});
vm.runInContext("this.__Settings = Settings;", settings.ctx);
const Settings = settings.ctx.__Settings;

const PAN = { state: "connected", ip: "192.168.44.23", iface: "bnep0" };
const NOFIX = { source: "udp,tcp", state: "no_fix", peer: "", last_ts: null,
                inputs: [{ source: "udp", state: "listening" }, { source: "tcp", state: "waiting" }],
                udp_port: 10110, tcp_port: 50000 };

let html = Settings.gpsRowHtml(NOFIX, PAN, t);
assert.ok(html.includes('data-gps-state="no_fix"'), html);
assert.ok(html.includes("GPS:") && html.includes("UDP + TCP") && html.includes("brak pozycji"), html);
assert.ok(html.includes("Wyślij NMEA na 192.168.44.23:10110 (UDP) albo uruchom serwer NMEA TCP na porcie 50000"),
          html);
assert.ok(!/class="[^"]*\b(flex|gap-|px-|py-|text-\[)/.test(html.replace(/material-symbols-outlined/g, "")),
          "only inline styles in the new row: " + html);

// No PAN yet: the hint names the place to look instead of an address.
html = Settings.gpsRowHtml(NOFIX, { state: "waiting_phone", ip: "" }, t);
assert.ok(html.includes("Wyślij NMEA na &lt;IP bnep0 z „Internet z telefonu”&gt;:10110 (UDP)"), html);
html = Settings.gpsRowHtml(NOFIX, null, t);
assert.ok(html.includes("&lt;IP bnep0"), html);
// Only the inputs that run are suggested.
html = Settings.gpsRowHtml(Object.assign({}, NOFIX, { source: "tcp", udp_port: null }), PAN, t);
assert.ok(!html.includes("(UDP)") && html.includes("uruchom serwer NMEA TCP na porcie 50000"), html);
assert.ok(!html.includes(" albo "), html);

// A fix: source, state and sender, no hint.
html = Settings.gpsRowHtml({ source: "udp", state: "fix", peer: "192.168.44.1", udp_port: 10110,
                             tcp_port: null, inputs: [] }, PAN, t);
assert.ok(html.includes('data-gps-state="fix"') && html.includes("jest pozycja"), html);
assert.ok(html.includes("od") && html.includes("192.168.44.1"), html);
assert.ok(!html.includes("data-gps-hint"), html);

// No payload = location module off: no row.
assert.strictEqual(Settings.gpsRowHtml(null, PAN, t), "");
assert.strictEqual(Settings.gpsRowHtml(undefined), "");
assert.strictEqual(Settings.gpsRowHtml("fix", PAN, t), "");

// Everything from the network is escaped, "$&" stays literal.
html = Settings.gpsRowHtml({ source: "<img src=x onerror=alert(1)>", state: "fix",
                             peer: '"><script>x</script>' }, PAN, t);
assert.ok(!html.includes("<img") && !html.includes("<script>"), html);
assert.ok(html.includes("&lt;img src=x onerror=alert(1)&gt;"), html);
html = Settings.gpsRowHtml(NOFIX, { state: "connected", ip: "$&<b>" }, t);
assert.ok(html.includes("Wyślij NMEA na $&amp;&lt;b&gt;:10110"), html);
assert.ok(!html.includes("<b>"), html);

// The screen draws the row in its slot; update() redraws only that slot.
const screen = settings.screens.settings;
const container = { innerHTML: "" };
screen.render(container, "modern", { gps_state: NOFIX, phone_tether: PAN });
assert.ok(container.innerHTML.includes("data-gps-slot"), "slot rendered");
assert.ok(container.innerHTML.includes('data-gps-state="no_fix"'), "row rendered");
screen.render(container, "modern", { aa_status: "running" });
assert.ok(/data-gps-slot style="display:contents"><\/div>/.test(container.innerHTML));

const gpsSlot = { innerHTML: "<untouched>" };
slots["[data-gps-slot]"] = gpsSlot;
screen.render(container, "modern", { gps_state: NOFIX, phone_tether: PAN });
screen.update({ gps_state: Object.assign({}, NOFIX, { last_ts: 123 }), phone_tether: PAN });
assert.strictEqual(gpsSlot.innerHTML, "<untouched>", "last_ts alone redraws nothing");
screen.update({ gps_state: Object.assign({}, NOFIX, { state: "fix", peer: "192.168.44.1" }),
                phone_tether: PAN });
assert.ok(gpsSlot.innerHTML.includes('data-gps-state="fix"'), gpsSlot.innerHTML);
screen.update({ gps_state: null, phone_tether: PAN });
assert.strictEqual(gpsSlot.innerHTML, "");
screen.update(undefined);                                   // never throws

// ── Weather: the map badge ───────────────────────────────────────────────
const elements = {};
const weather = load("weather.js", {
    document: {
        getElementById: (id) => elements[id] || null, createElement: () => ({ style: {} }),
        body: {}, querySelector: () => null,
    },
});
const a4 = weather.screens.a4;
const wbox = { innerHTML: "" };
a4.render(wbox, "heritage", { weather_city: "Kraków", gps_fix: false });
assert.ok(wbox.innerHTML.includes('id="weather-gps-label"'), "badge has an id");
assert.ok(wbox.innerHTML.includes("BRAK GPS") && !wbox.innerHTML.includes("GPS AKTYWNY"),
          "no fix: no 'GPS AKTYWNY'");
a4.render(wbox, "heritage", { weather_city: "Warszawa", gps_fix: true });
assert.ok(wbox.innerHTML.includes("GPS AKTYWNY"), "fix: GPS AKTYWNY");
elements["weather-gps-label"] = { textContent: "" };
a4.update({ gps_fix: false });
assert.strictEqual(elements["weather-gps-label"].textContent, "BRAK GPS");
a4.update({ gps_fix: true });
assert.strictEqual(elements["weather-gps-label"].textContent, "GPS AKTYWNY");

// ── Trip: where the route starts ─────────────────────────────────────────
let appended = null;
const host = {
    querySelector: () => null,
    appendChild(el) { appended = el; },
};
const overlayEl = () => ({
    style: {}, className: "", innerHTML: "", querySelector: () => null,
    addEventListener() {}, remove() {},
});
const trip = load("trip.js", {
    localStorage: { getItem: (k) => (k === "bcm.travelPlan" ? "1" : null), setItem() {} },
    document: {
        getElementById: () => null, createElement: overlayEl, body: {},
        querySelector: (sel) => (sel === "#app .screen-container" ? host : null),
    },
});
const a3 = trip.screens.a3;
const tbox = { innerHTML: "" };
const plan = (extra) => ({ trip_plan: Object.assign({
    destination_name: "Gdynia<script>", distance_km: 500, eta_min: 330, predicted_fuel_l: 30,
    weather_points: [], incidents: [{ description: "<img src=x onerror=alert(1)>" }],
}, extra), trip_planning: false });

a3.render(tbox, "heritage", plan({ origin_source: "fallback" }));
assert.ok(appended && appended.innerHTML.includes('data-trip-origin="fallback"'), "fallback notice");
assert.ok(appended.innerHTML.includes("start: domyślny (brak GPS)"), appended.innerHTML);
assert.ok(!appended.innerHTML.includes("<img") && !appended.innerHTML.includes("Gdynia<script>"),
          "plan texts escaped: " + appended.innerHTML);
a3.render(tbox, "heritage", plan({ origin_source: "gps" }));
assert.ok(appended.innerHTML.includes('data-trip-origin="gps"'), appended.innerHTML);
assert.ok(!appended.innerHTML.includes("brak GPS"), appended.innerHTML);
a3.render(tbox, "heritage", plan({ origin_source: null }));
assert.ok(!appended.innerHTML.includes("data-trip-origin"), "unknown origin: nothing");
a3.render(tbox, "heritage", Object.assign(plan({ origin_source: "fallback" }), { trip_planning: true }));
assert.ok(!appended.innerHTML.includes("data-trip-origin"), "not while computing");

console.log("ok");
