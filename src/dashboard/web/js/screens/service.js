/**
 * A4 Service Screen — Vehicle diagnostics and service status.
 */

App.registerScreen("a4", (() => {
    function render(container, theme, data) {
        if (theme === "heritage") container.innerHTML = _renderHeritage(data);
        else if (theme === "modern") container.innerHTML = _renderModern(data);
        else if (theme === "autodelta") container.innerHTML = _renderAutodelta(data);
        else container.innerHTML = _renderHeritage(data);
    }

    function update(data) {
        _updateEl("svc-temp", `${Math.round(data.coolant_temp || 0)}°C`);
        _updateEl("svc-oil", data.oil_level_pct >= 0 ? `${Math.round(data.oil_level_pct)}%` : "OK");
        _updateEl("svc-battery", `${(data.battery_voltage || 12.6).toFixed(1)}V`);
        const tpms = data.tpms_pressures || [2.4, 2.4, 2.2, 2.2];
        ["fl", "fr", "rl", "rr"].forEach((pos, i) => {
            _updateEl(`svc-tire-${pos}`, `${tpms[i].toFixed(1)}`);
        });
    }

    function _updateEl(id, text) {
        const el = document.getElementById(id);
        if (el) el.textContent = text;
    }

    function _renderHeritage(data) {
        const temp = Math.round(data.coolant_temp || 0);
        const tpms = data.tpms_pressures || [2.4, 2.4, 2.2, 2.2];
        const lowTire = tpms.findIndex(p => p > 0 && p < 2.0);
        const oilOk = data.oil_level_pct < 0 || data.oil_level_pct > 20;
        const batteryV = (data.battery_voltage || 13.8).toFixed(1);

        return `<div class="screen-container bg-[#1a0f0a] text-zinc-100">
            ${AppBar.render("heritage", data)}
            <main class="content-area flex px-6 py-5 gap-6">
                <!-- Left: Car sketch -->
                <div class="w-[45%] h-full flex flex-col gap-2">
                    <div class="flex-1 rounded-xl overflow-hidden bg-zinc-900/60 border border-zinc-800 relative p-2">
                        <div class="w-full h-full rounded-lg bg-center bg-no-repeat bg-contain" style="background-image:url('/assets/heritage/giulia_gta_sketch.png');filter:contrast(1.25) sepia(0.3) brightness(0.9);"></div>
                        <div class="absolute bottom-4 left-4 right-4 bg-black/80 backdrop-blur-sm p-3 rounded-lg border border-amber-900/30 flex justify-between items-center">
                            <div>
                                <p class="text-xs font-bold text-zinc-500 uppercase tracking-wider">Vehicle</p>
                                <p class="text-sm font-semibold text-amber-500">Giulia GTA (1965)</p>
                            </div>
                            <span class="material-symbols-outlined text-amber-500">directions_car</span>
                        </div>
                    </div>
                </div>
                <!-- Right: Diagnostics -->
                <div class="w-[55%] flex flex-col h-full">
                    <div class="flex items-end justify-between mb-4">
                        <h2 class="text-2xl font-bold text-amber-500 tracking-tight amber-glow">System Status</h2>
                        <span class="text-xs font-semibold px-2 py-1 bg-green-900/40 text-green-400 rounded-md">All OK</span>
                    </div>
                    <div class="flex-1 overflow-y-auto pr-2 space-y-3">
                        ${_diagItem("engineering", "Engine Mechanics", `${temp}°C — nominal`, "OK", false)}
                        ${lowTire >= 0
                            ? _diagItem("tire_repair", "Tire Pressure", `${["FL","FR","RL","RR"][lowTire]}: ${tpms[lowTire].toFixed(1)} BAR`, "Warning", true)
                            : _diagItem("tire_repair", "Tire Pressure", "All tires nominal", "OK", false)}
                        ${_diagItem("oil_barrel", "Fluid Levels", "Oil & Coolant optimal", "OK", false)}
                        ${_diagItem("battery_charging_full", "Electrical System", `${batteryV}V Charging`, "OK", false)}
                    </div>
                </div>
            </main>
            ${NavBar.render("heritage", "a4")}
        </div>`;
    }

    function _diagItem(icon, title, desc, status, isWarning) {
        const theme = App.getTheme();
        const isHeritage = theme === "heritage";

        const bgCls = isWarning
            ? (isHeritage ? "bg-amber-900/20 border-amber-600/30" : "bg-orange-50 border-[#ec5b13]/30")
            : (isHeritage ? "bg-zinc-900/60 border-zinc-800" : "bg-white border-neutral-200");
        const leftBar = isWarning ? `<div class="absolute left-0 top-0 bottom-0 w-1 ${isHeritage ? 'bg-amber-500' : 'bg-[#ec5b13]'}"></div>` : '';
        const iconBg = isWarning
            ? (isHeritage ? "bg-zinc-800 text-amber-500" : "bg-white text-[#ec5b13] shadow-sm")
            : (isHeritage ? "bg-zinc-800 text-zinc-400" : "bg-neutral-100 text-[#221610]");
        const statusColor = isWarning
            ? (isHeritage ? "text-amber-500" : "text-[#ec5b13]")
            : (isHeritage ? "text-green-400" : "text-green-600");
        const titleColor = isHeritage ? "text-zinc-200" : "text-[#221610]";
        const descColor = isWarning
            ? (isHeritage ? "text-amber-500 font-medium" : "text-[#ec5b13] font-medium")
            : (isHeritage ? "text-zinc-500" : "text-neutral-500");

        return `<div class="flex items-center justify-between p-3.5 ${bgCls} rounded-xl shadow-sm relative overflow-hidden">
            ${leftBar}
            <div class="flex items-center gap-3">
                <div class="w-10 h-10 rounded-full ${iconBg} flex items-center justify-center">
                    <span class="material-symbols-outlined">${icon}</span>
                </div>
                <div>
                    <p class="text-sm font-bold ${titleColor}">${title}</p>
                    <p class="text-xs ${descColor}">${desc}</p>
                </div>
            </div>
            <span class="text-sm font-bold ${statusColor}">${status}</span>
        </div>`;
    }

    function _renderModern(data) {
        const tpms = data.tpms_pressures || [2.4, 2.4, 2.2, 2.2];
        const oilPct = data.oil_level_pct >= 0 ? Math.round(data.oil_level_pct) : 84;
        const thermLoad = Math.min(100, Math.max(0, ((data.coolant_temp || 80) - 40) / 90 * 100));

        return `<div class="screen-container" style="background:#f8fafc;color:#0f172a;">
            ${AppBar.render("modern", data)}
            <main class="content-area relative overflow-hidden" style="background:#fff;">
                <!-- Background sketch -->
                <div class="absolute top-0 right-0 w-2/3 h-64 opacity-20 pointer-events-none pencil-sketch-mask">
                    <img src="/assets/modern/berlina_156_sketch.png" alt="" class="w-full h-full object-contain grayscale contrast-125" onerror="this.style.display='none'">
                </div>
                <div class="px-8 pt-6 relative z-10">
                    <div class="mb-8">
                        <h1 class="text-3xl font-extrabold tracking-tighter text-slate-900">A4 SERVICE</h1>
                        <p class="text-slate-500 font-medium uppercase text-xs tracking-[0.2em]">Detailed Vehicle Diagnostics</p>
                    </div>
                    <div class="grid grid-cols-12 gap-4">
                        <!-- Engine -->
                        <div class="col-span-8 bg-slate-50 border border-slate-200 p-5 rounded-xl flex flex-col justify-between">
                            <div class="flex justify-between items-start">
                                <div>
                                    <span class="material-symbols-outlined text-blue-700 mb-2" style="font-variation-settings:'FILL' 1;">settings</span>
                                    <h3 class="font-bold text-slate-800 tracking-tight">Engine Analytics</h3>
                                </div>
                                <span class="text-xs font-bold text-emerald-600 bg-emerald-100 px-2 py-1 rounded">OPTIMAL</span>
                            </div>
                            <div class="mt-4 flex items-end gap-6">
                                <div class="flex-1">
                                    <div class="flex justify-between text-[10px] font-bold text-slate-400 mb-1">
                                        <span>THERMAL LOAD</span><span>${Math.round(thermLoad)}%</span>
                                    </div>
                                    <div class="h-1.5 w-full bg-slate-200 rounded-full overflow-hidden">
                                        <div class="h-full bg-blue-700 transition-all duration-500" style="width:${thermLoad}%"></div>
                                    </div>
                                </div>
                                <div id="svc-temp" class="text-2xl font-black text-slate-900">${Math.round(data.coolant_temp || 80)}°C</div>
                            </div>
                        </div>
                        <!-- Oil -->
                        <div class="col-span-4 bg-slate-900 p-5 rounded-xl flex flex-col justify-between text-white">
                            <span class="material-symbols-outlined text-red-500" style="font-variation-settings:'FILL' 1;">oil_barrel</span>
                            <div>
                                <p class="text-[10px] font-bold text-slate-400 uppercase tracking-widest">Oil Life</p>
                                <p id="svc-oil" class="text-3xl font-extrabold italic">${oilPct}%</p>
                            </div>
                        </div>
                        <!-- Tires -->
                        <div class="col-span-12 grid grid-cols-4 gap-4">
                            ${["FL","FR","RL","RR"].map((pos, i) => `<div class="bg-white border border-slate-200 p-3 rounded-lg flex flex-col items-center">
                                <span class="text-[9px] font-bold text-slate-400 mb-1">${pos}</span>
                                <span class="text-lg font-bold text-slate-800"><span id="svc-tire-${pos.toLowerCase()}">${tpms[i].toFixed(1)}</span> <span class="text-[10px] text-slate-400">BAR</span></span>
                            </div>`).join("")}
                        </div>
                    </div>
                </div>
            </main>
            ${NavBar.render("modern", "a4")}
        </div>`;
    }

    function _renderAutodelta(data) {
        const temp = Math.round(data.coolant_temp || 0);
        const oil = Math.round(data.oil_pressure || 45);
        const batteryV = (data.battery_voltage || 13.8).toFixed(1);
        const tpms = data.tpms_pressures || [2.4, 2.4, 2.2, 2.2];

        return `<div class="screen-container bg-black text-white">
            <div class="flex items-center justify-between px-4 py-2 border-b border-[#ec5b13]/30 shrink-0 h-12">
                <div class="flex items-center gap-4 text-white/70">
                    <span class="material-symbols-outlined text-xl">bluetooth</span>
                </div>
                <div class="text-[#ec5b13] font-bold text-lg tracking-widest uppercase">Alfa Romeo</div>
                <div class="flex items-center gap-4 text-white/90 text-sm font-medium">
                    <span>${_time()}</span>
                    <span class="material-symbols-outlined text-lg">thermostat</span>
                    <span>${_tempStr(data)}</span>
                </div>
            </div>
            <main class="content-area flex overflow-hidden">
                <!-- Left: Diagnostics -->
                <div class="w-1/3 border-r border-[#ec5b13]/30 flex flex-col p-4 gap-3 overflow-y-auto">
                    <h2 class="text-[#ec5b13] font-bold text-xl uppercase tracking-wider mb-2">A4 Diagnostics</h2>
                    ${_autoDiagCard("Engine Temp", `${temp}°C`, "device_thermostat")}
                    ${_autoDiagCard("Oil Pressure", `${oil} PSI`, "oil_barrel")}
                    ${_autoDiagCard("Battery", `${batteryV}V`, "battery_charging_full")}
                    ${_autoDiagCard("Tire Pressure", `${tpms[0].toFixed(1)} BAR`, "tire_repair")}
                </div>
                <!-- Right: Car sketch -->
                <div class="w-2/3 relative flex flex-col justify-center items-center bg-[#221610] p-6">
                    <div class="w-full h-full bg-cover bg-center rounded-xl border border-[#ec5b13]/20 shadow-[0_0_30px_rgba(236,91,19,0.1)] relative overflow-hidden flex items-center justify-center"
                         style="background-image:url('/assets/autodelta/junior_z_sketch.png');background-size:contain;background-repeat:no-repeat;background-position:center;">
                        <div class="absolute inset-0 bg-gradient-to-t from-black via-transparent to-transparent opacity-80"></div>
                        <div class="absolute bottom-4 left-6 z-10">
                            <h3 class="text-white font-bold text-2xl tracking-wide">1600 Junior Z</h3>
                            <p class="text-[#ec5b13] font-medium tracking-widest text-sm uppercase">Autodelta Sport</p>
                        </div>
                    </div>
                </div>
            </main>
            ${NavBar.render("autodelta", "a4")}
        </div>`;
    }

    function _autoDiagCard(label, value, icon) {
        return `<div class="bg-[#221610]/50 border border-[#ec5b13]/40 rounded-lg p-3 flex justify-between items-center">
            <div class="flex flex-col">
                <span class="text-white/60 text-xs uppercase tracking-wider">${label}</span>
                <span class="text-white font-bold text-xl">${value}</span>
            </div>
            <span class="material-symbols-outlined text-[#ec5b13] text-2xl">${icon}</span>
        </div>`;
    }

    function _time() {
        return new Date().toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit", hour12: true });
    }
    function _tempStr(data) {
        if (data.ext_temp == null) return "--";
        return `${Math.round(data.ext_temp)}°C`;
    }

    return { render, update };
})());
