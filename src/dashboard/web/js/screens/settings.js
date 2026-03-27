/**
 * Settings Screen — Theme, language, units configuration.
 */

App.registerScreen("settings", (() => {
    function render(container, theme, data) {
        const config = App.getConfig();
        container.innerHTML = `<div class="screen-container bg-black text-white">
            ${AppBar.render(theme, data)}
            <main class="content-area p-6 overflow-y-auto">
                <h1 class="text-2xl font-bold mb-6 uppercase tracking-wider">Settings</h1>
                <div class="space-y-4">
                    <!-- Theme -->
                    <div class="bg-zinc-900 rounded-xl p-4 border border-zinc-800">
                        <p class="text-xs font-bold text-zinc-400 uppercase tracking-wider mb-3">Theme</p>
                        <div class="flex gap-3">
                            ${_themeBtn("heritage", "Heritage Warmth", config.theme)}
                            ${_themeBtn("modern", "Modern Elegance", config.theme)}
                            ${_themeBtn("autodelta", "Autodelta Sport", config.theme)}
                        </div>
                    </div>
                    <!-- Language -->
                    <div class="bg-zinc-900 rounded-xl p-4 border border-zinc-800">
                        <p class="text-xs font-bold text-zinc-400 uppercase tracking-wider mb-3">Language</p>
                        <div class="flex gap-3">
                            ${_optBtn("pl", "Polski", config.language, "lang")}
                            ${_optBtn("en", "English", config.language, "lang")}
                        </div>
                    </div>
                    <!-- Units -->
                    <div class="bg-zinc-900 rounded-xl p-4 border border-zinc-800 flex gap-8">
                        <div>
                            <p class="text-xs font-bold text-zinc-400 uppercase tracking-wider mb-3">Speed</p>
                            <div class="flex gap-2">
                                ${_optBtn("km/h", "km/h", config.speed_unit, "speed")}
                                ${_optBtn("mph", "mph", config.speed_unit, "speed")}
                            </div>
                        </div>
                        <div>
                            <p class="text-xs font-bold text-zinc-400 uppercase tracking-wider mb-3">Temperature</p>
                            <div class="flex gap-2">
                                ${_optBtn("C", "°C", config.temp_unit, "temp")}
                                ${_optBtn("F", "°F", config.temp_unit, "temp")}
                            </div>
                        </div>
                    </div>
                </div>
                <button class="mt-6 px-6 py-2 bg-zinc-800 rounded-lg text-sm font-bold hover:bg-zinc-700 transition-colors" onclick="App.navigateTo('a1')">
                    Back to Dashboard
                </button>
            </main>
        </div>`;
    }

    function _themeBtn(value, label, current) {
        const active = value === current;
        const cls = active
            ? "bg-red-600 text-white border-red-600"
            : "bg-zinc-800 text-zinc-300 border-zinc-700 hover:border-zinc-500";
        return `<button class="px-4 py-2 rounded-lg text-sm font-bold border ${cls} transition-colors"
                    onclick="App.setTheme('${value}')">${label}</button>`;
    }

    function _optBtn(value, label, current, type) {
        const active = value === current;
        const cls = active
            ? "bg-zinc-600 text-white"
            : "bg-zinc-800 text-zinc-400 hover:bg-zinc-700";
        return `<button class="px-3 py-1.5 rounded text-xs font-bold ${cls} transition-colors"
                    onclick="Settings.set('${type}','${value}')">${label}</button>`;
    }

    return { render };
})());

const Settings = {
    async set(type, value) {
        const body = {};
        if (type === "lang") body.language = value;
        else if (type === "speed") body.speed_unit = value;
        else if (type === "temp") body.temp_unit = value;
        try {
            await fetch("/api/config", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(body),
            });
            // Reload config and re-render
            location.reload();
        } catch (e) { /* ignore */ }
    },
};
