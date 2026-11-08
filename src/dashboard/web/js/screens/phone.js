/**
 * A8 Phone Screen — BT dialer, contacts (PBAP), call history.
 * Tabs: Contacts | History | Dialer
 * Incoming call overlay with accept/reject.
 *
 * State lives on the global Phone object so render() and Phone methods
 * share the same source of truth.
 */

/** Rows from /api/phone/{contacts,history}: only objects, as a list (PBAP
 *  data is the phone's — a malformed reply must not throw in render()). */
function _phoneRows(value) {
    return Array.isArray(value) ? value.filter((r) => r && typeof r === "object") : [];
}

// Phone state & API — defined BEFORE the screen IIFE so render() can read it.
const Phone = {
    _tab: "contacts",        // "contacts" | "history" | "dialer"
    _input: "",
    _contacts: [],
    _history: [],
    _contactsFilter: "",
    _callState: "idle",      // "idle" | "ringing" | "active" | "incoming"
    _callInfo: {},

    setTab(tab) { Phone._tab = tab; App.navigateTo("a8"); },

    key(k) {
        if (k === "del") {
            Phone._input = Phone._input.slice(0, -1);
        } else {
            Phone._input += k;
        }
        // Update ONLY the number display. Re-rendering the whole screen
        // (App.navigateTo) on every digit rebuilds AppBar/NavBar + the
        // contacts/history lists and sets container.innerHTML, which makes
        // the keypad feel laggy. The keypad buttons never change, so a
        // direct textContent write is instant. Fall back to a full render
        // only if the display node isn't present (not on the dialer view).
        const disp = document.getElementById("dialer-display");
        if (disp) {
            disp.textContent = Phone._input || " ";
        } else {
            App.navigateTo("a8");
        }
    },

    /** A number from the phonebook/history → a dial string ("+48600123456"),
     *  or "" if it is not one. Mirrors bluetooth.normalize_dial_number (the
     *  backend validates /api/phone/dial again): separators dropped, then
     *  only 1-32 of 0-9 + * #. PBAP data is untrusted — anything else never
     *  reaches the dialer. */
    normalizeNumber(value) {
        if (typeof value !== "string" && typeof value !== "number") return "";
        const text = String(value);
        if (text.length > 128) return "";
        const number = text.replace(/[\s\-().\/]/g, "");
        return /^[0-9+*#]{1,32}$/.test(number) ? number : "";
    },

    dialNumber(num) {
        const number = Phone.normalizeNumber(num);
        if (!number) return;          // not dialable (letters, junk): ignore the tap
        Phone._input = number;
        Phone._tab = "dialer";
        App.navigateTo("a8");
    },

    async dial() {
        if (!Phone._input) return;
        const number = Phone._input;
        // Show calling overlay immediately
        Phone._callState = "ringing";
        Phone._callInfo = { number: number, name: "" };
        Phone._input = "";
        App.navigateTo("a8");
        let ok = false;
        try {
            const res = await fetch("/api/phone/dial", {
                method: "POST",
                headers: {"Content-Type": "application/json"},
                body: JSON.stringify({number: number}),
            });
            // 400 = not a dial string (the backend refuses it); otherwise the
            // call state follows bt.call_state over the WebSocket.
            ok = !!res.ok;
        } catch (e) { /* network error: same as refused */ }
        if (!ok && Phone._callState === "ringing") {
            Phone._callState = "idle";
            Phone._callInfo = {};
            App.navigateTo("a8");
        }
    },

    async answer() {
        try { await fetch("/api/phone/answer", {method: "POST"}); } catch (e) {}
    },

    async reject() {
        try { await fetch("/api/phone/hangup", {method: "POST"}); } catch (e) {}
    },

    async hangup() {
        try { await fetch("/api/phone/hangup", {method: "POST"}); } catch (e) {}
        Phone._callState = "idle";
        Phone._callInfo = {};
        App.navigateTo("a8");
    },

    toggleMute() {
        DataStore.sendKey("mute_mic");
    },

    filterContacts(val) {
        Phone._contactsFilter = val;
        App.navigateTo("a8");
    },

    async loadContacts() {
        try {
            const res = await fetch("/api/phone/contacts");
            const data = await res.json();
            Phone._contacts = _phoneRows(data && data.contacts);
            App.navigateTo("a8");
        } catch (e) {}
    },

    async loadHistory() {
        try {
            const res = await fetch("/api/phone/history");
            const data = await res.json();
            Phone._history = _phoneRows(data && data.history);
            App.navigateTo("a8");
        } catch (e) {}
    },
};

App.registerScreen("a8", (() => {
    let _contactsLoaded = false;
    let _historyLoaded = false;

    // Everything shown here comes from the phone: caller name/number from the
    // phone network via oFono (bt.call_info), names/numbers/times from the
    // phonebook (PBAP). Untrusted text going into innerHTML — always _esc(),
    // and never spliced into inline JavaScript: rows carry the number in a
    // data-dial attribute and one delegated listener (_onRowClick) reads it.
    function _esc(v) {
        return String(v == null ? "" : v).replace(/&/g, "&amp;").replace(/</g, "&lt;")
            .replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#39;");
    }

    function render(container, theme, data) {
        const t = App.t.bind(App);
        const bgCls = theme === "modern" ? "bg-slate-100 text-slate-900" : "bg-black text-white";
        const cardBg = theme === "modern" ? "bg-white border-slate-200 shadow-sm" : "bg-zinc-900 border-zinc-800";
        const accentClr = theme === "autodelta" ? "#FF5F00" : theme === "modern" ? "#005596" : "#f59e0b";
        const tabActive = theme === "modern" ? "bg-blue-600 text-white" : "bg-zinc-700 text-white";
        const tabInactive = theme === "modern" ? "bg-slate-200 text-slate-600" : "bg-zinc-800 text-zinc-400";

        const tab = Phone._tab;
        const _callState = Phone._callState || "idle";
        const _callInfo = Phone._callInfo || {};
        const callActive = _callState !== "idle";

        container.innerHTML = `<div class="screen-container ${bgCls}">
            ${AppBar.render(theme, data)}
            <main class="content-area flex flex-col p-3 relative">
                <!-- Tab bar -->
                <div class="flex gap-2 mb-3 shrink-0">
                    <button class="px-4 py-1.5 rounded-lg text-xs font-bold ${tab==='contacts'?tabActive:tabInactive}" onclick="Phone.setTab('contacts')">
                        <span class="material-symbols-outlined mr-1" style="font-size:14px;vertical-align:-2px;">contacts</span>${t("contacts","Contacts")}
                    </button>
                    <button class="px-4 py-1.5 rounded-lg text-xs font-bold ${tab==='history'?tabActive:tabInactive}" onclick="Phone.setTab('history')">
                        <span class="material-symbols-outlined mr-1" style="font-size:14px;vertical-align:-2px;">history</span>${t("call_history","History")}
                    </button>
                    <button class="px-4 py-1.5 rounded-lg text-xs font-bold ${tab==='dialer'?tabActive:tabInactive}" onclick="Phone.setTab('dialer')">
                        <span class="material-symbols-outlined mr-1" style="font-size:14px;vertical-align:-2px;">dialpad</span>${t("dialer","Dialer")}
                    </button>
                </div>

                <!-- Tab content (rows: delegated click, see _onRowClick) -->
                <div class="flex-1 overflow-hidden" data-phone-rows>
                    ${tab === "contacts" ? _renderContacts(theme, cardBg, accentClr, t) : ""}
                    ${tab === "history" ? _renderHistory(theme, cardBg, accentClr, t) : ""}
                    ${tab === "dialer" ? _renderDialer(theme, cardBg, accentClr, t) : ""}
                </div>

                <!-- Active call overlay -->
                ${callActive ? _renderCallOverlay(theme, accentClr, t) : ""}
                <!-- Incoming call overlay -->
                ${_callState === "incoming" ? _renderIncomingOverlay(theme, accentClr, t) : ""}
            </main>
            ${NavBar.render(theme, "a8")}
        </div>`;

        // One listener per render on the freshly built list (it goes away
        // with the markup on the next render — nothing accumulates).
        const rows = typeof container.querySelector === "function"
            ? container.querySelector("[data-phone-rows]") : null;
        if (rows && typeof rows.addEventListener === "function") {
            rows.addEventListener("click", _onRowClick);
        }

        // Load contacts/history once
        _renderedCallKey = _callKey();

        if (!_contactsLoaded) { _contactsLoaded = true; Phone.loadContacts(); }
        if (!_historyLoaded) { _historyLoaded = true; Phone.loadHistory(); }
    }

    /** Tap on a contact/history row → its number into the dialer. The value
     *  is read back from the attribute (the browser un-escapes it) and
     *  validated again by Phone.dialNumber(). */
    function _onRowClick(ev) {
        const target = ev && ev.target;
        const row = target && typeof target.closest === "function" ? target.closest("[data-dial]") : null;
        if (row) Phone.dialNumber(row.getAttribute("data-dial"));
    }

    /** Own-property lookup: h.type comes from the phone, and "constructor"
     *  or "__proto__" must not pick up Object.prototype members. */
    function _pick(map, key, fallback) {
        return typeof key === "string" && Object.prototype.hasOwnProperty.call(map, key)
            ? map[key] : fallback;
    }

    function _renderDialer(theme, cardBg, accent, t) {
        const keys = ["1","2","3","4","5","6","7","8","9","*","0","#"];
        const keyBg = theme === "modern" ? "bg-slate-50 hover:bg-slate-100 text-slate-900" : "bg-zinc-800 hover:bg-zinc-700 text-white";

        return `<div class="flex flex-col items-center h-full">
            <!-- Number display -->
            <div id="dialer-display" class="text-3xl font-bold tracking-wider mb-3 h-10" style="color:${accent};">${_esc(Phone._input) || "\u00a0"}</div>
            <!-- Keypad -->
            <div class="grid grid-cols-3 gap-2 w-[280px]">
                ${keys.map(k => `<button class="${keyBg} rounded-xl py-3 text-xl font-bold active:scale-95 transition-transform" onclick="Phone.key('${k}')">${k}</button>`).join("")}
            </div>
            <!-- Action buttons -->
            <div class="flex gap-4 mt-3">
                <button class="w-14 h-14 rounded-full bg-red-600 text-white flex items-center justify-center active:scale-95" onclick="Phone.key('del')">
                    <span class="material-symbols-outlined">backspace</span>
                </button>
                <button class="w-14 h-14 rounded-full bg-green-600 text-white flex items-center justify-center active:scale-95" onclick="Phone.dial()">
                    <span class="material-symbols-outlined">call</span>
                </button>
            </div>
        </div>`;
    }

    function _renderContacts(theme, cardBg, accent, t) {
        const filterBg = theme === "modern" ? "bg-white border-slate-200" : "bg-zinc-800 border-zinc-700";
        const filtered = Phone._contactsFilter
            ? Phone._contacts.filter(c => String(c.name || "").toLowerCase().includes(Phone._contactsFilter.toLowerCase()))
            : Phone._contacts;
        // Names/numbers come from the phone's phonebook (PBAP): untrusted
        // text, escaped for innerHTML; the number travels in data-dial.

        return `<div class="flex flex-col h-full">
            <div class="flex items-center gap-2 ${filterBg} border rounded-lg px-3 py-1.5 mb-2 shrink-0">
                <span class="material-symbols-outlined opacity-40" style="font-size:18px;">search</span>
                <input type="text" value="${_esc(Phone._contactsFilter)}" placeholder="${t("search_contacts","Search...")}"
                       class="bg-transparent border-none outline-none text-sm flex-1 p-0"
                       oninput="Phone.filterContacts(this.value)">
            </div>
            <div class="flex-1 overflow-y-auto space-y-1">
                ${filtered.length === 0
                    ? `<div class="flex flex-col items-center justify-center py-8 opacity-30">
                        <span class="material-symbols-outlined text-4xl mb-2">person_off</span>
                        <span class="text-sm font-bold">${t("no_contacts","No contacts synced")}</span>
                       </div>`
                    : filtered.map(c => `<div class="${cardBg} border rounded-lg p-2 flex justify-between items-center cursor-pointer hover:opacity-80" data-dial="${_esc(c.number)}">
                        <div class="flex items-center gap-3">
                            <div class="w-8 h-8 rounded-full flex items-center justify-center text-xs font-bold" style="background:${accent}20;color:${accent};">${_esc(String(c.name || "").charAt(0))}</div>
                            <div>
                                <p class="text-sm font-bold">${_esc(c.name)}</p>
                                <p class="text-[10px] opacity-50">${_esc(c.number)}</p>
                            </div>
                        </div>
                        <span class="material-symbols-outlined opacity-30" style="font-size:20px;">call</span>
                    </div>`).join("")
                }
            </div>
        </div>`;
    }

    function _renderHistory(theme, cardBg, accent, t) {
        const iconMap = { incoming: "call_received", outgoing: "call_made", missed: "call_missed" };
        const colorMap = { incoming: "text-green-500", outgoing: "text-blue-500", missed: "text-red-500" };

        return `<div class="flex-1 overflow-y-auto space-y-1">
            ${Phone._history.length === 0
                ? `<div class="flex flex-col items-center justify-center py-8 opacity-30">
                    <span class="material-symbols-outlined text-4xl mb-2">history</span>
                    <span class="text-sm font-bold">${t("no_history","No call history")}</span>
                   </div>`
                : Phone._history.map(h => `<div class="${cardBg} border rounded-lg p-2 flex justify-between items-center cursor-pointer hover:opacity-80" data-dial="${_esc(h.number)}">
                    <div class="flex items-center gap-3">
                        <span class="material-symbols-outlined ${_pick(colorMap, h.type, '')}" style="font-size:20px;">${_pick(iconMap, h.type, 'call')}</span>
                        <div>
                            <p class="text-sm font-bold">${_esc(h.name || h.number)}</p>
                            <p class="text-[10px] opacity-50">${_esc(h.time || '')}</p>
                        </div>
                    </div>
                    <span class="text-[10px] opacity-40">${_esc(h.duration || '')}</span>
                </div>`).join("")
            }
        </div>`;
    }

    // The overlays read the call state from Phone themselves: render()'s
    // _callState/_callInfo are local to render(), and referencing them here
    // threw a ReferenceError — the screen broke exactly when a call started.
    function _renderCallOverlay(theme, accent, t) {
        const _callState = Phone._callState || "idle";
        const _callInfo = Phone._callInfo || {};
        if (_callState === "incoming") return "";
        return `<div class="absolute inset-0 z-50 flex flex-col items-center justify-center" style="background:rgba(0,0,0,0.9);">
            <span class="material-symbols-outlined text-6xl mb-4" style="color:${accent};">call</span>
            <p class="text-2xl font-bold">${_esc(_callInfo.name || _callInfo.number || "...")}</p>
            <p class="text-sm opacity-50 mt-1">${_callState === "ringing" ? t("calling","Calling...") : t("on_call","On call")}</p>
            <p id="call-duration" class="text-lg font-mono mt-4 opacity-60">00:00</p>
            <div class="flex gap-6 mt-6">
                <button class="w-14 h-14 rounded-full bg-zinc-700 text-white flex items-center justify-center" onclick="Phone.toggleMute()">
                    <span class="material-symbols-outlined">${_callInfo.muted ? 'mic_off' : 'mic'}</span>
                </button>
                <button class="w-16 h-16 rounded-full bg-red-600 text-white flex items-center justify-center active:scale-95" onclick="Phone.hangup()">
                    <span class="material-symbols-outlined text-2xl">call_end</span>
                </button>
            </div>
        </div>`;
    }

    function _renderIncomingOverlay(theme, accent, t) {
        const _callInfo = Phone._callInfo || {};
        return `<div class="absolute inset-0 z-50 flex flex-col items-center justify-center" style="background:rgba(0,0,0,0.95);">
            <span class="material-symbols-outlined text-6xl text-green-500 mb-4 animate-pulse">ring_volume</span>
            <p class="text-sm opacity-50 mb-1">${t("incoming_call","Incoming call")}</p>
            <p class="text-2xl font-bold">${_esc(_callInfo.name || _callInfo.number || "Unknown")}</p>
            <div class="flex gap-8 mt-8">
                <button class="w-16 h-16 rounded-full bg-red-600 text-white flex items-center justify-center active:scale-95" onclick="Phone.reject()">
                    <span class="material-symbols-outlined text-2xl">call_end</span>
                </button>
                <button class="w-16 h-16 rounded-full bg-green-600 text-white flex items-center justify-center active:scale-95" onclick="Phone.answer()">
                    <span class="material-symbols-outlined text-2xl">call</span>
                </button>
            </div>
        </div>`;
    }

    // What the last render() showed of the call. Phone._callState/_callInfo
    // are kept in sync with bt.call_state by app.js (_syncCallState) on EVERY
    // screen — that is also where an incoming call switches to A8. Here we
    // only re-render when the overlay on screen is out of date (state change,
    // or the caller's name arriving after the call itself).
    let _renderedCallKey = "";
    function _callKey() {
        return (Phone._callState || "idle") + "|" + JSON.stringify(Phone._callInfo || {});
    }

    function update(data) {
        if (_callKey() !== _renderedCallKey) App.navigateTo("a8");
    }

    return { render, update };
})());
