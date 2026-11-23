/**
 * A3 Weather Screen — Weather data + Leaflet.js interactive map.
 * No search bar — shows actual live weather data overlaid on map.
 * Optimized for encoder navigation (no touch inputs).
 */

App.registerScreen("a4", (() => {
    let _map = null;
    let _marker = null;

    /** City and condition come from OpenWeatherMap (and the city also from
     *  POST /api/weather/location) — escaped before they go into innerHTML.
     *  update() uses textContent and needs no escaping. */
    function _esc(v) {
        return String(v == null ? "" : v)
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#39;");
    }

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
        _updateEl("weather-city", _cityText(data));
        _updateEl("weather-status", _statusText(data));
        _updateEl("weather-condition", data.weather_condition || "---");
        _updateEl("weather-temp", data.weather_temp != null ? `${Math.round(data.weather_temp)}°` : "--°");
        _updateEl("weather-feels", data.weather_feels_like != null ? `Feels ${Math.round(data.weather_feels_like)}°` : "");
        _updateEl("weather-wind", `${Math.round(data.weather_wind_speed || 0)} km/h`);
        _updateEl("weather-humidity", `${data.weather_humidity || 0}%`);
        _updateEl("weather-gps-label", _gpsLabel(data));
        _updateAlerts(data);
        _updateForecast(data);

        // Move map to weather location (from search) or GPS position
        const wLat = data.weather_lat || data.gps_lat;
        const wLon = data.weather_lon || data.gps_lon;
        if (_map && wLat && wLon) {
            const pos = [wLat, wLon];
            _map.setView(pos, _map.getZoom());
            if (_marker) _marker.setLatLng(pos);
        }
    }

    function _updateEl(id, text) {
        const el = document.getElementById(id);
        if (el) el.textContent = text;
    }

    /** data.weather_status (web_viewer._weather_status_summary of
     *  weather.status): source demo | cache | live, last_error, http_code.
     *  The demo data ("Milan, IT") is published at start so the screen is
     *  never empty — it must never pass for the weather outside. */
    function _isDemo(data) {
        const ws = data && data.weather_status;
        return !!(ws && typeof ws === "object" && ws.source === "demo");
    }

    /** City label: a clear placeholder while only demo data exists. */
    function _cityText(data) {
        if (_isDemo(data)) return App.t("weather_no_data", "brak prawdziwych danych pogody");
        return (data && typeof data.weather_city === "string" && data.weather_city) || "---";
    }

    /** One status line: why the data is demo / old, or '' when live and the
     *  last request worked. Fixed i18n strings + an integer HTTP code only
     *  (safe in the template and via textContent). */
    function _statusText(data) {
        const ws = data && data.weather_status;
        if (!ws || typeof ws !== "object") return "";
        const t = (k, d) => App.t(k, d);
        const code = Number.isInteger(ws.http_code) ? ws.http_code : null;
        let why = "";
        switch (ws.last_error) {
            case "no_key": why = t("weather_err_no_key", "brak klucza — wpisz BCM_OWM_API_KEY do /etc/bcm/bcm.env"); break;
            case "network": why = t("weather_err_network", "brak połączenia z serwerem pogody"); break;
            case "bad_response": why = t("weather_err_bad", "dziwna odpowiedź serwera pogody"); break;
            case "http":
                why = (code === 401 || code === 403)
                    ? t("weather_err_auth", "błąd {code} — zły albo nieaktywny klucz").replace("{code}", String(code))
                    : t("weather_err_http", "błąd HTTP {code}").replace("{code}", code === null ? "?" : String(code));
                break;
            default: why = "";
        }
        if (ws.source === "demo") {
            const head = t("weather_demo", "dane przykładowe");
            return why ? `${head} — ${why}` : `${head} — ${t("weather_waiting", "czekam na pierwsze pobranie")}`;
        }
        if (ws.source === "cache") {
            const head = t("weather_cache", "dane z pamięci");
            return why ? `${head} — ${why}` : head;
        }
        return why ? `${t("weather_last_fetch", "ostatnie pobranie")}: ${why}` : "";
    }

    function _statusHtml(data, cls) {
        return `<p id="weather-status" data-weather-source="${_esc((data && data.weather_status && data.weather_status.source) || "")}" class="${cls}" style="color:#fbbf24;font-size:10px;line-height:1.3;">${_esc(_statusText(data))}</p>`;
    }

    /** Map badge: "GPS AKTYWNY" only with a real fix (data.gps_fix from the
     *  backend). It used to say so always — also while the weather was for
     *  the default city because no GPS had arrived. Fixed i18n strings only,
     *  so it is safe in the template and via textContent. */
    function _gpsLabel(data) {
        return (data && data.gps_fix === true)
            ? App.t("gps_active", "GPS AKTYWNY")
            : App.t("gps_no_fix", "BRAK GPS");
    }

    function _initMap() {
        const mapEl = document.getElementById("weather-map");
        if (!mapEl || _map) return;

        const data = DataStore.getAll();
        const lat = data.weather_lat || data.gps_lat || 45.4642;
        const lon = data.weather_lon || data.gps_lon || 9.1900;

        _map = L.map(mapEl, {
            center: [lat, lon], zoom: 13,
            zoomControl: false, attributionControl: false,
            keyboard: false, dragging: false, scrollWheelZoom: false,
            doubleClickZoom: false, touchZoom: false,
        });

        L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 19 }).addTo(_map);

        // Store map reference globally so WeatherSearch can access it
        window._weatherMap = _map;
        window._weatherMarker = null;

        const theme = App.getTheme();
        const color = theme === "modern" ? "#3b82f6" : theme === "autodelta" ? "#FF5F00" : "#f59e0b";
        _marker = L.marker([lat, lon], {
            icon: L.divIcon({
                className: "",
                html: `<div style="width:14px;height:14px;border-radius:50%;background:${color};border:2px solid white;box-shadow:0 0 10px ${color};"></div>`,
                iconSize: [14, 14], iconAnchor: [7, 7],
            }),
        }).addTo(_map);
        window._weatherMarker = _marker;
    }

    // ── forecast rows: data.weather_forecast (weather.forecast) ─────────
    // Daily entries from WeatherManager._parse_forecast: {day: "Today" | "Wed"
    // …, high, low, condition, icon: OWM code}. They used to be made up from
    // the current temperature (temp + 3, temp - 5 …) — now real or nothing.
    const _OWM_GLYPHS = { "01": "sunny", "02": "partly_cloudy_day", "03": "cloud", "04": "cloud",
                          "09": "rainy", "10": "rainy", "11": "thunderstorm", "13": "ac_unit",
                          "50": "foggy" };
    const _DAY_KEYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"];

    /** Pure: up to 3 validated forecast entries → {label, glyph, high, low}
     *  (label from fixed i18n keys only, numbers rounded or null). */
    function forecastEntries(data) {
        // Demo data ("Milan, IT" before the first real fetch) is no forecast.
        if (data && data.weather_status && data.weather_status.source === "demo") return [];
        const list = data && Array.isArray(data.weather_forecast) ? data.weather_forecast : [];
        const out = [];
        const num = (v) => (typeof v === "number" && isFinite(v) && Math.abs(v) < 100 ? Math.round(v) : null);
        for (const f of list) {
            if (!f || typeof f !== "object") continue;
            const day = typeof f.day === "string" ? f.day : "";
            let label;
            if (day === "Today") label = App.t("weather_today", "DZIŚ");
            else {
                const key = day.slice(0, 3).toLowerCase();
                label = _DAY_KEYS.indexOf(key) !== -1 ? App.t(key, key.toUpperCase()) : "—";
            }
            const code = typeof f.icon === "string" && /^[0-9]{2}[dn]$/.test(f.icon) ? f.icon.slice(0, 2) : "";
            const high = num(f.high), low = num(f.low);
            if (high === null && low === null) continue;
            out.push({ label, glyph: _OWM_GLYPHS[code] || "partly_cloudy_day", high, low });
            if (out.length === 3) break;
        }
        return out;
    }

    function _deg(v) { return v === null ? "--°" : `${v}°`; }

    function _forecastRow(f, theme) {
        const iconColor = theme === "autodelta" ? "text-[#FF5F00]" : theme === "heritage" ? "text-amber-500" : "text-blue-400";
        return `<div class="flex items-center justify-between py-0.5">
            <span class="text-zinc-400 w-10 text-[11px]">${_esc(f.label)}</span>
            <span class="material-symbols-outlined ${iconColor}" style="font-size:18px;">${f.glyph}</span>
            <span class="text-white font-medium text-xs w-6 text-right">${_deg(f.high)}</span>
            <span class="text-zinc-600 text-xs w-6 text-right">${_deg(f.low)}</span>
        </div>`;
    }

    // Per-theme forecast markup, inside a #weather-forecast container so
    // update() can refresh it in place: A4 may be open when the first real
    // fetch (or a new day) arrives, and render() runs only on screen entry.
    function _forecastHeritage(fc) {
        return fc.length ? fc.map((f) => _forecastRow(f, "heritage")).join("") : _noForecast();
    }

    function _forecastModern(fc) {
        return fc.length ? fc.map((f) => `<div><p class="text-[9px] text-zinc-500">${_esc(f.label)}</p><span class="material-symbols-outlined text-blue-300" style="font-size:14px;">${f.glyph}</span><p class="text-[11px] font-bold">${_deg(f.high)} <span class="text-zinc-500">${_deg(f.low)}</span></p></div>`).join("") : `<div style="grid-column:span 3;">${_noForecast()}</div>`;
    }

    function _forecastAutodelta(fc) {
        return fc.length ? fc.map((f, i) => `
                        <div class="flex-1 autodelta-glass rounded-xl p-2 flex flex-col items-center justify-center gap-1"${i === 1 ? ' style="border-color:rgba(255,95,0,0.3);background:rgba(255,95,0,0.05);"' : ""}>
                            <span class="text-[9px] font-bold text-zinc-500 uppercase">${_esc(f.label)}</span>
                            <span class="material-symbols-outlined text-[#FF5F00]" style="font-size:20px;">${f.glyph}</span>
                            <span class="text-base font-black text-white">${_deg(f.high)} <span class="text-zinc-500" style="font-size:11px;">${_deg(f.low)}</span></span>
                        </div>`).join("") : `<div class="flex-1 autodelta-glass rounded-xl p-2 flex items-center justify-center">${_noForecast()}</div>`;
    }

    const _FORECAST_BY_THEME = { heritage: _forecastHeritage, modern: _forecastModern,
                                 autodelta: _forecastAutodelta };

    function _updateForecast(data) {
        const el = document.getElementById("weather-forecast");
        if (!el) return;
        const fn = _FORECAST_BY_THEME[el.getAttribute && el.getAttribute("data-theme")];
        if (!fn) return;
        const key = JSON.stringify(forecastEntries(data));
        // Rewrite only on a change (update() runs every second).
        if (el._fcKey === key) return;
        el._fcKey = key;
        el.innerHTML = fn(forecastEntries(data));
    }

    function _noForecast() {
        return `<p class="text-zinc-500" style="font-size:11px;" data-weather-forecast="none">${_esc(App.t("weather_no_forecast", "brak prognozy"))}</p>`;
    }

    // ── weather warnings (data.weather_alerts, modules.weather_alerts) ──
    // Inline styles only (Tailwind is precompiled). Texts are escaped: they
    // are built by BCM, but from network data, and pass the bus.
    const _ALERT_COLORS = { info: "#38bdf8", warning: "#f59e0b", danger: "#dc2626" };
    const _ALERT_GLYPHS = { icing: "ac_unit", snow: "weather_snowy", rain: "rainy",
                            storm: "thunderstorm", wind: "air", fog: "foggy" };

    function alertList(data) {
        const list = data && Array.isArray(data.weather_alerts) ? data.weather_alerts : [];
        return list.filter((a) => a && typeof a === "object"
            && Object.prototype.hasOwnProperty.call(_ALERT_GLYPHS, a.kind)
            && Object.prototype.hasOwnProperty.call(_ALERT_COLORS, a.severity));
    }

    function _alertsInner(alerts) {
        if (!alerts.length) return "";
        const a = alerts[0];
        const color = _ALERT_COLORS[a.severity];
        const more = alerts.length > 1
            ? `<span style="margin-left:6px;color:#a1a1aa;white-space:nowrap;">${_esc(App.t("weather_alert_more", "+{n} więcej").replace("{n}", String(alerts.length - 1)))}</span>`
            : "";
        return `<div style="display:flex;align-items:center;gap:8px;border-left:4px solid ${color};padding:4px 8px;">`
            + `<span class="material-symbols-outlined" style="font-size:22px;color:${color};font-variation-settings:'FILL' 1;">${_ALERT_GLYPHS[a.kind]}</span>`
            + `<div style="min-width:0;flex:1;">`
            + `<div style="font-size:12px;font-weight:700;color:${color};white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">${_esc(a.title)} · ${_esc(a.where)}${more}</div>`
            + `<div style="font-size:11px;color:#e4e4e7;line-height:1.25;overflow:hidden;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;">${_esc(a.text)}</div>`
            + `</div></div>`;
    }

    /** The strip, positioned over the map; present (hidden) without alerts
     *  so update() can show it in place. */
    function _alertsHtml(data, pos) {
        const alerts = alertList(data);
        return `<div id="weather-alerts" data-count="${alerts.length}" style="position:absolute;${pos}z-index:20;background:rgba(0,0,0,0.82);border-radius:8px;overflow:hidden;display:${alerts.length ? "block" : "none"};">${_alertsInner(alerts)}</div>`;
    }

    function _updateAlerts(data) {
        const el = document.getElementById("weather-alerts");
        if (!el) return;
        const alerts = alertList(data);
        const inner = _alertsInner(alerts);
        // Rewrite only on a change (update() runs every second).
        if (el.innerHTML !== inner) el.innerHTML = inner;
        if (el.style) el.style.display = alerts.length ? "block" : "none";
        if (typeof el.setAttribute === "function") el.setAttribute("data-count", String(alerts.length));
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
        const fc = forecastEntries(data);
        const city = _esc(_cityText(data));
        const condition = _esc(data.weather_condition || "Partly Cloudy");
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
                    <div class="relative mb-3">
                        <div class="flex items-center gap-2 bg-zinc-900/60 border border-amber-900/30 rounded-full px-3 py-1.5">
                            <span class="material-symbols-outlined text-amber-500" style="font-size:16px;">search</span>
                            <input id="weather-search-input" type="text" placeholder="${t("weather_search", "Szukaj lokalizacji...")}"
                                   class="bg-transparent border-none text-sm text-white placeholder-zinc-600 w-full outline-none p-0" style="font-size:12px;"
                                   oninput="WeatherSearch.query(this.value)">
                        </div>
                        <div id="weather-search-results" class="absolute left-0 right-0 top-full mt-1 z-50 rounded-lg overflow-hidden" style="display:none;"></div>
                    </div>
                    <div class="mb-2">
                        <h1 id="weather-city" class="text-xl font-bold text-white">${city}</h1>
                        ${_statusHtml(data, "")}
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
                        <div id="weather-forecast" data-theme="heritage">${_forecastHeritage(fc)}</div>
                    </div>
                </div>
                <!-- Right: Map with weather overlay -->
                <div class="flex-1 relative bg-black">
                    <div id="weather-map" class="absolute inset-0 z-0"></div>
                    ${_alertsHtml(data, "top:12px;right:12px;width:60%;")}
                    <!-- Weather data overlay on map -->
                    <div class="absolute top-3 left-3 z-10 bg-black/70 backdrop-blur-sm rounded-lg px-3 py-2 border border-amber-900/30">
                        <div class="flex items-center gap-2">
                            <span class="material-symbols-outlined text-amber-500" style="font-size:16px;">location_on</span>
                            <span id="weather-gps-label" class="text-[10px] text-zinc-400 font-bold uppercase">${_gpsLabel(data)}</span>
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
        const fc = forecastEntries(data);
        const city = _esc(_cityText(data));
        const condition = _esc(data.weather_condition || "Partly Cloudy");
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
                        <!-- Search bar overlay -->
                        <div class="absolute top-3 left-3 right-3 z-20 flex gap-2">
                            <div class="relative flex-1">
                                <div class="flex items-center gap-2 rounded-lg px-3 py-1.5" style="background:rgba(0,0,0,0.75);border:1px solid rgba(255,255,255,0.1);">
                                    <span class="material-symbols-outlined text-red-500" style="font-size:16px;">search</span>
                                    <input id="weather-search-input" type="text" placeholder="${t("weather_search","Search location...")}"
                                           class="bg-transparent border-none text-xs text-white placeholder-zinc-500 w-full outline-none p-0"
                                           oninput="WeatherSearch.query(this.value)" value="">
                                    <span id="weather-city" class="text-xs font-bold text-white whitespace-nowrap">${city}</span>
                                </div>
                                <div id="weather-search-results" class="absolute left-0 right-0 top-full mt-1 z-50 rounded-lg overflow-hidden" style="display:none;"></div>
                                <div style="margin-top:4px;padding:0 4px;background:rgba(0,0,0,0.6);border-radius:6px;">${_statusHtml(data, "")}</div>
                            </div>
                        </div>
                        ${_alertsHtml(data, "bottom:64px;left:12px;right:12px;")}
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
                        <div id="weather-forecast" data-theme="modern" class="mt-3 pt-3 border-t border-white/10 grid grid-cols-3 gap-1 text-center">
                            ${_forecastModern(fc)}
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
        const fc = forecastEntries(data);
        const city = _esc(_cityText(data));
        const condition = _esc(data.weather_condition || "Partly Cloudy");
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
                            <!-- Search bar -->
                            <div class="relative mb-2">
                                <div class="flex items-center gap-2 bg-black/40 border border-[#FF5F00]/20 rounded-full px-3 py-1">
                                    <span class="material-symbols-outlined text-[#FF5F00]" style="font-size:14px;">search</span>
                                    <input id="weather-search-input" type="text" placeholder="${t("weather_search","Search...")}"
                                           class="bg-transparent border-none text-[11px] text-white placeholder-zinc-500 w-full outline-none p-0"
                                           oninput="WeatherSearch.query(this.value)">
                                </div>
                                <div id="weather-search-results" class="absolute left-0 right-0 top-full mt-1 z-50 rounded-lg overflow-hidden" style="display:none;"></div>
                            </div>
                            <div class="flex items-center gap-1 text-[#FF5F00] mb-1">
                                <span class="material-symbols-outlined" style="font-size:14px;">location_on</span>
                                <span id="weather-city" class="text-[10px] font-bold tracking-widest uppercase">${city}</span>
                            </div>
                            ${_statusHtml(data, "mb-1")}
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
                        ${_alertsHtml(data, "top:12px;left:12px;right:12px;")}
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
                        <div id="weather-forecast" data-theme="autodelta" style="display:contents;">${_forecastAutodelta(fc)}</div>
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

    return { render, mount, unmount, update, forecastEntries, alertList };
})());

// WeatherSearch — live city autocomplete with debounce
const WeatherSearch = {
    _timer: null,
    _results: [],
    _error: null,

    /** Place names come from the geocoder (OpenWeatherMap, upstream data we
     *  do not control) — escape them before they go into innerHTML. */
    _esc(v) {
        return String(v == null ? "" : v)
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#39;");
    },

    /** Delegated click on the result list: each row carries only its index
     *  (data-weather-idx); no result text is ever part of an inline handler. */
    _onResultClick(ev) {
        const target = ev && ev.target;
        const row = target && typeof target.closest === "function"
            ? target.closest("[data-weather-idx]") : null;
        if (!row) return;
        const idx = Number(row.getAttribute("data-weather-idx"));
        if (Number.isInteger(idx)) WeatherSearch.select(idx);
    },

    query(q) {
        clearTimeout(WeatherSearch._timer);
        if (!q || q.length < 2) {
            WeatherSearch._hideResults();
            return;
        }
        WeatherSearch._timer = setTimeout(() => WeatherSearch._fetch(q), 300);
    },

    async _fetch(q) {
        try {
            const res = await fetch(`/api/weather/search?q=${encodeURIComponent(q)}`);
            const data = await res.json();
            WeatherSearch._results = Array.isArray(data && data.results) ? data.results : [];
            // Why nothing was found (/api/weather/search error code) — a
            // missing or rejected OWM key must not look like "no such city".
            WeatherSearch._error = (data && typeof data.error === "string")
                ? { error: data.error, http_code: Number.isInteger(data.http_code) ? data.http_code : null }
                : null;
            WeatherSearch._showResults();
        } catch (e) {
            WeatherSearch._results = [];
            WeatherSearch._error = { error: "network", http_code: null };
            WeatherSearch._showResults();
        }
    },

    /** One-line text for a search error code (same wording as trip.js). */
    errorText(err) {
        if (!err || typeof err !== "object" || typeof err.error !== "string") return "";
        const t = (k, d) => (typeof App !== "undefined" && App.t ? App.t(k, d) : d);
        const c = Number.isInteger(err.http_code) ? err.http_code : null;
        if (err.error === "no_key") return t("weather_search_no_key", "brak klucza — wpisz BCM_OWM_API_KEY do /etc/bcm/bcm.env");
        if (err.error === "http" && (c === 401 || c === 403)) return t("trip_search_auth", "wyszukiwanie: błąd {code} — zły albo nieaktywny klucz OpenWeatherMap").replace("{code}", String(c));
        if (err.error === "http") return t("trip_search_http", "wyszukiwanie: błąd HTTP {code}").replace("{code}", c === null ? "?" : String(c));
        if (err.error === "bad_response") return t("weather_search_bad", "wyszukiwanie: dziwna odpowiedź serwera");
        return t("trip_search_network", "wyszukiwanie: brak połączenia (internet?)");
    },

    _showResults() {
        const el = document.getElementById("weather-search-results");
        if (!el) return;
        if (WeatherSearch._results.length === 0) {
            const msg = WeatherSearch.errorText(WeatherSearch._error);
            if (!msg) {
                WeatherSearch._hideResults();
                return;
            }
            // textContent only: the message never carries server text.
            el.innerHTML = "";
            const box = document.createElement("div");
            box.className = "px-3 py-2 text-[10px] bg-black/90";
            box.setAttribute("data-weather-search-error", "1");
            box.style.color = "#fca5a5";
            box.textContent = msg;
            el.appendChild(box);
            el.style.display = "block";
            return;
        }
        const theme = App.getTheme();
        const bg = theme === "autodelta" ? "bg-black/90 border-[#FF5F00]/20" : theme === "modern" ? "bg-zinc-900/95 border-zinc-700" : "bg-[#1a0f0a]/95 border-amber-900/30";
        const hoverCls = theme === "autodelta" ? "hover:bg-[#FF5F00]/10" : theme === "modern" ? "hover:bg-zinc-800" : "hover:bg-amber-900/20";
        const accent = theme === "autodelta" ? "text-[#FF5F00]" : theme === "modern" ? "text-blue-400" : "text-amber-500";

        const esc = WeatherSearch._esc;
        el.innerHTML = `<div class="${bg} border rounded-lg overflow-hidden shadow-2xl">
            ${WeatherSearch._results.map((r, i) => {
                r = (r && typeof r === "object") ? r : {};
                const place = (r.state ? esc(r.state) + ", " : "") + esc(r.country);
                return `<div class="px-3 py-2 cursor-pointer ${hoverCls} flex items-center gap-2 transition-colors"
                 data-weather-idx="${i}">
                <span class="material-symbols-outlined ${accent}" style="font-size:14px;">location_on</span>
                <div>
                    <span class="text-xs font-bold text-white">${esc(r.name)}</span>
                    <span class="text-[10px] text-zinc-400 ml-1">${place}</span>
                </div>
            </div>`;
            }).join("")}
        </div>`;
        // The list element is re-created with the screen; bind once per element.
        if (el.getAttribute("data-ws-bound") !== "1") {
            el.setAttribute("data-ws-bound", "1");
            el.addEventListener("click", WeatherSearch._onResultClick);
        }
        el.style.display = "block";
    },

    _hideResults() {
        const el = document.getElementById("weather-search-results");
        if (el) { el.style.display = "none"; el.innerHTML = ""; }
    },

    async select(idx) {
        if (!Number.isInteger(idx)) return;
        const r = WeatherSearch._results[idx];
        if (!r || typeof r !== "object") return;
        // Coordinates go to Leaflet and to the backend — numbers only.
        const lat = Number(r.lat);
        const lon = Number(r.lon);
        if (!Number.isFinite(lat) || !Number.isFinite(lon)
            || Math.abs(lat) > 90 || Math.abs(lon) > 180) return;
        // A search still pending from the last keystroke (300 ms debounce)
        // would re-open the list under the field cleared below.
        clearTimeout(WeatherSearch._timer);
        WeatherSearch._hideResults();
        const input = document.getElementById("weather-search-input");
        if (input) input.value = "";

        // Move map + update city IMMEDIATELY (don't wait for backend).
        // textContent, never innerHTML: the name is geocoder data.
        const cityName = `${r.name == null ? "" : r.name}, ${r.country == null ? "" : r.country}`;
        const cityEl = document.getElementById("weather-city");
        if (cityEl) cityEl.textContent = cityName;
        if (window._weatherMap) {
            window._weatherMap.setView([lat, lon], 11);
            if (window._weatherMarker) window._weatherMarker.setLatLng([lat, lon]);
        }
        console.log("[WeatherSearch] Selected:", cityName, lat, lon);

        // Show loading state on weather data elements
        const condEl = document.getElementById("weather-condition");
        const tempEl = document.getElementById("weather-temp");
        if (condEl) condEl.textContent = "Loading...";
        if (tempEl) tempEl.textContent = "...";

        // Capture the current search_done marker so we can detect a new
        // one arriving via the WebSocket (indicating the backend fetch
        // completed — success or failure).
        const baseMarker = DataStore.get("weather_search_done", 0);

        // Tell backend to re-fetch weather for this location
        try {
            const resp = await fetch("/api/weather/location", {
                method: "POST",
                headers: {"Content-Type": "application/json"},
                body: JSON.stringify({lat, lon, city: cityName}),
            });
            const result = await resp.json();
            console.log("[WeatherSearch] location POST response:", result);
        } catch (e) { console.error("[WeatherSearch] location POST failed:", e); }

        // Reactive re-render: subscribe once to the weather_search_done
        // marker and re-render A4 as soon as the backend fires it. Keeps
        // a 10s hard fallback so the UI never stays stuck on "Loading..."
        // if the event never comes (network error, no API key, etc.).
        const handler = (value) => {
            if (value && value !== baseMarker) {
                DataStore.unsubscribe("weather_search_done", handler);
                if (App.getCurrentScreen() === "a4") App.navigateTo("a4");
            }
        };
        DataStore.subscribe("weather_search_done", handler);
        setTimeout(() => {
            DataStore.unsubscribe("weather_search_done", handler);
            if (App.getCurrentScreen() === "a4") App.navigateTo("a4");
        }, 10000);
    },
};
