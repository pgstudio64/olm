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
        state.room_openings = data.openings || [];
        state.room_exclusions = data.exclusion_zones || [];
        render(document.getElementById("rvCanvas"));
        if (window.rvUpdateRoomInfo) window.rvUpdateRoomInfo();
      } catch (err) { console.error("rvApplyDslAsync:", err); }
    }

    function rvDslAppendExcl(x_cm, y_cm, w_cm, h_cm) {
      var el = document.getElementById("rvRoomDsl");
      var line = "EXCLUSION " + x_cm + " " + y_cm + " " + w_cm + " " + h_cm;
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
      (state.room_openings || []).forEach(function (o) {
        var f = FACE[o.face] || o.face || "?";
        if (o.has_door) {
          var dir = o.opens_inward ? "INT" : "EXT";
          var side = (o.hinge_side === "left") ? "L" : "R";
          dsl += "\nDOOR " + f + " " + (o.offset_cm || 0) + " " + (o.width_cm || 90) + " " + dir + " " + side;
        } else {
          dsl += "\nOPENING " + f + " " + (o.offset_cm || 0) + " " + (o.width_cm || 90);
        }
      });
      (state.room_exclusions || []).forEach(function (z) {
        dsl += "\nEXCLUSION " + (z.x_cm || 0) + " " + (z.y_cm || 0) +
          " " + (z.width_cm || 0) + " " + (z.depth_cm || 0);
      });
      return dsl;
    }

    var rvCvEl = document.getElementById("rvCanvas");
    if (!rvCvEl) return;

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

    // rvCanvas mousedown: start drawing, drag, or resize
    rvCvEl.addEventListener("mousedown", function (e) {
      if (!state.roomAmendMode) return;
      if (e.button !== 0) return;

      var roomHandleTarget = e.target.closest("[data-room-handle]");
      var handleTarget = e.target.closest("[data-excl-handle]");
      var exclTarget = e.target.closest("[data-excl]");

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
      if (!exclTarget && (rvTool.mode === "selected" || rvTool.mode === "idle")) {
        rvTool.selectedIndex = -1;
        rvTool.mode = "idle";
        state.selectedExclusion = -1;
        render(rvCvEl);
      }
    });

    // document mousemove: drawing ghost rect and drag feedback
    document.addEventListener("mousemove", function (e) {
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
          rvDslAppendExcl(x_cm, y_cm, w_cm, h_cm);
          rvApplyDslAsync();
        }
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
