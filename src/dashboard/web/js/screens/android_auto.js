/**
 * A2 Android Auto Screen — kiosk embed with BCM header + nav.
 * MJPEG stream fills content area between AppBar and NavBar.
 * Touch events forwarded to Xvfb via xdotool.
 *
 * NOTE: On x86/VM, AA is streamed via MJPEG from Xvfb — quality is limited.
 * On Orange Pi hardware, OpenAuto renders natively via SDL2/EGL to HDMI-2
 * at full quality without MJPEG overhead.
 */

App.registerScreen("a2", (() => {
    function render(container, theme, data) {
        const t = App.t.bind(App);
        const bgCls = theme === "modern" ? "bg-slate-100 text-slate-900" : "bg-black text-white";
        const aaStatus = data.aa_status || "unavailable";
        const isFailed = aaStatus === "failed" || aaStatus === "error";
        const isUnavailable = aaStatus === "unavailable";
        const isRestarting = aaStatus === "restarting";

        // Status badge for header
        let statusBadge = "";
        if (isFailed) {
            statusBadge = `<div class="absolute top-16 left-1/2 -translate-x-1/2 z-20 bg-red-600/90 text-white text-xs font-bold px-4 py-1.5 rounded-full">AA Service Failed</div>`;
        } else if (isRestarting) {
            statusBadge = `<div class="absolute top-16 left-1/2 -translate-x-1/2 z-20 bg-amber-600/90 text-white text-xs font-bold px-4 py-1.5 rounded-full animate-pulse">Restarting...</div>`;
        }

        // Placeholder message varies by status
        let placeholderMsg = t("connect_aa");
        let placeholderIcon = "link_off";
        if (isUnavailable) {
            placeholderMsg = "OpenAuto not installed";
            placeholderIcon = "block";
        } else if (isFailed) {
            placeholderMsg = "Android Auto service failed. Check logs or restart.";
            placeholderIcon = "error";
        } else if (isRestarting) {
            placeholderMsg = "Android Auto is restarting...";
            placeholderIcon = "sync";
        }

        container.innerHTML = `<div class="screen-container ${bgCls}">
            ${AppBar.render(theme, data)}
            <main class="content-area relative overflow-hidden bg-black">
                ${statusBadge}
                <!-- AA Stream — fills content area between header and nav.
                     object-cover prevents the letterboxed right/bottom
                     black bars that appeared with the previous object-fill
                     when the AA canvas aspect didn't match the panel. -->
                <img id="aa-stream" src="/aa/stream" alt=""
                     class="absolute inset-0 w-full h-full object-cover z-0"
                     style="display:none;"
                     onload="this.style.display='block';document.getElementById('aa-placeholder').style.display='none';document.getElementById('aa-touch-overlay').style.display='block';"
                     onerror="this.style.display='none';document.getElementById('aa-placeholder').style.display='flex';document.getElementById('aa-touch-overlay').style.display='none';">

                <!-- Touch overlay — captures clicks and forwards to OpenAuto -->
                <div id="aa-touch-overlay" class="absolute inset-0 z-10"
                     onclick="AATouch.click(event)"
                     ontouchstart="AATouch.touch(event)"
                     style="display:none;"></div>

                <!-- Placeholder when AA not connected -->
                <div id="aa-placeholder" class="flex flex-col items-center justify-center h-full gap-6">
                    <div class="relative">
                        <span class="material-symbols-outlined text-8xl opacity-20">android</span>
                        <div class="absolute -bottom-1 -right-1 w-6 h-6 rounded-full ${theme==='modern'?'bg-slate-300':'bg-zinc-700'} flex items-center justify-center">
                            <span class="material-symbols-outlined text-sm opacity-60">${placeholderIcon}</span>
                        </div>
                    </div>
                    <div class="text-center">
                        <h2 class="text-2xl font-bold mb-2">${t("android_auto")}</h2>
                        <p class="opacity-50 text-sm max-w-md">${placeholderMsg}</p>
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
