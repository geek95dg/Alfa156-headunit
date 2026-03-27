/**
 * A3 Weather Screen — Weather data + Leaflet.js interactive map.
 */

App.registerScreen("a3", (() => {
    let _map = null;
    let _marker = null;

    function render(container, theme, data) {
        if (theme === "heritage") container.innerHTML = _renderHeritage(data);
        else if (theme === "modern") container.innerHTML = _renderModern(data);
        else if (theme === "autodelta") container.innerHTML = _renderAutodelta(data);
        else container.innerHTML = _renderHeritage(data);
    }

    function mount() {
        // Initialize Leaflet map after DOM is ready
        setTimeout(_initMap, 100);
    }

    function unmount() {
        if (_map) {
            _map.remove();
            _map = null;
            _marker = null;
        }
    }

    function update(data) {
        _updateEl("weather-city", data.weather_city || "---");
        _updateEl("weather-condition", data.weather_condition || "---");
        _updateEl("weather-temp", data.weather_temp != null ? `${Math.round(data.weather_temp)}°` : "--°");
        _updateEl("weather-feels", data.weather_feels_like != null ? `Feels like ${Math.round(data.weather_feels_like)}°` : "");
        _updateEl("weather-wind", `${Math.round(data.weather_wind_speed || 0)} km/h`);
        _updateEl("weather-humidity", `${data.weather_humidity || 0}%`);

        // Update map position
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
            center: [lat, lon],
            zoom: 13,
            zoomControl: false,
            attributionControl: false,
        });

        L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
            maxZoom: 19,
        }).addTo(_map);

        const theme = App.getTheme();
        const markerColor = theme === "modern" ? "#3b82f6" : theme === "autodelta" ? "#FF5F00" : "#f59e0b";
        const markerIcon = L.divIcon({
            className: "",
            html: `<div style="width:16px;height:16px;border-radius:50%;background:${markerColor};border:2px solid white;box-shadow:0 0 10px ${markerColor};"></div>`,
            iconSize: [16, 16],
            iconAnchor: [8, 8],
        });

        _marker = L.marker([lat, lon], { icon: markerIcon }).addTo(_map);
    }

    function _forecastHtml(data, theme) {
        const forecast = data.weather_forecast || [
            { day: "Tomorrow", high: 28, low: 18, condition: "sunny", icon: "sunny" },
            { day: "Wed", high: 22, low: 15, condition: "cloudy", icon: "cloud" },
            { day: "Thu", high: 19, low: 12, condition: "rainy", icon: "rainy" },
        ];
        return forecast.map(f => {
            const iconColor = theme === "autodelta" ? "text-[#FF5F00]"
                : theme === "heritage" ? "text-amber-500" : "text-blue-400";
            return `<div class="flex items-center justify-between py-1">
                <span class="text-gray-300 w-12">${f.day}</span>
                <span class="material-symbols-outlined ${iconColor}">${f.icon || "cloud"}</span>
                <div class="flex gap-3 text-right">
                    <span class="text-white font-medium w-6">${f.high}°</span>
                    <span class="text-gray-500 w-6">${f.low}°</span>
                </div>
            </div>`;
        }).join("");
    }

    function _renderHeritage(data) {
        const city = data.weather_city || "Milan, IT";
        const condition = data.weather_condition || "Partly Cloudy";
        const temp = data.weather_temp != null ? Math.round(data.weather_temp) : 22;
        const feels = data.weather_feels_like != null ? Math.round(data.weather_feels_like) : temp + 2;

        return `<div class="screen-container bg-[#221610] text-white">
            <header class="flex items-center justify-between px-6 py-3 border-b border-[#3d2716] bg-gradient-to-r from-[#3d2716] via-[#221610] to-[#3d2716] shrink-0">
                <div class="flex items-center gap-4 w-1/3">
                    <span class="text-xl font-bold text-[#ff9a3d] tracking-wide" data-bind="time">${_time()}</span>
                    <span class="text-sm font-medium text-gray-400" data-bind="date">${_date()}</span>
                </div>
                <div class="flex-1 flex justify-center w-1/3">
                    <span class="text-2xl font-bold tracking-[0.2em] text-white">ALFA ROMEO</span>
                </div>
                <div class="flex items-center justify-end gap-4 w-1/3">
                    <span class="material-symbols-outlined text-gray-400">bluetooth</span>
                    <span class="text-lg font-bold text-[#ec5b13]" data-bind="ext_temp">${_tempStr(data)}</span>
                </div>
            </header>
            <main class="content-area flex overflow-hidden">
                <!-- Left: Weather -->
                <div class="w-1/3 p-6 flex flex-col gap-6 bg-[#3d2716]/50 border-r border-[#3d2716]">
                    <div class="flex flex-col gap-1">
                        <h1 id="weather-city" class="text-3xl font-bold text-white tracking-wide">${city}</h1>
                        <p id="weather-condition" class="text-[#ff9a3d] text-lg">${condition}</p>
                    </div>
                    <div class="flex items-center gap-4 my-2">
                        <span class="material-symbols-outlined text-6xl text-[#ec5b13]" style="font-variation-settings:'FILL' 1;">partly_cloudy_day</span>
                        <div class="flex flex-col">
                            <span id="weather-temp" class="text-5xl font-bold text-white tracking-tighter">${temp}°</span>
                            <span id="weather-feels" class="text-sm text-gray-400">Feels like ${feels}°</span>
                        </div>
                    </div>
                    <div class="flex flex-col gap-3 mt-auto">
                        <h3 class="text-sm uppercase tracking-widest text-gray-400 mb-1 border-b border-[#5a3a22] pb-2">3-Day Forecast</h3>
                        ${_forecastHtml(data, "heritage")}
                    </div>
                </div>
                <!-- Right: Map -->
                <div class="flex-1 relative bg-black">
                    <div id="weather-map" class="absolute inset-0 z-0"></div>
                    <div class="absolute inset-x-0 top-0 p-6 flex justify-between items-start pointer-events-none z-10">
                        <div class="flex items-center bg-[#221610]/90 border border-[#5a3a22] backdrop-blur-sm rounded-full px-4 py-2 w-72 pointer-events-auto shadow-lg">
                            <span class="material-symbols-outlined text-[#ff9a3d] mr-3">search</span>
                            <span class="text-sm text-gray-500">Change Location...</span>
                        </div>
                        <div class="flex flex-col gap-2 pointer-events-auto">
                            <button class="w-10 h-10 rounded-full bg-[#221610]/90 border border-[#5a3a22] flex items-center justify-center text-[#ff9a3d]" onclick="if(_map)_map.locate({setView:true});">
                                <span class="material-symbols-outlined">my_location</span>
                            </button>
                            <button class="w-10 h-10 rounded-full bg-[#221610]/90 border border-[#5a3a22] flex items-center justify-center text-white mt-4" onclick="if(_map)_map.zoomIn();">
                                <span class="material-symbols-outlined">add</span>
                            </button>
                            <button class="w-10 h-10 rounded-full bg-[#221610]/90 border border-[#5a3a22] flex items-center justify-center text-white" onclick="if(_map)_map.zoomOut();">
                                <span class="material-symbols-outlined">remove</span>
                            </button>
                        </div>
                    </div>
                </div>
            </main>
            ${NavBar.render("heritage", "a3")}
        </div>`;
    }

    function _renderModern(data) {
        const city = data.weather_city || "Milan";
        const condition = data.weather_condition || "Partly Cloudy";
        const temp = data.weather_temp != null ? Math.round(data.weather_temp) : 18;
        const wind = Math.round(data.weather_wind_speed || 12);
        const humidity = data.weather_humidity || 42;

        return `<div class="screen-container text-white" style="background:#000;">
            ${AppBar.render("modern", data)}
            <main class="content-area grid grid-cols-12 gap-3 p-3" style="background:#000;">
                <!-- Map -->
                <div class="col-span-8 flex flex-col gap-3 h-full">
                    <div class="relative flex-grow rounded-xl overflow-hidden border border-zinc-800">
                        <div id="weather-map" class="absolute inset-0 z-0"></div>
                        <div class="absolute top-4 left-4 glass-card px-4 py-2 rounded-lg flex items-center gap-3 z-10" style="background:rgba(0,0,0,0.7);border:1px solid rgba(255,255,255,0.1);">
                            <span class="material-symbols-outlined text-red-500">location_on</span>
                            <div>
                                <p class="text-[10px] text-zinc-400 uppercase font-bold tracking-wider">Current Location</p>
                                <p id="weather-city" class="text-sm font-bold text-white">${city}</p>
                            </div>
                        </div>
                        <div class="absolute inset-0 pointer-events-none bg-gradient-to-t from-black/60 to-transparent z-[1]"></div>
                    </div>
                </div>
                <!-- Weather panel -->
                <div class="col-span-4 flex flex-col gap-3 h-full">
                    <div class="rounded-xl p-5 flex flex-col justify-between flex-grow" style="background:rgba(24,24,27,0.8);backdrop-filter:blur(12px);border:1px solid rgba(255,255,255,0.1);">
                        <div class="flex justify-between items-start">
                            <div>
                                <p class="text-xs font-bold text-zinc-500 uppercase tracking-widest">Weather</p>
                                <p id="weather-condition" class="text-lg font-bold text-white">${condition}</p>
                            </div>
                            <span class="material-symbols-outlined text-4xl text-blue-400">cloud</span>
                        </div>
                        <div class="mt-4">
                            <span id="weather-temp" class="text-6xl font-light tracking-tighter text-white">${temp}°</span>
                        </div>
                        <div class="mt-4 pt-4 border-t border-white/10 grid grid-cols-3 gap-2 text-center">
                            <div><p class="text-[10px] text-zinc-500 font-bold">16:00</p><span class="material-symbols-outlined text-sm my-1 text-blue-300">wb_sunny</span><p class="text-xs font-bold">${temp+1}°</p></div>
                            <div><p class="text-[10px] text-zinc-500 font-bold">17:00</p><span class="material-symbols-outlined text-sm my-1 text-zinc-400">cloud</span><p class="text-xs font-bold">${temp-1}°</p></div>
                            <div><p class="text-[10px] text-zinc-500 font-bold">18:00</p><span class="material-symbols-outlined text-sm my-1 text-zinc-500">rainy</span><p class="text-xs font-bold">${temp-3}°</p></div>
                        </div>
                    </div>
                    <div class="rounded-xl p-3 grid grid-cols-2 gap-2" style="background:rgba(24,24,27,0.8);backdrop-filter:blur(12px);border:1px solid rgba(255,255,255,0.1);">
                        <div class="flex items-center gap-2">
                            <span class="material-symbols-outlined text-zinc-500 text-lg">air</span>
                            <div class="leading-none"><p class="text-[8px] text-zinc-500 uppercase font-bold">Wind</p><p id="weather-wind" class="text-xs font-bold">${wind} km/h</p></div>
                        </div>
                        <div class="flex items-center gap-2">
                            <span class="material-symbols-outlined text-zinc-500 text-lg">humidity_percentage</span>
                            <div class="leading-none"><p class="text-[8px] text-zinc-500 uppercase font-bold">Hum</p><p id="weather-humidity" class="text-xs font-bold">${humidity}%</p></div>
                        </div>
                    </div>
                </div>
            </main>
            ${NavBar.render("modern", "a3")}
        </div>`;
    }

    function _renderAutodelta(data) {
        const city = data.weather_city || "Milano, IT";
        const condition = data.weather_condition || "Partly Cloudy";
        const temp = data.weather_temp != null ? Math.round(data.weather_temp) : 24;
        const feels = data.weather_feels_like != null ? Math.round(data.weather_feels_like) : temp + 2;
        const wind = Math.round(data.weather_wind_speed || 12);
        const humidity = data.weather_humidity || 64;

        return `<div class="screen-container bg-black text-white">
            ${AppBar.render("autodelta", data)}
            <main class="content-area">
                <div class="grid grid-cols-12 grid-rows-6 gap-3 p-4 h-full">
                    <!-- Weather Hero -->
                    <div class="col-span-5 row-span-4 autodelta-glass rounded-xl p-5 flex flex-col justify-between relative overflow-hidden">
                        <div class="absolute top-[-20%] right-[-10%] opacity-20">
                            <span class="material-symbols-outlined text-[140px] text-[#FF5F00]" style="font-variation-settings:'FILL' 1;">cloud</span>
                        </div>
                        <div class="relative z-10">
                            <div class="flex items-center gap-2 text-[#FF5F00] mb-1">
                                <span class="material-symbols-outlined text-lg">location_on</span>
                                <span id="weather-city" class="text-xs font-bold tracking-widest uppercase">${city}</span>
                            </div>
                            <h2 id="weather-condition" class="text-4xl font-black text-white leading-none">${condition}</h2>
                        </div>
                        <div class="relative z-10 flex items-end gap-2">
                            <span id="weather-temp" class="text-7xl font-black text-white tracking-tighter">${temp}°</span>
                            <div class="flex flex-col pb-2">
                                <span id="weather-feels" class="text-[#FF5F00] font-bold text-xs uppercase">Feels like ${feels}°</span>
                            </div>
                        </div>
                    </div>
                    <!-- Map -->
                    <div class="col-span-7 row-span-4 rounded-xl overflow-hidden border border-zinc-800 relative">
                        <div id="weather-map" class="absolute inset-0 z-0"></div>
                        <div class="absolute inset-0 bg-gradient-to-t from-black/80 via-transparent to-transparent z-[1]"></div>
                        <div class="absolute bottom-4 left-4 right-4 flex justify-between items-center z-10">
                            <div class="px-3 py-1.5 rounded-full flex items-center gap-2" style="background:rgba(24,24,27,0.8);border:1px solid rgba(255,95,0,0.1);">
                                <div class="w-2 h-2 bg-[#FF5F00] rounded-full animate-pulse"></div>
                                <span class="text-[10px] font-bold text-white tracking-wider uppercase">Live Tracking</span>
                            </div>
                            <button class="bg-[#FF5F00] text-black p-2 rounded-lg" onclick="if(_map)_map.locate({setView:true});">
                                <span class="material-symbols-outlined text-lg" style="font-variation-settings:'FILL' 1;">my_location</span>
                            </button>
                        </div>
                    </div>
                    <!-- Forecast -->
                    <div class="col-span-12 row-span-2 flex gap-3">
                        ${_autodeltaForecast(data)}
                        <div class="flex-[1.5] autodelta-glass rounded-xl p-3 flex flex-col justify-center gap-2">
                            <div class="flex justify-between items-center border-b border-zinc-800 pb-1">
                                <span class="text-[9px] font-bold text-zinc-500 uppercase">Wind</span>
                                <span id="weather-wind" class="text-xs font-bold text-white">${wind} km/h</span>
                            </div>
                            <div class="flex justify-between items-center border-b border-zinc-800 pb-1">
                                <span class="text-[9px] font-bold text-zinc-500 uppercase">Humidity</span>
                                <span id="weather-humidity" class="text-xs font-bold text-white">${humidity}%</span>
                            </div>
                            <div class="flex justify-between items-center">
                                <span class="text-[9px] font-bold text-zinc-500 uppercase">UV Index</span>
                                <span class="text-xs font-bold text-[#FF5F00]">High 7</span>
                            </div>
                        </div>
                    </div>
                </div>
            </main>
            ${NavBar.render("autodelta", "a3")}
        </div>`;
    }

    function _autodeltaForecast(data) {
        const forecast = data.weather_forecast || [
            { day: "Tomorrow", icon: "sunny", temp: 29, desc: "Sunny" },
            { day: "Wednesday", icon: "thunderstorm", temp: 22, desc: "Storms" },
            { day: "Thursday", icon: "partly_cloudy_day", temp: 25, desc: "Cloudy" },
        ];
        return forecast.map((f, i) => {
            const highlight = i === 1 ? "border-[#FF5F00]/30 bg-[#FF5F00]/5" : "";
            const labelColor = i === 1 ? "text-[#FF5F00]" : "text-zinc-500";
            return `<div class="flex-1 autodelta-glass rounded-xl p-3 flex flex-col items-center justify-center gap-2 ${highlight}">
                <span class="text-[10px] font-bold ${labelColor} uppercase">${f.day}</span>
                <span class="material-symbols-outlined text-[#FF5F00]" ${i === 1 ? "style=\"font-variation-settings:'FILL' 1;\"" : ""}>${f.icon}</span>
                <div class="flex flex-col items-center">
                    <span class="text-lg font-black text-white">${f.temp}°</span>
                    <span class="text-[9px] text-zinc-500 font-bold">${f.desc}</span>
                </div>
            </div>`;
        }).join("");
    }

    function _time() {
        return new Date().toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit", hour12: false });
    }
    function _date() {
        const months = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
        const d = new Date();
        return `${months[d.getMonth()]} ${d.getDate()}`;
    }
    function _tempStr(data) {
        if (data.ext_temp == null) return "--";
        return `${Math.round(data.ext_temp)}°C`;
    }

    return { render, mount, unmount, update };
})());
