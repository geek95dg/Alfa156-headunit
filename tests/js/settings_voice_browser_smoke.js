// Headless-Chromium check of the Settings row "Komunikaty głosowe"
// (screens/settings.js voiceRowHtml, data.voice_announce from
// web_viewer._voice_summary) on the real dashboard at the car's 1024x600
// panel, for tests/test_frontend_gestures.py. Needs the `playwright` package
// and its Chromium; without either it prints "SKIP: <reason>" and exits 0.
//
// Why: the row packs the status, Wł./Wył., the volume slider, three category
// switches and "Powiedz test" into one flex row at 11-12 px — the node smoke
// test (settings_voice_smoke.js) cannot see wrapping or overflow.
//
// Nothing leaves the process: every request is answered here and the data
// WebSocket is a stub. For mouse and touch, with the longest status (no
// speech engine) and a normal one:
//  - the row fits the 1024 px width, every element inside the row's box;
//  - "Powiedz test" is on screen and not covered; a tap posts once to
//    /api/voice/test with no body; a category tap posts one whitelisted
//    /api/config change.

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

const LONG = {
    enabled: false, volume: 100, categories: { weather: false, traffic: false, system: false },
    engine: "none", player: "none", queue: 0, speaking: false, call_active: false,
    last_result: "", last_spoken_ts: null, ducking: "off",
};
const NORMAL = {
    enabled: true, volume: 80, categories: { weather: true, traffic: true, system: true },
    engine: "piper", player: "pw-play", queue: 0, speaking: false, call_active: true,
    last_result: "interrupted", last_spoken_ts: 1.8e9, ducking: "eq",
};
const READY_LONG = Object.assign({}, NORMAL, { engine: "espeak", player: "none",
                                                last_result: "synth_failed", call_active: false });

async function open(browser, touch, posts, errors) {
    const ctx = await browser.newContext({ viewport: { width: W, height: H }, hasTouch: touch });
    const page = await ctx.newPage();
    page.on("pageerror", (e) => errors.push(e.message));
    await ctx.route("**/*", async (route) => {
        const req = route.request();
        const url = new URL(req.url());
        if (url.origin !== ORIGIN) return route.abort();
        const p = url.pathname;
        const json = (obj, status) => route.fulfill({ status: status || 200,
                                                      contentType: "application/json",
                                                      body: JSON.stringify(obj) });
        if (p === "/api/voice/test" && req.method() === "POST") {
            posts.push([p, req.postData() || ""]);
            return json({ ok: true, queued: true }, 202);
        }
        if (p === "/api/config" && req.method() === "POST") {
            posts.push([p, req.postData() || ""]);
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

async function measure(page) {
    await page.evaluate(() => document.querySelector("[data-voice-row]")
        .scrollIntoView({ block: "center" }));
    await page.waitForTimeout(150);
    return page.evaluate(() => {
        const row = document.querySelector("[data-voice-row]");
        const r = row.getBoundingClientRect();
        const btn = row.querySelector("[data-voice-test]");
        const b = btn.getBoundingClientRect();
        const hit = document.elementFromPoint(b.left + b.width / 2, b.top + b.height / 2);
        const outside = [...row.querySelectorAll("*")].filter((el) => {
            const e = el.getBoundingClientRect();
            return e.width > 0 && (e.left < r.left - 0.5 || e.right > r.right + 0.5);
        }).map((el) => el.outerHTML.slice(0, 80));
        return {
            l: r.left, r: r.right, sw: row.scrollWidth, cw: row.clientWidth,
            page: document.documentElement.scrollWidth, text: row.textContent,
            btn: { l: b.left, r: b.right, t: b.top, b: b.bottom, w: b.width, h: b.height },
            btnHit: !!hit && (hit === btn || btn.contains(hit)), outside,
        };
    });
}

async function tap(page, touch, selector) {
    const b = await page.evaluate((sel) => {
        const r = document.querySelector(sel).getBoundingClientRect();
        return { x: r.left + r.width / 2, y: r.top + r.height / 2 };
    }, selector);
    if (touch) await page.touchscreen.tap(b.x, b.y);
    else await page.mouse.click(b.x, b.y);
    await page.waitForTimeout(300);
}

async function run(browser, touch) {
    const tag = `${W}x${H}${touch ? " touch" : ""}`;
    const posts = [];
    const errors = [];
    const { ctx, page } = await open(browser, touch, posts, errors);
    await push(page, { voice_announce: LONG });
    await page.evaluate(() => App.navigateTo("settings"));
    await page.waitForSelector("[data-voice-row]");
    for (const [name, payload, expect] of [
        ["long", LONG, /brak syntezatora mowy — uruchom apply-fixes.sh/],
        ["ready-long", READY_LONG, /espeak-ng \(zapasowy\) · brak pw-play \/ paplay · synteza mowy nie powiodła się/],
        ["normal", NORMAL, /Piper \(głos polski\) · rozmowa — komunikaty czekają · przerwany \(rozmowa\)/],
    ]) {
        await push(page, { voice_announce: payload });
        await page.waitForFunction((re) => new RegExp(re).test(
            (document.querySelector("[data-voice-row]") || {}).textContent || ""),
        expect.source, { timeout: 3000 });
        const m = await measure(page);
        if (m.l < 0 || m.r > W || m.page > W) fail(`${tag} ${name}: row does not fit ${JSON.stringify(m)}`);
        if (m.sw > m.cw) fail(`${tag} ${name}: row overflows (${m.sw} > ${m.cw})`);
        if (m.outside.length) fail(`${tag} ${name}: outside the row: ${m.outside.join(" | ")}`);
        if (!(m.btn.w > 0 && m.btn.h > 0 && m.btn.l >= 0 && m.btn.r <= W && m.btn.t >= 0 && m.btn.b <= H)) {
            fail(`${tag} ${name}: test button off screen ${JSON.stringify(m.btn)}`);
        }
        if (!m.btnHit) fail(`${tag} ${name}: test button covered`);
    }
    await tap(page, touch, "[data-voice-test]");
    await tap(page, touch, '[data-voice-cat="traffic"]');
    const want = [["/api/voice/test", ""], ["/api/config", JSON.stringify({ voice_cat_traffic: false })]];
    if (JSON.stringify(posts) !== JSON.stringify(want)) fail(`${tag}: posted ${JSON.stringify(posts)}`);
    if (errors.length) fail(`${tag}: page errors: ${errors.join("; ")}`);
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
    } finally {
        await browser.close();
    }
    process.stdout.write("ok\n");
})().catch((e) => {
    process.stderr.write(String(e && e.stack || e) + "\n");
    process.exit(1);
});
