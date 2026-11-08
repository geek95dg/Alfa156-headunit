// Settings screen: the "Internet z telefonu" row (data.phone_tether from the
// dashboard payload, src/network/phone_tether.py), for
// tests/test_frontend_gestures.py. Loads the real screens/settings.js in a
// node vm with DOM stubs; plain node + assert, no packages. Exits non-zero on
// failure, prints "ok" on success.
"use strict";
const assert = require("assert");
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const WEB = path.join(__dirname, "..", "..", "src", "dashboard", "web", "js");

let screen = null;
const fetches = [];
const slot = { innerHTML: "<untouched>" };
let slotPresent = true;
const ctx = {
    console, setTimeout, clearTimeout, Promise, JSON, Math, Date, Object, String,
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
        querySelector: (sel) => (sel === "[data-tether-slot]" && slotPresent ? slot : null),
    },
};
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(path.join(WEB, "screens", "settings.js"), "utf8"), ctx,
                { filename: "settings.js" });
vm.runInContext("this.__Settings = Settings;", ctx);
const Settings = ctx.__Settings;
const t = (k, d) => d;

// ── the row on its own ───────────────────────────────────────────────────
let html = Settings.tetherRowHtml({ state: "connected", ip: "192.168.44.23", iface: "bnep0" }, t);
assert.ok(html.includes("Internet z telefonu"), html);
assert.ok(html.includes("połączono"), html);
assert.ok(html.includes("192.168.44.23"), html);
assert.ok(html.includes("(bnep0)"), html);
assert.ok(html.includes('data-tether-state="connected"'), html);
assert.ok(!/class="[^"]*\b(flex|gap-|px-|py-|text-\[)/.test(html.replace(/material-symbols-outlined/g, "")),
          "only inline styles in the new row: " + html);

// Every state has a human label; IP only while connected.
const LABELS = {
    disabled: "wyłączony", unavailable: "brak NetworkManagera", waiting_phone: "czeka na telefon",
    no_nap: "włącz tethering Bluetooth w telefonie", connecting: "łączenie…",
    failed: "błąd — ponowię",
};
for (const [state, label] of Object.entries(LABELS)) {
    html = Settings.tetherRowHtml({ state, ip: "10.0.0.9", iface: "bnep0" }, t);
    assert.ok(html.includes(label), state + ": " + html);
    assert.ok(!html.includes("10.0.0.9"), "no IP unless connected: " + html);
    // "Ponów" only where a retry can help
    assert.strictEqual(html.includes("data-tether-retry"), state === "failed", state + ": " + html);
}

// failed + hint: what to check on the phone, never the raw nmcli error.
const HINT = "sprawdź „Tethering przez Bluetooth” w telefonie";
html = Settings.tetherRowHtml({ state: "failed", hint: "check_tethering",
                                error: "Error: raw nmcli" }, t);
assert.ok(html.includes(HINT) && html.includes("Ponów"), html);
assert.ok(!html.includes("raw nmcli"), html);
assert.ok(!Settings.tetherRowHtml({ state: "failed", hint: "" }, t).includes(HINT));
assert.ok(!Settings.tetherRowHtml({ state: "connecting", hint: "check_tethering" }, t).includes(HINT));

// No payload = module not running (production): no row at all.
assert.strictEqual(Settings.tetherRowHtml(undefined, t), "");
assert.strictEqual(Settings.tetherRowHtml(null), "");
assert.strictEqual(Settings.tetherRowHtml("connected", t), "");
// Garbage state: no exception, the raw state escaped.
html = Settings.tetherRowHtml({ state: "<img src=x onerror=alert(1)>" }, t);
assert.ok(!html.includes("<img"), html);
assert.ok(html.includes("&lt;img src=x onerror=alert(1)&gt;"), html);

// Values from the network are escaped.
html = Settings.tetherRowHtml({ state: "connected", ip: "<b>1.2.3.4</b>", iface: '"><script>x</script>' }, t);
assert.ok(!html.includes("<b>") && !html.includes("<script>"), html);
assert.ok(html.includes("&lt;b&gt;1.2.3.4&lt;/b&gt;"), html);
assert.ok(html.includes("&quot;&gt;&lt;script&gt;"), html);

// ── the whole screen shows it ────────────────────────────────────────────
assert.ok(screen && typeof screen.render === "function");
const container = { innerHTML: "" };
screen.render(container, "modern", {
    aa_status: "connected",
    phone_tether: { state: "connected", ip: "192.168.44.23", iface: "bnep0" },
});
assert.ok(container.innerHTML.includes('data-tether-state="connected"'), "row rendered");
assert.ok(container.innerHTML.includes("192.168.44.23"));
assert.ok(container.innerHTML.includes("data-tether-slot"));
// Module off (payload null) or an older backend without the key: no row,
// but the (display:contents) slot is there for update().
for (const data of [{ aa_status: "running" }, { aa_status: "running", phone_tether: null }]) {
    screen.render(container, "modern", data);
    assert.ok(!container.innerHTML.includes("data-tether-state"), container.innerHTML);
    assert.ok(/data-tether-slot style="display:contents"><\/div>/.test(container.innerHTML));
}

// ── update(): only the row, only on change ──────────────────────────────
assert.strictEqual(typeof screen.update, "function", "settings screen has update()");
screen.render(container, "modern", { phone_tether: { state: "connecting", ip: "", iface: "" } });
const rendered = container.innerHTML;
screen.update({ phone_tether: { state: "connecting", ip: "", iface: "" } });
assert.strictEqual(slot.innerHTML, "<untouched>", "same payload: nothing redrawn");
screen.update({ phone_tether: { state: "connected", ip: "192.168.44.23", iface: "bnep0" } });
assert.ok(slot.innerHTML.includes('data-tether-state="connected"'), slot.innerHTML);
assert.ok(slot.innerHTML.includes("192.168.44.23"), slot.innerHTML);
assert.strictEqual(container.innerHTML, rendered, "the screen itself is not re-rendered");
screen.update({ phone_tether: { state: "failed", hint: "check_tethering" } });
assert.ok(slot.innerHTML.includes(HINT), slot.innerHTML);
screen.update({ phone_tether: null });
assert.strictEqual(slot.innerHTML, "");
screen.update(undefined);                                   // never throws
// No slot in the DOM (e.g. mid navigation): no exception, redrawn later.
slotPresent = false;
screen.update({ phone_tether: { state: "no_nap" } });
slotPresent = true;
screen.update({ phone_tether: { state: "no_nap" } });
assert.ok(slot.innerHTML.includes('data-tether-state="no_nap"'), slot.innerHTML);

// ── "Ponów": one POST, double taps swallowed ────────────────────────────
(async () => {
    await Settings.tetherRetry();
    await Settings.tetherRetry();
    const retries = fetches.filter(([url]) => url === "/api/phone_tether/retry");
    assert.deepStrictEqual(retries, [["/api/phone_tether/retry", "POST"]]);
    console.log("ok");
})().catch((e) => { console.error(e); process.exit(1); });
