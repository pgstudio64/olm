"use strict";

// Requires BLOCK_DEFS global (loaded from /api/blocks by each page)
// Requires FACE_ROTATE_MAP and SIDE_ROTATE_MAP from block_constants.js

function countDesksInBlock(type) {
  const def = BLOCK_DEFS[type];
  return def ? (def.n_desks || 0) : 0;
}

function getBlockGeom(type) {
  const def = BLOCK_DEFS[type];
  if (!def) return { eo: 80, ns: 160, faces: {} };
  return { eo: def.eo_cm || 80, ns: def.ns_cm || 160, faces: def.faces || {} };
}

function getEffectiveGeom(type, orientation) {
  const g = getBlockGeom(type);
  const orient = orientation || 0;
  if (orient === 0) return g;
  const swap = (orient === 90 || orient === 270);
  const m = FACE_ROTATE_MAP[orient];
  const faces = {};
  for (const dir of ["north", "south", "east", "west"]) {
    faces[dir] = g.faces[m[dir]] || {};
  }
  return { eo: swap ? g.ns : g.eo, ns: swap ? g.eo : g.ns, faces: faces };
}

function transformDeskRects(rects, eo0, ns0, orient) {
  if (!orient || orient === 0) return rects;
  const sm = SIDE_ROTATE_MAP[orient];
  return rects.map(function(d) {
    let nx, ny, nw, nh;
    if (orient === 90) {
      // 90° CW: (x,y,w,h) -> (ns0-y-h, x, h, w)
      nx = ns0 - d.y - d.h; ny = d.x; nw = d.h; nh = d.w;
    } else if (orient === 180) {
      // 180°: (x,y,w,h) -> (eo0-x-w, ns0-y-h, w, h)
      nx = eo0 - d.x - d.w; ny = ns0 - d.y - d.h; nw = d.w; nh = d.h;
    } else {
      // 270° CW: (x,y,w,h) -> (y, eo0-x-w, h, w)
      nx = d.y; ny = eo0 - d.x - d.w; nw = d.h; nh = d.w;
    }
    return { x: nx, y: ny, w: nw, h: nh, label: d.label,
             screenSide: sm[d.screenSide] || d.screenSide,
             chairSide: sm[d.chairSide] || d.chairSide };
  });
}

function getDeskRects(type) {
  const def = BLOCK_DEFS[type];
  if (!def) return [];
  const n = def.n_desks || 1;
  const eo = def.eo_cm || 80;
  const ns = def.ns_cm || 160;

  // DESK_W = width (wide side, 180), DESK_D = depth (front-to-back, 80)
  // In block layout: EO axis = DESK_D, NS axis = DESK_W
  const symmetric = ["BLOCK_2_FACE", "BLOCK_4_FACE", "BLOCK_6_FACE"];
  if (symmetric.includes(type)) {
    const pairs = n / 2;
    const rects = [];
    for (let p = 0; p < pairs; p++) {
      rects.push({ x: 0,      y: p * DESK_W, w: DESK_D, h: DESK_W,
                   label: "WS" + String(p * 2 + 1).padStart(2, "0"),
                   screenSide: "E", chairSide: "W" });
      rects.push({ x: DESK_D, y: p * DESK_W, w: DESK_D, h: DESK_W,
                   label: "WS" + String(p * 2 + 2).padStart(2, "0"),
                   screenSide: "W", chairSide: "E" });
    }
    return rects;
  }

  // Blocs orthogonaux : 2 desks a 90 degres
  if (type === "BLOCK_2_ORTHO_R") {
    // L en bas-gauche : desk2 regarde ouest, chaise est
    return [
      { x: 0, y: 0, w: DESK_W, h: DESK_D,
        label: "WS01", screenSide: "S", chairSide: "N" },
      { x: 0, y: DESK_D, w: DESK_D, h: DESK_W,
        label: "WS02", screenSide: "W", chairSide: "E" },
    ];
  }
  if (type === "BLOCK_2_ORTHO_L") {
    // L en bas-droite (miroir) : desk2 regarde est, chaise ouest
    return [
      { x: 0, y: 0, w: DESK_W, h: DESK_D,
        label: "WS01", screenSide: "S", chairSide: "N" },
      { x: DESK_W - DESK_D, y: DESK_D, w: DESK_D, h: DESK_W,
        label: "WS02", screenSide: "E", chairSide: "W" },
    ];
  }

  const rects = [];
  for (let i = 0; i < n; i++) {
    rects.push({ x: 0, y: i * DESK_W, w: DESK_D, h: DESK_W,
                 label: "WS" + String(i + 1).padStart(2, "0"),
                 screenSide: "E", chairSide: "W" });
  }
  return rects;
}
