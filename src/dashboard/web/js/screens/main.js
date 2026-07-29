/**
 * A1 Main Screen — music-centric hub (now-playing card + volume + spectrum).
 *
 * Trimmed for the quick-start build: the engine-temp / fuel / oil-pressure /
 * avg-speed / voltage tiles are gone (those modules are off and only rendered
 * zeros). A1 is now the large media card + a tappable equalizer strip, in all
 * three themes.
 */

App.registerScreen("a1", (() => {
    function render(container, theme, data) {
        if (theme === "modern") container.innerHTML = _renderModern(data);
        else if (theme === "autodelta") container.innerHTML = _renderAutodelta(data);
        else container.innerHTML = _renderHeritage(data);
    }

    function update(data, theme) {
        // Media now-playing — live refresh every tick (no full re-render).
        // This fixes the old bug where track info only updated after switching
        // screens (main.js looked for id="media-info" which never existed).
        _updateEl("media-title", data.bt_media_title || "No Media");
        _updateEl("media-artist", data.bt_media_artist || "---");
        _updateEl("media-playpause", data.bt_media_playing ? "pause" : "play_arrow");
        _updateEl("media-mute-icon", data.audio_muted ? "volume_off" : "volume_up");

        // Volume slider — reflect backend level, but don't fight the user
        // while they're dragging it.
        const volEl = document.getElementById("media-volume");
        if (volEl && document.activeElement !== volEl && data.audio_volume != null) {
            volEl.value = data.audio_volume;
        }

        // Spectrum visualizer
        const canvas = document.getElementById("spectrum-canvas");
        if (canvas && data.audio_spectrum) {
            _drawSpectrum(canvas, data.audio_spectrum, theme);
        }
    }

    function _updateEl(id, text) {
        const el = document.getElementById(id);
        if (el && el.textContent !== text) el.textContent = text;
    }

    // Equalizer strip shown under the media card. `tk` supplies theme classes.
    function _eqStrip(tk) {
        return `<div class="rounded-xl border p-3 cursor-pointer ${tk.card}" onclick="App.navigateTo('audio')">
            <div class="flex items-center justify-between mb-1">
                <span class="text-[9px] font-bold uppercase tracking-wider ${tk.label}">Equalizer</span>
                <span class="material-symbols-outlined ${tk.eqIcon}" style="font-size:16px">equalizer</span>
            </div>
            <canvas id="spectrum-canvas" class="w-full" style="height:44px"></canvas>
        </div>`;
    }

    function _renderHeritage(data) {
        return `<div class="screen-container bg-black text-zinc-100">
            ${AppBar.render("heritage", data)}
            <main class="content-area flex items-center justify-center overflow-hidden px-6 py-4">
                <div class="w-full max-w-2xl flex flex-col gap-4">
                    ${MediaPlayer.renderHeritage(data)}
                    ${_eqStrip({ card: "border-zinc-800 bg-zinc-900/30", label: "text-zinc-500", eqIcon: "text-zinc-600" })}
                </div>
            </main>
            ${NavBar.render("heritage", "a1")}
        </div>`;
    }

    function _renderModern(data) {
        return `<div class="screen-container text-slate-900">
            ${AppBar.render("modern", data)}
            <main class="content-area flex items-center justify-center overflow-hidden px-6 py-4 bg-gradient-to-br from-slate-50 to-blue-50/30">
                <div class="w-full max-w-2xl flex flex-col gap-4">
                    ${MediaPlayer.renderModern(data)}
                    ${_eqStrip({ card: "border-slate-100 bg-white shadow-sm", label: "text-slate-400", eqIcon: "text-blue-400" })}
                </div>
            </main>
            ${NavBar.render("modern", "a1")}
        </div>`;
    }

    function _renderAutodelta(data) {
        return `<div class="screen-container bg-black text-white">
            ${AppBar.render("autodelta", data)}
            <main class="content-area flex items-center justify-center overflow-hidden px-6 py-4">
                <div class="w-full max-w-2xl flex flex-col gap-4">
                    ${MediaPlayer.renderAutodelta(data)}
                    ${_eqStrip({ card: "border-[#222222]", label: "text-gray-500", eqIcon: "text-[#FF5F00]" })}
                </div>
            </main>
            ${NavBar.render("autodelta", "a1")}
        </div>`;
    }

    function _drawSpectrum(canvas, bands, theme) {
        const ctx = canvas.getContext("2d");
        if (!ctx) return;
        const dpr = window.devicePixelRatio || 1;
        const w = canvas.clientWidth;
        const h = canvas.clientHeight;
        if (canvas.width !== w * dpr || canvas.height !== h * dpr) {
            canvas.width = w * dpr;
            canvas.height = h * dpr;
            ctx.scale(dpr, dpr);
        }
        ctx.clearRect(0, 0, w, h);

        const n = bands.length;
        const gap = 2;
        const barW = Math.max(2, (w - gap * (n + 1)) / n);
        const colors = {
            heritage: ["#f59e0b", "#d97706"],
            modern: ["#3b82f6", "#1d4ed8"],
            autodelta: ["#FF5F00", "#ec5b13"],
        };
        const [c1, c2] = colors[theme] || colors.heritage;

        for (let i = 0; i < n; i++) {
            const val = Math.max(0, Math.min(1, bands[i]));
            const barH = val * (h - 4);
            const x = gap + i * (barW + gap);
            const y = h - barH;
            const grad = ctx.createLinearGradient(x, y, x, h);
            grad.addColorStop(0, c1);
            grad.addColorStop(1, c2);
            ctx.fillStyle = grad;
            ctx.beginPath();
            ctx.roundRect(x, y, barW, barH, 1.5);
            ctx.fill();
        }
    }

    return { render, update };
})());
