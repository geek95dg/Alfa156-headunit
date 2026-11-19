// Settings screen: the "Jasność ekranu" row (data.auto_brightness from the
// dashboard payload = web_viewer._auto_brightness_summary of
// display.brightness_state, src/power/brightness.py) and the dimming
// overlay component (components/dim_overlay.js), for
// tests/test_frontend_gestures.py. Loads the real files in a node vm with DOM
// stubs; plain node + assert, no packages. Exits non-zero on failure, prints
// "ok" on success.
"use strict";
const assert = require("assert");
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const WEB = path.join(__dirname, "..", "..", "src", "dashboard", "web", "js");

let screen = null;
const listeners = {};
const fetches = [];
const slots = { "[data-brightness-slot]": { innerHTML: "<untouched>" },
                "[data-cabin-watch-slot]": { innerHTML: "<untouched>" },
                "[data-parking-guard-slot]": { innerHTML: "<untouched>" },
                "[data-car-phone-agent-slot]": { innerHTML: "<untouched>" },
                "[data-car-phone-slot]": { innerHTML: "<untouched>" },
                "[data-tether-slot]": { innerHTML: "<untouched>" },
                "[data-gps-slot]": { innerHTML: "<untouched>" } };
const brightMsg = { textContent: "" };
const pctLabel = { textContent: "" };
const ctx = {
    console, setTimeout, clearTimeout, Promise, JSON, Math, Date, Object, String, Number,
    isFinite, Array,
    setInterval: () => 0, clearInterval() {},
    fetch: async (url, opts) => {
        fetches.push([url, opts]);
        return { ok: true, status: 200, json: async () => ({ ok: true }) };
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
        querySelector: (sel) => (sel === "[data-bright-msg]" ? brightMsg
            : sel === "[data-bright-pct]" ? pctLabel : slots[sel] || null),
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

const AUTO = {
    mode: "auto", effective: "auto", source: "phone", lux: 120.0, adc: null, pct: 47,
    target_pct: 47, manual_pct: 70, hold_left_min: null, min_pct: 15, max_pct: 100,
    backend: "css", active: "css", probe: "idle", reason: "",
};
const row = (over) => Settings.brightnessRowHtml(Object.assign({}, AUTO, over || {}), t);
const status = (over) => Settings.brightnessStatusText(Object.assign({}, AUTO, over || {}), t);

// ── the row on its own ───────────────────────────────────────────────────
let html = row();
assert.ok(html.includes("Jasność ekranu") && html.includes(">brightness_6<"), html);
assert.ok(html.includes("Auto (telefon) · 120 lx · 47%"), html);
assert.ok(html.includes('data-bright-effective="auto"'), html);
assert.ok(html.includes('data-bright-mode="auto" aria-pressed="true"'), html);
assert.ok(html.includes('data-bright-mode="manual" aria-pressed="false"'), html);
assert.ok(html.includes("Ściemnianie") && html.includes("Programowe") && html.includes("Sprzętowe (DDC/CI)"), html);
assert.ok(html.includes('data-bright-backend="css" aria-pressed="true"'), html);
assert.ok(html.includes('data-bright-backend="ddc" aria-pressed="false"'), html);
assert.ok(/data-bright-slider type="range" min="15" max="100" step="1" value="47"/.test(html), html);
assert.ok(!/class="[^"]*\b(flex|gap-|px-|py-|text-\[)/.test(html.replace(/material-symbols-outlined/g, "")),
          "only inline styles: " + html);
assert.ok(!/\son[a-z]+=/.test(html), "no inline handlers: " + html);
// status per effective mode — and the current lux in every one of them
assert.strictEqual(status({ source: "arduino", lux: null }), "Auto (czujnik Arduino) · 47%");
assert.strictEqual(status({ effective: "hold", hold_left_min: 8, pct: 70 }),
                   "Ręczna — wraca do auto za 8 min · 120 lx · 70%");
assert.strictEqual(status({ effective: "manual", mode: "manual", lux: 3.25 }), "Ręczna · 3.3 lx · 47%");
assert.strictEqual(status({ effective: "stale", lux: null }),
                   "czujnik światła nie odpowiada — trzymam ostatnią jasność · 47%");
assert.strictEqual(status({ effective: "no_source", lux: null, pct: 70 }),
                   "brak czujnika światła — jasność ręczna · 70%");
html = row({ mode: "manual", effective: "manual" });
assert.ok(html.includes('data-bright-mode="manual" aria-pressed="true"'), html);
// the hardware switch: probing / works / why not
html = row({ backend: "ddc", probe: "probing" });
assert.ok(html.includes('data-bright-backend="ddc" aria-pressed="true"') && html.includes("sprawdzam monitor"), html);
assert.ok(row({ backend: "ddc", active: "ddc", probe: "ok" }).includes("Sprzętowe: DDC/CI działa"));
const WHY = {
    no_ddcutil: "brak programu ddcutil (sudo apt install ddcutil)",
    no_i2c: "brak /dev/i2c-* (sudo modprobe i2c-dev)",
    no_display: "monitor nie odpowiada przez DDC/CI",
    no_vcp: "monitor nie podaje jasności (VCP 10)",
    timeout: "ddcutil nie odpowiedział na czas",
    write_failed: "monitor przestał przyjmować jasność",
};
for (const [reason, text] of Object.entries(WHY)) {
    html = row({ backend: "ddc", probe: "failed", reason });
    assert.ok(html.includes("Sprzętowe niedostępne: " + text + " — używam programowego"), reason + ": " + html);
}
html = row({ backend: "xrandr", probe: "failed", reason: "xrandr_config" });
assert.ok(html.includes("xrandr niedostępny: zła konfiguracja") && !html.includes('aria-pressed="true">Programowe'), html);
assert.ok(row({ backend: "xrandr", active: "xrandr", probe: "ok" }).includes("xrandr (z config/local.yaml)"));
assert.ok(row({ backend: "auto" }).includes('data-bright-backend="css" aria-pressed="true"'));
// type checks and escaping
html = Settings.brightnessRowHtml({ effective: "<img src=x onerror=alert(1)>", pct: "47", lux: "9",
                                    min_pct: "<b>", backend: "<script>", probe: "failed",
                                    reason: "<svg onload=alert(1)>" }, t);
assert.ok(!html.includes("<img") && !html.includes("<script") && !html.includes("<svg") && !html.includes("<b>"), html);
assert.ok(html.includes('data-bright-effective="no_source"') && html.includes("nieznany błąd"), html);
assert.ok(/min="5" max="100" step="1" value="100"/.test(html), html);
assert.ok(!html.includes(" lx"), "lux only when it is a number");
// no payload = module not running: no row
assert.strictEqual(Settings.brightnessRowHtml(undefined, t), "");
assert.strictEqual(Settings.brightnessRowHtml(null), "");
assert.strictEqual(Settings.brightnessRowHtml("auto", t), "");
assert.strictEqual(Settings.brightnessStatusText(null, t), "");

// ── the whole screen and update() ────────────────────────────────────────
assert.ok(screen && typeof screen.render === "function");
const container = { innerHTML: "" };
screen.render(container, "modern", { aa_status: "running" });
assert.ok(/data-brightness-slot style="display:contents"><\/div>/.test(container.innerHTML));
assert.ok(!listeners.change, "no listener without the row (other rows count theirs)");
const clicks = (listeners.click || []).length;              // the "Postój" row's own
screen.render(container, "modern", { auto_brightness: AUTO });
assert.ok(container.innerHTML.includes('data-bright-effective="auto"'), "row rendered");
assert.ok(listeners.click.length === clicks + 1 && listeners.change.length === 1
          && listeners.input.length === 1);
screen.render(container, "modern", { auto_brightness: AUTO });
assert.ok(listeners.click.length === clicks + 1 && listeners.change.length === 1, "installed once");
const slot = slots["[data-brightness-slot]"];
// same key, new numbers: only the text and the slider position change
const statusNode = { textContent: "" };
const slider = { value: "47" };
const label = { textContent: "" };
slot.querySelector = (sel) => ({ "[data-bright-status]": statusNode, "[data-bright-slider]": slider,
                                 "[data-bright-pct]": label })[sel] || null;
screen.update({ auto_brightness: Object.assign({}, AUTO, { lux: 300, pct: 55, target_pct: 55 }) });
assert.strictEqual(slot.innerHTML, "<untouched>", "no redraw for new numbers");
assert.strictEqual(statusNode.textContent, "Auto (telefon) · 300 lx · 55%");
assert.strictEqual(slider.value, "55");
assert.strictEqual(label.textContent, "55%");
// not under the finger: neither the slider nor a redraw
Settings._bright.down = true;
screen.update({ auto_brightness: Object.assign({}, AUTO, { pct: 60 }) });
assert.strictEqual(slider.value, "55", "slider untouched while dragged");
screen.update({ auto_brightness: Object.assign({}, AUTO, { backend: "ddc", probe: "probing" }) });
assert.strictEqual(slot.innerHTML, "<untouched>", "no redraw while dragged");
Settings._bright.down = false;
Settings._bright.inputAt = 0;
screen.update({ auto_brightness: Object.assign({}, AUTO, { backend: "ddc", probe: "probing" }) });
assert.ok(slot.innerHTML.includes("sprawdzam monitor"), slot.innerHTML);
assert.strictEqual(slots["[data-cabin-watch-slot]"].innerHTML, "<untouched>");
screen.update({ auto_brightness: null });
assert.strictEqual(slot.innerHTML, "", "module gone: row gone");
screen.update(undefined);                                    // never throws

// ── the controls: delegated listeners, whitelisted bodies only ──────────
(async () => {
    const el = (attrs) => ({
        getAttribute: (a) => (Object.prototype.hasOwnProperty.call(attrs, a) ? attrs[a] : null),
        hasAttribute: (a) => Object.prototype.hasOwnProperty.call(attrs, a),
        // like Element.closest: only when the selector names one of its attributes
        closest(sel) { return Object.keys(attrs).some((a) => sel.includes("[" + a)) ? this : null; },
    });
    const click = (attrs) => listeners.click.forEach((fn) => fn({ target: el(attrs) }));
    const bodies = () => fetches.filter(([url]) => url === "/api/config")
        .map(([, o]) => JSON.parse(o.body));
    const settle = () => new Promise((r) => setTimeout(r, 0));
    click({ "data-bright-backend": "ddc" });
    await settle();
    assert.deepStrictEqual(bodies(), [{ brightness_backend: "ddc" }]);
    click({ "data-bright-backend": "css" });                 // double tap: swallowed
    await settle();
    assert.strictEqual(bodies().length, 1);
    Settings._bright.sentAt = 0;
    click({ "data-bright-backend": "xrandr" });               // not offered: nothing
    click({ "data-bright-mode": "night" });
    click({ "data-other": "x" });
    await settle();
    assert.strictEqual(bodies().length, 1);
    click({ "data-bright-mode": "manual" });
    await settle();
    assert.deepStrictEqual(bodies()[1], { brightness_mode: "manual" });
    // the slider: input only moves the label, change posts the value
    const sl = el({ "data-bright-slider": "" });
    sl.value = "42";
    listeners.input.forEach((fn) => fn({ target: sl }));
    assert.strictEqual(pctLabel.textContent, "42%");
    assert.ok(Settings.brightDragging(), "dragging after an input event");
    assert.strictEqual(bodies().length, 2);
    listeners.change.forEach((fn) => fn({ target: sl }));
    await settle();
    assert.deepStrictEqual(bodies()[2], { brightness: 42 });
    sl.value = "abc";
    listeners.change.forEach((fn) => fn({ target: sl }));
    await settle();
    assert.strictEqual(bodies().length, 3, "no NaN posted");
    // pointer state
    listeners.pointerdown.forEach((fn) => fn({ target: sl }));
    assert.strictEqual(Settings._bright.down, true);
    listeners.pointerup.forEach((fn) => fn({ target: sl }));
    assert.strictEqual(Settings._bright.down, false);
    // a refused save is said in the row
    ctx.fetch = async (url, opts) => { fetches.push([url, opts]); return { ok: false, status: 400, json: async () => ({}) }; };
    Settings._bright.sentAt = 0;
    click({ "data-bright-mode": "auto" });
    await settle(); await settle();
    assert.strictEqual(brightMsg.textContent, "nie udało się zapisać");

    // ── components/dim_overlay.js on its own ─────────────────────────────
    const D = require(path.join(WEB, "components", "dim_overlay.js"));
    assert.strictEqual(D.Z_INDEX, 190);
    assert.strictEqual(D.levelOf(null), 0);
    assert.strictEqual(D.levelOf({ level: 0.5 }), 0.5);
    assert.strictEqual(D.levelOf({ level: 0.0005 }), 0);
    assert.strictEqual(D.levelOf({ level: 1 }), 0.9);
    assert.strictEqual(D.levelOf({ level: "0.5" }), 0);
    assert.strictEqual(D.levelOf({ level: NaN }), 0);
    assert.strictEqual(D.levelOf({ level: Infinity }), 0);
    D.sync({ level: 0.5 });                                    // no document in node: no-op
    console.log("ok");
})().catch((e) => { console.error(e); process.exit(1); });
