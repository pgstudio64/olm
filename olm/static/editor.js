"use strict";

const SCALE = 0.5;
var GRID_STEP_CM = 10;  // updated from APP_CONFIG.grid_cell_cm
const DEFAULT_ROW_GAP_CM = 180;

let BLOCK_DEFS = {};
// BLOCK_DEFS per standard — loaded at startup for multi-standard rendering
let BLOCK_DEFS_BY_STD = {};
let SPACING_CONFIGS = {};
let CURRENT_SPACING = null;

let state = {
  name: "P_NEW",
  rows: [],
  row_gaps_cm: [],
  room_width_cm: 300,
  room_depth_cm: 480,
  standard: "",  // set dynamically from loaded config
  room_windows: [],      // [{face, offset_cm, width_cm}]
  room_openings: [],     // [{face, offset_cm, width_cm, has_door, opens_inward, hinge_side}]
  room_exclusions: [],   // [{x_cm, y_cm, width_cm, depth_cm}]
  selectedRow: 0,
  selectedBlock: -1,
  selectedExclusion: -1,
  gridVisible: true,
  circVisible: false,
  dirty: false,          // true when pattern has unsaved changes
  amendMode: null,       // { roomName, roomIdx, candidate } when adjusting a solution
  roomAmendMode: null,   // { roomName, originalRoom } when editing room geometry
  overlay: null,         // { dataUrl, pxPerCm, opacity, offsetX, offsetY, imgW, imgH }
  corridor_face: "",     // face with main door (defines canonical south)
  viewBox: { x: 0, y: 0, w: 800, h: 600 },
  zoom: 1.0,
  isPanning: false,
  panStart: { x: 0, y: 0 },
};

function markDirty() {
  if (!state.dirty) {
    state.dirty = true;
    document.querySelector(".ol-header").classList.add("edit-mode");
    document.getElementById("btnAmendCancel").style.display = "";
  }
}
function clearDirty() {
  state.dirty = false;
  document.querySelector(".ol-header").classList.remove("edit-mode");
  if (!state.amendMode) {
    document.getElementById("btnAmendCancel").style.display = "none";
  }
}

function patternOverflowsRoom(p) {
  // Check if block footprints exceed the room
  var rows = p.rows || [];
  var rowGaps = p.row_gaps_cm || [];
  var roomW = p.room_width_cm || 0;
  var roomD = p.room_depth_cm || 0;
  if (rows.length === 0 || roomW === 0) return false;

  var maxRowEO = 0;
  var totalNS = 0;

  for (var ri = 0; ri < rows.length; ri++) {
    var blocks = rows[ri].blocks || [];
    var x = 0;
    var rowMaxNS = 0;
    for (var bi = 0; bi < blocks.length; bi++) {
      var b = blocks[bi];
      if (b.gap_cm) x += b.gap_cm;
      var g = getEffectiveGeom(b.type, b.orientation);
      x += g.eo;
      var nsWithOffset = g.ns + Math.abs(b.offset_ns_cm || 0);
      if (nsWithOffset > rowMaxNS) rowMaxNS = nsWithOffset;
    }
    if (x > maxRowEO) maxRowEO = x;
    totalNS += rowMaxNS;
    if (ri < rows.length - 1) {
      totalNS += (rowGaps[ri] || 0);
    }
  }

  return maxRowEO > roomW || totalNS > roomD;
}

function computeAutoName() {
  const w = state.room_width_cm;
  const d = state.room_depth_cm;
  return w + "x" + d + "_" + getStdLabel(state.standard);
}

function updateAutoName() {
  state.name = computeAutoName();
  _safeText("autoName", state.name);
}

function buildRoomDSL() {
  var lines = ["ROOM " + state.room_width_cm + "x" + state.room_depth_cm];
  state.room_windows.forEach(function(w) {
    var wallLen = (w.face === "north" || w.face === "south") ? state.room_width_cm : state.room_depth_cm;
    if (w.offset_cm === 0 && w.width_cm === wallLen) {
      lines.push("WINDOW " + faceToCode(w.face));
    } else {
      lines.push("WINDOW " + faceToCode(w.face) + " " + w.offset_cm + " " + w.width_cm);
    }
  });
  state.room_openings.forEach(function(o) {
    if (o.has_door) {
      var dir = o.opens_inward ? "INT" : "EXT";
      var hinge = o.hinge_side === "left" ? "L" : "R";
      lines.push("DOOR " + faceToCode(o.face) + " " + o.offset_cm + " " + o.width_cm + " " + dir + " " + hinge);
    } else {
      lines.push("OPENING " + faceToCode(o.face) + " " + o.offset_cm + " " + o.width_cm);
    }
  });
  state.room_exclusions.forEach(function(z) {
    lines.push("EXCLUSION " + z.x_cm + " " + z.y_cm + " " + z.width_cm + " " + z.depth_cm);
  });
  return lines.join("\n");
}

function faceToCode(face) {
  return { north: "N", south: "S", east: "E", west: "W" }[face] || face;
}

function updateRoomDSL() {
  document.getElementById("dslRoom").value = buildRoomDSL();
}

async function applyRoomDSL() {
  markDirty();
  var text = document.getElementById("dslRoom").value.trim();
  if (!text) return;
  try {
    var resp = await fetch("/api/room-dsl/parse", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ dsl: text })
    });
    if (!resp.ok) {
      var err = await resp.json();
      setStatus("Room definition error: " + (err.error || "?"));
      return;
    }
    var data = await resp.json();
    state.room_width_cm = data.width_cm;
    state.room_depth_cm = data.depth_cm;
    state.room_windows = data.windows || [];
    state.room_openings = data.openings || [];
    state.room_exclusions = data.exclusion_zones || [];
    document.getElementById("roomWidth").value = state.room_width_cm;
    document.getElementById("roomDepth").value = state.room_depth_cm;
    if (!state.roomAmendMode) updateAutoName();
    zoomFit();
    setStatus("Room definition applied.");
  } catch (err) {
    setStatus("Room definition error: " + err.message);
  }
}

function renderRoomElements(elements, roomX, roomY, roomWPx, roomHPx, isReview) {
  // Windows — cyan line offset outward (or on wall in review mode)
  var wallThick = isReview ? 0 : 1.5;
  var winStroke = isReview ? 3 : 1.5;
  state.room_windows.forEach(function(w) {
    var pos = wallSegment(w.face, w.offset_cm, w.width_cm, roomX, roomY, roomWPx, roomHPx, wallThick);
    elements.push({ z: 6, s: '<line x1="' + pos.x1 + '" y1="' + pos.y1 +
      '" x2="' + pos.x2 + '" y2="' + pos.y2 +
      '" stroke="#50b8d0" stroke-width="' + winStroke + '" stroke-linecap="round"/>' });
  });

  // Doors and open bays
  state.room_openings.forEach(function(o) {
    var pos = wallSegment(o.face, o.offset_cm, o.width_cm, roomX, roomY, roomWPx, roomHPx);
    var dw = o.width_cm * SCALE;

    // Erase wall under opening (background-colored line)
    elements.push({ z: 5.5, s: '<line x1="' + pos.x1 + '" y1="' + pos.y1 +
      '" x2="' + pos.x2 + '" y2="' + pos.y2 +
      '" stroke="#1e1e1e" stroke-width="3"/>' });

    if (!o.has_door) {
      // Open bay — green line
      elements.push({ z: 6, s: '<line x1="' + pos.x1 + '" y1="' + pos.y1 +
        '" x2="' + pos.x2 + '" y2="' + pos.y2 +
        '" stroke="#80c060" stroke-width="1" stroke-dasharray="4 3"/>' });
      return;
    }

    // Hinged door — delegate arc + leaf geometry to render_shared.
    // West wall inverts the swing↔hinge-coord mapping (see render_shared).
    var swing = o.hinge_side;  // "left" or "right"
    var swingLeft = (swing === "left");
    var hingeAtStart = swingLeft !== (o.face === "west");
    var along, wallCoord;
    if (o.face === "south") {
      along = roomX + o.offset_cm * SCALE; wallCoord = roomY + roomHPx;
    } else if (o.face === "north") {
      along = roomX + o.offset_cm * SCALE; wallCoord = roomY;
    } else if (o.face === "east") {
      along = roomY + o.offset_cm * SCALE; wallCoord = roomX + roomWPx;
    } else { // west
      along = roomY + o.offset_cm * SCALE; wallCoord = roomX;
    }
    var hingeCoord = hingeAtStart ? along : along + dw;
    var freeCoord  = hingeAtStart ? along + dw : along;
    var doorParts = window.renderShared.doorSvg(
      o.face, hingeCoord, freeCoord, wallCoord, swing, o.opens_inward, 1.5);
    elements.push({ z: 6, s: doorParts[0] });
    elements.push({ z: 6, s: doorParts[1] });
  });

  // Exclusion zones — semi-transparent red rectangle, clickable
  state.room_exclusions.forEach(function(z, zi) {
    var zx = roomX + z.x_cm * SCALE;
    var zy = roomY + z.y_cm * SCALE;
    var zw = z.width_cm * SCALE;
    var zh = z.depth_cm * SCALE;
    elements.push({ z: 5, s: '<rect x="' + zx + '" y="' + zy +
      '" width="' + zw + '" height="' + zh +
      '" fill="#c05858" fill-opacity="0.25" stroke="#c05858" stroke-width="0.5"/>' });
    // Highlight if selected — red dashed outline + corner resize handles
    if (zi === state.selectedExclusion) {
      elements.push({ z: 8, s: '<rect x="' + zx + '" y="' + zy +
        '" width="' + zw + '" height="' + zh +
        '" fill="none" stroke="#c05858" stroke-width="1.5" stroke-dasharray="6 3"/>' });
      // Corner resize handles (centered on each corner).
      var hs = 2;
      var corners = [
        { h: 'nw', cx: zx,        cy: zy,        cur: 'nw-resize' },
        { h: 'ne', cx: zx + zw,   cy: zy,        cur: 'ne-resize' },
        { h: 'sw', cx: zx,        cy: zy + zh,   cur: 'sw-resize' },
        { h: 'se', cx: zx + zw,   cy: zy + zh,   cur: 'se-resize' },
      ];
      corners.forEach(function (c) {
        elements.push({ z: 9.2, s: '<rect x="' + (c.cx - hs / 2) +
          '" y="' + (c.cy - hs / 2) + '" width="' + hs + '" height="' + hs +
          '" fill="#c05858" stroke="#ffffff" stroke-width="0.5"' +
          ' data-excl-handle="' + c.h + '" data-excl="' + zi +
          '" style="cursor:' + c.cur + ';"/>' });
      });
    }
    // Clickable zone
    elements.push({ z: 9, s: '<rect x="' + zx + '" y="' + zy +
      '" width="' + zw + '" height="' + zh +
      '" fill="transparent" data-excl="' + zi + '" style="cursor:pointer;"/>' });
  });
}

function wallSegment(face, offset_cm, width_cm, roomX, roomY, roomWPx, roomHPx, outset, sc) {
  // outset > 0 shifts outward from the room
  // sc: scale (defaults to global SCALE)
  var s = sc || SCALE;
  var off = offset_cm * s;
  var w = width_cm * s;
  var d = outset || 0;
  if (face === "north") return { x1: roomX + off, y1: roomY - d, x2: roomX + off + w, y2: roomY - d };
  if (face === "south") return { x1: roomX + off, y1: roomY + roomHPx + d, x2: roomX + off + w, y2: roomY + roomHPx + d };
  if (face === "west") return { x1: roomX - d, y1: roomY + off, x2: roomX - d, y2: roomY + off + w };
  if (face === "east") return { x1: roomX + roomWPx + d, y1: roomY + off, x2: roomX + roomWPx + d, y2: roomY + off + w };
  return { x1: 0, y1: 0, x2: 0, y2: 0 };
}

function setStatus(msg) {
  document.getElementById("statusBar").textContent = msg;
}

function normalizeRowGaps() {
  const target = Math.max(0, state.rows.length - 1);
  while (state.row_gaps_cm.length < target) {
    state.row_gaps_cm.push(DEFAULT_ROW_GAP_CM);
  }
  state.row_gaps_cm.length = target;
}

function totalDesks() {
  let n = 0;
  for (const row of state.rows) {
    for (const b of row.blocks) n += countDesksInBlock(b.type);
  }
  return n;
}

function totalBlocks() {
  return state.rows.reduce((s, r) => s + r.blocks.length, 0);
}
function computePatternDims() {
  if (state.rows.length === 0) return { eoBlocks: 0, nsBlocks: 0, eoTotal: 0, nsTotal: 0 };
  normalizeRowGaps();

  let maxRowEO = 0;
  const rowNS = [];
  let maxWest = 0;
  let maxEast = 0;

  for (const row of state.rows) {
    let x = 0;
    let maxNS = 0;
    for (const b of row.blocks) {
      if (b.gap_cm) x += b.gap_cm;
      const g = getEffectiveGeom(b.type, b.orientation);
      const f = g.faces;
      x += g.eo;
      const nsWithOffset = g.ns + Math.abs(b.offset_ns_cm || 0);
      if (nsWithOffset > maxNS) maxNS = nsWithOffset;
      const we = (f.west ? ((f.west.non_superposable_cm || 0) + (f.west.candidate_cm || 0)) : 0);
      const ee = (f.east ? ((f.east.non_superposable_cm || 0) + (f.east.candidate_cm || 0)) : 0);
      if (we > maxWest) maxWest = we;
      if (ee > maxEast) maxEast = ee;
    }
    if (x > maxRowEO) maxRowEO = x;
    rowNS.push(maxNS);
  }

  let nsBlocks = 0;
  for (let i = 0; i < rowNS.length; i++) {
    nsBlocks += rowNS[i];
    if (i < rowNS.length - 1) {
      nsBlocks += state.row_gaps_cm[i];
    }
  }

  return {
    eoBlocks: maxRowEO,
    nsBlocks: nsBlocks,
    eoTotal: maxWest + maxRowEO + maxEast,
    nsTotal: nsBlocks,
  };
}

function _canonicalAngle(corridorFace) {
  var map = { south: 0, east: 90, north: 180, west: 270 };
  return map[corridorFace] || 0;
}

function _roomVisualInfo(corridorFace, roomWPx, roomHPx) {
  var angle = _canonicalAngle(corridorFace);
  var cx = roomWPx / 2;
  var cy = roomHPx / 2;
  var swap = (angle === 90 || angle === 270);
  return {
    angle: angle,
    cx: cx,
    cy: cy,
    swap: swap,
    visW: swap ? roomHPx : roomWPx,
    visH: swap ? roomWPx : roomHPx,
    visX: swap ? cx - roomHPx / 2 : 0,
    visY: swap ? cy - roomWPx / 2 : 0,
    labelTopVal: swap ? "depth" : "width",
    labelSideVal: swap ? "width" : "depth",
  };
}

function render(targetSvg) {
  try { _renderImpl(targetSvg); }
  catch(e) { console.error("render() error:", e); setStatus("RENDER ERROR: " + e.message); }
}
function _renderImpl(targetSvg) {
  const svg = targetSvg || document.getElementById("canvas");
  const isReview = svg && svg.id === "rvCanvas";
  const isDesign = svg && svg.id === "fpCanvas";
  // Review/Design canvases: skip render entirely if no rooms loaded (shared state residual)
  if ((isReview || isDesign) && (!window.fpData || !window.fpData.rooms || !window.fpData.rooms.length)) {
    svg.innerHTML = "";
    return;
  }
  // Review canvas outside amend mode: never show pattern blocks (shared state residual)
  var _savedRows;
  if (isReview && !state.roomAmendMode) {
    _savedRows = state.rows;
    state.rows = [];
  }
  normalizeRowGaps();

  const MARGIN = 0;
  const hasBlocks = state.rows.length > 0 && totalBlocks() > 0;
  const elements = [];
  // Zoom-compensated font size: labels stay visually constant regardless of zoom/room size.
  // zf = SVG units per CSS pixel — text scaled by zf appears at constant visual size.
  // zf converts a target CSS-pixel size to SVG units: fontSize_svg = targetPx * zf
  // With preserveAspectRatio="meet", scale = min(pxW/vbW, pxH/vbH)
  // If SVG is hidden (inactive tab), reuse last known size
  var svgRect = svg.getBoundingClientRect();
  if (svgRect.width > 0 && svgRect.height > 0) {
    svg._lastPxW = svgRect.width;
    svg._lastPxH = svgRect.height;
  }
  var pxW = svg._lastPxW || svgRect.width || 800;
  var pxH = svg._lastPxH || svgRect.height || 600;
  var vb = state.viewBox;
  var svgScale = Math.min(pxW / vb.w, pxH / vb.h);
  var zf = 1 / svgScale;
  window._currentZf = zf;  // shared with block_svg.js

  let globalWestOffset = 0;  // obsolete, kept for viewBox compatibility
  let totalW = 0;
  let totalH = 0;
  let minX = MARGIN;  // track leftmost x coordinate (west zones)

  if (!hasBlocks) {
    // No blocks: default viewBox based on room size
    totalW = state.room_width_cm * SCALE + MARGIN * 2;
    totalH = state.room_depth_cm * SCALE + MARGIN * 2;
    if (state.viewBox.w === 800 && state.viewBox.h === 600) {
      state.viewBox = { x: -10, y: -10, w: totalW + 20, h: totalH + 20 };
    }
  }

  if (hasBlocks) {
  // Blocks are positioned from the NW corner of the room (MARGIN),
  // independent of zones — desks stay fixed regardless of standard.
  const originX = MARGIN;
  const originY = MARGIN;

  let yRow = originY;
  let globalDeskIndex = 0;

  // Positions for gap labels
  const rowBlockPos = [];
  const rowYPos = [];

  for (let ri = 0; ri < state.rows.length; ri++) {
    const row = state.rows[ri];
    let xBlock = originX;
    let rowMaxNS = 0;
    const curRowBlocks = [];

    for (let bi = 0; bi < row.blocks.length; bi++) {
      const b = row.blocks[bi];
      const g = getEffectiveGeom(b.type, b.orientation);
      const f = g.faces;
      const offsetNS = (b.offset_ns_cm || 0) * SCALE;

      if (b.gap_cm) xBlock += b.gap_cm * SCALE;

      const bx = xBlock;
      const by = yRow + offsetNS;
      const bw = g.eo * SCALE;
      const bh = g.ns * SCALE;
      curRowBlocks.push({ x: bx, y: by, w: bw, h: bh, gap_cm: b.gap_cm || 0 });

      // Setback zone dimensions (always computed for the opaque background)
      var isOrtho = (b.type === "BLOCK_2_ORTHO_R" || b.type === "BLOCK_2_ORTHO_L");
      var wNSup = isOrtho ? 0 : (((f.west && f.west.non_superposable_cm) || 0) * SCALE);
      var eNSup = isOrtho ? 0 : (((f.east && f.east.non_superposable_cm) || 0) * SCALE);
      var nNSup = isOrtho ? 0 : (((f.north && f.north.non_superposable_cm) || 0) * SCALE);
      var sNSup = isOrtho ? 0 : (((f.south && f.south.non_superposable_cm) || 0) * SCALE);
      var wCandPx = isOrtho ? 0 : (((f.west && f.west.candidate_cm) || 0) * SCALE);
      var eCandPx = isOrtho ? 0 : (((f.east && f.east.candidate_cm) || 0) * SCALE);
      var nCandPx = isOrtho ? 0 : (((f.north && f.north.candidate_cm) || 0) * SCALE);
      var sCandPx = isOrtho ? 0 : (((f.south && f.south.candidate_cm) || 0) * SCALE);

      renderBlockZones(elements, bx, by, bw, bh, b.type, b.orientation, f, SCALE, 0.5);

      // Opaque background full footprint (masks the grid under block + zones)
      var blockMinX = bx - wNSup - wCandPx;
      if (blockMinX < minX) minX = blockMinX;
      var wTotal = wNSup + wCandPx;
      var eTotal = eNSup + eCandPx;
      var nTotal = nNSup + nCandPx;
      var sTotal = sNSup + sCandPx;
      // Opaque background: covers block + setback zones (even in circulation mode)
      elements.push({ z: 0.5, s: '<rect x="' + (bx - wTotal) + '" y="' + (by - nTotal) +
        '" width="' + (bw + wTotal + eTotal) + '" height="' + (bh + nTotal + sTotal) +
        '" fill="#1e1e1e"/>' });
      elements.push({ z: 3, s: '<rect x="' + bx + '" y="' + by +
        '" width="' + bw + '" height="' + bh +
        '" fill="none" stroke="' + COLOR_BLOCK_BORDER +
        '" stroke-width="1" stroke-dasharray="4 3"/>' });

      // Workstations (via shared renderBlockDesks)
      globalDeskIndex += renderBlockDesks(elements, bx, by, b.type, b.orientation, SCALE, globalDeskIndex);

      // Highlight selected block (aligned to block edges)
      if (ri === state.selectedRow && bi === state.selectedBlock) {
        elements.push({ z: 8, s: '<rect x="' + bx + '" y="' + by +
          '" width="' + bw + '" height="' + bh +
          '" fill="none" stroke="#58c080" stroke-width="1.5" stroke-dasharray="6 3"/>' });
      }

      // Clickable zone
      elements.push({ z: 9, s: '<rect x="' + bx + '" y="' + by +
        '" width="' + bw + '" height="' + bh +
        '" fill="transparent" data-row="' + ri + '" data-block="' + bi + '"/>' });

      xBlock += bw;
      if (g.ns > rowMaxNS) rowMaxNS = g.ns;
    }

    const rowBottomY = yRow + rowMaxNS * SCALE;
    if (rowBottomY > totalH) totalH = rowBottomY;
    if (xBlock > totalW) totalW = xBlock;

    rowYPos.push({ y: yRow, h: rowMaxNS * SCALE });
    rowBlockPos.push(curRowBlocks);

    yRow += rowMaxNS * SCALE;
    if (ri < state.rows.length - 1) {
      yRow += state.row_gaps_cm[ri] * SCALE;
    }
  }

  // Distance labels between neighboring blocks (z=7)
  // Rule UI-DIST: distance is shown between two blocks if and only if
  //   1. One is the nearest neighbor of the other in a direction (right or below)
  //   2. The DESK footprints of both blocks overlap on the perpendicular axis
  //      (EW overlap for vertical neighbors, NS overlap for horizontal neighbors)
  // Circulation zones are not considered in the overlap test.
  const allBlocks = [];
  for (let ri = 0; ri < rowBlockPos.length; ri++) {
    for (let bi = 0; bi < rowBlockPos[ri].length; bi++) {
      const bp = rowBlockPos[ri][bi];
      const blk = state.rows[ri].blocks[bi];
      const g = getEffectiveGeom(blk.type, blk.orientation);
      const ff = g.faces;
      const isO = (blk.type === "BLOCK_2_ORTHO_R" || blk.type === "BLOCK_2_ORTHO_L");
      // Visual footprint = desk + zones (non_superposable + candidate)
      const wZ = isO ? 0 : (((ff.west && ff.west.non_superposable_cm) || 0) + ((ff.west && ff.west.candidate_cm) || 0)) * SCALE;
      const eZ = isO ? 0 : (((ff.east && ff.east.non_superposable_cm) || 0) + ((ff.east && ff.east.candidate_cm) || 0)) * SCALE;
      const nZ = (((ff.north && ff.north.non_superposable_cm) || 0) + ((ff.north && ff.north.candidate_cm) || 0)) * SCALE;
      const sZ = (((ff.south && ff.south.non_superposable_cm) || 0) + ((ff.south && ff.south.candidate_cm) || 0)) * SCALE;
      allBlocks.push({
        x: bp.x, y: bp.y, w: bp.w, h: bp.h,
        deskX: bp.x, deskY: bp.y, deskW: bp.w, deskH: bp.h,
        vizX: bp.x - wZ, vizY: bp.y - nZ, vizW: bp.w + wZ + eZ, vizH: bp.h + nZ + sZ
      });
    }
  }
  for (let i = 0; i < allBlocks.length; i++) {
    const a = allBlocks[i];
    let nearestRight = null;
    let nearestRightGap = Infinity;
    let nearestBelow = null;
    let nearestBelowGap = Infinity;

    for (let j = 0; j < allBlocks.length; j++) {
      if (i === j) continue;
      const b = allBlocks[j];

      // Right neighbor: b is to the right of a, NS desk overlap
      if (b.deskX > a.deskX) {
        const gapPx = b.deskX - (a.deskX + a.deskW);
        if (gapPx > 0.5 && gapPx < nearestRightGap) {
          const nsOverlap = Math.min(a.deskY + a.deskH, b.deskY + b.deskH)
                          - Math.max(a.deskY, b.deskY);
          if (nsOverlap > 0.5) {
            nearestRightGap = gapPx;
            nearestRight = b;
          }
        }
      }

      // Below neighbor: b is below a, EW desk overlap
      if (b.deskY > a.deskY) {
        const gapPx = b.deskY - (a.deskY + a.deskH);
        if (gapPx > 0.5 && gapPx < nearestBelowGap) {
          const eoOverlap = Math.min(a.deskX + a.deskW, b.deskX + b.deskW)
                          - Math.max(a.deskX, b.deskX);
          if (eoOverlap > 0.5) {
            nearestBelowGap = gapPx;
            nearestBelow = b;
          }
        }
      }
    }

    if (nearestRight) {
      const gapCm = Math.round(nearestRightGap / SCALE);
      const lx = a.deskX + a.deskW + nearestRightGap / 2;
      const overlapTop = Math.max(a.deskY, nearestRight.deskY);
      const overlapBot = Math.min(a.deskY + a.deskH, nearestRight.deskY + nearestRight.deskH);
      const ly = (overlapTop + overlapBot) / 2;
      pushDistLabel(elements, lx, ly + 4 * zf, gapCm, COLOR_GAP_LABEL, zf);
    }

    if (nearestBelow) {
      const gapCm = Math.round(nearestBelowGap / SCALE);
      const overlapLeft = Math.max(a.deskX, nearestBelow.deskX);
      const overlapRight = Math.min(a.deskX + a.deskW, nearestBelow.deskX + nearestBelow.deskW);
      const lx = (overlapLeft + overlapRight) / 2;
      const ly = a.deskY + a.deskH + nearestBelowGap / 2;
      pushDistLabel(elements, lx, ly + 4 * zf, gapCm, COLOR_GAP_LABEL, zf);
    }
  }

  // Block-to-wall distances (z=7) — N, S, W, E
  // Rule V-02: for each block x each direction, show distance to wall
  // UNLESS (1) another block whose visual footprint (desk+zones) overlaps this
  // block on the perpendicular axis is between this block and the wall, or
  // (2) the distance is zero.
  const roomRight = MARGIN + state.room_width_cm * SCALE;
  const roomBottom = MARGIN + state.room_depth_cm * SCALE;
  for (let i = 0; i < allBlocks.length; i++) {
    const a = allBlocks[i];
    const dirs = [
      { axis: "y", sign: -1, wallEdge: MARGIN,     blockEdge: a.deskY,            vizCross: "vizX", vizCrossSize: "vizW" },
      { axis: "y", sign:  1, wallEdge: roomBottom,  blockEdge: a.deskY + a.deskH,  vizCross: "vizX", vizCrossSize: "vizW" },
      { axis: "x", sign: -1, wallEdge: MARGIN,     blockEdge: a.deskX,            vizCross: "vizY", vizCrossSize: "vizH" },
      { axis: "x", sign:  1, wallEdge: roomRight,  blockEdge: a.deskX + a.deskW,  vizCross: "vizY", vizCrossSize: "vizH" },
    ];
    for (const dir of dirs) {
      const dist = dir.sign > 0 ? dir.wallEdge - dir.blockEdge : dir.blockEdge - dir.wallEdge;
      if (dist < 0.5) continue;
      // Is another block between this block and the wall?
      // Overlap test on the VISUAL footprint (desk + zones) on the perpendicular axis.
      let blocked = false;
      for (let j = 0; j < allBlocks.length; j++) {
        if (i === j) continue;
        const o = allBlocks[j];
        const crossOv = Math.min(a[dir.vizCross] + a[dir.vizCrossSize], o[dir.vizCross] + o[dir.vizCrossSize])
                      - Math.max(a[dir.vizCross], o[dir.vizCross]);
        if (crossOv <= 0.5) continue;
        if (dir.sign > 0) {
          const oEdge = dir.axis === "y" ? o.deskY : o.deskX;
          if (oEdge >= dir.blockEdge - 0.5 && oEdge < dir.wallEdge) { blocked = true; break; }
        } else {
          const oFar = dir.axis === "y" ? o.deskY + o.deskH : o.deskX + o.deskW;
          if (oFar <= dir.blockEdge + 0.5 && oFar > dir.wallEdge) { blocked = true; break; }
        }
      }
      if (blocked) continue;
      const dcm = Math.round(dist / SCALE);
      let tx, ty;
      if (dir.axis === "y") {
        tx = a.deskX + a.deskW / 2;
        ty = dir.sign > 0 ? dir.blockEdge + dist / 2 : dir.wallEdge + dist / 2;
      } else {
        tx = dir.sign > 0 ? dir.blockEdge + dist / 2 : dir.wallEdge + dist / 2;
        ty = a.deskY + a.deskH / 2;
      }
      pushDistLabel(elements, tx, ty + 4, dcm, COLOR_GAP_LABEL);
    }
  }

  totalW += MARGIN;
  totalH += MARGIN;
  } // end if (hasBlocks)

  // Draw the room (rectangle)
  var roomWPx = state.room_width_cm * SCALE;
  var roomHPx = state.room_depth_cm * SCALE;
  var roomX = MARGIN;
  var roomY = MARGIN;
  // D-99: during Room amend-mode corner drag, offset the room rendering so
  // the dragged corner visually tracks the mouse while the overlay stays
  // fixed. The offset is set by init_rvtool.js and cleared on commit.
  if (state.roomRenderOffset) {
    roomX += (state.roomRenderOffset.x_cm || 0) * SCALE;
    roomY += (state.roomRenderOffset.y_cm || 0) * SCALE;
  }
  state._roomNW = { x: roomX, y: roomY };
  var isEditor = svg.id === "canvas";
  var wallColor = "#ffffff";
  var wallWidth = isEditor ? 0.75 : 1;
  // Walls drawn above blocks (z=3) but below openings/doors/windows (z=6)
  // and their erase-line (z=5.5). Dimension labels stay on top (z=9.5+).
  elements.push({ z: 4, s: '<rect x="' + roomX + '" y="' + roomY +
    '" width="' + roomWPx + '" height="' + roomHPx +
    '" fill="none" stroke="' + wallColor + '" stroke-width="' + wallWidth + '"/>' });
  // D-99: Room amend mode — 4 corner handles for mouse resize in Room tab.
  // Dragging any corner shifts the room AND translates all anchored content
  // (windows, doors, openings, exclusions) so they keep their absolute
  // position. See init_rvtool.js roomResize handlers.
  if (isReview && state.roomAmendMode) {
    var rhs = 2;
    var roomCorners = [
      { h: 'nw', cx: roomX,           cy: roomY,           cur: 'nw-resize' },
      { h: 'ne', cx: roomX + roomWPx, cy: roomY,           cur: 'ne-resize' },
      { h: 'sw', cx: roomX,           cy: roomY + roomHPx, cur: 'sw-resize' },
      { h: 'se', cx: roomX + roomWPx, cy: roomY + roomHPx, cur: 'se-resize' },
    ];
    roomCorners.forEach(function (c) {
      elements.push({ z: 9.2, s: '<rect x="' + (c.cx - rhs / 2) +
        '" y="' + (c.cy - rhs / 2) + '" width="' + rhs + '" height="' + rhs +
        '" fill="#c05858" stroke="#ffffff" stroke-width="0.5"' +
        ' data-room-handle="' + c.h + '" style="cursor:' + c.cur + ';"/>' });
    });
  }
  // Room dimension labels — data already in local coordinates, no swap needed
  var dimFs = (16.5 * zf).toFixed(1);
  var dimOff = 16 * zf;
  var dimBgColor = "#0e0e0d";
  var dimCharW = dimFs * 0.62;  // approximate monospace char width
  var dimPadX = dimFs * 0.3, dimPadY = dimFs * 0.2;
  // Width label (top)
  var wLabel = state.room_width_cm + ' cm';
  var wLabelW = wLabel.length * dimCharW;
  var wLabelX = roomX + roomWPx / 2;
  var wLabelY = roomY - dimOff;
  elements.push({ z: 9.5, s: '<rect x="' + (wLabelX - wLabelW / 2 - dimPadX).toFixed(1) +
    '" y="' + (wLabelY - dimFs * 0.75 - dimPadY).toFixed(1) +
    '" width="' + (wLabelW + dimPadX * 2).toFixed(1) +
    '" height="' + (dimFs * 1.1 + dimPadY * 2).toFixed(1) +
    '" rx="' + (dimFs * 0.2).toFixed(1) + '" fill="' + dimBgColor + '" opacity="0.85"/>' });
  elements.push({ z: 10, s: '<text x="' + wLabelX + '" y="' + wLabelY +
    '" text-anchor="middle" fill="' + COLOR_RULER + '" font-size="' + dimFs + '" font-family="monospace">' +
    wLabel + '</text>' });
  // Depth label (left, rotated)
  var dLabel = state.room_depth_cm + ' cm';
  var dLabelW = dLabel.length * dimCharW;
  var dLabelX = roomX - dimOff;
  var dLabelY = roomY + roomHPx / 2;
  elements.push({ z: 9.5, s: '<rect x="' + (dLabelX - dLabelW / 2 - dimPadX).toFixed(1) +
    '" y="' + (dLabelY - dimFs * 0.75 - dimPadY).toFixed(1) +
    '" width="' + (dLabelW + dimPadX * 2).toFixed(1) +
    '" height="' + (dimFs * 1.1 + dimPadY * 2).toFixed(1) +
    '" rx="' + (dimFs * 0.2).toFixed(1) + '" fill="' + dimBgColor + '" opacity="0.85"' +
    ' transform="rotate(-90,' + dLabelX + ',' + dLabelY + ')"/>' });
  elements.push({ z: 10, s: '<text x="' + dLabelX + '" y="' + dLabelY +
    '" text-anchor="middle" fill="' + COLOR_RULER + '" font-size="' + dimFs + '" font-family="monospace"' +
    ' transform="rotate(-90,' + dLabelX + ',' + dLabelY + ')">' +
    dLabel + '</text>' });

  // Windows, doors, openings, exclusion zones
  renderRoomElements(elements, roomX, roomY, roomWPx, roomHPx, isReview);

  // Circulation — smoothed polylines, width proportional to traffic (z=0.2)
  if (hasBlocks && state.circVisible) {
    var circ = computeCirculationInfo();
    if (circ && circ.paths.length > 0) {
      var cellPx = GRID_STEP_CM * SCALE;
      var halfCell = cellPx / 2;
      var CIRC_COLORS = ["#58c080", "#c8a050", "#c05858"];
      var STROKE_PER_DESK = 1.0;
      var MIN_STROKE = 1.5;
      var passage = CURRENT_SPACING ? CURRENT_SPACING.passage_cm : 0;
      var corridorW = CURRENT_SPACING ? CURRENT_SPACING.main_corridor_cm : 0;

      // Color per edge: red/amber only on shared corridors (traffic > 1)
      var edgeWorst = {};
      circ.paths.forEach(function(p) {
        for (var i = 0; i < p.points.length - 1; i++) {
          var a = p.points[i], b = p.points[i + 1];
          var key = Math.min(a.r, b.r) + "," + Math.min(a.c, b.c) + "-" + Math.max(a.r, b.r) + "," + Math.max(a.c, b.c);
          var et = circ.edgeTraffic[key] || 1;
          var pw1 = circ.passWidth[a.r] ? circ.passWidth[a.r][a.c] || 0 : 0;
          var pw2 = circ.passWidth[b.r] ? circ.passWidth[b.r][b.c] || 0 : 0;
          var minPw = Math.min(pw1, pw2) * GRID_STEP_CM;
          var localColor = 0;
          // Red if < passage (ES-06), amber if = passage, green if >
          if (minPw < passage) localColor = 2;
          else if (minPw <= passage) localColor = 1;
          edgeWorst[key] = Math.max(edgeWorst[key] || 0, localColor);
        }
      });

      // Propagate: if a path crosses a red/amber edge, subsequent edges remain so
      circ.paths.forEach(function(p) {
        var worst = 0;
        for (var i = p.points.length - 1; i > 0; i--) {
          var a = p.points[i], b = p.points[i - 1];
          var key = Math.min(a.r, b.r) + "," + Math.min(a.c, b.c) + "-" + Math.max(a.r, b.r) + "," + Math.max(a.c, b.c);
          if ((edgeWorst[key] || 0) > worst) worst = edgeWorst[key];
          if (worst > (edgeWorst[key] || 0)) edgeWorst[key] = worst;
        }
      });

      // Build smoothed polylines per unique path
      // Extract points as SVG coordinates
      function cellToSvg(cell) {
        return { x: roomX + cell.c * cellPx + halfCell, y: roomY + cell.r * cellPx + halfCell };
      }

      // Rendering: smooth paths (Catmull-Rom -> cubic SVG)
      circ.paths.forEach(function(p) {
        if (p.points.length < 2) return;
        var pts = p.points.map(cellToSvg);

        // Simplify: keep only direction-change points + endpoints
        var key_pts = [pts[0]];
        for (var i = 1; i < pts.length - 1; i++) {
          var dx1 = pts[i].x - pts[i-1].x, dy1 = pts[i].y - pts[i-1].y;
          var dx2 = pts[i+1].x - pts[i].x, dy2 = pts[i+1].y - pts[i].y;
          if (Math.abs(dx1 - dx2) > 0.1 || Math.abs(dy1 - dy2) > 0.1) key_pts.push(pts[i]);
        }
        key_pts.push(pts[pts.length - 1]);

        // Average path thickness
        var totalTraffic = 0, nEdges = 0;
        for (var i = 0; i < p.points.length - 1; i++) {
          var a = p.points[i], b = p.points[i + 1];
          var ek = Math.min(a.r, b.r) + "," + Math.min(a.c, b.c) + "-" + Math.max(a.r, b.r) + "," + Math.max(a.c, b.c);
          totalTraffic += circ.edgeTraffic[ek] || 1;
          nEdges++;
        }
        var avgTraffic = nEdges > 0 ? totalTraffic / nEdges : 1;
        var strokeW = MIN_STROKE + STROKE_PER_DESK * avgTraffic;

        // Color = worst edge of the path
        var pathWorst = 0;
        for (var i = 0; i < p.points.length - 1; i++) {
          var a = p.points[i], b = p.points[i + 1];
          var ek = Math.min(a.r, b.r) + "," + Math.min(a.c, b.c) + "-" + Math.max(a.r, b.r) + "," + Math.max(a.c, b.c);
          if ((edgeWorst[ek] || 0) > pathWorst) pathWorst = edgeWorst[ek];
        }

        // SVG path: Catmull-Rom -> cubic curves
        var d = smoothPath(key_pts);

        elements.push({ z: 0.2, s: '<path d="' + d +
          '" fill="none" stroke="' + CIRC_COLORS[pathWorst] +
          '" stroke-width="' + strokeW.toFixed(1) +
          '" stroke-opacity="0.55" stroke-linecap="round" stroke-linejoin="round"/>' });
      });

      // Arrival discs at workstations
      var DISC_RADIUS = 2.5;
      circ.paths.forEach(function(p) {
        if (p.points.length === 0) return;
        var dest = p.points[0];
        var dx = roomX + dest.c * cellPx + halfCell;
        var dy = roomY + dest.r * cellPx + halfCell;
        var pathWorst = 0;
        for (var i = 0; i < p.points.length - 1; i++) {
          var a = p.points[i], b = p.points[i + 1];
          var key = Math.min(a.r, b.r) + "," + Math.min(a.c, b.c) + "-" + Math.max(a.r, b.r) + "," + Math.max(a.c, b.c);
          if ((edgeWorst[key] || 0) > pathWorst) pathWorst = edgeWorst[key];
        }
        elements.push({ z: 0.3, s: '<circle cx="' + dx.toFixed(1) + '" cy="' + dy.toFixed(1) +
          '" r="' + DISC_RADIUS + '" fill="' + CIRC_COLORS[pathWorst] + '" fill-opacity="0.8"/>' });
      });
    }
  }

  // totalW/totalH = always at least the room size
  var roomTotalW = roomWPx + MARGIN * 2;
  var roomTotalH = roomHPx + MARGIN * 2;
  if (totalW < roomTotalW) totalW = roomTotalW;
  if (totalH < roomTotalH) totalH = roomTotalH;

  // Grid: 10cm dots + 1m lines + graduated ruler (z=0: behind everything)
  if (state.gridVisible) {
    const meterPx = 100 * SCALE;
    const vb = state.viewBox;
    var gridParts = window.renderShared.gridSvg({
      vb: vb,
      cmPerPx: 1 / SCALE,
      dotColor: COLOR_GRID,
      lineColor: COLOR_GRID_METER,
      marginRatio: 0.5,
      minStartAt0: true,
    });
    gridParts.dots.forEach(function(s) { elements.push({ z: -0.5, s: s }); });
    gridParts.lines.forEach(function(s) { elements.push({ z: -0.4, s: s }); });

    // Meter labels rendered by updateRulers() around the SVG (rulers HTML).
  }

  // Overlay raster background (only for Review/Design canvases, not the Pattern Editor)
  var isEditor = svg && svg.id === "canvas";
  if (state.overlay && !isEditor) {
    var ov = state.overlay;
    var ovScale = SCALE / ov.pxPerCm;  // convert image px to SVG units
    var ovW = ov.imgW * ovScale;
    var ovH = ov.imgH * ovScale;
    var ovX = -(ov.offsetX * SCALE);
    var ovY = -(ov.offsetY * SCALE);
    var ovImg = '<image href="' + ov.dataUrl +
      '" x="' + ovX.toFixed(1) + '" y="' + ovY.toFixed(1) +
      '" width="' + ovW.toFixed(1) + '" height="' + ovH.toFixed(1) +
      '" opacity="' + (ov.opacity / 100).toFixed(2) +
      '" preserveAspectRatio="none"/>';
    // D-83: rotate overlay to match local coordinate system.
    // D-99: in room amend mode, pin rotation center to the ORIGINAL room
    //       dimensions so live resize doesn't drift the overlay.
    var ovAngle = _canonicalAngle(state.corridor_face);
    if (ovAngle !== 0 && !isEditor) {
      var origRoom = state.roomAmendMode && state.roomAmendMode.originalRoom;
      var refWPx = origRoom ? origRoom.width_cm * SCALE : roomWPx;
      var refHPx = origRoom ? origRoom.depth_cm * SCALE : roomHPx;
      var ocx = roomX + refWPx / 2;
      var ocy = roomY + refHPx / 2;
      // Pour 90/270, la room canonicalisée a w/h swappés vs l'image originale.
      // Après rotation autour du centre room, compenser le décalage dû au swap.
      var dx = 0, dy = 0;
      if (ovAngle === 90 || ovAngle === 270) {
        dx = (refWPx - refHPx) / 2;
        dy = (refHPx - refWPx) / 2;
      }
      ovImg = '<g transform="translate(' + dx.toFixed(1) + ' ' + dy.toFixed(1) + ') rotate(' + ovAngle + ' ' + ocx.toFixed(1) + ' ' + ocy.toFixed(1) + ')">' + ovImg + '</g>';
    }
    elements.push({ z: -1, s: ovImg });
  }

  // Hide canvas background when overlay is active (avoid dark veil)
  svg.style.background = state.overlay ? 'transparent' : '';

  elements.sort(function(a, b) { return a.z - b.z; });

  // D-83: data is already in local coordinates — render directly, no SVG rotation needed.
  // Only the overlay needs rotation (handled separately via overlay transform).
  svg.innerHTML = elements.map(function(e) { return e.s; }).join("\n");

  // Store dimensions for zoomFit
  state._lastContentW = totalW;
  state._lastContentH = totalH;
  state._lastMinX = minX;
  updateViewBox(svg);
  updateInfo();
  document.getElementById("canvasDims").textContent =
    state.room_width_cm + " x " + state.room_depth_cm + " cm";
  // zoomLevel display removed — simplified toolbar
  // Restore rows if they were hidden for Review
  if (_savedRows !== undefined) state.rows = _savedRows;
}

function updateViewBox(targetSvg) {
  const svg = targetSvg || document.getElementById("canvas");
  const vb = state.viewBox;
  svg.setAttribute("viewBox", vb.x + " " + vb.y + " " + vb.w + " " + vb.h);
  updateRulers(svg);
}

function _ensureRulers(svg) {
  // Create a ruler container around the SVG if it doesn't exist
  if (svg._rulersReady) return;
  var parent = svg.parentElement;
  var rulerBox = document.createElement("div");
  rulerBox.className = "ruler-box";
  parent.insertBefore(rulerBox, svg);
  rulerBox.appendChild(svg);
  ["ruler-top", "ruler-bottom", "ruler-left", "ruler-right"].forEach(function(cls) {
    var div = document.createElement("div");
    div.className = "ruler " + cls;
    rulerBox.appendChild(div);
  });
  svg._rulersReady = true;
  svg._rulerBox = rulerBox;
}

window.updateRulers = updateRulers;
function updateRulers(targetSvg) {
  var svg = targetSvg || document.getElementById("canvas");
  _ensureRulers(svg);
  var box = svg._rulerBox;
  if (!box) return;
  var rulerTop = box.querySelector(".ruler-top");
  var rulerBottom = box.querySelector(".ruler-bottom");
  var rulerLeft = box.querySelector(".ruler-left");
  var rulerRight = box.querySelector(".ruler-right");

  var wrapRect = box.getBoundingClientRect();
  var vb = state.viewBox;
  var meterPx = 100 * SCALE;
  var htmlH = "";
  var htmlV = "";

  // Use getScreenCTM for exact SVG-to-screen coordinate mapping
  var ctm = svg.getScreenCTM();
  if (!ctm) return;

  function svgToWrap(svgX, svgY) {
    return {
      x: ctm.a * svgX + ctm.c * svgY + ctm.e - wrapRect.left,
      y: ctm.b * svgX + ctm.d * svgY + ctm.f - wrapRect.top
    };
  }

  // Origine (0,0) = coin NW de la pièce (fallback SVG origin si non défini).
  var nw = state._roomNW || { x: 0, y: 0 };

  // Horizontal labels (top + bottom) — couvrent toute la vb visible, valeurs négatives incluses
  var mxStart = Math.floor((vb.x - nw.x) / meterPx) * meterPx + nw.x;
  var mxEnd = vb.x + vb.w;
  for (var mx = mxStart; mx <= mxEnd; mx += meterPx) {
    var p = svgToWrap(mx, 0);
    if (p.x < 22 || p.x > wrapRect.width - 22) continue;
    var m = Math.round((mx - nw.x) / meterPx);
    htmlH += '<span style="left:' + p.x.toFixed(0) + 'px;">' + m + 'm</span>';
  }

  // Vertical labels (left + right)
  var myStart = Math.floor((vb.y - nw.y) / meterPx) * meterPx + nw.y;
  var myEnd = vb.y + vb.h;
  for (var my = myStart; my <= myEnd; my += meterPx) {
    var p = svgToWrap(0, my);
    if (p.y < 0 || p.y > wrapRect.height - 36) continue;
    var m = Math.round((my - nw.y) / meterPx);
    htmlV += '<span style="top:' + p.y.toFixed(0) + 'px;">' + m + 'm</span>';
  }

  rulerTop.innerHTML = htmlH;
  if (rulerBottom) rulerBottom.innerHTML = htmlH;
  rulerLeft.innerHTML = htmlV;
  if (rulerRight) rulerRight.innerHTML = htmlV;
}

function _safeText(id, val) {
  var el = document.getElementById(id);
  if (el) el.textContent = val;
}
function _safeHtml(id, val) {
  var el = document.getElementById(id);
  if (el) el.innerHTML = val;
}

function updateInfo() {
  const nd = totalDesks();
  const nb = totalBlocks();
  const nr = state.rows.length;
  const dims = computePatternDims();

  _safeText("deskCount", nd + " desk(s)");
  updateRoomDSL();

  // Room info
  _safeText("infoRoomArea", (state.room_width_cm * state.room_depth_cm / 10000).toFixed(1));

  _safeText("infoRows", nr);
  _safeText("infoBlocks", nb);
  _safeText("infoDesks", nd);
  _safeText("infoDimsBlocks", dims.eoBlocks + " x " + dims.nsBlocks);
  _safeText("infoDimsTotal", dims.eoTotal + " x " + dims.nsTotal);

  // m²/desk and density grade
  var roomAreaM2 = (state.room_width_cm * state.room_depth_cm) / 10000;
  var scoreColor = "var(--accent2)";
  if (nd > 0) {
    var m2pp = roomAreaM2 / nd;
    _safeHtml("infoM2", '<span style="color:' + scoreColor + ';">' + m2pp.toFixed(1) + '</span>');
  } else {
    _safeText("infoM2", "-");
  }

  // Circulation: grade + min passage
  var circInfo = computeCirculationInfo();
  if (circInfo && nd > 0) {
    var cg = circGrade(circInfo);
    var gradeSpan = '<span style="color:' + cg.color + ';">' + cg.grade + '</span>';
    _safeHtml("infoCirc", gradeSpan +
      ' <span style="color:' + scoreColor + ';">(' + circInfo.minPassageCm + ' cm min)</span>');
  } else {
    _safeText("infoCirc", "-");
  }

  const selInfo = document.getElementById("selectionInfo");
  const selHint = document.getElementById("selectionHint");
  if (state.selectedBlock >= 0 && state.rows[state.selectedRow]) {
    const b = state.rows[state.selectedRow].blocks[state.selectedBlock];
    if (b) {
      if (selInfo) selInfo.style.display = "block";
      if (selHint) selHint.style.display = "none";
      _safeText("selRow", state.selectedRow);
      _safeText("selBlock", state.selectedBlock);
      _safeText("selType", b.type);
      _safeText("selOrient", (b.orientation || 0) + "\u00B0");
      _safeText("selGap", b.gap_cm || 0);
      _safeText("selOffset", b.offset_ns_cm || 0);
      var bs = b.sticks || [];
      var stN = document.getElementById("stickN"); if (stN) stN.checked = bs.indexOf("N") >= 0;
      var stS = document.getElementById("stickS"); if (stS) stS.checked = bs.indexOf("S") >= 0;
      var stE = document.getElementById("stickE"); if (stE) stE.checked = bs.indexOf("E") >= 0;
      var stW = document.getElementById("stickW"); if (stW) stW.checked = bs.indexOf("W") >= 0;
    } else {
      if (selInfo) selInfo.style.display = "none";
      if (selHint) selHint.style.display = "block";
    }
  } else {
    if (selInfo) selInfo.style.display = "none";
    if (selHint) selHint.style.display = "block";
  }
}

function updateRowList() {
  const container = document.getElementById("rowList");
  container.innerHTML = "";

  for (let i = 0; i < state.rows.length; i++) {
    const row = state.rows[i];
    const div = document.createElement("div");
    div.className = "row-item" + (i === state.selectedRow ? " active" : "");
    const nb = row.blocks.length;
    const nd = row.blocks.reduce(function(s, b) { return s + countDesksInBlock(b.type); }, 0);
    div.innerHTML = "<span>Row " + (i + 1) + "</span>" +
      "<span class=\"row-sub\">" + nb + " block(s) - " + nd + " desk(s)</span>" +
      "<button class=\"row-del\" data-idx=\"" + i + "\" title=\"Delete\">x</button>";
    div.addEventListener("click", function(e) {
      if (e.target.classList.contains("row-del")) return;
      state.selectedRow = i;
      updateRowList();
    });
    div.querySelector(".row-del").addEventListener("click", function() { deleteRow(i); });
    container.appendChild(div);

    if (i < state.rows.length - 1 && i < state.row_gaps_cm.length) {
      const gapIndex = i;
      const gapDiv = document.createElement("div");
      gapDiv.className = "row-gap-item";
      gapDiv.innerHTML =
        "<span class=\"row-gap-label\">&#8597;</span>" +
        "<button class=\"btn-xs gap-minus\">&#8722;</button>" +
        "<input type=\"number\" class=\"gap-input\" value=\"" + state.row_gaps_cm[gapIndex] +
        "\" min=\"0\" step=\"10\">" +
        "<button class=\"btn-xs gap-plus\">+</button>" +
        "<span class=\"row-gap-unit\">cm</span>";
      gapDiv.querySelector(".gap-minus").addEventListener("click", function() {
        state.row_gaps_cm[gapIndex] = Math.max(0, (state.row_gaps_cm[gapIndex] || 0) - 10);
        render(); updateDSL(); updateRowList();
      });
      gapDiv.querySelector(".gap-plus").addEventListener("click", function() {
        state.row_gaps_cm[gapIndex] = (state.row_gaps_cm[gapIndex] || 0) + 10;
        render(); updateDSL(); updateRowList();
      });
      gapDiv.querySelector(".gap-input").addEventListener("change", function(e) {
        const val = parseInt(e.target.value) || 0;
        state.row_gaps_cm[gapIndex] = Math.max(0, val);
        render(); updateDSL(); updateRowList();
      });
      container.appendChild(gapDiv);
    }
  }
}

function deleteRow(i) {
  state.rows.splice(i, 1);
  if (i < state.row_gaps_cm.length) {
    state.row_gaps_cm.splice(i, 1);
  } else if (i > 0 && state.row_gaps_cm.length >= i) {
    state.row_gaps_cm.splice(i - 1, 1);
  }
  if (state.selectedRow >= state.rows.length) {
    state.selectedRow = Math.max(0, state.rows.length - 1);
  }
  state.selectedBlock = -1;
  updateRowList();
  render();
  updateDSL();
}

async function updateDSL() {
  try {
    const payload = buildPatternPayload();
    const resp = await fetch("/api/dsl/export", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });
    if (!resp.ok) throw new Error(await resp.text());
    const data = await resp.json();
    document.getElementById("dslText").value = data.dsl || JSON.stringify(payload, null, 2);
  } catch (err) {
    document.getElementById("dslText").value = JSON.stringify(buildPatternPayload(), null, 2);
  }
}

async function applyDSL() {
  markDirty();
  const text = document.getElementById("dslText").value.trim();
  try {
    const resp = await fetch("/api/dsl/parse", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ dsl: text })
    });
    if (!resp.ok) throw new Error(await resp.text());
    const data = await resp.json();
    if (data.rows) {
      state.rows = data.rows;
      state.row_gaps_cm = data.row_gaps_cm || [];
      if (state.selectedRow >= state.rows.length) state.selectedRow = 0;
      state.selectedBlock = -1;
      updateRowList();
      render();
      zoomFit();
      setStatus("DSL applied.");
      return;
    }
  } catch (err) {
    // try direct JSON
  }
  try {
    const data = JSON.parse(text);
    if (data.rows) {
      state.rows = data.rows;
      state.row_gaps_cm = data.row_gaps_cm || [];
      if (state.selectedRow >= state.rows.length) state.selectedRow = 0;
      state.selectedBlock = -1;
      updateRowList();
      render();
      zoomFit();
      setStatus("JSON applied.");
    }
  } catch (e2) {
    setStatus("DSL parse error.");
  }
}

function buildPatternPayload() {
  // Exclude trailing empty rows for DSL/save
  let lastNonEmpty = state.rows.length - 1;
  while (lastNonEmpty >= 0 && state.rows[lastNonEmpty].blocks.length === 0) {
    lastNonEmpty--;
  }
  const rows = state.rows.slice(0, lastNonEmpty + 1);
  const row_gaps_cm = state.row_gaps_cm.slice(0, Math.max(0, rows.length - 1));
  return {
    name: state.name,
    rows: rows,
    row_gaps_cm: row_gaps_cm,
    room_width_cm: state.room_width_cm,
    room_depth_cm: state.room_depth_cm,
    standard: state.standard,
    room_windows: state.room_windows,
    room_openings: state.room_openings,
    room_exclusions: state.room_exclusions,
  };
}

function addBlock(blockType) {
  markDirty();
  if (state.rows.length === 0) addRow(false);
  const row = state.rows[state.selectedRow];
  const block = { type: blockType, orientation: 0, offset_ns_cm: 0 };
  if (row.blocks.length > 0) {
    var defaultGap = parseInt(document.getElementById("gapIntra").value) || 180;
    // Compute space already used in the row
    var usedCm = 0;
    for (var i = 0; i < row.blocks.length; i++) {
      var gb = getEffectiveGeom(row.blocks[i].type, row.blocks[i].orientation);
      usedCm += gb.eo + (row.blocks[i].gap_cm || 0);
    }
    var newBlockW = getEffectiveGeom(blockType, 0).eo;
    var remaining = state.room_width_cm - usedCm - newBlockW;
    if (remaining < 0) {
      // Row full: create a new row
      addRow(false);
      row = state.rows[state.selectedRow];
    } else {
      block.gap_cm = Math.max(0, Math.min(defaultGap, remaining));
    }
  }
  row.blocks.push(block);
  state.selectedBlock = row.blocks.length - 1;
  state.selectedExclusion = -1;
  updateRowList();
  updateDSL();
  zoomFit();
}

function addRow(andRender) {
  markDirty();
  if (andRender === undefined) andRender = true;
  if (state.rows.length > 0) {
    const gap = DEFAULT_ROW_GAP_CM;
    state.row_gaps_cm.push(gap);
  }
  state.rows.push({ blocks: [] });
  state.selectedRow = state.rows.length - 1;
  updateRowList();
  if (andRender) {
    render();
    updateDSL();
    zoomFit();
  }
}

async function save() {
  // Room amend mode: store amended room geometry and re-run matching
  if (state.roomAmendMode) {
    var ramend = state.roomAmendMode;
    // State contains local coordinates (D-83) — convert back to absolute for storage
    var origCf = ramend.originalRoom.corridor_face || "";
    var localRoom = {
      name: ramend.roomName,
      width_cm: state.room_width_cm,
      depth_cm: state.room_depth_cm,
      windows: JSON.parse(JSON.stringify(state.room_windows)),
      openings: JSON.parse(JSON.stringify(state.room_openings)),
      exclusion_zones: JSON.parse(JSON.stringify(state.room_exclusions)),
      bbox_px: ramend.originalRoom.bbox_px ? ramend.originalRoom.bbox_px.slice() : undefined,
      corridor_face: origCf,
    };
    var amendedRoom = (origCf && origCf !== "south" && typeof window._decanonicalizeRoom === "function")
      ? window._decanonicalizeRoom(localRoom, origCf)
      : localRoom;
    fpRoomAmendments[ramend.roomName] = amendedRoom;
    amendedRoom.corridor_face = origCf;

    // D-99: propagate the new size + NW shift back to ingState.rooms (and
    // fpData.rooms + the stored amendment) so Floor reflects the amendment
    // on the bbox overlay. Only handled for south-corridor rooms for now —
    // non-south requires axis-remapping (see TODO).
    var renderOffset = state.roomRenderOffset || { x_cm: 0, y_cm: 0 };
    var scaleCmPerPx = (window.ingState && window.ingState.scale) || 0;
    if (scaleCmPerPx > 0 && (!origCf || origCf === "south")) {
      var newBbox = null;
      var ingRooms = (window.ingState && window.ingState.rooms) || [];
      for (var ir = 0; ir < ingRooms.length; ir++) {
        if (ingRooms[ir].name !== ramend.roomName) continue;
        var orig = ingRooms[ir].bbox_px;
        if (!orig || orig.length !== 4) break;
        var nx0 = orig[0] + renderOffset.x_cm / scaleCmPerPx;
        var ny0 = orig[1] + renderOffset.y_cm / scaleCmPerPx;
        var nx1 = nx0 + state.room_width_cm / scaleCmPerPx;
        var ny1 = ny0 + state.room_depth_cm / scaleCmPerPx;
        newBbox = [nx0, ny0, nx1, ny1];
        ingRooms[ir].bbox_px = newBbox;
        ingRooms[ir].width_cm = state.room_width_cm;
        ingRooms[ir].depth_cm = state.room_depth_cm;
        ingRooms[ir].surface_m2 = parseFloat(((state.room_width_cm * state.room_depth_cm) / 10000).toFixed(2));
        break;
      }
      if (newBbox) {
        amendedRoom.bbox_px = newBbox.slice();
        if (window.fpData && window.fpData.rooms) {
          for (var fr = 0; fr < window.fpData.rooms.length; fr++) {
            if (window.fpData.rooms[fr].name !== ramend.roomName) continue;
            window.fpData.rooms[fr].width_cm = state.room_width_cm;
            window.fpData.rooms[fr].depth_cm = state.room_depth_cm;
            window.fpData.rooms[fr].bbox_px = newBbox.slice();
            break;
          }
        }
        // Re-render Floor SVG + room list so the new size shows up without
        // needing a click to trigger a redraw.
        if (typeof window.renderIngestion === "function") window.renderIngestion();
        if (typeof window.updateIngRoomList === "function") window.updateIngRoomList();
      }
    }

    state.roomAmendMode = null;
    state.roomRenderOffset = null;
    exitRoomAmendUI();
    // Re-run matching then refresh Review
    fpRematchRoom(ramend.roomName, amendedRoom);
    rvRenderCurrent();
    return;
  }

  // Amend mode: store amendment locally and return to Floor Plan
  if (state.amendMode) {
    var amend = state.amendMode;
    if (!state.dirty) {
      // No changes — exit without creating an amendment
      state.amendMode = null;
      exitAmendUI();
      clearDirty();
      document.querySelector('.tab-btn[data-tab="lytDesign"]').click();
      fpRenderCurrent();
      setStatus("No changes — amendment discarded.");
      return;
    }
    var payload = buildPatternPayload();
    // Recompute desk count
    var nd = totalDesks();
    var roomArea = (state.room_width_cm * state.room_depth_cm) / 10000;
    var circInfo = computeCirculationInfo();
    var cg = circInfo ? circGrade(circInfo) : { grade: "F" };
    fpAmendments[amend.roomName] = {
      pattern_name: amend.candidate.pattern_name + " (amended)",
      standard: state.standard,
      n_desks: nd,
      m2_per_desk: nd > 0 ? +(roomArea / nd).toFixed(1) : 0,
      circulation_grade: cg.grade,
      min_passage_cm: circInfo ? circInfo.minPassageCm : 0,
      connectivity_pct: circInfo ? circInfo.connectivityPct : 0,
      worst_detour: circInfo ? circInfo.worstDetour : 0,
      largest_free_rect_m2: 0,
      desks: circInfo ? circInfo.desks : [],
      pattern: payload,
      amended: true,
    };
    state.amendMode = null;
    exitAmendUI();
    setStatus("Amendment saved for room \"" + amend.roomName + "\".");
    // Switch back to Design
    document.querySelector('.tab-btn[data-tab="lytDesign"]').click();
    fpRenderCurrent();
    return;
  }

  updateAutoName();
  var isUpdate = !!state._savedName;
  var payload = buildPatternPayload();
  if (isUpdate) {
    // Update existing pattern: send the saved name
    payload.name = state._savedName;
  } else {
    // New pattern: let the server generate the name    payload.auto_name = true;
    delete payload.name;
  }
  try {
    const resp = await fetch("/api/patterns", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });
    if (!resp.ok) throw new Error(await resp.text());
    var result = await resp.json();
    // Server may rename (auto-compaction) — store the actual name
    if (result.name) {
      state.name = result.name;
      state._savedName = result.name;
      document.getElementById("autoName").textContent = result.name;
    }
    clearDirty();
    setStatus("Pattern \"" + state._savedName + "\" saved.");
    loadCatalogue();
  } catch (err) {
    setStatus("Save error: " + err.message);
  }
}

async function loadList() {
  try {
    const resp = await fetch("/api/patterns");
    if (!resp.ok) throw new Error(await resp.text());
    const data = await resp.json();
    const raw = data.patterns || data || [];
    // Sort like catalogue: depth asc, width asc, name asc (numeric)
    var sorted = raw.slice().sort(function(a, b) {
      if (typeof a === "string") return a.localeCompare(b, undefined, { numeric: true });
      var da = (a.room_depth_cm || 0) - (b.room_depth_cm || 0);
      if (da !== 0) return da;
      var wa = (a.room_width_cm || 0) - (b.room_width_cm || 0);
      if (wa !== 0) return wa;
      return (a.name || "").localeCompare(b.name || "", undefined, { numeric: true });
    });
    const list = sorted.map(function(p) { return typeof p === "string" ? p : p.name; });
    const ul = document.getElementById("modalList");
    ul.innerHTML = "";
    if (list.length === 0) {
      ul.innerHTML = "<li style=\"color:var(--text-dim)\">No patterns saved.</li>";
    } else {
      list.forEach(function(name) {
        const li = document.createElement("li");
        li.textContent = name;
        li.addEventListener("click", function() { loadPattern(name); });
        ul.appendChild(li);
      });
    }
    document.getElementById("loadModal").classList.add("active");
  } catch (err) {
    setStatus("Load list error: " + err.message);
  }
}

async function loadPattern(name) {
  document.getElementById("loadModal").classList.remove("active");
  try {
    const resp = await fetch("/api/patterns/" + encodeURIComponent(name));
    if (!resp.ok) throw new Error(await resp.text());
    const data = await resp.json();
    state.rows = data.rows || [];
    state.row_gaps_cm = data.row_gaps_cm || [];
    state.room_width_cm = data.room_width_cm || 300;
    state.room_depth_cm = data.room_depth_cm || 480;
    state.standard = data.standard || getStandards()[0] || "";
    state.room_windows = data.room_windows || [];
    state.room_openings = data.room_openings || [];
    state.room_exclusions = data.room_exclusions || [];
    state.selectedRow = 0;
    state.selectedBlock = -1;
    state.overlay = null;
    state.corridor_face = "";
    document.getElementById("roomWidth").value = state.room_width_cm;
    document.getElementById("roomDepth").value = state.room_depth_cm;
    var radios = document.querySelectorAll('input[name="standard"]');
    radios.forEach(function(r) { r.checked = (r.value === state.standard); });
    // Use the actual catalogue name (with auto-generated suffix)
    state.name = data.name || computeAutoName();
    state._savedName = state.name;
    document.getElementById("autoName").textContent = state.name;
    updateRowList();
    render();
    zoomFit();
    updateDSL();
    clearDirty();
    setStatus("Pattern \"" + state.name + "\" loaded.");
  } catch (err) {
    setStatus("Load error: " + err.message);
  }
}

function loadPatternFromData(data) {
  clearDirty();
  state.rows = data.rows || [];
  state.row_gaps_cm = data.row_gaps_cm || [];
  state.room_width_cm = data.room_width_cm || 300;
  state.room_depth_cm = data.room_depth_cm || 480;
  state.standard = data.standard || getStandards()[0] || "";
  state.room_windows = data.room_windows || [];
  state.room_openings = data.room_openings || [];
  state.room_exclusions = data.room_exclusions || [];
  state.selectedRow = 0;
  state.selectedBlock = -1;
  state._savedName = data.name || null;
  document.getElementById("roomWidth").value = state.room_width_cm;
  document.getElementById("roomDepth").value = state.room_depth_cm;
  var radios = document.querySelectorAll('input[name="standard"]');
  radios.forEach(function(r) { r.checked = (r.value === state.standard); });
  updateAutoName();
  updateRowList();
  render();
  zoomFit();
  updateDSL();
  setStatus("Pattern loaded from floor plan.");
}

function switchToEditorWithPattern(data) {
  // Switch to Office Layout > Editor (triggers canvas move)
  state.amendMode = null;
  state.roomAmendMode = null;
  state.roomRenderOffset = null;
  exitAmendUI();
  exitRoomAmendUI();
  document.querySelector('.tab-btn[data-tab="lytCatalogue"]').click();
  document.querySelector('.sub-tab-btn[data-subtab="catEditor"]').click();
  loadPatternFromData(JSON.parse(JSON.stringify(data)));
}

// IDs to disable in amend mode (room controls + catalogue actions)
var AMEND_DISABLE_IDS = [
  "roomWidth", "roomDepth", "btnWidthPlus", "btnWidthMinus",
  "btnDepthPlus", "btnDepthMinus", "dslRoom", "btnApplyRoomDSL",
  "btnNew", "btnLoad", "btnDuplicate", "btnDelete",
];

function enterAmendMode(room, candidate) {
  state.amendMode = {
    roomName: room.name,
    roomIdx: null,
    candidate: candidate,
  };
  // Switch BLOCK_DEFS to candidate's standard
  if (candidate.standard && BLOCK_DEFS_BY_STD[candidate.standard]) {
    BLOCK_DEFS = BLOCK_DEFS_BY_STD[candidate.standard];
  }
  // Show editor content (inside Catalogue tab)
  document.querySelectorAll(".tab-content").forEach(function(c) { c.classList.remove("active"); });
  document.getElementById("tabLytCatalogue").classList.add("active");
  document.querySelectorAll(".sub-tab-content").forEach(function(c) { c.classList.remove("active"); });
  document.getElementById("subtabCatEditor").classList.add("active");
  document.querySelectorAll(".tab-btn").forEach(function(b) { b.classList.remove("active"); });
  document.querySelector('.tab-btn[data-tab="lytCatalogue"]').classList.add("active");
  // Hide sub-tab bar (Card view / Grid view / Pattern editor)
  document.querySelector("#tabLytCatalogue > .sub-tab-bar").style.display = "none";
  loadPatternFromData(JSON.parse(JSON.stringify(candidate.pattern)));

  // Disable room controls + irrelevant actions
  AMEND_DISABLE_IDS.forEach(function(id) {
    var el = document.getElementById(id);
    if (el) { el.disabled = true; el.style.opacity = "0.4"; }
  });
  // Disable standard radios
  document.querySelectorAll('#headerStandard input').forEach(function(r) {
    r.disabled = true;
  });
  document.getElementById("headerStandard").style.opacity = "0.4";

  // Replace Save label, show Cancel
  document.getElementById("btnSave").textContent = "Save amendment";
  document.getElementById("btnAmendCancel").style.display = "";

  // Visual cue: amend mode banner
  document.querySelector(".ol-header").classList.add("edit-mode");
  _safeText("autoName", "\u270E " + room.name);
  setStatus("Adjusting layout for room \"" + room.name + "\". Save to apply, Cancel to discard.");
}

function exitAmendUI() {
  AMEND_DISABLE_IDS.forEach(function(id) {
    var el = document.getElementById(id);
    if (el) { el.disabled = false; el.style.opacity = ""; }
  });
  document.querySelectorAll('#headerStandard input').forEach(function(r) {
    r.disabled = false;
  });
  document.getElementById("headerStandard").style.opacity = "";
  document.getElementById("btnSave").textContent = "Save";
  document.getElementById("btnAmendCancel").style.display = "none";
  document.querySelector(".ol-header").classList.remove("edit-mode");
  // Restore sub-tab bar
  var subBar = document.querySelector("#tabLytCatalogue > .sub-tab-bar");
  if (subBar) subBar.style.display = "";
}

// IDs to disable in room-amend mode (layout controls + catalogue actions)
var ROOM_AMEND_DISABLE_IDS = [
  "dslText", "btnApplyDSL", "btnAddRow",
  "btnNew", "btnLoad", "btnDuplicate", "btnDelete",
  "gapIntra",
];

function enterRoomAmendMode(room) {
  // Stay in Review — edit room in-place
  state.roomAmendMode = {
    roomName: room.name,
    originalRoom: JSON.parse(JSON.stringify(room)),
  };
  // D-99: fresh render offset for this amend session.
  state.roomRenderOffset = { x_cm: 0, y_cm: 0 };

  // D-83: convert absolute data to local coordinates for editing
  var localRoom = (typeof window._canonicalizeRoom === "function")
    ? window._canonicalizeRoom(room) : room;
  state.rows = [];
  state.row_gaps_cm = [];
  state.room_width_cm = localRoom.width_cm;
  state.room_depth_cm = localRoom.depth_cm;
  state.room_windows = JSON.parse(JSON.stringify(localRoom.windows || []));
  state.room_openings = JSON.parse(JSON.stringify(localRoom.openings || []));
  state.room_exclusions = JSON.parse(JSON.stringify(localRoom.exclusion_zones || []));
  state.corridor_face = room.corridor_face || "";

  // Inject overlay for visual reference, aligned to room bbox
  if (window.fpOverlay) {
    var ov = window.fpOverlay;
    var ovOffX = 0, ovOffY = 0;
    if (room.bbox_px) {
      ovOffX = room.bbox_px[0] / ov.pxPerCm;
      ovOffY = room.bbox_px[1] / ov.pxPerCm;
    }
    state.overlay = {
      dataUrl: ov.dataUrl, pxPerCm: ov.pxPerCm,
      opacity: 30,
      offsetX: ovOffX, offsetY: ovOffY,
      imgW: ov.imgW, imgH: ov.imgH,
    };
  }

  render(document.getElementById("rvCanvas"));
  zoomFit(document.getElementById("rvCanvas"));

  // Enable editing in Review sidebar
  var dslEl = document.getElementById("rvRoomDsl");
  dslEl.readOnly = false;
  dslEl.style.color = "var(--text)";
  dslEl.style.cursor = "";
  document.getElementById("rvAmendApply").style.display = "";

  // Show Save/Cancel/AddExcl in nav bar, hide Adjust room
  document.getElementById("rvBtnAdjustRoom").style.display = "none";
  document.getElementById("rvBtnSaveRoom").style.display = "";
  document.getElementById("rvBtnCancelRoom").style.display = "";
  document.getElementById("rvBtnAddExcl").style.display = "";

  // Disable navigation during edit
  document.getElementById("rvBtnPrev").disabled = true;
  document.getElementById("rvBtnNext").disabled = true;

  // Visual cue: amber edit-mode on nav bar
  document.querySelector("#tabFpReview .fp-nav").classList.add("edit-mode");
  document.getElementById("rvRoomLabel").textContent = "\u270E " + room.name;
}

function exitRoomAmendUI() {
  // Restore Review sidebar to read-only
  var dslEl = document.getElementById("rvRoomDsl");
  dslEl.readOnly = true;
  dslEl.style.color = "var(--text-dim)";
  dslEl.style.cursor = "default";
  document.getElementById("rvAmendApply").style.display = "none";

  // Restore nav bar: show Adjust room, hide Save/Cancel/AddExcl
  document.getElementById("rvBtnAdjustRoom").style.display = "";
  document.getElementById("rvBtnSaveRoom").style.display = "none";
  document.getElementById("rvBtnCancelRoom").style.display = "none";
  document.getElementById("rvBtnAddExcl").style.display = "none";

  // Reset rvTool and clean up any drawing in progress
  if (window.rvTool) {
    window.rvTool.mode = "idle";
    window.rvTool.selectedIndex = -1;
    window.rvTool.drawStart = null;
    window.rvTool.dragOffset = null;
  }
  state.selectedExclusion = -1;
  var _rvBtn = document.getElementById("rvBtnAddExcl");
  if (_rvBtn) _rvBtn.classList.remove("active");
  var _rvCv = document.getElementById("rvCanvas");
  if (_rvCv) _rvCv.style.cursor = "";
  if (window.rvRemoveGhostRect) window.rvRemoveGhostRect();

  // Re-enable navigation
  document.getElementById("rvBtnPrev").disabled = false;
  document.getElementById("rvBtnNext").disabled = false;

  // Remove edit-mode
  document.querySelector("#tabFpReview .fp-nav").classList.remove("edit-mode");

  state.overlay = null;
}

function duplicatePattern() {
  // Copy layout to memory without saving.
  // User adjusts size/standard -> name changes -> Save creates a new pattern.
  state._savedName = null;
  setStatus("Copied in memory. Adjust size/standard then save.");
}

async function deletePattern() {
  const name = state._savedName || state.name;
  if (!name || name === "P_NEW") {
    setStatus("No pattern to delete.");
    return;
  }
  if (!confirm("Delete pattern \"" + name + "\" from catalogue?")) return;
  try {
    const resp = await fetch("/api/patterns/" + encodeURIComponent(name), { method: "DELETE" });
    if (!resp.ok) throw new Error(await resp.text());
    setStatus("Pattern \"" + name + "\" deleted.");
    resetState();
    loadCatalogue();
  } catch (err) {
    setStatus("Delete error: " + err.message);
  }
}

function resetState() {
  clearDirty();
  state.rows = [];
  state.row_gaps_cm = [];
  state.room_width_cm = parseInt(document.getElementById("roomWidth").value) || 300;
  state.room_depth_cm = parseInt(document.getElementById("roomDepth").value) || 480;
  state.standard = document.querySelector('input[name="standard"]:checked').value;
  state.room_windows = [{ face: "north", offset_cm: 0, width_cm: state.room_width_cm }];
  state.room_openings = [{ face: "south", offset_cm: 0, width_cm: APP_CONFIG.default_door_width_cm || 90, has_door: true, opens_inward: true, hinge_side: "left" }];
  state.room_exclusions = [];
  state.selectedRow = 0;
  state.selectedBlock = -1;
  state.viewBox = { x: 0, y: 0, w: 800, h: 600 };
  state.zoom = 1.0;
  updateAutoName();
  document.getElementById("dslText").value = "";
  updateRowList();
  zoomFit();
  setStatus("New pattern.");
}

const BLOCK_DESKS_FALLBACK = {
  BLOCK_1: 1, BLOCK_2_FACE: 2, BLOCK_2_SIDE: 2,
  BLOCK_3_SIDE: 3, BLOCK_4_FACE: 4, BLOCK_6_FACE: 6,
  BLOCK_2_ORTHO_L: 2, BLOCK_2_ORTHO_R: 2,
};

function buildPalette() {
  const container = document.getElementById("blockPalette");
  container.innerHTML = "";
  const types = ["BLOCK_1", "BLOCK_2_FACE", "BLOCK_2_SIDE", "BLOCK_3_SIDE", "BLOCK_4_FACE", "BLOCK_6_FACE",
                 "BLOCK_2_ORTHO_L", "BLOCK_2_ORTHO_R"];
  types.forEach(function(type) {
    const nd = countDesksInBlock(type) || BLOCK_DESKS_FALLBACK[type] || "?";
    const btn = document.createElement("button");
    btn.className = "block-btn";
    btn.innerHTML = type + " <span class=\"block-sub\">(" + nd +
      " desk" + (nd > 1 ? "s" : "") + ")</span>";
    btn.addEventListener("click", function() { addBlock(type); });
    container.appendChild(btn);
  });
}

function zoomIn(targetSvg) {
  const vb = state.viewBox;
  const factor = 0.8;
  const newW = vb.w * factor;
  const newH = vb.h * factor;
  vb.x += (vb.w - newW) / 2;
  vb.y += (vb.h - newH) / 2;
  vb.w = newW;
  vb.h = newH;
  state.zoom /= factor;
  render(targetSvg);
}

function zoomOut(targetSvg) {
  // Clamp: don't zoom out beyond the fitViewBox (content fully visible)
  if (state._fitViewBox) {
    if (state.viewBox.w * 1.25 > state._fitViewBox.w * 1.1) return;
  }
  const vb = state.viewBox;
  const factor = 1.25;
  const newW = vb.w * factor;
  const newH = vb.h * factor;
  vb.x += (vb.w - newW) / 2;
  vb.y += (vb.h - newH) / 2;
  vb.w = newW;
  vb.h = newH;
  state.zoom /= factor;
  render(targetSvg);
}

function fitViewBoxToContent(svg, totalW, totalH, minX) {
  // Review/Design canvases get extra breathing room
  var isRoomView = svg && (svg.id === "rvCanvas" || svg.id === "fpCanvas");
  var extraPad = isRoomView ? 25 : 0;
  var padLeft = 35 + extraPad;
  var padTop = 50 + extraPad;
  var padRight = 15 + extraPad;
  var padBottom = 30 + extraPad;
  var x = minX - padLeft;
  var y = -padTop;
  var w = totalW - minX + padLeft + padRight;
  var h = totalH + padTop + padBottom;

  // Match viewBox aspect ratio to SVG element to avoid wasted space
  var rect = svg.getBoundingClientRect();
  var svgW = rect.width || 1;
  var svgH = rect.height || 1;
  var svgRatio = svgW / svgH;
  var vbRatio = w / h;
  if (vbRatio < svgRatio) {
    // Content is taller than SVG — widen viewBox
    var newW = h * svgRatio;
    x -= (newW - w) / 2;
    w = newW;
  } else {
    // Content is wider than SVG — heighten viewBox
    var newH = w / svgRatio;
    y -= (newH - h) / 2;
    h = newH;
  }

  state.viewBox = { x: x, y: y, w: w, h: h };
  state._fitViewBox = { w: w, h: h };  // max zoom-out limit
  state.zoom = 1.0;
}

function zoomFit(targetSvg) {
  var svg = targetSvg || document.getElementById("canvas");
  // First render to compute content dimensions
  render(svg);

  // D-83: data already in local coords — standard zoomFit works for all angles
  fitViewBoxToContent(svg,
    state._lastContentW || 100, state._lastContentH || 100, state._lastMinX || 0);
  // Re-render with corrected viewBox (for the grid)
  render(svg);
}

function getSelectedBlock() {
  if (state.selectedBlock < 0 || !state.rows[state.selectedRow]) return null;
  return state.rows[state.selectedRow].blocks[state.selectedBlock] || null;
}

function rotateSelectedBlock() {
  const b = getSelectedBlock();
  if (!b) { setStatus("No block selected for rotation"); return; }
  markDirty();
  b.orientation = ((b.orientation || 0) + 90) % 360;
  setStatus("Rotation " + b.type + " -> " + b.orientation + "\u00B0");
  updateDSL(); updateRowList(); zoomFit();
}

function cleanSticks(b) {
  // Remove sticks inconsistent with block position
  if (!b) return;
  if (!b.sticks || b.sticks.length === 0) return;
  // Any movement removes all sticks
  var cleaned = [];
  b.sticks = cleaned.length > 0 ? cleaned : undefined;
}

function offsetSelectedBlock(deltaCm) {
  const b = getSelectedBlock();
  if (!b) return;
  markDirty();
  b.offset_ns_cm = (b.offset_ns_cm || 0) + deltaCm;
  cleanSticks(b);
  render(); updateDSL();
}

function offsetSelectedBlockEO(deltaCm) {
  const b = getSelectedBlock();
  if (!b) return;
  markDirty();
  b.gap_cm = Math.max(0, (b.gap_cm || 0) + deltaCm);
  cleanSticks(b);
  render(); updateDSL();
}

