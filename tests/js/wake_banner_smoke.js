// Remote wake session (modules.remote_session, plan E): the pure parts of
// components/wake_banner.js (normalize / texts / fmtLeft) and the Settings
// row "Wybudzanie" (screens/settings.js remoteSessionRowHtml + update()),
// for tests/test_frontend_gestures.py. Plain node + assert in a vm with DOM
// stubs, no packages. Exits non-zero on failure, prints "ok" on success.
// The real banner on the page (z-index, buttons, countdown, kiosk-only) is
// wake_banner_browser_smoke.js.
"use strict";
const assert = require("assert");
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const WEB = path.join(__dirname, "..", "..", "src", "dashboard", "web", "js");

// ── the banner's pure functions ──────────────────────────────────────────
const B = require(path.join(WEB, "components", "wake_banner.js"));
const t = (k, d) => d;
const SESSION = {
    state: "session", reason: "door", since: 1763000000, lease_left_s: 299,
    sleep_pending: false, holds_used_min: 0, hold_step_min: 30, hold_max_min: 60,
    can_hold: true, idle_suspend_min: 10, link: true, ended: "",
    last_wake: { reason: "door", ts: 1763000000 }, denied_seen: 0, denied_total: 2,
    last_denied: null, last_denied_nano: "rate", cmd: null,
};
const S = (over) => Object.assign({}, SESSION, over || {});

assert.strictEqual(B.fmtLeft(299), "04:59");
assert.strictEqual(B.fmtLeft(0), "00:00");
assert.strictEqual(B.fmtLeft(3600), "60:00");
assert.strictEqual(B.fmtLeft(null), "—");
assert.strictEqual(B.fmtLeft(-1), "—");
assert.strictEqual(B.fmtLeft("60"), "—");

let v = B.normalize(S());
assert.deepStrictEqual([v.state, v.reason, v.left, v.sleeping, v.canHold, v.step],
                       ["session", "door", 299, false, true, 30]);
assert.strictEqual(B.texts(v, t, 299).line, "Wybudzono: drzwi — uśpienie za 04:59");
assert.strictEqual(B.texts(B.normalize(S({ reason: "ir" })), t, 61).line,
                   "Wybudzono: telefon — uśpienie za 01:01");
assert.ok(B.texts(B.normalize(S({ reason: "ext" })), t, 1).line.includes("wejście EXT"));
assert.ok(B.texts(B.normalize(S({ reason: "<img>" })), t, 1).line.includes("z zewnątrz"));
// no lease yet: a dash, never NaN
assert.ok(B.texts(B.normalize(S({ lease_left_s: null })), t, null).line.endsWith("za —"));
// going to sleep: no countdown, no hold
v = B.normalize(S({ sleep_pending: true }));
assert.ok(v.sleeping && !v.canHold);
assert.ok(B.texts(v, t, 10).line.endsWith("usypianie…"));
v = B.normalize(S({ state: "ending", ended: "released" }));
assert.ok(v && v.sleeping);
// nothing to show
for (const bad of [null, undefined, "session", 5, {}, S({ state: "idle" }), S({ state: "<b>" }),
                   S({ state: "ending", ended: "ignition" }), S({ state: "ending", ended: "lost" })]) {
    assert.strictEqual(B.normalize(bad), null, JSON.stringify(bad));
}
// the hold button needs the budget
assert.strictEqual(B.normalize(S({ can_hold: false })).canHold, false);
assert.strictEqual(B.normalize(S({ hold_step_min: "30" })).step, 0);
assert.strictEqual(B.normalize(S({ lease_left_s: 99999 })).left, null);
// a recent failed command shows a note; an old one does not
const now = Date.now() / 1000;
v = B.normalize(S({ cmd: { action: "hold", ok: false, error: "not_sent", ts: now - 5 } }));
assert.ok(B.texts(v, t, 100).note.includes("nie udało się przedłużyć"));
v = B.normalize(S({ cmd: { action: "sleep", ok: false, error: "not_sent", ts: now - 5 } }));
assert.ok(B.texts(v, t, 100).note.includes("nie udało się uśpić"));
v = B.normalize(S({ cmd: { action: "hold", ok: false, error: "not_sent", ts: now - 600 } }));
assert.strictEqual(B.texts(v, t, 100).note, "");
v = B.normalize(S({ cmd: { action: "hold", ok: true, error: "", ts: now } }));
assert.strictEqual(B.texts(v, t, 100).note, "");
assert.strictEqual(B.Z_INDEX, 250);
// idle suspend before the lease end: the banner counts down to it, marked
v = B.normalize(S({ lease_left_s: 1700, idle_left_s: 502 }));
assert.ok(v.idleFirst && v.left === 502, JSON.stringify(v));
assert.strictEqual(B.texts(v, t, 502).line, "Wybudzono: drzwi — uśpienie za 08:22 (bez użycia)");
v = B.normalize(S({ lease_left_s: 100, idle_left_s: 100 }));     // not earlier: the lease
assert.ok(!v.idleFirst && v.left === 100);
assert.ok(!B.texts(v, t, 100).line.includes("bez użycia"));
for (const bad of ["502", -1, 99999, null, 1.5]) {
    v = B.normalize(S({ lease_left_s: 1700, idle_left_s: bad }));
    assert.ok(!v.idleFirst && v.left === 1700, String(bad));
}
v = B.normalize(S({ lease_left_s: null, idle_left_s: 30 }));
assert.ok(v.idleFirst && v.left === 30);
// above the navbar and out of the bottom gesture edge (gestures.js EDGE_PX 40)
assert.ok(B.BOTTOM_PX >= 68, String(B.BOTTOM_PX));
assert.strictEqual(B.ACTIVITY_PING_MS, 5000);
// sync() without a document never throws
B.sync(S());

// ── the Settings row ─────────────────────────────────────────────────────
let screen = null;
const slots = { "[data-remote-session-slot]": { innerHTML: "<untouched>" },
                "[data-cabin-watch-slot]": { innerHTML: "<untouched>" },
                "[data-parking-guard-slot]": { innerHTML: "<untouched>" },
                "[data-car-phone-agent-slot]": { innerHTML: "<untouched>" },
                "[data-car-phone-slot]": { innerHTML: "<untouched>" },
                "[data-tether-slot]": { innerHTML: "<untouched>" },
                "[data-gps-slot]": { innerHTML: "<untouched>" } };
const ctx = {
    console, setTimeout, clearTimeout, Promise, JSON, Math, Date, Object, String, Number,
    isFinite, Array,
    setInterval: () => 0, clearInterval() {},
    fetch: async () => ({ ok: true, status: 200, json: async () => ({}) }),
    App: {
        registerScreen(name, impl) { if (name === "settings") screen = impl; },
        getConfig: () => ({ theme: "modern", language: "pl", speed_unit: "km/h", temp_unit: "C" }),
        t: (key, fallback) => fallback || key,
        navigateTo() {},
    },
    AppBar: { render: () => "" },
    document: {
        getElementById: () => null, createElement: () => ({ style: {} }), body: {},
        querySelector: (sel) => slots[sel] || null,
        querySelectorAll: () => [],
        addEventListener() {},
        activeElement: null,
    },
};
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(path.join(WEB, "screens", "settings.js"), "utf8"), ctx,
                { filename: "settings.js" });
vm.runInContext("this.__Settings = Settings;", ctx);
const Settings = ctx.__Settings;
const TS = new Date(2026, 10, 19, 3, 12, 0).getTime() / 1000;
const IDLE = Object.assign({}, SESSION, { state: "idle", reason: "", since: null, lease_left_s: null,
                                          ended: "lease_end", last_wake: { reason: "ir", ts: TS } });
const row = (over) => Settings.remoteSessionRowHtml(Object.assign({}, IDLE, over || {}), t);

let html = row();
assert.ok(html.includes("Wybudzanie") && html.includes(">power_settings_new<"), html);
assert.ok(html.includes("czeka") && html.includes("ostatnie: telefon 19.11 03:12"), html);
assert.ok(html.includes("koniec sesji: koniec dzierżawy"), html);
assert.ok(html.includes("odmowy Nano: 2 (ostatnio: limit pobudek)"), html);
assert.ok(html.includes('data-wake-state="idle"'), html);
assert.ok(!html.includes("<button") && !html.includes("onclick"), "read-only row: " + html);
assert.ok(!/class="[^"]*\b(flex|gap-|px-|py-|text-\[)/.test(html.replace(/material-symbols-outlined/g, "")),
          "only inline styles: " + html);
html = row({ state: "session", reason: "door", holds_used_min: 30, ended: "" });
assert.ok(html.includes("sesja: drzwi") && html.includes("przedłużenia: 30/60 min"), html);
assert.ok(html.includes("uśpienie po bezczynności 10 min") && !html.includes("koniec sesji"), html);
assert.ok(row({ link: false }).includes("Nano #2 (sensor_hub) niepodłączony"));
assert.ok(row({ ir_default: true }).includes("kod IR z repozytorium"));
assert.ok(!row({ ir_default: false }).includes("kod IR z repozytorium"));
assert.ok(row({ cmd: { action: "sleep", ok: false, error: "not_confirmed", ts: TS } })
    .includes("Nano nie potwierdził uśpienia"));
assert.ok(row({ denied_total: 0 }).includes("odmowy Nano: 0") && !row({ denied_total: 0 }).includes("ostatnio"));
assert.ok(row({ denied_total: null, denied_seen: 3 }).includes("odmowy Nano: 3"));
assert.ok(row({ state: "ending", ended: "idle" }).includes("usypianie"));
// escaping and whitelists
html = Settings.remoteSessionRowHtml({ state: "<img src=x onerror=alert(1)>", reason: "<b>",
                                       last_wake: { reason: "<script>", ts: TS },
                                       last_denied_nano: "<i>", ended: "<u>" }, t);
assert.ok(!/<img|<b>|<script>|<i>|<u>/.test(html) && html.includes('data-wake-state="idle"'), html);
assert.strictEqual(Settings.remoteSessionRowHtml(null, t), "");
assert.strictEqual(Settings.remoteSessionRowHtml("session", t), "");
// the key leaves the countdown out (no redraw every second)
assert.strictEqual(Settings.remoteSessionRowKey(S({ lease_left_s: 10 })),
                   Settings.remoteSessionRowKey(S({ lease_left_s: 9 })));
assert.notStrictEqual(Settings.remoteSessionRowKey(S()), Settings.remoteSessionRowKey(S({ reason: "ir" })));

// ── the whole screen and update() ────────────────────────────────────────
const container = { innerHTML: "" };
screen.render(container, "modern", { remote_session: IDLE });
assert.ok(container.innerHTML.includes('data-wake-state="idle"'), "row rendered");
screen.render(container, "modern", { aa_status: "running" });
assert.ok(/data-remote-session-slot style="display:contents"><\/div>/.test(container.innerHTML));
const slot = slots["[data-remote-session-slot]"];
screen.render(container, "modern", { remote_session: S() });
screen.update({ remote_session: S({ lease_left_s: 120 }) });
assert.strictEqual(slot.innerHTML, "<untouched>", "only the countdown changed: nothing redrawn");
screen.update({ remote_session: S({ reason: "ir" }) });
assert.ok(slot.innerHTML.includes("sesja: telefon"), slot.innerHTML);
screen.update({ remote_session: null });
assert.strictEqual(slot.innerHTML, "", "module gone: row gone");
screen.update(undefined);

process.stdout.write("ok\n");
