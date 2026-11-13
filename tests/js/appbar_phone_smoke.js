// Top-bar phone cluster (components/appbar.js, data.phone_status from
// src/multimedia/phone_status.py), for tests/test_frontend_gestures.py.
// Plain node + assert, no packages: the pure helpers directly, render() as a
// string and update() against a small fake DOM. Exits non-zero on failure,
// prints "ok" on success.
"use strict";
const assert = require("assert");
const path = require("path");

const WEB = path.join(__dirname, "..", "..", "src", "dashboard", "web", "js");
// appbar.js reads App.t / App.getConfig lazily (date, temperature unit).
global.App = { t: (k) => k.toUpperCase(), getConfig: () => ({ temp_unit: "C" }) };
const AppBar = require(path.join(WEB, "components", "appbar.js"));

// ── pure helpers ─────────────────────────────────────────────────────────
const SIGNAL = [
    [0, null, "signal_cellular_0_bar"], [20, null, "signal_cellular_1_bar"],
    [40, "registered", "signal_cellular_2_bar"], [60, "roaming", "signal_cellular_2_bar"],
    [80, "registered", "signal_cellular_3_bar"], [100, "unknown", "signal_cellular_4_bar"],
    [80, "searching", "signal_cellular_off"], [null, "denied", "signal_cellular_off"],
    [50, "unregistered", "signal_cellular_off"],
    [null, "registered", null], [undefined, null, null], [-1, null, null], [101, null, null],
    ["80", null, null], [NaN, null, null], [Infinity, null, null],
];
for (const [pct, reg, want] of SIGNAL) {
    assert.strictEqual(AppBar.signalIcon(pct, reg), want, `signalIcon(${pct}, ${reg})`);
}
const BATTERY = [
    [0, "battery_0_bar"], [14, "battery_0_bar"], [15, "battery_1_bar"], [20, "battery_1_bar"],
    [40, "battery_2_bar"], [60, "battery_4_bar"], [80, "battery_5_bar"], [99, "battery_6_bar"],
    [100, "battery_full"], [null, null], [-5, null], [150, null], ["60", null], [NaN, null],
];
for (const [pct, want] of BATTERY) {
    assert.strictEqual(AppBar.batteryIcon(pct), want, `batteryIcon(${pct})`);
}
// Every glyph the cluster can ask for (tests/test_frontend_gestures.py checks
// these names against the bundled font's ligature table).
const glyphs = new Set();
for (let p = 0; p <= 100; p++) { glyphs.add(AppBar.signalIcon(p, null)); glyphs.add(AppBar.batteryIcon(p)); }
glyphs.add(AppBar.signalIcon(50, "searching"));

const AVAILABLE = {
    available: true, battery_pct: 60, signal_pct: 80, operator: "Orange PL",
    registration: "registered", roaming: false, source: "ofono",
};
const HIDDEN = [
    {}, { phone_status: null }, { phone_status: "x" }, { phone_status: { available: false } },
    { phone_status: { available: "true", battery_pct: 50 } },
    // available, but nothing displayable
    { phone_status: { available: true, battery_pct: null, signal_pct: null, operator: null,
                      registration: "registered", source: "ofono" } },
];
for (const data of HIDDEN) {
    assert.strictEqual(AppBar.phoneView(data).visible, false, JSON.stringify(data));
}
assert.strictEqual(AppBar.phoneView(undefined).visible, false);
let view = AppBar.phoneView({ phone_status: AVAILABLE });
assert.deepStrictEqual(JSON.parse(JSON.stringify(view)), {
    visible: true, signal: "signal_cellular_3_bar", operator: "Orange PL", roaming: false,
    battery: "battery_4_bar", batteryText: "60%", low: false,
});
view = AppBar.phoneView({ phone_status: { ...AVAILABLE, battery_pct: 10, roaming: true,
                                          operator: "X".repeat(80) } });
assert.strictEqual(view.low, true);
assert.strictEqual(view.roaming, true);
assert.strictEqual(view.operator.length, 24);
view = AppBar.phoneView({ phone_status: { available: true, battery_pct: 45, source: "bluez" } });
assert.strictEqual(view.visible, true);
assert.strictEqual(view.signal, null);
assert.strictEqual(view.operator, "");

// ── render(): skeleton only, never the operator text ────────────────────
const EVIL = "<img src=x onerror=alert(1)>";
let html = AppBar.render("heritage", { bt_connected: true });
assert.ok(html.includes('data-bind="phone"'), "cluster skeleton always present");
assert.ok(/data-bind="phone" style="display:none;/.test(html), "hidden without a phone");
assert.ok(!/data-bind="bar_left" style=/.test(html), "no width change without a phone: " + html);
assert.ok(!/data-bind="bar_right"[^>]*style=/.test(html));

html = AppBar.render("modern", { phone_status: { ...AVAILABLE, operator: EVIL } });
assert.ok(/data-bind="phone_battery" data-low="" style="(?![^"]*color)/.test(html), html);
assert.ok(/data-bind="phone" style="display:inline-flex;/.test(html), html);
assert.ok(html.includes('data-bind="bar_left" style="width:340px"'), html);
assert.ok(/data-bind="bar_right" style="width:340px"/.test(html), html);
assert.ok(!html.includes("<img src=x") && !html.includes("alert(1)"), "operator text in markup");
assert.ok(/data-bind="phone_operator" style="[^"]*"><\/span>/.test(html), "operator span not empty");
assert.ok(html.includes(">signal_cellular_3_bar<") && html.includes(">battery_4_bar<"), html);
assert.ok(html.includes(">60%<"), html);
const lowHtml = AppBar.render("heritage", { phone_status: { ...AVAILABLE, battery_pct: 5 } });
assert.ok(/data-bind="phone_battery" data-low="1" style="[^"]*color:#dc2626;/.test(lowHtml), lowHtml);
// No new Tailwind classes: the cluster uses only classes the bar already had.
const cluster = html.slice(html.indexOf('data-bind="phone"'), html.indexOf("</div>", html.indexOf('data-bind="phone"')));
const used = new Set((cluster.match(/class="([^"]*)"/g) || [])
    .flatMap((c) => c.slice(7, -1).split(/\s+/)));
for (const c of used) {
    assert.ok(["material-symbols-outlined", "text-zinc-600", "text-xs", "font-bold"].includes(c),
              "unexpected class " + c);
}

// ── update(): change-only writes, textContent for the operator ──────────
// Like a browser, the fake style reads colours back normalised ("#dc2626"
// -> "rgb(220, 38, 38)"), so code comparing el.style.color with the value it
// wrote would rewrite it every second — the change-only check must catch it.
function cssColor(value) {
    const m = /^#([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i.exec(String(value));
    return m ? `rgb(${parseInt(m[1], 16)}, ${parseInt(m[2], 16)}, ${parseInt(m[3], 16)})` : value;
}
const LOW_RGB = "rgb(220, 38, 38)";
function fakeEl(name) {
    const style = {};
    const attrs = {};
    const counts = { style: 0, text: 0, attr: 0 };
    const el = {
        name, counts, _text: "",
        style: new Proxy(style, {
            // An unset inline property reads as "" in a browser.
            get(target, prop) { return prop in target ? target[prop] : ""; },
            set(target, prop, value) {
                counts.style++;
                target[prop] = prop === "color" ? cssColor(value) : value;
                return true;
            },
        }),
        getAttribute(n) { return Object.prototype.hasOwnProperty.call(attrs, n) ? attrs[n] : null; },
        setAttribute(n, v) { counts.attr++; attrs[n] = String(v); },
        get textContent() { return this._text; },
        set textContent(v) { counts.text++; this._text = String(v); },
        set innerHTML(v) { throw new Error("innerHTML written on " + name); },
        children: {},
        querySelector(sel) {
            const m = /^\[data-bind="(\w+)"\]$/.exec(sel);
            return (m && this.children[m[1]]) || null;
        },
    };
    return el;
}
const nodes = {};
for (const n of ["time", "date", "ext_temp", "bar_left", "bar_right", "phone"]) nodes[n] = fakeEl(n);
for (const n of ["phone_signal", "phone_roaming", "phone_operator", "phone_battery",
                 "phone_battery_pct"]) {
    nodes.phone.children[n] = nodes[n] = fakeEl(n);
}
// As rendered without a phone.
nodes.phone.style.display = "none";
const doc = {
    querySelector(sel) {
        const m = /^\[data-bind="(\w+)"\]$/.exec(sel);
        return m && !(m[1] in nodes.phone.children) ? nodes[m[1]] || null : null;
    },
};
// DOM writes on the cluster and the two side blocks (the clock's own
// time/date nodes may tick over a minute boundary and are not counted).
const PHONE_NODES = ["bar_left", "bar_right", "phone", "phone_signal", "phone_roaming",
                     "phone_operator", "phone_battery", "phone_battery_pct"];
const totals = () => PHONE_NODES.reduce(
    (s, n) => s + nodes[n].counts.style + nodes[n].counts.text + nodes[n].counts.attr, 0);

AppBar.update(doc, { phone_status: null });
assert.strictEqual(nodes.phone.style.display, "none");
assert.ok(!nodes.bar_left.style.width && !nodes.bar_right.style.width);
assert.strictEqual(nodes.phone_operator.counts.text, 0);

AppBar.update(doc, { phone_status: { ...AVAILABLE, operator: EVIL } });
assert.strictEqual(nodes.phone.style.display, "inline-flex");
assert.strictEqual(nodes.bar_left.style.width, "340px");
assert.strictEqual(nodes.bar_right.style.width, "340px");
assert.strictEqual(nodes.phone_operator.textContent, EVIL.slice(0, 24), "operator via textContent, verbatim");
assert.strictEqual(nodes.phone_operator.style.display, "inline-block");
assert.strictEqual(nodes.phone_signal.textContent, "signal_cellular_3_bar");
assert.strictEqual(nodes.phone_battery.textContent, "battery_4_bar");
assert.strictEqual(nodes.phone_battery_pct.textContent, "60%");
assert.strictEqual(nodes.phone_roaming.style.display, "none");
assert.strictEqual(nodes.phone_battery.style.color, "");

// Same data again: not a single DOM write (the clock calls this every second).
const before = totals();
AppBar.update(doc, { phone_status: { ...AVAILABLE, operator: EVIL } });
assert.strictEqual(totals(), before, "phone cluster rewritten without a change");

// Roaming, low battery, no signal reported, new operator.
AppBar.update(doc, { phone_status: { ...AVAILABLE, signal_pct: null, battery_pct: 8,
                                     roaming: true, operator: "Vodafone" } });
assert.strictEqual(nodes.phone_signal.style.display, "none");
assert.strictEqual(nodes.phone_roaming.style.display, "inline");
assert.strictEqual(nodes.phone_battery.style.color, LOW_RGB);
assert.strictEqual(nodes.phone_battery.getAttribute("data-low"), "1");
assert.strictEqual(nodes.phone_battery.textContent, "battery_0_bar");
assert.strictEqual(nodes.phone_battery_pct.textContent, "8%");
assert.strictEqual(nodes.phone_operator.textContent, "Vodafone");
// Low battery unchanged: still no DOM write per clock tick (the browser
// reads the colour back as rgb(), which must not count as a change).
const lowBefore = totals();
AppBar.update(doc, { phone_status: { ...AVAILABLE, signal_pct: null, battery_pct: 8,
                                     roaming: true, operator: "Vodafone" } });
assert.strictEqual(totals(), lowBefore, "low-battery colour rewritten without a change");
assert.strictEqual(nodes.phone_battery.style.color, LOW_RGB);

// Battery only (BlueZ fallback): operator hidden and emptied.
AppBar.update(doc, { phone_status: { available: true, battery_pct: 100, source: "bluez" } });
assert.strictEqual(nodes.phone_operator.style.display, "none");
assert.strictEqual(nodes.phone_operator.textContent, "");
assert.strictEqual(nodes.phone_battery.textContent, "battery_full");
assert.strictEqual(nodes.phone_battery.style.color, "");
assert.strictEqual(nodes.phone_battery.getAttribute("data-low"), "");

// Phone gone: hidden, bar back to its normal width.
AppBar.update(doc, { phone_status: { available: false } });
assert.strictEqual(nodes.phone.style.display, "none");
assert.strictEqual(nodes.bar_left.style.width, "");
assert.strictEqual(nodes.bar_right.style.width, "");

// Containers without the cluster (A2) or without querySelector never throw.
AppBar.update({ querySelector: () => null }, { phone_status: AVAILABLE });
AppBar.update(null, {});
AppBar.update({}, {});

process.stdout.write(JSON.stringify([...glyphs].sort()) + "\nok");
