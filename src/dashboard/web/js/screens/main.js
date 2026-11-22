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

        // Spectrum visualizer: the payload (15 Hz) only sets the TARGET; the
        // requestAnimationFrame loop below eases the bars toward it, so the
        // strip moves smoothly at the display rate instead of jumping.
        _spectrum.setTarget(data.audio_spectrum);
    }

    function unmount() {
        _spectrum.stop();
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

    // ── Spectrum strip renderer ────────────────────────────────────────────
    // Data: data.audio_spectrum = 16 levels 0..1 from src/audio/spectrum.py,
    // already in dBFS and smoothed there; zeros = silence. Here:
    //  - keep the last frame as the target and ease toward it every animation
    //    frame (fast up, slower down), with falling peak-hold caps;
    //  - a 2 px baseline per band, so silence still shows a live strip
    //    instead of an empty box;
    //  - the loop runs only while the canvas is on screen and something still
    //    moves; leaving A1 (unmount) or a re-render stops it;
    //  - colours come from the theme (--spectrum-* in themes.css, falling back
    //    to --color-primary/--color-accent), the gradient is cached per size
    //    and colours, and a browser without ctx.roundRect gets fillRect.
    const _spectrum = (() => {
        const N = 16;
        const ATTACK_S = 0.05;       // easing time constant up
        const RELEASE_S = 0.14;      // ... and down (backend already smooths)
        const PEAK_HOLD_S = 0.45;
        const PEAK_FALL = 0.7;       // levels per second once the hold ends
        const BASE_PX = 2;
        const GAP = 2;
        const target = new Array(N).fill(0);
        const cur = new Array(N).fill(0);
        const peak = new Array(N).fill(0);
        const hold = new Array(N).fill(0);
        let raf = 0;
        let lastT = 0;
        let cache = { canvas: null, key: "", colors: null, grad: null };

        function _raf(fn) {
            return (typeof requestAnimationFrame === "function")
                ? requestAnimationFrame(fn) : setTimeout(() => fn(Date.now()), 16);
        }
        function _caf(id) {
            if (typeof cancelAnimationFrame === "function") cancelAnimationFrame(id);
            else clearTimeout(id);
        }

        function setTarget(bands) {
            const arr = Array.isArray(bands) ? bands : [];
            for (let i = 0; i < N; i++) {
                const v = Number(arr[i]);
                target[i] = Number.isFinite(v) ? Math.max(0, Math.min(1, v)) : 0;
            }
            if (!raf) {
                lastT = 0;
                raf = _raf(_frame);
            }
        }

        function stop() {
            if (raf) _caf(raf);
            raf = 0;
            lastT = 0;
            cache = { canvas: null, key: "", colors: null, grad: null };
        }

        function _cssVar(el, name) {
            try {
                return getComputedStyle(el).getPropertyValue(name).trim();
            } catch (e) {
                return "";
            }
        }

        function _colors(canvas) {
            const top = _cssVar(canvas, "--spectrum-top") || _cssVar(canvas, "--color-primary") || "#f59e0b";
            return {
                top,
                bottom: _cssVar(canvas, "--spectrum-bottom") || _cssVar(canvas, "--color-accent") || top,
                peak: _cssVar(canvas, "--spectrum-peak") || top,
                base: _cssVar(canvas, "--spectrum-base") || "rgba(127,127,127,0.35)",
            };
        }

        function _step(dt) {
            let moving = false;
            const aUp = 1 - Math.exp(-dt / ATTACK_S);
            const aDn = 1 - Math.exp(-dt / RELEASE_S);
            for (let i = 0; i < N; i++) {
                const d = target[i] - cur[i];
                cur[i] += d * (d > 0 ? aUp : aDn);
                if (Math.abs(target[i] - cur[i]) < 0.002) cur[i] = target[i];
                else moving = true;
                if (cur[i] >= peak[i]) {
                    peak[i] = cur[i];
                    hold[i] = PEAK_HOLD_S;
                } else if (hold[i] > 0) {
                    hold[i] -= dt;
                    moving = true;
                } else {
                    peak[i] = Math.max(cur[i], peak[i] - PEAK_FALL * dt);
                    if (peak[i] > cur[i]) moving = true;
                }
            }
            return moving;
        }

        function _draw(canvas) {
            const ctx = canvas.getContext("2d");
            if (!ctx) return;
            const dpr = window.devicePixelRatio || 1;
            const w = Math.round(canvas.clientWidth);
            const h = Math.round(canvas.clientHeight);
            if (w <= 0 || h <= 0) return;
            const pw = Math.round(w * dpr);
            const ph = Math.round(h * dpr);
            if (canvas.width !== pw || canvas.height !== ph) {
                canvas.width = pw;
                canvas.height = ph;
            }
            // setTransform, not scale(): scale() piles up on every resize.
            ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
            ctx.clearRect(0, 0, w, h);

            if (cache.canvas !== canvas) {
                cache = { canvas, key: "", colors: _colors(canvas), grad: null };
            }
            const c = cache.colors;
            const key = h + "|" + c.top + "|" + c.bottom;
            if (cache.key !== key || !cache.grad) {
                const g = ctx.createLinearGradient(0, 0, 0, h);
                g.addColorStop(0, c.top);
                g.addColorStop(1, c.bottom);
                cache.grad = g;
                cache.key = key;
            }

            const barW = Math.max(2, (w - GAP * (N + 1)) / N);
            const usable = h - BASE_PX - 3;            // room for the peak cap
            const round = typeof ctx.roundRect === "function";
            for (let i = 0; i < N; i++) {
                const x = GAP + i * (barW + GAP);
                ctx.fillStyle = c.base;
                ctx.fillRect(x, h - BASE_PX, barW, BASE_PX);
                const barH = cur[i] * usable;
                if (barH >= 0.5) {
                    const y = h - BASE_PX - barH;
                    ctx.fillStyle = cache.grad;
                    if (round && barH > 3) {
                        ctx.beginPath();
                        ctx.roundRect(x, y, barW, barH, 1.5);
                        ctx.fill();
                    } else {
                        ctx.fillRect(x, y, barW, barH);
                    }
                }
                if (peak[i] > 0.02) {
                    const py = h - BASE_PX - peak[i] * usable - 2;
                    ctx.fillStyle = c.peak;
                    ctx.fillRect(x, Math.max(0, py), barW, 1.5);
                }
            }
        }

        function _frame(t) {
            raf = 0;
            const canvas = document.getElementById("spectrum-canvas");
            if (!canvas || canvas.isConnected === false) {
                stop();
                return;
            }
            const now = Number.isFinite(t) ? t : Date.now();
            const dt = lastT ? Math.min(0.1, Math.max(0, (now - lastT) / 1000)) : 1 / 60;
            lastT = now;
            const moving = _step(dt);
            try {
                _draw(canvas);
            } catch (e) {
                stop();
                throw e;
            }
            // Idle when nothing moves; the next payload restarts the loop.
            if (moving) raf = _raf(_frame);
        }

        return { setTarget, stop, _state: () => ({ target: target.slice(), cur: cur.slice(),
                                                   peak: peak.slice(), running: !!raf }) };
    })();

    return { render, update, unmount, _spectrum };
})());
