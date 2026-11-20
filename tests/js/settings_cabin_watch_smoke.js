// Settings screen: the "Czuwanie kabiny" row (data.cabin_watch from the
// dashboard payload = web_viewer._cabin_watch_summary of park.cabin_state,
// src/safety/cabin_watch.py), for tests/test_frontend_gestures.py. Loads the
// real screens/settings.js in a node vm with DOM stubs; plain node + assert,
// no packages. Exits non-zero on failure, prints "ok" on success.
"use strict";
const assert = require("assert");
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const WEB = path.join(__dirname, "..", "..", "src", "dashboard", "web", "js");

let screen = null;
const listeners = {};
const slots = { "[data-cabin-watch-slot]": { innerHTML: "<untouched>" },
                "[data-parking-guard-slot]": { innerHTML: "<untouched>" },
                "[data-car-phone-agent-slot]": { innerHTML: "<untouched>" },
                "[data-car-phone-slot]": { innerHTML: "<untouched>" },
                "[data-tether-slot]": { innerHTML: "<untouched>" },
                "[data-gps-slot]": { innerHTML: "<untouched>" } };
const ctx = {
    console, setTimeout, clearTimeout, Promise, JSON, Math, Date, Object, String, Number,
    isFinite, Array,
    setInterval: () => 0, clearInterval() {},
    fetch: async () => ({ ok: true, status: 200, json: async () => ({}) }),
    App: {
        registerScreen(name, impl) { if (name === "settings") screen = impl; },
        getConfig: () => ({ theme: "modern", language: "pl", speed_unit: "km/h", temp_unit: "C" }),
        t: (key, fallback) => fallback || key,
        navigateTo() {},
    },
    AppBar: { render: () => "" },
    document: {
        getElementById: () => null, createElement: () => ({ style: {} }), body: {},
        querySelector: (sel) => slots[sel] || null,
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

const TS = new Date(2026, 10, 19, 3, 12, 0).getTime() / 1000;
const WATCHING = {
    state: "watching", camera: "ok", light_sensor: "ok", lux: 0.5, pillow: true,
    log_only: false, entry_until: null, photos_n: 3, photos_mb: 2.14, events_today: 1,
    last_event: { ts: TS, reasons: ["light", "shake"], weak: false, photos: 3, outcome: "alarm",
                  verdict: "change", changed_pct: 12.3, ref: "ref", camera: "ok" },
    error: "",
};
const row = (over) => Settings.cabinWatchRowHtml(Object.assign({}, WATCHING, over || {}), t);

// ── the row on its own ───────────────────────────────────────────────────
let html = row();
assert.ok(html.includes("Czuwanie kabiny") && html.includes(">photo_camera<"), html);
assert.ok(html.includes("czuwa") && html.includes("kamera gotowa"), html);
assert.ok(html.includes("zdjęcia w telefonie: 3 (2.1 MB)") && html.includes("dziś: 1"), html);
assert.ok(html.includes('data-cabin-state="watching"'), html);
assert.ok(html.includes("Ostatnie zdarzenie: 19.11 03:12 — światło + ruch, zdjęcia 3, "
                       + "zmiana w kabinie 12.3%, alarm — SMS do numerów alarmu"), html);
assert.ok(!/class="[^"]*\b(flex|gap-|px-|py-|text-\[)/.test(html.replace(/material-symbols-outlined/g, "")),
          "only inline styles: " + html);
assert.ok(!html.includes("<button") && !html.includes("onclick"), "read-only row: " + html);
// every state has its label
const LABELS = {
    unknown: "brak danych z telefonu", off: "wyłączone w telefonie",
    idle: "czeka na uzbrojenie postoju", watching: "czuwa", pending: "ruch w kabinie",
};
for (const [state, label] of Object.entries(LABELS)) {
    assert.ok(row({ state }).includes(label), state);
}
// pending: when the alarm goes out without the owner's proof
html = row({ state: "pending", entry_until: TS + 60,
             last_event: Object.assign({}, WATCHING.last_event, { outcome: "pending" }) });
assert.ok(html.includes("alarm bez rozbrojenia o 03:13") && html.includes("czeka na dowód właściciela"), html);
assert.ok(html.includes("#dc2626"), html);
// the camera layer off — and why; only while watching
for (const [cam, text] of [["cold", "za zimno"], ["hot", "za gorąco"], ["charging_hot", "ładowanie"],
                           ["low_battery", "poniżej 30%"], ["light_mode", "oszczędzanie"],
                           ["no_front_camera", "Aparat"], ["no_temp", "temperatury"]]) {
    assert.ok(row({ camera: cam }).includes(text), cam);
}
assert.ok(!row({ state: "idle", camera: "cold" }).includes("za zimno"));
// outcomes and verdicts
html = row({ last_event: Object.assign({}, WATCHING.last_event, { outcome: "owner", photos: 0,
                                                                  verdict: null }) });
assert.ok(html.includes("właściciel — zdjęcia usunięte") && html.includes("zdjęcia 0"), html);
html = row({ last_event: Object.assign({}, WATCHING.last_event, { outcome: "logged",
                                                                  verdict: "skipped" }) });
assert.ok(html.includes("tylko log") && html.includes("bez analizy"), html);
html = row({ last_event: Object.assign({}, WATCHING.last_event, { verdict: "dark", reasons: ["door"],
                                                                  camera: "cold" }) });
assert.ok(html.includes("drzwi") && html.includes("zdjęcia ciemne") && html.includes("za zimno"), html);
assert.ok(!row({ last_event: Object.assign({}, WATCHING.last_event, { outcome: "<img>" }) })
    .includes("Ostatnie zdarzenie"));
// hints: what to do
assert.ok(row({ pillow: false }).includes("pkg install python-pillow"));
assert.ok(row({ light_sensor: "none" }).includes("brak czujnika światła"));
assert.ok(row({ state: "unknown", error: "agent_outdated" }).includes("≥ 1.3.0"));
assert.ok(row({ state: "unknown", error: "no_agent" }).includes("Agent w telefonie"));
assert.ok(row({ log_only: true }).includes("tylko log, bez SMS"));
// type checks and escaping
html = row({ photos_n: "3", photos_mb: "2", events_today: "x" });
assert.ok(!html.includes("zdjęcia w telefonie") && !html.includes("dziś"), html);
html = Settings.cabinWatchRowHtml({ state: "<img src=x onerror=alert(1)>", error: "<b>x</b>" }, t);
assert.ok(!html.includes("<img") && !html.includes("<b>") && html.includes('data-cabin-state="unknown"'), html);
html = row({ last_event: Object.assign({}, WATCHING.last_event, { reasons: ["<script>", "light"] }) });
assert.ok(!html.includes("<script>") && html.includes("światło"), html);
// no payload = module not running: no row
assert.strictEqual(Settings.cabinWatchRowHtml(undefined, t), "");
assert.strictEqual(Settings.cabinWatchRowHtml(null), "");
assert.strictEqual(Settings.cabinWatchRowHtml("watching", t), "");
// the park row knows the cabin alarm as its last event
html = Settings.parkingGuardRowHtml({ state: "alarm", last_event: { kind: "cabin", ts: TS, value: 3,
                                                                    logged_only: false } }, t);
assert.ok(html.includes("Ostatnie zdarzenie: ruch w kabinie 19.11 03:12"), html);

// ── the whole screen and update() ────────────────────────────────────────
assert.ok(screen && typeof screen.render === "function");
const container = { innerHTML: "" };
screen.render(container, "modern", { cabin_watch: WATCHING });
assert.ok(container.innerHTML.includes('data-cabin-state="watching"'), "row rendered");
screen.render(container, "modern", { aa_status: "running" });
assert.ok(/data-cabin-watch-slot style="display:contents"><\/div>/.test(container.innerHTML));
const slot = slots["[data-cabin-watch-slot]"];
screen.render(container, "modern", { cabin_watch: WATCHING });
screen.update({ cabin_watch: WATCHING });
assert.strictEqual(slot.innerHTML, "<untouched>", "same payload: nothing redrawn");
screen.update({ cabin_watch: Object.assign({}, WATCHING, { state: "pending", entry_until: TS }) });
assert.ok(slot.innerHTML.includes('data-cabin-state="pending"'), slot.innerHTML);
assert.strictEqual(slots["[data-parking-guard-slot]"].innerHTML, "<untouched>");
screen.update({ cabin_watch: null });
assert.strictEqual(slot.innerHTML, "", "module gone: row gone");
screen.update(undefined);                                    // never throws
console.log("ok");
