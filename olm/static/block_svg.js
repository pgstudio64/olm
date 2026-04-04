"use strict";

// Requires COLOR_* and CHAIR_*_CM from block_constants.js

function renderDesk(elements, bx, by, d, SCALE) {
  const dx = bx + d.x * SCALE;
  const dy = by + d.y * SCALE;
  const dw = d.w * SCALE;
  const dh = d.h * SCALE;

  // Fauteuil (z=4)
  const isHoriz = (d.chairSide === "W" || d.chairSide === "E");
  const chW = isHoriz ? CHAIR_D_CM * SCALE : CHAIR_W_CM * SCALE;
  const chH = isHoriz ? CHAIR_W_CM * SCALE : CHAIR_D_CM * SCALE;
  const overlap = chW * 0.4;
  const armH = 3;
  let chX, chY, backX, backY, backW, backH;
  let arm1X, arm1Y, arm2X, arm2Y, armRW, armRH;
  chY = dy + (dh - chH) / 2;
  if (d.chairSide === "W") {
    chX = dx - chW + overlap;
    backX = chX - 2; backY = chY + 2; backW = 5; backH = chH - 4;
    arm1X = chX; arm1Y = chY - 1; armRW = chW; armRH = armH;
    arm2X = chX; arm2Y = chY + chH - armH + 1; armRW = chW; armRH = armH;
  } else if (d.chairSide === "E") {
    chX = dx + dw - overlap;
    backX = chX + chW - 5; backY = chY + 2; backW = 5; backH = chH - 4;
    arm1X = chX; arm1Y = chY - 1; armRW = chW; armRH = armH;
    arm2X = chX; arm2Y = chY + chH - armH + 1; armRW = chW; armRH = armH;
  } else if (d.chairSide === "N") {
    chX = dx + (dw - chW) / 2;
    chY = dy - chH + chH * 0.6;
    backX = chX + 2; backY = chY - 2; backW = chW - 4; backH = 5;
    arm1X = chX - 1; arm1Y = chY; armRW = armH; armRH = chH;
    arm2X = chX + chW - armH + 1; arm2Y = chY; armRW = armH; armRH = chH;
  } else {
    chX = dx + (dw - chW) / 2;
    chY = dy + dh - chH * 0.6;
    backX = chX + 2; backY = chY + chH - 3; backW = chW - 4; backH = 5;
    arm1X = chX - 1; arm1Y = chY; armRW = armH; armRH = chH;
    arm2X = chX + chW - armH + 1; arm2Y = chY; armRW = armH; armRH = chH;
  }
  elements.push({ z: 4, s:
    '<rect x="' + chX + '" y="' + chY + '" width="' + chW + '" height="' + chH +
    '" fill="' + COLOR_CHAIR + '" rx="5"/>' +
    '<rect x="' + backX + '" y="' + backY + '" width="' + backW + '" height="' + backH +
    '" fill="' + COLOR_CHAIR_BACK + '" rx="3"/>' +
    '<rect x="' + arm1X + '" y="' + arm1Y + '" width="' + armRW + '" height="' + armRH +
    '" fill="' + COLOR_CHAIR_ARM + '" rx="2"/>' +
    '<rect x="' + arm2X + '" y="' + arm2Y + '" width="' + armRW + '" height="' + armRH +
    '" fill="' + COLOR_CHAIR_ARM + '" rx="2"/>'
  });

  // Bureau (z=5)
  elements.push({ z: 5, s:
    '<rect x="' + dx + '" y="' + dy + '" width="' + dw + '" height="' + dh +
    '" fill="' + COLOR_DESK_FILL + '" stroke="' + COLOR_DESK_STROKE + '" stroke-width="0.8"/>'
  });

  // Ecran (z=6)
  let scrX, scrY, scrW, scrH;
  if (d.screenSide === "E" || d.screenSide === "W") {
    scrW = 3; scrH = dh * 0.55;
    scrY = dy + (dh - scrH) / 2;
    scrX = (d.screenSide === "W") ? dx : dx + dw - scrW;
  } else {
    scrH = 3; scrW = dw * 0.55;
    scrX = dx + (dw - scrW) / 2;
    scrY = (d.screenSide === "N") ? dy : dy + dh - scrH;
  }
  elements.push({ z: 6, s:
    '<rect x="' + scrX + '" y="' + scrY + '" width="' + scrW + '" height="' + scrH +
    '" fill="' + COLOR_SCREEN + '" rx="1"/>'
  });

  // Label (z=6)
  elements.push({ z: 6, s:
    '<text x="' + (dx + dw / 2) + '" y="' + (dy + dh / 2 + 3) +
    '" text-anchor="middle" fill="' + COLOR_LABEL +
    '" font-size="8" font-family="monospace">' + d.label + '</text>'
  });
}
