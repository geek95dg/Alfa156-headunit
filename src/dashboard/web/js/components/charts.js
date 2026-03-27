/**
 * Charts component — bar charts and SVG line graphs for trip screens.
 */

const Charts = (() => {
    /** Render a bar chart (Heritage/Autodelta style) */
    function renderBarChart(values, theme, options = {}) {
        const {
            width = "100%",
            height = "100%",
            labels = [],
            barGap = 2,
        } = options;

        const max = Math.max(...values, 1);
        const barColor = theme === "autodelta" ? "#FF5F00" : "#ec5b13";
        const inactiveColor = theme === "autodelta" ? "#27272a" : "rgba(0,0,0,0.2)";

        const bars = values.map((v, i) => {
            const pct = (v / max * 100).toFixed(1);
            const isRecent = i >= values.length - 3;
            const color = isRecent ? barColor : inactiveColor;
            const opacity = isRecent ? (0.4 + (i - (values.length - 3)) * 0.2) : 1;
            return `<div class="w-full rounded-t-sm transition-all duration-300" style="height:${pct}%;background:${color};opacity:${opacity};"></div>`;
        }).join("");

        const labelHtml = labels.length > 0
            ? `<div class="flex justify-between text-[9px] text-zinc-500 uppercase font-medium mt-2">${labels.map(l => `<span>${l}</span>`).join("")}</div>`
            : "";

        return `<div class="w-full h-full flex flex-col">
            <div class="flex-1 flex items-end justify-between gap-${barGap}">${bars}</div>
            ${labelHtml}
        </div>`;
    }

    /** Render an SVG line graph (Modern style) */
    function renderLineGraph(values, options = {}) {
        const {
            width = 400,
            height = 150,
            color = "#005596",
            fillOpacity = 0.2,
        } = options;

        if (values.length < 2) return "";

        const max = Math.max(...values, 1);
        const stepX = width / (values.length - 1);

        const points = values.map((v, i) => {
            const x = i * stepX;
            const y = height - (v / max * height);
            return `${x},${y}`;
        });

        const linePath = `M${points.join(" L")}`;
        const areaPath = `${linePath} L${width},${height} L0,${height} Z`;

        const lastPoint = points[points.length - 1].split(",");

        return `<svg viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" class="w-full h-full">
            <defs>
                <linearGradient id="lineGrad" x1="0%" y1="0%" x2="0%" y2="100%">
                    <stop offset="0%" style="stop-color:${color};stop-opacity:${fillOpacity}"/>
                    <stop offset="100%" style="stop-color:${color};stop-opacity:0"/>
                </linearGradient>
            </defs>
            <!-- Grid -->
            <line x1="0" y1="0" x2="${width}" y2="0" stroke="#f1f5f9" stroke-width="1"/>
            <line x1="0" y1="${height/3}" x2="${width}" y2="${height/3}" stroke="#f1f5f9" stroke-width="1"/>
            <line x1="0" y1="${height*2/3}" x2="${width}" y2="${height*2/3}" stroke="#f1f5f9" stroke-width="1"/>
            <line x1="0" y1="${height}" x2="${width}" y2="${height}" stroke="#cbd5e1" stroke-width="2"/>
            <!-- Area fill -->
            <path d="${areaPath}" fill="url(#lineGrad)"/>
            <!-- Line -->
            <path d="${linePath}" fill="none" stroke="${color}" stroke-width="3" stroke-linecap="round"/>
            <!-- Highlight point -->
            <circle cx="${lastPoint[0]}" cy="${lastPoint[1]}" r="4" fill="${color}"/>
            <circle cx="${lastPoint[0]}" cy="${lastPoint[1]}" r="8" fill="none" stroke="${color}" stroke-width="2" class="animate-pulse"/>
        </svg>`;
    }

    /** Render a circular progress gauge (Autodelta style) */
    function renderCircularGauge(value, max, options = {}) {
        const { size = 40, color = "#FF5F00", bgColor = "#27272a", strokeWidth = 3 } = options;
        const r = (size / 2) - strokeWidth;
        const circumference = 2 * Math.PI * r;
        const offset = circumference - (value / max * circumference);

        return `<div class="relative" style="width:${size}px;height:${size}px;">
            <svg class="w-full h-full transform -rotate-90">
                <circle cx="${size/2}" cy="${size/2}" r="${r}" fill="transparent" stroke="${bgColor}" stroke-width="${strokeWidth}"/>
                <circle cx="${size/2}" cy="${size/2}" r="${r}" fill="transparent" stroke="${color}" stroke-width="${strokeWidth}" stroke-dasharray="${circumference}" stroke-dashoffset="${offset}"/>
            </svg>
            <span class="absolute inset-0 flex items-center justify-center text-[10px] font-bold">${value}</span>
        </div>`;
    }

    return { renderBarChart, renderLineGraph, renderCircularGauge };
})();
