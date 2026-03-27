/**
 * Shared Top App Bar — Alfa Romeo logo (PNG per theme), time, temp, icons.
 * Logo files expected at:
 *   /assets/logo_heritage.png  (color logo on dark/transparent bg)
 *   /assets/logo_modern.png    (black outline on white/transparent bg)
 *   /assets/logo_autodelta.png (white logo on black/transparent bg)
 *   Falls back to SVG if PNG not found.
 */

const AppBar = (() => {
    function _logoHtml(theme) {
        const file = `/assets/logo_${theme}.png`;
        const fallback = `/assets/alfa_romeo_logo.svg`;
        return `<img src="${file}" alt="Alfa Romeo" class="h-9 w-9 object-contain"
                     onerror="this.onerror=null;this.src='${fallback}';this.style.color='var(--color-primary)';">`;
    }

    function render(theme, data) {
        const time = _formatTime();
        const date = _formatDate();
        const temp = _formatTemp(data);
        const btClass = data.bt_connected ? "text-green-500" : "text-zinc-600";
        const btIcon = `<span class="material-symbols-outlined ${btClass}" style="font-size:16px;font-variation-settings:'FILL' ${data.bt_connected ? 1 : 0};">bluetooth</span>`;

        if (theme === "heritage") return _renderHeritage(time, date, temp, btIcon);
        if (theme === "modern") return _renderModern(time, date, temp, btIcon);
        if (theme === "autodelta") return _renderAutodelta(time, date, temp, btIcon);
        return _renderHeritage(time, date, temp, btIcon);
    }

    function _renderHeritage(time, date, temp, btIcon) {
        return `<header class="w-full h-12 bg-black border-b border-zinc-800 flex items-center px-4 shrink-0 z-50">
            <div class="flex items-center gap-2 w-[200px]">
                <span class="text-sm font-bold text-zinc-400" data-bind="time">${time}</span>
                <span class="text-[10px] font-bold text-zinc-600 uppercase" data-bind="date">${date}</span>
            </div>
            <div class="flex-1 flex justify-center">
                ${_logoHtml("heritage")}
            </div>
            <div class="flex items-center gap-3 w-[200px] justify-end">
                <span class="text-zinc-500 text-sm font-bold" data-bind="ext_temp">${temp}</span>
                ${btIcon}
                <span class="material-symbols-outlined text-zinc-600 text-[18px] cursor-pointer hover:text-zinc-400" onclick="App.navigateTo('settings')">settings</span>
            </div>
        </header>`;
    }

    function _renderModern(time, date, temp, btIcon) {
        return `<header class="w-full h-12 bg-black border-b border-zinc-800 flex items-center px-4 shrink-0 z-50">
            <div class="flex items-center gap-2 w-[200px] text-zinc-400">
                <span class="font-bold text-white text-sm" data-bind="time">${time}</span>
                <span class="text-[10px] uppercase font-bold" data-bind="date">${date}</span>
            </div>
            <div class="flex-1 flex justify-center">
                ${_logoHtml("modern")}
            </div>
            <div class="flex items-center gap-3 w-[200px] justify-end">
                <span class="text-sm font-bold text-white" data-bind="ext_temp">${temp}</span>
                ${btIcon}
                <span class="material-symbols-outlined text-zinc-600 text-[18px] cursor-pointer hover:text-zinc-400" onclick="App.navigateTo('settings')">settings</span>
            </div>
        </header>`;
    }

    function _renderAutodelta(time, date, temp, btIcon) {
        return `<header class="w-full h-12 bg-[#111111] border-b border-[#222222] flex items-center px-4 shrink-0 z-50">
            <div class="flex items-center gap-2 w-[200px]">
                <span class="text-sm font-bold text-white tracking-wider" data-bind="time">${time}</span>
                <span class="text-[10px] text-gray-500 font-medium uppercase" data-bind="date">${date}</span>
            </div>
            <div class="flex-1 flex justify-center">
                ${_logoHtml("autodelta")}
            </div>
            <div class="flex items-center gap-3 w-[200px] justify-end">
                <span class="text-sm font-bold text-[#FF5F00]" data-bind="ext_temp">${temp}</span>
                ${btIcon}
                <span class="material-symbols-outlined text-zinc-600 text-[18px] cursor-pointer hover:text-zinc-400" onclick="App.navigateTo('settings')">settings</span>
            </div>
        </header>`;
    }

    function _formatTime() {
        const now = new Date();
        return now.toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit", hour12: false });
    }

    function _formatDate() {
        const now = new Date();
        const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
        const days = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
        return `${days[now.getDay()]} ${months[now.getMonth()]} ${now.getDate()}`;
    }

    function _formatTemp(data) {
        const temp = data.ext_temp;
        if (temp == null) return "--";
        const unit = (App && App.getConfig().temp_unit) || "C";
        if (unit === "F") return `${Math.round(temp * 9/5 + 32)}°F`;
        return `${Math.round(temp)}°C`;
    }

    function update(container, data) {
        const timeEl = container.querySelector('[data-bind="time"]');
        const dateEl = container.querySelector('[data-bind="date"]');
        const tempEl = container.querySelector('[data-bind="ext_temp"]');
        if (timeEl) timeEl.textContent = _formatTime();
        if (dateEl) dateEl.textContent = _formatDate();
        if (tempEl) tempEl.textContent = _formatTemp(data);
    }

    return { render, update };
})();
