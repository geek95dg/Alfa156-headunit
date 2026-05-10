/**
 * Shared Bottom Navigation Bar — 7 screens (A1-A7).
 * Compact icons, no labels (to fit 7 items).
 */

const NavBar = (() => {
    const NAV_ITEMS = [
        { icon: "home", screen: "a1", tip: "Dashboard" },
        { icon: "android", screen: "a2", tip: "Android Auto", requiresAA: true },
        { icon: "call", screen: "a8", tip: "Phone", requiresBT: true },
        { icon: "route", screen: "a3", tip: "Trip" },
        { icon: "cloud", screen: "a4", tip: "Weather" },
        { icon: "build", screen: "a5", tip: "Service" },
        { icon: "videocam", screen: "a6", tip: "DVR" },
        { icon: "speed", screen: "a7", tip: "Performance" },
    ];

    function render(theme, activeScreen) {
        const activeIdx = NAV_ITEMS.findIndex(n => n.screen === activeScreen);

        if (theme === "heritage") return _render(activeIdx, "bg-zinc-950 border-zinc-800", "text-red-500", "text-zinc-500", "bg-red-950/30");
        if (theme === "modern") return _render(activeIdx, "bg-black border-zinc-800", "text-red-500", "text-zinc-400", "bg-red-600/20");
        if (theme === "autodelta") return _render(activeIdx, "bg-zinc-950 border-zinc-800", "text-red-500", "text-zinc-500", "bg-red-950/30");
        return _render(activeIdx, "bg-zinc-950 border-zinc-800", "text-red-500", "text-zinc-500", "bg-red-950/30");
    }

    function _render(activeIdx, barCls, activeColor, inactiveColor, activeBg) {
        const data = DataStore.getAll();
        const aaAvailable = data.aa_available || data.aa_status === "running" || data.aa_status === "connected";
        const btAvailable = data.bt_available || data.bt_connected;

        const items = NAV_ITEMS.map((item, i) => {
            const isActive = i === activeIdx;
            // Dim items that require unavailable features
            const isDisabled = (item.requiresAA && !aaAvailable) || (item.requiresBT && !btAvailable);
            const iconStyle = isActive ? "font-variation-settings:'FILL' 1;" : "";

            if (isDisabled && !isActive) {
                return `<div class="flex items-center justify-center text-zinc-500 w-12 h-12 cursor-pointer opacity-50 transition-all"
                         title="${item.tip} (unavailable)" onclick="App.navigateTo('${item.screen}')">
                    <span class="material-symbols-outlined" style="font-size:26px;">${item.icon}</span>
                </div>`;
            }
            if (isActive) {
                return `<div class="flex items-center justify-center ${activeBg} ${activeColor} rounded-xl w-12 h-12 cursor-pointer transition-all"
                         title="${item.tip}" onclick="App.navigateTo('${item.screen}')">
                    <span class="material-symbols-outlined" style="font-size:26px;${iconStyle}">${item.icon}</span>
                </div>`;
            }
            return `<div class="flex items-center justify-center ${inactiveColor} w-12 h-12 cursor-pointer hover:text-zinc-300 transition-all"
                     title="${item.tip}" onclick="App.navigateTo('${item.screen}')">
                <span class="material-symbols-outlined" style="font-size:26px;">${item.icon}</span>
            </div>`;
        }).join("");

        // Autohiding floating navbar — anchored to the bottom of the
        // viewport, hidden by translateY(100%) until the user swipes up
        // from the bottom edge. App.showNavBar()/hideNavBar() toggle the
        // .bcm-navbar-shown class. Floating so it doesn't steal vertical
        // space from content-area on any screen.
        return `<nav id="bcm-navbar"
            class="bcm-navbar absolute bottom-0 left-0 right-0 z-50 flex justify-around items-center h-12 ${barCls} border-t"
            ontouchstart="App.kickNavBar(true)"
            onmouseenter="App.kickNavBar(true)"
            onmouseleave="App.kickNavBar(false)">
            ${items}
            <div class="flex items-center justify-center text-zinc-600 w-12 h-12 cursor-pointer hover:text-zinc-400 transition-all"
                 title="Settings" onclick="App.navigateTo('settings')">
                <span class="material-symbols-outlined" style="font-size:24px;">settings</span>
            </div>
        </nav>`;
    }

    return { render };
})();
