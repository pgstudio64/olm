"use strict";
async function loadSpacingConfigs() {
  try {
    var resp = await fetch("/api/spacing");
    if (resp.ok) {
      SPACING_CONFIGS = await resp.json();
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
}

function getStandards() {
  if (APP_CONFIG.spacing) return Object.keys(APP_CONFIG.spacing);
  return [];
}

function getStdLabel(key) {
  if (APP_CONFIG.standard_labels && APP_CONFIG.standard_labels[key]) {
    return APP_CONFIG.standard_labels[key];
  }
  // Generic fallback: "Std 1", "Std 2"...
  var stds = getStandards();
  var idx = stds.indexOf(key);
  return idx >= 0 ? "Std " + (idx + 1) : key;
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
  { key: "chair_clearance_cm",             label: "ES-01 Chair clearance" },
  { key: "front_access_cm",               label: "ES-02 Front access" },
  { key: "access_single_desk_cm",          label: "ES-03 Single desk access" },
  { key: "passage_behind_one_row_cm",      label: "ES-04 Behind one row" },
  { key: "passage_between_back_to_back_cm",label: "ES-05 Between back-to-back" },
  { key: "passage_cm",                    label: "ES-06 Inter-block passage" },
  { key: "door_exclusion_depth_cm",        label: "ES-08 Door exclusion" },
  { key: "desk_to_wall_cm",               label: "ES-09 Desk to wall" },
  { key: "max_island_size",               label: "ES-10 Max island size" },
  { key: "min_block_separation_cm",        label: "ES-11 Block separation" },
  { key: "main_corridor_cm",              label: "PS-04 Main corridor" },
];

function renderSpacingSettings() {
  var grid = document.getElementById("spacingSettingsGrid");
  if (!grid || !SPACING_CONFIGS) return;
  var stds = getStandards();
  var html = '<div style="font-weight:bold;color:var(--text-dim);">Parameter</div>';
  stds.forEach(function(s) {
    html += '<div style="font-weight:bold;text-align:center;color:var(--accent);">' +
      getStdLabel(s) + '</div>';
  });
  SPACING_FIELDS.forEach(function(f) {
    html += '<div style="color:var(--text-dim);padding:2px 0;">' + f.label + '</div>';
    stds.forEach(function(s) {
      var val = SPACING_CONFIGS[s] ? SPACING_CONFIGS[s][f.key] : "";
      html += '<div><input type="number" data-std="' + s + '" data-field="' + f.key +
        '" value="' + val + '" style="width:80px;background:var(--surface);border:1px solid var(--border);' +
        'color:var(--text);font-family:var(--font-mono);font-size:11px;padding:2px 4px;text-align:right;"></div>';
    });
  });
  grid.innerHTML = html;

  // Wire change events
  grid.querySelectorAll("input[data-std]").forEach(function(inp) {
    inp.addEventListener("change", function() {
      saveSpacingField(inp.dataset.std, inp.dataset.field, parseInt(inp.value) || 0);
    });
  });
}

function renderEditorStandardRadios() {
  var container = document.getElementById("headerStandard");
  if (!container) return;
  var stds = getStandards();
  var html = "";
  stds.forEach(function(s, i) {
    var checked = i === 0 ? " checked" : "";
    html += '<label><input type="radio" name="standard" value="' + s + '"' + checked + '> ' + getStdLabel(s) + '</label>';
  });
  container.innerHTML = html;
  // Re-wire change listeners
  container.querySelectorAll('input[name="standard"]').forEach(function(r) {
    r.addEventListener("change", function() {
      state.standard = this.value;
      loadBlockDefs().then(function() { render(); updateAutoName(); });
    });
  });
}

function renderCatStandardFilter() {
  var sel = document.getElementById("catFilterStandard");
  if (!sel) return;
  var html = '<option value="">All</option>';
  getStandards().forEach(function(s) {
    html += '<option value="' + s + '">' + getStdLabel(s) + '</option>';
  });
  sel.innerHTML = html;
}

function renderFpStandardFilter() {
  var container = document.getElementById("fpStandardFilter");
  if (!container) return;
  var html = '<label><input type="radio" name="fpStandard" value="" checked> All</label>';
  getStandards().forEach(function(s) {
    html += '<label><input type="radio" name="fpStandard" value="' + s + '"> ' + getStdLabel(s) + '</label>';
  });
  container.innerHTML = html;
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

  el = document.getElementById("cfgPlansDir");
  if (el) {
    var ing = APP_CONFIG.ingestion || {};
    el.value = ing.plans_dir || "project/plans";
    el.onchange = function() { saveConfigField(["ingestion", "plans_dir"], this.value); };
  }

  var matching = APP_CONFIG.matching || {};
  el = document.getElementById("cfgWDensity");
  if (el) { el.value = matching.w_density != null ? matching.w_density : 0.5; el.onchange = function() { saveConfigField(["matching", "w_density"], parseFloat(this.value)||0.5); }; }

  el = document.getElementById("cfgWComfort");
  if (el) { el.value = matching.w_comfort != null ? matching.w_comfort : 0.5; el.onchange = function() { saveConfigField(["matching", "w_comfort"], parseFloat(this.value)||0.5); }; }

  var labelsDiv = document.getElementById("cfgStandardLabels");
  if (labelsDiv) {
    var html = "";
    getStandards().forEach(function(s) {
      var label = getStdLabel(s);
      html += '<label style="color:var(--text-dim);">' + s + '</label>';
      html += '<input type="text" data-std-label="' + s + '" value="' + label +
        '" style="width:100px;background:var(--surface);border:1px solid var(--border);color:var(--text);font-family:var(--font-mono);font-size:12px;padding:2px 6px;">';
    });
    labelsDiv.innerHTML = html;
    labelsDiv.querySelectorAll("input[data-std-label]").forEach(function(inp) {
      inp.addEventListener("change", function() {
        var labels = APP_CONFIG.standard_labels || {};
        labels[inp.dataset.stdLabel] = inp.value;
        saveConfigField("standard_labels", labels);
      });
    });
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
