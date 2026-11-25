/**
 * A5 Service Screen — diagnostics cards + car sketch, three themes.
 *
 * Values come from data.live (web_viewer._live_metrics) through Live
 * (components/live.js): a card shows a reading only when a real source
 * delivered it recently (OBD, battery monitor, TPMS, service counter);
 * otherwise "—" and a grey "brak danych". The header badge says
 * "brak danych z auta" until at least one reading exists — the old screen
 * claimed "All OK" with 12.6 V and 2.4 bar tyres made up from defaults.
 * Everything fits in 1024x600 — no scrolling.
 */

App.registerScreen("a5", (() => {
    const TIRES = ["fl", "fr", "rl", "rr"];

    function render(container, theme, data) {
        if (theme === "modern") container.innerHTML = _renderModern(data);
        else if (theme === "autodelta") container.innerHTML = _renderAutodelta(data);
        else container.innerHTML = _renderHeritage(data);
        update(data);
    }

    // ── values (shared by render and update) ─────────────────────────────
    function _vals(data) {
        const tp = Live.get(data, "tpms");
        return {
            temp: Live.fmt(Live.get(data, "coolant"), 0, "°C"),
            oil: Live.fmt(Live.get(data, "oil_level"), 0, "%"),
            oilPress: Live.fmt(Live.get(data, "oil_pressure"), 1, " bar"),
            battery: Live.fmt(Live.get(data, "battery_v"), 1, "V"),
            tires: TIRES.map((_, i) => (tp ? tp.v[i].toFixed(1) : "—")),
            tiresShort: tp ? `${tp.v[0].toFixed(1)}/${tp.v[1].toFixed(1)}` : "—",
            km: Live.fmt(Live.get(data, "service_km"), 0, ""),
        };
    }

    function _status(data, name) {
        return Live.status(Live.get(data, name), Live.JUDGE[name]);
    }

    function update(data) {
        const v = _vals(data);
        _text("svc-temp", v.temp);
        _text("svc-oil", v.oil);
        _text("svc-oil-press", v.oilPress);
        _text("svc-battery", v.battery);
        _text("svc-tires", v.tiresShort);
        _text("svc-km", v.km);
        TIRES.forEach((pos, i) => _text(`svc-tire-${pos}`, v.tires[i]));
        for (const [id, name] of [["temp", "coolant"], ["oil", "oil_level"], ["oil-press", "oil_pressure"],
                                  ["battery", "battery_v"], ["tires", "tpms"]]) {
            const st = _status(data, name);
            _label(`svc-${id}-st`, st.text, st.color);
            const srcEl = document.getElementById(`svc-${id}-src`);
            if (srcEl) {
                const s = Live.src(Live.get(data, name));
                if (srcEl.textContent !== (s ? "· " + s : "")) srcEl.textContent = s ? "· " + s : "";
            }
        }
        const badge = Live.overall(data);
        _label("svc-badge", badge.text, badge.color);
    }

    function _text(id, text) {
        const el = document.getElementById(id);
        if (el && el.textContent !== text) el.textContent = text;
    }

    function _label(id, text, color) {
        const el = document.getElementById(id);
        if (!el) return;
        if (el.textContent !== text) el.textContent = text;
        if (el.getAttribute("data-color") !== color) {
            el.style.color = color;
            el.setAttribute("data-color", color);
        }
    }

    // A diagnostic card: label + source tag, value, corner status (filled by update()).
    function _card(id, label, icon, tk) {
        return `<div class="${tk.card} rounded-lg p-2 flex items-center gap-2">
            <span class="material-symbols-outlined ${tk.icon}" style="font-size:20px;">${icon}</span>
            <div class="flex-1" style="min-width:0">
                <p class="text-[8px] ${tk.label} uppercase">${label} <span id="svc-${id}-src" style="text-transform:none"></span></p>
                <p id="svc-${id}" class="text-lg font-bold ${tk.value}">—</p>
            </div>
            <span id="svc-${id}-st" class="text-[9px] font-bold" style="color:${Live.COLORS.none}">—</span>
        </div>`;
    }

    function _badge() {
        return `<span id="svc-badge" class="text-[9px] font-bold px-2 py-0.5 rounded" style="background:rgba(127,127,127,0.15);color:${Live.COLORS.none}">—</span>`;
    }

    function _renderHeritage(data) {
        const t = App.t.bind(App);
        const tk = { card: "bg-zinc-900/60 border border-zinc-800", icon: "text-zinc-500",
                     label: "text-zinc-500", value: "text-zinc-200" };
        return `<div class="screen-container bg-[#1a0f0a] text-zinc-100">
            ${AppBar.render("heritage", data)}
            <main class="content-area flex overflow-hidden">
                <div class="w-[340px] relative shrink-0 flex items-center justify-center p-4">
                    <div class="w-full h-full rounded-xl bg-zinc-900/40 border border-zinc-800 relative overflow-hidden flex items-center justify-center">
                        <img src="/assets/heritage/giulia_gta_sketch.png" alt="Giulia GTA" class="max-w-[90%] max-h-[85%] object-contain" style="filter:contrast(1.2) sepia(0.3) brightness(0.85);" onerror="this.style.display='none'">
                        <div class="absolute bottom-2 left-3 right-3 flex justify-between items-end">
                            <div>
                                <p class="text-[9px] text-zinc-600 uppercase tracking-wider">${t("vehicle")}</p>
                                <p class="text-xs font-bold text-amber-500">Giulia GTA 1965</p>
                            </div>
                            <span class="text-[9px] text-zinc-600">${t("next_service")}: <span id="svc-km" class="text-amber-500 font-bold">—</span> km</span>
                        </div>
                    </div>
                </div>
                <div class="flex-1 flex flex-col p-4 gap-2">
                    <div class="flex items-center justify-between mb-1">
                        <h2 class="text-lg font-bold text-amber-500 amber-glow">${t("system_status")}</h2>
                        ${_badge()}
                    </div>
                    <div class="grid grid-cols-2 gap-2 flex-1">
                        ${_card("temp", t("engine"), "device_thermostat", tk)}
                        ${_card("oil", t("oil_life"), "oil_barrel", tk)}
                        ${_card("battery", t("battery"), "battery_charging_full", tk)}
                        ${_card("tires", t("tires"), "tire_repair", tk)}
                    </div>
                    <div class="flex gap-2">
                        ${TIRES.map((pos) => `<div class="flex-1 bg-zinc-900/40 border border-zinc-800 rounded p-1.5 text-center">
                            <span class="text-[8px] text-zinc-600 font-bold">${pos.toUpperCase()}</span>
                            <p class="text-sm font-bold text-zinc-300"><span id="svc-tire-${pos}">—</span> <span class="text-[8px] text-zinc-600">BAR</span></p>
                        </div>`).join("")}
                    </div>
                    ${_dtc(t)}
                </div>
            </main>
            ${NavBar.render("heritage", "a5")}
        </div>`;
    }

    function _dtc(t) {
        return `<div class="mt-2 p-2 bg-zinc-900/40 border border-zinc-800 rounded-lg">
            <div class="flex justify-between items-center mb-1">
                <span class="text-[9px] font-bold text-zinc-500 uppercase">${t("diagnostics", "DTC Error Codes")}</span>
                <div class="flex gap-2">
                    <button class="text-[8px] font-bold px-2 py-0.5 bg-zinc-800 rounded text-amber-500 hover:bg-zinc-700" onclick="App._readDTC()">${t("dtc_read", "Read")}</button>
                    <button class="text-[8px] font-bold px-2 py-0.5 bg-zinc-800 rounded text-red-400 hover:bg-zinc-700" onclick="App._clearDTC()">${t("dtc_clear", "Clear")}</button>
                </div>
            </div>
            <div id="dtc-list" class="text-[10px] text-zinc-500">${t("dtc_none", "No error codes")}</div>
        </div>`;
    }

    function _renderModern(data) {
        const t = App.t.bind(App);
        const tk = { card: "bg-slate-50 border border-slate-200", icon: "text-slate-400",
                     label: "text-slate-400", value: "text-slate-900" };
        return `<div class="screen-container" style="background:#f8fafc;color:#0f172a;">
            ${AppBar.render("modern", data)}
            <main class="content-area flex overflow-hidden" style="background:#fff;">
                <div class="w-[320px] relative shrink-0 p-4 flex items-center justify-center">
                    <div class="w-full h-full rounded-xl bg-slate-50 border border-slate-200 relative overflow-hidden flex items-center justify-center shadow-sm">
                        <img src="/assets/modern/berlina_156_sketch.png" alt="156 Berlina" class="max-w-[85%] max-h-[80%] object-contain grayscale contrast-125 opacity-60" onerror="this.style.display='none'">
                        <div class="absolute bottom-2 left-3 right-3 flex justify-between items-end">
                            <span class="text-[9px] font-bold text-slate-400">Alfa Romeo 156</span>
                            <span class="text-[9px] text-slate-400">${t("next_service")}: <span id="svc-km" class="font-bold text-[#005596]">—</span> km</span>
                        </div>
                    </div>
                </div>
                <div class="flex-1 flex flex-col p-4 gap-2">
                    <div class="flex items-center justify-between mb-1">
                        <h2 class="text-lg font-extrabold text-slate-900 tracking-tighter">${t("system_status")}</h2>
                        ${_badge()}
                    </div>
                    <div class="grid grid-cols-2 gap-2 flex-1">
                        ${_card("temp", t("engine"), "device_thermostat", tk)}
                        ${_card("oil", t("oil_life"), "oil_barrel", tk)}
                        ${_card("battery", t("battery"), "battery_charging_full", tk)}
                        ${_card("tires", t("tires"), "tire_repair", tk)}
                    </div>
                    <div class="flex gap-2">
                        ${TIRES.map((pos) => `<div class="flex-1 bg-white border border-slate-200 p-2 rounded-lg text-center shadow-sm">
                            <span class="text-[8px] font-bold text-slate-400">${pos.toUpperCase()}</span>
                            <p class="text-lg font-bold text-slate-800"><span id="svc-tire-${pos}">—</span></p>
                            <span class="text-[8px] text-slate-400">BAR</span>
                        </div>`).join("")}
                    </div>
                </div>
            </main>
            ${NavBar.render("modern", "a5")}
        </div>`;
    }

    function _renderAutodelta(data) {
        const t = App.t.bind(App);
        const tk = { card: "bg-[#111]/80 border border-[#ec5b13]/30", icon: "text-[#ec5b13]",
                     label: "text-zinc-500", value: "text-white" };
        return `<div class="screen-container bg-black text-white">
            ${AppBar.render("autodelta", data)}
            <main class="content-area flex overflow-hidden">
                <div class="w-[260px] border-r border-[#ec5b13]/30 flex flex-col p-3 gap-2 shrink-0">
                    <div class="flex items-center justify-between mb-1">
                        <h2 class="text-[#ec5b13] font-bold text-lg uppercase tracking-wider">${t("diagnostics")}</h2>
                    </div>
                    ${_badge()}
                    ${_card("temp", t("engine"), "device_thermostat", tk)}
                    ${_card("oil-press", t("oil_press"), "oil_barrel", tk)}
                    ${_card("battery", t("battery"), "battery_charging_full", tk)}
                    ${_card("tires", t("tires"), "tire_repair", tk)}
                    <div class="mt-auto text-[9px] text-zinc-600">${t("next_service")}: <span id="svc-km" class="text-[#ec5b13] font-bold">—</span> km</div>
                </div>
                <div class="flex-1 relative flex items-center justify-center bg-[#0a0a0a] p-4">
                    <img src="/assets/autodelta/junior_z_sketch.png" alt="1600 Junior Z" class="max-w-[90%] max-h-[85%] object-contain" style="filter:brightness(0.8) contrast(1.3);" onerror="this.style.display='none'">
                    <div class="absolute inset-0 bg-gradient-to-t from-black/70 via-transparent to-transparent pointer-events-none"></div>
                    <div class="absolute bottom-4 left-6 z-10">
                        <h3 class="text-white font-bold text-xl tracking-wide">1600 Junior Z</h3>
                        <p class="text-[#ec5b13] font-medium tracking-widest text-xs uppercase">Autodelta Sport</p>
                    </div>
                </div>
            </main>
            ${NavBar.render("autodelta", "a5")}
        </div>`;
    }

    return { render, update };
})());
