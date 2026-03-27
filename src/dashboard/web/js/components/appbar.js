/**
 * Shared Top App Bar component — renders differently per theme.
 */

const AppBar = (() => {
    function render(theme, data) {
        const time = _formatTime();
        const date = _formatDate();
        const temp = _formatTemp(data);
        const btIcon = data.bt_connected
            ? '<span class="material-symbols-outlined" style="font-variation-settings:\'FILL\' 1;">bluetooth_connected</span>'
            : '<span class="material-symbols-outlined">bluetooth</span>';
        const lteIcon = data.lte_connected
            ? '<span class="material-symbols-outlined">smartphone</span>'
            : '';

        if (theme === "heritage") return _renderHeritage(time, date, temp, btIcon, lteIcon);
        if (theme === "modern") return _renderModern(time, date, temp, btIcon, lteIcon);
        if (theme === "autodelta") return _renderAutodelta(time, date, temp, btIcon, lteIcon, data);
        return _renderHeritage(time, date, temp, btIcon, lteIcon);
    }

    function _renderHeritage(time, date, temp, btIcon, lteIcon) {
        return `<header class="w-full h-12 bg-black border-b border-zinc-800 flex justify-between items-center px-6 shrink-0 z-50">
            <div class="flex items-center gap-4">
                <span class="font-sans tracking-tight text-sm font-bold text-zinc-400" data-bind="time">${time}</span>
                <span class="font-sans tracking-tight text-sm font-bold text-zinc-500" data-bind="date">${date}</span>
            </div>
            <div class="flex items-center gap-2">
                <span class="text-red-600 font-black tracking-widest text-lg uppercase">Alfa Romeo</span>
            </div>
            <div class="flex items-center gap-4">
                <span class="text-zinc-500 font-sans text-sm font-bold" data-bind="ext_temp">${temp}</span>
                <span class="text-red-600 text-xl">${btIcon}</span>
                <span class="material-symbols-outlined text-zinc-600 text-xl cursor-pointer hover:text-zinc-400 transition-colors" onclick="App.navigateTo('settings')" title="Settings">settings</span>
            </div>
        </header>`;
    }

    function _renderModern(time, date, temp, btIcon, lteIcon) {
        return `<header class="w-full h-12 bg-black border-b border-zinc-800 flex justify-between items-center px-6 shrink-0 z-50">
            <div class="flex items-center gap-4 text-zinc-400">
                <span class="font-bold text-white text-sm" data-bind="time">${time}</span>
                <span class="text-[10px] uppercase font-bold" data-bind="date">${date}</span>
            </div>
            <div class="absolute left-1/2 -translate-x-1/2 flex items-center gap-2">
                <span class="font-bold italic text-red-600 text-lg tracking-tighter">Alfa Romeo</span>
            </div>
            <div class="flex items-center gap-4">
                <div class="flex items-center gap-1 text-white">
                    <span class="text-sm font-bold" data-bind="ext_temp">${temp}</span>
                </div>
                <div class="flex items-center gap-3 text-zinc-500">
                    ${lteIcon}
                    <span class="text-red-600">${btIcon}</span>
                    <span class="material-symbols-outlined text-zinc-600 text-xl cursor-pointer hover:text-zinc-400 transition-colors" onclick="App.navigateTo('settings')" title="Settings">settings</span>
                </div>
            </div>
        </header>`;
    }

    function _renderAutodelta(time, date, temp, btIcon, lteIcon, data) {
        return `<header class="w-full h-12 bg-[#111111] border-b border-[#222222] flex justify-between items-center px-6 shrink-0 z-50">
            <div class="flex flex-col">
                <span class="text-xl font-bold text-white tracking-wider" data-bind="time">${time}</span>
                <span class="text-sm text-gray-400 font-medium" data-bind="date">${date}</span>
            </div>
            <div class="flex-1 flex justify-center items-center">
                <div class="w-12 h-12 rounded-full border-2 border-[#FF5F00] flex items-center justify-center bg-black shadow-[0_0_15px_rgba(236,91,19,0.3)]">
                    <span class="text-[#FF5F00] font-bold text-lg tracking-tighter">AR</span>
                </div>
            </div>
            <div class="flex items-center gap-4">
                <div class="flex gap-2 text-gray-400">
                    ${btIcon}
                    ${lteIcon}
                    <span class="material-symbols-outlined text-zinc-600 text-xl cursor-pointer hover:text-zinc-400 transition-colors" onclick="App.navigateTo('settings')" title="Settings">settings</span>
                </div>
                <div class="flex flex-col items-end border-l border-[#333333] pl-4">
                    <span class="text-xl font-bold text-white" data-bind="ext_temp">${temp}</span>
                    <span class="text-xs text-gray-400">EXT</span>
                </div>
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
        return `${days[now.getDay()]}, ${months[now.getMonth()]} ${now.getDate()}`;
    }

    function _formatTemp(data) {
        const temp = data.ext_temp;
        if (temp == null) return "--";
        const unit = (App && App.getConfig().temp_unit) || "C";
        if (unit === "F") return `${Math.round(temp * 9/5 + 32)}°F`;
        return `${Math.round(temp)}°C`;
    }

    /** Update dynamic fields in the appbar */
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
