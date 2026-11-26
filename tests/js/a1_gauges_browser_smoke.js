// Headless-Chromium check of the A1 side bars (screens/main.js: fuel left,
// engine temperature right) on the real dashboard at the car's 1024x600
// panel, for tests/test_frontend_gestures.py. Needs the `playwright` package
// and its Chromium; without either it prints "SKIP: <reason>" and exits 0.
//
// Nothing leaves the process: every request is answered here and the data
// WebSocket is a stub this script pushes payloads through. Checked, in all
// three themes:
//  - both bars are on screen, left / right of the media card, not covering
//    it, the top bar or the nav bar, and tall enough to read (>= 150 px);
//  - no horizontal scroll at 1024 px;
//  - a payload without a source draws grey "brak danych", an empty bar;
//  - real values fill the bar in proportion and refresh in place;
//  - no page errors.
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

async function open(browser, theme, errors) {
    const ctx = await browser.newContext({ viewport: { width: W, height: H } });
    const page = await ctx.newPage();
    page.on("pageerror", (e) => errors.push(e.message));
    await ctx.route("**/*", async (route) => {
        const req = route.request();
        const url = new URL(req.url());
        if (url.origin !== ORIGIN) return route.abort();
        const p = url.pathname;
        const json = (obj) => route.fulfill({ status: 200, contentType: "application/json",
                                              body: JSON.stringify(obj) });
        if (p === "/api/config" && req.method() === "GET") {
            return json({ theme, language: "pl", speed_unit: "km/h", temp_unit: "C" });
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
    await page.waitForSelector("#a1-fuel-gauge");
    return { ctx, page };
}

const push = (page, payload) => page.evaluate((p) => window.__push(p), payload);

async function geometry(page) {
    return page.evaluate(() => {
        const r = (sel) => {
            const e = document.querySelector(sel);
            if (!e) return null;
            const b = e.getBoundingClientRect();
            return { l: b.left, r: b.right, t: b.top, b: b.bottom, w: b.width, h: b.height };
        };
        const track = (k) => {
            const f = document.getElementById("a1-" + k + "-fill");
            return f ? { fill: f.getBoundingClientRect().height,
                         track: f.parentElement.getBoundingClientRect().height,
                         color: getComputedStyle(f).backgroundColor } : null;
        };
        const card = document.getElementById("media-title");
        let cardBox = null;
        if (card) {
            let n = card;
            // the column holding the media card + equalizer strip
            while (n && n.parentElement && n.parentElement.tagName !== "MAIN") n = n.parentElement;
            const b = n.getBoundingClientRect();
            cardBox = { l: b.left, r: b.right, t: b.top, b: b.bottom };
        }
        const main = document.querySelector("main.content-area").getBoundingClientRect();
        return {
            fuel: r("#a1-fuel-gauge"), coolant: r("#a1-coolant-gauge"), card: cardBox,
            main: { t: main.top, b: main.bottom },
            scrollW: document.scrollingElement.scrollWidth, vw: window.innerWidth,
            fuelTrack: track("fuel"), coolantTrack: track("coolant"),
            fuelVal: document.getElementById("a1-fuel-val").textContent,
            fuelNote: document.getElementById("a1-fuel-note").textContent,
            coolantVal: document.getElementById("a1-coolant-val").textContent,
            coolantState: document.getElementById("a1-coolant-gauge").getAttribute("data-state"),
        };
    });
}

async function run(browser, theme, shotDir) {
    const errors = [];
    const { ctx, page } = await open(browser, theme, errors);
    const tag = theme;

    // Old-style payload: fuel_level 50 default, no a1_gauges → no data.
    await push(page, { fuel_level: 50, coolant_temp: 0 });
    await page.waitForTimeout(150);
    let g = await geometry(page);
    if (g.fuelVal !== "—" || g.fuelNote !== "brak danych") fail(`${tag}: no source shows ${g.fuelVal} / ${g.fuelNote}`);
    if (g.fuelTrack.fill > 1) fail(`${tag}: empty bar is filled (${g.fuelTrack.fill}px)`);
    if (g.scrollW > g.vw) fail(`${tag}: horizontal scroll ${g.scrollW} > ${g.vw}`);
    for (const k of ["fuel", "coolant"]) {
        const b = g[k];
        if (!b) fail(`${tag}: ${k} bar missing`);
        if (b.l < 0 || b.r > g.vw) fail(`${tag}: ${k} bar off screen ${JSON.stringify(b)}`);
        if (b.t < g.main.t - 1 || b.b > g.main.b + 1) fail(`${tag}: ${k} bar outside content area`);
        if (g[k + "Track"].track < 150) fail(`${tag}: ${k} track only ${g[k + "Track"].track}px`);
    }
    if (!g.card) fail(`${tag}: media card not found`);
    if (g.fuel.r > g.card.l + 0.5) fail(`${tag}: fuel bar overlaps card (${g.fuel.r} > ${g.card.l})`);
    if (g.coolant.l < g.card.r - 0.5) fail(`${tag}: coolant bar overlaps card (${g.coolant.l} < ${g.card.r})`);
    if (g.card.r - g.card.l < 560) fail(`${tag}: media card shrank to ${g.card.r - g.card.l}px`);

    await push(page, { a1_gauges: { fuel: { source: "sensor", pct: 50 },
                                    coolant: { source: "sensor", c: 85 } } });
    await page.waitForTimeout(900);              // CSS transition .6 s
    g = await geometry(page);
    const ratio = g.fuelTrack.fill / g.fuelTrack.track;
    if (Math.abs(ratio - 0.5) > 0.04) fail(`${tag}: fuel 50% fills ${ratio.toFixed(2)}`);
    if (g.fuelVal !== "50%") fail(`${tag}: fuel text ${g.fuelVal}`);
    const cr = g.coolantTrack.fill / g.coolantTrack.track;
    if (Math.abs(cr - 0.5) > 0.04) fail(`${tag}: 85 °C fills ${cr.toFixed(2)}`);
    if (g.coolantVal !== "85°" || g.coolantState !== "ok") fail(`${tag}: coolant ${g.coolantVal} ${g.coolantState}`);
    if (shotDir) await page.screenshot({ path: path.join(shotDir, `a1_${theme}.png`) });

    await push(page, { a1_gauges: { fuel: { source: "estimate", pct: 12, litres: 7, reserve_pct: 12.7 },
                                    coolant: { source: "sensor", c: 108 } } });
    await page.waitForTimeout(900);
    g = await geometry(page);
    if (g.fuelNote !== "rezerwa · szac. 7 l") fail(`${tag}: estimate note ${g.fuelNote}`);
    const tickBottom = await page.evaluate(() => document.getElementById("a1-fuel-tick").style.bottom);
    if (tickBottom !== "12.7%") fail(`${tag}: reserve tick at ${tickBottom}`);
    if (g.fuelTrack.color !== "rgb(239, 68, 68)") fail(`${tag}: low fuel colour ${g.fuelTrack.color}`);
    if (g.coolantState !== "hot" || g.coolantTrack.color !== "rgb(239, 68, 68)") fail(`${tag}: hot coolant`);
    if (shotDir) await page.screenshot({ path: path.join(shotDir, `a1_${theme}_warn.png`) });

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
    const shotDir = process.env.A1_SHOT_DIR || "";
    try {
        for (const theme of ["heritage", "modern", "autodelta"]) await run(browser, theme, shotDir);
    } finally {
        await browser.close();
    }
    process.stdout.write("ok\n");
})().catch((e) => {
    process.stderr.write(String(e && e.stack || e) + "\n");
    process.exit(1);
});
