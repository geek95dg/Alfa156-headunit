/**
 * A2 Trip Screen — Trip statistics, consumption chart with scales and driving profile.
 * Everything fits in 800x480 — no scrolling.
 */

App.registerScreen("a3", (() => {
    // --- Travel Plan mode state -------------------------------------------
    // Toggled by the [Travel Plan] button in the trip header. When active
    // we overlay a destination search + route summary panel on top of the
    // normal trip stats. Persisted to localStorage so the toggle state
    // survives page reloads (the saved destination lives server-side in
    // TripComputer).
    let travelPlanActive = false;
    let _searchResults = [];
    let _searchDebounce = null;
    try {
        travelPlanActive = localStorage.getItem("bcm.travelPlan") === "1";
    } catch (e) {}

    function render(container, theme, data) {
        if (theme === "heritage") container.innerHTML = _renderHeritage(data);
        else if (theme === "modern") container.innerHTML = _renderModern(data);
        else if (theme === "autodelta") container.innerHTML = _renderAutodelta(data);
        else container.innerHTML = _renderHeritage(data);
        _renderTravelPlanOverlay(data);
    }

    function update(data) {
        _updateEl("trip-dist", (data.trip_distance || 0).toFixed(1));
        _updateEl("trip-avg-speed", Math.round(data.avg_speed || 0));
        _updateEl("trip-time", data.trip_time || "00:00");
        _updateEl("trip-avg-cons", (data.avg_consumption || 0).toFixed(1));
        _updateEl("trip-range", Math.round(data.estimated_range || 0));
        _updateEl("trip-instant", (data.instant_consumption || 0).toFixed(1));
        _refreshTravelPlan(data);
    }

    function _updateEl(id, text) {
        const el = document.getElementById(id);
        if (el) el.textContent = text;
    }

    // --- Travel Plan UI ---------------------------------------------------

    // Snapshot of the plan fingerprint used to detect real changes so we
    // don't rebuild the overlay (and destroy user touch targets) on every
    // ~200 ms WebSocket tick. Only a real plan change triggers a rerender.
    let _lastPlanKey = null;
    function _planKey(data) {
        const p = data.trip_plan || {};
        return JSON.stringify([
            p.destination_name || "",
            p.distance_km || 0,
            p.eta_min || 0,
            p.predicted_fuel_l || 0,
            (p.weather_points || []).length,
            (p.incidents || []).length,
            !!data.trip_planning,
        ]);
    }

    // --- Travel Plan UI ---------------------------------------------------

    function _toggleTravelPlan() {
        travelPlanActive = !travelPlanActive;
        try { localStorage.setItem("bcm.travelPlan", travelPlanActive ? "1" : "0"); } catch (e) {}
        _lastPlanKey = null;
        _renderTravelPlanOverlay(DataStore.getAll());
    }

    function _renderTravelPlanOverlay(data) {
        const host = document.querySelector("#app .screen-container");
        if (!host) return;
        // Remove any existing overlay before re-rendering
        const prev = host.querySelector(".travel-plan-overlay");
        if (prev) prev.remove();
        // Always inject the toggle button — it needs to sit above the
        // overlay (z-index 50 > overlay 40) so the user can toggle
        // back to live trip stats regardless of plan state.
        _injectToggleButton(host);
        _updateToggleButton();
        if (!travelPlanActive) return;

        const plan = data.trip_plan || {};
        const planning = !!data.trip_planning;
        const name = plan.destination_name || "";
        const dist = (plan.distance_km || 0).toFixed(1);
        const etaMin = Math.round(plan.eta_min || 0);
        const etaH = Math.floor(etaMin / 60);
        const etaM = etaMin % 60;
        const etaStr = etaH > 0 ? `${etaH}h ${etaM}m` : `${etaM}m`;
        const fuel = (plan.predicted_fuel_l || 0).toFixed(1);
        const weatherPts = plan.weather_points || [];
        const incidents = plan.incidents || [];

        // Weather strip — icons for each waypoint
        const weatherStripHtml = weatherPts.length > 0
            ? weatherPts.map(w => `
                <div class="flex flex-col items-center" style="min-width:56px;">
                    <span class="material-symbols-outlined text-amber-400" style="font-size:20px;">${_conditionIcon(w.condition)}</span>
                    <span class="text-[9px] text-zinc-400">${w.temp != null ? Math.round(w.temp) + "°" : "--"}</span>
                    <span class="text-[8px] text-zinc-600">+${Math.round(w.eta_min)}m</span>
                </div>`).join("")
            : `<span class="text-[9px] text-zinc-500">No route weather yet</span>`;

        // Incidents list
        const incidentsHtml = incidents.length > 0
            ? incidents.slice(0, 4).map(inc => `
                <div class="flex items-center gap-2 text-[10px]">
                    <span class="material-symbols-outlined text-red-400" style="font-size:14px;">warning</span>
                    <span class="text-zinc-300 truncate">${inc.description || "Incident"}</span>
                </div>`).join("")
            : `<span class="text-[9px] text-zinc-500">${plan.destination_name ? "No road works reported" : "Set destination to see incidents"}</span>`;

        const loadingNotice = planning
            ? `<span class="text-[9px] text-amber-400 flex items-center gap-1">
                   <span class="material-symbols-outlined" style="font-size:12px;">sync</span>Computing route…
               </span>`
            : "";

        // Bez klucza OpenRouteService planer zwraca odległość w linii prostej.
        // Liczba wygląda identycznie jak realna trasa, więc bez tego paska
        // wyglądałoby to na działającą funkcję, która po prostu kłamie.
        const approxNotice = (!planning && plan.approximate)
            ? `<div style="display:flex;align-items:center;gap:6px;background:rgba(120,53,15,0.35);
                        border:1px solid #b45309;border-radius:6px;padding:6px 8px;">
                   <span class="material-symbols-outlined text-amber-400" style="font-size:14px;">warning</span>
                   <span style="font-size:10px;color:#fcd34d;line-height:1.3;">
                       Trasa przybliżona — odległość w linii prostej.
                       Wpisz travel.openrouteservice_key w config/bcm_config.yaml.
                   </span>
               </div>`
            : "";

        const overlay = document.createElement("div");
        overlay.className = "travel-plan-overlay";
        overlay.style.cssText = [
            "position:absolute",
            "top:48px",          // leave AppBar clickable
            "bottom:48px",       // leave NavBar clickable
            "left:0",
            "right:0",
            "z-index:40",
            "background:rgba(0,0,0,0.92)",
            "backdrop-filter:blur(4px)",
            "padding:16px 16px 16px 16px",
            "display:flex",
            "flex-direction:column",
            "gap:12px",
            "overflow:auto",
        ].join(";");
        overlay.innerHTML = `
            <div style="display:flex;align-items:center;justify-content:space-between;padding-right:140px;">
                <h2 style="color:#f59e0b;font-weight:800;font-size:16px;text-transform:uppercase;letter-spacing:2px;display:flex;align-items:center;gap:8px;">
                    <span class="material-symbols-outlined">route</span>
                    Travel Plan
                </h2>
            </div>
            ${approxNotice}
            <div class="tp-search-wrap" style="position:relative;">
                <input class="tp-search" type="text" placeholder="Destination (e.g. Gdynia)"
                       value="${name.replace(/"/g, '&quot;')}"
                       style="width:100%;background:#18181b;border:1px solid #3f3f46;border-radius:6px;padding:10px 12px;font-size:14px;color:#f4f4f5;outline:none;">
            </div>
            <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px;">
                <div style="background:rgba(24,24,27,0.6);border:1px solid #27272a;border-radius:8px;padding:8px;">
                    <div style="font-size:9px;color:#71717a;text-transform:uppercase;">Distance</div>
                    <div style="font-size:18px;font-weight:800;color:#f59e0b;">${dist} <span style="font-size:10px;color:#71717a;">km</span></div>
                </div>
                <div style="background:rgba(24,24,27,0.6);border:1px solid #27272a;border-radius:8px;padding:8px;">
                    <div style="font-size:9px;color:#71717a;text-transform:uppercase;">ETA</div>
                    <div style="font-size:18px;font-weight:800;color:#f59e0b;">${etaStr}</div>
                </div>
                <div style="background:rgba(24,24,27,0.6);border:1px solid #27272a;border-radius:8px;padding:8px;">
                    <div style="font-size:9px;color:#71717a;text-transform:uppercase;">Fuel</div>
                    <div style="font-size:18px;font-weight:800;color:#f59e0b;">${fuel} <span style="font-size:10px;color:#71717a;">l</span></div>
                </div>
            </div>
            <div>
                <div style="font-size:9px;color:#71717a;text-transform:uppercase;margin-bottom:4px;">Weather along route</div>
                <div style="display:flex;gap:8px;overflow-x:auto;background:rgba(24,24,27,0.4);border:1px solid #27272a;border-radius:8px;padding:8px;">
                    ${weatherStripHtml}
                </div>
            </div>
            <div style="flex:1;min-height:0;">
                <div style="font-size:9px;color:#71717a;text-transform:uppercase;margin-bottom:4px;">Road works / incidents</div>
                <div style="background:rgba(24,24,27,0.4);border:1px solid #27272a;border-radius:8px;padding:8px;display:flex;flex-direction:column;gap:4px;">
                    ${incidentsHtml}
                </div>
            </div>
            <div style="display:flex;align-items:center;justify-content:space-between;margin-top:auto;">
                ${loadingNotice}
                <button class="tp-clear-btn" type="button"
                        style="margin-left:auto;padding:6px 14px;background:#27272a;color:#e4e4e7;font-size:12px;border-radius:6px;border:1px solid #3f3f46;cursor:pointer;">
                    Clear plan
                </button>
            </div>`;
        host.appendChild(overlay);

        // Attach handlers with addEventListener so they always fire even
        // if DataStore or window globals aren't yet ready.
        const searchInput = overlay.querySelector(".tp-search");
        if (searchInput) {
            searchInput.addEventListener("input", (e) => {
                _searchDestination(e.target.value);
            });
        }
        const clearBtn = overlay.querySelector(".tp-clear-btn");
        if (clearBtn) {
            clearBtn.addEventListener("click", _clearPlan);
            clearBtn.addEventListener("touchend", (e) => {
                e.preventDefault();
                _clearPlan();
            });
        }
        // Preserve any pending search results across overlay rebuilds.
        _renderSearchResults();
    }

    function _injectToggleButton(host) {
        if (host.querySelector(".tp-toggle-btn")) return;
        // The button is placed inline, immediately to the left of the
        // fuel-consumption section header. Each theme template renders a
        // `.tp-toggle-anchor` slot at that location; we just fill it.
        // z-index keeps the button visible above the travel-plan overlay
        // so the user can always toggle back to live trip stats.
        const anchor = host.querySelector(".tp-toggle-anchor");
        if (!anchor) return;
        const btn = document.createElement("button");
        btn.className = "tp-toggle-btn";
        btn.type = "button";
        btn.style.cssText = [
            "position:relative",
            "z-index:50",
            "display:inline-flex",
            "align-items:center",
            "gap:6px",
            "padding:4px 10px",
            "border-radius:8px",
            "background:rgba(24,24,27,0.92)",
            "border:1px solid rgba(245,158,11,0.5)",
            "color:#f59e0b",
            "font-size:10px",
            "font-weight:800",
            "text-transform:uppercase",
            "letter-spacing:1px",
            "cursor:pointer",
            "box-shadow:0 1px 4px rgba(0,0,0,0.4)",
        ].join(";");
        btn.addEventListener("click", (e) => {
            e.preventDefault();
            e.stopPropagation();
            _toggleTravelPlan();
        });
        btn.addEventListener("touchend", (e) => {
            e.preventDefault();
            e.stopPropagation();
            _toggleTravelPlan();
        });
        anchor.innerHTML = "";
        anchor.appendChild(btn);
    }

    function _updateToggleButton() {
        const btn = document.querySelector(".tp-toggle-btn");
        if (!btn) return;
        if (travelPlanActive) {
            btn.innerHTML = `<span class="material-symbols-outlined" style="font-size:16px;">arrow_back</span>Trip Stats`;
        } else {
            btn.innerHTML = `<span class="material-symbols-outlined" style="font-size:16px;">route</span>Travel Plan`;
        }
    }

    function _conditionIcon(cond) {
        const c = (cond || "").toLowerCase();
        if (c.includes("rain")) return "rainy";
        if (c.includes("storm") || c.includes("thunder")) return "thunderstorm";
        if (c.includes("snow")) return "ac_unit";
        if (c.includes("cloud")) return "cloud";
        if (c.includes("clear") || c.includes("sun")) return "wb_sunny";
        return "cloud_queue";
    }

    function _refreshTravelPlan(data) {
        // Only rerender when the plan *actually* changes. Otherwise the
        // 5 Hz WebSocket ticks would destroy the overlay DOM faster than
        // a touch tap can register on any of its buttons.
        if (!travelPlanActive) return;
        const key = _planKey(data);
        if (key === _lastPlanKey) return;
        _lastPlanKey = key;
        _renderTravelPlanOverlay(data);
    }

    function _searchDestination(query) {
        if (_searchDebounce) clearTimeout(_searchDebounce);
        if (!query || query.length < 2) {
            _searchResults = [];
            _renderSearchResults();
            return;
        }
        _searchDebounce = setTimeout(async () => {
            try {
                const r = await fetch(`/api/trip/search?q=${encodeURIComponent(query)}`);
                const json = await r.json();
                _searchResults = (json.results || []).slice(0, 5);
            } catch (e) {
                _searchResults = [];
            }
            _renderSearchResults();
        }, 300);
    }

    function _renderSearchResults() {
        // Update only the search-results dropdown inside an already
        // rendered overlay; keeps the input focused and preserves
        // user-typed text.
        const overlay = document.querySelector(".travel-plan-overlay");
        if (!overlay) return;
        const container = overlay.querySelector(".tp-search-wrap");
        if (!container) return;
        let list = container.querySelector(".tp-search-results");
        if (list) list.remove();
        if (_searchResults.length === 0) return;
        list = document.createElement("div");
        list.className = "tp-search-results";
        list.style.cssText = [
            "position:absolute",
            "top:44px",
            "left:0",
            "right:0",
            "background:#18181b",
            "border:1px solid #3f3f46",
            "border-radius:6px",
            "max-height:180px",
            "overflow:auto",
            "z-index:60",
        ].join(";");
        _searchResults.forEach((r, i) => {
            const item = document.createElement("div");
            item.className = "tp-result-item";
            item.dataset.idx = String(i);
            item.style.cssText = "padding:10px 14px;font-size:13px;color:#e4e4e7;cursor:pointer;border-bottom:1px solid #27272a;";
            item.textContent = `${r.name}${r.state ? ", " + r.state : ""}, ${r.country}`;
            item.addEventListener("click", () => _selectResult(i));
            item.addEventListener("touchend", (e) => {
                e.preventDefault();
                _selectResult(i);
            });
            list.appendChild(item);
        });
        container.appendChild(list);
    }

    async function _selectResult(idx) {
        const r = _searchResults[idx];
        if (!r) return;
        _searchResults = [];
        try {
            await fetch("/api/trip/destination", {
                method: "POST",
                headers: {"Content-Type": "application/json"},
                body: JSON.stringify({
                    lat: r.lat, lon: r.lon,
                    name: `${r.name}, ${r.country}`,
                }),
            });
        } catch (e) { /* ignore */ }
        _renderTravelPlanOverlay(DataStore.getAll());
    }

    async function _clearPlan() {
        try {
            await fetch("/api/trip/clear", { method: "POST" });
        } catch (e) { /* ignore */ }
        _renderTravelPlanOverlay(DataStore.getAll());
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
                    <div class="flex justify-between items-center mb-2 gap-2">
                        <div class="flex items-center gap-2 min-w-0">
                            <span class="tp-toggle-anchor"></span>
                            <span class="text-[10px] text-zinc-500 font-bold uppercase tracking-wider truncate">${t("fuel_consumption")} (L/100km)</span>
                        </div>
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
            ${NavBar.render("heritage", "a3")}
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
                    <div class="flex justify-between items-center mb-2 gap-2">
                        <div class="flex items-center gap-2 min-w-0">
                            <span class="tp-toggle-anchor"></span>
                            <span class="text-[10px] font-bold text-slate-800 flex items-center gap-1 truncate">
                                <span class="material-symbols-outlined text-[#005596]" style="font-size:16px;">monitoring</span>
                                ${t("fuel_consumption")} (L/100km)
                            </span>
                        </div>
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
            ${NavBar.render("modern", "a3")}
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
                        <div class="flex items-center gap-2 mb-1 min-w-0">
                            <span class="tp-toggle-anchor"></span>
                            <span class="text-[9px] text-zinc-500 font-bold uppercase tracking-wider truncate">${t("fuel_consumption")} L/100km</span>
                        </div>
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
            ${NavBar.render("autodelta", "a3")}
        </div>`;
    }

    return { render, update };
})());
