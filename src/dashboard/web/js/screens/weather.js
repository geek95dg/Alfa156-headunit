/**
 * A3 Weather Screen — Weather data + Leaflet.js interactive map.
 * No search bar — shows actual live weather data overlaid on map.
 * Optimized for encoder navigation (no touch inputs).
 */

App.registerScreen("a4", (() => {
    let _map = null;
    let _marker = null;

    function render(container, theme, data) {
        if (theme === "heritage") container.innerHTML = _renderHeritage(data);
        else if (theme === "modern") container.innerHTML = _renderModern(data);
        else if (theme === "autodelta") container.innerHTML = _renderAutodelta(data);
        else container.innerHTML = _renderHeritage(data);
    }

    function mount() {
        setTimeout(_initMap, 100);
    }

    function unmount() {
        if (_map) { _map.remove(); _map = null; _marker = null; }
    }

    function update(data) {
        _updateEl("weather-city", data.weather_city || "---");
        _updateEl("weather-condition", data.weather_condition || "---");
        _updateEl("weather-temp", data.weather_temp != null ? `${Math.round(data.weather_temp)}°` : "--°");
        _updateEl("weather-feels", data.weather_feels_like != null ? `Feels ${Math.round(data.weather_feels_like)}°` : "");
        _updateEl("weather-wind", `${Math.round(data.weather_wind_speed || 0)} km/h`);
        _updateEl("weather-humidity", `${data.weather_humidity || 0}%`);

        if (_map && data.gps_lat && data.gps_lon && data.gps_fix) {
            const pos = [data.gps_lat, data.gps_lon];
            _map.setView(pos, _map.getZoom());
            if (_marker) _marker.setLatLng(pos);
        }
    }

    function _updateEl(id, text) {
        const el = document.getElementById(id);
        if (el) el.textContent = text;
    }

    function _initMap() {
        const mapEl = document.getElementById("weather-map");
        if (!mapEl || _map) return;

        const data = DataStore.getAll();
        const lat = data.gps_lat || 45.4642;
        const lon = data.gps_lon || 9.1900;

        _map = L.map(mapEl, {
            center: [lat, lon], zoom: 13,
            zoomControl: false, attributionControl: false,
            keyboard: false, dragging: false, scrollWheelZoom: false,
            doubleClickZoom: false, touchZoom: false,
        });

        L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 19 }).addTo(_map);

        const theme = App.getTheme();
        const color = theme === "modern" ? "#3b82f6" : theme === "autodelta" ? "#FF5F00" : "#f59e0b";
        _marker = L.marker([lat, lon], {
            icon: L.divIcon({
                className: "",
                html: `<div style="width:14px;height:14px;border-radius:50%;background:${color};border:2px solid white;box-shadow:0 0 10px ${color};"></div>`,
                iconSize: [14, 14], iconAnchor: [7, 7],
            }),
        }).addTo(_map);
    }

    function _forecastRow(day, icon, high, low, theme) {
        const iconColor = theme === "autodelta" ? "text-[#FF5F00]" : theme === "heritage" ? "text-amber-500" : "text-blue-400";
        return `<div class="flex items-center justify-between py-0.5">
            <span class="text-zinc-400 w-10 text-[11px]">${day}</span>
            <span class="material-symbols-outlined ${iconColor}" style="font-size:18px;">${icon}</span>
            <span class="text-white font-medium text-xs w-6 text-right">${high}°</span>
            <span class="text-zinc-600 text-xs w-6 text-right">${low}°</span>
        </div>`;
    }

    function _weatherIcon(condition) {
        const c = (condition || "").toLowerCase();
        if (c.includes("sun") || c.includes("clear")) return "sunny";
        if (c.includes("rain")) return "rainy";
        if (c.includes("thunder") || c.includes("storm")) return "thunderstorm";
        if (c.includes("snow")) return "ac_unit";
        return "partly_cloudy_day";
    }

    function _renderHeritage(data) {
        const t = App.t.bind(App);
        const city = data.weather_city || "Milan, IT";
        const condition = data.weather_condition || "Partly Cloudy";
        const temp = data.weather_temp != null ? Math.round(data.weather_temp) : 22;
        const feels = data.weather_feels_like != null ? Math.round(data.weather_feels_like) : temp + 2;
        const wind = Math.round(data.weather_wind_speed || 12);
        const humidity = data.weather_humidity || 55;

        return `<div class="screen-container bg-[#1a0f0a] text-white">
            ${AppBar.render("heritage", data)}
            <main class="content-area flex overflow-hidden">
                <!-- Left: Weather data -->
                <div class="w-[260px] p-4 flex flex-col bg-[#221610] border-r border-amber-900/30 shrink-0">
                    <!-- Search (touch) -->
                    <div class="flex items-center gap-2 bg-zinc-900/60 border border-amber-900/30 rounded-full px-3 py-1.5 mb-3">
                        <span class="material-symbols-outlined text-amber-500" style="font-size:16px;">search</span>
                        <input type="text" placeholder="${t("weather_search", "Szukaj lokalizacji...")}" class="bg-transparent border-none text-sm text-white placeholder-zinc-600 w-full outline-none p-0" style="font-size:12px;">
                    </div>
                    <div class="mb-2">
                        <h1 id="weather-city" class="text-xl font-bold text-white">${city}</h1>
                        <p id="weather-condition" class="text-amber-500 text-sm">${condition}</p>
                    </div>
                    <div class="flex items-center gap-3 my-2">
                        <span class="material-symbols-outlined text-4xl text-amber-500" style="font-variation-settings:'FILL' 1;">${_weatherIcon(condition)}</span>
                        <div>
                            <span id="weather-temp" class="text-4xl font-bold text-white">${temp}°</span>
                            <p id="weather-feels" class="text-[11px] text-zinc-500">${t("feels_like")} ${feels}°</p>
                        </div>
                    </div>
                    <!-- Wind + Humidity -->
                    <div class="flex gap-3 my-2">
                        <div class="flex items-center gap-1">
                            <span class="material-symbols-outlined text-zinc-600" style="font-size:16px;">air</span>
                            <span id="weather-wind" class="text-xs text-zinc-400">${wind} km/h</span>
                        </div>
                        <div class="flex items-center gap-1">
                            <span class="material-symbols-outlined text-zinc-600" style="font-size:16px;">humidity_percentage</span>
                            <span id="weather-humidity" class="text-xs text-zinc-400">${humidity}%</span>
                        </div>
                    </div>
                    <!-- Forecast -->
                    <div class="mt-auto">
                        <h3 class="text-[10px] uppercase tracking-widest text-zinc-600 mb-1 border-b border-amber-900/30 pb-1">${t("forecast")}</h3>
                        ${_forecastRow("Today", "sunny", temp + 3, temp - 5, "heritage")}
                        ${_forecastRow("Wed", "cloud", temp - 2, temp - 8, "heritage")}
                        ${_forecastRow("Thu", "rainy", temp - 5, temp - 10, "heritage")}
                    </div>
                </div>
                <!-- Right: Map with weather overlay -->
                <div class="flex-1 relative bg-black">
                    <div id="weather-map" class="absolute inset-0 z-0"></div>
                    <!-- Weather data overlay on map -->
                    <div class="absolute top-3 left-3 z-10 bg-black/70 backdrop-blur-sm rounded-lg px-3 py-2 border border-amber-900/30">
                        <div class="flex items-center gap-2">
                            <span class="material-symbols-outlined text-amber-500" style="font-size:16px;">location_on</span>
                            <span class="text-[10px] text-zinc-400 font-bold uppercase">${t("gps_active")}</span>
                        </div>
                    </div>
                    <div class="absolute bottom-3 left-3 right-3 z-10 bg-black/70 backdrop-blur-sm rounded-lg px-3 py-2 border border-amber-900/30 flex justify-between items-center">
                        <div class="flex items-center gap-2">
                            <span class="material-symbols-outlined text-amber-500" style="font-size:18px;font-variation-settings:'FILL' 1;">${_weatherIcon(condition)}</span>
                            <span class="text-sm font-bold text-white">${temp}° ${condition}</span>
                        </div>
                        <div class="flex items-center gap-3 text-[10px] text-zinc-400">
                            <span>${t("wind")}: ${wind} km/h</span>
                            <span>${t("humidity")}: ${humidity}%</span>
                        </div>
                    </div>
                </div>
            </main>
            ${NavBar.render("heritage", "a4")}
        </div>`;
    }

    function _renderModern(data) {
        const t = App.t.bind(App);
        const city = data.weather_city || "Milan";
        const condition = data.weather_condition || "Partly Cloudy";
        const temp = data.weather_temp != null ? Math.round(data.weather_temp) : 18;
        const wind = Math.round(data.weather_wind_speed || 12);
        const humidity = data.weather_humidity || 42;

        return `<div class="screen-container text-white" style="background:#000;">
            ${AppBar.render("modern", data)}
            <main class="content-area grid grid-cols-12 gap-3 p-3" style="background:#000;">
                <!-- Map (larger) -->
                <div class="col-span-8 flex flex-col gap-3 h-full">
                    <div class="relative flex-grow rounded-xl overflow-hidden border border-zinc-800">
                        <div id="weather-map" class="absolute inset-0 z-0"></div>
                        <!-- Location + weather overlay -->
                        <div class="absolute top-3 left-3 z-10 px-3 py-2 rounded-lg flex items-center gap-2" style="background:rgba(0,0,0,0.75);border:1px solid rgba(255,255,255,0.1);">
                            <span class="material-symbols-outlined text-red-500" style="font-size:16px;">location_on</span>
                            <span id="weather-city" class="text-xs font-bold text-white">${city}</span>
                        </div>
                        <div class="absolute bottom-3 left-3 right-3 z-10 rounded-lg px-3 py-2 flex justify-between items-center" style="background:rgba(0,0,0,0.75);border:1px solid rgba(255,255,255,0.1);">
                            <div class="flex items-center gap-2">
                                <span class="material-symbols-outlined text-blue-400" style="font-size:20px;font-variation-settings:'FILL' 1;">${_weatherIcon(condition)}</span>
                                <span id="weather-condition" class="text-sm font-bold">${condition}</span>
                                <span id="weather-temp" class="text-lg font-bold ml-2">${temp}°</span>
                            </div>
                            <div class="flex gap-3 text-[10px] text-zinc-400">
                                <span id="weather-wind">${wind} km/h</span>
                                <span id="weather-humidity">${humidity}%</span>
                            </div>
                        </div>
                        <div class="absolute inset-0 pointer-events-none bg-gradient-to-t from-black/50 to-transparent z-[1]"></div>
                    </div>
                </div>
                <!-- Weather panel -->
                <div class="col-span-4 flex flex-col gap-3 h-full">
                    <div class="rounded-xl p-4 flex flex-col justify-between flex-grow" style="background:rgba(24,24,27,0.8);backdrop-filter:blur(12px);border:1px solid rgba(255,255,255,0.1);">
                        <div>
                            <p class="text-xs font-bold text-zinc-500 uppercase tracking-widest">${t("weather")}</p>
                            <span class="text-5xl font-light tracking-tighter text-white">${temp}°</span>
                        </div>
                        <div class="mt-3 pt-3 border-t border-white/10 grid grid-cols-3 gap-1 text-center">
                            <div><p class="text-[9px] text-zinc-500">16:00</p><span class="material-symbols-outlined text-blue-300" style="font-size:14px;">wb_sunny</span><p class="text-[11px] font-bold">${temp+1}°</p></div>
                            <div><p class="text-[9px] text-zinc-500">17:00</p><span class="material-symbols-outlined text-zinc-400" style="font-size:14px;">cloud</span><p class="text-[11px] font-bold">${temp-1}°</p></div>
                            <div><p class="text-[9px] text-zinc-500">18:00</p><span class="material-symbols-outlined text-zinc-500" style="font-size:14px;">rainy</span><p class="text-[11px] font-bold">${temp-3}°</p></div>
                        </div>
                    </div>
                    <div class="rounded-xl p-3 grid grid-cols-2 gap-2" style="background:rgba(24,24,27,0.8);border:1px solid rgba(255,255,255,0.1);">
                        <div class="flex items-center gap-1">
                            <span class="material-symbols-outlined text-zinc-500" style="font-size:16px;">air</span>
                            <div><p class="text-[8px] text-zinc-500 uppercase">${t("wind")}</p><p class="text-xs font-bold">${wind} km/h</p></div>
                        </div>
                        <div class="flex items-center gap-1">
                            <span class="material-symbols-outlined text-zinc-500" style="font-size:16px;">humidity_percentage</span>
                            <div><p class="text-[8px] text-zinc-500 uppercase">${t("humidity")}</p><p class="text-xs font-bold">${humidity}%</p></div>
                        </div>
                    </div>
                </div>
            </main>
            ${NavBar.render("modern", "a4")}
        </div>`;
    }

    function _renderAutodelta(data) {
        const t = App.t.bind(App);
        const city = data.weather_city || "Milano, IT";
        const condition = data.weather_condition || "Partly Cloudy";
        const temp = data.weather_temp != null ? Math.round(data.weather_temp) : 24;
        const feels = data.weather_feels_like != null ? Math.round(data.weather_feels_like) : temp + 2;
        const wind = Math.round(data.weather_wind_speed || 12);
        const humidity = data.weather_humidity || 64;

        return `<div class="screen-container bg-black text-white">
            ${AppBar.render("autodelta", data)}
            <main class="content-area">
                <div class="grid grid-cols-12 grid-rows-6 gap-3 p-3 h-full">
                    <!-- Weather hero -->
                    <div class="col-span-4 row-span-4 autodelta-glass rounded-xl p-4 flex flex-col justify-between relative overflow-hidden">
                        <div class="absolute top-[-20%] right-[-10%] opacity-15">
                            <span class="material-symbols-outlined text-[120px] text-[#FF5F00]" style="font-variation-settings:'FILL' 1;">cloud</span>
                        </div>
                        <div class="relative z-10">
                            <div class="flex items-center gap-1 text-[#FF5F00] mb-1">
                                <span class="material-symbols-outlined" style="font-size:14px;">location_on</span>
                                <span id="weather-city" class="text-[10px] font-bold tracking-widest uppercase">${city}</span>
                            </div>
                            <h2 id="weather-condition" class="text-2xl font-black text-white leading-none">${condition}</h2>
                        </div>
                        <div class="relative z-10">
                            <span id="weather-temp" class="text-6xl font-black text-white tracking-tighter">${temp}°</span>
                            <p id="weather-feels" class="text-[#FF5F00] font-bold text-[10px] uppercase">${t("feels_like")} ${feels}°</p>
                        </div>
                    </div>
                    <!-- Map -->
                    <div class="col-span-8 row-span-4 rounded-xl overflow-hidden border border-zinc-800 relative">
                        <div id="weather-map" class="absolute inset-0 z-0"></div>
                        <div class="absolute inset-0 bg-gradient-to-t from-black/70 via-transparent to-transparent z-[1]"></div>
                        <div class="absolute bottom-3 left-3 right-3 z-10 flex justify-between items-center">
                            <div class="px-3 py-1 rounded-full flex items-center gap-2" style="background:rgba(24,24,27,0.8);border:1px solid rgba(255,95,0,0.15);">
                                <div class="w-2 h-2 bg-[#FF5F00] rounded-full animate-pulse"></div>
                                <span class="text-[10px] font-bold text-white uppercase">${t("live_tracking")}</span>
                            </div>
                            <div class="flex items-center gap-2 text-[10px] text-zinc-400 px-2 py-1 rounded-full" style="background:rgba(24,24,27,0.8);">
                                <span class="material-symbols-outlined text-[#FF5F00]" style="font-size:14px;font-variation-settings:'FILL' 1;">${_weatherIcon(condition)}</span>
                                <span class="text-white font-bold">${temp}°</span>
                                <span>${t("wind")} ${wind}km/h</span>
                            </div>
                        </div>
                    </div>
                    <!-- Forecast + stats -->
                    <div class="col-span-12 row-span-2 flex gap-3">
                        ${_forecastRow("Tomorrow", "sunny", temp + 5, temp - 2, "autodelta") ? `
                        <div class="flex-1 autodelta-glass rounded-xl p-2 flex flex-col items-center justify-center gap-1">
                            <span class="text-[9px] font-bold text-zinc-500 uppercase">Tomorrow</span>
                            <span class="material-symbols-outlined text-[#FF5F00]" style="font-size:20px;">sunny</span>
                            <span class="text-base font-black text-white">${temp+5}°</span>
                        </div>
                        <div class="flex-1 autodelta-glass rounded-xl p-2 flex flex-col items-center justify-center gap-1 border-[#FF5F00]/30 bg-[#FF5F00]/5">
                            <span class="text-[9px] font-bold text-[#FF5F00] uppercase">Wednesday</span>
                            <span class="material-symbols-outlined text-[#FF5F00]" style="font-size:20px;font-variation-settings:'FILL' 1;">thunderstorm</span>
                            <span class="text-base font-black text-white">${temp-2}°</span>
                        </div>
                        <div class="flex-1 autodelta-glass rounded-xl p-2 flex flex-col items-center justify-center gap-1">
                            <span class="text-[9px] font-bold text-zinc-500 uppercase">Thursday</span>
                            <span class="material-symbols-outlined text-[#FF5F00]" style="font-size:20px;">partly_cloudy_day</span>
                            <span class="text-base font-black text-white">${temp+1}°</span>
                        </div>` : ''}
                        <div class="flex-[1.5] autodelta-glass rounded-xl p-2 flex flex-col justify-center gap-1">
                            <div class="flex justify-between items-center border-b border-zinc-800 pb-1">
                                <span class="text-[9px] font-bold text-zinc-500 uppercase">${t("wind")}</span>
                                <span id="weather-wind" class="text-xs font-bold text-white">${wind} km/h</span>
                            </div>
                            <div class="flex justify-between items-center border-b border-zinc-800 pb-1">
                                <span class="text-[9px] font-bold text-zinc-500 uppercase">${t("humidity")}</span>
                                <span id="weather-humidity" class="text-xs font-bold text-white">${humidity}%</span>
                            </div>
                            <div class="flex justify-between items-center">
                                <span class="text-[9px] font-bold text-zinc-500 uppercase">UV</span>
                                <span class="text-xs font-bold text-[#FF5F00]">High 7</span>
                            </div>
                        </div>
                    </div>
                </div>
            </main>
            ${NavBar.render("autodelta", "a4")}
        </div>`;
    }

    function _time() { return new Date().toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit", hour12: false }); }
    function _date() { const d = new Date(); return `${["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"][d.getMonth()]} ${d.getDate()}`; }
    function _tempStr(data) { return data.ext_temp != null ? `${Math.round(data.ext_temp)}°C` : "--"; }

    return { render, mount, unmount, update };
})());
