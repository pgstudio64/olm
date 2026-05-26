"use strict";

async function init() {
  await loadAppConfig();
  if (typeof window.prefillDrawingScale === 'function') window.prefillDrawingScale();
  await loadAllBlockDefs();
  await loadBlockDefs();
  await loadSpacingConfigs();
  renderSpacingSettings();
  renderGeneralSettings();
  initSettingsTabs();
  renderFloorplanSettings();
  updateActiveStandardBadge();
  setActiveStandard(getCurrentStandard() || getStandards()[0] || "");

  // P1.4: All addEventListener calls in init() are session-life
  // (bound once at DOMContentLoaded, never re-bound). No dispose needed.

  // Settings drawer open/close
  document.getElementById("btnOpenSettings").addEventListener("click", function() {
    document.getElementById("settingsDrawer").classList.add("open");
    document.getElementById("settingsBackdrop").classList.add("open");
  });
  document.getElementById("btnCloseSettings").addEventListener("click", closeSettings);
  document.getElementById("settingsBackdrop").addEventListener("click", closeSettings);

  buildPalette();
  // Pre-create ruler boxes before first render (avoids layout shift)
  _ensureRulers(document.getElementById("canvas"));
  _ensureRulers(document.getElementById("fpCanvas"));
  _ensureRulers(document.getElementById("rvCanvas"));
  addRow(false);
  // Default room (D-122 P4 : door dans state.room_doors séparé)
  state.room_windows = [{ face: "north", offset_cm: 0, width_cm: state.room_width_cm }];
  state.room_openings = [];
  state.room_doors = [{ face: "south", offset_cm: 0, width_cm: APP_CONFIG.default_door_width_cm || 90, opens_inward: true, hinge_side: "left" }];
  updateAutoName();
  clearDirty();
  requestAnimationFrame(function() { zoomFit(); });
  loadCatalogue();

  // Guard: confirm discard if pattern room amend is active
  function _guardPatternRoomAmend(callback) {
    if (state.roomAmendMode && state.roomAmendMode.context === "pattern") {
      confirmModal("Discard unsaved room changes?").then(function(ok) {
        if (!ok) return;
        state.roomAmendMode = null;
        state.roomRenderOffset = null;
        exitRoomAmendUI();
        callback();
      });
    } else {
      callback();
    }
  }
  // PE left-column: Room + Layout sections stacked (no tabs).

  document.getElementById("btnNew").addEventListener("click", function() {
    _guardPatternRoomAmend(resetState);
  });
  // "New pattern" from Catalogue view → reset + switch to Editor sub-tab
  var btnNewPat = document.getElementById("btnNewPattern");
  if (btnNewPat) btnNewPat.addEventListener("click", function() {
    resetState();
    document.querySelector('.sub-tab-btn[data-subtab="catEditor"]').click();
  });
  document.getElementById("btnSave").addEventListener("click", save);
  document.getElementById("btnDuplicate").addEventListener("click", function() {
    _guardPatternRoomAmend(duplicatePattern);
  });
  document.getElementById("btnDelete").addEventListener("click", function() {
    _guardPatternRoomAmend(deletePattern);
  });
  document.getElementById("btnAmendCancel").addEventListener("click", function() {
    var msg = "Discard unsaved changes?";
    confirmModal(msg).then(function(ok) {
      if (!ok) return;
      clearDirty();
      if (state.roomAmendMode) {
        var ctx = state.roomAmendMode.context || "floor";
        if (ctx === "pattern") {
          // Restore room from original and reload pattern
          state.roomAmendMode = null; state.roomRenderOffset = null;
          exitRoomAmendUI();
          if (state._savedName) {
            loadPattern(state._savedName);
          } else {
            resetState();
          }
        } else {
          state.roomAmendMode = null; state.roomRenderOffset = null;
          exitRoomAmendUI();
          document.querySelector('.tab-btn[data-tab="fpReview"]').click();
        }
      } else if (state.amendMode) {
        state.amendMode = null;
        state.overlay = null;
        exitAmendUI();
        document.querySelector('.tab-btn[data-tab="lytDesign"]').click();
        fpRenderCurrent();
      } else if (_preFitSnapshot) {
        loadPatternFromData(_preFitSnapshot);
        _preFitSnapshot = null;
      } else if (state._savedName) {
        loadPattern(state._savedName);
      } else {
        resetState();
      }
      setStatus("Discarded.");
    });
  });
  // Pattern editor — Add door
  document.getElementById("peBtnAddDoor").addEventListener("click", function() {
    var doorW = APP_CONFIG.default_door_width_cm || 90;
    var doorPos = APP_CONFIG.default_pattern_door_position || "left";
    var offset = 0;
    if (doorPos === "center") offset = Math.round((state.room_width_cm - doorW) / 2);
    else if (doorPos === "right") offset = state.room_width_cm - doorW;
    state.room_doors.push({
      face: "south", offset_cm: offset, width_cm: doorW,
      opens_inward: true, hinge_side: "left"
    });
    state.selectedOpening = { type: "door", index: state.room_doors.length - 1 };
    markDirty();
    render();
    updateDSL();
    setStatus("Door added. Click to move, resize or delete.");
  });

  document.getElementById("btnAddRow").addEventListener("click", function() { addRow(true); });
  document.getElementById("btnApplyDSL").addEventListener("click", applyDSL);
  document.getElementById("btnApplyRoomDSL").addEventListener("click", applyRoomDSL);

  // Review room amend controls
  document.getElementById("rvBtnApplyDsl").addEventListener("click", async function() {
    var text = document.getElementById("rvRoomDsl").value.trim();
    if (!text) return;
    try {
      var resp = await fetch("/api/room-dsl/parse", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ dsl: text })
      });
      if (!resp.ok) { var err = await resp.json(); alertModal("Error: " + (err.error || "?")); return; }
      var data = await resp.json();
      // D-83: DSL is in local coordinates — state is also in local, no conversion needed
      state.room_width_cm = data.width_cm;
      state.room_depth_cm = data.depth_cm;
      state.room_windows = data.windows || [];
      // D-122 P4 : backend DSL renvoie openings combiné → split.
      _splitOpeningsIntoState(data.openings);
      state.room_exclusions = data.exclusion_zones || [];
      render(document.getElementById("rvCanvas"));
      zoomFit(document.getElementById("rvCanvas"));
      rvUpdateRoomInfo();
    } catch (err) { alertModal("Error: " + err.message); }
  });
  document.getElementById("rvBtnSaveRoom").addEventListener("click", function() {
    if (state.roomAmendMode) save();
  });
  document.getElementById("rvBtnCancelRoom").addEventListener("click", function() {
    if (!state.roomAmendMode) return;
    confirmModal("Discard unsaved room changes?").then(function(ok) {
      if (!ok) return;
      state.roomAmendMode = null; state.roomRenderOffset = null;
      exitRoomAmendUI();
      rvRenderCurrent();
      setStatus("Discarded.");
    });
  });

  document.getElementById("btnResetSpacing").addEventListener("click", async function() {
    // Delete overrides file by posting empty values for each standard
    var stds = getStandards();
    for (var i = 0; i < stds.length; i++) {
      await fetch("/api/spacing", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ standard: stds[i], values: {}, reset: true }),
      });
    }
    await loadSpacingConfigs();
    await loadAllBlockDefs();
    await loadBlockDefs();
    renderSpacingSettings();
    render();
    document.getElementById("spacingSaveStatus").textContent = "Reset to defaults.";
  });

  // Ctrl+Enter in DSL = Apply (Enter alone = normal line break)
  document.getElementById("dslText").addEventListener("keydown", function(e) {
    if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); applyDSL(); }
  });
  document.getElementById("dslRoom").addEventListener("keydown", function(e) {
    if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); applyRoomDSL(); }
  });
  var rvDslEl = document.getElementById("rvRoomDsl");
  if (rvDslEl) {
    rvDslEl.addEventListener("keydown", function(e) {
      if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
        e.preventDefault();
        var btn = document.getElementById("rvBtnApplyDsl");
        if (btn) btn.click();
      }
    });
  }

  function showTooltipCentered(tip) {
    var visible = tip.style.display !== "none";
    if (visible) { tip.style.display = "none"; return; }
    tip.style.display = "";
    tip.style.pointerEvents = "auto";
    var tipRect = tip.getBoundingClientRect();
    tip.style.left = Math.max(8, (window.innerWidth - tipRect.width) / 2) + "px";
    tip.style.top = Math.max(8, (window.innerHeight - tipRect.height) / 2) + "px";
  }
  function showDslHelp() {
    showTooltipCentered(document.getElementById("dslHelpTooltip"));
  }
  document.getElementById("dslHelpToggle").addEventListener("click", function(e) {
    showDslHelp(e.target);
  });
  var rvHelp = document.getElementById("rvDslHelpToggle");
  if (rvHelp) {
    rvHelp.addEventListener("click", function(e) {
      showDslHelp(e.target);
    });
  }

  function showLayoutDslHelp() {
    showTooltipCentered(document.getElementById("dslLayoutHelpTooltip"));
  }
  var layoutHelp = document.getElementById("dslLayoutHelpToggle");
  if (layoutHelp) {
    layoutHelp.addEventListener("click", function(e) {
      showLayoutDslHelp(e.target);
    });
  }

  document.addEventListener("click", function(e) {
    if (e.target.id !== "dslHelpToggle" && e.target.id !== "rvDslHelpToggle") {
      document.getElementById("dslHelpTooltip").style.display = "none";
    }
    if (e.target.id !== "dslLayoutHelpToggle") {
      var lt = document.getElementById("dslLayoutHelpTooltip");
      if (lt) lt.style.display = "none";
    }
  });

  // Lock checkboxes (Locks section — sidebar)
  ["stickN", "stickS", "stickE", "stickW"].forEach(function(id) {
    document.getElementById(id).addEventListener("change", function() {
      var b = getSelectedBlock();
      if (!b) return;
      var sticks = [];
      if (document.getElementById("stickN").checked) sticks.push("N");
      if (document.getElementById("stickS").checked) sticks.push("S");
      if (document.getElementById("stickE").checked) sticks.push("E");
      if (document.getElementById("stickW").checked) sticks.push("W");
      b.sticks = sticks.length > 0 ? sticks : undefined;
      markDirty();
      updateDSL();
      render();
    });
  });

  // Lock icons on canvas — event delegation (click on SVG lock toggles stick)
  function _handleLockClick(e) {
    var el = e.target;
    if (!el.getAttribute || !el.getAttribute("data-lock-face")) {
      el = el.closest ? el.closest("[data-lock-face]") : null;
    }
    if (!el) return;
    // D-215: locks are hidden in amend-layout mode — no-op guard
    if (state.amendMode) return;
    // Prevent the block-selection handler from running on the same click.
    e.stopImmediatePropagation();
    var face = el.getAttribute("data-lock-face");
    var ri = parseInt(el.getAttribute("data-lock-row"));
    var bi = parseInt(el.getAttribute("data-lock-block"));
    if (isNaN(ri) || isNaN(bi)) return;
    var row = state.rows[ri];
    if (!row || !row.blocks[bi]) return;
    var b = row.blocks[bi];
    var sticks = b.sticks ? b.sticks.slice() : [];
    var idx = sticks.indexOf(face);
    if (idx >= 0) {
      sticks.splice(idx, 1);
    } else {
      sticks.push(face);
    }
    b.sticks = sticks.length > 0 ? sticks : undefined;
    // Select this block so the sidebar checkboxes update
    state.selectedRow = ri;
    state.selectedBlock = bi;
    markDirty();
    updateDSL();
    render();
  }
  document.getElementById("canvas").addEventListener("click", _handleLockClick);
  var peCanvas = document.getElementById("peCanvas");
  if (peCanvas) peCanvas.addEventListener("click", _handleLockClick);
  document.getElementById("gridToggle").addEventListener("change", function(e) {
    if (window.syncGridToggle) window.syncGridToggle(e.target.checked);
    else { state.gridVisible = e.target.checked; }
    render();
  });
  document.getElementById("circToggle").addEventListener("change", function(e) {
    state.circVisible = e.target.checked;
    document.getElementById("fpCircToggle").checked = e.target.checked;
    saveConfigField("circulation_visible", e.target.checked);
    render();
  });
  // Editor overlay toggle + opacity — sync across all tabs
  document.getElementById("edOverlayToggle").addEventListener("change", function(e) {
    if (window.syncOverlayToggle) window.syncOverlayToggle(e.target.checked);
    render();
  });
  document.getElementById("edOverlayOpacity").addEventListener("input", function() {
    if (window.syncOverlayOpacity) window.syncOverlayOpacity(this.value);
    if (state.overlay) {
      state.overlay.opacity = parseInt(this.value);
      render();
    }
  });

  // fpGridToggle and fpCircToggle are wired in floor_plan.js
  // (they need access to fpCurrent/fpCurrentCandidate to re-render correctly)

  // Room dimensions
  // Resize tolerance: a block whose body extends past the room edge by more
  // than this is "outside" (float-noise guard; positions snap to the grid).
  var ROOM_RESIZE_TOL_CM = 0.5;

  function _applyFullWidthWindows(oldW, oldD, newW, newD) {
    state.room_windows.forEach(function(w) {
      var wallOld = (w.face === "north" || w.face === "south") ? oldW : oldD;
      var wallNew = (w.face === "north" || w.face === "south") ? newW : newD;
      if (w.offset_cm === 0 && w.width_cm === wallOld) {
        w.width_cm = wallNew;
      }
    });
  }

  function _anyBlockOutside(newW, newD) {
    // Test block BODIES (not the emprise): in the body coordinate frame the
    // north/west clearance zones legitimately sit at negative coordinates
    // (handled by the room viewBox), so an emprise test would false-positive
    // on every top-row block and block all resizes. Bodies must stay within
    // [0, room] — that is the "blocs à l'extérieur" constraint.
    var positions = computeBlockPositions();
    var t = ROOM_RESIZE_TOL_CM;
    return positions.some(function(p) {
      return p.x_cm < -t || p.y_cm < -t ||
        (p.x_cm + p.w_cm) > newW + t || (p.y_cm + p.h_cm) > newD + t;
    });
  }

  function _commitRoomSize(oldW, oldD, newW, newD) {
    markDirty();
    state.room_width_cm = newW;
    state.room_depth_cm = newD;
    _applyFullWidthWindows(oldW, oldD, newW, newD);
    document.getElementById("roomWidth").value = newW;
    document.getElementById("roomDepth").value = newD;
    updateDSL();
    updateAutoName();
    render();
    zoomFit();
  }

  function _revertRoomSizeFields(oldW, oldD) {
    document.getElementById("roomWidth").value = oldW;
    document.getElementById("roomDepth").value = oldD;
  }

  // Commit a shrink only if no block body falls outside the new room. Tests
  // the adapted rows when available, otherwise the current rows (covers the
  // case where adaptation failed, e.g. a pattern with no standard yet).
  function _finishShrink(adaptedRows, adaptedGaps, oldW, oldD, newW, newD) {
    var savedRows = state.rows;
    var savedGaps = state.row_gaps_cm;
    if (adaptedRows) {
      state.rows = adaptedRows;
      state.row_gaps_cm = adaptedGaps;
    }
    if (_anyBlockOutside(newW, newD)) {
      state.rows = savedRows;
      state.row_gaps_cm = savedGaps;
      _revertRoomSizeFields(oldW, oldD);
      setStatus("Réduction impossible : des blocs sortiraient de la pièce.");
      return;
    }
    _commitRoomSize(oldW, oldD, newW, newD);
  }

  function onRoomChange() {
    var oldW = state.room_width_cm;
    var oldD = state.room_depth_cm;
    var rawW = parseInt(document.getElementById("roomWidth").value) || 300;
    var rawD = parseInt(document.getElementById("roomDepth").value) || 480;
    var newW = Math.round(rawW / GRID_STEP_CM) * GRID_STEP_CM;
    var newD = Math.round(rawD / GRID_STEP_CM) * GRID_STEP_CM;

    var dimsChanged = (newW !== oldW || newD !== oldD);
    var hasBlocks = state.rows.length > 0 && totalBlocks() > 0;
    // A resize can only push a block outside when a dimension SHRINKS.
    var isShrink = (newW < oldW || newD < oldD);

    // No change, no blocks, or pure enlarge: apply directly (nothing can fall
    // outside). Still adapt block positions in the background.
    if (!dimsChanged || !hasBlocks) {
      _commitRoomSize(oldW, oldD, newW, newD);
      return;
    }

    // Blocks present: adapt on the backend. For a shrink, commit ONLY if every
    // block body still fits; otherwise reject. For an enlarge, always commit.
    var payload = {
      pattern: {
        rows: state.rows,
        row_gaps_cm: state.row_gaps_cm,
        room_width_cm: oldW,
        room_depth_cm: oldD,
      },
      new_width_cm: newW,
      new_depth_cm: newD,
    };
    fetch("/api/pattern/adapt-room-size", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    })
      .then(function(r) { return r.json(); })
      .then(function(data) {
        var pat = data && data.pattern;
        if (!isShrink) {
          // Enlarge: apply adapted positions if any, always commit.
          if (pat) {
            state.rows = pat.rows || state.rows;
            state.row_gaps_cm = pat.row_gaps_cm || state.row_gaps_cm;
          }
          _commitRoomSize(oldW, oldD, newW, newD);
          return;
        }
        // Shrink: enforce that no block falls outside (adapted rows if any).
        _finishShrink(
          pat ? (pat.rows || state.rows) : null,
          pat ? (pat.row_gaps_cm || state.row_gaps_cm) : null,
          oldW, oldD, newW, newD);
      })
      .catch(function(err) {
        // Adaptation failed (e.g. pattern without a standard).
        console.error("adapt-room-size failed:", err);
        if (!isShrink) { _commitRoomSize(oldW, oldD, newW, newD); return; }
        // Shrink: still enforce the constraint on the current (unadapted) rows.
        _finishShrink(null, null, oldW, oldD, newW, newD);
      });
  }
  document.getElementById("roomWidth").addEventListener("change", onRoomChange);
  document.getElementById("roomDepth").addEventListener("change", onRoomChange);
  document.getElementById("btnWidthMinus").addEventListener("click", function() {
    var el = document.getElementById("roomWidth");
    el.value = Math.max(GRID_STEP_CM, (parseInt(el.value) || 300) - GRID_STEP_CM);
    onRoomChange();
  });
  document.getElementById("btnWidthPlus").addEventListener("click", function() {
    var el = document.getElementById("roomWidth");
    el.value = (parseInt(el.value) || 300) + GRID_STEP_CM;
    onRoomChange();
  });
  document.getElementById("btnDepthMinus").addEventListener("click", function() {
    var el = document.getElementById("roomDepth");
    el.value = Math.max(GRID_STEP_CM, (parseInt(el.value) || 480) - GRID_STEP_CM);
    onRoomChange();
  });
  document.getElementById("btnDepthPlus").addEventListener("click", function() {
    var el = document.getElementById("roomDepth");
    el.value = (parseInt(el.value) || 480) + GRID_STEP_CM;
    onRoomChange();
  });

  // Standard: controlled by Settings radio (D-208 + D-230)

  // Editor state save/restore (no DOM movement — each view has its own canvas)
  var _editorSnapshot = null;
  function _saveEditorState() {
    _editorSnapshot = {
      rows: JSON.parse(JSON.stringify(state.rows)),
      row_gaps_cm: state.row_gaps_cm.slice(),
      room_width_cm: state.room_width_cm,
      room_depth_cm: state.room_depth_cm,
      room_windows: JSON.parse(JSON.stringify(state.room_windows)),
      room_openings: JSON.parse(JSON.stringify(state.room_openings)),
      room_doors: JSON.parse(JSON.stringify(state.room_doors || [])),
      room_exclusions: JSON.parse(JSON.stringify(state.room_exclusions)),
      name: state.name,
      standard: state.standard,
      _savedName: state._savedName,
      selectedRow: state.selectedRow,
      selectedBlock: state.selectedBlock,
      overlay: null,
    };
  }
  function _restoreEditorState() {
    if (_editorSnapshot) {
      Object.assign(state, _editorSnapshot);
      _editorSnapshot = null;
      render();
      updateDSL();
      zoomFit();
    }
    if (state.rows.length === 0 && catalogueData.length > 0) {
      loadPatternFromData(JSON.parse(JSON.stringify(catalogueData[0])));
    }
  }

  // Guard: discard unsaved amend/room changes before navigating.
  // Returns a Promise<boolean> (true = proceed, false = stay).
  function _cancelAmendIfActive() {
    if (state.amendMode && state.dirty) {
      return confirmModal("Discard unsaved layout changes?").then(function(ok) {
        if (!ok) return false;
        state.amendMode = null; state.overlay = null;
        exitAmendUI(); _restoreEditorState();
        return !state.roomAmendMode ? true :
          confirmModal("Discard unsaved room changes?").then(function(ok2) {
            if (!ok2) return false;
            state.roomAmendMode = null; state.roomRenderOffset = null;
            exitRoomAmendUI(); return true;
          });
      });
    }
    if (state.amendMode) {
      state.amendMode = null; state.overlay = null;
      exitAmendUI(); _restoreEditorState();
    }
    if (state.roomAmendMode) {
      return confirmModal("Discard unsaved room changes?").then(function(ok) {
        if (!ok) return false;
        state.roomAmendMode = null; state.roomRenderOffset = null;
        exitRoomAmendUI(); return true;
      });
    }
    return Promise.resolve(true);
  }

  var DISCARD_PATTERN_MSG = "Discard unsaved pattern changes?";

  // True when the pattern editor is open with unsaved changes (and not in
  // amend / room-amend mode). Shared condition for every navigation guard.
  function _isEditingDirtyPattern() {
    var editorSub = document.getElementById("subtabCatEditor");
    return !!(state.dirty && !state.amendMode && !state.roomAmendMode
              && editorSub && editorSub.classList.contains("active"));
  }

  // Confirm discard before leaving a dirty pattern. Promise<boolean>:
  // true = proceed (editor clean, or user confirmed discard).
  window._confirmDiscardPatternIfDirty = function() {
    if (!_isEditingDirtyPattern()) return Promise.resolve(true);
    return confirmModal(DISCARD_PATTERN_MSG).then(function(ok) {
      if (ok) clearDirty();
      return ok;
    });
  };

  // Tab descriptions (flat nav — 4 tabs)

  // Main tabs (flat nav)
  document.querySelectorAll(".tab-btn").forEach(function(btn) {
    btn.addEventListener("click", function() {
      // Tab active BEFORE switching — used to special-case Office → Catalogue.
      var _originTabEl = document.querySelector(".tab-btn.active");
      var originTab = _originTabEl ? _originTabEl.dataset.tab : null;
      // v0.5.34 instrumentation : demarrer la capture du freeze des le clic
      // d'onglet vers Room (couvre tab-switch + paint, avant rvRenderCurrent).
      if (btn.dataset.tab === "fpReview" && window._perf) {
        window._perf.begin("Floor→Room");
      }
      var isLayoutTab = btn.dataset.tab === "lytDesign" || btn.dataset.tab === "lytCatalogue";
      // Guard: room amend mode active — confirm discard before switching
      if (state.roomAmendMode && btn.dataset.tab !== "fpReview") {
        confirmModal("Discard unsaved room changes?").then(function(ok) {
          if (!ok) return;
          state.roomAmendMode = null; state.roomRenderOffset = null;
          exitRoomAmendUI();
          // Re-trigger the tab click now that amend mode is cleared
          btn.click();
        });
        return;
      }
      // Guard: leaving the pattern editor with unsaved changes → confirm
      // discard. The Card-view sub-tab is already guarded; this covers
      // main-tab switches to Floor/Room/Office.
      if (btn.dataset.tab !== "lytCatalogue" && _isEditingDirtyPattern()) {
        confirmModal(DISCARD_PATTERN_MSG).then(function(ok) {
          if (!ok) return;
          clearDirty();
          btn.click();
        });
        return;
      }
      function _doSwitch() {
        document.querySelectorAll(".tab-btn").forEach(function(b) { b.classList.remove("active"); });
        document.querySelectorAll(".tab-content").forEach(function(c) { c.classList.remove("active"); });
        btn.classList.add("active");
        var tabId = "tab" + btn.dataset.tab.charAt(0).toUpperCase() + btn.dataset.tab.slice(1);
        var tab = document.getElementById(tabId);
        if (tab) tab.classList.add("active");
        if (isLayoutTab) {
          _restoreEditorState();
        }
        if (btn.dataset.tab === "lytDesign") {
          loadCatalogue();
        }
        if (btn.dataset.tab === "lytCatalogue") {
          // D-286: clicking the Catalogue tab always lands on the Card view
          // (not the last-used Editor sub-tab). When arriving from Office with
          // a selected candidate, pre-select that pattern's card; otherwise
          // (Office without selection, Room, Floor) just show the Card view.
          if (originTab === "lytDesign" && window.fpGetSelectedPatternName) {
            var _selName = window.fpGetSelectedPatternName();
            if (_selName && window.catRequestSelectByName) {
              window.catRequestSelectByName(_selName);
            }
          }
          document.querySelector(
            '.sub-tab-btn[data-subtab="catalogue"]').click();
        }
        if (btn.dataset.tab === "fpReview") {
          rvRenderCurrent();
        }
        if (btn.dataset.tab === "lytDesign" &&
            typeof window.fpRenderCurrent === "function") {
          window.fpRenderCurrent();
        }
        // Rafraîchir les rulers HTML quand l'onglet devient visible
        if (btn.dataset.tab === "fpReview" || btn.dataset.tab === "lytDesign") {
          var svgId = btn.dataset.tab === "fpReview" ? "rvCanvas" : "fpCanvas";
          requestAnimationFrame(function () {
            var s = document.getElementById(svgId);
            if (s && typeof window.updateRulers === "function") window.updateRulers(s);
          });
        }
      } // end _doSwitch

      // Cancel amend mode when switching tabs (async).
      // Also triggers on layout-tab clicks during amend mode.
      if (state.amendMode || !isLayoutTab) {
        _cancelAmendIfActive().then(function(ok) {
          if (!ok) return;
          _saveEditorState();
          _doSwitch();
        });
      } else {
        _doSwitch();
      }
    });
  });

  // Sub-tabs (Catalogue sub-tab-bar)

  document.querySelectorAll(".sub-tab-btn").forEach(function(btn) {
    btn.addEventListener("click", function() {
      function _doSubSwitch() {
        var bar = btn.parentElement;
        bar.querySelectorAll(":scope > .sub-tab-btn").forEach(function(b) { b.classList.remove("active"); });
        btn.classList.add("active");
        var parentTab = bar.parentElement;
        parentTab.querySelectorAll(":scope > .sub-tab-content").forEach(function(c) { c.classList.remove("active"); });
        var subtab = document.getElementById("subtab" + btn.dataset.subtab.charAt(0).toUpperCase() + btn.dataset.subtab.slice(1));
        if (subtab) subtab.classList.add("active");
        if (btn.dataset.subtab === "catalogue") { loadCatalogue(); }
      }
      // Guard: leaving the pattern editor with unsaved changes → confirm
      // discard (same behaviour as Room/Office). _doSubSwitch reloads the
      // catalogue so Card view is never shown empty.
      if (btn.dataset.subtab === "catalogue" && _isEditingDirtyPattern()) {
        confirmModal(DISCARD_PATTERN_MSG).then(function(ok) {
          if (!ok) return;
          clearDirty();
          _doSubSwitch();
        });
        return;
      }
      // Guard: pattern room amend active — confirm discard
      if (state.roomAmendMode && state.roomAmendMode.context === "pattern"
          && btn.dataset.subtab !== "catEditor") {
        confirmModal("Discard unsaved room changes?").then(function(ok) {
          if (!ok) return;
          state.roomAmendMode = null; state.roomRenderOffset = null;
          exitRoomAmendUI();
          _doSubSwitch();
        });
        return;
      }
      if (btn.dataset.subtab !== "catEditor") {
        var result = _cancelAmendIfActive();
        if (result && typeof result.then === "function") {
          result.then(function(ok) { if (ok) _doSubSwitch(); });
          return;
        }
      }
      _doSubSwitch();
    });
  });

  // Catalogue import/export — dropdown menus
  var _EXPORT_BTN   = ["btnCatExport"];
  var _EXPORT_MENU  = ["catExportMenu"];
  var _IMPORT_BTN   = ["btnCatImport"];
  var _IMPORT_MENU  = ["catImportMenu"];
  var _ALL_MENUS    = _EXPORT_MENU.concat(_IMPORT_MENU);

  function _hideAllCatMenus() {
    _ALL_MENUS.forEach(function(id) {
      var el = document.getElementById(id);
      if (el) el.style.display = "none";
    });
  }

  function _catImportRecalSummary(resp) {
    var msg = resp.imported + " pattern(s) imported. Total: " + resp.total;
    var r = resp.recalibration;
    if (r) {
      msg += "\nRecalibration: " + r.expanded + " expanded, "
        + r.compressed + " compressed, " + r.noop + " unchanged";
      if (r.with_warnings > 0) msg += ", " + r.with_warnings + " with warnings";
    }
    return msg;
  }

  function _catStdLabel() {
    var v = getCurrentStandard();
    return (typeof getStdLabel === "function" && v) ? getStdLabel(v) : v;
  }

  function _catSendImport(url, body) {
    var stdVal = getCurrentStandard();
    if (stdVal) body.target_standard = stdVal;
    fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    })
    .then(function(r) { return r.json(); })
    .then(function(resp) {
      if (resp.error) { alertModal("Import error: " + resp.error); return; }
      setStatus(_catImportRecalSummary(resp));
      loadCatalogue();
      var activeBtn = document.querySelector('.sub-tab-btn.active');
      if (activeBtn && activeBtn.dataset.subtab === "catEditor") {
        var catBtn = document.querySelector('.sub-tab-btn[data-subtab="catalogue"]');
        if (catBtn) catBtn.click();
      }
    });
  }

  function _catDoFileImport(data) {
    var label = _catStdLabel();
    confirmModal("Replace all " + label + " patterns with the imported ones? Other standards are preserved.").then(function(ok) {
      if (!ok) return;
      _catSendImport("/api/catalogue/import", data);
    });
  }

  function _catImportDefault() {
    _hideAllCatMenus();
    var label = _catStdLabel();
    confirmModal("Replace all " + label + " patterns with the defaults? Other standards are preserved.").then(function(ok) {
      if (!ok) return;
      _catSendImport("/api/catalogue/import-default", {});
    });
  }

  function _catExportFile() {
    _hideAllCatMenus();
    fetch("/api/catalogue/export")
      .then(function(r) { return r.blob(); })
      .then(function(blob) {
        var url = URL.createObjectURL(blob);
        var a = document.createElement("a");
        a.href = url;
        a.download = "patterns.json";
        a.click();
        URL.revokeObjectURL(url);
      });
  }

  function _catSaveAsDefault() {
    _hideAllCatMenus();
    var label = _catStdLabel();
    var stdVal = getCurrentStandard();
    confirmModal("Save current " + label + " patterns as the default catalogue?\n\nThis OVERWRITES the entire default \u2014 patterns from other standards (if any) will be lost.").then(function(ok) {
      if (!ok) return;
      fetch("/api/catalogue/save-as-default", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ target_standard: stdVal }),
      })
        .then(function(r) { return r.json().then(function(d) { return { status: r.status, data: d }; }); })
        .then(function(res) {
          if (res.status === 403) { alertModal("Forbidden: " + res.data.error); return; }
          if (res.data.error) { alertModal("Error: " + res.data.error); return; }
          setStatus("Saved " + res.data.count + " " + label + " pattern(s) as default.");
        });
    });
  }

  function _catImportFromFile(filePickerId) {
    _hideAllCatMenus();
    document.getElementById(filePickerId).click();
  }

  // Helper: attach same handler to multiple IDs
  function _bindPair(ids, handler) {
    ids.forEach(function(id) {
      var el = document.getElementById(id);
      if (el) el.addEventListener("click", handler);
    });
  }

  // -- Export dropdown toggle --
  _EXPORT_BTN.forEach(function(btnId, idx) {
    var menuId = _EXPORT_MENU[idx];
    var el = document.getElementById(btnId);
    if (el) el.addEventListener("click", function() {
      var menu = document.getElementById(menuId);
      var show = menu.style.display === "none";
      _hideAllCatMenus();
      if (show) menu.style.display = "block";
    });
  });

  // -- Import dropdown toggle --
  _IMPORT_BTN.forEach(function(btnId, idx) {
    var menuId = _IMPORT_MENU[idx];
    var el = document.getElementById(btnId);
    if (el) el.addEventListener("click", function() {
      var menu = document.getElementById(menuId);
      var show = menu.style.display === "none";
      _hideAllCatMenus();
      if (show) menu.style.display = "block";
    });
  });

  // Close all dropdowns on outside click
  document.addEventListener("click", function(e) {
    var insideExport = _EXPORT_BTN.concat(_EXPORT_MENU).some(function(id) { return e.target.closest("#" + id); });
    var insideImport = _IMPORT_BTN.concat(_IMPORT_MENU).some(function(id) { return e.target.closest("#" + id); });
    if (!insideExport) _EXPORT_MENU.forEach(function(id) { var m = document.getElementById(id); if (m) m.style.display = "none"; });
    if (!insideImport) _IMPORT_MENU.forEach(function(id) { var m = document.getElementById(id); if (m) m.style.display = "none"; });
  });

  // -- Export actions --
  _bindPair(["btnCatExportFile"], _catExportFile);
  _bindPair(["btnCatExportPng"], function() {
    _hideAllCatMenus();
    if (typeof exportCatalogueToPng === "function") exportCatalogueToPng();
  });
  _bindPair(["btnCatSaveAsDefault"], _catSaveAsDefault);

  // -- Import from file --
  _bindPair(["btnCatImportFile"], function() {
    _catImportFromFile("catImportFile");
  });

  // -- File picker change --
  document.getElementById("catImportFile").addEventListener("change", function(e) {
    var file = e.target.files[0];
    if (!file) return;
    var reader = new FileReader();
    reader.onload = function(ev) {
      var data;
      try { data = JSON.parse(ev.target.result); } catch(err) {
        alertModal("Invalid JSON: " + err.message); return;
      }
      if (!data.patterns || !Array.isArray(data.patterns)) {
        alertModal("Invalid format: 'patterns' key expected"); return;
      }
      _catDoFileImport(data);
    };
    reader.readAsText(file);
    e.target.value = "";
  });

  // -- Import default --
  _bindPair(["btnCatImportDefault"], function() {
    _catImportDefault();
  });

  // -- First-launch banner --
  _bindPair(["btnCatLoadDefault"], function() {
    _catSendImport("/api/catalogue/import-default", {});
    var el = document.getElementById("catDefaultBanner");
    if (el) el.style.display = "none";
  });

  // --- Fit to pattern (editor) ---
  // Snapshot before Fit — allows Discard to revert
  var _preFitSnapshot = null;
  document.getElementById("btnFit").addEventListener("click", function() {
    _preFitSnapshot = JSON.parse(JSON.stringify(buildPatternPayload()));
    var payload = buildPatternPayload();
    fetch("/api/patterns/fit-inline", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    })
      .then(function(r) { return r.json().then(function(d) { return { ok: r.ok, data: d }; }); })
      .then(function(res) {
        if (!res.ok) {
          setStatus("Fit error: " + (res.data.error || "unknown"));
          return;
        }
        var d = res.data;
        // Update editor state with new dims
        var prevW = state.room_width_cm;
        var prevD = state.room_depth_cm;
        state.room_width_cm = d.new_width;
        state.room_depth_cm = d.new_depth;
        document.getElementById("roomWidth").value = d.new_width;
        document.getElementById("roomDepth").value = d.new_depth;
        state.name = renameAfterFit(state.name, d.new_width, d.new_depth);
        _safeText("autoName", state.name);
        // Apply updated block positions and features from backend
        if (d.rows) {
          state.rows = d.rows;
          state.row_gaps_cm = d.row_gaps_cm || [];
        }
        if (d.room_windows) {
          state.room_windows = d.room_windows;
        }
        if (d.room_openings) {
          _splitOpeningsIntoState(d.room_openings);
        }
        markDirty();
        render();
        zoomFit();
        updateDSL();
        updateRowList();
        // Toast
        if (d.direction === "shrink") {
          setStatus("Room shrunk: " + d.old_width + "x" + d.old_depth + " -> " + d.new_width + "x" + d.new_depth + " cm");
        } else if (d.direction === "expand") {
          setStatus("Room expanded: " + d.old_width + "x" + d.old_depth + " -> " + d.new_width + "x" + d.new_depth + " cm");
        } else {
          setStatus("Room already at minimum (" + d.new_width + "x" + d.new_depth + " cm)");
        }
        // Warnings
        var warnEl = document.getElementById("editorWarnings");
        if (d.warnings && d.warnings.length > 0) {
          warnEl.textContent = d.warnings.join(" | ");
          warnEl.style.display = "block";
        } else {
          warnEl.style.display = "none";
        }
      })
      .catch(function(err) { setStatus("Fit error: " + err.message); });
  });

  // --- Compact (editor) : normalize gaps + fit room ---
  var _btnCompact = document.getElementById("btnCompact");
  if (_btnCompact) _btnCompact.addEventListener("click", function() {
    var payload = buildPatternPayload();
    fetch("/api/patterns/compact-inline", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    })
      .then(function(r) { return r.json().then(function(d) { return { ok: r.ok, data: d }; }); })
      .then(function(res) {
        if (!res.ok) {
          setStatus("Compact error: " + (res.data.error || "unknown"));
          return;
        }
        var d = res.data;
        state.room_width_cm = d.new_width;
        state.room_depth_cm = d.new_depth;
        document.getElementById("roomWidth").value = d.new_width;
        document.getElementById("roomDepth").value = d.new_depth;
        state.name = renameAfterFit(state.name, d.new_width, d.new_depth);
        _safeText("autoName", state.name);
        if (d.rows) {
          state.rows = d.rows;
          state.row_gaps_cm = d.row_gaps_cm || [];
        }
        if (d.room_windows) state.room_windows = d.room_windows;
        if (d.room_openings) _splitOpeningsIntoState(d.room_openings);
        markDirty();
        render();
        zoomFit();
        updateDSL();
        updateRowList();
        var changed = (d.gaps_changed || 0) + (d.row_gaps_changed || 0);
        if (changed > 0 || d.direction !== "noop") {
          setStatus("Compacted: " + changed + " gap(s) tightened, room "
            + d.old_width + "x" + d.old_depth + " -> " + d.new_width + "x" + d.new_depth);
        } else {
          setStatus("Already compact (" + d.new_width + "x" + d.new_depth + " cm)");
        }
        var warnEl = document.getElementById("editorWarnings");
        if (d.warnings && d.warnings.length > 0) {
          warnEl.textContent = d.warnings.join(" | ");
          warnEl.style.display = "block";
        } else {
          warnEl.style.display = "none";
        }
      })
      .catch(function(err) { setStatus("Compact error: " + err.message); });
  });

  // --- Fit all to pattern (catalogue) ---
  function _catFitAll() {
    fetch("/api/patterns/fit-all", { method: "POST" })
      .then(function(r) { return r.json(); })
      .then(function(data) {
        if (data.error) { alertModal("Fit-all error: " + data.error); return; }
        var s = data.summary;
        var fitted = data.fitted || [];
        var skipped = data.skipped || [];
        var html = "<div style='font-size:12px;margin-bottom:8px;'>"
          + "Fitted " + s.fitted + " / " + s.total + " patterns ("
          + s.noop + " already minimal, " + s.skipped + " skipped).</div>";
        if (fitted.length > 0) {
          html += "<details><summary style='cursor:pointer;font-size:11px;'>Fitted details</summary>"
            + "<table style='font-size:10px;border-collapse:collapse;width:100%;margin-top:4px;'>"
            + "<tr style='border-bottom:1px solid var(--border);'><th style='text-align:left;padding:2px 6px;'>Name</th>"
            + "<th>Direction</th><th>Old</th><th>New</th><th>Warnings</th></tr>";
          fitted.forEach(function(f) {
            var r = f.result;
            var warns = (r.warnings && r.warnings.length > 0) ? r.warnings.join("; ") : "";
            html += "<tr style='border-bottom:1px solid var(--border);'>"
              + "<td style='padding:2px 6px;'>" + f.name + "</td>"
              + "<td style='text-align:center;'>" + r.direction + "</td>"
              + "<td style='text-align:center;'>" + r.old_width + "x" + r.old_depth + "</td>"
              + "<td style='text-align:center;'>" + r.new_width + "x" + r.new_depth + "</td>"
              + "<td style='font-size:9px;color:#c09050;'>" + warns + "</td></tr>";
          });
          html += "</table></details>";
        }
        if (skipped.length > 0) {
          html += "<details><summary style='cursor:pointer;font-size:11px;color:#c05858;'>Skipped (" + skipped.length + ")</summary>"
            + "<table style='font-size:10px;border-collapse:collapse;width:100%;margin-top:4px;'>"
            + "<tr style='border-bottom:1px solid var(--border);'><th style='text-align:left;padding:2px 6px;'>Name</th><th>Reason</th></tr>";
          skipped.forEach(function(sk) {
            html += "<tr style='border-bottom:1px solid var(--border);'>"
              + "<td style='padding:2px 6px;'>" + sk.name + "</td>"
              + "<td style='font-size:9px;'>" + sk.reason + "</td></tr>";
          });
          html += "</table></details>";
        }
        alertModal(html, true);
        loadCatalogue();
      })
      .catch(function(err) { alertModal("Fit-all error: " + err.message); });
  }
  _bindPair(["btnFitAll"], _catFitAll);

  // Catalogue filters — update card view
  function onCatalogueFilterChange() {
    renderCatalogue();
  }
  var _peBtnPrev = document.getElementById("peBtnPrev");
  if (_peBtnPrev) _peBtnPrev.addEventListener("click", function() {
    if (window.peNavigate) window.peNavigate(-1);
  });
  var _peBtnNext = document.getElementById("peBtnNext");
  if (_peBtnNext) _peBtnNext.addEventListener("click", function() {
    if (window.peNavigate) window.peNavigate(1);
  });
  var _peBtnBackCards = document.getElementById("peBtnBackCards");
  if (_peBtnBackCards) _peBtnBackCards.addEventListener("click", function() {
    // Same action as Esc → Card view (init.js keydown handler).
    document.querySelector('.sub-tab-btn[data-subtab="catalogue"]').click();
    if (window.catScrollSelectedIntoView) window.catScrollSelectedIntoView();
  });
  document.getElementById("catFilterMinW").addEventListener("change", onCatalogueFilterChange);
  document.getElementById("catFilterMaxW").addEventListener("change", onCatalogueFilterChange);
  document.getElementById("catFilterMinD").addEventListener("change", onCatalogueFilterChange);
  document.getElementById("catFilterMaxD").addEventListener("change", onCatalogueFilterChange);
  document.getElementById("catFilterDesks").addEventListener("change", onCatalogueFilterChange);
  document.getElementById("btnRotate").addEventListener("click", rotateSelectedBlock);
  document.getElementById("btnOffsetN").addEventListener("click", function() { offsetSelectedBlock(-GRID_STEP_CM); });
  document.getElementById("btnOffsetS").addEventListener("click", function() { offsetSelectedBlock(GRID_STEP_CM); });
  document.getElementById("btnOffsetW").addEventListener("click", function() { offsetSelectedBlockEO(-GRID_STEP_CM); });
  document.getElementById("btnOffsetE").addEventListener("click", function() { offsetSelectedBlockEO(GRID_STEP_CM); });

  document.getElementById("btnZoomIn").addEventListener("click", function() { zoomIn(); });
  document.getElementById("btnZoomOut").addEventListener("click", function() { zoomOut(); });
  document.getElementById("btnZoomFit").addEventListener("click", function() { zoomFit(); });

  const canvas = document.getElementById("canvas");
  var _panSvg = null;  // which SVG is currently being panned

  function setupPan(svg) {
    svg.addEventListener("mousedown", function(e) {
      if (e.target.closest("[data-row]") || e.target.closest("[data-excl]") ||
          e.target.closest("[data-excl-handle]") || e.target.closest("[data-room-handle]") ||
          e.target.closest("[data-transp]") || e.target.closest("[data-transp-handle]") ||
          e.target.closest("[data-opening-handle]") || e.target.closest("[data-opening-delete]") ||
          e.target.closest("[data-opening-resize]") || e.target.closest("[data-door-hinge]") ||
          e.target.closest("[data-door-dir]") ||
          e.target.closest("[data-furn]") ||
          e.target.closest("[data-furn-rotate]") ||
          e.target.closest("[data-furn-delete]") ||
          e.target.getAttribute && e.target.getAttribute("data-lock-face")) return;
      if (svg.id === "rvCanvas" && window.rvTool &&
          (window.rvTool.mode === "placing" || window.rvTool.mode === "drawing" ||
           window.rvTool.mode === "roomResizing" ||
           window.rvTool.mode === "transpDragging" ||
           window.rvTool.mode === "transpResizing" ||
           window.rvTool.mode === "transpSelected" ||
           window.rvTool.mode === "furnPlacing" ||
           window.rvTool.mode === "furnSelected" ||
           window.rvTool.mode === "furnDragging" ||
           window.rvTool.mode === "openingMoving" ||
           window.rvTool.mode === "openingResizing")) return;
      if (e.button !== 0) return;
      if (zoomSelStart(e, svg, state.viewBox, function() { updateViewBox(svg); render(svg); })) return;
      state.isPanning = true;
      state.panStart = { x: e.clientX, y: e.clientY };
      _panSvg = svg;
      svg.classList.add("panning");
      e.preventDefault();
    });
  }
  setupPan(canvas);
  setupPan(document.getElementById("fpCanvas"));
  setupPan(document.getElementById("rvCanvas"));

  function setupWheelZoom(svg) {
    if (!svg) return;
    svg.addEventListener("wheel", function(e) {
      e.preventDefault();
      var vb = state.viewBox;
      var isZoomIn = e.deltaY < 0;
      var factor = isZoomIn ? ZOOM_IN_FACTOR : ZOOM_OUT_FACTOR;
      // Zoom-in limit: minimum 200 cm visible (all views)
      if (isZoomIn) {
        var minW = 200 * SCALE;
        if (vb.w * factor < minW) return;
      }
      // Zoom-out limit: max ZOOM_OUT_MAX_FIT_RATIO × fitted view
      if (!isZoomIn && state._fitViewBox) {
        if (vb.w * factor > state._fitViewBox.w * ZOOM_OUT_MAX_FIT_RATIO) return;
      }
      var rect = svg.getBoundingClientRect();
      var mx = vb.x + (e.clientX - rect.left) / rect.width * vb.w;
      var my = vb.y + (e.clientY - rect.top) / rect.height * vb.h;
      vb.x = mx - (mx - vb.x) * factor;
      vb.y = my - (my - vb.y) * factor;
      vb.w *= factor;
      vb.h *= factor;
      state.zoom = 1 / (vb.w / (state._fitViewBox ? state._fitViewBox.w : vb.w));
      render(svg);
    }, { passive: false });
  }
  setupWheelZoom(canvas);
  setupWheelZoom(document.getElementById("fpCanvas"));
  setupWheelZoom(document.getElementById("rvCanvas"));

  // rvTool (forbidden-zone interaction for Review amend mode) extracted
  // to olm/static/init_rvtool.js as of D-94 P3.

  document.addEventListener("mousemove", function(e) {
    if (zoomSel.active) { zoomSelMove(e); return; }
    // D-99: during a room-corner resize, block any pan motion that could
    // otherwise fight the resize and drift the overlay.
    if (window.rvTool && window.rvTool.mode === "roomResizing") return;
    if (!state.isPanning || !_panSvg) return;
    const dx = e.clientX - state.panStart.x;
    const dy = e.clientY - state.panStart.y;
    state.panStart = { x: e.clientX, y: e.clientY };
    const rect = _panSvg.getBoundingClientRect();
    state.viewBox.x -= dx * (state.viewBox.w / rect.width);
    state.viewBox.y -= dy * (state.viewBox.h / rect.height);
    updateViewBox(_panSvg);
  });

  document.addEventListener("mouseup", function(e) {
    if (zoomSel.active) { zoomSelEnd(e); return; }
    if (state.isPanning && _panSvg) {
      state.isPanning = false;
      _panSvg.classList.remove("panning");
      render(_panSvg);
      _panSvg = null;
    }
  });

  canvas.addEventListener("click", function(e) {
    // D-267: suppress click after block drag release (SVG rebuilt, stale target)
    if (window._blockDragJustReleased) {
      window._blockDragJustReleased = false;
      return;
    }
    // Skip if clicking on door/opening interactive elements
    if (e.target.closest("[data-opening-handle]") ||
        e.target.closest("[data-opening-delete]") ||
        e.target.closest("[data-opening-resize]") ||
        e.target.closest("[data-door-hinge]") ||
        e.target.closest("[data-door-dir]")) return;
    var exclTarget = e.target.closest("[data-excl]");
    if (exclTarget) {
      state.selectedExclusion = parseInt(exclTarget.dataset.excl);
      state.selectedBlock = -1;
      state.selectedFurniture = -1;
      render();
      updateRowList();
      return;
    }
    var target = e.target.closest("[data-row]");
    // Block selection only in Catalogue > Editor or amend mode
    var activeTab = document.querySelector(".tab-btn.active");
    var inEditor = activeTab && activeTab.dataset.tab === "lytCatalogue";
    var inAmend = !!state.amendMode;
    if (!inEditor && !inAmend) return;
    var editorSub = document.getElementById("subtabCatEditor");
    if (!inAmend && (!editorSub || !editorSub.classList.contains("active"))) return;
    if (target) {
      state.selectedRow = parseInt(target.dataset.row);
      state.selectedBlock = parseInt(target.dataset.block);
      state.selectedExclusion = -1;
      state.selectedFurniture = -1;
    } else {
      state.selectedBlock = -1;
      state.selectedExclusion = -1;
      state.selectedFurniture = -1;
    }
    render();
    updateRowList();
  });

  document.addEventListener("keydown", function(e) {
    if (e.target.tagName === "INPUT" || e.target.tagName === "TEXTAREA") return;

    // D-243 C4: PageUp/Down navigates prev/next pattern in PE
    // Active in Catalogue tab (any subtab), not in amend mode.
    if (e.key === "PageUp" || e.key === "PageDown") {
      var navTab = document.querySelector(".tab-btn.active");
      if (navTab && navTab.dataset.tab === "lytCatalogue" && !state.amendMode) {
        e.preventDefault();
        if (window.peNavigate) {
          window.peNavigate(e.key === "PageUp" ? -1 : 1);
        }
      }
      return;
    }

    // Keyboard editing only in Catalogue > Editor or amend mode
    var activeTab = document.querySelector(".tab-btn.active");
    var inEditor = activeTab && activeTab.dataset.tab === "lytCatalogue";
    var inAmend = !!state.amendMode;
    if (!inEditor && !inAmend) return;
    var editorSub = document.getElementById("subtabCatEditor");
    if (!inAmend && (!editorSub || !editorSub.classList.contains("active"))) return;
    const step = e.shiftKey ? GRID_STEP_CM * 5 : GRID_STEP_CM;

    // Esc in the pattern editor → back to Card view at the same card.
    if (e.key === "Escape" && !inAmend) {
      e.preventDefault();
      document.querySelector('.sub-tab-btn[data-subtab="catalogue"]').click();
      if (window.catScrollSelectedIntoView) window.catScrollSelectedIntoView();
      return;
    }

    // Exclusion selected
    if (state.selectedExclusion >= 0) {
      var excl = state.room_exclusions[state.selectedExclusion];
      if (!excl) return;
      if (e.key === "ArrowRight") {
        e.preventDefault(); excl.x_cm += step; render(); updateDSL();
      } else if (e.key === "ArrowLeft") {
        e.preventDefault(); excl.x_cm = Math.max(0, excl.x_cm - step); render(); updateDSL();
      } else if (e.key === "ArrowDown") {
        e.preventDefault(); excl.y_cm += step; render(); updateDSL();
      } else if (e.key === "ArrowUp") {
        e.preventDefault(); excl.y_cm = Math.max(0, excl.y_cm - step); render(); updateDSL();
      } else if (e.key === "Delete" || e.key === "Backspace") {
        e.preventDefault();
        markDirty();
        state.room_exclusions.splice(state.selectedExclusion, 1);
        state.selectedExclusion = -1;
        render(); updateDSL();
      }
      return;
    }

    // No block selected (PE, not amend): arrow keys navigate prev/next
    // pattern. PageUp/PageDown keep working too.
    if (state.selectedBlock < 0) {
      if (!inAmend && (e.key === "ArrowLeft" || e.key === "ArrowRight" ||
                       e.key === "ArrowUp" || e.key === "ArrowDown")) {
        e.preventDefault();
        if (window.peNavigate) {
          window.peNavigate(
            (e.key === "ArrowLeft" || e.key === "ArrowUp") ? -1 : 1);
        }
      }
      return;
    }
    // Selected block
    const row = state.rows[state.selectedRow];
    if (!row) return;
    const block = row.blocks[state.selectedBlock];
    if (!block) return;

    if (e.key === "ArrowRight") {
      e.preventDefault();
      offsetSelectedBlockEO(step);
    } else if (e.key === "ArrowLeft") {
      e.preventDefault();
      offsetSelectedBlockEO(-step);
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      offsetSelectedBlock(-step);
    } else if (e.key === "ArrowDown") {
      e.preventDefault();
      offsetSelectedBlock(step);
    } else if (e.key === "r" || e.key === "R") {
      e.preventDefault();
      rotateSelectedBlock();
    } else if (e.key === "Delete" || e.key === "Backspace") {
      e.preventDefault();
      markDirty();
      if (state.amendMode &&
          typeof deleteSelectedBlockKeepPositions === "function") {
        // Office / Amend layout: deleting a block must not move the others.
        deleteSelectedBlockKeepPositions();
      } else {
        row.blocks.splice(state.selectedBlock, 1);
        state.selectedBlock = -1;
        render(); updateDSL(); updateRowList();
        canonicalizeState();
      }
    }
  });

  // Homogeneous panel shortcuts: S = Save, D = Discard, R = Revert.
  // Each key clicks the matching button *only when it is visible*, so the
  // action auto-scopes to the active panel (Pattern editor, Amend layout,
  // Room amend, Office review). Reuses each button's own click handler and
  // its existing confirmation — no extra confirmation is introduced.
  // S stays LOCAL to an editing panel: it never triggers the global floor-plan
  // save (btnSavePlan, header-level, always visible) — that would, in Amend
  // layout, exit the amend and look like a discard.
  // R = Revert targets the Office "Revert" button only; in the editor/amend
  // R already rotates the selection (those handlers run first and call
  // preventDefault), and the Revert button is not visible there, so they
  // never collide.
  function _firstVisibleBtn(ids) {
    for (var i = 0; i < ids.length; i++) {
      var el = document.getElementById(ids[i]);
      if (el && el.offsetParent !== null) return el;
    }
    return null;
  }
  document.addEventListener("keydown", function(e) {
    if (e.target.tagName === "INPUT" || e.target.tagName === "TEXTAREA") return;
    if (e.ctrlKey || e.metaKey || e.altKey || e.defaultPrevented) return;
    var backdrop = document.getElementById("olmModalBackdrop");
    if (backdrop && backdrop.style.display !== "none") return;
    var btn = null;
    if ((e.key === "d" || e.key === "D") && e.shiftKey) {
      // Shift+D = Diag (dev-only, off-screen on small viewports).
      btn = _firstVisibleBtn(["fpBtnDiag", "rvBtnDiag"]);
    } else if (e.shiftKey) {
      return;
    } else if (e.key === "s" || e.key === "S") {
      btn = _firstVisibleBtn(
        ["btnSave", "rvBtnSaveRoom", "fpBtnSaveLayout"]);
    } else if (e.key === "d" || e.key === "D") {
      btn = _firstVisibleBtn(["btnAmendCancel", "rvBtnCancelRoom"]);
    } else if (e.key === "r" || e.key === "R") {
      btn = _firstVisibleBtn(["fpBtnDiscard"]);
    }
    if (btn) { e.preventDefault(); btn.click(); }
  });

  // Floor + Room sidebar resize handles extracted to
  // olm/static/init_resize.js as of D-94 P3.


  // Save button — writes directly to plan JSON on disk
  document.getElementById("btnSavePlan").addEventListener("click", function() {
    if (typeof window.savePlanToDisk === "function") {
      window.savePlanToDisk();
    } else {
      alertModal("Save not available — load a floor plan first.");
    }
  });

  // Candidate solutions help modal
  var candidateHelpLink = document.getElementById("candidateHelpToggle");
  if (candidateHelpLink) {
    candidateHelpLink.addEventListener("click", function() {
      var tip = document.getElementById("candidateHelpTooltip");
      var backdrop = document.getElementById("candidateHelpBackdrop");
      if (!tip) return;
      var show = tip.style.display === "none";
      tip.style.display = show ? "block" : "none";
      if (backdrop) backdrop.style.display = show ? "block" : "none";
    });
  }

  // Preview button
  document.getElementById("btnPreviewPlan").addEventListener("click", function() {
    if (typeof window.previewPlan === "function") window.previewPlan();
  });

  // Export dropdown toggle
  document.getElementById("btnExportPlan").addEventListener("click", function() {
    var menu = document.getElementById("exportMenu");
    menu.style.display = menu.style.display === "none" ? "" : "none";
  });
  document.getElementById("btnExportPng").addEventListener("click", function() {
    document.getElementById("exportMenu").style.display = "none";
    if (typeof window.exportPlan === "function") window.exportPlan("png");
  });
  document.getElementById("btnExportPdf").addEventListener("click", function() {
    document.getElementById("exportMenu").style.display = "none";
    if (typeof window.exportPlan === "function") window.exportPlan("pdf");
  });

  // Close button
  document.getElementById("btnClosePlan").addEventListener("click", function() {
    confirmModal("Close the current floor plan? Unsaved changes will be lost.").then(function(ok) {
    if (!ok) return;
    // Reset header
    var hdr = document.getElementById("hdrCurrentPlanText");
    if (hdr) { hdr.textContent = "Select a floor plan..."; hdr.style.fontStyle = "italic"; hdr.style.fontWeight = "normal"; hdr.style.color = "var(--text-dim)"; hdr.style.fontSize = "var(--fs-sm)"; }
    // Hide Save/Preview/Export/Close buttons + toolbar
    document.getElementById("btnSavePlan").style.display = "none";
    document.getElementById("btnPreviewPlan").style.display = "none";
    document.getElementById("exportWrapper").style.display = "none";
    document.getElementById("btnClosePlan").style.display = "none";
    var ingTbClose = document.getElementById("ingToolbar");
    if (ingTbClose) ingTbClose.style.display = "none";
    document.getElementById("eraseWrapper").style.display = "none";
    // Reset floor plan data (D-94: in-place reset preserves refs)
    window.olmStore.reset("floor");
    window.olmStore.reset("plan.overlay");
    window.olmStore.reset("amendments");
    // Clear ingestion SVG
    var svg = document.getElementById("ingSvg");
    if (svg) svg.innerHTML = "";
    // Clear room list
    var roomList = document.getElementById("ingRoomList");
    if (roomList) roomList.innerHTML = "";
    // Clear rooms JSON textarea
    var jsonTa = document.getElementById("fpRoomsJson");
    if (jsonTa) jsonTa.value = "";
    // Clear Design canvas
    var fpCanvas = document.getElementById("fpCanvas");
    if (fpCanvas) fpCanvas.innerHTML = "";
    var rvCanvas = document.getElementById("rvCanvas");
    if (rvCanvas) rvCanvas.innerHTML = "";
    // Clear Review room list and labels
    var rvList = document.getElementById("rvRoomPopupList");
    if (rvList) rvList.innerHTML = "";
    var rvLabel = document.getElementById("rvRoomLabel");
    if (rvLabel) rvLabel.textContent = "-";
    var rvNav = document.getElementById("rvNavInfo");
    if (rvNav) rvNav.textContent = "0 / 0";
    // Reset overlay toggles
    if (window.syncOverlayToggle) window.syncOverlayToggle(false);
    // Reset plan selection (new list-based selector)
    if (typeof window._ingSetSelectedPlan === "function") {
      window._ingSetSelectedPlan("", "");
    }
    var searchEl = document.getElementById("hdrPlanSearch");
    if (searchEl) searchEl.value = "";
    // Reset ingestion state rooms (keeps ingState identity; only rooms cleared)
    window.ingState.rooms = [];
    window.ingState.firstScanDone = false;
    window.ingState.focusedRoom = null;
    window.ingState.bboxEditor = {
      selectedName: null, sessionStartBbox: null,
      mode: 'idle', handle: null, dragStart: null
    };
    var ingLwReset = document.getElementById("ingLockWalls");
    if (ingLwReset) ingLwReset.checked = false;
    window.ingState.buildingId = '';
    window.ingState.floorId    = '';
    window.ingState.northAngleDeg = 0;
    if (typeof window.updateFloorMetadataUI === 'function') {
      window.updateFloorMetadataUI();
    }
    // Hide plan-dependent sections, disable Review/Design
    if (window.updatePlanDependentUI) window.updatePlanDependentUI();
    // Switch to Import tab
    var importBtn = document.querySelector('.tab-btn[data-tab="fpImport"]');
    if (importBtn) importBtn.click();
    }); // end confirmModal.then
  });

  // Erase dropdown toggle
  document.getElementById("btnErasePlan").addEventListener("click", function() {
    var menu = document.getElementById("eraseMenu");
    menu.style.display = menu.style.display === "none" ? "" : "none";
  });
  // Close dropdown menus on click outside
  document.addEventListener("click", function(e) {
    var wrapper = document.getElementById("eraseWrapper");
    if (wrapper && !wrapper.contains(e.target)) {
      document.getElementById("eraseMenu").style.display = "none";
    }
    var expWrapper = document.getElementById("exportWrapper");
    if (expWrapper && !expWrapper.contains(e.target)) {
      document.getElementById("exportMenu").style.display = "none";
    }
  });

  // Erase All — clear all data but keep plan loaded
  document.getElementById("btnEraseAll").addEventListener("click", function() {
    document.getElementById("eraseMenu").style.display = "none";
    var sel = window.ingState && window.ingState._selectedPlan;
    var planId = sel && sel.id;
    if (!planId) { alertModal("No plan loaded."); return; }
    confirmModal("Reinit: strip all detection and manual data from '" +
        planId + "' and re-import from scratch?").then(function(ok) {
    if (!ok) return;
    showModal("Reinitializing floor plan...");
    var statusEl = document.getElementById("ingStatus");
    if (statusEl) statusEl.textContent = "Reinit...";
    fetch("/api/plans/" + encodeURIComponent(planId) + "/reinit", {
      method: "POST",
    })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (data.error) {
          alertModal("Reinit error: " + data.error);
          if (statusEl) statusEl.textContent = "Reinit failed";
          return;
        }
        // Re-trigger import of the cleaned plan (skip switch confirm)
        window.ingState._skipSwitchConfirm = true;
        var planItem = document.querySelector(
          '.plan-item[data-plan-id="' + planId + '"]');
        if (planItem) {
          planItem.click();
        } else {
          // Fallback: switch to Import tab
          var importBtn = document.querySelector(
            '.tab-btn[data-tab="fpImport"]');
          if (importBtn) importBtn.click();
        }
      })
      .catch(function (e) {
        hideModal();
        alertModal("Reinit error: " + e);
        if (statusEl) statusEl.textContent = "Reinit failed";
      });
    }); // end confirmModal.then
  });

  // Erase Layout only — remove layout data, keep floorplan amendments
  document.getElementById("btnEraseLayout").addEventListener("click", function() {
    document.getElementById("eraseMenu").style.display = "none";
    confirmModal("Erase layout data only? Floor plan amendments will be kept.").then(function(ok) {
    if (!ok) return;
    // Clear layout-specific data (D-94: reset in place)
    window.olmStore.reset("amendments.layout");
    window.fpData.rooms.forEach(function(r) {
      r.candidates = [];
      r.selectedCandidate = null;
    });
    window.fpData.currentIdx = 0;
    // Clear Design canvas
    var fpCanvas = document.getElementById("fpCanvas");
    if (fpCanvas) fpCanvas.innerHTML = "";
    // Re-render if on Design tab
    if (typeof window.fpRenderCurrent === "function") window.fpRenderCurrent();
    }); // end confirmModal.then
  });
}

document.addEventListener("DOMContentLoaded", function() {
  init();
});
