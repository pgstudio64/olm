// circulation_runner.js — controlled study harness for walking-margin / Dijkstra
//
// Loads the REAL production JS (block_constants.js, block_geometry.js,
// distance_rules.js, shared.js) plus the relevant editor.js helpers
// (_isPassage, _isPassageAlong, _gapResidualCells), shims the browser
// globals, and runs computeCirculationInfo() on synthetic scenarios so we
// can observe passage detection before and after the walking-margin fix.
//
// Usage: node olm/tests/js/circulation/circulation_runner.js [blockType]
//
// No npm dependencies. Pure Node.

"use strict";

var fs = require("fs");
var path = require("path");

var STATIC = path.join(__dirname, "..", "..", "..", "static");
var EDITOR = path.join(STATIC, "editor.js");

function read(p) { return fs.readFileSync(p, "utf-8"); }

// Extract a top-level `function NAME(...) { ... }` body by brace matching.
function extractFn(src, name) {
  var sig = "function " + name + "(";
  var i = src.indexOf(sig);
  if (i < 0) throw new Error("function not found: " + name);
  var brace = src.indexOf("{", i);
  var depth = 0, j = brace;
  for (; j < src.length; j++) {
    if (src[j] === "{") depth++;
    else if (src[j] === "}") { depth--; if (depth === 0) { j++; break; } }
  }
  return src.slice(i, j);
}

var editorSrc = read(EDITOR);

// ---- Build one combined eval scope so every const/var/function sees the others.
var parts = [
  read(path.join(STATIC, "block_constants.js")),
  read(path.join(STATIC, "block_geometry.js")),
  read(path.join(STATIC, "distance_rules.js")),
  read(path.join(STATIC, "shared.js")),
  extractFn(editorSrc, "_isPassage"),
  extractFn(editorSrc, "_isPassageAlong"),
  extractFn(editorSrc, "_isPassageForBlock"),
  extractFn(editorSrc, "_gapResidualCells"),
];

var fixture = JSON.parse(read(path.join(__dirname, "block_defs.json")));

// Globals the production code expects.
var window = {};                           // shimmed browser global
var BLOCK_DEFS = fixture.blocks;
var GRID_STEP_CM = 10;
var SCALE = 1;                             // 1 px = 1 cm in this harness
var MARGIN = 0;
var state = null;                          // set per scenario
var CURRENT_SPACING = fixture.spacing;

// shims for helpers used by computeCirculationInfo
parts.push(
  "function totalDesks(){var n=0;state.rows.forEach(function(row){" +
  "row.blocks.forEach(function(b){n+=countDesksInBlock(b.type);});});return n;}");
parts.push(
  "function _furnitureEffectiveDims(item){" +
  "return {width_cm:item.width_cm,depth_cm:item.depth_cm};}");

// Expose globals to the eval'd code.
var __api = {};
eval(parts.join("\n;\n") +
  "\n;__api.computeCirculationInfo = computeCirculationInfo;" +
  "\n;__api._isPassage = _isPassage;" +
  "\n;__api._isPassageAlong = _isPassageAlong;" +
  "\n;__api._isPassageForBlock = _isPassageForBlock;" +
  "\n;__api.getDeskRects = getDeskRects;" +
  "\n;__api.getEffectiveGeom = getEffectiveGeom;" +
  "\n;__api.analyzeGap = analyzeGap;" +
  "\n;__api._gapResidualCells = _gapResidualCells;" +
  "\n;__api.getFacingFace = getFacingFace;" +
  "\n;__api.classifyGapSide = classifyGapSide;" +
  "\n;__api.setDeskDims = function(w,d){ DESK_W = w; DESK_D = d; };");

// Sync DESK_W/DESK_D with the real config (160/80).
__api.setDeskDims(fixture.constants.DESK_W_CM, fixture.constants.DESK_D_CM);

// ---------------------------------------------------------------------------
// Scenario builder: one block, south door, configurable side corridors.
// ---------------------------------------------------------------------------
function makeScenario(blockType, opts) {
  opts = opts || {};
  var def = BLOCK_DEFS[blockType];
  var eo = def.eo_cm, ns = def.ns_cm;
  var westCorr = opts.westCorr != null ? opts.westCorr : 90;
  var eastCorr = opts.eastCorr != null ? opts.eastCorr : 90;
  var southCorr = opts.southCorr != null ? opts.southCorr : 120;
  var roomW = westCorr + eo + eastCorr;
  var roomD = ns + southCorr;
  return {
    standard: "test",
    room_width_cm: roomW,
    room_depth_cm: roomD,
    room_exclusions: [],
    furniture: [],
    room_openings: [],
    room_doors: [{ face: "south", offset_cm: Math.round(roomW / 2 - 45),
                   width_cm: 90 }],
    rows: [{ blocks: [{ type: blockType, orientation: 0,
                         offset_ns_cm: 0, gap_cm: westCorr }] }],
    row_gaps_cm: [],
    _meta: { westCorr: westCorr, eastCorr: eastCorr,
             southCorr: southCorr, eo: eo, ns: ns },
  };
}

// Scenario: two blocks side by side separated by a variable gap.
function makeTwoBlockScenario(blockType, gapCm, opts) {
  opts = opts || {};
  var def = BLOCK_DEFS[blockType];
  var eo = def.eo_cm, ns = def.ns_cm;
  var wallMargin = opts.wallMargin != null ? opts.wallMargin : 90;
  var southCorr = opts.southCorr != null ? opts.southCorr : 120;
  var roomW = wallMargin + eo + gapCm + eo + wallMargin;
  var roomD = ns + southCorr;
  return {
    standard: "test",
    room_width_cm: roomW,
    room_depth_cm: roomD,
    room_exclusions: [],
    furniture: [],
    room_openings: [],
    room_doors: [{ face: "south", offset_cm: Math.round(roomW / 2 - 45),
                   width_cm: 90 }],
    rows: [{ blocks: [
      { type: blockType, orientation: 0, offset_ns_cm: 0,
        gap_cm: wallMargin },
      { type: blockType, orientation: 0, offset_ns_cm: 0,
        gap_cm: gapCm },
    ] }],
    row_gaps_cm: [],
    _meta: { wallMargin: wallMargin, gapCm: gapCm,
             southCorr: southCorr, eo: eo, ns: ns },
  };
}

// Scenario: two single-desk blocks STACKED in two rows, chairs facing the same
// west corridor, door south.  D-303 straddle: the FRONT desk (near door) is a
// passage (traffic to the back desk crosses its chair band), the BACK desk
// (end of corridor) is NOT a passage (no traffic beyond).
function makeStackedScenario(blockType, opts) {
  opts = opts || {};
  var def = BLOCK_DEFS[blockType];
  var eo = def.eo_cm, ns = def.ns_cm;
  var westCorr = opts.westCorr != null ? opts.westCorr : 160;
  var southCorr = opts.southCorr != null ? opts.southCorr : 120;
  var roomW = westCorr + eo + 10;
  var roomD = ns * 2 + southCorr;
  return {
    standard: "test",
    room_width_cm: roomW,
    room_depth_cm: roomD,
    room_exclusions: [],
    furniture: [],
    room_openings: [],
    room_doors: [{ face: "south", offset_cm: Math.round(roomW / 2 - 45),
                   width_cm: 90 }],
    rows: [
      { blocks: [{ type: blockType, orientation: 0, offset_ns_cm: 0,
                   gap_cm: westCorr }] },
      { blocks: [{ type: blockType, orientation: 0, offset_ns_cm: 0,
                   gap_cm: westCorr }] },
    ],
    row_gaps_cm: [0],
    _meta: { westCorr: westCorr, southCorr: southCorr, eo: eo, ns: ns },
  };
}

// Scenario: THREE single-desk blocks STACKED in three rows (D-303 straddle).
// desk1 (south, near door) = passage, desk2 (middle) = passage,
// desk3 (north, end of corridor) = NOT passage.
function makeStacked3Scenario(blockType, opts) {
  opts = opts || {};
  var def = BLOCK_DEFS[blockType];
  var eo = def.eo_cm, ns = def.ns_cm;
  var westCorr = opts.westCorr != null ? opts.westCorr : 160;
  var southCorr = opts.southCorr != null ? opts.southCorr : 120;
  var roomW = westCorr + eo + 10;
  var roomD = ns * 3 + southCorr;
  return {
    standard: "test",
    room_width_cm: roomW,
    room_depth_cm: roomD,
    room_exclusions: [],
    furniture: [],
    room_openings: [],
    room_doors: [{ face: "south", offset_cm: Math.round(roomW / 2 - 45),
                   width_cm: 90 }],
    rows: [
      { blocks: [{ type: blockType, orientation: 0, offset_ns_cm: 0,
                   gap_cm: westCorr }] },
      { blocks: [{ type: blockType, orientation: 0, offset_ns_cm: 0,
                   gap_cm: westCorr }] },
      { blocks: [{ type: blockType, orientation: 0, offset_ns_cm: 0,
                   gap_cm: westCorr }] },
    ],
    row_gaps_cm: [0, 0],
    _meta: { westCorr: westCorr, southCorr: southCorr, eo: eo, ns: ns },
  };
}

// Scenario: TWO COLUMNS of stacked blocks with ASYMMETRIC heights.
// Column A (left) = 3 rows of BLOCK_1 (rows [0, 3*ns]).
// Column B (right) = 2 rows of BLOCK_1 (rows [0, 2*ns]).
// D-303 straddle: colB_front (near door) = passage, colB_back (far) = not.
function makeTwoColumnScenario(blockType, opts) {
  opts = opts || {};
  var def = BLOCK_DEFS[blockType];
  var eo = def.eo_cm, ns = def.ns_cm;
  var westCorr = opts.westCorr != null ? opts.westCorr : 160;
  var midGap = opts.midGap != null ? opts.midGap : 160;
  var southCorr = opts.southCorr != null ? opts.southCorr : 120;
  var nRowsA = opts.nRowsA != null ? opts.nRowsA : 3;
  var nRowsB = opts.nRowsB != null ? opts.nRowsB : 2;
  var maxRows = Math.max(nRowsA, nRowsB);
  var roomW = westCorr + eo + midGap + eo + 10;
  var roomD = ns * maxRows + southCorr;
  var rows = [];
  var rowGaps = [];
  for (var ri = 0; ri < maxRows; ri++) {
    var blks = [];
    if (ri < nRowsA) {
      blks.push({ type: blockType, orientation: 0, offset_ns_cm: 0,
                   gap_cm: westCorr });
    }
    if (ri < nRowsB) {
      // If colA is absent in this row, colB still needs its gap from the
      // left wall: westCorr + eo (colA slot) + midGap.
      var bGap = ri < nRowsA ? midGap : westCorr + eo + midGap;
      blks.push({ type: blockType, orientation: 0, offset_ns_cm: 0,
                   gap_cm: bGap });
    }
    rows.push({ blocks: blks });
    if (ri < maxRows - 1) rowGaps.push(0);
  }
  return {
    standard: "test",
    room_width_cm: roomW,
    room_depth_cm: roomD,
    room_exclusions: [],
    furniture: [],
    room_openings: [],
    room_doors: [{ face: "south", offset_cm: Math.round(roomW / 2 - 45),
                   width_cm: 90 }],
    rows: rows,
    row_gaps_cm: rowGaps,
    _meta: { westCorr: westCorr, midGap: midGap, southCorr: southCorr,
             eo: eo, ns: ns, nRowsA: nRowsA, nRowsB: nRowsB },
  };
}

function runTwoColumns(blockType, opts) {
  var scn = makeTwoColumnScenario(blockType, opts);
  state = scn;
  var ci = __api.computeCirculationInfo();
  var m = scn._meta;
  var ns = m.ns, eo = m.eo, westCorr = m.westCorr, midGap = m.midGap;
  console.log("==================================================================");
  console.log("TWO_COLUMNS " + m.nRowsA + "A+" + m.nRowsB + "B " +
    blockType + "  room " + scn.room_width_cm + "x" + scn.room_depth_cm +
    "  westCorr=" + westCorr + " midGap=" + midGap);

  var faces0 = __api.getEffectiveGeom(blockType, 0).faces;
  var xA = westCorr, xB = westCorr + eo + midGap;
  // Build block descriptors for all blocks.
  var allBlks = [];
  for (var ri = 0; ri < Math.max(m.nRowsA, m.nRowsB); ri++) {
    if (ri < m.nRowsA) {
      allBlks.push({ deskX: xA, deskY: ri * ns, deskW: eo, deskH: ns,
                      faces: faces0 });
    }
    if (ri < m.nRowsB) {
      allBlks.push({ deskX: xB, deskY: ri * ns, deskW: eo, deskH: ns,
                      faces: faces0 });
    }
  }
  var spacing = CURRENT_SPACING;

  // Test column B blocks (back = row0, front = last row of B).
  var colBBlks = allBlks.filter(function (b) { return b.deskX === xB; });
  var labels = [
    ["colB_back",  colBBlks[0]],
    ["colB_front", colBBlks[colBBlks.length - 1]],
  ];
  labels.forEach(function (e) {
    var label = e[0], blk = e[1];
    var prod = passageProd(ci, blk, "west", spacing, allBlks);
    var rawCm = midGap;
    var faceObj = __api.getFacingFace(blk.faces, "west");
    var gap = __api.analyzeGap(rawCm, faceObj, null, spacing,
      { passage: prod.passage });
    console.log("  " + label + " west gap: PROD passage=" + prod.passage +
      " -> " + colorName(gap.color) + " (marge=" + gap.marge + ")");
    RESULTS.push({
      scenario: "TWOCOL_" + blockType, width: midGap,
      kind: "twocol", face: "west", position: label,
      prod: prod.passage, color: colorName(gap.color), marge: gap.marge,
    });
  });
}

function runStacked(blockType, opts) {
  var scn = makeStackedScenario(blockType, opts);
  state = scn;
  var ci = __api.computeCirculationInfo();
  var ns = scn._meta.ns, westCorr = scn._meta.westCorr, eo = scn._meta.eo;
  console.log("==================================================================");
  console.log("STACKED 2x " + blockType + "  room " + scn.room_width_cm + "x" +
    scn.room_depth_cm + "  westCorr=" + westCorr);
  // Two blocks: row0 = BACK (north, y0..ns), row1 = FRONT (south, y ns..2ns).
  var spacing = CURRENT_SPACING;
  var faces0 = __api.getEffectiveGeom(blockType, 0).faces;
  var backBlk = { deskX: westCorr, deskY: 0, deskW: eo, deskH: ns,
                  faces: faces0 };
  var frontBlk = { deskX: westCorr, deskY: ns, deskW: eo, deskH: ns,
                   faces: faces0 };
  var stackedAll = [backBlk, frontBlk];
  [["BACK(north,row0)", backBlk], ["FRONT(south,row1)", frontBlk]]
      .forEach(function (e) {
    var label = e[0], blk = e[1];
    var prod = passageProd(ci, blk, "west", spacing, stackedAll);
    var rawCm = westCorr;
    var faceObj = __api.getFacingFace(blk.faces, "west");
    var gap = __api.analyzeGap(rawCm, faceObj, null, spacing,
      { passage: prod.passage });
    console.log("  " + label + " west gap: PROD passage=" + prod.passage +
      " -> " + colorName(gap.color) + " (marge=" + gap.marge + ")");
    var pos = label.indexOf("BACK") >= 0 ? "back" : "front";
    RESULTS.push({
      scenario: "STACKED_" + blockType, width: westCorr,
      kind: "stacked", face: "west", position: pos,
      prod: prod.passage, color: colorName(gap.color), marge: gap.marge,
    });
  });
  // Per-path penetration (row-span of the FULL path = door->arrival).
  ci.paths.forEach(function (p, i) {
    var arr = p.points[0], mnR = Infinity, mxR = -Infinity;
    p.points.forEach(function (pt) { if (pt.r < mnR) mnR = pt.r; if (pt.r > mxR) mxR = pt.r; });
    console.log("  path#" + i + " arrival y" + (arr.r * GRID_STEP_CM) +
      "  full row-span=" + ((mxR - mnR + 1) * GRID_STEP_CM) + "cm");
  });
  console.log(renderMap(ci, scn));
}

function runStacked3(blockType, opts) {
  var scn = makeStacked3Scenario(blockType, opts);
  state = scn;
  var ci = __api.computeCirculationInfo();
  var ns = scn._meta.ns, westCorr = scn._meta.westCorr, eo = scn._meta.eo;
  console.log("==================================================================");
  console.log("STACKED3 3x " + blockType + "  room " + scn.room_width_cm + "x" +
    scn.room_depth_cm + "  westCorr=" + westCorr);
  var spacing = CURRENT_SPACING;
  var faces0 = __api.getEffectiveGeom(blockType, 0).faces;
  var backBlk = { deskX: westCorr, deskY: 0, deskW: eo, deskH: ns,
                  faces: faces0 };
  var midBlk  = { deskX: westCorr, deskY: ns, deskW: eo, deskH: ns,
                  faces: faces0 };
  var frontBlk = { deskX: westCorr, deskY: 2 * ns, deskW: eo, deskH: ns,
                   faces: faces0 };
  var all3 = [backBlk, midBlk, frontBlk];
  [["BACK(north,row0)", backBlk], ["MID(row1)", midBlk],
   ["FRONT(south,row2)", frontBlk]].forEach(function (e) {
    var label = e[0], blk = e[1];
    var prod = passageProd(ci, blk, "west", spacing, all3);
    var rawCm = westCorr;
    var faceObj = __api.getFacingFace(blk.faces, "west");
    var gap = __api.analyzeGap(rawCm, faceObj, null, spacing,
      { passage: prod.passage });
    console.log("  " + label + " west gap: PROD passage=" + prod.passage +
      " -> " + colorName(gap.color) + " (marge=" + gap.marge + ")");
    var pos = label.indexOf("BACK") >= 0 ? "back"
      : label.indexOf("MID") >= 0 ? "mid" : "front";
    RESULTS.push({
      scenario: "STACKED3_" + blockType, width: westCorr,
      kind: "stacked3", face: "west", position: pos,
      prod: prod.passage, color: colorName(gap.color), marge: gap.marge,
    });
  });
  console.log(renderMap(ci, scn));
}

// ASCII render of grid + paths + arrival points.
function renderMap(ci, scn) {
  var glyph = [];
  for (var r = 0; r < ci.rows; r++) {
    glyph[r] = [];
    for (var c = 0; c < ci.cols; c++) {
      glyph[r][c] = ci.grid[r][c] === 1 ? "x" : (ci.grid[r][c] === 2
        ? "E" : ".");
    }
  }
  // mark block bodies '#'
  var cellCm = GRID_STEP_CM;
  if (scn._meta.westCorr != null) {
    var m = scn._meta;
    var bx0 = Math.floor(m.westCorr / cellCm);
    var bx1 = Math.ceil((m.westCorr + m.eo) / cellCm);
    for (var r = 0; r < Math.ceil(m.ns / cellCm); r++)
      for (var c = bx0; c < bx1; c++)
        if (r < ci.rows && c < ci.cols) glyph[r][c] = "#";
  }
  // paths
  ci.paths.forEach(function (p) {
    p.points.forEach(function (pt, idx) {
      if (glyph[pt.r][pt.c] === ".") glyph[pt.r][pt.c] = idx === 0
        ? "@" : "*";
      else if (idx === 0) glyph[pt.r][pt.c] = "@";
    });
  });
  return glyph.map(function (row) { return row.join(""); }).join("\n");
}

// JSON mode (--json): collect structured results for pytest, silence logs.
var JSON_MODE = process.argv.indexOf("--json") >= 0;
var RESULTS = [];
var _log = console.log;
if (JSON_MODE) console.log = function () {};

// Passage detection using REAL prod functions.
// For wall gaps (b=null): D-303 straddle OR _isPassageAlong (intra-block).
// For block-to-block gaps: _isPassageAlong (D-297).
var DESK_W_HARNESS = fixture.constants.DESK_W_CM;
function passageProd(ci, blockA, face, spacing, allBlocks) {
  var rect = __api._gapResidualCells(face, blockA, null, spacing, state);
  var band = __api._gapResidualCells(face, blockA, null, spacing, state,
    "walkable");
  var pass;
  if (allBlocks) {
    // Wall gap: D-303 straddle (inter-block) OR along (intra-block).
    pass = band && (__api._isPassageForBlock(ci, band, band.axis,
        blockA, face)
      || __api._isPassageAlong(ci, band, band.axis, DESK_W_HARNESS));
  } else {
    // Block-to-block gap: original D-297 logic.
    pass = (rect && __api._isPassage(ci, rect, rect.axis))
      || (band && __api._isPassageAlong(ci, band, band.axis,
          DESK_W_HARNESS));
  }
  return { passage: !!pass, rect: rect, band: band };
}

// Legacy detection (before fix): only _isPassage on residual rect.
function passageLegacy(ci, blockA, face, spacing) {
  var rect = __api._gapResidualCells(face, blockA, null, spacing, state);
  var pass = rect ? __api._isPassage(ci, rect, rect.axis) : false;
  return { passage: pass, rect: rect };
}

function colorName(hex) {
  if (hex === "#58c080") return "GREEN";
  if (hex === "#c8a050") return "AMBER";
  if (hex === "#d88080") return "RED";
  return hex;
}

function runOne(blockType, opts) {
  var scn = makeScenario(blockType, opts);
  state = scn;
  var ci = __api.computeCirculationInfo();
  console.log("==================================================================");
  console.log(blockType + "  room " + scn.room_width_cm + "x" +
    scn.room_depth_cm + "  corridors W=" + scn._meta.westCorr +
    " E=" + scn._meta.eastCorr + " S=" + scn._meta.southCorr +
    "  cell=" + GRID_STEP_CM + "cm");
  console.log("minPassageCm=" + ci.minPassageCm +
    "  nPaths=" + ci.paths.length);

  // Per-desk arrival point + path length
  var desks = __api.getDeskRects(blockType);
  console.log("desks (canonical block coords): " + desks.map(function (d) {
    return d.label + "[x" + d.x + " y" + d.y + " " + d.w + "x" + d.h +
      " chair" + d.chairSide + "]";
  }).join("  "));
  ci.paths.forEach(function (p, i) {
    var arr = p.points[0];
    console.log("  path#" + i + " arrival cell (r" + arr.r + ",c" + arr.c +
      ") = (x" + (arr.c * GRID_STEP_CM) + ",y" + (arr.r * GRID_STEP_CM) +
      ")  len=" + p.points.length + "  worstColor=" + p.worst);
  });

  // Per-block wall-gap passage analysis.
  var g = __api.getEffectiveGeom(blockType, 0);
  var a = {
    deskX: scn._meta.westCorr, deskY: 0,
    deskW: scn._meta.eo, deskH: scn._meta.ns,
    faces: g.faces,
  };
  var spacing = CURRENT_SPACING;
  ["west", "east"].forEach(function (face) {
    var rawCm = (face === "west") ? scn._meta.westCorr : scn._meta.eastCorr;
    var faceObj = __api.getFacingFace(a.faces, face);
    var legacy = passageLegacy(ci, a, face, spacing);
    var prod = passageProd(ci, a, face, spacing, [a]);
    var legacyGap = __api.analyzeGap(rawCm, faceObj, null, spacing,
      { passage: legacy.passage });
    var prodGap = __api.analyzeGap(rawCm, faceObj, null, spacing,
      { passage: prod.passage });
    console.log("  GAP " + face + ": LEGACY=" + legacy.passage +
      " -> " + colorName(legacyGap.color) +
      "   ||  PROD=" + prod.passage + " -> " + colorName(prodGap.color) +
      "   [raw=" + rawCm + ", marge=" + prodGap.marge + "]");
    RESULTS.push({
      scenario: blockType, width: opts.westCorr != null ? opts.westCorr : 90,
      kind: "wall", face: face, legacy: legacy.passage, prod: prod.passage,
      color: colorName(prodGap.color), marge: prodGap.marge,
    });
  });

  console.log(renderMap(ci, scn));
  return { scn: scn, ci: ci };
}

function runTwoBlocks(blockType, gapCm, opts) {
  var scn = makeTwoBlockScenario(blockType, gapCm, opts);
  state = scn;
  var ci = __api.computeCirculationInfo();
  console.log("==================================================================");
  console.log("TWO " + blockType + "  gap=" + gapCm +
    "  room " + scn.room_width_cm + "x" + scn.room_depth_cm +
    "  wallMargin=" + scn._meta.wallMargin +
    "  cell=" + GRID_STEP_CM + "cm");
  console.log("minPassageCm=" + ci.minPassageCm +
    "  nPaths=" + ci.paths.length);

  // Analyse the gap between the two blocks (right gap from block A to B).
  var g = __api.getEffectiveGeom(blockType, 0);
  var wm = scn._meta.wallMargin;
  var eo = scn._meta.eo;
  var aBlock = {
    deskX: wm, deskY: 0,
    deskW: eo, deskH: scn._meta.ns,
    faces: g.faces,
  };
  var bBlock = {
    deskX: wm + eo + gapCm, deskY: 0,
    deskW: eo, deskH: scn._meta.ns,
    faces: g.faces,
  };
  var spacing = CURRENT_SPACING;

  // Right gap between the two blocks.
  var rectAB = __api._gapResidualCells("right", aBlock, bBlock, spacing,
    state);
  var bandAB = __api._gapResidualCells("right", aBlock, bBlock, spacing,
    state, "walkable");
  var legacyAB = rectAB ? __api._isPassage(ci, rectAB, rectAB.axis) : false;
  var prodAB = (rectAB && __api._isPassage(ci, rectAB, rectAB.axis))
    || (bandAB && __api._isPassageAlong(ci, bandAB, bandAB.axis,
        DESK_W_HARNESS));
  console.log("  BETWEEN-BLOCKS right: LEGACY=" + legacyAB +
    "  PROD=" + prodAB +
    "  rect=" + JSON.stringify(rectAB) +
    "  band=" + JSON.stringify(bandAB));
  RESULTS.push({
    scenario: "TWO_" + blockType, width: gapCm, kind: "between",
    face: "right", legacy: legacyAB, prod: prodAB,
  });

  // Wall gaps for each block (west of A, east of B).
  ["west", "east"].forEach(function (face) {
    var blk = face === "west" ? aBlock : bBlock;
    var rawCm = wm;
    var faceObj = __api.getFacingFace(blk.faces, face);
    var legacy = passageLegacy(ci, blk, face, spacing);
    var prod = passageProd(ci, blk, face, spacing, [aBlock, bBlock]);
    var prodGap = __api.analyzeGap(rawCm, faceObj, null, spacing,
      { passage: prod.passage });
    console.log("  WALL " + face + ": LEGACY=" + legacy.passage +
      " PROD=" + prod.passage + " -> " + colorName(prodGap.color) +
      " [raw=" + rawCm + "]");
  });

  return { scn: scn, ci: ci };
}

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------
var _pos = process.argv.slice(2).filter(function (s) {
  return s.indexOf("--") !== 0;
});
var only = _pos[0];
var widthArg = _pos[1] ? parseInt(_pos[1], 10) : null;

// Single-block scenarios
var types = only ? [only]
  : ["BLOCK_2_SIDE", "BLOCK_3_SIDE", "BLOCK_4_FACE", "BLOCK_6_FACE"];
var widths = widthArg ? [widthArg] : [90, 130, 160, 200];
types.forEach(function (t) {
  widths.forEach(function (w) { runOne(t, { westCorr: w, eastCorr: w }); });
});

// Non-passage controls (depth 1): BLOCK_1 + BLOCK_2_FACE
if (!only) {
  console.log("\n=== NON-PASSAGE CONTROLS (depth 1) ===");
  runOne("BLOCK_1", { westCorr: 90, eastCorr: 90 });
  runOne("BLOCK_2_FACE", { westCorr: 90, eastCorr: 90 });
}

// ORTHO control: BLOCK_2_ORTHO_R has east face internal=true
if (!only) {
  console.log("\n=== ORTHO CONTROL (internal face must NOT trigger) ===");
  runOne("BLOCK_2_ORTHO_R", { westCorr: 90, eastCorr: 90 });
}

// Two-block scenarios
if (!only) {
  console.log("\n=== TWO-BLOCK NON-REGRESSION ===");
  // Traverse corridor: 160 gap between two BLOCK_2_SIDE (paths cross)
  runTwoBlocks("BLOCK_2_SIDE", 160, {});
  // Narrow gap: 90 between two BLOCK_2_SIDE (perpendicular access only)
  runTwoBlocks("BLOCK_2_SIDE", 90, {});

  // Stacked single-desk blocks (D-303 straddle: front=passage, back=not)
  console.log("\n=== STACKED ATTRIBUTION (front vs back desk) ===");
  runStacked("BLOCK_1", { westCorr: 160 });

  // Three stacked (D-303: front+mid=passage, back=not)
  console.log("\n=== STACKED3 (3 desks: front+mid passage, back not) ===");
  runStacked3("BLOCK_1", { westCorr: 160 });

  // Two columns of stacked blocks: end-of-corridor isolation.
  console.log("\n=== TWO COLUMNS (end-of-corridor isolation) ===");
  runTwoColumns("BLOCK_1", { westCorr: 160, midGap: 160 });
}

if (JSON_MODE) _log(JSON.stringify(RESULTS));
