"use strict";

// --- Listener tracking (P1.4) ---
var _cfgListeners = [];
function _cfgTrack(el, event, handler, options) {
  el.addEventListener(event, handler, options);
  _cfgListeners.push({ el: el, event: event, handler: handler, options: options });
}
function _cfgDispose() {
  _cfgListeners.forEach(function(l) {
    l.el.removeEventListener(l.event, l.handler, l.options);
  });
  _cfgListeners = [];
}

async function loadSpacingConfigs() {
  try {
    var resp = await fetch("/api/spacing");
    if (resp.ok) {
      var data = await resp.json();
      // data is {slot: {label, spacing: {...}}} — extract spacing dicts
      SPACING_CONFIGS = {};
      Object.keys(data).forEach(function(slot) {
        SPACING_CONFIGS[slot] = data[slot].spacing || {};
      });
      CURRENT_SPACING = SPACING_CONFIGS[state.standard] || null;
    }
  } catch (e) { /* silent */ }
}

var APP_CONFIG = {};

async function loadAppConfig() {
  try {
    var resp = await fetch("/api/config");
    if (resp.ok) APP_CONFIG = await resp.json();
  } catch (e) { console.warn("Failed to load config:", e); }
  // Propagate config to rendering constants (direct mapping)
  if (APP_CONFIG.desk_width_cm) DESK_W = APP_CONFIG.desk_width_cm;
  if (APP_CONFIG.desk_depth_cm) DESK_D = APP_CONFIG.desk_depth_cm;
  if (APP_CONFIG.grid_cell_cm) GRID_STEP_CM = APP_CONFIG.grid_cell_cm;
  // Sync HTML step attributes with GRID_STEP_CM
  ["roomWidth", "roomDepth", "gapIntra",
   "catFilterMinW", "catFilterMaxW", "catFilterMinD", "catFilterMaxD"
  ].forEach(function(id) {
    var el = document.getElementById(id);
    if (el) el.step = GRID_STEP_CM;
  });
  // D-156 : afficher la version OLM dans le header Settings.
  var verEl = document.getElementById("settingsVersion");
  if (verEl && APP_CONFIG.olm_version) {
    var suffix = APP_CONFIG.dev_mode ? " [DEV]" : "";
    verEl.textContent = "v" + APP_CONFIG.olm_version + suffix;
  }
  // D-229 §2.8: hydrate circulation toggle from config (default: visible)
  if (typeof state !== "undefined") {
    var circVal = APP_CONFIG.circulation_visible != null
      ? APP_CONFIG.circulation_visible : true;
    state.circVisible = circVal;
    var cb1 = document.getElementById("circToggle");
    var cb2 = document.getElementById("fpCircToggle");
    if (cb1) cb1.checked = circVal;
    if (cb2) cb2.checked = circVal;
  }
  // Apply dev-mode class on body to reveal dev-only elements.
  if (APP_CONFIG.dev_mode) {
    document.body.classList.add("dev-mode");
  } else {
    document.body.classList.remove("dev-mode");
  }
}

function getStandards() {
  if (APP_CONFIG.standards) return Object.keys(APP_CONFIG.standards);
  return [];
}

function getStdLabel(slot) {
  if (APP_CONFIG.standards && APP_CONFIG.standards[slot]) {
    return APP_CONFIG.standards[slot].label || slot;
  }
  return slot;
}

function getCurrentStandard() {
  return APP_CONFIG.current_standard || "";
}

async function saveConfigField(keyOrPath, value) {
  var body;
  if (Array.isArray(keyOrPath)) {
    body = { path: keyOrPath, value: value };
  } else {
    body = { key: keyOrPath, value: value };
  }
  try {
    var resp = await fetch("/api/config", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!resp.ok) throw new Error(await resp.text());
    await loadAppConfig();
  } catch (e) {
    console.error("Config save error:", e);
  }
}

var SPACING_FIELDS = [
  { group: "Workstation", key: "chair_clearance_cm",
    label: "Chair clearance",
    help: "Depth for the chair to roll back from the desk (ES-01)" },
  { key: "slip_in_margin_cm",
    label: "Slip-in margin",
    help: "Space for a person to reach and pull back a chair at an isolated desk (ES-03)" },
  { group: "Circulation", key: "walking_margin_cm",
    label: "Walking margin",
    help: "Free width for a person to walk past a seated occupant (ES-02)" },
  { key: "main_corridor_cm",
    label: "Main corridor width",
    help: "Width of the main evacuation corridor (ES-04)" },
  { key: "door_exclusion_depth_cm",
    label: "Door clearance zone",
    help: "Depth of the clear zone in front of a door (ES-05)" },
  { group: "Layout", key: "max_island_size",
    label: "Max island size",
    help: "Maximum number of desks in a continuous island (ES-06)" },
];

function renderSpacingSettings() {
  var grid = document.getElementById("spacingSettingsGrid");
  if (!grid || !SPACING_CONFIGS) return;
  var stds = getStandards();
  var nCols = 1 + stds.length;  // parameter + one col per standard
  var html = '<div style="font-weight:bold;color:var(--text-dim);">Parameter</div>';
  stds.forEach(function(s) {
    html += '<div style="font-weight:bold;text-align:center;color:var(--accent);">' +
      getStdLabel(s) + '</div>';
  });
  SPACING_FIELDS.forEach(function(f) {
    // Group header row spanning all columns
    if (f.group) {
      html += '<div style="grid-column:1/-1;color:var(--accent);font-weight:bold;' +
        'font-size:10px;letter-spacing:0.1em;text-transform:uppercase;' +
        'margin-top:8px;padding-bottom:2px;border-bottom:1px solid var(--border);">' +
        f.group + '</div>';
    }
    html += '<div style="color:var(--text-dim);padding:2px 0;">' + f.label + '</div>';
    stds.forEach(function(s) {
      var val = SPACING_CONFIGS[s] ? SPACING_CONFIGS[s][f.key] : "";
      html += '<div><input type="number" data-std="' + s + '" data-field="' + f.key +
        '" value="' + val + '" style="width:80px;background:var(--surface);border:1px solid var(--border);' +
        'color:var(--text);font-family:var(--font-mono);font-size:11px;padding:2px 4px;text-align:right;"></div>';
    });
  });
  grid.innerHTML = html;

  // Wire change events — dispose previous before re-binding
  _cfgDispose();
  grid.querySelectorAll("input[data-std]").forEach(function(inp) {
    var handler = function() {
      saveSpacingField(inp.dataset.std, inp.dataset.field, parseInt(inp.value) || 0);
    };
    _cfgTrack(inp, "change", handler);
  });

  // Help link — opens centered modal with parameter definitions
  var helpLink = document.getElementById("spacingHelpToggle");
  if (helpLink) {
    helpLink.onclick = function() {
      var tip = document.getElementById("spacingHelpTooltip");
      var backdrop = document.getElementById("spacingHelpBackdrop");
      if (!tip) return;
      var show = tip.style.display === "none";
      tip.style.display = show ? "block" : "none";
      if (backdrop) backdrop.style.display = show ? "block" : "none";
    };
  }
}

// Standard controlled by Settings radio only (D-230).
// Badge in header updated by updateActiveStandardBadge().

function updateActiveStandardBadge() {
  var el = document.getElementById("hdrActiveStandard");
  if (!el) return;
  var current = getCurrentStandard();
  var label = getStdLabel(current);
  el.textContent = label ? "Standard: " + label : "";
}

function renderGeneralSettings() {
  if (!APP_CONFIG) return;

  var el;
  el = document.getElementById("cfgRoomCode");
  if (el) { el.value = APP_CONFIG.room_code || "14"; el.onchange = function() { saveConfigField("room_code", this.value); }; }

  el = document.getElementById("cfgDoorWidth");
  if (el) { el.value = APP_CONFIG.default_door_width_cm || 90; el.onchange = function() { saveConfigField("default_door_width_cm", parseInt(this.value)||90); }; }

  el = document.getElementById("cfgDeskW");
  if (el) { el.value = APP_CONFIG.desk_width_cm || 80; el.onchange = function() {
    saveConfigField("desk_width_cm", parseInt(this.value)||80).then(function() {
      loadAllBlockDefs().then(function() { loadBlockDefs().then(function() { render(); }); });
    });
  }; }

  el = document.getElementById("cfgDeskD");
  if (el) { el.value = APP_CONFIG.desk_depth_cm || 180; el.onchange = function() {
    saveConfigField("desk_depth_cm", parseInt(this.value)||180).then(function() {
      loadAllBlockDefs().then(function() { loadBlockDefs().then(function() { render(); }); });
    });
  }; }

  el = document.getElementById("cfgGrid");
  if (el) { el.value = APP_CONFIG.grid_cell_cm || 10; el.onchange = function() { saveConfigField("grid_cell_cm", parseInt(this.value)||10).then(function() { render(); }); }; }

  // New pattern defaults (Settings > Catalogue)
  el = document.getElementById("cfgDefPatternW");
  if (el) { el.value = APP_CONFIG.default_pattern_width_cm || 300; el.onchange = function() { saveConfigField("default_pattern_width_cm", parseInt(this.value)||300); }; }

  el = document.getElementById("cfgDefPatternD");
  if (el) { el.value = APP_CONFIG.default_pattern_depth_cm || 480; el.onchange = function() { saveConfigField("default_pattern_depth_cm", parseInt(this.value)||480); }; }

  el = document.getElementById("cfgDefPatternDoor");
  if (el) { el.value = APP_CONFIG.default_pattern_door_position || "left"; el.onchange = function() { saveConfigField("default_pattern_door_position", this.value); }; }

  el = document.getElementById("cfgPlansDir");
  if (el) {
    var ing = APP_CONFIG.ingestion || {};
    el.value = ing.plans_dir || "project/plans";
    el.onchange = function() { saveConfigField(["ingestion", "plans_dir"], this.value); };
  }

  el = document.getElementById("cfgWindowMode");
  if (el) {
    el.value = (APP_CONFIG.ingestion || {}).window_mode || "simple";
    el.onchange = function() { saveConfigField(["ingestion", "window_mode"], this.value); };
  }

  var matching = APP_CONFIG.matching || {};
  el = document.getElementById("cfgWDensity");
  if (el) { el.value = matching.w_density != null ? matching.w_density : 0.5; el.onchange = function() { saveConfigField(["matching", "w_density"], parseFloat(this.value)||0.5); }; }

  el = document.getElementById("cfgWComfort");
  if (el) { el.value = matching.w_comfort != null ? matching.w_comfort : 0.5; el.onchange = function() { saveConfigField(["matching", "w_comfort"], parseFloat(this.value)||0.5); }; }

  el = document.getElementById("cfgWBackDoor");
  if (el) { el.value = matching.w_back_door != null ? matching.w_back_door : 0; el.onchange = function() { saveConfigField(["matching", "w_back_door"], parseFloat(this.value)||0); }; }

  el = document.getElementById("cfgWLight");
  if (el) { el.value = matching.w_light != null ? matching.w_light : 0; el.onchange = function() { saveConfigField(["matching", "w_light"], parseFloat(this.value)||0); }; }

  el = document.getElementById("cfgWFaceWall");
  if (el) { el.value = matching.w_face_wall != null ? matching.w_face_wall : 0; el.onchange = function() { saveConfigField(["matching", "w_face_wall"], parseFloat(this.value)||0); }; }

  var labelsDiv = document.getElementById("cfgStandardLabels");
  if (labelsDiv) {
    var current = getCurrentStandard();
    var stds = getStandards();
    var html = '';
    stds.forEach(function(s) {
      var label = getStdLabel(s);
      var checked = (s === current) ? " checked" : "";
      html += '<div style="display:flex;align-items:center;gap:8px;margin-bottom:4px;">';
      html += '<input type="radio" name="cfgDefaultStd" value="' + s + '"' + checked +
        ' style="margin:0;cursor:pointer;" title="Set as current standard">';
      html += '<input type="text" data-std-label="' + s + '" value="' + label +
        '" style="width:80px;background:var(--surface);border:1px solid var(--border);color:var(--text);font-family:var(--font-mono);font-size:12px;padding:2px 6px;">';
      html += '</div>';
    });
    labelsDiv.innerHTML = html;
    // Session-life: bound once at init, no dispose needed
    labelsDiv.querySelectorAll("input[data-std-label]").forEach(function(inp) {
      inp.addEventListener("change", function() {
        var slot = inp.dataset.stdLabel;
        fetch("/api/config", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ path: ["standards", slot, "label"], value: inp.value }),
        }).then(function() {
          return loadAppConfig();
        }).then(function() {
          updateActiveStandardBadge();
          renderSpacingSettings();
        });
      });
    });
    // Session-life: bound once at init, no dispose needed
    labelsDiv.querySelectorAll('input[name="cfgDefaultStd"]').forEach(function(radio) {
      radio.addEventListener("change", function() {
        var slot = this.value;
        fetch("/api/current-standard", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ slot: slot }),
        }).then(function(resp) {
          if (!resp.ok) throw new Error("Failed");
          return loadAppConfig();
        }).then(function() {
          updateActiveStandardBadge();
          if (typeof setActiveStandard === "function") setActiveStandard(slot);
          if (typeof loadBlockDefs === "function") {
            loadBlockDefs().then(function() {
              if (typeof render === "function") render();
              if (typeof updateAutoName === "function") updateAutoName();
            });
          }
          if (typeof loadCatalogue === "function") loadCatalogue();
          if (typeof window.fpRenderCurrent === "function") window.fpRenderCurrent();
        });
      });
    });
  }
}

function initSettingsTabs() {
  // Session-life: tab buttons are persistent, bound once at init
  document.querySelectorAll(".settings-tab-btn").forEach(function(btn) {
    btn.addEventListener("click", function() {
      document.querySelectorAll(".settings-tab-btn").forEach(function(b) { b.classList.remove("active"); });
      document.querySelectorAll(".settings-tab-pane").forEach(function(p) { p.classList.remove("active"); });
      btn.classList.add("active");
      var pane = document.getElementById(btn.dataset.settingsTab);
      if (pane) pane.classList.add("active");
    });
  });
}

function renderFloorplanSettings() {
  var ing = APP_CONFIG.ingestion || {};

  // Render DPI
  var dpiEl = document.getElementById("cfgRenderDpi");
  if (dpiEl) {
    dpiEl.value = ing.render_dpi || 300;
    dpiEl.onchange = function() {
      saveConfigField(["ingestion", "render_dpi"], parseInt(this.value) || 300);
    };
  }
  // Hide detection colors toggle
  var hdcEl = document.getElementById("cfgHideDetectionColors");
  if (hdcEl) {
    hdcEl.checked = !!window.ingState && !!window.ingState.hideDetectionColors;
    hdcEl.onchange = function () {
      if (window.ingState) {
        window.ingState.hideDetectionColors = this.checked;
        try { localStorage.setItem("olm_hideDetectionColors", this.checked ? "1" : ""); }
        catch (e) { /* ignore */ }
        if (typeof window.renderIngestion === "function") window.renderIngestion();
        if (typeof window.fpRenderCurrent === "function") window.fpRenderCurrent();
      }
    };
  }

  // OCR Detection overrides (D-155)
  var cmEl = document.getElementById("cfgCartoucheMargin");
  if (cmEl) {
    cmEl.value = ing.cartouche_margin_cm != null ? ing.cartouche_margin_cm : 3.0;
    cmEl.onchange = function() {
      saveConfigField(["ingestion", "cartouche_margin_cm"],
                      parseFloat(this.value) || 3.0);
    };
  }
  var tsEl = document.getElementById("cfgTextSkipMargin");
  if (tsEl) {
    tsEl.value = ing.text_skip_margin_cm != null ? ing.text_skip_margin_cm : 6.0;
    tsEl.onchange = function() {
      saveConfigField(["ingestion", "text_skip_margin_cm"],
                      parseFloat(this.value) || 6.0);
    };
  }
  var btEl = document.getElementById("cfgBinarizeThreshold");
  if (btEl) {
    btEl.value = ing.binarize_threshold != null ? ing.binarize_threshold : 110;
    btEl.onchange = function() {
      saveConfigField(["ingestion", "binarize_threshold"],
                      parseInt(this.value) || 110);
    };
  }
  var mdEl = document.getElementById("cfgMaxDoorWidth");
  if (mdEl) {
    mdEl.value = ing.max_door_width_cm != null ? ing.max_door_width_cm : 120;
    mdEl.onchange = function() {
      saveConfigField(["ingestion", "max_door_width_cm"],
                      parseInt(this.value) || 120);
    };
  }

  var odEl = document.getElementById("cfgMinOpeningDepth");
  if (odEl) {
    odEl.value = ing.min_opening_depth_cm != null
      ? ing.min_opening_depth_cm : 60;
    odEl.onchange = function() {
      saveConfigField(["ingestion", "min_opening_depth_cm"],
                      parseInt(this.value) || 60);
    };
  }
  var owEl = document.getElementById("cfgMinObstacleWidth");
  if (owEl) {
    owEl.value = ing.min_obstacle_width_cm != null
      ? ing.min_obstacle_width_cm : 30;
    owEl.onchange = function() {
      saveConfigField(["ingestion", "min_obstacle_width_cm"],
                      parseInt(this.value) || 30);
    };
  }

  var pdEl = document.getElementById("cfgMinPillarSize");
  if (pdEl) {
    pdEl.value = ing.min_pillar_size_cm != null
      ? ing.min_pillar_size_cm : 15;
    pdEl.onchange = function() {
      saveConfigField(["ingestion", "min_pillar_size_cm"],
                      parseInt(this.value) || 15);
    };
  }

  var mpdEl = document.getElementById("cfgMaxPillarSize");
  if (mpdEl) {
    mpdEl.value = ing.max_pillar_size_cm != null
      ? ing.max_pillar_size_cm : 50;
    mpdEl.onchange = function() {
      saveConfigField(["ingestion", "max_pillar_size_cm"],
                      parseInt(this.value) || 50);
    };
  }

  var csEl = document.getElementById("cfgCombStep");
  if (csEl) {
    csEl.value = ing.comb_step_cm != null ? ing.comb_step_cm : 5;
    csEl.onchange = function() {
      saveConfigField(["ingestion", "comb_step_cm"],
                      parseInt(this.value) || 5);
    };
  }

  var ext = ing.preprocessed_exterior_rgb || [135, 206, 235];
  var cor = ing.preprocessed_corridor_rgb || [193, 247, 179];

  var ids = [["cfgExteriorR","cfgExteriorG","cfgExteriorB"], ["cfgCorridorR","cfgCorridorG","cfgCorridorB"]];
  var vals = [ext, cor];
  var keys = ["preprocessed_exterior_rgb", "preprocessed_corridor_rgb"];
  var previews = ["cfgExteriorPreview", "cfgCorridorPreview"];

  for (var i = 0; i < 2; i++) {
    (function(idx) {
      for (var c = 0; c < 3; c++) {
        var el = document.getElementById(ids[idx][c]);
        if (el) {
          el.value = vals[idx][c];
          el.onchange = function() {
            var rgb = [
              parseInt(document.getElementById(ids[idx][0]).value) || 0,
              parseInt(document.getElementById(ids[idx][1]).value) || 0,
              parseInt(document.getElementById(ids[idx][2]).value) || 0
            ];
            saveConfigField(["ingestion", keys[idx]], rgb);
            var prev = document.getElementById(previews[idx]);
            if (prev) prev.style.background = "rgb(" + rgb.join(",") + ")";
          };
        }
      }
      var prev = document.getElementById(previews[idx]);
      if (prev) prev.style.background = "rgb(" + vals[idx].join(",") + ")";
    })(i);
  }

  // Corridor / exterior width (cm) for color sampling
  var cwEl = document.getElementById("cfgCorridorWidth");
  if (cwEl) {
    cwEl.value = ing.corridor_width_cm != null ? ing.corridor_width_cm : 60;
    cwEl.onchange = function() {
      saveConfigField(["ingestion", "corridor_width_cm"],
                      parseFloat(this.value) || 60);
    };
  }
  var ewEl = document.getElementById("cfgExteriorWidth");
  if (ewEl) {
    ewEl.value = ing.exterior_width_cm != null ? ing.exterior_width_cm : 100;
    ewEl.onchange = function() {
      saveConfigField(["ingestion", "exterior_width_cm"],
                      parseFloat(this.value) || 100);
    };
  }
}

async function saveSpacingField(standard, field, value) {
  var status = document.getElementById("spacingSaveStatus");
  try {
    var values = {};
    values[field] = value;
    var resp = await fetch("/api/spacing", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ standard: standard, values: values }),
    });
    if (!resp.ok) throw new Error(await resp.text());
    // Reload configs and block defs
    await loadSpacingConfigs();
    _BLOCK_DEFS_CACHE_JS = {};
    await loadAllBlockDefs();
    await loadBlockDefs();
    render();
    if (status) status.textContent = "Saved.";
    setTimeout(function() { if (status) status.textContent = ""; }, 2000);
  } catch (e) {
    if (status) status.textContent = "Error: " + e.message;
  }
}
var _BLOCK_DEFS_CACHE_JS = {};

function closeSettings() {
  document.getElementById("settingsDrawer").classList.remove("open");
  document.getElementById("settingsBackdrop").classList.remove("open");
}
