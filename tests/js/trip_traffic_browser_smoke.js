// Headless-Chromium check of the live traffic section on the A3 travel plan
// overlay (screens/trip.js, data.traffic_alerts from web_viewer
// _traffic_alerts_summary) at the car's 1024x600 panel, for
// tests/test_frontend_gestures.py. Needs the `playwright` package and its
// Chromium; without either it prints "SKIP: <reason>" and exits 0.
//
// Checked in every theme:
//  - module off (traffic_alerts null): the section is hidden;
//  - a list arrives: rows with icon, title and text, network text escaped
//    (a title with markup stays text — no element, no handler runs);
//  - the next payload refreshes the list IN PLACE: the overlay (and its
//    search field, a touch target) is the same element, not rebuilt;
//  - status lines: "zapytania dziś", no key, 429 with the pause, idle;
//  - the section fits inside 1024 px and the overlay scrolls to it;
//  - with 3 planned incidents and 8 live items the planned-incidents box
//    keeps its height and does not overlap the live section;
//  - trip stats view: the Travel Plan button carries a count badge with the
//    nearest distance, gone when nothing is ahead.
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
    window.__pwned = 0;
    try { localStorage.setItem("bcm.travelPlan", "1"); } catch (e) {}
}

const PLAN = { destination_name: "Cel testowy", distance_km: 120, eta_min: 80,
               predicted_fuel_l: 8.4, weather_points: [], incidents: [], service_errors: [] };

function traffic(items, extra) {
    return Object.assign({ items, state: "driving", mode: "route", used: 12, budget: 300,
                           poll_min: 5, last_ok: 1.8e9, backoff_until: null, error: null }, extra || {});
}

const JAM = { kind: "jam", title: "Korek za 3,2 km", text: "S8 · opóźnienie ok. 10 min",
              distance_km: 3.2, delay_min: 10, on_route: true };
const EVIL = { kind: "accident", title: '<img src=x onerror="window.__pwned=1">Wypadek',
               text: "<b>A</b> → B", distance_km: 6.0, delay_min: null, on_route: false };

async function open(browser) {
    const ctx = await browser.newContext({ viewport: { width: W, height: H } });
    const page = await ctx.newPage();
    const errors = [];
    page.on("pageerror", (e) => errors.push(e.message));
    await ctx.route("**/*", async (route) => {
        const url = new URL(route.request().url());
        if (url.origin !== ORIGIN) return route.abort();
        const p = url.pathname;
        if (p.startsWith("/api/") || p.startsWith("/bt/") || p.startsWith("/aa/")) {
            return route.fulfill({ status: 200, contentType: "application/json",
                                   body: JSON.stringify(p === "/api/boot_mode" ? { boot_mode: "cold" } : {}) });
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
    return { ctx, page, errors };
}

async function state(page) {
    return page.evaluate(() => {
        const wrap = document.querySelector("[data-trip-traffic-wrap]");
        const box = document.querySelector("[data-trip-traffic]");
        const st = document.querySelector("[data-trip-traffic-status]");
        return {
            present: !!wrap,
            shown: !!wrap && getComputedStyle(wrap).display !== "none",
            rows: [...document.querySelectorAll("[data-trip-traffic-item]")].map((r) => r.textContent.replace(/\s+/g, " ").trim()),
            icons: [...document.querySelectorAll("[data-trip-traffic-item] .material-symbols-outlined")].map((i) => i.textContent),
            status: st ? st.textContent : null,
            statusState: st ? st.getAttribute("data-trip-traffic-status") : null,
            none: !!document.querySelector("[data-trip-traffic-none]"),
            imgs: box ? box.querySelectorAll("img, b").length : -1,
            pwned: window.__pwned,
        };
    });
}

async function run(browser, theme) {
    const tag = `${W}x${H} ${theme}`;
    const { ctx, page, errors } = await open(browser);
    await page.evaluate((t) => App.setTheme(t), theme);
    await page.evaluate(() => App.navigateTo("a3"));
    await page.evaluate((plan) => window.__push({ trip_plan: plan, traffic_alerts: null }), PLAN);
    await page.waitForSelector(".travel-plan-overlay");
    let s = await state(page);
    if (!s.present) fail(`${tag}: no traffic section in the overlay`);
    if (s.shown) fail(`${tag}: section shown with the module off`);

    // Mark the overlay and its search field: an in-place refresh keeps them.
    await page.evaluate(() => {
        document.querySelector(".travel-plan-overlay").dataset.mark = "1";
        document.querySelector(".tp-search").dataset.mark = "1";
    });
    await page.evaluate(([plan, t]) => window.__push({ trip_plan: plan, traffic_alerts: t }),
                        [PLAN, traffic([JAM, EVIL])]);
    await page.waitForFunction(() => document.querySelectorAll("[data-trip-traffic-item]").length === 2);
    s = await state(page);
    if (!s.shown) fail(`${tag}: section hidden with items`);
    if (s.pwned || s.imgs !== 0) fail(`${tag}: network text rendered as markup ${JSON.stringify(s)}`);
    if (!s.rows[0].includes("Korek za 3,2 km") || !s.rows[0].includes("na trasie")) fail(`${tag}: row ${s.rows[0]}`);
    if (!s.rows[1].includes('<img src=x onerror="window.__pwned=1">Wypadek') || !s.rows[1].includes("<b>A</b> → B")) {
        fail(`${tag}: escaped row ${s.rows[1]}`);
    }
    if (s.icons.join(",") !== "traffic,car_crash") fail(`${tag}: icons ${s.icons}`);
    if (!/na trasie · zapytania dziś: 12\/300/.test(s.status)) fail(`${tag}: status ${s.status}`);

    // Geometry: inside the panel width; the overlay scrolls to it.
    const g = await page.evaluate(() => {
        const sec = document.querySelector("[data-trip-traffic-wrap]");
        sec.scrollIntoView({ block: "nearest" });
        const r = sec.getBoundingClientRect();
        return { l: r.left, r: r.right, t: r.top, b: r.bottom };
    });
    if (!(g.l >= 0 && g.r <= W && g.t >= 0 && g.b <= H)) fail(`${tag}: section off screen ${JSON.stringify(g)}`);

    // A full overlay: 3 planned incidents + 8 live items must not overlap
    // (the planned box used to collapse to 0 px and paint over the list).
    const busy = Object.assign({}, PLAN, { incidents: [
        { description: "Roboty A" }, { description: "Roboty B" }, { description: "Roboty C" }] });
    const eight = Array.from({ length: 8 }, (_, i) => Object.assign({}, JAM, { title: `Korek ${i}`, distance_km: 1 + i }));
    await page.evaluate(([plan, t]) => window.__push({ trip_plan: plan, traffic_alerts: t }),
                        [busy, traffic(eight)]);
    await page.waitForFunction(() => document.querySelectorAll("[data-trip-traffic-item]").length === 8
                                     && document.querySelectorAll("[data-trip-plan-incidents] .material-symbols-outlined").length === 3);
    const ov = await page.evaluate(() => {
        const a = document.querySelector("[data-trip-plan-incidents]").getBoundingClientRect();
        const b = document.querySelector("[data-trip-traffic-wrap]").getBoundingClientRect();
        return { at: a.top, ab: a.bottom, ah: a.height, bt: b.top };
    });
    if (!(ov.ah > 0 && ov.ab <= ov.bt + 0.5)) fail(`${tag}: planned incidents overlap the live list ${JSON.stringify(ov)}`);
    // Back to the plain plan (a changed plan rebuilds the overlay), then mark.
    await page.evaluate(([plan, t]) => window.__push({ trip_plan: plan, traffic_alerts: t }),
                        [PLAN, traffic([JAM, EVIL])]);
    await page.waitForFunction(() => document.querySelectorAll("[data-trip-traffic-item]").length === 2);
    await page.evaluate(() => { document.querySelector(".travel-plan-overlay").dataset.mark = "1";
                                document.querySelector(".tp-search").dataset.mark = "1"; });

    // Refresh in place.
    await page.evaluate(([plan, t]) => window.__push({ trip_plan: plan, traffic_alerts: t }),
                        [PLAN, traffic([JAM], { used: 13 })]);
    await page.waitForFunction(() => document.querySelectorAll("[data-trip-traffic-item]").length === 1);
    const kept = await page.evaluate(() => document.querySelector(".travel-plan-overlay").dataset.mark === "1"
                                         && document.querySelector(".tp-search").dataset.mark === "1");
    if (!kept) fail(`${tag}: overlay rebuilt for a traffic update`);
    s = await state(page);
    if (!/12|13/.test(s.status) || !s.status.includes("13/300")) fail(`${tag}: status not refreshed ${s.status}`);

    // Nothing ahead while driving.
    await page.evaluate(([plan, t]) => window.__push({ trip_plan: plan, traffic_alerts: t }),
                        [PLAN, traffic([], { mode: "ahead" })]);
    await page.waitForFunction(() => !!document.querySelector("[data-trip-traffic-none]"));
    s = await state(page);
    if (!s.status.startsWith("przed autem")) fail(`${tag}: ahead status ${s.status}`);

    const cases = [
        [{ state: "no_key" }, "no_key", /BCM_TOMTOM_API_KEY/],
        [{ state: "backoff", error: { service: "tomtom", result: "http", http_code: 429 },
           backoff_until: Date.now() / 1000 + 14 * 60 }, "backoff", /TomTom: błąd 429.*ponowię za 1[45] min/],
        [{ state: "budget", used: 300 }, "budget", /limit zapytań wykorzystany.*300\/300/],
        [{ state: "idle" }, "idle", /w trakcie jazdy.*12\/300/],
    ];
    for (const [extra, want, re] of cases) {
        await page.evaluate(([plan, t]) => window.__push({ trip_plan: plan, traffic_alerts: t }),
                            [PLAN, traffic([], extra)]);
        await page.waitForFunction((w) => {
            const st = document.querySelector("[data-trip-traffic-status]");
            return st && st.getAttribute("data-trip-traffic-status") === w;
        }, want);
        s = await state(page);
        if (!re.test(s.status)) fail(`${tag}: ${want} status ${s.status}`);
        if (s.none) fail(`${tag}: "brak utrudnień" in state ${want}`);
    }

    // Trip stats view (no overlay): the toggle button carries the badge.
    await page.evaluate(([plan, t]) => window.__push({ trip_plan: plan, traffic_alerts: t }),
                        [PLAN, traffic([EVIL, JAM])]);
    await page.click(".tp-toggle-btn");
    await page.waitForFunction(() => !document.querySelector(".travel-plan-overlay"));
    await page.waitForFunction(() => !!document.querySelector(".tp-toggle-btn [data-trip-traffic-badge]"));
    const badge = await page.evaluate(() => {
        const b = document.querySelector(".tp-toggle-btn [data-trip-traffic-badge]");
        const r = document.querySelector(".tp-toggle-btn").getBoundingClientRect();
        return { text: b.textContent.replace(/\s+/g, " ").trim(), l: r.left, r: r.right, t: r.top, b: r.bottom };
    });
    if (badge.text !== "warning2 · 3,2 km") fail(`${tag}: badge ${badge.text}`);
    if (!(badge.l >= 0 && badge.r <= W && badge.t >= 0 && badge.b <= H)) fail(`${tag}: button off screen ${JSON.stringify(badge)}`);
    await page.evaluate(([plan, t]) => window.__push({ trip_plan: plan, traffic_alerts: t }),
                        [PLAN, traffic([])]);
    await page.waitForFunction(() => !document.querySelector(".tp-toggle-btn [data-trip-traffic-badge]"));
    await page.click(".tp-toggle-btn");
    await page.waitForSelector(".travel-plan-overlay");

    // Module switched off at runtime: hidden again.
    await page.evaluate((plan) => window.__push({ trip_plan: plan, traffic_alerts: null }), PLAN);
    await page.waitForFunction(() => getComputedStyle(document.querySelector("[data-trip-traffic-wrap]")).display === "none");
    if (errors.length) fail(`${tag}: page errors ${errors.join("; ")}`);
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
        process.stdout.write("ok\n");
    } catch (e) {
        process.stderr.write(String(e && e.stack || e) + "\n");
        process.exitCode = 1;
    } finally {
        await browser.close();
    }
})();
