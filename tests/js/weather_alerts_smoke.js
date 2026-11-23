// A4 weather screen (screens/weather.js) and the top bar (components/
// appbar.js) for modules.weather_alerts, for tests/test_frontend_gestures.py:
//  - the forecast rows come from data.weather_forecast in all three themes
//    (they used to be made up from the current temperature: temp + 3,
//    temp - 5, "16:00 … 18:00", "Tomorrow/Wednesday/Thursday");
//  - without a forecast: "brak prognozy", no numbers;
//  - forecast entries are validated (odd icon / day / numbers);
//  - the alert strip shows the most severe alert, escaped, "+N więcej",
//    hidden without alerts, updated in place by update();
//  - the top-bar icon: glyph and colour of the most severe alert, hidden
//    without (or with only invalid) alerts, never the alert text;
//  - the kiosk icing popup stays disabled (owner's request).
// Plain node + assert, real files in a vm with DOM stubs. Prints the glyph
// list (JSON) on the first line for the font check, "ok" last.
"use strict";
const assert = require("assert");
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const WEB = path.join(__dirname, "..", "..", "src", "dashboard", "web", "js");
const EVIL = '<img src=x onerror="alert(1)">';

function element(id) {
    const attrs = {};
    return {
        id, innerHTML: "", textContent: "", style: {},
        getAttribute: (k) => (k in attrs ? attrs[k] : null),
        setAttribute: (k, v) => { attrs[k] = String(v); },
        addEventListener() {},
        querySelector: () => null,
    };
}
const els = {};
const screens = {};
const STRINGS = { weather_today: "DZIŚ", wed: "ŚR", thu: "CZW", weather_no_forecast: "brak prognozy",
                  weather_alert_more: "+{n} więcej" };
const ctx = {
    console: { log() {}, error() {}, warn() {} },
    setTimeout: () => 0, clearTimeout() {}, setInterval: () => 0, clearInterval() {},
    Promise, JSON, Math, Date, Object, String, Number, Array, isFinite,
    App: {
        registerScreen(name, impl) { screens[name] = impl; },
        getTheme: () => "modern", getCurrentScreen: () => "a4",
        getConfig: () => ({ theme: "modern", language: "pl", temp_unit: "C" }),
        t: (key, fallback) => (key in STRINGS ? STRINGS[key] : (fallback || key)),
        navigateTo() {},
    },
    AppBar: { render: () => "" },
    NavBar: { render: () => "" },
    DataStore: { get: () => 0, getAll: () => ({}), subscribe() {}, unsubscribe() {} },
    document: { getElementById: (id) => els[id] || null, querySelector: () => null,
                createElement: () => element(), body: {} },
    window: {},
};
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(path.join(WEB, "screens", "weather.js"), "utf8"), ctx,
                { filename: "weather.js" });
const A4 = screens.a4;

// ── forecast rows: real data ────────────────────────────────────────────
const FORECAST = [
    { day: "Today", high: 3.4, low: -1.2, condition: "Snow", icon: "13d" },
    { day: "Wed", high: 7, low: 1, condition: "Rain", icon: "10n" },
    { day: "Thu", high: 12, low: 4, condition: "Clear", icon: "01d" },
    { day: "Fri", high: 20, low: 10, condition: "x", icon: "01d" },     // only 3 shown
];
const entries = A4.forecastEntries({ weather_forecast: FORECAST });
assert.deepStrictEqual(JSON.parse(JSON.stringify(entries)), [
    { label: "DZIŚ", glyph: "ac_unit", high: 3, low: -1 },
    { label: "ŚR", glyph: "rainy", high: 7, low: 1 },
    { label: "CZW", glyph: "sunny", high: 12, low: 4 },
]);
// Untrusted entries: odd icon → generic glyph, odd day → "—", no numbers → skipped.
const odd = A4.forecastEntries({ weather_forecast: [
    null, "x", { day: EVIL, high: 5, low: 2, icon: "<b>" }, { day: "Mon", high: "9", low: NaN },
    { day: "Sat", high: 1e9, low: 2, icon: "99d" },
] });
assert.deepStrictEqual(JSON.parse(JSON.stringify(odd)), [
    { label: "—", glyph: "partly_cloudy_day", high: 5, low: 2 },
    { label: "SAT", glyph: "partly_cloudy_day", high: null, low: 2 },
]);
assert.deepStrictEqual(Array.from(A4.forecastEntries({ weather_forecast: "x" })), []);
assert.deepStrictEqual(Array.from(A4.forecastEntries(undefined)), []);

const BASE = { weather_temp: 10, weather_condition: "Snow", weather_forecast: FORECAST,
               weather_status: { source: "live" } };
for (const theme of ["heritage", "modern", "autodelta"]) {
    const box = { innerHTML: "" };
    A4.render(box, theme, BASE);
    const html = box.innerHTML;
    for (const want of ["DZIŚ", "ŚR", "CZW", "3°", "-1°", "7°", "12°", "ac_unit", "rainy"]) {
        assert.ok(html.includes(want), `${theme}: ${want} missing`);
    }
    // The made-up values are gone (temp 10 → 13°/5°, 11°, 15°, fixed hours / day names).
    for (const fake of ["13°", "15°", "16:00", "17:00", "18:00", "Tomorrow", "Wednesday", "Thursday",
                        ">Today<", ">Wed<"]) {
        assert.ok(!html.includes(fake), `${theme}: fake forecast value ${fake}`);
    }
    assert.ok(!html.includes("Pt") && !html.includes("20°"), `${theme}: a 4th day shown`);
    // No forecast: a plain line, no numbers from the current temperature.
    const empty = { innerHTML: "" };
    A4.render(empty, theme, { ...BASE, weather_forecast: [] });
    assert.ok(empty.innerHTML.includes('data-weather-forecast="none"'), theme);
    assert.ok(empty.innerHTML.includes("brak prognozy"), theme);
    assert.ok(!empty.innerHTML.includes("13°") && !empty.innerHTML.includes("5°"), theme);
    // Hidden alert strip present without alerts (update() fills it in place).
    assert.ok(/id="weather-alerts" data-count="0"[^>]*display:none/.test(empty.innerHTML), theme);
}

// ── alert strip ─────────────────────────────────────────────────────────
const ALERTS = [
    { kind: "icing", severity: "danger", title: "Gołoledź" + EVIL, where: "teraz",
      text: "Marznący opad, minus 1 stopień, teraz.<script>x</script>", valid_until: 2e9 },
    { kind: "wind", severity: "warning", title: "Silny wiatr", where: "za ~3 h", text: "Porywy", valid_until: 2e9 },
    { kind: "bogus", severity: "warning", title: "x", where: "", text: "", valid_until: 2e9 },
    { kind: "fog", severity: "extreme", title: "x", where: "", text: "", valid_until: 2e9 },
    null,
];
assert.strictEqual(A4.alertList({ weather_alerts: ALERTS }).length, 2);
assert.strictEqual(A4.alertList({ weather_alerts: "x" }).length, 0);
for (const theme of ["heritage", "modern", "autodelta"]) {
    const box = { innerHTML: "" };
    A4.render(box, theme, { ...BASE, weather_alerts: ALERTS });
    const html = box.innerHTML;
    assert.ok(/id="weather-alerts" data-count="2"[^>]*display:block/.test(html), theme);
    assert.ok(!html.includes("<img") && !html.includes("<script>"), theme + ": " + html);
    assert.ok(html.includes("Gołoledź&lt;img src=x onerror=&quot;alert(1)&quot;&gt;"), theme);
    assert.ok(html.includes("teraz") && html.includes("+1 więcej"), theme);
    assert.ok(html.includes("#dc2626"), theme + ": danger colour");
    assert.ok(!html.includes("Silny wiatr"), theme + ": only the most severe one in the strip");
}
// update(): the strip appears / disappears in place.
const strip = element("weather-alerts");
els["weather-alerts"] = strip;
A4.update({ ...BASE, weather_alerts: ALERTS });
assert.strictEqual(strip.style.display, "block");
assert.strictEqual(strip.getAttribute("data-count"), "2");
assert.ok(strip.innerHTML.includes("&lt;script&gt;") && !strip.innerHTML.includes("<script>"));
A4.update({ ...BASE, weather_alerts: [] });
assert.strictEqual(strip.style.display, "none");
assert.strictEqual(strip.innerHTML, "");
A4.update({ ...BASE, weather_alerts: null });
assert.strictEqual(strip.style.display, "none");

// Demo data is no forecast.
assert.deepStrictEqual(Array.from(A4.forecastEntries({ ...BASE, weather_status: { source: "demo" } })), []);

// update(): the forecast rows refresh in place (A4 open when the first real
// fetch arrives), only when they change, per theme.
for (const theme of ["heritage", "modern", "autodelta"]) {
    const fcEl = element("weather-forecast");
    fcEl.setAttribute("data-theme", theme);
    els["weather-forecast"] = fcEl;
    A4.update({ ...BASE, weather_forecast: [], weather_status: { source: "demo" } });
    assert.ok(fcEl.innerHTML.includes("brak prognozy"), theme);
    A4.update({ ...BASE });
    assert.ok(fcEl.innerHTML.includes("DZIŚ") && fcEl.innerHTML.includes("12°"), theme);
    fcEl.innerHTML = "untouched";
    A4.update({ ...BASE });
    assert.strictEqual(fcEl.innerHTML, "untouched", theme + ": rewritten without a change");
    A4.update({ ...BASE, weather_forecast: [{ day: "Today", high: EVIL, low: 1, icon: "01d" }] });
    assert.ok(!fcEl.innerHTML.includes("<img"), theme);
    delete els["weather-forecast"];
}

// ── top-bar icon ─────────────────────────────────────────────────────────
global.App = ctx.App;
const AppBar = require(path.join(WEB, "components", "appbar.js"));
assert.strictEqual(AppBar.alertView({}).visible, false);
assert.strictEqual(AppBar.alertView({ weather_alerts: null }).visible, false);
assert.strictEqual(AppBar.alertView({ weather_alerts: [ALERTS[2], ALERTS[3], null] }).visible, false);
// Most severe wins even if the list is not sorted.
let av = AppBar.alertView({ weather_alerts: [ALERTS[1], ALERTS[0]] });
assert.deepStrictEqual(JSON.parse(JSON.stringify(av)),
                       { visible: true, glyph: "ac_unit", severity: "danger", count: 2 });
let bar = AppBar.render("modern", { weather_alerts: [ALERTS[1]] });
assert.ok(/data-bind="weather_alert"[^>]*display:inline-block;color:#f59e0b;/.test(bar), bar);
assert.ok(bar.includes(">air</span>"));
assert.ok(!bar.includes("Porywy") && !bar.includes("Silny wiatr"), "no alert text in the bar");
assert.ok(/data-bind="bar_right" style="width:260px"/.test(bar), "right block widened for the icon");
bar = AppBar.render("modern", {});
assert.ok(/data-bind="weather_alert"[^>]*display:none;/.test(bar));
assert.ok(!/data-bind="bar_right"[^>]*style=/.test(bar), "no width change without an alert");

// update() against a small fake DOM: show, recolour, hide.
function fakeEl() {
    const attrs = {};
    return { textContent: "", style: {}, getAttribute: (k) => (k in attrs ? attrs[k] : null),
             setAttribute: (k, v) => { attrs[k] = String(v); } };
}
const nodes = { weather_alert: fakeEl(), bar_left: fakeEl(), bar_right: fakeEl() };
const container = { querySelector: (sel) => {
    const m = /data-bind="([a-z_]+)"/.exec(sel);
    return m && nodes[m[1]] ? nodes[m[1]] : null;
} };
AppBar.update(container, { weather_alerts: [ALERTS[1]] });
assert.strictEqual(nodes.weather_alert.style.display, "inline-block");
assert.strictEqual(nodes.weather_alert.textContent, "air");
assert.strictEqual(nodes.weather_alert.style.color, "#f59e0b");
assert.strictEqual(nodes.bar_right.style.width, "260px");
AppBar.update(container, { weather_alerts: [ALERTS[0]] });
assert.strictEqual(nodes.weather_alert.textContent, "ac_unit");
assert.strictEqual(nodes.weather_alert.style.color, "#dc2626");
AppBar.update(container, { weather_alerts: [] });
assert.strictEqual(nodes.weather_alert.style.display, "none");
assert.strictEqual(nodes.bar_right.style.width, "");

// ── the kiosk icing popup stays off ─────────────────────────────────────
const app = fs.readFileSync(path.join(WEB, "app.js"), "utf8");
const icing = /function _checkIcingAlert\(data\) \{([\s\S]*?)\n    \}/.exec(app);
assert.ok(icing, "_checkIcingAlert not found");
assert.ok(/^\s*(\/\/[^\n]*\n\s*)*return;/.test(icing[1]), "icing popup must return first");

process.stdout.write(JSON.stringify(Object.values(AppBar.ALERT_GLYPHS)
    .concat(entries.map((e) => e.glyph), ["partly_cloudy_day", "cloud", "thunderstorm", "foggy"])) + "\n");
process.stdout.write("ok\n");
