// screens/phone.js and bt_dial_result, for tests/test_frontend_gestures.py:
// Phone.dial() shows "ringing" at once; when the backend reports that the
// dial failed (no HFP modem, D-Bus error, no network) the overlay must go
// away even if the backend's own ringing → idle fell between two payloads.
// A refused SECOND dial ("busy") leaves the first, real call alone. Plain
// node + assert; exits non-zero on failure, prints "ok" on success.
"use strict";
const assert = require("assert");
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const WEB = path.join(__dirname, "..", "..", "src", "dashboard", "web", "js");

let screen = null;
let renders = 0;
const container = { innerHTML: "", querySelector: () => null };
const posts = [];
let dialStatus = 200;
const ctx = {
    console, setTimeout, clearTimeout, Promise, JSON, Math, Date, Object, String, Array,
    fetch: async (url, opts) => {
        posts.push([url, opts && opts.method, opts && opts.body]);
        return { ok: dialStatus === 200, status: dialStatus, json: async () => ({}) };
    },
    App: {
        registerScreen(name, impl) { if (name === "a8") screen = impl; },
        navigateTo(s) { if (s === "a8") { renders += 1; screen.render(container, "heritage", {}); } },
        t: (key, fallback) => fallback || key,
    },
    AppBar: { render: () => "" },
    NavBar: { render: () => "" },
    DataStore: { sendKey() {} },
    document: { getElementById: () => null },
};
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(path.join(WEB, "screens", "phone.js"), "utf8"), ctx,
                { filename: "phone.js" });
vm.runInContext("this.__Phone = Phone;", ctx);
const Phone = ctx.__Phone;

(async () => {
    // The first payload only seeds what has been seen (an old failure from
    // before the page loaded must not touch anything).
    screen.update({ bt_dial_result: { ok: false, error: "no_modem", ts: 100 } });
    assert.strictEqual(Phone._callState, "idle");

    // Dial: instant "ringing".
    Phone._input = "600123456";
    await Phone.dial();
    assert.strictEqual(Phone._callState, "ringing");
    const dials = posts.filter(([url]) => url === "/api/phone/dial");
    assert.deepStrictEqual(dials.map((d) => d[1]), ["POST"]);
    assert.ok(container.innerHTML.includes("Calling..."), "ringing overlay shown");

    // Same result again (no news): nothing changes.
    screen.update({ bt_dial_result: { ok: false, error: "no_modem", ts: 100 } });
    assert.strictEqual(Phone._callState, "ringing");

    // A refused second dial: the first call stays.
    screen.update({ bt_dial_result: { ok: false, error: "busy", ts: 101 } });
    assert.strictEqual(Phone._callState, "ringing");

    // The dial failed: back to idle, the screen re-renders without the overlay.
    const before = renders;
    screen.update({ bt_dial_result: { ok: false, error: "no_modem", ts: 102 } });
    assert.strictEqual(Phone._callState, "idle");
    assert.strictEqual(JSON.stringify(Phone._callInfo), "{}");
    assert.ok(renders > before, "re-rendered");
    assert.ok(!container.innerHTML.includes("Calling..."), "overlay gone");

    // A second dial (B) accepted by the route but refused by the backend as
    // "busy": the overlay must show A again — the call really being placed
    // (the refusal changes no bt_call_state, so app.js sees no news).
    Phone._callState = "ringing";
    Phone._callInfo = { number: "600111222", name: "" };
    Phone._input = "600333444";
    await Phone.dial();
    assert.strictEqual(Phone._callInfo.number, "600333444");
    const beforeBusy = renders;
    screen.update({ bt_dial_result: { ok: false, error: "busy", ts: 102.5 },
                    bt_call_state: "ringing",
                    bt_call_info: { number: "600111222", name: "<b>Ania</b>" } });
    assert.strictEqual(Phone._callState, "ringing");
    assert.strictEqual(Phone._callInfo.number, "600111222");
    assert.ok(renders > beforeBusy, "re-rendered for A");
    assert.ok(container.innerHTML.includes("&lt;b&gt;Ania"), "name escaped");
    assert.ok(!container.innerHTML.includes("600333444"), "B is not on the overlay");
    // A busy result with a garbage call state changes nothing.
    screen.update({ bt_dial_result: { ok: false, error: "busy", ts: 102.6 },
                    bt_call_state: "<x>" });
    assert.strictEqual(Phone._callInfo.number, "600111222");
    // Outcome unknown (oFono did not answer in time): the overlay stays.
    screen.update({ bt_dial_result: { ok: null, error: "unknown", ts: 102.7 } });
    assert.strictEqual(Phone._callState, "ringing");

    // A successful dial result never ends a call.
    Phone._input = "600123456";
    await Phone.dial();
    screen.update({ bt_dial_result: { ok: true, error: null, ts: 103 } });
    assert.strictEqual(Phone._callState, "ringing");
    // ... and a failure for an active call (not our instant ringing) neither.
    Phone._callState = "active";
    screen.update({ bt_dial_result: { ok: false, error: "dbus", ts: 104 } });
    assert.strictEqual(Phone._callState, "active");

    // 403 (emergency number from a browser that is not the kiosk) / 429:
    // dial() itself drops the instant ringing.
    Phone._callState = "idle";
    for (const status of [403, 429]) {
        dialStatus = status;
        Phone._input = "112";
        await Phone.dial();
        assert.strictEqual(Phone._callState, "idle", "status " + status);
    }

    // Garbage never throws.
    screen.update({ bt_dial_result: "x" });
    screen.update({ bt_dial_result: null });
    screen.update(undefined);
    console.log("ok");
})().catch((e) => { console.error(e); process.exit(1); });
