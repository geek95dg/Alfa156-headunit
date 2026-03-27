/**
 * A2 Trip Screen — Trip statistics, consumption chart with scales and driving profile.
 * Everything fits in 800x480 — no scrolling.
 */

App.registerScreen("a2", (() => {
    function render(container, theme, data) {
        if (theme === "heritage") container.innerHTML = _renderHeritage(data);
        else if (theme === "modern") container.innerHTML = _renderModern(data);
        else if (theme === "autodelta") container.innerHTML = _renderAutodelta(data);
        else container.innerHTML = _renderHeritage(data);
    }

    function update(data) {
        _updateEl("trip-dist", (data.trip_distance || 0).toFixed(1));
        _updateEl("trip-avg-speed", Math.round(data.avg_speed || 0));
        _updateEl("trip-time", data.trip_time || "00:00");
        _updateEl("trip-avg-cons", (data.avg_consumption || 0).toFixed(1));
        _updateEl("trip-range", Math.round(data.estimated_range || 0));
        _updateEl("trip-instant", (data.instant_consumption || 0).toFixed(1));
    }

    function _updateEl(id, text) {
        const el = document.getElementById(id);
        if (el) el.textContent = text;
    }

    /** Driving profile based on consumption */
    function _drivingProfile(avgCons) {
        const t = App.t.bind(App);
        if (avgCons < 5) return { label: t("eco"), color: "text-green-400", bg: "bg-green-900/30", icon: "eco" };
        if (avgCons < 7) return { label: t("normal"), color: "text-blue-400", bg: "bg-blue-900/30", icon: "speed" };
        if (avgCons < 10) return { label: t("dynamic"), color: "text-amber-400", bg: "bg-amber-900/30", icon: "bolt" };
        return { label: t("sport"), color: "text-red-400", bg: "bg-red-900/30", icon: "local_fire_department" };
    }

    /** Bar chart with Y-axis scale and time labels */
    function _chartWithScale(values, labels, theme, maxY) {
        const yLabels = [maxY, Math.round(maxY * 0.75), Math.round(maxY * 0.5), Math.round(maxY * 0.25), 0];
        const barColor = theme === "autodelta" ? "#FF5F00" : theme === "modern" ? "#005596" : "#f59e0b";
        const dimColor = theme === "modern" ? "#e2e8f0" : "#27272a";
        const textColor = theme === "modern" ? "text-slate-400" : "text-zinc-600";

        const bars = values.map((v, i) => {
            const pct = Math.min(100, (v / maxY * 100)).toFixed(0);
            const isRecent = i >= values.length - 2;
            const opacity = isRecent ? 1 : 0.5;
            return `<div class="flex flex-col items-center flex-1 gap-1">
                <div class="w-full h-full flex items-end justify-center">
                    <div class="w-[80%] rounded-t-sm transition-all duration-300" style="height:${pct}%;background:${barColor};opacity:${opacity};"></div>
                </div>
                <span class="text-[8px] ${textColor} font-bold">${labels[i] || ''}</span>
            </div>`;
        }).join("");

        return `<div class="flex h-full">
            <!-- Y axis -->
            <div class="flex flex-col justify-between pr-2 py-1 ${textColor} text-[9px] font-bold w-8 shrink-0 text-right">
                ${yLabels.map(v => `<span>${v}</span>`).join("")}
            </div>
            <!-- Chart area -->
            <div class="flex-1 flex flex-col">
                <div class="flex-1 flex items-end border-l border-b" style="border-color:${dimColor}">
                    ${bars}
                </div>
            </div>
        </div>`;
    }

    function _renderHeritage(data) {
        const t = App.t.bind(App);
        const dist = (data.trip_distance || 0).toFixed(1);
        const avgSpd = Math.round(data.avg_speed || 0);
        const time = data.trip_time || "0h 0m";
        const avgCons = (data.avg_consumption || 0).toFixed(1);
        const instantCons = (data.instant_consumption || 0).toFixed(1);
        const range = Math.round(data.estimated_range || 0);
        const profile = _drivingProfile(parseFloat(avgCons));
        const chartValues = [4.2, 5.8, 7.1, 8.5, 6.3, 7.9, parseFloat(instantCons) || 6.5];
        const chartLabels = ["-30m", "-25m", "-20m", "-15m", "-10m", "-5m", "Now"];

        return `<div class="screen-container bg-[#1a0f0a] text-zinc-100">
            ${AppBar.render("heritage", data)}
            <main class="content-area flex overflow-hidden">
                <!-- Left: Compact stats -->
                <div class="w-[220px] p-4 flex flex-col gap-3 border-r border-amber-900/30 bg-[#221610] shrink-0">
                    <h1 class="text-lg font-bold text-amber-500 uppercase tracking-wide amber-glow">${t("trip_title")}</h1>
                    <div class="p-3 rounded-lg bg-zinc-900/60 border border-zinc-800">
                        <p class="text-[9px] text-zinc-500 uppercase tracking-wider">${t("distance")}</p>
                        <p class="text-2xl font-bold text-amber-500 amber-glow"><span id="trip-dist">${dist}</span> <span class="text-xs text-zinc-500">km</span></p>
                    </div>
                    <div class="flex gap-2">
                        <div class="flex-1 p-2 rounded-lg bg-zinc-900/60 border border-zinc-800">
                            <p class="text-[8px] text-zinc-500 uppercase">${t("avg_speed")}</p>
                            <p class="text-lg font-bold text-zinc-200"><span id="trip-avg-speed">${avgSpd}</span> <span class="text-[9px] text-zinc-500">km/h</span></p>
                        </div>
                        <div class="flex-1 p-2 rounded-lg bg-zinc-900/60 border border-zinc-800">
                            <p class="text-[8px] text-zinc-500 uppercase">${t("time")}</p>
                            <p id="trip-time" class="text-lg font-bold text-zinc-200">${time}</p>
                        </div>
                    </div>
                    <div class="p-3 rounded-lg bg-zinc-900/60 border border-zinc-800">
                        <p class="text-[9px] text-zinc-500 uppercase tracking-wider">${t("avg_consumption")}</p>
                        <p class="text-2xl font-bold text-amber-500 amber-glow"><span id="trip-avg-cons">${avgCons}</span> <span class="text-xs text-zinc-500">L/100km</span></p>
                    </div>
                    <div class="p-2 rounded-lg ${profile.bg} border border-zinc-800 flex items-center gap-2">
                        <span class="material-symbols-outlined ${profile.color}" style="font-size:20px;">${profile.icon}</span>
                        <div>
                            <p class="text-[8px] text-zinc-500 uppercase">${t("driving_style")}</p>
                            <p class="text-sm font-bold ${profile.color}">${profile.label}</p>
                        </div>
                    </div>
                </div>
                <!-- Right: Chart with scale -->
                <div class="flex-1 p-4 flex flex-col bg-[#1a0f0a]">
                    <div class="flex justify-between items-center mb-2">
                        <span class="text-[10px] text-zinc-500 font-bold uppercase tracking-wider">${t("fuel_consumption")} (L/100km)</span>
                        <div class="flex items-center gap-2">
                            <span class="text-[9px] text-zinc-600">Now:</span>
                            <span id="trip-instant" class="text-sm font-bold text-amber-500">${instantCons}</span>
                            <span class="text-[9px] text-zinc-600">L/100km</span>
                        </div>
                    </div>
                    <div class="flex-1 bg-zinc-900/50 rounded-xl border border-zinc-800 p-3">
                        ${_chartWithScale(chartValues, chartLabels, "heritage", 15)}
                    </div>
                    <div class="flex justify-between items-center mt-2 px-1">
                        <span class="text-[9px] text-zinc-600">${t("est_range")}: <span id="trip-range" class="text-amber-500 font-bold">${range}</span> km</span>
                    </div>
                </div>
            </main>
            ${NavBar.render("heritage", "a2")}
        </div>`;
    }

    function _renderModern(data) {
        const t = App.t.bind(App);
        const dist = (data.trip_distance || 0).toFixed(1);
        const avgSpd = Math.round(data.avg_speed || 0);
        const time = data.trip_time || "01:45";
        const avgCons = (data.avg_consumption || 0).toFixed(1);
        const instantCons = (data.instant_consumption || 0).toFixed(1);
        const range = Math.round(data.estimated_range || 0);
        const profile = _drivingProfile(parseFloat(avgCons));
        const graphValues = [8, 12, 10, 14, 7, 9, 11, 6, 8, 7];
        const graphLabels = ["-30m", "", "-20m", "", "-10m", "", "-5m", "", "", "Now"];

        return `<div class="screen-container text-slate-900" style="background:#f8fafc;">
            ${AppBar.render("modern", data)}
            <main class="content-area p-4 overflow-hidden flex gap-3" style="background:#f1f5f9;">
                <!-- Left: Stats -->
                <div class="w-[200px] flex flex-col gap-2 shrink-0">
                    <div class="bg-white rounded-xl p-3 shadow-sm border border-slate-200 flex-1 flex flex-col justify-between">
                        <div>
                            <span class="text-[9px] font-bold text-slate-400 uppercase tracking-wider">${t("trip_dist")}</span>
                            <h2 class="text-2xl font-extrabold text-[#005596]"><span id="trip-dist">${dist}</span> <span class="text-xs font-normal text-slate-500">km</span></h2>
                        </div>
                        <div class="flex justify-between mt-2">
                            <div><span class="text-[8px] font-bold text-slate-400 uppercase">${t("avg_speed")}</span><br><span id="trip-avg-speed" class="font-bold text-slate-700 text-sm">${avgSpd}</span> <span class="text-[9px]">km/h</span></div>
                            <div><span class="text-[8px] font-bold text-slate-400 uppercase">${t("time")}</span><br><span id="trip-time" class="font-bold text-slate-700 text-sm">${time}</span></div>
                        </div>
                    </div>
                    <div class="bg-[#005596] text-white rounded-xl p-3 shadow-md flex items-center justify-between">
                        <div>
                            <span class="text-[9px] font-bold text-white/70 uppercase">${t("avg_consumption")}</span>
                            <div class="text-xl font-bold"><span id="trip-avg-cons">${avgCons}</span> <span class="text-[9px] font-light">l/100km</span></div>
                        </div>
                        <span class="material-symbols-outlined text-2xl opacity-30">local_gas_station</span>
                    </div>
                    <div class="bg-white rounded-lg p-2 shadow-sm border border-slate-200 flex items-center gap-2">
                        <span class="material-symbols-outlined ${profile.color}" style="font-size:18px;">${profile.icon}</span>
                        <div>
                            <span class="text-[8px] font-bold text-slate-400 uppercase">${t("driving_style")}</span>
                            <p class="text-xs font-bold ${profile.color}">${profile.label}</p>
                        </div>
                    </div>
                </div>
                <!-- Right: Graph with scale -->
                <div class="flex-1 bg-white rounded-xl shadow-sm border border-slate-200 p-3 flex flex-col">
                    <div class="flex justify-between items-center mb-2">
                        <span class="text-[10px] font-bold text-slate-800 flex items-center gap-1">
                            <span class="material-symbols-outlined text-[#005596]" style="font-size:16px;">monitoring</span>
                            ${t("fuel_consumption")} (L/100km)
                        </span>
                        <span class="text-[9px] text-slate-500">Now: <span id="trip-instant" class="font-bold text-slate-700">${instantCons}</span></span>
                    </div>
                    <div class="flex-1">
                        ${_chartWithScale(graphValues, graphLabels, "modern", 20)}
                    </div>
                    <div class="flex justify-between mt-1 pt-1 border-t border-slate-100 text-[9px]">
                        <span class="text-slate-400">${t("est_range")}: <span id="trip-range" class="font-bold text-slate-700">${range}</span> km</span>
                    </div>
                </div>
            </main>
            ${NavBar.render("modern", "a2")}
        </div>`;
    }

    function _renderAutodelta(data) {
        const t = App.t.bind(App);
        const dist = (data.trip_distance || 0).toFixed(1);
        const avgSpd = Math.round(data.avg_speed || 0);
        const time = data.trip_time || "01:54";
        const range = Math.round(data.estimated_range || 0);
        const avgCons = (data.avg_consumption || 0).toFixed(1);
        const instantCons = (data.instant_consumption || 0).toFixed(1);
        const profile = _drivingProfile(parseFloat(avgCons));
        const chartValues = [5.1, 6.8, 9.2, 7.5, 5.9, 8.3, 11.2, 9.8, 4.5, 7.1, 6.4, parseFloat(instantCons) || 7.8];
        const chartLabels = ["", "", "", "", "", "", "", "", "", "", "", "Now"];

        return `<div class="screen-container bg-black text-white">
            ${AppBar.render("autodelta", data)}
            <main class="content-area px-4 py-2 flex flex-col">
                <!-- Header row -->
                <div class="flex justify-between items-center mb-2">
                    <div>
                        <h1 class="text-[#FF5F00] font-bold text-lg tracking-tight leading-none uppercase">${t("trip_analytics")}</h1>
                    </div>
                    <div class="flex items-center gap-3">
                        <div class="px-2 py-1 rounded ${profile.bg} flex items-center gap-1">
                            <span class="material-symbols-outlined ${profile.color}" style="font-size:14px;">${profile.icon}</span>
                            <span class="text-[10px] font-bold ${profile.color}">${profile.label}</span>
                        </div>
                        <span class="text-xl font-bold"><span id="trip-dist">${dist}</span> <span class="text-xs text-zinc-500">KM</span></span>
                    </div>
                </div>
                <!-- Main grid: chart + stats -->
                <div class="flex-1 flex gap-3 min-h-0">
                    <!-- Chart -->
                    <div class="flex-1 bg-zinc-900/50 rounded-xl border border-zinc-800 p-3 flex flex-col">
                        <span class="text-[9px] text-zinc-500 font-bold uppercase tracking-wider mb-1">${t("fuel_consumption")} L/100km</span>
                        <div class="flex-1">
                            ${_chartWithScale(chartValues, chartLabels, "autodelta", 15)}
                        </div>
                    </div>
                    <!-- Stats column -->
                    <div class="w-[180px] flex flex-col gap-2 shrink-0">
                        <div class="bg-zinc-900/50 rounded-xl border border-zinc-800 p-3 flex-1 flex flex-col justify-center">
                            <span class="text-[9px] text-zinc-500 font-bold uppercase tracking-widest">${t("avg_speed")}</span>
                            <span class="text-2xl font-bold text-white"><span id="trip-avg-speed">${avgSpd}</span> <span class="text-xs text-[#FF5F00]">KM/H</span></span>
                        </div>
                        <div class="bg-zinc-900/50 rounded-xl border border-zinc-800 p-3 flex-1 flex flex-col justify-center">
                            <span class="text-[9px] text-zinc-500 font-bold uppercase tracking-widest">${t("avg_consumption")}</span>
                            <span class="text-2xl font-bold text-white"><span id="trip-avg-cons">${avgCons}</span> <span class="text-xs text-[#FF5F00]">L/100</span></span>
                        </div>
                        <div class="bg-zinc-950 rounded-xl border border-[#FF5F00]/30 p-3 flex-1 flex items-center justify-between">
                            <div>
                                <span class="text-[9px] text-zinc-500 font-bold uppercase">${t("est_range")}</span>
                                <div class="text-xl font-bold"><span id="trip-range">${range}</span> <span class="text-xs text-[#FF5F00]">KM</span></div>
                            </div>
                            <span class="material-symbols-outlined text-[#FF5F00]" style="font-variation-settings:'FILL' 1;font-size:20px;">local_gas_station</span>
                        </div>
                        <div class="bg-zinc-900/50 rounded-xl border border-zinc-800 p-3 flex-1 flex flex-col justify-center">
                            <span class="text-[9px] text-zinc-500 font-bold uppercase tracking-widest">${t("drive_time")}</span>
                            <span id="trip-time" class="text-xl font-bold text-white">${time}</span>
                        </div>
                    </div>
                </div>
            </main>
            ${NavBar.render("autodelta", "a2")}
        </div>`;
    }

    return { render, update };
})());
