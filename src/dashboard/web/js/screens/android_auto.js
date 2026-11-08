/**
 * A2 Android Auto Screen — fullscreen MJPEG view of autoapp's Xvfb (:99)
 * with touch forwarding.
 *
 * NOTE: On x86/VM, AA is streamed via MJPEG from Xvfb — quality is limited.
 * On Orange Pi hardware, OpenAuto renders natively via SDL2/EGL to HDMI-2
 * at full quality without MJPEG overhead.
 *
 * Lifecycle (App.navigateTo calls render → mount, unmount on leave; App's
 * data loop calls update ~15×/s):
 *   - mount() starts AAStream and attaches AATouch to the overlay;
 *   - update() patches the status badge / placeholder in place — it never
 *     rebuilds the <img>, which would restart the stream 15 times a second;
 *   - the stream reconnects (backoff 1→10 s) on <img> error, when aa_status
 *     becomes running/connected, when aa_stream_epoch changes (Xvfb was
 *     restarted) and when the data WebSocket comes back. Before this the
 *     picture stayed black after any AA/BCM restart until a kiosk reload;
 *   - unmount() stops the stream and sends a safety "cancel" so no AA
 *     finger is left pressed.
 *
 * Tailwind is precompiled: markup below reuses only classes that already
 * existed here; anything new is an inline style.
 */

App.registerScreen("a2", (() => {
    let _lastStatus;        // aa_status as last applied to the DOM
    let _lastEpoch;         // aa_stream_epoch as last seen
    let _lastAutoRestart;   // aa_auto_restart as last rendered
    let _onConnection = null;

    const _live = (s) => s === "running" || s === "connected";

    function _statusView(status) {
        const t = App.t.bind(App);
        const isFailed = status === "failed" || status === "error";
        const isUnavailable = status === "unavailable";
        const isRestarting = status === "restarting";

        // Status badge — anchored to top edge directly (no AppBar above
        // the canvas in fullscreen mode).
        let badge = "";
        if (isFailed) {
            badge = `<div class="absolute top-2 left-1/2 -translate-x-1/2 z-20 flex items-center gap-2 bg-red-600/90 text-white text-xs font-bold px-4 py-1.5 rounded-full shadow-lg">
                <span>AA Service Failed</span>
                <button onclick="App.restartAA()" class="underline ml-2 flex items-center gap-1 hover:opacity-80">
                    <span class="material-symbols-outlined text-xs">sync</span> Restart
                </button>
            </div>`;
        } else if (isRestarting) {
            badge = `<div class="absolute top-2 left-1/2 -translate-x-1/2 z-20 bg-amber-600/90 text-white text-xs font-bold px-4 py-1.5 rounded-full animate-pulse shadow-lg">Restarting...</div>`;
        }

        // Placeholder message varies by status
        let msg = t("connect_aa");
        let icon = "link_off";
        if (isUnavailable) {
            msg = "OpenAuto not installed";
            icon = "block";
        } else if (isFailed) {
            msg = "Android Auto service failed. Check logs or restart.";
            icon = "error";
        } else if (isRestarting) {
            msg = "Android Auto is restarting...";
            icon = "sync";
        }

        const restartBtn = `<span class="material-symbols-outlined text-base ${isRestarting ? 'animate-spin' : ''}">sync</span>
                                ${isRestarting ? t("aa_restarting", "Restartowanie...") : t("aa_restart", "Restartuj AA")}`;
        return { badge, msg, icon, restartBtn };
    }

    function _autoRestartView(enabled) {
        const t = App.t.bind(App);
        return `<span>${t("aa_auto_restart", "Autorestart AA")}:</span>
                            <span class="font-bold ${enabled ? 'text-green-400' : 'text-zinc-500'}">
                                ${enabled ? t("active", "AKTYWNY") : t("inactive", "NIEAKTYWNY")}
                            </span>
                            <button onclick="App.setAAAutoRestart(${!enabled})"
                                    class="underline ml-1 cursor-pointer hover:opacity-100 font-semibold" style="color:var(--color-primary, #ef4444)">
                                (${enabled ? 'wyłącz' : 'włącz'})
                            </button>`;
    }

    function render(container, theme, data) {
        const t = App.t.bind(App);
        const bgCls = theme === "modern" ? "bg-slate-100 text-slate-900" : "bg-black text-white";
        const view = _statusView(data.aa_status || "unavailable");

        // Fullscreen — no AppBar. The autohiding NavBar floats over the
        // canvas, revealed by a swipe up from the bottom edge. The
        // captured autoapp stream below is an <img> with absolute
        // inset-0, so the global 7" rem bump doesn't touch its 1:1
        // pixel mapping. Only the shared NavBar gets larger.
        //
        // The <img> has no src here: AAStream.start() (mount) sets it with a
        // cache-busting ?ts= so every (re)connect is a fresh MJPEG request.
        container.innerHTML = `<div class="screen-container ${bgCls}">
            <main class="content-area relative overflow-hidden bg-black">
                <div id="aa-status-badge">${view.badge}</div>
                <!-- AA Canvas fills the full BCM content area. AA can change
                     resolution at runtime — _aa_canvas_size() gives autoapp
                     the same dimensions we render into here, so 1 px on
                     screen == 1 px in the Xvfb capture and touch coordinates
                     map 1:1 with no letterboxing. The canvas is never
                     resized for gestures: edge gestures are recognised by
                     AATouch on top of it. -->
                <div id="aa-canvas" class="absolute inset-0">
                    <img id="aa-stream" alt=""
                         class="absolute inset-0 w-full h-full object-fill z-0"
                         style="display:none;">

                    <!-- Touch overlay — same size as the canvas, no gutters
                         to swallow taps. touch-action:none so the browser
                         never turns a drag into a scroll/zoom. -->
                    <div id="aa-touch-overlay" class="absolute inset-0 z-10"
                         style="display:none;touch-action:none;"></div>
                </div>

                <!-- Placeholder fills the full content-area when AA is not
                     connected — intentional, so the offline state owns
                     the whole panel and isn't letterboxed. -->
                <div id="aa-placeholder" class="absolute inset-0 flex flex-col items-center justify-center gap-6">
                    <div class="relative">
                        <span class="material-symbols-outlined text-8xl opacity-20">android</span>
                        <div class="absolute -bottom-1 -right-1 w-6 h-6 rounded-full ${theme==='modern'?'bg-slate-300':'bg-zinc-700'} flex items-center justify-center">
                            <span id="aa-placeholder-icon" class="material-symbols-outlined text-sm opacity-60">${view.icon}</span>
                        </div>
                    </div>
                    <div class="text-center">
                        <h2 class="text-2xl font-bold mb-2">${t("android_auto")}</h2>
                        <p id="aa-placeholder-msg" class="opacity-50 text-sm max-w-md">${view.msg}</p>
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

                    <!-- Quick controls: Restart AA, Kiosk Restart, Auto-restart toggle -->
                    <div class="flex flex-col items-center gap-3 mt-2">
                        <div class="flex items-center gap-3">
                            <button id="aa-restart-btn" onclick="App.restartAA()"
                                    class="px-4 py-2 rounded-xl text-xs font-bold flex items-center gap-2 hover:opacity-80 transition-all shadow-md active:scale-95"
                                    style="background:${theme==='modern'?'#e2e8f0':'#27272a'};color:${theme==='modern'?'#0f172a':'#fff'};border:1px solid ${theme==='modern'?'#cbd5e1':'#3f3f46'}">
                                ${view.restartBtn}
                            </button>
                            <button onclick="App.restartKioskModal()"
                                    class="px-4 py-2 bg-red-600/20 border border-red-600/40 hover:bg-red-600/30 text-red-400 rounded-xl text-xs font-bold flex items-center gap-2 transition-all shadow-md active:scale-95">
                                <span class="material-symbols-outlined text-base">restart_alt</span>
                                ${t("kiosk_restart", "Restart kiosku")}
                            </button>
                        </div>
                        <div id="aa-autorestart" class="flex items-center gap-2 text-[11px] opacity-70">
                            ${_autoRestartView(!!data.aa_auto_restart)}
                        </div>
                    </div>
                </div>
            </main>
            ${NavBar.render(theme, "a2")}
        </div>`;
    }

    function _setHTML(id, html) {
        const el = document.getElementById(id);
        if (el) el.innerHTML = html;
    }

    function _setText(id, text) {
        const el = document.getElementById(id);
        if (el && el.textContent !== text) el.textContent = text;
    }

    function _applyStatus(status) {
        const view = _statusView(status);
        _setHTML("aa-status-badge", view.badge);
        _setText("aa-placeholder-msg", view.msg);
        _setText("aa-placeholder-icon", view.icon);
        _setHTML("aa-restart-btn", view.restartBtn);
    }

    function mount() {
        const data = DataStore.getAll();
        _lastStatus = data.aa_status || "unavailable";
        _lastEpoch = data.aa_stream_epoch || 0;
        _lastAutoRestart = !!data.aa_auto_restart;
        AATouch.attach(document.getElementById("aa-touch-overlay"));
        const img = document.getElementById("aa-stream");
        if (img) AAStream.start(img, () => _lastStatus);
        // BCM restarted / Wi-Fi blip: the old MJPEG connection is dead.
        _onConnection = (connected) => { if (connected) AAStream.reconnectSoon(); };
        DataStore.subscribe("_connection", _onConnection);
    }

    function update(data) {
        const status = data.aa_status || "unavailable";
        if (status !== _lastStatus) {
            const prev = _lastStatus;
            _lastStatus = status;
            _applyStatus(status);
            // Into running/connected from a dead state (or with no picture):
            // autoapp is up again, so is a fresh Xvfb — reconnect.
            if (_live(status) && (!_live(prev) || !AAStream.isShowing())) {
                AAStream.reconnectSoon();
            }
        }
        const epoch = data.aa_stream_epoch || 0;
        if (epoch !== _lastEpoch) {
            _lastEpoch = epoch;
            if (epoch) AAStream.reconnectSoon();
        }
        const autoRestart = !!data.aa_auto_restart;
        if (autoRestart !== _lastAutoRestart) {
            _lastAutoRestart = autoRestart;
            _setHTML("aa-autorestart", _autoRestartView(autoRestart));
        }
    }

    function unmount() {
        if (_onConnection) {
            DataStore.unsubscribe("_connection", _onConnection);
            _onConnection = null;
        }
        AAStream.stop();
        AATouch.detach();
        // Safety net: whatever the overlay believed, no AA finger stays down
        // once the screen is gone (the server ignores it if none is).
        DataStore.sendAATouch("cancel", null, null);
    }

    return { render, mount, update, unmount };
})());

/**
 * MJPEG <img> lifecycle with reconnect backoff (1, 2, 4, 8, 10, 10… s).
 */
const AAStream = (() => {
    const MIN_DELAY_MS = 1000;
    const MAX_DELAY_MS = 10000;
    const DEBOUNCE_MS = 300;   // epoch + status often change within ~1 s

    let _img = null;
    let _timer = null;
    let _delay = MIN_DELAY_MS;
    let _showing = false;
    let _statusFn = null;

    function _clearTimer() {
        if (_timer) { clearTimeout(_timer); _timer = null; }
    }

    function _setLive(live) {
        _showing = live;
        if (_img) _img.style.display = live ? "block" : "none";
        const ph = document.getElementById("aa-placeholder");
        if (ph) ph.style.display = live ? "none" : "flex";
        const ov = document.getElementById("aa-touch-overlay");
        if (ov) ov.style.display = live ? "block" : "none";
        // A finger on a stream that just vanished must not stay pressed.
        if (!live) AATouch.abort();
    }

    function connect() {
        _clearTimer();
        if (!_img) return;
        _img.src = "/aa/stream?ts=" + Date.now();
    }

    function _onLoad() {
        _delay = MIN_DELAY_MS;
        _setLive(true);
    }

    function _onError() {
        _setLive(false);
        if (!_img) return;
        // No autoapp at all: retrying every 10 s would only spawn ffmpeg
        // into the void. A status change or WS reconnect restarts us.
        if (_statusFn && _statusFn() === "unavailable") return;
        _clearTimer();
        _timer = setTimeout(connect, _delay);
        _delay = Math.min(_delay * 2, MAX_DELAY_MS);
    }

    function stop() {
        _clearTimer();
        if (_img) {
            _img.onload = null;
            _img.onerror = null;
            _img.src = "";   // closes the MJPEG connection → server stops ffmpeg
        }
        _img = null;
        _statusFn = null;
        _showing = false;
    }

    return {
        start(img, statusFn) {
            stop();
            _img = img;
            _statusFn = statusFn || null;
            _delay = MIN_DELAY_MS;
            img.onload = _onLoad;
            img.onerror = _onError;
            connect();
        },
        /** Something changed server-side: reconnect now (debounced), with
         *  the backoff reset. */
        reconnectSoon() {
            if (!_img) return;
            _delay = MIN_DELAY_MS;
            _clearTimer();
            _timer = setTimeout(connect, DEBOUNCE_MS);
        },
        isShowing() { return _showing; },
        stop,
    };
})();

/**
 * AA touch forwarding — Pointer Events on #aa-touch-overlay → the edge state
 * machine (components/gestures.js createEdgeTracker) → DataStore.sendAATouch
 * (/ws/input) → xdotool on :99.
 *
 * Only the first pointer is tracked (xdotool has one mouse; pinch cannot be
 * replayed). Moves are throttled to one per animation frame; while the
 * button is down the last position is re-sent every second so the server's
 * stuck-button watchdog (3 s) only fires when this page is really gone, not
 * during a long press. Coordinates are relative to the overlay (0..1).
 */
const AATouch = (() => {
    const HEARTBEAT_MS = 1000;

    let _el = null;
    let _tracker = null;
    let _pointerId = null;
    let _rect = null;
    let _raf = 0;
    let _pendingMove = null;
    let _lastPos = null;
    let _heartbeat = null;
    let _buttonDown = false;

    function _emit(action, x, y) {
        let rx = null;
        let ry = null;
        if (action !== "cancel") {
            const r = _rect;
            if (!r || !(r.width > 0) || !(r.height > 0)) return;
            rx = Math.min(1, Math.max(0, x / r.width));
            ry = Math.min(1, Math.max(0, y / r.height));
        }
        DataStore.sendAATouch(action, rx, ry);
    }

    function _flushMove() {
        _raf = 0;
        const p = _pendingMove;
        _pendingMove = null;
        if (p) _emit("move", p[0], p[1]);
    }

    function _dropPendingMove() {
        if (_raf) { cancelAnimationFrame(_raf); _raf = 0; }
        _pendingMove = null;
    }

    function _stopHeartbeat() {
        if (_heartbeat) { clearInterval(_heartbeat); _heartbeat = null; }
    }

    function _startHeartbeat() {
        _stopHeartbeat();
        _heartbeat = setInterval(() => {
            if (_buttonDown && _lastPos && !_pendingMove) _emit("move", _lastPos[0], _lastPos[1]);
        }, HEARTBEAT_MS);
    }

    /** Output of the edge tracker. */
    function _send(action, x, y) {
        if (action === "move") {
            _lastPos = [x, y];
            _pendingMove = [x, y];
            if (!_raf) _raf = requestAnimationFrame(_flushMove);
            return;
        }
        // up/tap carry their own coordinates, so a queued move is moot.
        _dropPendingMove();
        _emit(action, x, y);
        if (action === "down") {
            _buttonDown = true;
            _lastPos = [x, y];
            _startHeartbeat();
        } else {
            _buttonDown = false;
            _stopHeartbeat();
        }
    }

    function _pos(e) {
        const r = _rect || _el.getBoundingClientRect();
        return [e.clientX - r.left, e.clientY - r.top];
    }

    function _onDown(e) {
        if (!_tracker || _pointerId !== null) return;   // first pointer only
        if (e.pointerType === "mouse" && e.button !== 0) return;
        e.preventDefault();
        _pointerId = e.pointerId;
        _rect = _el.getBoundingClientRect();
        try { _el.setPointerCapture(e.pointerId); } catch (err) { /* still works without */ }
        const p = _pos(e);
        _tracker.down(p[0], p[1], performance.now(), _rect.height);
    }

    function _onMove(e) {
        if (!_tracker || e.pointerId !== _pointerId) return;
        e.preventDefault();
        const p = _pos(e);
        _tracker.move(p[0], p[1], performance.now());
    }

    function _onUp(e) {
        if (!_tracker || e.pointerId !== _pointerId) return;
        e.preventDefault();
        const p = _pos(e);
        _pointerId = null;
        try { _el.releasePointerCapture(e.pointerId); } catch (err) { /* already released */ }
        _tracker.up(p[0], p[1], performance.now());
    }

    function _onCancel(e) {
        if (!_tracker || e.pointerId !== _pointerId) return;
        _pointerId = null;
        _tracker.cancel();
    }

    // preventDefault() on pointerdown plus touch-action:none stop scrolling
    // and zooming, but NOT Chromium's own touch gestures: holding a finger
    // still for ~0.5-1 s fires "contextmenu" and can open the browser menu
    // over the kiosk, which cancels the pointer (pointercancel → "cancel" to
    // AA) — exactly the press-and-hold the edge tracker and map drags rely
    // on. The old overlay blocked this with an inline ontouchstart that
    // called preventDefault(). Cancelling touchstart (non-passive) and
    // contextmenu restores that; pointer events still fire, and the global
    // document handler in app.js ignores overlay touches anyway.
    function _noDefault(e) {
        if (e.cancelable) e.preventDefault();
    }

    function abort() {
        _pointerId = null;
        if (_tracker) _tracker.cancel();   // sends "cancel" if AA had the finger
        _dropPendingMove();
        _stopHeartbeat();
        _buttonDown = false;
    }

    function detach() {
        abort();
        if (_el) {
            _el.removeEventListener("pointerdown", _onDown);
            _el.removeEventListener("pointermove", _onMove);
            _el.removeEventListener("pointerup", _onUp);
            _el.removeEventListener("pointercancel", _onCancel);
            _el.removeEventListener("lostpointercapture", _onCancel);
            _el.removeEventListener("touchstart", _noDefault);
            _el.removeEventListener("contextmenu", _noDefault);
        }
        _el = null;
        _tracker = null;
        _rect = null;
        _lastPos = null;
    }

    function attach(el) {
        detach();
        const G = window.BCMGestures;
        if (!el || !G) return;
        _el = el;
        _tracker = G.createEdgeTracker({
            send: _send,
            // Deferred: navigating unmounts A2 (and detaches us) — not from
            // inside our own pointerup handler.
            onPull: () => setTimeout(() => App.navCycleNext(), 0),
            onNavbar: () => App.showNavBar(),
        });
        el.style.touchAction = "none";
        el.addEventListener("pointerdown", _onDown);
        el.addEventListener("pointermove", _onMove);
        el.addEventListener("pointerup", _onUp);
        el.addEventListener("pointercancel", _onCancel);
        el.addEventListener("lostpointercapture", _onCancel);
        el.addEventListener("touchstart", _noDefault, { passive: false });
        el.addEventListener("contextmenu", _noDefault);
    }

    return { attach, detach, abort };
})();
