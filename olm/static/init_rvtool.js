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
  // P1.4: All 21 addEventListener calls in this IIFE are session-life
  // (bound once at DOMContentLoaded, never re-bound). The inline-edit
  // popup (L1464-1466) creates ephemeral elements cleaned up by
  // popup.remove(). No _dispose() needed.
  document.addEventListener("DOMContentLoaded", function () {
    var rvTool = { mode: "idle", drawStart: null, selectedIndex: -1, dragOffset: null };
    // rvTool sub-fields populated on demand by the various handlers:
    //   openingMove  : { type, index, face, startOffset, widthAlong, mouseStart }
    //   openingResize: { type, index, end, face, startOffset, startWidth, mouseStart }
    //   roomResizeStart / transpDrag / transpResize / resizeStart / dragStart …
    window.rvTool = rvTool;

    // --- Constants --------------------------------------------------------
    var ROOM_RESIZE_SNAP_CM = 5;        // D-99 fine snap for room resize handles
    var WALL_SNAP_CM = 10;              // opening placement snap on walls
    var GHOST_RECT_COLOR = "#2a9d8f";   // teal (draw preview outline)
    var GHOST_RECT_DASH = "4 4";
    var DEFAULT_WINDOW_WIDTH_CM = 100;  // "+ Add window" default width
    var SQ_CM_PER_SQ_M = 10000;         // cm² → m² divisor
    var ARROW_KEY_SHIFT_MULTIPLIER = 5; // Shift+arrow nudge = 5 × grid step

    // --- Helpers ----------------------------------------------------------
    // D-122 P4 : state.room_openings, room_doors, room_windows vivent en
    // collections séparées. L'UI badge/handle encode le type dans le
    // dataset ; on route l'accès à la bonne collection.
    function _getOpeningArray(type) {
      if (type === "window") return state.room_windows;
      if (type === "door")   return state.room_doors;
      return state.room_openings;
    }

    var _rvGhostRect = null;

    // Resolve active SVG canvas and DSL textarea based on amend context
    function _isPatternEditorActive() {
      // PE is active if roomAmendMode says "pattern" OR if the PE sub-tab is visible
      if (state.roomAmendMode && state.roomAmendMode.context === "pattern") return true;
      var editorSub = document.getElementById("subtabCatEditor");
      return editorSub && editorSub.classList.contains("active");
    }
    function _getActiveSvg() {
      if (_isPatternEditorActive()) return document.getElementById("canvas");
      return document.getElementById("rvCanvas");
    }
    function _getActiveDslEl() {
      if (_isPatternEditorActive()) return document.getElementById("dslRoom");
      return document.getElementById("rvRoomDsl");
    }
    function _renderActive() {
      render(_getActiveSvg());
    }
    // Post-modification hook: sync PE-specific UI after visual edits
    function _syncPatternEditorUI() {
      // Called after door edits — works in PE even without roomAmendMode
      // Update dimension inputs
      var wEl = document.getElementById("roomWidth");
      var dEl = document.getElementById("roomDepth");
      if (wEl) wEl.value = state.room_width_cm;
      if (dEl) dEl.value = state.room_depth_cm;
      // Update DSL textarea
      var dslEl = _getActiveDslEl();
      if (dslEl) dslEl.value = _stateToDsl();
    }

    function rvScreenToRoomCm(evt, customSnapCm, ignoreOffset) {
      var svg = _getActiveSvg();
      var pt = svg.createSVGPoint();
      pt.x = evt.clientX;
      pt.y = evt.clientY;
      var svgPt = pt.matrixTransform(svg.getScreenCTM().inverse());
      var snap = (typeof customSnapCm === "number" && customSnapCm > 0) ? customSnapCm : GRID_STEP_CM;
      // D-243 F2: subtract roomRenderOffset BEFORE snap so coords are
      // relative to room NW (not SVG NW) after resize.
      // D-292: during a room resize the offset is itself driven by the mouse,
      // so subtracting the LIVE offset creates a feedback loop (oscillation +
      // halved enlargement). The resize path passes ignoreOffset=true to
      // measure the raw mouse delta against the drag-start frame instead.
      var offX = (ignoreOffset || !state.roomRenderOffset) ? 0 : state.roomRenderOffset.x_cm;
      var offY = (ignoreOffset || !state.roomRenderOffset) ? 0 : state.roomRenderOffset.y_cm;
      var rawX = svgPt.x / SCALE - offX;
      var rawY = svgPt.y / SCALE - offY;
      return {
        x_cm: Math.round(rawX / snap) * snap,
        y_cm: Math.round(rawY / snap) * snap,
      };
    }

    async function rvApplyDslAsync() {
      var text = (_getActiveDslEl() || {}).value || "";
      text = text.trim();
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
        _renderActive();
        if (window.rvUpdateRoomInfo) window.rvUpdateRoomInfo();
        _syncPatternEditorUI();
      } catch (err) { console.error("rvApplyDslAsync:", err); }
    }

    function rvDslAppendExcl(x_cm, y_cm, w_cm, h_cm) {
      var el = _getActiveDslEl();
      if (!el) return;
      var line = "EXCLUSION " + x_cm + " " + y_cm + " " + w_cm + " " + h_cm;
      el.value = el.value.trimEnd() + "\n" + line;
    }
    function rvDslAppendTransparent(x_cm, y_cm, w_cm, h_cm) {
      var el = _getActiveDslEl();
      if (!el) return;
      var line = "TRANSPARENT " + x_cm + " " + y_cm + " " + w_cm + " " + h_cm;
      el.value = el.value.trimEnd() + "\n" + line;
    }

    function rvDslReplaceExcl(index, x_cm, y_cm, w_cm, h_cm) {
      var el = _getActiveDslEl();
      if (!el) return;
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
      var el = _getActiveDslEl();
      if (!el) return;
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

    // D-256 Lot 2: factored helpers for rect drag + arrow move (shared by
    // exclusions, transparents, and furniture).
    function _dragRectClamped(rect, mouseCm, dragOffset) {
      var maxX = state.room_width_cm - (rect.width_cm || 0);
      var maxY = state.room_depth_cm - (rect.depth_cm || 0);
      rect.x_cm = Math.max(0, Math.min(maxX, mouseCm.x_cm - dragOffset.dx_cm));
      rect.y_cm = Math.max(0, Math.min(maxY, mouseCm.y_cm - dragOffset.dy_cm));
    }
    function _arrowMoveRect(rect, key, step) {
      var maxX = state.room_width_cm - (rect.width_cm || 0);
      var maxY = state.room_depth_cm - (rect.depth_cm || 0);
      if (key === "ArrowRight") rect.x_cm = Math.min(maxX, rect.x_cm + step);
      else if (key === "ArrowLeft") rect.x_cm = Math.max(0, rect.x_cm - step);
      else if (key === "ArrowDown") rect.y_cm = Math.min(maxY, rect.y_cm + step);
      else if (key === "ArrowUp") rect.y_cm = Math.max(0, rect.y_cm - step);
    }

    function rvShowGhostRect(x_svg, y_svg, w_svg, h_svg, color, dash, strokeW) {
      var svg = _getActiveSvg();
      if (!_rvGhostRect) {
        _rvGhostRect = document.createElementNS("http://www.w3.org/2000/svg", "rect");
        _rvGhostRect.setAttribute("fill", "none");
        _rvGhostRect.setAttribute("pointer-events", "none");
      }
      // Style set on every call (the element is reused across ghost types).
      _rvGhostRect.setAttribute("stroke", color || GHOST_RECT_COLOR);
      _rvGhostRect.setAttribute("stroke-width", strokeW || "1");
      _rvGhostRect.setAttribute("stroke-dasharray", dash || GHOST_RECT_DASH);
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
        // NF convention: L/R = swing direction (hinge left → swings right → "R")
        var side = (d.hinge_side === "left") ? "R" : "L";
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
    var peCvEl = document.getElementById("canvas");
    if (!rvCvEl && !peCvEl) return;

    // --- Opening placement buttons (Add Window / Door / Opening) ---
    // Click a button → enter placingOpening mode; next click on a wall
    // inserts the opening at that position.
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
        _getActiveSvg().style.cursor = "";
        return;
      }
      rvTool.mode = "placingOpening";
      rvTool.placingOpeningType = type;
      if (btn) btn.classList.add("active");
      _getActiveSvg().style.cursor = "crosshair";
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

    // --- Seeds / V-Rays / H-Rays toggles ---
    ([
      ["rvSeedsToggle", "showSeeds"],
      ["rvVraysToggle", "showVrays"],
      ["rvHraysToggle", "showHrays"],
    ]).forEach(function (entry) {
      var cb = document.getElementById(entry[0]);
      if (cb) {
        cb.addEventListener("change", function () {
          state[entry[1]] = cb.checked;
          _renderActive();
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
          alertModal("Orientation check: missing bbox or plan path.");
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

    // --- Diagnostic modal helpers ---
    var diagModal = document.getElementById("diagModal");
    var diagText = document.getElementById("diagText");
    var diagTitle = document.getElementById("diagTitle");
    var diagClose = document.getElementById("diagClose");
    var diagCopy = document.getElementById("diagCopy");
    function showDiag(title, text) {
      if (!diagModal || !diagText) { alertModal(text); return; }
      diagTitle.textContent = title;
      diagText.value = text;
      diagModal.style.display = "flex";
    }
    if (diagClose) diagClose.onclick = function () {
      diagModal.style.display = "none";
    };
    if (diagCopy) diagCopy.onclick = function () {
      diagText.select();
      document.execCommand("copy");
    };
    if (diagModal) diagModal.onclick = function (e) {
      if (e.target === diagModal) diagModal.style.display = "none";
    };

    // --- Perf button (v0.5.33) : timing transition Floor→Room (freeze diag) ---
    var perfBtn = document.getElementById("rvBtnPerf");
    if (perfBtn) {
      perfBtn.addEventListener("click", function () {
        OLM_DIAGS.run("perf.transition");
      });
    }

    // --- Diagnostic button (D-160) ---
    var diagBtn = document.getElementById("rvBtnDiag");
    if (diagBtn) {
      diagBtn.addEventListener("click", async function () {
        if (!state.roomAmendMode) return;
        var ingst = window.ingState || {};
        var orig = state.roomAmendMode.originalRoom || {};
        var seedPx = orig.seed_px || orig.seed ||
          (orig.seed_x != null && orig.seed_y != null
            ? [orig.seed_x, orig.seed_y] : null);
        if (!seedPx || !ingst.planPathEnhanced || !ingst.scale) {
          alertModal("Diag unavailable: missing seed, plan path, or scale.");
          return;
        }
        var roomName = orig.name || "";
        var otherSeeds = [];
        (ingst.rooms || []).forEach(function (r) {
          if (r.name === roomName) return;
          var sp = r.seed_px || r.seed;
          if (sp && sp.length >= 2) {
            otherSeeds.push([sp[0], sp[1]]);
          }
        });
        diagBtn.disabled = true;
        diagBtn.textContent = "...";
        try {
          var resp = await fetch("/api/debug/room-diagnostic", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              plan_path: ingst.planPathEnhanced,
              seed_px: [parseInt(seedPx[0]), parseInt(seedPx[1])],
              bbox_px: orig.bbox_px || null,
              scale_cm_per_px: ingst.scale,
              mode: ingst.mode || "preprocessed",
              other_seeds_px: otherSeeds,
              doors: orig.doors || [],
              transparent_zones: orig.transparent_zones || [],
            }),
          });
          var data = await resp.json();
          if (data.error) throw new Error(data.error);
          var diag = data.diag || {};
          var cd = data.color_detection || {};
          var ch = data.corner_hits || [];
          var lines = [
            "=== Room " + roomName + " diagnostic ===",
            "",
            "--- ORIENTATION ---",
            "corridor_face_abs (stored): " +
              (orig.corridor_face_abs || "(empty)"),
            "green detected: " + (cd.corridor_face || "(none)"),
            "blue detected: " + JSON.stringify(
              cd.exterior_faces || []),
            "deduced corridor: " +
              (data.deduced_corridor_face || "(none)"),
            "",
            "--- CORNER SCAN ---",
          ];
          ch.forEach(function (c) {
            var h = c.hit || {};
            var rgb = h.match_rgb || h.first_rgb;
            var rgbStr = rgb ? " rgb=" + JSON.stringify(rgb) : "";
            var hitStr = h.color
              ? h.color + " at " + h.dist + "px" + rgbStr
              : "(none) " + (h.reason || "") +
                " @" + (h.dist || 0) + "px" + rgbStr;
            lines.push(
              "  " + c.corner + " -> " + c.direction +
              " : " + hitStr);
          });
          var cp = data.color_params || {};
          if (cp.image_mode) {
            lines.push("  image_mode: " + cp.image_mode +
              " size: " + JSON.stringify(cp.image_size));
          }
          lines.push("");
          lines.push("--- DOOR DETECTION ---");
          lines.push("rect_after_largest: " +
            JSON.stringify(diag.rect_after_largest || "?"));
          lines.push("rect_after_snap: " +
            JSON.stringify(diag.rect_after_snap || "?"));
          lines.push("rect_after_pillars: " +
            JSON.stringify(diag.rect_after_pillars || "?"));
          lines.push("binarize_threshold: " +
            (diag.binarize_threshold || "?"));
          lines.push("door_width_px: " +
            (diag.door_width_px || "?"));
          var doorFaces = diag.door_faces || [];
          if (!doorFaces.length) {
            lines.push("  (no door_faces diag — old backend?)");
          }
          doorFaces.forEach(function (df) {
            lines.push("");
            var status = df.rejected ? "REJECTED=" + df.rejected
              : "OK doors=" + (df.doors_found || 0);
            if (df.seed_confirmed) status += " [SEED CONFIRMED]";
            if (df.seed_fallback) status += " [SEED FALLBACK]";
            lines.push("  === " + df.face.toUpperCase() + " === " + status);
            lines.push("  rect: " + JSON.stringify(df.rect));
            lines.push("  face_len: " + df.face_len_px +
              "  door_width: " + (df.door_width_px || "?") +
              "  tolerance: " + (df.tolerance || "?"));
            lines.push("  seeds: " + (df.has_seeds ? df.seeds_count : "none") +
              "  total_hits: " + (df.total_face_hits || 0));

            if (df.wall_px != null) {
              lines.push("  -- wall (mode) --");
              lines.push("  wall_px: " + df.wall_px +
                "  wall_hits: " + df.wall_hits);
              if (df.wall_distribution && df.wall_distribution.length) {
                df.wall_distribution.slice(0, 5).forEach(function (w) {
                  lines.push("    pos=" + w.pos + " count=" + w.count);
                });
              }
            }

            if (df.arc_hits_count != null) {
              lines.push("  -- arc --");
              lines.push("  arc_hits: " + df.arc_hits_count +
                "  arc_span: " + (df.arc_span_px || "?") +
                "  range: " + JSON.stringify(df.arc_along_range || []));
            }

            if (df.arc_hinge_side) {
              lines.push("  -- arc profile --");
              lines.push("  hinge: " + df.arc_hinge_side +
                "  violations: " + (df.arc_violations || 0) +
                "/" + ((df.arc_profile_dists || []).length) +
                " = " + ((df.arc_violation_ratio || 0) * 100).toFixed(1) + "%");
              lines.push("  dist_range: " + (df.arc_dist_range || "?"));
            }

            if (df.wall_fill_ratio != null) {
              lines.push("  -- wall opening --");
              lines.push("  wall_fill: " + (df.wall_fill_ratio * 100).toFixed(1) +
                "%  (" + (df.wall_pixels_in_arc || 0) + "/" +
                (df.arc_zone_len || 0) + " px)");
            }

            if (df.door_offset_px != null) {
              lines.push("  -- result --");
              lines.push("  offset: " + df.door_offset_px +
                "  width: " + (df.door_width_detected_px || "?") +
                "  wall_confirmation: " + (df.wall_confirmation || "?"));
            }
          });

          lines = lines.concat([
            "",
            "--- BBOX ---",
            "seed_px: [" + seedPx[0] + ", " + seedPx[1] + "]",
            "bbox_detected: " + JSON.stringify(data.bbox_px),
            "bbox_coarse: " + JSON.stringify(diag.bbox_coarse),
            "coarse_mode: " + JSON.stringify(diag.coarse_mode),
            "coarse_max: " + JSON.stringify(diag.coarse_max),
            "seed_caps: " + JSON.stringify(diag.seed_caps),
            "max_range: " + JSON.stringify(diag.max_range),
            "other_seeds: " + (data.other_seeds_count || 0),
            "",
            "--- HITS PIPELINE ---",
            "1. hits_raw (after comb): " + JSON.stringify(diag.hits_raw),
            "2. seed_filter: " + JSON.stringify(diag.seed_filter
              ? Object.keys(diag.seed_filter).reduce(function(o, k) {
                  o[k] = "kept=" + diag.seed_filter[k].kept +
                    " removed=" + diag.seed_filter[k].removed;
                  return o; }, {}) : "none"),
            "3. hits_after_seed_filter: " +
              JSON.stringify(diag.hits_after_seed_filter),
            "4. pillar_hits_removed: " +
              (diag.pillar_hits_removed || 0),
            "   pillars_detected: " +
              JSON.stringify(diag.pillars_detected || []),
            "5. hits_after_pillar_filter: " +
              JSON.stringify(diag.hits_after_pillar_filter),
            "6. hits_filtered (final): " +
              JSON.stringify(diag.hits_filtered),
            "obstacles: " + (diag.obstacles_px
              ? diag.obstacles_px.length : 0),
          ]);
          // Seed filter: only show directions with removals
          if (diag.seed_filter) {
            Object.keys(diag.seed_filter).forEach(function (dir) {
              var sf = diag.seed_filter[dir];
              if (sf.removed > 0 && sf.removed_hits) {
                var blockers = {};
                sf.removed_hits.forEach(function (r) {
                  var k = r.blocker.join(",");
                  blockers[k] = (blockers[k] || 0) + 1;
                });
                var bstr = Object.keys(blockers).map(function (k) {
                  return "[" + k + "]×" + blockers[k];
                }).join(" ");
                lines.push("  " + dir + " removed=" + sf.removed +
                  " by: " + bstr);
              }
            });
          }
          // South hits: y range summary
          if (diag.south_hits && diag.south_hits.length) {
            var sh = diag.south_hits;
            var ys = sh.map(function (h) { return h[1]; });
            var xs = sh.map(function (h) { return h[0]; });
            lines.push("south_hits: " + sh.length +
              "  x=[" + Math.min.apply(null, xs) + ".." +
              Math.max.apply(null, xs) + "]" +
              "  y=[" + Math.min.apply(null, ys) + ".." +
              Math.max.apply(null, ys) + "]");
          }
          lines = lines.concat([
            "",
            "--- DOORS ---",
            "doors: " + (data.doors ? data.doors.length : 0),
          ]);
          (data.doors || []).forEach(function (d) {
            lines.push("  " + d.face + " @" + d.offset_px +
              " w=" + d.width_px +
              (d.seed_x != null ? " seed=" + d.seed_x +
                "," + d.seed_y : ""));
          });
          lines.push("");
          lines.push("--- WINDOWS ---");
          lines.push("windows: " + (data.windows
            ? data.windows.length : 0));
          (data.windows || []).forEach(function (w) {
            lines.push("  " + w.face + " @" + w.offset_px +
              " w=" + w.width_px);
          });
          lines.push("");
          lines.push("--- OPENINGS ---");
          lines.push("openings: " + (data.openings
            ? data.openings.length : 0));
          (data.openings || []).forEach(function (o) {
            lines.push("  " + o.face + " @" + o.offset_px +
              " w=" + o.width_px);
          });

          // --- OVERLAY DEBUG ---
          lines.push("");
          lines.push("--- OVERLAY DEBUG ---");
          var _cfAbs = orig.corridor_face_abs || "";
          var _cAngle = (window.canonicalIO && window.canonicalIO.canonAngle)
            ? window.canonicalIO.canonAngle(_cfAbs) : 0;
          var _bpx = orig.bbox_px || [0, 0, 0, 0];
          var _sc = (ingst.scale || 1);
          var _ov = state.overlay || {};
          var _ovScale = _ov.pxPerCm ? (2 / _ov.pxPerCm) : 0;
          var _roomWCm = state.room_width_cm || 0;
          var _roomDCm = state.room_depth_cm || 0;
          var _refWPx = _roomWCm * 2;
          var _refHPx = _roomDCm * 2;
          var _swapC = (_cAngle === 90 || _cAngle === 270);
          var _ocx = (_swapC ? _refHPx : _refWPx) / 2;
          var _ocy = (_swapC ? _refWPx : _refHPx) / 2;
          var _dx = 0, _dy = 0;
          if (_cAngle === 90 || _cAngle === 270) {
            _dx = (_refWPx - _refHPx) / 2;
            _dy = (_refHPx - _refWPx) / 2;
          }
          var _ovOffX = _ov.offsetX || 0;
          var _ovOffY = _ov.offsetY || 0;
          var _ovX = -(_ovOffX * 2);
          var _ovY = -(_ovOffY * 2);
          lines.push("corridor_face_abs: " + (_cfAbs || "(empty)"));
          lines.push("canonAngle: " + _cAngle);
          lines.push("room_width_cm (canon): " + _roomWCm);
          lines.push("room_depth_cm (canon): " + _roomDCm);
          lines.push("bbox_px (abs): " + JSON.stringify(_bpx));
          lines.push("bbox_px w×h: " +
            (_bpx[2] - _bpx[0]) + " × " + (_bpx[3] - _bpx[1]));
          lines.push("scale: " + _sc.toFixed(4) + " cm/px");
          lines.push("abs dims cm: " +
            Math.round((_bpx[2] - _bpx[0]) * _sc) + " × " +
            Math.round((_bpx[3] - _bpx[1]) * _sc));
          lines.push("refWPx (canon W*SCALE): " + _refWPx.toFixed(1));
          lines.push("refHPx (canon D*SCALE): " + _refHPx.toFixed(1));
          lines.push("rotation center: (" +
            _ocx.toFixed(1) + ", " + _ocy.toFixed(1) + ")");
          lines.push("translate dx: " + _dx.toFixed(1) +
            ", dy: " + _dy.toFixed(1));
          lines.push("overlay offsetX: " + _ovOffX.toFixed(2) +
            ", offsetY: " + _ovOffY.toFixed(2));
          lines.push("overlay imgW: " + (_ov.imgW || 0) +
            ", imgH: " + (_ov.imgH || 0));
          lines.push("overlay pxPerCm: " + (_ov.pxPerCm || 0).toFixed(4));
          lines.push("image pos (ovX, ovY): (" +
            _ovX.toFixed(1) + ", " + _ovY.toFixed(1) + ")");

          showDiag("Room " + roomName, lines.join("\n"));
        } catch (err) {
          showDiag("Error", err.message);
        } finally {
          diagBtn.disabled = false;
          diagBtn.textContent = "Diag";
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
          alertModal("Rescan unavailable: missing plan path, seed, or scale.");
          return;
        }
        // D-127 : si l'utilisateur a redimensionné la pièce en amend mode
        // (roomRenderOffset != 0 ou dims ≠ dims originelles), propager le
        // bbox effectif user → backend. Sans ça, backend détecte dans
        // l'ancienne zone et ré-applique les openings dans la nouvelle
        // géométrie — résultat incohérent (cf. Test 3 D-126 : porte
        // fantôme à la face sud après raccourcissement par le bas).
        //
        // Pipeline : canonBbox {x: shift, y: shift, w: canonW, d: canonD}
        //   → rotateRectInv(cfAbs, absOrigW, absOrigD) → abs-room-local
        //   → + origBbox NW × pxPerCm → effBbox (image px).
        var cfAbsForZones = amend.originalRoom.corridor_face_abs ||
          state.corridor_face_abs || "";
        var effBbox = bbox;
        var effAbsW = bbox ? (bbox[2] - bbox[0]) * ingst.scale : 0;
        var effAbsD = bbox ? (bbox[3] - bbox[1]) * ingst.scale : 0;
        var cio = window.canonicalIO;
        if (bbox && ingst.scale && cio && cio.rotateRectInv) {
          var pxPerCm = 1.0 / ingst.scale;
          var absOrigW = (bbox[2] - bbox[0]) * ingst.scale;
          var absOrigD = (bbox[3] - bbox[1]) * ingst.scale;
          var offs = state.roomRenderOffset || { x_cm: 0, y_cm: 0 };
          var canonBboxUser = {
            x: offs.x_cm || 0,
            y: offs.y_cm || 0,
            width: state.room_width_cm || 0,
            depth: state.room_depth_cm || 0,
          };
          var origCanonW = origRoom.width_cm || 0;
          var origCanonD = origRoom.depth_cm || 0;
          var resized = (canonBboxUser.x !== 0 || canonBboxUser.y !== 0 ||
            canonBboxUser.width !== origCanonW ||
            canonBboxUser.depth !== origCanonD);
          if (resized && canonBboxUser.width > 0 && canonBboxUser.depth > 0) {
            var absRel = cio.rotateRectInv(
              canonBboxUser, cfAbsForZones, absOrigW, absOrigD);
            effBbox = [
              Math.round(bbox[0] + absRel.x * pxPerCm),
              Math.round(bbox[1] + absRel.y * pxPerCm),
              Math.round(bbox[0] + (absRel.x + absRel.width) * pxPerCm),
              Math.round(bbox[1] + (absRel.y + absRel.depth) * pxPerCm),
            ];
            effAbsW = absRel.width;
            effAbsD = absRel.depth;
          }
        }
        // Backend /api/room/reanalyze interprète transparent_zones en
        // abs-room-local relative à effBbox (dims effectives user).
        var transparents = window.canonicalZonesToAbs
          ? window.canonicalZonesToAbs(
              state.room_transparents || [],
              cfAbsForZones, effAbsW, effAbsD)
          : (state.room_transparents || []).map(function (z) {
              return {
                x_cm: z.x_cm, y_cm: z.y_cm,
                width_cm: z.width_cm, depth_cm: z.depth_cm,
              };
            });
        // D-204: typed doors canon → abs. door_seeds sent separately.
        var _Wc = state.room_width_cm || 0;
        var _Dc = state.room_depth_cm || 0;
        var typedRoomDoors = (state.room_doors || []).filter(
          function (d) { return !!d.face; });
        var doorsPx = typedRoomDoors.map(function (d) {
          var absFace = d.face;
          var invMap = cio && cio.INV_FACE_MAPS
            ? cio.INV_FACE_MAPS[cfAbsForZones] : null;
          if (invMap && invMap[d.face]) absFace = invMap[d.face];
          var _canonFaceLen = (d.face === 'north' || d.face === 'south')
            ? _Wc : _Dc;
          var offAbs = d.offset_cm || 0;
          var _ft = cio && cio._flipTo;
          var _flip = _ft
            ? _ft(cfAbsForZones, d.face)
            : (cfAbsForZones === 'north');
          if (_flip) {
            offAbs = _canonFaceLen - offAbs - (d.width_cm || 0);
          }
          var hingeAbs = (cio && cio.flipHingeOnRotation)
            ? cio.flipHingeOnRotation(d.hinge_side, d.face, absFace, _flip)
            : d.hinge_side;
          var entry = {
            face: absFace,
            offset_cm: offAbs,
            width_cm: d.width_cm || 0,
          };
          if (hingeAbs) entry.hinge_side = hingeAbs;
          if (d.opens_inward != null) entry.opens_inward = d.opens_inward;
          return entry;
        });
        // D-204: door_seeds from ingState room (image-absolute coords).
        var _ingRoom = (ingst.rooms || []).find(function (ir) {
          return ir.name === amend.roomName;
        });
        var _doorSeeds = (_ingRoom && _ingRoom.door_seeds) || [];
        var doorWidthCm = ((window.APP_CONFIG || {}).default_door_width_cm) || 90;
        reanalyzeBtn.disabled = true;
        reanalyzeBtn.textContent = "Rescanning...";
        try {
          // Lock walls (ex-Lock bbox, D-132) → demande au backend de
          // contraindre le ray-cast aux bords de effBbox (clip_to_bbox) :
          // on re-scanne fenêtres / ouvertures / portes sans re-détecter
          // les murs — le bbox user est préservé.
          var lockWallsElFetch = document.getElementById("rvLockWalls");
          var lockWallsFlag = !!(lockWallsElFetch && lockWallsElFetch.checked);
          var planMode = (ingst._selectedPlan && ingst._selectedPlan.mode)
                         || 'ocr';
          // Collect seeds of all other rooms to limit rays at boundaries.
          var otherSeeds = [];
          (ingst.rooms || []).forEach(function (ir) {
            var sp = ir.seed_px || ir.seed;
            if (sp && ir.name !== amend.roomName) {
              otherSeeds.push([sp[0], sp[1]]);
            }
          });
          var _rvPayload = {
              plan_path: ingst.planPathEnhanced,
              overlay_path: ingst.planPath || '',
              seed_px: seedPx,
              bbox_px: effBbox,
              scale_cm_per_px: ingst.scale,
              transparent_zones: transparents,
              doors: doorsPx,
              door_width_cm: doorWidthCm,
              clip_to_bbox: lockWallsFlag,
              mode: planMode,
              window_mode: ((window.APP_CONFIG || {}).ingestion || {}).window_mode || 'simple',
              other_seeds_px: otherSeeds,
              corridor_face: amend.originalRoom.corridor_face_abs || "",
          };
          if (_doorSeeds.length) _rvPayload.door_seeds = _doorSeeds;
          var resp = await fetch("/api/room/reanalyze", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(_rvPayload),
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

          // D-126 : toggle "Lock walls" — quand coché, la géométrie
          // (bbox_px, dims, corridor_face_abs, overlay) reste figée ;
          // seuls openings / windows / doors / hits sont adoptés. Quand
          // décoché, on a re-détecté les murs → le flag user-edited est
          // reset (la géométrie repart du scan backend).
          var lockWallsEl = document.getElementById("rvLockWalls");
          var lockWalls = !!(lockWallsEl && lockWallsEl.checked);
          if (!lockWalls) state.walls_user_edited = false;
          // D-135 : un scan (unitaire) suffit à armer le flag global Floor ;
          // la toolbar Floor reflète l'état au retour sur cet onglet.
          if (window.ingState) {
            window.ingState.firstScanDone = true;
            var ingLwAfter = document.getElementById("ingLockWalls");
            if (ingLwAfter) ingLwAfter.checked = true;
          }

          if (canon.corridor_face && !lockWalls) {
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
          // D-204: doors[] is exclusively typed. door_seeds untouched.
          var newDoors = preservedDoors.length ? []
            : (canon.doors || []).filter(function (d) { return !!d.face; });

          if (canon.hits) state.room_hits = canon.hits;
          if (canon.coarse_hits) state.room_coarse_hits = canon.coarse_hits;
          if (canon.pillar_hits) state.room_pillar_hits = canon.pillar_hits;
          if (canon.seed_cm) state.room_seed_cm = canon.seed_cm;
          if (canon.auto_door_masks) state.room_auto_door_masks = canon.auto_door_masks;
          // Merge auto exclusion zones: keep manual, replace auto.
          if (Array.isArray(canon.auto_exclusion_zones)) {
            var manualExcl = (state.room_exclusions || []).filter(function(z) {
              return z.origin !== 'auto';
            });
            state.room_exclusions = manualExcl.concat(
              canon.auto_exclusion_zones);
          }

          if (canon.bbox_px && ingst.scale && !lockWalls) {
            if (canon.width_cm > 0 && canon.depth_cm > 0) {
              state.room_width_cm = canon.width_cm;
              state.room_depth_cm = canon.depth_cm;
            }
            // D-126 rider : re-analyze sans Lock = revient à la détection
            // automatique, donc on reset le roomRenderOffset du resize
            // manuel éventuel. Sans ce reset, les nouvelles dims s'appliquent
            // mais la pièce reste visuellement décalée par le resize, ce
            // qui la fait déborder hors de l'overlay.
            state.roomRenderOffset = { x_cm: 0, y_cm: 0 };
            // Re-anchor zones to preserve their absolute image position
            // across bbox / corridor_face changes (fix symptôme 2 D-124).
            // D-127 : on passe effBbox (bbox effectif user, tient compte du
            // resize amend) et non l'origBbox — les coords zones sont
            // relatives au canonical NW user, pas au canonical NW original.
            if (window.reanchorCanonicalZones) {
              var newCf = canon.corridor_face || prevCf || "";
              state.room_exclusions = window.reanchorCanonicalZones(
                state.room_exclusions, effBbox, prevCf,
                canon.bbox_px, newCf, ingst.scale);
              state.room_transparents = window.reanchorCanonicalZones(
                state.room_transparents, effBbox, prevCf,
                canon.bbox_px, newCf, ingst.scale);
            }
            amend.originalRoom.bbox_px = canon.bbox_px;
            amend.originalRoom.width_cm = canon.width_cm;
            amend.originalRoom.depth_cm = canon.depth_cm;
            amend.originalRoom.surface_m2_bbox = parseFloat(
              ((canon.width_cm * canon.depth_cm) / SQ_CM_PER_SQ_M).toFixed(2));
            if (window.fpOverlay && state.overlay) {
              var ov2 = window.fpOverlay;
              state.overlay.offsetX = canon.bbox_px[0] / ov2.pxPerCm;
              state.overlay.offsetY = canon.bbox_px[1] / ov2.pxPerCm;
            }
          }

          // D-129 : clamp des openings/windows/doors acceptées aux dims
          // courantes de state. Lock ON protège le bbox user mais les
          // openings canon peuvent déborder si le backend a détecté un
          // bbox légèrement plus large. Non-Lock : idempotent (dims =
          // canon, openings déjà dans canon frame).
          var _sW = state.room_width_cm || 0;
          var _sD = state.room_depth_cm || 0;
          var clampOd = window.clampOpeningsToDims || function (a) { return a; };
          state.room_windows = clampOd(newWindows.concat(manualW), _sW, _sD);
          state.room_openings = clampOd(newOpenings.concat(manualO), _sW, _sD);
          state.room_doors = clampOd(newDoors.concat(preservedDoors), _sW, _sD);
          _rvCommitFromState();
          if (window.rvUpdateRoomInfo) window.rvUpdateRoomInfo();
        _syncPatternEditorUI();
        } catch (err) {
          alertModal("Rescan failed: " + err.message);
        } finally {
          reanalyzeBtn.disabled = false;
          reanalyzeBtn.textContent = "Rescan";
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
            _getActiveSvg().style.cursor = "crosshair";
            rvTool.placingZoneKind = "exclusion";
            _renderActive();
          } else if (kind === "transparent") {
            rvTool.mode = "placing";
            rvTool.selectedIndex = -1;
            state.selectedExclusion = -1;
            _getActiveSvg().style.cursor = "crosshair";
            rvTool.placingZoneKind = "transparent";
            _renderActive();
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
          _getActiveSvg().style.cursor = "";
        } else {
          rvTool.mode = "placing";
          rvTool.selectedIndex = -1;
          state.selectedExclusion = -1;
          rvBtnAddExclEl.classList.add("active");
          _getActiveSvg().style.cursor = "crosshair";
          _renderActive();
        }
      });
    }

    // D-256: "Add cabinet" button — toggle furnPlacing mode
    var btnAddCabinet = document.getElementById("btnAddCabinet");
    if (btnAddCabinet) {
      btnAddCabinet.addEventListener("click", function () {
        if (!state.amendMode) return;
        if (rvTool.mode === "furnPlacing") {
          rvTool.mode = "idle";
          btnAddCabinet.classList.remove("active");
          rvRemoveGhostRect();
          _getActiveSvg().style.cursor = "";
        } else {
          rvTool.mode = "furnPlacing";
          rvTool._furnOrientation = 0;
          state.selectedFurniture = -1;
          btnAddCabinet.classList.add("active");
          _getActiveSvg().style.cursor = "crosshair";
          _renderActive();
        }
      });
    }

    // Helper: rebuild full Room DSL from state and push to backend.
    // Preserves `origin` across the DSL round-trip by caching per
    // (type, face, offset, width) key — the DSL serializes these 3 values
    // exactly, so the cache key is stable.
    function _rvCommitFromState() {
      // v0.5.42 DIAG TEMPORAIRE (room-shift) : capture avant/après commit.
      // Gated --dev, affiché en barre de statut (sans DevTools). À retirer.
      var _diag = !!(window.APP_CONFIG && window.APP_CONFIG.dev_mode);
      var _snap = function () {
        var rro = state.roomRenderOffset || { x_cm: 0, y_cm: 0 };
        var items = []
          .concat((state.room_doors || []).map(function (d) {
            return "D:" + d.face + "@" + d.offset_cm; }))
          .concat((state.room_windows || []).map(function (w) {
            return "W:" + w.face + "@" + w.offset_cm; }));
        return "cf=" + (state.corridor_face_abs || "-")
          + " dims=" + state.room_width_cm + "x" + state.room_depth_cm
          + " rro=(" + rro.x_cm + "," + rro.y_cm + ") [" + items.join(" ") + "]";
      };
      var _before = _diag ? _snap() : "";
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
      var el = _getActiveDslEl();
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
        _syncPatternEditorUI();
        if (typeof markDirty === "function") markDirty();
        if (_diag) {
          var msg = "DIAG room-shift | BEFORE " + _before + " | AFTER " + _snap();
          console.log(msg);
          if (typeof setStatus === "function") setStatus(msg);
        }
      });
    }

    // Canvas mousedown: start drawing, drag, or resize (both canvases)
    function _onRoomCanvasMousedown(e) {
      // PE canvas: allow door interactions without roomAmendMode
      var isPeCanvas = peCvEl && (e.currentTarget === peCvEl);
      if (!state.roomAmendMode && !isPeCanvas) return;
      if (e.button !== 0) return;

      var openingDelete = e.target.closest("[data-opening-delete]");
      var openingResize = e.target.closest("[data-opening-resize]");
      var openingHandle = e.target.closest("[data-opening-handle]");
      var doorHinge = e.target.closest("[data-door-hinge]");
      var doorDir = e.target.closest("[data-door-dir]");
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
          rvTool._dragStartPos = { x_cm: tT.x_cm, y_cm: tT.y_cm };
          rvTool.mode = "transpDragging";
        } else {
          rvTool.selectedIndex = tIdx;
          rvTool.mode = "transpSelected";
          state.selectedTransparent = tIdx;
          state.selectedExclusion = -1;
          state.selectedOpening = null;
          _renderActive();
        }
        e.preventDefault(); e.stopPropagation();
        return;
      }

      // Opening delete badge → remove the opening from state and commit.
      // D-215: block in amend-layout mode (openings are read-only)
      if (openingDelete && state.amendMode) {
        e.preventDefault(); e.stopPropagation(); return;
      }
      if (openingDelete) {
        var dparts = openingDelete.dataset.openingDelete.split("-");
        var dtype = dparts[0], didx = parseInt(dparts[1], 10);
        var darr = _getOpeningArray(dtype);
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

      // Door hinge badge → toggle L/R
      // D-215: block in amend-layout mode
      if (doorHinge && state.amendMode) {
        e.preventDefault(); e.stopPropagation(); return;
      }
      if (doorHinge) {
        var hIdx = parseInt(doorHinge.dataset.doorHinge, 10);
        var hDoor = (state.room_doors || [])[hIdx];
        if (hDoor) {
          hDoor.hinge_side = (hDoor.hinge_side === "right") ? "left" : "right";
          hDoor.origin = "manual";
          _rvCommitFromState();
        }
        e.preventDefault(); e.stopPropagation();
        if (typeof e.stopImmediatePropagation === "function") e.stopImmediatePropagation();
        return;
      }
      // Door direction badge → toggle INT/EXT
      // D-215: block in amend-layout mode
      if (doorDir && state.amendMode) {
        e.preventDefault(); e.stopPropagation(); return;
      }
      if (doorDir) {
        var dIdx = parseInt(doorDir.dataset.doorDir, 10);
        var dDoor = (state.room_doors || [])[dIdx];
        if (dDoor) {
          dDoor.opens_inward = !dDoor.opens_inward;
          dDoor.origin = "manual";
          _rvCommitFromState();
        }
        e.preventDefault(); e.stopPropagation();
        if (typeof e.stopImmediatePropagation === "function") e.stopImmediatePropagation();
        return;
      }

      // Opening resize handle (square) → start width resize.
      // D-215: block in amend-layout mode
      if (openingResize && state.amendMode) {
        e.preventDefault(); e.stopPropagation(); return;
      }
      if (openingResize) {
        var rparts = openingResize.dataset.openingResize.split("-");
        var rtype = rparts[0], ridx = parseInt(rparts[1], 10), rend = rparts[2];
        var rarr = _getOpeningArray(rtype);
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
        _renderActive();
        e.preventDefault(); e.stopPropagation();
        if (typeof e.stopImmediatePropagation === "function") e.stopImmediatePropagation();
        return;
      }

      // Opening handle → select + start move along its wall (or dblclick → edit).
      // D-215: block in amend-layout mode (covers both drag and dblclick edit)
      if (openingHandle && state.amendMode) {
        e.preventDefault(); e.stopPropagation(); return;
      }
      if (openingHandle) {
        var parts = openingHandle.dataset.openingHandle.split("-");
        var otype = parts[0], oidx = parseInt(parts[1], 10);
        var oarr = _getOpeningArray(otype);
        var op = oarr && oarr[oidx];
        if (!op) return;
        // Double-click detection (timing-based, SVG is re-rendered between clicks)
        if (_checkOpeningDblClick(otype, oidx)) {
          _showInlineEdit(otype, oidx, e.clientX, e.clientY);
          e.preventDefault(); e.stopPropagation();
          return;
        }
        state.selectedOpening = { type: otype, index: oidx };
        state.selectedExclusion = -1;
        rvTool.selectedIndex = -1;
        var pt0 = rvScreenToRoomCm(e);
        rvTool.mode = "openingMoving";
        rvTool.openingMove = {
          type: otype, index: oidx, face: op.face, _startFace: op.face,
          startOffset: op.offset_cm || 0,
          widthAlong: op.width_cm || 0,
          mouseStart: pt0,
        };
        state.isPanning = false;
        _renderActive();
        e.preventDefault(); e.stopPropagation();
        if (typeof e.stopImmediatePropagation === "function") e.stopImmediatePropagation();
        return;
      }

      // Room corner handle click → start resizing the whole room (D-99).
      // Snapshot contents deep so mousemove recomputes translations cleanly.
      if (roomHandleTarget !== null) {
        // D-292: ignoreOffset=true → raw mouse frame (no feedback with the
        // resize-driven roomRenderOffset).
        var roomPt = rvScreenToRoomCm(e, ROOM_RESIZE_SNAP_CM, true);
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

      // D-256: Furniture (cabinet) — click to deposit
      if (rvTool.mode === "furnPlacing") {
        var fpt = rvScreenToRoomCm(e);
        var fdims = window._furnitureEffectiveDims({ orientation: rvTool._furnOrientation || 0 });
        var fx = Math.max(0, Math.min(state.room_width_cm - fdims.width_cm, fpt.x_cm));
        var fy = Math.max(0, Math.min(state.room_depth_cm - fdims.depth_cm, fpt.y_cm));
        state.furniture = state.furniture || [];
        state.furniture.push({
          type: "CABINET", x_cm: fx, y_cm: fy,
          orientation: rvTool._furnOrientation || 0,
        });
        state.selectedFurniture = state.furniture.length - 1;
        state.selectedBlock = -1;
        state.selectedExclusion = -1;
        rvTool.mode = "furnSelected";
        rvRemoveGhostRect();
        _getActiveSvg().style.cursor = "";
        var _abtn = document.getElementById("btnAddCabinet");
        if (_abtn) _abtn.classList.remove("active");
        if (typeof markDirty === "function") markDirty();
        _renderActive();
        e.preventDefault();
        e.stopPropagation();
        if (typeof e.stopImmediatePropagation === "function") e.stopImmediatePropagation();
        return;
      }

      // D-256: Furniture target — select + start drag in one motion
      var furnTarget = e.target.closest("[data-furn]") ||
        e.target.closest("[data-furn-rotate]") ||
        e.target.closest("[data-furn-delete]");
      if (furnTarget !== null && state.amendMode) {
        // Handle rotate/delete pictogram clicks
        var rotTarget = e.target.closest("[data-furn-rotate]");
        var delTarget = e.target.closest("[data-furn-delete]");
        if (rotTarget) {
          var rfi = parseInt(rotTarget.dataset.furnRotate, 10);
          var rItem = (state.furniture || [])[rfi];
          if (rItem) {
            rItem.orientation = (rItem.orientation || 0) === 0 ? 90 : 0;
            if (typeof markDirty === "function") markDirty();
            _renderActive();
          }
          e.preventDefault(); e.stopPropagation();
          if (typeof e.stopImmediatePropagation === "function") e.stopImmediatePropagation();
          return;
        }
        if (delTarget) {
          var dfi = parseInt(delTarget.dataset.furnDelete, 10);
          state.furniture.splice(dfi, 1);
          state.selectedFurniture = -1;
          rvTool.mode = "idle";
          if (typeof markDirty === "function") markDirty();
          _renderActive();
          e.preventDefault(); e.stopPropagation();
          if (typeof e.stopImmediatePropagation === "function") e.stopImmediatePropagation();
          return;
        }
        var fIdx = parseInt(furnTarget.dataset.furn, 10);
        var fItem = (state.furniture || [])[fIdx];
        if (fItem) {
          // Always start drag immediately (select + drag in one motion)
          state.selectedFurniture = fIdx;
          state.selectedBlock = -1;
          state.selectedExclusion = -1;
          var fpt2 = rvScreenToRoomCm(e);
          var fdims2 = window._furnitureEffectiveDims(fItem);
          rvTool.dragOffset = {
            dx_cm: fpt2.x_cm - fItem.x_cm,
            dy_cm: fpt2.y_cm - fItem.y_cm,
          };
          rvTool._dragStartPos = { x_cm: fItem.x_cm, y_cm: fItem.y_cm };
          rvTool._furnDragDims = fdims2;
          rvTool.mode = "furnDragging";
          _renderActive();
          e.preventDefault();
          e.stopPropagation();
          if (typeof e.stopImmediatePropagation === "function") e.stopImmediatePropagation();
          return;
        }
      }

      // D-267: Block drag — select + start drag in one motion
      // Active in amend (Office, free drag) and PE (lock-aware drag).
      var _peActiveDrag = _isPatternEditorActive() && !state.roomAmendMode;
      if (state.amendMode || _peActiveDrag) {
        var blockTarget = e.target.closest("[data-row][data-block]");
        if (blockTarget) {
          var bri = parseInt(blockTarget.dataset.row, 10);
          var bbi = parseInt(blockTarget.dataset.block, 10);
          var bRow = (state.rows || [])[bri];
          var bBlk = bRow && bRow.blocks && bRow.blocks[bbi];
          if (bBlk) {
            state.selectedRow = bri;
            state.selectedBlock = bbi;
            state.selectedExclusion = -1;
            state.selectedFurniture = -1;
            // Compute absolute position of this block
            var bPositions = computeBlockPositions();
            var bPos = null;
            for (var bpi = 0; bpi < bPositions.length; bpi++) {
              if (bPositions[bpi].rowIdx === bri &&
                  bPositions[bpi].blockIdx === bbi) {
                bPos = bPositions[bpi]; break;
              }
            }
            if (bPos) {
              var bpt = rvScreenToRoomCm(e);
              rvTool.dragOffset = {
                dx_cm: bpt.x_cm - bPos.x_cm,
                dy_cm: bpt.y_cm - bPos.y_cm,
              };
              // D-267: total footprint extents (body + clearance zones) so the
              // drag ghost shows the block's real limits, not just the body.
              var bExt = (typeof blockOuterExtentsCm === "function")
                ? blockOuterExtentsCm(bBlk.type, bBlk.orientation)
                : { w: 0, e: 0, n: 0, s: 0 };
              rvTool._blockDragStart = {
                rowIdx: bri, blockIdx: bbi,
                x_cm: bPos.x_cm, y_cm: bPos.y_cm,
                w_cm: bPos.w_cm, h_cm: bPos.h_cm,
                zW: bExt.w, zE: bExt.e, zN: bExt.n, zS: bExt.s,
              };
              // PE lock-aware drag: capture valid sticks at mousedown so
              // locked axes stay fixed for the entire gesture.
              if (_peActiveDrag && typeof faceTouchesWall === "function") {
                var stks = bBlk.sticks || [];
                var lockX = false, lockY = false;
                for (var si = 0; si < stks.length; si++) {
                  if (faceTouchesWall(bri, bbi, stks[si])) {
                    if (stks[si] === "E" || stks[si] === "W") lockX = true;
                    if (stks[si] === "N" || stks[si] === "S") lockY = true;
                  }
                }
                rvTool._blockDragStart.lockedAxes = { x: lockX, y: lockY };
              } else {
                rvTool._blockDragStart.lockedAxes = null;
              }
              // Store ALL block positions for rebuild at release
              rvTool._allBlockPositions = bPositions;
              rvTool._blockDragMoved = false;
              rvTool.mode = "blockDragging";
              _renderActive();
              e.preventDefault();
              e.stopPropagation();
              if (typeof e.stopImmediatePropagation === "function")
                e.stopImmediatePropagation();
              return;
            }
          }
        }
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
          ? DEFAULT_WINDOW_WIDTH_CM
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
        _getActiveSvg().style.cursor = "";
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
          rvTool._dragStartPos = { x_cm: excl.x_cm, y_cm: excl.y_cm };
          rvTool.mode = "dragging";
        } else {
          // Select
          rvTool.selectedIndex = idx;
          rvTool.mode = "selected";
          state.selectedExclusion = idx;
          _renderActive();
        }
        e.preventDefault();
        e.stopPropagation();
      }

      // Mousedown on empty area: deselect any selected opening
      if (!exclTarget && !transpTarget && !transpHandleTarget &&
          !openingHandle && !openingResize && !openingDelete &&
          !doorHinge && !doorDir && !handleTarget && !roomHandleTarget &&
          rvTool.mode === "idle" && state.selectedOpening) {
        state.selectedOpening = null;
        state.selectedExclusion = -1;
        state.selectedTransparent = -1;
        _renderActive();
      }
    }
    if (rvCvEl) rvCvEl.addEventListener("mousedown", _onRoomCanvasMousedown);
    if (peCvEl) peCvEl.addEventListener("mousedown", _onRoomCanvasMousedown);

    // Canvas click: deselect on empty area (both canvases)
    function _onRoomCanvasClick(e) {
      var isPeCanvas2 = peCvEl && (e.currentTarget === peCvEl);
      if (!state.roomAmendMode && !isPeCanvas2 && !state.amendMode) return;
      if (rvTool.mode === "placing" || rvTool.mode === "drawing" ||
          rvTool.mode === "furnPlacing") return;
      var exclTarget = e.target.closest("[data-excl]");
      var openingTarget = e.target.closest("[data-opening-handle]") ||
        e.target.closest("[data-opening-delete]") ||
        e.target.closest("[data-opening-resize]") ||
        e.target.closest("[data-door-hinge]") ||
        e.target.closest("[data-door-dir]");
      var transpTarget2 = e.target.closest("[data-transp]") ||
        e.target.closest("[data-transp-handle]");
      var furnTarget2 = e.target.closest("[data-furn]") ||
        e.target.closest("[data-furn-rotate]") ||
        e.target.closest("[data-furn-delete]");
      if (!exclTarget && !openingTarget && !transpTarget2 && !furnTarget2 &&
          (rvTool.mode === "selected" || rvTool.mode === "transpSelected" ||
           rvTool.mode === "furnSelected" || rvTool.mode === "idle")) {
        rvTool.selectedIndex = -1;
        rvTool.mode = "idle";
        state.selectedExclusion = -1;
        state.selectedOpening = null;
        state.selectedTransparent = -1;
        state.selectedFurniture = -1;
        _renderActive();
      }
    }
    if (rvCvEl) rvCvEl.addEventListener("click", _onRoomCanvasClick);
    if (peCvEl) peCvEl.addEventListener("click", _onRoomCanvasClick);

    // Delete key → remove selected opening (works in PE without roomAmendMode).
    document.addEventListener("keydown", function (e) {
      if (!state.roomAmendMode && !state.selectedOpening) return;
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

    // Double-click on opening → inline edit of offset and width (exact values)
    // Native dblclick does not fire reliably because render() recreates SVG
    // elements between the two clicks. Use a timing-based approach instead.
    var _openingDblClick = { type: null, index: -1, time: 0 };
    function _checkOpeningDblClick(type, index) {
      var now = Date.now();
      if (_openingDblClick.type === type &&
          _openingDblClick.index === index &&
          (now - _openingDblClick.time) < 400) {
        _openingDblClick.type = null;
        _openingDblClick.index = -1;
        _openingDblClick.time = 0;
        return true;
      }
      _openingDblClick.type = type;
      _openingDblClick.index = index;
      _openingDblClick.time = now;
      return false;
    }
    function _showInlineEdit(etype, eidx, clientX, clientY) {
      var earr = _getOpeningArray(etype);
      var eop = earr && earr[eidx];
      if (!eop) return;
      // Remove any existing edit popup
      var existing = document.getElementById("rvInlineEdit");
      if (existing) existing.remove();
      // Create popup near the mouse
      var popup = document.createElement("div");
      popup.id = "rvInlineEdit";
      popup.style.cssText = "position:fixed;z-index:200;background:var(--surface);" +
        "border:1px solid var(--border);padding:6px 8px;font-size:11px;" +
        "display:flex;gap:6px;align-items:center;box-shadow:0 2px 8px rgba(0,0,0,0.3);";
      popup.style.left = clientX + "px";
      popup.style.top = (clientY + 8) + "px";
      popup.innerHTML =
        '<label>Offset<input type="number" id="rvEditOff" value="' +
        Math.round(eop.offset_cm || 0) +
        '" min="0" style="width:55px;margin-left:2px;font-size:11px;' +
        'background:var(--surface);color:var(--text);border:1px solid var(--border);padding:2px 3px;"></label>' +
        '<label>Width<input type="number" id="rvEditW" value="' +
        Math.round(eop.width_cm || 0) +
        '" min="1" style="width:55px;margin-left:2px;font-size:11px;' +
        'background:var(--surface);color:var(--text);border:1px solid var(--border);padding:2px 3px;"></label>' +
        '<button id="rvEditOk" class="btn btn-ok" style="padding:2px 8px;font-size:11px;">OK</button>' +
        '<button id="rvEditCancel" class="btn" style="padding:2px 8px;font-size:11px;">Cancel</button>';
      document.body.appendChild(popup);
      document.getElementById("rvEditOff").focus();
      function _apply() {
        var newOff = parseInt(document.getElementById("rvEditOff").value, 10);
        var newW = parseInt(document.getElementById("rvEditW").value, 10);
        if (isFinite(newOff) && isFinite(newW) && newW > 0) {
          var wallLen = (eop.face === "north" || eop.face === "south")
            ? state.room_width_cm : state.room_depth_cm;
          eop.offset_cm = Math.max(0, Math.min(wallLen - newW, newOff));
          eop.width_cm = Math.min(newW, wallLen);
          eop.origin = "manual";
          _rvCommitFromState();
        }
        popup.remove();
      }
      function _cancel() { popup.remove(); }
      document.getElementById("rvEditOk").addEventListener("click", _apply);
      document.getElementById("rvEditCancel").addEventListener("click", _cancel);
      popup.addEventListener("keydown", function (ke) {
        if (ke.key === "Enter") { ke.preventDefault(); _apply(); }
        if (ke.key === "Escape") { ke.preventDefault(); _cancel(); }
      });
    }

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
        _renderActive();
        return;
      }
      if (rvTool.mode === "transpDragging" && rvTool.dragOffset) {
        var tpt2 = rvScreenToRoomCm(e);
        var tzDrag = state.room_transparents[rvTool.selectedIndex];
        if (!tzDrag) return;
        _dragRectClamped(tzDrag, tpt2, rvTool.dragOffset);
        _renderActive();
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
        _renderActive();
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
        // Check if mouse is closer to a different wall → change face
        var nearest = _nearestFaceAndOffset(pt.x_cm, pt.y_cm);
        if (nearest.face !== om.face) {
          var newWallLen = (nearest.face === "north" || nearest.face === "south")
            ? state.room_width_cm : state.room_depth_cm;
          var clampedW = Math.min(om.widthAlong, newWallLen);
          var newOff = Math.max(0, Math.min(newWallLen - clampedW,
            nearest.offset_cm - clampedW / 2));
          op.face = nearest.face;
          op.offset_cm = newOff;
          op.width_cm = clampedW;
          om.face = nearest.face;
          om.startOffset = newOff;
          om.widthAlong = clampedW;
          om.mouseStart = pt;
        } else {
          var axis = (om.face === "north" || om.face === "south") ? "x_cm" : "y_cm";
          var delta = pt[axis] - om.mouseStart[axis];
          var wallLen = (om.face === "north" || om.face === "south")
            ? state.room_width_cm : state.room_depth_cm;
          var maxOff = Math.max(0, wallLen - om.widthAlong);
          op.offset_cm = Math.max(0, Math.min(maxOff, om.startOffset + delta));
        }
        op.origin = "manual";
        _renderActive();
        return;
      }
      // D-256 Lot 2: furnPlacing — ghost follows cursor
      if (rvTool.mode === "furnPlacing") {
        var fpt3 = rvScreenToRoomCm(e);
        var fdims3 = window._furnitureEffectiveDims({ orientation: rvTool._furnOrientation || 0 });
        var fx3 = Math.max(0, Math.min(state.room_width_cm - fdims3.width_cm, fpt3.x_cm));
        var fy3 = Math.max(0, Math.min(state.room_depth_cm - fdims3.depth_cm, fpt3.y_cm));
        var fOffX = state.roomRenderOffset ? state.roomRenderOffset.x_cm : 0;
        var fOffY = state.roomRenderOffset ? state.roomRenderOffset.y_cm : 0;
        rvShowGhostRect(
          (fx3 + fOffX) * SCALE, (fy3 + fOffY) * SCALE,
          fdims3.width_cm * SCALE, fdims3.depth_cm * SCALE);
        return;
      }
      // D-256: furnDragging — move cabinet
      if (rvTool.mode === "furnDragging" && rvTool.dragOffset) {
        var fpt4 = rvScreenToRoomCm(e);
        var fIdx4 = state.selectedFurniture;
        var fItem4 = (state.furniture || [])[fIdx4];
        if (!fItem4) return;
        var fdims4 = rvTool._furnDragDims || window._furnitureEffectiveDims(fItem4);
        var fProxy = { x_cm: fItem4.x_cm, y_cm: fItem4.y_cm,
                       width_cm: fdims4.width_cm, depth_cm: fdims4.depth_cm };
        _dragRectClamped(fProxy, fpt4, rvTool.dragOffset);
        fItem4.x_cm = fProxy.x_cm;
        fItem4.y_cm = fProxy.y_cm;
        _renderActive();
        return;
      }
      // D-267 + D-268: blockDragging — free drag of a workstation block
      if (rvTool.mode === "blockDragging" && rvTool.dragOffset) {
        var bpt2 = rvScreenToRoomCm(e);
        var bds = rvTool._blockDragStart;
        if (!bds) return;
        // D-268: free position — no clamp to room bounds
        var newBX = bpt2.x_cm - rvTool.dragOffset.dx_cm;
        var newBY = bpt2.y_cm - rvTool.dragOffset.dy_cm;
        // Snap to grid
        newBX = Math.round(newBX / GRID_STEP_CM) * GRID_STEP_CM;
        newBY = Math.round(newBY / GRID_STEP_CM) * GRID_STEP_CM;
        // D-268 + D-316: soft wall snap — attract the EMPRISE edge (body +
        // outer extent) to the wall from INSIDE only, so the lock position
        // (emprise touching wall, per faceTouchesWall) is the magnetic target.
        var zW = bds.zW || 0, zE = bds.zE || 0, zN = bds.zN || 0, zS = bds.zS || 0;
        var wEdge = newBX - zW;
        var nEdge = newBY - zN;
        var eEdge = newBX + bds.w_cm + zE;
        var sEdge = newBY + bds.h_cm + zS;
        if (wEdge > 0 && wEdge <= GRID_STEP_CM) newBX = zW;
        if (nEdge > 0 && nEdge <= GRID_STEP_CM) newBY = zN;
        if (eEdge < state.room_width_cm &&
            eEdge >= state.room_width_cm - GRID_STEP_CM)
          newBX = state.room_width_cm - bds.w_cm - zE;
        if (sEdge < state.room_depth_cm &&
            sEdge >= state.room_depth_cm - GRID_STEP_CM)
          newBY = state.room_depth_cm - bds.h_cm - zS;
        // PE lock-aware: freeze locked axes to origin (after snap, last word)
        if (bds.lockedAxes) {
          if (bds.lockedAxes.x) newBX = bds.x_cm;
          if (bds.lockedAxes.y) newBY = bds.y_cm;
        }
        // Update stored drag position for ghost rendering
        rvTool._blockDragCurrent = { x_cm: newBX, y_cm: newBY };
        rvTool._blockDragMoved = true;
        // Show ghost rect at dragged position — total footprint (body +
        // clearance zones) so the user sees the block's real limits (D-267).
        var bdOffX = state.roomRenderOffset ? state.roomRenderOffset.x_cm : 0;
        var bdOffY = state.roomRenderOffset ? state.roomRenderOffset.y_cm : 0;
        // Same total footprint, colour and dash as the selection box (editor.js).
        // Red when the dragged position conflicts (emprise overlap or desk on
        // a door exclusion zone).
        var ghostConflict = (typeof blockHasPlacementConflict === "function")
          ? blockHasPlacementConflict(bds.rowIdx, bds.blockIdx,
              { x_cm: newBX, y_cm: newBY })
          : false;
        rvShowGhostRect(
          (newBX - zW + bdOffX) * SCALE, (newBY - zN + bdOffY) * SCALE,
          (bds.w_cm + zW + zE) * SCALE, (bds.h_cm + zN + zS) * SCALE,
          ghostConflict ? COLOR_DANGER : COLOR_GOOD, "6 3", "1.5");
        return;
      }
      if (rvTool.mode === "drawing" && rvTool.drawStart) {
        var pt = rvScreenToRoomCm(e);
        var ds = rvTool.drawStart;
        // ds/pt are room cm (rvScreenToRoomCm already subtracted the
        // roomRenderOffset). To draw the ghost in SVG units, add the offset
        // back — exactly mirroring render()'s roomX = offset*SCALE — otherwise
        // the ghost is shifted while a resize offset is pending (not saved).
        var offX = state.roomRenderOffset ? state.roomRenderOffset.x_cm : 0;
        var offY = state.roomRenderOffset ? state.roomRenderOffset.y_cm : 0;
        var x_svg = (Math.min(ds.x_cm, pt.x_cm) + offX) * SCALE;
        var y_svg = (Math.min(ds.y_cm, pt.y_cm) + offY) * SCALE;
        var w_svg = Math.abs(pt.x_cm - ds.x_cm) * SCALE;
        var h_svg = Math.abs(pt.y_cm - ds.y_cm) * SCALE;
        rvShowGhostRect(x_svg, y_svg, w_svg, h_svg);
        return;
      }
      if (rvTool.mode === "dragging" && rvTool.dragOffset) {
        var pt3 = rvScreenToRoomCm(e);
        var excl3 = state.room_exclusions[rvTool.selectedIndex];
        if (!excl3) return;
        _dragRectClamped(excl3, pt3, rvTool.dragOffset);
        _renderActive();
        return;
      }
      if (rvTool.mode === "roomResizing" && rvTool.roomResizeStart) {
        // D-292: ignoreOffset=true → measure the raw mouse delta against the
        // drag-start frame (no feedback loop with roomRenderOffset).
        var ptRoom = rvScreenToRoomCm(e, ROOM_RESIZE_SNAP_CM, true);
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
        _renderActive();
        if (window.rvUpdateRoomInfo) window.rvUpdateRoomInfo();
        _syncPatternEditorUI();
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
        _renderActive();
      }
    });

    // document mouseup: commit drawing or drag
    document.addEventListener("mouseup", function (e) {
      // D-267: commit block drag — infer rows from positions
      if (rvTool.mode === "blockDragging") {
        rvRemoveGhostRect();
        var bds2 = rvTool._blockDragStart;
        var moved = rvTool._blockDragMoved && rvTool._blockDragCurrent;
        rvTool.mode = "idle";
        rvTool.dragOffset = null;
        if (!moved || !bds2) {
          // Click without move — just select, no inference
          rvTool._blockDragStart = null;
          rvTool._allBlockPositions = null;
          rvTool._blockDragCurrent = null;
          _renderActive();
          if (typeof updateRowList === "function") updateRowList();
          return;
        }
        // Build flat block list with absolute positions
        var allPos = rvTool._allBlockPositions || [];
        var flatBlocks = [];
        for (var bpi2 = 0; bpi2 < allPos.length; bpi2++) {
          var bp = allPos[bpi2];
          var bSrc = state.rows[bp.rowIdx].blocks[bp.blockIdx];
          var bCopy = {};
          for (var bk in bSrc) {
            if (Object.prototype.hasOwnProperty.call(bSrc, bk)) bCopy[bk] = bSrc[bk];
          }
          // Override with absolute position
          if (bp.rowIdx === bds2.rowIdx && bp.blockIdx === bds2.blockIdx) {
            bCopy.x_cm = rvTool._blockDragCurrent.x_cm;
            bCopy.y_cm = rvTool._blockDragCurrent.y_cm;
          } else {
            bCopy.x_cm = bp.x_cm;
            bCopy.y_cm = bp.y_cm;
          }
          flatBlocks.push(bCopy);
        }
        rvTool._blockDragStart = null;
        rvTool._allBlockPositions = null;
        rvTool._blockDragCurrent = null;
        rvTool._blockDragMoved = false;
        // Suppress the click event that fires after mouseup on the same SVG
        window._blockDragJustReleased = true;
        // Call server to infer rows
        fetch("/api/patterns/infer-rows", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ blocks: flatBlocks }),
        })
          .then(function (r) { return r.json(); })
          .then(function (data) {
            if (data.rows) {
              state.rows = data.rows;
              state.row_gaps_cm = data.row_gaps_cm || [];
              state.selectedBlock = -1;
              state.selectedRow = -1;
              if (typeof markDirty === "function") markDirty();
              render();
              if (typeof updateDSL === "function") updateDSL();
              if (typeof updateRowList === "function") updateRowList();
            }
          })
          .catch(function (err) {
            console.warn("infer-rows failed:", err);
          });
        return;
      }
      // D-256 Lot 2: commit furniture drag
      if (rvTool.mode === "furnDragging") {
        rvTool.mode = "furnSelected";
        rvTool.dragOffset = null;
        rvTool._furnDragDims = null;
        if (typeof markDirty === "function") markDirty();
        _renderActive();
        return;
      }
      if (rvTool.mode === "transpDragging" || rvTool.mode === "transpResizing") {
        rvTool.mode = "transpSelected";
        rvTool.dragOffset = null;
        rvTool.resizeStart = null;
        _rvCommitFromState();
        if (typeof canonicalizeState === "function") canonicalizeState();
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
        _getActiveSvg().style.cursor = "";
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
        // User-driven wall change → mark the room so the next Rescan defaults
        // to Lock walls (preserve the hand-tuned geometry).
        state.walls_user_edited = true;
        var lwEl = document.getElementById("rvLockWalls");
        if (lwEl) lwEl.checked = true;
        // Commit: regenerate the whole DSL from current state (since a
        // corner drag may have shifted many content offsets) and re-apply.
        var dslEl = _getActiveDslEl();
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
      if (e.target.tagName === "INPUT" || e.target.tagName === "TEXTAREA") return;

      // D-256 Lot 2: Furniture interactions (Amend Layout mode)
      if (state.amendMode) {
        // Escape — cancel placing or deselect
        if (e.key === "Escape") {
          if (rvTool.mode === "furnPlacing") {
            rvTool.mode = "idle";
            rvRemoveGhostRect();
            _getActiveSvg().style.cursor = "";
            var _ab = document.getElementById("btnAddCabinet");
            if (_ab) _ab.classList.remove("active");
            e.preventDefault();
            return;
          }
          // D-267: cancel block drag
          if (rvTool.mode === "blockDragging") {
            rvRemoveGhostRect();
            rvTool.mode = "idle";
            rvTool.dragOffset = null;
            rvTool._blockDragStart = null;
            rvTool._allBlockPositions = null;
            rvTool._blockDragCurrent = null;
            rvTool._blockDragMoved = false;
            _renderActive();
            e.preventDefault();
            return;
          }
          if (rvTool.mode === "furnDragging" && rvTool.dragOffset) {
            var fDrag = (state.furniture || [])[state.selectedFurniture];
            if (fDrag && rvTool._dragStartPos) {
              fDrag.x_cm = rvTool._dragStartPos.x_cm;
              fDrag.y_cm = rvTool._dragStartPos.y_cm;
            }
            rvTool.mode = "furnSelected";
            rvTool.dragOffset = null;
            _renderActive();
            e.preventDefault();
            return;
          }
          if (rvTool.mode === "furnSelected") {
            state.selectedFurniture = -1;
            rvTool.mode = "idle";
            _renderActive();
            e.preventDefault();
            return;
          }
        }
        // R key — rotate selected cabinet (capture phase — always fires)
        if ((e.key === "r" || e.key === "R") && !e.ctrlKey && !e.metaKey) {
          if (rvTool.mode === "furnPlacing") {
            rvTool._furnOrientation = (rvTool._furnOrientation || 0) === 0 ? 90 : 0;
            e.preventDefault();
            if (typeof e.stopImmediatePropagation === "function") e.stopImmediatePropagation();
            return;
          }
          if (state.selectedFurniture >= 0) {
            var fRot = (state.furniture || [])[state.selectedFurniture];
            if (fRot) {
              fRot.orientation = (fRot.orientation || 0) === 0 ? 90 : 0;
              if (typeof markDirty === "function") markDirty();
              _renderActive();
              e.preventDefault();
              if (typeof e.stopImmediatePropagation === "function") e.stopImmediatePropagation();
              return;
            }
          }
        }
        // Delete / Backspace — remove selected cabinet
        if ((e.key === "Delete" || e.key === "Backspace") &&
            state.selectedFurniture >= 0) {
          state.furniture.splice(state.selectedFurniture, 1);
          state.selectedFurniture = -1;
          rvTool.mode = "idle";
          if (typeof markDirty === "function") markDirty();
          _renderActive();
          e.preventDefault();
          return;
        }
        // Arrow keys — move selected cabinet
        if (state.selectedFurniture >= 0 &&
            (e.key === "ArrowLeft" || e.key === "ArrowRight" ||
             e.key === "ArrowUp" || e.key === "ArrowDown")) {
          var fMov = (state.furniture || [])[state.selectedFurniture];
          if (fMov) {
            e.preventDefault();
            if (typeof e.stopImmediatePropagation === "function") e.stopImmediatePropagation();
            var fStep = e.shiftKey ? GRID_STEP_CM * ARROW_KEY_SHIFT_MULTIPLIER : GRID_STEP_CM;
            var fDims = window._furnitureEffectiveDims(fMov);
            var fProxy2 = { x_cm: fMov.x_cm, y_cm: fMov.y_cm,
                            width_cm: fDims.width_cm, depth_cm: fDims.depth_cm };
            _arrowMoveRect(fProxy2, e.key, fStep);
            fMov.x_cm = fProxy2.x_cm;
            fMov.y_cm = fProxy2.y_cm;
            if (typeof markDirty === "function") markDirty();
            _renderActive();
            return;
          }
        }
      }

      if (!state.roomAmendMode) return;

      // Arrow keys: move the selected exclusion (Shift = 5× step)
      if (rvTool.mode === "selected" && rvTool.selectedIndex >= 0 &&
          (e.key === "ArrowLeft" || e.key === "ArrowRight" ||
           e.key === "ArrowUp" || e.key === "ArrowDown")) {
        e.preventDefault();
        // Stop other handlers (floor_plan.js room nav, editor.js block nav)
        // from firing on this event.
        if (typeof e.stopImmediatePropagation === "function") e.stopImmediatePropagation();
        var step = e.shiftKey ? GRID_STEP_CM * ARROW_KEY_SHIFT_MULTIPLIER : GRID_STEP_CM;
        var idxK = rvTool.selectedIndex;
        var exclK = state.room_exclusions[idxK];
        if (!exclK) return;
        _arrowMoveRect(exclK, e.key, step);
        rvDslReplaceExcl(idxK, exclK.x_cm, exclK.y_cm, exclK.width_cm, exclK.depth_cm);
        _renderActive();
        return;
      }

      if (e.key === "Escape") {
        e.preventDefault();
        // Cancel in-progress opening move: restore original offset/face
        if (rvTool.mode === "openingMoving" && rvTool.openingMove) {
          var om = rvTool.openingMove;
          var arr = _getOpeningArray(om.type);
          var op = arr && arr[om.index];
          if (op) {
            op.offset_cm = om.startOffset;
            op.width_cm = om.widthAlong;
            op.face = om._startFace || om.face;
          }
          rvTool.mode = "idle";
          rvTool.openingMove = null;
          _renderActive();
          return;
        }
        // Cancel in-progress opening resize: restore original offset/width
        if (rvTool.mode === "openingResizing" && rvTool.openingResize) {
          var or2 = rvTool.openingResize;
          var arr2 = _getOpeningArray(or2.type);
          var op2 = arr2 && arr2[or2.index];
          if (op2) {
            op2.offset_cm = or2.startOffset;
            op2.width_cm = or2.startWidth;
          }
          rvTool.mode = "idle";
          rvTool.openingResize = null;
          _renderActive();
          return;
        }
        // Cancel in-progress exclusion drag
        if (rvTool.mode === "dragging" && rvTool.dragOffset) {
          var excD = state.room_exclusions[rvTool.selectedIndex];
          if (excD && rvTool._dragStartPos) {
            excD.x_cm = rvTool._dragStartPos.x_cm;
            excD.y_cm = rvTool._dragStartPos.y_cm;
          }
          rvTool.mode = "selected";
          rvTool.dragOffset = null;
          _renderActive();
          return;
        }
        // Cancel in-progress transparent drag
        if (rvTool.mode === "transpDragging" && rvTool.dragOffset) {
          var trD = state.room_transparents[rvTool.selectedIndex];
          if (trD && rvTool._dragStartPos) {
            trD.x_cm = rvTool._dragStartPos.x_cm;
            trD.y_cm = rvTool._dragStartPos.y_cm;
          }
          rvTool.mode = "transpSelected";
          rvTool.dragOffset = null;
          _renderActive();
          return;
        }
        if (rvTool.mode === "placing" || rvTool.mode === "drawing") {
          rvRemoveGhostRect();
          rvTool.mode = "idle";
          rvTool.drawStart = null;
          if (rvBtnAddExclEl) rvBtnAddExclEl.classList.remove("active");
          _getActiveSvg().style.cursor = "";
        } else if (rvTool.mode === "selected") {
          rvTool.selectedIndex = -1;
          rvTool.mode = "idle";
          state.selectedExclusion = -1;
          _renderActive();
        }
        return;
      }

      // Enter / Return: deselect (commit, same as clicking outside)
      if ((e.key === "Enter" || e.key === "Return") && rvTool.mode === "selected") {
        e.preventDefault();
        rvTool.selectedIndex = -1;
        rvTool.mode = "idle";
        state.selectedExclusion = -1;
        _renderActive();
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
