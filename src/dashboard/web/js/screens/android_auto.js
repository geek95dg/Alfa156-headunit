/**
 * A2 Android Auto Screen — embedded kiosk mode.
 * Shows AA video stream in a card with BCM header+nav visible.
 * Falls back to connection placeholder when AA not active.
 */

App.registerScreen("a2", (() => {
    let _aaCheckInterval = null;

    function render(container, theme, data) {
        const t = App.t.bind(App);
        const bgCls = theme === "modern" ? "bg-slate-100 text-slate-900" : "bg-black text-white";
        const cardBorder = theme === "modern" ? "border-slate-200" : "border-zinc-800";
        const accentClr = theme === "autodelta" ? "text-[#FF5F00]" : theme === "modern" ? "text-blue-600" : "text-amber-500";

        container.innerHTML = `<div class="screen-container ${bgCls}">
            ${AppBar.render(theme, data)}
            <main class="content-area relative overflow-hidden">
                <!-- AA Stream (tries MJPEG from OpenAuto) -->
                <img id="aa-stream" src="/aa/stream" alt=""
                     class="absolute inset-0 w-full h-full object-contain z-0"
                     style="display:none;"
                     onload="this.style.display='block';document.getElementById('aa-placeholder').style.display='none';"
                     onerror="this.style.display='none';document.getElementById('aa-placeholder').style.display='flex';">

                <!-- Placeholder when AA not connected -->
                <div id="aa-placeholder" class="flex flex-col items-center justify-center h-full gap-6">
                    <div class="relative">
                        <span class="material-symbols-outlined text-8xl opacity-20">android</span>
                        <div class="absolute -bottom-1 -right-1 w-6 h-6 rounded-full ${theme==='modern'?'bg-slate-300':'bg-zinc-700'} flex items-center justify-center">
                            <span class="material-symbols-outlined text-sm opacity-60">link_off</span>
                        </div>
                    </div>
                    <div class="text-center">
                        <h2 class="text-2xl font-bold mb-2">${t("android_auto")}</h2>
                        <p class="opacity-50 text-sm max-w-md">${t("connect_aa")}</p>
                    </div>
                    <div class="flex gap-6 mt-4">
                        <div class="flex flex-col items-center gap-2 opacity-30">
                            <div class="w-16 h-16 rounded-2xl ${theme==='modern'?'bg-slate-200':'bg-zinc-800'} flex items-center justify-center">
                                <span class="material-symbols-outlined text-2xl">usb</span>
                            </div>
                            <span class="text-xs font-bold">USB-C</span>
                        </div>
                        <div class="flex flex-col items-center gap-2 opacity-30">
                            <div class="w-16 h-16 rounded-2xl ${theme==='modern'?'bg-slate-200':'bg-zinc-800'} flex items-center justify-center">
                                <span class="material-symbols-outlined text-2xl">wifi</span>
                            </div>
                            <span class="text-xs font-bold">WiFi</span>
                        </div>
                    </div>
                </div>
            </main>
            ${NavBar.render(theme, "a2")}
        </div>`;
    }

    return { render };
})());
