/**
 * BCM v8.5 — Second Display (6.86" widescreen 1280x480)
 * 1x4 stats row + persistent media bar + notification popups.
 *
 * Reverse: the cameras + parking sensors are shown on the MAIN display now,
 * so this screen switches to a full-screen media-control view (now-playing +
 * prev/play-pause/next). Outside reverse it shows the stats row + media bar.
 */

(() => {
    const app = document.getElementById("app");
    let data = {};
    let popupQueue = [];
    let popupActive = false;
    let activeCamera = null;   // "rear" | "left" | "right" | null
    let theme = "heritage";
    let lang = "pl";

    // --- Boot/wake splash overlay ---
    // Same rationale as the main display (web/js/components/splash.js): a DRM
    // splash can't be replayed once X owns the screen and the page isn't
    // reloaded on an S3 wake, so play /splash/small.mp4 in-browser on load and
    // on every reconnect-after-sleep, dismissing once live data resumes.
    let _splashEl = null, _splashShownAt = 0, _splashHideTimer = null, _splashMaxTimer = null, _wsDownSince = 0;
    function showSplash() {
        if (_splashEl) return;
        _splashEl = document.createElement("div");
        _splashEl.id = "bcm-splash-overlay";
        _splashEl.style.cssText = "position:fixed;inset:0;z-index:9999;background:#000;opacity:1;transition:opacity 0.5s ease;";
        _splashEl.innerHTML = '<video autoplay loop muted playsinline style="width:100%;height:100%;object-fit:cover;background:#000;" onerror="this.style.display=\'none\'"><source src="/splash/small.mp4" type="video/mp4"></video>';
        document.body.appendChild(_splashEl);
        _splashShownAt = Date.now();
        clearTimeout(_splashMaxTimer);
        _splashMaxTimer = setTimeout(hideSplash, 12000);
    }
    function hideSplash() {
        clearTimeout(_splashHideTimer); _splashHideTimer = null;
        clearTimeout(_splashMaxTimer); _splashMaxTimer = null;
        if (!_splashEl) return;
        const el = _splashEl; _splashEl = null;
        el.style.opacity = "0";
        setTimeout(() => { try { el.remove(); } catch (e) {} }, 550);
    }
    function scheduleSplashHide() {
        if (!_splashEl || _splashHideTimer) return;
        const wait = Math.max(1200 - (Date.now() - _splashShownAt), 600);
        _splashHideTimer = setTimeout(hideSplash, wait);
    }

    // --- WebSocket ---
    function connectWS() {
        const proto = location.protocol === "https:" ? "wss:" : "ws:";
        const ws = new WebSocket(`${proto}//${location.host}/ws`);
        ws.onmessage = (e) => {
            try {
                data = JSON.parse(e.data);
                onDataUpdate();
                scheduleSplashHide();   // live data flowing → dismiss splash
            } catch (err) {}
        };
        ws.onopen = () => {
            if (_wsDownSince && Date.now() - _wsDownSince > 4000) showSplash();
            _wsDownSince = 0;
            loadConfig().then(() => renderGrid());
        };
        ws.onclose = () => { _wsDownSince = _wsDownSince || Date.now(); setTimeout(connectWS, 2000); };
        ws.onerror = () => ws.close();
    }

    // --- Load config ---
    async function loadConfig() {
        try {
            const res = await fetch("/api/config");
            const cfg = await res.json();
            theme = cfg.theme || "heritage";
            lang = cfg.language || "pl";
            document.body.setAttribute("data-theme", theme);
        } catch (e) {}
    }

    // --- Time formatting ---
    function formatTime() {
        return new Date().toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit", hour12: false });
    }
    function formatDate() {
        const d = new Date();
        const daysMap = {
            pl: ["NIE","PON","WT","\u015aR","CZW","PT","SOB"],
            en: ["SUN","MON","TUE","WED","THU","FRI","SAT"]
        };
        const monthsMap = {
            pl: ["STY","LUT","MAR","KWI","MAJ","CZE","LIP","SIE","WRZ","PA\u0179","LIS","GRU"],
            en: ["JAN","FEB","MAR","APR","MAY","JUN","JUL","AUG","SEP","OCT","NOV","DEC"]
        };
        const days = daysMap[lang] || daysMap["pl"];
        const months = monthsMap[lang] || monthsMap["pl"];
        return `${days[d.getDay()]} ${d.getDate()} ${months[d.getMonth()]}`;
    }

    // --- i18n labels ---
    const LABELS = {
        pl: {
            fuel: "POZIOM PALIWA", coolant: "TEMP. PŁYNU",
            ext_temp: "TEMP. ZEWN.", int_temp: "TEMP. WEWN.",
        },
        en: {
            fuel: "FUEL LEVEL", coolant: "COOLANT TEMP",
            ext_temp: "EXT. TEMP", int_temp: "INT. TEMP",
        },
    };

    function l(key) {
        return (LABELS[lang] || LABELS["pl"])[key] || key;
    }

    // --- 1x4 stat cells ---
    const cells = [
        { icon: "local_gas_station", key: "fuel_level",   labelKey: "fuel",     unit: "%",  format: v => Math.round(v || 0) },
        { icon: "device_thermostat", key: "coolant_temp", labelKey: "coolant",  unit: "°C", format: v => Math.round(v || 0) },
        { icon: "thermostat",        key: "ext_temp",     labelKey: "ext_temp", unit: "°C", format: v => v != null ? Math.round(v) : "--" },
        { icon: "thermostat_auto",   key: "int_temp",     labelKey: "int_temp", unit: "°C", format: v => v != null ? Math.round(v) : "--" },
    ];

    // --- Media bar (persistent, under the stat row) ---
    function mediaBarHtml() {
        const title = data.bt_media_title || (data.bt_connected ? (lang === "pl" ? "Brak utworu" : "No track") : (lang === "pl" ? "Brak BT" : "No BT"));
        const artist = data.bt_media_artist || "—";
        const playIcon = data.bt_media_playing ? "pause" : "play_arrow";
        return `
            <div class="media-bar">
                <span class="material-symbols-outlined mb-icon">music_note</span>
                <div class="mb-meta">
                    <span class="mb-title" id="mb-title">${title}</span>
                    <span class="mb-artist" id="mb-artist">${artist}</span>
                </div>
                <button class="mb-btn" onclick="window.__mediaCmd('previous')"><span class="material-symbols-outlined">skip_previous</span></button>
                <button class="mb-btn mb-play" onclick="window.__mediaCmd('playpause')"><span class="material-symbols-outlined" id="mb-play">${playIcon}</span></button>
                <button class="mb-btn" onclick="window.__mediaCmd('next')"><span class="material-symbols-outlined">skip_next</span></button>
            </div>`;
    }

    function updateMediaBar() {
        const t = document.getElementById("mb-title");
        const a = document.getElementById("mb-artist");
        const p = document.getElementById("mb-play");
        if (t) t.textContent = data.bt_media_title || (data.bt_connected ? (lang === "pl" ? "Brak utworu" : "No track") : (lang === "pl" ? "Brak BT" : "No BT"));
        if (a) a.textContent = data.bt_media_artist || "—";
        if (p) p.textContent = data.bt_media_playing ? "pause" : "play_arrow";
    }

    window.__mediaCmd = function (action) {
        fetch(`/api/media/${action}`, { method: "POST" }).catch(() => {});
    };

    function renderGrid() {
        const cellHtml = cells.map(c => {
            const val = c.format(data[c.key]);
            return `
                <div class="cell">
                    <span class="material-symbols-outlined cell-icon" aria-hidden="true">${c.icon}</span>
                    <div class="cell-value">${val}<span class="cell-unit">${c.unit}</span></div>
                    <div class="cell-label">${l(c.labelKey)}</div>
                </div>`;
        }).join("");

        app.innerHTML = `
            <div class="screen">
                <div class="header">
                    <div><span class="time">${formatTime()}</span> <span class="date">${formatDate()}</span></div>
                    <div style="font-size:12px;font-weight:600;opacity:0.4;">BCM v8.5</div>
                </div>
                <div class="grid">${cellHtml}</div>
                ${mediaBarHtml()}
                <div id="popup-container"></div>
            </div>`;
    }

    function updateGridValues() {
        // Lightweight in-place update without re-rendering the whole grid
        const valueEls = app.querySelectorAll(".cell-value");
        cells.forEach((c, i) => {
            const el = valueEls[i];
            if (!el) return;
            const val = c.format(data[c.key]);
            el.innerHTML = `${val}<span class="cell-unit">${c.unit}</span>`;
        });
        updateMediaBar();
    }

    // --- Reverse media view (full screen) ---
    // During reverse the MAIN display shows the cameras + parking sensors;
    // this second screen switches to large now-playing + transport controls.
    let mediaFullActive = false;
    function showMediaFull() {
        if (mediaFullActive) { updateMediaFull(); return; }
        mediaFullActive = true;
        const title = data.bt_media_title || (lang === "pl" ? "Brak utworu" : "No track");
        const artist = data.bt_media_artist || "—";
        const playIcon = data.bt_media_playing ? "pause" : "play_arrow";
        const overlay = document.createElement("div");
        overlay.className = "media-full";
        overlay.id = "media-full";
        overlay.innerHTML = `
            <div class="mf-art"><span class="material-symbols-outlined">music_note</span></div>
            <div style="text-align:center;max-width:100%;">
                <div class="mf-title" id="mf-title">${title}</div>
                <div class="mf-artist" id="mf-artist">${artist}</div>
            </div>
            <div class="mf-controls">
                <button class="mb-btn" onclick="window.__mediaCmd('previous')"><span class="material-symbols-outlined">skip_previous</span></button>
                <button class="mb-btn mb-play" onclick="window.__mediaCmd('playpause')"><span class="material-symbols-outlined" id="mf-play">${playIcon}</span></button>
                <button class="mb-btn" onclick="window.__mediaCmd('next')"><span class="material-symbols-outlined">skip_next</span></button>
            </div>`;
        app.appendChild(overlay);
    }
    function updateMediaFull() {
        const t = document.getElementById("mf-title");
        const a = document.getElementById("mf-artist");
        const p = document.getElementById("mf-play");
        if (t) t.textContent = data.bt_media_title || (lang === "pl" ? "Brak utworu" : "No track");
        if (a) a.textContent = data.bt_media_artist || "—";
        if (p) p.textContent = data.bt_media_playing ? "pause" : "play_arrow";
    }
    function hideMediaFull() {
        mediaFullActive = false;
        const o = document.getElementById("media-full");
        if (o) o.remove();
    }

    // --- Notification popups + reverse routing ---
    function onDataUpdate() {
        // During reverse the cameras + parking sensors live on the MAIN
        // display now; this second screen switches to the media-control view.
        // (Side-camera / blinker states leave this screen on its normal
        // stats+media layout — only reverse swaps to the big media view.)
        const inReverse = data.camera_active === "rear" || data.reverse;
        if (inReverse) {
            showMediaFull();
        } else if (mediaFullActive) {
            hideMediaFull();
            renderGrid();
        }

        // Queue notifications
        const notifs = data.notifications || [];
        for (const n of notifs) {
            if (!popupQueue.find(q => q.type === n.type)) {
                popupQueue.push(n);
            }
        }
        // Remove resolved notifications
        popupQueue = popupQueue.filter(q => notifs.some(n => n.type === q.type) || q.duration === 0);

        if (!popupActive && popupQueue.length > 0) {
            showNextPopup();
        }

        if (inReverse) {
            updateMediaFull();
        } else {
            updateGridValues();
        }

        // Update time in header
        const timeEl = app.querySelector(".time");
        if (timeEl) timeEl.textContent = formatTime();
    }

    function showNextPopup() {
        if (popupQueue.length === 0) { popupActive = false; return; }
        popupActive = true;
        const n = popupQueue[0];
        showCurrentPopup();

        if (n.duration > 0) {
            setTimeout(() => {
                popupQueue.shift();
                popupActive = false;
                hidePopup();
                if (popupQueue.length > 0) setTimeout(showNextPopup, 500);
            }, n.duration);
        }
    }

    function showCurrentPopup() {
        const container = document.getElementById("popup-container");
        if (!container || popupQueue.length === 0) return;
        const n = popupQueue[0];
        const sevClass = n.severity === "danger" ? "severity-danger" : "";
        container.innerHTML = `<div class="popup ${sevClass}">
            <span class="material-symbols-outlined popup-icon">${n.icon}</span>
            <span class="popup-text">${n.text}</span>
        </div>`;
    }

    function hidePopup() {
        const container = document.getElementById("popup-container");
        if (container) container.innerHTML = "";
    }

    // --- Camera overlay (rear/left/right) ---
    const CAMERA_LABELS = {
        rear:  { badge: "R", title: "KAMERA COFANIA",   missing: "BRAK KAMERY COFANIA" },
        left:  { badge: "L", title: "KAMERA LEWA",      missing: "BRAK KAMERY LEWEJ"  },
        right: { badge: "P", title: "KAMERA PRAWA",     missing: "BRAK KAMERY PRAWEJ" },
    };

    function showCameraOverlay(role) {
        const meta = CAMERA_LABELS[role] || CAMERA_LABELS.rear;
        const streamUrl = `/api/camera/stream?cam=${role}&t=${Date.now()}`;
        const showParking = role === "rear";
        const labels = ["LL", "CL", "CP", "PP"];
        const dists = data.parking_distances || [];

        const sensorBarHtml = showParking ? `
            <div class="sensor-bar" id="sensor-bar">
                ${labels.map((lbl, i) => {
                    const d = dists[i] || 0;
                    const pct = d > 0 ? Math.min(100, d / 2 * 100) : 0;
                    const clr = d <= 0 ? "#27272a" : d < 0.3 ? "#ef4444" : d < 0.5 ? "#f97316" : d < 1.0 ? "#eab308" : "#22c55e";
                    const txtClr = d <= 0 ? "#52525b" : d < 0.3 ? "#f87171" : d < 0.5 ? "#fb923c" : d < 1.0 ? "#facc15" : "#4ade80";
                    return `<div class="sensor-item">
                        <span class="sensor-label">${lbl}</span>
                        <div class="sensor-gauge"><div class="sensor-fill" style="height:${pct}%;background:${clr};"></div></div>
                        <span class="sensor-value" style="color:${txtClr};">${d > 0 ? d.toFixed(1) + 'm' : '--'}</span>
                    </div>`;
                }).join("")}
                <div class="closest">
                    <span class="closest-label">NAJBLIŻEJ</span>
                    <span class="closest-value">${_closest(dists)}</span>
                    <span class="closest-unit">m</span>
                </div>
            </div>` : "";

        // For rear: overlay guide lines. For left/right: simple fullscreen feed.
        const guidesHtml = showParking ? `
            <div style="position:absolute;bottom:0;left:50%;transform:translateX(-50%);width:55%;height:65%;border-left:2px solid rgba(34,197,94,0.4);border-right:2px solid rgba(34,197,94,0.4);border-bottom:2px solid rgba(34,197,94,0.4);border-radius:0 0 16px 16px;"></div>
            <div style="position:absolute;bottom:18%;left:50%;transform:translateX(-50%);width:45%;border-top:2px dashed rgba(234,179,8,0.4);"></div>
            <div style="position:absolute;bottom:36%;left:50%;transform:translateX(-50%);width:35%;border-top:2px dashed rgba(239,68,68,0.4);"></div>` : "";

        app.innerHTML = `<div class="reverse-overlay camera-${role}">
            <div class="camera-area">
                <img id="cam-feed" src="${streamUrl}" style="display:none;position:absolute;inset:0;width:100%;height:100%;object-fit:cover;"
                     onload="this.style.display='block';document.getElementById('cam-placeholder').style.display='none';"
                     onerror="this.style.display='none';">
                <div id="cam-placeholder" style="display:flex;flex-direction:column;align-items:center;color:#52525b;">
                    <span class="material-symbols-outlined" style="font-size:64px;">videocam_off</span>
                    <span style="font-size:14px;font-weight:700;margin-top:8px;">${meta.missing}</span>
                </div>
                <div class="badge">${meta.badge}</div>
                <div class="camera-title">${meta.title}</div>
                ${guidesHtml}
            </div>
            ${sensorBarHtml}
        </div>`;
    }

    function _closest(dists) {
        const valid = (dists || []).filter(d => d > 0);
        return valid.length > 0 ? Math.min(...valid).toFixed(1) : "--";
    }

    function updateReverseSensors() {
        const dists = data.parking_distances || [];
        const fills = document.querySelectorAll(".sensor-fill");
        const values = document.querySelectorAll(".sensor-value");
        fills.forEach((el, i) => {
            const d = dists[i] || 0;
            const pct = d > 0 ? Math.min(100, d / 2 * 100) : 0;
            const clr = d <= 0 ? "#27272a" : d < 0.3 ? "#ef4444" : d < 0.5 ? "#f97316" : d < 1.0 ? "#eab308" : "#22c55e";
            el.style.height = `${pct}%`;
            el.style.background = clr;
        });
        values.forEach((el, i) => {
            const d = dists[i] || 0;
            el.textContent = d > 0 ? d.toFixed(1) + 'm' : '--';
        });
        const cv = document.querySelector(".closest-value");
        if (cv) cv.textContent = _closest(dists);
    }

    function hideCameraOverlay() {
        renderGrid();
    }

    // --- Dev keyboard shortcuts (bench testing without GPIO) ---
    // R = toggle rear camera, L = toggle left blinker, P = toggle right blinker
    // The shortcuts fake a camera_active field directly so the UI reacts
    // without needing the backend to publish anything on the event bus.
    function installDevKeys() {
        let fakeRole = null;
        document.addEventListener("keydown", (e) => {
            const key = e.key.toLowerCase();
            if (key === "r") {
                fakeRole = fakeRole === "rear" ? null : "rear";
            } else if (key === "l") {
                fakeRole = fakeRole === "left" ? null : "left";
            } else if (key === "p") {
                fakeRole = fakeRole === "right" ? null : "right";
            } else {
                return;
            }
            data.camera_active = fakeRole;
            onDataUpdate();
        });
    }

    // --- Init ---
    async function init() {
        showSplash();   // boot splash; dismissed when first WS data arrives
        await loadConfig();
        renderGrid();
        connectWS();
        installDevKeys();
        // Update time every second
        setInterval(() => {
            const timeEl = app.querySelector(".time");
            if (timeEl) timeEl.textContent = formatTime();
        }, 1000);
    }

    init();
})();
