"use strict";

// D-235 (simplified): distance coloring with a single threshold.
// Without Dijkstra integration in PE, fine-grained rules
// (slip-in / walking / main_corridor + dead-end detection) produce
// too many false positives. Conservative 2-state model:
//   - free space >= walking_margin_cm : green (definitely OK)
//   - free space <  walking_margin_cm : amber (user judges)
// No red, no sub-label, no rule name.
// Shared between editor.js (PE) and catalogue.js (cards).

/**
 * Classify one side of a gap.
 *
 * @param {object|null} faceInfo - Effective face object with
 *   non_superposable_cm, or null for a wall / opening / door zone.
 * @returns {{type: string, chairClearanceCm: number}}
 */
function classifyGapSide(faceInfo) {
  if (!faceInfo) return { type: "wall", chairClearanceCm: 0 };
  var nsup = faceInfo.non_superposable_cm || 0;
  if (nsup > 0) return { type: "chair", chairClearanceCm: nsup };
  return { type: "other", chairClearanceCm: 0 };
}

/**
 * Analyze a single gap and decide its colour.
 *
 * @param {number} rawDistCm - Body-to-body (or body-to-wall) distance.
 * @param {object|null} faceA - Effective face on side A (null = wall).
 * @param {object|null} faceB - Effective face on side B (null = wall).
 * @param {object} spacing - CURRENT_SPACING object.
 * @param {object} [opts] - Reserved for future Dijkstra-aware rules.
 * @returns {{color: string, freeSpaceCm: number, minReqCm: number,
 *            ruleName: string, chairNote: string}}
 */
function analyzeGap(rawDistCm, faceA, faceB, spacing, opts) {
  if (!spacing) {
    return {
      color: "#c8a050",
      freeSpaceCm: rawDistCm,
      minReqCm: 0,
      ruleName: "",
      chairNote: "",
    };
  }
  var sideA = classifyGapSide(faceA);
  var sideB = classifyGapSide(faceB);
  var encroachment = sideA.chairClearanceCm + sideB.chairClearanceCm;
  var freeSpace = rawDistCm - encroachment;
  var nChairs = (sideA.type === "chair" ? 1 : 0)
              + (sideB.type === "chair" ? 1 : 0);
  // Default threshold = walking margin. Exception: one chair facing a
  // wall = personal access only, no one passes between chair and wall,
  // so slip-in suffices.
  var minReq;
  if (nChairs === 1 && (sideA.type === "wall" || sideB.type === "wall")) {
    minReq = spacing.slip_in_margin_cm || 0;
  } else {
    minReq = spacing.walking_margin_cm || 0;
  }
  var TOL = 5;
  var color;
  if (freeSpace > minReq + TOL) color = "#58c080";        // green
  else if (freeSpace >= minReq - TOL) color = "#c8a050";  // amber
  else color = "#d88080";                                 // soft red
  return {
    color: color,
    freeSpaceCm: freeSpace,
    minReqCm: minReq,
    ruleName: "",
    chairNote: "",
  };
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
