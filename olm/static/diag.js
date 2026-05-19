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
    summary = "Footprint fits in room";
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
