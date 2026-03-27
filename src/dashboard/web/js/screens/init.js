/**
 * Initialization / Splash Screen — theme-aware boot sequence.
 */

App.registerScreen("init", (() => {
    function render(container, theme, data) {
        if (theme === "heritage") container.innerHTML = _renderHeritage();
        else if (theme === "modern") container.innerHTML = _renderModern();
        else if (theme === "autodelta") container.innerHTML = _renderAutodelta();
        else container.innerHTML = _renderHeritage();
    }

    function _renderHeritage() {
        return `<main class="relative w-full h-full flex flex-col items-center justify-center overflow-hidden bg-black">
            <!-- Vignette -->
            <div class="absolute inset-0 bg-[radial-gradient(circle_at_center,_transparent_0%,_#000000_90%)] z-10"></div>
            <!-- Texture overlay -->
            <div class="absolute inset-0 opacity-10 mix-blend-overlay pointer-events-none z-20" style="background:repeating-linear-gradient(45deg,#2c1a12 0px,#2c1a12 1px,transparent 1px,transparent 8px);"></div>
            <!-- Central sketch -->
            <div class="relative z-30 flex flex-col items-center justify-center">
                <div class="relative group">
                    <div class="absolute inset-0 rounded-full bg-amber-500/10 blur-[100px] animate-pulse-soft" style="--glow-rgb:245,158,11;"></div>
                    <div class="sketch-mask relative">
                        <img src="/assets/heritage/giulia_gta_sketch.png" alt="Giulia GTA"
                             class="w-[480px] h-auto object-contain mix-blend-screen opacity-80 animate-pulse-soft grayscale brightness-125"
                             onerror="this.style.display='none'">
                        <div class="w-[480px] h-[280px] flex items-center justify-center text-zinc-700 text-sm" style="display:none;" id="heritage-init-fallback">
                            <span class="material-symbols-outlined text-8xl text-amber-900/30">directions_car</span>
                        </div>
                    </div>
                </div>
                <!-- Brand -->
                <div class="mt-8 flex flex-col items-center">
                    <div class="flex items-center space-x-4 mb-2">
                        <div class="h-[1px] w-12 bg-gradient-to-r from-transparent to-amber-500/40"></div>
                        <span class="text-amber-500 tracking-[0.4em] text-xs font-light">ALFA ROMEO</span>
                        <div class="h-[1px] w-12 bg-gradient-to-l from-transparent to-amber-500/40"></div>
                    </div>
                </div>
            </div>
            <!-- Progress -->
            <div class="absolute bottom-12 z-40 w-full flex flex-col items-center">
                <div class="w-48 h-[2px] bg-zinc-900 mb-6 relative overflow-hidden">
                    <div class="absolute top-0 left-0 h-full bg-amber-500/60 shadow-[0_0_8px_rgba(255,191,0,0.4)] animate-init-progress"></div>
                </div>
                <p class="text-amber-500 tracking-[0.2em] text-[10px] font-bold opacity-60 flex items-center">
                    <span class="material-symbols-outlined text-[14px] mr-2" style="font-variation-settings:'FILL' 1;">settings_bluetooth</span>
                    CHECKING SYSTEMS...
                </p>
            </div>
            <!-- Corner accents -->
            <div class="absolute top-8 left-8 w-8 h-8 border-t border-l border-amber-500/20 z-30"></div>
            <div class="absolute top-8 right-8 w-8 h-8 border-t border-r border-amber-500/20 z-30"></div>
            <div class="absolute bottom-8 left-8 w-8 h-8 border-b border-l border-amber-500/20 z-30"></div>
            <div class="absolute bottom-8 right-8 w-8 h-8 border-b border-r border-amber-500/20 z-30"></div>
            <style>
                @keyframes init-progress { 0%{width:0} 100%{width:100%} }
                .animate-init-progress { animation: init-progress 3.5s ease-out forwards; }
            </style>
        </main>`;
    }

    function _renderModern() {
        return `<main class="relative w-full h-full flex flex-col items-center justify-center overflow-hidden" style="background:#161618;">
            <!-- Glow effect -->
            <div class="absolute w-[120%] h-[120%] bg-[radial-gradient(circle,rgba(59,130,246,0.08)_0%,transparent_70%)]"></div>
            <!-- Sketch -->
            <div class="relative z-10 w-[80%] max-h-[300px] flex justify-center items-center">
                <img src="/assets/modern/berlina_156_sketch.png" alt="156 Berlina"
                     class="w-full h-auto object-contain opacity-80 mix-blend-screen grayscale contrast-125"
                     onerror="this.style.display='none'">
            </div>
            <!-- Brand -->
            <div class="absolute top-12 flex items-center gap-3 opacity-40 z-20">
                <div class="h-[1px] w-8 bg-blue-500"></div>
                <span class="text-[10px] font-bold tracking-[0.3em] uppercase text-white">Centro Stile Alfa Romeo</span>
                <div class="h-[1px] w-8 bg-blue-500"></div>
            </div>
            <!-- Status -->
            <div class="absolute bottom-10 flex flex-col items-center gap-2 z-20">
                <p class="text-[10px] font-medium text-zinc-500">SYSTEM INITIALIZING...</p>
                <div class="flex gap-1">
                    <div class="w-1 h-1 rounded-full bg-blue-500"></div>
                    <div class="w-1 h-1 rounded-full bg-zinc-700"></div>
                    <div class="w-1 h-1 rounded-full bg-zinc-700"></div>
                </div>
            </div>
            <!-- Corner accents -->
            <div class="absolute top-8 left-8 border-l border-t border-blue-500/30 w-4 h-4"></div>
            <div class="absolute top-8 right-8 border-r border-t border-blue-500/30 w-4 h-4"></div>
            <div class="absolute bottom-8 left-8 border-l border-b border-blue-500/30 w-4 h-4"></div>
            <div class="absolute bottom-8 right-8 border-r border-b border-blue-500/30 w-4 h-4"></div>
            <!-- Progress bar -->
            <div class="absolute bottom-0 left-0 w-full h-[2px] bg-white/5">
                <div class="h-full bg-gradient-to-r from-transparent via-blue-500 to-transparent animate-init-progress"></div>
            </div>
            <style>
                @keyframes init-progress { 0%{width:0} 100%{width:100%} }
                .animate-init-progress { animation: init-progress 3.5s ease-out forwards; }
            </style>
        </main>`;
    }

    function _renderAutodelta() {
        return `<main class="relative w-full h-full flex flex-col items-center justify-center overflow-hidden bg-black">
            <!-- Scanline -->
            <div class="absolute inset-0 pointer-events-none scanline opacity-30"></div>
            <!-- Crosshair grid -->
            <div class="absolute inset-0 flex items-center justify-center opacity-10 z-0">
                <div class="w-full h-px bg-[#FF4500]"></div>
                <div class="h-full w-px bg-[#FF4500] absolute"></div>
            </div>
            <!-- Sketch -->
            <div class="relative z-10 w-[540px] h-[280px] flex items-center justify-center">
                <div class="animate-breathing">
                    <img src="/assets/autodelta/junior_z_sketch.png" alt="1600 Junior Z"
                         class="w-full h-full object-contain filter invert brightness-200"
                         onerror="this.style.display='none'">
                </div>
                <!-- Corner accents -->
                <div class="absolute top-0 left-0 w-8 h-8 border-t-2 border-l-2 border-[#FF4500]"></div>
                <div class="absolute top-0 right-0 w-8 h-8 border-t-2 border-r-2 border-white"></div>
                <div class="absolute bottom-0 left-0 w-8 h-8 border-b-2 border-l-2 border-white"></div>
                <div class="absolute bottom-0 right-0 w-8 h-8 border-b-2 border-r-2 border-[#FF4500]"></div>
            </div>
            <!-- Status -->
            <div class="mt-16 w-full max-w-md z-10">
                <div class="flex flex-col items-center gap-3">
                    <div class="w-full h-1 bg-zinc-900 overflow-hidden">
                        <div class="h-full bg-[#FF4500] animate-init-progress"></div>
                    </div>
                    <div class="flex justify-between w-full items-end">
                        <div class="flex flex-col gap-1">
                            <span class="text-[10px] font-bold text-white/40 tracking-[0.2em]">SYSTEM_VERSION</span>
                            <span class="text-xs text-white font-mono italic">v2.0.4_AUTODELTA</span>
                        </div>
                        <div class="text-center">
                            <h1 class="text-[#FF4500] font-bold text-lg tracking-[0.3em] uppercase italic">AUTODELTA CORE ENGAGED</h1>
                        </div>
                        <div class="flex flex-col gap-1 items-end">
                            <span class="text-[10px] font-bold text-white/40 tracking-[0.2em]">UNIT_ID</span>
                            <span class="text-xs text-white font-mono italic">AR-1600-JZ</span>
                        </div>
                    </div>
                </div>
            </div>
            <!-- Brand -->
            <div class="absolute top-6 left-6 z-30 flex items-center gap-2">
                <span class="material-symbols-outlined text-[#FF4500] text-lg">token</span>
                <div class="flex flex-col">
                    <span class="text-[10px] font-extrabold text-white leading-tight italic">ALFA ROMEO</span>
                    <span class="text-[8px] text-[#FF4500] leading-tight tracking-[0.1em]">RACING DIVISION</span>
                </div>
            </div>
            <div class="absolute top-6 right-6 z-30 text-right">
                <span class="text-[10px] font-mono text-white/50 tracking-tighter">EST. 1963</span>
            </div>
            <style>
                @keyframes init-progress { 0%{width:0} 100%{width:100%} }
                .animate-init-progress { animation: init-progress 3.5s ease-out forwards; }
            </style>
        </main>`;
    }

    return { render };
})());
