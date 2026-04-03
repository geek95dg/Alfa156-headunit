/**
 * On-Screen QWERTY Keyboard — touchscreen virtual keyboard overlay.
 * Appears when any text input is focused. Themed per active theme.
 * Position: bottom of screen (like mobile keyboards).
 */

const OnScreenKeyboard = (() => {
    let _activeInput = null;
    let _value = "";
    let _shift = false;
    let _visible = false;
    let _onInputCallback = null;

    const ROWS = [
        ["1","2","3","4","5","6","7","8","9","0"],
        ["q","w","e","r","t","y","u","i","o","p"],
        ["a","s","d","f","g","h","j","k","l"],
        ["shift","z","x","c","v","b","n","m","backspace"],
        ["space","done"],
    ];

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
        }
        _updateDisplay();
    }

    function _show() {
        _visible = true;
        let overlay = document.getElementById("osk-overlay");
        if (!overlay) {
            overlay = document.createElement("div");
            overlay.id = "osk-overlay";
            document.body.appendChild(overlay);
        }
        _render(overlay);
        // Prevent the input from losing focus on keyboard click
        overlay.addEventListener("mousedown", (e) => e.preventDefault());
        overlay.addEventListener("touchstart", (e) => e.preventDefault());
    }

    function _close() {
        _visible = false;
        if (_activeInput) {
            _activeInput.value = _value;
            _activeInput.dispatchEvent(new Event("input", { bubbles: true }));
        }
        const overlay = document.getElementById("osk-overlay");
        if (overlay) overlay.remove();
        _activeInput = null;
    }

    function _render(overlay) {
        const theme = (App && App.getTheme) ? App.getTheme() : "heritage";
        const bg = theme === "autodelta" ? "bg-[#111] border-[#FF5F00]/20"
                 : theme === "modern" ? "bg-zinc-900 border-zinc-700"
                 : "bg-[#1a0f0a] border-amber-900/40";
        const keyBg = theme === "autodelta" ? "bg-zinc-800 hover:bg-[#FF5F00]/20 active:bg-[#FF5F00]/40 text-white"
                    : theme === "modern" ? "bg-zinc-800 hover:bg-zinc-700 active:bg-zinc-600 text-white"
                    : "bg-zinc-800 hover:bg-amber-900/30 active:bg-amber-900/50 text-white";
        const accent = theme === "autodelta" ? "bg-[#FF5F00] text-white"
                     : theme === "modern" ? "bg-blue-600 text-white"
                     : "bg-amber-600 text-white";

        overlay.className = "fixed bottom-0 left-0 right-0 z-[200] p-2 border-t shadow-2xl " + bg;
        overlay.style.cssText = "backdrop-filter:blur(12px);";

        let html = `<div class="flex flex-col gap-1.5 max-w-[800px] mx-auto">`;

        // Display current value
        html += `<div class="flex items-center gap-2 px-2 mb-1">
            <span id="osk-display" class="text-sm font-mono opacity-60 truncate flex-1">${_escHtml(_value)}</span>
        </div>`;

        for (const row of ROWS) {
            html += `<div class="flex gap-1 justify-center">`;
            for (const k of row) {
                if (k === "space") {
                    html += `<button class="${keyBg} rounded-lg py-2.5 flex-[4] text-xs font-bold transition-colors" onclick="OnScreenKeyboard.key('space')">SPACE</button>`;
                } else if (k === "done") {
                    html += `<button class="${accent} rounded-lg py-2.5 flex-[2] text-xs font-bold transition-colors" onclick="OnScreenKeyboard.key('done')">OK</button>`;
                } else if (k === "shift") {
                    html += `<button class="${_shift ? accent : keyBg} rounded-lg py-2.5 px-3 text-xs font-bold transition-colors" onclick="OnScreenKeyboard.key('shift')">
                        <span class="material-symbols-outlined" style="font-size:16px;">shift</span>
                    </button>`;
                } else if (k === "backspace") {
                    html += `<button class="${keyBg} rounded-lg py-2.5 px-3 text-xs font-bold transition-colors" onclick="OnScreenKeyboard.key('backspace')">
                        <span class="material-symbols-outlined" style="font-size:16px;">backspace</span>
                    </button>`;
                } else {
                    const display = _shift ? k.toUpperCase() : k;
                    html += `<button class="${keyBg} rounded-lg py-2.5 min-w-[36px] text-sm font-bold transition-colors" onclick="OnScreenKeyboard.key('${k}')">${display}</button>`;
                }
            }
            html += `</div>`;
        }
        html += `</div>`;
        overlay.innerHTML = html;
    }

    function _renderKeys() {
        const overlay = document.getElementById("osk-overlay");
        if (overlay) _render(overlay);
    }

    function _updateDisplay() {
        const el = document.getElementById("osk-display");
        if (el) el.textContent = _value;
    }

    function _escHtml(s) {
        return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
    }

    return { attach, key, close: _close };
})();

// Auto-attach to all text inputs on focus (global handler)
document.addEventListener("focusin", (e) => {
    if (e.target && e.target.tagName === "INPUT" && e.target.type === "text") {
        OnScreenKeyboard.attach(e.target);
    }
});
