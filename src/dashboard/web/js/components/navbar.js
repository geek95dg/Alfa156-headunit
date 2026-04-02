/**
 * Shared Bottom Navigation Bar — 7 screens (A1-A7).
 * Compact icons, no labels (to fit 7 items).
 */

const NavBar = (() => {
    const NAV_ITEMS = [
        { icon: "home", screen: "a1", tip: "Dashboard" },
        { icon: "android", screen: "a2", tip: "Android Auto" },
        { icon: "route", screen: "a3", tip: "Trip" },
        { icon: "cloud", screen: "a4", tip: "Weather" },
        { icon: "build", screen: "a5", tip: "Service" },
        { icon: "videocam", screen: "a6", tip: "DVR" },
        { icon: "speed", screen: "a7", tip: "Performance" },
        { icon: "call", screen: "a8", tip: "Phone" },
    ];

    function render(theme, activeScreen) {
        const activeIdx = NAV_ITEMS.findIndex(n => n.screen === activeScreen);

        if (theme === "heritage") return _render(activeIdx, "bg-zinc-950 border-zinc-800", "text-red-500", "text-zinc-500", "bg-red-950/30");
        if (theme === "modern") return _render(activeIdx, "bg-black border-zinc-800", "text-red-500", "text-zinc-400", "bg-red-600/20");
        if (theme === "autodelta") return _render(activeIdx, "bg-zinc-950 border-zinc-800", "text-red-500", "text-zinc-500", "bg-red-950/30");
        return _render(activeIdx, "bg-zinc-950 border-zinc-800", "text-red-500", "text-zinc-500", "bg-red-950/30");
    }

    function _render(activeIdx, barCls, activeColor, inactiveColor, activeBg) {
        const items = NAV_ITEMS.map((item, i) => {
            const isActive = i === activeIdx;
            const iconStyle = isActive ? "font-variation-settings:'FILL' 1;" : "";
            if (isActive) {
                return `<div class="flex items-center justify-center ${activeBg} ${activeColor} rounded-xl w-10 h-10 cursor-pointer transition-all"
                         title="${item.tip}" onclick="App.navigateTo('${item.screen}')">
                    <span class="material-symbols-outlined" style="font-size:22px;${iconStyle}">${item.icon}</span>
                </div>`;
            }
            return `<div class="flex items-center justify-center ${inactiveColor} w-10 h-10 cursor-pointer hover:text-zinc-300 transition-all"
                     title="${item.tip}" onclick="App.navigateTo('${item.screen}')">
                <span class="material-symbols-outlined" style="font-size:22px;">${item.icon}</span>
            </div>`;
        }).join("");

        return `<nav class="w-full z-50 flex justify-around items-center h-12 ${barCls} border-t shrink-0">
            ${items}
            <div class="flex items-center justify-center text-zinc-600 w-10 h-10 cursor-pointer hover:text-zinc-400 transition-all"
                 title="Settings" onclick="App.navigateTo('settings')">
                <span class="material-symbols-outlined" style="font-size:20px;">settings</span>
            </div>
        </nav>`;
    }

    return { render };
})();
