/**
 * A7 Performance Screen — boost gauge, 0-100 timer, telemetry.
 * Full implementation in Phase 9.
 */

App.registerScreen("a7", (() => {
    function render(container, theme, data) {
        const t = App.t.bind(App);
        const boost = (data.boost || 0).toFixed(2);
        const speed = Math.round(data.speed || 0);
        const rpm = Math.round(data.rpm || 0);
        const bgCls = theme === "modern" ? "bg-slate-100 text-slate-900" : "bg-black text-white";
        const cardBg = theme === "modern" ? "bg-white border-slate-200 shadow-sm" : "bg-zinc-900 border-zinc-800";
        const accentClr = theme === "autodelta" ? "#FF5F00" : theme === "modern" ? "#005596" : "#f59e0b";

        // Boost gauge SVG
        const boostPct = Math.min(100, Math.max(0, (parseFloat(boost) / 1.5) * 100));
        const r = 70, cx = 90, cy = 90, sw = 12;
        const circumference = Math.PI * r; // half circle
        const offset = circumference - (boostPct / 100 * circumference);

        container.innerHTML = `<div class="screen-container ${bgCls}">
            ${AppBar.render(theme, data)}
            <main class="content-area p-4 flex gap-4">
                <!-- Left: Boost gauge -->
                <div class="flex flex-col items-center justify-center w-[240px] shrink-0">
                    <svg viewBox="0 0 180 120" class="w-full">
                        <path d="M 10,100 A 80,80 0 0,1 170,100" fill="none" stroke="${theme==='modern'?'#e2e8f0':'#27272a'}" stroke-width="${sw}" stroke-linecap="round"/>
                        <path d="M 10,100 A 80,80 0 0,1 170,100" fill="none" stroke="${accentClr}" stroke-width="${sw}" stroke-linecap="round"
                              stroke-dasharray="${circumference}" stroke-dashoffset="${offset}" style="transition:stroke-dashoffset 0.5s;" data-perf="boost-arc"/>
                    </svg>
                    <div class="text-center -mt-8">
                        <span class="text-4xl font-black" style="color:${accentClr};" data-perf="boost-val">${boost}</span>
                        <span class="text-sm opacity-50 ml-1">BAR</span>
                    </div>
                    <span class="text-[10px] font-bold uppercase tracking-wider opacity-40 mt-2">${t("boost", "BOOST")}</span>
                </div>
                <!-- Right: Stats grid -->
                <div class="flex-1 grid grid-cols-2 gap-3">
                    <!-- Speed -->
                    <div class="${cardBg} border rounded-xl p-4 flex flex-col justify-center items-center">
                        <span class="text-[9px] font-bold uppercase opacity-40">${t("speed", "SPEED")}</span>
                        <span class="text-4xl font-black" data-perf="speed">${speed}</span>
                        <span class="text-xs opacity-40">km/h</span>
                    </div>
                    <!-- RPM -->
                    <div class="${cardBg} border rounded-xl p-4 flex flex-col justify-center items-center">
                        <span class="text-[9px] font-bold uppercase opacity-40">RPM</span>
                        <span class="text-3xl font-black" data-perf="rpm">${rpm}</span>
                        <div class="w-full h-1.5 rounded-full mt-2" style="background:${theme==='modern'?'#e2e8f0':'#27272a'};">
                            <div class="h-full rounded-full transition-all" style="width:${Math.min(100,rpm/50)}%;background:${accentClr};"></div>
                        </div>
                    </div>
                    <!-- 0-100 Timer -->
                    <div class="${cardBg} border rounded-xl p-4 flex flex-col justify-center items-center">
                        <span class="text-[9px] font-bold uppercase opacity-40">${t("timer_0_100", "0-100 km/h")}</span>
                        <span class="text-3xl font-black" data-perf="timer">--.-</span>
                        <span class="text-[9px] opacity-30">${t("best_time", "Best")}: --.-s</span>
                    </div>
                    <!-- G-Force -->
                    <div class="${cardBg} border rounded-xl p-4 flex flex-col justify-center items-center">
                        <span class="text-[9px] font-bold uppercase opacity-40">${t("g_force", "G-FORCE")}</span>
                        <span class="text-3xl font-black">0.00</span>
                        <span class="text-xs opacity-40">G</span>
                    </div>
                    <!-- Peak Boost -->
                    <div class="${cardBg} border rounded-xl p-3 flex items-center justify-between col-span-2">
                        <div>
                            <span class="text-[9px] font-bold uppercase opacity-40">${t("peak_boost", "PEAK BOOST")}</span>
                            <div class="text-xl font-black" style="color:${accentClr};">0.00 <span class="text-xs opacity-50">BAR</span></div>
                        </div>
                        <div>
                            <span class="text-[9px] font-bold uppercase opacity-40">${t("voltage", "VOLTAGE")}</span>
                            <div class="text-xl font-black">${(data.battery_voltage||12.6).toFixed(1)} <span class="text-xs opacity-50">V</span></div>
                        </div>
                    </div>
                </div>
            </main>
            ${NavBar.render(theme, "a7")}
        </div>`;
    }

    let _peakBoost = 0;
    let _timerStart = 0;
    let _timerRunning = false;
    let _bestTime = null;

    function update(data) {
        const boost = parseFloat(data.boost || 0);
        const speed = Math.round(data.speed || 0);
        const rpm = Math.round(data.rpm || 0);

        // Track peak boost
        if (boost > _peakBoost) _peakBoost = boost;

        // 0-100 timer logic
        if (!_timerRunning && speed >= 3 && speed < 10) {
            _timerRunning = true;
            _timerStart = Date.now();
        }
        if (_timerRunning && speed >= 100) {
            const elapsed = ((Date.now() - _timerStart) / 1000).toFixed(1);
            _timerRunning = false;
            if (!_bestTime || parseFloat(elapsed) < parseFloat(_bestTime)) {
                _bestTime = elapsed;
            }
            const timerEl = document.querySelector('[data-perf="timer"]');
            if (timerEl) timerEl.textContent = elapsed;
            const bestEl = document.querySelector('[data-perf="best"]');
            if (bestEl) bestEl.textContent = `${App.t("best_time")}: ${_bestTime}s`;
        }
        if (_timerRunning && speed < 2) _timerRunning = false;

        // Update DOM elements
        const boostEl = document.querySelector('[data-perf="boost-val"]');
        if (boostEl) boostEl.textContent = boost.toFixed(2);
        const speedEl = document.querySelector('[data-perf="speed"]');
        if (speedEl) speedEl.textContent = speed;
        const rpmEl = document.querySelector('[data-perf="rpm"]');
        if (rpmEl) rpmEl.textContent = rpm;
        const peakEl = document.querySelector('[data-perf="peak"]');
        if (peakEl) peakEl.textContent = _peakBoost.toFixed(2);
        const rpmBar = document.querySelector('[data-perf="rpm-bar"]');
        if (rpmBar) rpmBar.style.width = `${Math.min(100, rpm / 50)}%`;
        // Update boost gauge arc
        const arc = document.querySelector('[data-perf="boost-arc"]');
        if (arc) {
            const pct = Math.min(100, Math.max(0, (boost / 1.5) * 100));
            const r = 70;
            const circ = Math.PI * r;
            arc.setAttribute("stroke-dashoffset", String(circ - (pct / 100 * circ)));
        }
    }

    return { render, update };
})());
