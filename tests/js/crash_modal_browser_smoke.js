// Headless-Chromium check of the crash SMS window (#crash-modal,
// components/crash_modal.js + app.js _syncCrashState) on the real dashboard
// at the car's 1024x600 panel, for tests/test_frontend_gestures.py. Needs the
// `playwright` package and its Chromium; without either it prints
// "SKIP: <reason>" and exits 0 so the pytest wrapper can skip.
//
// Nothing leaves the process: every request is answered here, and the data
// WebSocket is a stub this script pushes payloads through (exactly what
// web_viewer._crash_sms_summary sends). Checked, with mouse and with touch:
//  - the window opens on Android Auto (A2) and on A1 without navigating,
//    fixed, z-index 300, covering the whole viewport;
//  - the countdown is big and follows countdown_left_s; recipients, phone
//    state, the DRY RUN badge and the forced-test-mode reason are shown;
//  - "ANULUJ – nic się nie stało" covers >= 1/3 of the screen, is the
//    element under its own centre (nothing on top) and NOTHING of the window
//    lies outside 1024x600; the reserved 112 slot is >= 15% of the width
//    away from ANULUJ;
//  - a pull-down from the top edge does not change the screen (the window is
//    in GESTURE_OVERLAYS);
//  - the countdown beeps (WebAudio) while pending, stops when cancelled;
//  - tapping ANULUJ posts {event_id} once to /api/crash/cancel;
//  - the result view shows the outcome, fits the screen and closes on a tap,
//    and the same result does not come back;
//  - hostile strings in the payload never become markup;
//  - a countdown stuck at 0 (the phone stopped answering) does not beep, and
//    "no confirmation from the phone" (unconfirmed) is a closable view;
//  - "SMS MAY still be sent" (may_send) keeps a working ANULUJ and is not
//    closed by a stray tap; "Jestem OK" posts to /api/crash/follow_up;
//  - off the kiosk (a passenger's phone: not a loopback host) the window is
//    read-only — no buttons, a note that only the car's screen can cancel.
// The kiosk loads http://localhost:5002 — so does this script (every
// request is still answered here; nothing listens on that port).
"use strict";

const fs = require("fs");
const path = require("path");

let chromium;
try {
    ({ chromium } = require("playwright"));
} catch (e) {
    process.stdout.write("SKIP: playwright not installed\n");
    process.exit(0);
}

const WEB = path.resolve(__dirname, "..", "..", "src", "dashboard", "web");
const ORIGIN = "http://localhost:5002";        // the kiosk's own address
const REMOTE_ORIGIN = "http://bcm.invalid";    // a network client
const W = 1024;
const H = 600;
const EID = "0123456789abcdef".repeat(2);   // no 32-hex literal in the repo
const EID2 = "fedcba9876543210".repeat(2);
const MIME = {
    ".html": "text/html; charset=utf-8", ".js": "application/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8", ".json": "application/json", ".svg": "image/svg+xml",
    ".png": "image/png", ".jpg": "image/jpeg", ".ttf": "font/ttf", ".woff2": "font/woff2",
    ".woff": "font/woff", ".mp4": "video/mp4",
};

function fail(msg) { throw new Error(msg); }

function stubWebSocket() {
    window.__ws = [];
    window.WebSocket = class {
        constructor(url) { this.url = url; this.readyState = 0; window.__ws.push(this); }
        send() {}
        close() {}
        addEventListener() {}
        removeEventListener() {}
    };
    window.__push = (payload) => {
        for (const ws of window.__ws) {
            if (/\/ws$/.test(ws.url) && ws.onmessage) ws.onmessage({ data: JSON.stringify(payload) });
        }
    };
    // Count beeps without a sound card (headless): wrap the oscillator start.
    window.__beeps = 0;
    const Ctx = window.AudioContext || window.webkitAudioContext;
    if (Ctx) {
        const orig = Ctx.prototype.createOscillator;
        Ctx.prototype.createOscillator = function () {
            const osc = orig.call(this);
            const start = osc.start.bind(osc);
            osc.start = (...a) => { window.__beeps += 1; return start(...a); };
            return osc;
        };
    }
}

function crash(state, extra) {
    return Object.assign({
        state, event_id: EID, ts: 1763000000, countdown_s: 45, countdown_left_s: 45,
        deadline_ts: 1763000045, recipients_n: 2, phone_ok: true, dry_run: true,
        forced_dry_run_reason: "no_verified_test", results: [], cancel_sms: null, error: "",
        modal: true, cancel_pending: false, send_now_pending: false, can_follow_up: false,
        test: { request: "", error: "", state: null, ts: null, dry_run: null, verified: false,
                last_verified_ts: null },
    }, extra || {});
}

async function geometry(page) {
    return page.evaluate(() => {
        const m = document.getElementById("crash-modal");
        if (!m) return null;
        const r = (el) => { const b = el.getBoundingClientRect();
            return { x: b.left, y: b.top, w: b.width, h: b.height, r: b.right, b: b.bottom }; };
        const cancel = m.querySelector("[data-crash-action='cancel']");
        const slot = m.querySelector("[data-crash-112-slot]");
        const out = [];
        for (const el of m.querySelectorAll("*")) {
            const b = el.getBoundingClientRect();
            const st = getComputedStyle(el);
            if (b.width === 0 || b.height === 0 || st.display === "none" || st.visibility === "hidden") continue;
            if (b.left < -0.5 || b.top < -0.5 || b.right > innerWidth + 0.5 || b.bottom > innerHeight + 0.5) {
                out.push(`${el.tagName}.${[...el.attributes].map((a) => a.name).join(",")} ${JSON.stringify(r(el))}`);
            }
            // text clipped by an ancestor with overflow:hidden?
            if (el.scrollHeight > el.clientHeight + 2 && st.overflow === "hidden" && el.children.length) {
                const kids = [...el.children].filter((k) => getComputedStyle(k).display !== "none");
                const last = kids[kids.length - 1];
                if (last && last.getBoundingClientRect().bottom > b.bottom + 1) {
                    out.push(`clipped: ${el.tagName} ${JSON.stringify(r(el))}`);
                }
            }
        }
        let hit = null;
        if (cancel) {
            const c = cancel.getBoundingClientRect();
            const at = document.elementFromPoint(c.left + c.width / 2, c.top + c.height / 2);
            hit = !!(at && (at === cancel || cancel.contains(at)));
        }
        return {
            modal: r(m), z: getComputedStyle(m).zIndex, position: getComputedStyle(m).position,
            parentIsBody: m.parentNode === document.body,
            cancel: cancel ? r(cancel) : null, slot: slot ? r(slot) : null,
            offscreen: out, cancelOnTop: hit,
            count: (m.querySelector("[data-crash-count]") || {}).textContent,
            dry: (m.querySelector("[data-crash-dry]") || {}).textContent,
            reason: (m.querySelector("[data-crash-reason]") || {}).textContent,
            phone: (m.querySelector("[data-crash-phone]") || {}).textContent,
            recipients: (m.querySelector("[data-crash-recipients]") || {}).textContent,
            result: (m.querySelector("[data-crash-result]") || {}).textContent,
            imgs: m.querySelectorAll("img,script,iframe").length,
            cancelFont: cancel ? parseFloat(getComputedStyle(cancel).fontSize) : 0,
            countFont: parseFloat(getComputedStyle(m.querySelector("[data-crash-count]") || m).fontSize),
        };
    });
}

async function open(browser, touch, origin, posts, errors) {
    const ctx = await browser.newContext({ viewport: { width: W, height: H }, hasTouch: touch });
    const page = await ctx.newPage();
    page.on("pageerror", (e) => errors.push(e.message));
    await ctx.route("**/*", async (route) => {
        const req = route.request();
        const url = new URL(req.url());
        if (url.origin !== origin) return route.abort();
        const p = url.pathname;
        const json = (obj, status) => route.fulfill({ status: status || 200,
                                                      contentType: "application/json",
                                                      body: JSON.stringify(obj) });
        if (p.startsWith("/api/crash/")) {
            posts.push([p, JSON.parse(req.postData() || "null")]);
            return json({ ok: true });
        }
        if (p.startsWith("/api/") || p.startsWith("/bt/") || p.startsWith("/aa/")) {
            return json(p === "/api/boot_mode" ? { boot_mode: "cold" } : {});
        }
        const file = path.resolve(WEB, "." + (p === "/" ? "/index.html" : p));
        if (!file.startsWith(WEB + path.sep) || !fs.existsSync(file) || !fs.statSync(file).isFile()) {
            return route.fulfill({ status: 404, body: "" });
        }
        return route.fulfill({ status: 200, body: fs.readFileSync(file),
                               contentType: MIME[path.extname(file)] || "application/octet-stream" });
    });
    await ctx.addInitScript(stubWebSocket);
    await page.goto(origin + "/");
    await page.waitForFunction(() => typeof App !== "undefined" && App.getCurrentScreen
                                     && App.getCurrentScreen() === "a1");
    await page.evaluate(() => {
        if (typeof Splash !== "undefined" && Splash.hide) Splash.hide();
        const s = document.getElementById("bcm-splash-overlay");
        if (s) s.remove();
    });
    return { ctx, page };
}

async function tap(page, touch, x, y) {
    if (touch) await page.touchscreen.tap(x, y);
    else await page.mouse.click(x, y);
}

async function box(page, sel) {
    return page.evaluate((s) => {
        const el = document.querySelector(s);
        if (!el) return null;
        const b = el.getBoundingClientRect();
        const st = getComputedStyle(el);
        return { x: b.left, y: b.top, w: b.width, h: b.height,
                 visible: st.display !== "none" && st.visibility !== "hidden" && b.width > 0,
                 text: el.textContent };
    }, sel);
}

async function run(browser, touch) {
    const tag = `${W}x${H}${touch ? " touch" : ""}`;
    const posts = [];
    const errors = [];
    const { ctx, page } = await open(browser, touch, ORIGIN, posts, errors);
    if (!await page.evaluate(() => CrashModal.isKiosk())) fail(`${tag}: localhost is not the kiosk`);
    await page.evaluate(() => App.navigateTo("a2"));
    await page.waitForTimeout(200);

    // ── countdown on Android Auto ─────────────────────────────────────────
    await page.evaluate((p) => window.__push({ crash_sms: p }), crash("pending"));
    await page.waitForSelector("#crash-modal [data-crash-action='cancel']");
    let g = await geometry(page);
    if (App_screen(await page.evaluate(() => App.getCurrentScreen())) !== "a2") fail(`${tag}: screen changed`);
    if (g.z !== "300" || g.position !== "fixed" || !g.parentIsBody) fail(`${tag}: modal ${g.z} ${g.position} ${g.parentIsBody}`);
    if (Math.round(g.modal.x) !== 0 || Math.round(g.modal.y) !== 0 || Math.round(g.modal.w) !== W
        || Math.round(g.modal.h) !== H) fail(`${tag}: modal does not cover the screen ${JSON.stringify(g.modal)}`);
    if (g.offscreen.length) fail(`${tag}: off-screen / clipped: ${g.offscreen.join(" | ")}`);
    const area = g.cancel.w * g.cancel.h;
    if (area < (W * H) / 3) fail(`${tag}: cancel covers ${(area / (W * H)).toFixed(3)} of the screen`);
    if (!g.cancelOnTop) fail(`${tag}: something covers the cancel button`);
    if (g.slot.x - g.cancel.r < 0.15 * W - 1) fail(`${tag}: 112 slot only ${g.slot.x - g.cancel.r}px from ANULUJ`);
    if (g.count !== "45" || g.countFont < 120) fail(`${tag}: countdown ${g.count} ${g.countFont}px`);
    if (!/TRYB TESTOWY/.test(g.dry)) fail(`${tag}: no DRY RUN badge (${g.dry})`);
    if (!/brak potwierdzonego testowego SMS-a/.test(g.reason)) fail(`${tag}: no reason (${g.reason})`);
    if (!/2/.test(g.recipients)) fail(`${tag}: recipients ${g.recipients}`);
    if (g.cancelFont < 28) fail(`${tag}: cancel font ${g.cancelFont}`);
    await page.screenshot({ path: process.env.CRASH_SHOT_DIR
        ? path.join(process.env.CRASH_SHOT_DIR, `countdown${touch ? "-touch" : ""}.png`) : undefined });

    // The countdown follows the backend.
    await page.evaluate((p) => window.__push({ crash_sms: p }), crash("pending", { countdown_left_s: 9 }));
    g = await geometry(page);
    if (g.count !== "9") fail(`${tag}: countdown not updated (${g.count})`);

    // Beeps while pending.
    const beeping = await page.evaluate(() => CrashModal._beeping());
    if (!beeping) fail(`${tag}: not beeping while pending`);

    // A pull-down from the top edge must not navigate under the window.
    await page.evaluate(() => {
        const mk = (y) => new Touch({ identifier: 1, target: document.body, clientX: 500, clientY: y });
        const fire = (type, y) => document.body.dispatchEvent(new TouchEvent(type, {
            bubbles: true, cancelable: true, touches: type === "touchend" ? [] : [mk(y)],
            changedTouches: [mk(y)] }));
        fire("touchstart", 5);
        fire("touchend", 200);
    });
    if (await page.evaluate(() => App.getCurrentScreen()) !== "a2") fail(`${tag}: edge pull navigated under the window`);

    // Hostile strings never become markup (whitelisted / textContent).
    await page.evaluate((p) => window.__push({ crash_sms: p }), crash("pending", {
        forced_dry_run_reason: "<img src=x onerror=alert(1)>", error: "<script>x</script>",
        results: [{ state: "<img src=x>", verified: true }] }));
    g = await geometry(page);
    if (g.imgs !== 0) fail(`${tag}: markup injected`);
    if (g.reason !== "") fail(`${tag}: unknown reason shown: ${g.reason}`);

    // Tap ANULUJ → one POST with the event id.
    const c = g.cancel;
    if (touch) await page.touchscreen.tap(c.x + c.w / 2, c.y + c.h / 2);
    else await page.mouse.click(c.x + c.w / 2, c.y + c.h / 2);
    await page.waitForTimeout(100);
    if (touch) await page.touchscreen.tap(c.x + c.w / 2, c.y + c.h / 2);
    else await page.mouse.click(c.x + c.w / 2, c.y + c.h / 2);
    await page.waitForTimeout(150);
    const cancels = posts.filter(([p]) => p === "/api/crash/cancel");
    if (cancels.length !== 1 || cancels[0][1].event_id !== EID || Object.keys(cancels[0][1]).length !== 1) {
        fail(`${tag}: cancel posts ${JSON.stringify(posts)}`);
    }

    // Backend: cancel pending (no phone) → still the countdown, no beeping.
    await page.evaluate((p) => window.__push({ crash_sms: p }),
        crash("pending", { cancel_pending: true, phone_ok: false, countdown_left_s: 7 }));
    g = await geometry(page);
    if (!/Anulowanie/.test(g.phone)) fail(`${tag}: cancel pending not shown (${g.phone})`);
    if (await page.evaluate(() => CrashModal._beeping())) fail(`${tag}: still beeping after cancel`);

    // ── result: cancelled ─────────────────────────────────────────────────
    await page.evaluate((p) => window.__push({ crash_sms: p }),
        crash("cancelled", { countdown_left_s: null, deadline_ts: null }));
    await page.waitForSelector("#crash-modal [data-crash-result]");
    g = await geometry(page);
    if (!/Anulowano/.test(g.result)) fail(`${tag}: result ${g.result}`);
    if (g.offscreen.length) fail(`${tag}: result off-screen: ${g.offscreen.join(" | ")}`);
    if (touch) await page.touchscreen.tap(W / 2, H - 40);
    else await page.mouse.click(W / 2, H - 40);
    await page.waitForTimeout(100);
    if (await page.$("#crash-modal")) fail(`${tag}: result did not close on a tap`);
    await page.evaluate((p) => window.__push({ crash_sms: p }),
        crash("cancelled", { countdown_left_s: null, deadline_ts: null, ts: 1763000001 }));
    if (await page.$("#crash-modal")) fail(`${tag}: dismissed result came back`);

    // ── no phone at arm time (another event), on A1 ───────────────────────
    await page.evaluate(() => App.navigateTo("a1"));
    await page.evaluate((p) => window.__push({ crash_sms: p }), crash("failed_no_phone", {
        event_id: EID2, phone_ok: false, error: "no_phone",
        countdown_left_s: null }));
    await page.waitForSelector("#crash-modal [data-crash-result]");
    g = await geometry(page);
    if (!/Brak połączenia z telefonem – SMS NIE zostanie wysłany/.test(g.result)) fail(`${tag}: ${g.result}`);
    if (await page.evaluate(() => App.getCurrentScreen()) !== "a1") fail(`${tag}: navigated`);
    await page.screenshot({ path: process.env.CRASH_SHOT_DIR
        ? path.join(process.env.CRASH_SHOT_DIR, `no-phone${touch ? "-touch" : ""}.png`) : undefined });

    // modal: false from the backend closes it.
    await page.evaluate((p) => window.__push({ crash_sms: p }), crash("failed_no_phone", {
        event_id: EID2, modal: false }));
    if (await page.$("#crash-modal")) fail(`${tag}: modal:false did not close`);

    // ── a countdown stuck at 0 does not beep ─────────────────────────────
    const EID3 = "0a0b0c0d0e0f0102".repeat(2);
    await page.evaluate((p) => window.__push({ crash_sms: p }), crash("pending", {
        event_id: EID3, countdown_left_s: 0, phone_ok: false }));
    await page.waitForSelector("#crash-modal [data-crash-action='cancel']");
    if (await page.evaluate(() => CrashModal._beeping())) fail(`${tag}: beeping at 0`);
    // … and once BCM says "unconfirmed" it is a result that a tap closes.
    await page.evaluate((p) => window.__push({ crash_sms: p }), crash("pending", {
        event_id: EID3, countdown_left_s: 0, phone_ok: false, unconfirmed: true }));
    await page.waitForSelector("#crash-modal [data-crash-result]");
    let r = await box(page, "#crash-modal [data-crash-result]");
    if (!/mógł już wysłać/.test(r.text)) fail(`${tag}: unconfirmed text ${r.text}`);
    if (await page.evaluate(() => CrashModal._beeping())) fail(`${tag}: beeping unconfirmed`);
    await tap(page, touch, W / 2, 30);
    await page.waitForTimeout(100);
    if (await page.$("#crash-modal")) fail(`${tag}: unconfirmed did not close on a tap`);
    await page.evaluate((p) => window.__push({ crash_sms: p }), crash("pending", {
        event_id: EID3, countdown_left_s: 0, phone_ok: false, unconfirmed: true }));
    if (await page.$("#crash-modal")) fail(`${tag}: dismissed unconfirmed came back`);

    // ── the phone MAY hold it: ANULUJ stays, a stray tap does not close ──
    const EID4 = "1a1b1c1d1e1f1112".repeat(2);
    await page.evaluate((p) => window.__push({ crash_sms: p }), crash("failed_no_phone", {
        event_id: EID4, phone_ok: false, error: "no_phone", may_send: true,
        countdown_left_s: null }));
    await page.waitForSelector("#crash-modal [data-crash-result]");
    r = await box(page, "#crash-modal [data-crash-result]");
    if (!/MOŻE/.test(r.text) || /NIE zostanie/.test(r.text)) fail(`${tag}: may_send text ${r.text}`);
    g = await geometry(page);
    if (g.offscreen.length) fail(`${tag}: may_send off-screen: ${g.offscreen.join(" | ")}`);
    await tap(page, touch, W / 2, 30);
    await page.waitForTimeout(100);
    if (!await page.$("#crash-modal")) fail(`${tag}: a stray tap hid the only ANULUJ`);
    const rc = await box(page, "#crash-modal [data-crash-mode='result'] [data-crash-action='cancel']");
    if (!rc || !rc.visible || !/ANULUJ/.test(rc.text)) fail(`${tag}: no ANULUJ ${JSON.stringify(rc)}`);
    posts.length = 0;
    await tap(page, touch, rc.x + rc.w / 2, rc.y + rc.h / 2);
    await page.waitForTimeout(150);
    if (posts.length !== 1 || posts[0][0] !== "/api/crash/cancel" || posts[0][1].event_id !== EID4) {
        fail(`${tag}: may_send cancel posts ${JSON.stringify(posts)}`);
    }

    // ── "Jestem OK" after a sent SMS: its own route ───────────────────────
    const EID5 = "2a2b2c2d2e2f2122".repeat(2);
    await page.evaluate((p) => window.__push({ crash_sms: p }), crash("sent", {
        event_id: EID5, dry_run: false, forced_dry_run_reason: "", can_follow_up: true,
        results: [{ state: "sent", verified: true }], countdown_left_s: null }));
    await page.waitForSelector("#crash-modal [data-crash-action='follow_up']");
    const fu = await box(page, "#crash-modal [data-crash-action='follow_up']");
    if (!fu.visible) fail(`${tag}: no Jestem OK button`);
    const hiddenCancel = await box(page, "#crash-modal [data-crash-mode='result'] [data-crash-action='cancel']");
    if (hiddenCancel && hiddenCancel.visible) fail(`${tag}: ANULUJ shown after a sent SMS`);
    posts.length = 0;
    await tap(page, touch, fu.x + fu.w / 2, fu.y + fu.h / 2);
    await page.waitForTimeout(150);
    if (posts.length !== 1 || posts[0][0] !== "/api/crash/follow_up" || posts[0][1].event_id !== EID5) {
        fail(`${tag}: follow-up posts ${JSON.stringify(posts)}`);
    }

    if (errors.length) fail(`${tag}: page errors: ${errors.join("; ")}`);
    await ctx.close();
}

/** A passenger's phone on the car's network: same window, read-only. */
async function runRemote(browser) {
    const posts = [];
    const errors = [];
    const { ctx, page } = await open(browser, true, REMOTE_ORIGIN, posts, errors);
    if (await page.evaluate(() => CrashModal.isKiosk())) fail("remote: counted as the kiosk");
    await page.evaluate((p) => window.__push({ crash_sms: p }), crash("pending"));
    await page.waitForSelector("#crash-modal [data-crash-remote]", { state: "attached" });
    const cancel = await box(page, "#crash-modal [data-crash-action='cancel']");
    const sendNow = await box(page, "#crash-modal [data-crash-action='send_now']");
    const note = await box(page, "#crash-modal [data-crash-mode='countdown'] [data-crash-remote]");
    if (cancel.visible || sendNow.visible) fail("remote: action buttons shown");
    if (!note.visible || !/tylko na ekranie w aucie/.test(note.text)) fail(`remote: note ${JSON.stringify(note)}`);
    await page.touchscreen.tap(note.x + note.w / 2, note.y + note.h / 2);
    await page.waitForTimeout(100);
    if (posts.length) fail(`remote: posted ${JSON.stringify(posts)}`);
    await page.evaluate((p) => window.__push({ crash_sms: p }), crash("failed_no_phone", {
        may_send: true, phone_ok: false, countdown_left_s: null }));
    await page.waitForSelector("#crash-modal [data-crash-result]");
    const rc = await box(page, "#crash-modal [data-crash-mode='result'] [data-crash-action='cancel']");
    if (rc && rc.visible) fail("remote: ANULUJ in the result view");
    await page.touchscreen.tap(W / 2, 30);              // any tap closes it off the kiosk
    await page.waitForTimeout(100);
    if (await page.$("#crash-modal")) fail("remote: did not close");
    if (errors.length) fail(`remote: page errors: ${errors.join("; ")}`);
    await ctx.close();
}


function App_screen(s) { return s; }

(async () => {
    let browser;
    try {
        browser = await chromium.launch();
    } catch (e) {
        process.stdout.write(`SKIP: chromium not available (${String(e.message).split("\n")[0]})\n`);
        process.exit(0);
    }
    try {
        await run(browser, false);
        await run(browser, true);
        await runRemote(browser);
    } finally {
        await browser.close();
    }
    process.stdout.write("ok\n");
})().catch((e) => {
    process.stderr.write(String(e && e.stack || e) + "\n");
    process.exit(1);
});
