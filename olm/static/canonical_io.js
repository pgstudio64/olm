// ============================================================================
// canonical_io.js — Frontières abs ↔ canonique (R-12, D-117)
// ============================================================================
// Expose window.canonicalIO = { fromStorage, toStorage, FACE_MAPS, INV_FACE_MAPS }
//
// Deux fonctions frontière :
//   fromStorage(roomStorage) → roomCanon  : repère absolu → corridor_face "south"
//   toStorage(roomCanon)     → roomStorage: corridor_face "south" → repère absolu
//
// Source unique des matrices de rotation. Les copies dans floor_plan.js
// (_FACE_MAPS / _INV_FACE_MAPS) seront retirées à l'étape B du refactor.
// ============================================================================
(function () {

  // ── Matrices de rotation face absolu → face canonique ──────────────────
  // Clé = corridor_face absolu de la pièce.
  // Valeur = mapping face_abs → face_canon.
  var FACE_MAPS = {
    north: { north: "south", south: "north", east: "west",  west: "east"  },
    east:  { north: "east",  east:  "south", south: "west", west: "north" },
    west:  { north: "west",  west:  "south", south: "east", east: "north" },
  };

  // ── Matrices inverses face canonique → face absolu ──────────────────────
  var INV_FACE_MAPS = {
    north: { north: "south", south: "north", east: "west",  west: "east"  },
    east:  { north: "west",  east:  "north", south: "east", west: "south" },
    west:  { north: "east",  east:  "south", south: "west", west: "north" },
  };

  // ── Helpers internes ────────────────────────────────────────────────────

  /**
   * Longueur de la face dans le repère ABSOLU (avant swap).
   * @param {string} face  - "north" | "south" | "east" | "west"
   * @param {number} W     - width_cm absolu
   * @param {number} D     - depth_cm absolu
   * @returns {number}
   */
  function _absLen(face, W, D) {
    return (face === "north" || face === "south") ? W : D;
  }

  /**
   * Longueur de la face dans le repère CANONIQUE (après swap si east/west).
   * @param {string} face  - face canonique
   * @param {number} Wc    - width_cm canonique
   * @param {number} Dc    - depth_cm canonique
   * @returns {number}
   */
  function _canonLen(face, Wc, Dc) {
    return (face === "north" || face === "south") ? Wc : Dc;
  }

  // ── fromStorage ─────────────────────────────────────────────────────────

  /**
   * Convertit une pièce en repère absolu (stockage JSON v3 ou retour re-analyze)
   * en repère canonique (corridor_face = "south", invariant).
   *
   * @param {Object} roomStorage - Pièce telle que lue du JSON v3 ou re-analyze.
   *   corridor_face ∈ {"", "south", "north", "east", "west"}
   * @returns {Object} roomCanon - Copie profonde avec repère canonique.
   *
   * @example
   *   var canon = window.canonicalIO.fromStorage(room);
   *   // canon.corridor_face === "south"
   *   // canon.original_corridor_face === room.corridor_face || ""
   */
  function fromStorage(roomStorage) {
    var copy = JSON.parse(JSON.stringify(roomStorage));
    var cf = roomStorage.corridor_face || "";

    copy.original_corridor_face = cf;
    copy.bbox_abs_px = roomStorage.bbox_px || null;
    copy.seed_abs_px = roomStorage.seed_px || null;

    if (!cf || cf === "south") {
      // Rotation identité — assurer les champs canoniques
      copy.corridor_face = "south";
      copy.bbox_canon_cm = { x: 0, y: 0, w: copy.width_cm, h: copy.depth_cm };
      copy.surface_m2_bbox = Math.round(copy.width_cm * copy.depth_cm / 10000 * 100) / 100;
      return copy;
    }

    var faceMap = FACE_MAPS[cf];
    if (!faceMap) {
      copy.corridor_face = "south";
      copy.bbox_canon_cm = { x: 0, y: 0, w: copy.width_cm, h: copy.depth_cm };
      copy.surface_m2_bbox = Math.round(copy.width_cm * copy.depth_cm / 10000 * 100) / 100;
      return copy;
    }

    var W = roomStorage.width_cm;
    var D = roomStorage.depth_cm;
    var swap = (cf === "east" || cf === "west");
    if (swap) { copy.width_cm = D; copy.depth_cm = W; }

    // Transforme une ouverture (window / opening / door)
    function xformOpening(o) {
      var r = Object.assign({}, o);
      r.face = faceMap[o.face] || o.face;
      if (cf === "north" || cf === "west") {
        r.offset_cm = _absLen(o.face, W, D) - (o.offset_cm || 0) - (o.width_cm || 0);
        if (o.hinge_side) {
          r.hinge_side = (o.hinge_side === "left") ? "right" : "left";
        }
      }
      return r;
    }

    copy.windows  = (roomStorage.windows  || []).map(xformOpening);
    copy.openings = (roomStorage.openings || []).map(xformOpening);
    copy.doors    = (roomStorage.doors    || []).map(xformOpening);

    // Transforme une zone (exclusion / transparent)
    function xformZone(e) {
      var ex = Object.assign({}, e);
      if (cf === "north") {
        ex.x_cm = W - e.x_cm - e.width_cm;
        ex.y_cm = D - e.y_cm - e.depth_cm;
      } else if (cf === "east") {
        ex.x_cm     = e.y_cm;
        ex.y_cm     = W - e.x_cm - e.width_cm;
        ex.width_cm = e.depth_cm;
        ex.depth_cm = e.width_cm;
      } else if (cf === "west") {
        ex.x_cm     = D - e.y_cm - e.depth_cm;
        ex.y_cm     = e.x_cm;
        ex.width_cm = e.depth_cm;
        ex.depth_cm = e.width_cm;
      }
      return ex;
    }

    if (roomStorage.exclusion_zones  && roomStorage.exclusion_zones.length) {
      copy.exclusion_zones  = roomStorage.exclusion_zones.map(xformZone);
    }
    if (roomStorage.transparent_zones && roomStorage.transparent_zones.length) {
      copy.transparent_zones = roomStorage.transparent_zones.map(xformZone);
    }

    copy.corridor_face    = "south";
    copy.bbox_canon_cm    = { x: 0, y: 0, w: copy.width_cm, h: copy.depth_cm };
    copy.surface_m2_bbox  = Math.round(copy.width_cm * copy.depth_cm / 10000 * 100) / 100;

    return copy;
  }

  // ── toStorage ────────────────────────────────────────────────────────────

  /**
   * Convertit une pièce en repère canonique (state mémoire) vers le repère
   * absolu (stockage JSON v3 ou payload re-analyze).
   *
   * Inverse exacte de fromStorage : toStorage(fromStorage(r)) ≡ r.
   *
   * @param {Object} roomCanon - Pièce en repère canonique.
   *   Doit posséder original_corridor_face (mémorisé par fromStorage).
   * @returns {Object} roomStorage - Copie profonde en repère absolu.
   *
   * @example
   *   var stored = window.canonicalIO.toStorage(canonRoom);
   *   // stored.corridor_face === canonRoom.original_corridor_face || "south"
   */
  function toStorage(roomCanon) {
    var copy = JSON.parse(JSON.stringify(roomCanon));
    var ocf = roomCanon.original_corridor_face || "";

    // Restaure bbox_px / seed_px
    if (roomCanon.bbox_abs_px) {
      copy.bbox_px = roomCanon.bbox_abs_px;
    }
    if (roomCanon.seed_abs_px) {
      copy.seed_px = roomCanon.seed_abs_px;
    }

    // Nettoie les champs canoniques (absents du stockage)
    delete copy.original_corridor_face;
    delete copy.bbox_abs_px;
    delete copy.seed_abs_px;
    delete copy.bbox_canon_cm;
    delete copy.surface_m2_bbox;

    copy.corridor_face = ocf;

    if (!ocf || ocf === "south") {
      return copy;
    }

    var invMap = INV_FACE_MAPS[ocf];
    if (!invMap) return copy;

    // Dimensions canoniques (avant swap retour)
    var Wc = roomCanon.width_cm;
    var Dc = roomCanon.depth_cm;
    var swap = (ocf === "east" || ocf === "west");
    if (swap) { copy.width_cm = Dc; copy.depth_cm = Wc; }

    // Transforme en retour une ouverture
    function xformBack(o) {
      var r = Object.assign({}, o);
      r.face = invMap[o.face] || o.face;
      if (ocf === "north" || ocf === "west") {
        r.offset_cm = _canonLen(o.face, Wc, Dc) - (o.offset_cm || 0) - (o.width_cm || 0);
        if (o.hinge_side) {
          r.hinge_side = (o.hinge_side === "left") ? "right" : "left";
        }
      }
      return r;
    }

    copy.windows  = (roomCanon.windows  || []).map(xformBack);
    copy.openings = (roomCanon.openings || []).map(xformBack);
    copy.doors    = (roomCanon.doors    || []).map(xformBack);

    // Transforme en retour une zone
    function xformZoneBack(e) {
      var ex = Object.assign({}, e);
      if (ocf === "north") {
        // canonical dims = absolu pour north (pas de swap)
        ex.x_cm = Wc - e.x_cm - e.width_cm;
        ex.y_cm = Dc - e.y_cm - e.depth_cm;
      } else if (ocf === "east") {
        // canonical: w=D_abs, h=W_abs → inverse: (xc,yc) → (W-yc-hc, xc)
        ex.x_cm     = Dc - e.y_cm - e.depth_cm;
        ex.y_cm     = e.x_cm;
        ex.width_cm = e.depth_cm;
        ex.depth_cm = e.width_cm;
      } else if (ocf === "west") {
        // canonical: w=D_abs, h=W_abs → inverse: (xc,yc) → (yc, W-xc-wc)
        ex.x_cm     = e.y_cm;
        ex.y_cm     = Wc - e.x_cm - e.width_cm;
        ex.width_cm = e.depth_cm;
        ex.depth_cm = e.width_cm;
      }
      return ex;
    }

    if (roomCanon.exclusion_zones  && roomCanon.exclusion_zones.length) {
      copy.exclusion_zones  = roomCanon.exclusion_zones.map(xformZoneBack);
    }
    if (roomCanon.transparent_zones && roomCanon.transparent_zones.length) {
      copy.transparent_zones = roomCanon.transparent_zones.map(xformZoneBack);
    }

    return copy;
  }

  // ── Auto-tests round-trip ────────────────────────────────────────────────
  // Activer via : window.RUN_CANONICAL_IO_TESTS = true;  (avant le chargement
  // du script ou depuis la console avant reload)

  function _runTests() {
    var SAMPLES = [
      {
        name: "T1-south",
        room: {
          name: "T1", corridor_face: "south", width_cm: 300, depth_cm: 500,
          bbox_px: [100, 200, 160, 300], seed_px: [130, 250],
          windows:  [{ face: "north", offset_cm: 50,  width_cm: 120 }],
          openings: [{ face: "south", offset_cm: 80,  width_cm: 90  }],
          doors:    [{ face: "east",  offset_cm: 100, width_cm: 80, hinge_side: "left" }],
          exclusion_zones: [{ x_cm: 10, y_cm: 20, width_cm: 50, depth_cm: 60 }],
        },
      },
      {
        name: "T2-north",
        room: {
          name: "T2", corridor_face: "north", width_cm: 400, depth_cm: 600,
          bbox_px: [200, 300, 280, 420], seed_px: [240, 360],
          windows:  [{ face: "north", offset_cm: 30, width_cm: 150 }],
          openings: [{ face: "west",  offset_cm: 20, width_cm: 100 }],
          doors:    [{ face: "south", offset_cm: 50, width_cm: 80, hinge_side: "right" }],
          exclusion_zones: [{ x_cm: 5, y_cm: 10, width_cm: 40, depth_cm: 70 }],
          transparent_zones: [{ x_cm: 100, y_cm: 200, width_cm: 60, depth_cm: 80 }],
        },
      },
      {
        name: "T3-east",
        room: {
          name: "T3", corridor_face: "east", width_cm: 250, depth_cm: 700,
          bbox_px: [50, 80, 120, 290], seed_px: [85, 185],
          windows:  [{ face: "east",  offset_cm: 60,  width_cm: 110 }],
          openings: [{ face: "south", offset_cm: 40,  width_cm: 90  }],
          doors:    [{ face: "north", offset_cm: 20,  width_cm: 80, hinge_side: "left" }],
          exclusion_zones: [{ x_cm: 15, y_cm: 25, width_cm: 80, depth_cm: 100 }],
        },
      },
      {
        name: "T4-west",
        room: {
          name: "T4", corridor_face: "west", width_cm: 350, depth_cm: 550,
          bbox_px: [300, 100, 380, 265], seed_px: [340, 180],
          windows:  [{ face: "west",  offset_cm: 70,  width_cm: 130 }],
          openings: [{ face: "north", offset_cm: 30,  width_cm: 95  }],
          doors:    [{ face: "east",  offset_cm: 45,  width_cm: 80, hinge_side: "right" }],
          exclusion_zones: [{ x_cm: 20, y_cm: 30, width_cm: 70, depth_cm: 90 }],
        },
      },
    ];

    var allOk = true;

    SAMPLES.forEach(function (s) {
      var canon   = fromStorage(s.room);
      var storage = toStorage(canon);
      var diff    = _deepDiff(s.room, storage, "");
      if (diff.length === 0) {
        console.log("[canonical_io] OK — round-trip " + s.name);
      } else {
        allOk = false;
        console.error("[canonical_io] DIFF — round-trip " + s.name, diff);
      }
    });

    if (allOk) {
      console.log("[canonical_io] ALL TESTS PASSED");
    } else {
      console.error("[canonical_io] SOME TESTS FAILED — see diffs above");
    }
  }

  /**
   * Comparaison profonde de deux valeurs; retourne un tableau de chemins
   * qui diffèrent.  Tolère les arrondis entiers sur les offset_cm.
   */
  function _deepDiff(a, b, path) {
    var diffs = [];
    if (typeof a !== typeof b) {
      diffs.push(path + " type " + typeof a + " vs " + typeof b);
      return diffs;
    }
    if (Array.isArray(a)) {
      if (!Array.isArray(b) || a.length !== b.length) {
        diffs.push(path + " array length " + (Array.isArray(a) ? a.length : "?")
          + " vs " + (Array.isArray(b) ? b.length : "?"));
        return diffs;
      }
      a.forEach(function (v, i) {
        diffs = diffs.concat(_deepDiff(v, b[i], path + "[" + i + "]"));
      });
      return diffs;
    }
    if (a !== null && typeof a === "object") {
      var keys = Object.keys(a);
      keys.forEach(function (k) {
        diffs = diffs.concat(_deepDiff(a[k], b[k], path ? path + "." + k : k));
      });
      return diffs;
    }
    // Valeur primitive — tolérance d'1 cm sur les offsets
    if (a !== b) {
      if (typeof a === "number" && Math.abs(a - b) <= 1) return diffs;
      diffs.push(path + " " + JSON.stringify(a) + " vs " + JSON.stringify(b));
    }
    return diffs;
  }

  // ── Exposition publique ──────────────────────────────────────────────────
  window.canonicalIO = {
    fromStorage:   fromStorage,
    toStorage:     toStorage,
    FACE_MAPS:     FACE_MAPS,
    INV_FACE_MAPS: INV_FACE_MAPS,
  };

  if (window.RUN_CANONICAL_IO_TESTS) {
    _runTests();
  }

}());
