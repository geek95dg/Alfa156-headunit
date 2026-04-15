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
                <span class="material-symbols-outlined ${iconColor}">${n.icon}</span>
                <div>
                    <p class="text-xs font-bold text-zinc-200">${n.title}</p>
                    <p class="text-[10px] text-zinc-500 mt-0.5">${n.desc}</p>
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
                    <span class="material-symbols-outlined" style="font-size:20px;">${n.icon}</span>
                </div>
                <div>
                    <div class="text-xs font-bold text-slate-800">${n.title}</div>
                    <div class="text-[11px] text-slate-500 mt-0.5">${n.desc}</div>
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
                <span class="material-symbols-outlined ${iconColor}" style="font-size:28px;">${n.icon}</span>
            </div>
            <div class="flex flex-col">
                <h4 class="text-xl font-bold text-white mb-1">${n.title}</h4>
                <p class="text-gray-400 text-sm leading-relaxed">${n.desc}</p>
            </div>
        </div>`;
    }

    return { getNotifications, renderHeritage, renderModern, renderAutodelta };
})();
