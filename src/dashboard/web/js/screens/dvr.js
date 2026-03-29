/**
 * A6 DVR Recordings Browser — browse, play, export recordings.
 * Full implementation in Phase 8.
 */

App.registerScreen("a6", (() => {
    function render(container, theme, data) {
        const t = App.t.bind(App);
        const bgCls = theme === "modern" ? "bg-slate-100 text-slate-900" : "bg-black text-white";
        const cardBg = theme === "modern" ? "bg-white border-slate-200" : "bg-zinc-900 border-zinc-800";
        const accentClr = theme === "autodelta" ? "text-[#FF5F00]" : theme === "modern" ? "text-blue-600" : "text-amber-500";

        container.innerHTML = `<div class="screen-container ${bgCls}">
            ${AppBar.render(theme, data)}
            <main class="content-area p-4">
                <div class="flex justify-between items-center mb-4">
                    <h1 class="text-xl font-bold ${accentClr}">${t("dvr", "DVR Recordings")}</h1>
                    <div class="flex gap-2">
                        <button class="${cardBg} border px-3 py-1.5 rounded-lg text-sm font-bold opacity-60">${t("dvr_front", "Front")}</button>
                        <button class="${cardBg} border px-3 py-1.5 rounded-lg text-sm font-bold opacity-60">${t("dvr_rear", "Rear")}</button>
                    </div>
                </div>
                <div class="grid grid-cols-3 gap-3 flex-1">
                    ${[1,2,3,4,5,6].map(i => `<div class="${cardBg} border rounded-xl p-3 flex flex-col items-center justify-center gap-2 opacity-40">
                        <span class="material-symbols-outlined text-3xl">movie</span>
                        <span class="text-[10px] font-bold">REC_${String(i).padStart(3,'0')}.mp4</span>
                        <span class="text-[9px] opacity-60">--:-- · --MB</span>
                    </div>`).join("")}
                </div>
                <div class="flex justify-between items-center mt-3">
                    <span class="text-[10px] opacity-40">Storage: --/128 GB</span>
                    <button class="${cardBg} border px-4 py-2 rounded-lg text-sm font-bold flex items-center gap-2 opacity-60">
                        <span class="material-symbols-outlined" style="font-size:16px;">usb</span>
                        ${t("dvr_export", "Export to USB")}
                    </button>
                </div>
            </main>
            ${NavBar.render(theme, "a6")}
        </div>`;
    }

    return { render };
})());
