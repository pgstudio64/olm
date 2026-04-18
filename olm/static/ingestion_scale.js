"use strict";
// ========================================================================
// INGESTION SCALE — drawing-scale helpers (D-94 P4)
// ========================================================================
//
// Pure helpers extracted from ingestion.js:
//   parseDrawingScale(str)         — "1 : 300" or "300" → 300 (0 on fail)
//   computeCmPerPx(scale, dpi)     — 2.54 × scale / dpi
//   getDrawingScale()              — reads #ingDrawingScale, returns "1 : N"
//   getRenderDpi()                 — reads APP_CONFIG.ingestion.render_dpi
//   suggestDrawingScale(cmPerPx)   — back-calculate & display suggestion
//
// Exposed as `window.olmScale.*` for ingestion.js (and any future caller).
// ========================================================================

(function () {
  /**
   * Parse drawing scale value → number. Accepts plain number ("300")
   * or "1 : 300" format. Returns 0 if unparseable.
   */
  function parseDrawingScale(str) {
    if (!str) return 0;
    var s = String(str).trim();
    // Try "1 : 300" format first
    var m = s.match(/1\s*:\s*(\d+(?:\.\d+)?)/);
    if (m) return parseFloat(m[1]);
    // Plain number
    var n = parseFloat(s);
    return (n > 0) ? n : 0;
  }

  /**
   * Compute cm_per_px from drawing scale and render DPI.
   * Formula: cm_per_px = 2.54 × scale_number / render_dpi
   */
  function computeCmPerPx(scaleNumber, renderDpi) {
    if (!scaleNumber || scaleNumber <= 0 || !renderDpi || renderDpi <= 0) return 0;
    return 2.54 * scaleNumber / renderDpi;
  }

  /** Read current drawing_scale from the UI field, formatted for backend. */
  function getDrawingScale() {
    var el = document.getElementById('ingDrawingScale');
    var val = el ? el.value.trim() : '';
    if (!val) return '';
    var n = parseDrawingScale(val);
    return n > 0 ? '1 : ' + n : '';
  }

  /** Read render_dpi from config (APP_CONFIG). */
  function getRenderDpi() {
    var ing = (window.APP_CONFIG || {}).ingestion || {};
    return ing.render_dpi || 300;
  }

  /**
   * After import: if drawing_scale field is empty, back-calculate an estimated
   * scale from the cm_per_px returned by the backend, and show it as a suggestion.
   */
  function suggestDrawingScale(scaleCmPerPx) {
    var dsField = document.getElementById('ingDrawingScale');
    var info = document.getElementById('ingScaleInfo');
    if (!dsField) return;
    var dpi = getRenderDpi();
    if (dsField.value.trim() && parseDrawingScale(dsField.value) > 0) {
      // User already provided a scale — show effective cm/px, white text
      dsField.style.color = 'var(--text)';
      var num = parseDrawingScale(dsField.value);
      if (info) info.textContent = num + ' → ' + scaleCmPerPx.toFixed(4) + ' cm/px (at ' + dpi + ' DPI)';
      return;
    }
    // Back-calculate: scale_number = cm_per_px × render_dpi / 2.54
    if (scaleCmPerPx > 0 && dpi > 0) {
      var estimated = Math.round(scaleCmPerPx * dpi / 2.54);
      if (estimated > 0) {
        dsField.value = '1 : ' + estimated;
        dsField.style.color = 'var(--warn)';
        if (info) info.textContent = 'Estimated from room surfaces (may be inaccurate). ' +
          'Effective: ' + scaleCmPerPx.toFixed(4) + ' cm/px at ' + dpi + ' DPI. ' +
          'Edit to correct.';
      }
    }
  }

  window.olmScale = {
    parseDrawingScale: parseDrawingScale,
    computeCmPerPx: computeCmPerPx,
    getDrawingScale: getDrawingScale,
    getRenderDpi: getRenderDpi,
    suggestDrawingScale: suggestDrawingScale,
  };
})();
