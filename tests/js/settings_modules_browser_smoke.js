// Headless-Chromium check of Settings → Moduły (screens/settings.js) on the
// real dashboard at the car's 1024x600 panel, for
// tests/test_frontend_gestures.py. Needs the `playwright` package and its
// Chromium; without either it prints "SKIP: <reason>" and exits 0 so the
// pytest wrapper can skip instead of failing.
//
// Why: the Moduły card sits near the bottom of Settings (below SWC mapping).
// Module actions used to call App.navigateTo("settings"), which rebuilds
// .content-area and resets its scroll to 0 — the dependency question, the
// save status and the "disable bluetooth" warning were drawn below the
// screen while the tapped checkbox just flipped back. The node smoke test
// (settings_modules_smoke.js) stubs navigateTo, so only a real layout shows
// this.
//
// Usage: node settings_modules_browser_smoke.js <fixture.json>
// The fixture is written by the pytest wrapper from the REAL catalog
// (modules_catalog.catalog_state) — {"before": GET /api/modules with
// bluetooth off, "after": the POST reply once phone_status was enabled with
// its dependencies}. Nothing leaves the process: every request is answered
// here, and WebSocket is an inert stub.
//
// For mouse and touch it scrolls the card into view, taps phone_status
// (blocked: bluetooth off) and checks the question is on screen (inside the
// scroll area, not covered), the scroll position kept, the checkbox still
// unchecked and nothing saved; "Anuluj" saves nothing; "Włącz z
// zależnościami" sends one POST with with_deps and the status line is on
// screen; then unticking bluetooth (others need it) shows its question on
// screen.
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

const fixturePath = process.argv[2];
if (!fixturePath) {
    process.stderr.write("usage: node settings_modules_browser_smoke.js <fixture.json>\n");
    process.exit(2);
}
const FIXTURE = JSON.parse(fs.readFileSync(fixturePath, "utf8"));

const WEB = path.resolve(__dirname, "..", "..", "src", "dashboard", "web");
const ORIGIN = "http://bcm.invalid";
const MIME = {
    ".html": "text/html; charset=utf-8", ".js": "application/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8", ".json": "application/json", ".svg": "image/svg+xml",
    ".png": "image/png", ".jpg": "image/jpeg", ".ttf": "font/ttf", ".woff2": "font/woff2",
    ".woff": "font/woff", ".mp4": "video/mp4",
};

function fail(msg) { throw new Error(msg); }

function stubWebSocket() {
    window.WebSocket = class {
        constructor() { this.readyState = 0; }
        send() {}
        close() {}
        addEventListener() {}
        removeEventListener() {}
    };
}

async function run(browser, touch) {
    const tag = `1024x600${touch ? " touch" : ""}`;
    const posts = [];
    let modulesState = FIXTURE.before;
    const ctx = await browser.newContext({ viewport: { width: 1024, height: 600 }, hasTouch: touch });
    const page = await ctx.newPage();
    const errors = [];
    page.on("pageerror", (e) => errors.push(e.message));
    await ctx.route("**/*", async (route) => {
        const req = route.request();
        const url = new URL(req.url());
        if (url.origin !== ORIGIN) return route.abort();
        const p = url.pathname;
        const json = (obj) => route.fulfill({ status: 200, contentType: "application/json",
                                              body: JSON.stringify(obj) });
        if (p === "/api/modules") {
            if (req.method() === "POST") {
                posts.push(JSON.parse(req.postData() || "null"));
                modulesState = FIXTURE.after;
                return json(Object.assign({ ok: true, persisted: true }, FIXTURE.after));
            }
            return json(modulesState);
        }
        if (p.startsWith("/api/") || p.startsWith("/bt/")) {
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
        if (typeof Splash !== "undefined") Splash.hide();
        const s = document.getElementById("bcm-splash-overlay");
        if (s) s.remove();
    });
    await page.evaluate(() => App.navigateTo("settings"));
    await page.waitForSelector('[data-modules-card] input[data-module="phone_status"]');
    // Let the entry-time loads (radio, Wi-Fi, AA, modules) finish their
    // re-renders before scrolling — they would reset the scroll themselves.
    await page.waitForTimeout(800);

    const tap = async (sel) => {
        const el = await page.$(sel);
        if (!el) fail(`${tag}: no ${sel}`);
        const r = await el.boundingBox();
        if (!r) fail(`${tag}: ${sel} not laid out`);
        const x = r.x + r.width / 2;
        const y = r.y + r.height / 2;
        if (touch) await page.touchscreen.tap(x, y);
        else await page.mouse.click(x, y);
        await page.waitForTimeout(250);   // fetch stub + redraw + scroll
    };
    const scrollTop = () => page.evaluate(() => document.querySelector(".content-area").scrollTop);
    // On screen = inside the window AND the visible part of the scroll area
    // AND the element hit at its own centre (not under the app bar).
    const onScreen = (sel) => page.evaluate((sel) => {
        const el = document.querySelector(sel);
        if (!el) return { ok: false, why: "missing" };
        const r = el.getBoundingClientRect();
        const ca = document.querySelector(".content-area").getBoundingClientRect();
        const hit = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
        const inside = r.top >= Math.max(0, ca.top) - 0.5 && r.bottom <= Math.min(innerHeight, ca.bottom) + 0.5
            && r.height > 0;
        return { ok: inside && !!hit && el.contains(hit),
                 why: JSON.stringify({ top: r.top, bottom: r.bottom, ca: [ca.top, ca.bottom],
                                       innerHeight, hit: hit ? hit.outerHTML.slice(0, 80) : null }) };
    }, sel);
    const expectOnScreen = async (sel, what) => {
        const m = await onScreen(sel);
        if (!m.ok) fail(`${tag} ${what}: ${sel} not on screen ${m.why}`);
    };
    const checked = (name) => page.evaluate(
        (n) => document.querySelector(`input[data-module="${n}"]`).checked, name);

    // Scroll the card's phone_status row to the middle of the screen.
    await page.evaluate(() => document.querySelector('[data-module-row="phone_status"]')
        .scrollIntoView({ block: "center" }));
    await page.waitForTimeout(100);
    const before = await scrollTop();
    if (before < 100) fail(`${tag}: the card is not below the fold (scrollTop ${before}) — check is moot`);

    // 1. Blocked module: the question, on screen, nothing saved.
    await tap('input[data-module="phone_status"]');
    await expectOnScreen("[data-module-question]", "enable question");
    await expectOnScreen('[data-module-confirm="deps"]', "enable question");
    await expectOnScreen('[data-module-confirm="cancel"]', "enable question");
    const after = await scrollTop();
    if (after < 100) fail(`${tag}: scroll reset to ${after} (was ${before})`);
    if (await checked("phone_status")) fail(`${tag}: checkbox shows unsaved state`);
    if (posts.length) fail(`${tag}: saved before the driver answered: ${JSON.stringify(posts)}`);

    // 2. "Anuluj": question gone, still nothing saved, scroll kept.
    await tap('[data-module-confirm="cancel"]');
    if (await page.$("[data-module-question]")) fail(`${tag}: question still open after cancel`);
    if (posts.length) fail(`${tag}: cancel saved something`);
    if ((await scrollTop()) < 100) fail(`${tag}: cancel reset the scroll`);

    // 3. Again, "Włącz z zależnościami": one POST, status line on screen.
    await tap('input[data-module="phone_status"]');
    await tap('[data-module-confirm="deps"]');
    if (JSON.stringify(posts) !== JSON.stringify([{ name: "phone_status", enabled: true, with_deps: true }])) {
        fail(`${tag}: POST ${JSON.stringify(posts)}`);
    }
    await expectOnScreen("[data-modules-status]", "save status");
    const status = await page.evaluate(() => document.querySelector("[data-modules-status]").textContent);
    if (!status.includes("włączono też: bluetooth")) fail(`${tag}: status ${JSON.stringify(status)}`);
    if (!(await checked("phone_status")) || !(await checked("bluetooth"))) {
        fail(`${tag}: list not redrawn from the reply`);
    }
    if ((await scrollTop()) < 100) fail(`${tag}: save reset the scroll`);

    // 4. Unticking bluetooth (others need it): its question on screen.
    await page.evaluate(() => document.querySelector('[data-module-row="bluetooth"]')
        .scrollIntoView({ block: "center" }));
    await page.waitForTimeout(100);
    await tap('input[data-module="bluetooth"]');
    await expectOnScreen('[data-module-question="disable"]', "disable question");
    await expectOnScreen('[data-module-confirm="disable"]', "disable question");
    if (!(await checked("bluetooth"))) fail(`${tag}: bluetooth shown off before confirming`);
    if (posts.length !== 1) fail(`${tag}: disable saved without confirmation`);

    if (errors.length) fail(`${tag}: page errors: ${errors.join(" | ")}`);
    await ctx.close();
    return tag;
}

(async () => {
    let browser;
    try {
        browser = await chromium.launch();
    } catch (e) {
        process.stdout.write("SKIP: chromium unavailable: " + String(e.message).split("\n")[0] + "\n");
        process.exit(0);
    }
    try {
        for (const touch of [false, true]) process.stdout.write((await run(browser, touch)) + " ok\n");
    } finally {
        await browser.close();
    }
    process.stdout.write("ok\n");
})().catch((e) => {
    process.stderr.write(String(e && e.stack || e) + "\n");
    process.exit(1);
});
