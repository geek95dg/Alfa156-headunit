/**
 * Settings Screen — Theme, Language, Units, Bluetooth, WiFi.
 */

App.registerScreen("settings", (() => {
    let _btDevices = [];
    let _btScanning = false;

    function render(container, theme, data) {
        const config = App.getConfig();
        const t = App.t.bind(App);
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
                                ${_btScanning ? '...' : t("bt_scan", "Scan")}
                            </button>
                        </div>
                        <div id="bt-devices" class="flex-1 space-y-1 overflow-y-auto">
                            ${_btDevices.length === 0
                                ? `<p class="text-[10px] text-zinc-600 py-4 text-center">${t("bt_no_devices", "No devices. Tap Scan.")}</p>`
                                : _btDevices.map(d => `<div class="flex justify-between items-center p-2 bg-zinc-800/50 rounded-lg">
                                    <div>
                                        <p class="text-xs font-bold">${d.name || d.address}</p>
                                        <p class="text-[9px] text-zinc-500">${d.address}</p>
                                    </div>
                                    <button class="text-[8px] font-bold px-2 py-1 rounded ${d.connected ? 'bg-green-700 text-white' : 'bg-zinc-700 text-zinc-300'}"
                                            onclick="Settings.btConnect('${d.address}')">
                                        ${d.connected ? t("bt_connected", "Connected") : t("bt_connect", "Connect")}
                                    </button>
                                </div>`).join("")
                            }
                        </div>
                    </div>
                </div>
                <button class="mt-3 px-4 py-2 bg-zinc-800 rounded-lg text-xs font-bold hover:bg-zinc-700" onclick="App.navigateTo('a1')">
                    \u2190 ${t("back_to_dash")}
                </button>
            </main>
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

const Settings = {
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
        try {
            await fetch("/bt/scan", { method: "POST" });
            setTimeout(() => Settings.btRefresh(), 3000);
        } catch (e) {}
    },
    async btConnect(addr) {
        try { await fetch(`/bt/connect/${addr}`, { method: "POST" }); } catch (e) {}
        setTimeout(() => App.navigateTo("settings"), 1000);
    },
    async btRefresh() {
        try {
            const res = await fetch("/bt/devices");
            const data = await res.json();
            // Reload settings to show devices
            App.navigateTo("settings");
        } catch (e) {}
    },
};
