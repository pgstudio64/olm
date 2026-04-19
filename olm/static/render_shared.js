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
//       Retourne un tableau de chaînes SVG (points 10 cm + lignes 1 m).
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
  var DEFAULT_GRID_DOT  = '#6e6a62';
  var DEFAULT_GRID_LINE = '#6e6a62';

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
      sweepDir = swingLeft ? 0 : 1;
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

  /**
   * Build SVG strings for a grid (10 cm dots + 1 m lines) over a viewbox.
   *
   * @param {object} opts
   * @param {object} opts.vb           { x, y, w, h } current viewBox.
   * @param {number} opts.cmPerPx      cm per pixel for this rendering.
   * @param {string} [opts.dotColor]   Color for 10 cm dots.
   * @param {string} [opts.lineColor]  Color for 1 m lines.
   * @param {number} [opts.marginRatio=0.5] Render margin as a fraction of
   *                                   max(vb.w, vb.h) — survives panning.
   * @param {boolean} [opts.minStartAt0=false] Clamp the first 1 m line
   *                                   origin to 0 (editor behaviour).
   * @returns {{dots: string[], lines: string[]}} Separate arrays so callers
   *          can apply different z-indices (editor uses z=-0.5 for dots,
   *          z=-0.4 for lines). Concatenate dots + lines for flat output.
   */
  function gridSvg(opts) {
    var vb = opts.vb;
    var cmPerPx = opts.cmPerPx;
    if (!vb || !cmPerPx || cmPerPx <= 0) return { dots: [], lines: [] };

    var dotColor = opts.dotColor || DEFAULT_GRID_DOT;
    var lineColor = opts.lineColor || DEFAULT_GRID_LINE;
    var marginRatio = (typeof opts.marginRatio === 'number') ? opts.marginRatio : 0.5;
    var minStartAt0 = !!opts.minStartAt0;

    var step10cm = 10 / cmPerPx;
    var step1m = 100 / cmPerPx;
    var margin = Math.max(vb.w, vb.h) * marginRatio;
    var gxS = Math.floor((vb.x - margin) / step10cm) * step10cm;
    var gyS = Math.floor((vb.y - margin) / step10cm) * step10cm;
    var gxE = vb.x + vb.w + margin;
    var gyE = vb.y + vb.h + margin;

    var dots = [];
    var lines = [];

    // 10 cm dots — skip when zoomed out too far (would overlap).
    // Cap max visual size: r ne dépasse pas 1.5 px (via _currentZf).
    if (vb.w / step10cm < 150) {
      var zf = window._currentZf || 1;
      var r = Math.min(0.6, 2 * zf);
      for (var gx = gxS; gx <= gxE; gx += step10cm) {
        for (var gy = gyS; gy <= gyE; gy += step10cm) {
          dots.push('<circle cx="' + gx.toFixed(1) + '" cy="' + gy.toFixed(1) +
            '" r="' + r.toFixed(2) + '" fill="' + dotColor + '"/>');
        }
      }
    }

    // 1 m lines
    var mxS, myS;
    if (minStartAt0) {
      mxS = Math.max(0, Math.floor(vb.x / step1m) * step1m);
      myS = Math.max(0, Math.floor(vb.y / step1m) * step1m);
    } else {
      mxS = Math.floor((vb.x - margin) / step1m) * step1m;
      myS = Math.floor((vb.y - margin) / step1m) * step1m;
    }

    for (var mx = mxS; mx <= gxE; mx += step1m) {
      lines.push('<line x1="' + mx.toFixed(1) + '" y1="' + gyS.toFixed(1) +
        '" x2="' + mx.toFixed(1) + '" y2="' + gyE.toFixed(1) +
        '" stroke="' + lineColor + '" stroke-width="0.5"/>');
    }
    for (var my = myS; my <= gyE; my += step1m) {
      lines.push('<line x1="' + gxS.toFixed(1) + '" y1="' + my.toFixed(1) +
        '" x2="' + gxE.toFixed(1) + '" y2="' + my.toFixed(1) +
        '" stroke="' + lineColor + '" stroke-width="0.5"/>');
    }

    return { dots: dots, lines: lines };
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
