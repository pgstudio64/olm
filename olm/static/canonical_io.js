// ============================================================================
// canonical_io.js — Frontières abs ↔ canonique (R-12, D-117, D-122 P1)
// ============================================================================
// Expose window.canonicalIO = { fromStorage, toStorage, FACE_MAPS, INV_FACE_MAPS }
//
// Deux fonctions frontière :
//   fromStorage(roomStorage, scale) → roomCanon  : repère absolu → "south"
//   toStorage(roomCanon,     scale) → roomStorage: "south"       → absolu
//
// Source unique des matrices de rotation (D-120) et des conversions px ↔ cm
// (D-122 P1). scale = cm/px (ingState.scale) ; si omis, les offset_px /
// width_px sont laissés intacts (utile pour les tests fragments).
//
// Champs traités automatiquement dans chaque opening/door :
//   face, offset_cm, width_cm, hinge_side (symétrie gauche/droite).
//   offset_px et width_px sont recalculés depuis offset_cm × pxPerCm
//   lorsqu'un scale est passé — plus besoin de recalc ad-hoc côté
//   appelant (cf. ingestion_serialize.js, ingestion.js:_renderRoom).
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

  /**
   * Détermine si l'offset d'une ouverture doit être retourné (flipped)
   * lors de la conversion abs → canon (fromStorage).
   *
   * Pour une rotation 90° CW (cf="east"), seules les faces verticales abs
   * (east, west) voient leur direction d'offset inversée.  Les faces
   * horizontales (north, south) conservent l'offset.
   * Pour 90° CCW (cf="west"), c'est l'inverse : seules les horizontales.
   * Pour 180° (cf="north"), toutes les faces sont inversées.
   *
   * @param {string} cf       - corridor_face absolu
   * @param {string} absFace  - face dans le repère absolu
   * @returns {boolean}
   */
  function _flipFrom(cf, absFace) {
    if (cf === "north") return true;
    var isV = (absFace === "east" || absFace === "west");
    if (cf === "east") return isV;
    if (cf === "west") return !isV;
    return false;
  }

  /**
   * Inverse de _flipFrom : détermine si l'offset doit être retourné lors
   * de la conversion canon → abs (toStorage).
   *
   * @param {string} ocf        - corridor_face absolu d'origine
   * @param {string} canonFace  - face dans le repère canonique
   * @returns {boolean}
   */
  function _flipTo(ocf, canonFace) {
    if (ocf === "north") return true;
    var isH = (canonFace === "north" || canonFace === "south");
    if (ocf === "east") return isH;
    if (ocf === "west") return !isH;
    return false;
  }

  /**
   * Recalcule offset_px / width_px depuis offset_cm × pxPerCm.
   * Si pxPerCm <= 0 ou offset_cm absent, laisse la valeur en l'état.
   * D-122 P1 : toStorage/fromStorage deviennent la source unique des px.
   */
  function _syncPx(o, pxPerCm) {
    if (!(pxPerCm > 0)) return;
    if (o.offset_cm != null) o.offset_px = Math.round(o.offset_cm * pxPerCm);
    if (o.width_cm  != null) o.width_px  = Math.round(o.width_cm  * pxPerCm);
  }

  // ── Helpers publics de rotation (D-122 P6) ───────────────────────────────

  /**
   * Rote un point room-local (cm) depuis le repère ABSOLU vers le repère
   * CANONIQUE (corridor = "south"). Les coords d'entrée sont relatives au
   * coin NW absolu de la pièce ; celles de sortie sont relatives au coin
   * NW canonique après swap éventuel.
   *
   * @param {{x:number,y:number}} pt - Point absolu room-local (cm).
   * @param {string} cfAbs           - corridor_face absolu ("north"/"east"/"west"/"south"/"").
   * @param {number} absW            - Largeur absolue (cm).
   * @param {number} absD            - Profondeur absolue (cm).
   * @returns {{x:number,y:number}} Point canonique room-local (cm).
   */
  var DIR_LONG = { n: "north", s: "south", e: "east", w: "west" };
  var DIR_SHORT = { north: "n", south: "s", east: "e", west: "w" };

  /**
   * Pivote une direction courte (n/s/e/w) abs → canon, même logique que
   * rotatePoint. Retourne null si d est falsy ou si cfAbs n'a pas de map.
   */
  function rotateDir(d, cfAbs) {
    if (!d) return d;
    var map = FACE_MAPS[cfAbs];
    if (!map) return d;  // south ou vide → identité
    var long = DIR_LONG[d];
    if (!long) return d;
    return DIR_SHORT[map[long]] || d;
  }

  /**
   * Inverse de rotateDir : canon → abs. Utilise INV_FACE_MAPS.
   */
  function rotateDirInv(d, cfAbs) {
    if (!d) return d;
    var map = INV_FACE_MAPS[cfAbs];
    if (!map) return d;
    var long = DIR_LONG[d];
    if (!long) return d;
    return DIR_SHORT[map[long]] || d;
  }

  function rotatePoint(pt, cfAbs, absW, absD) {
    var x = pt.x, y = pt.y;
    if (cfAbs === "north") return { x: absW - x, y: absD - y };
    if (cfAbs === "east")  return { x: absD - y, y: x         };
    if (cfAbs === "west")  return { x: y,        y: absW - x };
    return { x: x, y: y };
  }

  /**
   * Rote un rectangle room-local (cm) abs → canon. Applique la rotation
   * au coin NW puis remappe width/depth selon l'axe swap (east/west).
   *
   * @param {{x:number,y:number,width:number,depth:number}} rect
   * @param {string} cfAbs
   * @param {number} absW
   * @param {number} absD
   */
  function rotateRect(rect, cfAbs, absW, absD) {
    var x = rect.x, y = rect.y, w = rect.width, d = rect.depth;
    if (cfAbs === "north") return { x: absW - x - w, y: absD - y - d, width: w, depth: d };
    if (cfAbs === "east")  return { x: absD - y - d, y: x,             width: d, depth: w };
    if (cfAbs === "west")  return { x: y,            y: absW - x - w, width: d, depth: w };
    return { x: x, y: y, width: w, depth: d };
  }

  /**
   * Angle SVG (degrés, sens SVG rotate positif) pour mettre une pièce en
   * repère canonique (corridor sud). cfAbs = corridor_face absolu.
   *
   * Convention dérivée du rendu overlay actuel (D-83 / éditeur.js) :
   *   south → 0, east → 270, north → 180, west → 90.
   *
   * Source unique de cette convention (D-134 P6) — remplace
   * `_canonicalAngle` éparpillé dans editor.js.
   *
   * @param {string} cfAbs
   * @returns {number} degrés pour `transform="rotate(angle cx cy)"`.
   */
  function canonAngle(cfAbs) {
    if (cfAbs === "east")  return 90;
    if (cfAbs === "north") return 180;
    if (cfAbs === "west")  return 270;
    return 0;  // "" ou "south" ou inconnu → pas de rotation
  }

  /**
   * Inverse exact de rotateRect : canon → abs. Prend un rectangle en repère
   * canonique (corridor sud) et retourne ses coords room-local dans le repère
   * absolu avec corridor_face_abs = cfAbs.
   * absW / absD sont les dims ABSOLUES (pas canoniques) ; ce sont les mêmes
   * que celles passées à rotateRect, ce qui garantit la symétrie :
   *   rotateRectInv(rotateRect(r, cf, W, D), cf, W, D) ≡ r.
   *
   * @param {{x:number,y:number,width:number,depth:number}} rect
   * @param {string} cfAbs
   * @param {number} absW
   * @param {number} absD
   */
  function rotateRectInv(rect, cfAbs, absW, absD) {
    var xc = rect.x, yc = rect.y, wc = rect.width, dc = rect.depth;
    if (cfAbs === "north") return { x: absW - xc - wc, y: absD - yc - dc, width: wc, depth: dc };
    if (cfAbs === "east")  return { x: yc,             y: absD - xc - wc, width: dc, depth: wc };
    if (cfAbs === "west")  return { x: absW - yc - dc, y: xc,             width: dc, depth: wc };
    return { x: xc, y: yc, width: wc, depth: dc };
  }


  /**
   * Inverse exact de rotatePoint : canon → abs.
   * rotatePointInv(rotatePoint(p, cf, W, D), cf, W, D) ≡ p.
   *
   * @param {{x:number,y:number}} pt
   * @param {string} cfAbs
   * @param {number} absW
   * @param {number} absD
   */
  function rotatePointInv(pt, cfAbs, absW, absD) {
    var x = pt.x, y = pt.y;
    if (cfAbs === "north") return { x: absW - x, y: absD - y };
    if (cfAbs === "east")  return { x: y,        y: absD - x };
    if (cfAbs === "west")  return { x: absW - y, y: x        };
    return { x: x, y: y };
  }

  // ── fromStorage ─────────────────────────────────────────────────────────

  /**
   * Convertit une pièce en repère absolu (stockage JSON v3 ou retour re-analyze)
   * en repère canonique (corridor_face = "south", invariant).
   *
   * @param {Object} roomStorage - Pièce telle que lue du JSON v3 ou re-analyze.
   *   corridor_face ∈ {"", "south", "north", "east", "west"}
   * @param {number}  [scale]    - cm/px ; optionnel. Permet de recalculer
   *   offset_px / width_px en cohérence avec offset_cm post-rotation.
   * @returns {Object} roomCanon - Copie profonde avec repère canonique.
   *
   * @example
   *   var canon = window.canonicalIO.fromStorage(room, ingState.scale);
   *   // canon.corridor_face === "south"
   *   // canon.corridor_face_abs === room.corridor_face || ""
   */
  function fromStorage(roomStorage, scale) {
    var pxPerCm = (typeof scale === "number" && scale > 0) ? (1.0 / scale) : 0;
    var copy = JSON.parse(JSON.stringify(roomStorage));
    var cf = roomStorage.corridor_face || "";

    copy.corridor_face_abs = cf;
    // D-122 P2 : bbox_px / seed_px en coords image absolues (jamais rotés).
    // Plus de duplication bbox_abs_px / seed_abs_px — fusion acquise.

    // D-204: door_seeds are image-absolute coords, never rotated.
    if (roomStorage.door_seeds && roomStorage.door_seeds.length) {
      copy.door_seeds = roomStorage.door_seeds.slice();
    }
    // D-204: split legacy mixed doors[] at load (migration).
    if (!copy.door_seeds && copy.doors && copy.doors.length) {
      var _legacySeeds = [];
      var _typedOnly = [];
      copy.doors.forEach(function (d) {
        if (typeof d.seed_x === "number" && !d.face) {
          _legacySeeds.push({ seed_x: d.seed_x, seed_y: d.seed_y });
        } else {
          _typedOnly.push(d);
        }
      });
      if (_legacySeeds.length) {
        copy.door_seeds = _legacySeeds;
        copy.doors = _typedOnly;
      }
    }

    if (!cf || cf === "south") {
      // Rotation identité — assurer les champs canoniques + sync px
      copy.corridor_face = "south";
      copy.bbox_canon_cm = { x: 0, y: 0, w: copy.width_cm, h: copy.depth_cm };
      copy.surface_m2_bbox = Math.round(copy.width_cm * copy.depth_cm / 10000 * 100) / 100;
      (copy.windows  || []).forEach(function (o) { _syncPx(o, pxPerCm); });
      (copy.openings || []).forEach(function (o) { _syncPx(o, pxPerCm); });
      (copy.doors    || []).forEach(function (o) { _syncPx(o, pxPerCm); });
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

    // Transforme une ouverture (window / opening / door) + sync px
    function xformOpening(o) {
      var r = Object.assign({}, o);
      r.face = faceMap[o.face] || o.face;
      if (_flipFrom(cf, o.face)) {
        r.offset_cm = _absLen(o.face, W, D) - (o.offset_cm || 0) - (o.width_cm || 0);
        if (o.hinge_side) {
          r.hinge_side = (o.hinge_side === "left") ? "right" : "left";
        }
      }
      _syncPx(r, pxPerCm);
      return r;
    }

    copy.windows  = (roomStorage.windows  || []).map(xformOpening);
    copy.openings = (roomStorage.openings || []).map(xformOpening);
    copy.doors    = (roomStorage.doors    || []).map(xformOpening);

    // Transforme une zone (exclusion / transparent)
    function xformZone(e) {
      var ex = Object.assign({}, e);
      if (cf === "north") {
        ex.x_cm = Math.round(W - e.x_cm - e.width_cm);
        ex.y_cm = Math.round(D - e.y_cm - e.depth_cm);
      } else if (cf === "east") {
        ex.x_cm     = Math.round(D - e.y_cm - e.depth_cm);
        ex.y_cm     = Math.round(e.x_cm);
        ex.width_cm = Math.round(e.depth_cm);
        ex.depth_cm = Math.round(e.width_cm);
      } else if (cf === "west") {
        ex.x_cm     = Math.round(e.y_cm);
        ex.y_cm     = Math.round(W - e.x_cm - e.width_cm);
        ex.width_cm = Math.round(e.depth_cm);
        ex.depth_cm = Math.round(e.width_cm);
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
   *   Doit posséder corridor_face_abs (mémorisé par fromStorage).
   * @param {number} [scale]   - cm/px ; optionnel. Permet de recalculer
   *   offset_px / width_px en cohérence avec offset_cm post-rotation.
   * @returns {Object} roomStorage - Copie profonde en repère absolu.
   *
   * @example
   *   var stored = window.canonicalIO.toStorage(canonRoom, ingState.scale);
   *   // stored.corridor_face === canonRoom.corridor_face_abs || "south"
   */
  function toStorage(roomCanon, scale) {
    var pxPerCm = (typeof scale === "number" && scale > 0) ? (1.0 / scale) : 0;
    var copy = JSON.parse(JSON.stringify(roomCanon));
    var ocf = roomCanon.corridor_face_abs || "";

    // D-122 P2 : bbox_px / seed_px = coords image absolues, jamais rotés.
    // Plus de bbox_abs_px / seed_abs_px à restaurer.

    // Nettoie les champs canoniques (absents du stockage)
    delete copy.corridor_face_abs;
    delete copy.bbox_canon_cm;
    delete copy.surface_m2_bbox;

    // D-204: door_seeds passthrough via deep clone (no rotation —
    // image-absolute coords, not room-local).

    copy.corridor_face = ocf;

    if (!ocf || ocf === "south") {
      (copy.windows  || []).forEach(function (o) { _syncPx(o, pxPerCm); });
      (copy.openings || []).forEach(function (o) { _syncPx(o, pxPerCm); });
      (copy.doors    || []).forEach(function (o) { _syncPx(o, pxPerCm); });
      return copy;
    }

    var invMap = INV_FACE_MAPS[ocf];
    if (!invMap) return copy;

    // Dimensions canoniques (avant swap retour)
    var Wc = roomCanon.width_cm;
    var Dc = roomCanon.depth_cm;
    var swap = (ocf === "east" || ocf === "west");
    if (swap) { copy.width_cm = Dc; copy.depth_cm = Wc; }

    // Transforme en retour une ouverture + sync px
    function xformBack(o) {
      var r = Object.assign({}, o);
      r.face = invMap[o.face] || o.face;
      if (_flipTo(ocf, o.face)) {
        r.offset_cm = _canonLen(o.face, Wc, Dc) - (o.offset_cm || 0) - (o.width_cm || 0);
        if (o.hinge_side) {
          r.hinge_side = (o.hinge_side === "left") ? "right" : "left";
        }
      }
      _syncPx(r, pxPerCm);
      return r;
    }

    copy.windows  = (roomCanon.windows  || []).map(xformBack);
    copy.openings = (roomCanon.openings || []).map(xformBack);
    copy.doors    = (roomCanon.doors    || []).map(xformBack);

    // Transforme en retour une zone
    function xformZoneBack(e) {
      var ex = Object.assign({}, e);
      if (ocf === "north") {
        ex.x_cm = Math.round(Wc - e.x_cm - e.width_cm);
        ex.y_cm = Math.round(Dc - e.y_cm - e.depth_cm);
      } else if (ocf === "east") {
        ex.x_cm     = Math.round(e.y_cm);
        ex.y_cm     = Math.round(Wc - e.x_cm - e.width_cm);
        ex.width_cm = Math.round(e.depth_cm);
        ex.depth_cm = Math.round(e.width_cm);
      } else if (ocf === "west") {
        ex.x_cm     = Math.round(Dc - e.y_cm - e.depth_cm);
        ex.y_cm     = Math.round(e.x_cm);
        ex.width_cm = Math.round(e.depth_cm);
        ex.depth_cm = Math.round(e.width_cm);
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
    // scale = cm/px ; pxPerCm = 1/scale = 2 ⇒ 100 cm = 200 px.
    var SCALE = 0.5;
    var SAMPLES = [
      {
        name: "T1-south",
        room: {
          name: "T1", corridor_face: "south", width_cm: 300, depth_cm: 500,
          bbox_px: [100, 200, 160, 300], seed_px: [130, 250],
          windows:  [{ face: "north", offset_cm: 50,  width_cm: 120, offset_px: 100, width_px: 240, origin: "manual" }],
          openings: [{ face: "south", offset_cm: 80,  width_cm: 90,  offset_px: 160, width_px: 180, origin: "auto" }],
          doors:    [{ face: "east",  offset_cm: 100, width_cm: 80,  offset_px: 200, width_px: 160, hinge_side: "left", origin: "manual" }],
          exclusion_zones: [{ x_cm: 10, y_cm: 20, width_cm: 50, depth_cm: 60 }],
        },
      },
      {
        name: "T2-north",
        room: {
          name: "T2", corridor_face: "north", width_cm: 400, depth_cm: 600,
          bbox_px: [200, 300, 280, 420], seed_px: [240, 360],
          windows:  [{ face: "north", offset_cm: 30, width_cm: 150, offset_px: 60,  width_px: 300 }],
          openings: [{ face: "west",  offset_cm: 20, width_cm: 100, offset_px: 40,  width_px: 200 }],
          doors:    [{ face: "south", offset_cm: 50, width_cm: 80,  offset_px: 100, width_px: 160, hinge_side: "right" }],
          exclusion_zones: [{ x_cm: 5, y_cm: 10, width_cm: 40, depth_cm: 70 }],
          transparent_zones: [{ x_cm: 100, y_cm: 200, width_cm: 60, depth_cm: 80 }],
        },
      },
      {
        name: "T3-east",
        room: {
          name: "T3", corridor_face: "east", width_cm: 250, depth_cm: 700,
          bbox_px: [50, 80, 120, 290], seed_px: [85, 185],
          windows:  [{ face: "east",  offset_cm: 60,  width_cm: 110, offset_px: 120, width_px: 220 }],
          openings: [{ face: "south", offset_cm: 40,  width_cm: 90,  offset_px: 80,  width_px: 180 }],
          doors:    [{ face: "north", offset_cm: 20,  width_cm: 80,  offset_px: 40,  width_px: 160, hinge_side: "left" }],
          exclusion_zones: [{ x_cm: 15, y_cm: 25, width_cm: 80, depth_cm: 100 }],
        },
      },
      {
        name: "T4-west",
        room: {
          name: "T4", corridor_face: "west", width_cm: 350, depth_cm: 550,
          bbox_px: [300, 100, 380, 265], seed_px: [340, 180],
          windows:  [{ face: "west",  offset_cm: 70,  width_cm: 130, offset_px: 140, width_px: 260 }],
          openings: [{ face: "north", offset_cm: 30,  width_cm: 95,  offset_px: 60,  width_px: 190 }],
          doors:    [{ face: "east",  offset_cm: 45,  width_cm: 80,  offset_px: 90,  width_px: 160, hinge_side: "right" }],
          exclusion_zones: [{ x_cm: 20, y_cm: 30, width_cm: 70, depth_cm: 90 }],
        },
      },
    ];

    var allOk = true;

    SAMPLES.forEach(function (s) {
      var canon   = fromStorage(s.room, SCALE);
      var storage = toStorage(canon,    SCALE);
      var diff    = _deepDiff(s.room, storage, "");
      if (diff.length === 0) {
        console.log("[canonical_io] OK — round-trip " + s.name);
      } else {
        allOk = false;
        console.error("[canonical_io] DIFF — round-trip " + s.name, diff);
      }
    });

    // Tests auxiliaires rotatePoint / rotateRect (D-122 P6) ────────────────
    var W = 300, D = 500;
    var POINT_CASES = [
      { cf: "south", pt: { x: 30, y: 40 }, exp: { x: 30, y: 40 } },
      { cf: "north", pt: { x: 30, y: 40 }, exp: { x: W - 30, y: D - 40 } },
      { cf: "east",  pt: { x: 30, y: 40 }, exp: { x: D - 40,  y: 30      } },
      { cf: "west",  pt: { x: 30, y: 40 }, exp: { x: 40,      y: W - 30 } },
    ];
    POINT_CASES.forEach(function (c) {
      var r = rotatePoint(c.pt, c.cf, W, D);
      if (r.x === c.exp.x && r.y === c.exp.y) {
        console.log("[canonical_io] OK — rotatePoint " + c.cf);
      } else {
        allOk = false;
        console.error("[canonical_io] FAIL — rotatePoint " + c.cf,
          "got", r, "expected", c.exp);
      }
    });
    var RECT = { x: 10, y: 20, width: 50, depth: 60 };
    var RECT_CASES = [
      { cf: "south", exp: { x: 10, y: 20, width: 50, depth: 60 } },
      { cf: "north", exp: { x: W - 10 - 50, y: D - 20 - 60, width: 50, depth: 60 } },
      { cf: "east",  exp: { x: D - 20 - 60, y: 10, width: 60, depth: 50 } },
      { cf: "west",  exp: { x: 20, y: W - 10 - 50, width: 60, depth: 50 } },
    ];
    RECT_CASES.forEach(function (c) {
      var r = rotateRect(RECT, c.cf, W, D);
      var ok = (r.x === c.exp.x && r.y === c.exp.y &&
                r.width === c.exp.width && r.depth === c.exp.depth);
      if (ok) {
        console.log("[canonical_io] OK — rotateRect " + c.cf);
      } else {
        allOk = false;
        console.error("[canonical_io] FAIL — rotateRect " + c.cf,
          "got", r, "expected", c.exp);
      }
    });
    // rotateRectInv : round-trip rotateRect ∘ rotateRectInv ≡ identity.
    ["south", "north", "east", "west"].forEach(function (cf) {
      var fwd = rotateRect(RECT, cf, W, D);
      var back = rotateRectInv(fwd, cf, W, D);
      var ok = (back.x === RECT.x && back.y === RECT.y &&
                back.width === RECT.width && back.depth === RECT.depth);
      if (ok) {
        console.log("[canonical_io] OK — rotateRectInv " + cf);
      } else {
        allOk = false;
        console.error("[canonical_io] FAIL — rotateRectInv " + cf,
          "got", back, "expected", RECT);
      }
    });
    // canonAngle (D-134 P6) : convention overlay SVG rotate.
    var ANGLE_CASES = [
      { cf: "",      exp: 0   },
      { cf: "south", exp: 0   },
      { cf: "east",  exp: 90  },
      { cf: "north", exp: 180 },
      { cf: "west",  exp: 270 },
    ];
    ANGLE_CASES.forEach(function (c) {
      var got = canonAngle(c.cf);
      if (got === c.exp) {
        console.log("[canonical_io] OK — canonAngle " + (c.cf || "<empty>"));
      } else {
        allOk = false;
        console.error("[canonical_io] FAIL — canonAngle " + c.cf,
          "got", got, "expected", c.exp);
      }
    });

    // D-135 : walls_user_edited traverse fromStorage / toStorage sans
    // altération (champ booléen non géométrique). Aucune rotation, aucune
    // suppression dans le delete-chain (corridor_face_abs / bbox_canon_cm /
    // surface_m2_bbox uniquement).
    var WUE_CASES = [
      { label: "true-south",  cf: "south", wue: true },
      { label: "false-south", cf: "south", wue: false },
      { label: "true-north",  cf: "north", wue: true },
      { label: "true-east",   cf: "east",  wue: true },
      { label: "true-west",   cf: "west",  wue: true },
      { label: "absent-south", cf: "south", wue: undefined },
    ];
    WUE_CASES.forEach(function (c) {
      var room = {
        name: "WUE-" + c.label, corridor_face: c.cf,
        width_cm: 300, depth_cm: 400,
        bbox_px: [0, 0, 60, 80], seed_px: [30, 40],
      };
      if (c.wue !== undefined) room.walls_user_edited = c.wue;
      var canon = fromStorage(room, SCALE);
      var back = toStorage(canon, SCALE);
      var expectCanon = c.wue;
      var expectBack = c.wue;
      var canonOk = canon.walls_user_edited === expectCanon;
      var backOk = back.walls_user_edited === expectBack;
      if (canonOk && backOk) {
        console.log("[canonical_io] OK — walls_user_edited " + c.label);
      } else {
        allOk = false;
        console.error("[canonical_io] FAIL — walls_user_edited " + c.label,
          "canon=", canon.walls_user_edited,
          "back=", back.walls_user_edited,
          "expected=", expectCanon);
      }
    });

    // Canonical offset intermediate values — T3-east door on north abs face.
    // cf_abs="east", door face="north" offset=20 width=80 hinge=left.
    // 90° CW: north(h) → east(v), offset preserved (no flip).
    var t3c = fromStorage(SAMPLES[2].room, SCALE);
    var t3d = t3c.doors[0];
    if (t3d.face === "east" && t3d.offset_cm === 20 && t3d.hinge_side === "left") {
      console.log("[canonical_io] OK — T3-east door canon offset preserved");
    } else {
      allOk = false;
      console.error("[canonical_io] FAIL — T3-east door canon offset",
        "face=" + t3d.face, "offset=" + t3d.offset_cm, "hinge=" + t3d.hinge_side,
        "expected face=east offset=20 hinge=left");
    }
    // T3-east window on east abs face: east(v) → south, offset FLIPPED.
    var t3w = t3c.windows[0];
    var t3wExpOff = 700 - 60 - 110;  // D - offset - width = 530
    if (t3w.face === "south" && t3w.offset_cm === t3wExpOff) {
      console.log("[canonical_io] OK — T3-east window canon offset flipped");
    } else {
      allOk = false;
      console.error("[canonical_io] FAIL — T3-east window canon offset",
        "face=" + t3w.face, "offset=" + t3w.offset_cm,
        "expected face=south offset=" + t3wExpOff);
    }
    // T4-west window on west abs face: west(v), CCW → no flip.
    var t4c = fromStorage(SAMPLES[3].room, SCALE);
    var t4w = t4c.windows[0];
    if (t4w.face === "south" && t4w.offset_cm === 70) {
      console.log("[canonical_io] OK — T4-west window canon offset preserved");
    } else {
      allOk = false;
      console.error("[canonical_io] FAIL — T4-west window canon offset",
        "face=" + t4w.face, "offset=" + t4w.offset_cm,
        "expected face=south offset=70");
    }
    // T4-west opening on north abs face: north(h), CCW → FLIP.
    var t4o = t4c.openings[0];
    var t4oExpOff = 350 - 30 - 95;  // W - offset - width = 225
    if (t4o.face === "west" && t4o.offset_cm === t4oExpOff) {
      console.log("[canonical_io] OK — T4-west opening canon offset flipped");
    } else {
      allOk = false;
      console.error("[canonical_io] FAIL — T4-west opening canon offset",
        "face=" + t4o.face, "offset=" + t4o.offset_cm,
        "expected face=west offset=" + t4oExpOff);
    }

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
    fromStorage:    fromStorage,
    toStorage:      toStorage,
    rotateDir:      rotateDir,
    rotateDirInv:   rotateDirInv,
    rotatePoint:    rotatePoint,
    rotatePointInv: rotatePointInv,
    rotateRect:     rotateRect,
    rotateRectInv:  rotateRectInv,
    canonAngle:     canonAngle,
    FACE_MAPS:      FACE_MAPS,
    INV_FACE_MAPS:  INV_FACE_MAPS,
    _flipFrom:      _flipFrom,
    _flipTo:        _flipTo,
  };

  if (window.RUN_CANONICAL_IO_TESTS) {
    _runTests();
  }

}());
