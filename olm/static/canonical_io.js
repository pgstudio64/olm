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
  function rotatePoint(pt, cfAbs, absW, absD) {
    var x = pt.x, y = pt.y;
    if (cfAbs === "north") return { x: absW - x, y: absD - y };
    if (cfAbs === "east")  return { x: y,        y: absW - x };
    if (cfAbs === "west")  return { x: absD - y, y: x         };
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
    if (cfAbs === "east")  return { x: y,            y: absW - x - w, width: d, depth: w };
    if (cfAbs === "west")  return { x: absD - y - d, y: x,             width: d, depth: w };
    return { x: x, y: y, width: w, depth: d };
  }

  /**
   * Angle SVG (degrés, sens SVG rotate positif) pour mettre une pièce en
   * repère canonique (corridor sud). cfAbs = corridor_face absolu.
   *
   * Convention dérivée du rendu overlay actuel (D-83 / éditeur.js) :
   *   south → 0, east → 90, north → 180, west → 270.
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
    if (cfAbs === "east")  return { x: absW - yc - dc, y: xc,             width: dc, depth: wc };
    if (cfAbs === "west")  return { x: yc,             y: absD - xc - wc, width: dc, depth: wc };
    return { x: xc, y: yc, width: wc, depth: dc };
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
      if (cf === "north" || cf === "west") {
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
      if (ocf === "north" || ocf === "west") {
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
      { cf: "east",  pt: { x: 30, y: 40 }, exp: { x: 40,      y: W - 30 } },
      { cf: "west",  pt: { x: 30, y: 40 }, exp: { x: D - 40,  y: 30      } },
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
      { cf: "east",  exp: { x: 20, y: W - 10 - 50, width: 60, depth: 50 } },
      { cf: "west",  exp: { x: D - 20 - 60, y: 10, width: 60, depth: 50 } },
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
    rotatePoint:    rotatePoint,
    rotateRect:     rotateRect,
    rotateRectInv:  rotateRectInv,
    canonAngle:     canonAngle,
    FACE_MAPS:      FACE_MAPS,
    INV_FACE_MAPS:  INV_FACE_MAPS,
  };

  if (window.RUN_CANONICAL_IO_TESTS) {
    _runTests();
  }

}());
