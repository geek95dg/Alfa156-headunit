/**
 * Edge gestures — pure functions shared by the global touch handler
 * (app.js _initTouchSwipe) and the Android Auto touch overlay
 * (screens/android_auto.js AATouch).
 *
 * Why: screen changes used to be a horizontal swipe anywhere, which also
 * fired on the AA stream — every horizontal drag meant for the phone (map,
 * lists, media carousel) switched the BCM screen instead. Now:
 *   - pull DOWN from the top edge   → next screen (A1→A2→A3→A4→A1),
 *   - swipe UP from the bottom edge → reveal the autohiding NavBar,
 * and everything else on A2 goes to Android Auto untouched.
 *
 * No DOM access here, so tests/test_frontend_gestures.py runs this file in
 * plain node. Loaded before app.js (index.html); exposed as
 * window.BCMGestures.
 */
(function (root) {
    "use strict";

    const EDGE_PX = 40;        // touch must start this close to the top/bottom edge
    const PULL_MIN = 80;       // pull-down distance that changes the screen
    const PULL_MAX_MS = 800;   // ...within this time (a slow drag is not a flick)
    const TAP_SLOP = 10;       // movement below this is still a tap / long-press
    const HOLD_PASS_MS = 500;  // edge touch held still this long → long-press to AA
    const NAVBAR_MIN = 40;     // swipe-up distance that reveals the NavBar

    function _finite(v) {
        return typeof v === "number" && isFinite(v);
    }

    /** "top" | "bottom" | null for a touch at y in a box of height h. */
    function edgeZone(y, h) {
        if (!_finite(y) || !_finite(h) || h <= 0) return null;
        if (y <= EDGE_PX) return "top";
        if (h - y <= EDGE_PX) return "bottom";
        return null;
    }

    /**
     * Classify an edge touch from its displacement so far:
     *   "pending" — still within TAP_SLOP, undecided;
     *   "pull"    — top zone, moving down and mostly vertical (|dx| <= dy/2);
     *   "navbar"  — bottom zone, moving up and more vertical than horizontal;
     *   "pass"    — anything else: it is not ours, hand it to the content.
     */
    function classify(zone, dx, dy) {
        if (!_finite(dx) || !_finite(dy)) return "pass";
        if (Math.hypot(dx, dy) < TAP_SLOP) return "pending";
        if (zone === "top" && dy > 0 && Math.abs(dx) <= 0.5 * dy) return "pull";
        if (zone === "bottom" && dy < 0 && Math.abs(dx) < Math.abs(dy)) return "navbar";
        return "pass";
    }

    /** Is a finished pull-down (displacement dx, dy over dt ms) a screen change? */
    function pullDone(dx, dy, dt) {
        if (!_finite(dx) || !_finite(dy) || !_finite(dt)) return false;
        return dy >= PULL_MIN && Math.abs(dx) <= 0.5 * dy && dt >= 0 && dt <= PULL_MAX_MS;
    }

    /** Is a finished bottom-edge swipe (dx, dy) a NavBar reveal? */
    function navbarDone(dx, dy) {
        if (!_finite(dx) || !_finite(dy)) return false;
        return dy <= -NAVBAR_MIN && Math.abs(dy) > Math.abs(dx);
    }

    /**
     * Edge state machine for a surface that forwards touches elsewhere (the
     * AA overlay). Coordinates are pixels relative to the surface; times are
     * ms on one clock (performance.now()).
     *
     *   IDLE --down in edge zone--> HELD   (nothing sent yet: buffered p0)
     *   IDLE --down elsewhere-----> PASS   send down(p)
     *   HELD --held > HOLD_PASS_MS-> PASS  send down(p0)  (long-press works)
     *   HELD --classify "pull"----> PULL   (swallowed)
     *   HELD --classify "navbar"--> NAV    (swallowed)
     *   HELD --other move---------> PASS   send down(p0), move(p)
     *   HELD --up-----------------> IDLE   send tap(p0)
     *   PULL --up-----------------> IDLE   pullDone ? onPull() : nothing
     *   NAV  --up-----------------> IDLE   navbarDone ? onNavbar() : nothing
     *   PASS --move/up/cancel-----> send move / up / cancel
     *
     * opts: send(action, x, y), onPull(), onNavbar(),
     *       setTimer(fn, ms) / clearTimer(id) (default setTimeout/clearTimeout).
     */
    function createEdgeTracker(opts) {
        const o = opts || {};
        const send = o.send || function () {};
        const onPull = o.onPull || function () {};
        const onNavbar = o.onNavbar || function () {};
        const setTimer = o.setTimer || function (fn, ms) { return setTimeout(fn, ms); };
        const clearTimer = o.clearTimer || function (id) { clearTimeout(id); };

        let state = "idle";
        let zone = null;
        let x0 = 0, y0 = 0, t0 = 0;
        let holdTimer = null;

        function clearHold() {
            if (holdTimer !== null) { clearTimer(holdTimer); holdTimer = null; }
        }
        function toPass() {
            clearHold();
            state = "pass";
            send("down", x0, y0);
        }

        return {
            state() { return state; },

            down(x, y, t, h) {
                if (state !== "idle") return state;   // one touch at a time
                x0 = x; y0 = y; t0 = t;
                zone = edgeZone(y, h);
                if (zone) {
                    state = "held";
                    holdTimer = setTimer(function () {
                        holdTimer = null;
                        if (state === "held") toPass();
                    }, HOLD_PASS_MS);
                } else {
                    state = "pass";
                    send("down", x, y);
                }
                return state;
            },

            move(x, y, t) {
                if (state === "pass") { send("move", x, y); return state; }
                if (state !== "held") return state;    // pull/nav are swallowed
                const c = classify(zone, x - x0, y - y0);
                if (c === "pending") {
                    // Timers can be throttled; the move clock is authoritative.
                    if (_finite(t) && t - t0 > HOLD_PASS_MS) toPass();
                } else if (c === "pull") {
                    clearHold(); state = "pull";
                } else if (c === "navbar") {
                    clearHold(); state = "nav";
                } else {
                    toPass();
                    send("move", x, y);
                }
                return state;
            },

            /** Returns the state the touch ended in. */
            up(x, y, t) {
                const ended = state;
                clearHold();
                state = "idle";
                if (ended === "pass") send("up", x, y);
                else if (ended === "held") send("tap", x0, y0);
                else if (ended === "pull") { if (pullDone(x - x0, y - y0, t - t0)) onPull(); }
                else if (ended === "nav") { if (navbarDone(x - x0, y - y0)) onNavbar(); }
                return ended;
            },

            cancel() {
                const ended = state;
                clearHold();
                state = "idle";
                if (ended === "pass") send("cancel", null, null);
                return ended;
            },
        };
    }

    const api = {
        EDGE_PX, PULL_MIN, PULL_MAX_MS, TAP_SLOP, HOLD_PASS_MS, NAVBAR_MIN,
        edgeZone, classify, pullDone, navbarDone, createEdgeTracker,
    };
    root.BCMGestures = api;
    if (typeof module !== "undefined" && module.exports) module.exports = api;
})(typeof window !== "undefined" ? window : globalThis);
