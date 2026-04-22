"use strict";
// ============================================================================
// INGESTION SERIALIZE — Unified rooms serializer (D-94 P4, R-12 C3, D-122 P5)
// ============================================================================
//
// Deux destinations, deux repères distincts :
//   • Matching   → POST `/api/floor-plan/match` en repère CANONIQUE
//                  (backend matcher suppose canonique — P5 acté).
//   • Storage v3 → écriture disque `<plan_id>.json` en repère ABSOLU
//                  (format fichier historique, voir PREPROCESSED_JSON_SPEC).
//
// `_canonRooms()` renvoie ingState.rooms tel quel (canonique).
// `_toAbsRooms()` applique `canonicalIO.toStorage` avant sérialisation.
// ============================================================================

(function () {

  // Source canonique : ingState.rooms tel quel (invariant post-fromStorage).
  function _canonRooms() {
    var ingState = window.ingState;
    if (!ingState || !ingState.rooms) return [];
    return ingState.rooms;
  }

  // Source absolue : canonicalIO.toStorage par pièce.
  // D-122 P1 : scale passé à toStorage pour rotation des offset_px / width_px.
  function _toAbsRooms() {
    var ingState = window.ingState;
    if (!ingState || !ingState.rooms) return [];
    var scale = ingState.scale || 0;
    return ingState.rooms.map(function (rC) {
      return (rC.corridor_face_abs !== undefined && window.canonicalIO)
        ? window.canonicalIO.toStorage(rC, scale)
        : rC;
    });
  }

  // ==========================================================================
  // Destination 1 : Matching (D-122 P5 — frontière canonique)
  // Consommée par fpLoadAndMatch / fpRematchRoom → `/api/floor-plan/match`.
  // Payload en repère CANONIQUE : le backend matcher suppose corridor-south,
  // aligné avec le catalogue lui-même canonique. Les portes sont fusionnées
  // dans `openings[]` via has_door=true (contrat OpeningSpec backend).
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
    var rooms = _canonRooms().map(function (r) {
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
          opens_inward: d.opens_inward !== false,
          hinge_side: d.hinge_side || 'left',
        });
      });
      return {
        name: r.name,
        width_cm: r.width_cm,       // canonique (post-swap pour east/west)
        depth_cm: r.depth_cm,
        windows: windows,
        openings: openings,
        exclusion_zones: (r.exclusion_zones || []).map(function (z) {
          return {
            x_cm: z.x_cm, y_cm: z.y_cm,
            width_cm: z.width_cm, depth_cm: z.depth_cm,
          };
        }),
        exterior_faces: r.exterior_faces,
        corridor_face: 'south',     // invariant canonique explicite
        corridor_face_abs: r.corridor_face_abs || '',
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

    // D-122 P1 : _toAbsRooms() passe scale à toStorage → offset_px /
    // width_px déjà rotés en cohérence avec offset_cm. Fallback vers 0
    // uniquement pour les legacy rooms sans offset_cm ni offset_px.
    function _px(v) {
      return (typeof v === 'number' && !isNaN(v)) ? Math.round(v) : 0;
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

      // D-135 : flag user-edit de la géométrie des murs. Persistant pour que
      // la pièce rouverte pré-coche "Lock walls" et préserve le bbox réglé
      // à la main au prochain Rescan.
      if (r.walls_user_edited) roomObj.walls_user_edited = true;

      // canonical_top_face : recalculé à chaque export depuis la porte
      // principale (cohérence avec re-analyze qui modifie les portes).
      if (Array.isArray(r.doors) && r.doors.length > 0 && r.doors[0].face) {
        var OPPOSITE = { north: 'south', south: 'north', east: 'west', west: 'east' };
        roomObj.canonical_top_face = OPPOSITE[r.doors[0].face] || 'north';
      }

      // D-131 : persiste origin ("auto"|"manual") si présent. Sans ça, la
      // distinction auto vs manual se perd entre sessions → chaque Re-analyze
      // écrase les ouvertures que l'utilisateur avait personnalisées.
      if (Array.isArray(r.doors) && r.doors.length > 0) {
        roomObj.doors = r.doors.map(function (d) {
          var o = {
            face: d.face,
            offset_px: _px(d.offset_px),
            width_px:  _px(d.width_px),
          };
          if (d.hinge_side) o.hinge_side = d.hinge_side;
          if (typeof d.opens_inward === 'boolean') o.opens_inward = d.opens_inward;
          if (d.origin) o.origin = d.origin;
          return o;
        });
      }
      if (Array.isArray(r.openings) && r.openings.length > 0) {
        roomObj.openings = r.openings.map(function (o) {
          var out = {
            face: o.face,
            offset_px: _px(o.offset_px),
            width_px:  _px(o.width_px),
          };
          if (o.origin) out.origin = o.origin;
          return out;
        });
      }
      if (Array.isArray(r.windows) && r.windows.length > 0) {
        roomObj.windows = r.windows.map(function (w) {
          var out = {
            face: w.face,
            offset_px: _px(w.offset_px),
            width_px:  _px(w.width_px),
          };
          if (w.origin) out.origin = w.origin;
          return out;
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

    // Métadonnées floor (PREPROCESSED_JSON_SPEC §1). Persistées seulement
    // si renseignées pour respecter la convention d'omission.
    if (ingState.buildingId) out.building_id = ingState.buildingId;
    if (ingState.floorId)    out.floor_id    = ingState.floorId;
    if (typeof ingState.northAngleDeg === 'number' &&
        ingState.northAngleDeg !== 0) {
      out.north_angle_deg = ingState.northAngleDeg;
    }

    // D-135 : persiste "au moins un scan a été effectué". Sert de défaut
    // pour la case Lock walls de la toolbar Floor au prochain chargement.
    if (ingState.firstScanDone) out.first_scan_done = true;

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
