/**
 * Settings Screen — Theme, Language, Units, Bluetooth, WiFi.
 * BT state lives on the global Settings object for cross-scope access.
 */

const Settings = {
    _btPaired: [],
    _btDiscovered: [],
    _btScanning: false,
    _swcMapping: null,
    _swcAllButtons: [],
    _swcActions: [],

    async setUnit(type, value) {
        const body = {};
        if (type === "speed") body.speed_unit = value;
        else if (type === "temp") body.temp_unit = value;
        try {
            await fetch("/api/config", { method: "POST", headers: {"Content-Type":"application/json"}, body: JSON.stringify(body) });
            App.navigateTo("settings");
        } catch (e) {}
    },

    async btMakeDiscoverable() {
        try { await fetch("/bt/discoverable", { method: "POST" }); } catch (e) {}
    },

    async btScan() {
        Settings._btScanning = true;
        App.navigateTo("settings");
        try { await fetch("/bt/scan", { method: "POST" }); } catch (e) {}
        // Backend scans for 15s — refresh at 10s and 16s to catch all devices
        setTimeout(() => Settings.btRefresh(), 10000);
        setTimeout(() => Settings.btRefresh(), 16000);
    },

    async btConnect(addr) {
        // Start pairing poll — connecting can also trigger PIN confirmation
        Settings._startPairingPoll();
        fetch(`/bt/connect/${addr}`, { method: "POST" })
            .then(() => Settings.btRefresh())
            .catch(() => {});
    },

    async btDisconnect() {
        try { await fetch("/bt/disconnect", { method: "POST" }); } catch (e) {}
        setTimeout(() => Settings.btRefresh(), 1000);
    },

    async btPair(addr) {
        console.log("[BT] Pairing:", addr);
        // Start polling for PIN popup FIRST (before the blocking pair request)
        Settings._startPairingPoll();
        // Fire pair request WITHOUT awaiting — backend blocks up to 30s during pairing
        fetch(`/bt/pair/${addr}`, { method: "POST" })
            .then(() => { console.log("[BT] Pair request completed"); Settings.btRefresh(); })
            .catch((e) => { console.error("[BT] Pair request failed:", e); });
    },

    _pairingPopupVisible: false,
    _pairingPoll: null,
    _pairingPollCount: 0,

    _startPairingPoll() {
        // Stop any existing poll
        if (Settings._pairingPoll) clearInterval(Settings._pairingPoll);
        Settings._pairingPollCount = 0;
        Settings._pairingPoll = setInterval(async () => {
            Settings._pairingPollCount++;
            if (Settings._pairingPollCount > 60) { // 30s timeout
                clearInterval(Settings._pairingPoll);
                Settings._pairingPoll = null;
                Settings._hidePairingPopup();
                Settings.btRefresh();
                return;
            }
            try {
                const res = await fetch("/bt/pairing");
                const data = await res.json();
                if (data.pending && data.request) {
                    Settings._showPairingPopup(data.request);
                } else if (Settings._pairingPopupVisible) {
                    // Pairing resolved — close popup
                    clearInterval(Settings._pairingPoll);
                    Settings._pairingPoll = null;
                    Settings._hidePairingPopup();
                    Settings.btRefresh();
                }
            } catch (e) {}
        }, 500);
    },

    _showPairingPopup(req) {
        if (Settings._pairingPopupVisible) return;
        Settings._pairingPopupVisible = true;
        const t = (App && App.t) ? App.t.bind(App) : (k, d) => d;
        let overlay = document.getElementById("bt-pairing-overlay");
        if (!overlay) {
            overlay = document.createElement("div");
            overlay.id = "bt-pairing-overlay";
            document.body.appendChild(overlay);
        }
        overlay.className = "fixed inset-0 z-[200] flex items-center justify-center";
        overlay.style.background = "rgba(0,0,0,0.85)";
        overlay.innerHTML = `<div class="bg-zinc-900 border border-zinc-700 rounded-2xl p-6 w-[360px] shadow-2xl text-white text-center">
            <span class="material-symbols-outlined text-4xl text-blue-400 mb-3">bluetooth</span>
            <h3 class="text-lg font-bold mb-2">${t("bt_pair_confirm","Confirm Pairing")}</h3>
            <p class="text-sm text-zinc-400 mb-4">${req.address}</p>
            <div class="bg-zinc-800 rounded-xl py-4 px-6 mb-4">
                <span class="text-3xl font-mono font-bold tracking-[0.3em] text-white">${req.passkey || "------"}</span>
            </div>
            <p class="text-[10px] text-zinc-500 mb-4">${t("bt_pair_match","Does this code match your device?")}</p>
            <div class="flex gap-3 justify-center">
                <button class="px-6 py-2 bg-zinc-700 rounded-lg text-sm font-bold hover:bg-zinc-600" onclick="Settings.btPairingRespond(false)">${t("reject","Reject")}</button>
                <button class="px-6 py-2 bg-green-600 rounded-lg text-sm font-bold hover:bg-green-500" onclick="Settings.btPairingRespond(true)">${t("answer","Accept")}</button>
            </div>
        </div>`;
    },

    _hidePairingPopup() {
        Settings._pairingPopupVisible = false;
        const overlay = document.getElementById("bt-pairing-overlay");
        if (overlay) overlay.remove();
    },

    async btPairingRespond(accept) {
        console.log("[BT] Pairing response:", accept);
        try {
            await fetch("/bt/pairing/confirm", {
                method: "POST",
                headers: {"Content-Type": "application/json"},
                body: JSON.stringify({accept}),
            });
        } catch (e) {}
        if (Settings._pairingPoll) clearInterval(Settings._pairingPoll);
        Settings._hidePairingPopup();
        setTimeout(() => Settings.btRefresh(), 1000);
    },

    async btRemove(addr) {
        try { await fetch(`/bt/remove/${addr}`, { method: "POST" }); } catch (e) {}
        setTimeout(() => Settings.btRefresh(), 1000);
    },

    async btRefresh() {
        try {
            const res = await fetch("/bt/devices");
            const data = await res.json();
            Settings._btPaired = data.paired || [];
            Settings._btDiscovered = data.discovered || [];
            Settings._btScanning = false;
            App.navigateTo("settings");
        } catch (e) {
            Settings._btScanning = false;
        }
    },

    async swcLoad() {
        try {
            const res = await fetch("/api/config/swc");
            const data = await res.json();
            Settings._swcMapping = data.mapping || {};
            Settings._swcAllButtons = data.all_buttons || [];
            Settings._swcActions = data.actions || [];
        } catch (e) {
            console.error("[SWC] Load failed:", e);
        }
    },

    async swcSave() {
        if (!Settings._swcMapping) return;
        try {
            await fetch("/api/config/swc", {
                method: "POST",
                headers: {"Content-Type": "application/json"},
                body: JSON.stringify({ mapping: Settings._swcMapping }),
            });
        } catch (e) {
            console.error("[SWC] Save failed:", e);
        }
    },

    swcSetButton(action, slotIndex, btnName) {
        if (!Settings._swcMapping || !Settings._swcMapping[action]) return;
        Settings._swcMapping[action][slotIndex] = btnName;
        Settings.swcSave();
        App.navigateTo("settings");
    },
};

App.registerScreen("settings", (() => {
    function render(container, theme, data) {
        const config = App.getConfig();
        const t = App.t.bind(App);
        const paired = Settings._btPaired;
        const discovered = Settings._btDiscovered;
        const scanning = Settings._btScanning;

        container.innerHTML = `<div class="screen-container bg-black text-white">
            ${AppBar.render(theme, data)}
            <main class="content-area p-4 overflow-y-auto">
                <div class="grid grid-cols-2 gap-3">
                    <!-- Left column -->
                    <div class="flex flex-col gap-3">
                        <!-- Theme -->
                        <div class="bg-zinc-900 rounded-xl p-3 border border-zinc-800">
                            <p class="text-[10px] font-bold text-zinc-400 uppercase tracking-wider mb-2">${t("theme")}</p>
                            <div class="flex gap-2">
                                ${_themeBtn("heritage", "Heritage", config.theme)}
                                ${_themeBtn("modern", "Modern", config.theme)}
                                ${_themeBtn("autodelta", "Autodelta", config.theme)}
                            </div>
                        </div>
                        <!-- Language + Units -->
                        <div class="bg-zinc-900 rounded-xl p-3 border border-zinc-800 flex gap-6">
                            <div>
                                <p class="text-[10px] font-bold text-zinc-400 uppercase tracking-wider mb-2">${t("language")}</p>
                                <div class="flex gap-2">
                                    ${_langBtn("pl", "PL", config.language)}
                                    ${_langBtn("en", "EN", config.language)}
                                </div>
                            </div>
                            <div>
                                <p class="text-[10px] font-bold text-zinc-400 uppercase tracking-wider mb-2">${t("speed_units")}</p>
                                <div class="flex gap-2">
                                    ${_unitBtn("km/h", "km/h", config.speed_unit, "speed")}
                                    ${_unitBtn("mph", "mph", config.speed_unit, "speed")}
                                </div>
                            </div>
                            <div>
                                <p class="text-[10px] font-bold text-zinc-400 uppercase tracking-wider mb-2">${t("temp_units")}</p>
                                <div class="flex gap-2">
                                    ${_unitBtn("C", "\u00b0C", config.temp_unit, "temp")}
                                    ${_unitBtn("F", "\u00b0F", config.temp_unit, "temp")}
                                </div>
                            </div>
                        </div>
                        <!-- WiFi AP -->
                        <div class="bg-zinc-900 rounded-xl p-3 border border-zinc-800">
                            <p class="text-[10px] font-bold text-zinc-400 uppercase tracking-wider mb-2">WiFi AP</p>
                            <div class="flex items-center justify-between">
                                <div>
                                    <p class="text-sm font-bold">SSID: <span class="text-zinc-400">ALFA</span></p>
                                    <p class="text-[10px] text-zinc-500">Android Auto wireless link</p>
                                </div>
                                <div class="w-10 h-6 bg-green-600 rounded-full flex items-center justify-end px-0.5 cursor-pointer">
                                    <div class="w-5 h-5 bg-white rounded-full"></div>
                                </div>
                            </div>
                        </div>
                    </div>
                    <!-- Right column: Bluetooth -->
                    <div class="bg-zinc-900 rounded-xl p-3 border border-zinc-800 flex flex-col">
                        <div class="flex justify-between items-center mb-2">
                            <p class="text-[10px] font-bold text-zinc-400 uppercase tracking-wider">Bluetooth</p>
                            <div class="flex gap-1">
                                <button class="text-[9px] font-bold px-2 py-1 bg-zinc-800 rounded text-zinc-300 hover:bg-zinc-700"
                                        onclick="Settings.btMakeDiscoverable()">
                                    ${t("bt_discoverable","Discoverable")}
                                </button>
                                <button class="text-[9px] font-bold px-2 py-1 bg-zinc-800 rounded text-zinc-300 hover:bg-zinc-700"
                                        onclick="Settings.btScan()">
                                    ${scanning ? `<span class="animate-pulse">${t("bt_scanning","Scanning...")}</span>` : t("bt_scan", "Scan")}
                                </button>
                            </div>
                        </div>
                        <div class="flex-1 space-y-1 overflow-y-auto">
                            ${paired.length > 0 ? `
                                <p class="text-[8px] font-bold text-zinc-500 uppercase tracking-widest mt-1 mb-1">${t("bt_paired","Paired")}</p>
                                ${paired.map(d => _renderDevice(d, "paired", t)).join("")}
                            ` : ""}
                            ${discovered.length > 0 ? `
                                <p class="text-[8px] font-bold text-zinc-500 uppercase tracking-widest mt-2 mb-1">${t("bt_discovered","Discovered")}</p>
                                ${discovered.map(d => _renderDevice(d, "discovered", t)).join("")}
                            ` : ""}
                            ${paired.length === 0 && discovered.length === 0
                                ? `<p class="text-[10px] text-zinc-600 py-4 text-center">${t("bt_no_devices", "No devices. Tap Scan.")}</p>`
                                : ""}
                        </div>
                    </div>
                </div>
                <!-- SWC Button Mapping -->
                <div class="bg-zinc-900 rounded-xl p-3 border border-zinc-800 mt-3">
                    <p class="text-[10px] font-bold text-zinc-400 uppercase tracking-wider mb-2">SWC Button Mapping</p>
                    ${_renderSwcTable()}
                </div>
                <button class="mt-3 px-4 py-2 bg-zinc-800 rounded-lg text-xs font-bold hover:bg-zinc-700" onclick="App.navigateTo('a1')">
                    \u2190 ${t("back_to_dash")}
                </button>
            </main>
        </div>`;
    }

    function _renderDevice(d, type, t) {
        const isConnected = d.connected === true;
        const isPaired = type === "paired";
        const statusBadge = isConnected
            ? `<span class="text-[7px] font-bold px-1.5 py-0.5 rounded bg-green-600/20 text-green-400">${t("bt_connected","Connected")}</span>`
            : isPaired
                ? `<span class="text-[7px] font-bold px-1.5 py-0.5 rounded bg-zinc-700 text-zinc-400">${t("bt_paired","Paired")}</span>`
                : `<span class="text-[7px] font-bold px-1.5 py-0.5 rounded bg-blue-600/20 text-blue-400">New</span>`;

        let actions = "";
        if (type === "discovered") {
            actions = `<button class="text-[8px] font-bold px-2 py-1 rounded bg-blue-600 text-white hover:bg-blue-500" onclick="Settings.btPair('${d.address}')">${t("bt_pair","Pair")}</button>`;
        } else if (isConnected) {
            actions = `<button class="text-[8px] font-bold px-2 py-1 rounded bg-red-600/20 text-red-400 hover:bg-red-600/30" onclick="Settings.btDisconnect()">${t("bt_disconnect","Disconnect")}</button>`;
        } else {
            actions = `<div class="flex gap-1">
                <button class="text-[8px] font-bold px-2 py-1 rounded bg-green-700 text-white hover:bg-green-600" onclick="Settings.btConnect('${d.address}')">${t("bt_connect","Connect")}</button>
                <button class="text-[8px] font-bold px-1.5 py-1 rounded bg-zinc-700 text-zinc-300 hover:bg-zinc-600" onclick="Settings.btRemove('${d.address}')" title="${t("bt_remove","Remove")}">
                    <span class="material-symbols-outlined" style="font-size:12px;">delete</span>
                </button>
            </div>`;
        }

        return `<div class="flex justify-between items-center p-2 bg-zinc-800/50 rounded-lg ${isConnected ? 'border border-green-600/30' : ''}">
            <div class="flex items-center gap-2">
                <span class="material-symbols-outlined ${isConnected ? 'text-green-500' : 'text-zinc-500'}" style="font-size:16px;">bluetooth</span>
                <div>
                    <div class="flex items-center gap-2">
                        <p class="text-xs font-bold">${d.name || d.address}</p>
                        ${statusBadge}
                    </div>
                    <p class="text-[9px] text-zinc-500">${d.address}</p>
                </div>
            </div>
            ${actions}
        </div>`;
    }

    function _actionLabel(action) {
        const labels = {
            volume_up: "Volume Up", volume_down: "Volume Down", mute: "Mute",
            menu_up: "Menu Up", menu_down: "Menu Down", next_track: "Next Track",
            prev_track: "Prev Track", play_pause: "Play/Pause",
            phone_pickup: "Phone Pickup", phone_hangup: "Phone Hangup",
            bcm_power_toggle: "Power Toggle", voice_aa_trigger: "AA Voice",
            navigate_aa: "Open AA", home: "Home", back: "Back",
            source_cycle: "Source Cycle", brightness_cycle: "Brightness",
        };
        return labels[action] || action;
    }

    function _renderSwcTable() {
        const m = Settings._swcMapping;
        if (!m) {
            Settings.swcLoad().then(() => App.navigateTo("settings"));
            return '<p class="text-[10px] text-zinc-500">Loading...</p>';
        }
        const allBtns = Settings._swcAllButtons;
        const actions = Object.keys(m);
        let html = '<table class="w-full text-[10px]">';
        html += '<thead><tr class="text-zinc-500 uppercase tracking-wider">';
        html += '<th class="text-left py-1 font-bold">Action</th>';
        html += '<th class="text-left py-1 font-bold">Pod 1 Button</th>';
        html += '<th class="text-left py-1 font-bold">Pod 2 Button</th></tr></thead>';
        html += '<tbody>';
        for (const action of actions) {
            const btns = m[action] || ["", ""];
            html += `<tr class="border-t border-zinc-800">`;
            html += `<td class="py-1.5 text-zinc-300 font-bold">${_actionLabel(action)}</td>`;
            for (let slot = 0; slot < 2; slot++) {
                const cur = btns[slot] || "";
                html += `<td class="py-1.5"><select class="bg-zinc-800 text-zinc-300 text-[10px] rounded px-1 py-0.5 border border-zinc-700" onchange="Settings.swcSetButton('${action}',${slot},this.value)">`;
                html += `<option value=""${cur === "" ? " selected" : ""}>-- None --</option>`;
                for (const b of allBtns) {
                    html += `<option value="${b}"${b === cur ? " selected" : ""}>${b}</option>`;
                }
                html += '</select></td>';
            }
            html += '</tr>';
        }
        html += '</tbody></table>';
        return html;
    }

    function _themeBtn(v, label, current) {
        const cls = v === current ? "bg-red-600 text-white border-red-600" : "bg-zinc-800 text-zinc-300 border-zinc-700 hover:border-zinc-500";
        return `<button class="px-3 py-1.5 rounded-lg text-xs font-bold border ${cls}" onclick="App.setTheme('${v}')">${label}</button>`;
    }
    function _langBtn(v, label, current) {
        const cls = v === current ? "bg-zinc-600 text-white" : "bg-zinc-800 text-zinc-400 hover:bg-zinc-700";
        return `<button class="px-2 py-1 rounded text-xs font-bold ${cls}" onclick="App.setLang('${v}')">${label}</button>`;
    }
    function _unitBtn(v, label, current, type) {
        const cls = v === current ? "bg-zinc-600 text-white" : "bg-zinc-800 text-zinc-400 hover:bg-zinc-700";
        return `<button class="px-2 py-1 rounded text-xs font-bold ${cls}" onclick="Settings.setUnit('${type}','${v}')">${label}</button>`;
    }

    return { render };
})());
