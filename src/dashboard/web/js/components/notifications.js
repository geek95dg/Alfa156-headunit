/**
 * Notification rendering component — theme-aware.
 */

const Notifications = (() => {
    const SEVERITY_ICONS = {
        warning: "warning",
        danger: "oil_barrel",
        info: "route",
        tire: "tire_repair",
        nav: "navigation",
        service: "calendar_month",
        check: "check_circle",
    };

    // The card renderers below build innerHTML; entries may come from the
    // backend (system.notifications), so every field is escaped and the icon
    // must be a plain glyph name. (The toasts further down use textContent.)
    function _esc(v) {
        return String(v == null ? "" : v).replace(/&/g, "&amp;").replace(/</g, "&lt;")
            .replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#39;");
    }
    function _icon(v) {
        return /^[a-z0-9_]{1,40}$/.test(v || "") ? v : "info";
    }

    /** Generate demo notifications if none from backend */
    function getNotifications(data) {
        const notifs = data.notifications;
        if (notifs && notifs.length > 0) return notifs;

        // Generate from live data
        const items = [];
        const tpms = data.tpms_pressures || [0, 0, 0, 0];
        const lowTire = tpms.findIndex(p => p > 0 && p < 2.0);
        if (lowTire >= 0) {
            const pos = ["Front Left", "Front Right", "Rear Left", "Rear Right"][lowTire];
            items.push({
                severity: "warning",
                icon: "tire_repair",
                title: "Low Tire Pressure",
                desc: `${pos}: ${tpms[lowTire].toFixed(1)} BAR. Check at next stop.`,
            });
        }
        if (data.service_km < 1000) {
            items.push({
                severity: "danger",
                icon: "oil_barrel",
                title: "Maintenance Due",
                desc: `Scheduled oil change in ${data.service_km} km.`,
            });
        }
        // Always show at least one
        if (items.length === 0) {
            items.push({
                severity: "info",
                icon: "check_circle",
                title: "Systems Nominal",
                desc: "All parameters within optimal range.",
            });
        }
        return items;
    }

    function renderHeritage(notifications) {
        const items = notifications.map(n => {
            const borderColor = n.severity === "danger" ? "border-red-600"
                : n.severity === "warning" ? "border-amber-600" : "border-zinc-700";
            const iconColor = n.severity === "danger" ? "text-red-600"
                : n.severity === "warning" ? "text-amber-600" : "text-zinc-400";
            const opacity = n.severity === "info" ? "opacity-70" : "";
            return `<div class="bg-zinc-900/50 p-3 rounded-lg border-l-2 ${borderColor} flex gap-4 items-start ${opacity}">
                <span class="material-symbols-outlined ${iconColor}">${_icon(n.icon)}</span>
                <div>
                    <p class="text-xs font-bold text-zinc-200">${_esc(n.title)}</p>
                    <p class="text-[10px] text-zinc-500 mt-0.5">${_esc(n.desc)}</p>
                </div>
            </div>`;
        }).join("");
        return items;
    }

    function renderModern(notifications) {
        const items = notifications.map(n => {
            const borderColor = n.severity === "danger" ? "border-red-500"
                : n.severity === "warning" ? "border-amber-500" : "border-slate-200";
            const iconColor = n.severity === "danger" ? "text-red-600"
                : n.severity === "warning" ? "text-amber-600" : "text-slate-400";
            return `<div class="flex gap-3 items-start p-3 rounded-lg border-l-4 ${borderColor}">
                <div class="bg-white p-2 rounded-lg shadow-sm ${iconColor}">
                    <span class="material-symbols-outlined" style="font-size:20px;">${_icon(n.icon)}</span>
                </div>
                <div>
                    <div class="text-xs font-bold text-slate-800">${_esc(n.title)}</div>
                    <div class="text-[11px] text-slate-500 mt-0.5">${_esc(n.desc)}</div>
                </div>
            </div>`;
        }).join("");
        return items;
    }

    function renderAutodelta(notifications) {
        const n = notifications[0] || { icon: "check_circle", title: "Systems Nominal", desc: "All telemetry parameters within optimal range." };
        const iconColor = n.severity === "danger" ? "text-red-500"
            : n.severity === "warning" ? "text-amber-500" : "text-green-500";
        return `<div class="bg-gradient-to-br from-[#1a1a1a] to-[#0a0a0a] border border-[#333333] rounded-xl p-6 flex items-start gap-4 shadow-xl">
            <div class="w-12 h-12 rounded-full bg-[#222222] flex items-center justify-center shrink-0 border border-[#444444]">
                <span class="material-symbols-outlined ${iconColor}" style="font-size:28px;">${_icon(n.icon)}</span>
            </div>
            <div class="flex flex-col">
                <h4 class="text-xl font-bold text-white mb-1">${_esc(n.title)}</h4>
                <p class="text-gray-400 text-sm leading-relaxed">${_esc(n.desc)}</p>
            </div>
        </div>`;
    }

    // --- Toasts for backend announcements (system.notifications) ---------
    //
    // src/core/notifications.py publishes short-lived entries {id, severity,
    // icon, title, desc, ttl}; web_viewer drops expired ones from the
    // payload. Each id is shown once, as a toast on top of whatever screen is
    // active (A2/AA included). Text arrives from the backend and is rendered
    // with textContent only — never innerHTML. Inline styles only: Tailwind
    // is precompiled, new classes would not exist.
    const TOAST_MAX_VISIBLE = 3;
    const TOAST_MAX_MS = 10000;
    const SEEN_MAX = 50;
    const _seen = [];
    const TOAST_COLORS = { danger: "#dc2626", warning: "#f59e0b", info: "#71717a" };

    /** Entries of `list` not in `seen` that are worth a toast. Pure. */
    function pendingToasts(list, seen) {
        if (!Array.isArray(list)) return [];
        return list.filter((n) => n && typeof n === "object"
            && (typeof n.id === "string" || typeof n.id === "number")
            && typeof n.title === "string" && n.title
            && seen.indexOf(String(n.id)) === -1);
    }

    function _remember(id) {
        _seen.push(String(id));
        while (_seen.length > SEEN_MAX) _seen.shift();
    }

    function _toastHost(doc) {
        let host = doc.getElementById("bcm-toast-host");
        if (!host) {
            host = doc.createElement("div");
            host.id = "bcm-toast-host";
            host.style.cssText = "position:fixed;top:56px;left:50%;transform:translateX(-50%);"
                + "z-index:400;display:flex;flex-direction:column;gap:8px;align-items:center;"
                + "pointer-events:none;max-width:90vw;";
            (doc.body || doc.documentElement).appendChild(host);
        }
        return host;
    }

    function _showToast(doc, n) {
        const host = _toastHost(doc);
        while (host.children.length >= TOAST_MAX_VISIBLE) host.removeChild(host.firstChild);
        const box = doc.createElement("div");
        box.setAttribute("role", "status");
        box.style.cssText = "display:flex;gap:12px;align-items:center;padding:10px 16px;"
            + "border-radius:10px;background:rgba(15,15,15,0.94);color:#fff;"
            + "box-shadow:0 6px 24px rgba(0,0,0,0.5);border-left:4px solid "
            + (TOAST_COLORS[n.severity] || TOAST_COLORS.info) + ";max-width:90vw;";
        const icon = doc.createElement("span");
        icon.className = "material-symbols-outlined";
        icon.style.cssText = "font-size:26px;color:" + (TOAST_COLORS[n.severity] || TOAST_COLORS.info) + ";";
        icon.textContent = /^[a-z0-9_]{1,40}$/.test(n.icon || "") ? n.icon : "info";
        const text = doc.createElement("div");
        const title = doc.createElement("div");
        title.style.cssText = "font-size:15px;font-weight:700;line-height:1.25;";
        title.textContent = String(n.title).slice(0, 120);
        text.appendChild(title);
        if (n.desc) {
            const desc = doc.createElement("div");
            desc.style.cssText = "font-size:12px;opacity:0.7;margin-top:2px;";
            desc.textContent = String(n.desc).slice(0, 240);
            text.appendChild(desc);
        }
        box.appendChild(icon);
        box.appendChild(text);
        host.appendChild(box);
        const ttl = Number(n.ttl) > 0 ? Number(n.ttl) * 1000 : 6000;
        setTimeout(() => { if (box.parentNode) box.parentNode.removeChild(box); },
                   Math.min(TOAST_MAX_MS, ttl));
    }

    /** Show a toast for every new backend notification. Never throws. */
    function syncToasts(list, doc) {
        try {
            const d = doc || (typeof document !== "undefined" ? document : null);
            for (const n of pendingToasts(list, _seen)) {
                _remember(n.id);
                if (d) _showToast(d, n);
            }
        } catch (e) { /* a toast must never break the data loop */ }
    }

    return { getNotifications, renderHeritage, renderModern, renderAutodelta,
             pendingToasts, syncToasts };
})();

if (typeof module !== "undefined" && module.exports) module.exports = Notifications;
