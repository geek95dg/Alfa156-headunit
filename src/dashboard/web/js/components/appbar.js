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
        return `<img src="/assets/alfa_logo.png" alt="Alfa Romeo" class="h-10 w-10 object-contain" style="${filterStyle}" onerror="this.parentElement.innerHTML='<span class=\\'text-sm font-bold\\'>AR</span>';">`;
    }

    function render(theme, data) {
        const time = _formatTime();
        const date = _formatDate();
        const temp = _formatTemp(data);
        const btClass = data.bt_connected ? "text-green-500" : "text-zinc-600";
        const btIcon = `<span class="material-symbols-outlined ${btClass}" style="font-size:16px;font-variation-settings:'FILL' ${data.bt_connected ? 1 : 0};">bluetooth</span>`;

        const bgColor = theme === "autodelta" ? "bg-[#111111] border-[#222222]"
            : "bg-black border-zinc-800";

        const timeColor = theme === "autodelta" ? "text-white" : theme === "modern" ? "text-white" : "text-zinc-400";
        const tempColor = theme === "autodelta" ? "text-[#FF5F00]" : theme === "modern" ? "text-white" : "text-zinc-500";

        return `<header class="w-full h-12 ${bgColor} border-b flex items-center px-4 shrink-0 z-50">
            <div class="flex items-center gap-2 w-[200px]">
                <span class="text-sm font-bold ${timeColor}" data-bind="time">${time}</span>
                <span class="text-[10px] font-bold text-zinc-600 uppercase" data-bind="date">${date}</span>
            </div>
            <div class="flex-1 flex justify-center">
                ${_logoImg(theme)}
            </div>
            <div class="flex items-center gap-3 w-[200px] justify-end">
                <span class="${tempColor} text-sm font-bold" data-bind="ext_temp">${temp}</span>
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
