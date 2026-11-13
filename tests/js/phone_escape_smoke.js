// Text that comes from the phone (or from any Bluetooth device in range)
// never becomes markup or script, for tests/test_frontend_gestures.py:
//   * screens/phone.js — PBAP contacts / call history and the call overlays;
//     rows carry the number in data-dial and one delegated listener dials it,
//   * components/media-player.js — AVRCP title / artist,
//   * screens/settings.js — Bluetooth device names / addresses, pairing popup,
//   * components/notifications.js — the card renderers.
// No DOM library is available, so the markup is checked with a small tag
// scanner: no foreign element (img/script/svg/iframe), no event-handler
// attribute other than the known constant ones, and attribute values decode
// back to exactly the input (a quote cannot break out). Plain node + assert;
// exits non-zero on failure, prints "ok" on success.
"use strict";
const assert = require("assert");
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const WEB = path.join(__dirname, "..", "..", "src", "dashboard", "web", "js");

// ── tiny markup scanner ──────────────────────────────────────────────────
const TAG_RE = /<([a-zA-Z][a-zA-Z0-9-]*)((?:\s+[^\s=>\/]+(?:\s*=\s*(?:"[^"]*"|'[^']*'|[^\s>]+))?)*)\s*\/?>/g;
const ATTR_RE = /([^\s=>\/]+)(?:\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+)))?/g;

function scan(html) {
    const tags = [];
    let m;
    TAG_RE.lastIndex = 0;
    while ((m = TAG_RE.exec(html)) !== null) {
        const attrs = [];
        let a;
        ATTR_RE.lastIndex = 0;
        while ((a = ATTR_RE.exec(m[2])) !== null) {
            attrs.push([a[1].toLowerCase(), a[2] !== undefined ? a[2] : a[3] !== undefined ? a[3] : (a[4] || "")]);
        }
        tags.push({ name: m[1].toLowerCase(), attrs });
    }
    return tags;
}

function decode(v) {
    return v.replace(/&quot;/g, '"').replace(/&#39;/g, "'").replace(/&lt;/g, "<")
        .replace(/&gt;/g, ">").replace(/&amp;/g, "&");
}

const FORBIDDEN_TAGS = ["img", "script", "svg", "iframe", "object", "embed", "style", "a"];

/** No foreign element; every on* attribute is one of `handlers` (regexps
 *  of constant handler code). Returns the scanned tags. */
function assertInert(html, handlers, where) {
    const tags = scan(html);
    for (const t of tags) {
        assert.ok(!FORBIDDEN_TAGS.includes(t.name), `${where}: <${t.name}> produced`);
        for (const [name, value] of t.attrs) {
            if (!name.startsWith("on")) continue;
            assert.ok(handlers.some((re) => re.test(value)),
                      `${where}: unexpected handler ${name}="${value}"`);
        }
    }
    return tags;
}

const EVIL_NAME = "<img src=x onerror=alert(1)>";
const EVIL_NUMBERS = ["1');alert(1);//", "\"><img src=x onerror=alert(2)>", "2' onclick='alert(3)"];

// ── screens/phone.js ─────────────────────────────────────────────────────
let screen = null;
const rowListeners = [];
const rowsEl = { addEventListener(type, fn) { rowListeners.push([type, fn]); } };
const container = {
    innerHTML: "",
    querySelector: (sel) => (sel === "[data-phone-rows]" ? rowsEl : null),
};
let contactsReply = [];
let historyReply = [];
const phoneCtx = {
    console, setTimeout, clearTimeout, Promise, JSON, Math, Date, Object, String, Array,
    fetch: async (url) => ({
        ok: true,
        json: async () => (url === "/api/phone/contacts" ? { contacts: contactsReply }
            : url === "/api/phone/history" ? { history: historyReply } : {}),
    }),
    App: {
        registerScreen(name, impl) { if (name === "a8") screen = impl; },
        navigateTo(s) { if (s === "a8") screen.render(container, "heritage", {}); },
        t: (key, fallback) => fallback || key,
    },
    AppBar: { render: () => "" },
    NavBar: { render: () => "" },
    DataStore: { sendKey() {} },
    document: { getElementById: () => null },
};
vm.createContext(phoneCtx);
vm.runInContext(fs.readFileSync(path.join(WEB, "screens", "phone.js"), "utf8"), phoneCtx,
                { filename: "phone.js" });
vm.runInContext("this.__Phone = Phone;", phoneCtx);
const Phone = phoneCtx.__Phone;

// Constant handlers phone.js may use (no data inside).
const PHONE_HANDLERS = [
    /^Phone\.(setTab|key)\('[a-z0-9*#]+'\)$/,
    /^Phone\.(dial|answer|reject|hangup|toggleMute)\(\)$/,
    /^Phone\.filterContacts\(this\.value\)$/,
];

// Number normalisation mirrors bluetooth.normalize_dial_number.
const NUMBERS = [
    ["+48 600-123-456", "+48600123456"], ["(22) 123 45 67", "221234567"], ["*100#", "*100#"],
    ["112", "112"], [600123456, "600123456"],
    ["1');alert(1);//", ""], ["abc", ""], ["", ""], ["+48\n600", "+48600"], ["9".repeat(33), ""],
    ["1".repeat(200), ""], [null, ""], [undefined, ""], [{}, ""], [["112"], ""],
];
for (const [input, want] of NUMBERS) {
    assert.strictEqual(Phone.normalizeNumber(input), want, `normalizeNumber(${JSON.stringify(input)})`);
}

(async () => {
    contactsReply = [
        { name: EVIL_NAME, number: EVIL_NUMBERS[0] },
        { name: 'Jan "Kowal" </p><script>alert(4)</script>', number: EVIL_NUMBERS[1] },
        { name: "Ola", number: EVIL_NUMBERS[2] },
        { name: "Ok", number: "+48 600-123-456" },
        null, "junk", 5,
    ];
    historyReply = [
        { name: "<b>x</b>", number: "2", type: "constructor", time: "<i>t</i>", duration: "<u>" },
        { name: "", number: EVIL_NUMBERS[1], type: "__proto__" },
        { name: "Ok", number: "112", type: "missed" },
    ];
    App_navigate("a8");                         // first render triggers the loads
    await new Promise((r) => setTimeout(r, 0));
    await new Promise((r) => setTimeout(r, 0));
    assert.strictEqual(Phone._contacts.length, 4, "non-object rows dropped");

    // Contacts
    Phone._tab = "contacts";
    App_navigate("a8");
    let html = container.innerHTML;
    let tags = assertInert(html, PHONE_HANDLERS, "contacts");
    let dial = tags.flatMap((t) => t.attrs.filter(([n]) => n === "data-dial").map(([, v]) => decode(v)));
    assert.deepStrictEqual(dial, [EVIL_NUMBERS[0], EVIL_NUMBERS[1], EVIL_NUMBERS[2], "+48 600-123-456"],
                           "data-dial values must round-trip exactly");
    assert.ok(html.includes("&lt;img src=x onerror=alert(1)&gt;"), "name shown as text");
    assert.ok(!/dialNumber\(/.test(html), "no number-carrying inline handler left");

    // History: no Object.prototype members from h.type, text escaped.
    Phone._tab = "history";
    App_navigate("a8");
    html = container.innerHTML;
    tags = assertInert(html, PHONE_HANDLERS, "history");
    assert.ok(!/function|\[object/.test(html), "prototype member leaked into the markup");
    assert.ok(html.includes("&lt;b&gt;x&lt;/b&gt;") && html.includes("&lt;i&gt;t&lt;/i&gt;"));
    assert.ok(html.includes(">call<"), "unknown call type falls back to the call icon");
    assert.ok(html.includes("call_missed"));

    // Delegated click → dialer, validated.
    assert.ok(rowListeners.length > 0 && rowListeners.every(([type]) => type === "click"));
    const click = rowListeners[rowListeners.length - 1][1];
    const rowTarget = (value) => ({ closest: (sel) => (sel === "[data-dial]"
        ? { getAttribute: (a) => (a === "data-dial" ? value : null) } : null) });
    Phone._input = "";
    click({ target: rowTarget(EVIL_NUMBERS[0]) });
    assert.strictEqual(Phone._input, "", "a non-number never reaches the dialer");
    assert.strictEqual(Phone._tab, "history");
    click({ target: { closest: () => null } });          // tap between rows
    click({});                                            // no target
    click({ target: rowTarget("+48 600-123-456") });
    assert.strictEqual(Phone._input, "+48600123456");
    assert.strictEqual(Phone._tab, "dialer");
    html = container.innerHTML;
    assertInert(html, PHONE_HANDLERS, "dialer");
    assert.ok(html.includes(">+48600123456<"));

    // Call overlays (bt.call_info from oFono).
    for (const state of ["incoming", "active", "ringing"]) {
        Phone._callState = state;
        Phone._callInfo = { name: EVIL_NAME, number: EVIL_NUMBERS[1] };
        App_navigate("a8");
        assertInert(container.innerHTML, PHONE_HANDLERS, "overlay " + state);
        assert.ok(container.innerHTML.includes("&lt;img src=x onerror=alert(1)&gt;"));
    }
    Phone._callState = "idle";
    Phone._callInfo = {};

    // A malformed /api/phone reply never breaks render().
    contactsReply = "nope";
    historyReply = { 0: { name: "x" } };
    await Phone.loadContacts();
    await Phone.loadHistory();
    assert.deepStrictEqual([Phone._contacts.length, Phone._history.length], [0, 0]);

    // ── components/media-player.js (AVRCP metadata) ──────────────────────
    const MediaPlayer = require(path.join(WEB, "components", "media-player.js"));
    const MEDIA_HANDLERS = [
        /^MediaPlayer\.cmd\('[a-z]+', event\)$/, /^MediaPlayer\.toggleMute\(event\)$/,
        /^MediaPlayer\.setVolume\(this\.value, event\)$/,
    ];
    for (const fn of ["renderHeritage", "renderModern", "renderAutodelta"]) {
        html = MediaPlayer[fn]({ bt_media_title: EVIL_NAME, bt_media_artist: '"><script>x</script>',
                                 audio_volume: '50" onfocus="alert(5)' });
        tags = assertInert(html, MEDIA_HANDLERS, "media " + fn);
        assert.ok(html.includes("&lt;img src=x onerror=alert(1)&gt;"), html);
        const vol = tags.find((t) => t.attrs.some(([n, v]) => n === "id" && v === "media-volume"));
        assert.ok(vol.attrs.some(([n, v]) => n === "value" && v === "70"), "bad volume → default");
    }

    // ── components/notifications.js (card renderers) ─────────────────────
    const Notifications = require(path.join(WEB, "components", "notifications.js"));
    const evilNote = [{ severity: "danger", icon: "x\"><img src=x onerror=alert(6)>",
                        title: EVIL_NAME, desc: "<script>alert(7)</script>" }];
    for (const fn of ["renderHeritage", "renderModern", "renderAutodelta"]) {
        html = Notifications[fn](evilNote);
        assertInert(html, [], "notifications " + fn);
        assert.ok(html.includes(">info<"), "bad icon name → info");
    }

    // ── screens/settings.js (Bluetooth devices + pairing popup) ──────────
    let settingsScreen = null;
    const popup = { style: {}, innerHTML: "" };
    const settingsCtx = {
        console, setTimeout, clearTimeout, Promise, JSON, Math, Date, Object, String,
        setInterval: () => 0, clearInterval() {},
        fetch: async () => ({ ok: true, json: async () => ({}) }),
        App: {
            registerScreen(name, impl) { if (name === "settings") settingsScreen = impl; },
            getConfig: () => ({ theme: "modern", language: "pl", speed_unit: "km/h", temp_unit: "C" }),
            t: (key, fallback) => fallback || key,
            navigateTo() {},
        },
        AppBar: { render: () => "" },
        document: {
            getElementById: () => null, createElement: () => popup,
            body: { appendChild() {} }, querySelector: () => null,
        },
    };
    vm.createContext(settingsCtx);
    vm.runInContext(fs.readFileSync(path.join(WEB, "screens", "settings.js"), "utf8"), settingsCtx,
                    { filename: "settings.js" });
    vm.runInContext("this.__Settings = Settings;", settingsCtx);
    const Settings = settingsCtx.__Settings;
    Settings._btPaired = [
        { address: "AA:BB:CC:DD:EE:01", name: EVIL_NAME, connected: false },
        { address: "AA:BB:CC:DD:EE:02", name: "Pixel", connected: true },
    ];
    Settings._btDiscovered = [
        { address: "AA:BB');alert(8);//", name: "x" },
        { address: "11:22:33:44:55:66", name: '"><script>alert(9)</script>' },
    ];
    const sc = { innerHTML: "" };
    settingsScreen.render(sc, "modern", {});
    html = sc.innerHTML;
    // Inline handlers in Settings are constants or a validated MAC.
    const SETTINGS_HANDLERS = [
        /^Settings\.bt(Pair|Connect|Remove)\('[0-9A-F]{2}(:[0-9A-F]{2}){5}'\)$/,
        /^(?!.*alert)(?!.*AA:BB')[\s\S]*$/,          // anything else must not carry the payloads
    ];
    tags = assertInert(html, SETTINGS_HANDLERS, "settings");
    assert.ok(html.includes("Settings.btConnect('AA:BB:CC:DD:EE:01')"));
    assert.ok(html.includes("Settings.btPair('11:22:33:44:55:66')"));
    assert.ok(!html.includes("alert(8)") || html.includes("AA:BB&#39;);alert(8);//"),
              "bad address only as escaped text");
    assert.ok(!html.includes("Settings.btPair('AA:BB"), "no button for an invalid address");
    assert.ok(html.includes("&lt;img src=x onerror=alert(1)&gt;"));

    Settings._showPairingPopup({ address: EVIL_NAME, passkey: "<b>123456</b>" });
    assertInert(popup.innerHTML, [/^Settings\.btPairingRespond\((true|false)\)$/], "pairing popup");
    assert.ok(popup.innerHTML.includes("&lt;b&gt;123456&lt;/b&gt;"));

    process.stdout.write("ok");
})().catch((e) => { console.error(e); process.exit(1); });

function App_navigate(s) { phoneCtx.App.navigateTo(s); }
