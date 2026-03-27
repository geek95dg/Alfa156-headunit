/**
 * Shared Bottom Navigation Bar component.
 */

const NavBar = (() => {
    const NAV_ITEMS = [
        { id: "a1", icon: "home", label: "Home", screen: "a1" },
        { id: "a2", icon: "directions_car", label: "Drive", screen: "a2" },
        { id: "a3", icon: "cloud", label: "Climate", screen: "a3" },
        { id: "a4", icon: "build", label: "Service", screen: "a4" },
    ];

    function render(theme, activeScreen) {
        const activeIdx = NAV_ITEMS.findIndex(n => n.screen === activeScreen);

        if (theme === "heritage") return _renderHeritage(activeIdx);
        if (theme === "modern") return _renderModern(activeIdx);
        if (theme === "autodelta") return _renderAutodelta(activeIdx);
        return _renderHeritage(activeIdx);
    }

    function _renderHeritage(activeIdx) {
        const items = NAV_ITEMS.map((item, i) => {
            const isActive = i === activeIdx;
            const cls = isActive
                ? "flex flex-col items-center justify-center text-red-500 scale-110 transition-transform p-2 rounded-lg"
                : "flex flex-col items-center justify-center text-zinc-500 p-2 rounded-lg transition-all hover:text-zinc-300";
            const fill = isActive ? "font-variation-settings: 'FILL' 1;" : "";
            return `<a class="${cls}" href="#" data-nav="${item.screen}" onclick="event.preventDefault(); App.navigateTo('${item.screen}')">
                <span class="material-symbols-outlined text-2xl" style="${fill}">${item.icon}</span>
                <span class="text-[10px] font-bold uppercase mt-1">${item.label}</span>
            </a>`;
        }).join("");

        return `<nav class="w-full z-50 flex justify-around items-center h-20 pb-2 bg-zinc-950 border-t border-zinc-800 shadow-2xl shrink-0">
            ${items}
        </nav>`;
    }

    function _renderModern(activeIdx) {
        const items = NAV_ITEMS.map((item, i) => {
            const isActive = i === activeIdx;
            const cls = isActive
                ? "flex items-center justify-center bg-red-600/20 text-red-500 rounded-xl w-16 h-12 active:scale-95 transition-transform cursor-pointer"
                : "flex items-center justify-center text-zinc-400 w-16 h-12 active:scale-95 transition-transform cursor-pointer";
            const fill = isActive ? "font-variation-settings: 'FILL' 1;" : "";
            return `<div class="${cls}" data-nav="${item.screen}" onclick="App.navigateTo('${item.screen}')">
                <span class="material-symbols-outlined" style="${fill}">${item.icon}</span>
            </div>`;
        }).join("");

        return `<nav class="w-full h-16 z-50 flex justify-around items-center px-4 bg-black border-t border-zinc-800 shrink-0">
            ${items}
        </nav>`;
    }

    function _renderAutodelta(activeIdx) {
        const items = NAV_ITEMS.map((item, i) => {
            const isActive = i === activeIdx;
            const cls = isActive
                ? "flex items-center justify-center bg-red-950/30 text-red-500 rounded-xl w-16 h-12 active:bg-zinc-800 transition-opacity cursor-pointer"
                : "flex items-center justify-center text-zinc-500 w-16 h-12 active:bg-zinc-800 transition-opacity cursor-pointer";
            const fill = isActive ? "font-variation-settings: 'FILL' 1;" : "";
            return `<div class="${cls}" data-nav="${item.screen}" onclick="App.navigateTo('${item.screen}')">
                <span class="material-symbols-outlined" style="${fill}">${item.icon}</span>
            </div>`;
        }).join("");

        return `<nav class="w-full z-50 flex justify-around items-center pb-2 bg-zinc-950 h-16 border-t border-zinc-800 shrink-0">
            ${items}
        </nav>`;
    }

    return { render };
})();
