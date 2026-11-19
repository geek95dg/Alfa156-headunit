// Headless-Chromium check of "Zadzwoń 112" in the crash window
// (components/crash_modal.js + components/hold.js, plan H) on the real
// dashboard at the car's 1024x600 panel, for tests/test_frontend_gestures.py.
// Needs the `playwright` package and its Chromium; without either it prints
// "SKIP: <reason>" and exits 0 so the pytest wrapper can skip.
//
// Nothing leaves the process: every request is answered here, the data
// WebSocket is a stub this script pushes payloads through (what
// web_viewer._crash_sms_summary / _call112_summary send). NOTHING here can
// dial: /api/crash/call112 is answered by this script. Checked:
//  - the red "PRZYTRZYMAJ 2 s – ZADZWOŃ 112" sits in the countdown's right
//    column, >= 15% of the width away from ANULUJ, names the path
//    ("telefon główny" / "telefon w aucie, głośnik"), nothing off-screen;
//  - hold-to-confirm with the mouse AND a real touch (CDP touch events):
//    a press inside the arm delay does nothing, a short press does nothing,
//    a finger that slides off does nothing, a 2 s hold posts ONCE with an
//    empty body (no number), a second hold right after does not post again;
//  - test mode: "TEST – dzwoni na +48...567", never "ZADZWOŃ 112";
//  - the call view: "Łączenie z 112…" / "Rozmowa 01:23", the path, the
//    "przypadkowe" note, "Rozłącz" held 1 s posts to .../hangup, no beep
//    during the call; "Odbierz" when the phone rings posts /api/phone/answer;
//  - during the call a running SMS countdown stays visible and has its own
//    tap "ANULUJ SMS" >= 15% away from "Rozłącz" (posts .../cancel);
//  - a "Rozłącz" that did not take (hangup_pending on, then off while the
//    call is still live) can be held again;
//  - the main phone's call without a microphone uplink: "Dyspozytor może Cię
//    nie słyszeć" and the 112 button back DURING the call (car phone);
//  - after a cancelled SMS ("nic się nie stało") the 112 panel does not take
//    the screen by itself;
//  - the dispatcher panel: position and DMS, fix age, vehicle — font
//    >= 48 px — and the read-out sentence, all on screen; hostile vehicle
//    text never becomes markup;
//  - no path: "Zadzwoń 112 ze swojego telefonu"; "Zamknij" (>= 15% away from
//    the 112 button) posts {event_id} to .../close;
//  - module off (data.call112 null): no 112 button at all;
//  - a passenger's phone (not the kiosk): the panel without any button.
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
const REMOTE_ORIGIN = "http://bcm.invalid";
const W = 1024;
const H = 600;
const EID = "0123456789abcdef".repeat(2);
const SHOTS = process.env.CRASH_SHOT_DIR || "";
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
    window.__ctx = 0;
    window.addEventListener("contextmenu", (e) => { if (!e.defaultPrevented) window.__ctx += 1; });
}

function sms(state, extra) {
    return Object.assign({
        state, event_id: EID, ts: 1763000000, countdown_s: 45, countdown_left_s: 40,
        deadline_ts: 1763000045, recipients_n: 2, phone_ok: true, dry_run: true,
        forced_dry_run_reason: "", results: [], cancel_sms: null, error: "",
        modal: true, cancel_pending: false, send_now_pending: false, can_follow_up: false,
        test: { request: "", error: "", state: null, ts: null, dry_run: null, verified: false,
                last_verified_ts: null },
    }, extra || {});
}

function c112(extra, disp) {
    return Object.assign({
        window: true, event_id: EID, event_ts: 1763000000, window_until_ts: 1763001800,
        state: "idle", path: "", error: "", started_ts: null, active_ts: null, ended_ts: null,
        duration_s: null, unverified: false, hangup_pending: false, offer: "hfp",
        fallback: false, reasons: { hfp: "", car_phone: "not_ready" }, retry_after_s: 0,
        test_mode: false, test_number: "", hold_ms: 2000, arm_delay_ms: 700, incoming: false,
        dispatcher: Object.assign({
            lat: 52.229676, lon: 21.012229, fix_age_s: 4, sats: 9, heading: 270,
            speed_kmh: 72, event_ts: 1763000000,
            vehicle: { label: "Alfa Romeo 156", colour: "czerwona", plate: "WX 12345" },
        }, disp || {}),
    }, extra || {});
}

async function open(browser, touch, origin, posts, errors) {
    const ctx = await browser.newContext({ viewport: { width: W, height: H }, hasTouch: touch });
    const page = await ctx.newPage();
    page.on("pageerror", (e) => errors.push(e.message));
    await ctx.route("**/*", async (route) => {
        const req = route.request();
        const url = new URL(req.url());
        if (url.origin !== origin) return route.abort();
        const p = url.pathname;
        const json = (obj, status) => route.fulfill({ status: status || 200,
                                                      contentType: "application/json",
                                                      body: JSON.stringify(obj) });
        if (p.startsWith("/api/crash/") || p === "/api/phone/answer") {
            posts.push([p, req.method() === "POST" ? (req.postData() || "") : null]);
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
    await page.goto(origin + "/");
    await page.waitForFunction(() => typeof App !== "undefined" && App.getCurrentScreen
                                     && App.getCurrentScreen() === "a1");
    await page.evaluate(() => {
        if (typeof Splash !== "undefined" && Splash.hide) Splash.hide();
        const s = document.getElementById("bcm-splash-overlay");
        if (s) s.remove();
    });
    return { ctx, page };
}

async function push(page, smsP, c112P) {
    await page.evaluate(([a, b]) => window.__push({ crash_sms: a, call112: b }), [smsP, c112P]);
    await page.waitForTimeout(60);
}

async function box(page, sel) {
    return page.evaluate((s) => {
        const el = document.querySelector(s);
        if (!el) return null;
        const b = el.getBoundingClientRect();
        const st = getComputedStyle(el);
        return { x: b.left, y: b.top, w: b.width, h: b.height, r: b.right, b: b.bottom,
                 visible: st.display !== "none" && st.visibility !== "hidden" && b.width > 0,
                 text: el.textContent, font: parseFloat(st.fontSize) };
    }, sel);
}

/** Everything of the window that lies outside the viewport. */
async function offscreen(page) {
    return page.evaluate(() => {
        const m = document.getElementById("crash-modal");
        if (!m) return ["no window"];
        const out = [];
        for (const el of m.querySelectorAll("*")) {
            const b = el.getBoundingClientRect();
            const st = getComputedStyle(el);
            if (b.width === 0 || b.height === 0 || st.display === "none" || st.visibility === "hidden") continue;
            if (b.left < -0.5 || b.top < -0.5 || b.right > innerWidth + 0.5 || b.bottom > innerHeight + 0.5) {
                out.push(`${el.tagName}.${[...el.attributes].map((a) => a.name).join(",")}`);
            }
            if (el.matches("[data-c112-panel] > div") && el.scrollHeight > el.clientHeight + 2
                && !el.hasAttribute("data-c112-say")) {
                out.push(`overflow: ${[...el.attributes].map((a) => a.name).join(",")}`);
            }
        }
        const say = m.querySelector("[data-c112-say]");
        if (say && say.offsetParent && say.scrollHeight > say.clientHeight + 2) out.push("sentence clipped");
        return out;
    });
}

/** Hold at (x, y) for ms — mouse, or a real touch through CDP. */
async function hold(page, cdp, x, y, ms, slideTo) {
    if (cdp) {
        await cdp.send("Input.dispatchTouchEvent", { type: "touchStart", touchPoints: [{ x, y }] });
        if (slideTo) {
            await page.waitForTimeout(300);
            await cdp.send("Input.dispatchTouchEvent", { type: "touchMove",
                touchPoints: [{ x: slideTo[0], y: slideTo[1] }] });
            await page.waitForTimeout(ms - 300);
        } else {
            await page.waitForTimeout(ms);
        }
        await cdp.send("Input.dispatchTouchEvent", { type: "touchEnd", touchPoints: [] });
    } else {
        await page.mouse.move(x, y);
        await page.mouse.down();
        if (slideTo) {
            await page.waitForTimeout(300);
            await page.mouse.move(slideTo[0], slideTo[1], { steps: 4 });
            await page.waitForTimeout(ms - 300);
        } else {
            await page.waitForTimeout(ms);
        }
        await page.mouse.up();
    }
    await page.waitForTimeout(120);
}

const centre = (b) => [b.x + b.w / 2, b.y + b.h / 2];

async function run(browser, touch) {
    const tag = `${W}x${H}${touch ? " touch" : ""}`;
    const posts = [];
    const errors = [];
    const { ctx, page } = await open(browser, touch, ORIGIN, posts, errors);
    const cdp = touch ? await ctx.newCDPSession(page) : null;
    await page.evaluate(() => App.navigateTo("a2"));
    await page.waitForTimeout(150);
    const calls = () => posts.filter(([p]) => p === "/api/crash/call112");

    // ── the 112 button next to the SMS countdown ──────────────────────────
    await push(page, sms("pending"), c112());
    await page.waitForSelector("#crash-modal [data-c112-hold='call']");
    const cancel = await box(page, "#crash-modal [data-crash-action='cancel']");
    let btn = await box(page, "#crash-modal [data-c112-hold='call']");
    if (!btn.visible) fail(`${tag}: no 112 button`);
    if (btn.x - cancel.r < 0.15 * W - 1) fail(`${tag}: 112 only ${btn.x - cancel.r}px from ANULUJ`);
    if (!/PRZYTRZYMAJ 2 s – ZADZWOŃ 112/.test(btn.text) || !/telefon główny/.test(btn.text)) {
        fail(`${tag}: label ${btn.text}`);
    }
    let off = await offscreen(page);
    if (off.length) fail(`${tag}: countdown off-screen: ${off.join(" | ")}`);
    if (SHOTS) await page.screenshot({ path: path.join(SHOTS, `c112-countdown${touch ? "-touch" : ""}.png`) });

    // "Pozycja dla 112": the panel from the moment the window opens, and
    // back to the countdown (which keeps running underneath).
    const pbtn0 = await box(page, "#crash-modal [data-c112-action='panel']");
    if (touch) await page.touchscreen.tap(...centre(pbtn0)); else await page.mouse.click(...centre(pbtn0));
    await page.waitForSelector("#crash-modal [data-crash-mode='panel']");
    const back = await box(page, "#crash-modal [data-c112-action='back']");
    const line0 = await box(page, "#crash-modal [data-c112-line]");
    if (!back.visible || !/SMS do bliskich za 40 s/.test(line0.text)) fail(`${tag}: panel ${line0.text}`);
    if (!await page.evaluate(() => CrashModal._beeping())) fail(`${tag}: the countdown stopped beeping`);
    if (touch) await page.touchscreen.tap(...centre(back)); else await page.mouse.click(...centre(back));
    await page.waitForSelector("#crash-modal [data-crash-action='cancel']");
    if (posts.length) fail(`${tag}: the panel toggle posted ${JSON.stringify(posts)}`);

    // Pressed inside the arm delay (the window just opened): nothing, even
    // when held for longer than 2 s.
    await page.evaluate(() => { const m = document.getElementById("crash-modal"); if (m) m.remove(); CrashModal._close(); });
    await push(page, sms("pending"), c112());
    btn = await box(page, "#crash-modal [data-c112-hold='call']");
    await hold(page, cdp, ...centre(btn), 2400);
    if (calls().length) fail(`${tag}: a press inside the arm delay dialled`);
    // Too short.
    await hold(page, cdp, ...centre(btn), 900);
    if (calls().length) fail(`${tag}: a 0.9 s press dialled`);
    // The finger slides off the button.
    await hold(page, cdp, ...centre(btn), 2400, [btn.x - 200, btn.y + btn.h / 2]);
    if (calls().length) fail(`${tag}: a finger that slid off dialled`);
    // Held 2 s: ONE post, empty body (never a number).
    await hold(page, cdp, ...centre(btn), 2300);
    if (calls().length !== 1 || calls()[0][1] !== "{}") fail(`${tag}: posts ${JSON.stringify(posts)}`);
    // A second hold right away (double trigger): nothing more.
    await hold(page, cdp, ...centre(btn), 2300);
    if (calls().length !== 1) fail(`${tag}: second hold posted again`);
    if (await page.evaluate(() => window.__ctx)) fail(`${tag}: the long-press menu opened`);
    if (await page.evaluate(() => App.getCurrentScreen()) !== "a2") fail(`${tag}: screen changed`);

    // ── the call view (the window covers AA) ──────────────────────────────
    await push(page, sms("pending"), c112({ state: "dialing", path: "hfp", offer: "none",
                                            started_ts: 1763000060, retry_after_s: 58 }));
    await page.waitForSelector("#crash-modal [data-crash-mode='panel']");
    let title = await box(page, "#crash-modal [data-c112-title]");
    if (!/Łączenie z 112/.test(title.text)) fail(`${tag}: ${title.text}`);
    const note = await box(page, "#crash-modal [data-c112-note]");
    if (!/przypadkowe – nie rozłączaj się/.test(note.text)) fail(`${tag}: note ${note.text}`);
    if (await page.evaluate(() => CrashModal._beeping())) fail(`${tag}: beeping during the 112 call`);
    await push(page, sms("pending"), c112({ state: "active", path: "car_phone", offer: "none",
                                            duration_s: 83, retry_after_s: 40 }));
    title = await box(page, "#crash-modal [data-c112-title]");
    const line = await box(page, "#crash-modal [data-c112-line]");
    if (!/Rozmowa 01:23/.test(title.text) || !/telefon w aucie, głośnik/.test(line.text)) {
        fail(`${tag}: ${title.text} / ${line.text}`);
    }
    for (const sel of ["[data-c112-pos]", "[data-c112-dms]", "[data-c112-fix]",
                       "[data-c112-move]", "[data-c112-vehicle]"]) {
        const b = await box(page, "#crash-modal " + sel);
        if (!b.visible || b.font < 48) fail(`${tag}: ${sel} ${b.font}px`);
    }
    const pos = await box(page, "#crash-modal [data-c112-pos]");
    if (!/52,22968 N/.test(pos.text) || !/21,01223 E/.test(pos.text)) fail(`${tag}: pos ${pos.text}`);
    const dms = await box(page, "#crash-modal [data-c112-dms]");
    if (!/52°13'46,8" N/.test(dms.text)) fail(`${tag}: dms ${dms.text}`);
    const say = await box(page, "#crash-modal [data-c112-say]");
    if (!/WX 12345/.test(say.text) || !/52,22968 N/.test(say.text)) fail(`${tag}: say ${say.text}`);
    off = await offscreen(page);
    if (off.length) fail(`${tag}: call view off-screen: ${off.join(" | ")}`);
    if (await box(page, "#crash-modal [data-crash-mode='countdown']")) fail(`${tag}: the countdown under the call view`);
    // The SMS countdown keeps running during the call: shown, and its own
    // tap ANULUJ on the right, far from "Rozłącz" on the left.
    if (!/SMS do bliskich za 40 s/.test(line.text)) fail(`${tag}: no SMS countdown in the call: ${line.text}`);
    const smsCancel = await box(page, "#crash-modal [data-c112-sms-cancel]");
    if (!smsCancel || !smsCancel.visible || !/ANULUJ SMS/.test(smsCancel.text)) {
        fail(`${tag}: no ANULUJ SMS in the call view ${JSON.stringify(smsCancel)}`);
    }
    if (SHOTS) await page.screenshot({ path: path.join(SHOTS, `c112-call${touch ? "-touch" : ""}.png`) });
    // "Rozłącz": held 1 s (after its own arm delay).
    const hang = await box(page, "#crash-modal [data-c112-hold='hangup']");
    if (!hang.visible) fail(`${tag}: no Rozłącz`);
    if (smsCancel.x - hang.r < 0.15 * W - 1) fail(`${tag}: ANULUJ SMS only ${smsCancel.x - hang.r}px from Rozłącz`);
    await page.waitForTimeout(750);
    await hold(page, cdp, ...centre(hang), 400);
    if (posts.some(([p]) => p.endsWith("/hangup"))) fail(`${tag}: a short press hung up`);
    await hold(page, cdp, ...centre(hang), 1300);
    if (posts.filter(([p]) => p === "/api/crash/call112/hangup").length !== 1) {
        fail(`${tag}: hangup posts ${JSON.stringify(posts)}`);
    }
    // The hang-up did not take: pending, then given up while still live —
    // "Rozłącz" can be held again (it must not stay dead).
    await push(page, sms("pending"), c112({ state: "active", path: "car_phone", offer: "none",
                                            duration_s: 85, retry_after_s: 38, hangup_pending: true }));
    await hold(page, cdp, ...centre(hang), 1300);
    if (posts.filter(([p]) => p === "/api/crash/call112/hangup").length !== 1) {
        fail(`${tag}: a fired Rozłącz posted again while pending`);
    }
    await push(page, sms("pending"), c112({ state: "active", path: "car_phone", offer: "none",
                                            duration_s: 96, retry_after_s: 27 }));
    await hold(page, cdp, ...centre(hang), 1300);
    if (posts.filter(([p]) => p === "/api/crash/call112/hangup").length !== 2) {
        fail(`${tag}: Rozłącz stayed dead ${JSON.stringify(posts)}`);
    }
    // ANULUJ SMS during the call: a tap posts the cancel with the event id.
    if (touch) await page.touchscreen.tap(...centre(smsCancel)); else await page.mouse.click(...centre(smsCancel));
    await page.waitForTimeout(120);
    const cancels = posts.filter(([p]) => p === "/api/crash/cancel");
    if (cancels.length !== 1 || JSON.parse(cancels[0][1]).event_id !== EID) {
        fail(`${tag}: ANULUJ SMS posts ${JSON.stringify(cancels)}`);
    }

    // ── the main phone's call has no microphone uplink ────────────────────
    await push(page, null, c112({ state: "active", path: "hfp", uplink: "missing", duration_s: 7,
                                  offer: "car_phone", fallback: true, retry_after_s: 0 }));
    const noteUp = await box(page, "#crash-modal [data-c112-note]");
    if (!/Dyspozytor może Cię nie słyszeć/.test(noteUp.text)) fail(`${tag}: uplink note ${noteUp.text}`);
    const upBtn = await box(page, "#crash-modal [data-crash-mode='panel'] [data-c112-hold='call']");
    if (!upBtn || !upBtn.visible || !/teraz: telefon w aucie/.test(upBtn.text)) {
        fail(`${tag}: no car-phone 112 during the HFP call ${JSON.stringify(upBtn)}`);
    }
    if (!(await box(page, "#crash-modal [data-c112-hold='hangup']")).visible) fail(`${tag}: no Rozłącz`);
    await push(page, null, c112({ state: "active", path: "hfp", uplink: "ok", duration_s: 9,
                                  offer: "none", retry_after_s: 50 }));
    if ((await box(page, "#crash-modal [data-crash-mode='panel'] [data-c112-hold='call']")).visible) {
        fail(`${tag}: 112 button during a call with a working microphone`);
    }

    // ── an SMS result with the 112 column: a tap on the column does not
    //    close it; a tap elsewhere does, and the 112 panel takes over ──
    await push(page, sms("sent", { dry_run: false, results: [{ state: "sent", verified: true }],
                                   countdown_left_s: null }),
               c112({ state: "ended", path: "car_phone", duration_s: 95, retry_after_s: 0 }));
    await page.waitForSelector("#crash-modal [data-crash-result]");
    off = await offscreen(page);
    if (off.length) fail(`${tag}: result+112 off-screen: ${off.join(" | ")}`);
    const col = await box(page, "#crash-modal [data-crash-mode='result'] [data-c112-hold='call']");
    if (!col || !col.visible) fail(`${tag}: no 112 next to the SMS result`);
    if (SHOTS) await page.screenshot({ path: path.join(SHOTS, `c112-result${touch ? "-touch" : ""}.png`) });
    const pbtn = await box(page, "#crash-modal [data-crash-mode='result'] [data-c112-action='panel']");
    if (touch) await page.touchscreen.tap(pbtn.x + pbtn.w / 2, pbtn.y - 4);
    else await page.mouse.click(pbtn.x + pbtn.w / 2, pbtn.y - 4);
    await page.waitForTimeout(100);
    if (!await page.$("#crash-modal [data-crash-result]")) fail(`${tag}: a tap in the 112 column closed the result`);
    if (touch) await page.touchscreen.tap(W / 3, H - 30); else await page.mouse.click(W / 3, H - 30);
    await page.waitForTimeout(150);
    if (!await page.$("#crash-modal [data-crash-mode='panel']")) fail(`${tag}: no panel after the result closed`);
    title = await box(page, "#crash-modal [data-c112-title]");
    if (!/Rozmowa zakończona \(01:35\)/.test(title.text)) fail(`${tag}: ended ${title.text}`);

    // ── the dispatcher calls back: "Odbierz" ──────────────────────────────
    await push(page, null, c112({ state: "ended", path: "car_phone", duration_s: 95,
                                  offer: "hfp", incoming: true, retry_after_s: 20 }));
    const ans = await box(page, "#crash-modal [data-c112-action='answer']");
    if (!ans.visible) fail(`${tag}: no Odbierz`);
    if (touch) await page.touchscreen.tap(...centre(ans)); else await page.mouse.click(...centre(ans));
    await page.waitForTimeout(120);
    if (!posts.some(([p]) => p === "/api/phone/answer")) fail(`${tag}: answer not posted`);

    // ── no path, no SMS window: own phone + Zamknij ───────────────────────
    await push(page, null, c112({ offer: "none", reasons: { hfp: "no_mic", car_phone: "not_ready" } },
                                { lat: null, lon: null, vehicle: { label: "<img src=x onerror=alert(1)>", colour: "", plate: "" } }));
    const none = await box(page, "#crash-modal [data-crash-mode='panel'] [data-c112-none]");
    if (!none.visible || !/Zadzwoń 112 ze swojego telefonu/.test(none.text) || !/brak mikrofonu/.test(none.text)) {
        fail(`${tag}: none ${JSON.stringify(none)}`);
    }
    if (await page.evaluate(() => document.querySelectorAll("#crash-modal img").length)) fail(`${tag}: markup injected`);
    const veh = await box(page, "#crash-modal [data-c112-vehicle]");
    if (!/<img/.test(veh.text)) fail(`${tag}: vehicle text not shown literally`);
    const close = await box(page, "#crash-modal [data-c112-action='close']");
    if (!close.visible) fail(`${tag}: no Zamknij`);

    // ── panel geometry with a path: Zamknij vs 112, test mode label ───────
    await push(page, null, c112({ offer: "car_phone", test_mode: true, test_number: "+48...567" }));
    btn = await box(page, "#crash-modal [data-crash-mode='panel'] [data-c112-hold='call']");
    if (!btn.visible) fail(`${tag}: no 112 button in the panel`);
    if (btn.x - close.r < 0.15 * W - 1) fail(`${tag}: 112 only ${btn.x - close.r}px from Zamknij`);
    if (!/TEST/.test(btn.text) || /ZADZWOŃ 112/.test(btn.text) || !/dzwoni na \+48\.\.\.567/.test(btn.text)
        || !/telefon w aucie, głośnik/.test(btn.text)) fail(`${tag}: test label ${btn.text}`);
    off = await offscreen(page);
    if (off.length) fail(`${tag}: panel off-screen: ${off.join(" | ")}`);
    if (SHOTS) await page.screenshot({ path: path.join(SHOTS, `c112-panel${touch ? "-touch" : ""}.png`) });
    if (touch) await page.touchscreen.tap(...centre(close)); else await page.mouse.click(...centre(close));
    await page.waitForTimeout(120);
    const closes = posts.filter(([p]) => p === "/api/crash/call112/close");
    if (closes.length !== 1 || JSON.parse(closes[0][1]).event_id !== EID) fail(`${tag}: close ${JSON.stringify(closes)}`);
    await push(page, null, null);
    if (await page.$("#crash-modal")) fail(`${tag}: window stayed after the backend closed it`);

    // ── a cancelled SMS: no full-screen 112 panel by itself ───────────────
    await push(page, sms("cancelled", { countdown_left_s: null }), c112());
    await page.waitForSelector("#crash-modal [data-crash-mode='result'] [data-c112-hold='call']");
    await push(page, sms("cancelled", { countdown_left_s: null, modal: false }), c112());
    if (await page.$("#crash-modal")) fail(`${tag}: 112 panel over the screen after ANULUJ`);
    await push(page, null, null);

    // ── module off: the countdown without any 112 button ─────────────────
    await push(page, sms("pending"), null);
    await page.waitForSelector("#crash-modal [data-crash-action='cancel']");
    if (await page.$("#crash-modal [data-c112-hold]")) fail(`${tag}: 112 button without the module`);
    if (calls().length !== 1) fail(`${tag}: extra dials ${JSON.stringify(posts)}`);

    if (errors.length) fail(`${tag}: page errors: ${errors.join("; ")}`);
    await ctx.close();
}

/** A passenger's phone on the car's network: the panel, no buttons. */
async function runRemote(browser) {
    const posts = [];
    const errors = [];
    const { ctx, page } = await open(browser, true, REMOTE_ORIGIN, posts, errors);
    await push(page, null, c112());
    await page.waitForSelector("#crash-modal [data-crash-mode='panel']");
    for (const sel of ["[data-c112-hold='call']", "[data-c112-hold='hangup']",
                       "[data-c112-action='close']", "[data-c112-action='answer']"]) {
        const b = await box(page, "#crash-modal " + sel);
        if (b && b.visible) fail(`remote: ${sel} shown`);
    }
    const note = await box(page, "#crash-modal [data-c112-col] [data-crash-remote]");
    if (!note.visible) fail("remote: no kiosk-only note");
    const pos = await box(page, "#crash-modal [data-c112-pos]");
    if (!/52,22968 N/.test(pos.text)) fail("remote: no position");
    if (posts.length) fail(`remote: posted ${JSON.stringify(posts)}`);
    if (errors.length) fail(`remote: page errors: ${errors.join("; ")}`);
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
        await runRemote(browser);
        process.stdout.write("ok\n");
    } finally {
        await browser.close();
    }
})().catch((e) => {
    process.stderr.write(String(e && e.stack || e) + "\n");
    process.exit(1);
});
