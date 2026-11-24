// Headless-Chromium check of the Settings rows "Traccar" and "Ostatni postój"
// (screens/settings.js traccarRowHtml / lastParkRowHtml, data.traccar and
// data.last_park from web_viewer) on the real dashboard at the car's
// 1024x600 panel, for tests/test_frontend_gestures.py. Needs the
// `playwright` package and its Chromium; without either it prints
// "SKIP: <reason>" and exits 0.
//
// Why: the Traccar row packs the state, host, mode, last point, queue and
// "Wyślij pozycję teraz" into one flex row at 11 px, and the last-stop row
// carries a long map URL — the node smoke test cannot see wrapping or
// overflow. Nothing leaves the process: every request is answered here.
//  - both rows fit the 1024 px width, nothing inside sticks out, no
//    horizontal page scroll (also with the longest hints);
//  - the button is on screen and not covered; a tap posts once to
//    /api/traccar/send with "{}".

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

const TS = 1.8e9;
const AGENT = { enabled: true, configured: true, id_fp: "a1b2c3d4", mode: "drive", queue_n: 487,
                last_sent_ts: TS, last_ok_ts: TS, last_error: "unknown_device", last_http: 400,
                dropped: 0, paused_low_battery: true };
const LONG = { url_ok: true, url_host: "traccar-gps.very-long-subdomain.example.org", id_set: true,
               id_fp: "ffffffff", agent: AGENT, error: "",
               cmd: { state: "failed", error: "rate_limited", ts: TS } };
const OK = { url_ok: true, url_host: "example.org", id_set: true, id_fp: "a1b2c3d4",
             agent: Object.assign({}, AGENT, { mode: "park", queue_n: 0, last_error: "",
                                               paused_low_battery: false }),
             cmd: null, error: "" };
const LP = { lat: -33.123456, lon: -170.654321, ts: TS, reason: "still",
             osm_url: "https://www.openstreetmap.org/?mlat=-33.123456&mlon=-170.654321#map=17/-33.123456/-170.654321",
             geo_url: "geo:-33.123456,-170.654321" };

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
        if (p === "/api/traccar/send" && req.method() === "POST") {
            posts.push([p, req.postData() || ""]);
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

async function measure(page, sel, btnSel) {
    await page.evaluate((s) => document.querySelector(s).scrollIntoView({ block: "center" }), sel);
    await page.waitForTimeout(150);
    return page.evaluate(([s, bs]) => {
        const row = document.querySelector(s);
        const r = row.getBoundingClientRect();
        const outside = [...row.querySelectorAll("*")].filter((el) => {
            const e = el.getBoundingClientRect();
            return e.width > 0 && (e.left < r.left - 0.5 || e.right > r.right + 0.5);
        }).map((el) => el.outerHTML.slice(0, 80));
        let btn = null;
        if (bs) {
            const b = row.querySelector(bs).getBoundingClientRect();
            const hit = document.elementFromPoint(b.left + b.width / 2, b.top + b.height / 2);
            btn = { l: b.left, r: b.right, t: b.top, b: b.bottom, w: b.width, h: b.height,
                    hit: !!hit && (hit === row.querySelector(bs) || row.querySelector(bs).contains(hit)) };
        }
        return { l: r.left, r: r.right, sw: row.scrollWidth, cw: row.clientWidth,
                 page: document.documentElement.scrollWidth, outside, btn };
    }, [sel, btnSel]);
}

function check(tag, m) {
    if (m.l < 0 || m.r > W || m.page > W) fail(`${tag}: row does not fit ${JSON.stringify(m)}`);
    if (m.sw > m.cw + 1) fail(`${tag}: row overflows (${m.sw} > ${m.cw})`);
    if (m.outside.length) fail(`${tag}: outside the row: ${m.outside.join(" | ")}`);
    if (m.btn && !(m.btn.w > 0 && m.btn.h > 0 && m.btn.l >= 0 && m.btn.r <= W
                   && m.btn.t >= 0 && m.btn.b <= H && m.btn.hit)) {
        fail(`${tag}: button off screen or covered ${JSON.stringify(m.btn)}`);
    }
}

async function run(browser, touch) {
    const tag = `${W}x${H}${touch ? " touch" : ""}`;
    const posts = [];
    const errors = [];
    const { ctx, page } = await open(browser, touch, posts, errors);
    await push(page, { traccar: LONG, last_park: LP });
    await page.evaluate(() => App.navigateTo("settings"));
    await page.waitForSelector("[data-traccar-state]");
    await page.waitForSelector("[data-last-park]");
    for (const [name, payload] of [["long", LONG], ["ok", OK]]) {
        await push(page, { traccar: payload, last_park: LP });
        await page.waitForFunction((st) => !!document.querySelector(`[data-traccar-state="${st}"]`),
                                   name === "long" ? "error" : "ok", { timeout: 3000 });
        check(`${tag} traccar ${name}`, await measure(page, "[data-traccar-state]", "[data-traccar-send]"));
        check(`${tag} last park`, await measure(page, "[data-last-park]", null));
    }
    const b = await page.evaluate(() => {
        const r = document.querySelector("[data-traccar-send]").getBoundingClientRect();
        return { x: r.left + r.width / 2, y: r.top + r.height / 2 };
    });
    if (touch) await page.touchscreen.tap(b.x, b.y);
    else await page.mouse.click(b.x, b.y);
    await page.waitForTimeout(300);
    const want = [["/api/traccar/send", "{}"]];
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
