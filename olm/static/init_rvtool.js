"use strict";
// ========================================================================
// RV-TOOL — forbidden-zone interaction for the Review amend mode (D-94 P3)
// ========================================================================
//
// Extracted from init.js. Self-contained: depends only on globals already
// exposed by editor.js (`state`, `SCALE`, `GRID_STEP_CM`, `render()`).
// Exposes `window.rvTool` and `window.rvRemoveGhostRect` for the amend
// save/cancel flow in init.js.
// ========================================================================

(function () {
  document.addEventListener("DOMContentLoaded", function () {
    var rvTool = { mode: "idle", drawStart: null, selectedIndex: -1, dragOffset: null };
    window.rvTool = rvTool;

    var _rvGhostRect = null;

    function rvScreenToRoomCm(evt, customSnapCm) {
      var svg = document.getElementById("rvCanvas");
      var pt = svg.createSVGPoint();
      pt.x = evt.clientX;
      pt.y = evt.clientY;
      var svgPt = pt.matrixTransform(svg.getScreenCTM().inverse());
      var snap = (typeof customSnapCm === "number" && customSnapCm > 0) ? customSnapCm : GRID_STEP_CM;
      return {
        x_cm: Math.round(svgPt.x / SCALE / snap) * snap,
        y_cm: Math.round(svgPt.y / SCALE / snap) * snap,
      };
    }
    // D-99: finer snap (5 cm) for room position handles.
    var ROOM_RESIZE_SNAP_CM = 5;

    async function rvApplyDslAsync() {
      var text = document.getElementById("rvRoomDsl").value.trim();
      if (!text) return;
      try {
        var resp = await fetch("/api/room-dsl/parse", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ dsl: text }),
        });
        if (!resp.ok) return;
        var data = await resp.json();
        state.room_width_cm = data.width_cm;
        state.room_depth_cm = data.depth_cm;
        state.room_windows = data.windows || [];
        // D-122 P4 : DSL backend retourne openings combiné (has_door) → split.
        _splitOpeningsIntoState(data.openings);
        state.room_exclusions = data.exclusion_zones || [];
        state.room_transparents = data.transparent_zones || [];
        render(document.getElementById("rvCanvas"));
        if (window.rvUpdateRoomInfo) window.rvUpdateRoomInfo();
      } catch (err) { console.error("rvApplyDslAsync:", err); }
    }

    function rvDslAppendExcl(x_cm, y_cm, w_cm, h_cm) {
      var el = document.getElementById("rvRoomDsl");
      var line = "EXCLUSION " + x_cm + " " + y_cm + " " + w_cm + " " + h_cm;
      el.value = el.value.trimEnd() + "\n" + line;
    }
    function rvDslAppendTransparent(x_cm, y_cm, w_cm, h_cm) {
      var el = document.getElementById("rvRoomDsl");
      var line = "TRANSPARENT " + x_cm + " " + y_cm + " " + w_cm + " " + h_cm;
      el.value = el.value.trimEnd() + "\n" + line;
    }

    function rvDslReplaceExcl(index, x_cm, y_cm, w_cm, h_cm) {
      var el = document.getElementById("rvRoomDsl");
      var lines = el.value.split("\n");
      var count = 0;
      for (var i = 0; i < lines.length; i++) {
        if (/^\s*EXCLUSION\b/i.test(lines[i])) {
          if (count === index) {
            lines[i] = "EXCLUSION " + x_cm + " " + y_cm + " " + w_cm + " " + h_cm;
            el.value = lines.join("\n");
            return;
          }
          count++;
        }
      }
    }

    function rvDslDeleteExcl(index) {
      var el = document.getElementById("rvRoomDsl");
      var lines = el.value.split("\n");
      var count = 0;
      for (var i = 0; i < lines.length; i++) {
        if (/^\s*EXCLUSION\b/i.test(lines[i])) {
          if (count === index) {
            lines.splice(i, 1);
            el.value = lines.join("\n");
            return;
          }
          count++;
        }
      }
    }

    function rvShowGhostRect(x_svg, y_svg, w_svg, h_svg) {
      var svg = document.getElementById("rvCanvas");
      if (!_rvGhostRect) {
        _rvGhostRect = document.createElementNS("http://www.w3.org/2000/svg", "rect");
        _rvGhostRect.setAttribute("fill", "none");
        _rvGhostRect.setAttribute("stroke", "#2a9d8f");
        _rvGhostRect.setAttribute("stroke-width", "1");
        _rvGhostRect.setAttribute("stroke-dasharray", "4 4");
        _rvGhostRect.setAttribute("pointer-events", "none");
      }
      _rvGhostRect.setAttribute("x", x_svg);
      _rvGhostRect.setAttribute("y", y_svg);
      _rvGhostRect.setAttribute("width", w_svg);
      _rvGhostRect.setAttribute("height", h_svg);
      svg.appendChild(_rvGhostRect);
    }

    function rvRemoveGhostRect() {
      if (_rvGhostRect && _rvGhostRect.parentNode) {
        _rvGhostRect.parentNode.removeChild(_rvGhostRect);
      }
      _rvGhostRect = null;
    }
    window.rvRemoveGhostRect = rvRemoveGhostRect;

    // Clamp windows/openings/doors/exclusions that overflow the current
    // room bounds (after a shrink-direction resize). Width of a feature is
    // preserved; its offset is nudged inward; if the feature is wider than
    // the wall, width is shrunk too.
    function _clampContentsToRoom() {
      var W = state.room_width_cm || 0;
      var D = state.room_depth_cm || 0;
      function clampFeature(f) {
        var wallLen = (f.face === "north" || f.face === "south") ? W : D;
        var w = Math.min(f.width_cm || 0, wallLen);
        var off = Math.max(0, Math.min(wallLen - w, f.offset_cm || 0));
        f.width_cm = w;
        f.offset_cm = off;
      }
      (state.room_windows || []).forEach(clampFeature);
      (state.room_openings || []).forEach(clampFeature);
      (state.room_doors || []).forEach(clampFeature);
      (state.room_exclusions || []).forEach(function (z) {
        z.x_cm = Math.max(0, z.x_cm || 0);
        z.y_cm = Math.max(0, z.y_cm || 0);
        z.width_cm = Math.min(z.width_cm || 0, W - z.x_cm);
        z.depth_cm = Math.min(z.depth_cm || 0, D - z.y_cm);
        if (z.width_cm < 0) z.width_cm = 0;
        if (z.depth_cm < 0) z.depth_cm = 0;
      });
    }

    // Regenerate the full Room DSL from the current `state.room_*` arrays.
    // Mirrors the DSL construction in floor_plan.js rvRenderCurrent.
    function _stateToDsl() {
      var W = state.room_width_cm || 0;
      var D = state.room_depth_cm || 0;
      var dsl = "ROOM " + W + "x" + D;
      var FACE = { north: "N", south: "S", east: "E", west: "W" };
      (state.room_windows || []).forEach(function (w) {
        var f = FACE[w.face] || w.face || "?";
        var wallLen = (f === "N" || f === "S") ? W : D;
        if ((w.offset_cm || 0) === 0 && w.width_cm === wallLen) {
          dsl += "\nWINDOW " + f;
        } else {
          dsl += "\nWINDOW " + f + " " + (w.offset_cm || 0) + " " + (w.width_cm || 0);
        }
      });
      // D-122 P4 : openings ne contient plus de doors (collections séparées).
      (state.room_openings || []).forEach(function (o) {
        var f = FACE[o.face] || o.face || "?";
        dsl += "\nOPENING " + f + " " + (o.offset_cm || 0) + " " + (o.width_cm || 90);
      });
      (state.room_doors || []).forEach(function (d) {
        var f = FACE[d.face] || d.face || "?";
        var dir = d.opens_inward !== false ? "INT" : "EXT";
        var side = (d.hinge_side === "left") ? "L" : "R";
        dsl += "\nDOOR " + f + " " + (d.offset_cm || 0) + " " + (d.width_cm || 90) + " " + dir + " " + side;
      });
      (state.room_exclusions || []).forEach(function (z) {
        dsl += "\nEXCLUSION " + (z.x_cm || 0) + " " + (z.y_cm || 0) +
          " " + (z.width_cm || 0) + " " + (z.depth_cm || 0);
      });
      (state.room_transparents || []).forEach(function (z) {
        dsl += "\nTRANSPARENT " + (z.x_cm || 0) + " " + (z.y_cm || 0) +
          " " + (z.width_cm || 0) + " " + (z.depth_cm || 0);
      });
      return dsl;
    }

    var rvCvEl = document.getElementById("rvCanvas");
    if (!rvCvEl) return;

    // --- Opening placement buttons (Add Window / Door / Opening) ---
    // Click a button → enter placingOpening mode; next click on a wall
    // inserts the opening at that position.
    var WALL_SNAP_CM = 10;
    function _nearestFaceAndOffset(x_cm, y_cm) {
      var W = state.room_width_cm, D = state.room_depth_cm;
      // Distance to each wall (clamped pt inside room).
      var cx = Math.max(0, Math.min(W, x_cm));
      var cy = Math.max(0, Math.min(D, y_cm));
      var dN = cy, dS = D - cy, dW = cx, dE = W - cx;
      var m = Math.min(dN, dS, dW, dE);
      if (m === dN) return { face: "north", offset_cm: cx };
      if (m === dS) return { face: "south", offset_cm: cx };
      if (m === dW) return { face: "west", offset_cm: cy };
      return { face: "east", offset_cm: cy };
    }
    function _setPlacingOpening(type, btn) {
      var ids = ["rvBtnAddWindow", "rvBtnAddDoor", "rvBtnAddOpening"];
      ids.forEach(function (id) {
        var b = document.getElementById(id);
        if (b) b.classList.remove("active");
      });
      if (rvTool.mode === "placingOpening" && rvTool.placingOpeningType === type) {
        rvTool.mode = "idle";
        rvTool.placingOpeningType = null;
        rvCvEl.style.cursor = "";
        return;
      }
      rvTool.mode = "placingOpening";
      rvTool.placingOpeningType = type;
      if (btn) btn.classList.add("active");
      rvCvEl.style.cursor = "crosshair";
    }
    ([
      ["rvBtnAddWindow", "window"],
      ["rvBtnAddDoor", "door"],
      ["rvBtnAddOpening", "opening"],
    ]).forEach(function (entry) {
      var el = document.getElementById(entry[0]);
      if (el) {
        el.addEventListener("click", function () {
          if (!state.roomAmendMode) return;
          _setPlacingOpening(entry[1], el);
        });
      }
    });

    // --- V-Rays / H-Rays toggles ---
    ([
      ["rvVraysToggle", "showVrays"],
      ["rvHraysToggle", "showHrays"],
    ]).forEach(function (entry) {
      var cb = document.getElementById(entry[0]);
      if (cb) {
        cb.addEventListener("change", function () {
          state[entry[1]] = cb.checked;
          render(document.getElementById("rvCanvas"));
        });
      }
    });

    // --- Check orientation button (R-13 / D-119) ---
    var checkBtn = document.getElementById("rvBtnCheckOrient");
    var badge = document.getElementById("rvOrientBadge");
    if (checkBtn && badge) {
      checkBtn.addEventListener("click", async function () {
        if (!state.roomAmendMode) return;
        var ingst = window.ingState || {};
        var orig = state.roomAmendMode.originalRoom || {};
        var bbox = orig.bbox_px;
        if (!bbox || !ingst.planPathEnhanced) {
          alert("Orientation check: missing bbox or plan path.");
          return;
        }
        badge.style.display = "";
        badge.textContent = "Checking…";
        badge.style.background = "var(--surface2)";
        badge.style.color = "var(--text-dim)";
        try {
          var resp = await fetch("/api/room/orientation-check", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              plan_path: ingst.planPathEnhanced,
              bbox_px: bbox,
              corridor_face_abs: orig.corridor_face_abs || "",
            }),
          });
          var data = await resp.json();
          if (data.error) throw new Error(data.error);
          var gs = data.corridor_south || {};
          var gn = data.exterior_north || {};
          var ok = gs.ok;
          var rg = (gs.ratio_green || 0).toFixed(2);
          var rb = (gn.ratio_blue || 0).toFixed(2);
          badge.textContent = (ok ? "OK" : "WARN") +
            " — corridor south " + rg + "g · exterior north " + rb + "b";
          badge.style.background = ok ? "#2a4d2a" : "#7a3a1a";
          badge.style.color = "#fff";
          badge.title = "ocf=" + (data.corridor_face_abs || "-") +
            "\nFaces canon → ratio green / blue:\n" +
            Object.entries(data.faces || {}).map(function (e) {
              return "  " + e[0] + " (abs " + e[1].face_abs + "): " +
                e[1].ratio_green.toFixed(2) + "g " +
                e[1].ratio_blue.toFixed(2) + "b";
            }).join("\n");
        } catch (err) {
          badge.textContent = "Error: " + err.message;
          badge.style.background = "#7a1a1a";
          badge.style.color = "#fff";
        }
      });
    }

    // --- Re-analyze button (R-04 Review) ---
    var reanalyzeBtn = document.getElementById("rvBtnReanalyze");
    if (reanalyzeBtn) {
      reanalyzeBtn.addEventListener("click", async function () {
        if (!state.roomAmendMode) return;
        var ingst = window.ingState || {};
        var amend = state.roomAmendMode;
        var origRoom = amend.originalRoom || {};
        var bbox = origRoom.bbox_px;
        var seedPx = origRoom.seed_px || origRoom.seed ||
          (origRoom.seed_x != null && origRoom.seed_y != null
            ? [origRoom.seed_x, origRoom.seed_y] : null);
        if (!seedPx || !ingst.planPathEnhanced || !ingst.scale) {
          alert("Re-analyze unavailable: missing plan path, seed, or scale.");
          return;
        }
        // Backend /api/room/reanalyze interprète transparent_zones en
        // abs-room-local ; le state les porte en canonique. Conversion
        // canon → abs via rotateRectInv (identité si corridor_face_abs
        // ∈ {"", "south"}).
        var cfAbsForZones = amend.originalRoom.corridor_face_abs ||
          state.corridor_face_abs || "";
        var absWForZones = bbox ? (bbox[2] - bbox[0]) * ingst.scale : 0;
        var absDForZones = bbox ? (bbox[3] - bbox[1]) * ingst.scale : 0;
        var transparents = window.canonicalZonesToAbs
          ? window.canonicalZonesToAbs(
              state.room_transparents || [],
              cfAbsForZones, absWForZones, absDForZones)
          : (state.room_transparents || []).map(function (z) {
              return {
                x_cm: z.x_cm, y_cm: z.y_cm,
                width_cm: z.width_cm, depth_cm: z.depth_cm,
              };
            });
        // Re-analyze = redétection complète : on ne préserve PAS les
        // anciennes portes (sinon leurs masques empêchent la détection
        // de fraîches portes via l'arc).
        var doorsPx = [];
        var doorWidthCm = ((window.APP_CONFIG || {}).default_door_width_cm) || 90;
        reanalyzeBtn.disabled = true;
        reanalyzeBtn.textContent = "Analyzing...";
        try {
          var resp = await fetch("/api/room/reanalyze", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              plan_path: ingst.planPathEnhanced,
              seed_px: seedPx,
              bbox_px: bbox,
              scale_cm_per_px: ingst.scale,
              transparent_zones: transparents,
              doors: doorsPx,
              door_width_cm: doorWidthCm,
            }),
          });
          if (!resp.ok) throw new Error("HTTP " + resp.status);
          var data = await resp.json();
          if (data.error) throw new Error(data.error);

          // Merge : on conserve tous les manuels, on remplace les auto par
          // les nouveaux résultats, en filtrant ceux dont la signature est
          // dans deleted_auto_signatures. La canonicalisation abs → canon
          // (D-112) et la mise à jour de corridor_face (D-113) sont
          // factorisées dans computeCanonicalReanalyzeResult (ingestion.js).
          var deleted = new Set(state.deleted_auto_signatures || []);
          function sig(type, e) {
            return type + "|" + e.face + "|" +
              (e.offset_cm || 0) + "|" + (e.width_cm || 0);
          }
          // D-122 P4 : openings et doors séparés dans le state → plus de
          // filtrage has_door, chaque collection a son propre filter.
          var manualW = (state.room_windows || []).filter(function (w) {
            return w.origin === "manual";
          });
          var manualO = (state.room_openings || []).filter(function (o) {
            return o.origin === "manual";
          });
          // D-110 fix : ne préserver QUE les doors explicitement "manual".
          var preservedDoors = (state.room_doors || []).filter(function (d) {
            return d.origin === "manual";
          });

          // R-12 / D-122 P3 : le helper travaille en repère ABSOLU
          // (entrée backend). prevCf doit donc être le corridor_face
          // absolu mémorisé (corridor_face_abs).
          var prevCf = (amend.originalRoom &&
            amend.originalRoom.corridor_face_abs) || "";
          var canon = window.computeCanonicalReanalyzeResult(
            data, prevCf, ingst.scale || 0);

          // D-126 : toggle "Lock bbox" — quand coché, la géométrie
          // (bbox_px, dims, corridor_face_abs, overlay) reste figée ;
          // seuls openings / windows / doors / hits sont adoptés.
          var lockBboxEl = document.getElementById("rvLockBbox");
          var lockBbox = !!(lockBboxEl && lockBboxEl.checked);

          if (canon.corridor_face && !lockBbox) {
            // D-113 + R-12 : la porte détectée met à jour le repère
            // absolu mémorisé. corridor_face_abs seul — corridor_face
            // "south" est une constante implicite du repère canon.
            amend.originalRoom.corridor_face_abs = canon.corridor_face;
            state.corridor_face_abs = canon.corridor_face;
          }
          var newWindows = canon.windows.filter(function (w) {
            return !deleted.has(sig("window", w));
          });
          var newOpenings = canon.openings.filter(function (o) {
            return !deleted.has(sig("opening", o));
          });
          var newDoors = preservedDoors.length ? [] : canon.doors;

          if (canon.hits) state.room_hits = canon.hits;
          if (canon.seed_cm) state.room_seed_cm = canon.seed_cm;
          if (canon.auto_door_masks) state.room_auto_door_masks = canon.auto_door_masks;

          if (canon.bbox_px && ingst.scale && !lockBbox) {
            if (canon.width_cm > 0 && canon.depth_cm > 0) {
              state.room_width_cm = canon.width_cm;
              state.room_depth_cm = canon.depth_cm;
            }
            // Re-anchor zones to preserve their absolute image position
            // across bbox / corridor_face changes (fix symptôme 2 D-124).
            if (window.reanchorCanonicalZones) {
              var newCf = canon.corridor_face || prevCf || "";
              state.room_exclusions = window.reanchorCanonicalZones(
                state.room_exclusions, bbox, prevCf,
                canon.bbox_px, newCf, ingst.scale);
              state.room_transparents = window.reanchorCanonicalZones(
                state.room_transparents, bbox, prevCf,
                canon.bbox_px, newCf, ingst.scale);
            }
            amend.originalRoom.bbox_px = canon.bbox_px;
            amend.originalRoom.width_cm = canon.width_cm;
            amend.originalRoom.depth_cm = canon.depth_cm;
            amend.originalRoom.surface_m2_bbox = parseFloat(
              ((canon.width_cm * canon.depth_cm) / 10000).toFixed(2));
            if (window.fpOverlay && state.overlay) {
              var ov2 = window.fpOverlay;
              state.overlay.offsetX = canon.bbox_px[0] / ov2.pxPerCm;
              state.overlay.offsetY = canon.bbox_px[1] / ov2.pxPerCm;
            }
          }

          state.room_windows = newWindows.concat(manualW);
          state.room_openings = newOpenings.concat(manualO);
          state.room_doors = newDoors.concat(preservedDoors);
          _rvCommitFromState();
          if (window.rvUpdateRoomInfo) window.rvUpdateRoomInfo();
        } catch (err) {
          alert("Re-analyze failed: " + err.message);
        } finally {
          reanalyzeBtn.disabled = false;
          reanalyzeBtn.textContent = "Re-analyze";
        }
      });
    }

    // --- Unified "+ Add" dropdown menu (Phase C) ---
    var addMenuBtn = document.getElementById("rvAddMenuBtn");
    var addMenu = document.getElementById("rvAddMenu");
    if (addMenuBtn && addMenu) {
      addMenuBtn.addEventListener("click", function (e) {
        e.stopPropagation();
        addMenu.style.display = addMenu.style.display === "none" ? "" : "none";
      });
      document.addEventListener("click", function (e) {
        var wrap = document.getElementById("rvAddMenuWrap");
        if (wrap && !wrap.contains(e.target)) addMenu.style.display = "none";
      });
      addMenu.querySelectorAll(".rv-add-item").forEach(function (el) {
        el.addEventListener("mouseover", function () {
          this.style.background = "var(--surface2)";
        });
        el.addEventListener("mouseout", function () {
          this.style.background = "";
        });
        el.addEventListener("click", function () {
          addMenu.style.display = "none";
          if (!state.roomAmendMode) return;
          var kind = this.dataset.add;
          if (kind === "window" || kind === "door" || kind === "opening") {
            _setPlacingOpening(kind, null);
          } else if (kind === "exclusion") {
            rvTool.mode = "placing";
            rvTool.selectedIndex = -1;
            state.selectedExclusion = -1;
            rvCvEl.style.cursor = "crosshair";
            rvTool.placingZoneKind = "exclusion";
            render(rvCvEl);
          } else if (kind === "transparent") {
            rvTool.mode = "placing";
            rvTool.selectedIndex = -1;
            state.selectedExclusion = -1;
            rvCvEl.style.cursor = "crosshair";
            rvTool.placingZoneKind = "transparent";
            render(rvCvEl);
          }
        });
      });
    }

    // Button toggle: placing mode on/off
    var rvBtnAddExclEl = document.getElementById("rvBtnAddExcl");
    if (rvBtnAddExclEl) {
      rvBtnAddExclEl.addEventListener("click", function () {
        if (!state.roomAmendMode) return;
        if (rvTool.mode === "placing") {
          rvTool.mode = "idle";
          rvBtnAddExclEl.classList.remove("active");
          rvCvEl.style.cursor = "";
        } else {
          rvTool.mode = "placing";
          rvTool.selectedIndex = -1;
          state.selectedExclusion = -1;
          rvBtnAddExclEl.classList.add("active");
          rvCvEl.style.cursor = "crosshair";
          render(rvCvEl);
        }
      });
    }

    // Helper: rebuild full Room DSL from state and push to backend.
    // Preserves `origin` across the DSL round-trip by caching per
    // (type, face, offset, width) key — the DSL serializes these 3 values
    // exactly, so the cache key is stable.
    function _rvCommitFromState() {
      var originCache = {};
      function _keyFor(kind, e) {
        return kind + "|" + e.face + "|" + (e.offset_cm || 0) +
          "|" + (e.width_cm || 0);
      }
      (state.room_windows || []).forEach(function (w) {
        if (w.origin) originCache[_keyFor("w", w)] = w.origin;
      });
      (state.room_openings || []).forEach(function (o) {
        if (o.origin) originCache[_keyFor("o", o)] = o.origin;
      });
      (state.room_doors || []).forEach(function (d) {
        if (d.origin) originCache[_keyFor("d", d)] = d.origin;
      });
      var el = document.getElementById("rvRoomDsl");
      if (el) el.value = _stateToDsl();
      rvApplyDslAsync().then(function () {
        (state.room_windows || []).forEach(function (w) {
          var k = _keyFor("w", w);
          if (originCache[k]) w.origin = originCache[k];
          else if (!w.origin) w.origin = "auto";
        });
        (state.room_openings || []).forEach(function (o) {
          var k = _keyFor("o", o);
          if (originCache[k]) o.origin = originCache[k];
          else if (!o.origin) o.origin = "auto";
        });
        (state.room_doors || []).forEach(function (d) {
          var k = _keyFor("d", d);
          if (originCache[k]) d.origin = originCache[k];
          else if (!d.origin) d.origin = "auto";
        });
      });
    }

    // rvCanvas mousedown: start drawing, drag, or resize
    rvCvEl.addEventListener("mousedown", function (e) {
      if (!state.roomAmendMode) return;
      if (e.button !== 0) return;

      var openingDelete = e.target.closest("[data-opening-delete]");
      var openingResize = e.target.closest("[data-opening-resize]");
      var openingHandle = e.target.closest("[data-opening-handle]");
      var roomHandleTarget = e.target.closest("[data-room-handle]");
      var handleTarget = e.target.closest("[data-excl-handle]");
      var exclTarget = e.target.closest("[data-excl]");
      var transpHandleTarget = e.target.closest("[data-transp-handle]");
      var transpTarget = e.target.closest("[data-transp]");

      // Transparent zone corner → resize (mirrors exclusion resize).
      if (transpHandleTarget !== null) {
        var thIdx = parseInt(transpHandleTarget.dataset.transp);
        var thT = state.room_transparents[thIdx];
        if (!thT) return;
        var thPt = rvScreenToRoomCm(e);
        rvTool.selectedIndex = thIdx;
        rvTool.mode = "transpResizing";
        rvTool.resizeHandle = transpHandleTarget.dataset.transpHandle;
        rvTool.resizeStart = {
          mouse_x_cm: thPt.x_cm, mouse_y_cm: thPt.y_cm,
          x_cm: thT.x_cm, y_cm: thT.y_cm,
          width_cm: thT.width_cm, depth_cm: thT.depth_cm,
        };
        e.preventDefault(); e.stopPropagation();
        return;
      }
      // Transparent zone body → select / start drag.
      if (transpTarget !== null) {
        var tIdx = parseInt(transpTarget.dataset.transp);
        var tT = state.room_transparents[tIdx];
        if (!tT) return;
        if (rvTool.mode === "transpSelected" && rvTool.selectedIndex === tIdx) {
          var tpt = rvScreenToRoomCm(e);
          rvTool.dragOffset = {
            dx_cm: tpt.x_cm - tT.x_cm,
            dy_cm: tpt.y_cm - tT.y_cm,
          };
          rvTool.mode = "transpDragging";
        } else {
          rvTool.selectedIndex = tIdx;
          rvTool.mode = "transpSelected";
          state.selectedTransparent = tIdx;
          state.selectedExclusion = -1;
          state.selectedOpening = null;
          render(rvCvEl);
        }
        e.preventDefault(); e.stopPropagation();
        return;
      }

      // Opening delete badge → remove the opening from state and commit.
      if (openingDelete) {
        var dparts = openingDelete.dataset.openingDelete.split("-");
        var dtype = dparts[0], didx = parseInt(dparts[1], 10);
        // D-122 P4 : type peut être window / opening / door.
        var darr = (dtype === "window") ? state.room_windows
                 : (dtype === "door")   ? state.room_doors
                 :                        state.room_openings;
        var dRemoved = darr && darr[didx];
        if (dRemoved && dRemoved.origin === "auto") {
          state.deleted_auto_signatures = state.deleted_auto_signatures || [];
          state.deleted_auto_signatures.push(
            dtype + "|" + dRemoved.face + "|" +
            (dRemoved.offset_cm || 0) + "|" + (dRemoved.width_cm || 0)
          );
        }
        if (darr && darr[didx]) darr.splice(didx, 1);
        state.selectedOpening = null;
        _rvCommitFromState();
        e.preventDefault(); e.stopPropagation();
        if (typeof e.stopImmediatePropagation === "function") e.stopImmediatePropagation();
        return;
      }

      // Opening resize handle (square) → start width resize.
      if (openingResize) {
        var rparts = openingResize.dataset.openingResize.split("-");
        var rtype = rparts[0], ridx = parseInt(rparts[1], 10), rend = rparts[2];
        var rarr = (rtype === "window") ? state.room_windows
                 : (rtype === "door")   ? state.room_doors
                 :                        state.room_openings;
        var rop = rarr && rarr[ridx];
        if (!rop) return;
        state.selectedOpening = { type: rtype, index: ridx };
        state.selectedExclusion = -1;
        rvTool.selectedIndex = -1;
        var rpt0 = rvScreenToRoomCm(e);
        rvTool.mode = "openingResizing";
        rvTool.openingResize = {
          type: rtype, index: ridx, end: rend, face: rop.face,
          startOffset: rop.offset_cm || 0,
          startWidth: rop.width_cm || 0,
          mouseStart: rpt0,
        };
        state.isPanning = false;
        render(rvCvEl);
        e.preventDefault(); e.stopPropagation();
        if (typeof e.stopImmediatePropagation === "function") e.stopImmediatePropagation();
        return;
      }

      // Opening handle → select + start move along its wall.
      if (openingHandle) {
        var parts = openingHandle.dataset.openingHandle.split("-");
        var otype = parts[0], oidx = parseInt(parts[1], 10);
        var oarr = (otype === "window") ? state.room_windows
                 : (otype === "door")   ? state.room_doors
                 :                        state.room_openings;
        var op = oarr && oarr[oidx];
        if (!op) return;
        state.selectedOpening = { type: otype, index: oidx };
        state.selectedExclusion = -1;
        rvTool.selectedIndex = -1;
        var pt0 = rvScreenToRoomCm(e);
        rvTool.mode = "openingMoving";
        rvTool.openingMove = {
          type: otype, index: oidx, face: op.face,
          startOffset: op.offset_cm || 0,
          widthAlong: op.width_cm || 0,
          mouseStart: pt0,
        };
        state.isPanning = false;
        render(rvCvEl);
        e.preventDefault(); e.stopPropagation();
        if (typeof e.stopImmediatePropagation === "function") e.stopImmediatePropagation();
        return;
      }

      // Room corner handle click → start resizing the whole room (D-99).
      // Snapshot contents deep so mousemove recomputes translations cleanly.
      if (roomHandleTarget !== null) {
        var roomPt = rvScreenToRoomCm(e, ROOM_RESIZE_SNAP_CM);
        rvTool.mode = "roomResizing";
        rvTool.selectedIndex = -1;
        state.selectedExclusion = -1;
        // Start from the current cumulative render offset (may be non-zero
        // from a previous resize in the same amend session).
        var baseOffset = state.roomRenderOffset || { x_cm: 0, y_cm: 0 };
        // Belt-and-suspenders: cancel any leftover pan that could fight us.
        state.isPanning = false;
        rvTool.roomResizeStart = {
          handle: roomHandleTarget.dataset.roomHandle,
          mouse_x_cm: roomPt.x_cm, mouse_y_cm: roomPt.y_cm,
          width_cm: state.room_width_cm, depth_cm: state.room_depth_cm,
          offset_x_cm: baseOffset.x_cm, offset_y_cm: baseOffset.y_cm,
          windows: JSON.parse(JSON.stringify(state.room_windows || [])),
          openings: JSON.parse(JSON.stringify(state.room_openings || [])),
          doors: JSON.parse(JSON.stringify(state.room_doors || [])),
          exclusions: JSON.parse(JSON.stringify(state.room_exclusions || [])),
        };
        e.preventDefault();
        e.stopPropagation();
        // Prevent any other mousedown listener on rvCanvas (e.g. setupPan)
        // from racing us and starting a pan.
        if (typeof e.stopImmediatePropagation === "function") e.stopImmediatePropagation();
        return;
      }

      if (rvTool.mode === "placing") {
        var pt = rvScreenToRoomCm(e);
        rvTool.drawStart = pt;
        rvTool.mode = "drawing";
        e.preventDefault();
        e.stopPropagation();
        return;
      }

      if (rvTool.mode === "placingOpening") {
        var ptO = rvScreenToRoomCm(e, WALL_SNAP_CM);
        var fo = _nearestFaceAndOffset(ptO.x_cm, ptO.y_cm);
        var type = rvTool.placingOpeningType;
        var defaultW = (type === "window")
          ? 100
          : ((window.APP_CONFIG && window.APP_CONFIG.default_door_width_cm) || 90);
        var wallLen = (fo.face === "north" || fo.face === "south")
          ? state.room_width_cm : state.room_depth_cm;
        var width = Math.min(defaultW, wallLen);
        var offset = Math.max(0, Math.min(wallLen - width, fo.offset_cm - width / 2));
        // Snap offset to WALL_SNAP_CM.
        offset = Math.round(offset / WALL_SNAP_CM) * WALL_SNAP_CM;
        offset = Math.max(0, Math.min(wallLen - width, offset));
        if (type === "window") {
          state.room_windows = state.room_windows || [];
          state.room_windows.push({
            face: fo.face, offset_cm: offset, width_cm: width,
            origin: "manual",
          });
        } else if (type === "door") {
          // D-122 P4 : push dans state.room_doors (séparé).
          state.room_doors = state.room_doors || [];
          state.room_doors.push({
            face: fo.face, offset_cm: offset, width_cm: width,
            opens_inward: true, hinge_side: "left", origin: "manual",
          });
        } else {
          state.room_openings = state.room_openings || [];
          state.room_openings.push({
            face: fo.face, offset_cm: offset, width_cm: width,
            origin: "manual",
          });
        }
        // Exit placing mode.
        rvTool.mode = "idle";
        rvTool.placingOpeningType = null;
        rvCvEl.style.cursor = "";
        ["rvBtnAddWindow", "rvBtnAddDoor", "rvBtnAddOpening"].forEach(function (id) {
          var b = document.getElementById(id);
          if (b) b.classList.remove("active");
        });
        _rvCommitFromState();
        e.preventDefault();
        e.stopPropagation();
        return;
      }

      // Corner handle click → start resizing
      if (handleTarget !== null) {
        var hIdx = parseInt(handleTarget.dataset.excl);
        var hExcl = state.room_exclusions[hIdx];
        if (!hExcl) return;
        var hPt = rvScreenToRoomCm(e);
        rvTool.selectedIndex = hIdx;
        rvTool.mode = "resizing";
        rvTool.resizeHandle = handleTarget.dataset.exclHandle;
        rvTool.resizeStart = {
          mouse_x_cm: hPt.x_cm, mouse_y_cm: hPt.y_cm,
          x_cm: hExcl.x_cm, y_cm: hExcl.y_cm,
          width_cm: hExcl.width_cm, depth_cm: hExcl.depth_cm,
        };
        e.preventDefault();
        e.stopPropagation();
        return;
      }

      if (exclTarget !== null) {
        var idx = parseInt(exclTarget.dataset.excl);
        var excl = state.room_exclusions[idx];
        if (!excl) return;
        if (rvTool.mode === "selected" && rvTool.selectedIndex === idx) {
          // Start drag on already-selected zone
          var pt2 = rvScreenToRoomCm(e);
          rvTool.dragOffset = {
            dx_cm: pt2.x_cm - excl.x_cm,
            dy_cm: pt2.y_cm - excl.y_cm,
          };
          rvTool.mode = "dragging";
        } else {
          // Select
          rvTool.selectedIndex = idx;
          rvTool.mode = "selected";
          state.selectedExclusion = idx;
          render(rvCvEl);
        }
        e.preventDefault();
        e.stopPropagation();
      }
    });

    // rvCanvas click: deselect on empty area
    rvCvEl.addEventListener("click", function (e) {
      if (!state.roomAmendMode) return;
      if (rvTool.mode === "placing" || rvTool.mode === "drawing") return;
      var exclTarget = e.target.closest("[data-excl]");
      var openingTarget = e.target.closest("[data-opening-handle]") ||
        e.target.closest("[data-opening-delete]");
      var transpTarget2 = e.target.closest("[data-transp]") ||
        e.target.closest("[data-transp-handle]");
      if (!exclTarget && !openingTarget && !transpTarget2 &&
          (rvTool.mode === "selected" || rvTool.mode === "transpSelected" ||
           rvTool.mode === "idle")) {
        rvTool.selectedIndex = -1;
        rvTool.mode = "idle";
        state.selectedExclusion = -1;
        state.selectedOpening = null;
        state.selectedTransparent = -1;
        render(rvCvEl);
      }
    });

    // Delete key → remove selected opening.
    document.addEventListener("keydown", function (e) {
      if (!state.roomAmendMode) return;
      if (e.key !== "Delete" && e.key !== "Backspace") return;
      if (document.activeElement &&
          (document.activeElement.tagName === "INPUT" ||
           document.activeElement.tagName === "TEXTAREA")) return;
      var sel = state.selectedOpening;
      if (sel) {
        var arr = (sel.type === "window") ? state.room_windows
                : (sel.type === "door")   ? state.room_doors
                :                           state.room_openings;
        var removed = arr && arr[sel.index];
        if (removed && removed.origin === "auto") {
          state.deleted_auto_signatures = state.deleted_auto_signatures || [];
          state.deleted_auto_signatures.push(
            sel.type + "|" + removed.face + "|" +
            (removed.offset_cm || 0) + "|" + (removed.width_cm || 0)
          );
        }
        if (arr && arr[sel.index]) arr.splice(sel.index, 1);
        state.selectedOpening = null;
        _rvCommitFromState();
        e.preventDefault();
        return;
      }
      if (typeof state.selectedTransparent === "number" &&
          state.selectedTransparent >= 0) {
        state.room_transparents.splice(state.selectedTransparent, 1);
        state.selectedTransparent = -1;
        rvTool.mode = "idle";
        _rvCommitFromState();
        e.preventDefault();
      }
    });

    // document mousemove: drawing ghost rect and drag feedback
    document.addEventListener("mousemove", function (e) {
      if (rvTool.mode === "openingResizing" && rvTool.openingResize) {
        var or = rvTool.openingResize;
        var arrR = (or.type === "window") ? state.room_windows
                 : (or.type === "door")   ? state.room_doors
                 :                          state.room_openings;
        var opR = arrR[or.index];
        if (!opR) return;
        var ptR = rvScreenToRoomCm(e);
        var axisR = (or.face === "north" || or.face === "south") ? "x_cm" : "y_cm";
        var deltaR = ptR[axisR] - or.mouseStart[axisR];
        var wallLenR = (or.face === "north" || or.face === "south")
          ? state.room_width_cm : state.room_depth_cm;
        var MIN = GRID_STEP_CM;
        if (or.end === "start") {
          var newOff = Math.max(0,
            Math.min(or.startOffset + or.startWidth - MIN, or.startOffset + deltaR));
          opR.offset_cm = newOff;
          opR.width_cm = or.startOffset + or.startWidth - newOff;
        } else {
          var newW = Math.max(MIN,
            Math.min(wallLenR - or.startOffset, or.startWidth + deltaR));
          opR.width_cm = newW;
        }
        opR.origin = "manual";
        render(rvCvEl);
        return;
      }
      if (rvTool.mode === "transpDragging" && rvTool.dragOffset) {
        var tpt2 = rvScreenToRoomCm(e);
        var tiDrag = rvTool.selectedIndex;
        var tzDrag = state.room_transparents[tiDrag];
        if (!tzDrag) return;
        var tMaxX = state.room_width_cm - tzDrag.width_cm;
        var tMaxY = state.room_depth_cm - tzDrag.depth_cm;
        tzDrag.x_cm = Math.max(0, Math.min(tMaxX, tpt2.x_cm - rvTool.dragOffset.dx_cm));
        tzDrag.y_cm = Math.max(0, Math.min(tMaxY, tpt2.y_cm - rvTool.dragOffset.dy_cm));
        render(rvCvEl);
        return;
      }
      if (rvTool.mode === "transpResizing" && rvTool.resizeStart) {
        var tpt3 = rvScreenToRoomCm(e);
        var trs = rvTool.resizeStart;
        var tzRes = state.room_transparents[rvTool.selectedIndex];
        if (!tzRes) return;
        var tdx = tpt3.x_cm - trs.mouse_x_cm;
        var tdy = tpt3.y_cm - trs.mouse_y_cm;
        var TMIN = GRID_STEP_CM;
        var tH = rvTool.resizeHandle;
        var tRoomW = state.room_width_cm, tRoomD = state.room_depth_cm;
        if (tH === "nw") {
          var tnx = Math.max(0, Math.min(trs.x_cm + trs.width_cm - TMIN, trs.x_cm + tdx));
          var tny = Math.max(0, Math.min(trs.y_cm + trs.depth_cm - TMIN, trs.y_cm + tdy));
          tzRes.x_cm = tnx; tzRes.y_cm = tny;
          tzRes.width_cm = trs.x_cm + trs.width_cm - tnx;
          tzRes.depth_cm = trs.y_cm + trs.depth_cm - tny;
        } else if (tH === "ne") {
          var tny2 = Math.max(0, Math.min(trs.y_cm + trs.depth_cm - TMIN, trs.y_cm + tdy));
          tzRes.y_cm = tny2;
          tzRes.width_cm = Math.max(TMIN, Math.min(tRoomW - trs.x_cm, trs.width_cm + tdx));
          tzRes.depth_cm = trs.y_cm + trs.depth_cm - tny2;
        } else if (tH === "sw") {
          var tnx3 = Math.max(0, Math.min(trs.x_cm + trs.width_cm - TMIN, trs.x_cm + tdx));
          tzRes.x_cm = tnx3;
          tzRes.width_cm = trs.x_cm + trs.width_cm - tnx3;
          tzRes.depth_cm = Math.max(TMIN, Math.min(tRoomD - trs.y_cm, trs.depth_cm + tdy));
        } else if (tH === "se") {
          tzRes.width_cm = Math.max(TMIN, Math.min(tRoomW - trs.x_cm, trs.width_cm + tdx));
          tzRes.depth_cm = Math.max(TMIN, Math.min(tRoomD - trs.y_cm, trs.depth_cm + tdy));
        }
        render(rvCvEl);
        return;
      }
      if (rvTool.mode === "openingMoving" && rvTool.openingMove) {
        var om = rvTool.openingMove;
        var arr = (om.type === "window") ? state.room_windows
                : (om.type === "door")   ? state.room_doors
                :                          state.room_openings;
        var op = arr[om.index];
        if (!op) return;
        var pt = rvScreenToRoomCm(e);
        var axis = (om.face === "north" || om.face === "south") ? "x_cm" : "y_cm";
        var delta = pt[axis] - om.mouseStart[axis];
        var wallLen = (om.face === "north" || om.face === "south")
          ? state.room_width_cm : state.room_depth_cm;
        var maxOff = Math.max(0, wallLen - om.widthAlong);
        op.offset_cm = Math.max(0, Math.min(maxOff, om.startOffset + delta));
        op.origin = "manual";
        render(rvCvEl);
        return;
      }
      if (rvTool.mode === "drawing" && rvTool.drawStart) {
        var pt = rvScreenToRoomCm(e);
        var ds = rvTool.drawStart;
        var x_svg = Math.min(ds.x_cm, pt.x_cm) * SCALE;
        var y_svg = Math.min(ds.y_cm, pt.y_cm) * SCALE;
        var w_svg = Math.abs(pt.x_cm - ds.x_cm) * SCALE;
        var h_svg = Math.abs(pt.y_cm - ds.y_cm) * SCALE;
        rvShowGhostRect(x_svg, y_svg, w_svg, h_svg);
        return;
      }
      if (rvTool.mode === "dragging" && rvTool.dragOffset) {
        var pt3 = rvScreenToRoomCm(e);
        var idx3 = rvTool.selectedIndex;
        var excl3 = state.room_exclusions[idx3];
        if (!excl3) return;
        var maxX3 = state.room_width_cm - excl3.width_cm;
        var maxY3 = state.room_depth_cm - excl3.depth_cm;
        excl3.x_cm = Math.max(0, Math.min(maxX3, pt3.x_cm - rvTool.dragOffset.dx_cm));
        excl3.y_cm = Math.max(0, Math.min(maxY3, pt3.y_cm - rvTool.dragOffset.dy_cm));
        render(rvCvEl);
        return;
      }
      if (rvTool.mode === "roomResizing" && rvTool.roomResizeStart) {
        var ptRoom = rvScreenToRoomCm(e, ROOM_RESIZE_SNAP_CM);
        var rrs = rvTool.roomResizeStart;
        // Raw mouse deltas (snapped to GRID_STEP_CM by rvScreenToRoomCm).
        var mdx = ptRoom.x_cm - rrs.mouse_x_cm;
        var mdy = ptRoom.y_cm - rrs.mouse_y_cm;
        // Per-handle → (shiftX, shiftY) : origin shift in the original
        // coord system (how far NW corner moves). dW / dD : dimension delta.
        var shiftX = 0, shiftY = 0, dW = 0, dD = 0;
        switch (rrs.handle) {
          case "se": dW = mdx;   dD = mdy;   break;
          case "ne": dW = mdx;   dD = -mdy;  shiftY = mdy; break;
          case "sw": dW = -mdx;  dD = mdy;   shiftX = mdx; break;
          case "nw": dW = -mdx;  dD = -mdy;  shiftX = mdx; shiftY = mdy; break;
        }
        // Clamp so width/depth stay ≥ MIN_CM. Adjust shifts consistently.
        var MIN = GRID_STEP_CM;
        var newW = rrs.width_cm + dW;
        var newD = rrs.depth_cm + dD;
        if (newW < MIN) {
          var overW = MIN - newW;
          newW = MIN;
          if (shiftX !== 0) shiftX -= Math.sign(shiftX) * overW;
        }
        if (newD < MIN) {
          var overD = MIN - newD;
          newD = MIN;
          if (shiftY !== 0) shiftY -= Math.sign(shiftY) * overD;
        }
        state.room_width_cm = newW;
        state.room_depth_cm = newD;
        // Render offset so the dragged corner visually tracks the mouse
        // (the NW corner of the displayed room shifts by (shiftX, shiftY)
        // relative to the offset at drag start — offsets accumulate across
        // successive resizes in the same amend session).
        state.roomRenderOffset = {
          x_cm: rrs.offset_x_cm + shiftX,
          y_cm: rrs.offset_y_cm + shiftY,
        };
        // Apply shift to contents: any element anchored to the OLD origin
        // must stay at its absolute position → subtract the shift.
        state.room_windows = rrs.windows.map(function (w) {
          var c = Object.assign({}, w);
          if (c.face === "north" || c.face === "south") c.offset_cm = (c.offset_cm || 0) - shiftX;
          else c.offset_cm = (c.offset_cm || 0) - shiftY;
          return c;
        });
        state.room_openings = rrs.openings.map(function (o) {
          var c = Object.assign({}, o);
          if (c.face === "north" || c.face === "south") c.offset_cm = (c.offset_cm || 0) - shiftX;
          else c.offset_cm = (c.offset_cm || 0) - shiftY;
          return c;
        });
        // D-122 P4 : doors suivent le même shift que openings.
        state.room_doors = (rrs.doors || []).map(function (d) {
          var c = Object.assign({}, d);
          if (c.face === "north" || c.face === "south") c.offset_cm = (c.offset_cm || 0) - shiftX;
          else c.offset_cm = (c.offset_cm || 0) - shiftY;
          return c;
        });
        state.room_exclusions = rrs.exclusions.map(function (z) {
          var c = Object.assign({}, z);
          c.x_cm = (c.x_cm || 0) - shiftX;
          c.y_cm = (c.y_cm || 0) - shiftY;
          return c;
        });
        render(rvCvEl);
        if (window.rvUpdateRoomInfo) window.rvUpdateRoomInfo();
        return;
      }
      if (rvTool.mode === "resizing" && rvTool.resizeStart) {
        var ptR = rvScreenToRoomCm(e);
        var rs = rvTool.resizeStart;
        var idxR = rvTool.selectedIndex;
        var exclR = state.room_exclusions[idxR];
        if (!exclR) return;
        var dx = ptR.x_cm - rs.mouse_x_cm;
        var dy = ptR.y_cm - rs.mouse_y_cm;
        var MIN_CM = GRID_STEP_CM;
        var h = rvTool.resizeHandle;
        var roomW = state.room_width_cm;
        var roomD = state.room_depth_cm;
        if (h === "nw") {
          var nx = Math.max(0, Math.min(rs.x_cm + rs.width_cm - MIN_CM, rs.x_cm + dx));
          var ny = Math.max(0, Math.min(rs.y_cm + rs.depth_cm - MIN_CM, rs.y_cm + dy));
          exclR.x_cm = nx; exclR.y_cm = ny;
          exclR.width_cm = rs.x_cm + rs.width_cm - nx;
          exclR.depth_cm = rs.y_cm + rs.depth_cm - ny;
        } else if (h === "ne") {
          var ny2 = Math.max(0, Math.min(rs.y_cm + rs.depth_cm - MIN_CM, rs.y_cm + dy));
          exclR.y_cm = ny2;
          exclR.width_cm = Math.max(MIN_CM, Math.min(roomW - rs.x_cm, rs.width_cm + dx));
          exclR.depth_cm = rs.y_cm + rs.depth_cm - ny2;
        } else if (h === "sw") {
          var nx3 = Math.max(0, Math.min(rs.x_cm + rs.width_cm - MIN_CM, rs.x_cm + dx));
          exclR.x_cm = nx3;
          exclR.width_cm = rs.x_cm + rs.width_cm - nx3;
          exclR.depth_cm = Math.max(MIN_CM, Math.min(roomD - rs.y_cm, rs.depth_cm + dy));
        } else if (h === "se") {
          exclR.width_cm = Math.max(MIN_CM, Math.min(roomW - rs.x_cm, rs.width_cm + dx));
          exclR.depth_cm = Math.max(MIN_CM, Math.min(roomD - rs.y_cm, rs.depth_cm + dy));
        }
        render(rvCvEl);
      }
    });

    // document mouseup: commit drawing or drag
    document.addEventListener("mouseup", function (e) {
      if (rvTool.mode === "transpDragging" || rvTool.mode === "transpResizing") {
        rvTool.mode = "transpSelected";
        rvTool.dragOffset = null;
        rvTool.resizeStart = null;
        _rvCommitFromState();
        return;
      }
      if (rvTool.mode === "openingMoving") {
        rvTool.mode = "idle";
        rvTool.openingMove = null;
        _rvCommitFromState();
        return;
      }
      if (rvTool.mode === "openingResizing") {
        rvTool.mode = "idle";
        rvTool.openingResize = null;
        _rvCommitFromState();
        return;
      }
      if (rvTool.mode === "drawing") {
        rvRemoveGhostRect();
        var pt = rvScreenToRoomCm(e);
        var ds = rvTool.drawStart;
        var x_cm = Math.min(ds.x_cm, pt.x_cm);
        var y_cm = Math.min(ds.y_cm, pt.y_cm);
        var w_cm = Math.abs(pt.x_cm - ds.x_cm);
        var h_cm = Math.abs(pt.y_cm - ds.y_cm);
        rvTool.drawStart = null;
        rvTool.mode = "idle";
        if (rvBtnAddExclEl) rvBtnAddExclEl.classList.remove("active");
        rvCvEl.style.cursor = "";
        if (w_cm >= GRID_STEP_CM && h_cm >= GRID_STEP_CM) {
          if (rvTool.placingZoneKind === "transparent") {
            rvDslAppendTransparent(x_cm, y_cm, w_cm, h_cm);
          } else {
            rvDslAppendExcl(x_cm, y_cm, w_cm, h_cm);
          }
          rvApplyDslAsync();
        }
        rvTool.placingZoneKind = null;
        return;
      }
      if (rvTool.mode === "dragging") {
        var idx4 = rvTool.selectedIndex;
        var excl4 = state.room_exclusions[idx4];
        rvTool.mode = "selected";
        rvTool.dragOffset = null;
        if (excl4) {
          state.selectedExclusion = idx4;
          rvDslReplaceExcl(idx4, excl4.x_cm, excl4.y_cm, excl4.width_cm, excl4.depth_cm);
          rvApplyDslAsync();
        }
        return;
      }
      if (rvTool.mode === "roomResizing") {
        rvTool.mode = "idle";
        rvTool.roomResizeStart = null;
        // Keep state.roomRenderOffset persistent across the amend session:
        // the NW corner stays where the user dropped it. It will be reset
        // on amend mode exit (see _cancelAmendIfActive / exitRoomAmendMode).
        // Clamp any element that ended up outside the new room bounds.
        _clampContentsToRoom();
        // Commit: regenerate the whole DSL from current state (since a
        // corner drag may have shifted many content offsets) and re-apply.
        var dslEl = document.getElementById("rvRoomDsl");
        if (dslEl) {
          dslEl.value = _stateToDsl();
          rvApplyDslAsync();
        }
        return;
      }
      if (rvTool.mode === "resizing") {
        var idx6 = rvTool.selectedIndex;
        var excl6 = state.room_exclusions[idx6];
        rvTool.mode = "selected";
        rvTool.resizeHandle = null;
        rvTool.resizeStart = null;
        if (excl6) {
          state.selectedExclusion = idx6;
          rvDslReplaceExcl(idx6, excl6.x_cm, excl6.y_cm, excl6.width_cm, excl6.depth_cm);
          rvApplyDslAsync();
        }
      }
    });

    // rvTool keydown: arrows move selected exclusion, Delete/Backspace
    // remove, Escape deselect/cancel.
    // Capture phase so arrow keys preempt floor_plan.js's room navigation
    // when an exclusion is selected.
    document.addEventListener("keydown", function (e) {
      if (!state.roomAmendMode) return;
      if (e.target.tagName === "INPUT" || e.target.tagName === "TEXTAREA") return;

      // Arrow keys: move the selected exclusion (Shift = 5× step)
      if (rvTool.mode === "selected" && rvTool.selectedIndex >= 0 &&
          (e.key === "ArrowLeft" || e.key === "ArrowRight" ||
           e.key === "ArrowUp" || e.key === "ArrowDown")) {
        e.preventDefault();
        // Stop other handlers (floor_plan.js room nav, editor.js block nav)
        // from firing on this event.
        if (typeof e.stopImmediatePropagation === "function") e.stopImmediatePropagation();
        var step = e.shiftKey ? GRID_STEP_CM * 5 : GRID_STEP_CM;
        var idxK = rvTool.selectedIndex;
        var exclK = state.room_exclusions[idxK];
        if (!exclK) return;
        var maxXK = state.room_width_cm - exclK.width_cm;
        var maxYK = state.room_depth_cm - exclK.depth_cm;
        if (e.key === "ArrowRight") exclK.x_cm = Math.min(maxXK, exclK.x_cm + step);
        else if (e.key === "ArrowLeft") exclK.x_cm = Math.max(0, exclK.x_cm - step);
        else if (e.key === "ArrowDown") exclK.y_cm = Math.min(maxYK, exclK.y_cm + step);
        else if (e.key === "ArrowUp") exclK.y_cm = Math.max(0, exclK.y_cm - step);
        rvDslReplaceExcl(idxK, exclK.x_cm, exclK.y_cm, exclK.width_cm, exclK.depth_cm);
        render(rvCvEl);
        return;
      }

      if (e.key === "Escape") {
        e.preventDefault();
        if (rvTool.mode === "placing" || rvTool.mode === "drawing") {
          rvRemoveGhostRect();
          rvTool.mode = "idle";
          rvTool.drawStart = null;
          if (rvBtnAddExclEl) rvBtnAddExclEl.classList.remove("active");
          rvCvEl.style.cursor = "";
        } else if (rvTool.mode === "selected") {
          rvTool.selectedIndex = -1;
          rvTool.mode = "idle";
          state.selectedExclusion = -1;
          render(rvCvEl);
        }
        return;
      }

      // Enter / Return: deselect (commit, same as clicking outside)
      if ((e.key === "Enter" || e.key === "Return") && rvTool.mode === "selected") {
        e.preventDefault();
        rvTool.selectedIndex = -1;
        rvTool.mode = "idle";
        state.selectedExclusion = -1;
        render(rvCvEl);
        return;
      }

      if ((e.key === "Delete" || e.key === "Backspace") &&
          rvTool.mode === "selected" && rvTool.selectedIndex >= 0) {
        e.preventDefault();
        var idx5 = rvTool.selectedIndex;
        rvTool.selectedIndex = -1;
        rvTool.mode = "idle";
        state.selectedExclusion = -1;
        rvDslDeleteExcl(idx5);
        rvApplyDslAsync();
      }
    }, true);
  });
})();
