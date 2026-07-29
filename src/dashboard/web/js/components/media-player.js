/**
 * Media Player component — theme-aware BT/AA now-playing card.
 *
 * All three themes render the SAME large, touch-friendly card: cover icon +
 * title/artist, prev / play-pause / next transport, and a master volume
 * slider. Elements carry stable ids (media-title, media-artist,
 * media-playpause, media-volume, media-mute-icon) so main.js update() can
 * refresh them live every tick — no full re-render needed.
 */

const MediaPlayer = (() => {
    // AVRCP transport control → /api/media/<action> → bt.cmd.media.
    async function cmd(action, ev) {
        if (ev) { ev.stopPropagation(); }
        try { await fetch("/api/media/" + action, { method: "POST" }); }
        catch (e) { /* phone may be disconnected — ignore */ }
    }

    // Master volume → /api/audio/volume → VolumeController.set_volume.
    // Dragging a range input fires oninput per pixel; throttle so we don't
    // flood the single-threaded Flask server (~1 POST / 120 ms + final value).
    let _volTimer = null, _volPending = null;
    function _flushVolume() {
        _volTimer = null;
        if (_volPending == null) return;
        const vol = _volPending; _volPending = null;
        fetch("/api/audio/volume", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ volume: vol }),
        }).catch(() => { /* audio not ready — ignore */ });
    }
    function setVolume(v, ev) {
        if (ev) { ev.stopPropagation(); }
        _volPending = Math.max(0, Math.min(100, parseInt(v, 10) || 0));
        if (_volTimer) return;
        _volTimer = setTimeout(_flushVolume, 120);
    }

    async function toggleMute(ev) {
        if (ev) { ev.stopPropagation(); }
        const icon = document.getElementById("media-mute-icon");
        const muted = icon && icon.textContent.trim() === "volume_off";
        try {
            await fetch("/api/audio/volume", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ mute: !muted }),
            });
        } catch (e) { /* ignore */ }
    }

    // Theme token tables — keep the structure identical, vary the colours.
    const THEMES = {
        heritage: {
            card: "bg-zinc-900/40 border-zinc-800",
            iconWrap: "bg-red-950/30 border border-red-900/20",
            icon: "text-red-500", play: "bg-red-600",
            btn: "text-zinc-300", label: "text-zinc-500",
            title: "text-zinc-100", artist: "text-zinc-400",
        },
        modern: {
            card: "bg-white border-slate-100 shadow-lg",
            iconWrap: "bg-blue-50 border border-slate-100",
            icon: "text-blue-500", play: "bg-blue-600",
            btn: "text-slate-500", label: "text-slate-400",
            title: "text-slate-800", artist: "text-slate-500",
        },
        autodelta: {
            card: "bg-[#111111] border-[#222222]",
            iconWrap: "bg-[#222222] border border-[#222222]",
            icon: "text-[#FF5F00]", play: "bg-[#FF5F00]",
            btn: "text-gray-400", label: "text-gray-500",
            title: "text-white", artist: "text-[#FF5F00]",
        },
    };

    function _card(data, tk) {
        const title = data.bt_media_title || "No Media";
        const artist = data.bt_media_artist || "---";
        const playIcon = data.bt_media_playing ? "pause" : "play_arrow";
        const vol = (data.audio_volume != null) ? data.audio_volume : 70;
        const muteIcon = data.audio_muted ? "volume_off" : "volume_up";
        return `<div class="rounded-2xl border p-5 flex flex-col gap-5 ${tk.card}">
            <div class="flex items-center gap-4">
                <div class="w-16 h-16 rounded-xl flex items-center justify-center shrink-0 ${tk.iconWrap}">
                    <span class="material-symbols-outlined ${tk.icon}" style="font-size:34px;font-variation-settings:'FILL' 1;">music_note</span>
                </div>
                <div class="flex-1 overflow-hidden">
                    <p class="text-[10px] font-black uppercase tracking-widest ${tk.label}">Now Playing</p>
                    <p id="media-title" class="text-xl font-bold truncate ${tk.title}">${title}</p>
                    <p id="media-artist" class="text-sm truncate ${tk.artist}">${artist}</p>
                </div>
            </div>
            <div class="flex items-center justify-center gap-8">
                <span class="material-symbols-outlined active:scale-90 transition-transform ${tk.btn}" style="font-size:42px;cursor:pointer;" onclick="MediaPlayer.cmd('previous', event)">skip_previous</span>
                <span class="w-16 h-16 rounded-full flex items-center justify-center active:scale-90 transition-transform ${tk.play}" style="cursor:pointer;" onclick="MediaPlayer.cmd('playpause', event)">
                    <span id="media-playpause" class="material-symbols-outlined text-white" style="font-size:40px;font-variation-settings:'FILL' 1;">${playIcon}</span>
                </span>
                <span class="material-symbols-outlined active:scale-90 transition-transform ${tk.btn}" style="font-size:42px;cursor:pointer;" onclick="MediaPlayer.cmd('next', event)">skip_next</span>
            </div>
            <div class="flex items-center gap-3">
                <span id="media-mute-icon" class="material-symbols-outlined active:scale-90 transition-transform ${tk.btn}" style="font-size:26px;cursor:pointer;" onclick="MediaPlayer.toggleMute(event)">${muteIcon}</span>
                <input id="media-volume" type="range" min="0" max="100" value="${vol}" class="bcm-vol flex-1" oninput="MediaPlayer.setVolume(this.value, event)">
            </div>
        </div>`;
    }

    function renderHeritage(data) { return _card(data, THEMES.heritage); }
    function renderModern(data) { return _card(data, THEMES.modern); }
    function renderAutodelta(data) { return _card(data, THEMES.autodelta); }

    return { renderHeritage, renderModern, renderAutodelta, cmd, setVolume, toggleMute };
})();
