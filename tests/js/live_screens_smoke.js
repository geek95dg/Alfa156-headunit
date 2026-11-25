// A5 (screens/service.js) and A7 (screens/performance.js) with
// components/live.js, for tests/test_frontend_gestures.py: no reading →
// "—" + "brak danych" and the A5 badge "brak danych z auta" (never the old
// 12.6 V / 2.4 bar / 4500 km / "All OK" placeholders); real readings shown
// with their source tag; warning thresholds; garbage entries ignored.
// Plain node + assert in a vm with DOM stubs. Prints "ok" on success.
"use strict";
const assert = require("assert");
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const WEB = path.join(__dirname, "..", "..", "src", "dashboard", "web", "js");
const screens = {};
const els = {};
function el(id) {
    if (!els[id]) {
        const attrs = {};
        els[id] = { id, textContent: "", style: {}, getAttribute: (k) => (k in attrs ? attrs[k] : null),
                    setAttribute: (k, v) => { attrs[k] = String(v); } };
    }
    return els[id];
}
const ctx = {
    console, Math, Number, Array, Object, String, JSON,
    App: { registerScreen(n, impl) { screens[n] = impl; }, t: (k, d) => d || k, navigateTo() {} },
    AppBar: { render: () => "" }, NavBar: { render: () => "" },
};
ctx.document = { getElementById: (id) => el(id) };
vm.createContext(ctx);
for (const f of ["components/live.js", "screens/service.js", "screens/performance.js"]) {
    vm.runInContext(fs.readFileSync(path.join(WEB, f), "utf8"), ctx, { filename: f });
}
vm.runInContext("this.__Live = Live;", ctx);
const Live = ctx.__Live;

// ── Live helpers ─────────────────────────────────────────────────────────
assert.strictEqual(Live.get({}, "coolant"), null);
assert.strictEqual(Live.get({ live: { coolant: { v: "88" } } }, "coolant"), null, "string rejected");
assert.strictEqual(Live.get({ live: { tpms: { v: [2, 2, null, 2] } } }, "tpms"), null);
assert.strictEqual(Live.fmt(null, 1, "V"), "—");
assert.strictEqual(Live.fmt({ v: 12.44 }, 1, "V"), "12.4V");
assert.strictEqual(Live.src({ v: 1, src: "gps" }), "GPS");
assert.strictEqual(Live.src({ v: 1, src: "<b>" }), "", "unknown source code never shown");
assert.strictEqual(Live.JUDGE.coolant(106), "bad");
assert.strictEqual(Live.JUDGE.battery_v(12.0), "warn");
assert.strictEqual(Live.JUDGE.tpms([2.2, 2.2, 1.9, 2.2]), "warn");
assert.strictEqual(Live.overall({}).level, "none");
assert.strictEqual(Live.overall({ live: { coolant: { v: 90, src: "obd" } } }).text, "WSZYSTKO OK · 1/5");
assert.strictEqual(Live.overall({ live: { coolant: { v: 90 }, battery_v: { v: 11.5 } } }).level, "bad");

// ── A5 without data: nothing made up ─────────────────────────────────────
for (const theme of ["heritage", "modern", "autodelta"]) {
    const c = { innerHTML: "" };
    screens.a5.render(c, theme, {});
    assert.ok(!/12\.6|2\.4|4500|All OK/.test(c.innerHTML), `${theme}: no placeholder values in markup`);
    assert.ok(c.innerHTML.includes('id="svc-badge"'));
}
screens.a5.update({ coolant_temp: 0, battery_voltage: 12.6, tpms_pressures: [0, 0, 0, 0], service_km: 4500 });
assert.strictEqual(el("svc-temp").textContent, "—");
assert.strictEqual(el("svc-battery").textContent, "—");
assert.strictEqual(el("svc-tire-fl").textContent, "—");
assert.strictEqual(el("svc-km").textContent, "—");
assert.strictEqual(el("svc-temp-st").textContent, "brak danych");
assert.strictEqual(el("svc-badge").textContent, "brak danych z auta");

// ── A5 with readings ─────────────────────────────────────────────────────
screens.a5.update({ live: { coolant: { v: 107, src: "obd" }, battery_v: { v: 12.7, src: "batt" },
                            tpms: { v: [2.3, 2.3, 2.2, 1.8], src: "tpms" }, service_km: { v: 3200, src: "service" } } });
assert.strictEqual(el("svc-temp").textContent, "107°C");
assert.strictEqual(el("svc-temp-src").textContent, "· OBD");
assert.strictEqual(el("svc-temp-st").getAttribute("data-color"), Live.COLORS.bad);
assert.strictEqual(el("svc-battery").textContent, "12.7V");
assert.strictEqual(el("svc-tire-rr").textContent, "1.8");
assert.strictEqual(el("svc-tires-st").getAttribute("data-color"), Live.COLORS.warn);
assert.strictEqual(el("svc-km").textContent, "3200");
assert.strictEqual(el("svc-badge").getAttribute("data-color"), Live.COLORS.bad);

// ── A7 ───────────────────────────────────────────────────────────────────
const c7 = { innerHTML: "" };
screens.a7.render(c7, "heritage", { speed: 0, rpm: 0, boost: 0, battery_voltage: 12.6 });
assert.ok(!/12\.6/.test(c7.innerHTML), "no placeholder voltage");
assert.strictEqual(el("perf-speed").textContent, "—");
assert.strictEqual(el("perf-rpm").textContent, "—");
assert.strictEqual(el("perf-volt").textContent, "—");
assert.strictEqual(el("perf-boost-note").textContent, "doładowanie i obroty: potrzebne OBD");
screens.a7.update({ live: { speed: { v: 87.4, src: "gps" }, g_h: { v: 0.31, src: "phone" },
                            timer_last: { v: 12.3, src: "gps" } } });
assert.strictEqual(el("perf-speed").textContent, "87");
assert.strictEqual(el("perf-speed-src").textContent, "· GPS");
assert.strictEqual(el("perf-g").textContent, "0.31");
assert.strictEqual(el("perf-timer").textContent, "12.3 s");
screens.a7.update({ live: { timer_last: { v: 10.9, src: "gps" } } });
screens.a7.update({ live: { timer_last: { v: 13.0, src: "gps" } } });
assert.strictEqual(el("perf-best").textContent, "Best: 10.9 s", "best of the session");
assert.strictEqual(el("perf-speed").textContent, "—", "speed gone → dash again");

process.stdout.write("ok\n");
