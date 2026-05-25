"use strict";

// D-257 + D-312: signed-margin model for distance coloring.
// Each gap's margin = rawDist - emprise(A) - emprise(B) - walking (if passage).
// Emprise chair side:
//   - passage (Dijkstra traversal): chair_clearance_cm only (AFNOR fig 8/9).
//   - dead-end (no passage): chair_clearance_cm + slip_in_margin_cm (AFNOR fig 7).
// Emprise non-chair/wall = 0.
// Passage = determined by Dijkstra (caller provides opts.passage boolean).
// Tolerance = spacing.distance_tolerance_cm (per standard, default 5).
// Shared between editor.js (PE), catalogue.js (cards), shared.js wrappers.

/**
 * Classify one side of a gap as chair or non-chair.
 *
 * @param {object|null} faceInfo - Effective face object with
 *   non_superposable_cm, or null for a wall / opening / door zone.
 * @returns {{type: string}}
 */
function classifyGapSide(faceInfo) {
  if (!faceInfo) return { type: "wall" };
  // D-241: internal face = chair in void, no outer clearance
  if (faceInfo.internal) return { type: "other" };
  var nsup = faceInfo.non_superposable_cm || 0;
  if (nsup > 0) return { type: "chair" };
  return { type: "other" };
}

/**
 * Compute the emprise (reserved space) for one side of a gap.
 *
 * D-312: in a passage, slip-in is not cumulated with walking
 * (seated person does not stand while someone walks by — AFNOR fig 8/9).
 * In a dead-end, slip-in is required to access the seat (AFNOR fig 7).
 *
 * @param {{type: string}} side - Output of classifyGapSide.
 * @param {object} spacing - CURRENT_SPACING object.
 * @param {boolean} passage - Whether this gap is a passage.
 * @returns {number} Reserved cm for this side.
 */
function _gapSideEmprise(side, spacing, passage) {
  if (side.type === "chair") {
    var chair = spacing.chair_clearance_cm || 0;
    return passage ? chair : chair + (spacing.slip_in_margin_cm || 0);
  }
  return 0;
}

/**
 * Format a signed margin for display: "+12", "0", "-8".
 *
 * @param {number} marge - Signed margin in cm.
 * @returns {string}
 */
function formatMarge(marge) {
  if (marge > 0) return "+" + marge;
  return String(marge);
}

/**
 * Analyze a single gap and decide its colour via signed margin.
 *
 * D-257: replaces the D-235 heuristic. Margin = rawDist - emprise(A)
 * - emprise(B) - walking (if passage). Color from tolerance band.
 *
 * @param {number} rawDistCm - Body-to-body (or body-to-wall) distance.
 * @param {object|null} faceA - Effective face on side A (null = wall).
 * @param {object|null} faceB - Effective face on side B (null = wall).
 * @param {object} spacing - CURRENT_SPACING object.
 * @param {object} [opts] - { passage: boolean } from Dijkstra analysis.
 * @returns {{color: string, marge: number}}
 */
function analyzeGap(rawDistCm, faceA, faceB, spacing, opts) {
  if (!spacing) {
    return { color: "#c8a050", marge: rawDistCm };
  }
  var sideA = classifyGapSide(faceA);
  var sideB = classifyGapSide(faceB);
  var passage = opts && opts.passage;
  var empriseA = _gapSideEmprise(sideA, spacing, passage);
  var empriseB = _gapSideEmprise(sideB, spacing, passage);
  var walking = passage ? (spacing.walking_margin_cm || 0) : 0;
  var requis = empriseA + empriseB + walking;
  var marge = rawDistCm - requis;
  var tol = spacing.distance_tolerance_cm || 5;
  var color;
  if (marge > tol) color = "#58c080";         // green
  else if (marge >= -tol) color = "#c8a050";   // amber
  else color = "#d88080";                      // red
  return { color: color, marge: marge };
}

/**
 * Determine the effective face of a block facing a given direction.
 */
function getFacingFace(faces, dir) {
  return (faces && faces[dir]) || null;
}

var GAP_DIR_TO_FACES = {
  right:  { a: "east",  b: "west"  },
  below:  { a: "south", b: "north" },
};

var WALL_DIR_TO_FACE = {
  north: "north",
  south: "south",
  west:  "west",
  east:  "east",
};
