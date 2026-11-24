// screens/main.js A1 side bars for tests/test_frontend_gestures.py: the pure
// view() that maps data.a1_gauges to fill / colour / text, and the HTML the
// three themes render. Checked: no source → grey "brak danych" and an empty
// bar (never the old 50 % / 0 °C payload defaults); fuel zones (< 15 % red,
// < 25 % amber); the refuel-log estimate is marked "szac." with litres;
// demo data is marked "demo"; coolant zones (< 60 °C blue, 80–100 green,
// 100–105 amber, > 105 red) and the 40–130 °C bar scale; garbage payloads.
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
        els[id] = { id, textContent: "", style: {},
                    getAttribute: (k) => (k in attrs ? attrs[k] : null),
                    setAttribute: (k, v) => { attrs[k] = String(v); } };
    }
    return els[id];
}
const sandbox = {
    console, Math, Number, Array, Object, String, JSON, Date, setTimeout, clearTimeout,
    App: { registerScreen(name, impl) { screens[name] = impl; }, navigateTo() {},
           t: (k, d) => d },
    AppBar: { render: () => "" },
    NavBar: { render: () => "" },
    MediaPlayer: { renderHeritage: () => "", renderModern: () => "", renderAutodelta: () => "" },
    document: { getElementById: (id) => (id.startsWith("a1-") ? el(id) : null), activeElement: null },
    requestAnimationFrame: () => 0, cancelAnimationFrame: () => {},
};
sandbox.window = { devicePixelRatio: 1 };
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(path.join(WEB, "screens", "main.js"), "utf8"), sandbox,
                { filename: "main.js" });
const A1 = screens.a1;
const view = A1._gauges.view;

// ── no source ────────────────────────────────────────────────────────────
for (const g of [undefined, null, {}, { source: "none", pct: 50 }, { source: "sensor" },
                 { source: "sensor", pct: "50" }, { source: "sensor", pct: NaN }]) {
    const v = view("fuel", g);
    assert.strictEqual(v.state, "none", JSON.stringify(g));
    assert.strictEqual(v.fill, 0);
    assert.strictEqual(v.value, "—");
    assert.strictEqual(v.note, "brak danych");
}
for (const g of [undefined, {}, { source: "none", c: 90 }, { source: "sensor", c: null }]) {
    const v = view("coolant", g);
    assert.strictEqual(v.state, "none");
    assert.strictEqual(v.value, "—");
}

// ── fuel ─────────────────────────────────────────────────────────────────
let v = view("fuel", { source: "sensor", pct: 62 });
assert.deepStrictEqual([v.fill, v.value, v.note, v.state, v.color], [62, "62%", "", "ok", null]);
v = view("fuel", { source: "sensor", pct: 20 });
assert.strictEqual(v.color, "#f59e0b", "amber below 25 %");
v = view("fuel", { source: "sensor", pct: 14 });
assert.deepStrictEqual([v.color, v.state], ["#ef4444", "low"]);
v = view("fuel", { source: "sensor", pct: 140 });
assert.strictEqual(v.fill, 100, "clamped");
v = view("fuel", { source: "estimate", pct: 40, litres: 23.4 });
assert.strictEqual(v.note, "szac. 23 l");
assert.strictEqual(v.estimate, true);
v = view("fuel", { source: "demo", pct: 50 });
assert.strictEqual(v.note, "demo");

// ── coolant ──────────────────────────────────────────────────────────────
const zone = (c) => view("coolant", { source: "sensor", c });
assert.deepStrictEqual([zone(30).color, zone(30).state], ["#3b82f6", "cold"]);
assert.strictEqual(zone(59).state, "cold");
assert.strictEqual(zone(70).state, "warming");
assert.deepStrictEqual([zone(90).color, zone(90).state, zone(90).value], ["#22c55e", "ok", "90°"]);
assert.strictEqual(zone(100).state, "ok");
assert.strictEqual(zone(103).state, "warm");
assert.deepStrictEqual([zone(106).color, zone(106).state], ["#ef4444", "hot"]);
assert.strictEqual(zone(40).fill, 0);
assert.strictEqual(zone(130).fill, 100);
assert.ok(Math.abs(zone(85).fill - 50) < 1e-9, "85 °C is mid-scale");
assert.strictEqual(zone(-20).fill, 0, "clamped low");
assert.strictEqual(view("coolant", { source: "demo", c: 88 }).note, "demo");

// ── HTML in all three themes + live apply ────────────────────────────────
for (const theme of ["heritage", "modern", "autodelta"]) {
    const c = { innerHTML: "" };
    A1.render(c, theme, {});
    for (const kind of ["fuel", "coolant"]) {
        assert.ok(c.innerHTML.includes(`id="a1-${kind}-gauge"`), `${theme}: ${kind} bar`);
        assert.ok(c.innerHTML.includes(`id="a1-${kind}-fill"`));
    }
    assert.ok(c.innerHTML.indexOf("a1-fuel-gauge") < c.innerHTML.indexOf("a1-coolant-gauge"),
              "fuel left, coolant right");
}
// Payload without a1_gauges (old backend): grey, never 50 %.
A1.update({ fuel_level: 50, coolant_temp: 0 }, "heritage");
assert.strictEqual(el("a1-fuel-val").textContent, "—");
assert.strictEqual(el("a1-fuel-fill").style.height, "0.0%");
assert.strictEqual(el("a1-coolant-note").textContent, "brak danych");
A1.update({ a1_gauges: { fuel: { source: "sensor", pct: 10 }, coolant: { source: "sensor", c: 110 } } },
          "heritage");
assert.strictEqual(el("a1-fuel-val").textContent, "10%");
assert.strictEqual(el("a1-fuel-fill").style.height, "10.0%");
assert.strictEqual(el("a1-fuel-fill").style.backgroundColor, "#ef4444");
assert.strictEqual(el("a1-fuel-gauge").getAttribute("data-state"), "low");
assert.strictEqual(el("a1-coolant-val").textContent, "110°");
assert.strictEqual(el("a1-coolant-gauge").getAttribute("data-state"), "hot");

process.stdout.write("ok\n");
