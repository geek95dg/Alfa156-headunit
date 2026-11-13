// On-screen keyboard behaviour (web/js/components/keyboard.js) against a
// small fake DOM, for tests/test_frontend_keyboard.py. Plain node + assert,
// no packages, so it also runs where there is no Chromium (CI): the
// browser-level check is osk_browser_smoke.js. Exits non-zero on failure,
// prints "ok" on success.
//
// Covers what the old code got wrong:
//   * a tap on a field in the lower half — pointerdown on the field, focus
//     builds the keyboard under the finger, the click is retargeted to
//     <body> — must leave the keyboard open (the old click handler closed it);
//   * password fields open it and keep it open (only type=text was handled);
//   * a tap outside closes it on the click of that tap, a drag
//     (pointercancel, no click) does not;
//   * a tap outside whose click is suppressed (touchend.preventDefault in
//     the trip planner) still closes it, after OSK_CLICK_WAIT_MS — but a
//     drag that ends in pointerup (touch-action:none, the weather map) and
//     a tap that focuses another field do not;
//   * closing writes nothing back and fires no "input" event (the old
//     extra event re-ran the search after a suggestion had been picked);
//   * sizes go to the --osk-* variables on <html> and follow a resize;
//   * _ensureVisible scrolls the nearest scroller so the field ends >= 12 px
//     above the keyboard (tall fields by their top, fields above the
//     scroller's top edge back down).
"use strict";
const assert = require("assert");
const path = require("path");

// ── fake DOM ──────────────────────────────────────────────────────────────
const byId = new Map();
const docListeners = [];
const winListeners = [];
let rafQueue = [];

class FakeEl {
    constructor(tag, props = {}) {
        this.tagName = tag.toUpperCase();
        this.parentElement = null;
        this.children = [];
        this.className = "";
        this.innerHTML = "";
        this.style = { cssText: "" };
        this.value = "";
        this.events = [];
        this.scrollTop = 0;
        this.scrollHeight = 0;
        this.clientHeight = 0;
        this.overflowY = "visible";
        this.rect = null;              // function returning a rect, for measured elements
        Object.assign(this, props);
        const classes = new Set();
        this.classList = {
            add: (c) => classes.add(c), remove: (c) => classes.delete(c),
            contains: (c) => classes.has(c),
        };
    }
    get isConnected() {
        let e = this;
        while (e.parentElement) e = e.parentElement;
        return e === document.documentElement;
    }
    get id() { return this._id || ""; }
    set id(v) { this._id = v; }
    appendChild(c) {
        c.parentElement = this;
        this.children.push(c);
        if (c.id) byId.set(c.id, c);
        return c;
    }
    remove() {
        if (this.parentElement) {
            this.parentElement.children = this.parentElement.children.filter((x) => x !== this);
        }
        this.parentElement = null;
        if (byId.get(this.id) === this) byId.delete(this.id);
    }
    contains(o) {
        for (let e = o; e; e = e.parentElement) if (e === this) return true;
        return false;
    }
    addEventListener() {}
    dispatchEvent(ev) { this.events.push(ev.type); }
    focus() { this.focused = true; }
    getBoundingClientRect() { return this.rect ? this.rect() : { top: 0, bottom: 0 }; }
}

const htmlEl = new FakeEl("html");
const vars = {};
htmlEl.style.setProperty = (k, v) => { vars[k] = v; };
const body = new FakeEl("body");
htmlEl.appendChild(body);

global.document = {
    documentElement: htmlEl,
    body,
    createElement: (t) => new FakeEl(t),
    getElementById: (id) => byId.get(id) || null,
    addEventListener: (type, fn, capture) => docListeners.push({ type, fn, capture: !!capture }),
};
global.window = {
    innerHeight: 600,
    addEventListener: (type, fn) => winListeners.push({ type, fn }),
};
global.requestAnimationFrame = (fn) => { rafQueue.push(fn); return rafQueue.length; };
// Fake timers (only keyboard.js's tap fallback uses them): the test runs
// them by hand instead of sleeping.
let timers = new Map();
let timerSeq = 0;
global.setTimeout = (fn, ms) => { timers.set(++timerSeq, { fn, ms }); return timerSeq; };
global.clearTimeout = (id) => { timers.delete(id); };
function runTimers() {
    const due = [...timers.values()];
    timers = new Map();
    due.forEach((t) => t.fn());
    return due.map((t) => t.ms);
}
global.getComputedStyle = (el) => ({ overflowY: el.overflowY });
global.Event = class { constructor(type) { this.type = type; } };

function fire(type, target, extra = {}) {
    // Capture-phase listeners first, then bubble — all on document.
    const ev = { type, target, pointerId: 1, pointerType: "touch", clientX: 100, clientY: 100, ...extra };
    for (const cap of [true, false]) {
        for (const l of docListeners) if (l.type === type && l.capture === cap) l.fn(ev);
    }
}
function flushRaf() {
    const q = rafQueue;
    rafQueue = [];
    q.forEach((fn) => fn());
}
function overlay() { return document.getElementById("osk-overlay"); }
function isOpen() { return !!overlay() && body.classList.contains("osk-open"); }
// The open keyboard's top edge, from the height keyboard.js asked for.
function kbTop() { return window.innerHeight - parseInt(vars["--osk-h"], 10); }

const OSK = require(path.join(__dirname, "..", "..", "src", "dashboard", "web", "js",
                              "components", "keyboard.js"));
assert.strictEqual(OSK.ROWS.length, 6);

// The page: a scrollable content area (top at 60 px) with fields in it.
const content = new FakeEl("main", { overflowY: "auto", scrollHeight: 2000, clientHeight: 540 });
content.rect = () => ({ top: 60, bottom: 600 });
body.appendChild(content);
const plain = new FakeEl("div");
content.appendChild(plain);
function field(tag, type, top, bottom, extra = {}) {
    const el = new FakeEl(tag, { type, ...extra });
    el.rect = () => ({ top: top - content.scrollTop, bottom: bottom - content.scrollTop });
    content.appendChild(el);
    return el;
}
const ssid = field("input", "text", 500, 520);
const pwd = field("input", "password", 530, 550);
const num = field("input", "number", 560, 580);
const ro = field("input", "text", 100, 120, { readOnly: true });

// Measured rects for the overlay (created by keyboard.js) are patched in
// after it exists.
function patchOverlay() {
    const o = overlay();
    if (o && !o.rect) o.rect = () => ({ top: kbTop(), bottom: window.innerHeight });
}

// 1. Lower-half text field: pointerdown on it, focus opens the keyboard, the
//    click lands on <body> (retargeted) — must stay open.
fire("pointerdown", ssid);
fire("focusin", ssid);
patchOverlay();
fire("click", body);
assert.ok(isOpen(), "keyboard closed right after opening on a lower-half field");
assert.deepStrictEqual(
    { h: vars["--osk-h"], pad: vars["--osk-pad"], gap: vars["--osk-gap"], font: vars["--osk-font"] },
    { h: "348px", pad: "7px", gap: "6px", font: "23px" });
assert.strictEqual(overlay().style.cssText, "", "no inline 50vh height any more");
assert.ok(!/\b(p-3|gap-2|mb-1|py-2|text-lg|text-base)\b/.test(overlay().innerHTML + overlay().className),
          "rem-sized classes left in the keyboard markup");
assert.strictEqual((overlay().innerHTML.match(/<button /g) || []).length, 50);

// 2. _ensureVisible (next frame): field bottom 520 → 12 px above the keys.
flushRaf();
assert.strictEqual(content.scrollTop, 520 - (kbTop() - 12));
assert.ok(ssid.getBoundingClientRect().bottom <= kbTop() - 12);

// 3. Typing goes into the field.
OSK.key("a");
OSK.key("shift");
OSK.key("ł");
assert.strictEqual(ssid.value, "aŁ");
assert.ok(ssid.events.includes("input"));

// 4. A tap on a key (inside the overlay) keeps it open.
const keyBtn = new FakeEl("button");
overlay().appendChild(keyBtn);
fire("pointerdown", keyBtn);
fire("click", keyBtn);
assert.ok(isOpen(), "a tap on a key closed the keyboard");

// 5. A drag over the content (pointercancel, no click) keeps it open; a later
//    click that never had an outside pointerdown does not close it either.
fire("pointerdown", plain);
fire("pointercancel", plain);
fire("click", body);
assert.ok(isOpen(), "scrolling the page closed the keyboard");

// 6. A tap outside closes it — on the click, not already on pointerdown.
fire("pointerdown", plain);
assert.ok(isOpen(), "closed on pointerdown: the click would land on shifted content");
fire("click", plain);
assert.ok(!isOpen(), "a tap outside did not close the keyboard");
assert.strictEqual(ssid.value, "aŁ");

// 7. Password field in the lower half: opens and stays open.
content.scrollTop = 0;
fire("pointerdown", pwd);
fire("focusin", pwd);
patchOverlay();
fire("click", pwd);
assert.ok(isOpen(), "password field: keyboard closed right after opening");
fire("click", body);
assert.ok(isOpen());
OSK.close();
assert.ok(!isOpen());

// 8. Fields the keyboard must not open for.
fire("focusin", num);
fire("focusin", ro);
fire("focusin", plain);
assert.ok(!isOpen(), "opened for a number/readonly/non-input element");

// 9. Resize while open → new sizes on the next frame; closed → ignored.
content.scrollTop = 0;
fire("focusin", ssid);
patchOverlay();
flushRaf();
window.innerHeight = 480;
winListeners.filter((l) => l.type === "resize").forEach((l) => l.fn());
flushRaf();
assert.strictEqual(vars["--osk-h"], "278px");
assert.ok(ssid.getBoundingClientRect().bottom <= kbTop() - 12, "field under the keys after resize");
OSK.close();
window.innerHeight = 600;
winListeners.filter((l) => l.type === "resize").forEach((l) => l.fn());
flushRaf();
assert.strictEqual(vars["--osk-h"], "278px", "re-sized while closed");

// 10. A field taller than the space above the keyboard is aligned by its top.
content.scrollTop = 0;
const area = field("textarea", undefined, 300, 600);
fire("focusin", area);
patchOverlay();
flushRaf();
assert.strictEqual(area.getBoundingClientRect().top, 60 + 12);
OSK.close();

// 11. A field scrolled above the content's top edge comes back down.
content.scrollTop = 450;           // ssid rect: 50..70, content top 60
fire("focusin", ssid);
patchOverlay();
flushRaf();
assert.strictEqual(ssid.getBoundingClientRect().top, 60 + 12);
OSK.close();

// 12. A field that is not in the page any more is left alone.
const gone = new FakeEl("input", { type: "text" });
gone.rect = () => { throw new Error("measured a detached field"); };
fire("focusin", gone);
patchOverlay();
flushRaf();
OSK.close();

// 13. A tap outside whose click never comes (a page handler called
//     preventDefault in touchend — trip planner suggestions): pointerup arms
//     a fallback, which closes the keyboard once the tap is over.
function openOn(el) {
    content.scrollTop = 0;
    fire("pointerdown", el);
    fire("focusin", el);
    patchOverlay();
    fire("pointerup", el);
    fire("click", el);
    flushRaf();
    assert.ok(isOpen(), "keyboard did not open");
    assert.strictEqual(timers.size, 0, "a tap on the field armed the close fallback");
}
openOn(ssid);
fire("pointerdown", plain);
fire("pointerup", plain);
assert.ok(isOpen(), "closed before the tap was over");
assert.deepStrictEqual(runTimers(), [350]);
assert.ok(!isOpen(), "a tap outside without a click left the keyboard open");
// ... and the flag is spent: a stray click later (no pointerdown) is ignored.
openOn(ssid);
fire("click", body);
assert.ok(isOpen(), "a stale outside tap closed the keyboard on a later click");

// 14. Ordinary tap outside: the click closes it and disarms the fallback,
//     which must not close a keyboard opened again right after.
fire("pointerdown", plain);
fire("pointerup", plain);
fire("click", plain);
assert.ok(!isOpen());
assert.strictEqual(timers.size, 0, "the click left the fallback timer armed");
openOn(ssid);
runTimers();
assert.ok(isOpen(), "the fallback of an earlier tap closed the reopened keyboard");

// 15. A drag ending in pointerup (touch-action:none, e.g. the weather map —
//     no pointercancel, no click) is not a tap: no fallback.
fire("pointerdown", plain, { clientX: 100, clientY: 100 });
fire("pointerup", plain, { clientX: 160, clientY: 130 });
assert.strictEqual(timers.size, 0, "a drag armed the close fallback");
assert.ok(isOpen(), "a drag closed the keyboard");
// Another finger's pointerup does not count either.
fire("pointerdown", plain, { pointerId: 7 });
fire("pointerup", plain, { pointerId: 8 });
assert.strictEqual(timers.size, 0, "another pointer's pointerup armed the fallback");

// 16. A tap outside whose handler focuses another field: the new field keeps
//     the keyboard.
fire("pointerdown", plain);
fire("pointerup", plain);
fire("focusin", pwd);
patchOverlay();
runTimers();
assert.ok(isOpen(), "the fallback closed the keyboard just attached to another field");
fire("click", plain);
assert.ok(isOpen(), "the click of that tap closed the keyboard of the new field");
OSK.close();

// 17. Closing writes nothing and fires no "input": key() already synced the
//     field, and a page that changed the field since (cleared it after a
//     pick) must keep its value.
ssid.value = "";
openOn(ssid);
ssid.events = [];
OSK.key("g");
assert.strictEqual(ssid.value, "g");
assert.deepStrictEqual(ssid.events, ["input"]);
OSK.key("done");
assert.deepStrictEqual(ssid.events, ["input"], "closing fired another input event");
openOn(ssid);
OSK.key("d");
ssid.events = [];
ssid.value = "";                   // the page clears the field after a pick
fire("pointerdown", plain);
fire("click", plain);
assert.ok(!isOpen());
assert.strictEqual(ssid.value, "", "closing put the typed text back into a cleared field");
assert.deepStrictEqual(ssid.events, [], "closing fired an input event");

process.stdout.write("ok\n");
