"use strict";

async function init() {
  await loadAppConfig();
  await loadAllBlockDefs();
  await loadBlockDefs();
  await loadSpacingConfigs();
  renderSpacingSettings();
  renderGeneralSettings();
  initSettingsTabs();
  renderFloorplanSettings();
  renderEditorStandardRadios();
  renderCatStandardFilter();
  renderFpStandardFilter();

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
  // Default room
  state.room_windows = [{ face: "north", offset_cm: 0, width_cm: state.room_width_cm }];
  state.room_openings = [{ face: "south", offset_cm: 0, width_cm: APP_CONFIG.default_door_width_cm || 90, has_door: true, opens_inward: true, hinge_side: "left" }];
  updateAutoName();
  clearDirty();
  requestAnimationFrame(function() { zoomFit(); });
  loadCatalogue();

  document.getElementById("btnNew").addEventListener("click", resetState);
  document.getElementById("btnSave").addEventListener("click", save);
  document.getElementById("btnLoad").addEventListener("click", loadList);
  document.getElementById("btnDuplicate").addEventListener("click", duplicatePattern);
  document.getElementById("btnDelete").addEventListener("click", deletePattern);
  document.getElementById("btnAmendCancel").addEventListener("click", function() {
    clearDirty();
    if (state.roomAmendMode) {
      state.roomAmendMode = null;
      exitRoomAmendUI();
      document.querySelector('.tab-btn[data-tab="fpReview"]').click();
    } else if (state.amendMode) {
      state.amendMode = null;
      exitAmendUI();
      document.querySelector('.tab-btn[data-tab="lytDesign"]').click();
      fpRenderCurrent();
    } else if (state._savedName) {
      // Dirty editor, not amend — reload saved pattern
      loadPattern(state._savedName);
    } else {
      // New unsaved pattern — reset to empty
      resetState();
    }
    setStatus("Cancelled.");
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
      if (!resp.ok) { var err = await resp.json(); alert("Error: " + (err.error || "?")); return; }
      var data = await resp.json();
      // D-83: DSL is in local coordinates — state is also in local, no conversion needed
      state.room_width_cm = data.width_cm;
      state.room_depth_cm = data.depth_cm;
      state.room_windows = data.windows || [];
      state.room_openings = data.openings || [];
      state.room_exclusions = data.exclusion_zones || [];
      render(document.getElementById("rvCanvas"));
      zoomFit(document.getElementById("rvCanvas"));
      rvUpdateRoomInfo();
    } catch (err) { alert("Error: " + err.message); }
  });
  document.getElementById("rvBtnSaveRoom").addEventListener("click", function() {
    if (state.roomAmendMode) save();
  });
  document.getElementById("rvBtnCancelRoom").addEventListener("click", function() {
    if (!state.roomAmendMode) return;
    state.roomAmendMode = null;
    exitRoomAmendUI();
    rvRenderCurrent();
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

  // Wall stick checkboxes
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
      updateDSL();
      render();
    });
  });
  document.getElementById("btnModalClose").addEventListener("click", function() {
    document.getElementById("loadModal").classList.remove("active");
  });
  document.getElementById("gridToggle").addEventListener("change", function(e) {
    state.gridVisible = e.target.checked;
    document.getElementById("fpGridToggle").checked = e.target.checked;
    render();
  });
  document.getElementById("circToggle").addEventListener("change", function(e) {
    state.circVisible = e.target.checked;
    document.getElementById("fpCircToggle").checked = e.target.checked;
    render();
  });
  // fpGridToggle and fpCircToggle are wired in floor_plan.js
  // (they need access to fpCurrent/fpCurrentCandidate to re-render correctly)

  // Room dimensions
  function onRoomChange() {
    markDirty();
    var oldW = state.room_width_cm;
    var oldD = state.room_depth_cm;
    state.room_width_cm = parseInt(document.getElementById("roomWidth").value) || 300;
    state.room_depth_cm = parseInt(document.getElementById("roomDepth").value) || 480;
    // Update full-width windows
    state.room_windows.forEach(function(w) {
      var wallOld = (w.face === "north" || w.face === "south") ? oldW : oldD;
      var wallNew = (w.face === "north" || w.face === "south") ? state.room_width_cm : state.room_depth_cm;
      if (w.offset_cm === 0 && w.width_cm === wallOld) {
        w.width_cm = wallNew;
      }
    });
    updateAutoName();
    zoomFit();
  }
  document.getElementById("roomWidth").addEventListener("change", onRoomChange);
  document.getElementById("roomDepth").addEventListener("change", onRoomChange);
  document.getElementById("btnWidthMinus").addEventListener("click", function() {
    var el = document.getElementById("roomWidth");
    el.value = Math.max(100, (parseInt(el.value) || 300) - 10);
    onRoomChange();
  });
  document.getElementById("btnWidthPlus").addEventListener("click", function() {
    var el = document.getElementById("roomWidth");
    el.value = (parseInt(el.value) || 300) + 10;
    onRoomChange();
  });
  document.getElementById("btnDepthMinus").addEventListener("click", function() {
    var el = document.getElementById("roomDepth");
    el.value = Math.max(100, (parseInt(el.value) || 480) - 10);
    onRoomChange();
  });
  document.getElementById("btnDepthPlus").addEventListener("click", function() {
    var el = document.getElementById("roomDepth");
    el.value = (parseInt(el.value) || 480) + 10;
    onRoomChange();
  });

  // Standard
  document.querySelectorAll('input[name="standard"]').forEach(function(r) {
    r.addEventListener("change", async function() {
      state.standard = r.value;
      CURRENT_SPACING = SPACING_CONFIGS[state.standard] || null;
      await loadBlockDefs();
      updateAutoName();
      render();
    });
  });

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

  // Cancel any active amend mode when navigating away from editor
  function _cancelAmendIfActive() {
    if (state.amendMode) {
      if (state.dirty && !confirm("Unsaved layout changes will be lost. Continue?")) return false;
      state.amendMode = null;
      exitAmendUI();
      _restoreEditorState();
    }
    if (state.roomAmendMode) {
      if (!confirm("Unsaved room changes will be lost. Continue?")) return false;
      state.roomAmendMode = null;
      exitRoomAmendUI();
    }
    return true;
  }

  // Tab descriptions (flat nav — 4 tabs)
  var TAB_DESCRIPTIONS = {
    "fpImport": "Load the floor plan and manage rooms",
    "fpReview": "Review and adjust each room",
    "lytDesign": "Office layout for each room",
    "lytCatalogue": "Browse and edit the pattern catalogue",
  };

  // Main tabs (flat nav)
  document.querySelectorAll(".tab-btn").forEach(function(btn) {
    btn.addEventListener("click", function() {
      var isLayoutTab = btn.dataset.tab === "lytDesign" || btn.dataset.tab === "lytCatalogue";
      // Cancel amend mode when leaving Layout tabs
      if (!isLayoutTab) {
        if (_cancelAmendIfActive() === false) return;
        _saveEditorState();
      }
      document.querySelectorAll(".tab-btn").forEach(function(b) { b.classList.remove("active"); });
      document.querySelectorAll(".tab-content").forEach(function(c) { c.classList.remove("active"); });
      btn.classList.add("active");
      var tabId = "tab" + btn.dataset.tab.charAt(0).toUpperCase() + btn.dataset.tab.slice(1);
      var tab = document.getElementById(tabId);
      if (tab) tab.classList.add("active");
      var descEl = document.getElementById("tabDescription");
      if (descEl) descEl.textContent = TAB_DESCRIPTIONS[btn.dataset.tab] || "";
      if (isLayoutTab) {
        _restoreEditorState();
        loadCatalogue();
      }
      if (btn.dataset.tab === "fpReview") {
        rvRenderCurrent();
      }
    });
  });

  // Sub-tabs (Catalogue sub-tab-bar)
  var SUB_TAB_DESCRIPTIONS = {
    "catCards": "Browse patterns as cards",
    "catGrid": "Patterns organized by room dimensions",
    "catEditor": "Create and edit patterns",
  };

  function _updateSubTabDescription(subtabName) {
    var el = document.getElementById("subTabDescription");
    if (el) el.textContent = SUB_TAB_DESCRIPTIONS[subtabName] || "";
  }

  document.querySelectorAll(".sub-tab-btn").forEach(function(btn) {
    btn.addEventListener("click", function() {
      if (btn.dataset.subtab !== "catEditor") {
        if (_cancelAmendIfActive() === false) return;
      }
      var bar = btn.parentElement;
      bar.querySelectorAll(":scope > .sub-tab-btn").forEach(function(b) { b.classList.remove("active"); });
      btn.classList.add("active");
      var parentTab = bar.parentElement;
      parentTab.querySelectorAll(":scope > .sub-tab-content").forEach(function(c) { c.classList.remove("active"); });
      var subtab = document.getElementById("subtab" + btn.dataset.subtab.charAt(0).toUpperCase() + btn.dataset.subtab.slice(1));
      if (subtab) subtab.classList.add("active");
      _updateSubTabDescription(btn.dataset.subtab);
      if (btn.dataset.subtab === "catCards") loadCatalogue();
      if (btn.dataset.subtab === "catGrid") { loadCatalogue(); renderMatrixView(); }
    });
  });
  // Initial description
  _updateSubTabDescription("catCards");

  // Matrix pan/zoom
  initMatrixPanZoom();
  document.getElementById("btnMatrixZoomIn").addEventListener("click", function() { matrixZoomBy(0.8); });
  document.getElementById("btnMatrixZoomOut").addEventListener("click", function() { matrixZoomBy(1.25); });
  document.getElementById("btnMatrixZoomFit").addEventListener("click", matrixZoomFit);

  // Catalogue import/export
  document.getElementById("btnCatExport").addEventListener("click", function() {
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
  });

  document.getElementById("btnCatImport").addEventListener("click", function() {
    document.getElementById("catImportFile").click();
  });
  document.getElementById("catImportFile").addEventListener("change", function(e) {
    var file = e.target.files[0];
    if (!file) return;
    var reader = new FileReader();
    reader.onload = function(ev) {
      var data;
      try { data = JSON.parse(ev.target.result); } catch(err) {
        alert("Invalid JSON: " + err.message); return;
      }
      if (!data.patterns || !Array.isArray(data.patterns)) {
        alert("Invalid format: 'patterns' key expected"); return;
      }
      fetch("/api/catalogue/import", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data),
      })
      .then(function(r) { return r.json(); })
      .then(function(resp) {
        if (resp.error) { alert("Import error: " + resp.error); return; }
        alert(resp.imported + " pattern(s) imported. Total: " + resp.total);
        loadCatalogue();
      });
    };
    reader.readAsText(file);
    e.target.value = "";
  });

  // Catalogue filters — update both views
  function onCatalogueFilterChange() {
    renderCatalogue();
  }
  document.getElementById("catFilterStandard").addEventListener("change", onCatalogueFilterChange);
  document.getElementById("catFilterMinW").addEventListener("change", onCatalogueFilterChange);
  document.getElementById("catFilterMaxW").addEventListener("change", onCatalogueFilterChange);
  document.getElementById("catFilterMinD").addEventListener("change", onCatalogueFilterChange);
  document.getElementById("catFilterMaxD").addEventListener("change", onCatalogueFilterChange);
  document.getElementById("btnRotate").addEventListener("click", rotateSelectedBlock);
  document.getElementById("btnOffsetN").addEventListener("click", function() { offsetSelectedBlock(-GRID_STEP_CM); });
  document.getElementById("btnOffsetS").addEventListener("click", function() { offsetSelectedBlock(GRID_STEP_CM); });
  document.getElementById("btnOffsetW").addEventListener("click", function() { offsetSelectedBlockEO(-GRID_STEP_CM); });
  document.getElementById("btnOffsetE").addEventListener("click", function() { offsetSelectedBlockEO(GRID_STEP_CM); });
  document.getElementById("loadModal").addEventListener("click", function(e) {
    if (e.target === document.getElementById("loadModal")) {
      document.getElementById("loadModal").classList.remove("active");
    }
  });

  document.getElementById("btnZoomIn").addEventListener("click", function() { zoomIn(); });
  document.getElementById("btnZoomOut").addEventListener("click", function() { zoomOut(); });
  document.getElementById("btnZoomFit").addEventListener("click", function() { zoomFit(); });

  const canvas = document.getElementById("canvas");
  var _panSvg = null;  // which SVG is currently being panned

  function setupPan(svg) {
    svg.addEventListener("mousedown", function(e) {
      if (e.target.closest("[data-row]") || e.target.closest("[data-excl]")) return;
      if (svg.id === "rvCanvas" && window.rvTool &&
          (window.rvTool.mode === "placing" || window.rvTool.mode === "drawing")) return;
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

  // rvTool (forbidden-zone interaction for Review amend mode) extracted
  // to olm/static/init_rvtool.js as of D-94 P3.

  document.addEventListener("mousemove", function(e) {
    if (zoomSel.active) { zoomSelMove(e); return; }
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
    var exclTarget = e.target.closest("[data-excl]");
    if (exclTarget) {
      state.selectedExclusion = parseInt(exclTarget.dataset.excl);
      state.selectedBlock = -1;
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
    } else {
      state.selectedBlock = -1;
      state.selectedExclusion = -1;
    }
    render();
    updateRowList();
  });

  document.addEventListener("keydown", function(e) {
    if (e.target.tagName === "INPUT" || e.target.tagName === "TEXTAREA") return;
    // Keyboard editing only in Catalogue > Editor or amend mode
    var activeTab = document.querySelector(".tab-btn.active");
    var inEditor = activeTab && activeTab.dataset.tab === "lytCatalogue";
    var inAmend = !!state.amendMode;
    if (!inEditor && !inAmend) return;
    var editorSub = document.getElementById("subtabCatEditor");
    if (!inAmend && (!editorSub || !editorSub.classList.contains("active"))) return;
    const step = e.shiftKey ? GRID_STEP_CM * 5 : GRID_STEP_CM;

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

    // Selected block
    if (state.selectedBlock < 0) return;
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
      row.blocks.splice(state.selectedBlock, 1);
      state.selectedBlock = -1;
      render(); updateDSL(); updateRowList();
    }
  });

  // Floor + Room sidebar resize handles extracted to
  // olm/static/init_resize.js as of D-94 P3.

  var descEl = document.getElementById("tabDescription");
  if (descEl) descEl.textContent = TAB_DESCRIPTIONS["fpImport"] || "";

  // Save button
  document.getElementById("btnSavePlan").addEventListener("click", function() {
    // TODO R-11: replace with POST /api/save that writes the enriched JSON with olm_state to disk
    if (typeof window.devExportV3Json === "function") {
      window.devExportV3Json();
    } else {
      alert("Save not available yet — load a floor plan first.");
    }
  });

  // Export button — download current state as JSON file
  document.getElementById("btnExportPlan").addEventListener("click", function() {
    if (typeof window.devExportV3Json === "function") {
      window.devExportV3Json();
    } else {
      alert("Export not available — load a floor plan first.");
    }
  });

  // Close button
  document.getElementById("btnClosePlan").addEventListener("click", function() {
    if (!confirm("Close the current floor plan? Unsaved changes will be lost.")) return;
    // Reset header
    var hdr = document.getElementById("hdrCurrentPlan");
    if (hdr) hdr.textContent = "";
    // Hide Save/Export/Close buttons + toolbar
    document.getElementById("btnSavePlan").style.display = "none";
    document.getElementById("btnExportPlan").style.display = "none";
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
    // Reset overlay toggles
    var fpTog = document.getElementById("fpOverlayToggle");
    if (fpTog) fpTog.checked = false;
    var rvTog = document.getElementById("rvOverlayToggle");
    if (rvTog) rvTog.checked = false;
    // Reset plan dropdown to placeholder
    var planSel = document.getElementById("ingPlanIdSelect");
    if (planSel) planSel.selectedIndex = 0;
    // Reset ingestion state rooms (keeps ingState identity; only rooms cleared)
    window.ingState.rooms = [];
    // Hide plan-dependent sections, disable Review/Design
    if (window.updatePlanDependentUI) window.updatePlanDependentUI();
    // Switch to Import tab
    var importBtn = document.querySelector('.tab-btn[data-tab="fpImport"]');
    if (importBtn) importBtn.click();
  });

  // Erase dropdown toggle
  document.getElementById("btnErasePlan").addEventListener("click", function() {
    var menu = document.getElementById("eraseMenu");
    menu.style.display = menu.style.display === "none" ? "" : "none";
  });
  // Close menu on click outside
  document.addEventListener("click", function(e) {
    var wrapper = document.getElementById("eraseWrapper");
    if (wrapper && !wrapper.contains(e.target)) {
      document.getElementById("eraseMenu").style.display = "none";
    }
  });

  // Erase All — clear all data but keep plan loaded
  document.getElementById("btnEraseAll").addEventListener("click", function() {
    document.getElementById("eraseMenu").style.display = "none";
    if (!confirm("Erase all data (floor plan + layouts)?")) return;
    // Clear layout data (D-94: reset in place)
    window.olmStore.reset("amendments");
    window.fpData.rooms.forEach(function(r) {
      r.candidates = [];
      r.selectedCandidate = null;
    });
    window.fpData.currentIdx = 0;
    // Clear Design/Review canvases
    var fpCanvas = document.getElementById("fpCanvas");
    if (fpCanvas) fpCanvas.innerHTML = "";
    var rvCanvas = document.getElementById("rvCanvas");
    if (rvCanvas) rvCanvas.innerHTML = "";
    // Clear ingestion room amendments (bbox edits, exclusions, openings)
    var rooms = window.ingState ? window.ingState.rooms : [];
    rooms.forEach(function(r) {
      r.exclusion_zones = [];
      r.amendments = null;
    });
    // Re-render and switch to Import
    var importBtn = document.querySelector('.tab-btn[data-tab="fpImport"]');
    if (importBtn) importBtn.click();
  });

  // Erase Layout only — remove layout data, keep floorplan amendments
  document.getElementById("btnEraseLayout").addEventListener("click", function() {
    document.getElementById("eraseMenu").style.display = "none";
    if (!confirm("Erase layout data only? Floor plan amendments will be kept.")) return;
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
  });
}

document.addEventListener("DOMContentLoaded", function() {
  init();
});
