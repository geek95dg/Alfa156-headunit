/**
 * A2 Trip Screen — Trip statistics and consumption charts.
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

    function _renderHeritage(data) {
        const dist = (data.trip_distance || 0).toFixed(1);
        const avgSpd = Math.round(data.avg_speed || 0);
        const time = data.trip_time || "0h 0m";
        const avgCons = (data.avg_consumption || 0).toFixed(1);
        const chartValues = [15, 25, 45, 60, 75, 55, 85];
        const chartLabels = ["-50km", "-40km", "-30km", "-20km", "-10km", "-5km", "Now"];

        return `<div class="screen-container bg-[#1a0f0a] text-zinc-100">
            ${AppBar.render("heritage", data)}
            <main class="content-area flex overflow-hidden">
                <!-- Left: Stats -->
                <div class="w-[300px] p-6 flex flex-col gap-4 border-r border-amber-900/30 bg-[#221610]">
                    <h1 class="text-2xl font-bold text-amber-500 uppercase tracking-wide mb-2 amber-glow">Trip A2</h1>
                    <div class="flex flex-col gap-1 p-4 rounded-xl bg-zinc-900/60 border border-zinc-800">
                        <p class="text-sm font-medium text-zinc-500 uppercase tracking-wider">Distance</p>
                        <p class="text-3xl font-bold text-amber-500 amber-glow"><span id="trip-dist">${dist}</span> <span class="text-lg text-zinc-500">km</span></p>
                    </div>
                    <div class="flex flex-col gap-1 p-4 rounded-xl bg-zinc-900/60 border border-zinc-800">
                        <p class="text-sm font-medium text-zinc-500 uppercase tracking-wider">Avg Speed</p>
                        <p class="text-3xl font-bold text-amber-500 amber-glow"><span id="trip-avg-speed">${avgSpd}</span> <span class="text-lg text-zinc-500">km/h</span></p>
                    </div>
                    <div class="flex flex-col gap-1 p-4 rounded-xl bg-zinc-900/60 border border-zinc-800">
                        <p class="text-sm font-medium text-zinc-500 uppercase tracking-wider">Travel Time</p>
                        <p id="trip-time" class="text-3xl font-bold text-amber-500 amber-glow">${time}</p>
                    </div>
                </div>
                <!-- Right: Chart -->
                <div class="flex-1 p-6 flex flex-col bg-[#1a0f0a]">
                    <div class="flex justify-between items-end mb-6">
                        <div>
                            <p class="text-sm font-medium text-zinc-500 uppercase tracking-wider">Avg Fuel Consumption</p>
                            <p class="text-4xl font-bold text-amber-500 mt-1 amber-glow"><span id="trip-avg-cons">${avgCons}</span> <span class="text-xl text-zinc-500">L/100KM</span></p>
                        </div>
                    </div>
                    <div class="flex-1 bg-zinc-900/50 rounded-xl border border-zinc-800 p-6">
                        ${Charts.renderBarChart(chartValues, "heritage", { labels: chartLabels })}
                    </div>
                </div>
            </main>
            ${NavBar.render("heritage", "a2")}
        </div>`;
    }

    function _renderModern(data) {
        const dist = (data.trip_distance || 0).toFixed(1);
        const avgSpd = Math.round(data.avg_speed || 0);
        const time = data.trip_time || "01:45";
        const avgCons = (data.avg_consumption || 0).toFixed(1);
        const instantCons = (data.instant_consumption || 0).toFixed(1);
        const graphValues = [8, 12, 10, 14, 7, 9, 11, 6, 8, 7];

        return `<div class="screen-container text-slate-900" style="background:#f8fafc;">
            ${AppBar.render("modern", data)}
            <main class="content-area p-4 overflow-hidden flex gap-4" style="background:#f1f5f9;">
                <!-- Left: Stats -->
                <div class="w-1/3 flex flex-col gap-3">
                    <div class="flex-1 bg-white rounded-xl p-4 shadow-sm border border-slate-200 flex flex-col justify-between">
                        <div>
                            <span class="text-[10px] font-bold text-slate-400 uppercase tracking-wider">Trip A2 Distance</span>
                            <h2 class="text-3xl font-extrabold text-[#005596] leading-tight"><span id="trip-dist">${dist}</span> <span class="text-sm font-normal text-slate-500">km</span></h2>
                        </div>
                        <div class="flex justify-between items-end">
                            <div class="flex flex-col">
                                <span class="text-[10px] font-bold text-slate-400 uppercase">Duration</span>
                                <span id="trip-time" class="font-bold text-slate-700">${time}</span>
                            </div>
                            <div class="flex flex-col text-right">
                                <span class="text-[10px] font-bold text-slate-400 uppercase">Avg Speed</span>
                                <span class="font-bold text-slate-700"><span id="trip-avg-speed">${avgSpd}</span> km/h</span>
                            </div>
                        </div>
                    </div>
                    <div class="h-1/3 bg-[#005596] text-white rounded-xl p-4 shadow-md flex items-center justify-between">
                        <div>
                            <span class="text-[10px] font-bold text-white/70 uppercase">Average Fuel</span>
                            <div class="text-2xl font-bold"><span id="trip-avg-cons">${avgCons}</span> <span class="text-xs font-light">l/100km</span></div>
                        </div>
                        <span class="material-symbols-outlined text-3xl opacity-30">local_gas_station</span>
                    </div>
                </div>
                <!-- Right: Graph -->
                <div class="w-2/3 bg-white rounded-xl shadow-sm border border-slate-200 p-4 flex flex-col">
                    <div class="flex justify-between items-center mb-4">
                        <h3 class="text-sm font-bold text-slate-800 flex items-center gap-2">
                            <span class="material-symbols-outlined text-[#005596] text-lg">monitoring</span>
                            Consumption History
                        </h3>
                        <span class="px-2 py-1 bg-slate-100 rounded text-[9px] font-bold text-slate-500">LAST 30 MIN</span>
                    </div>
                    <div class="flex-1 relative mt-2">
                        ${Charts.renderLineGraph(graphValues, { color: "#005596" })}
                    </div>
                    <div class="flex justify-between mt-4 border-t border-slate-50 pt-4">
                        <div class="flex gap-6">
                            <div class="flex flex-col">
                                <span class="text-[9px] font-bold text-slate-400 uppercase">Current</span>
                                <span class="text-sm font-bold text-slate-700"><span id="trip-instant">${instantCons}</span> l/100km</span>
                            </div>
                        </div>
                    </div>
                </div>
            </main>
            ${NavBar.render("modern", "a2")}
        </div>`;
    }

    function _renderAutodelta(data) {
        const dist = (data.trip_distance || 0).toFixed(1);
        const avgSpd = Math.round(data.avg_speed || 0);
        const time = data.trip_time || "01:54";
        const range = Math.round(data.estimated_range || 0);
        const chartValues = [12, 16, 24, 20, 14, 18, 28, 32, 10, 22, 16, 20];

        return `<div class="screen-container bg-black text-white">
            ${AppBar.render("autodelta", data)}
            <main class="content-area px-4 py-2">
                <div class="flex justify-between items-end mb-4">
                    <div>
                        <h1 class="text-[#FF5F00] font-bold text-xl tracking-tight leading-none uppercase">Autodelta Sport A2</h1>
                        <p class="text-zinc-500 text-[10px] tracking-[0.2em] uppercase mt-1">Trip Statistics & Analytics</p>
                    </div>
                    <div class="text-right">
                        <div class="text-2xl font-bold leading-none"><span id="trip-dist">${dist}</span> <span class="text-xs text-zinc-500">KM</span></div>
                        <p class="text-[10px] text-zinc-500 uppercase">Current Session</p>
                    </div>
                </div>
                <div class="grid grid-cols-12 grid-rows-6 gap-3" style="height:340px;">
                    <!-- Consumption Chart -->
                    <div class="col-span-8 row-span-4 bg-zinc-900/50 rounded-xl border border-zinc-800 p-4 relative overflow-hidden">
                        <div class="flex justify-between items-center mb-4">
                            <span class="text-[10px] text-zinc-400 font-bold uppercase tracking-wider">Fuel Consumption L/100KM</span>
                        </div>
                        <div class="w-full" style="height:128px;">
                            ${Charts.renderBarChart(chartValues, "autodelta")}
                        </div>
                    </div>
                    <!-- Avg Speed -->
                    <div class="col-span-4 row-span-2 bg-zinc-900/50 rounded-xl border border-zinc-800 p-4 flex flex-col justify-center">
                        <span class="text-[10px] text-zinc-500 font-bold uppercase tracking-widest mb-1">Avg Speed</span>
                        <div class="flex items-baseline gap-1">
                            <span id="trip-avg-speed" class="text-3xl font-bold text-white tracking-tighter">${avgSpd}</span>
                            <span class="text-[#FF5F00] text-xs font-bold">KM/H</span>
                        </div>
                    </div>
                    <!-- Efficiency -->
                    <div class="col-span-4 row-span-2 bg-zinc-900/50 rounded-xl border border-zinc-800 p-4 flex flex-col justify-center">
                        <span class="text-[10px] text-zinc-500 font-bold uppercase tracking-widest mb-1">Efficiency</span>
                        <div class="flex items-center gap-3">
                            ${Charts.renderCircularGauge(75, 100)}
                            <span class="text-xs font-bold text-white">OPTIMAL<br><span class="text-zinc-500 font-normal">ZONE</span></span>
                        </div>
                    </div>
                    <!-- Range -->
                    <div class="col-span-6 row-span-2 bg-zinc-950 rounded-xl border border-[#FF5F00]/30 p-4 flex items-center justify-between">
                        <div>
                            <span class="text-[10px] text-zinc-500 font-bold uppercase tracking-widest">Range Remaining</span>
                            <div class="text-2xl font-bold text-white tracking-tight"><span id="trip-range">${range}</span> <span class="text-xs text-[#FF5F00]">KM</span></div>
                        </div>
                        <div class="w-12 h-12 rounded-full border-2 border-[#FF5F00]/20 flex items-center justify-center">
                            <span class="material-symbols-outlined text-[#FF5F00]" style="font-variation-settings:'FILL' 1;">local_gas_station</span>
                        </div>
                    </div>
                    <!-- Time -->
                    <div class="col-span-6 row-span-2 bg-zinc-900/50 rounded-xl border border-zinc-800 p-4 flex items-center justify-between">
                        <div>
                            <span class="text-[10px] text-zinc-500 font-bold uppercase tracking-widest">Active Driving</span>
                            <div id="trip-time" class="text-2xl font-bold text-white tracking-tight">${time}</div>
                        </div>
                        <span class="material-symbols-outlined text-zinc-600" style="font-size:32px;">timer</span>
                    </div>
                </div>
            </main>
            ${NavBar.render("autodelta", "a2")}
        </div>`;
    }

    return { render, update };
})());
