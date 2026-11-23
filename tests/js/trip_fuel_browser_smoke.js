// Headless-Chromium check of the "Zatankowano" form on the A3 trip screen
// (screens/trip.js, data.fuel_log) at the car's 1024x600 panel, for
// tests/test_frontend_gestures.py. Needs the `playwright` package and its
// Chromium; without either it prints "SKIP: <reason>" and exits 0.
//
// Why: the form is used right after refuelling, with a finger, while the
// on-screen keyboard (58 % of the height) covers the lower half. Checked,
// for mouse and touch, in every theme:
//  - the panel's "Zatankowano" button is on screen and not covered;
//  - the form's fields are at least 48 px tall, inside 1024 px;
//  - each field, once focused, is lifted above the keyboard (bottom at
//    least 8 px above the keyboard's top) — litres AND odometer;
//  - typing "45,5" on the keyboard (the "," key) reaches the field;
//  - "Do pełna" starts on and toggles;
//  - "Zapisz" posts once with what was typed; a 400 odometer_backwards
//    shows the message and the second "Zapisz" confirms it; a 201 closes
//    the form.
// Nothing leaves the process: every request is answered here.
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

const FUEL = {
    enabled: true, running: true, status: "ok", count: 6,
    avg_l100_last: 7.04, avg_l100_overall: 6.81, cost_per_100km: 43.2,
    km_since_full: 210.4, est_range_km: 512, read_only: false,
    recent: [1, 2, 3, 4, 5].map((i) => ({
        id: 10 - i, ts: 1.8e9 - i * 86400 * 7, litres: 40 + i, price_per_l: 6.29, odometer_km: 150000 - i * 600,
        full: i !== 2,
        interval: i === 2 ? null : { km: 600, l100: 6.8, cost: 256.6, litres: 40.8, source: "gps", usable: true },
    })),
};

async function open(browser, touch, posts, errors, replies) {
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
        if (p === "/api/fuel/refuel" && req.method() === "POST") {
            posts.push(JSON.parse(req.postData() || "{}"));
            const r = replies.shift() || [201, { ok: true, refuel: { id: 11 }, warnings: [] }];
            return json(r[1], r[0]);
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

async function tap(page, touch, sel) {
    const b = await page.evaluate((s) => {
        const el = typeof s === "string" ? document.querySelector(s) : null;
        if (!el) return null;
        const r = el.getBoundingClientRect();
        const x = r.left + r.width / 2;
        const y = r.top + r.height / 2;
        const hit = document.elementFromPoint(x, y);
        return { x, y, l: r.left, r: r.right, t: r.top, b: r.bottom, w: r.width, h: r.height,
                 hit: !!hit && (hit === el || el.contains(hit)) };
    }, sel);
    if (!b) fail(`no element ${sel}`);
    if (!(b.l >= 0 && b.r <= W && b.t >= 0 && b.b <= H)) fail(`${sel} off screen ${JSON.stringify(b)}`);
    if (!b.hit) fail(`${sel} covered`);
    if (touch) await page.touchscreen.tap(b.x, b.y);
    else await page.mouse.click(b.x, b.y);
    await page.waitForTimeout(120);
    return b;
}

/** Tap one key of the on-screen keyboard by its label. */
async function key(page, touch, label) {
    const id = await page.evaluate((lab) => {
        const btn = [...document.querySelectorAll("#osk-overlay button")]
            .find((b) => b.textContent.trim() === lab);
        if (!btn) return null;
        btn.setAttribute("data-test-key", lab === "," ? "comma" : lab);
        return btn.getAttribute("data-test-key");
    }, label);
    if (!id) fail(`no OSK key ${label}`);
    await tap(page, touch, `[data-test-key="${id}"]`);
}

/** The focused field vs the keyboard. */
async function fieldAboveKeyboard(page, name) {
    await page.waitForTimeout(250);   // rAF fit + scroll
    return page.evaluate((n) => {
        const f = document.querySelector(`[data-fuel-field="${n}"]`).getBoundingClientRect();
        const k = document.getElementById("osk-overlay");
        return { fieldTop: f.top, fieldBottom: f.bottom, h: f.height, w: f.width, l: f.left, r: f.right,
                 kbTop: k ? k.getBoundingClientRect().top : null,
                 focused: document.activeElement && document.activeElement.dataset.fuelField };
    }, name);
}

async function run(browser, touch, theme) {
    const tag = `${W}x${H} ${theme}${touch ? " touch" : ""}`;
    const posts = [];
    const errors = [];
    const replies = [[400, { ok: false, error: "odometer_backwards" }]];
    const { ctx, page } = await open(browser, touch, posts, errors, replies);
    await page.evaluate((t) => App.setTheme(t), theme);
    await page.evaluate(() => App.navigateTo("a3"));
    const active = await page.evaluate(() => App.getTheme());
    if (active !== theme) fail(`${tag}: theme is ${active}`);
    await page.evaluate((f) => window.__push({ fuel_log: f, avg_consumption: 6.8,
                                               estimated_range: 512 }), FUEL);
    await page.waitForSelector('[data-fuel-action="refuel"]');
    await page.waitForFunction(() => document.querySelectorAll("[data-fuel-row]").length === 5);
    await tap(page, touch, '[data-fuel-action="refuel"]');
    await page.waitForSelector("#fuel-modal");

    // Fields: touch-sized, inside the width.
    for (const name of ["litres", "price_per_l", "odometer_km"]) {
        const m = await page.evaluate((n) => {
            const r = document.querySelector(`[data-fuel-field="${n}"]`).getBoundingClientRect();
            return { h: r.height, l: r.left, r: r.right };
        }, name);
        if (m.h < 48 || m.l < 0 || m.r > W) fail(`${tag}: field ${name} ${JSON.stringify(m)}`);
    }
    // Litres is focused on open → keyboard; type 45,5 on it.
    await tap(page, touch, '[data-fuel-field="litres"]');
    await page.waitForSelector("#osk-overlay");
    let m = await fieldAboveKeyboard(page, "litres");
    if (m.kbTop === null || m.fieldBottom > m.kbTop - 8 || m.fieldTop < 0) {
        fail(`${tag}: litres under the keyboard ${JSON.stringify(m)}`);
    }
    for (const k of ["4", "5", ",", "5"]) await key(page, touch, k);
    const typed = await page.evaluate(() => document.querySelector('[data-fuel-field="litres"]').value);
    if (typed !== "45,5") fail(`${tag}: typed ${JSON.stringify(typed)}`);
    // The odometer, the lowest field, also comes up above the keys.
    await tap(page, touch, '[data-fuel-field="odometer_km"]');
    m = await fieldAboveKeyboard(page, "odometer_km");
    if (m.focused !== "odometer_km" || m.kbTop === null || m.fieldBottom > m.kbTop - 8 || m.fieldTop < 0) {
        fail(`${tag}: odometer under the keyboard ${JSON.stringify(m)}`);
    }
    for (const k of ["1", "2", "3"]) await key(page, touch, k);
    // Close the keyboard (its own hide key), then the switch and Save.
    await page.evaluate(() => OnScreenKeyboard.close());
    await page.waitForTimeout(150);
    const before = await page.evaluate(() => document.querySelector("[data-fuel-full]").getAttribute("aria-checked"));
    if (before !== "true") fail(`${tag}: "Do pełna" not on by default`);
    await tap(page, touch, "[data-fuel-full]");
    await tap(page, touch, "[data-fuel-save]");
    await page.waitForFunction(() => /Licznik mniejszy/.test(
        (document.querySelector("[data-fuel-form-msg]") || {}).textContent || ""), null, { timeout: 3000 });
    await tap(page, touch, "[data-fuel-save]");
    await page.waitForFunction(() => !document.getElementById("fuel-modal"), null, { timeout: 3000 });
    if (posts.length !== 2) fail(`${tag}: posted ${JSON.stringify(posts)}`);
    const want = { litres: "45,5", price_per_l: null, odometer_km: "123", full: false };
    for (const [k, v] of Object.entries(want)) {
        if (posts[0][k] !== v) fail(`${tag}: first POST ${k}=${JSON.stringify(posts[0][k])}`);
    }
    if (posts[0].confirm_odometer || posts[1].confirm_odometer !== true) {
        fail(`${tag}: confirm_odometer ${JSON.stringify(posts)}`);
    }
    await page.waitForFunction(() => /Zapisano tankowanie/.test(
        (document.querySelector("[data-fuel-msg]") || {}).textContent || ""), null, { timeout: 3000 });
    if (await page.evaluate(() => !!document.getElementById("osk-overlay"))) fail(`${tag}: keyboard left open`);
    const page_w = await page.evaluate(() => document.documentElement.scrollWidth);
    if (page_w > W) fail(`${tag}: page scrolls sideways (${page_w})`);
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
        for (const theme of ["heritage", "modern", "autodelta"]) {
            await run(browser, false, theme);
        }
        await run(browser, true, "autodelta");
    } finally {
        await browser.close();
    }
    process.stdout.write("ok\n");
})().catch((e) => {
    process.stderr.write(String(e && e.stack || e) + "\n");
    process.exit(1);
});
