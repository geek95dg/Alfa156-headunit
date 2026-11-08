// Smoke test of screens/android_auto.js (A2) in a node vm with DOM stubs
// and fake timers, for tests/test_frontend_gestures.py: stream lifecycle
// and reconnect triggers, pointer → sendAATouch, edge gestures, unmount.
// Plain node + assert, no packages. Prints "ok" on success.
"use strict";
const assert = require("assert");
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const WEB = path.join(__dirname, "..", "..", "src", "dashboard", "web", "js");

// ── fake clock / timers / rAF ────────────────────────────────────────────
let clock = 0;
let timers = [];
let nextId = 1;
function setTimeout_(fn, ms) { const id = nextId++; timers.push({ id, at: clock + (ms || 0), fn }); return id; }
function clearTimeout_(id) { timers = timers.filter((t) => t.id !== id); }
const intervals = new Map();
function setInterval_(fn, ms) { const id = nextId++; intervals.set(id, { fn, ms }); return id; }
function clearInterval_(id) { intervals.delete(id); }
let rafQueue = [];
function advance(ms) {
    const end = clock + ms;
    for (;;) {
        timers.sort((a, b) => a.at - b.at);
        const t = timers[0];
        if (!t || t.at > end) break;
        timers.shift();
        clock = t.at;
        t.fn();
    }
    clock = end;
}
function frame() { const q = rafQueue; rafQueue = []; q.forEach((f) => f()); }

// ── DOM stubs ────────────────────────────────────────────────────────────
function makeEl(id) {
    const listeners = {};
    const options = {};
    return {
        id, innerHTML: "", textContent: "", style: {}, src: "", listeners, options,
        addEventListener(t, fn, opts) {
            (listeners[t] = listeners[t] || []).push(fn);
            options[t] = opts;
        },
        removeEventListener(t, fn) { listeners[t] = (listeners[t] || []).filter((f) => f !== fn); },
        getBoundingClientRect: () => ({ left: 0, top: 0, width: 1000, height: 600 }),
        setPointerCapture() {}, releasePointerCapture() {},
        fire(t, ev) { (listeners[t] || []).slice().forEach((fn) => fn(ev)); },
    };
}
const elements = {};
const el = (id) => elements[id] || (elements[id] = makeEl(id));

let data = { aa_status: "running", aa_stream_epoch: 100, aa_auto_restart: true };
const sent = [];
const subs = {};
const appCalls = [];
let renderer = null;

const ctx = {
    console, Math, JSON, Promise,
    setTimeout: setTimeout_, clearTimeout: clearTimeout_,
    setInterval: setInterval_, clearInterval: clearInterval_,
    requestAnimationFrame: (fn) => { rafQueue.push(fn); return rafQueue.length; },
    cancelAnimationFrame: () => { rafQueue = []; },
    performance: { now: () => clock },
    Date: { now: () => 1700000000000 + clock },
    document: { getElementById: el },
    App: {
        registerScreen: (name, r) => { renderer = r; },
        t: (k, fb) => fb || k,
        navCycleNext: () => appCalls.push("navCycleNext"),
        showNavBar: () => appCalls.push("showNavBar"),
    },
    NavBar: { render: () => "" },
    DataStore: {
        getAll: () => ({ ...data }),
        subscribe: (k, cb) => { (subs[k] = subs[k] || []).push(cb); },
        unsubscribe: (k, cb) => { subs[k] = (subs[k] || []).filter((f) => f !== cb); },
        sendAATouch: (a, x, y) => { sent.push([a, x, y]); return true; },
    },
};
ctx.window = {};
vm.createContext(ctx);
// gestures.js runs inside the context too, so its hold timer uses the fake
// setTimeout (exactly as in the browser, where both share one window).
for (const file of [path.join("components", "gestures.js"), path.join("screens", "android_auto.js")]) {
    vm.runInContext(fs.readFileSync(path.join(WEB, file), "utf8"), ctx, { filename: file });
}
assert.ok(ctx.window.BCMGestures, "gestures.js did not attach to window");
assert.ok(renderer && renderer.mount && renderer.update && renderer.unmount);

const container = { innerHTML: "" };
renderer.render(container, "heritage", data);
assert.ok(!/src="\/aa\/stream"/.test(container.innerHTML), "img must not carry a static src");
assert.ok(container.innerHTML.includes('id="aa-touch-overlay"'));
renderer.mount();

const img = el("aa-stream");
const overlay = el("aa-touch-overlay");
assert.match(img.src, /^\/aa\/stream\?ts=\d+$/);
// Chromium's own touch gestures (long-press context menu) are blocked on
// the overlay: touchstart must be non-passive, and both must cancel.
assert.strictEqual((overlay.listeners.touchstart || []).length, 1);
assert.strictEqual((overlay.listeners.contextmenu || []).length, 1);
assert.ok(overlay.options.touchstart && overlay.options.touchstart.passive === false,
          "touchstart must be registered non-passive");
for (const type of ["touchstart", "contextmenu"]) {
    let prevented = 0;
    overlay.fire(type, { cancelable: true, preventDefault() { prevented++; } });
    overlay.fire(type, { cancelable: false, preventDefault() { prevented += 100; } });
    assert.strictEqual(prevented, 1, type + " must preventDefault only when cancelable");
}
let src = img.src;
const changed = () => { const c = img.src !== src; src = img.src; return c; };

// ── reconnect backoff on <img> error: 1, 2, 4, 8, 10, 10 s ──────────────
const delays = [];
for (let i = 0; i < 6; i++) {
    img.onerror();
    assert.strictEqual(overlay.style.display, "none");
    const before = clock;
    while (!changed()) advance(100);
    delays.push(Math.round((clock - before) / 1000));
}
assert.deepStrictEqual(delays, [1, 2, 4, 8, 10, 10]);
img.onload();
assert.strictEqual(overlay.style.display, "block");
assert.strictEqual(el("aa-placeholder").style.display, "none");

// ── update(): in place, reconnect only on the right transitions ─────────
const overlayRef = el("aa-touch-overlay");
renderer.update({ ...data, aa_status: "connected" });          // running → connected
advance(1000);
assert.strictEqual(changed(), false, "running→connected must not reconnect");
renderer.update({ ...data, aa_status: "restarting" });
advance(1000);
assert.strictEqual(changed(), false);
assert.ok(el("aa-status-badge").innerHTML.includes("Restarting"));
renderer.update({ ...data, aa_status: "running" });           // restarting → running
advance(400);
assert.strictEqual(changed(), true, "restarting→running must reconnect");
data = { ...data, aa_stream_epoch: 200 };
renderer.update(data);                                          // new Xvfb
advance(400);
assert.strictEqual(changed(), true, "epoch change must reconnect");
renderer.update(data);
advance(400);
assert.strictEqual(changed(), false, "same epoch must not reconnect");
subs._connection.forEach((cb) => cb(true));                    // WS came back
advance(400);
assert.strictEqual(changed(), true, "WS reconnect must reconnect");
assert.strictEqual(el("aa-touch-overlay"), overlayRef, "update must not rebuild the DOM");
renderer.update({ ...data, aa_auto_restart: false });
assert.ok(el("aa-autorestart").innerHTML.includes("NIEAKTYWNY"));
img.onload();

// ── pointer → AA ─────────────────────────────────────────────────────────
const ev = (x, y, extra) => Object.assign({ pointerId: 7, pointerType: "touch", button: 0,
                                             clientX: x, clientY: y, preventDefault() {} }, extra);
sent.length = 0;
overlay.fire("pointerdown", ev(500, 300));
overlay.fire("pointermove", ev(600, 300));
overlay.fire("pointermove", ev(700, 300));
overlay.fire("pointerdown", ev(10, 10, { pointerId: 8 }));     // 2nd finger ignored
frame();                                                         // one rAF → one move
overlay.fire("pointerup", ev(750, 300));
assert.deepStrictEqual(sent, [["down", 0.5, 0.5], ["move", 0.7, 0.5], ["up", 0.75, 0.5]]);

// Heartbeat while the button is held (keeps the server watchdog away)
sent.length = 0;
overlay.fire("pointerdown", ev(500, 300));
for (const iv of intervals.values()) iv.fn();
overlay.fire("pointerup", ev(500, 300));
assert.deepStrictEqual(sent.map((s) => s[0]), ["down", "move", "up"]);
assert.strictEqual(intervals.size, 0, "heartbeat must stop on up");

// Top-edge tap → tap to AA; pull-down → next screen, nothing to AA
sent.length = 0;
overlay.fire("pointerdown", ev(500, 20));
overlay.fire("pointerup", ev(502, 21));
assert.deepStrictEqual(sent, [["tap", 0.5, 20 / 600]]);
sent.length = 0;
clock += 1000;
overlay.fire("pointerdown", ev(500, 10));
clock += 50; overlay.fire("pointermove", ev(505, 40));
clock += 150; overlay.fire("pointermove", ev(510, 200));
clock += 50; overlay.fire("pointerup", ev(510, 210));
advance(0);
assert.deepStrictEqual(sent, []);
assert.deepStrictEqual(appCalls, ["navCycleNext"]);
// Bottom-edge swipe up → NavBar
overlay.fire("pointerdown", ev(500, 590));
overlay.fire("pointermove", ev(500, 560));
overlay.fire("pointerup", ev(500, 520));
assert.deepStrictEqual(appCalls, ["navCycleNext", "showNavBar"]);
assert.deepStrictEqual(sent, []);
// Top-edge long press → down to AA after 500 ms
overlay.fire("pointerdown", ev(300, 20));
advance(600);
assert.deepStrictEqual(sent, [["down", 0.3, 20 / 600]]);
// Stream drops mid-press → cancel
img.onerror();
assert.deepStrictEqual(sent[sent.length - 1], ["cancel", null, null]);

// ── unmount ──────────────────────────────────────────────────────────────
sent.length = 0;
renderer.unmount();
assert.strictEqual(img.src, "");
assert.strictEqual(img.onerror, null);
assert.deepStrictEqual(sent[sent.length - 1], ["cancel", null, null]);
assert.strictEqual((subs._connection || []).length, 0);
assert.strictEqual((overlay.listeners.pointerdown || []).length, 0);
assert.strictEqual((overlay.listeners.touchstart || []).length, 0);
assert.strictEqual((overlay.listeners.contextmenu || []).length, 0);
const pending = timers.length;
advance(20000);
assert.strictEqual(img.src, "", "no reconnect after unmount");
assert.ok(pending >= 0);

process.stdout.write("ok");
