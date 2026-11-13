// Evaluates the pure helpers of src/dashboard/web/js/components/keyboard.js
// for tests/test_frontend_keyboard.py. Plain node, no packages, no DOM —
// keyboard.js only touches the document when one exists.
//
// stdin:  {"layouts": [[viewportH, nRows], ...], "inputs": [element-like, ...]}
//         element-like: {"tagName": "INPUT", "type": "text", "readOnly": false, ...}
//         (null stays null)
// stdout: {"layouts": [{height, pad, gap, rowH, font}, ...],
//          "inputs": [bool, ...], "rows": ROWS.length, "keys": key count}
"use strict";
const fs = require("fs");
const path = require("path");

const OSK = require(path.join(__dirname, "..", "..", "src", "dashboard", "web", "js",
                              "components", "keyboard.js"));
const input = JSON.parse(fs.readFileSync(0, "utf8"));

const layouts = (input.layouts || []).map(([vh, n]) => OSK.oskLayout(vh, n));
const inputs = (input.inputs || []).map((el) => OSK.isOskInput(el));
// Everything in ROWS is a key except the typed-text preview.
const keys = OSK.ROWS.reduce((n, row) => n + row.filter((k) => k !== "preview").length, 0);

process.stdout.write(JSON.stringify({ layouts, inputs, rows: OSK.ROWS.length, keys }));
