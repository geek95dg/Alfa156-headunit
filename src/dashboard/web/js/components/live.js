/**
 * Live readings for A5 (Serwis) and A7 (Osiągi) — data.live from
 * web_viewer._live_metrics(): {name: {v, src} | null}.
 *
 * One rule for every screen that uses it: a reading is shown only when the
 * backend vouched for it (real source, fresh, in range). Otherwise the value
 * is "—" with a grey "brak danych" — never a made-up placeholder (the old
 * screens showed 12.6 V, 2.4 bar tyres and "All OK" with no sensor at all).
 * Pure functions, no DOM; exported for the node tests.
 */
const Live = (() => {
    const t = (k, d) => (typeof App !== "undefined" && App.t ? App.t(k, d) : d);

    const COLORS = { ok: "#22c55e", warn: "#f59e0b", bad: "#ef4444", none: "#71717a" };
    const SOURCES = { obd: "OBD", gps: "GPS", phone: "telefon", batt: "BATT",
                      tpms: "TPMS", service: "serwis", demo: "demo" };

    /** The entry for `name`, or null when there is no trustworthy value. */
    function get(data, name) {
        const live = data && typeof data.live === "object" && data.live ? data.live : null;
        const e = live ? live[name] : null;
        if (!e || typeof e !== "object") return null;
        if (Array.isArray(e.v)) return e.v.every(Number.isFinite) ? e : null;
        return Number.isFinite(e.v) ? e : null;
    }

    /** "12.4V" / "—". */
    function fmt(e, digits, unit) {
        if (!e || !Number.isFinite(e.v)) return "—";
        return e.v.toFixed(digits) + (unit || "");
    }

    /** Short source tag ("GPS", "OBD", "demo"…), "" without a reading. */
    function src(e) {
        return e && typeof e.src === "string" && SOURCES[e.src] ? SOURCES[e.src] : "";
    }

    /** {level: ok|warn|bad|none, text, color} for a card's corner label.
     *  `judge(v)` returns "ok" | "warn" | "bad". */
    function status(e, judge) {
        if (!e) return { level: "none", text: t("live_no_data", "brak danych"), color: COLORS.none };
        const level = judge ? judge(e.v) : "ok";
        const text = level === "ok" ? t("ok", "OK") : t("warning", "OSTRZEŻENIE");
        return { level, text, color: COLORS[level] || COLORS.ok };
    }

    // Thresholds for the service cards (Alfa 156 1.9 JTD, 12 V AGM buffer).
    const JUDGE = {
        coolant: (c) => (c > 105 ? "bad" : c > 100 ? "warn" : "ok"),
        // Below 11.8 V the battery is flat; above 14.9 V the charger misbehaves.
        battery_v: (v) => (v < 11.8 || v > 14.9 ? "bad" : v < 12.2 ? "warn" : "ok"),
        oil_level: (p) => (p < 10 ? "bad" : p < 25 ? "warn" : "ok"),
        oil_pressure: (b) => (b < 0.5 ? "bad" : "ok"),
        tpms: (arr) => (arr.some((p) => p < 1.6) ? "bad" : arr.some((p) => p < 2.0) ? "warn" : "ok"),
    };

    /** The A5 header badge: no reading at all → "brak danych z auta";
     *  any warning → "OSTRZEŻENIE"; else "WSZYSTKO OK". */
    function overall(data) {
        const names = ["coolant", "battery_v", "oil_level", "oil_pressure", "tpms"];
        let have = 0;
        let worst = "ok";
        for (const name of names) {
            const e = get(data, name);
            if (!e) continue;
            have++;
            const lv = JUDGE[name](e.v);
            if (lv === "bad" || (lv === "warn" && worst === "ok")) worst = lv;
        }
        if (!have) return { level: "none", text: t("live_no_car_data", "brak danych z auta"), color: COLORS.none };
        // "OK" only speaks for what was measured: "WSZYSTKO OK · 1/5".
        const part = have < names.length ? ` · ${have}/${names.length}` : "";
        if (worst === "ok") return { level: "ok", text: t("all_ok", "WSZYSTKO OK") + part, color: COLORS.ok };
        return { level: worst, text: t("warning", "OSTRZEŻENIE"), color: COLORS[worst] };
    }

    return { get, fmt, src, status, overall, JUDGE, COLORS };
})();

if (typeof module !== "undefined" && module.exports) module.exports = Live;
