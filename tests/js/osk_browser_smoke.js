// Headless-Chromium check of the on-screen keyboard (web/js/components/
// keyboard.js + web/css/themes.css) on the real dashboard, for
// tests/test_frontend_keyboard.py. Needs the `playwright` package and its
// Chromium; without either it prints "SKIP: <reason>" and exits 0 so the
// pytest wrapper can skip instead of failing.
//
// Nothing leaves the process: every HTTP request is answered from
// src/dashboard/web (API calls get "{}"), and WebSocket is replaced by an
// inert stub before any page script runs.
//
// For each panel size (1024x600 — the car's 7" panel, 800x480, 1280x800) it
// opens Settings, pushes the Wi-Fi SSID field into the lower part of the
// screen (where the keyboard will appear), taps it, and checks:
//   * the keyboard is still open after the whole tap (the old click handler
//     closed it again for lower-half fields and for every password field);
//   * all 50 keys are inside the window AND are the element hit at their own
//     centre, i.e. each one can actually be pressed;
//   * the panel leaves >= 150 px above it and the field ends >= 12 px above
//     the keys;
//   * typing works, a password preview is masked, a tap outside closes it,
//     and a tap on a button above the keyboard still reaches that button;
//   * a resize while open re-sizes the keyboard.
// The 1024x600 run is repeated with touch input.
//
// Then, at 1024x600 with mouse and with touch, the two search boxes with a
// suggestion list (trip planner, weather): type "gdy" on the keyboard, tap a
// suggestion, and check the keyboard is gone and the list stays gone. The
// trip planner's suggestions call preventDefault() in touchend, so on touch
// no click follows the tap — the keyboard's pointerup fallback must close
// it. The weather list used to come back (under an empty field) because
// closing the keyboard fired an extra "input" event that re-ran the search.
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
const ORIGIN = "http://bcm.invalid";
const MIME = {
    ".html": "text/html; charset=utf-8", ".js": "application/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8", ".json": "application/json", ".svg": "image/svg+xml",
    ".png": "image/png", ".jpg": "image/jpeg", ".ttf": "font/ttf", ".woff2": "font/woff2",
    ".woff": "font/woff", ".mp4": "video/mp4",
};
const CASES = [
    { w: 1024, h: 600, touch: false },
    { w: 1024, h: 600, touch: true },
    { w: 800, h: 480, touch: false },
    { w: 1280, h: 800, touch: false },
];
const N_KEYS = 50;   // 10 + 10 + 9 + 9 + 9 + (hide, SPACE, OK)
// Answer of both place searches (/api/trip/search, /api/weather/search).
const PLACES = JSON.stringify({ results: [
    { name: "Gdynia", state: "Pomorskie", country: "PL", lat: 54.52, lon: 18.53 },
    { name: "Gdańsk", state: "Pomorskie", country: "PL", lat: 54.35, lon: 18.65 },
] });

function fail(msg) { throw new Error(msg); }

async function serve(route) {
    const url = new URL(route.request().url());
    if (url.origin !== ORIGIN) return route.abort();
    const p = url.pathname;
    if (p.startsWith("/api/") || p.startsWith("/bt/")) {
        // Cold boot → App goes straight to a1 instead of waiting on "init".
        const body = p === "/api/boot_mode" ? '{"boot_mode":"cold"}'
            : (p === "/api/trip/search" || p === "/api/weather/search") ? PLACES : "{}";
        return route.fulfill({ status: 200, contentType: "application/json", body });
    }
    const file = path.resolve(WEB, "." + (p === "/" ? "/index.html" : p));
    if (!file.startsWith(WEB + path.sep) || !fs.existsSync(file) || !fs.statSync(file).isFile()) {
        return route.fulfill({ status: 404, body: "" });
    }
    return route.fulfill({
        status: 200, body: fs.readFileSync(file),
        contentType: MIME[path.extname(file)] || "application/octet-stream",
    });
}

// Runs in the page before any script: no real sockets.
function stubWebSocket() {
    window.WebSocket = class {
        constructor() { this.readyState = 0; }
        send() {}
        close() {}
        addEventListener() {}
        removeEventListener() {}
    };
}

// The dashboard in a fresh context, booted to a1, splash gone; plus tap
// helpers that use the mouse or the touchscreen as the case asks.
async function openDashboard(browser, c) {
    const tag = `${c.w}x${c.h}${c.touch ? " touch" : ""}`;
    const ctx = await browser.newContext({ viewport: { width: c.w, height: c.h }, hasTouch: c.touch });
    const page = await ctx.newPage();
    const errors = [];
    page.on("pageerror", (e) => errors.push(e.message));
    await ctx.route("**/*", serve);
    await ctx.addInitScript(stubWebSocket);
    await page.goto(ORIGIN + "/");
    await page.waitForFunction(() => typeof App !== "undefined" && App.getCurrentScreen
                                     && App.getCurrentScreen() === "a1");
    await page.evaluate(() => {
        if (typeof Splash !== "undefined") Splash.hide();
        const s = document.getElementById("bcm-splash-overlay");
        if (s) s.remove();
    });

    const tap = async (x, y) => {
        if (c.touch) await page.touchscreen.tap(x, y);
        else await page.mouse.click(x, y);
        await page.waitForTimeout(150);   // rAF + layout
    };
    const tapKey = async (k) => {
        const b = await page.$(`#osk-overlay button[onclick="OnScreenKeyboard.key('${k}')"]`);
        if (!b) fail(`${tag}: no key ${k}`);
        const r = await b.boundingBox();
        await tap(r.x + r.width / 2, r.y + r.height / 2);
    };
    return { tag, ctx, page, errors, tap, tapKey };
}

async function run(browser, c) {
    const { tag, ctx, page, errors, tap, tapKey } = await openDashboard(browser, c);
    await page.evaluate(() => App.navigateTo("settings"));
    await page.waitForSelector(".content-area input[type=text]");

    // Push a field to `frac` of the window height (a spacer at the top of the
    // content area), so it sits where the keyboard is about to appear.
    const placeField = (sel, frac) => page.evaluate(([sel, frac]) => {
        const el = document.querySelector(sel);
        const ca = el.closest(".content-area");
        ca.scrollTop = 0;
        let sp = document.getElementById("osk-test-spacer");
        if (!sp) {
            sp = document.createElement("div");
            sp.id = "osk-test-spacer";
            ca.insertBefore(sp, ca.firstChild);
        }
        sp.style.height = "0px";
        const r0 = el.getBoundingClientRect();
        sp.style.height = Math.max(0, Math.round(innerHeight * frac - (r0.top + r0.bottom) / 2)) + "px";
        const r = el.getBoundingClientRect();
        return { top: r.top, bottom: r.bottom, cx: r.left + r.width / 2, cy: r.top + r.height / 2 };
    }, [sel, frac]);

    // Geometry of the open keyboard and the field; null when it is closed.
    const measure = (sel) => page.evaluate((sel) => {
        const ov = document.getElementById("osk-overlay");
        if (!ov) return null;
        const o = ov.getBoundingClientRect();
        const keys = [...ov.querySelectorAll("button")].map((b) => {
            const r = b.getBoundingClientRect();
            const hit = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
            return { label: (b.getAttribute("onclick") || b.title || "").slice(0, 40),
                     left: r.left, top: r.top, right: r.right, bottom: r.bottom,
                     h: r.height, w: r.width, hit: !!hit && b.contains(hit) };
        });
        const f = document.querySelector(sel).getBoundingClientRect();
        return { top: o.top, bottom: o.bottom, keys, field: { top: f.top, bottom: f.bottom },
                 open: document.body.classList.contains("osk-open"),
                 focused: document.activeElement === document.querySelector(sel),
                 preview: (document.getElementById("osk-display") || {}).textContent };
    }, sel);

    const check = (m, what) => {
        if (!m) fail(`${tag} ${what}: keyboard closed right after the tap`);
        if (!m.open) fail(`${tag} ${what}: body.osk-open missing`);
        if (m.keys.length !== N_KEYS) fail(`${tag} ${what}: ${m.keys.length} keys, expected ${N_KEYS}`);
        const eps = 0.5;
        const minH = c.h >= 600 ? 40 : 34;
        for (const k of m.keys) {
            if (k.left < -eps || k.top < -eps || k.right > c.w + eps || k.bottom > c.h + eps) {
                fail(`${tag} ${what}: key ${k.label} outside the window ${JSON.stringify(k)}`);
            }
            if (!k.hit) fail(`${tag} ${what}: key ${k.label} is covered (not hit at its centre)`);
            if (k.h < minH) fail(`${tag} ${what}: key ${k.label} only ${k.h}px tall (< ${minH})`);
        }
        if (Math.abs(m.bottom - c.h) > 1) fail(`${tag} ${what}: panel bottom ${m.bottom} != ${c.h}`);
        if (m.top < 150 - eps) fail(`${tag} ${what}: panel top ${m.top} leaves < 150 px above`);
        if (m.field.bottom > m.top - 12 + eps) {
            fail(`${tag} ${what}: field bottom ${m.field.bottom} not 12 px above keys (top ${m.top})`);
        }
        if (m.field.top < 0) fail(`${tag} ${what}: field scrolled off the top (${m.field.top})`);
    };

    const SSID = ".content-area input[type=text]";
    const PWD = ".content-area input[type=password]";

    // 1. Text field in the lower part of the screen.
    let p = await placeField(SSID, 0.8);
    if (p.cy < c.h / 2 || p.bottom > c.h) fail(`${tag}: could not place the field low (${JSON.stringify(p)})`);
    await page.$eval(SSID, (el) => { el.value = ""; });
    await tap(p.cx, p.cy);
    let m = await measure(SSID);
    check(m, "text field");
    await tapKey("a");
    await tapKey("shift");
    await tapKey("b");
    await tapKey("ł");
    const typed = await page.$eval(SSID, (el) => el.value);
    if (typed !== "aBł") fail(`${tag}: typed ${JSON.stringify(typed)}, expected "aBł"`);
    m = await measure(SSID);
    check(m, "after typing");
    if (m.preview !== "aBł") fail(`${tag}: preview ${JSON.stringify(m.preview)}`);

    // 2. Tap outside (a plain spot of content above the keyboard) closes it.
    // The spot keeps 16 px of plain content around it: Chromium's touch
    // adjustment snaps a finger-sized tap onto a nearby clickable element
    // (the keyboard itself, if the spot hugs its top edge).
    const spot = await page.evaluate(() => {
        const top = document.getElementById("osk-overlay").getBoundingClientRect().top;
        const plain = (x, y) => {
            const el = document.elementFromPoint(x, y);
            return !!el && !!el.closest(".content-area")
                && !el.closest("button,a,input,label,select,textarea,[onclick]");
        };
        for (let y = Math.floor(top) - 40; y > 80; y -= 6) {
            for (const x of [innerWidth - 24, innerWidth / 2, 24]) {
                if ([[0, 0], [-16, 0], [16, 0], [0, -16], [0, 16]]
                    .every(([dx, dy]) => plain(x + dx, y + dy))) return { x, y };
            }
        }
        return null;
    });
    if (!spot) fail(`${tag}: no plain spot above the keyboard to tap`);
    await tap(spot.x, spot.y);
    if (await measure(SSID)) fail(`${tag}: tap outside did not close the keyboard`);
    if (await page.evaluate(() => document.body.classList.contains("osk-open"))) {
        fail(`${tag}: body.osk-open left behind after closing`);
    }

    // 3. Password field, also low on the screen: stays open, preview masked.
    p = await placeField(PWD, 0.8);
    await page.$eval(PWD, (el) => { el.value = ""; });
    await tap(p.cx, p.cy);
    m = await measure(PWD);
    check(m, "password field");
    await tapKey("x");
    await tapKey("7");
    m = await measure(PWD);
    if (m.preview !== "\u2022\u2022") fail(`${tag}: password preview ${JSON.stringify(m.preview)}`);
    if ((await page.$eval(PWD, (el) => el.value)) !== "x7") fail(`${tag}: password not typed`);

    // 4. OK closes and keeps the value.
    await tapKey("done");
    if (await measure(PWD)) fail(`${tag}: OK did not close the keyboard`);
    if ((await page.$eval(PWD, (el) => el.value)) !== "x7") fail(`${tag}: OK lost the value`);

    // 5. The last field on the page: the keyboard scrolls it up into the
    // content padding. A tap on a button above the keyboard must still reach
    // that button — closing already on pointerdown would drop the padding
    // mid-tap, the content would jump down and the click would miss.
    p = await page.evaluate(() => {
        const ca = document.querySelector(".content-area");
        ca.insertAdjacentHTML("beforeend",
            '<button id="osk-test-btn" type="button" style="display:block;width:240px;height:44px">t</button>'
            + '<div style="height:20px"></div><input id="osk-test-last" type="text" style="display:block">');
        window.__oskBtn = 0;
        document.getElementById("osk-test-btn").addEventListener("click", () => { window.__oskBtn++; });
        ca.scrollTop = ca.scrollHeight;
        const r = document.getElementById("osk-test-last").getBoundingClientRect();
        return { cx: r.left + r.width / 2, cy: r.top + r.height / 2 };
    });
    await tap(p.cx, p.cy);
    m = await measure("#osk-test-last");
    check(m, "last field");
    const btn = await page.evaluate(() => {
        const r = document.getElementById("osk-test-btn").getBoundingClientRect();
        return { cx: r.left + r.width / 2, cy: r.top + r.height / 2, top: r.top, bottom: r.bottom };
    });
    if (btn.bottom > m.top || btn.top < 60) fail(`${tag}: test button not visible ${JSON.stringify(btn)}`);
    await tap(btn.cx, btn.cy);
    if ((await page.evaluate(() => window.__oskBtn)) !== 1) {
        fail(`${tag}: the tap on a button above the keyboard was lost`);
    }
    if (await measure("#osk-test-last")) fail(`${tag}: tap on the button did not close the keyboard`);

    // 6. Resize while open: the keyboard follows the new window height.
    p = await placeField(SSID, 0.8);
    await tap(p.cx, p.cy);
    await page.setViewportSize({ width: c.w, height: c.h - 30 });
    await page.waitForTimeout(150);
    m = await measure(SSID);
    if (!m) fail(`${tag}: keyboard closed by the resize`);
    if (Math.abs(m.bottom - (c.h - 30)) > 1) fail(`${tag}: after resize panel bottom ${m.bottom}`);
    if (m.field.bottom > m.top - 12 + 0.5) fail(`${tag}: after resize the field is under the keys`);

    if (errors.length) fail(`${tag}: page errors: ${errors.join(" | ")}`);
    await ctx.close();
    return tag;
}

// Tap the first suggestion of a search box while the keyboard is open; the
// keyboard must close and the suggestion list must not come back.
async function runSuggestions(browser, c) {
    const { tag, ctx, page, errors, tap, tapKey } = await openDashboard(browser, c);
    const open = () => page.evaluate(() => !!document.getElementById("osk-overlay")
                                           || document.body.classList.contains("osk-open"));
    // Centre of the part of `sel` that is not under the keyboard, if that
    // point really hits it.
    const visibleCentre = (sel) => page.evaluate((sel) => {
        const el = document.querySelector(sel);
        if (!el) return null;
        const r = el.getBoundingClientRect();
        const ov = document.getElementById("osk-overlay");
        const bottom = Math.min(r.bottom, ov ? ov.getBoundingClientRect().top : innerHeight);
        if (bottom - r.top < 12) return null;
        const x = r.left + r.width / 2;
        const y = (r.top + bottom) / 2;
        const hit = document.elementFromPoint(x, y);
        return hit && el.contains(hit) ? { x, y } : null;
    }, sel);
    const typeGdy = async (field) => {
        const f = await visibleCentre(field);
        if (!f) fail(`${tag}: ${field} not tappable`);
        await tap(f.x, f.y);
        if (!(await open())) fail(`${tag}: ${field} did not open the keyboard`);
        for (const k of ["g", "d", "y"]) await tapKey(k);
        if ((await page.$eval(field, (el) => el.value)) !== "gdy") fail(`${tag}: ${field} not typed`);
    };

    // 1. Trip planner (a3, Travel Plan on).
    await page.evaluate(() => App.navigateTo("a3"));
    await page.waitForSelector(".tp-toggle-btn");
    await page.evaluate(() => {
        if (!document.querySelector(".travel-plan-overlay")) document.querySelector(".tp-toggle-btn").click();
    });
    await page.waitForSelector(".travel-plan-overlay .tp-search");
    await typeGdy(".travel-plan-overlay .tp-search");
    await page.waitForSelector(".tp-result-item", { timeout: 3000 });
    let item = await visibleCentre(".tp-result-item");
    if (!item) fail(`${tag}: trip suggestion hidden under the keyboard`);
    await tap(item.x, item.y);
    await page.waitForTimeout(700);   // > the 350 ms fallback and the 300 ms search debounce
    if (await open()) fail(`${tag}: keyboard still open after picking a trip suggestion`);
    if (await page.$(".tp-result-item")) fail(`${tag}: trip suggestions came back after the pick`);

    // 2. Weather (a4).
    await page.evaluate(() => App.navigateTo("a4"));
    await page.waitForSelector("#weather-search-input");
    await typeGdy("#weather-search-input");
    const firstPlace = "#weather-search-results [data-weather-idx]";
    await page.waitForSelector(firstPlace, { timeout: 3000 });
    item = await visibleCentre(firstPlace);
    if (!item) fail(`${tag}: weather suggestion hidden under the keyboard`);
    await tap(item.x, item.y);
    await page.waitForTimeout(700);
    if (await open()) fail(`${tag}: keyboard still open after picking a weather suggestion`);
    const list = await page.evaluate(() => {
        const el = document.getElementById("weather-search-results");
        return { shown: !!el && el.style.display !== "none" && el.children.length > 0,
                 value: document.getElementById("weather-search-input").value };
    });
    if (list.shown) fail(`${tag}: weather suggestions came back after the pick`);
    if (list.value !== "") fail(`${tag}: weather field refilled with ${JSON.stringify(list.value)}`);

    if (errors.length) fail(`${tag}: page errors: ${errors.join(" | ")}`);
    await ctx.close();
    return tag + " suggestions";
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
        for (const c of CASES) process.stdout.write((await run(browser, c)) + " ok\n");
        for (const touch of [false, true]) {
            process.stdout.write((await runSuggestions(browser, { w: 1024, h: 600, touch })) + " ok\n");
        }
    } finally {
        await browser.close();
    }
    process.stdout.write("ok\n");
})().catch((e) => {
    process.stderr.write(String(e && e.stack || e) + "\n");
    process.exit(1);
});
