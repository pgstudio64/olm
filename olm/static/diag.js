"use strict";
/**
 * diag.js — Generic diagnostic framework for OLM (dev-mode only).
 *
 * Usage:
 *   OLM_DIAGS.register("domain.subject", function(target, ctx) { return result; })
 *   OLM_DIAGS.run("domain.subject", target, ctx)  // runs + renders modal
 *   OLM_DIAGS.list()  // returns registered diag names
 *
 * Result contract:
 *   { name, verdict ("ok"|"warning"|"error"), summary, sections[] }
 *   Each section: { title, rows[] }
 *   Each row: { label, value, status? ("ok"|"warning"|"error"), note? }
 */
var OLM_DIAGS = (function () {
  var _registry = {};

  function register(name, fn) {
    _registry[name] = fn;
  }

  function list() {
    return Object.keys(_registry);
  }

  function run(name, target, ctx) {
    var fn = _registry[name];
    if (!fn) {
      alertModal("Diagnostic \"" + name + "\" not registered.", false);
      return;
    }
    var result = fn(target, ctx);
    if (result) renderModal(result);
  }

  // --- Verdict colors (reuses D-235 3-color system) ---
  var VERDICT_COLORS = {
    ok: "var(--good, #4caf50)",
    warning: "var(--warn, #ff9800)",
    error: "var(--bad, #d88080)"
  };

  function _verdictDot(status) {
    if (!status) return "";
    var c = VERDICT_COLORS[status] || "var(--text-dim)";
    return '<span style="display:inline-block;width:10px;height:10px;'
      + 'border-radius:50%;background:' + c + ';margin-right:6px;'
      + 'vertical-align:middle;"></span>';
  }

  function renderModal(result) {
    var html = '<div style="text-align:left;max-height:70vh;overflow-y:auto;'
      + 'font-size:13px;line-height:1.5;min-width:340px;">';

    // Header: name + verdict
    var vc = VERDICT_COLORS[result.verdict] || "var(--text)";
    html += '<div style="font-weight:bold;font-size:15px;margin-bottom:4px;">'
      + _escHtml(result.name) + '</div>';
    html += '<div style="color:' + vc + ';font-weight:bold;margin-bottom:10px;">'
      + _verdictDot(result.verdict)
      + _escHtml(result.summary) + '</div>';

    // Sections
    var sections = result.sections || [];
    for (var si = 0; si < sections.length; si++) {
      var sec = sections[si];
      html += '<div style="margin-top:8px;font-weight:bold;'
        + 'border-bottom:1px solid var(--border);padding-bottom:2px;">'
        + _escHtml(sec.title) + '</div>';
      html += '<table style="width:100%;border-collapse:collapse;">';
      var rows = sec.rows || [];
      for (var ri = 0; ri < rows.length; ri++) {
        var r = rows[ri];
        var bg = ri % 2 === 0 ? "transparent" : "var(--surface, #f5f5f5)";
        html += '<tr style="background:' + bg + ';">';
        html += '<td style="padding:2px 8px 2px 4px;white-space:nowrap;">'
          + _verdictDot(r.status) + _escHtml(r.label) + '</td>';
        html += '<td style="padding:2px 4px;text-align:right;font-family:monospace;">'
          + _escHtml(String(r.value)) + '</td>';
        if (r.note) {
          html += '<td style="padding:2px 4px;color:var(--text-dim);font-size:11px;">'
            + _escHtml(r.note) + '</td>';
        } else {
          html += '<td></td>';
        }
        html += '</tr>';
      }
      html += '</table>';
    }

    html += '</div>';
    alertModal(html, true);
  }

  function _escHtml(s) {
    var d = document.createElement("div");
    d.textContent = s;
    return d.innerHTML;
  }

  return {
    register: register,
    run: run,
    list: list,
    renderModal: renderModal
  };
})();


// ========== DIAG: pattern.footprint ==========

OLM_DIAGS.register("pattern.footprint", function (pattern) {
  var roomW = pattern.room_width_cm || 0;
  var roomD = pattern.room_depth_cm || 0;
  var std = pattern.standard || "?";
  var stdLabel = (typeof getStdLabel === "function") ? getStdLabel(std) : std;

  // Get spacing config for this standard
  var spacing = (SPACING_CONFIGS && SPACING_CONFIGS[std]) ? SPACING_CONFIGS[std] : null;
  var excl = spacing ? (spacing.door_exclusion_depth_cm || 0) : 0;

  // Compute footprint with trace
  var fp = computePatternFootprint(pattern, { trace: true });
  var contributors = fp.contributors || [];
  var doorObstacles = fp.doorObstacles || [];

  // Verdict
  var overflows = fp.xMin < 0 || fp.yMin < 0 || fp.xMax > roomW || fp.yMax > roomD;
  var verdict = overflows ? "error" : "ok";

  // Summary
  var summary;
  if (!overflows) {
    var spareW = roomW - (fp.xMax - fp.xMin);
    var spareD = roomD - (fp.yMax - fp.yMin);
    summary = (spareW <= 0 && spareD <= 0)
      ? "Exact fit — no room to spare"
      : "Fits — room to spare: " + spareW + " × " + spareD + " cm";
  } else {
    var parts = [];
    if (fp.xMin < 0) parts.push("WEST " + fp.xMin + " cm");
    if (fp.yMin < 0) parts.push("NORTH " + fp.yMin + " cm");
    if (fp.xMax > roomW) parts.push("EAST +" + (fp.xMax - roomW) + " cm");
    if (fp.yMax > roomD) parts.push("SOUTH +" + (fp.yMax - roomD) + " cm");
    summary = "Overflow: " + parts.join(", ");
  }

  // Sections
  var sections = [];

  // Section 1: Room
  var roomRows = [
    { label: "Standard", value: stdLabel },
    { label: "Room width", value: roomW + " cm" },
    { label: "Room depth", value: roomD + " cm" }
  ];
  if (spacing) {
    roomRows.push({
      label: "Door exclusion",
      value: excl + " cm",
      note: "from " + stdLabel
    });
  } else {
    roomRows.push({
      label: "Spacing config",
      value: "not found for " + std,
      status: "warning"
    });
  }
  sections.push({ title: "Room", rows: roomRows });

  // Section 2: Footprint (final bbox)
  var fpRows = [
    {
      label: "X range",
      value: fp.xMin + " .. " + fp.xMax + " cm",
      status: (fp.xMin < 0 || fp.xMax > roomW) ? "error" : "ok"
    },
    {
      label: "Y range",
      value: fp.yMin + " .. " + fp.yMax + " cm",
      status: (fp.yMin < 0 || fp.yMax > roomD) ? "error" : "ok"
    },
    {
      label: "Total width",
      value: (fp.xMax - fp.xMin) + " cm",
      status: (fp.xMax - fp.xMin > roomW) ? "error" : "ok",
      note: "room: " + roomW + " cm"
    },
    {
      label: "Total depth",
      value: (fp.yMax - fp.yMin) + " cm",
      status: (fp.yMax - fp.yMin > roomD) ? "error" : "ok",
      note: "room: " + roomD + " cm"
    }
  ];
  sections.push({ title: "Footprint", rows: fpRows });

  // Section 3: Contributors (per-block breakdown)
  if (contributors.length > 0) {
    var contribRows = [];
    for (var i = 0; i < contributors.length; i++) {
      var c = contributors[i];
      var cXMin = c.x - c.fw;
      var cXMax = c.x + c.w + c.fe;
      var cYMin = c.y - c.fn;
      var cYMax = c.y + c.h + c.fs;
      var xBad = cXMin < 0 || cXMax > roomW;
      var yBad = cYMin < 0 || cYMax > roomD;
      var st = (xBad || yBad) ? "error" : "ok";
      contribRows.push({
        label: c.label,
        value: "[" + cXMin + ".." + cXMax + "] x [" + cYMin + ".." + cYMax + "]",
        status: st,
        note: "body " + c.w + "x" + c.h
          + " faces W:" + c.fw + " E:" + c.fe
          + " N:" + c.fn + " S:" + c.fs
      });
    }
    sections.push({ title: "Contributors (blocks)", rows: contribRows });
  } else {
    sections.push({
      title: "Contributors (blocks)",
      rows: [{ label: "No blocks", value: "-" }]
    });
  }

  // Section 4: Door obstacles
  if (doorObstacles.length > 0) {
    var doorRows = [];
    for (var di = 0; di < doorObstacles.length; di++) {
      var d = doorObstacles[di];
      doorRows.push({
        label: d.face + " door @ " + d.offset_cm + " cm",
        value: "width " + d.width_cm + " cm, excl " + d.excl_cm + " cm",
        note: d.pushback_desc || ""
      });
    }
    sections.push({ title: "Door obstacles", rows: doorRows });
  } else {
    sections.push({
      title: "Door obstacles",
      rows: [{ label: "No doors", value: "-" }]
    });
  }

  return {
    name: "pattern.footprint",
    verdict: verdict,
    summary: summary,
    sections: sections
  };
});


// ========== DIAG: perf.transition (v0.5.34 — freeze Floor→Room) ==========
// Couverture EXHAUSTIVE des 5 endroits ou 20s peuvent passer :
//   1 JS sync (deltas marques) · 2 async (longtask) · 3 decode (sonde) ·
//   4 reseau (Resource Timing) · 5 rendu navigateur (ecart rAF).
// Le gel apparait forcement dans une de ces lignes. A retirer apres diagnostic.

OLM_DIAGS.register("perf.transition", function () {
  var WARN = 300, BAD = 1000;   // seuils d'AFFICHAGE uniquement
  var cap = (window._perf && window._perf.getLast) ? window._perf.getLast() : null;
  if (!cap || !cap.marks || cap.marks.length < 2) {
    return {
      name: "perf.transition", verdict: "warning",
      summary: "Aucune transition capturee. Navigue Floor→Room puis re-clique Perf.",
      sections: [],
    };
  }
  function _st(ms) { return ms >= BAD ? "error" : (ms >= WARN ? "warning" : "ok"); }

  // 1. JS synchrone — deltas entre marques consecutives.
  var phaseRows = [];
  var maxDelta = 0, maxLabel = "";
  for (var i = 1; i < cap.marks.length; i++) {
    var dt = cap.marks[i].t - cap.marks[i - 1].t;
    phaseRows.push({
      label: cap.marks[i].label, value: dt + " ms",
      status: _st(dt), note: "@ " + cap.marks[i].t + " ms",
    });
    if (dt > maxDelta) { maxDelta = dt; maxLabel = cap.marks[i].label; }
  }

  // 2. Async — longtasks.
  var ltRows = [];
  var maxLt = 0;
  (cap.longtasks || []).forEach(function (lt) {
    if (lt.dur > maxLt) maxLt = lt.dur;
    ltRows.push({ label: "longtask @ " + lt.start + " ms",
      value: lt.dur + " ms", status: _st(lt.dur) });
  });
  if (!ltRows.length) ltRows.push({ label: "aucune longtask >50ms", value: "-",
    note: "API absente ou rien d'async lourd cote JS" });

  // 5. Rendu navigateur — frames longues (ecart entre rAF).
  var rafRows = [];
  var maxRaf = 0, maxRafAt = 0;
  (cap.rafStalls || []).forEach(function (s) {
    if (s.dur > maxRaf) { maxRaf = s.dur; maxRafAt = s.start; }
    rafRows.push({ label: "frame longue @ " + s.start + " ms",
      value: s.dur + " ms", status: _st(s.dur) });
  });
  if (!rafRows.length) rafRows.push({ label: "aucune frame longue >200ms", value: "-",
    note: "ni raster/paint/layout ni blocage du thread" });

  // 4. Reseau — Resource Timing pendant la fenetre de capture.
  var resRows = [];
  var maxRes = 0, maxResName = "";
  try {
    var entries = performance.getEntriesByType("resource")
      .filter(function (e) { return e.startTime >= cap.t0 - 50 && e.duration > WARN; })
      .sort(function (a, b) { return b.duration - a.duration; })
      .slice(0, 8);
    entries.forEach(function (e) {
      var d = Math.round(e.duration);
      if (d > maxRes) { maxRes = d; maxResName = e.name; }
      var nm = e.name.split("?")[0].split("/").slice(-1)[0] || e.name;
      resRows.push({ label: (e.initiatorType || "?") + ": " + nm.slice(0, 38),
        value: d + " ms", status: _st(d) });
    });
  } catch (e) { /* Resource Timing indispo */ }
  if (!resRows.length) resRows.push({ label: "aucune ressource >300ms", value: "-",
    note: "rien de lent cote reseau/serveur (local)" });

  // 3 + serveur — overlay & match.
  var ex = cap.extra || {};
  var ovRows = [
    { label: "URL overlay", value: ex.overlay_url || ex.overlay || "n/a" },
    { label: "dimensions", value: ex.overlay_px || "n/a" },
    { label: "decode (sonde)",
      value: (ex.overlay_decode_ms != null ? ex.overlay_decode_ms + " ms" : "n/a"),
      status: (typeof ex.overlay_decode_ms === "number") ? _st(ex.overlay_decode_ms) : undefined },
  ];
  if (ex.server_match_ms != null) ovRows.push({ label: "matching serveur",
    value: ex.server_match_ms + " ms", note: "reponse /api/floor-plan/match" });

  // Verdict : la plus grosse des 5 categories l'emporte → cause unique.
  var cats = [
    { v: maxDelta, msg: "JS SYNCHRONE : phase \"" + maxLabel + "\"" },
    { v: maxLt, msg: "JS ASYNC : longtask de " + maxLt + " ms" },
    { v: maxRes, msg: "RESEAU/SERVEUR : " + (maxResName.split("/").slice(-1)[0] || "") },
    { v: maxRaf, msg: "RENDU NAVIGATEUR (paint/raster/layout) : frame de " + maxRaf
      + " ms @ " + maxRafAt + " ms" },
  ];
  cats.sort(function (a, b) { return b.v - a.v; });
  var worst = cats[0].v;
  var verdict = _st(worst);
  var summary = worst < WARN
    ? "RAS : total " + cap.marks[cap.marks.length - 1].t + " ms mesure, rien de >300ms. "
      + "Si le gel a bien eu lieu, il est hors fenetre (>30s ou avant le clic)."
    : "CAUSE : " + cats[0].msg + " (" + worst + " ms).";

  return {
    name: "perf.transition (" + cap.label + ")",
    verdict: verdict,
    summary: summary,
    sections: [
      { title: "5 · Rendu navigateur (ecart rAF)", rows: rafRows },
      { title: "4 · Reseau / serveur (Resource Timing)", rows: resRows },
      { title: "1 · JS synchrone (deltas marques)", rows: phaseRows },
      { title: "2 · JS async (longtasks)", rows: ltRows },
      { title: "3 · Overlay & match", rows: ovRows },
    ],
  };
});


// ========== DIAG: office.candidates (async — server-side) ==========
// Fetches /api/office/diagnose for the current room and renders
// room_context + step_counts + per-pattern table in diagModal.

/**
 * Run the office.candidates diagnostic for a room.
 *
 * @param {Object} room - The client-side room object (fpCurrent()).
 * @param {Function} buildApiRoom - Function to build the API payload.
 */
OLM_DIAGS.runOfficeDiag = function (room, buildApiRoom) {
  if (!room) {
    alertModal("No room selected.");
    return;
  }
  var apiRoom = buildApiRoom(room);
  fetch("/api/office/diagnose", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ room: apiRoom }),
  })
  .then(function (r) { return r.json(); })
  .then(function (data) {
    if (data.error) {
      alertModal("Diag error: " + data.error);
      return;
    }
    var result = _buildOfficeDiagResult(data, room);
    OLM_DIAGS.renderModal(result);
  })
  .catch(function (e) {
    alertModal("Diag network error: " + e.message);
  });
};


function _buildOfficeDiagResult(data, room) {
  var ctx = data.room_context || {};
  var counts = data.step_counts || {};
  var patterns = data.patterns || [];

  // Overall verdict.
  var kept = counts.kept || 0;
  var verdict = kept > 0 ? "ok" : "error";
  var summary = kept + " candidate(s) kept out of "
    + (counts.total_catalogue || 0) + " in catalogue";

  var sections = [];

  // --- Section 1: Room context (server + client fields) ---
  var ctxRows = [
    { label: "Name", value: ctx.name || "(unnamed)" },
    { label: "Dimensions", value: ctx.width_cm + " x " + ctx.depth_cm + " cm" },
    { label: "Effective dims", value: ctx.effective_width_cm + " x "
      + ctx.effective_depth_cm + " cm",
      status: (ctx.effective_width_cm < ctx.width_cm
        || ctx.effective_depth_cm < ctx.depth_cm) ? "warning" : "ok" },
    { label: "Current standard", value: ctx.current_standard || "(none)" },
    { label: "Windows", value: String(ctx.n_windows) },
    { label: "Doors", value: String(ctx.n_doors) },
    { label: "Passages (no door)", value: String(ctx.n_passages) },
    { label: "Exclusion zones", value: String(ctx.n_exclusion_zones),
      status: ctx.n_exclusion_zones > 0 ? "warning" : "ok" },
  ];
  // Client-only fields.
  ctxRows.push({
    label: "corridor_face_abs",
    value: room.corridor_face_abs || "(none)",
  });
  ctxRows.push({
    label: "saved_layout",
    value: room.saved_layout ? "yes" : "no",
    status: room.saved_layout ? "warning" : "ok",
    note: room.saved_layout ? "room uses saved layout, not re-matched" : "",
  });
  ctxRows.push({
    label: "room_amended",
    value: room.room_amended ? "yes" : "no",
  });
  ctxRows.push({
    label: "source_mode",
    value: room.source_mode || "(default)",
  });
  sections.push({ title: "Room context", rows: ctxRows });

  // --- Section 2: Pipeline step counts ---
  var stepRows = [
    { label: "Total catalogue", value: String(counts.total_catalogue || 0) },
    { label: "After standard + fit", value: String(counts.after_standard_fit || 0),
      status: (counts.after_standard_fit || 0) === 0 ? "error" : "ok" },
    { label: "After adapt / overflow", value: String(counts.after_adapt || 0),
      status: (counts.after_adapt || 0) === 0 && (counts.after_standard_fit || 0) > 0
        ? "error" : "ok" },
    { label: "After 6bis (reach/passage)", value: String(counts.after_6bis || 0),
      status: (counts.after_6bis || 0) === 0 && (counts.after_adapt || 0) > 0
        ? "error" : "ok" },
    { label: "After 6ter (dominated)", value: String(counts.after_6ter || 0),
      status: (counts.after_6ter || 0) === 0 && (counts.after_6bis || 0) > 0
        ? "warning" : "ok" },
    { label: "Kept", value: String(kept),
      status: kept === 0 ? "error" : "ok" },
  ];
  sections.push({ title: "Pipeline step counts", rows: stepRows });

  // --- Section 3: Per-pattern table ---
  var _STATUS_STYLE = {
    kept: "ok",
    removed_6ter: "warning",
    removed_6bis_passage: "warning",
    removed_6bis_reach: "error",
    no_fit: "error",
    hidden: "error",
    wrong_standard: "error",
  };
  var patRows = [];
  for (var i = 0; i < patterns.length; i++) {
    var p = patterns[i];
    var lbl = (p.standard || "?") + "  " + (p.pattern_name || "?");
    var parts = [p.status || "?"];
    if (p.fit_class && p.fit_class !== p.status) parts.push("fit:" + p.fit_class);
    if (p.n_desks != null) parts.push(p.n_desks + "d");
    if (p.dim_reachability != null) parts.push("reach:" + p.dim_reachability);
    if (p.min_passage_cm != null) parts.push("pass:" + p.min_passage_cm + "cm");
    if (p.passage_grade) parts.push("grade:" + p.passage_grade);
    if (p.category) parts.push("cat:" + p.category);
    patRows.push({
      label: lbl,
      value: parts.join(" | "),
      status: _STATUS_STYLE[p.status] || undefined,
    });
  }
  if (!patRows.length) {
    patRows.push({ label: "No patterns in catalogue", value: "-" });
  }
  sections.push({ title: "Patterns (" + patterns.length + ")", rows: patRows });

  return {
    name: "office.candidates",
    verdict: verdict,
    summary: summary,
    sections: sections,
  };
}
