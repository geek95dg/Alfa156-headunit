/**
 * Media Player component — theme-aware BT media display.
 */

const MediaPlayer = (() => {
    function renderHeritage(data) {
        const title = data.bt_media_title || "No Media";
        const artist = data.bt_media_artist || "---";
        const playIcon = data.bt_media_playing ? "pause" : "play_arrow";
        return `<div class="bg-zinc-900/30 rounded-xl border border-zinc-800 p-4 flex items-center gap-4">
            <div class="w-12 h-12 bg-red-950/30 rounded-full flex items-center justify-center border border-red-900/20">
                <span class="material-symbols-outlined text-red-500" style="font-variation-settings:'FILL' 1;">music_note</span>
            </div>
            <div class="flex-1 overflow-hidden">
                <p class="text-[10px] text-zinc-500 font-black uppercase tracking-widest">Now Playing</p>
                <p class="text-sm font-bold text-zinc-200 truncate" data-bind="media_info">${title} - ${artist}</p>
            </div>
        </div>`;
    }

    function renderModern(data) {
        const title = data.bt_media_title || "No Media";
        const artist = data.bt_media_artist || "---";
        return `<div class="aspect-square bg-slate-900 rounded-xl overflow-hidden relative group shadow-lg">
            <div class="absolute inset-0 bg-gradient-to-t from-black/80 to-transparent"></div>
            <div class="absolute inset-0 p-4 flex flex-col justify-between">
                <div class="flex justify-end">
                    <span class="material-symbols-outlined text-white" style="font-size:18px;">music_note</span>
                </div>
                <div>
                    <div class="text-xs font-bold text-white leading-tight" data-bind="bt_media_title">${title}</div>
                    <div class="text-[10px] text-zinc-300 font-medium" data-bind="bt_media_artist">${artist}</div>
                    <div class="mt-2 flex items-center gap-2">
                        <span class="material-symbols-outlined text-white" style="font-size:16px;">skip_previous</span>
                        <span class="material-symbols-outlined text-white" style="font-size:24px;">${data.bt_media_playing ? 'pause' : 'play_arrow'}</span>
                        <span class="material-symbols-outlined text-white" style="font-size:16px;">skip_next</span>
                    </div>
                </div>
            </div>
        </div>`;
    }

    function renderAutodelta(data) {
        const title = data.bt_media_title || "No Media";
        const artist = data.bt_media_artist || "---";
        return `<div class="bg-[#111111] rounded-xl p-4 flex items-center gap-4 border border-[#222222]">
            <div class="w-12 h-12 bg-[#222222] rounded-lg overflow-hidden shrink-0 relative flex items-center justify-center">
                <span class="material-symbols-outlined text-white text-opacity-80" style="font-size:24px;">${data.bt_media_playing ? 'pause' : 'play_arrow'}</span>
            </div>
            <div class="flex flex-col flex-1 overflow-hidden">
                <span class="text-white font-bold truncate" data-bind="bt_media_title">${title}</span>
                <span class="text-[#FF5F00] text-xs font-medium truncate" data-bind="bt_media_artist">${artist}</span>
            </div>
            <div class="flex items-center gap-2 text-gray-400">
                <span class="material-symbols-outlined">skip_previous</span>
                <span class="material-symbols-outlined">skip_next</span>
            </div>
        </div>`;
    }

    return { renderHeritage, renderModern, renderAutodelta };
})();
