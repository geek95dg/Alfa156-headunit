/**
 * On-Screen QWERTY Keyboard — touchscreen virtual keyboard overlay.
 * Appears when a text-like field is focused (isOskInput). Themed per active
 * theme. Position: bottom of screen (like mobile keyboards).
 *
 * Sizing: every dimension is computed in pixels from the window height by the
 * pure function oskLayout() and handed to themes.css as CSS variables on
 * <html> (--osk-h, --osk-pad, --osk-gap, --osk-font). Why: the old panel was
 * a fixed 50vh with rem-sized padding/rows/text. Commit 2e3baaf added the 6th
 * row (Polish letters) and raised the root font to 17 px, so on the 1024x600
 * panel the content needed ~386 px of a 300 px panel — the last row ended
 * 87 px below the screen and shift, z..m, backspace, SPACE and OK could not be
 * pressed. Rows are now flex rows that share whatever height the panel has,
 * so they can never overflow it, and the panel itself never exceeds the
 * viewport.
 *
 * No DOM access at load time when there is no document, so
 * tests/test_frontend_keyboard.py can require() this file in plain node.
 */

const OnScreenKeyboard = (() => {
    let _activeInput = null;
    let _value = "";
    let _shift = false;
    let _visible = false;
    let _raf = 0;

    // Gap kept between the bottom of the focused field and the top of the
    // keyboard after _ensureVisible() scrolls it (themes.css pads the content
    // area by the keyboard height + the same 12 px so the scroll has room).
    const VISIBLE_MARGIN = 12;
    // Window height assumed when the real one is unusable (0 while the kiosk
    // window is still mapping, NaN from a broken caller): the 7" panel.
    const FALLBACK_VH = 600;

    // Input types the keyboard can type into. Not "number": the OSK writes
    // input.value directly, and a number field silently turns any non-numeric
    // string into "" — the field and the OSK's own buffer would disagree, and
    // OK would then wipe the field. Not checkbox/range/etc.: no text at all.
    const OSK_INPUT_TYPES = ["text", "password", "search", "email", "url", "tel"];

    // The last row holds the hide button and the typed-text preview next to
    // SPACE/OK. They used to be a separate header row above the keys; folding
    // them in gives the six key rows the whole panel (50 px keys instead of
    // 42 px at 1024x600). The preview is kept because a field that sits in a
    // container that cannot scroll may still end up under the keyboard, and
    // then it is the only place the user sees what was typed.
    const ROWS = [
        ["1","2","3","4","5","6","7","8","9","0"],
        ["q","w","e","r","t","y","u","i","o","p"],
        ["a","s","d","f","g","h","j","k","l"],
        // Polskie znaki diakrytyczne — key() już robi toUpperCase(), więc
        // shift daje wersaliki (Ą, Ć, …) bez dodatkowego kodu.
        ["ą","ć","ę","ł","ń","ó","ś","ź","ż"],
        ["shift","z","x","c","v","b","n","m","backspace"],
        ["hide","preview","space","done"],
    ];

    /**
     * Pure: keyboard geometry for a window `viewportH` px tall with `nRows`
     * key rows. Returns integers {height, pad, gap, rowH, font} in px.
     *
     *   height — 58% of the window, at least 220 px, but always leaving
     *            150 px above it for the field being edited (AppBar + one
     *            row of content) and never taller than the window;
     *   pad    — panel padding, gap — space between rows/keys;
     *   rowH   — height one row gets; 2*pad + n*rowH + (n-1)*gap <= height
     *            always holds, so the last row is never cut off;
     *   font   — key label size, ~45% of the row, clamped to 14..26 px.
     */
    function oskLayout(viewportH, nRows) {
        let vh = Number(viewportH);
        if (!isFinite(vh) || vh <= 0) vh = FALLBACK_VH;
        vh = Math.floor(vh);
        let n = Math.floor(Number(nRows));
        if (!isFinite(n) || n < 1) n = 1;

        let height = Math.round(Math.min(Math.max(vh * 0.58, 220), vh - 150));
        height = Math.max(0, Math.min(height, vh));
        let pad = Math.max(4, Math.round(height * 0.02));
        let gap = Math.max(3, Math.round(height * 0.016));
        // A window too small for even the minimum padding (not a real panel)
        // drops padding/gaps instead of producing negative rows.
        if (height - 2 * pad - gap * (n - 1) < n) { pad = 0; gap = 0; }
        const rowH = Math.max(0, Math.floor((height - 2 * pad - gap * (n - 1)) / n));
        const font = Math.min(26, Math.max(14, Math.round(rowH * 0.45)));
        return { height, pad, gap, rowH, font };
    }

    /** Pure: does focusing `el` open the keyboard? Text-like inputs and
     *  textareas that the user may edit (readonly fields stay read-only —
     *  the OSK writes .value directly, which would bypass the attribute). */
    function isOskInput(el) {
        if (!el || typeof el !== "object") return false;
        if (el.disabled || el.readOnly) return false;
        const tag = String(el.tagName || "").toUpperCase();
        if (tag === "TEXTAREA") return true;
        if (tag !== "INPUT") return false;
        // An <input> without a type attribute is a text field.
        const type = String(el.type || "text").toLowerCase();
        return OSK_INPUT_TYPES.includes(type);
    }

    function attach(inputEl) {
        if (_visible && _activeInput === inputEl) return;
        _activeInput = inputEl;
        _value = inputEl.value || "";
        _shift = false;
        _show();
    }

    function key(k) {
        if (k === "shift") {
            _shift = !_shift;
            _renderKeys();
            return;
        }
        if (k === "backspace") {
            _value = _value.slice(0, -1);
        } else if (k === "space") {
            _value += " ";
        } else if (k === "done") {
            _close();
            return;
        } else {
            _value += _shift ? k.toUpperCase() : k;
            if (_shift) { _shift = false; _renderKeys(); }
        }
        if (_activeInput) {
            _activeInput.value = _value;
            _activeInput.dispatchEvent(new Event("input", { bubbles: true }));
            // Tapping a key on a touchscreen typically moves focus to
            // the button; restore focus on the input so the user keeps
            // typing without re-tapping the field.
            try { _activeInput.focus({ preventScroll: true }); } catch (_) {}
        }
        _updateDisplay();
    }

    /** Size the keyboard for the current window: the CSS variables live on
     *  <html> so the content-area padding rule (themes.css) can use --osk-h
     *  too, not only the overlay. */
    function _applyLayout() {
        const L = oskLayout(window.innerHeight, ROWS.length);
        const s = document.documentElement.style;
        s.setProperty("--osk-h", L.height + "px");
        s.setProperty("--osk-pad", L.pad + "px");
        s.setProperty("--osk-gap", L.gap + "px");
        s.setProperty("--osk-font", L.font + "px");
        return L;
    }

    /** Next frame: re-size (window may have changed) and pull the field
     *  above the keyboard. One pending frame at a time — a burst of resize
     *  events costs one layout pass. */
    function _scheduleFit() {
        if (_raf) return;
        const run = () => {
            _raf = 0;
            if (!_visible) return;
            _applyLayout();
            _ensureVisible(_activeInput);
        };
        _raf = (typeof requestAnimationFrame === "function")
            ? requestAnimationFrame(run) : setTimeout(run, 16);
    }

    /** Scrollable ancestors of `el`, nearest first: overflow-y auto/scroll
     *  and actually overflowing. Covers the screens' .content-area (padded
     *  by the keyboard height while it is open) and overlays with their own
     *  scroller (the trip planner's overflow:auto panel). */
    function _scrollParents(el) {
        const out = [];
        for (let p = el.parentElement; p && p !== document.body && p !== document.documentElement;
             p = p.parentElement) {
            const oy = getComputedStyle(p).overflowY;
            if ((oy === "auto" || oy === "scroll") && p.scrollHeight > p.clientHeight) out.push(p);
        }
        return out;
    }

    /**
     * Scroll so the field's bottom sits at least VISIBLE_MARGIN px above the
     * keyboard. The old scrollIntoView({block:"center"}) centred the field
     * in the window — i.e. right under a keyboard that covers the bottom
     * 58%. Walks outwards through nested scrollers and re-measures after
     * each one, because an inner list may only be able to scroll part of
     * the way. A field taller than the space left (a textarea) is aligned
     * by its top instead. Instant, not smooth: a smooth scroll would still
     * be running when the next measurement is taken.
     */
    function _ensureVisible(input) {
        if (!input || !input.isConnected) return;
        const overlay = document.getElementById("osk-overlay");
        if (!overlay) return;
        const limit = overlay.getBoundingClientRect().top - VISIBLE_MARGIN;
        for (const sc of _scrollParents(input)) {
            const r = input.getBoundingClientRect();
            const top = Math.max(0, sc.getBoundingClientRect().top);
            let delta = 0;
            if (r.bottom > limit) delta = Math.min(r.bottom - limit, r.top - top - VISIBLE_MARGIN);
            else if (r.top < top) delta = r.top - top - VISIBLE_MARGIN;
            if (delta === 0) return;
            // Round away from zero: scroll offsets snap to whole pixels and
            // the rects are fractional (rem-sized content), so a plain
            // += could leave the field a fraction of a pixel short.
            sc.scrollTop += delta > 0 ? Math.ceil(delta) : Math.floor(delta);
        }
    }

    function _show() {
        _visible = true;
        let overlay = document.getElementById("osk-overlay");
        const fresh = !overlay;
        if (fresh) {
            overlay = document.createElement("div");
            overlay.id = "osk-overlay";
            document.body.appendChild(overlay);
        }
        // Sizes first, so the very first paint already fits the screen.
        _applyLayout();
        _render(overlay);
        // Pad the content area up by the keyboard height (themes.css), then —
        // once that padding is laid out — scroll the field above the keys.
        document.body.classList.add("osk-open");
        _scheduleFit();
        if (!fresh) return;

        // Prevent the input from losing focus when the user taps a key.
        // mousedown.preventDefault keeps focus on the input on desktop;
        // we MUST NOT preventDefault on touchstart here because that
        // also cancels the synthetic click event that drives the OSK
        // button onclick handlers — exactly what broke typing on the
        // OPi5 touchscreen while the desktop VM still worked. Use
        // pointerdown.preventDefault to cover both pointer and touch
        // without killing the click.
        overlay.addEventListener("mousedown", (e) => e.preventDefault());
        overlay.addEventListener("pointerdown", (e) => {
            // Only prevent default for non-touch pointers; for touch we
            // need the click to still fire. Touch pointers are handled
            // via the focus restore in `key()` below.
            if (e.pointerType !== "touch") e.preventDefault();
        });
    }

    /** Hide the keyboard. The field is deliberately NOT written here: key()
     *  already puts every keystroke into it (with an "input" event), so the
     *  field and _value can only differ when someone else changed the field
     *  afterwards — and then the field is the newer truth (a page that
     *  clears it after a pick, an "input" handler that reformats it). The
     *  old write-back plus "input" event got that wrong: the tap-outside
     *  close runs in the capture phase, before the tapped suggestion's own
     *  handler, so the extra event started a fresh search that re-opened the
     *  result list (weather: under the field the pick had just cleared) a
     *  moment after the user had chosen a result. When the close came after
     *  the page's handler, it also put the typed text back into that
     *  cleared field. */
    function _close() {
        _visible = false;
        const overlay = document.getElementById("osk-overlay");
        if (overlay) overlay.remove();
        document.body.classList.remove("osk-open");
        _activeInput = null;
    }

    function _render(overlay) {
        const theme = (typeof App !== "undefined" && App && App.getTheme) ? App.getTheme() : "heritage";
        const bg = theme === "autodelta" ? "bg-[#111] border-[#FF5F00]/20"
                 : theme === "modern" ? "bg-zinc-900 border-zinc-700"
                 : "bg-[#1a0f0a] border-amber-900/40";
        const keyBg = theme === "autodelta" ? "bg-zinc-800 hover:bg-[#FF5F00]/20 active:bg-[#FF5F00]/40 text-white"
                    : theme === "modern" ? "bg-zinc-800 hover:bg-zinc-700 active:bg-zinc-600 text-white"
                    : "bg-zinc-800 hover:bg-amber-900/30 active:bg-amber-900/50 text-white";
        const accent = theme === "autodelta" ? "bg-[#FF5F00] text-white"
                     : theme === "modern" ? "bg-blue-600 text-white"
                     : "bg-amber-600 text-white";

        // Position, height, padding and gaps come from the #osk-overlay rules
        // in themes.css (driven by the --osk-* variables); only colours and
        // the border are theme classes here. 7" touchscreen OSK — explicitly
        // NOT max-width-clamped: every key stretches to fill the full width
        // so the hit-targets match the user's actual finger size.
        overlay.className = "border-t shadow-2xl " + bg;
        overlay.style.cssText = "";

        // Each row is a flex row of equal height (.osk-row); within a row
        // the flex weights share the full width, so a 9-letter row gets
        // fatter keys than the 10-digit row, which matches typing
        // ergonomics (the home row needs bigger keys, the number row gets
        // fewer taps).
        const btn = "rounded-lg font-bold transition-colors osk-key";
        let html = "";
        for (const row of ROWS) {
            html += `<div class="osk-row">`;
            for (const k of row) {
                if (k === "space") {
                    html += `<button type="button" class="${keyBg} ${btn} flex-[6]" onclick="OnScreenKeyboard.key('space')">SPACE</button>`;
                } else if (k === "done") {
                    html += `<button type="button" class="${accent} ${btn} flex-[2]" onclick="OnScreenKeyboard.key('done')">OK</button>`;
                } else if (k === "hide") {
                    html += `<button type="button" class="${keyBg} ${btn} flex-[1.4]" onclick="OnScreenKeyboard.close()" title="Hide keyboard">
                        <span class="material-symbols-outlined">keyboard_hide</span>
                    </button>`;
                } else if (k === "preview") {
                    // Filled by _updateDisplay() via textContent — the typed
                    // text never becomes markup. text-white like the keys:
                    // the panel is dark in every theme, the page text in
                    // "modern" is not.
                    html += `<span id="osk-display" class="osk-preview font-mono text-white"></span>`;
                } else if (k === "shift") {
                    html += `<button type="button" class="${_shift ? accent : keyBg} ${btn} flex-[1.4]" onclick="OnScreenKeyboard.key('shift')">
                        <span class="material-symbols-outlined">shift</span>
                    </button>`;
                } else if (k === "backspace") {
                    html += `<button type="button" class="${keyBg} ${btn} flex-[1.4]" onclick="OnScreenKeyboard.key('backspace')">
                        <span class="material-symbols-outlined">backspace</span>
                    </button>`;
                } else {
                    // k comes from the constant ROWS table above, never from input.
                    const display = _shift ? k.toUpperCase() : k;
                    html += `<button type="button" class="${keyBg} ${btn} flex-1" onclick="OnScreenKeyboard.key('${k}')">${display}</button>`;
                }
            }
            html += `</div>`;
        }
        overlay.innerHTML = html;
        _updateDisplay();
    }

    function _renderKeys() {
        const overlay = document.getElementById("osk-overlay");
        if (overlay) _render(overlay);
    }

    /** Typed-text preview. A password is shown masked: the field itself
     *  shows dots, and the keyboard must not print it in clear for anyone
     *  next to the screen (Settings has its own "Show" button). Scrolled to
     *  the end so the most recently typed characters are the visible ones. */
    function _updateDisplay() {
        const el = document.getElementById("osk-display");
        if (!el) return;
        const masked = _activeInput && String(_activeInput.type).toLowerCase() === "password";
        el.textContent = masked ? "\u2022".repeat(_value.length) : _value;
        el.scrollLeft = el.scrollWidth;
    }

    if (typeof window !== "undefined" && window.addEventListener) {
        // The kiosk window can change size while the keyboard is open (panel
        // swapped, xrandr mode change): re-size it and re-check the field.
        window.addEventListener("resize", () => { if (_visible) _scheduleFit(); });
    }

    return { attach, key, close: _close, oskLayout, isOskInput, ROWS };
})();

if (typeof document !== "undefined") {
    // "Tap outside closes the keyboard". The decision is taken on
    // pointerdown (capture phase, before any page handler can stop it),
    // because that is the only moment the target is still the element the
    // finger actually landed on: when a field in the lower half is tapped,
    // the focus that follows builds the keyboard right under the finger, so
    // the matching click lands on the keyboard and is retargeted to <body> —
    // the old click-based check then closed the keyboard it had just opened.
    // It also closed it for every password field (only type=text was exempt).
    //
    // The close itself still waits for the click of that same tap (also in
    // the capture phase): closing on pointerdown would drop the content
    // padding mid-tap, the content would jump down, and the click would land
    // on whatever moved under the finger instead of the button the user
    // aimed at. A drag (scrolling the page) ends in pointercancel and no
    // click, so scrolling does not close the keyboard.
    //
    // Some page handlers call preventDefault() in touchend (trip planner:
    // suggestions, "Clear plan", the Travel Plan toggle), which on a
    // touchscreen suppresses the click altogether — the keyboard then stayed
    // open over most of the screen, still typing into a field the page had
    // already replaced. So pointerup arms a fallback: if no click of this tap
    // has arrived within OSK_CLICK_WAIT_MS, close anyway. By then the tap is
    // over, so dropping the padding cannot misdirect it. The click normally
    // follows pointerup within a few ms (index.html has width=device-width
    // and user-scalable=no, so Chromium adds no double-tap delay); the click
    // path disarms the timer first, so ordinary taps behave as before. Only
    // for a tap, not a drag: on an element with touch-action:none (the
    // weather map) a drag ends in pointerup without pointercancel, and
    // panning the map must not close the keyboard.
    const OSK_CLICK_WAIT_MS = 350;
    const OSK_TAP_SLOP_PX = 16;          // ~ Chromium's touch slop
    let _outsideTap = false;
    let _tapStart = null;                // {id, x, y} of the last pointerdown
    let _tapTimer = 0;
    const _disarm = () => {
        _outsideTap = false;
        if (_tapTimer) { clearTimeout(_tapTimer); _tapTimer = 0; }
    };
    document.addEventListener("focusin", (e) => {
        if (!OnScreenKeyboard.isOskInput(e.target)) return;
        // A field is being (re)attached: whatever tap led here was meant to
        // open the keyboard, not to close it (e.g. a button whose handler
        // focuses the search field), so a pending outside tap is dropped.
        _disarm();
        OnScreenKeyboard.attach(e.target);
    });
    document.addEventListener("pointerdown", (e) => {
        _disarm();
        const overlay = document.getElementById("osk-overlay");
        const t = e.target;
        _outsideTap = !!overlay && !(t && overlay.contains(t)) && !OnScreenKeyboard.isOskInput(t);
        _tapStart = { id: e.pointerId, x: Number(e.clientX) || 0, y: Number(e.clientY) || 0 };
    }, true);
    document.addEventListener("pointerup", (e) => {
        if (!_outsideTap || _tapTimer || !_tapStart || e.pointerId !== _tapStart.id) return;
        const dx = (Number(e.clientX) || 0) - _tapStart.x;
        const dy = (Number(e.clientY) || 0) - _tapStart.y;
        // A drag: no fallback. A click, if one still comes, closes as usual.
        if (dx * dx + dy * dy > OSK_TAP_SLOP_PX * OSK_TAP_SLOP_PX) return;
        _tapTimer = setTimeout(() => {
            _tapTimer = 0;
            if (!_outsideTap) return;
            _outsideTap = false;
            if (document.getElementById("osk-overlay")) OnScreenKeyboard.close();
        }, OSK_CLICK_WAIT_MS);
    }, true);
    document.addEventListener("pointercancel", _disarm, true);
    document.addEventListener("click", () => {
        if (!_outsideTap) return;
        _disarm();
        if (document.getElementById("osk-overlay")) OnScreenKeyboard.close();
    }, true);
}

if (typeof module !== "undefined" && module.exports) module.exports = OnScreenKeyboard;
