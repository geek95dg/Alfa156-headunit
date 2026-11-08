// Evaluates src/dashboard/web/js/components/gestures.js for
// tests/test_frontend_gestures.py. Plain node, no packages.
//
// stdin: {"calls": [[fn, ...args], ...], "scripts": [[op, ...], ...]}
//   calls   — direct calls of the pure functions (edgeZone, classify, ...)
//   scripts — edge-tracker runs; ops: ["down", x, y, t, h], ["move", x, y, t],
//             ["up", x, y, t], ["cancel"], ["timer"] (fire pending timers)
// stdout: {"calls": [result, ...], "scripts": [[event, ...], ...]} where an
// event is ["send", action, x, y] | ["pull"] | ["navbar"] | ["state", s].
"use strict";
const path = require("path");
const fs = require("fs");

const G = require(path.join(__dirname, "..", "..", "src", "dashboard", "web", "js",
                            "components", "gestures.js"));
const input = JSON.parse(fs.readFileSync(0, "utf8"));

const calls = (input.calls || []).map(([fn, ...args]) => {
    if (typeof G[fn] !== "function") throw new Error("no such function: " + fn);
    return G[fn](...args);
});

const scripts = (input.scripts || []).map((ops) => {
    const events = [];
    let timers = [];
    const tracker = G.createEdgeTracker({
        send: (action, x, y) => events.push(["send", action, x, y]),
        onPull: () => events.push(["pull"]),
        onNavbar: () => events.push(["navbar"]),
        setTimer: (fn, ms) => { timers.push({ fn, ms, live: true }); return timers.length - 1; },
        clearTimer: (id) => { if (timers[id]) timers[id].live = false; },
    });
    for (const [op, ...args] of ops) {
        if (op === "timer") {
            const due = timers.filter((t) => t.live);
            timers = timers.map((t) => ({ ...t, live: false }));
            due.forEach((t) => t.fn());
        } else if (op === "state") {
            events.push(["state", tracker.state()]);
        } else {
            tracker[op](...args);
        }
    }
    return events;
});

process.stdout.write(JSON.stringify({ calls, scripts }));
