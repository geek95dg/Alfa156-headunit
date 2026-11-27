// Settings screen: the "Komunikaty głosowe" row (data.voice_announce from the
// dashboard payload = web_viewer._voice_summary of voice.status,
// src/audio/voice_announce.py), for tests/test_frontend_gestures.py. Loads the
// real settings.js in a node vm with DOM stubs; plain node + assert, no
// packages. Exits non-zero on failure, prints "ok" on success.
"use strict";
const assert = require("assert");
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const WEB = path.join(__dirname, "..", "..", "src", "dashboard", "web", "js");

let screen = null;
const listeners = {};
const fetches = [];
let nextStatus = 200;
let nextBody = { ok: true };
const slots = { "[data-voice-slot]": { innerHTML: "<untouched>" } };
const voiceMsg = { textContent: "" };
const volLabel = { textContent: "" };
const ctx = {
    console, setTimeout, clearTimeout, Promise, JSON, Math, Date, Object, String, Number,
    isFinite, Array,
    setInterval: () => 0, clearInterval() {},
    fetch: async (url, opts) => {
        fetches.push([url, opts]);
        const status = nextStatus;
        const body = nextBody;
        return { ok: status >= 200 && status < 300, status, json: async () => body };
    },
    App: {
        registerScreen(name, impl) { if (name === "settings") screen = impl; },
        getConfig: () => ({ theme: "modern", language: "pl", speed_unit: "km/h", temp_unit: "C" }),
        t: (key, fallback) => fallback || key,
        navigateTo() {},
    },
    AppBar: { render: () => "" },
    document: {
        getElementById: () => null, createElement: () => ({ style: {} }), body: {},
        querySelector: (sel) => (sel === "[data-voice-msg]" ? voiceMsg
            : sel === "[data-voice-vol-pct]" ? volLabel : slots[sel] || null),
        querySelectorAll: () => [],
        addEventListener: (type, fn) => { (listeners[type] = listeners[type] || []).push(fn); },
        activeElement: null,
    },
};
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(path.join(WEB, "screens", "settings.js"), "utf8"), ctx,
                { filename: "settings.js" });
vm.runInContext("this.__Settings = Settings;", ctx);
const Settings = ctx.__Settings;
const t = (k, d) => d;

const VA = {
    enabled: true, volume: 80, categories: { weather: true, traffic: false, system: true },
    engine: "piper", player: "pw-play", queue: 0, speaking: false, call_active: false,
    last_result: "spoken", last_spoken_ts: 1.8e9, ducking: "eq",
};
const row = (over) => Settings.voiceRowHtml(Object.assign({}, VA, over || {}), t);

(async () => {
    // ── the row ──────────────────────────────────────────────────────────
    let html = row();
    assert.ok(html.includes("Komunikaty głosowe") && html.includes(">record_voice_over<"), html);
    assert.ok(html.includes("Piper (głos polski) · ostatni komunikat odtworzony"), html);
    assert.ok(html.includes('data-voice-enabled="true" aria-pressed="true"'), html);
    assert.ok(html.includes('data-voice-enabled="false" aria-pressed="false"'), html);
    assert.ok(html.includes('data-voice-cat="weather" aria-pressed="true"'), html);
    assert.ok(html.includes('data-voice-cat="traffic" aria-pressed="false"'), html);
    assert.ok(html.includes('data-voice-cat="system" aria-pressed="true"'), html);
    assert.ok(/data-voice-volume type="range" min="10" max="200" step="5" value="80"/.test(html), html);
    assert.ok(html.includes("Powiedz test") && !/data-voice-test disabled/.test(html), html);
    assert.ok(!/\son[a-z]+=/.test(html), "no inline handlers: " + html);
    assert.ok(row({ speaking: true }).includes("mówię…"));
    assert.ok(row({ call_active: true, last_result: "" }).includes("rozmowa — komunikaty czekają"));
    assert.ok(row({ enabled: false, last_result: "" }).includes("wyłączone"));
    // no engine: says what to do, test disabled
    html = row({ engine: "none" });
    assert.ok(html.includes("brak syntezatora mowy — uruchom apply-fixes.sh"), html);
    assert.ok(/data-voice-test disabled/.test(html), html);
    // escaping and type checks
    html = Settings.voiceRowHtml({ enabled: "yes", volume: "<b>", engine: "<img src=x onerror=alert(1)>",
                                   categories: "<svg>", last_result: "<script>" }, t);
    assert.ok(!html.includes("<img") && !html.includes("<svg") && !html.includes("<script")
              && !html.includes("<b>"), html);
    assert.ok(html.includes('data-voice-engine="none"') && /value="80"/.test(html), html);
    assert.strictEqual(Settings.voiceRowHtml(null, t), "");
    assert.strictEqual(Settings.voiceRowHtml(undefined), "");

    // ── screen + update() ─────────────────────────────────────────────────
    assert.ok(screen && typeof screen.render === "function");
    const container = { innerHTML: "" };
    screen.render(container, "modern", {});
    assert.ok(/data-voice-slot style="display:contents"><\/div>/.test(container.innerHTML));
    const before = (listeners.click || []).length;
    screen.render(container, "modern", { voice_announce: VA });
    assert.ok(container.innerHTML.includes("Komunikaty głosowe"));
    assert.strictEqual(listeners.click.length, before + 1);
    screen.render(container, "modern", { voice_announce: VA });
    assert.strictEqual(listeners.click.length, before + 1, "installed once");
    screen.update({ voice_announce: Object.assign({}, VA, { speaking: true }) });
    assert.ok(slots["[data-voice-slot]"].innerHTML.includes("mówię…"));

    // ── clicks send only whitelisted values ───────────────────────────────
    const click = (attrs) => {
        const el = {
            getAttribute: (k) => (k in attrs ? attrs[k] : null),
            hasAttribute: (k) => k in attrs,
        };
        el.closest = () => el;
        listeners.click.forEach((fn) => fn({ target: el }));
    };
    const lastBody = () => JSON.parse(fetches[fetches.length - 1][1].body);
    click({ "data-voice-enabled": "false" });
    await new Promise((r) => setTimeout(r, 0));
    assert.deepStrictEqual(lastBody(), { voice_enabled: false });
    Settings._voice.sentAt = 0;
    click({ "data-voice-cat": "traffic", "aria-pressed": "false" });
    await new Promise((r) => setTimeout(r, 0));
    assert.deepStrictEqual(lastBody(), { voice_cat_traffic: true });
    Settings._voice.sentAt = 0;
    const n = fetches.length;
    click({ "data-voice-cat": "<script>" });
    click({ "data-voice-enabled": "maybe" });
    assert.strictEqual(fetches.length, n, "unknown values are never sent");
    // the slider
    listeners.change.forEach((fn) => fn({ target: { value: "45", hasAttribute: (k) => k === "data-voice-volume" } }));
    await new Promise((r) => setTimeout(r, 0));
    assert.deepStrictEqual(lastBody(), { voice_volume: 45 });
    listeners.change.forEach((fn) => fn({ target: { value: "5", hasAttribute: (k) => k === "data-voice-volume" } }));
    assert.deepStrictEqual(lastBody(), { voice_volume: 45 }, "out of range is not sent");
    // the test button: POST without a body, messages per answer
    nextStatus = 202;
    click({ "data-voice-test": "" });
    await new Promise((r) => setTimeout(r, 0));
    assert.strictEqual(fetches[fetches.length - 1][0], "/api/voice/test");
    assert.ok(!fetches[fetches.length - 1][1].body, "the test sends no text");
    await new Promise((r) => setTimeout(r, 0));
    assert.strictEqual(voiceMsg.textContent, "mówię test…");
    Settings._voice.testAt = 0;
    nextStatus = 409; nextBody = { ok: false, error: "call_active" };
    await Settings.voiceTest();
    assert.strictEqual(voiceMsg.textContent, "trwa rozmowa — test po jej zakończeniu");
    Settings._voice.testAt = 0;
    nextStatus = 403; nextBody = { ok: false, error: "forbidden" };
    await Settings.voiceTest();
    assert.strictEqual(voiceMsg.textContent, "test tylko z ekranu w aucie");

    // Azure Neural: status names the voice; picker only with a key; the
    // voice attribute is whitelisted (an unknown one is never drawn).
    let az = row({ engine: "azure", azure: "ok", azure_voice: "pl-PL-ZofiaNeural" });
    assert.ok(/Azure · Zofia/.test(az), "status shows the Azure voice");
    assert.ok(/data-voice-azure="pl-PL-AgnieszkaNeural"/.test(az), "picker drawn");
    assert.ok(/data-voice-azure="pl-PL-ZofiaNeural" aria-pressed="true"/.test(az), "current voice pressed");
    az = row({ engine: "piper", azure: "no_key", azure_voice: "pl-PL-AgnieszkaNeural" });
    assert.ok(!/data-voice-azure=/.test(az), "no picker without a key");
    assert.ok(/BCM_AZURE_TTS_KEY/.test(az), "tells where the key goes");
    az = row({ engine: "piper", azure: "auth", azure_voice: "pl-PL-AgnieszkaNeural" });
    assert.ok(/401\/403/.test(az));
    console.log("ok");
})().catch((e) => { console.error(e); process.exit(1); });
