// Smoke test of app.js + appbar.js in a node vm with DOM stubs, for
// tests/test_frontend_gestures.py. Plain node + assert, no packages.
// Exits non-zero (assert) on failure; prints "ok" on success.
"use strict";
const assert = require("assert");
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const WEB = path.join(__dirname, "..", "..", "src", "dashboard", "web", "js");
const G = require(path.join(WEB, "components", "gestures.js"));

function makeEl(id) {
    const classes = new Set();
    return {
        id, innerHTML: "", style: {}, writes: 0, _text: "",
        get textContent() { return this._text; },
        set textContent(v) { this.writes++; this._text = String(v); },
        classList: { add: (...c) => c.forEach((x) => classes.add(x)),
                     remove: (...c) => c.forEach((x) => classes.delete(x)),
                     contains: (c) => classes.has(c) },
        setAttribute() {}, appendChild() {}, remove() {},
        querySelector() { return null; }, querySelectorAll() { return []; },
    };
}

const elements = {};
const el = (id) => elements[id] || (elements[id] = makeEl(id));
const docListeners = {};
const intervals = [];
let now = 0;
let overlayOpen = false;
const appbarNodes = { time: makeEl("t"), date: makeEl("d"), ext_temp: makeEl("e") };

const ctx = {
    console, setTimeout, clearTimeout, Promise, JSON, Math, Date,
    setInterval: (fn, ms) => { intervals.push({ fn, ms }); return intervals.length; },
    clearInterval() {},
    requestAnimationFrame: () => 0,
    performance: { now: () => now },
    localStorage: {
        _s: {},
        getItem(k) { return Object.prototype.hasOwnProperty.call(this._s, k) ? this._s[k] : null; },
        setItem(k, v) { this._s[k] = String(v); },
    },
    fetch: async (url) => ({
        ok: true,
        json: async () => (url === "/api/boot_mode" ? { boot_mode: "cold" } : {}),
    }),
    DataStore: { init() {}, subscribe() {}, unsubscribe() {}, getAll: () => ({ ext_temp: 21.4 }),
                 get() {}, sendKey() {}, sendAATouch() {} },
};
ctx.document = {
    body: el("body"),
    hidden: false,
    activeElement: null,
    getElementById: el,
    addEventListener: (type, fn) => { (docListeners[type] = docListeners[type] || []).push(fn); },
    querySelector: (sel) => {
        const m = /^\[data-bind="(\w+)"\]$/.exec(sel);
        if (m) return appbarNodes[m[1]] || null;
        return overlayOpen ? makeEl("overlay") : null;
    },
};
ctx.window = { addEventListener() {}, innerHeight: 600, BCMGestures: G, document: ctx.document };
vm.createContext(ctx);

for (const file of ["app.js", path.join("components", "appbar.js")]) {
    vm.runInContext(fs.readFileSync(path.join(WEB, file), "utf8"), ctx, { filename: file });
}
vm.runInContext("this.__App = App; this.__AppBar = AppBar;", ctx);
const App = ctx.__App;
const AppBar = ctx.__AppBar;

const rendered = [];
for (const s of ["init", "a1", "a2", "a3", "a4", "settings"]) {
    App.registerScreen(s, { render: () => rendered.push(s) });
}

function touch(target, x0, y0, x1, y1, dtMs) {
    const tgt = target || { tagName: "DIV", closest: () => null };
    now = 1000;
    docListeners.touchstart.forEach((fn) => fn({ touches: [{ clientX: x0, clientY: y0 }], target: tgt }));
    now = 1000 + dtMs;
    docListeners.touchend.forEach((fn) => fn({ changedTouches: [{ clientX: x1, clientY: y1 }], target: tgt }));
}

(async () => {
    await App.init();
    assert.strictEqual(App.getCurrentScreen(), "a1");

    // navCycleNext: A1 → A2 → A3 → A4 → A1
    const seq = [];
    for (let i = 0; i < 4; i++) { App.navCycleNext(); seq.push(App.getCurrentScreen()); }
    assert.deepStrictEqual(seq, ["a2", "a3", "a4", "a1"]);

    // From Settings: back to the last A-screen
    App.navigateTo("a3");
    App.navigateTo("settings");
    App.navCycleNext();
    assert.strictEqual(App.getCurrentScreen(), "a3");

    // Pull-down from the top edge → next screen (evaluated on touchend)
    touch(null, 500, 10, 505, 150, 300);
    assert.strictEqual(App.getCurrentScreen(), "a4");
    // Too slow → nothing
    touch(null, 500, 10, 505, 150, 1500);
    assert.strictEqual(App.getCurrentScreen(), "a4");
    // Started below the edge → nothing
    touch(null, 500, 200, 505, 400, 200);
    assert.strictEqual(App.getCurrentScreen(), "a4");
    // Horizontal swipes no longer change screens
    touch(null, 800, 300, 200, 310, 200);
    touch(null, 200, 300, 800, 310, 200);
    assert.strictEqual(App.getCurrentScreen(), "a4");
    // On the AA overlay the global handler stays out (A2 runs its own)
    const onAA = { tagName: "DIV", closest: (sel) => (sel === "#aa-touch-overlay" ? {} : null) };
    touch(onAA, 500, 10, 505, 150, 300);
    assert.strictEqual(App.getCurrentScreen(), "a4");
    // Starting on a button / input → nothing
    touch({ tagName: "BUTTON", closest: () => null }, 500, 10, 505, 150, 300);
    touch({ tagName: "INPUT", closest: () => null }, 500, 10, 505, 150, 300);
    assert.strictEqual(App.getCurrentScreen(), "a4");
    // A modal/overlay is open → nothing
    overlayOpen = true;
    touch(null, 500, 10, 505, 150, 300);
    assert.strictEqual(App.getCurrentScreen(), "a4");
    overlayOpen = false;

    // Bottom-edge swipe up → NavBar shown; a tap there does not
    touch(null, 500, 590, 500, 585, 100);
    assert.strictEqual(el("bcm-navbar").classList.contains("bcm-navbar-shown"), false);
    touch(null, 500, 590, 505, 500, 200);
    assert.strictEqual(el("bcm-navbar").classList.contains("bcm-navbar-shown"), true);

    // Clock: a 1 s interval refreshes the AppBar
    const clock = intervals.find((i) => i.ms === 1000);
    assert.ok(clock, "clock interval not started");
    clock.fn();
    assert.match(appbarNodes.time.textContent, /^([01]\d|2[0-3]):[0-5]\d$/);
    assert.strictEqual(appbarNodes.ext_temp.textContent, "21°C");
    const before = { t: appbarNodes.time.writes, d: appbarNodes.date.writes,
                     e: appbarNodes.ext_temp.writes };
    clock.fn();   // nothing changed → no DOM writes (a minute/day may tick over)
    assert.strictEqual(appbarNodes.ext_temp.writes, before.e);
    assert.ok(appbarNodes.time.writes - before.t <= 1);
    assert.ok(appbarNodes.date.writes - before.d <= 1);
    assert.ok(docListeners.visibilitychange && docListeners.visibilitychange.length === 1);

    // AppBar.update tolerates containers without querySelector
    AppBar.update(null, {});
    AppBar.update({}, {});

    process.stdout.write("ok");
})().catch((e) => { console.error(e); process.exit(1); });
