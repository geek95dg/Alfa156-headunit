/**
 * A2 Android Auto Screen — fullscreen kiosk mode with touch forwarding.
 * Stream fills entire content area. Touch events forwarded to Xvfb via xdotool.
 * Small floating "Back" button to return to BCM navigation.
 */

App.registerScreen("a2", (() => {
    function render(container, theme, data) {
        const t = App.t.bind(App);
        const bgCls = "bg-black text-white";

        // Kiosk mode: no AppBar, no NavBar — fullscreen AA
        container.innerHTML = `<div class="screen-container ${bgCls}">
            <main class="relative w-full h-full overflow-hidden">
                <!-- AA Stream — fullscreen -->
                <img id="aa-stream" src="/aa/stream" alt=""
                     class="absolute inset-0 w-full h-full object-fill z-0"
                     style="display:none;"
                     onload="this.style.display='block';document.getElementById('aa-placeholder').style.display='none';"
                     onerror="this.style.display='none';document.getElementById('aa-placeholder').style.display='flex';">

                <!-- Touch overlay — captures clicks and forwards to OpenAuto -->
                <div id="aa-touch-overlay" class="absolute inset-0 z-10"
                     onclick="AATouch.click(event)"
                     ontouchstart="AATouch.touch(event)"
                     style="display:none;"></div>

                <!-- Placeholder when AA not connected -->
                <div id="aa-placeholder" class="flex flex-col items-center justify-center h-full gap-6">
                    <div class="relative">
                        <span class="material-symbols-outlined text-8xl opacity-20">android</span>
                        <div class="absolute -bottom-1 -right-1 w-6 h-6 rounded-full bg-zinc-700 flex items-center justify-center">
                            <span class="material-symbols-outlined text-sm opacity-60">link_off</span>
                        </div>
                    </div>
                    <div class="text-center">
                        <h2 class="text-2xl font-bold mb-2">${t("android_auto")}</h2>
                        <p class="opacity-50 text-sm max-w-md">${t("connect_aa")}</p>
                    </div>
                    <div class="flex gap-6 mt-4">
                        <div class="flex flex-col items-center gap-2 opacity-30">
                            <div class="w-16 h-16 rounded-2xl bg-zinc-800 flex items-center justify-center">
                                <span class="material-symbols-outlined text-2xl">usb</span>
                            </div>
                            <span class="text-xs font-bold">USB-C</span>
                        </div>
                        <div class="flex flex-col items-center gap-2 opacity-30">
                            <div class="w-16 h-16 rounded-2xl bg-zinc-800 flex items-center justify-center">
                                <span class="material-symbols-outlined text-2xl">wifi</span>
                            </div>
                            <span class="text-xs font-bold">WiFi</span>
                        </div>
                    </div>
                </div>

                <!-- Floating back button (always visible) -->
                <button class="absolute top-3 left-3 z-20 w-10 h-10 rounded-full bg-black/60 backdrop-blur text-white flex items-center justify-center hover:bg-black/80 transition-all border border-white/10"
                        onclick="App.navigateTo('a1')" title="Back to BCM">
                    <span class="material-symbols-outlined" style="font-size:20px;">arrow_back</span>
                </button>
            </main>
        </div>`;

        // Enable touch overlay when stream loads
        const img = document.getElementById("aa-stream");
        if (img) {
            img.addEventListener("load", () => {
                const overlay = document.getElementById("aa-touch-overlay");
                if (overlay) overlay.style.display = "block";
            });
        }
    }

    return { render };
})());

// AA Touch forwarding — translates browser clicks to Xvfb coordinates
const AATouch = {
    async click(e) {
        const rect = e.currentTarget.getBoundingClientRect();
        const relX = (e.clientX - rect.left) / rect.width;
        const relY = (e.clientY - rect.top) / rect.height;
        AATouch._send(relX, relY);
    },
    async touch(e) {
        if (e.touches && e.touches.length > 0) {
            e.preventDefault();
            const rect = e.currentTarget.getBoundingClientRect();
            const t = e.touches[0];
            const relX = (t.clientX - rect.left) / rect.width;
            const relY = (t.clientY - rect.top) / rect.height;
            AATouch._send(relX, relY);
        }
    },
    async _send(relX, relY) {
        try {
            await fetch("/aa/touch", {
                method: "POST",
                headers: {"Content-Type": "application/json"},
                body: JSON.stringify({x: relX, y: relY}),
            });
        } catch (e) {}
    },
};
