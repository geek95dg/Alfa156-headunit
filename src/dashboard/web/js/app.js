/**
 * Main application controller — routing, theme switching, data binding.
 */

const App = (() => {
    const SCREENS = ["init", "a1", "a2", "a3", "a4", "a5", "a6", "a7", "a8", "settings"];
    // Quick-start build: swipe/navbar cycle only the four in-scope screens.
    // A5-A8 stay registered (reachable by direct navigateTo) but are hidden.
    const NAV_SCREENS = ["a1", "a2", "a3", "a4"]; // screens with navbar

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

    /** Persist the last user-visible screen to localStorage so we can
     *  restore it on the next app launch. "init" and "settings" are
     *  intentionally excluded — we only remember A-screens (a1..a8). */
    const LAST_SCREEN_KEY = "bcm.lastScreen";
    function _saveLastScreen(screen) {
        if (!NAV_SCREENS.includes(screen)) return;
        try { localStorage.setItem(LAST_SCREEN_KEY, screen); } catch (e) {}
    }
    function _loadLastScreen() {
        try {
            const s = localStorage.getItem(LAST_SCREEN_KEY);
            return NAV_SCREENS.includes(s) ? s : null;
        } catch (e) {
            return null;
        }
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
        // Fill the fresh AppBar at once instead of on the next clock tick:
        // the phone operator name only ever arrives through AppBar.update()
        // (textContent — untrusted text never goes into the markup).
        _tickClock();

        // Mount (start updates)
        if (_renderers[screen].mount) {
            _renderers[screen].mount();
        }

        // Persist A-screens so next launch lands on the same screen.
        _saveLastScreen(screen);
    }

    /** Get nav index for current screen */
    function getNavIndex() {
        return NAV_SCREENS.indexOf(_currentScreen);
    }

    /** Handle keyboard navigation */
    function handleKeyDown(e) {
        // Don't hijack keys when the user is typing in a text field —
        // weather/trip search inputs need every printable key (including
        // 'h', 'H' and arrows for cursor navigation), and Escape should
        // dismiss the OSK rather than navigate.
        const ae = document.activeElement;
        if (ae && (ae.tagName === "INPUT" || ae.tagName === "TEXTAREA"
                   || ae.isContentEditable)) {
            return;
        }

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
            // R key reverse toggle removed — reverse camera only on small display
        }
    }

    // --- Reverse / Side Camera Overlay (MAIN display) ---
    let _reverseOverlayActive = false;
    let _reverseManual = false; // true when toggled via R key (not auto from event bus)
    let _reverseFeed = null;    // "rear" | "left" | "right"

    function _toggleReverseOverlay() {
        if (_reverseOverlayActive) {
            _reverseManual = false;
            _hideReverseOverlay();
        } else {
            _reverseManual = true;
            _showReverseOverlay("rear");
        }
    }

    function _showReverseOverlay(feed) {
        feed = feed || "rear";
        _reverseFeed = feed;
        const isRear = feed === "rear";
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
        const badge = { rear: "R", left: "L", right: "P" }[feed] || "R";
        const badgeColor = { rear: "bg-red-600", left: "bg-amber-500", right: "bg-emerald-500" }[feed] || "bg-red-600";
        // Side-camera insets (rear/reverse view only) so the driver also sees
        // what the L/R cameras catch while backing out.
        const sideInsets = isRear ? `
            <div class="absolute top-3 left-3 w-[22%] aspect-video rounded-lg overflow-hidden border border-zinc-700 bg-zinc-900 z-10">
                <img src="/api/camera/stream?cam=left" class="w-full h-full object-cover" onerror="this.style.display='none'">
                <span class="absolute bottom-1 left-1 text-[9px] font-bold text-amber-400">L</span>
            </div>
            <div class="absolute top-3 right-16 w-[22%] aspect-video rounded-lg overflow-hidden border border-zinc-700 bg-zinc-900 z-10">
                <img src="/api/camera/stream?cam=right" class="w-full h-full object-cover" onerror="this.style.display='none'">
                <span class="absolute bottom-1 left-1 text-[9px] font-bold text-emerald-400">P</span>
            </div>` : "";

        overlay.innerHTML = `
            <!-- Camera area — tries live feed, falls back to placeholder -->
            <div class="flex-1 relative bg-zinc-900 flex items-center justify-center overflow-hidden">
                <img id="reverse-cam-feed" src="/api/camera/stream?cam=${feed}" alt=""
                     class="absolute inset-0 w-full h-full object-cover z-0"
                     style="display:none;"
                     onload="this.style.display='block';document.getElementById('reverse-cam-placeholder').style.display='none';"
                     onerror="this.style.display='none';document.getElementById('reverse-cam-placeholder').style.display='flex';">
                <div id="reverse-cam-placeholder" class="flex flex-col items-center text-zinc-600 z-[1]">
                    <span class="material-symbols-outlined text-6xl">videocam_off</span>
                    <span class="text-sm font-bold mt-2 uppercase tracking-wider">${noCameraText}</span>
                </div>
                <!-- camera badge + side-camera insets -->
                <div class="absolute top-3 right-3 ${badgeColor} text-white font-black text-xl w-10 h-10 rounded-full flex items-center justify-center z-20">${badge}</div>
                ${sideInsets}
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

        // Start updating sensor values + proximity beep
        _reverseUpdateInterval = setInterval(_updateReverseSensors, 200);
        if (isRear) _startReverseBeep();
    }

    // --- Proximity beep (WebAudio) for the reverse view ---
    // The hardware parking buzzer (src/parking/buzzer.py) drives the real
    // car; this adds an audible head-unit beep too, essential on bench/x86
    // where there's no buzzer GPIO. Cadence follows the closest sensor
    // distance, going near-solid under ~0.3 m.
    let _beepCtx = null, _beepTimer = null;
    function _startReverseBeep() {
        _stopReverseBeep();
        const tick = () => {
            const dists = (DataStore.getAll().parking_distances || []).filter(d => d > 0);
            const closest = dists.length ? Math.min(...dists) : 0;
            let gap = 0; // 0 = silent
            if (closest > 0) {
                if (closest < 0.3) gap = 1;
                else if (closest < 0.5) gap = 150;
                else if (closest < 1.0) gap = 400;
                else if (closest < 1.5) gap = 800;
            }
            if (gap > 0) _beep(closest < 0.3 ? 0.25 : 0.08);
            _beepTimer = setTimeout(tick, gap > 0 ? Math.max(gap, 120) : 300);
        };
        tick();
    }
    function _beep(durSec) {
        try {
            if (!_beepCtx) _beepCtx = new (window.AudioContext || window.webkitAudioContext)();
            const osc = _beepCtx.createOscillator();
            const gain = _beepCtx.createGain();
            osc.frequency.value = 880;
            gain.gain.value = 0.12;
            osc.connect(gain); gain.connect(_beepCtx.destination);
            osc.start();
            osc.stop(_beepCtx.currentTime + durSec);
        } catch (e) { /* audio unavailable — hardware buzzer still beeps */ }
    }
    function _stopReverseBeep() {
        if (_beepTimer) { clearTimeout(_beepTimer); _beepTimer = null; }
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
        _reverseFeed = null;
        _stopReverseBeep();
        if (_reverseUpdateInterval) {
            clearInterval(_reverseUpdateInterval);
            _reverseUpdateInterval = null;
        }
        const overlay = document.getElementById("reverse-overlay");
        if (overlay) overlay.remove();
    }

    // --- Icing Alert ---
    function _checkIcingAlert(data) {
        // Quick-start build: ice/frost warnings disabled (user request). The
        // environment module is off anyway, but hard-gate it so a stray
        // ext_temp can never pop the overlay.
        return;
        const temp = data.ext_temp;   // eslint-disable-line no-unreachable
        if (temp != null && temp < 3 && !document.getElementById("icing-alert")) {
            const t = App.t.bind(App);
            const alert = document.createElement("div");
            alert.id = "icing-alert";
            alert.className = "absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 z-[150] bg-black/90 border-2 border-amber-500 rounded-xl p-6 flex flex-col items-center gap-3 shadow-2xl";
            alert.innerHTML = `
                <span class="material-symbols-outlined text-4xl text-amber-500">ac_unit</span>
                <h3 class="text-lg font-black text-amber-500 uppercase tracking-wider">${t("icing_title", "ICING WARNING")}</h3>
                <p class="text-sm text-zinc-400 text-center">${t("icing_msg", "External temperature")} ${Math.round(temp)}\u00b0C<br>${t("icing_msg2", "Road surface may be icy")}</p>
            `;
            _appEl.appendChild(alert);
            setTimeout(() => { alert.remove(); }, 5000);
        }
    }

    // --- Global BT Pairing Monitor ---
    function _startGlobalPairingPoll() {
        setInterval(async () => {
            try {
                const res = await fetch("/bt/pairing");
                const data = await res.json();
                if (data.pending && data.request) {
                    Settings._showPairingPopup(data.request);
                    Settings._startPairingPoll();
                }
            } catch (e) {}
        }, 2000);
    }

    // --- Touch gestures ---
    // Two edge gestures, classified by components/gestures.js:
    //   pull DOWN from the top edge   → next screen (navCycleNext),
    //   swipe UP from the bottom edge → reveal the autohiding NavBar.
    // The old horizontal swipe is gone: it fired on the AA stream too, so a
    // horizontal drag meant for the phone changed the BCM screen. Both
    // gestures are evaluated on touchend only — nothing navigates mid-drag.
    //
    // Touches on the AA overlay are skipped: A2 runs the same edge machine
    // itself (screens/android_auto.js) because it must also decide what goes
    // to the phone. Overlays/modals are skipped so a pull never navigates
    // the screen away underneath them.
    const GESTURE_OVERLAYS = "#osk-overlay, #reverse-overlay, #kiosk-restart-modal, "
        + "#system-reboot-modal, #kiosk-restarting-overlay, #system-rebooting-overlay, "
        + "#bt-pairing-overlay, #bcm-splash-overlay";

    function _isFormControl(el) {
        if (!el) return false;
        const tag = el.tagName;
        return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT"
            || tag === "BUTTON" || !!el.isContentEditable;
    }

    function _gestureIgnored(el) {
        if (el && el.closest && el.closest("#aa-touch-overlay")) return true;
        if (document.querySelector(GESTURE_OVERLAYS)) return true;
        return false;
    }

    function _initTouchSwipe() {
        const G = window.BCMGestures;
        if (!G) return;   // gestures.js failed to load — keyboard nav still works
        let tracking = false;
        let zone = null;
        let startX = 0, startY = 0, startT = 0;
        let onControl = false;

        document.addEventListener("touchstart", (e) => {
            tracking = false;
            if (!e.touches || e.touches.length !== 1) return;  // pinch etc.
            if (_gestureIgnored(e.target)) return;
            const t = e.touches[0];
            zone = G.edgeZone(t.clientY, window.innerHeight);
            if (!zone) return;
            tracking = true;
            startX = t.clientX;
            startY = t.clientY;
            startT = performance.now();
            onControl = _isFormControl(e.target);
        }, { passive: true });

        document.addEventListener("touchcancel", () => { tracking = false; }, { passive: true });

        document.addEventListener("touchend", (e) => {
            if (!tracking) return;
            tracking = false;
            if (!e.changedTouches || !e.changedTouches.length) return;
            const t = e.changedTouches[0];
            const dx = t.clientX - startX;
            const dy = t.clientY - startY;
            if (zone === "bottom") {
                // Works over buttons too (fixed-bottom controls sit right in
                // the edge strip); a tap there is < NAVBAR_MIN and passes.
                if (G.navbarDone(dx, dy)) showNavBar();
            } else if (zone === "top" && !onControl) {
                if (G.pullDone(dx, dy, performance.now() - startT)) navCycleNext();
            }
        }, { passive: true });
    }

    // --- Autohiding NavBar ---
    let _navHideTimer = null;
    const NAV_AUTOHIDE_MS = 4000;
    function showNavBar() {
        const nav = document.getElementById("bcm-navbar");
        if (!nav) return;
        nav.classList.add("bcm-navbar-shown");
        _scheduleNavHide();
    }
    function hideNavBar() {
        const nav = document.getElementById("bcm-navbar");
        if (!nav) return;
        nav.classList.remove("bcm-navbar-shown");
        if (_navHideTimer) { clearTimeout(_navHideTimer); _navHideTimer = null; }
    }
    function _scheduleNavHide() {
        if (_navHideTimer) clearTimeout(_navHideTimer);
        _navHideTimer = setTimeout(() => {
            hideNavBar();
        }, NAV_AUTOHIDE_MS);
    }
    /** Called from NavBar inline handlers — keeps the nav visible
     *  while the user is interacting, hides shortly after they leave. */
    function kickNavBar(active) {
        if (active) {
            showNavBar();
        } else {
            _scheduleNavHide();
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

    /** Pull-down target: the next A-screen, wrapping A4 → A1. From a screen
     *  outside the cycle (Settings, Audio, init…) go back to the last
     *  A-screen the user was on, else A1. */
    function navCycleNext() {
        const idx = NAV_SCREENS.indexOf(_currentScreen);
        if (idx >= 0) {
            navigateTo(NAV_SCREENS[(idx + 1) % NAV_SCREENS.length]);
        } else {
            navigateTo(_loadLastScreen() || "a1");
        }
    }

    // --- Top-bar clock ---
    // AppBar.render() stamps the time once; nothing refreshed it, so the
    // clock stood still until the next screen change. Tick once a second
    // (AppBar.update only writes when the text changed) and catch up at once
    // when the kiosk becomes visible again.
    let _clockTimer = null;
    function _tickClock() {
        if (typeof AppBar === "undefined") return;
        try { AppBar.update(document, DataStore.getAll()); } catch (e) { /* never kill the timer */ }
    }
    function _startClock() {
        if (_clockTimer) return;
        _clockTimer = setInterval(_tickClock, 1000);
        document.addEventListener("visibilitychange", () => {
            if (!document.hidden) _tickClock();
        });
        _tickClock();
    }

    // --- Phone calls (bt.call_state from the oFono monitor) ---
    // Only the CURRENT screen's update() runs on new data, so a call that
    // arrives while the kiosk shows A1/A3/A4 used to show nothing: the A8
    // overlay (answer / reject) only appeared if the driver was already on
    // A8, and Phone._callState went stale everywhere else. The call state is
    // therefore followed here, on every screen.
    const CALL_STATES = ["idle", "incoming", "ringing", "active"];
    // Never pulled to A8 from these: A8 shows the overlay itself, and on A2
    // Android Auto projects its own call UI.
    const CALL_NAV_SKIP = ["a8", "a2"];
    let _lastCallState = null;   // last bt_call_state seen from the backend
    let _lastCallKey = null;     // state + caller info, to spot news only
    let _callReturnTo = null;    // screen to go back to after an auto-switch

    /** Pure: where a bt_call_state change should take the kiosk, or null.
     *  prev: last backend state (null before the first payload), next: new
     *  state, screen: current screen, returnTo: the screen we came from if
     *  this call already switched to A8 by itself. */
    function callNavDecision(prev, next, screen, returnTo) {
        if (CALL_STATES.indexOf(next) === -1 || next === prev) return null;
        if (next === "idle") {
            // Call over: go back only if WE moved the driver and they stayed.
            return (returnTo && screen === "a8") ? returnTo : null;
        }
        if (CALL_NAV_SKIP.indexOf(screen) !== -1) return null;
        if (next === "incoming") return "a8";      // needs answer / reject
        // A call started on the phone (or already running when the kiosk
        // loaded): show the hang-up overlay once, not on every state step.
        if (prev === "idle" || prev === null) return "a8";
        return null;
    }

    /** Caller info from the payload as plain, bounded strings. Escaping is
     *  done where it is rendered (phone.js _esc), not here. */
    function _callInfoOf(v) {
        if (!v || typeof v !== "object") return {};
        const out = {};
        if (v.number != null && v.number !== "") out.number = String(v.number).slice(0, 32);
        if (v.name != null && v.name !== "") out.name = String(v.name).slice(0, 64);
        return out;
    }

    function _syncCallState(data) {
        const next = data ? data.bt_call_state : undefined;
        if (CALL_STATES.indexOf(next) === -1) return;
        const info = next === "idle" ? {} : _callInfoOf(data.bt_call_info);
        const key = next + "|" + (info.number || "") + "|" + (info.name || "");
        // Act on NEWS from the backend only. Re-applying an unchanged state on
        // every push would clobber Phone.dial()'s instant local "ringing".
        if (key === _lastCallKey) return;
        const prev = _lastCallState;
        _lastCallState = next;
        _lastCallKey = key;
        if (typeof Phone !== "undefined" && Phone) {
            Phone._callState = next;
            Phone._callInfo = info;
        }
        const target = callNavDecision(prev, next, _currentScreen, _callReturnTo);
        if (next === "idle") _callReturnTo = null;
        if (target === "a8") {
            if (!_callReturnTo) {
                _callReturnTo = NAV_SCREENS.includes(_currentScreen) || _currentScreen === "settings"
                    ? _currentScreen : (_loadLastScreen() || "a1");
            }
            navigateTo("a8");
        } else if (target) {
            navigateTo(target);
        }
    }

    /** Update current screen with new data */
    function onDataUpdate(data) {
        // Calls first: may switch to A8, whose update() then sees fresh state.
        try { _syncCallState(data); } catch (e) { /* never break the data loop */ }
        if (_renderers[_currentScreen] && _renderers[_currentScreen].update) {
            _renderers[_currentScreen].update(data, _currentTheme);
        }
        // Reverse / side camera now lives on the MAIN display: auto-show the
        // overlay whenever the CameraController resolves a feed (rear on
        // reverse gear, left/right on blinkers) and auto-hide when it clears.
        // A manual R-key toggle (_reverseManual) is left alone.
        _syncReverseOverlay(data);
        // Icing alert check
        _checkIcingAlert(data);
        // Backend announcements (e.g. "no microphone") as toasts, on any screen.
        if (typeof Notifications !== "undefined" && Notifications.syncToasts) {
            Notifications.syncToasts(data.notifications);
        }
    }

    function _syncReverseOverlay(data) {
        if (_reverseManual) return;   // R-key override owns the overlay
        const feed = data.camera_active
            || (data.reverse_gear ? "rear" : null);
        if (feed && (!_reverseOverlayActive || _reverseFeed !== feed)) {
            _showReverseOverlay(feed);
        } else if (!feed && _reverseOverlayActive) {
            _hideReverseOverlay();
        }
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
        navCycleNext,
        getNavIndex,

        /** Pure call-navigation rule (exported for the node test). */
        callNavDecision,

        /** NavBar autohide controls (called from NavBar markup + global) */
        showNavBar,
        hideNavBar,
        kickNavBar,

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

        /** Open modal to confirm kiosk restart */
        restartKioskModal() {
            let overlay = document.getElementById("kiosk-restart-modal");
            if (!overlay) {
                overlay = document.createElement("div");
                overlay.id = "kiosk-restart-modal";
                document.body.appendChild(overlay);
            }
            overlay.className = "fixed inset-0 z-[200] flex items-center justify-center p-4";
            overlay.style.background = "rgba(0,0,0,0.85)";
            overlay.innerHTML = `
                <div class="rounded-2xl p-6 w-[380px] max-w-full shadow-2xl text-center"
                     style="background:var(--card-bg);border:1px solid var(--card-border);color:var(--color-on-surface)">
                    <div class="w-14 h-14 rounded-full bg-red-600/20 text-red-500 mx-auto flex items-center justify-center mb-3">
                        <span class="material-symbols-outlined text-3xl">restart_alt</span>
                    </div>
                    <h3 class="text-lg font-bold mb-2">${App.t("kiosk_restart", "Restart kiosku")}</h3>
                    <p class="text-xs mb-6" style="color:var(--text-dim)">${App.t("kiosk_restart_confirm", "Czy na pewno chcesz zrestartować cały kiosk?")}</p>
                    <div class="flex gap-3 justify-center">
                        <button class="px-5 py-2.5 rounded-xl text-xs font-bold hover:opacity-80 transition-opacity"
                                style="background:var(--card-border);color:var(--text-mid)"
                                onclick="document.getElementById('kiosk-restart-modal').remove()">
                            ${App.t("cancel", "Anuluj")}
                        </button>
                        <button class="px-6 py-2.5 bg-red-600 hover:bg-red-500 text-white rounded-xl text-xs font-bold transition-colors flex items-center gap-1.5"
                                onclick="App.restartKiosk()">
                            <span class="material-symbols-outlined text-sm">restart_alt</span>
                            ${App.t("kiosk_restart", "Restartuj")}
                        </button>
                    </div>
                </div>
            `;
        },

        /** Execute kiosk restart and show reloading splash */
        async restartKiosk() {
            const modal = document.getElementById("kiosk-restart-modal");
            if (modal) modal.remove();

            let splash = document.getElementById("kiosk-restarting-overlay");
            if (!splash) {
                splash = document.createElement("div");
                splash.id = "kiosk-restarting-overlay";
                document.body.appendChild(splash);
            }
            splash.className = "fixed inset-0 z-[300] flex flex-col items-center justify-center bg-black text-white p-6";
            splash.innerHTML = `
                <div class="flex flex-col items-center gap-4 text-center">
                    <span class="material-symbols-outlined text-6xl text-red-500 animate-spin">sync</span>
                    <h2 class="text-2xl font-bold">${App.t("kiosk_restarting", "Restartowanie kiosku...")}</h2>
                    <p class="text-xs text-zinc-400 max-w-sm">Ładowanie panelu nastąpi automatycznie po restarcie procesów.</p>
                </div>
            `;

            try {
                await fetch("/api/kiosk/restart", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ scope: "kiosk" })
                });
            } catch (e) {
                console.log("Kiosk restart triggered", e);
            }

            // Poll until server is answering again, then reload window
            let checkCount = 0;
            const pollInterval = setInterval(async () => {
                checkCount++;
                try {
                    const res = await fetch("/api/data", { cache: "no-store" });
                    if (res.ok) {
                        clearInterval(pollInterval);
                        setTimeout(() => window.location.reload(true), 500);
                    }
                } catch (e) {
                    // still restarting
                }
                if (checkCount > 30) {
                    clearInterval(pollInterval);
                    window.location.reload(true);
                }
            }, 1000);
        },

        /** Open modal to confirm baremetal OS reboot */
        rebootSystemModal() {
            let overlay = document.getElementById("system-reboot-modal");
            if (!overlay) {
                overlay = document.createElement("div");
                overlay.id = "system-reboot-modal";
                document.body.appendChild(overlay);
            }
            overlay.className = "fixed inset-0 z-[200] flex items-center justify-center p-4";
            overlay.style.background = "rgba(0,0,0,0.85)";
            overlay.innerHTML = `
                <div class="rounded-2xl p-6 w-[380px] max-w-full shadow-2xl text-center"
                     style="background:var(--card-bg);border:1px solid var(--card-border);color:var(--color-on-surface)">
                    <div class="w-14 h-14 rounded-full bg-red-600/20 text-red-500 mx-auto flex items-center justify-center mb-3">
                        <span class="material-symbols-outlined text-3xl">power_settings_new</span>
                    </div>
                    <h3 class="text-lg font-bold mb-2">${App.t("system_reboot", "Restart komputera")}</h3>
                    <p class="text-xs mb-6" style="color:var(--text-dim)">${App.t("system_reboot_confirm", "Czy na pewno chcesz zrestartować cały komputer (baremetal)? Nastąpi pełny reboot systemu.")}</p>
                    <div class="flex gap-3 justify-center">
                        <button class="px-5 py-2.5 rounded-xl text-xs font-bold hover:opacity-80 transition-opacity"
                                style="background:var(--card-border);color:var(--text-mid)"
                                onclick="document.getElementById('system-reboot-modal').remove()">
                            ${App.t("cancel", "Anuluj")}
                        </button>
                        <button class="px-6 py-2.5 bg-red-600 hover:bg-red-500 text-white rounded-xl text-xs font-bold transition-colors flex items-center gap-1.5"
                                onclick="App.rebootSystem()">
                            <span class="material-symbols-outlined text-sm">power_settings_new</span>
                            ${App.t("system_reboot", "Restartuj system")}
                        </button>
                    </div>
                </div>
            `;
        },

        /** Execute baremetal OS reboot and show rebooting splash */
        async rebootSystem() {
            const modal = document.getElementById("system-reboot-modal");
            if (modal) modal.remove();

            let splash = document.getElementById("system-rebooting-overlay");
            if (!splash) {
                splash = document.createElement("div");
                splash.id = "system-rebooting-overlay";
                document.body.appendChild(splash);
            }
            splash.className = "fixed inset-0 z-[300] flex flex-col items-center justify-center bg-black text-white p-6";
            splash.innerHTML = `
                <div class="flex flex-col items-center gap-4 text-center">
                    <span class="material-symbols-outlined text-6xl text-red-500 animate-spin">sync</span>
                    <h2 class="text-2xl font-bold">${App.t("system_rebooting", "Restartowanie komputera...")}</h2>
                    <p class="text-xs text-zinc-400 max-w-sm">${App.t("system_reboot_desc", "Pełny reboot OS (np. przy braku karty dźwiękowej). Panel powróci automatycznie.")}</p>
                </div>
            `;

            try {
                await fetch("/api/system/reboot", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" }
                });
            } catch (e) {
                console.log("System reboot triggered", e);
            }

            // Wait 8 seconds before polling (full system reboot takes time)
            let checkCount = 0;
            setTimeout(() => {
                const pollInterval = setInterval(async () => {
                    checkCount++;
                    try {
                        const res = await fetch("/api/data", { cache: "no-store" });
                        if (res.ok) {
                            clearInterval(pollInterval);
                            setTimeout(() => window.location.reload(true), 1000);
                        }
                    } catch (e) {
                        // still booting
                    }
                    if (checkCount > 90) {
                        clearInterval(pollInterval);
                        window.location.reload(true);
                    }
                }, 2000);
            }, 8000);
        },

        /** Restart Android Auto service */
        async restartAA() {
            try {
                await fetch("/api/aa/restart", { method: "POST" });
            } catch (e) {
                console.error("AA restart failed:", e);
            }
        },

        /** Toggle Android Auto Auto-restart */
        async setAAAutoRestart(enabled) {
            try {
                await fetch("/api/aa/config", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ auto_restart: enabled }),
                });
            } catch (e) {
                console.error("Set AA auto-restart failed:", e);
            }
        },

        /** Initialize the application */
        async init() {
            _appEl = document.getElementById("app");

            // Boot/wake splash overlay — shows small.mp4 until live data is
            // flowing, and replays on every WebSocket reconnect-after-sleep.
            if (typeof Splash !== "undefined") Splash.init();

            // Load config and i18n
            await loadConfig();
            await loadI18n(_config.language);

            // Apply theme
            applyTheme(_currentTheme);

            // Init WebSocket
            DataStore.init();

            // Global BT pairing monitor — checks for phone-initiated pairing
            _startGlobalPairingPoll();

            // Listen for data updates
            DataStore.subscribe("*", onDataUpdate);

            // SWC navigate_aa → switch to Android Auto screen
            DataStore.subscribe("navigate_aa", (val) => {
                if (val && _currentScreen !== "a2") navigateTo("a2");
            });

            // SWC HOME → main screen A1
            DataStore.subscribe("home", (val) => {
                if (val && _currentScreen !== "a1") navigateTo("a1");
            });

            // Keyboard input
            document.addEventListener("keydown", handleKeyDown);

            // Edge gestures (touchscreen): pull down from the top = next
            // screen, swipe up from the bottom = NavBar.
            _initTouchSwipe();

            // Live top-bar clock (i18n is loaded, so the date is localised).
            _startClock();

            const restoreTarget = _loadLastScreen() || "a1";
            let bootMode = "warm";
            try {
                const res = await fetch("/api/boot_mode");
                const bm = await res.json();
                bootMode = bm.boot_mode || "warm";
            } catch (e) { /* default to warm */ }

            // An incoming call may already have switched to A8 while the
            // boot-mode fetch was in flight (data flows from DataStore.init
            // above) — only take the boot path if nothing navigated yet.
            if (_currentScreen !== "init") {
                /* keep the screen the call (or SWC) chose */
            } else if (bootMode === "cold") {
                navigateTo(restoreTarget);
            } else {
                navigateTo("init");
                setTimeout(() => {
                    if (_currentScreen === "init") {
                        navigateTo(restoreTarget);
                    }
                }, 4000);
            }

            // Tell the splash player that the dashboard has actually
            // rendered. /api/ready is the gate bcm-splash-play.sh polls,
            // so this flips the splash off the moment the user can see
            // BCM. Wrapped in requestAnimationFrame to make sure paint
            // happened before we claim ready.
            requestAnimationFrame(() => {
                requestAnimationFrame(() => {
                    fetch("/api/ready", {method: "POST"}).catch(() => {});
                });
            });
        },
    };
})();

window.addEventListener("load", () => App.init());
