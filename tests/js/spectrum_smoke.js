// screens/main.js spectrum strip for tests/test_frontend_gestures.py: the A1
// equalizer canvas eases toward the last payload frame on a
// requestAnimationFrame loop, keeps falling peak-hold caps, draws a 2 px
// baseline at silence, falls back to fillRect without ctx.roundRect, sizes the
// canvas in whole pixels, caches the gradient, takes colours from the theme's
// CSS variables, ignores garbage payloads and stops its loop on unmount or
// when the canvas is gone. Loads the real file in a node vm with DOM/canvas
// stubs; plain node + assert. Prints "ok" on success.
"use strict";
const assert = require("assert");
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const WEB = path.join(__dirname, "..", "..", "src", "dashboard", "web", "js");

function makeCtx(withRoundRect) {
    const calls = [];
    const ctx = {
        calls,
        fillStyle: "",
        setTransform: (...a) => calls.push(["setTransform", ...a]),
        clearRect: (...a) => calls.push(["clearRect", ...a]),
        fillRect(...a) { calls.push(["fillRect", this.fillStyle, ...a]); },
        beginPath: () => calls.push(["beginPath"]),
        fill() { calls.push(["fill", this.fillStyle]); },
        grads: 0,
        createLinearGradient(...a) {
            this.grads++;
            calls.push(["grad", ...a]);
            return { stops: [], addColorStop(o, c) { this.stops.push([o, c]); } };
        },
    };
    if (withRoundRect) ctx.roundRect = (...a) => calls.push(["roundRect", ...a]);
    return ctx;
}

function makeCanvas(ctx) {
    return { clientWidth: 517.6, clientHeight: 44.4, width: 300, height: 150,
             isConnected: true, getContext: () => ctx };
}

let rafQueue = [];
let rafId = 0;
let canvas = null;
const screens = {};
const sandbox = {
    console, Math, Number, Array, Object, String, JSON, Date,
    setTimeout, clearTimeout,
    requestAnimationFrame: (fn) => { rafQueue.push({ id: ++rafId, fn }); return rafId; },
    cancelAnimationFrame: (id) => { rafQueue = rafQueue.filter((r) => r.id !== id); },
    getComputedStyle: () => ({
        getPropertyValue: (name) => ({
            "--spectrum-top": " #111111", "--spectrum-bottom": "#222222",
            "--spectrum-peak": "#333333", "--spectrum-base": "#444444",
        }[name] || ""),
    }),
    App: { registerScreen(name, impl) { screens[name] = impl; }, navigateTo() {} },
    AppBar: { render: () => "" },
    NavBar: { render: () => "" },
    MediaPlayer: { renderHeritage: () => "", renderModern: () => "", renderAutodelta: () => "" },
    document: {
        getElementById: (id) => (id === "spectrum-canvas" ? canvas : null),
        activeElement: null,
    },
};
sandbox.window = { devicePixelRatio: 1.5 };
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(path.join(WEB, "screens", "main.js"), "utf8"), sandbox,
                { filename: "main.js" });
const A1 = screens.a1;
assert.ok(A1 && A1.update && A1.unmount, "a1 registered with update + unmount");

let clock = 1000;
function frames(n, stepMs = 16) {
    for (let i = 0; i < n && rafQueue.length; i++) {
        const q = rafQueue;
        rafQueue = [];
        clock += stepMs;
        for (const r of q) r.fn(clock);
    }
}
const data = (bands) => ({ audio_spectrum: bands, audio_volume: 50 });

// ── silence: a live baseline, no bars ────────────────────────────────────
let ctx = makeCtx(false);                      // no roundRect: must not throw
canvas = makeCanvas(ctx);
A1.update(data(new Array(16).fill(0)), "heritage");
assert.strictEqual(rafQueue.length, 1, "update starts the rAF loop");
frames(1);
assert.strictEqual(canvas.width, Math.round(Math.round(517.6) * 1.5), "whole-pixel width");
assert.strictEqual(canvas.height, Math.round(Math.round(44.4) * 1.5), "whole-pixel height");
let rects = ctx.calls.filter((c) => c[0] === "fillRect");
assert.strictEqual(rects.length, 16, "16 baseline rects at silence: " + rects.length);
for (const r of rects) {
    assert.strictEqual(r[1], "#444444", "baseline colour from --spectrum-base");
    assert.strictEqual(r[5], 2, "2 px baseline");
    assert.strictEqual(r[3], 44 - 2);
}
assert.strictEqual(rafQueue.length, 0, "silence: the loop idles");

// ── music: ease toward the target (no jump), then peak caps ─────────────
ctx.calls.length = 0;
const target = [0.9, 0.8, 0.7, 0.6, 0.5, 0.4, 0.3, 0.2, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8];
A1.update(data(target), "heritage");
frames(1);
let st = A1._spectrum._state();
assert.ok(st.cur[0] > 0 && st.cur[0] < 0.9, "first frame eases, does not jump: " + st.cur[0]);
frames(60);
st = A1._spectrum._state();
for (let i = 0; i < 16; i++) assert.ok(Math.abs(st.cur[i] - target[i]) < 0.01, `band ${i} reached target`);
assert.ok(!ctx.calls.some((c) => c[0] === "roundRect"), "no roundRect on this ctx");
const bars = ctx.calls.filter((c) => c[0] === "fillRect" && typeof c[1] === "object");
assert.ok(bars.length > 0, "bars drawn with fillRect fallback");
assert.strictEqual(ctx.grads, 1, "gradient cached across frames: " + ctx.grads);
const g = bars[0][1];
assert.deepStrictEqual(g.stops, [[0, "#111111"], [1, "#222222"]], "theme colours");
assert.ok(ctx.calls.some((c) => c[0] === "fillRect" && c[1] === "#333333"), "peak caps drawn");

// ── drop to silence: bars fall, caps hold then fall ──────────────────────
A1.update(data(new Array(16).fill(0)), "heritage");
frames(5);
st = A1._spectrum._state();
assert.ok(st.peak[0] > st.cur[0], "peak cap above the falling bar");
assert.ok(st.peak[0] > 0.8, "peak holds for a moment: " + st.peak[0]);
frames(200);
st = A1._spectrum._state();
assert.ok(st.cur.every((v) => v === 0) && st.peak.every((v) => v === 0), "all back to zero");
assert.strictEqual(st.running, false, "loop idles once everything settled");

// ── roundRect used where available ───────────────────────────────────────
ctx = makeCtx(true);
canvas = makeCanvas(ctx);
A1.update(data(target), "modern");
frames(20);
assert.ok(ctx.calls.some((c) => c[0] === "roundRect"), "roundRect used when present");
assert.strictEqual(ctx.grads, 1, "new canvas = one new gradient");

// ── garbage payloads ─────────────────────────────────────────────────────
for (const bad of [null, undefined, "x", [NaN, -5, 7, "0.5", null], { 0: 1 }]) {
    A1.update(data(bad), "heritage");
    frames(2);
}
st = A1._spectrum._state();
assert.ok(st.target.every((v) => v >= 0 && v <= 1 && Number.isFinite(v)), "targets clamped");

// ── unmount stops the loop ───────────────────────────────────────────────
A1.update(data(target), "heritage");
assert.ok(rafQueue.length > 0);
A1.unmount();
assert.strictEqual(rafQueue.length, 0, "unmount cancels the pending frame");
assert.strictEqual(A1._spectrum._state().running, false);

// ── canvas gone (screen re-rendered / left): loop stops by itself ────────
A1.update(data(new Array(16).fill(0.5)), "heritage");
canvas = null;
frames(3);
assert.strictEqual(rafQueue.length, 0, "no canvas: no more frames");

// ── zero-size canvas (hidden) does not throw ─────────────────────────────
ctx = makeCtx(false);
canvas = makeCanvas(ctx);
canvas.clientWidth = 0;
A1.update(data(target), "heritage");
frames(3);
A1.unmount();

process.stdout.write("ok\n");
