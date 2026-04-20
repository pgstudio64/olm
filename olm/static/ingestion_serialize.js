"use strict";
// ============================================================================
// INGESTION SERIALIZE — Unified rooms serializer (D-94 P4, R-12 C3)
// ============================================================================
//
// Deux destinations partagent la même fondation en repère absolu :
//   • Matching   → textarea `fpRoomsJson` puis fpLoadAndMatch (C3, avant C4).
//   • Storage v3 → écriture disque `<plan_id>.json` (bouton Save / Export).
//
// Les deux passent chaque pièce en repère canonique par `canonicalIO.toStorage`
// quand elle est marquée par `original_corridor_face`, pour que les
// formatteurs en aval voient uniformément du repère absolu. La logique
// `toStorage` n'apparaît qu'à un seul endroit : `_toAbsRooms()`.
// ============================================================================

(function () {

  // --- Source unique : pièces de ingState.rooms ramenées en repère absolu ---
  function _toAbsRooms() {
    var ingState = window.ingState;
    if (!ingState || !ingState.rooms) return [];
    return ingState.rooms.map(function (rC) {
      return (rC.original_corridor_face !== undefined && window.canonicalIO)
        ? window.canonicalIO.toStorage(rC)
        : rC;
    });
  }

  // ==========================================================================
  // Destination 1 : Matching
  // Consommée par fpLoadAndMatch via le textarea `fpRoomsJson` (avant C4).
  // Format : { rooms: [{name, width_cm, depth_cm, windows, openings, ...}] }
  // Offsets en cm (offset_cm / width_cm) pour rester aligné avec l'algo de
  // matching. Les portes sont fusionnées dans `openings[]` via has_door=true.
  // ==========================================================================
  function serializeForMatching() {
    var ingState = window.ingState;
    var scale = (ingState && ingState.scale) || 0;
    function _offCm(e) {
      return (e && e.offset_cm != null)
        ? Math.round(e.offset_cm)
        : Math.round(((e && e.offset_px) || 0) * scale);
    }
    function _widCm(e) {
      return (e && e.width_cm != null)
        ? Math.round(e.width_cm)
        : Math.round(((e && e.width_px) || 0) * scale);
    }
    var rooms = _toAbsRooms().map(function (r) {
      var windows = (r.windows || []).map(function (w) {
        return { face: w.face, offset_cm: _offCm(w), width_cm: _widCm(w) };
      });
      var openings = (r.openings || []).map(function (o) {
        return {
          face: o.face,
          offset_cm: _offCm(o),
          width_cm: _widCm(o),
          has_door: false,
        };
      });
      (r.doors || []).forEach(function (d) {
        openings.push({
          face: d.face,
          offset_cm: _offCm(d),
          width_cm: _widCm(d),
          has_door: true,
          opens_inward: d.opens_inward || true,
          hinge_side: d.hinge_side || 'left',
        });
      });
      return {
        name: r.name,
        width_cm: r.width_cm,
        depth_cm: r.depth_cm,
        windows: windows,
        openings: openings,
        exclusion_zones: [],
        exterior_faces: r.exterior_faces,
        corridor_face: r.corridor_face,
        bbox_px: r.bbox_px,
        seed_px: r.seed_px || r.seed,
        doors: r.doors || [],
      };
    });
    return { rooms: rooms };
  }

  // Wrapper UI : écrit la sortie dans le textarea d'édition.
  function populateRoomsJson() {
    var textarea = document.getElementById('fpRoomsJson');
    if (!textarea) return;
    textarea.value = JSON.stringify(serializeForMatching(), null, 2);
  }

  // ==========================================================================
  // Destination 2 : Storage v3
  // Format documenté dans `docs/specs/PREPROCESSED_JSON_SPEC.md` §5.
  // Offsets en px, portes séparées des openings, métadonnées scale / page.
  // ==========================================================================
  function serializeForStorage() {
    var ingState = window.ingState;
    if (!ingState || !ingState.rooms) return null;

    var hdr = document.getElementById('hdrCurrentPlan');
    var planName = hdr ? hdr.textContent.trim() : '';
    var fileHint = planName ? (planName + '.png') : 'plan.png';

    // R-12 dette : toStorage rote offset_cm / face mais pas offset_px.
    // On recalcule donc offset_px / width_px depuis offset_cm × pxPerCm
    // à la sérialisation. Fallback sur l'offset_px existant si offset_cm
    // est absent (rétrocompat rooms OCR legacy).
    var pxPerCm = (ingState.scale && ingState.scale > 0)
      ? (1.0 / ingState.scale) : 0;
    function _pxFromCm(cm, fallbackPx) {
      if (cm != null && pxPerCm > 0) return Math.round(cm * pxPerCm);
      return (fallbackPx != null) ? fallbackPx : 0;
    }

    var roomsDict = {};
    _toAbsRooms().forEach(function (r) {
      var roomId = r.name || '';
      if (!roomId) return;

      // Cartouche seed : prefer seed_px, else seed, else bbox center
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

      // Surface en string "N.NN m2" — v3 garde la forme texte
      var surfaceStr = '';
      if (typeof r.surface_m2 === 'number' && r.surface_m2 > 0) {
        surfaceStr = r.surface_m2.toFixed(2) + ' m2';
      }

      var roomObj = { surface: surfaceStr, seed_x: seed[0], seed_y: seed[1] };

      if (Array.isArray(r.bbox_px) && r.bbox_px.length === 4) {
        roomObj.bbox_px = r.bbox_px.map(function (v) { return Math.round(v); });
      }

      // canonical_top_face : recalculé à chaque export depuis la porte
      // principale (cohérence avec re-analyze qui modifie les portes).
      if (Array.isArray(r.doors) && r.doors.length > 0 && r.doors[0].face) {
        var OPPOSITE = { north: 'south', south: 'north', east: 'west', west: 'east' };
        roomObj.canonical_top_face = OPPOSITE[r.doors[0].face] || 'north';
      }

      if (Array.isArray(r.doors) && r.doors.length > 0) {
        roomObj.doors = r.doors.map(function (d) {
          var o = {
            face: d.face,
            offset_px: _pxFromCm(d.offset_cm, d.offset_px),
            width_px:  _pxFromCm(d.width_cm,  d.width_px),
          };
          if (d.hinge_side) o.hinge_side = d.hinge_side;
          if (typeof d.opens_inward === 'boolean') o.opens_inward = d.opens_inward;
          return o;
        });
      }
      if (Array.isArray(r.openings) && r.openings.length > 0) {
        roomObj.openings = r.openings.map(function (o) {
          return {
            face: o.face,
            offset_px: _pxFromCm(o.offset_cm, o.offset_px),
            width_px:  _pxFromCm(o.width_cm,  o.width_px),
          };
        });
      }
      if (Array.isArray(r.windows) && r.windows.length > 0) {
        roomObj.windows = r.windows.map(function (w) {
          return {
            face: w.face,
            offset_px: _pxFromCm(w.offset_cm, w.offset_px),
            width_px:  _pxFromCm(w.width_cm,  w.width_px),
          };
        });
      }
      roomsDict[roomId] = roomObj;
    });

    var out = {
      file: fileHint,
      page_width_px: ingState.planW || 0,
      page_height_px: ingState.planH || 0,
      rooms: roomsDict,
    };

    // D-95 : persistance de l'échelle dans les deux champs.
    if (ingState.scale && ingState.scale > 0) {
      var dpiExp = window.olmScale.getRenderDpi();
      if (dpiExp > 0) {
        var scaleNumExp = Math.round(ingState.scale * dpiExp / 2.54);
        if (scaleNumExp > 0) out.drawing_scale_text = '1 : ' + scaleNumExp;
      }
      out.drawing_scale_measured = ingState.scale.toFixed(4) + ' cm/px';
    }

    return { payload: out, planName: planName };
  }

  // Wrapper UI : déclenche le téléchargement du JSON v3.
  function devExportV3Json() {
    var ingState = window.ingState;
    if (!ingState || !ingState.rooms || ingState.rooms.length === 0) {
      alert('No rooms to export. Load a floor plan first.');
      return;
    }
    var res = serializeForStorage();
    if (!res) return;
    var json = JSON.stringify(res.payload, null, 2);
    var blob = new Blob([json], { type: 'application/json' });
    var url = URL.createObjectURL(blob);
    var a = document.createElement('a');
    a.href = url;
    var stem = res.planName || 'plan';
    a.download = stem + '.json';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }

  // ==========================================================================
  // API publique
  // ==========================================================================
  window.olmSerialize = {
    serializeForMatching: serializeForMatching,
    serializeForStorage:  serializeForStorage,
  };
  window.populateRoomsJson = populateRoomsJson;
  window.devExportV3Json   = devExportV3Json;
})();
