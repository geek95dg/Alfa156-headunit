// Crash SMS window and Settings section, for tests/test_frontend_gestures.py.
// Plain node + assert (no packages); exits non-zero on failure, prints "ok".
//
//  - components/crash_modal.js, pure parts: which payloads open the window,
//    which texts it shows (DRY RUN badge, forced-test-mode reason, "no phone"
//    message, results), escaping, and the skeleton's geometry from its inline
//    styles (ANULUJ >= 1/3 of the screen, the reserved 112 slot >= 15% of
//    the width away, no inline JS);
//  - app.js: #crash-modal is in GESTURE_OVERLAYS and _syncCrashState hands
//    data.crash_sms to CrashModal on EVERY screen (A2 included), even when
//    the screen's own update() throws;
//  - screens/settings.js: the "SMS po stłuczce" row (escaping, two-tap real
//    test, nothing without a payload), the recipients editor (data-*
//    attributes, no inline handlers, escaped values) and the client-side
//    E.164 check.
"use strict";
const assert = require("assert");
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const WEB = path.join(__dirname, "..", "..", "src", "dashboard", "web", "js");
const C = require(path.join(WEB, "components", "crash_modal.js"));
const G = require(path.join(WEB, "components", "gestures.js"));
const EID = "0123456789abcdef".repeat(2);   // no 32-hex literal in the repo

function payload(state, extra) {
    return Object.assign({
        state, event_id: EID, countdown_left_s: 30, recipients_n: 2, phone_ok: true,
        dry_run: false, forced_dry_run_reason: "", results: [], cancel_sms: null, error: "",
        modal: true, cancel_pending: false, send_now_pending: false, can_follow_up: false,
    }, extra || {});
}

// ── normalize / shouldShow ────────────────────────────────────────────────
assert.strictEqual(C.normalize(null), null);
assert.strictEqual(C.normalize(payload("idle")), null);
assert.strictEqual(C.normalize(payload("<b>")), null);
assert.strictEqual(C.normalize(payload("pending", { event_id: "XYZ" })), null);
assert.strictEqual(C.normalize(payload("pending", { event_id: "<img>" })), null);
let v = C.normalize(payload("pending", { countdown_left_s: 500, recipients_n: 9,
                                         forced_dry_run_reason: "<img src=x>" }));
assert.strictEqual(v.left, null);
assert.strictEqual(v.recipients, 0);
assert.strictEqual(v.reason, "");
assert.strictEqual(C.normalize(payload("pending", { dry_run: "no" })).dry, true);  // only false is real

assert.strictEqual(C.shouldShow(payload("pending"), null), true);
assert.strictEqual(C.shouldShow(payload("pending", { modal: false }), null), false);
assert.strictEqual(C.shouldShow(payload("sent"), EID + "|sent"), false);       // closed by tap
assert.strictEqual(C.shouldShow(payload("cancelled"), EID + "|sent"), true);   // a new result
assert.strictEqual(C.shouldShow(payload("pending"), EID + "|pending"), true);  // never a countdown

// ── texts ────────────────────────────────────────────────────────────────
let tx = C.texts(C.normalize(payload("pending", { dry_run: true,
                                                  forced_dry_run_reason: "not_calibrated" })));
assert.strictEqual(tx.count, "30");
assert.strictEqual(tx.dry, "TRYB TESTOWY – SMS nie zostanie wysłany");
assert.ok(/nieskalibrowane/.test(tx.reason), tx.reason);
assert.strictEqual(tx.cancel, "ANULUJ – nic się nie stało");
assert.strictEqual(tx.recipients, "odbiorcy SMS: 2");
tx = C.texts(C.normalize(payload("pending")));
assert.strictEqual(tx.dry, "");
assert.strictEqual(tx.reason, "");
tx = C.texts(C.normalize(payload("pending", { countdown_left_s: 0 })));
assert.ok(/WYSYŁANIE/.test(tx.label));
tx = C.texts(C.normalize(payload("armed", { phone_ok: false })));
assert.ok(/Łączenie z telefonem/.test(tx.phone));
tx = C.texts(C.normalize(payload("pending", { phone_ok: false, cancel_pending: true })));
assert.ok(/Anulowanie/.test(tx.phone) && tx.cancel === "Anulowanie…");
tx = C.texts(C.normalize(payload("failed_no_phone", { phone_ok: false, error: "no_phone" })));
assert.strictEqual(tx.result, "Brak połączenia z telefonem – SMS NIE zostanie wysłany");
// An arm request may have reached the phone: never "NIE zostanie wysłany".
v = C.normalize(payload("failed_no_phone", { phone_ok: false, error: "no_phone", may_send: true }));
assert.strictEqual(v.maySend, true);
tx = C.texts(v);
assert.ok(/MOŻE zostać wysłany/.test(tx.result) && !/NIE zostanie/.test(tx.result), tx.result);
assert.strictEqual(tx.resultCancel, "ANULUJ – nic się nie stało");
assert.strictEqual(C.closableByTap(v), false, "a stray tap must not hide the only ANULUJ");
assert.strictEqual(tx.close, "");
v = C.normalize(payload("failed_no_phone", { may_send: true, cancel_pending: true }));
assert.ok(/Anulowanie/.test(C.texts(v).result) && C.closableByTap(v));
assert.strictEqual(C.normalize(payload("failed_no_phone", { may_send: "yes" })).maySend, false);
assert.strictEqual(C.normalize(payload("sent", { may_send: true })).maySend, false);
// The phone went silent after the deadline: a closable "no confirmation" view.
v = C.normalize(payload("pending", { countdown_left_s: 0, phone_ok: false, unconfirmed: true }));
assert.strictEqual(C.modeOf(v), "result");
assert.ok(C.closableByTap(v));
tx = C.texts(v);
assert.ok(/mógł już wysłać/.test(tx.result), tx.result);
assert.strictEqual(tx.resultCancel, tx.followUp, "unconfirmed: never a bare ANULUJ to silence it");
assert.strictEqual(C.shouldShow(payload("pending", { unconfirmed: true }), EID + "|unconfirmed"), false);
assert.strictEqual(C.shouldShow(payload("sent", { unconfirmed: true }), EID + "|unconfirmed"), true);
assert.strictEqual(C.modeOf(C.normalize(payload("pending", { countdown_left_s: 0 }))), "countdown");
// A resumed event still connecting with its shown time used up.
tx = C.texts(C.normalize(payload("armed", { countdown_left_s: 0, phone_ok: false })));
assert.ok(/Łączenie/.test(tx.label) && /15 s/.test(tx.phone), tx.label + " / " + tx.phone);
// The follow-up cancel SMS has its own route.
assert.strictEqual(C.ROUTES.follow_up, "/api/crash/follow_up");
assert.strictEqual(C.ROUTES.cancel, "/api/crash/cancel");
tx = C.texts(C.normalize(payload("sent", { cancel_sms: { state: "failed" } })));
assert.ok(/NIE wyszedł/.test(tx.result), tx.result);
tx = C.texts(C.normalize(payload("cancelled", { cancel_sms: { state: "failed" } })));
assert.ok(/niepotwierdzony/.test(tx.result), tx.result);
tx = C.texts(C.normalize(payload("sent", { dry_run: true, results: [
    { state: "sent_dry" }, { state: "sent_dry" }] })));
assert.strictEqual(tx.result, "SMS wysłany (2 z 2)");
assert.ok(/tryb testowy/.test(tx.resultDry));
tx = C.texts(C.normalize(payload("partial", { results: [{ state: "sent" }, { state: "failed" }] })));
assert.strictEqual(tx.result, "SMS wysłany tylko do 1 z 2 odbiorców");
tx = C.texts(C.normalize(payload("failed", { error: "no_recipients" })));
assert.ok(/Brak odbiorców/.test(tx.result));
tx = C.texts(C.normalize(payload("cancelled", { cancel_sms: { state: "sent" } })));
assert.ok(/odwołujący/.test(tx.result));
// "$&" in a translation stays literal (function replacements)
tx = C.texts(C.normalize(payload("pending")), (k, d) => (k === "crash_recipients" ? "$& {n}" : d));
assert.strictEqual(tx.recipients, "$& 2");

// GSM-7 is the phone's business, but our own window texts must not leak
// markup: esc() is used for every static text put into the skeleton.
assert.strictEqual(C.esc(`<a href="x">'&`), "&lt;a href=&quot;x&quot;&gt;&#39;&amp;");
const evilT = () => "<img src=x onerror=alert(1)>";
for (const html of [C.countdownHtml(C.texts(C.normalize(payload("pending")), evilT)),
                    C.resultHtml(C.texts(C.normalize(payload("sent")), evilT))]) {
    assert.ok(!/<img/.test(html), "markup from a translation reached the skeleton");
}
for (const html of [C.countdownHtml(C.texts(C.normalize(payload("pending")))),
                    C.resultHtml(C.texts(C.normalize(payload("sent"))))]) {
    assert.ok(!/<[^>]*\son[a-z]+=/i.test(html), "inline JS in the window");
    assert.ok(/data-crash-remote/.test(html), "no read-only note for network clients");
}
assert.strictEqual(C.isKiosk(), false);              // node: no location → not the kiosk

// ── geometry from the inline styles ───────────────────────────────────────
const sk = C.countdownHtml(C.texts(C.normalize(payload("pending"))));
const cancelTag = sk.match(/<button[^>]*data-crash-action="cancel"[^>]*>/)[0];
const w = Number(cancelTag.match(/width:(\d+(?:\.\d+)?)vw/)[1]);
const h = Number(cancelTag.match(/height:(\d+(?:\.\d+)?)vh/)[1]);
assert.ok(w * h / 10000 >= 1 / 3, `ANULUJ covers only ${w}vw x ${h}vh`);
const gap = Number(sk.match(/data-crash-gap style="width:(\d+)vw/)[1]);
assert.ok(gap >= 15, "the 112 slot must be >= 15% of the width away from ANULUJ");
assert.ok(/data-crash-112-slot/.test(sk), "no reserved place for the 112 button");
assert.ok(/data-crash-action="send_now"/.test(sk));
assert.ok(!/112/.test(sk.replace(/<!--[\s\S]*?-->/g, "").replace(/data-crash-112-slot/g, "")),
          "no 112 logic in this batch");

// ── app.js: overlay list + sync on every screen ───────────────────────────
const appSrc = fs.readFileSync(path.join(WEB, "app.js"), "utf8");
const overlays = appSrc.match(/const GESTURE_OVERLAYS = ([\s\S]*?);/)[1];
assert.ok(/#crash-modal/.test(overlays), "#crash-modal is not in GESTURE_OVERLAYS");

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
const synced = [];
const ctx = {
    console, setTimeout, clearTimeout, Promise, JSON, Math, Date,
    setInterval: () => 0, clearInterval() {},
    requestAnimationFrame: () => 0,
    performance: { now: () => 0 },
    localStorage: { getItem: () => null, setItem() {} },
    fetch: async (url) => ({ ok: true, json: async () => (url === "/api/boot_mode"
        ? { boot_mode: "cold" } : {}) }),
    DataStore: {
        init() {}, unsubscribe() {}, get() {}, sendKey() {}, sendAATouch() {},
        getAll: () => ({}),
        subscribe(key, fn) { if (key === "*") dataListener = fn; },
    },
    AppBar: { render: () => "", update() {} },
    NavBar: { render: () => "" },
    CrashModal: { sync(cs) { synced.push(cs); } },
};
ctx.document = {
    body: el("body"), hidden: false, activeElement: null,
    getElementById: el, addEventListener() {}, querySelector: () => null,
};
ctx.window = { addEventListener() {}, innerHeight: 600, BCMGestures: G, document: ctx.document };
vm.createContext(ctx);
vm.runInContext(appSrc, ctx, { filename: "app.js" });
vm.runInContext("this.__App = App;", ctx);
const App = ctx.__App;
for (const s of ["init", "a1", "a2", "a3", "a4", "settings"]) {
    App.registerScreen(s, { render() {}, update() { if (s === "a3") throw new Error("boom"); } });
}

(async () => {
    await App.init();
    assert.ok(dataListener, "App did not subscribe to data updates");
    for (const screen of ["a2", "a1", "a3", "settings"]) {
        App.navigateTo(screen);
        synced.length = 0;
        const cs = payload("pending", { countdown_left_s: 12 });
        // (DataStore._notify swallows a subscriber's exception — like here.)
        try { dataListener({ crash_sms: cs }); } catch (e) { assert.strictEqual(screen, "a3"); }
        assert.strictEqual(App.getCurrentScreen(), screen, "the window must not navigate");
        assert.strictEqual(synced.length, 1, `not synced on ${screen}`);
        assert.strictEqual(synced[0].countdown_left_s, 12);
    }
    dataListener({});                      // module off: sync(undefined) closes it
    assert.strictEqual(synced[synced.length - 1], undefined);

    // ── settings.js rows ─────────────────────────────────────────────────
    const sctx = {
        console, setTimeout: () => 0, clearTimeout() {}, Date, JSON, Math, Promise,
        App: { t: (k, d) => d, getConfig: () => ({}), navigateTo() {}, registerScreen() {} },
        document: { querySelector: () => null, querySelectorAll: () => [], activeElement: null },
    };
    vm.createContext(sctx);
    vm.runInContext(fs.readFileSync(path.join(WEB, "screens", "settings.js"), "utf8") +
                    "\nthis.__S = Settings;", sctx, { filename: "settings.js" });
    const S = sctx.__S;
    assert.strictEqual(S.crashSmsRowHtml(null), "");
    assert.strictEqual(S.crashEditorHtml(undefined), "");
    const row = S.crashSmsRowHtml({ dry_run: true, forced_dry_run_reason: "no_verified_test",
                                    recipients_n: 2, test: { last_verified_ts: "<b>" } });
    assert.ok(/data-crash-dry="1"/.test(row) && /brak potwierdzonego testowego SMS-a/.test(row));
    assert.ok(/data-crash-test/.test(row) && !/\son[a-z]+=/i.test(row));
    assert.ok(/brak potwierdzonego testu/.test(row), "a non-number timestamp was shown");
    const evil = S.crashSmsRowHtml({ dry_run: false, forced_dry_run_reason: "<img src=x>",
                                     recipients_n: "<b>", test: { request: "<i>" } });
    assert.ok(!/<img|<b>|<i>/.test(evil), "payload text reached the markup");
    assert.ok(/data-crash-dry="0"/.test(evil));
    assert.ok(!/data-crash-test /.test(evil), "test button without recipients");
    S._crash.recipients = ['"><img src=x>', "48601234567", ""];
    const ed = S.crashEditorHtml({ state: "idle" });
    assert.ok(!/<img/.test(ed), "a typed value broke out of its attribute");
    assert.ok(/data-crash-rcpt="0"/.test(ed) && /data-crash-save/.test(ed));
    assert.ok(!/\son[a-z]+=/i.test(ed), "inline handler in the editor");
    // Two taps for a REAL test: the first only arms the button.
    S._crash.testArmAt = Date.now();
    assert.ok(/PRAWDZIWY SMS do 2 odbiorców/.test(S.crashSmsRowHtml({ recipients_n: 2 })));
    S._crash.testArmAt = 0;

    const P = (fields) => {
        const out = JSON.parse(JSON.stringify(S.crashParseRecipients(fields)));
        const reason = out.reason;
        delete out.reason;
        return Object.assign(out, reason ? { reason } : {});
    };
    assert.deepStrictEqual(P(["48601234567", "", "+48 602-345-678"]),
                           { numbers: ["+48601234567", "+48602345678"], bad: -1 });
    assert.deepStrictEqual(P(["0048601234567", "48601234567"]),
                           { numbers: ["+48601234567"], bad: -1 });          // duplicate
    assert.deepStrictEqual(P(["", "601234"]), { numbers: [], bad: 1 });       // too short
    assert.deepStrictEqual(P(["0601234567"]), { numbers: [], bad: 0 });       // no country code
    // A Polish number typed without 48 would become +60… (Malaysia).
    assert.deepStrictEqual(P(["601234567"]), { numbers: [], bad: 0, reason: "no_cc" });
    assert.deepStrictEqual(P(["48601234567", "601 234 567"]),
                           { numbers: [], bad: 1, reason: "no_cc" });
    assert.deepStrictEqual(P(["4860123456"]), { numbers: [], bad: 0 });       // 48 + 8 digits
    assert.deepStrictEqual(P(["48 601 234 567"]), { numbers: ["+48601234567"], bad: -1 });
    assert.deepStrictEqual(P(["4915112345678"]), { numbers: ["+4915112345678"], bad: -1 });
    assert.deepStrictEqual(P(["4860123456789012"]), { numbers: [], bad: 0 }); // too long
    assert.deepStrictEqual(P(["48 60a"]), { numbers: [], bad: 0 });
    assert.deepStrictEqual(P(["", "", "", "48601234567"]), { numbers: [], bad: -1 }); // only 3 fields
    // Saved numbers are shown with their country code visible.
    assert.strictEqual(S.crashFieldText("+48601234567"), "48 601 234 567");
    assert.strictEqual(S.crashFieldText("+4915112345678"), "4915112345678");
    assert.strictEqual(S.crashFieldText("<b>"), "");
    assert.strictEqual(S.crashFieldText(null), "");

    // Two taps for a REAL test, and a bounce of the first is no confirmation.
    let posted = 0;
    sctx.fetch = async () => { posted += 1; return { ok: true, status: 200, json: async () => ({}) }; };
    let fakeNow = 1000000;
    sctx.Date = class extends Date { static now() { return fakeNow; } };
    vm.runInContext("Date = this.Date; fetch = this.fetch;", sctx);
    S._crash.testArmAt = 0;
    await S.crashTest();                                 // arms
    fakeNow += 40;                                        // a bounce, 40 ms later
    await S.crashTest();
    assert.strictEqual(posted, 0, "a bounced tap sent a REAL test SMS");
    fakeNow += 1000;
    await S.crashTest();                                 // a real second tap
    assert.strictEqual(posted, 1);
    process.stdout.write("ok\n");
})().catch((e) => {
    process.stderr.write(String(e && e.stack || e) + "\n");
    process.exit(1);
});
