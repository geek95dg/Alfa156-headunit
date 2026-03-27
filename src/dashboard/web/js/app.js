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
                e.preventDefault();
                navigateTo("a1");
                break;
            case "Escape":
                e.preventDefault();
                if (_currentScreen === "settings") {
                    navigateTo("a1");
                }
                break;
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
