// Headless-Chromium check of the weather warnings (modules.weather_alerts)
// at the car's 1024x600 panel, for tests/test_frontend_gestures.py. Needs the
// `playwright` package and its Chromium; without either it prints
// "SKIP: <reason>" and exits 0.
//
// Checked in every theme: on A4 the alert strip is on screen, inside the map,
// not covering the search field or the bottom weather bar, and shows the
// escaped text; the forecast rows are the real ones; in the top bar the
// warning icon is visible, does not overlap the logo or the temperature, and
// opens A4 when tapped (from A1); without alerts both disappear in place.
// BCM_SHOT_DIR=<dir> also saves screenshots (manual review only).
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


const ALERTS = [
    { kind: "icing", severity: "danger", title: "Gołoledź", where: "teraz",
      text: "Marznący opad, minus 1 stopień, teraz. Jedź bardzo ostrożnie. <b>x</b>", valid_until: 2e9 },
    { kind: "wind", severity: "warning", title: "Silny wiatr", where: "za ~3 h",
      text: "Porywy wiatru do 60 kilometrów na godzinę.", valid_until: 2e9 },
];
const FORECAST = [
    { day: "Today", high: 3, low: -1, condition: "Snow", icon: "13d" },
    { day: "Wed", high: 7, low: 1, condition: "Rain", icon: "10n" },
    { day: "Thu", high: 12, low: 4, condition: "Clear", icon: "01d" },
];
const BASE = { weather_temp: 1, weather_condition: "Light Snow", weather_city: "Kraków, PL",
               weather_status: { source: "live" }, weather_forecast: FORECAST, ext_temp: 1 };

function box(page, sel) {
    return page.evaluate((s) => {
        const el = document.querySelector(s);
        if (!el) return null;
        const r = el.getBoundingClientRect();
        const cs = getComputedStyle(el);
        return { l: r.left, r: r.right, t: r.top, b: r.bottom, w: r.width, h: r.height,
                 visible: cs.display !== "none" && r.width > 0 && r.height > 0 };
    }, sel);
}

function overlap(a, b) {
    return a && b && a.l < b.r && b.l < a.r && a.t < b.b && b.t < a.b;
}

async function run(browser, theme) {
    const tag = `${W}x${H} ${theme}`;
    const errors = [];
    const { ctx, page } = await open(browser, false, [], errors, []);
    await page.evaluate((t) => App.setTheme(t), theme);
    // Top bar on A1 first: icon visible, tap → A4.
    await page.evaluate((d) => window.__push(d), { ...BASE, weather_alerts: ALERTS });
    await page.waitForFunction(() => {
        const el = document.querySelector('[data-bind="weather_alert"]');
        return el && getComputedStyle(el).display !== "none";
    }, null, { timeout: 3000 });
    const icon = await box(page, '[data-bind="weather_alert"]');
    const logo = await box(page, ".appbar-logo");
    const temp = await box(page, '[data-bind="ext_temp"]');
    if (!icon.visible || icon.l < 0 || icon.r > W || icon.t < 0) fail(`${tag}: icon ${JSON.stringify(icon)}`);
    if (overlap(icon, logo) || overlap(icon, temp)) fail(`${tag}: icon overlaps ${JSON.stringify({ icon, logo, temp })}`);
    const glyph = await page.evaluate(() => document.querySelector('[data-bind="weather_alert"]').textContent);
    if (glyph !== "ac_unit") fail(`${tag}: icon glyph ${glyph}`);
    await page.mouse.click(icon.l + icon.w / 2, icon.t + icon.h / 2);
    await page.waitForFunction(() => App.getCurrentScreen() === "a4", null, { timeout: 3000 });
    await page.evaluate((d) => window.__push(d), { ...BASE, weather_alerts: ALERTS });
    await page.waitForSelector("#weather-alerts");
    await page.waitForTimeout(300);
    const strip = await box(page, "#weather-alerts");
    const map = await box(page, "#weather-map");
    const search = await box(page, "#weather-search-input");
    if (!strip || !strip.visible) fail(`${tag}: no strip`);
    if (strip.l < map.l - 1 || strip.r > map.r + 1 || strip.t < map.t - 1 || strip.b > map.b + 1) {
        fail(`${tag}: strip outside the map ${JSON.stringify({ strip, map })}`);
    }
    if (overlap(strip, search)) fail(`${tag}: strip covers the search field`);
    if (strip.h > 90) fail(`${tag}: strip too tall (${strip.h})`);
    const text = await page.evaluate(() => document.getElementById("weather-alerts").textContent);
    if (!/Gołoledź · teraz/.test(text) || !/\+1 więcej/.test(text) || !/<b>x<\/b>/.test(text)) {
        fail(`${tag}: strip text ${JSON.stringify(text)}`);
    }
    const html = await page.evaluate(() => document.querySelector(".screen-container").innerHTML);
    // Translations come from /api (stubbed empty here): day keys fall back
    // to their upper-case name.
    for (const want of [/DZIŚ/, /ŚR|WED/, /CZW|THU/, />3°[ <]/, />12°[ <]/]) {
        if (!want.test(html)) fail(`${tag}: forecast ${want} missing`);
    }
    if (process.env.BCM_SHOT_DIR) {
        await page.screenshot({ path: path.join(process.env.BCM_SHOT_DIR, `weather_alerts_${theme}.png`) });
    }
    // Cleared: both disappear without a re-render.
    await page.evaluate((d) => window.__push(d), { ...BASE, weather_alerts: [] });
    await page.waitForFunction(() => getComputedStyle(document.getElementById("weather-alerts")).display === "none"
        && getComputedStyle(document.querySelector('[data-bind="weather_alert"]')).display === "none",
    null, { timeout: 3000 });
    const pageW = await page.evaluate(() => document.documentElement.scrollWidth);
    if (pageW > W) fail(`${tag}: page scrolls sideways (${pageW})`);
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
        for (const theme of ["heritage", "modern", "autodelta"]) await run(browser, theme);
    } finally {
        await browser.close();
    }
    process.stdout.write("ok\n");
})().catch((e) => {
    process.stderr.write(String(e && e.stack || e) + "\n");
    process.exit(1);
});
