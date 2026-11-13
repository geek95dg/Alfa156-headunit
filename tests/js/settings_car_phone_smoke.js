// Settings screen: the "Telefon w aucie" row (data.car_phone from the
// dashboard payload = web_viewer._car_phone_summary of net.car_phone,
// src/network/car_phone.py), for tests/test_frontend_gestures.py. Loads the
// real screens/settings.js in a node vm with DOM stubs; plain node + assert,
// no packages. Exits non-zero on failure, prints "ok" on success.
"use strict";
const assert = require("assert");
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const WEB = path.join(__dirname, "..", "..", "src", "dashboard", "web", "js");

let screen = null;
const fetches = [];
const slots = { "[data-car-phone-slot]": { innerHTML: "<untouched>" },
                "[data-tether-slot]": { innerHTML: "<untouched>" },
                "[data-gps-slot]": { innerHTML: "<untouched>" } };
const ctx = {
    console, setTimeout, clearTimeout, Promise, JSON, Math, Date, Object, String, Number,
    isFinite,
    setInterval: () => 0, clearInterval() {},
    fetch: async (url, opts) => {
        fetches.push([url, opts && opts.method]);
        return { ok: true, json: async () => ({}) };
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
        querySelector: (sel) => slots[sel] || null,
    },
};
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(path.join(WEB, "screens", "settings.js"), "utf8"), ctx,
                { filename: "settings.js" });
vm.runInContext("this.__Settings = Settings;", ctx);
const Settings = ctx.__Settings;
const t = (k, d) => d;

const FULL = {
    state: "connected", hint: "", adb: "device", serial: "1a…4d", ip: "192.168.42.100",
    prefix: 24, gateway: "192.168.42.129", iface: "usb0", gps_forward: true,
    battery_pct: 78, temp_c: 31.2, charging: true, full: false, plugged: "usb",
    health: "good", overridden: false, hotspot_active: true, hotspot_clients: 2,
    heat: null, error: "",
};

// ── the row on its own ───────────────────────────────────────────────────
let html = Settings.carPhoneRowHtml(FULL, t);
assert.ok(html.includes("Telefon w aucie"), html);
assert.ok(html.includes("phone_android"), html);
assert.ok(html.includes("połączono"), html);
assert.ok(html.includes("192.168.42.100") && html.includes("(usb0)"), html);
assert.ok(html.includes("78% ⚡") && html.includes("31 °C"), html);
assert.ok(html.includes("GPS") && html.includes("hotspot (2)"), html);
assert.ok(html.includes('data-car-phone-state="connected"'), html);
assert.ok(!html.includes("data-car-phone-retry"), "no retry while connected");
assert.ok(!/class="[^"]*\b(flex|gap-|px-|py-|text-\[)/.test(html.replace(/material-symbols-outlined/g, "")),
          "only inline styles in the new row: " + html);

// Every state has a human label; IP only while connected; retry where it helps.
const LABELS = {
    disabled: "wyłączony", no_adb: "brak adb", adb_error: "błąd adb — ponowię",
    no_device: "brak telefonu na USB", unauthorized: "zezwól na debugowanie USB",
    tethering: "włączam tethering USB…", failed: "błąd — ponowię",
};
for (const [state, label] of Object.entries(LABELS)) {
    html = Settings.carPhoneRowHtml(Object.assign({}, FULL, { state }), t);
    assert.ok(html.includes(label), state + ": " + html);
    assert.ok(!html.includes("192.168.42.100"), "no IP unless connected: " + html);
    assert.strictEqual(html.includes("data-car-phone-retry"),
                       state === "failed" || state === "adb_error", state + ": " + html);
}

// Hints: what to do, never the raw adb/nmcli error.
const HINTS = {
    authorize: "Zawsze zezwalaj", pin_serial: "network.car_phone.serial",
    tether_blocked: "nie włącza tetheringu USB", aa_usb_probe: "BCM_AA_USB=0",
    install_adb: "sudo apt install adb",
};
for (const [hint, text] of Object.entries(HINTS)) {
    html = Settings.carPhoneRowHtml({ state: "failed", hint, error: "Error: raw adb text" }, t);
    assert.ok(html.includes(text), hint + ": " + html);
    assert.ok(!html.includes("raw adb text"), html);
}
assert.ok(!Settings.carPhoneRowHtml({ state: "failed", hint: "<b>x</b>" }, t).includes("<b>"));

// Heat colours by the module's own level, not a threshold in the browser.
html = Settings.carPhoneRowHtml(Object.assign({}, FULL, { temp_c: 47, heat: "warning" }), t);
assert.ok(html.includes("color:#dc2626\">78% ⚡ · 47 °C"), html);
html = Settings.carPhoneRowHtml(Object.assign({}, FULL, { temp_c: 47, heat: null }), t);
assert.ok(!html.includes("color:#dc2626\">78%"), html);

// Hotspot off / unknown; battery full; numbers checked for type.
html = Settings.carPhoneRowHtml(Object.assign({}, FULL, { hotspot_active: false, charging: false,
                                                          full: true }), t);
assert.ok(html.includes("hotspot wył.") && html.includes("78% ✓"), html);
html = Settings.carPhoneRowHtml(Object.assign({}, FULL, { hotspot_active: null,
    battery_pct: "78<img>", temp_c: "31", gps_forward: "true", hotspot_clients: "2" }), t);
assert.ok(!html.includes("hotspot") && !html.includes("%") && !html.includes("°C"), html);
assert.ok(!html.includes(" GPS"), html);

// No payload = module not running (production): no row at all.
assert.strictEqual(Settings.carPhoneRowHtml(undefined, t), "");
assert.strictEqual(Settings.carPhoneRowHtml(null), "");
assert.strictEqual(Settings.carPhoneRowHtml("connected", t), "");

// Everything from the device is escaped.
html = Settings.carPhoneRowHtml({ state: "<img src=x onerror=alert(1)>" }, t);
assert.ok(!html.includes("<img"), html);
assert.ok(html.includes("&lt;img src=x onerror=alert(1)&gt;"), html);
html = Settings.carPhoneRowHtml(Object.assign({}, FULL, { ip: "<b>1.2.3.4</b>",
                                                          iface: '"><script>x</script>' }), t);
assert.ok(!html.includes("<b>") && !html.includes("<script>"), html);
assert.ok(html.includes("&lt;b&gt;1.2.3.4&lt;/b&gt;"), html);

// ── the whole screen shows it ────────────────────────────────────────────
assert.ok(screen && typeof screen.render === "function");
const container = { innerHTML: "" };
screen.render(container, "modern", { aa_status: "connected", car_phone: FULL });
assert.ok(container.innerHTML.includes('data-car-phone-state="connected"'), "row rendered");
assert.ok(container.innerHTML.includes("data-car-phone-slot"));
for (const data of [{ aa_status: "running" }, { aa_status: "running", car_phone: null }]) {
    screen.render(container, "modern", data);
    assert.ok(!container.innerHTML.includes("data-car-phone-state"), container.innerHTML);
    assert.ok(/data-car-phone-slot style="display:contents"><\/div>/.test(container.innerHTML));
}

// ── update(): only the row, only on change ──────────────────────────────
const slot = slots["[data-car-phone-slot]"];
screen.render(container, "modern", { car_phone: { state: "tethering" } });
const rendered = container.innerHTML;
screen.update({ car_phone: { state: "tethering" } });
assert.strictEqual(slot.innerHTML, "<untouched>", "same payload: nothing redrawn");
screen.update({ car_phone: FULL });
assert.ok(slot.innerHTML.includes('data-car-phone-state="connected"'), slot.innerHTML);
assert.strictEqual(container.innerHTML, rendered, "the screen itself is not re-rendered");
screen.update({ car_phone: null });
assert.strictEqual(slot.innerHTML, "");
screen.update(undefined);                                   // never throws

// ── "Ponów": one POST, double taps swallowed ────────────────────────────
(async () => {
    await Settings.carPhoneRetry();
    await Settings.carPhoneRetry();
    const retries = fetches.filter(([url]) => url === "/api/car_phone/retry");
    assert.deepStrictEqual(retries, [["/api/car_phone/retry", "POST"]]);
    console.log("ok");
})().catch((e) => { console.error(e); process.exit(1); });
