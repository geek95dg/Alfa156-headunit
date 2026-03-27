/**
 * A1 Main Screen — Hub with engine temp, fuel, notifications, media.
 */

App.registerScreen("a1", (() => {
    function render(container, theme, data) {
        if (theme === "heritage") container.innerHTML = _renderHeritage(data);
        else if (theme === "modern") container.innerHTML = _renderModern(data);
        else if (theme === "autodelta") container.innerHTML = _renderAutodelta(data);
        else container.innerHTML = _renderHeritage(data);
    }

    function update(data, theme) {
        // Update dynamic values
        _updateEl("coolant-val", `${Math.round(data.coolant_temp || 0)}°`);
        _updateEl("fuel-val", `${Math.round(data.fuel_level || 0)}`);
        _updateEl("fuel-pct", `${Math.round(data.fuel_level || 0)}%`);
        _updateEl("range-val", `${Math.round(data.estimated_range || 0)} KM`);
        _updateEl("avg-speed-val", `${Math.round(data.avg_speed || 0)}`);
        _updateEl("drive-time-val", data.trip_time || "0h 0m");
        _updateEl("media-info", `${data.bt_media_title || "No Media"} - ${data.bt_media_artist || "---"}`);

        // Update progress bars
        const fuelBar = document.getElementById("fuel-bar");
        if (fuelBar) fuelBar.style.width = `${Math.round(data.fuel_level || 0)}%`;
        const tempBar = document.getElementById("temp-bar");
        if (tempBar) {
            const pct = Math.min(100, Math.max(0, ((data.coolant_temp || 0) - 40) / 90 * 100));
            tempBar.style.width = `${pct}%`;
        }
    }

    function _updateEl(id, text) {
        const el = document.getElementById(id);
        if (el) el.textContent = text;
    }

    function _renderHeritage(data) {
        const t = App.t.bind(App);
        const temp = Math.round(data.coolant_temp || 0);
        const fuel = Math.round(data.fuel_level || 0);
        const range = Math.round(data.estimated_range || 0);
        const avgSpd = Math.round(data.avg_speed || 0);
        const notifs = Notifications.getNotifications(data);
        const notifHtml = Notifications.renderHeritage(notifs);

        return `<div class="screen-container bg-black text-zinc-100">
            ${AppBar.render("heritage", data)}
            <main class="content-area flex items-center justify-center overflow-hidden">
                <div class="grid grid-cols-12 gap-4 w-full max-w-5xl px-6 h-full py-4">
                    <!-- Engine Temp -->
                    <div class="col-span-3 burl-texture rounded-xl border border-zinc-800 p-4 flex flex-col justify-between overflow-hidden">
                        <div class="flex items-center gap-2 text-zinc-500">
                            <span class="material-symbols-outlined text-sm">device_thermostat</span>
                            <span class="text-[10px] font-bold uppercase tracking-wider">${t("engine_temp")}</span>
                        </div>
                        <div class="relative py-4 flex flex-col items-center">
                            <div class="w-24 h-24 rounded-full border-4 border-zinc-900 flex items-center justify-center relative">
                                <div class="absolute inset-0 rounded-full border-t-4 border-amber-500 rotate-45 opacity-60"></div>
                                <span id="coolant-val" class="text-2xl font-black text-amber-500 amber-glow">${temp}°</span>
                            </div>
                            <span class="text-[10px] text-zinc-500 mt-2 font-bold">${temp > 95 ? 'HOT' : t("optimal")}</span>
                        </div>
                    </div>
                    <!-- Notifications -->
                    <div class="col-span-6 bg-zinc-950 rounded-xl border border-zinc-800 p-6 flex flex-col gap-4 relative overflow-hidden">
                        <div class="absolute top-0 left-0 w-full h-1 bg-gradient-to-r from-transparent via-red-600 to-transparent opacity-50"></div>
                        <div class="flex items-center justify-between border-b border-zinc-900 pb-2">
                            <h2 class="text-xs font-black uppercase tracking-[0.2em] text-zinc-400">${t("system_notifications")}</h2>
                            <span class="text-[10px] text-red-500 font-bold">${notifs.length} ACTIVE</span>
                        </div>
                        <div class="space-y-3 flex-1 overflow-y-auto pr-2">${notifHtml}</div>
                    </div>
                    <!-- Fuel -->
                    <div class="col-span-3 burl-texture rounded-xl border border-zinc-800 p-4 flex flex-col justify-between overflow-hidden">
                        <div class="flex items-center gap-2 text-zinc-500">
                            <span class="material-symbols-outlined text-sm">local_gas_station</span>
                            <span class="text-[10px] font-bold uppercase tracking-wider">${t("fuel_level")}</span>
                        </div>
                        <div class="flex flex-col gap-1 py-4">
                            <span class="text-3xl font-black text-amber-500 amber-glow"><span id="fuel-val">${fuel}</span><span class="text-sm font-normal ml-1">%</span></span>
                            <div class="w-full h-1.5 bg-zinc-900 rounded-full mt-2 overflow-hidden flex">
                                <div id="fuel-bar" class="h-full bg-amber-600 shadow-[0_0_8px_#d97706] transition-all duration-500" style="width:${fuel}%"></div>
                            </div>
                            <p class="text-[10px] text-zinc-500 mt-1 font-bold">${t("est_range")}: <span id="range-val">${range} KM</span></p>
                        </div>
                    </div>
                    <!-- Bottom Row -->
                    <div class="col-span-4">
                        ${MediaPlayer.renderHeritage(data)}
                    </div>
                    <div class="col-span-8 bg-zinc-900/30 rounded-xl border border-zinc-800 p-4 flex items-center justify-between px-8">
                        <div class="flex flex-col items-center">
                            <span class="text-[10px] text-zinc-500 font-bold uppercase">${t("avg_speed")}</span>
                            <span class="text-xl font-black text-zinc-200"><span id="avg-speed-val">${avgSpd}</span> <span class="text-[10px] text-zinc-500">km/h</span></span>
                        </div>
                        <div class="w-px h-8 bg-zinc-800"></div>
                        <div class="flex flex-col items-center">
                            <span class="text-[10px] text-zinc-500 font-bold uppercase">${t("drive_time")}</span>
                            <span id="drive-time-val" class="text-xl font-black text-zinc-200">${data.trip_time || "0h 0m"}</span>
                        </div>
                        <div class="w-px h-8 bg-zinc-800"></div>
                        <div class="flex flex-col items-center">
                            <span class="text-[10px] text-zinc-500 font-bold uppercase">${t("voltage")}</span>
                            <span class="text-xl font-black text-zinc-200">${(data.battery_voltage || 12.6).toFixed(1)} <span class="text-[10px] text-zinc-500">V</span></span>
                        </div>
                    </div>
                </div>
            </main>
            ${NavBar.render("heritage", "a1")}
        </div>`;
    }

    function _renderModern(data) {
        const t = App.t.bind(App);
        const temp = Math.round(data.coolant_temp || 0);
        const fuel = Math.round(data.fuel_level || 0);
        const range = Math.round(data.estimated_range || 0);
        const tempPct = Math.min(100, Math.max(0, (temp - 40) / 90 * 100));
        const notifs = Notifications.getNotifications(data);
        const notifHtml = Notifications.renderModern(notifs);

        return `<div class="screen-container text-slate-900">
            ${AppBar.render("modern", data)}
            <main class="content-area px-6 grid grid-cols-12 gap-4 items-center bg-gradient-to-br from-slate-50 to-blue-50/30 py-4">
                <!-- Left: Engine + Fuel -->
                <div class="col-span-3 flex flex-col gap-4">
                    <div class="bg-white p-4 rounded-xl shadow-sm border border-slate-100">
                        <div class="flex items-center justify-between mb-2">
                            <span class="text-[10px] font-bold text-slate-400 uppercase tracking-wider">${t("engine_temp")}</span>
                            <span class="material-symbols-outlined text-blue-500" style="font-size:16px;">device_thermostat</span>
                        </div>
                        <div class="flex items-end gap-2">
                            <span id="coolant-val" class="text-2xl font-bold text-slate-800 tracking-tighter">${temp}°</span>
                            <div class="flex-1 h-1.5 bg-slate-100 rounded-full mb-2 overflow-hidden">
                                <div id="temp-bar" class="bg-blue-500 h-full rounded-full transition-all duration-500" style="width:${tempPct}%"></div>
                            </div>
                        </div>
                    </div>
                    <div class="bg-white p-4 rounded-xl shadow-sm border border-slate-100">
                        <div class="flex items-center justify-between mb-2">
                            <span class="text-[10px] font-bold text-slate-400 uppercase tracking-wider">${t("fuel_level")}</span>
                            <span class="material-symbols-outlined text-blue-500" style="font-size:16px;">local_gas_station</span>
                        </div>
                        <div class="flex items-end gap-2">
                            <span class="text-2xl font-bold text-slate-800 tracking-tighter"><span id="fuel-pct">${fuel}%</span></span>
                            <div class="flex-1 h-1.5 bg-slate-100 rounded-full mb-2 overflow-hidden">
                                <div id="fuel-bar" class="bg-blue-500 h-full rounded-full transition-all duration-500" style="width:${fuel}%"></div>
                            </div>
                        </div>
                        <div class="mt-1 text-[10px] text-slate-400 font-medium">${t("est_range")}: <span id="range-val">${range} KM</span></div>
                    </div>
                </div>
                <!-- Center: Notifications -->
                <div class="col-span-6 h-full flex items-center justify-center">
                    <div class="relative w-full h-[280px] bg-white rounded-2xl shadow-xl shadow-blue-900/5 border border-slate-100 overflow-hidden flex flex-col">
                        <div class="p-4 border-b border-slate-50 flex items-center justify-between">
                            <span class="text-xs font-bold text-slate-800 uppercase tracking-widest">Notification Hub</span>
                            <span class="bg-blue-100 text-blue-600 text-[10px] px-2 py-0.5 rounded-full font-bold">${notifs.length} NEW</span>
                        </div>
                        <div class="flex-1 p-4 space-y-3 overflow-y-auto">${notifHtml}</div>
                    </div>
                </div>
                <!-- Right: Media + Status -->
                <div class="col-span-3 flex flex-col gap-4">
                    ${MediaPlayer.renderModern(data)}
                    <div class="bg-white p-4 rounded-xl shadow-sm border border-slate-100 flex items-center justify-between">
                        <div>
                            <span class="text-[10px] font-bold text-slate-400 uppercase tracking-wider block mb-1">Status</span>
                            <span class="text-xs font-bold text-green-600 flex items-center gap-1">
                                <span class="w-1.5 h-1.5 bg-green-500 rounded-full"></span>SYSTEM READY
                            </span>
                        </div>
                        <span class="material-symbols-outlined text-slate-300" style="font-size:20px;">verified_user</span>
                    </div>
                </div>
            </main>
            ${NavBar.render("modern", "a1")}
        </div>`;
    }

    function _renderAutodelta(data) {
        const t = App.t.bind(App);
        const temp = Math.round(data.coolant_temp || 0);
        const fuel = Math.round(data.fuel_level || 0);
        const oil = Math.round(data.oil_pressure || 45);
        const tempPct = Math.min(100, Math.max(0, (temp - 100) / 160 * 100));
        const notifs = Notifications.getNotifications(data);
        const notifHtml = Notifications.renderAutodelta(notifs);

        return `<div class="screen-container bg-black text-white">
            ${AppBar.render("autodelta", data)}
            <main class="content-area flex flex-row overflow-hidden relative">
                <!-- Left: Vitals -->
                <div class="w-1/3 flex flex-col p-6 gap-6 justify-center border-r border-[#222222] bg-gradient-to-r from-[#0a0a0a] to-transparent z-10">
                    <div class="flex flex-col gap-2">
                        <div class="flex justify-between items-end mb-1">
                            <span class="text-sm font-medium text-gray-400 uppercase tracking-widest">${t("coolant")}</span>
                            <span class="text-2xl font-bold text-white"><span id="coolant-val">${temp}</span><span class="text-sm text-gray-500">°C</span></span>
                        </div>
                        <div class="h-2 w-full bg-[#222222] rounded-full overflow-hidden">
                            <div id="temp-bar" class="h-full bg-gradient-to-r from-blue-500 via-green-500 to-red-500 rounded-full shadow-[0_0_10px_rgba(34,197,94,0.5)] transition-all duration-500" style="width:${tempPct}%"></div>
                        </div>
                    </div>
                    <div class="flex flex-col gap-2 mt-4">
                        <div class="flex justify-between items-end mb-1">
                            <span class="text-sm font-medium text-gray-400 uppercase tracking-widest">${t("fuel")}</span>
                            <span class="text-2xl font-bold text-white"><span id="fuel-val">${fuel}</span><span class="text-sm text-gray-500">%</span></span>
                        </div>
                        <div class="h-2 w-full bg-[#222222] rounded-full overflow-hidden">
                            <div id="fuel-bar" class="h-full bg-[#FF5F00] rounded-full shadow-[0_0_10px_rgba(236,91,19,0.5)] transition-all duration-500" style="width:${fuel}%"></div>
                        </div>
                    </div>
                    <div class="flex flex-col gap-2 mt-4">
                        <div class="flex justify-between items-end mb-1">
                            <span class="text-sm font-medium text-gray-400 uppercase tracking-widest">${t("oil_press")}</span>
                            <span class="text-2xl font-bold text-white">${oil}<span class="text-sm text-gray-500">psi</span></span>
                        </div>
                        <div class="h-2 w-full bg-[#222222] rounded-full overflow-hidden">
                            <div class="h-full bg-white rounded-full" style="width:60%"></div>
                        </div>
                    </div>
                </div>
                <!-- Right: Status + Media -->
                <div class="flex-1 flex flex-col p-6 relative">
                    <div class="absolute inset-0 opacity-5 pointer-events-none flex items-center justify-center">
                        <div class="w-[300px] h-[300px] rounded-full border-[20px] border-white blur-sm"></div>
                    </div>
                    <div class="flex-1 flex flex-col relative z-10">
                        <h3 class="text-sm font-bold text-[#FF5F00] uppercase tracking-widest mb-4">${t("system_status")}</h3>
                        ${notifHtml}
                        <div class="mt-auto">
                            ${MediaPlayer.renderAutodelta(data)}
                        </div>
                    </div>
                </div>
            </main>
            ${NavBar.render("autodelta", "a1")}
        </div>`;
    }

    return { render, update };
})());
