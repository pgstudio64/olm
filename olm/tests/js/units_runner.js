// units_runner.js — D-274 Lot 1
// Runs units.js pxToCm/cmToPx on test cases and outputs JSON results.
//
// Usage: node olm/tests/js/units_runner.js

"use strict";

var fs = require("fs");
var path = require("path");

// Shim browser globals.
global.window = {};

// Load units.js (exposes window.INCH_TO_CM, pxToCm, cmToPx, etc.).
var jsPath = path.join(__dirname, "..", "..", "static", "units.js");
var jsCode = fs.readFileSync(jsPath, "utf-8");
eval(jsCode);  // eslint-disable-line no-eval

var pxToCm = global.window.pxToCm;
var cmToPx = global.window.cmToPx;
var drawingScaleToCmPerPx = global.window.drawingScaleToCmPerPx;

if (!pxToCm || !cmToPx || !drawingScaleToCmPerPx) {
  process.stderr.write("ERROR: units.js functions not found\n");
  process.exit(1);
}

// Same cases as test_units.py.
var results = [
  { fn: "pxToCm", args: [100, 2.96], result: pxToCm(100, 2.96) },
  { fn: "pxToCm", args: [1, 0.5],    result: pxToCm(1, 0.5) },
  { fn: "pxToCm", args: [5, 0.5],    result: pxToCm(5, 0.5) },
  { fn: "pxToCm", args: [3, 0.5],    result: pxToCm(3, 0.5) },
  { fn: "cmToPx", args: [296, 2.96], result: cmToPx(296, 2.96) },
  { fn: "cmToPx", args: [1, 2.0],    result: cmToPx(1, 2.0) },
  { fn: "cmToPx", args: [5, 2.0],    result: cmToPx(5, 2.0) },
  { fn: "drawingScaleToCmPerPx", args: [100, 72],
    result: drawingScaleToCmPerPx(100, 72) },
];

process.stdout.write(JSON.stringify(results));
