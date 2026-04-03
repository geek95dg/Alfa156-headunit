/**
 * A6 DVR Recordings Browser — browse, play, export with USB folder picker.
 * Fetches recording list from /api/dvr/list.
 */

App.registerScreen("a6", (() => {
    let _recordings = [];
    let _filter = "all"; // "all", "front", "rear"
    let _selectedFiles = new Set();
    // USB browse modal state
    let _showBrowseModal = false;
    let _browsePath = "/";
    let _browseDirs = [];
    let _browseLoading = false;

    function render(container, theme, data) {
        const t = App.t.bind(App);
        const bgCls = theme === "modern" ? "bg-slate-100 text-slate-900" : "bg-black text-white";
        const cardBg = theme === "modern" ? "bg-white border-slate-200 shadow-sm" : "bg-zinc-900 border-zinc-800";
        const accentClr = theme === "autodelta" ? "text-[#FF5F00]" : theme === "modern" ? "text-blue-600" : "text-amber-500";
        const btnBg = theme === "modern" ? "bg-slate-100 hover:bg-slate-200 text-slate-700" : "bg-zinc-800 hover:bg-zinc-700 text-zinc-300";

        container.innerHTML = `<div class="screen-container ${bgCls}">
            ${AppBar.render(theme, data)}
            <main class="content-area p-3 flex flex-col relative">
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
                <!-- USB Browse Modal -->
                ${_showBrowseModal ? _renderBrowseModal(theme, cardBg, btnBg) : ""}
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

    function _renderBrowseModal(theme, cardBg, btnBg) {
        const t = App.t.bind(App);
        const overlayBg = "rgba(0,0,0,0.85)";
        const modalBg = theme === "modern" ? "bg-white text-slate-900" : "bg-zinc-900 text-white";
        const borderClr = theme === "modern" ? "border-slate-200" : "border-zinc-700";
        const accentBtn = theme === "autodelta" ? "bg-[#FF5F00]" : theme === "modern" ? "bg-blue-600" : "bg-amber-600";
        const isRoot = _browsePath === "/";

        return `<div class="absolute inset-0 z-50 flex items-center justify-center" style="background:${overlayBg};">
            <div class="${modalBg} ${borderClr} border rounded-2xl w-[420px] max-h-[80%] flex flex-col shadow-2xl">
                <!-- Modal header -->
                <div class="flex items-center justify-between px-4 py-3 border-b ${borderClr}">
                    <div class="flex items-center gap-2">
                        <span class="material-symbols-outlined" style="font-size:20px;">usb</span>
                        <span class="text-sm font-bold">${t("dvr_export","Export to USB")}</span>
                    </div>
                    <button class="opacity-50 hover:opacity-100" onclick="App._dvrBrowseClose()">
                        <span class="material-symbols-outlined" style="font-size:20px;">close</span>
                    </button>
                </div>
                <!-- Current path -->
                <div class="px-4 py-2 border-b ${borderClr} flex items-center gap-2">
                    <span class="material-symbols-outlined opacity-40" style="font-size:16px;">folder</span>
                    <span class="text-xs font-mono opacity-60">${_browsePath}</span>
                </div>
                <!-- Directory list -->
                <div class="flex-1 overflow-y-auto px-2 py-2 space-y-1" style="max-height:300px;">
                    ${!isRoot ? `<div class="${cardBg} border ${borderClr} rounded-lg px-3 py-2 flex items-center gap-2 cursor-pointer hover:opacity-80" onclick="App._dvrBrowseUp()">
                        <span class="material-symbols-outlined" style="font-size:18px;">arrow_upward</span>
                        <span class="text-xs font-bold">..</span>
                    </div>` : ""}
                    ${_browseLoading ? `<div class="flex items-center justify-center py-6 opacity-40">
                        <span class="text-xs">${t("loading","Loading...")}</span>
                    </div>` : ""}
                    ${!_browseLoading && _browseDirs.length === 0 ? `<div class="flex items-center justify-center py-6 opacity-30">
                        <span class="text-xs">${t("dvr_no_folders","No subfolders")}</span>
                    </div>` : ""}
                    ${!_browseLoading ? _browseDirs.map(d => `<div class="${cardBg} border ${borderClr} rounded-lg px-3 py-2 flex items-center gap-2 cursor-pointer hover:opacity-80" onclick="App._dvrBrowseInto('${d.name}')">
                        <span class="material-symbols-outlined text-amber-500" style="font-size:18px;">folder</span>
                        <span class="text-xs font-bold">${d.name}</span>
                    </div>`).join("") : ""}
                </div>
                <!-- Modal footer -->
                <div class="flex justify-between items-center px-4 py-3 border-t ${borderClr}">
                    <span class="text-[10px] opacity-40">${_selectedFiles.size} ${t("dvr_files_selected","files selected")}</span>
                    <div class="flex gap-2">
                        <button class="${btnBg} px-4 py-2 rounded-lg text-xs font-bold" onclick="App._dvrBrowseClose()">${t("cancel","Cancel")}</button>
                        <button class="${accentBtn} text-white px-4 py-2 rounded-lg text-xs font-bold" onclick="App._dvrExportToPath()">${t("dvr_export_here","Export Here")}</button>
                    </div>
                </div>
            </div>
        </div>`;
    }

    async function _loadRecordings() {
        try {
            const res = await fetch("/api/dvr/list");
            const data = await res.json();
            _recordings = data.recordings || [];
        } catch (e) {
            _recordings = [];
        }
        const grid = document.getElementById("dvr-grid");
        if (grid) {
            const theme = App.getTheme();
            const cardBg = theme === "modern" ? "bg-white border-slate-200 shadow-sm" : "bg-zinc-900 border-zinc-800";
            const accentClr = theme === "autodelta" ? "text-[#FF5F00]" : theme === "modern" ? "text-blue-600" : "text-amber-500";
            grid.innerHTML = _renderRecordings(cardBg, accentClr);
        }
        const countEl = document.getElementById("dvr-count");
        if (countEl) countEl.textContent = `${_recordings.length} recordings`;
        try {
            const usbRes = await fetch("/api/dvr/usb/status");
            const usb = await usbRes.json();
            const storageEl = document.getElementById("dvr-storage");
            if (storageEl) storageEl.textContent = usb.available ? `USB: ${usb.free_gb||'?'}GB free` : "No USB";
        } catch (e) {}
    }

    async function _loadUsbDirs(path) {
        _browseLoading = true;
        _browsePath = path;
        _browseDirs = [];
        App.navigateTo("a6");
        try {
            const res = await fetch(`/api/dvr/usb/browse?path=${encodeURIComponent(path)}`);
            const data = await res.json();
            _browsePath = data.path || path;
            _browseDirs = data.dirs || [];
        } catch (e) {
            _browseDirs = [];
        }
        _browseLoading = false;
        App.navigateTo("a6");
    }

    // Expose DVR methods on App
    if (!App._dvrFilter) {
        App._dvrFilter = (f) => { _filter = f; App.navigateTo("a6"); };
        App._dvrToggleSelect = (filename) => {
            if (_selectedFiles.has(filename)) _selectedFiles.delete(filename);
            else _selectedFiles.add(filename);
            App.navigateTo("a6");
        };
        App._dvrExport = () => {
            if (_selectedFiles.size === 0) return;
            _showBrowseModal = true;
            _loadUsbDirs("/");
        };
        App._dvrBrowseClose = () => {
            _showBrowseModal = false;
            App.navigateTo("a6");
        };
        App._dvrBrowseInto = (dirName) => {
            const newPath = _browsePath === "/" ? `/${dirName}` : `${_browsePath}/${dirName}`;
            _loadUsbDirs(newPath);
        };
        App._dvrBrowseUp = () => {
            const parts = _browsePath.split("/").filter(Boolean);
            parts.pop();
            const parent = parts.length === 0 ? "/" : "/" + parts.join("/");
            _loadUsbDirs(parent);
        };
        App._dvrExportToPath = async () => {
            if (_selectedFiles.size === 0) return;
            try {
                await fetch("/api/dvr/export", {
                    method: "POST",
                    headers: {"Content-Type": "application/json"},
                    body: JSON.stringify({
                        files: [..._selectedFiles],
                        target_path: _browsePath,
                    }),
                });
                _showBrowseModal = false;
                _selectedFiles.clear();
                App.navigateTo("a6");
            } catch (e) {}
        };
    }

    return { render };
})());
