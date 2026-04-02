/**
 * A8 Phone Screen — BT dialer, contacts (PBAP), call history.
 * Tabs: Dialer | Contacts | History
 * Incoming call overlay with accept/reject.
 */

App.registerScreen("a8", (() => {
    let _tab = "dialer"; // "dialer" | "contacts" | "history"
    let _dialInput = "";
    let _contacts = [];
    let _history = [];
    let _callState = "idle"; // "idle" | "ringing" | "active" | "incoming"
    let _callInfo = {};
    let _contactsFilter = "";

    function render(container, theme, data) {
        const t = App.t.bind(App);
        const bgCls = theme === "modern" ? "bg-slate-100 text-slate-900" : "bg-black text-white";
        const cardBg = theme === "modern" ? "bg-white border-slate-200 shadow-sm" : "bg-zinc-900 border-zinc-800";
        const accentClr = theme === "autodelta" ? "#FF5F00" : theme === "modern" ? "#005596" : "#f59e0b";
        const tabActive = theme === "modern" ? "bg-blue-600 text-white" : "bg-zinc-700 text-white";
        const tabInactive = theme === "modern" ? "bg-slate-200 text-slate-600" : "bg-zinc-800 text-zinc-400";

        const callActive = _callState !== "idle";

        container.innerHTML = `<div class="screen-container ${bgCls}">
            ${AppBar.render(theme, data)}
            <main class="content-area flex flex-col p-3 relative">
                <!-- Tab bar -->
                <div class="flex gap-2 mb-3 shrink-0">
                    <button class="px-4 py-1.5 rounded-lg text-xs font-bold ${_tab==='dialer'?tabActive:tabInactive}" onclick="Phone.setTab('dialer')">
                        <span class="material-symbols-outlined mr-1" style="font-size:14px;vertical-align:-2px;">dialpad</span>${t("dialer","Dialer")}
                    </button>
                    <button class="px-4 py-1.5 rounded-lg text-xs font-bold ${_tab==='contacts'?tabActive:tabInactive}" onclick="Phone.setTab('contacts')">
                        <span class="material-symbols-outlined mr-1" style="font-size:14px;vertical-align:-2px;">contacts</span>${t("contacts","Contacts")}
                    </button>
                    <button class="px-4 py-1.5 rounded-lg text-xs font-bold ${_tab==='history'?tabActive:tabInactive}" onclick="Phone.setTab('history')">
                        <span class="material-symbols-outlined mr-1" style="font-size:14px;vertical-align:-2px;">history</span>${t("call_history","History")}
                    </button>
                </div>

                <!-- Tab content -->
                <div class="flex-1 overflow-hidden">
                    ${_tab === "dialer" ? _renderDialer(theme, cardBg, accentClr, t) : ""}
                    ${_tab === "contacts" ? _renderContacts(theme, cardBg, accentClr, t) : ""}
                    ${_tab === "history" ? _renderHistory(theme, cardBg, accentClr, t) : ""}
                </div>

                <!-- Active call overlay -->
                ${callActive ? _renderCallOverlay(theme, accentClr, t) : ""}
                <!-- Incoming call overlay -->
                ${_callState === "incoming" ? _renderIncomingOverlay(theme, accentClr, t) : ""}
            </main>
            ${NavBar.render(theme, "a8")}
        </div>`;

        // Load contacts/history on first render
        if (_contacts.length === 0) Phone.loadContacts();
        if (_history.length === 0) Phone.loadHistory();
    }

    function _renderDialer(theme, cardBg, accent, t) {
        const keys = ["1","2","3","4","5","6","7","8","9","*","0","#"];
        const keyBg = theme === "modern" ? "bg-slate-50 hover:bg-slate-100 text-slate-900" : "bg-zinc-800 hover:bg-zinc-700 text-white";

        return `<div class="flex flex-col items-center h-full">
            <!-- Number display -->
            <div class="text-3xl font-bold tracking-wider mb-3 h-10" style="color:${accent};">${_dialInput || "\u00a0"}</div>
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
        const filtered = _contactsFilter
            ? _contacts.filter(c => c.name.toLowerCase().includes(_contactsFilter.toLowerCase()))
            : _contacts;

        return `<div class="flex flex-col h-full">
            <div class="flex items-center gap-2 ${filterBg} border rounded-lg px-3 py-1.5 mb-2 shrink-0">
                <span class="material-symbols-outlined opacity-40" style="font-size:18px;">search</span>
                <input type="text" value="${_contactsFilter}" placeholder="${t("search_contacts","Search...")}"
                       class="bg-transparent border-none outline-none text-sm flex-1 p-0"
                       oninput="Phone.filterContacts(this.value)">
            </div>
            <div class="flex-1 overflow-y-auto space-y-1">
                ${filtered.length === 0
                    ? `<div class="flex flex-col items-center justify-center py-8 opacity-30">
                        <span class="material-symbols-outlined text-4xl mb-2">person_off</span>
                        <span class="text-sm font-bold">${t("no_contacts","No contacts synced")}</span>
                       </div>`
                    : filtered.map(c => `<div class="${cardBg} border rounded-lg p-2 flex justify-between items-center cursor-pointer hover:opacity-80" onclick="Phone.dialNumber('${c.number}')">
                        <div class="flex items-center gap-3">
                            <div class="w-8 h-8 rounded-full flex items-center justify-center text-xs font-bold" style="background:${accent}20;color:${accent};">${c.name.charAt(0)}</div>
                            <div>
                                <p class="text-sm font-bold">${c.name}</p>
                                <p class="text-[10px] opacity-50">${c.number}</p>
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
            ${_history.length === 0
                ? `<div class="flex flex-col items-center justify-center py-8 opacity-30">
                    <span class="material-symbols-outlined text-4xl mb-2">history</span>
                    <span class="text-sm font-bold">${t("no_history","No call history")}</span>
                   </div>`
                : _history.map(h => `<div class="${cardBg} border rounded-lg p-2 flex justify-between items-center cursor-pointer hover:opacity-80" onclick="Phone.dialNumber('${h.number}')">
                    <div class="flex items-center gap-3">
                        <span class="material-symbols-outlined ${colorMap[h.type]||''}" style="font-size:20px;">${iconMap[h.type]||'call'}</span>
                        <div>
                            <p class="text-sm font-bold">${h.name || h.number}</p>
                            <p class="text-[10px] opacity-50">${h.time || ''}</p>
                        </div>
                    </div>
                    <span class="text-[10px] opacity-40">${h.duration || ''}</span>
                </div>`).join("")
            }
        </div>`;
    }

    function _renderCallOverlay(theme, accent, t) {
        if (_callState === "incoming") return "";
        return `<div class="absolute inset-0 z-50 flex flex-col items-center justify-center" style="background:rgba(0,0,0,0.9);">
            <span class="material-symbols-outlined text-6xl mb-4" style="color:${accent};">call</span>
            <p class="text-2xl font-bold">${_callInfo.name || _callInfo.number || "..."}</p>
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
        return `<div class="absolute inset-0 z-50 flex flex-col items-center justify-center" style="background:rgba(0,0,0,0.95);">
            <span class="material-symbols-outlined text-6xl text-green-500 mb-4 animate-pulse">ring_volume</span>
            <p class="text-sm opacity-50 mb-1">${t("incoming_call","Incoming call")}</p>
            <p class="text-2xl font-bold">${_callInfo.name || _callInfo.number || "Unknown"}</p>
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

    function update(data) {
        // Update call state from event bus
        if (data.bt_call_state && data.bt_call_state !== _callState) {
            _callState = data.bt_call_state;
            _callInfo = data.bt_call_info || {};
            App.navigateTo("a8"); // Re-render
        }
    }

    return { render, update };
})());

// Phone API object
const Phone = {
    setTab(tab) { Phone._tab = tab; App.navigateTo("a8"); },
    _tab: "dialer",

    key(k) {
        const screen = App._renderers?.a8;
        if (k === "del") {
            Phone._input = (Phone._input || "").slice(0, -1);
        } else {
            Phone._input = (Phone._input || "") + k;
        }
        App.navigateTo("a8");
    },
    _input: "",

    dialNumber(num) {
        Phone._input = num;
        Phone._tab = "dialer";
        App.navigateTo("a8");
    },

    async dial() {
        if (!Phone._input) return;
        try {
            await fetch("/api/phone/dial", {
                method: "POST",
                headers: {"Content-Type": "application/json"},
                body: JSON.stringify({number: Phone._input}),
            });
        } catch (e) {}
    },

    async answer() {
        try { await fetch("/api/phone/answer", {method: "POST"}); } catch (e) {}
    },

    async reject() {
        try { await fetch("/api/phone/hangup", {method: "POST"}); } catch (e) {}
    },

    async hangup() {
        try { await fetch("/api/phone/hangup", {method: "POST"}); } catch (e) {}
    },

    toggleMute() {
        // Toggle mic mute via event bus
        DataStore.sendKey("mute_mic");
    },

    filterContacts(val) {
        Phone._contactsFilter = val;
        App.navigateTo("a8");
    },
    _contactsFilter: "",

    async loadContacts() {
        try {
            const res = await fetch("/api/phone/contacts");
            const data = await res.json();
            // Store in closure — re-render will pick up
        } catch (e) {}
    },

    async loadHistory() {
        try {
            const res = await fetch("/api/phone/history");
            const data = await res.json();
        } catch (e) {}
    },
};
