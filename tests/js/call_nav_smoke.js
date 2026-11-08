// Incoming-call navigation: app.js follows bt_call_state on EVERY screen and
// keeps Phone (screens/phone.js) in sync, for tests/test_frontend_gestures.py.
// Loads the real app.js + phone.js in a node vm with DOM stubs; plain node +
// assert, no packages. Exits non-zero on failure, prints "ok" on success.
"use strict";
const assert = require("assert");
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const WEB = path.join(__dirname, "..", "..", "src", "dashboard", "web", "js");
const G = require(path.join(WEB, "components", "gestures.js"));

function makeEl(id) {
    return {
        id, innerHTML: "", style: {}, textContent: "",
        classList: { add() {}, remove() {}, contains: () => false },
        setAttribute() {}, appendChild() {}, remove() {},
        querySelector() { return null; }, querySelectorAll() { return []; },
    };
}
const elements = {};
const el = (id) => elements[id] || (elements[id] = makeEl(id));
let dataListener = null;

const ctx = {
    console, setTimeout, clearTimeout, Promise, JSON, Math, Date,
    setInterval: () => 0, clearInterval() {},
    requestAnimationFrame: () => 0,
    performance: { now: () => 0 },
    localStorage: {
        _s: { "bcm.lastScreen": "a3" },
        getItem(k) { return Object.prototype.hasOwnProperty.call(this._s, k) ? this._s[k] : null; },
        setItem(k, v) { this._s[k] = String(v); },
    },
    fetch: async (url) => ({
        ok: true,
        json: async () => (url === "/api/boot_mode" ? { boot_mode: "cold" }
            : url === "/api/phone/contacts" ? { contacts: [] }
            : url === "/api/phone/history" ? { history: [] } : {}),
    }),
    DataStore: {
        init() {}, unsubscribe() {}, get() {}, sendKey() {}, sendAATouch() {},
        getAll: () => ({}),
        subscribe(key, fn) { if (key === "*") dataListener = fn; },
    },
    AppBar: { render: () => "", update() {} },
    NavBar: { render: () => "" },
};
ctx.document = {
    body: el("body"), hidden: false, activeElement: null,
    getElementById: el, addEventListener() {}, querySelector: () => null,
};
ctx.window = { addEventListener() {}, innerHeight: 600, BCMGestures: G, document: ctx.document };
vm.createContext(ctx);
for (const file of ["app.js", path.join("screens", "phone.js")]) {
    vm.runInContext(fs.readFileSync(path.join(WEB, file), "utf8"), ctx, { filename: file });
}
vm.runInContext("this.__App = App; this.__Phone = Phone;", ctx);
const App = ctx.__App;
const Phone = ctx.__Phone;

const updates = [];
for (const s of ["init", "a1", "a2", "a3", "a4", "settings"]) {
    App.registerScreen(s, { render() {}, update: () => updates.push(s) });
}

// ── the pure rule ─────────────────────────────────────────────────────────
const D = App.callNavDecision;
const TABLE = [
    // prev, next, screen, returnTo -> target
    ["idle", "incoming", "a1", null, "a8"],
    ["idle", "incoming", "settings", null, "a8"],
    ["idle", "incoming", "a8", null, null],       // already there
    ["idle", "incoming", "a2", null, null],       // AA shows its own call UI
    ["idle", "ringing", "a3", null, "a8"],        // call started on the phone
    ["idle", "active", "a4", null, "a8"],
    [null, "active", "a1", null, "a8"],           // kiosk loaded mid-call
    [null, "idle", "a1", null, null],
    ["incoming", "active", "a1", null, null],     // answered: no second switch
    ["ringing", "active", "a1", null, null],
    ["active", "incoming", "a1", null, "a8"],     // call waiting
    ["active", "active", "a1", null, null],       // no change
    ["active", "idle", "a8", "a3", "a3"],         // back where we came from
    ["active", "idle", "a1", "a3", null],         // driver left A8 by hand
    ["active", "idle", "a8", null, null],         // driver went to A8 himself
    ["idle", "bogus", "a1", null, null],
    ["idle", undefined, "a1", null, null],
];
for (const [prev, next, screen, ret, want] of TABLE) {
    assert.strictEqual(D(prev, next, screen, ret), want,
        `callNavDecision(${prev}, ${next}, ${screen}, ${ret})`);
}

function push(state, info) {
    dataListener({ bt_call_state: state, bt_call_info: info === undefined ? {} : info });
}

(async () => {
    await App.init();
    assert.strictEqual(App.getCurrentScreen(), "a3");   // restored last screen
    assert.ok(dataListener, "App did not subscribe to data updates");

    // Idle pushes change nothing.
    push("idle");
    push("idle");
    assert.strictEqual(App.getCurrentScreen(), "a3");

    // Incoming call while on A3 → A8 with the overlay state set.
    push("incoming", { number: "+48123456789", name: "Jan <b>" });
    assert.strictEqual(App.getCurrentScreen(), "a8");
    assert.strictEqual(Phone._callState, "incoming");
    assert.deepStrictEqual(JSON.parse(JSON.stringify(Phone._callInfo)),
        { number: "+48123456789", name: "Jan <b>" });
    const html = el("app").innerHTML;
    assert.ok(html.includes("Jan &lt;b&gt;"), "caller name not escaped in the overlay");
    assert.ok(!html.includes("Jan <b>"), "raw caller name reached innerHTML");

    // Answered → active: stays on A8, overlay re-rendered with the new state.
    push("active", { number: "+48123456789", name: "Jan <b>" });
    assert.strictEqual(App.getCurrentScreen(), "a8");
    assert.strictEqual(Phone._callState, "active");
    assert.ok(el("app").innerHTML.includes("call-duration"), "active-call overlay missing");

    // Same payload again: no re-render (A8 already shows it).
    const before = el("app").innerHTML;
    el("app").innerHTML = "sentinel";
    push("active", { number: "+48123456789", name: "Jan <b>" });
    assert.strictEqual(el("app").innerHTML, "sentinel");
    el("app").innerHTML = before;

    // Call ends → back to A3, Phone idle.
    push("idle");
    assert.strictEqual(App.getCurrentScreen(), "a3");
    assert.strictEqual(Phone._callState, "idle");
    assert.deepStrictEqual(JSON.parse(JSON.stringify(Phone._callInfo)), {});

    // On Android Auto: state is followed, but the screen is left alone.
    App.navigateTo("a2");
    push("incoming", { number: "112" });
    assert.strictEqual(App.getCurrentScreen(), "a2");
    assert.strictEqual(Phone._callState, "incoming");
    push("idle");
    assert.strictEqual(App.getCurrentScreen(), "a2");
    // ... and A8 opened later never shows a stale overlay.
    App.navigateTo("a8");
    assert.ok(!el("app").innerHTML.includes("ring_volume"), "stale incoming overlay on A8");

    // Driver leaves A8 during the call: no jump back when it ends.
    App.navigateTo("a1");
    push("ringing", { number: "600" });          // outgoing from the phone
    assert.strictEqual(App.getCurrentScreen(), "a8");
    App.navigateTo("a4");
    push("idle");
    assert.strictEqual(App.getCurrentScreen(), "a4");

    // Phone.dial()'s instant local "ringing" survives unchanged idle pushes.
    App.navigateTo("a8");
    Phone._input = "123";
    await Phone.dial();
    assert.strictEqual(Phone._callState, "ringing");
    push("idle");
    assert.strictEqual(Phone._callState, "ringing", "provisional dial state clobbered");

    // Phonebook entries (PBAP = untrusted) are escaped, and the number goes
    // through a data-dial attribute read by a delegated listener — no inline
    // handler carries it (tests/js/phone_escape_smoke.js goes further).
    await new Promise((r) => setTimeout(r, 0));       // let loadContacts settle
    Phone._contacts = [{ name: "<img src=x onerror=alert(1)>", number: "1');alert(1);//" }];
    Phone._history = [{ name: "<b>x</b>", number: "2", type: "missed", time: "<i>" }];
    for (const tab of ["contacts", "history"]) {
        Phone._tab = tab;
        App.navigateTo("a8");
        const page = el("app").innerHTML;
        assert.ok(!page.includes("<img") && !page.includes("<b>x") && !page.includes("<i>"),
            tab + ": raw phonebook HTML reached innerHTML");
        assert.ok(!page.includes("dialNumber("), tab + ": number-carrying inline handler");
        assert.ok(page.includes("data-dial="), tab + ": row without data-dial");
    }
    assert.ok(el("app").innerHTML.includes("&lt;b&gt;x&lt;/b&gt;"));
    Phone._tab = "contacts";
    App.navigateTo("a8");
    assert.ok(el("app").innerHTML.includes('data-dial="1&#39;);alert(1);//"'));

    // Garbage never throws out of the data loop.
    dataListener({ bt_call_state: { x: 1 }, bt_call_info: "nope" });
    dataListener({ bt_call_state: "incoming", bt_call_info: null });
    dataListener({});
    assert.strictEqual(Phone._callState, "incoming");

    process.stdout.write("ok");
})().catch((e) => { console.error(e); process.exit(1); });
