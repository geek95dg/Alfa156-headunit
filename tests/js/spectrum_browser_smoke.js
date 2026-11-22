// Headless-Chromium check of the A1 spectrum strip (screens/main.js) on the
// real dashboard at the car's 1024x600 panel, for
// tests/test_frontend_gestures.py. Needs the `playwright` package and its
// Chromium; without either it prints "SKIP: <reason>" and exits 0.
//
// Nothing leaves the process: every request is answered here and the data
// WebSocket is a stub this script pushes payloads through. Checked, in all
// three themes:
//  - silence (zeros) draws only the low baseline: bottom rows painted, the
//    rest of the canvas transparent;
//  - a payload with music draws bars that reach well above the baseline;
//  - the canvas backing store is in whole pixels and matches its CSS size;
//  - with CanvasRenderingContext2D.prototype.roundRect removed the strip
//    still draws and nothing throws;
//  - a throwing A1 update() cannot keep the reverse-camera view from opening
//    (app.js wraps the screen update in try/catch).
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

function dropRoundRect() {
    delete CanvasRenderingContext2D.prototype.roundRect;
}

async function open(browser, theme, noRoundRect, errors) {
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
    if (noRoundRect) await ctx.addInitScript(dropRoundRect);
    await page.goto(ORIGIN + "/");
    await page.waitForFunction(() => typeof App !== "undefined" && App.getCurrentScreen
                                     && App.getCurrentScreen() === "a1");
    await page.evaluate(() => {
        if (typeof Splash !== "undefined" && Splash.hide) Splash.hide();
        const s = document.getElementById("bcm-splash-overlay");
        if (s) s.remove();
    });
    await page.waitForSelector("#spectrum-canvas");
    return { ctx, page };
}

const push = (page, payload) => page.evaluate((p) => window.__push(p), payload);

// Painted rows of the canvas: [first painted row from the top, height].
async function paint(page) {
    return page.evaluate(() => {
        const c = document.getElementById("spectrum-canvas");
        const g = c.getContext("2d");
        const img = g.getImageData(0, 0, c.width, c.height).data;
        let top = -1;
        for (let y = 0; y < c.height && top < 0; y++) {
            for (let x = 0; x < c.width; x++) {
                if (img[(y * c.width + x) * 4 + 3] > 0) { top = y; break; }
            }
        }
        const b = c.getBoundingClientRect();
        return { top, h: c.height, w: c.width, cssW: b.width, cssH: b.height,
                 dpr: window.devicePixelRatio || 1 };
    });
}

async function run(browser, theme, noRoundRect) {
    const errors = [];
    const { ctx, page } = await open(browser, theme, noRoundRect, errors);
    const tag = `${theme}${noRoundRect ? " (no roundRect)" : ""}`;
    if (noRoundRect && await page.evaluate(() => typeof CanvasRenderingContext2D.prototype.roundRect)
            !== "undefined") {
        fail(`${tag}: roundRect still present`);
    }

    await push(page, { audio_spectrum: new Array(16).fill(0) });
    await page.waitForTimeout(250);
    let p = await paint(page);
    if (!Number.isInteger(p.w) || !Number.isInteger(p.h)) fail(`${tag}: fractional canvas ${p.w}x${p.h}`);
    if (Math.abs(p.w - Math.round(Math.round(p.cssW) * p.dpr)) > 1) fail(`${tag}: width ${p.w} vs css ${p.cssW}`);
    if (p.top < 0) fail(`${tag}: silence draws nothing — no baseline`);
    if (p.h - p.top > Math.ceil(3 * p.dpr)) fail(`${tag}: silence painted ${p.h - p.top} rows, want a 2 px baseline`);

    const bands = [0.9, 0.8, 0.7, 0.6, 0.5, 0.45, 0.4, 0.35, 0.3, 0.35, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9];
    for (let i = 0; i < 6; i++) {
        await push(page, { audio_spectrum: bands });
        await page.waitForTimeout(66);
    }
    await page.waitForTimeout(200);
    p = await paint(page);
    if (p.top < 0 || p.top > p.h * 0.3) fail(`${tag}: music bars too low (top row ${p.top} of ${p.h})`);

    // Back to silence: the strip settles down to the baseline again.
    await push(page, { audio_spectrum: new Array(16).fill(0) });
    await page.waitForTimeout(2000);
    p = await paint(page);
    if (p.h - p.top > Math.ceil(3 * p.dpr)) fail(`${tag}: did not settle to the baseline (${p.h - p.top} rows)`);

    if (errors.length) fail(`${tag}: page errors: ${errors.join("; ")}`);
    await ctx.close();
}

async function runThrowingUpdate(browser) {
    const errors = [];
    const { ctx, page } = await open(browser, "heritage", false, errors);
    await page.evaluate(() => {
        App.registerScreen("a1", {
            render(c) { c.innerHTML = "<div id='broken-a1'></div>"; },
            update() { throw new Error("renderer bug"); },
        });
        App.navigateTo("a1");
    });
    await push(page, { reverse_gear: true, audio_spectrum: new Array(16).fill(0.5) });
    await page.waitForSelector("#reverse-overlay", { timeout: 3000 })
        .catch(() => fail("a throwing screen update() kept the reverse view from opening"));
    if (errors.some((e) => !/renderer bug/.test(e))) fail(`page errors: ${errors.join("; ")}`);
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
        for (const theme of ["heritage", "modern", "autodelta"]) await run(browser, theme, false);
        await run(browser, "heritage", true);
        await runThrowingUpdate(browser);
    } finally {
        await browser.close();
    }
    process.stdout.write("ok\n");
})().catch((e) => {
    process.stderr.write(String(e && e.stack || e) + "\n");
    process.exit(1);
});
