// Headless-Chromium check of the "Wybudzono" banner (modules.remote_session,
// plan E: components/wake_banner.js + app.js _syncWakeBanner) and the
// Settings row "Wybudzanie" on the real dashboard at the car's 1024x600
// panel, for tests/test_frontend_gestures.py. Needs the `playwright` package
// and its Chromium; without either it prints "SKIP: <reason>" and exits 0.
//
// Nothing leaves the process: every request is answered here and the data
// WebSocket is a stub this script pushes payloads through (what
// web_viewer._remote_session_summary sends). Checked:
//  - ONE fixed bar on <body> at the bottom, z-index 250, inside the 1024 px
//    width, buttons ≥ 44 px high, "Wybudzono: drzwi — uśpienie za 04:59";
//  - the countdown runs on its own between payloads (mm:ss goes down);
//  - it is NOT modal: the screen above it still takes a tap, and it is
//    not in GESTURE_OVERLAYS (a swipe still switches screens);
//  - it shows on Android Auto (A2) too, and under the crash window;
//  - "Nie usypiaj 30 min" / "Uśpij teraz" post {} to
//    /api/remote_session/hold | /sleep (a double tap posts once);
//  - "usypianie…": no buttons; module off / idle / garbage: no banner;
//  - opened from another host (a passenger's phone): text, no buttons;
//  - the Settings row shows the last wake and the refusals;
//  - it sits ABOVE the autohiding NavBar: with the bar shown every nav
//    button is still the tap target (A1 and A2), and a swipe up from the
//    bottom edge (gestures.js EDGE_PX) still reveals the bar (touch);
//  - a tap anywhere on the kiosk sends ONE {"type":"activity"} on
//    /ws/input (throttled; the idle suspend sees the driver using the
//    screen), none from another host;
//  - idle before the lease end: it counts down to idle, "(bez użycia)".
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
const W = 1024;
const H = 600;
const MIME = {
    ".html": "text/html; charset=utf-8", ".js": "application/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8", ".json": "application/json", ".svg": "image/svg+xml",
    ".png": "image/png", ".jpg": "image/jpeg", ".ttf": "font/ttf", ".woff2": "font/woff2",
    ".woff": "font/woff", ".mp4": "video/mp4",
};
const EID = "0123456789abcdef".repeat(2);

function fail(msg) { throw new Error(msg); }

function stubWebSocket() {
    window.__ws = [];
    window.__sent = [];
    window.WebSocket = class {
        constructor(url) { this.url = url; this.readyState = 0; window.__ws.push(this); }
        send(msg) { window.__sent.push([this.url, msg]); }
        close() {}
        addEventListener() {}
        removeEventListener() {}
    };
    window.WebSocket.CONNECTING = 0;
    window.WebSocket.OPEN = 1;
    // Only /ws/input is "open" (sendActivity / sendKey ride it); the data
    // socket stays a stub this script pushes through.
    window.__openInput = () => {
        for (const ws of window.__ws) if (/\/ws\/input$/.test(ws.url)) ws.readyState = 1;
    };
    window.__activity = () => window.__sent.filter(([u, m]) => /\/ws\/input$/.test(u)
        && JSON.parse(m).type === "activity").length;
    window.__push = (payload) => {
        for (const ws of window.__ws) {
            if (/\/ws$/.test(ws.url) && ws.onmessage) ws.onmessage({ data: JSON.stringify(payload) });
        }
    };
}

const SESSION = {
    state: "session", reason: "door", since: 1763000000, lease_left_s: 299,
    sleep_pending: false, holds_used_min: 0, hold_step_min: 30, hold_max_min: 60,
    can_hold: true, idle_suspend_min: 10, link: true, ended: "",
    last_wake: { reason: "door", ts: 1763000000 }, denied_seen: 0, denied_total: 2,
    last_denied: null, last_denied_nano: "rate", cmd: null,
};

async function open(browser, origin, touch, posts, errors) {
    const ctx = await browser.newContext({ viewport: { width: W, height: H }, hasTouch: touch });
    const page = await ctx.newPage();
    page.on("pageerror", (e) => errors.push(e.message));
    await ctx.route("**/*", async (route) => {
        const req = route.request();
        const url = new URL(req.url());
        if (url.origin !== origin) return route.abort();
        const p = url.pathname;
        const json = (obj) => route.fulfill({ status: 200, contentType: "application/json",
                                              body: JSON.stringify(obj) });
        if (p.startsWith("/api/remote_session/") && req.method() === "POST") {
            posts.push([p, req.postData()]);
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

const push = (page, payload) => page.evaluate((p) => window.__push(p), payload);

async function banner(page) {
    return page.evaluate(() => {
        const all = document.querySelectorAll("#wake-banner");
        const el = all[0];
        if (!el) return { count: 0 };
        const st = getComputedStyle(el);
        const b = el.getBoundingClientRect();
        const btns = [...el.querySelectorAll("[data-wake-action]")].map((x) => {
            const r = x.getBoundingClientRect();
            return { a: x.getAttribute("data-wake-action"), h: r.height, w: r.width,
                     r: r.right, shown: getComputedStyle(x).display !== "none", text: x.textContent };
        });
        return {
            count: all.length, parentIsBody: el.parentNode === document.body,
            position: st.position, z: st.zIndex, l: b.left, r: b.right, t: b.top, b: b.bottom,
            line: (el.querySelector("[data-wake-line]") || {}).textContent || "", btns,
        };
    });
}

/** Every NavBar button's centre: is it still the tap target? */
async function navbarClear(page, tag) {
    await page.evaluate(() => App.showNavBar());
    await page.waitForTimeout(320);                    // 240 ms transition
    const hits = await page.evaluate(() => {
        const nav = document.getElementById("bcm-navbar");
        if (!nav) return null;
        return [...nav.children].map((c) => {
            const r = c.getBoundingClientRect();
            const el = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
            return el ? (el.closest("#wake-banner") ? "banner" : (nav.contains(el) ? "nav" : el.tagName)) : null;
        });
    });
    if (!hits || hits.length < 5 || hits.some((h) => h !== "nav")) {
        fail(`${tag}: navbar buttons covered ${JSON.stringify(hits)}`);
    }
    await page.evaluate(() => App.hideNavBar());
    await page.waitForTimeout(320);
}

/** A real touch swipe up from y0 (inside the bottom edge) through CDP. */
async function swipeUp(page, cdp, x, y0, dy) {
    await cdp.send("Input.dispatchTouchEvent", { type: "touchStart", touchPoints: [{ x, y: y0 }] });
    for (let i = 1; i <= 4; i++) {
        await cdp.send("Input.dispatchTouchEvent", { type: "touchMove",
            touchPoints: [{ x, y: y0 - (dy * i) / 4 }] });
        await page.waitForTimeout(20);
    }
    await cdp.send("Input.dispatchTouchEvent", { type: "touchEnd", touchPoints: [] });
    await page.waitForTimeout(80);
}

async function tapAt(page, touch, x, y) {
    if (touch) await page.touchscreen.tap(x, y);
    else await page.mouse.click(x, y);
}

async function run(browser, touch) {
    const tag = `${W}x${H}${touch ? " touch" : ""}`;
    const posts = [];
    const errors = [];
    const { ctx, page } = await open(browser, "http://localhost:5002", touch, posts, errors);

    await push(page, { remote_session: SESSION });
    await page.waitForSelector("#wake-banner [data-wake-action='hold']");
    let b = await banner(page);
    if (b.count !== 1 || !b.parentIsBody || b.position !== "fixed" || b.z !== "250") {
        fail(`${tag}: banner ${JSON.stringify(b)}`);
    }
    if (b.l < 0 || b.r > W || b.b > H || b.t < H / 2) fail(`${tag}: banner placement ${JSON.stringify(b)}`);
    if (!/^Wybudzono: drzwi — uśpienie za 0[34]:[0-5][0-9]$/.test(b.line)) fail(`${tag}: line ${b.line}`);
    const hold = b.btns.find((x) => x.a === "hold");
    const sleep = b.btns.find((x) => x.a === "sleep");
    if (!hold || !sleep || hold.h < 44 || sleep.h < 44 || sleep.r > W) fail(`${tag}: buttons ${JSON.stringify(b.btns)}`);
    if (hold.text !== "Nie usypiaj 30 min" || sleep.text !== "Uśpij teraz") fail(`${tag}: labels ${JSON.stringify(b.btns)}`);

    // the countdown runs between payloads
    const first = b.line;
    await page.waitForTimeout(2200);
    b = await banner(page);
    if (b.line === first) fail(`${tag}: countdown stuck at ${b.line}`);

    // not modal: the A1 screen above the bar still gets the tap target
    const above = await page.evaluate(([x, y]) => {
        const el = document.elementFromPoint(x, y);
        return el ? !!el.closest("#wake-banner") : null;
    }, [W / 2, H / 3]);
    if (above !== false) fail(`${tag}: the banner covers the screen`);
    const inGestures = await page.evaluate(() => {
        const el = document.getElementById("wake-banner");
        return el.matches("#osk-overlay, #reverse-overlay, #kiosk-restart-modal, #bt-pairing-overlay, "
                          + "#bcm-splash-overlay, #crash-modal");
    });
    if (inGestures) fail(`${tag}: banner treated as a gesture overlay`);

    // above the NavBar: its buttons stay tappable, and (touch) the swipe up
    // from the bottom edge still reveals it — starting right under the banner
    if (b.b > H - 68) fail(`${tag}: banner inside the navbar/edge zone (bottom ${b.b})`);
    await navbarClear(page, tag + " A1");
    if (touch) {
        const cdp = await page.context().newCDPSession(page);
        for (const y0 of [575, 592]) {
            await page.evaluate(() => App.hideNavBar());
            await swipeUp(page, cdp, W / 2, y0, 80);
            const shown = await page.evaluate(() =>
                document.getElementById("bcm-navbar").classList.contains("bcm-navbar-shown"));
            if (!shown) fail(`${tag}: swipe up from y=${y0} did not reveal the navbar`);
        }
        await page.evaluate(() => App.hideNavBar());
        await cdp.detach();
    }

    // a tap on the kiosk = use: one activity message, throttled
    await page.evaluate(() => window.__openInput());
    await tapAt(page, touch, W / 2, H / 3);
    await tapAt(page, touch, W / 3, H / 3);
    await page.waitForTimeout(100);
    const pings = await page.evaluate(() => window.__activity());
    if (pings !== 1) fail(`${tag}: ${pings} activity pings for two taps`);

    // buttons post {} once (double tap swallowed)
    const center = (bt) => page.evaluate((a) => {
        const r = document.querySelector(`#wake-banner [data-wake-action='${a}']`).getBoundingClientRect();
        return [r.left + r.width / 2, r.top + r.height / 2];
    }, bt);
    let [x, y] = await center("hold");
    await tapAt(page, touch, x, y);
    await tapAt(page, touch, x, y);
    await page.waitForTimeout(200);
    if (JSON.stringify(posts) !== JSON.stringify([["/api/remote_session/hold", "{}"]])) {
        fail(`${tag}: hold posted ${JSON.stringify(posts)}`);
    }
    [x, y] = await center("sleep");
    await tapAt(page, touch, x, y);
    await page.waitForTimeout(200);
    if (posts.length !== 2 || posts[1][0] !== "/api/remote_session/sleep" || posts[1][1] !== "{}") {
        fail(`${tag}: sleep posted ${JSON.stringify(posts)}`);
    }

    // after the hold budget is used: the hold button goes, the label follows the step
    await push(page, { remote_session: Object.assign({}, SESSION, { hold_step_min: 15, holds_used_min: 45 }) });
    await page.waitForFunction(() => {
        const h = document.querySelector("#wake-banner [data-wake-action='hold']");
        return h && h.textContent === "Nie usypiaj 15 min";
    }, null, { timeout: 3000 });
    await push(page, { remote_session: Object.assign({}, SESSION, { can_hold: false, holds_used_min: 60 }) });
    await page.waitForFunction(() => {
        const h = document.querySelector("#wake-banner [data-wake-action='hold']");
        return h && getComputedStyle(h).display === "none";
    }, null, { timeout: 3000 });

    // Android Auto too; the crash window stays on top of it
    await page.evaluate(() => App.navigateTo("a2"));
    await page.waitForTimeout(150);
    await push(page, { remote_session: SESSION });
    b = await banner(page);
    if (b.count !== 1) fail(`${tag}: no banner on A2`);
    await navbarClear(page, tag + " A2");

    // idle would end it first: count down to idle, marked
    await push(page, { remote_session: Object.assign({}, SESSION, { lease_left_s: 1700, idle_left_s: 120 }) });
    await page.waitForFunction(() => {
        const l = document.querySelector("#wake-banner [data-wake-line]");
        return l && /uśpienie za 0[12]:[0-5][0-9] \(bez użycia\)$/.test(l.textContent);
    }, null, { timeout: 3000 });
    await push(page, { remote_session: SESSION, crash_sms: {
        state: "pending", event_id: EID, ts: 1763000000, countdown_s: 45, countdown_left_s: 45,
        deadline_ts: 1763000045, recipients_n: 1, phone_ok: true, dry_run: true,
        forced_dry_run_reason: "", results: [], cancel_sms: null, error: "", modal: true,
        cancel_pending: false, send_now_pending: false, can_follow_up: false,
        test: { request: "", error: "", state: null, ts: null, dry_run: null, verified: false,
                last_verified_ts: null } } });
    await page.waitForSelector("#crash-modal [data-crash-action='cancel']");
    const top = await page.evaluate(([x, y]) => {
        const el = document.elementFromPoint(x, y);
        return el && el.closest("#crash-modal") ? "crash" : (el && el.closest("#wake-banner") ? "banner" : "other");
    }, [W / 2, H - 30]);
    if (top !== "crash") fail(`${tag}: banner over the crash window (${top})`);
    await page.evaluate(() => { const m = document.getElementById("crash-modal"); if (m) m.remove(); });
    await push(page, { crash_sms: null, call112: null, remote_session: SESSION });

    // going to sleep: no buttons; then gone
    await push(page, { remote_session: Object.assign({}, SESSION, { sleep_pending: true }) });
    await page.waitForFunction(() => {
        const el = document.getElementById("wake-banner");
        return el && !el.querySelector("[data-wake-action]")
            && /usypianie…$/.test(el.querySelector("[data-wake-line]").textContent);
    }, null, { timeout: 3000 });
    for (const gone of [null, Object.assign({}, SESSION, { state: "idle" }), { state: "<img>" },
                        Object.assign({}, SESSION, { state: "ending", ended: "ignition" })]) {
        await push(page, { remote_session: SESSION });
        await page.waitForSelector("#wake-banner");
        await push(page, { remote_session: gone });
        await page.waitForFunction(() => !document.getElementById("wake-banner"), null, { timeout: 3000 });
    }

    // Settings → "Wybudzanie"
    await push(page, { remote_session: Object.assign({}, SESSION, { state: "idle", reason: "",
                                                                    ended: "lease_end" }) });
    await page.evaluate(() => App.navigateTo("settings"));
    await page.waitForSelector("[data-wake-state]");
    const rowText = await page.textContent("[data-wake-state]");
    if (!/Wybudzanie:\s*czeka/.test(rowText) || !/ostatnie: drzwi/.test(rowText)
        || !/odmowy Nano: 2 \(ostatnio: limit pobudek\)/.test(rowText)) {
        fail(`${tag}: row ${rowText}`);
    }
    const sw = await page.evaluate(() => document.documentElement.scrollWidth);
    if (sw > W) fail(`${tag}: settings wider than the screen (${sw})`);
    if (errors.length) fail(`${tag}: page errors: ${errors.join("; ")}`);
    await ctx.close();
}

async function runRemoteAndOff(browser) {
    // A passenger's phone in the car's network: the banner, but no buttons.
    let posts = [];
    let errors = [];
    let { ctx, page } = await open(browser, "http://192.168.4.1:5002", false, posts, errors);
    await push(page, { remote_session: SESSION });
    await page.waitForSelector("#wake-banner");
    const btns = await page.evaluate(() => document.querySelectorAll("#wake-banner [data-wake-action]").length);
    const text = await page.textContent("#wake-banner");
    if (btns !== 0 || !/Sterowanie tylko na ekranie w aucie/.test(text)) fail(`remote: ${btns} buttons, ${text}`);
    await page.evaluate(() => window.__openInput());
    await page.mouse.click(W / 2, H / 3);
    await page.waitForTimeout(100);
    if (await page.evaluate(() => window.__activity()) !== 0) fail("remote: sent an activity ping");
    if (errors.length) fail(`remote: page errors: ${errors.join("; ")}`);
    await ctx.close();

    // Module off (production): the key is null in every payload — nothing.
    posts = [];
    errors = [];
    ({ ctx, page } = await open(browser, "http://localhost:5002", false, posts, errors));
    for (const payload of [{ speed: 0, remote_session: null }, { reverse_gear: true, remote_session: null },
                           { reverse_gear: false, speed: 30, remote_session: null }]) {
        await push(page, payload);
        await page.waitForTimeout(80);
    }
    await page.evaluate(() => App.navigateTo("settings"));
    await page.waitForTimeout(300);
    const left = await page.evaluate(() => [!!document.getElementById("wake-banner"),
                                            !!document.querySelector("[data-wake-state]")]);
    if (left[0] || left[1]) fail(`module off: banner ${left[0]}, row ${left[1]}`);
    if (posts.length) fail(`module off: posted ${JSON.stringify(posts)}`);
    if (errors.length) fail(`module off: page errors: ${errors.join("; ")}`);
    await ctx.close();
}

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
        await runRemoteAndOff(browser);
    } finally {
        await browser.close();
    }
    process.stdout.write("ok\n");
})().catch((e) => {
    process.stderr.write(String(e && e.stack || e) + "\n");
    process.exit(1);
});
