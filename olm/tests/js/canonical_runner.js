// canonical_runner.js — D-274 Lot 0
// Runs canonical_io.js fromStorage on shared fixtures and outputs
// the canonical results as JSON (one per case).
//
// Usage: node olm/tests/js/canonical_runner.js
//
// Requires: Node.js (no npm dependencies).

"use strict";

var fs = require("fs");
var path = require("path");

// Shim browser globals — canonical_io.js only needs window (and Math).
global.window = {};

// Load canonical_io.js (IIFE that assigns to window.canonicalIO).
var jsPath = path.join(__dirname, "..", "..", "static", "canonical_io.js");
var jsCode = fs.readFileSync(jsPath, "utf-8");
eval(jsCode);  // eslint-disable-line no-eval

var canonicalIO = global.window.canonicalIO;
if (!canonicalIO || typeof canonicalIO.fromStorage !== "function") {
  process.stderr.write("ERROR: canonicalIO.fromStorage not found\n");
  process.exit(1);
}

// Load shared fixtures.
var fixturesPath = path.join(
  __dirname, "..", "fixtures", "canonical_cases.json"
);
var cases = JSON.parse(fs.readFileSync(fixturesPath, "utf-8"));

// Run fromStorage on each case (no scale — pure geometry).
var results = cases.map(function (c) {
  var canon = canonicalIO.fromStorage(c.input_room);
  return {
    width_cm: canon.width_cm,
    depth_cm: canon.depth_cm,
    corridor_face: canon.corridor_face,
    openings: (canon.openings || []).map(function (o) {
      var r = {
        face: o.face,
        offset_cm: o.offset_cm,
        width_cm: o.width_cm,
      };
      if (o.has_door !== undefined) r.has_door = o.has_door;
      if (o.hinge_side) r.hinge_side = o.hinge_side;
      if (o.opens_inward !== undefined) r.opens_inward = o.opens_inward;
      return r;
    }),
    windows: (canon.windows || []).map(function (w) {
      return {
        face: w.face,
        offset_cm: w.offset_cm,
        width_cm: w.width_cm,
      };
    }),
  };
});

process.stdout.write(JSON.stringify(results));
