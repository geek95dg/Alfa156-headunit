/**
 * Main application controller — routing, theme switching, data binding.
 */

const App = (() => {
    const SCREENS = ["init", "a1", "a2", "a3", "a4", "settings"];
    const NAV_SCREENS = ["a1", "a2", "a3", "a4"]; // screens with navbar

    let _currentScreen = "init";
    let _currentTheme = "heritage";
    let _config = {};
    let _i18n = {};
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

    function _toggleReverseOverlay() {
        if (_reverseOverlayActive) {
            _hideReverseOverlay();
        } else {
            _showReverseOverlay();
        }
    }

    function _showReverseOverlay() {
        _reverseOverlayActive = true;
        let overlay = document.getElementById("reverse-overlay");
        if (overlay) { overlay.remove(); }

        const data = DataStore.getAll();
        const distances = data.parking_distances || [];
        const labels = ["FL", "FR", "RL", "RR"];

        overlay = document.createElement("div");
        overlay.id = "reverse-overlay";
        overlay.className = "absolute inset-0 z-[200] flex flex-col bg-black";
        overlay.innerHTML = `
            <!-- Camera area -->
            <div class="flex-1 relative bg-zinc-900 flex items-center justify-center">
                <div class="absolute top-4 right-4 bg-red-600 text-white font-black text-2xl w-12 h-12 rounded-full flex items-center justify-center z-10">R</div>
                <div class="flex flex-col items-center text-zinc-600">
                    <span class="material-symbols-outlined text-6xl">videocam_off</span>
                    <span class="text-sm font-bold mt-2 uppercase tracking-wider">No Reverse Camera</span>
                </div>
                <!-- Parking guidelines -->
                <div class="absolute bottom-0 left-1/2 -translate-x-1/2 w-[60%] h-[70%] border-l-2 border-r-2 border-b-2 border-green-500/40 rounded-b-xl"></div>
                <div class="absolute bottom-[20%] left-1/2 -translate-x-1/2 w-[50%] border-t-2 border-dashed border-yellow-500/40"></div>
                <div class="absolute bottom-[40%] left-1/2 -translate-x-1/2 w-[40%] border-t-2 border-dashed border-red-500/40"></div>
            </div>
            <!-- Parking sensors bar -->
            <div class="h-[120px] bg-zinc-950 border-t border-zinc-800 flex items-center justify-around px-8">
                ${labels.map((lbl, i) => {
                    const dist = distances[i] || 0;
                    const pct = dist > 0 ? Math.min(100, (dist / 2.0) * 100) : 0;
                    const color = dist <= 0 ? "bg-zinc-800" : dist < 0.3 ? "bg-red-500" : dist < 0.5 ? "bg-orange-500" : dist < 1.0 ? "bg-yellow-500" : "bg-green-500";
                    const textColor = dist <= 0 ? "text-zinc-600" : dist < 0.3 ? "text-red-400" : dist < 0.5 ? "text-orange-400" : dist < 1.0 ? "text-yellow-400" : "text-green-400";
                    return `<div class="flex flex-col items-center gap-2">
                        <span class="text-[10px] font-bold text-zinc-500 uppercase">${lbl}</span>
                        <div class="w-8 h-16 bg-zinc-900 rounded relative overflow-hidden">
                            <div class="${color} absolute bottom-0 w-full rounded transition-all duration-300" style="height:${pct}%"></div>
                        </div>
                        <span class="text-xs font-bold ${textColor}">${dist > 0 ? dist.toFixed(1) + 'm' : '--'}</span>
                    </div>`;
                }).join("")}
                <div class="flex flex-col items-center">
                    <span class="text-[10px] font-bold text-zinc-500 uppercase">Closest</span>
                    <span class="text-3xl font-black text-white">${distances.length > 0 ? Math.min(...distances.filter(d => d > 0)).toFixed(1) : '--'}<span class="text-sm text-zinc-500 ml-1">m</span></span>
                </div>
            </div>
            <div class="text-center py-1 bg-zinc-950 text-zinc-600 text-[10px] font-bold uppercase tracking-widest">Press R or ESC to exit reverse view</div>
        `;
        _appEl.appendChild(overlay);
    }

    function _hideReverseOverlay() {
        _reverseOverlayActive = false;
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
        // Auto-show reverse overlay when gear=R from event bus
        if (data.reverse && !_reverseOverlayActive) {
            _showReverseOverlay();
        } else if (!data.reverse && _reverseOverlayActive) {
            _hideReverseOverlay();
        }
        // Icing alert check
        _checkIcingAlert(data);
    }

    /** Listen for config changes from backend */
    function onConfigChanged(value) {
        if (value && value.theme && value.theme !== _currentTheme) {
            applyTheme(value.theme);
            // Re-render current screen with new theme
            navigateTo(_currentScreen);
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

        /** Get translation string */
        t(key, fallback) {
            return _i18n[key] || fallback || key;
        },

        /** Navigate to a screen */
        navigateTo,
        navPrev,
        navNext,
        getNavIndex,

        /** Get current screen name */
        getCurrentScreen() { return _currentScreen; },

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
