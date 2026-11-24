// A3 trip screen: the refuel panel (data.fuel_log from
// web_viewer._fuel_log_summary) and the "—" for values without a source
// (no refuel log yet, no OBD), in all three themes, for
// tests/test_frontend_gestures.py. Loads the real trip.js in a node vm with
// DOM stubs; plain node + assert. Exits non-zero on failure, prints "ok".
"use strict";
const assert = require("assert");
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const WEB = path.join(__dirname, "..", "..", "src", "dashboard", "web", "js");
const screens = {};
const ctx = {
    console, setTimeout, clearTimeout, Promise, JSON, Math, Date, Object, String, Number,
    Array, isFinite,
    localStorage: { getItem: () => null, setItem() {} },
    fetch: async () => ({ status: 200, json: async () => ({}) }),
    App: {
        registerScreen(name, impl) { screens[name] = impl; },
        getTheme: () => "heritage",
        t: (key, fallback) => fallback || key,
    },
    AppBar: { render: () => "" },
    NavBar: { render: () => "" },
    DataStore: { getAll: () => ({}) },
    document: {
        getElementById: () => null,
        querySelector: () => null,
        createElement: () => ({ style: {}, querySelector: () => null, addEventListener() {} }),
    },
};
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(path.join(WEB, "screens", "trip.js"), "utf8"), ctx,
                { filename: "trip.js" });
const trip = screens.a3;

function draw(theme, data) {
    const c = { innerHTML: "" };
    trip.render(c, theme, data);
    return c.innerHTML;
}

const FULL = {
    trip_distance: 12.34, avg_speed: 41.2, trip_time: "00:18:00",
    avg_consumption: 6.8, estimated_range: 512, instant_consumption: null,
    fuel_log: {
        enabled: true, running: true, status: "ok", count: 3,
        avg_l100_last: 7.04, avg_l100_overall: 6.81, cost_per_100km: 43.2,
        km_since_full: 210.4, est_range_km: 512, read_only: false,
        recent: [
            { id: 3, ts: 1.8e9, litres: 35, price_per_l: 6.2, odometer_km: 10500, full: true,
              interval: { km: 500, l100: 7.0, cost: 217, litres: 35, source: "odometer", usable: true } },
            { id: 2, ts: 1.79e9, litres: 10, price_per_l: null, odometer_km: null, full: false,
              interval: null },
            { id: 1, ts: 1.78e9, litres: 50, price_per_l: 6.0, odometer_km: 10000, full: true,
              interval: { km: 15, l100: 40, cost: null, litres: 6, source: "gps", usable: false } },
        ],
    },
};

for (const theme of ["heritage", "modern", "autodelta"]) {
    const html = draw(theme, FULL);
    assert.ok(html.includes("data-fuel-panel"), `${theme}: no panel`);
    assert.ok(html.includes('data-fuel-action="refuel"') && html.includes("Zatankowano"), theme);
    assert.ok(html.includes("6.8") && html.includes("7.0") && html.includes("43.20"), theme);
    assert.ok(html.includes('data-fuel-row="3"') && html.includes('data-fuel-row="1"'), theme);
    assert.ok(html.includes("7.0 l/100 · 500 km (licznik) · 217.00 zł"), theme);
    assert.ok(html.includes("częściowe") && html.includes("pominięte"), theme);
    assert.ok(html.includes('data-fuel-action="delete" data-fuel-id="3"'), theme);
    // No made-up chart and no instant consumption without OBD.
    assert.ok(!html.includes("-30m") && !html.includes("4.2"), `${theme}: fake chart left`);
    if (theme !== "autodelta") {     // autodelta has no "Now" field
        assert.ok(/id="trip-instant"[^>]*>—</.test(html), `${theme}: instant not "—"`);
    }
}

// No source yet: "—", never 0.
let html = draw("autodelta", { avg_consumption: null, estimated_range: null,
                               fuel_log: { enabled: true, running: true, status: "need_second_full",
                                           recent: [] } });
assert.ok(/id="trip-avg-cons">—</.test(html) && /id="trip-range">—</.test(html), html);
assert.ok(html.includes("zatankuj do pełna jeszcze raz"), html);
assert.ok(!html.includes('data-fuel-action="delete"'), "nothing to delete");

// Module off: one line, no button.
html = draw("modern", { fuel_log: { enabled: false, running: false } });
assert.ok(html.includes('data-fuel-state="off"') && !html.includes('data-fuel-action="refuel"'));
html = draw("modern", {});
assert.ok(html.includes('data-fuel-state="off"'));

// Toggle on, module not running (tracking off / start failed): do not send
// the driver to the fuel_log toggle that is already on.
html = draw("modern", { fuel_log: { enabled: true, running: false } });
assert.ok(html.includes('data-fuel-state="blocked"') && html.includes("wymaga modułu tracking"), html);
assert.ok(!html.includes('data-fuel-state="off"') && !html.includes('data-fuel-action="refuel"'));

// "No average" statuses each say why.
for (const [st, text] of [["need_first_full", "brak tankowania do pełna"],
                          ["no_distance", "wpisz stan licznika"],
                          ["intervals_skipped", "odcinki pominięte"]]) {
    html = draw("heritage", { fuel_log: { enabled: true, running: true, status: st, recent: [] } });
    assert.ok(html.includes(text), st + ": " + html);
    assert.ok(!html.includes("zatankuj do pełna jeszcze raz"), st);
}

// Values are numbers only, but an id is still escaped.
html = draw("heritage", { fuel_log: { enabled: true, running: true, status: "ok",
    recent: [{ id: '"><img src=x onerror=1>', ts: "x", litres: "<b>", full: true }] } });
assert.ok(!html.includes("<img") && !html.includes("<b>"), html);

// Read-only database: no entry, no delete.
html = draw("heritage", { fuel_log: { ...FULL.fuel_log, read_only: true } });
assert.ok(/data-fuel-action="refuel" disabled/.test(html) && !html.includes('data-fuel-action="delete"'));

process.stdout.write("ok\n");
