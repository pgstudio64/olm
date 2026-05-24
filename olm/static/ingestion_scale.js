"use strict";
// ========================================================================
// INGESTION SCALE — scale source selector (custom dropdown)
// ========================================================================
//
// Three scale sources (priority order):
//   1. Notation scale — drawing_scale_text + render_dpi from JSON
//   2. Ruler scale    — drawing_scale_measured from JSON (cm/px)
//   3. Manual scale   — user-entered "1 : XXX" via prompt
//
// UI: custom dropdown matching Current Floorplan selector style.
// Label left-aligned, value right-aligned in monospace.
// Exposed as `window.olmScale.*` for ingestion.js.
// ========================================================================

(function () {

  var _renderDpi = 300;
  var _notationCmPerPx = 0;
  var _rulerCmPerPx = 0;
  var _manualCmPerPx = 0;
  var _notationText = '';
  var _selectedSource = '';
  var _prevSource = '';

  // --- Pure helpers ---

  function parseDrawingScale(str) {
    if (!str) return 0;
    var s = String(str).trim();
    var m = s.match(/1\s*:\s*(\d+(?:\.\d+)?)/);
    if (m) return parseFloat(m[1]);
    var n = parseFloat(s);
    return (n > 0) ? n : 0;
  }

  function computeCmPerPx(scaleNumber, renderDpi) {
    // Delegate to units.js source unique (D-274 Lot 1).
    return window.drawingScaleToCmPerPx(scaleNumber, renderDpi);
  }

  function cmPerPxToScaleText(cmPerPx, dpi) {
    // Delegate to units.js source unique (D-274 Lot 1).
    return window.cmPerPxToScaleText(cmPerPx, dpi);
  }

  function getRenderDpi() { return _renderDpi; }

  // --- Source data ---

  var SOURCES = [
    { key: 'notation', label: 'Notation scale' },
    { key: 'ruler',    label: 'Ruler scale' },
    { key: 'manual',   label: 'Manual scale' },
  ];

  function _getCmPerPx(key) {
    if (key === 'notation') return _notationCmPerPx;
    if (key === 'ruler') return _rulerCmPerPx;
    if (key === 'manual') return _manualCmPerPx;
    return 0;
  }

  function _getValueText(key) {
    var cmPx = _getCmPerPx(key);
    if (cmPx > 0) return cmPerPxToScaleText(cmPx, _renderDpi);
    if (key === 'manual') return '\u2014';
    return 'N/A';
  }

  function _isAvailable(key) {
    if (key === 'manual') return true;
    return _getCmPerPx(key) > 0;
  }

  // --- Public getters ---

  function getSelectedSource() { return _selectedSource; }

  function getActiveCmPerPx() { return _getCmPerPx(_selectedSource); }

  function getDrawingScale() {
    var cmPx = getActiveCmPerPx();
    if (cmPx <= 0) return '';
    return cmPerPxToScaleText(cmPx, _renderDpi);
  }

  // --- Display ---

  function _updateDisplay() {
    var lbl = document.getElementById('ingScaleDisplayLabel');
    var val = document.getElementById('ingScaleDisplayValue');
    if (!lbl || !val) return;

    var src = SOURCES.filter(function (s) {
      return s.key === _selectedSource;
    })[0];
    lbl.textContent = src ? src.label : '\u2014';

    var cmPx = getActiveCmPerPx();
    val.textContent = cmPx > 0
      ? cmPerPxToScaleText(cmPx, _renderDpi) : '\u2014';

    var info = document.getElementById('ingScaleInfo');
    if (info) {
      info.textContent = cmPx > 0
        ? cmPx.toFixed(4) + ' cm/px (' + _selectedSource +
          ', ' + _renderDpi + ' DPI)'
        : '';
    }
  }

  // --- Popup ---

  function _buildPopup() {
    var popup = document.getElementById('ingScalePopup');
    if (!popup) return;
    popup.innerHTML = '';

    SOURCES.forEach(function (src) {
      var avail = _isAvailable(src.key);
      var row = document.createElement('div');
      row.style.cssText =
        'padding:4px 6px;display:flex;justify-content:space-between;' +
        'align-items:center;';
      if (avail) {
        row.style.cursor = 'pointer';
      } else {
        row.style.cursor = 'default';
        row.style.opacity = '0.4';
      }
      if (src.key === _selectedSource) {
        row.style.background = 'rgba(255,255,255,0.06)';
      }
      if (avail) {
        row.addEventListener('mouseenter', function () {
          row.style.background = 'rgba(255,255,255,0.04)';
        });
        row.addEventListener('mouseleave', function () {
          row.style.background = src.key === _selectedSource
            ? 'rgba(255,255,255,0.06)' : '';
        });
      }

      var labelSpan = document.createElement('span');
      labelSpan.textContent = src.label;

      var valSpan = document.createElement('span');
      valSpan.style.fontFamily = 'var(--font-mono)';
      valSpan.textContent = _getValueText(src.key);
      if (!(_getCmPerPx(src.key) > 0)) {
        valSpan.style.color = 'var(--text-dim)';
      }

      row.appendChild(labelSpan);
      row.appendChild(valSpan);

      row.addEventListener('click', function () {
        if (!avail) return;
        if (src.key === 'manual') {
          var current = _manualCmPerPx > 0
            ? cmPerPxToScaleText(_manualCmPerPx, _renderDpi) : '';
          var input = prompt(
            'Manual scale (e.g. "1 : 300"):', current);
          if (input === null) {
            // Cancelled — keep previous if no manual value
            if (_manualCmPerPx <= 0) {
              popup.style.display = 'none';
              return;
            }
          } else {
            var n = parseDrawingScale(input);
            if (n > 0) {
              _manualCmPerPx = computeCmPerPx(n, _renderDpi);
            } else if (_manualCmPerPx <= 0) {
              popup.style.display = 'none';
              return;
            }
          }
        }
        _selectedSource = src.key;
        _prevSource = src.key;
        popup.style.display = 'none';
        _updateDisplay();
        _syncIngState();
      });

      popup.appendChild(row);
    });
  }

  function _togglePopup() {
    var popup = document.getElementById('ingScalePopup');
    if (!popup) return;
    if (popup.style.display !== 'none') {
      popup.style.display = 'none';
    } else {
      _buildPopup();
      popup.style.display = '';
    }
  }

  // --- State sync ---

  function _syncIngState() {
    var cmPx = getActiveCmPerPx();
    if (cmPx > 0 && window.ingState) {
      window.ingState.scale = cmPx;
      if (typeof window.onScaleChanged === 'function') {
        window.onScaleChanged();
      }
    }
  }

  /** Populate after import. Called with backend response data. */
  function populateScaleSelector(data) {
    _renderDpi = data.render_dpi || _renderDpi;
    _notationCmPerPx = data.notation_scale_cm_per_px || 0;
    _rulerCmPerPx = data.ruler_scale_cm_per_px || 0;
    _notationText = data.drawing_scale_text || '';

    if (_notationCmPerPx > 0) {
      _selectedSource = 'notation';
    } else if (_rulerCmPerPx > 0) {
      _selectedSource = 'ruler';
    } else {
      if (data.scale_cm_per_px > 0) {
        _manualCmPerPx = data.scale_cm_per_px;
      }
      _selectedSource = 'manual';
    }
    _prevSource = _selectedSource;

    _updateDisplay();

    var cmPx = getActiveCmPerPx();
    if (cmPx > 0 && window.ingState) {
      window.ingState.scale = cmPx;
    }
  }

  // --- Wire events ---

  function _wireEvents() {
    var display = document.getElementById('ingScaleDisplay');
    if (display) {
      display.addEventListener('click', _togglePopup);
    }
    document.addEventListener('click', function (e) {
      var sel = document.getElementById('ingScaleSelector');
      var popup = document.getElementById('ingScalePopup');
      if (sel && popup && !sel.contains(e.target)) {
        popup.style.display = 'none';
      }
    });
  }
  document.addEventListener('DOMContentLoaded', _wireEvents);

  // --- Exposed API ---
  window.olmScale = {
    parseDrawingScale: parseDrawingScale,
    computeCmPerPx: computeCmPerPx,
    getDrawingScale: getDrawingScale,
    getRenderDpi: getRenderDpi,
    getSelectedSource: getSelectedSource,
    getActiveCmPerPx: getActiveCmPerPx,
    populateScaleSelector: populateScaleSelector,
    suggestDrawingScale: function () {},
  };
})();
