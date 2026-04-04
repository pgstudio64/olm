"use strict";

async function init() {
  await loadAppConfig();
  await loadAllBlockDefs();
  await loadBlockDefs();
  await loadSpacingConfigs();
  renderSpacingSettings();
  renderGeneralSettings();
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
  addRow(false);
  // Default room
  state.room_windows = [{ face: "north", offset_cm: 0, width_cm: state.room_width_cm }];
  state.room_openings = [{ face: "south", offset_cm: 0, width_cm: 90, has_door: true, opens_inward: true, hinge_side: "left" }];
  updateAutoName();
  requestAnimationFrame(function() { zoomFit(); });
  loadCatalogue();

  document.getElementById("btnNew").addEventListener("click", resetState);
  document.getElementById("btnSave").addEventListener("click", save);
  document.getElementById("btnLoad").addEventListener("click", loadList);
  document.getElementById("btnDuplicate").addEventListener("click", duplicatePattern);
  document.getElementById("btnDelete").addEventListener("click", deletePattern);
  document.getElementById("btnAmendCancel").addEventListener("click", function() {
    if (state.roomAmendMode) {
      state.roomAmendMode = null;
      exitRoomAmendUI();
    } else {
      state.amendMode = null;
      exitAmendUI();
    }
    // Switch back to Floor Plan > Review
    document.querySelector('.tab-btn[data-tab="floorPlan"]').click();
    document.querySelector('.sub-tab-btn[data-subtab="fpReview"]').click();
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

  function showDslHelp(anchor) {
    var tip = document.getElementById("dslHelpTooltip");
    var visible = tip.style.display !== "none";
    if (visible) { tip.style.display = "none"; return; }
    var rect = anchor.getBoundingClientRect();
    tip.style.left = Math.min(rect.left, window.innerWidth - 420) + "px";
    tip.style.top = (rect.bottom + 4) + "px";
    tip.style.display = "";
    tip.style.pointerEvents = "none";
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
  document.addEventListener("click", function(e) {
    if (e.target.id !== "dslHelpToggle" && e.target.id !== "rvDslHelpToggle") {
      document.getElementById("dslHelpTooltip").style.display = "none";
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
    render();
  });
  document.getElementById("circToggle").addEventListener("change", function(e) {
    state.circVisible = e.target.checked;
    render();
  });

  // Room dimensions
  function onRoomChange() {
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
      state.amendMode = null;
      exitAmendUI();
      _restoreEditorState();
    }
    if (state.roomAmendMode) {
      state.roomAmendMode = null;
      exitRoomAmendUI();
    }
  }

  // Main tabs
  document.querySelectorAll(".tab-btn").forEach(function(btn) {
    btn.addEventListener("click", function() {
      // Cancel amend mode when leaving Office Layout
      if (btn.dataset.tab !== "officeLayout") {
        _cancelAmendIfActive();
        _saveEditorState();
      }
      document.querySelectorAll(".tab-btn").forEach(function(b) { b.classList.remove("active"); });
      document.querySelectorAll(".tab-content").forEach(function(c) { c.classList.remove("active"); });
      btn.classList.add("active");
      var tabId = "tab" + btn.dataset.tab.charAt(0).toUpperCase() + btn.dataset.tab.slice(1);
      var tab = document.getElementById(tabId);
      if (tab) tab.classList.add("active");
      if (btn.dataset.tab === "officeLayout") {
        _restoreEditorState();
        loadCatalogue();
      }
    });
  });

  // Sub-tabs
  document.querySelectorAll(".sub-tab-btn").forEach(function(btn) {
    btn.addEventListener("click", function() {
      // Cancel amend mode when leaving editor sub-tab
      if (btn.dataset.subtab !== "olEditor") {
        _cancelAmendIfActive();
      }
      var parent = btn.dataset.parent;
      // Deactivate sibling sub-tabs
      var bar = btn.parentElement;
      bar.querySelectorAll(".sub-tab-btn").forEach(function(b) { b.classList.remove("active"); });
      btn.classList.add("active");
      // Show/hide sub-tab content
      var parentTab = bar.parentElement;
      parentTab.querySelectorAll(".sub-tab-content").forEach(function(c) { c.classList.remove("active"); });
      var subtab = document.getElementById("subtab" + btn.dataset.subtab.charAt(0).toUpperCase() + btn.dataset.subtab.slice(1));
      if (subtab) subtab.classList.add("active");
      // Trigger view-specific renders
      if (btn.dataset.subtab === "fpReview") rvRenderCurrent();
      if (btn.dataset.subtab === "olCatalogue") loadCatalogue();
    });
  });

  // Catalogue view toggle
  document.getElementById("btnViewCards").classList.add("active");
  document.getElementById("btnViewCards").addEventListener("click", function() { setCatalogueView("cards"); });
  document.getElementById("btnViewMatrix").addEventListener("click", function() { setCatalogueView("matrix"); });
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
    if (catalogueViewMode === "matrix") {
      renderMatrixView();
    } else {
      renderCatalogue();
    }
  }
  document.getElementById("catFilterStandard").addEventListener("change", onCatalogueFilterChange);
  document.getElementById("catFilterMinW").addEventListener("change", onCatalogueFilterChange);
  document.getElementById("catFilterMaxW").addEventListener("change", onCatalogueFilterChange);
  document.getElementById("catFilterMinD").addEventListener("change", onCatalogueFilterChange);
  document.getElementById("catFilterMaxD").addEventListener("change", onCatalogueFilterChange);
  document.getElementById("btnRotate").addEventListener("click", rotateSelectedBlock);
  document.getElementById("btnOffsetN").addEventListener("click", function() { offsetSelectedBlock(-10); });
  document.getElementById("btnOffsetS").addEventListener("click", function() { offsetSelectedBlock(10); });
  document.getElementById("btnOffsetW").addEventListener("click", function() { offsetSelectedBlockEO(-10); });
  document.getElementById("btnOffsetE").addEventListener("click", function() { offsetSelectedBlockEO(10); });
  document.getElementById("loadModal").addEventListener("click", function(e) {
    if (e.target === document.getElementById("loadModal")) {
      document.getElementById("loadModal").classList.remove("active");
    }
  });

  document.getElementById("btnZoomIn").addEventListener("click", zoomIn);
  document.getElementById("btnZoomOut").addEventListener("click", zoomOut);
  document.getElementById("btnZoomFit").addEventListener("click", zoomFit);

  const canvas = document.getElementById("canvas");

  canvas.addEventListener("mousedown", function(e) {
    if (e.target.closest("[data-row]") || e.target.closest("[data-excl]")) return;
    if (e.button !== 0) return;
    // Shift+drag = zoom rectangle
    if (zoomSelStart(e, canvas, state.viewBox, function() { updateViewBox(); render(); })) return;
    state.isPanning = true;
    state.panStart = { x: e.clientX, y: e.clientY };
    canvas.classList.add("panning");
    e.preventDefault();
  });

  document.addEventListener("mousemove", function(e) {
    if (zoomSel.active) { zoomSelMove(e); return; }
    if (!state.isPanning) return;
    const dx = e.clientX - state.panStart.x;
    const dy = e.clientY - state.panStart.y;
    state.panStart = { x: e.clientX, y: e.clientY };
    const rect = canvas.getBoundingClientRect();
    state.viewBox.x -= dx * (state.viewBox.w / rect.width);
    state.viewBox.y -= dy * (state.viewBox.h / rect.height);
    updateViewBox();
  });

  document.addEventListener("mouseup", function(e) {
    if (zoomSel.active) { zoomSelEnd(e); return; }
    if (state.isPanning) {
      state.isPanning = false;
      canvas.classList.remove("panning");
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
    // No block selection in Floor Plan mode
    var activeTab = document.querySelector(".tab-btn.active");
    if (activeTab && activeTab.dataset.tab === "floorPlan") return;
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
    // No keyboard editing in Floor Plan mode (arrows, rotation, delete)
    var activeTab = document.querySelector(".tab-btn.active");
    if (activeTab && activeTab.dataset.tab === "floorPlan") return;
    const step = e.shiftKey ? 50 : 10;

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
      offsetSelectedBlock(e.shiftKey ? -50 : -10);
    } else if (e.key === "ArrowDown") {
      e.preventDefault();
      offsetSelectedBlock(e.shiftKey ? 50 : 10);
    } else if (e.key === "r" || e.key === "R") {
      e.preventDefault();
      rotateSelectedBlock();
    } else if (e.key === "Delete" || e.key === "Backspace") {
      e.preventDefault();
      row.blocks.splice(state.selectedBlock, 1);
      state.selectedBlock = -1;
      render(); updateDSL(); updateRowList();
    }
  });
}

document.addEventListener("DOMContentLoaded", init);
