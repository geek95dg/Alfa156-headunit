/**
 * BCM v8.5 — Small Display (4.3" 800x480)
 * Stats carousel + notification popups + reverse camera overlay.
 */

(() => {
    const app = document.getElementById("app");
    let data = {};
    let currentPage = 0;
    let cycleTimer = null;
    let popupQueue = [];
    let popupActive = false;
    let reverseActive = false;
    let theme = "heritage";

    // --- WebSocket ---
    function connectWS() {
        const proto = location.protocol === "https:" ? "wss:" : "ws:";
        const ws = new WebSocket(`${proto}//${location.host}/ws`);
        ws.onmessage = (e) => {
            try {
                data = JSON.parse(e.data);
                onDataUpdate();
            } catch (err) {}
        };
        ws.onclose = () => setTimeout(connectWS, 2000);
        ws.onerror = () => ws.close();
    }

    // --- Load config ---
    async function loadConfig() {
        try {
            const res = await fetch("/api/config");
            const cfg = await res.json();
            theme = cfg.theme || "heritage";
            document.body.setAttribute("data-theme", theme);
        } catch (e) {}
    }

    // --- Time formatting ---
    function formatTime() {
        return new Date().toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit", hour12: false });
    }
    function formatDate() {
        const d = new Date();
        const days = ["NIE","PON","WT","ŚR","CZW","PT","SOB"];
        const months = ["STY","LUT","MAR","KWI","MAJ","CZE","LIP","SIE","WRZ","PAŹ","LIS","GRU"];
        return `${days[d.getDay()]} ${d.getDate()} ${months[d.getMonth()]}`;
    }

    // --- Carousel pages ---
    const pages = [
        { icon: "local_gas_station", key: "fuel_level", label: "POZIOM PALIWA", unit: "%", format: v => Math.round(v || 0) },
        { icon: "device_thermostat", key: "coolant_temp", label: "TEMP. PŁYNU", unit: "°C", format: v => Math.round(v || 0) },
        { icon: "thermostat", key: "ext_temp", label: "TEMP. ZEWN.", unit: "°C", format: v => v != null ? Math.round(v) : "--" },
        { icon: "thermostat_auto", key: "int_temp", label: "TEMP. WEWN.", unit: "°C", format: v => v != null ? Math.round(v) : "--" },
    ];

    function renderCarousel() {
        const p = pages[currentPage];
        const val = p.format(data[p.key]);
        app.innerHTML = `
            <div class="screen">
                <div class="header">
                    <div><span class="time">${formatTime()}</span> <span class="date">${formatDate()}</span></div>
                    <div style="font-size:12px;font-weight:600;opacity:0.4;">BCM v8.5</div>
                </div>
                <div class="content">
                    <span class="material-symbols-outlined stat-icon">${p.icon}</span>
                    <div class="stat-value">${val}<span class="stat-unit">${p.unit}</span></div>
                    <div class="stat-label">${p.label}</div>
                </div>
                <div class="dots">
                    ${pages.map((_, i) => `<div class="dot ${i === currentPage ? 'active' : ''}"></div>`).join("")}
                </div>
                <div id="popup-container"></div>
            </div>`;
    }

    function nextPage() {
        currentPage = (currentPage + 1) % pages.length;
        renderCarousel();
        showCurrentPopup();
    }

    function startCycle() {
        if (cycleTimer) clearInterval(cycleTimer);
        cycleTimer = setInterval(nextPage, 5000);
    }

    // --- Notification Popups ---
    function onDataUpdate() {
        // Check reverse
        if (data.reverse === true && !reverseActive) {
            showReverse();
        } else if (data.reverse === false && reverseActive) {
            hideReverse();
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

        // Update reverse sensors if active
        if (reverseActive) updateReverseSensors();

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

    // --- Reverse Camera Overlay ---
    function showReverse() {
        reverseActive = true;
        if (cycleTimer) clearInterval(cycleTimer);
        const labels = ["LL", "CL", "CP", "PP"];
        const dists = data.parking_distances || [];

        app.innerHTML = `<div class="reverse-overlay">
            <div class="camera-area">
                <img id="cam-feed" src="/api/camera/stream" style="display:none;position:absolute;inset:0;width:100%;height:100%;object-fit:cover;"
                     onload="this.style.display='block';document.getElementById('cam-placeholder').style.display='none';"
                     onerror="this.style.display='none';">
                <div id="cam-placeholder" style="display:flex;flex-direction:column;align-items:center;color:#52525b;">
                    <span class="material-symbols-outlined" style="font-size:64px;">videocam_off</span>
                    <span style="font-size:14px;font-weight:700;margin-top:8px;">BRAK KAMERY COFANIA</span>
                </div>
                <div class="badge">R</div>
                <div style="position:absolute;bottom:0;left:50%;transform:translateX(-50%);width:55%;height:65%;border-left:2px solid rgba(34,197,94,0.4);border-right:2px solid rgba(34,197,94,0.4);border-bottom:2px solid rgba(34,197,94,0.4);border-radius:0 0 16px 16px;"></div>
                <div style="position:absolute;bottom:18%;left:50%;transform:translateX(-50%);width:45%;border-top:2px dashed rgba(234,179,8,0.4);"></div>
                <div style="position:absolute;bottom:36%;left:50%;transform:translateX(-50%);width:35%;border-top:2px dashed rgba(239,68,68,0.4);"></div>
            </div>
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
            </div>
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

    function hideReverse() {
        reverseActive = false;
        renderCarousel();
        startCycle();
    }

    // --- Init ---
    async function init() {
        await loadConfig();
        renderCarousel();
        startCycle();
        connectWS();
        // Update time every second
        setInterval(() => {
            const timeEl = app.querySelector(".time");
            if (timeEl) timeEl.textContent = formatTime();
        }, 1000);
    }

    init();
})();
