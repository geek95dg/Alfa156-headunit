/**
 * A7 Performance Screen — boost gauge, speed, RPM, 0-100 timer, G-force.
 *
 * Values come from data.live (web_viewer._live_metrics) through Live
 * (components/live.js): only real, fresh readings; "—" otherwise. In the car
 * today that means speed from the phone's GPS (OBD speed when the K-Line
 * works), G-force from the phone's accelerometer (calibrated mount only) and
 * the 0-100 km/h time from src/performance/timer.py (GPS speed). RPM, boost
 * and its peak need OBD; the voltage needs the battery monitor.
 */

App.registerScreen("a7", (() => {
    const ARC_LEN = Math.PI * 80;       // the gauge path is a half circle, r = 80
    const BOOST_MAX = 1.5;              // bar, full scale of the gauge
    let _best = null;                   // best 0-100 time this session (s)

    function render(container, theme, data) {
        const t = App.t.bind(App);
        const bgCls = theme === "modern" ? "bg-slate-100 text-slate-900" : "bg-black text-white";
        const cardBg = theme === "modern" ? "bg-white border-slate-200 shadow-sm" : "bg-zinc-900 border-zinc-800";
        const accentClr = theme === "autodelta" ? "#FF5F00" : theme === "modern" ? "#005596" : "#f59e0b";
        const track = theme === "modern" ? "#e2e8f0" : "#27272a";
        const tag = (id) => `<span id="perf-${id}-src" class="text-[9px] opacity-40"></span>`;

        container.innerHTML = `<div class="screen-container ${bgCls}">
            ${AppBar.render(theme, data)}
            <main class="content-area p-4 flex gap-4">
                <div class="flex flex-col items-center justify-center w-[240px] shrink-0">
                    <svg viewBox="0 0 180 120" class="w-full">
                        <path d="M 10,100 A 80,80 0 0,1 170,100" fill="none" stroke="${track}" stroke-width="12" stroke-linecap="round"/>
                        <path id="perf-boost-arc" d="M 10,100 A 80,80 0 0,1 170,100" fill="none" stroke="${accentClr}" stroke-width="12" stroke-linecap="round"
                              stroke-dasharray="${ARC_LEN}" stroke-dashoffset="${ARC_LEN}" style="transition:stroke-dashoffset 0.5s;"/>
                    </svg>
                    <div class="text-center -mt-8">
                        <span id="perf-boost" class="text-4xl font-black" style="color:${accentClr};">—</span>
                        <span class="text-sm opacity-50 ml-1">BAR</span>
                    </div>
                    <span class="text-[10px] font-bold uppercase tracking-wider opacity-40 mt-2">${t("boost", "BOOST")} ${tag("boost")}</span>
                    <span id="perf-boost-note" class="text-[9px] mt-1" style="color:${Live.COLORS.none}"></span>
                </div>
                <div class="flex-1 grid grid-cols-2 gap-3">
                    <div class="${cardBg} border rounded-xl p-4 flex flex-col justify-center items-center">
                        <span class="text-[9px] font-bold uppercase opacity-40">${t("speed", "SPEED")} ${tag("speed")}</span>
                        <span id="perf-speed" class="text-4xl font-black">—</span>
                        <span class="text-xs opacity-40">km/h</span>
                    </div>
                    <div class="${cardBg} border rounded-xl p-4 flex flex-col justify-center items-center">
                        <span class="text-[9px] font-bold uppercase opacity-40">RPM ${tag("rpm")}</span>
                        <span id="perf-rpm" class="text-3xl font-black">—</span>
                        <div class="w-full h-1.5 rounded-full mt-2" style="background:${track};">
                            <div id="perf-rpm-bar" class="h-full rounded-full transition-all" style="width:0%;background:${accentClr};"></div>
                        </div>
                    </div>
                    <div class="${cardBg} border rounded-xl p-4 flex flex-col justify-center items-center">
                        <span class="text-[9px] font-bold uppercase opacity-40">${t("timer_0_100", "0-100 km/h")}</span>
                        <span id="perf-timer" class="text-3xl font-black">—</span>
                        <span id="perf-best" class="text-[9px] opacity-30">${t("best_time", "Best")}: —</span>
                    </div>
                    <div class="${cardBg} border rounded-xl p-4 flex flex-col justify-center items-center">
                        <span class="text-[9px] font-bold uppercase opacity-40">${t("g_force", "G-FORCE")} ${tag("g")}</span>
                        <span id="perf-g" class="text-3xl font-black">—</span>
                        <span class="text-xs opacity-40">G</span>
                    </div>
                    <div class="${cardBg} border rounded-xl p-3 flex items-center justify-between col-span-2">
                        <div>
                            <span class="text-[9px] font-bold uppercase opacity-40">${t("peak_boost", "PEAK BOOST")}</span>
                            <div class="text-xl font-black" style="color:${accentClr};"><span id="perf-peak">—</span> <span class="text-xs opacity-50">BAR</span></div>
                        </div>
                        <div>
                            <span class="text-[9px] font-bold uppercase opacity-40">${t("voltage", "VOLTAGE")} ${tag("volt")}</span>
                            <div class="text-xl font-black"><span id="perf-volt">—</span> <span class="text-xs opacity-50">V</span></div>
                        </div>
                    </div>
                </div>
            </main>
            ${NavBar.render(theme, "a7")}
        </div>`;
        update(data);
    }

    function update(data) {
        const boost = Live.get(data, "boost");
        const speed = Live.get(data, "speed");
        const rpm = Live.get(data, "rpm");
        const g = Live.get(data, "g_h");
        const volt = Live.get(data, "battery_v");
        const timer = Live.get(data, "timer_last");

        _text("perf-boost", Live.fmt(boost, 2, ""));
        _text("perf-speed", Live.fmt(speed, 0, ""));
        _text("perf-rpm", Live.fmt(rpm, 0, ""));
        _text("perf-g", Live.fmt(g, 2, ""));
        _text("perf-volt", Live.fmt(volt, 1, ""));
        _text("perf-peak", Live.fmt(Live.get(data, "boost_peak"), 2, ""));
        _text("perf-boost-note", boost ? "" : App.t("live_needs_obd", "doładowanie i obroty: potrzebne OBD"));
        for (const [id, e] of [["boost", boost], ["speed", speed], ["rpm", rpm], ["g", g], ["volt", volt]]) {
            const s = Live.src(e);
            _text(`perf-${id}-src`, s ? "· " + s : "");
        }

        if (timer) {
            _text("perf-timer", timer.v.toFixed(1) + " s");
            if (_best === null || timer.v < _best) _best = timer.v;
        }
        _text("perf-best", `${App.t("best_time", "Best")}: ${_best === null ? "—" : _best.toFixed(1) + " s"}`);

        const bar = document.getElementById("perf-rpm-bar");
        const w = rpm ? `${Math.min(100, rpm.v / 50)}%` : "0%";
        if (bar && bar.style.width !== w) bar.style.width = w;
        const arc = document.getElementById("perf-boost-arc");
        if (arc) {
            const pct = boost ? Math.min(1, Math.max(0, boost.v / BOOST_MAX)) : 0;
            arc.setAttribute("stroke-dashoffset", String(ARC_LEN * (1 - pct)));
        }
    }

    function _text(id, text) {
        const el = document.getElementById(id);
        if (el && el.textContent !== text) el.textContent = text;
    }

    return { render, update };
})());
