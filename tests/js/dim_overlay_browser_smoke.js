// Headless-Chromium check of the software dimming (modules.auto_brightness,
// components/dim_overlay.js + app.js _syncDim) and the Settings row "Jasność
// ekranu" on the real dashboard at the car's 1024x600 panel, for
// tests/test_frontend_gestures.py. Needs the `playwright` package and its
// Chromium; without either it prints "SKIP: <reason>" and exits 0.
//
// Nothing leaves the process: every request is answered here and the data
// WebSocket is a stub this script pushes payloads through (what
// web_viewer._display_dim_summary / _auto_brightness_summary send). Checked:
//  - ONE fixed overlay on <body>, z-index 190, black, pointer-events none,
//    covering the viewport, opacity = level with a 1 s transition, capped at
//    0.9, removed for level 0 / no payload / garbage;
//  - it is ON TOP of the screens (A1, Android Auto) — and BELOW the reverse
//    camera view (#reverse-overlay) and the crash window (#crash-modal),
//    which stay fully bright (paint order checked with elementFromPoint
//    while the overlay is made hit-testable for the check only);
//  - touches go through it (a real tap on a Settings button under it works);
//  - module off (no display_dim in any payload): no overlay at all;
//  - the Settings row: Auto / Ręczna, the slider and "Programowe /
//    Sprzętowe (DDC/CI)" post exactly the whitelisted bodies to /api/config;
//    the probe's failure reason is shown; the row fits the 1024 px width.
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
const ORIGIN = "http://localhost:5002";
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
}

const STATE = {
    mode: "auto", effective: "auto", source: "phone", lux: 3.2, adc: null, pct: 30,
    target_pct: 30, manual_pct: 70, hold_left_min: null, min_pct: 15, max_pct: 100,
    backend: "css", active: "css", probe: "idle", reason: "",
};

async function open(browser, touch, posts, errors) {
    const ctx = await browser.newContext({ viewport: { width: W, height: H }, hasTouch: touch });
    const page = await ctx.newPage();
    page.on("pageerror", (e) => errors.push(e.message));
    await ctx.route("**/*", async (route) => {
        const req = route.request();
        const url = new URL(req.url());
        if (url.origin !== ORIGIN) return route.abort();
        const p = url.pathname;
        const json = (obj) => route.fulfill({ status: 200, contentType: "application/json",
                                              body: JSON.stringify(obj) });
        if (p === "/api/config" && req.method() === "POST") {
            posts.push(JSON.parse(req.postData() || "null"));
            return json({ ok: true, persisted: true });
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
    await page.goto(ORIGIN + "/");
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

async function overlay(page) {
    return page.evaluate(() => {
        const all = document.querySelectorAll("#bcm-dim-overlay");
        const el = all[0];
        if (!el) return { count: 0 };
        const st = getComputedStyle(el);
        const b = el.getBoundingClientRect();
        return {
            count: all.length, parentIsBody: el.parentNode === document.body,
            position: st.position, z: st.zIndex, pe: st.pointerEvents, bg: st.backgroundColor,
            transition: st.transitionProperty + " " + st.transitionDuration,
            target: el.style.opacity, x: b.left, y: b.top, w: b.width, h: b.height,
        };
    });
}

/** Which layer paints on top at (x, y): the overlay is made hit-testable
 *  for this one query only (it is pointer-events:none for real). */
async function topAt(page, x, y) {
    return page.evaluate(([x, y]) => {
        const ov = document.getElementById("bcm-dim-overlay");
        if (ov) ov.style.pointerEvents = "auto";
        const el = document.elementFromPoint(x, y);
        if (ov) ov.style.pointerEvents = "none";
        if (!el) return null;
        if (el.id === "bcm-dim-overlay") return "overlay";
        if (el.closest("#crash-modal")) return "crash";
        if (el.closest("#reverse-overlay")) return "reverse";
        return "content";
    }, [x, y]);
}

async function waitOverlay(page, target) {
    await page.waitForFunction((t) => {
        const el = document.getElementById("bcm-dim-overlay");
        return t === null ? !el : !!el && el.style.opacity === t;
    }, target, { timeout: 3000 });
}

async function run(browser, touch) {
    const tag = `${W}x${H}${touch ? " touch" : ""}`;
    const posts = [];
    const errors = [];
    const { ctx, page } = await open(browser, touch, posts, errors);

    // ── the overlay on A1 ─────────────────────────────────────────────────
    await push(page, { display_dim: { level: 0.6, brightness_pct: 30 } });
    await waitOverlay(page, "0.6");
    let o = await overlay(page);
    if (o.count !== 1 || !o.parentIsBody) fail(`${tag}: overlay ${JSON.stringify(o)}`);
    if (o.position !== "fixed" || o.z !== "190" || o.pe !== "none") fail(`${tag}: overlay style ${JSON.stringify(o)}`);
    if (o.bg !== "rgb(0, 0, 0)") fail(`${tag}: background ${o.bg}`);
    if (!/opacity 1s/.test(o.transition)) fail(`${tag}: transition ${o.transition}`);
    if (Math.round(o.x) !== 0 || Math.round(o.y) !== 0 || Math.round(o.w) !== W || Math.round(o.h) !== H) {
        fail(`${tag}: overlay does not cover the screen ${JSON.stringify(o)}`);
    }
    if (await topAt(page, W / 2, H / 2) !== "overlay") fail(`${tag}: A1 not under the overlay`);
    // pointer-events:none for real: the content gets the touch
    const under = await page.evaluate(([x, y]) => {
        const el = document.elementFromPoint(x, y);
        return el ? el.id || el.tagName : null;
    }, [W / 2, H / 2]);
    if (under === "bcm-dim-overlay") fail(`${tag}: overlay takes touches`);

    // same element, new value; cap; removal
    await push(page, { display_dim: { level: 0.3, brightness_pct: 65 } });
    await waitOverlay(page, "0.3");
    if ((await overlay(page)).count !== 1) fail(`${tag}: overlay duplicated`);
    await push(page, { display_dim: { level: 5, brightness_pct: 0 } });
    await waitOverlay(page, "0.9");
    for (const bad of [{ level: 0, brightness_pct: 100 }, null, { level: "0.5" }, { level: -1 }]) {
        await push(page, { display_dim: { level: 0.5, brightness_pct: 41 } });
        await waitOverlay(page, "0.5");
        await push(page, { display_dim: bad });
        await waitOverlay(page, null);
    }
    await push(page, { display_dim: { level: 0.5, brightness_pct: 41 } });
    await waitOverlay(page, "0.5");
    // module gone: the backend sends display_dim null (the keys are always in
    // the payload — DataStore merges, so the harness must send it too)
    await push(page, { display_dim: null });
    await waitOverlay(page, null);

    // ── Android Auto is dimmed too ────────────────────────────────────────
    await page.evaluate(() => App.navigateTo("a2"));
    await page.waitForTimeout(150);
    await push(page, { display_dim: { level: 0.6, brightness_pct: 30 } });
    await waitOverlay(page, "0.6");
    if (await topAt(page, W / 2, H / 2) !== "overlay") fail(`${tag}: A2 not under the overlay`);

    // ── the reverse camera stays fully bright ─────────────────────────────
    await page.evaluate(() => App.navigateTo("a1"));
    await page.waitForTimeout(150);
    await push(page, { display_dim: { level: 0.6, brightness_pct: 30 }, reverse_gear: true });
    await page.waitForSelector("#reverse-overlay");
    for (const [x, y] of [[W / 2, H / 2], [20, 20], [W - 20, H - 20]]) {
        const top = await topAt(page, x, y);
        if (top !== "reverse") fail(`${tag}: reverse view under the overlay at ${x},${y} (${top})`);
    }
    const zs = await page.evaluate(() => [
        getComputedStyle(document.getElementById("reverse-overlay")).zIndex,
        getComputedStyle(document.getElementById("bcm-dim-overlay")).zIndex]);
    if (!(Number(zs[0]) > Number(zs[1]))) fail(`${tag}: z-index reverse ${zs[0]} vs overlay ${zs[1]}`);
    await push(page, { display_dim: { level: 0.6, brightness_pct: 30 }, reverse_gear: false });
    await page.waitForFunction(() => !document.getElementById("reverse-overlay"));

    // ── the crash window (and the 112 view in it) stays fully bright ─────
    await push(page, { display_dim: { level: 0.6, brightness_pct: 30 }, crash_sms: {
        state: "pending", event_id: EID, ts: 1763000000, countdown_s: 45, countdown_left_s: 45,
        deadline_ts: 1763000045, recipients_n: 1, phone_ok: true, dry_run: true,
        forced_dry_run_reason: "", results: [], cancel_sms: null, error: "", modal: true,
        cancel_pending: false, send_now_pending: false, can_follow_up: false,
        test: { request: "", error: "", state: null, ts: null, dry_run: null, verified: false,
                last_verified_ts: null } } });
    await page.waitForSelector("#crash-modal [data-crash-action='cancel']");
    for (const [x, y] of [[W / 2, H / 2], [30, 30], [W - 30, H - 30]]) {
        const top = await topAt(page, x, y);
        if (top !== "crash") fail(`${tag}: crash window under the overlay at ${x},${y} (${top})`);
    }
    const zc = await page.evaluate(() => Number(getComputedStyle(document.getElementById("crash-modal")).zIndex));
    if (!(zc > 190)) fail(`${tag}: crash window z-index ${zc}`);
    await page.evaluate(() => { const m = document.getElementById("crash-modal"); if (m) m.remove(); });

    // ── Settings → "Jasność ekranu" (with the overlay on: taps go through) ─
    await push(page, { display_dim: { level: 0.6, brightness_pct: 30 }, auto_brightness: STATE });
    await page.evaluate(() => App.navigateTo("settings"));
    await page.waitForSelector("[data-bright-row]");
    await page.evaluate(() => document.querySelector("[data-bright-row]").scrollIntoView({ block: "center" }));
    await page.waitForTimeout(150);
    const rowBox = await page.evaluate(() => {
        const r = document.querySelector("[data-bright-row]").getBoundingClientRect();
        return { l: r.left, r: r.right, t: r.top, b: r.bottom, sw: document.documentElement.scrollWidth };
    });
    if (rowBox.l < 0 || rowBox.r > W || rowBox.sw > W) fail(`${tag}: row does not fit ${JSON.stringify(rowBox)}`);
    const status = await page.textContent("[data-bright-status]");
    if (status !== "Auto (telefon) · 3.2 lx · 30%") fail(`${tag}: status ${status}`);
    const tapOn = async (sel) => {
        const b = await page.evaluate((s) => {
            const r = document.querySelector(s).getBoundingClientRect();
            return { x: r.left + r.width / 2, y: r.top + r.height / 2 };
        }, sel);
        if (touch) await page.touchscreen.tap(b.x, b.y);
        else await page.mouse.click(b.x, b.y);
    };
    await tapOn("[data-bright-backend='ddc']");
    await page.waitForTimeout(150);
    if (JSON.stringify(posts) !== JSON.stringify([{ brightness_backend: "ddc" }])) {
        fail(`${tag}: backend tap posted ${JSON.stringify(posts)}`);
    }
    await page.waitForTimeout(600);                      // past the double-tap guard
    await tapOn("[data-bright-mode='manual']");
    await page.waitForTimeout(150);
    if (JSON.stringify(posts[1]) !== JSON.stringify({ brightness_mode: "manual" })) {
        fail(`${tag}: mode tap posted ${JSON.stringify(posts)}`);
    }
    // the slider: a value change posts it (the browser's own change event)
    await page.$eval("[data-bright-slider]", (el) => {
        el.value = "42";
        el.dispatchEvent(new Event("input", { bubbles: true }));
        el.dispatchEvent(new Event("change", { bubbles: true }));
    });
    await page.waitForTimeout(150);
    if (JSON.stringify(posts[2]) !== JSON.stringify({ brightness: 42 })) fail(`${tag}: slider posted ${JSON.stringify(posts)}`);
    if (posts.length !== 3) fail(`${tag}: extra posts ${JSON.stringify(posts)}`);
    // the probe's verdict appears in the row (applied live — no reload)
    await page.waitForTimeout(1600);                     // the slider is not "dragged" any more
    await push(page, { display_dim: { level: 0.6, brightness_pct: 30 },
                       auto_brightness: Object.assign({}, STATE, { backend: "ddc", probe: "failed",
                                                                   reason: "no_display" }) });
    await page.waitForFunction(() => /Sprzętowe niedostępne: monitor nie odpowiada przez DDC\/CI — używam programowego/
        .test((document.querySelector("[data-bright-backend-msg]") || {}).textContent || ""), null, { timeout: 3000 });
    await push(page, { display_dim: { level: 0, brightness_pct: 30 },
                       auto_brightness: Object.assign({}, STATE, { backend: "ddc", active: "ddc", probe: "ok" }) });
    await waitOverlay(page, null);                       // DDC: no overlay
    await page.waitForFunction(() => /DDC\/CI działa/.test(
        (document.querySelector("[data-bright-backend-msg]") || {}).textContent || ""), null, { timeout: 3000 });
    // module stopped: row and overlay gone
    await push(page, { display_dim: null, auto_brightness: null });
    await page.waitForFunction(() => !document.querySelector("[data-bright-row]"), null, { timeout: 3000 });
    if (errors.length) fail(`${tag}: page errors: ${errors.join("; ")}`);
    await ctx.close();
}

async function runModuleOff(browser) {
    const posts = [];
    const errors = [];
    const { ctx, page } = await open(browser, false, posts, errors);
    // what web_viewer sends with the module off: both keys null in every payload
    for (const payload of [{ speed: 0, display_dim: null, auto_brightness: null },
                           { reverse_gear: true, display_dim: null },
                           { reverse_gear: false, speed: 30, display_dim: null }]) {
        await push(page, payload);
        await page.waitForTimeout(80);
    }
    await page.evaluate(() => App.navigateTo("settings"));
    await page.waitForTimeout(300);
    const left = await page.evaluate(() => [!!document.getElementById("bcm-dim-overlay"),
                                            !!document.querySelector("[data-bright-row]")]);
    if (left[0] || left[1]) fail(`module off: overlay ${left[0]}, row ${left[1]}`);
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
        await runModuleOff(browser);
    } finally {
        await browser.close();
    }
    process.stdout.write("ok\n");
})().catch((e) => {
    process.stderr.write(String(e && e.stack || e) + "\n");
    process.exit(1);
});
