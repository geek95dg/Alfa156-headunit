/**
 * A6 DVR Recordings Browser — browse, play, export.
 * Fetches recording list from /api/dvr/list.
 */

App.registerScreen("a6", (() => {
    let _recordings = [];
    let _filter = "all"; // "all", "front", "rear"
    let _selectedFiles = new Set();

    function render(container, theme, data) {
        const t = App.t.bind(App);
        const bgCls = theme === "modern" ? "bg-slate-100 text-slate-900" : "bg-black text-white";
        const cardBg = theme === "modern" ? "bg-white border-slate-200 shadow-sm" : "bg-zinc-900 border-zinc-800";
        const accentClr = theme === "autodelta" ? "text-[#FF5F00]" : theme === "modern" ? "text-blue-600" : "text-amber-500";
        const btnBg = theme === "modern" ? "bg-slate-100 hover:bg-slate-200 text-slate-700" : "bg-zinc-800 hover:bg-zinc-700 text-zinc-300";

        container.innerHTML = `<div class="screen-container ${bgCls}">
            ${AppBar.render(theme, data)}
            <main class="content-area p-3 flex flex-col">
                <!-- Header -->
                <div class="flex justify-between items-center mb-2">
                    <h1 class="text-lg font-bold ${accentClr}">${t("dvr")}</h1>
                    <div class="flex gap-2">
                        <button class="${btnBg} px-3 py-1 rounded-lg text-xs font-bold ${_filter==='all'?'ring-1 ring-current':''}" onclick="App._dvrFilter('all')">${t("all_ok","All")}</button>
                        <button class="${btnBg} px-3 py-1 rounded-lg text-xs font-bold ${_filter==='front'?'ring-1 ring-current':''}" onclick="App._dvrFilter('front')">${t("dvr_front")}</button>
                        <button class="${btnBg} px-3 py-1 rounded-lg text-xs font-bold ${_filter==='rear'?'ring-1 ring-current':''}" onclick="App._dvrFilter('rear')">${t("dvr_rear")}</button>
                    </div>
                </div>
                <!-- Recording grid -->
                <div id="dvr-grid" class="grid grid-cols-4 gap-2 flex-1 overflow-y-auto">
                    ${_renderRecordings(cardBg, accentClr)}
                </div>
                <!-- Footer: storage + export -->
                <div class="flex justify-between items-center mt-2 pt-2 ${theme==='modern'?'border-slate-200':'border-zinc-800'} border-t">
                    <div class="flex items-center gap-3">
                        <span class="text-[10px] opacity-50" id="dvr-storage">--</span>
                        <span class="text-[10px] opacity-50" id="dvr-count">${_recordings.length} ${t("dvr","recordings")}</span>
                    </div>
                    <button class="${btnBg} px-4 py-2 rounded-lg text-xs font-bold flex items-center gap-2" onclick="App._dvrExport()">
                        <span class="material-symbols-outlined" style="font-size:16px;">usb</span>
                        ${t("dvr_export")}
                    </button>
                </div>
            </main>
            ${NavBar.render(theme, "a6")}
        </div>`;

        // Load recordings
        _loadRecordings();
    }

    function _renderRecordings(cardBg, accentClr) {
        if (_recordings.length === 0) {
            return `<div class="col-span-4 flex items-center justify-center opacity-30 py-8">
                <span class="material-symbols-outlined text-4xl mr-3">videocam_off</span>
                <span class="text-sm font-bold">${App.t("dvr_empty","No recordings found")}</span>
            </div>`;
        }
        const filtered = _filter === "all" ? _recordings
            : _recordings.filter(r => r.camera === _filter);
        return filtered.map(r => {
            const sel = _selectedFiles.has(r.filename) ? "ring-2 ring-amber-500" : "";
            const cam = r.camera === "front" ? "F" : "R";
            return `<div class="${cardBg} border rounded-xl p-2 flex flex-col items-center gap-1 cursor-pointer ${sel} hover:opacity-80 transition-all"
                         onclick="App._dvrToggleSelect('${r.filename}')">
                <div class="w-full aspect-video bg-black/30 rounded-lg flex items-center justify-center relative">
                    <span class="material-symbols-outlined text-2xl opacity-30">movie</span>
                    <span class="absolute top-1 right-1 text-[8px] font-bold px-1 rounded ${r.camera==='front'?'bg-blue-600':'bg-red-600'} text-white">${cam}</span>
                </div>
                <span class="text-[9px] font-bold truncate w-full text-center">${r.date || r.filename}</span>
                <span class="text-[8px] opacity-50">${r.size || '--'}</span>
            </div>`;
        }).join("");
    }

    async function _loadRecordings() {
        try {
            const res = await fetch("/api/dvr/list");
            const data = await res.json();
            _recordings = data.recordings || [];
        } catch (e) {
            _recordings = [];
        }
        // Update grid
        const grid = document.getElementById("dvr-grid");
        if (grid) {
            const theme = App.getTheme();
            const cardBg = theme === "modern" ? "bg-white border-slate-200 shadow-sm" : "bg-zinc-900 border-zinc-800";
            const accentClr = theme === "autodelta" ? "text-[#FF5F00]" : theme === "modern" ? "text-blue-600" : "text-amber-500";
            grid.innerHTML = _renderRecordings(cardBg, accentClr);
        }
        const countEl = document.getElementById("dvr-count");
        if (countEl) countEl.textContent = `${_recordings.length} recordings`;
        // Check USB
        try {
            const usbRes = await fetch("/api/dvr/usb/status");
            const usb = await usbRes.json();
            const storageEl = document.getElementById("dvr-storage");
            if (storageEl) storageEl.textContent = usb.available ? `USB: ${usb.free_gb||'?'}GB free` : "No USB";
        } catch (e) {}
    }

    // Expose DVR methods on App
    if (!App._dvrFilter) {
        App._dvrFilter = (f) => { _filter = f; App.navigateTo("a6"); };
        App._dvrToggleSelect = (filename) => {
            if (_selectedFiles.has(filename)) _selectedFiles.delete(filename);
            else _selectedFiles.add(filename);
            App.navigateTo("a6");
        };
        App._dvrExport = async () => {
            if (_selectedFiles.size === 0) return;
            try {
                await fetch("/api/dvr/export", {
                    method: "POST",
                    headers: {"Content-Type": "application/json"},
                    body: JSON.stringify({files: [..._selectedFiles]}),
                });
                alert(App.t("dvr_export_done", "Export started"));
            } catch (e) {}
        };
    }

    return { render };
})());
