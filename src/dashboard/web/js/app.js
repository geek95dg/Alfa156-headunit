/**
 * Main application controller — routing, theme switching, data binding.
 */

const App = (() => {
    const SCREENS = ["init", "a1", "a2", "a3", "a4", "a5", "a6", "a7", "settings"];
    const NAV_SCREENS = ["a1", "a2", "a3", "a4", "a5", "a6", "a7"]; // screens with navbar

    let _currentScreen = "init";
    let _currentTheme = "heritage";
    let _config = {};
    let _i18n = {};
    // Fallback English strings (used when backend i18n not available)
    const _fallbackStrings = {
        "screen.a1": "MAIN", "screen.a2": "ANDROID AUTO", "screen.a3": "TRIP",
        "screen.a4": "WEATHER", "screen.a5": "SERVICE", "screen.a6": "DVR", "screen.a7": "PERFORMANCE",
        "screen.settings": "SETTINGS",
        "android_auto": "Android Auto", "connect_aa": "Connect Android Auto",
        "dvr": "DVR Recordings", "dvr_export": "Export to USB", "dvr_front": "Front", "dvr_rear": "Rear",
        "performance_title": "Performance", "boost": "Boost", "timer_0_100": "0-100 km/h",
        "best_time": "Best Time", "peak_boost": "Peak Boost", "g_force": "G-Force",
        "engine_temp": "Engine Temp", "fuel_level": "Fuel Level", "coolant": "Coolant",
        "fuel": "Fuel", "oil_press": "Oil Press", "battery": "Battery",
        "notifications": "Notifications", "now_playing": "Now Playing",
        "avg_speed": "Avg Speed", "drive_time": "Drive Time", "voltage": "Voltage",
        "distance": "Distance", "time": "Time", "avg_fuel": "Avg Consumption",
        "instant_cons": "Inst. Cons.", "range": "Range", "trip_dist": "Trip Distance",
        "trip_time": "Trip Time", "est_range": "Est. Range",
        "weather": "Weather", "forecast": "Forecast", "wind": "Wind", "humidity": "Humidity",
        "system_status": "System Status", "engine": "Engine", "oil_life": "Oil Life",
        "tires": "TPMS", "tire_pressure": "Tire Pressure",
        "service_interval": "Next Service", "diagnostics": "Diagnostics",
        "driving_style": "Driving Style", "consumption": "Consumption",
        "icing_title": "ICING WARNING", "icing_msg": "Temperature dropping below 3°C",
        "icing_msg2": "Possible ice on road",
        "reverse_no_camera": "NO REVERSE CAMERA", "reverse_closest": "CLOSEST",
        "parking": "PARKING",
        "settings_title": "SETTINGS", "theme": "Theme", "language": "Language",
        "speed_units": "Speed Units", "temp_units": "Temp Units",
        "ok": "OK", "all_ok": "All OK", "warning": "Warning",
    };
    let _appEl = null;

    // Screen renderers (populated by screen modules)
    const _renderers = {};

    /** Fetch initial config from backend */
    async function loadConfig() {
        try {
            const res = await fetch("/api/config");
            _config = await res.json();
            _currentTheme = _config.theme || "heritage";
        } catch (e) {
            _config = { theme: "heritage", language: "pl", speed_unit: "km/h", temp_unit: "C" };
        }
    }

    /** Fetch i18n strings */
    async function loadI18n(lang) {
        try {
            const res = await fetch(`/api/i18n/${lang || "pl"}`);
            _i18n = await res.json();
        } catch (e) {
            _i18n = {};
        }
    }

    /** Apply theme to body */
    function applyTheme(theme) {
        _currentTheme = theme;
        document.body.setAttribute("data-theme", theme);
        // Remove old theme classes
        document.body.classList.remove("theme-heritage", "theme-modern", "theme-autodelta");
        document.body.classList.add(`theme-${theme}`);
    }

    /** Navigate to a screen */
    function navigateTo(screen) {
        if (!_renderers[screen]) return;

        const prev = _currentScreen;
        _currentScreen = screen;

        // Unmount previous
        if (_renderers[prev] && _renderers[prev].unmount) {
            _renderers[prev].unmount();
        }

        // Render new screen
        _appEl.innerHTML = "";
        _renderers[screen].render(_appEl, _currentTheme, DataStore.getAll());

        // Mount (start updates)
        if (_renderers[screen].mount) {
            _renderers[screen].mount();
        }
    }

    /** Get nav index for current screen */
    function getNavIndex() {
        return NAV_SCREENS.indexOf(_currentScreen);
    }

    /** Handle keyboard navigation */
    function handleKeyDown(e) {
        const key = e.key;

        // Forward to backend
        DataStore.sendKey(key);

        switch (key) {
            case "ArrowLeft":
                e.preventDefault();
                navPrev();
                break;
            case "ArrowRight":
                e.preventDefault();
                navNext();
                break;
            case "Home":
            case "h":
            case "H":
                e.preventDefault();
                if (_currentScreen === "settings") {
                    navigateTo("a1");
                } else {
                    navigateTo("settings");
                }
                break;
            case "Escape":
                e.preventDefault();
                if (_currentScreen === "settings") {
                    navigateTo("a1");
                }
                if (_reverseOverlayActive) {
                    _hideReverseOverlay();
                }
                break;
            case "r":
            case "R":
                e.preventDefault();
                _toggleReverseOverlay();
                break;
        }
    }

    // --- Reverse Camera Overlay ---
    let _reverseOverlayActive = false;
    let _reverseManual = false; // true when toggled via R key (not auto from event bus)

    function _toggleReverseOverlay() {
        if (_reverseOverlayActive) {
            _reverseManual = false;
            _hideReverseOverlay();
        } else {
            _reverseManual = true;
            _showReverseOverlay();
        }
    }

    function _showReverseOverlay() {
        _reverseOverlayActive = true;
        let overlay = document.getElementById("reverse-overlay");
        if (overlay) { overlay.remove(); }

        const data = DataStore.getAll();
        const distances = data.parking_distances || [];
        const lang = App.getLang();
        // Sensor labels: EN = LL, CL, CR, RR / PL = LL, CL, CP, PP
        const labels = lang === "pl"
            ? ["LL", "CL", "CP", "PP"]
            : ["LL", "CL", "CR", "RR"];
        const closestLabel = lang === "pl" ? "NAJBLI\u017bEJ" : "CLOSEST";
        const noCameraText = lang === "pl" ? "BRAK KAMERY COFANIA" : "NO REVERSE CAMERA";
        const exitText = lang === "pl" ? "NACI\u015aNIJ R LUB ESC ABY WYJ\u015a\u0106" : "PRESS R OR ESC TO EXIT REVERSE VIEW";

        overlay = document.createElement("div");
        overlay.id = "reverse-overlay";
        overlay.className = "absolute inset-0 z-[200] flex flex-col bg-black";

        // Sensor bar: each sensor at 1/4 width, aligned spatially
        const sensorBar = labels.map((lbl, i) => {
            const dist = distances[i] || 0;
            const pct = dist > 0 ? Math.min(100, (dist / 2.0) * 100) : 0;
            const color = dist <= 0 ? "bg-zinc-800" : dist < 0.3 ? "bg-red-500" : dist < 0.5 ? "bg-orange-500" : dist < 1.0 ? "bg-yellow-500" : "bg-green-500";
            const textColor = dist <= 0 ? "text-zinc-600" : dist < 0.3 ? "text-red-400" : dist < 0.5 ? "text-orange-400" : dist < 1.0 ? "text-yellow-400" : "text-green-400";
            return `<div class="flex-1 flex flex-col items-center gap-1">
                <span class="text-[10px] font-bold text-zinc-500">${lbl}</span>
                <div class="w-8 h-14 bg-zinc-900 rounded relative overflow-hidden">
                    <div class="${color} absolute bottom-0 w-full rounded transition-all duration-300" style="height:${pct}%"></div>
                </div>
                <span class="text-xs font-bold ${textColor}">${dist > 0 ? dist.toFixed(1) + 'm' : '--'}</span>
            </div>`;
        }).join("");

        const closestDist = distances.filter(d => d > 0);
        const closestVal = closestDist.length > 0 ? Math.min(...closestDist).toFixed(1) : '--';

        overlay.innerHTML = `
            <!-- Camera area — tries live feed, falls back to placeholder -->
            <div class="flex-1 relative bg-zinc-900 flex items-center justify-center overflow-hidden">
                <img id="reverse-cam-feed" src="/api/camera/stream" alt=""
                     class="absolute inset-0 w-full h-full object-cover z-0"
                     style="display:none;"
                     onload="this.style.display='block';document.getElementById('reverse-cam-placeholder').style.display='none';"
                     onerror="this.style.display='none';document.getElementById('reverse-cam-placeholder').style.display='flex';">
                <div id="reverse-cam-placeholder" class="flex flex-col items-center text-zinc-600 z-[1]">
                    <span class="material-symbols-outlined text-6xl">videocam_off</span>
                    <span class="text-sm font-bold mt-2 uppercase tracking-wider">${noCameraText}</span>
                </div>
                <!-- R badge -->
                <div class="absolute top-3 right-3 bg-red-600 text-white font-black text-xl w-10 h-10 rounded-full flex items-center justify-center z-10">R</div>
                <!-- Parking guidelines overlay -->
                <div class="absolute bottom-0 left-1/2 -translate-x-1/2 w-[55%] h-[65%] border-l-2 border-r-2 border-b-2 border-green-500/40 rounded-b-xl z-[2]"></div>
                <div class="absolute bottom-[18%] left-1/2 -translate-x-1/2 w-[45%] border-t-2 border-dashed border-yellow-500/40 z-[2]"></div>
                <div class="absolute bottom-[36%] left-1/2 -translate-x-1/2 w-[35%] border-t-2 border-dashed border-red-500/40 z-[2]"></div>
            </div>
            <!-- Parking sensors: 4 sensors aligned to 1/4 screen width each + closest readout -->
            <div class="h-[110px] bg-zinc-950 border-t border-zinc-800 flex items-center px-4 shrink-0">
                <div class="flex flex-1 items-center">
                    ${sensorBar}
                </div>
                <div class="w-[140px] flex flex-col items-center shrink-0 pl-4 border-l border-zinc-800">
                    <span class="text-[9px] font-bold text-zinc-500 uppercase">${closestLabel}</span>
                    <span class="text-3xl font-black text-white">${closestVal}<span class="text-sm text-zinc-500 ml-1">m</span></span>
                </div>
            </div>
            <div class="text-center py-1 bg-zinc-950 text-zinc-600 text-[9px] font-bold uppercase tracking-widest shrink-0">${exitText}</div>
        `;
        _appEl.appendChild(overlay);

        // Start updating sensor values
        _reverseUpdateInterval = setInterval(_updateReverseSensors, 200);
    }

    let _reverseUpdateInterval = null;

    function _updateReverseSensors() {
        const data = DataStore.getAll();
        const distances = data.parking_distances || [];
        const overlay = document.getElementById("reverse-overlay");
        if (!overlay) return;

        const bars = overlay.querySelectorAll('.flex-1 .flex-1');
        bars.forEach((bar, i) => {
            const dist = distances[i] || 0;
            const pct = dist > 0 ? Math.min(100, (dist / 2.0) * 100) : 0;
            const fill = bar.querySelector('[class*="absolute bottom-0"]');
            const label = bar.querySelector('.text-xs');
            if (fill) {
                fill.style.height = `${pct}%`;
                fill.className = fill.className.replace(/bg-\S+/, '');
                const color = dist <= 0 ? "bg-zinc-800" : dist < 0.3 ? "bg-red-500" : dist < 0.5 ? "bg-orange-500" : dist < 1.0 ? "bg-yellow-500" : "bg-green-500";
                fill.classList.add(color, "absolute", "bottom-0", "w-full", "rounded", "transition-all", "duration-300");
            }
            if (label) label.textContent = dist > 0 ? dist.toFixed(1) + 'm' : '--';
        });
    }

    function _hideReverseOverlay() {
        _reverseOverlayActive = false;
        if (_reverseUpdateInterval) {
            clearInterval(_reverseUpdateInterval);
            _reverseUpdateInterval = null;
        }
        const overlay = document.getElementById("reverse-overlay");
        if (overlay) overlay.remove();
    }

    // --- Icing Alert ---
    function _checkIcingAlert(data) {
        const temp = data.ext_temp;
        if (temp != null && temp < 3 && !document.getElementById("icing-alert")) {
            const alert = document.createElement("div");
            alert.id = "icing-alert";
            alert.className = "absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 z-[150] bg-black/90 border-2 border-amber-500 rounded-xl p-6 flex flex-col items-center gap-3 shadow-2xl";
            alert.innerHTML = `
                <span class="material-symbols-outlined text-4xl text-amber-500">ac_unit</span>
                <h3 class="text-lg font-black text-amber-500 uppercase tracking-wider">Icing Warning</h3>
                <p class="text-sm text-zinc-400 text-center">External temperature ${Math.round(temp)}°C<br>Road surface may be icy</p>
            `;
            _appEl.appendChild(alert);
            setTimeout(() => { alert.remove(); }, 5000);
        }
    }

    // --- Touch Swipe Navigation ---
    function _initTouchSwipe() {
        let startX = 0;
        let startY = 0;
        document.addEventListener("touchstart", (e) => {
            startX = e.touches[0].clientX;
            startY = e.touches[0].clientY;
        }, { passive: true });
        document.addEventListener("touchend", (e) => {
            const dx = e.changedTouches[0].clientX - startX;
            const dy = e.changedTouches[0].clientY - startY;
            // Require horizontal swipe > 60px and more horizontal than vertical
            if (Math.abs(dx) > 60 && Math.abs(dx) > Math.abs(dy) * 1.5) {
                if (dx < 0) navNext();  // Swipe left → next screen
                else navPrev();          // Swipe right → prev screen
            }
        }, { passive: true });
    }

    function navPrev() {
        const idx = NAV_SCREENS.indexOf(_currentScreen);
        if (idx > 0) {
            navigateTo(NAV_SCREENS[idx - 1]);
        }
    }

    function navNext() {
        const idx = NAV_SCREENS.indexOf(_currentScreen);
        if (idx >= 0 && idx < NAV_SCREENS.length - 1) {
            navigateTo(NAV_SCREENS[idx + 1]);
        }
    }

    /** Update current screen with new data */
    function onDataUpdate(data) {
        if (_renderers[_currentScreen] && _renderers[_currentScreen].update) {
            _renderers[_currentScreen].update(data, _currentTheme);
        }
        // Auto-show reverse overlay when gear=R from event bus (not manual toggle)
        if (data.reverse === true && !_reverseOverlayActive) {
            _reverseManual = false;
            _showReverseOverlay();
        } else if (data.reverse === false && _reverseOverlayActive && !_reverseManual) {
            _hideReverseOverlay();
        }
        // Icing alert check
        _checkIcingAlert(data);
    }

    /** Listen for config changes from backend */
    function onConfigChanged(value) {
        if (!value) return;
        if (value.theme && value.theme !== _currentTheme) {
            applyTheme(value.theme);
            navigateTo(_currentScreen);
        }
        if (value.language) {
            _config.language = value.language;
            loadI18n(value.language).then(() => navigateTo(_currentScreen));
        }
    }

    return {
        /** Register a screen renderer */
        registerScreen(name, renderer) {
            _renderers[name] = renderer;
        },

        /** Get current theme */
        getTheme() { return _currentTheme; },

        /** Get config */
        getConfig() { return _config; },

        /** Get translation string — checks loaded i18n, then fallback, then key */
        t(key, fallback) {
            return _i18n[key] || _fallbackStrings[key] || fallback || key;
        },

        /** Get current language */
        getLang() { return _config.language || "pl"; },

        /** Navigate to a screen */
        navigateTo,
        navPrev,
        navNext,
        getNavIndex,

        /** Get current screen name */
        getCurrentScreen() { return _currentScreen; },

        /** DTC: Read error codes from ECU */
        async _readDTC() {
            const el = document.getElementById("dtc-list");
            if (el) el.textContent = App.t("dtc_reading", "Reading...");
            try {
                const res = await fetch("/api/dtc/read");
                const result = await res.json();
                if (el) {
                    if (result.codes && result.codes.length > 0) {
                        el.innerHTML = result.codes.map(c =>
                            `<div class="flex justify-between py-0.5"><span class="text-amber-500 font-bold">${c.code}</span><span>${c.desc || ''}</span></div>`
                        ).join("");
                    } else {
                        el.textContent = App.t("dtc_none", "No error codes");
                    }
                }
            } catch (e) {
                if (el) el.textContent = App.t("dtc_error", "Read failed");
            }
        },

        /** DTC: Clear error codes */
        async _clearDTC() {
            if (!confirm(App.t("dtc_confirm", "Clear all error codes from ECU?"))) return;
            try {
                await fetch("/api/dtc/clear", { method: "POST" });
                const el = document.getElementById("dtc-list");
                if (el) el.textContent = App.t("dtc_cleared", "Codes cleared");
            } catch (e) { /* ignore */ }
        },

        /** Set theme and notify backend */
        async setTheme(theme) {
            applyTheme(theme);
            navigateTo(_currentScreen);
            try {
                await fetch("/api/config", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ theme }),
                });
            } catch (e) { /* ignore */ }
        },

        /** Set language, reload translations, and re-render */
        async setLang(lang) {
            _config.language = lang;
            await loadI18n(lang);
            navigateTo(_currentScreen);
            try {
                await fetch("/api/config", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ language: lang }),
                });
            } catch (e) { /* ignore */ }
        },

        /** Initialize the application */
        async init() {
            _appEl = document.getElementById("app");

            // Load config and i18n
            await loadConfig();
            await loadI18n(_config.language);

            // Apply theme
            applyTheme(_currentTheme);

            // Init WebSocket
            DataStore.init();

            // Listen for data updates
            DataStore.subscribe("*", onDataUpdate);

            // Keyboard input
            document.addEventListener("keydown", handleKeyDown);

            // Touch swipe navigation (for touchscreen)
            _initTouchSwipe();

            // Start at init screen, then auto-transition to A1
            navigateTo("init");

            // After init animation, go to A1
            setTimeout(() => {
                if (_currentScreen === "init") {
                    navigateTo("a1");
                }
            }, 4000);
        },
    };
})();

// Boot — use window.onload to ensure all screen scripts have registered
window.addEventListener("load", () => App.init());
