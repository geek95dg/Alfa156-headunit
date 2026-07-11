/**
 * Boot / wake splash overlay.
 *
 * On x86 the DRM `mpv` splash (bcm-splash-main) only covers the COLD-boot
 * gap before X starts — once X owns DRM master for the rest of uptime it
 * can never be replayed, and an S3 wake never reloads the kiosk page. So
 * the wake splash has to live inside the browser: this overlay plays
 * /splash/small.mp4 fullscreen and dismisses itself the moment live data
 * is flowing again ("Flask working"). It fires:
 *
 *   • on page load (any bootup where Chromium actually (re)launches), and
 *   • on every WebSocket reconnect that follows a real gap (wake-from-sleep
 *     — the socket dies during S3 and reconnects on resume).
 *
 * No time-of-day / "12h" gating — it shows on every boot and every wake.
 */
const Splash = (() => {
    const VIDEO_SRC = "/splash/small.mp4";
    const RECONNECT_GAP_MS = 4000;   // a drop longer than this == a real sleep
    const MIN_VISIBLE_MS = 1200;     // never flash for a single frame
    const MAX_VISIBLE_MS = 12000;    // safety: never wedge the screen on the splash
    const HIDE_AFTER_DATA_MS = 600;  // let the dashboard paint under us, then fade

    let _el = null;
    let _shownAt = 0;
    let _hideTimer = null;
    let _maxTimer = null;
    let _downSince = 0;
    let _gotDataSinceShow = false;

    function _build() {
        const wrap = document.createElement("div");
        wrap.id = "bcm-splash-overlay";
        wrap.style.cssText =
            "position:fixed;inset:0;z-index:9999;background:#000;" +
            "display:flex;align-items:center;justify-content:center;" +
            "opacity:1;transition:opacity 0.5s ease;";
        // Muted + playsinline so Chromium autoplays without a gesture.
        wrap.innerHTML =
            '<video id="bcm-splash-video" autoplay loop muted playsinline ' +
            'style="width:100%;height:100%;object-fit:cover;background:#000;" ' +
            'onerror="this.style.display=\'none\'">' +
            '<source src="' + VIDEO_SRC + '" type="video/mp4"></video>';
        return wrap;
    }

    function show() {
        if (_el) return;  // already up
        _el = _build();
        document.body.appendChild(_el);
        _shownAt = Date.now();
        _gotDataSinceShow = false;
        const v = document.getElementById("bcm-splash-video");
        if (v) { try { v.play().catch(() => {}); } catch (e) {} }
        clearTimeout(_maxTimer);
        _maxTimer = setTimeout(hide, MAX_VISIBLE_MS);
    }

    function hide() {
        clearTimeout(_hideTimer); _hideTimer = null;
        clearTimeout(_maxTimer); _maxTimer = null;
        if (!_el) return;
        const el = _el;
        _el = null;
        el.style.opacity = "0";
        setTimeout(() => { try { el.remove(); } catch (e) {} }, 550);
    }

    // Dismiss once data is flowing, but honour the minimum-visible floor so
    // the splash doesn't flicker on a fast reconnect.
    function _onData() {
        if (!_el) return;
        if (_gotDataSinceShow) return;   // schedule the hide only once
        _gotDataSinceShow = true;
        const elapsed = Date.now() - _shownAt;
        const wait = Math.max(MIN_VISIBLE_MS - elapsed, HIDE_AFTER_DATA_MS);
        clearTimeout(_hideTimer);
        _hideTimer = setTimeout(hide, wait);
    }

    function init() {
        // Boot: show immediately on page load; the DataStore subscription
        // below tears it down as soon as the first real frame lands.
        show();
        if (typeof DataStore !== "undefined") {
            DataStore.subscribe("*", _onData);
            DataStore.subscribe("_connection", (up) => {
                if (!up) {
                    _downSince = Date.now();
                } else if (_downSince && Date.now() - _downSince > RECONNECT_GAP_MS) {
                    // Reconnected after a real gap == woke from sleep.
                    _downSince = 0;
                    show();
                } else {
                    _downSince = 0;
                }
            });
        }
    }

    return { init, show, hide };
})();
