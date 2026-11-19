// Evaluates src/dashboard/web/js/components/hold.js (hold-to-confirm of the
// 112 / "Rozłącz" buttons) for tests/test_frontend_gestures.py. Plain node,
// no packages, a fake clock and fake timers.
//
// stdin: {"scripts": [{"opts": {holdMs, armDelayMs}, "ops": [[op, ...], ...]}]}
//   ops: ["advance", ms]  — move the clock, running due timers in order;
//        ["press", id] / ["release", id] / ["cancel", id] / ["leave", id];
//        ["rearm", ms]; ["destroy"]; ["state"]; ["progress"];
//        ["snap"]  — remember the pending timer callbacks;
//        ["late"]  — run the remembered callbacks NOW, even if they were
//                    cleared since (a timer that was already queued when
//                    the finger lifted, or a throttled one firing late).
// stdout: {"scripts": [[event, ...], ...]}; events: ["fire"], ["reset", why],
//   ["press", result], ["state", s], ["progress", p] (rounded to 0.01).
"use strict";
const path = require("path");
const fs = require("fs");

const Hold = require(path.join(__dirname, "..", "..", "src", "dashboard", "web", "js",
                               "components", "hold.js"));
const input = JSON.parse(fs.readFileSync(0, "utf8"));

const out = (input.scripts || []).map(({ opts, ops }) => {
    const events = [];
    let now = 1000;
    let timers = [];
    let nextId = 1;
    let snapped = [];
    const add = (fn, ms, every) => {
        const t = { id: nextId++, at: now + ms, fn, live: true, every };
        timers.push(t);
        return t.id;
    };
    const clear = (id) => { for (const t of timers) if (t.id === id) t.live = false; };
    const h = Hold.createHold(Object.assign({}, opts || {}, {
        now: () => now,
        setTimeout: (fn, ms) => add(fn, ms, 0),
        clearTimeout: clear,
        setInterval: (fn, ms) => add(fn, ms, ms),
        clearInterval: clear,
        onFire: () => events.push(["fire"]),
        onReset: (why) => events.push(["reset", why]),
        onProgress: () => {},
    }));
    for (const [op, ...args] of ops) {
        if (op === "advance") {
            const end = now + args[0];
            for (;;) {
                const due = timers.filter((t) => t.live && t.at <= end).sort((a, b) => a.at - b.at)[0];
                if (!due) break;
                now = due.at;
                if (due.every) due.at += due.every; else due.live = false;
                due.fn();
            }
            now = end;
            timers = timers.filter((t) => t.live);
        } else if (op === "press") {
            events.push(["press", h.press(args[0])]);
        } else if (op === "state") {
            events.push(["state", h.state()]);
        } else if (op === "progress") {
            events.push(["progress", Math.round(h.progress() * 100) / 100]);
        } else if (op === "snap") {
            snapped = timers.filter((t) => t.live && !t.every).map((t) => t.fn);
        } else if (op === "late") {
            snapped.forEach((fn) => fn());
        } else {
            h[op](...args);
        }
    }
    return events;
});

process.stdout.write(JSON.stringify({ scripts: out }));
