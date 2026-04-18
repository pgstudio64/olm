"use strict";
// ========================================================================
// INGESTION EXPORT — DEV export v3 JSON (D-94 P4)
// ========================================================================
//
// Serializes `ingState.rooms` into the v3 preprocessed JSON format and
// triggers a browser download. See docs/specs/PREPROCESSED_JSON_SPEC.md §5.
// Development helper — also used by the "Save" button (init.js delegates
// to `window.devExportV3Json`). D-95: scale is written back into both
// `drawing_scale_text` and `drawing_scale_measured`.
// ========================================================================

(function () {
  function devExportV3Json() {
    var ingState = window.ingState;
    if (!ingState || !ingState.rooms || ingState.rooms.length === 0) {
      alert('No rooms to export. Load a floor plan first.');
      return;
    }

    var hdr = document.getElementById('hdrCurrentPlan');
    var planName = hdr ? hdr.textContent.trim() : '';
    var fileHint = planName ? (planName + '.png') : 'plan.png';

    // v3 format: rooms is an object keyed by room id. No `id` / `code` fields
    // inside values (id is the key, code is a Settings filter). See
    // docs/specs/PREPROCESSED_JSON_SPEC.md.
    var roomsDict = {};
    ingState.rooms.forEach(function (r) {
      var roomId = r.name || '';
      if (!roomId) return;

      // Cartouche seed: prefer seed_px, else seed, else bbox center
      var seed;
      if (Array.isArray(r.seed_px) && r.seed_px.length === 2) {
        seed = [Math.round(r.seed_px[0]), Math.round(r.seed_px[1])];
      } else if (Array.isArray(r.seed) && r.seed.length === 2) {
        seed = [Math.round(r.seed[0]), Math.round(r.seed[1])];
      } else if (Array.isArray(r.bbox_px) && r.bbox_px.length === 4) {
        seed = [
          Math.round((r.bbox_px[0] + r.bbox_px[2]) / 2),
          Math.round((r.bbox_px[1] + r.bbox_px[3]) / 2),
        ];
      } else {
        seed = [0, 0];
      }

      // Surface as string "N.NN m2" — v3 keeps the string form, OLS parses on read
      var surfaceStr = '';
      if (typeof r.surface_m2 === 'number' && r.surface_m2 > 0) {
        surfaceStr = r.surface_m2.toFixed(2) + ' m2';
      }

      // v3 rename: seed_px [x,y] → seed_x / seed_y (two scalar fields)
      var roomObj = { surface: surfaceStr, seed_x: seed[0], seed_y: seed[1] };

      if (Array.isArray(r.bbox_px) && r.bbox_px.length === 4) {
        roomObj.bbox_px = r.bbox_px.map(function (v) { return Math.round(v); });
      }

      // canonical_top_face: derive from the primary door's face.
      // primary = first door in the list (OCR detects at most one main door per room).
      // opposite face becomes the canonical top (D-83: corridor at bottom, windows at top).
      if (Array.isArray(r.doors) && r.doors.length > 0 && r.doors[0].face) {
        var OPPOSITE = { north: 'south', south: 'north', east: 'west', west: 'east' };
        roomObj.canonical_top_face = OPPOSITE[r.doors[0].face] || 'north';
      }

      if (Array.isArray(r.doors) && r.doors.length > 0) {
        roomObj.doors = r.doors.map(function (d) {
          // v3 rename: label_px [x,y] → label_x / label_y. The OCR pipeline
          // doesn't produce a door label seed — omitted entirely per omission rule.
          var o = { face: d.face, offset_px: d.offset_px, width_px: d.width_px };
          if (d.hinge_side) o.hinge_side = d.hinge_side;
          if (typeof d.opens_inward === 'boolean') o.opens_inward = d.opens_inward;
          return o;
        });
      }
      if (Array.isArray(r.openings) && r.openings.length > 0) {
        roomObj.openings = r.openings.map(function (o) {
          return { face: o.face, offset_px: o.offset_px, width_px: o.width_px };
        });
      }
      if (Array.isArray(r.windows) && r.windows.length > 0) {
        roomObj.windows = r.windows.map(function (w) {
          return { face: w.face, offset_px: w.offset_px, width_px: w.width_px };
        });
      }
      roomsDict[roomId] = roomObj;
    });

    // Omission convention: optional metadata (building_id, floor_id,
    // north_angle_deg) is absent from the JSON, not empty-string/0.
    var out = {
      file: fileHint,
      page_width_px: ingState.planW || 0,
      page_height_px: ingState.planH || 0,
      rooms: roomsDict,
    };

    // D-95: persist the current scale in both fields. The UI value always
    // wins over anything previously stored in the JSON (Option D).
    if (ingState.scale && ingState.scale > 0) {
      var dpiExp = window.olmScale.getRenderDpi();
      if (dpiExp > 0) {
        var scaleNumExp = Math.round(ingState.scale * dpiExp / 2.54);
        if (scaleNumExp > 0) out.drawing_scale_text = '1 : ' + scaleNumExp;
      }
      out.drawing_scale_measured = ingState.scale.toFixed(4) + ' cm/px';
    }

    var json = JSON.stringify(out, null, 2);
    var blob = new Blob([json], { type: 'application/json' });
    var url = URL.createObjectURL(blob);
    var a = document.createElement('a');
    a.href = url;
    var stem = planName || 'plan';
    a.download = stem + '.json';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }

  window.devExportV3Json = devExportV3Json;
})();
