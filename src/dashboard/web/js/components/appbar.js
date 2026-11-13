/**
 * Shared Top App Bar — Alfa Romeo logo PNG center, time left, temp+icons right.
 *
 * Logo: uses single /assets/alfa_logo.png (black outline on transparent bg).
 * Per-theme CSS applies: invert for dark themes, tint via filter.
 * Place the black-outline Alfa Romeo logo PNG at:
 *   src/dashboard/web/assets/alfa_logo.png
 *
 * Phone cluster (after the date): signal bars, operator, battery — from
 * data.phone_status (bt.phone_status, src/multimedia/phone_status.py).
 * Hidden while the phone gives nothing (or the module is off: the payload
 * then carries null and the bar looks exactly as before). The operator name
 * comes from the phone network — untrusted — so it is NEVER put into the
 * markup: render() leaves its span empty and update() fills it with
 * textContent (App calls update() right after every render and every
 * second). Inline styles only: Tailwind is precompiled, new classes would
 * not exist.
 */

const AppBar = (() => {
    function _logoImg(theme) {
        // The shipped logo PNG is 8-bit grayscale with no alpha — its
        // "transparent" area is actually white pixels. Plain `filter:
        // invert(1)` flips that white to black and produces the ugly
        // square behind the mark.  `mix-blend-mode: screen` makes the
        // (post-invert) black background transparent on the black appbar
        // (screen of 0 is identity), while the white silhouette stays
        // bright and the per-theme tint comes from sepia+hue-rotate.
        // Result: clean cut-out logo, no visible rectangle.
        let filterStyle = "";
        if (theme === "heritage") {
            filterStyle = "filter: invert(1) sepia(1) saturate(3) hue-rotate(15deg) brightness(1.1);";
        } else if (theme === "modern") {
            filterStyle = "filter: invert(1) sepia(0.5) saturate(3) hue-rotate(-25deg) brightness(1.05);";
        } else if (theme === "autodelta") {
            filterStyle = "filter: invert(1) sepia(1) saturate(5) hue-rotate(-10deg) brightness(1.2);";
        }
        // h-16 (~64px logical → ~74px after 1.15 root-rem bump) with
        // negative vertical margin so the larger logo can overhang the
        // 56-logical-px (~64px) appbar without forcing a layout reflow.
        const cls = "appbar-logo h-16 w-auto object-contain -my-2";
        const style = `${filterStyle} mix-blend-mode: screen;`;
        return `<img src="/assets/alfa_logo.png" alt="Alfa Romeo" class="${cls}" style="${style}" onerror="this.parentElement.innerHTML='<span class=\\'text-base font-bold\\'>AR</span>';">`;
    }

    function render(theme, data) {
        const time = _formatTime();
        const date = _formatDate();
        const temp = _formatTemp(data);
        const btClass = data.bt_connected ? "text-green-500" : "text-zinc-600";
        // Pixel bumps for 7" touchscreen (matches navbar): icons go
        // 16/24 → 19/28 px, fonts text-sm → text-base, height h-12 → h-14.
        const btIcon = `<span class="material-symbols-outlined ${btClass}" style="font-size:19px;font-variation-settings:'FILL' ${data.bt_connected ? 1 : 0};">bluetooth</span>`;

        const bgColor = theme === "autodelta" ? "bg-[#111111] border-[#222222]"
            : "bg-black border-zinc-800";

        const timeColor = theme === "autodelta" ? "text-white" : theme === "modern" ? "text-white" : "text-zinc-400";
        const tempColor = theme === "autodelta" ? "text-[#FF5F00]" : theme === "modern" ? "text-white" : "text-zinc-500";

        // Both side blocks widen together while the phone cluster shows, so
        // the logo stays centred (inline width beats the w-[220px] class).
        const pv = phoneView(data);
        const sideStyle = pv.visible ? ` style="width:${PHONE_WIDE_PX}px"` : "";

        return `<header class="w-full h-14 ${bgColor} border-b flex items-center px-4 shrink-0 z-50">
            <div class="flex items-center gap-2 w-[220px]" data-bind="bar_left"${sideStyle}>
                <span class="text-base font-bold ${timeColor}" data-bind="time">${time}</span>
                <span class="text-xs font-bold text-zinc-600 uppercase" data-bind="date">${date}</span>
                ${_phoneCluster(pv)}
            </div>
            <div class="flex-1 flex justify-center">
                ${_logoImg(theme)}
            </div>
            <div class="flex items-center gap-4 w-[220px] justify-end" data-bind="bar_right"${sideStyle}>
                <span class="${tempColor} text-base font-bold" data-bind="ext_temp">${temp}</span>
                ${btIcon}
                <span class="material-symbols-outlined text-zinc-600 cursor-pointer hover:text-zinc-400 p-1" style="font-size:28px;" onclick="App.navigateTo('audio')">equalizer</span>
                <span class="material-symbols-outlined text-zinc-600 cursor-pointer hover:text-zinc-400 p-1" style="font-size:28px;" onclick="App.navigateTo('settings')">settings</span>
                <span class="material-symbols-outlined text-zinc-600 cursor-pointer hover:text-red-400 p-1" style="font-size:26px;" title="Restart kiosku" onclick="App.restartKioskModal()">restart_alt</span>
            </div>
        </header>`;
    }

    function _formatTime() {
        const now = new Date();
        // hourCycle "h23", not hour12:false: with en-US, hour12:false picks
        // the h24 cycle in Chromium and midnight renders as "24:05".
        return now.toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit", hourCycle: "h23" });
    }

    function _formatDate() {
        const now = new Date();
        const dayKeys = ["sun","mon","tue","wed","thu","fri","sat"];
        const monthKeys = ["jan","feb","mar","apr","may","jun","jul","aug","sep","oct","nov","dec"];
        const day = (App && App.t) ? App.t(dayKeys[now.getDay()]) : dayKeys[now.getDay()].toUpperCase();
        const month = (App && App.t) ? App.t(monthKeys[now.getMonth()]) : monthKeys[now.getMonth()].toUpperCase();
        return `${day} ${month} ${now.getDate()}`;
    }

    function _formatTemp(data) {
        const temp = data.ext_temp;
        if (temp == null) return "--";
        const unit = (App && App.getConfig().temp_unit) || "C";
        if (unit === "F") return `${Math.round(temp * 9/5 + 32)}\u00b0F`;
        return `${Math.round(temp)}\u00b0C`;
    }

    function _setText(el, text) {
        // Only touch the DOM on a change — App's clock calls this every
        // second and a no-op write still costs a style/layout pass.
        if (el && el.textContent !== text) el.textContent = text;
    }

    function _setStyle(el, prop, value) {
        // Change-only as well (see _setText). Only for values the browser
        // reads back verbatim (display keywords, "340px", ""): a colour is
        // read back normalised ("#dc2626" -> "rgb(220, 38, 38)"), so the
        // comparison would never match — colours go through _setLow().
        if (el && el.style && el.style[prop] !== value) el.style[prop] = value;
    }

    function _setLow(el, low) {
        // Low-battery colour, change-only: the flag lives in data-low (set
        // by render() too), so the colour is written only when it flips.
        if (!el || !el.style || typeof el.getAttribute !== "function") return;
        const flag = low ? "1" : "";
        if ((el.getAttribute("data-low") || "") === flag) return;
        el.setAttribute("data-low", flag);
        el.style.color = low ? BATTERY_LOW_COLOR : "";
    }

    // --- Phone cluster ---------------------------------------------------
    // Glyph names checked against the bundled font's ligature table
    // (assets/fonts/material-symbols-latin.ttf): signal_cellular_{0..4}_bar,
    // signal_cellular_off, battery_{0..6}_bar and battery_full all exist.
    const PHONE_WIDE_PX = 340;          // side blocks while the cluster shows
    const OPERATOR_MAX = 24;            // backend cuts to 24 already
    const BATTERY_LOW_PCT = 15;
    const BATTERY_LOW_COLOR = "#dc2626";
    const NO_SERVICE = ["searching", "denied", "unregistered"];
    const HIDDEN_VIEW = Object.freeze({ visible: false, signal: null, operator: "", roaming: false,
                                        battery: null, batteryText: "", low: false });

    function _isPct(v) {
        return typeof v === "number" && isFinite(v) && v >= 0 && v <= 100;
    }

    /** Pure: signal percent (0-100) → glyph name, or null (not reported).
     *  0-100 maps linearly onto the font's 0-4 bars; no service → "off". */
    function signalIcon(pct, registration) {
        if (NO_SERVICE.indexOf(registration) !== -1) return "signal_cellular_off";
        if (!_isPct(pct)) return null;
        return "signal_cellular_" + Math.min(4, Math.round(pct / 25)) + "_bar";
    }

    /** Pure: battery percent → glyph name (0-6 bars, full at 100), or null. */
    function batteryIcon(pct) {
        if (!_isPct(pct)) return null;
        if (pct >= 100) return "battery_full";
        return "battery_" + Math.min(6, Math.floor(pct * 7 / 100)) + "_bar";
    }

    /** Pure: what the cluster shows for this payload. Never throws. */
    function phoneView(data) {
        const ps = data && data.phone_status;
        if (!ps || typeof ps !== "object" || ps.available !== true) return HIDDEN_VIEW;
        const registration = typeof ps.registration === "string" ? ps.registration : null;
        const signal = signalIcon(ps.signal_pct, registration);
        const operator = typeof ps.operator === "string" ? ps.operator.slice(0, OPERATOR_MAX) : "";
        const battery = batteryIcon(ps.battery_pct);
        if (!signal && !operator && !battery) return HIDDEN_VIEW;
        return {
            visible: true, signal, operator, roaming: ps.roaming === true, battery,
            batteryText: battery ? Math.round(ps.battery_pct) + "%" : "",
            low: battery !== null && ps.battery_pct <= BATTERY_LOW_PCT,
        };
    }

    /** Skeleton of the cluster. Only glyph names and numbers from phoneView()
     *  go into the markup — the operator span stays empty (update() fills it
     *  with textContent). */
    function _phoneCluster(pv) {
        const disp = (on, how) => "display:" + (on ? how : "none") + ";";
        return `<span data-bind="phone" style="${disp(pv.visible, "inline-flex")}align-items:center;gap:4px;margin-left:4px;white-space:nowrap;">`
            + `<span class="material-symbols-outlined text-zinc-600" data-bind="phone_signal" style="font-size:18px;${disp(!!pv.signal, "inline-block")}">${pv.signal || ""}</span>`
            + `<span class="text-xs font-bold text-zinc-600" data-bind="phone_roaming" style="${disp(pv.roaming, "inline")}">R</span>`
            + `<span class="text-xs font-bold text-zinc-600" data-bind="phone_operator" style="max-width:110px;overflow:hidden;text-overflow:ellipsis;${disp(!!pv.operator, "inline-block")}"></span>`
            + `<span class="material-symbols-outlined text-zinc-600" data-bind="phone_battery" data-low="${pv.low ? "1" : ""}" style="font-size:18px;${disp(!!pv.battery, "inline-block")}${pv.low ? "color:" + BATTERY_LOW_COLOR + ";" : ""}">${pv.battery || ""}</span>`
            + `<span class="text-xs font-bold text-zinc-600" data-bind="phone_battery_pct" style="${disp(!!pv.battery, "inline")}">${pv.batteryText}</span>`
            + `</span>`;
    }

    /** Bring an existing cluster in line with `data` — writes only what changed. */
    function _updatePhone(container, data) {
        const cluster = container.querySelector('[data-bind="phone"]');
        if (!cluster) return;
        const pv = phoneView(data);
        const wide = pv.visible ? PHONE_WIDE_PX + "px" : "";
        _setStyle(container.querySelector('[data-bind="bar_left"]'), "width", wide);
        _setStyle(container.querySelector('[data-bind="bar_right"]'), "width", wide);
        _setStyle(cluster, "display", pv.visible ? "inline-flex" : "none");
        if (!pv.visible || typeof cluster.querySelector !== "function") return;
        const part = (name) => cluster.querySelector('[data-bind="' + name + '"]');

        const signal = part("phone_signal");
        _setStyle(signal, "display", pv.signal ? "inline-block" : "none");
        if (pv.signal) _setText(signal, pv.signal);
        _setStyle(part("phone_roaming"), "display", pv.roaming ? "inline" : "none");
        const operator = part("phone_operator");
        _setStyle(operator, "display", pv.operator ? "inline-block" : "none");
        _setText(operator, pv.operator);     // textContent: untrusted network text
        const battery = part("phone_battery");
        _setStyle(battery, "display", pv.battery ? "inline-block" : "none");
        _setLow(battery, pv.low);
        if (pv.battery) _setText(battery, pv.battery);
        const pct = part("phone_battery_pct");
        _setStyle(pct, "display", pv.battery ? "inline" : "none");
        _setText(pct, pv.batteryText);
    }

    /** Refresh time/date/temperature and the phone cluster in place.
     *  `container` is anything with querySelector (App's clock passes
     *  `document`); screens without an AppBar (A2) simply have no data-bind
     *  nodes. */
    function update(container, data) {
        if (!container || typeof container.querySelector !== "function") return;
        _setText(container.querySelector('[data-bind="time"]'), _formatTime());
        _setText(container.querySelector('[data-bind="date"]'), _formatDate());
        _setText(container.querySelector('[data-bind="ext_temp"]'), _formatTemp(data || {}));
        _updatePhone(container, data || {});
    }

    return { render, update, phoneView, signalIcon, batteryIcon };
})();

if (typeof module !== "undefined" && module.exports) module.exports = AppBar;
