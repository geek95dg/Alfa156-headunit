/**
 * Shared Top App Bar — Alfa Romeo logo PNG center, time left, temp+icons right.
 *
 * Logo: uses single /assets/alfa_logo.png (black outline on transparent bg).
 * Per-theme CSS applies: invert for dark themes, tint via filter.
 * Place the black-outline Alfa Romeo logo PNG at:
 *   src/dashboard/web/assets/alfa_logo.png
 */

const AppBar = (() => {
    function _logoImg(theme) {
        // Single PNG, CSS-differentiated per theme
        let filterStyle = "";
        if (theme === "heritage") {
            // Invert to white, then tint amber
            filterStyle = "filter: invert(1) sepia(1) saturate(3) hue-rotate(15deg) brightness(1.1);";
        } else if (theme === "modern") {
            // Invert to white, slight red tint
            filterStyle = "filter: invert(1) sepia(0.3) saturate(2) hue-rotate(-20deg) brightness(1);";
        } else if (theme === "autodelta") {
            // Invert to white, orange tint
            filterStyle = "filter: invert(1) sepia(1) saturate(5) hue-rotate(-10deg) brightness(1.2);";
        }
        return `<img src="/assets/alfa_logo.png" alt="Alfa Romeo" class="h-12 w-auto object-contain" style="${filterStyle}" onerror="this.parentElement.innerHTML='<span class=\\'text-base font-bold\\'>AR</span>';">`;
    }

    function render(theme, data) {
        const time = _formatTime();
        const date = _formatDate();
        const temp = _formatTemp(data);
        const btClass = data.bt_connected ? "text-green-500" : "text-zinc-600";
        // Pixel bumps for 7" touchscreen (matches navbar): icons go
        // 16/24 → 19/28 px, fonts text-sm → text-base, height h-12 → h-14.
        const btIcon = `<span class="material-symbols-outlined ${btClass}" style="font-size:19px;font-variation-settings:'FILL' ${data.bt_connected ? 1 : 0};">bluetooth</span>`;

        const bgColor = theme === "autodelta" ? "bg-[#111111] border-[#222222]"
            : "bg-black border-zinc-800";

        const timeColor = theme === "autodelta" ? "text-white" : theme === "modern" ? "text-white" : "text-zinc-400";
        const tempColor = theme === "autodelta" ? "text-[#FF5F00]" : theme === "modern" ? "text-white" : "text-zinc-500";

        return `<header class="w-full h-14 ${bgColor} border-b flex items-center px-4 shrink-0 z-50">
            <div class="flex items-center gap-2 w-[220px]">
                <span class="text-base font-bold ${timeColor}" data-bind="time">${time}</span>
                <span class="text-xs font-bold text-zinc-600 uppercase" data-bind="date">${date}</span>
            </div>
            <div class="flex-1 flex justify-center">
                ${_logoImg(theme)}
            </div>
            <div class="flex items-center gap-4 w-[220px] justify-end">
                <span class="${tempColor} text-base font-bold" data-bind="ext_temp">${temp}</span>
                ${btIcon}
                <span class="material-symbols-outlined text-zinc-600 cursor-pointer hover:text-zinc-400 p-1" style="font-size:28px;" onclick="App.navigateTo('audio')">equalizer</span>
                <span class="material-symbols-outlined text-zinc-600 cursor-pointer hover:text-zinc-400 p-1" style="font-size:28px;" onclick="App.navigateTo('settings')">settings</span>
            </div>
        </header>`;
    }

    function _formatTime() {
        const now = new Date();
        return now.toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit", hour12: false });
    }

    function _formatDate() {
        const now = new Date();
        const dayKeys = ["sun","mon","tue","wed","thu","fri","sat"];
        const monthKeys = ["jan","feb","mar","apr","may","jun","jul","aug","sep","oct","nov","dec"];
        const day = (App && App.t) ? App.t(dayKeys[now.getDay()]) : dayKeys[now.getDay()].toUpperCase();
        const month = (App && App.t) ? App.t(monthKeys[now.getMonth()]) : monthKeys[now.getMonth()].toUpperCase();
        return `${day} ${month} ${now.getDate()}`;
    }

    function _formatTemp(data) {
        const temp = data.ext_temp;
        if (temp == null) return "--";
        const unit = (App && App.getConfig().temp_unit) || "C";
        if (unit === "F") return `${Math.round(temp * 9/5 + 32)}\u00b0F`;
        return `${Math.round(temp)}\u00b0C`;
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
