/**
 * A1 Main Screen — music-centric hub (now-playing card + volume + spectrum).
 *
 * Trimmed for the quick-start build: the engine-temp / fuel / oil-pressure /
 * avg-speed / voltage tiles are gone (those modules are off and only rendered
 * zeros). A1 is now the large media card + a tappable equalizer strip, in all
 * three themes, flanked by two narrow vertical bars: fuel level on the left,
 * engine (coolant) temperature on the right — data.a1_gauges, built in
 * web_viewer._a1_gauges(). A bar with no real source is grey "brak danych";
 * it never shows a made-up default.
 */

App.registerScreen("a1", (() => {
    function render(container, theme, data) {
        if (theme === "modern") container.innerHTML = _renderModern(data);
        else if (theme === "autodelta") container.innerHTML = _renderAutodelta(data);
        else container.innerHTML = _renderHeritage(data);
        _gauges.apply(data);
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

        // Side bars (fuel / engine temperature).
        _gauges.apply(data);
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
            <main class="content-area flex items-center justify-center overflow-hidden px-6 py-4" style="gap:16px">
                ${_gauges.html("fuel", GAUGE_TK.heritage)}
                <div class="w-full max-w-2xl flex flex-col gap-4" style="min-width:0">
                    ${MediaPlayer.renderHeritage(data)}
                    ${_eqStrip({ card: "border-zinc-800 bg-zinc-900/30", label: "text-zinc-500", eqIcon: "text-zinc-600" })}
                </div>
                ${_gauges.html("coolant", GAUGE_TK.heritage)}
            </main>
            ${NavBar.render("heritage", "a1")}
        </div>`;
    }

    function _renderModern(data) {
        return `<div class="screen-container text-slate-900">
            ${AppBar.render("modern", data)}
            <main class="content-area flex items-center justify-center overflow-hidden px-6 py-4 bg-gradient-to-br from-slate-50 to-blue-50/30" style="gap:16px">
                ${_gauges.html("fuel", GAUGE_TK.modern)}
                <div class="w-full max-w-2xl flex flex-col gap-4" style="min-width:0">
                    ${MediaPlayer.renderModern(data)}
                    ${_eqStrip({ card: "border-slate-100 bg-white shadow-sm", label: "text-slate-400", eqIcon: "text-blue-400" })}
                </div>
                ${_gauges.html("coolant", GAUGE_TK.modern)}
            </main>
            ${NavBar.render("modern", "a1")}
        </div>`;
    }

    function _renderAutodelta(data) {
        return `<div class="screen-container bg-black text-white">
            ${AppBar.render("autodelta", data)}
            <main class="content-area flex items-center justify-center overflow-hidden px-6 py-4" style="gap:16px">
                ${_gauges.html("fuel", GAUGE_TK.autodelta)}
                <div class="w-full max-w-2xl flex flex-col gap-4" style="min-width:0">
                    ${MediaPlayer.renderAutodelta(data)}
                    ${_eqStrip({ card: "border-[#222222]", label: "text-gray-500", eqIcon: "text-[#FF5F00]" })}
                </div>
                ${_gauges.html("coolant", GAUGE_TK.autodelta)}
            </main>
            ${NavBar.render("autodelta", "a1")}
        </div>`;
    }

    // ── Side bars: fuel (left) and engine temperature (right) ─────────────
    // Theme look as inline styles: the Tailwind CSS is precompiled, so new
    // utility classes would not exist at runtime.
    const GAUGE_TK = {
        heritage:  { track: "rgba(255,255,255,0.07)", border: "#27272a", label: "#71717a",
                     value: "#e4e4e7", fill: "#d4a017" },
        modern:    { track: "rgba(15,23,42,0.07)", border: "#e2e8f0", label: "#94a3b8",
                     value: "#0f172a", fill: "#3b82f6" },
        autodelta: { track: "#141414", border: "#222222", label: "#6b7280",
                     value: "#ffffff", fill: "#FF5F00" },
    };

    const _gauges = (() => {
        const NO_DATA = "#52525b";            // grey bar: no source
        const RED = "#ef4444", AMBER = "#f59e0b", GREEN = "#22c55e";
        const BLUE = "#3b82f6", CYAN = "#06b6d4";
        const COOLANT_MIN = 40, COOLANT_MAX = 130;   // bar scale, °C
        const FUEL_LOW = 15, FUEL_WARN = 25;          // %

        const t = (k, d) => (typeof App !== "undefined" && App.t ? App.t(k, d) : d);

        // Pure: payload → what one bar shows. Exported for the node test.
        function view(kind, g) {
            const src = g && typeof g.source === "string" ? g.source : "none";
            if (kind === "fuel") {
                const pct = g && Number.isFinite(g.pct) ? Math.max(0, Math.min(100, g.pct)) : null;
                if (src === "none" || pct == null) {
                    return { fill: 0, color: NO_DATA, value: "—", note: t("a1_no_data", "brak danych"), state: "none" };
                }
                const color = pct < FUEL_LOW ? RED : pct < FUEL_WARN ? AMBER : null;
                let note = "";
                if (src === "estimate") {
                    note = t("a1_estimate", "szac.");
                    if (Number.isFinite(g.litres)) note += " " + Math.round(g.litres) + " l";
                } else if (src === "demo") note = t("a1_demo", "demo");
                return { fill: pct, color, value: Math.round(pct) + "%", note,
                         state: pct < FUEL_LOW ? "low" : "ok", estimate: src === "estimate" };
            }
            const c = g && Number.isFinite(g.c) ? g.c : null;
            if (src === "none" || c == null) {
                return { fill: 0, color: NO_DATA, value: "—", note: t("a1_no_data", "brak danych"), state: "none" };
            }
            const fill = Math.max(0, Math.min(100, 100 * (c - COOLANT_MIN) / (COOLANT_MAX - COOLANT_MIN)));
            let color, state;
            if (c > 105) { color = RED; state = "hot"; }
            else if (c > 100) { color = AMBER; state = "warm"; }
            else if (c >= 80) { color = GREEN; state = "ok"; }
            else if (c >= 60) { color = CYAN; state = "warming"; }
            else { color = BLUE; state = "cold"; }
            return { fill, color, value: Math.round(c) + "°", note: src === "demo" ? t("a1_demo", "demo") : "", state };
        }

        function html(kind, tk) {
            const icon = kind === "fuel" ? "local_gas_station" : "device_thermostat";
            const label = kind === "fuel" ? t("a1_fuel", "Paliwo") : t("a1_coolant", "Silnik");
            // Coolant: tick at 90 °C (the normal running temperature).
            const tick = kind === "coolant"
                ? `<div style="position:absolute;left:0;right:0;bottom:${100 * (90 - COOLANT_MIN) / (COOLANT_MAX - COOLANT_MIN)}%;height:1px;background:${tk.label};opacity:.6"></div>`
                : `<div style="position:absolute;left:0;right:0;bottom:${FUEL_LOW}%;height:1px;background:${RED};opacity:.5"></div>`;
            return `<div id="a1-${kind}-gauge" data-gauge="${kind}" data-state="none"
                        style="flex:0 0 52px;width:52px;align-self:stretch;display:flex;flex-direction:column;align-items:center;gap:6px;padding:4px 0">
                <span class="material-symbols-outlined" style="font-size:20px;color:${tk.label}">${icon}</span>
                <div style="font-size:9px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:${tk.label}">${label}</div>
                <div style="position:relative;flex:1 1 auto;min-height:60px;width:22px;border-radius:11px;overflow:hidden;background:${tk.track};border:1px solid ${tk.border}">
                    <div id="a1-${kind}-fill" data-fill="${tk.fill}"
                         style="position:absolute;left:0;right:0;bottom:0;height:0%;background:${NO_DATA};transition:height .6s ease,background-color .6s ease"></div>
                    ${tick}
                </div>
                <div id="a1-${kind}-val" style="font-size:15px;font-weight:700;font-variant-numeric:tabular-nums;color:${tk.value}">—</div>
                <div id="a1-${kind}-note" style="font-size:9px;line-height:1.1;text-align:center;min-height:20px;color:${tk.label}"></div>
            </div>`;
        }

        function _set(kind, v) {
            const root = document.getElementById("a1-" + kind + "-gauge");
            const fill = document.getElementById("a1-" + kind + "-fill");
            if (!root || !fill) return;
            const h = v.fill.toFixed(1) + "%";
            if (fill.style.height !== h) fill.style.height = h;
            const color = v.color || fill.getAttribute("data-fill") || GREEN;
            if (fill.getAttribute("data-color") !== color) {
                fill.style.backgroundColor = color;
                fill.setAttribute("data-color", color);
            }
            // The estimate is drawn half-transparent: a guess, not a reading.
            const op = v.estimate ? "0.6" : "1";
            if (fill.style.opacity !== op) fill.style.opacity = op;
            if (root.getAttribute("data-state") !== v.state) root.setAttribute("data-state", v.state);
            _updateEl("a1-" + kind + "-val", v.value);
            _updateEl("a1-" + kind + "-note", v.note);
        }

        function apply(data) {
            const g = data && typeof data.a1_gauges === "object" && data.a1_gauges ? data.a1_gauges : {};
            _set("fuel", view("fuel", g.fuel));
            _set("coolant", view("coolant", g.coolant));
        }

        return { html, apply, view };
    })();

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

    return { render, update, unmount, _spectrum, _gauges };
})());
