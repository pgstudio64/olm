"use strict";

// D-233: Gap analysis — 4-step method for distance coloring.
// Shared between editor.js (PE) and catalogue.js (cards).
// Requires CURRENT_SPACING global (set by config.js).

var CONFORMITY_TOL_CM = 5;

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
 * Full 4-step gap analysis (D-233 / CONSTRAINTS.md S2.6).
 *
 * Step 1: characterize both sides (chair / other / wall).
 * Step 2: free space = raw distance - chair encroachments.
 * Step 3: required margin (walking by default in PE).
 * Step 4: compare -> color.
 *
 * @param {number} rawDistCm - Body-to-body (or body-to-wall) distance.
 * @param {object|null} faceA - Effective face on side A (null = wall).
 * @param {object|null} faceB - Effective face on side B (null = wall).
 * @param {object} spacing - CURRENT_SPACING object.
 * @param {object} [opts] - Optional: {isMainCorridor, isDeadEnd}.
 * @returns {{color: string, freeSpaceCm: number, minReqCm: number,
 *            ruleName: string, chairNote: string}}
 */
function analyzeGap(rawDistCm, faceA, faceB, spacing, opts) {
  if (!spacing) {
    return {
      color: COLOR_GAP_LABEL,
      freeSpaceCm: rawDistCm,
      minReqCm: 0,
      ruleName: "",
      chairNote: "",
    };
  }

  // Step 1 — characterize sides
  var sideA = classifyGapSide(faceA);
  var sideB = classifyGapSide(faceB);

  // Step 2 — free space
  var encroachment = sideA.chairClearanceCm + sideB.chairClearanceCm;
  var freeSpace = rawDistCm - encroachment;

  // Step 3 — required margin
  var o = opts || {};
  var minReq, ruleName;
  if (o.isMainCorridor) {
    minReq = spacing.main_corridor_cm;
    ruleName = "Main corridor";
  } else if (o.isDeadEnd) {
    minReq = spacing.slip_in_margin_cm;
    ruleName = "Slip-in (single desk)";
  } else {
    minReq = spacing.walking_margin_cm;
    ruleName = "Walking margin";
  }

  // Step 4 — compare
  var color;
  if (freeSpace > minReq + CONFORMITY_TOL_CM) {
    color = "#58c080";  // green
  } else if (freeSpace >= minReq - CONFORMITY_TOL_CM) {
    color = "#c8a050";  // yellow
  } else {
    color = "#c05858";  // red
  }

  // Chair note for sub-label
  var chairNote = "";
  var nChairs = (sideA.type === "chair" ? 1 : 0)
              + (sideB.type === "chair" ? 1 : 0);
  if (nChairs === 2) {
    chairNote = "\u2212" + encroachment + " cm back-to-back";
  } else if (nChairs === 1) {
    chairNote = "\u2212" + encroachment + " cm chair";
  }

  return {
    color: color,
    freeSpaceCm: freeSpace,
    minReqCm: minReq,
    ruleName: ruleName,
    chairNote: chairNote,
  };
}

/**
 * Determine the effective face of a block facing a given direction.
 *
 * @param {object} faces - Effective faces {north, south, east, west}.
 * @param {string} dir - "north"|"south"|"east"|"west".
 * @returns {object|null} Face object or null.
 */
function getFacingFace(faces, dir) {
  return (faces && faces[dir]) || null;
}

/**
 * Map a gap direction to the block face that borders it.
 *
 * For block-to-block gaps:
 *   right neighbor -> A's east face, B's west face
 *   below neighbor -> A's south face, B's north face
 *
 * For block-to-wall gaps:
 *   wall on north  -> block's north face
 *   wall on south  -> block's south face
 *   wall on west   -> block's west face
 *   wall on east   -> block's east face
 */
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
