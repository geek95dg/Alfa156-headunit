/**
 * Settings Screen — Theme, Language, Units, Bluetooth, WiFi.
 * BT state lives on the global Settings object for cross-scope access.
 */

const Settings = {
    _btPaired: [],
    _btDiscovered: [],
    _btScanning: false,

    async setUnit(type, value) {
        const body = {};
        if (type === "speed") body.speed_unit = value;
        else if (type === "temp") body.temp_unit = value;
        try {
            await fetch("/api/config", { method: "POST", headers: {"Content-Type":"application/json"}, body: JSON.stringify(body) });
            App.navigateTo("settings");
        } catch (e) {}
    },

    async btScan() {
        Settings._btScanning = true;
        App.navigateTo("settings");
        try { await fetch("/bt/scan", { method: "POST" }); } catch (e) {}
        setTimeout(() => Settings.btRefresh(), 3000);
    },

    async btConnect(addr) {
        try { await fetch(`/bt/connect/${addr}`, { method: "POST" }); } catch (e) {}
        setTimeout(() => Settings.btRefresh(), 1000);
    },

    async btDisconnect() {
        try { await fetch("/bt/disconnect", { method: "POST" }); } catch (e) {}
        setTimeout(() => Settings.btRefresh(), 1000);
    },

    async btPair(addr) {
        try { await fetch(`/bt/pair/${addr}`, { method: "POST" }); } catch (e) {}
        setTimeout(() => Settings.btRefresh(), 2000);
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
                            <button class="text-[9px] font-bold px-2 py-1 bg-zinc-800 rounded text-zinc-300 hover:bg-zinc-700"
                                    onclick="Settings.btScan()">
                                ${scanning ? `<span class="animate-pulse">${t("bt_scanning","Scanning...")}</span>` : t("bt_scan", "Scan")}
                            </button>
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
