/**
 * A4 Service Screen — Compact diagnostics + visible car sketch.
 * Everything fits in 800x480 — no scrolling.
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
        const t = App.t.bind(App);
        const temp = Math.round(data.coolant_temp || 0);
        const tpms = data.tpms_pressures || [2.4, 2.4, 2.2, 2.2];
        const oilPct = data.oil_level_pct >= 0 ? Math.round(data.oil_level_pct) : 84;
        const batteryV = (data.battery_voltage || 13.8).toFixed(1);
        const serviceKm = data.service_km || 4500;

        return `<div class="screen-container bg-[#1a0f0a] text-zinc-100">
            ${AppBar.render("heritage", data)}
            <main class="content-area flex overflow-hidden">
                <!-- Left: Car sketch (visible!) -->
                <div class="w-[340px] relative shrink-0 flex items-center justify-center p-4">
                    <div class="w-full h-full rounded-xl bg-zinc-900/40 border border-zinc-800 relative overflow-hidden flex items-center justify-center">
                        <img src="/assets/heritage/giulia_gta_sketch.png" alt="Giulia GTA" class="max-w-[90%] max-h-[85%] object-contain" style="filter:contrast(1.2) sepia(0.3) brightness(0.85);" onerror="this.style.display='none'">
                        <div class="absolute bottom-2 left-3 right-3 flex justify-between items-end">
                            <div>
                                <p class="text-[9px] text-zinc-600 uppercase tracking-wider">${t("vehicle")}</p>
                                <p class="text-xs font-bold text-amber-500">Giulia GTA 1965</p>
                            </div>
                            <span class="text-[9px] text-zinc-600">${t("next_service")}: <span class="text-amber-500 font-bold">${serviceKm}</span> km</span>
                        </div>
                    </div>
                </div>
                <!-- Right: Compact diagnostics -->
                <div class="flex-1 flex flex-col p-4 gap-2">
                    <div class="flex items-center justify-between mb-1">
                        <h2 class="text-lg font-bold text-amber-500 amber-glow">${t("system_status")}</h2>
                        <span class="text-[9px] font-bold px-2 py-0.5 bg-green-900/40 text-green-400 rounded">${t("all_ok")}</span>
                    </div>
                    <!-- 2x2 Grid of compact diagnostic cards -->
                    <div class="grid grid-cols-2 gap-2 flex-1">
                        <div class="bg-zinc-900/60 border border-zinc-800 rounded-lg p-2 flex items-center gap-2">
                            <span class="material-symbols-outlined text-zinc-500" style="font-size:20px;">device_thermostat</span>
                            <div class="flex-1">
                                <p class="text-[8px] text-zinc-500 uppercase">${t("engine")}</p>
                                <p id="svc-temp" class="text-lg font-bold text-zinc-200">${temp}°C</p>
                            </div>
                            <span class="text-[9px] font-bold text-green-400">${t("ok")}</span>
                        </div>
                        <div class="bg-zinc-900/60 border border-zinc-800 rounded-lg p-2 flex items-center gap-2">
                            <span class="material-symbols-outlined text-zinc-500" style="font-size:20px;">oil_barrel</span>
                            <div class="flex-1">
                                <p class="text-[8px] text-zinc-500 uppercase">${t("oil_life")}</p>
                                <p id="svc-oil" class="text-lg font-bold text-zinc-200">${oilPct}%</p>
                            </div>
                            <span class="text-[9px] font-bold text-green-400">${t("ok")}</span>
                        </div>
                        <div class="bg-zinc-900/60 border border-zinc-800 rounded-lg p-2 flex items-center gap-2">
                            <span class="material-symbols-outlined text-zinc-500" style="font-size:20px;">battery_charging_full</span>
                            <div class="flex-1">
                                <p class="text-[8px] text-zinc-500 uppercase">${t("battery")}</p>
                                <p id="svc-battery" class="text-lg font-bold text-zinc-200">${batteryV}V</p>
                            </div>
                            <span class="text-[9px] font-bold text-green-400">${t("ok")}</span>
                        </div>
                        <div class="bg-zinc-900/60 border border-zinc-800 rounded-lg p-2 flex items-center gap-2">
                            <span class="material-symbols-outlined text-zinc-500" style="font-size:20px;">tire_repair</span>
                            <div class="flex-1">
                                <p class="text-[8px] text-zinc-500 uppercase">${t("tires")}</p>
                                <p class="text-sm font-bold text-zinc-200">${tpms[0].toFixed(1)}/${tpms[1].toFixed(1)}</p>
                            </div>
                            <span class="text-[9px] font-bold ${tpms.some(p => p > 0 && p < 2.0) ? 'text-amber-400' : 'text-green-400'}">${tpms.some(p => p > 0 && p < 2.0) ? t('warning') : t('ok')}</span>
                        </div>
                    </div>
                    <!-- TPMS detail row -->
                    <div class="flex gap-2">
                        ${["FL","FR","RL","RR"].map((pos, i) => `<div class="flex-1 bg-zinc-900/40 border border-zinc-800 rounded p-1.5 text-center">
                            <span class="text-[8px] text-zinc-600 font-bold">${pos}</span>
                            <p class="text-sm font-bold text-zinc-300"><span id="svc-tire-${pos.toLowerCase()}">${tpms[i].toFixed(1)}</span> <span class="text-[8px] text-zinc-600">BAR</span></p>
                        </div>`).join("")}
                    </div>
                </div>
            </main>
            ${NavBar.render("heritage", "a4")}
        </div>`;
    }

    function _renderModern(data) {
        const t = App.t.bind(App);
        const tpms = data.tpms_pressures || [2.4, 2.4, 2.2, 2.2];
        const oilPct = data.oil_level_pct >= 0 ? Math.round(data.oil_level_pct) : 84;
        const temp = Math.round(data.coolant_temp || 80);
        const batteryV = (data.battery_voltage || 13.8).toFixed(1);
        const serviceKm = data.service_km || 4500;
        const thermLoad = Math.min(100, Math.max(0, (temp - 40) / 90 * 100));

        return `<div class="screen-container" style="background:#f8fafc;color:#0f172a;">
            ${AppBar.render("modern", data)}
            <main class="content-area flex overflow-hidden" style="background:#fff;">
                <!-- Left: Car sketch (visible) -->
                <div class="w-[320px] relative shrink-0 p-4 flex items-center justify-center">
                    <div class="w-full h-full rounded-xl bg-slate-50 border border-slate-200 relative overflow-hidden flex items-center justify-center shadow-sm">
                        <img src="/assets/modern/berlina_156_sketch.png" alt="156 Berlina" class="max-w-[85%] max-h-[80%] object-contain grayscale contrast-125 opacity-60" onerror="this.style.display='none'">
                        <div class="absolute bottom-2 left-3 right-3 flex justify-between items-end">
                            <span class="text-[9px] font-bold text-slate-400">Alfa Romeo 156</span>
                            <span class="text-[9px] text-slate-400">${t("next_service")}: <span class="font-bold text-[#005596]">${serviceKm}</span> km</span>
                        </div>
                    </div>
                </div>
                <!-- Right: Diagnostics grid -->
                <div class="flex-1 flex flex-col p-4 gap-2">
                    <div class="flex items-center justify-between mb-1">
                        <h2 class="text-lg font-extrabold text-slate-900 tracking-tighter">${t("screen.a4")}</h2>
                        <span class="text-[9px] font-bold text-emerald-600 bg-emerald-100 px-2 py-0.5 rounded">${t("optimal")}</span>
                    </div>
                    <!-- Compact engine + oil row -->
                    <div class="flex gap-2">
                        <div class="flex-1 bg-slate-50 border border-slate-200 p-2 rounded-lg">
                            <div class="flex justify-between items-center mb-1">
                                <span class="text-[8px] font-bold text-slate-400 uppercase">${t("engine")}</span>
                                <span id="svc-temp" class="text-sm font-black text-slate-900">${temp}°C</span>
                            </div>
                            <div class="h-1 bg-slate-200 rounded-full overflow-hidden">
                                <div class="h-full bg-blue-700 transition-all" style="width:${thermLoad}%"></div>
                            </div>
                        </div>
                        <div class="w-[80px] bg-slate-900 p-2 rounded-lg text-white flex flex-col items-center justify-center shrink-0">
                            <span class="text-[8px] text-slate-400 uppercase">${t("oil_life")}</span>
                            <span id="svc-oil" class="text-xl font-extrabold">${oilPct}%</span>
                        </div>
                        <div class="flex-1 bg-slate-50 border border-slate-200 p-2 rounded-lg">
                            <div class="flex justify-between items-center mb-1">
                                <span class="text-[8px] font-bold text-slate-400 uppercase">${t("battery")}</span>
                                <span id="svc-battery" class="text-sm font-black text-slate-900">${batteryV}V</span>
                            </div>
                            <div class="h-1 bg-slate-200 rounded-full overflow-hidden">
                                <div class="h-full bg-emerald-500" style="width:${Math.min(100, ((parseFloat(batteryV) - 11) / 4) * 100)}%"></div>
                            </div>
                        </div>
                    </div>
                    <!-- TPMS -->
                    <div class="flex gap-2">
                        ${["FL","FR","RL","RR"].map((pos, i) => `<div class="flex-1 bg-white border border-slate-200 p-2 rounded-lg text-center shadow-sm">
                            <span class="text-[8px] font-bold text-slate-400">${pos}</span>
                            <p class="text-lg font-bold text-slate-800"><span id="svc-tire-${pos.toLowerCase()}">${tpms[i].toFixed(1)}</span></p>
                            <span class="text-[8px] text-slate-400">BAR</span>
                        </div>`).join("")}
                    </div>
                </div>
            </main>
            ${NavBar.render("modern", "a4")}
        </div>`;
    }

    function _renderAutodelta(data) {
        const t = App.t.bind(App);
        const temp = Math.round(data.coolant_temp || 0);
        const oil = Math.round(data.oil_pressure || 45);
        const batteryV = (data.battery_voltage || 13.8).toFixed(1);
        const tpms = data.tpms_pressures || [2.4, 2.4, 2.2, 2.2];
        const serviceKm = data.service_km || 4500;

        return `<div class="screen-container bg-black text-white">
            ${AppBar.render("autodelta", data)}
            <main class="content-area flex overflow-hidden">
                <!-- Left: Compact diagnostics -->
                <div class="w-[260px] border-r border-[#ec5b13]/30 flex flex-col p-3 gap-2 shrink-0">
                    <h2 class="text-[#ec5b13] font-bold text-lg uppercase tracking-wider mb-1">${t("diagnostics")}</h2>
                    ${_autoDiagCard(t("engine"), `${temp}°C`, "device_thermostat")}
                    ${_autoDiagCard(t("oil_press"), `${oil} PSI`, "oil_barrel")}
                    ${_autoDiagCard(t("battery"), `${batteryV}V`, "battery_charging_full")}
                    ${_autoDiagCard(t("tires"), `${tpms[0].toFixed(1)} BAR`, "tire_repair")}
                    <div class="mt-auto text-[9px] text-zinc-600">${t("next_service")}: <span class="text-[#ec5b13] font-bold">${serviceKm}</span> km</div>
                </div>
                <!-- Right: Car sketch (visible) -->
                <div class="flex-1 relative flex items-center justify-center bg-[#0a0a0a] p-4">
                    <img src="/assets/autodelta/junior_z_sketch.png" alt="1600 Junior Z" class="max-w-[90%] max-h-[85%] object-contain" style="filter:brightness(0.8) contrast(1.3);" onerror="this.style.display='none'">
                    <div class="absolute inset-0 bg-gradient-to-t from-black/70 via-transparent to-transparent pointer-events-none"></div>
                    <div class="absolute bottom-4 left-6 z-10">
                        <h3 class="text-white font-bold text-xl tracking-wide">1600 Junior Z</h3>
                        <p class="text-[#ec5b13] font-medium tracking-widest text-xs uppercase">Autodelta Sport</p>
                    </div>
                </div>
            </main>
            ${NavBar.render("autodelta", "a4")}
        </div>`;
    }

    function _autoDiagCard(label, value, icon) {
        return `<div class="bg-[#111]/80 border border-[#ec5b13]/30 rounded-lg p-2 flex items-center gap-2">
            <span class="material-symbols-outlined text-[#ec5b13]" style="font-size:20px;">${icon}</span>
            <div class="flex-1">
                <span class="text-[8px] text-zinc-500 uppercase">${label}</span>
                <p class="text-base font-bold text-white">${value}</p>
            </div>
            <span class="text-[9px] font-bold text-green-400">OK</span>
        </div>`;
    }

    return { render, update };
})());
