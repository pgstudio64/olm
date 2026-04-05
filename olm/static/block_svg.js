"use strict";

// Requires COLOR_* and CHAIR_*_CM from block_constants.js

function renderDesk(elements, bx, by, d, SCALE) {
  const dx = bx + d.x * SCALE;
  const dy = by + d.y * SCALE;
  const dw = d.w * SCALE;
  const dh = d.h * SCALE;

  // Chair — rounded seat + arc backrest (B1-3 design)
  const isHoriz = (d.chairSide === "W" || d.chairSide === "E");
  const chW = isHoriz ? CHAIR_D_CM * SCALE : CHAIR_W_CM * SCALE;
  const chH = isHoriz ? CHAIR_W_CM * SCALE : CHAIR_D_CM * SCALE;
  const seatRx = Math.min(chW, chH) * 0.24;
  const overlap = chW * 0.4;
  const backStroke = chW * 0.14;
  // Backrest offset: slightly onto the seat (B1-3 = ~10% of seat width from edge)
  const backInset = chW * 0.10;
  const arcCurve = chW * 0.16;
  const arcPad = chH * 0.125;

  let chX, chY;
  let arcD;  // arc path string

  if (d.chairSide === "W") {
    chX = dx - chW + overlap;
    chY = dy + (dh - chH) / 2;
    var ax = chX + backInset;
    arcD = "M" + ax + "," + (chY + arcPad) + " Q" + (ax - arcCurve) + "," + (chY + chH / 2) + " " + ax + "," + (chY + chH - arcPad);
  } else if (d.chairSide === "E") {
    chX = dx + dw - overlap;
    chY = dy + (dh - chH) / 2;
    var ax = chX + chW - backInset;
    arcD = "M" + ax + "," + (chY + arcPad) + " Q" + (ax + arcCurve) + "," + (chY + chH / 2) + " " + ax + "," + (chY + chH - arcPad);
  } else if (d.chairSide === "N") {
    chX = dx + (dw - chW) / 2;
    chY = dy - chH + chH * 0.6;
    var ay = chY + backInset;
    arcD = "M" + (chX + arcPad) + "," + ay + " Q" + (chX + chW / 2) + "," + (ay - arcCurve) + " " + (chX + chW - arcPad) + "," + ay;
  } else {
    chX = dx + (dw - chW) / 2;
    chY = dy + dh - chH * 0.6;
    var ay = chY + chH - backInset;
    arcD = "M" + (chX + arcPad) + "," + ay + " Q" + (chX + chW / 2) + "," + (ay + arcCurve) + " " + (chX + chW - arcPad) + "," + ay;
  }

  // Seat (z=4)
  elements.push({ z: 4, s:
    '<rect x="' + chX + '" y="' + chY + '" width="' + chW + '" height="' + chH +
    '" fill="' + COLOR_CHAIR + '" rx="' + seatRx + '"/>'
  });
  // Backrest arc (z=4)
  elements.push({ z: 4, s:
    '<path d="' + arcD + '" stroke="' + COLOR_CHAIR_BACK +
    '" stroke-width="' + backStroke + '" fill="none" stroke-linecap="round"/>'
  });

  // Desk (z=5)
  elements.push({ z: 5, s:
    '<rect x="' + dx + '" y="' + dy + '" width="' + dw + '" height="' + dh +
    '" fill="' + COLOR_DESK_FILL + '" stroke="' + COLOR_DESK_STROKE + '" stroke-width="0.8"/>'
  });

  // Screen — inset by screen thickness (z=6)
  let scrX, scrY, scrW, scrH;
  const scrThick = 3;
  if (d.screenSide === "E" || d.screenSide === "W") {
    scrW = scrThick; scrH = dh * 0.55;
    scrY = dy + (dh - scrH) / 2;
    scrX = (d.screenSide === "W") ? dx + scrThick : dx + dw - scrThick * 2;
  } else {
    scrH = scrThick; scrW = dw * 0.55;
    scrX = dx + (dw - scrW) / 2;
    scrY = (d.screenSide === "N") ? dy + scrThick : dy + dh - scrThick * 2;
  }
  elements.push({ z: 6, s:
    '<rect x="' + scrX + '" y="' + scrY + '" width="' + scrW + '" height="' + scrH +
    '" fill="' + COLOR_SCREEN + '" rx="1"/>'
  });

  // Label (z=6, zoom-compensated)
  var labelZf = window._currentZf || 1;
  var labelFs = (20 * labelZf).toFixed(1);
  elements.push({ z: 6, s:
    '<text x="' + (dx + dw / 2) + '" y="' + (dy + dh / 2 + 6 * labelZf) +
    '" text-anchor="middle" fill="' + COLOR_LABEL +
    '" font-size="' + labelFs + '" font-family="monospace">' + d.label + '</text>'
  });
}
