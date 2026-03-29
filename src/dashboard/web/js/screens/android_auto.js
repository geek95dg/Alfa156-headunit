/**
 * A2 Android Auto Screen — embedded kiosk mode.
 * Full implementation in Phase 4.
 */

App.registerScreen("a2", (() => {
    function render(container, theme, data) {
        const t = App.t.bind(App);
        const bgCls = theme === "modern" ? "bg-slate-100 text-slate-900" : "bg-black text-white";
        const cardBg = theme === "modern" ? "bg-white border-slate-200" : "bg-zinc-900 border-zinc-800";

        container.innerHTML = `<div class="screen-container ${bgCls}">
            ${AppBar.render(theme, data)}
            <main class="content-area flex items-center justify-center p-4">
                <div class="${cardBg} border rounded-2xl p-8 flex flex-col items-center gap-6 max-w-lg w-full">
                    <span class="material-symbols-outlined text-6xl opacity-30">android</span>
                    <h2 class="text-2xl font-bold">${t("android_auto")}</h2>
                    <p class="text-center opacity-60">${t("connect_aa", "Connect your phone via USB or WiFi to start Android Auto")}</p>
                    <div class="flex gap-4 opacity-40">
                        <div class="flex items-center gap-2">
                            <span class="material-symbols-outlined">usb</span>
                            <span class="text-sm">USB-C</span>
                        </div>
                        <div class="flex items-center gap-2">
                            <span class="material-symbols-outlined">wifi</span>
                            <span class="text-sm">WiFi</span>
                        </div>
                    </div>
                </div>
            </main>
            ${NavBar.render(theme, "a2")}
        </div>`;
    }

    return { render };
})());
