"use strict";
// ========================================================================
// RENDER SHARED — SVG primitives partagées (D-94, phase 2)
// ========================================================================
//
// Sort des chaînes SVG pour les éléments dessinés de façon identique
// entre l'éditeur de patterns (`editor.js`) et le rendu d'ingestion
// (`ingestion.js`). Pas de sémantique z-indexée ici — chaque appelant
// wrappe les chaînes à sa convention (element.push({z,s}) ou push direct).
//
// Fonctions :
//   renderShared.doorSvg(face, hingeCoord, freeCoord, wallCoord,
//                        swingSide, opensInward, leafOffsetMag)
//       Retourne [arcPath, leafLine] pour une porte battante.
//
//   renderShared.gridSvg({ vb, cmPerPx, dotColor, lineColor,
//                          marginRatio, minStartAt0 })
//       Retourne { defs, fills } : un bloc <defs> avec 0-2 <pattern>
//       et 0-2 <rect fill="url(#...)"> couvrant la zone de grille.
//
// Constantes couleurs exposées : COLOR_DOOR_ARC, COLOR_DOOR_LEAF,
//   COLOR_WINDOW, COLOR_OPENING.
// ========================================================================

(function () {
  var COLOR_DOOR_ARC  = '#6e6a62';
  var COLOR_DOOR_LEAF = '#e4e0d8';
  var COLOR_WINDOW    = '#50b8d0';
  var COLOR_OPENING   = '#80c060';

  // Default grid colors (used by ingestion SVG). editor.js passes its own
  // darker shades (COLOR_GRID / COLOR_GRID_METER from block_constants.js).
  var DEFAULT_GRID_DOT  = '#8a8680';
  var DEFAULT_GRID_LINE = '#8a8680';

  /**
   * Build SVG strings for a hinged door (arc + leaf line).
   *
   * @param {string} face         'south' | 'north' | 'west' | 'east'
   * @param {number} hingeCoord   Position along the wall of the hinge end.
   * @param {number} freeCoord    Position along the wall of the free end.
   * @param {number} wallCoord    Perpendicular wall coordinate.
   * @param {string} swingSide    'left' or 'right' (as per data source).
   * @param {boolean} opensInward Whether the door opens into the room.
   * @param {number} [leafOffsetMag=0]  Micro-offset of the leaf line (px)
   *                              to avoid overlap with the arc (editor: 1.5).
   * @returns {string[]} Two SVG fragments: [arcPath, leafLine].
   */
  function doorSvg(face, hingeCoord, freeCoord, wallCoord, swingSide, opensInward, leafOffsetMag) {
    var dw = Math.abs(freeCoord - hingeCoord);
    var mag = leafOffsetMag || 0;
    var swingLeft = (swingSide === 'left');
    var sweepDir, leafOff, arcEnd;
    var arcPath, leafLine;

    if (face === 'south') {
      sweepDir = swingLeft ? 0 : 1;
      if (!opensInward) sweepDir = 1 - sweepDir;
      arcEnd = opensInward ? wallCoord - dw : wallCoord + dw;
      leafOff = swingLeft ? mag : -mag;
      arcPath = '<path d="M ' + freeCoord + ' ' + wallCoord +
        ' A ' + dw + ' ' + dw + ' 0 0 ' + sweepDir + ' ' + hingeCoord + ' ' + arcEnd +
        '" fill="none" stroke="' + COLOR_DOOR_ARC + '" stroke-width="2" vector-effect="non-scaling-stroke" stroke-dasharray="6 3"/>';
      leafLine = '<line x1="' + (hingeCoord + leafOff) + '" y1="' + wallCoord +
        '" x2="' + (hingeCoord + leafOff) + '" y2="' + arcEnd +
        '" stroke="' + COLOR_DOOR_LEAF + '" stroke-width="2" vector-effect="non-scaling-stroke"/>';
    } else if (face === 'north') {
      sweepDir = swingLeft ? 1 : 0;
      if (!opensInward) sweepDir = 1 - sweepDir;
      arcEnd = opensInward ? wallCoord + dw : wallCoord - dw;
      leafOff = swingLeft ? mag : -mag;
      arcPath = '<path d="M ' + freeCoord + ' ' + wallCoord +
        ' A ' + dw + ' ' + dw + ' 0 0 ' + sweepDir + ' ' + hingeCoord + ' ' + arcEnd +
        '" fill="none" stroke="' + COLOR_DOOR_ARC + '" stroke-width="2" vector-effect="non-scaling-stroke" stroke-dasharray="6 3"/>';
      leafLine = '<line x1="' + (hingeCoord + leafOff) + '" y1="' + wallCoord +
        '" x2="' + (hingeCoord + leafOff) + '" y2="' + arcEnd +
        '" stroke="' + COLOR_DOOR_LEAF + '" stroke-width="2" vector-effect="non-scaling-stroke"/>';
    } else if (face === 'west') {
      sweepDir = swingLeft ? 1 : 0;
      if (!opensInward) sweepDir = 1 - sweepDir;
      arcEnd = opensInward ? wallCoord + dw : wallCoord - dw;
      leafOff = swingLeft ? -mag : mag;
      arcPath = '<path d="M ' + wallCoord + ' ' + freeCoord +
        ' A ' + dw + ' ' + dw + ' 0 0 ' + sweepDir + ' ' + arcEnd + ' ' + hingeCoord +
        '" fill="none" stroke="' + COLOR_DOOR_ARC + '" stroke-width="2" vector-effect="non-scaling-stroke" stroke-dasharray="6 3"/>';
      leafLine = '<line x1="' + wallCoord + '" y1="' + (hingeCoord + leafOff) +
        '" x2="' + arcEnd + '" y2="' + (hingeCoord + leafOff) +
        '" stroke="' + COLOR_DOOR_LEAF + '" stroke-width="2" vector-effect="non-scaling-stroke"/>';
    } else { // east
      sweepDir = swingLeft ? 1 : 0;
      if (!opensInward) sweepDir = 1 - sweepDir;
      arcEnd = opensInward ? wallCoord - dw : wallCoord + dw;
      leafOff = swingLeft ? mag : -mag;
      arcPath = '<path d="M ' + wallCoord + ' ' + freeCoord +
        ' A ' + dw + ' ' + dw + ' 0 0 ' + sweepDir + ' ' + arcEnd + ' ' + hingeCoord +
        '" fill="none" stroke="' + COLOR_DOOR_ARC + '" stroke-width="2" vector-effect="non-scaling-stroke" stroke-dasharray="6 3"/>';
      leafLine = '<line x1="' + wallCoord + '" y1="' + (hingeCoord + leafOff) +
        '" x2="' + arcEnd + '" y2="' + (hingeCoord + leafOff) +
        '" stroke="' + COLOR_DOOR_LEAF + '" stroke-width="2" vector-effect="non-scaling-stroke"/>';
    }

    return [arcPath, leafLine];
  }

  // Unique pattern ID counter — incremented each call to avoid <defs> collisions.
  var _gridSeq = 0;

  /**
   * Build SVG pattern definitions and fill rects for a grid (10 cm dots + 1 m lines).
   *
   * @param {object} opts
   * @param {object} opts.vb           { x, y, w, h } current viewBox.
   * @param {number} opts.cmPerPx      cm per pixel for this rendering.
   * @param {string} [opts.dotColor]   Color for 10 cm dots.
   * @param {string} [opts.lineColor]  Color for 1 m lines.
   * @param {number} [opts.marginRatio=0.5] Render margin as a fraction of
   *                                   max(vb.w, vb.h) — survives panning.
   * @param {boolean} [opts.minStartAt0=false] Clamp the fill rect origin
   *                                   to 0 (editor behaviour).
   * @returns {{ defs: string, fills: string }} A <defs> block with 0-2
   *          <pattern> elements and 0-2 <rect fill="url(#...)"> strings.
   */
  function gridSvg(opts) {
    var vb = opts.vb;
    var cmPerPx = opts.cmPerPx;
    if (!vb || !cmPerPx || cmPerPx <= 0) return { defs: '', fills: '' };

    var dotColor = opts.dotColor || DEFAULT_GRID_DOT;
    var lineColor = opts.lineColor || DEFAULT_GRID_LINE;
    var marginRatio = (typeof opts.marginRatio === 'number') ? opts.marginRatio : 0.5;
    var minStartAt0 = !!opts.minStartAt0;

    var seq = ++_gridSeq;
    var dotId = 'olmGridDot_' + seq;
    var lineId = 'olmGridLine_' + seq;

    var step10cm = 10 / cmPerPx;
    var step1m = 100 / cmPerPx;
    var margin = Math.max(vb.w, vb.h) * marginRatio;
    // Align both start AND end to step1m so dots and lines cover the
    // exact same area (step1m is a multiple of step10cm).
    var gxS = Math.floor((vb.x - margin) / step1m) * step1m;
    var gyS = Math.floor((vb.y - margin) / step1m) * step1m;
    var gxE = Math.ceil((vb.x + vb.w + margin) / step1m) * step1m;
    var gyE = Math.ceil((vb.y + vb.h + margin) / step1m) * step1m;

    var patternDefs = '';
    var fills = '';

    // Dot pattern — skip when zoomed out too far (would overlap).
    if (vb.w / step10cm < 250) {
      var zf = window._currentZf || 1;
      // Min radius = vb.w/1000: ensures ~1.2 px on a 1200 px screen.
      var r = Math.max(vb.w / 1000, Math.min(step10cm * 0.08, 2 * zf));
      var halfStep = step10cm / 2;
      patternDefs += '<pattern id="' + dotId + '" width="' + step10cm.toFixed(4) +
        '" height="' + step10cm.toFixed(4) + '" patternUnits="userSpaceOnUse">' +
        '<circle cx="' + halfStep.toFixed(4) + '" cy="' + halfStep.toFixed(4) +
        '" r="' + r.toFixed(2) + '" fill="' + dotColor + '"/>' +
        '</pattern>';
      fills += '<rect x="' + gxS.toFixed(1) + '" y="' + gyS.toFixed(1) +
        '" width="' + (gxE - gxS).toFixed(1) + '" height="' + (gyE - gyS).toFixed(1) +
        '" fill="url(#' + dotId + ')"/>';
    }

    // Line pattern
    var lineRectX = gxS;
    var lineRectY = gyS;
    var lineRectW = gxE - gxS;
    var lineRectH = gyE - gyS;
    var lineZf = window._currentZf || 1;
    var lineW = Math.min(1.5, Math.max(0.5, 1.5 * lineZf));
    patternDefs += '<pattern id="' + lineId + '" width="' + step1m.toFixed(4) +
      '" height="' + step1m.toFixed(4) + '" patternUnits="userSpaceOnUse">' +
      '<line x1="0" y1="0" x2="' + step1m.toFixed(4) + '" y2="0"' +
      ' stroke="' + lineColor + '" stroke-width="' + lineW.toFixed(2) + '"/>' +
      '<line x1="0" y1="0" x2="0" y2="' + step1m.toFixed(4) + '"' +
      ' stroke="' + lineColor + '" stroke-width="' + lineW.toFixed(2) + '"/>' +
      '</pattern>';
    fills += '<rect x="' + lineRectX.toFixed(1) + '" y="' + lineRectY.toFixed(1) +
      '" width="' + lineRectW.toFixed(1) + '" height="' + lineRectH.toFixed(1) +
      '" fill="url(#' + lineId + ')"/>';

    return {
      defs: '<defs>' + patternDefs + '</defs>',
      fills: fills,
    };
  }

  window.renderShared = {
    doorSvg: doorSvg,
    gridSvg: gridSvg,
    COLOR_DOOR_ARC: COLOR_DOOR_ARC,
    COLOR_DOOR_LEAF: COLOR_DOOR_LEAF,
    COLOR_WINDOW: COLOR_WINDOW,
    COLOR_OPENING: COLOR_OPENING,
  };
})();
