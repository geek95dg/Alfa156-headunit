/**
 * Settings Screen — Theme, Language, Units, Bluetooth, WiFi, SWC Mapping.
 * Theme-aware via CSS custom properties (--card-bg, --card-border, etc.).
 * SWC uses a learn mode: press "Configure" then press a button on the pod.
 */

const Settings = {
    _btPaired: [],
    _btDiscovered: [],
    _btScanning: false,
    _swcMapping: null,
    _swcAllButtons: [],
    _swcActions: [],
    _swcLearning: null,
    _swcLearnTimer: null,
    _radio: { bt: { available: false, powered: false },
              wifi: { available: false, running: false, ssid: "" } },
    _radioBusy: false,
    // Editable Android Auto wireless / Wi-Fi AP credentials. Loaded
    // from /api/wifi/config on first render of the AA Wireless card.
    _wifi: { ssid: "", password: "", channel: 6,
             loaded: false, saving: false, showPwd: false,
             restartRequired: false, status: "" },

    async radioRefresh() {
        try {
            const res = await fetch("/api/radio/status");
            Settings._radio = await res.json();
        } catch (e) { /* keep last known state */ }
    },

    async toggleBT() {
        if (Settings._radioBusy) return;
        Settings._radioBusy = true;
        const next = !Settings._radio.bt.powered;
        // Optimistic UI flip so the toggle visibly responds while the
        // backend works (rfkill + bluetoothctl can take ~1s).
        Settings._radio.bt.powered = next;
        App.navigateTo("settings");
        try {
            const res = await fetch("/api/radio/bt", {
                method: "POST",
                headers: {"Content-Type": "application/json"},
                body: JSON.stringify({enabled: next}),
            });
            const d = await res.json();
            Settings._radio.bt.powered = !!d.powered;
        } catch (e) {
            Settings._radio.bt.powered = !next;
        }
        Settings._radioBusy = false;
        await Settings.radioRefresh();
        App.navigateTo("settings");
    },

    async toggleWiFi() {
        if (Settings._radioBusy) return;
        Settings._radioBusy = true;
        const next = !Settings._radio.wifi.running;
        Settings._radio.wifi.running = next;
        App.navigateTo("settings");
        try {
            const res = await fetch("/api/radio/wifi", {
                method: "POST",
                headers: {"Content-Type": "application/json"},
                body: JSON.stringify({enabled: next}),
            });
            const d = await res.json();
            Settings._radio.wifi.running = !!d.running;
        } catch (e) {
            Settings._radio.wifi.running = !next;
        }
        Settings._radioBusy = false;
        // Toggling resolves any pending "restart needed" state.
        Settings._wifi.restartRequired = false;
        await Settings.radioRefresh();
        App.navigateTo("settings");
    },

    _wifiFetchedAt: 0,
    async wifiLoad(force) {
        // Throttle: this is invoked from render() and would otherwise
        // re-fire every time the JSON response triggers another
        // navigateTo("settings") → render() → wifiLoad() cycle. Cap
        // it at one refresh per 3 s (same gate as radioRefresh), or
        // pass force=true on user actions that need fresh values.
        const now = Date.now();
        if (!force && now - Settings._wifiFetchedAt < 3000) return;
        Settings._wifiFetchedAt = now;
        try {
            const res = await fetch("/api/wifi/config");
            if (!res.ok) return;
            const d = await res.json();
            Settings._wifi.ssid = d.ssid || "";
            Settings._wifi.password = d.password || "";
            Settings._wifi.channel = d.channel || 6;
            Settings._wifi.mode = d.mode || "p2p_go";
            Settings._wifi.live_ssid = d.live_ssid || "";
            Settings._wifi.live_password = d.live_password || "";
            Settings._wifi.live_bssid = d.live_bssid || "";
            Settings._wifi.alfa_net_enabled = d.alfa_net_enabled !== false;
            Settings._wifi.alfa_net_ssid = d.alfa_net_ssid || "ALFA-NET";
            Settings._wifi.alfa_net_password = d.alfa_net_password || "";
            Settings._wifi.loaded = true;
            App.navigateTo("settings");
        } catch (e) {}
    },

    wifiUpdate(field, value) {
        if (field === "channel") {
            const n = parseInt(value, 10);
            Settings._wifi.channel = Number.isFinite(n) ? n : value;
        } else {
            Settings._wifi[field] = value;
        }
    },

    wifiTogglePwd() {
        Settings._wifi.showPwd = !Settings._wifi.showPwd;
        App.navigateTo("settings");
    },

    async wifiSave() {
        const ssid = (Settings._wifi.ssid || "").trim();
        const pwd = Settings._wifi.password || "";
        const ch = parseInt(Settings._wifi.channel, 10);
        const valid5 = new Set([36, 40, 44, 48, 149, 153, 157, 161, 165]);
        if (!ssid || ssid.length > 32) {
            Settings._wifi.status = "SSID required (1-32 chars)";
            App.navigateTo("settings");
            return;
        }
        if (pwd.length < 8 || pwd.length > 63) {
            Settings._wifi.status = "Password must be 8-63 chars";
            App.navigateTo("settings");
            return;
        }
        if (!Number.isFinite(ch) || !((ch >= 1 && ch <= 13) || valid5.has(ch))) {
            Settings._wifi.status = "Channel must be 1-13 or 36-165 (5 GHz)";
            App.navigateTo("settings");
            return;
        }
        // ALFA-NET secondary AP — only validate when changed from defaults.
        const anSsid = (Settings._wifi.alfa_net_ssid || "").trim();
        const anPwd = Settings._wifi.alfa_net_password || "";
        if (anPwd && (anPwd.length < 8 || anPwd.length > 63)) {
            Settings._wifi.status = "ALFA-NET password must be 8-63 chars";
            App.navigateTo("settings");
            return;
        }
        Settings._wifi.saving = true;
        Settings._wifi.status = "";
        App.navigateTo("settings");
        try {
            const res = await fetch("/api/wifi/config", {
                method: "POST",
                headers: {"Content-Type": "application/json"},
                body: JSON.stringify({
                    ssid, password: pwd, channel: ch,
                    alfa_net_enabled: !!Settings._wifi.alfa_net_enabled,
                    alfa_net_ssid: anSsid,
                    alfa_net_password: anPwd,
                }),
            });
            const d = await res.json();
            if (d.ok === false || d.error) {
                Settings._wifi.status = d.error || "Save failed";
            } else {
                Settings._wifi.restartRequired = !!d.restart_required;
                Settings._wifi.status = d.restart_required
                    ? "Saved — toggle Wi-Fi AP to apply"
                    : "Saved";
            }
        } catch (e) {
            Settings._wifi.status = "Save failed (network)";
        }
        Settings._wifi.saving = false;
        await Settings.radioRefresh();
        App.navigateTo("settings");
    },

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
        try {
            await fetch("/bt/discoverable", { method: "POST" });
        } catch (e) {}
        await Settings.btRefresh();
    },

    async btScan() {
        Settings._btScanning = true;
        App.navigateTo("settings");
        try {
            await fetch("/bt/scan", { method: "POST" });
        } catch (e) {}
        // Server-side scan runs ~15 s; refresh once at 10 s for early
        // discovered devices and again at 16 s to clear the spinner.
        setTimeout(() => Settings.btRefresh(), 10000);
        setTimeout(() => Settings.btRefresh(), 16000);
    },

    async btConnect(addr) {
        try {
            await fetch(`/bt/connect/${addr}`, { method: "POST" });
        } catch (e) {}
        await Settings.btRefresh();
    },

    async btDisconnect() {
        try {
            await fetch("/bt/disconnect", { method: "POST" });
        } catch (e) {}
        await Settings.btRefresh();
    },

    async btPair(addr) {
        console.log("[BT] Pairing:", addr);
        Settings._startPairingPoll();
        try {
            await fetch(`/bt/pair/${addr}`, { method: "POST" });
            console.log("[BT] Pair request completed");
        } catch (e) {
            console.error("[BT] Pair request failed:", e);
        }
        await Settings.btRefresh();
    },

    _pairingPopupVisible: false,
    _pairingPoll: null,
    _pairingPollCount: 0,

    _startPairingPoll() {
        if (Settings._pairingPoll) clearInterval(Settings._pairingPoll);
        Settings._pairingPollCount = 0;
        Settings._pairingPoll = setInterval(async () => {
            Settings._pairingPollCount++;
            if (Settings._pairingPollCount > 60) {
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
        overlay.innerHTML = `<div style="background:var(--card-bg);border:1px solid var(--card-border)" class="rounded-2xl p-6 w-[360px] shadow-2xl text-center" style="color:var(--text-primary)">
            <span class="material-symbols-outlined text-4xl text-blue-400 mb-3">bluetooth</span>
            <h3 class="text-lg font-bold mb-2" style="color:var(--text-primary)">${t("bt_pair_confirm","Confirm Pairing")}</h3>
            <p class="text-sm mb-4" style="color:var(--text-dim)">${req.address}</p>
            <div class="rounded-xl py-4 px-6 mb-4" style="background:var(--color-surface)">
                <span class="text-3xl font-mono font-bold tracking-[0.3em]" style="color:var(--text-primary)">${req.passkey || "------"}</span>
            </div>
            <p class="text-[10px] mb-4" style="color:var(--text-dim)">${t("bt_pair_match","Does this code match your device?")}</p>
            <div class="flex gap-3 justify-center">
                <button class="px-6 py-2 rounded-lg text-sm font-bold" style="background:var(--card-border);color:var(--text-mid)" onclick="Settings.btPairingRespond(false)">${t("reject","Reject")}</button>
                <button class="px-6 py-2 bg-green-600 rounded-lg text-sm font-bold text-white hover:bg-green-500" onclick="Settings.btPairingRespond(true)">${t("answer","Accept")}</button>
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

    swcLearnStart(action, pod) {
        Settings._swcLearning = { action, pod };
        App.navigateTo("settings");
        fetch("/api/config/swc/learn", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({ action, pod }),
        });
        if (Settings._swcLearnTimer) clearInterval(Settings._swcLearnTimer);
        Settings._swcLearnTimer = setInterval(async () => {
            try {
                const res = await fetch("/api/config/swc/learn");
                const data = await res.json();
                if (!data.active) {
                    clearInterval(Settings._swcLearnTimer);
                    Settings._swcLearnTimer = null;
                    if (data.result && Settings._swcMapping) {
                        if (!Settings._swcMapping[action]) Settings._swcMapping[action] = ["", ""];
                        Settings._swcMapping[action][pod] = data.result;
                    }
                    Settings._swcLearning = null;
                    App.navigateTo("settings");
                }
            } catch (e) {}
        }, 500);
    },

    swcLearnCancel() {
        if (Settings._swcLearnTimer) clearInterval(Settings._swcLearnTimer);
        Settings._swcLearnTimer = null;
        Settings._swcLearning = null;
        App.navigateTo("settings");
    },
};

App.registerScreen("settings", (() => {
    let _radioFetchedAt = 0;
    function render(container, theme, data) {
        const config = App.getConfig();
        const t = App.t.bind(App);
        const paired = Settings._btPaired;
        const discovered = Settings._btDiscovered;
        const scanning = Settings._btScanning;

        // Refresh radio status (BT power + WiFi AP) at most once every
        // 3s while the user is poking at settings — guarantees the
        // toggles reflect reality after rfkill/systemctl side-effects
        // settle without spamming the API on every keystroke re-render.
        const now = Date.now();
        if (now - _radioFetchedAt > 3000) {
            _radioFetchedAt = now;
            Settings.radioRefresh().then(() => App.navigateTo("settings"));
        }
        Settings.wifiLoad();

        container.innerHTML = `<div class="screen-container" style="background:var(--color-surface);color:var(--color-on-surface)">
            ${AppBar.render(theme, data)}
            <main class="content-area p-4 overflow-y-auto">
                <div class="grid grid-cols-2 gap-3">
                    <!-- Left column -->
                    <div class="flex flex-col gap-3">
                        <!-- Theme -->
                        <div class="rounded-xl p-3" style="background:var(--card-bg);border:1px solid var(--card-border)">
                            <p class="text-[10px] font-bold uppercase tracking-wider mb-2" style="color:var(--text-dim)">${t("theme")}</p>
                            <div class="flex gap-2">
                                ${_themeBtn("heritage", "Heritage", config.theme)}
                                ${_themeBtn("modern", "Modern", config.theme)}
                                ${_themeBtn("autodelta", "Autodelta", config.theme)}
                            </div>
                        </div>
                        <!-- Language + Units -->
                        <div class="rounded-xl p-3 flex gap-6" style="background:var(--card-bg);border:1px solid var(--card-border)">
                            <div>
                                <p class="text-[10px] font-bold uppercase tracking-wider mb-2" style="color:var(--text-dim)">${t("language")}</p>
                                <div class="flex gap-2">
                                    ${_langBtn("pl", "PL", config.language)}
                                    ${_langBtn("en", "EN", config.language)}
                                </div>
                            </div>
                            <div>
                                <p class="text-[10px] font-bold uppercase tracking-wider mb-2" style="color:var(--text-dim)">${t("speed_units")}</p>
                                <div class="flex gap-2">
                                    ${_unitBtn("km/h", "km/h", config.speed_unit, "speed")}
                                    ${_unitBtn("mph", "mph", config.speed_unit, "speed")}
                                </div>
                            </div>
                            <div>
                                <p class="text-[10px] font-bold uppercase tracking-wider mb-2" style="color:var(--text-dim)">${t("temp_units")}</p>
                                <div class="flex gap-2">
                                    ${_unitBtn("C", "\u00b0C", config.temp_unit, "temp")}
                                    ${_unitBtn("F", "\u00b0F", config.temp_unit, "temp")}
                                </div>
                            </div>
                        </div>
                        <!-- Android Auto Wireless / Wi-Fi AP credentials -->
                        <div class="rounded-xl p-3" style="background:var(--card-bg);border:1px solid var(--card-border)">
                            <p class="text-[10px] font-bold uppercase tracking-wider mb-2" style="color:var(--text-dim)">${t("aa_wireless","Android Auto Wireless")}</p>
                            ${Settings._wifi.mode === "p2p_go" && Settings._wifi.live_ssid ? `
                            <!-- Live P2P-GO credentials — wpa_supplicant
                                 picks a fresh DIRECT-XX SSID + passphrase
                                 every boot, so the YAML defaults below
                                 aren't what the phone actually joins.
                                 Surface the live values here read-only. -->
                            <div class="rounded-lg p-2 mb-3" style="background:rgba(255,95,0,0.08);border:1px solid rgba(255,95,0,0.3)">
                                <p class="text-[9px] uppercase tracking-wider mb-1" style="color:#FF5F00">${t("live_ap","Live AP (read on phone)")}</p>
                                <div class="grid grid-cols-[auto_1fr] gap-x-2 gap-y-1 text-xs font-mono" style="color:var(--text-primary)">
                                    <span style="color:var(--text-dim)">SSID:</span><span data-bind="wifi_live_ssid">${_attrEsc(Settings._wifi.live_ssid)}</span>
                                    <span style="color:var(--text-dim)">PSK:</span><span data-bind="wifi_live_password" style="user-select:text;-webkit-user-select:text">${_attrEsc(Settings._wifi.live_password)}</span>
                                    ${Settings._wifi.live_bssid ? `<span style="color:var(--text-dim)">BSSID:</span><span class="text-[10px]" data-bind="wifi_live_bssid">${_attrEsc(Settings._wifi.live_bssid)}</span>` : ""}
                                </div>
                                <p class="text-[9px] mt-1" style="color:var(--text-dim)">${t("p2p_go_note","Wi-Fi Direct GO regenerates these on each boot. Phone gets them automatically over BT during AA pairing.")}</p>
                            </div>` : ""}
                            <p class="text-[9px] font-bold uppercase tracking-wider mb-1" style="color:var(--text-dim)">${t("defaults","Defaults (used in hostapd mode)")}</p>
                            <div class="space-y-2">
                                <div class="flex items-center gap-2">
                                    <label class="text-[9px] uppercase w-16" style="color:var(--text-dim)">SSID</label>
                                    <input type="text" maxlength="32" value="${_attrEsc(Settings._wifi.ssid)}"
                                        onfocus="OnScreenKeyboard.attach(this)"
                                        oninput="Settings.wifiUpdate('ssid', this.value)"
                                        class="flex-1 px-2 py-1 rounded text-xs"
                                        style="background:var(--color-surface);color:var(--text-primary);border:1px solid var(--card-border)">
                                </div>
                                <div class="flex items-center gap-2">
                                    <label class="text-[9px] uppercase w-16" style="color:var(--text-dim)">${t("password","Password")}</label>
                                    <input type="${Settings._wifi.showPwd ? 'text' : 'password'}" maxlength="63" value="${_attrEsc(Settings._wifi.password)}"
                                        onfocus="OnScreenKeyboard.attach(this)"
                                        oninput="Settings.wifiUpdate('password', this.value)"
                                        class="flex-1 px-2 py-1 rounded text-xs"
                                        style="background:var(--color-surface);color:var(--text-primary);border:1px solid var(--card-border)">
                                    <button onclick="Settings.wifiTogglePwd()"
                                        class="px-2 py-1 text-[9px] font-bold rounded"
                                        style="background:var(--card-border);color:var(--text-mid)">${Settings._wifi.showPwd ? t("hide","Hide") : t("show","Show")}</button>
                                </div>
                                <div class="flex items-center gap-2">
                                    <label class="text-[9px] uppercase w-16" style="color:var(--text-dim)">${t("channel","Channel")}</label>
                                    <input type="number" min="1" max="165" value="${Settings._wifi.channel}"
                                        oninput="Settings.wifiUpdate('channel', this.value)"
                                        class="w-16 px-2 py-1 rounded text-xs"
                                        style="background:var(--color-surface);color:var(--text-primary);border:1px solid var(--card-border)">
                                    <span class="text-[9px]" style="color:var(--text-dim)">${Settings._wifi.channel >= 36 ? "5 GHz" : "2.4 GHz"}</span>
                                    <button onclick="Settings.wifiSave()"
                                        ${Settings._wifi.saving ? 'disabled' : ''}
                                        class="ml-auto px-3 py-1 bg-green-600 text-white text-[10px] font-bold rounded hover:bg-green-500 ${Settings._wifi.saving ? 'opacity-50 cursor-not-allowed' : ''}">${Settings._wifi.saving ? t("saving","Saving...") : t("save","Save")}</button>
                                </div>
                                ${Settings._wifi.status ? `<p class="text-[10px]" style="color:var(--text-mid)">${Settings._wifi.status}</p>` : ""}
                                <!-- ALFA-NET secondary AP — broadcast in parallel for internet sharing -->
                                <div class="pt-2 space-y-2" style="border-top:1px solid var(--card-border)">
                                    <div class="flex items-center justify-between">
                                        <p class="text-[10px] font-bold uppercase tracking-wider" style="color:var(--text-dim)">${t("alfa_net","ALFA-NET (Internet share)")}</p>
                                        <label class="inline-flex items-center gap-1 text-[9px]" style="color:var(--text-dim)">
                                            <input type="checkbox" ${Settings._wifi.alfa_net_enabled ? 'checked' : ''}
                                                oninput="Settings.wifiUpdate('alfa_net_enabled', this.checked)">
                                            ${t("enabled","Enabled")}
                                        </label>
                                    </div>
                                    <div class="flex items-center gap-2">
                                        <label class="text-[9px] uppercase w-16" style="color:var(--text-dim)">SSID</label>
                                        <input type="text" maxlength="32" value="${_attrEsc(Settings._wifi.alfa_net_ssid || "ALFA-NET")}"
                                            onfocus="OnScreenKeyboard.attach(this)"
                                            oninput="Settings.wifiUpdate('alfa_net_ssid', this.value)"
                                            class="flex-1 px-2 py-1 rounded text-xs"
                                            style="background:var(--color-surface);color:var(--text-primary);border:1px solid var(--card-border)">
                                    </div>
                                    <div class="flex items-center gap-2">
                                        <label class="text-[9px] uppercase w-16" style="color:var(--text-dim)">${t("password","Password")}</label>
                                        <input type="${Settings._wifi.showAlfaPwd ? 'text' : 'password'}" maxlength="63" value="${_attrEsc(Settings._wifi.alfa_net_password || "")}"
                                            onfocus="OnScreenKeyboard.attach(this)"
                                            oninput="Settings.wifiUpdate('alfa_net_password', this.value)"
                                            class="flex-1 px-2 py-1 rounded text-xs"
                                            style="background:var(--color-surface);color:var(--text-primary);border:1px solid var(--card-border)">
                                        <button onclick="Settings._wifi.showAlfaPwd = !Settings._wifi.showAlfaPwd; App.navigateTo('settings')"
                                            class="px-2 py-1 text-[9px] font-bold rounded"
                                            style="background:var(--card-border);color:var(--text-mid)">${Settings._wifi.showAlfaPwd ? t("hide","Hide") : t("show","Show")}</button>
                                    </div>
                                </div>
                                <div class="flex items-center justify-between pt-2" style="border-top:1px solid var(--card-border)">
                                    <p class="text-[10px]" style="color:var(--text-dim)">${
                                        Settings._wifi.restartRequired
                                            ? t("wifi_restart_needed","Toggle Wi-Fi AP to apply new credentials")
                                            : (Settings._radio.wifi && Settings._radio.wifi.running
                                                ? t("wifi_ap_on","On — phones can connect")
                                                : t("wifi_ap_off","Off — phones can't connect"))
                                    }</p>
                                    ${_toggle(Settings._radio.wifi && Settings._radio.wifi.running, "Settings.toggleWiFi()")}
                                </div>
                            </div>
                        </div>
                    </div>
                    <!-- Right column: Bluetooth -->
                    <div class="rounded-xl p-3 flex flex-col" style="background:var(--card-bg);border:1px solid var(--card-border)">
                        <div class="flex justify-between items-center mb-2">
                            <div class="flex items-center gap-2">
                                <p class="text-[10px] font-bold uppercase tracking-wider" style="color:var(--text-dim)">Bluetooth</p>
                                ${_toggle(Settings._radio.bt && Settings._radio.bt.powered, "Settings.toggleBT()")}
                            </div>
                            <div class="flex gap-1">
                                <button class="text-[9px] font-bold px-2 py-1 rounded hover:opacity-80 ${(Settings._radio.bt && Settings._radio.bt.powered) ? '' : 'opacity-50 cursor-not-allowed'}"
                                        style="background:var(--card-border);color:var(--text-mid)"
                                        ${(Settings._radio.bt && Settings._radio.bt.powered) ? 'onclick="Settings.btMakeDiscoverable()"' : 'disabled'}>
                                    ${t("bt_discoverable","Discoverable")}
                                </button>
                                <button class="text-[9px] font-bold px-2 py-1 rounded hover:opacity-80 ${(Settings._radio.bt && Settings._radio.bt.powered) ? '' : 'opacity-50 cursor-not-allowed'}"
                                        style="background:var(--card-border);color:var(--text-mid)"
                                        ${(Settings._radio.bt && Settings._radio.bt.powered) ? 'onclick="Settings.btScan()"' : 'disabled'}>
                                    ${scanning ? `<span class="animate-pulse">${t("bt_scanning","Scanning...")}</span>` : t("bt_scan", "Scan")}
                                </button>
                            </div>
                        </div>
                        <div class="flex-1 space-y-1 overflow-y-auto">
                            ${paired.length > 0 ? `
                                <p class="text-[8px] font-bold uppercase tracking-widest mt-1 mb-1" style="color:var(--text-dim)">${t("bt_paired","Paired")}</p>
                                ${paired.map(d => _renderDevice(d, "paired", t)).join("")}
                            ` : ""}
                            ${discovered.length > 0 ? `
                                <p class="text-[8px] font-bold uppercase tracking-widest mt-2 mb-1" style="color:var(--text-dim)">${t("bt_discovered","Discovered")}</p>
                                ${discovered.map(d => _renderDevice(d, "discovered", t)).join("")}
                            ` : ""}
                            ${paired.length === 0 && discovered.length === 0
                                ? `<p class="text-[10px] py-4 text-center" style="color:var(--text-dim)">${t("bt_no_devices", "No devices. Tap Scan.")}</p>`
                                : ""}
                        </div>
                    </div>
                </div>
                <!-- Audio / EQ -->
                <div class="rounded-xl p-3 mt-3 cursor-pointer hover:opacity-80" style="background:var(--card-bg);border:1px solid var(--card-border)" onclick="App.navigateTo('audio')">
                    <div class="flex items-center gap-3">
                        <span class="material-symbols-outlined" style="color:var(--color-primary)">equalizer</span>
                        <div>
                            <p class="text-sm font-bold" style="color:var(--color-on-surface)">Audio / Equalizer</p>
                            <p class="text-[10px]" style="color:var(--text-dim)">EQ presets, bass, treble, fader</p>
                        </div>
                        <span class="material-symbols-outlined ml-auto" style="color:var(--text-dim)">chevron_right</span>
                    </div>
                </div>
                <!-- SWC Button Mapping -->
                <div class="rounded-xl p-3 mt-3" style="background:var(--card-bg);border:1px solid var(--card-border)">
                    <p class="text-[10px] font-bold uppercase tracking-wider mb-2" style="color:var(--text-dim)">SWC Button Mapping</p>
                    ${_renderSwcTable()}
                </div>
                <button class="mt-3 px-4 py-2 rounded-lg text-xs font-bold hover:opacity-80" style="background:var(--card-border);color:var(--text-mid)" onclick="App.navigateTo('a1')">
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
                ? `<span class="text-[7px] font-bold px-1.5 py-0.5 rounded" style="background:var(--card-border);color:var(--text-dim)">${t("bt_paired","Paired")}</span>`
                : `<span class="text-[7px] font-bold px-1.5 py-0.5 rounded bg-blue-600/20 text-blue-400">New</span>`;

        let actions = "";
        if (type === "discovered") {
            actions = `<button class="text-[8px] font-bold px-2 py-1 rounded bg-blue-600 text-white hover:bg-blue-500" onclick="Settings.btPair('${d.address}')">${t("bt_pair","Pair")}</button>`;
        } else if (isConnected) {
            actions = `<button class="text-[8px] font-bold px-2 py-1 rounded bg-red-600/20 text-red-400 hover:bg-red-600/30" onclick="Settings.btDisconnect()">${t("bt_disconnect","Disconnect")}</button>`;
        } else {
            actions = `<div class="flex gap-1">
                <button class="text-[8px] font-bold px-2 py-1 rounded bg-green-700 text-white hover:bg-green-600" onclick="Settings.btConnect('${d.address}')">${t("bt_connect","Connect")}</button>
                <button class="text-[8px] font-bold px-1.5 py-1 rounded hover:opacity-80" style="background:var(--card-border);color:var(--text-mid)" onclick="Settings.btRemove('${d.address}')" title="${t("bt_remove","Remove")}">
                    <span class="material-symbols-outlined" style="font-size:12px;">delete</span>
                </button>
            </div>`;
        }

        return `<div class="flex justify-between items-center p-2 rounded-lg ${isConnected ? 'border border-green-600/30' : ''}" style="background:color-mix(in srgb, var(--card-bg) 80%, var(--card-border))">
            <div class="flex items-center gap-2">
                <span class="material-symbols-outlined ${isConnected ? 'text-green-500' : ''}" style="font-size:16px;${isConnected ? '' : 'color:var(--text-dim)'}">bluetooth</span>
                <div>
                    <div class="flex items-center gap-2">
                        <p class="text-xs font-bold">${d.name || d.address}</p>
                        ${statusBadge}
                    </div>
                    <p class="text-[9px]" style="color:var(--text-dim)">${d.address}</p>
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
            return '<p class="text-[10px]" style="color:var(--text-dim)">Loading...</p>';
        }
        const actions = Object.keys(m);
        const learning = Settings._swcLearning;
        let html = '<table class="w-full text-[10px]">';
        html += '<thead><tr class="uppercase tracking-wider" style="color:var(--text-dim)">';
        html += '<th class="text-left py-1 font-bold">Action</th>';
        html += '<th class="text-left py-1 font-bold">Pod 1</th>';
        html += '<th class="text-left py-1 font-bold">Pod 2</th></tr></thead>';
        html += '<tbody>';
        for (const action of actions) {
            const btns = m[action] || ["", ""];
            html += `<tr style="border-top:1px solid var(--card-border)">`;
            html += `<td class="py-1.5 font-bold" style="color:var(--text-mid)">${_actionLabel(action)}</td>`;
            for (let pod = 0; pod < 2; pod++) {
                const cur = btns[pod] || "";
                const isLearning = learning && learning.action === action && learning.pod === pod;
                if (isLearning) {
                    html += `<td class="py-1.5">
                        <span class="inline-flex items-center gap-1">
                            <span class="animate-pulse font-bold" style="color:var(--color-primary)">Press button...</span>
                            <button class="text-[9px] px-1.5 py-0.5 rounded font-bold hover:opacity-80"
                                    style="background:var(--card-border);color:var(--text-dim)"
                                    onclick="Settings.swcLearnCancel()">Cancel</button>
                        </span>
                    </td>`;
                } else {
                    html += `<td class="py-1.5">
                        <span class="inline-flex items-center gap-1">
                            <span class="font-bold" style="color:var(--color-on-surface)">${cur || "---"}</span>
                            <button class="text-[9px] px-1.5 py-0.5 rounded font-bold hover:opacity-80"
                                    style="background:var(--color-primary);color:#fff"
                                    onclick="Settings.swcLearnStart('${action}',${pod})">
                                <span class="material-symbols-outlined" style="font-size:11px;vertical-align:-1px">tune</span>
                            </button>
                        </span>
                    </td>`;
                }
            }
            html += '</tr>';
        }
        html += '</tbody></table>';
        return html;
    }

    function _attrEsc(s) {
        // Minimal HTML attribute escape — SSID/password come from the
        // user but are re-emitted as `value="..."` attributes via a
        // template literal, so unescaped quotes/ampersands would break
        // out of the attribute.
        return String(s == null ? "" : s)
            .replace(/&/g, "&amp;")
            .replace(/"/g, "&quot;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;");
    }

    function _toggle(on, onclick) {
        // Tailwind-styled iOS-like switch. The `data-on` attribute is
        // just a hook for tests / accessibility — the visual state is
        // driven by class swaps and the click handler is wired so the
        // toggle actually does something on baremetal.
        const wrap = on
            ? "background:#16a34a"   // green-600
            : "background:var(--card-border)";
        const knob = on ? "translate-x-4" : "translate-x-0";
        return `<button type="button" data-on="${on ? '1' : '0'}"
            class="relative inline-flex w-10 h-6 rounded-full p-0.5 transition-colors"
            style="${wrap}"
            onclick="${onclick}">
            <span class="block w-5 h-5 bg-white rounded-full transform transition-transform ${knob}"></span>
        </button>`;
    }

    function _themeBtn(v, label, current) {
        const isActive = v === current;
        const style = isActive
            ? `background:var(--color-primary);color:#fff;border:1px solid var(--color-primary)`
            : `background:var(--card-bg);color:var(--text-mid);border:1px solid var(--card-border)`;
        return `<button class="px-3 py-1.5 rounded-lg text-xs font-bold hover:opacity-80" style="${style}" onclick="App.setTheme('${v}')">${label}</button>`;
    }
    function _langBtn(v, label, current) {
        const isActive = v === current;
        const style = isActive
            ? `background:var(--color-primary);color:#fff`
            : `background:var(--card-border);color:var(--text-dim)`;
        return `<button class="px-2 py-1 rounded text-xs font-bold hover:opacity-80" style="${style}" onclick="App.setLang('${v}')">${label}</button>`;
    }
    function _unitBtn(v, label, current, type) {
        const isActive = v === current;
        const style = isActive
            ? `background:var(--color-primary);color:#fff`
            : `background:var(--card-border);color:var(--text-dim)`;
        return `<button class="px-2 py-1 rounded text-xs font-bold hover:opacity-80" style="${style}" onclick="Settings.setUnit('${type}','${v}')">${label}</button>`;
    }

    return { render };
})());
