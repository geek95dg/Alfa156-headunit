// Settings → Moduły (screens/settings.js) for tests/test_frontend_gestures.py:
// the module list from GET /api/modules (src/core/modules_catalog.py) with the
// hardware note, "niedostępny w tej wersji", the "nie wystartuje" warning and
// "wymaga restartu BCM"; the question before enabling a module whose
// dependencies are off (explicit confirm — never a silent cascade) and before
// disabling one others need; every value escaped, inline styles only. Module
// actions redraw only the card ([data-modules-card]) — a full navigateTo()
// would reset the scroll and hide the question below the 1024x600 screen
// (the real-browser check is settings_modules_browser_smoke.js) — and the
// question / status are drawn under the grid line of the tapped module.
// Loads the real file in a node vm with DOM stubs; plain node + assert, no
// packages. Exits non-zero on failure, prints "ok" on success.
"use strict";
const assert = require("assert");
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const WEB = path.join(__dirname, "..", "..", "src", "dashboard", "web", "js");

let screen = null;
const fetches = [];
let reply = () => ({ ok: true, status: 200, body: { ok: true } });
let navigations = 0;
let currentScreen = "settings";
// The card slot of the rendered screen; null = Settings is not on screen.
const revealed = [];
function makeSlot() {
    return {
        innerHTML: "",
        querySelector(sel) {
            const attr = sel.replace(/^\[|\]$/g, "");
            return this.innerHTML.includes(attr)
                ? { sel, scrollIntoView(opts) { revealed.push([sel, opts]); } } : null;
        },
    };
}
let slot = makeSlot();
const ctx = {
    console, setTimeout, clearTimeout, Promise, JSON, Math, Date, Object, String,
    setInterval: () => 0, clearInterval() {},
    fetch: async (url, opts) => {
        const body = opts && opts.body ? JSON.parse(opts.body) : undefined;
        fetches.push({ url, method: (opts && opts.method) || "GET", body });
        const r = reply(url, body);
        return { ok: r.ok, status: r.status, json: async () => r.body };
    },
    App: {
        registerScreen(name, impl) { if (name === "settings") screen = impl; },
        getConfig: () => ({ theme: "modern", language: "pl", speed_unit: "km/h", temp_unit: "C" }),
        t: (key, fallback) => fallback || key,
        navigateTo() { navigations += 1; },
        getCurrentScreen: () => currentScreen,
    },
    AppBar: { render: () => "" },
    document: {
        getElementById: () => null, createElement: () => ({ style: {} }), body: {},
        querySelector: (sel) => (sel === "[data-modules-card]" ? slot : null),
    },
};
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(path.join(WEB, "screens", "settings.js"), "utf8"), ctx,
                { filename: "settings.js" });
vm.runInContext("this.__Settings = Settings;", ctx);
const Settings = ctx.__Settings;
const t = (k, d) => d;
const TAILWIND = /class="[^"]*\b(flex|grid|gap-|px-|py-|p-\d|text-\[|rounded|truncate|ml-)/;

function mod(over) {
    return Object.assign({
        name: "x", part: 1, description: "", enabled: false, kind: "module", available: true,
        runs: false, reason: "disabled", group: "", hardware: "", requires: [], requires_any: [],
        blocked_by: [], needs: [], would_stop: [],
    }, over);
}

// ── one row ──────────────────────────────────────────────────────────────
let html = Settings.moduleRowHtml(mod({
    name: "car_phone", description: "Telefon w aucie", hardware: "Redmi na USB (adb)",
    available: false, kind: "planned", group: "telefon_w_aucie", needs: null,
}), t);
assert.ok(html.includes('data-module="car_phone"'), html);
assert.ok(html.includes("Sprzęt: Redmi na USB (adb)"), html);
assert.ok(html.includes("niedostępny w tej wersji"), html);
assert.ok(/<input[^>]*\bdisabled\b/.test(html), "planned + off: cannot be switched on: " + html);
assert.ok(html.includes("onchange=\"Settings.moduleToggle(this.dataset.module, this.checked)\""), html);
assert.ok(!TAILWIND.test(html), "only inline styles: " + html);
// Planned but on (hand-edited local.yaml): may be switched off.
html = Settings.moduleRowHtml(mod({ name: "car_phone", available: false, enabled: true,
                                    reason: "unavailable" }), t);
assert.ok(!/<input[^>]*\bdisabled\b/.test(html) && html.includes('data-module="car_phone" checked'), html);

// Requirements (all + any-of) and the "will not start" warning.
html = Settings.moduleRowHtml(mod({
    name: "auto_brightness", enabled: true, runs: false, reason: "missing_deps",
    requires: ["car_phone"], requires_any: [["phone_sensors", "input"]],
    blocked_by: [["phone_sensors", "input"]],
}), t);
assert.ok(html.includes("wymaga: car_phone, phone_sensors lub input"), html);
assert.ok(html.includes("data-module-blocked") &&
          html.includes("nie wystartuje — brak: phone_sensors lub input"), html);
assert.ok(!html.includes("data-module-fix"), "nothing to switch on: no fix button " + html);
// On, but its dependency is itself on and blocked (a chain): the row names
// what really has to be switched on (the server's `needs`), not the
// dependency that is already enabled, and offers "Włącz z zależnościami".
const CHAIN = [
    mod({ name: "car_phone" }),
    mod({ name: "car_phone_agent", enabled: true, reason: "missing_deps",
          requires: ["car_phone"], blocked_by: [["car_phone"]], needs: ["car_phone"] }),
    mod({ name: "parking_guard", enabled: true, reason: "missing_deps",
          requires: ["car_phone_agent"], blocked_by: [["car_phone_agent"]], needs: ["car_phone"] }),
];
const CHAIN_IDX = Settings._moduleIndex(CHAIN);
html = Settings.moduleRowHtml(CHAIN[2], t, CHAIN_IDX);
assert.ok(html.includes("nie wystartuje — trzeba włączyć: car_phone"), html);
assert.ok(!html.includes("wyłączone: car_phone_agent"), html);
assert.ok(html.includes('data-module-fix="parking_guard"') &&
          html.includes('onclick="Settings.moduleFixDeps(this.dataset.moduleFix)"'), html);
assert.ok(html.indexOf("data-module-fix") > html.indexOf("</label>"),
          "the fix button is outside the <label> (a tap must not toggle the checkbox)");
// Without `needs` (cannot be enabled in this version): each blocker labelled.
html = Settings.moduleRowHtml(Object.assign({}, CHAIN[2], { needs: null }), t, CHAIN_IDX);
assert.ok(html.includes("nie wystartuje — brak: car_phone_agent (włączony, ale nie działa)"), html);
assert.ok(!html.includes("data-module-fix"), html);
html = Settings.moduleRowHtml(mod({ name: "x", enabled: true, reason: "missing_deps",
                                    blocked_by: [["pl"]], needs: null }), t,
                              Settings._moduleIndex([mod({ name: "pl", available: false })]));
assert.ok(html.includes("brak: pl (niedostępny w tej wersji)"), html);
// A module named like an Object.prototype key is just a name.
assert.strictEqual(Settings._moduleDepLabel("__proto__", Settings._moduleIndex([]), t), "__proto__");
assert.strictEqual(Settings._moduleDepLabel("constructor", Settings._moduleIndex([]), t), "constructor");
// Off: requirements shown, no warning (that comes when enabling).
html = Settings.moduleRowHtml(mod({ name: "phone_status", requires: ["bluetooth"],
                                    blocked_by: [["bluetooth"]] }), t);
assert.ok(html.includes("wymaga: bluetooth") && !html.includes("data-module-blocked"), html);
// Running, but the saved state differs from the running process.
html = Settings.moduleRowHtml(mod({ name: "weather", enabled: true, runs: true, reason: "ok",
                                    restart_pending: true }), t);
assert.ok(html.includes("data-module-restart") && html.includes("wymaga restartu BCM"), html);
assert.ok(!Settings.moduleRowHtml(mod({ name: "weather" }), t).includes("wymaga restartu"));
// Garbage never throws and renders nothing.
for (const bad of [null, undefined, "x", 5, { name: 7 }]) {
    assert.strictEqual(Settings.moduleRowHtml(bad, t), "");
}

// Everything escaped — the payload is data, not markup.
const EVIL = '"><img src=x onerror=alert(1)>';
html = Settings.moduleRowHtml(mod({
    name: "a" + EVIL, description: EVIL, hardware: EVIL, enabled: true,
    requires: [EVIL], blocked_by: [[EVIL]], reason: "missing_deps",
}), t);
assert.ok(!html.includes("<img"), html);
assert.ok(html.includes("&quot;&gt;&lt;img src=x onerror=alert(1)&gt;"), html);
assert.ok(!/moduleToggle\('/.test(html), "the name never goes into JS: " + html);
html = Settings.moduleRowHtml(mod({ name: "a" + EVIL, enabled: true, reason: "missing_deps",
                                    blocked_by: [[EVIL]], needs: [EVIL] }), t);
assert.ok(html.includes("data-module-fix") && !html.includes("<img"), html);
assert.ok(!/moduleFixDeps\('/.test(html), "the name never goes into JS: " + html);

// ── the card: groups in order, banner, status ───────────────────────────
const LIST = [
    mod({ name: "weather", enabled: true, runs: true, reason: "ok" }),
    mod({ name: "crash_detect", group: "bezpieczenstwo" }),
    mod({ name: "car_phone", group: "telefon_w_aucie", available: false, needs: null }),
    mod({ name: "remote_session", group: "zasilanie", available: false, needs: null,
          requires: ["input"] }),
    mod({ name: "odd", group: "<b>inna</b>" }),
];
html = Settings.modulesCardHtml({ list: LIST, status: "<i>zapisano</i>", restartRequired: true }, t);
const order = ["Podstawowe", "Telefon w aucie", "Bezpieczeństwo", "Zasilanie i wybudzanie"]
    .map(h => html.indexOf(h));
assert.ok(order.every(i => i >= 0) && order.every((v, i) => i === 0 || v > order[i - 1]),
          "group headings in catalog order: " + order);
assert.ok(html.includes("&lt;b&gt;inna&lt;/b&gt;") && !html.includes("<b>inna"), html);
assert.ok(html.includes("data-modules-restart"), html);
assert.ok(html.includes("&lt;i&gt;zapisano&lt;/i&gt;") && !html.includes("<i>zapisano"), html);
assert.ok(!TAILWIND.test(html), "only inline styles in the card: " + html);
assert.ok(!Settings.modulesCardHtml({ list: LIST }, t).includes("data-modules-restart"));
assert.strictEqual(Settings.modulesCardHtml(null, t), "");

// ── flows ────────────────────────────────────────────────────────────────
const S = Settings._modules;
function reset(list) {
    S.list = list.map(m => Object.assign({}, m));
    S.status = ""; S.statusName = null; S.confirm = null; S.busy = false;
    S.restartRequired = false;
    fetches.length = 0;
    revealed.length = 0;
    slot = makeSlot();
    currentScreen = "settings";
    navigations = 0;
}
const pos = (h, needle) => {
    const i = h.indexOf(needle);
    assert.ok(i >= 0, needle + " missing: " + h);
    return i;
};
const BT_OFF = [
    mod({ name: "bluetooth" }),
    mod({ name: "phone_status", requires: ["bluetooth"], blocked_by: [["bluetooth"]],
          needs: ["bluetooth"], description: "Stan telefonu" }),
    mod({ name: "crash_sms", available: true, requires: ["car_phone"],
          blocked_by: [["car_phone"]], needs: null }),
    mod({ name: "weather" }),
    mod({ name: "car_phone", available: false, needs: null }),
];
const BT_ON = [
    mod({ name: "bluetooth", enabled: true, runs: true, reason: "ok",
          would_stop: ["phonebook", "phone_status"] }),
    mod({ name: "phone_status", enabled: true, runs: true, reason: "ok", restart_pending: true }),
];

(async () => {
    // Enabling a module whose dependency is off: a question, no request.
    reset(BT_OFF);
    await Settings.moduleToggle("phone_status", true);
    assert.strictEqual(fetches.length, 0, "nothing saved before the driver answers");
    assert.ok(S.confirm && S.confirm.action === "enable", JSON.stringify(S.confirm));
    html = Settings.modulesCardHtml(S, t);
    assert.ok(html.includes('data-module-question="enable"'), html);
    assert.ok(html.includes("„phone_status” wymaga modułów, które nie działają: bluetooth."), html);
    assert.ok(html.includes("Włączyć też: bluetooth?"), html);
    for (const c of ["deps", "only", "cancel"]) {
        assert.ok(html.includes(`data-module-confirm="${c}"`), c + ": " + html);
    }
    assert.ok(html.includes('data-module="phone_status" ') &&
              !html.includes('data-module="phone_status" checked'),
              "checkbox shows the saved state until confirmed");

    // Only the card is redrawn — never the whole screen (scroll reset) —
    // and the question is scrolled into view by the smallest amount.
    assert.strictEqual(navigations, 0, "no full re-render for a module action");
    assert.strictEqual(slot.innerHTML, Settings.modulesCardHtml(S, t));
    // (JSON: the options object comes from the vm realm)
    assert.strictEqual(JSON.stringify(revealed), '[["[data-module-question]",{"block":"nearest"}]]');
    // The question sits under the grid line of the tapped module (bluetooth
    // | phone_status), before the next line (crash_sms | weather).
    assert.ok(pos(html, 'data-module-row="phone_status"') < pos(html, "data-module-question")
              && pos(html, "data-module-question") < pos(html, 'data-module-row="crash_sms"'), html);
    assert.ok(html.includes('data-module-notes="phone_status" style="grid-column:1/-1'), html);

    // Cancel: still nothing saved.
    await Settings.moduleConfirm("cancel");
    assert.strictEqual(fetches.length, 0);
    assert.strictEqual(S.confirm, null);
    assert.ok(!slot.innerHTML.includes("data-module-question"), "question gone");
    assert.strictEqual(navigations, 0);

    // Confirm with dependencies: one POST with with_deps, list from the reply.
    await Settings.moduleToggle("phone_status", true);
    reply = () => ({ ok: true, status: 200, body: {
        ok: true, persisted: true, restart_required: true, enabled_also: ["bluetooth"],
        modules: BT_ON } });
    await Settings.moduleConfirm("deps");
    assert.deepStrictEqual(fetches.map(f => [f.url, f.method, f.body]),
        [["/api/modules", "POST", { name: "phone_status", enabled: true, with_deps: true }]]);
    assert.strictEqual(S.list.length, 2, "list replaced by the reply");
    assert.ok(S.restartRequired);
    assert.ok(S.status.includes("Zapisano — wymaga restartu BCM") &&
              S.status.includes("włączono też: bluetooth"), S.status);
    // The status is drawn under the saved module's row and scrolled to.
    assert.strictEqual(S.statusName, "phone_status");
    assert.ok(pos(slot.innerHTML, 'data-module-row="phone_status"') <
              pos(slot.innerHTML, "data-modules-status"), slot.innerHTML);
    assert.strictEqual(JSON.stringify(revealed[revealed.length - 1]),
                       '["[data-modules-status]",{"block":"nearest"}]');
    assert.strictEqual(navigations, 0);

    // "Tylko ten moduł": saved alone (the module then logs one warning).
    reset(BT_OFF);
    reply = () => ({ ok: true, status: 200, body: { ok: true, restart_required: false,
                                                    persisted: false } });
    await Settings.moduleToggle("phone_status", true);
    await Settings.moduleConfirm("only");
    assert.deepStrictEqual(fetches[0].body, { name: "phone_status", enabled: true, with_deps: false });
    assert.ok(S.status.startsWith("Zapisano") && S.status.includes("nie zapisano w local.yaml"),
              S.status);
    assert.strictEqual(S.list.find(m => m.name === "phone_status").enabled, true,
                       "without a list in the reply the row is updated in place");

    // Dependencies that cannot be enabled in this version: no "with deps".
    reset(BT_OFF);
    await Settings.moduleToggle("crash_sms", true);
    // crash_sms is first on its line (crash_sms | weather): the question
    // comes after weather, so no row is pushed out of its column.
    assert.ok(pos(slot.innerHTML, 'data-module-row="weather"') <
              pos(slot.innerHTML, "data-module-question") &&
              pos(slot.innerHTML, "data-module-question") <
              pos(slot.innerHTML, 'data-module-row="car_phone"'), slot.innerHTML);
    html = Settings.moduleConfirmHtml(S.confirm, t);
    assert.ok(html.includes("nie są dostępne w tej wersji"), html);
    assert.ok(!html.includes('data-module-confirm="deps"') &&
              html.includes('data-module-confirm="only"'), html);
    await Settings.moduleConfirm("deps");      // forged choice: never with_deps
    assert.strictEqual(fetches.length, 1);
    assert.strictEqual(fetches[0].body.with_deps, false);

    // A module without missing dependencies is saved at once, no question.
    reset(BT_OFF);
    await Settings.moduleToggle("weather", true);
    assert.strictEqual(S.confirm, null);
    assert.deepStrictEqual(fetches[0].body, { name: "weather", enabled: true });

    // A planned module cannot be switched on from the UI.
    reset(BT_OFF);
    await Settings.moduleToggle("car_phone", true);
    assert.strictEqual(fetches.length, 0);
    assert.ok(S.status.includes("niedostępny w tej wersji"), S.status);

    // "Włącz z zależnościami" on a module that is on but blocked by a chain:
    // the question lists the dependency that is on but not running as such,
    // offers only "with dependencies" (it is on already) and saves on yes.
    reset(CHAIN);
    Settings.moduleFixDeps("parking_guard");
    assert.strictEqual(fetches.length, 0, "a question first");
    html = slot.innerHTML;
    assert.ok(html.includes("„parking_guard” wymaga modułów, które nie działają: " +
                            "car_phone_agent (włączony, ale nie działa)."), html);
    assert.ok(html.includes("Włączyć też: car_phone?"), html);
    assert.ok(html.includes('data-module-confirm="deps"') &&
              !html.includes('data-module-confirm="only"'), html);
    reply = () => ({ ok: true, status: 200, body: { ok: true, restart_required: true,
                                                    enabled_also: ["car_phone"] } });
    await Settings.moduleConfirm("deps");
    assert.deepStrictEqual(fetches.map(f => f.body),
                           [{ name: "parking_guard", enabled: true, with_deps: true }]);
    // Nothing to fix: no question.
    for (const name of ["car_phone", "nope"]) {
        reset(CHAIN);
        Settings.moduleFixDeps(name);
        assert.strictEqual(S.confirm, null, name);
    }
    reset(CHAIN.map(m => Object.assign({}, m, { needs: null })));
    Settings.moduleFixDeps("parking_guard");
    assert.strictEqual(S.confirm, null, "needs null: nothing the driver could switch on");

    // The driver left Settings while a save was in flight: the result is
    // kept for the next visit, the screen is NOT pulled back to Settings.
    reset(BT_OFF);
    slot = null;
    currentScreen = "a1";
    reply = () => ({ ok: true, status: 200, body: { ok: true } });
    await Settings.moduleToggle("weather", true);
    assert.strictEqual(navigations, 0);
    assert.ok(S.status.startsWith("Zapisano"), S.status);
    slot = makeSlot();

    // Switching off a module others need: a question naming them.
    reset(BT_ON);
    await Settings.moduleToggle("bluetooth", false);
    assert.strictEqual(fetches.length, 0);
    html = Settings.modulesCardHtml(S, t);
    assert.ok(html.includes("Wyłączenie „bluetooth” zatrzyma też: phonebook, phone_status."), html);
    assert.ok(html.includes('data-module-confirm="disable"'), html);
    reply = () => ({ ok: true, status: 200, body: { ok: true, restart_required: true } });
    await Settings.moduleConfirm("disable");
    assert.deepStrictEqual(fetches[0].body, { name: "bluetooth", enabled: false });

    // Server refusal: the (escaped) error is shown, the list is unchanged.
    reset(BT_OFF);
    reply = () => ({ ok: false, status: 409, body: { error: "<b>not available</b>" } });
    await Settings.moduleToggle("weather", true);
    assert.strictEqual(S.status, "<b>not available</b>");
    assert.strictEqual(S.list.find(m => m.name === "weather").enabled, false);
    assert.ok(Settings.modulesCardHtml(S, t).includes("&lt;b&gt;not available&lt;/b&gt;"));
    reply = () => ({ ok: false, status: 500, body: null });
    await Settings.moduleToggle("weather", true);
    assert.strictEqual(S.status, "HTTP 500");

    // Double tap while a save is in flight: one request.
    reset(BT_OFF);
    let release;
    reply = () => ({ ok: true, status: 200, body: { ok: true } });
    const slow = ctx.fetch;
    ctx.fetch = (url, opts) => new Promise(res => { release = () => res(slow(url, opts)); });
    const first = Settings.moduleToggle("weather", true);
    await Settings.moduleToggle("weather", true);
    release();
    await first;
    ctx.fetch = slow;
    assert.strictEqual(fetches.length, 1);

    // GET: restart flag from the server.
    reset([]);
    S.loaded = false;
    reply = () => ({ ok: true, status: 200, body: { modules: BT_ON, restart_required: true } });
    await Settings.modulesLoad(true);
    assert.ok(S.restartRequired && S.list.length === 2);
    assert.ok(slot.innerHTML.includes('data-module-row="bluetooth"'), "load redraws the card");
    assert.strictEqual(revealed.length, 0, "a plain load scrolls nothing");
    assert.strictEqual(navigations, 0);

    // ── the whole screen shows the card ─────────────────────────────────
    assert.ok(screen && typeof screen.render === "function");
    S.loaded = true;            // render() must not refetch for this check
    const container = { innerHTML: "" };
    screen.render(container, "modern", { aa_status: "connected" });
    assert.ok(container.innerHTML.includes("data-modules-card"), "card rendered");
    assert.ok(container.innerHTML.includes('data-module-row="bluetooth"'), container.innerHTML);
    console.log("ok");
})().catch((e) => { console.error(e); process.exit(1); });
