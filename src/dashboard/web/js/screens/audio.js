/**
 * Audio / EQ Settings Screen — Full-screen EQ controls.
 * Presets, 10-band graphic EQ, bass/treble, fader/balance.
 */

const AudioSettings = {
    _state: null,
    _loading: false,

    async load() {
        if (AudioSettings._loading) return;
        AudioSettings._loading = true;
        try {
            const res = await fetch("/api/audio/eq");
            AudioSettings._state = await res.json();
        } catch (e) {
            console.error("[Audio] Load failed:", e);
        }
        AudioSettings._loading = false;
    },

    async _post(data) {
        try {
            await fetch("/api/audio/eq", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(data),
            });
            await AudioSettings.load();
            App.navigateTo("audio");
        } catch (e) {
            console.error("[Audio] POST failed:", e);
        }
    },

    setPreset(name) { AudioSettings._post({ preset: name }); },
    setBand(idx, val) {
        if (!AudioSettings._state) return;
        const gains = [...AudioSettings._state.gains];
        gains[idx] = parseInt(val);
        AudioSettings._post({ gains });
    },
    setBass(val) { AudioSettings._post({ bass: parseInt(val) }); },
    setTreble(val) { AudioSettings._post({ treble: parseInt(val) }); },
    setFader(val) { AudioSettings._post({ fader: parseInt(val) }); },
    setBalance(val) { AudioSettings._post({ balance: parseInt(val) }); },
};

App.registerScreen("audio", (() => {
    function render(container, theme, data) {
        const st = AudioSettings._state;
        if (!st) {
            AudioSettings.load().then(() => App.navigateTo("audio"));
            container.innerHTML = `<div class="screen-container" style="background:var(--color-surface);color:var(--color-on-surface)">
                ${AppBar.render(theme, data)}
                <main class="content-area flex items-center justify-center">
                    <p class="text-sm" style="color:var(--text-dim)">Loading audio settings...</p>
                </main>
                ${NavBar.render(theme, "settings")}
            </div>`;
            return;
        }

        const t = App.t.bind(App);
        const presets = st.presets || ["flat", "rock", "jazz", "bass_boost", "custom"];
        const freqs = st.frequencies || [31, 62, 125, 250, 500, 1000, 2000, 4000, 8000, 16000];
        const gains = st.gains || [0, 0, 0, 0, 0, 0, 0, 0, 0, 0];

        container.innerHTML = `<div class="screen-container" style="background:var(--color-surface);color:var(--color-on-surface)">
            ${AppBar.render(theme, data)}
            <main class="content-area p-4 overflow-y-auto">
                <div class="grid grid-cols-12 gap-3 h-full">
                    <!-- Left: Presets + Bass/Treble + Fader -->
                    <div class="col-span-4 flex flex-col gap-3">
                        <!-- Presets -->
                        <div class="rounded-xl p-3" style="background:var(--card-bg);border:1px solid var(--card-border)">
                            <p class="text-[10px] font-bold uppercase tracking-wider mb-2" style="color:var(--text-dim)">EQ ${t("preset","Preset")}</p>
                            <div class="grid grid-cols-2 gap-1.5">
                                ${presets.map(p => _presetBtn(p, st.preset)).join("")}
                            </div>
                        </div>
                        <!-- Bass / Treble -->
                        <div class="rounded-xl p-3" style="background:var(--card-bg);border:1px solid var(--card-border)">
                            <p class="text-[10px] font-bold uppercase tracking-wider mb-2" style="color:var(--text-dim)">${t("bass","Bass")} / ${t("treble","Treble")}</p>
                            ${_sliderRow("Bass", st.bass || 0, -12, 12, "AudioSettings.setBass(this.value)")}
                            ${_sliderRow("Treble", st.treble || 0, -12, 12, "AudioSettings.setTreble(this.value)")}
                        </div>
                        <!-- Fader / Balance -->
                        <div class="rounded-xl p-3" style="background:var(--card-bg);border:1px solid var(--card-border)">
                            <p class="text-[10px] font-bold uppercase tracking-wider mb-2" style="color:var(--text-dim)">${t("fader","Fader")} / ${t("balance","Balance")}</p>
                            ${_sliderRow("R ↔ F", st.fader || 0, -10, 10, "AudioSettings.setFader(this.value)")}
                            ${_sliderRow("L ↔ R", st.balance || 0, -10, 10, "AudioSettings.setBalance(this.value)")}
                        </div>
                    </div>
                    <!-- Right: 10-band Graphic EQ -->
                    <div class="col-span-8 rounded-xl p-4 flex flex-col" style="background:var(--card-bg);border:1px solid var(--card-border)">
                        <p class="text-[10px] font-bold uppercase tracking-wider mb-3" style="color:var(--text-dim)">10-Band Graphic EQ</p>
                        <div class="flex-1 flex items-end gap-1 pb-2">
                            ${gains.map((g, i) => _eqBand(i, g, freqs[i])).join("")}
                        </div>
                    </div>
                </div>
                <button class="mt-2 px-4 py-1.5 rounded-lg text-xs font-bold hover:opacity-80"
                        style="background:var(--card-border);color:var(--text-mid)"
                        onclick="App.navigateTo('settings')">
                    ← ${t("back_to_dash","Back")}
                </button>
            </main>
            ${NavBar.render(theme, "settings")}
        </div>`;
    }

    function _presetBtn(name, current) {
        const label = name.replace("_", " ").replace(/\b\w/g, c => c.toUpperCase());
        const isActive = name === current;
        const style = isActive
            ? "background:var(--color-primary);color:#fff;border:1px solid var(--color-primary)"
            : "background:var(--card-bg);color:var(--text-mid);border:1px solid var(--card-border)";
        return `<button class="px-2 py-1.5 rounded-lg text-[11px] font-bold hover:opacity-80 truncate"
                    style="${style}"
                    onclick="AudioSettings.setPreset('${name}')">${label}</button>`;
    }

    function _sliderRow(label, value, min, max, onchange) {
        return `<div class="flex items-center gap-2 mt-1.5">
            <span class="text-[10px] font-bold w-10 text-right" style="color:var(--text-dim)">${label}</span>
            <input type="range" min="${min}" max="${max}" value="${value}"
                   class="flex-1 h-1.5 rounded-full appearance-none cursor-pointer"
                   style="accent-color:var(--color-primary)"
                   onchange="${onchange}">
            <span class="text-[10px] font-bold w-8 text-center" style="color:var(--text-mid)">${value > 0 ? "+" : ""}${value}</span>
        </div>`;
    }

    function _eqBand(idx, gain, freq) {
        const pct = ((gain + 12) / 24) * 100;
        const freqLabel = freq >= 1000 ? `${freq / 1000}k` : `${freq}`;
        return `<div class="flex-1 flex flex-col items-center gap-1">
            <span class="text-[9px] font-bold" style="color:var(--text-mid)">${gain > 0 ? "+" : ""}${gain}</span>
            <div class="relative w-full flex justify-center" style="height:160px">
                <input type="range" min="-12" max="12" value="${gain}"
                       orient="vertical"
                       class="eq-slider"
                       style="accent-color:var(--color-primary);writing-mode:vertical-lr;direction:rtl;height:160px;width:24px;"
                       onchange="AudioSettings.setBand(${idx}, this.value)">
            </div>
            <span class="text-[8px] font-bold" style="color:var(--text-dim)">${freqLabel}</span>
        </div>`;
    }

    return { render };
})());
