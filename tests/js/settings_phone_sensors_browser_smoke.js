// Headless-Chromium check of the Settings row "Czujniki telefonu"
// (screens/settings.js sensorsRowHtml, data.phone_sensors from
// web_viewer._phone_sensors_summary) on the real dashboard at the car's
// 1024x600 panel, for tests/test_frontend_gestures.py. Needs the
// `playwright` package and its Chromium; without either it prints
// "SKIP: <reason>" and exits 0.
//
// Why: the row packs the state, three facts, the "Test" button and up to
// four full-width lines (forward hint, refused light, split mode, verdict
// with what to do) into one flex row at 11 px — the node smoke test
// (settings_phone_sensors_smoke.js) cannot see wrapping or overflow.
//
// Nothing leaves the process: every request is answered here and the data
// WebSocket is a stub this script pushes payloads through. For mouse and
// touch, with the longest payload (split mode, forward down, light refused,
// "no_light" verdict with its hint, an error line) and a steady-light "ok":
//  - the row fits the 1024 px width (no horizontal overflow in the row or
//    the page), every line inside the row's box;
//  - "Test" is on screen, not covered, and a tap posts once to
//    /api/phone_sensors/test.
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

// The longest row web_viewer can send (every optional line present).
const WORST = {
    state: "error", mode: "split", rate_hz: 0, calib_ok: false,
    error: "no accelerometer data from SensorServer for 10 s (app stopped? sensors allowed?)",
    types: { accel: { subscribed: true, active: false, hz: 0, refused: false },
             gyro: { subscribed: false, active: false, hz: 0, refused: true },
             light: { subscribed: false, active: false, hz: 0, refused: true } },
    lux: 12345.6, lux_age_s: 7200,
    close: { code: 4002, reason: "Sensor of type android.sensor.light is not available", channel: "light" },
    test: { running: false, result: {
        ts: 1.7e9, verdict: "no_light", hint: "light", duration_s: 10,
        frames: { accel: 10000, gyro: 0, light: 0 }, hz: { accel: 100, gyro: 0, light: 0 },
        lux_min: null, lux_max: null, light_steady: false, lux: null, lux_age_s: null } },
    forward: { ok: false, error: "adb: error: device offline" },
};
const STEADY = {
    state: "streaming", mode: "combined", rate_hz: 99.6, calib_ok: true, error: "",
    types: { accel: { subscribed: true, active: true, hz: 99.6, refused: false },
             gyro: { subscribed: true, active: true, hz: 98.2, refused: false },
             light: { subscribed: true, active: true, hz: 0, refused: false } },
    lux: 321, lux_age_s: 42,
    close: { code: null, reason: "", channel: "" },
    test: { running: false, result: {
        ts: 1.7e9, verdict: "ok", hint: "", duration_s: 10,
        frames: { accel: 1000, gyro: 990, light: 0 }, hz: { accel: 100, gyro: 99, light: 0 },
        lux_min: null, lux_max: null, light_steady: true, lux: 321, lux_age_s: 38 } },
    forward: { ok: true, error: "" },
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
        const json = (obj, status) => route.fulfill({ status: status || 200,
                                                      contentType: "application/json",
                                                      body: JSON.stringify(obj) });
        if (p === "/api/phone_sensors/test" && req.method() === "POST") {
            posts.push(p);
            return json({ ok: true, started: true, duration_s: 10 }, 202);
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

/** The row's geometry after scrolling it into view. */
async function measure(page) {
    await page.evaluate(() => document.querySelector("[data-phone-sensors]")
        .scrollIntoView({ block: "center" }));
    await page.waitForTimeout(150);
    return page.evaluate(() => {
        const row = document.querySelector("[data-phone-sensors]");
        const r = row.getBoundingClientRect();
        const btn = row.querySelector("[data-sensors-test]");
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

async function run(browser, touch) {
    const tag = `${W}x${H}${touch ? " touch" : ""}`;
    const posts = [];
    const errors = [];
    const { ctx, page } = await open(browser, touch, posts, errors);
    await push(page, { phone_sensors: WORST });
    await page.evaluate(() => App.navigateTo("settings"));
    await page.waitForSelector("[data-phone-sensors]");
    for (const [name, payload, expect] of [
        ["worst", WORST, [/osobne połączenie dla każdego czujnika/, /telefon odrzuca czujnik światła/,
                          /forward „sensors” nie działa/, /test: brak odczytów światła/,
                          /zaznacz czujnik światła/]],
        ["steady", STEADY, [/test: wszystko działa/, /światło stałe — ostatni odczyt 321 lx, 38 s temu/]],
    ]) {
        await push(page, { phone_sensors: payload });
        await page.waitForFunction((re) => new RegExp(re).test(
            (document.querySelector("[data-phone-sensors]") || {}).textContent || ""),
        expect[0].source, { timeout: 3000 });
        const m = await measure(page);
        for (const re of expect) if (!re.test(m.text)) fail(`${tag} ${name}: missing ${re} in ${m.text}`);
        if (m.l < 0 || m.r > W || m.page > W) fail(`${tag} ${name}: row does not fit ${JSON.stringify(m)}`);
        if (m.sw > m.cw) fail(`${tag} ${name}: row overflows (${m.sw} > ${m.cw})`);
        if (m.outside.length) fail(`${tag} ${name}: outside the row: ${m.outside.join(" | ")}`);
        if (!(m.btn.w > 0 && m.btn.h > 0 && m.btn.l >= 0 && m.btn.r <= W && m.btn.t >= 0 && m.btn.b <= H)) {
            fail(`${tag} ${name}: Test button off screen ${JSON.stringify(m.btn)}`);
        }
        if (!m.btnHit) fail(`${tag} ${name}: Test button covered`);
    }
    // A tap on "Test": one POST.
    const b = await page.evaluate(() => {
        const r = document.querySelector("[data-sensors-test]").getBoundingClientRect();
        return { x: r.left + r.width / 2, y: r.top + r.height / 2 };
    });
    if (touch) await page.touchscreen.tap(b.x, b.y);
    else await page.mouse.click(b.x, b.y);
    await page.waitForTimeout(300);
    if (JSON.stringify(posts) !== JSON.stringify(["/api/phone_sensors/test"])) {
        fail(`${tag}: Test posted ${JSON.stringify(posts)}`);
    }
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
