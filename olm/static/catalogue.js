"use strict";
// ========== CATALOGUE ==========

let catalogueData = [];

async function loadCatalogue() {
  try {
    var resp = await fetch("/api/patterns");
    if (!resp.ok) throw new Error(await resp.text());
    var data = await resp.json();
    catalogueData = data.patterns || [];
    try {
      renderCatalogue();
    } catch (renderErr) {
      console.error("renderCatalogue error:", renderErr);
      document.getElementById("catalogueGrid").innerHTML =
        '<div style="color:var(--bad);padding:24px;">Render error: ' + renderErr.message + '</div>';
    }
  } catch (err) {
    console.error("loadCatalogue error:", err);
    document.getElementById("catalogueGrid").innerHTML =
      '<div style="color:var(--bad);padding:24px;">Error: ' + err.message + '</div>';
  }
}

function renderCatalogue() {
  var grid = document.getElementById("catalogueGrid");
  var filtered = getFilteredPatterns();

  // Matrix sort: depth ascending, width ascending, then name ascending
  filtered.sort(function(a, b) {
    var da = (a.room_depth_cm || 0) - (b.room_depth_cm || 0);
    if (da !== 0) return da;
    var wa = (a.room_width_cm || 0) - (b.room_width_cm || 0);
    if (wa !== 0) return wa;
    return (a.name || "").localeCompare(b.name || "", undefined, { numeric: true });
  });

  document.getElementById("catCount").textContent = filtered.length + " pattern(s)";

  if (filtered.length === 0) {
    grid.innerHTML = '<div style="color:var(--text-dim);font-size:12px;padding:24px;">No patterns.</div>';
    return;
  }

  // Group by depth to display one row per depth
  var groups = [];
  var currentDepth = null;
  filtered.forEach(function(p) {
    var d = p.room_depth_cm || 0;
    if (d !== currentDepth) {
      groups.push({ depth: d, patterns: [] });
      currentDepth = d;
    }
    groups[groups.length - 1].patterns.push(p);
  });

  var html = "";
  groups.forEach(function(group) {
    html += '<div class="catalogue-row">';
    html += '<div class="catalogue-row-label">' + group.depth + ' cm</div>';
    html += '<div class="catalogue-row-cards">';
    group.patterns.forEach(function(p) {
      var nDesks = 0;
      var nBlocks = 0;
      (p.rows || []).forEach(function(r) {
        (r.blocks || []).forEach(function(b) {
          nBlocks++;
          nDesks += countDesksInBlock(b.type) || 0;
        });
      });
      var std = getStdLabel(p.standard) || "?";
      var w = p.room_width_cm || "?";
      var d = p.room_depth_cm || "?";

      var overflow = patternOverflowsRoom(p);
      var cardClass = "catalogue-card" + (overflow ? " card-overflow" : "");
      html += '<div class="' + cardClass + '" data-pattern-name="' + (p.name || "") + '">';
      html += '<button class="card-delete" data-del-name="' + (p.name || "") + '" title="Delete">&times;</button>';
      html += '<div class="card-title">' + (p.name || "Unnamed") + '</div>';
      html += '<div class="card-info">' + nDesks + ' desks · ' + nBlocks + ' blocks · ' + std + ' · ' + w + 'x' + d + '</div>';
      var sc = computePatternScoring(p);
      if (sc.nDesks > 0) html += '<div class="card-info">' + scoringHtml(sc) + '</div>';
      if (overflow) html += '<div class="card-warning">Overflow</div>';
      html += '</div>';
    });
    html += '</div></div>';
  });
  grid.innerHTML = html;

  // Click card = switch to editor sub-tab and load pattern
  grid.querySelectorAll(".catalogue-card").forEach(function(card) {
    card.addEventListener("click", function(e) {
      if (e.target.classList.contains("card-delete")) return;
      var name = card.dataset.patternName;
      if (name) {
        document.querySelector('.sub-tab-btn[data-subtab="catEditor"]').click();
        loadPattern(name);
      }
    });
  });

  // Click delete button = remove with confirmation
  grid.querySelectorAll(".card-delete").forEach(function(btn) {
    btn.addEventListener("click", async function(e) {
      e.stopPropagation();
      var name = btn.dataset.delName;
      if (!name) return;
      if (!confirm("Delete \"" + name + "\" from catalogue?")) return;
      try {
        var resp = await fetch("/api/patterns/" + encodeURIComponent(name), { method: "DELETE" });
        if (!resp.ok) throw new Error(await resp.text());
        loadCatalogue();
      } catch (err) {
        setStatus("Delete error: " + err.message);
      }
    });
  });
}

// ========== MATRIX VIEW ==========

let matrixViewBox = { x: 0, y: 0, w: 1000, h: 800 };
let matrixPanning = false;
let matrixPanStart = { x: 0, y: 0 };
// Metadata for fixed rulers
let matrixMeta = { widths: [], depths: [], colXs: [], rowYs: [], colWidths: [], rowHeights: [], labelW: 60, labelH: 30, margin: 20 };


function getFilteredPatterns() {
  var stdFilter = document.getElementById("catFilterStandard").value;
  var minW = parseInt(document.getElementById("catFilterMinW").value) || 0;
  var maxW = parseInt(document.getElementById("catFilterMaxW").value) || Infinity;
  var minD = parseInt(document.getElementById("catFilterMinD").value) || 0;
  var maxD = parseInt(document.getElementById("catFilterMaxD").value) || Infinity;
  return catalogueData.filter(function(p) {
    if (stdFilter && p.standard !== stdFilter) return false;
    var w = p.room_width_cm || 0;
    var d = p.room_depth_cm || 0;
    if (w < minW || w > maxW) return false;
    if (d < minD || d > maxD) return false;
    return true;
  });
}


// --- Shared rendering functions (used by both _renderImpl and renderPatternMiniSvg) ---

function renderBlockZones(elements, bx, by, bw, bh, blockType, orientation, faces, scale, strokeW) {
  var isOrtho = (blockType === "BLOCK_2_ORTHO_R" || blockType === "BLOCK_2_ORTHO_L");
  if (isOrtho) {
    var orthoDesks = getDeskRects(blockType);
    var orthoOrient = orientation || 0;
    if (orthoOrient !== 0) {
      var g0 = getBlockGeom(blockType);
      orthoDesks = transformDeskRects(orthoDesks, g0.eo, g0.ns, orthoOrient);
    }
    orthoDesks.forEach(function(d) {
      var dx = bx + d.x * scale, dy = by + d.y * scale;
      var dw = d.w * scale, dh = d.h * scale;
      var faceKey = {N:"north",S:"south",E:"east",W:"west"}[d.chairSide];
      var faceData = faces[faceKey] || {};
      var chrPx = (faceData.non_superposable_cm || 70) * scale;
      var candPx = (faceData.candidate_cm || 30) * scale;
      if (d.chairSide === "W") {
        elements.push({ z: 2, s: '<rect x="' + (dx - chrPx) + '" y="' + dy + '" width="' + chrPx + '" height="' + dh + '" fill="' + COLOR_NSUP_FILL + '" fill-opacity="' + COLOR_NSUP_OPACITY + '" stroke="' + COLOR_CAND_STROKE + '" stroke-width="' + strokeW + '"/>' });
        elements.push({ z: 1, s: '<rect x="' + (dx - chrPx - candPx) + '" y="' + dy + '" width="' + candPx + '" height="' + dh + '" fill="' + COLOR_CAND_FILL + '" fill-opacity="' + COLOR_CAND_OPACITY + '" stroke="' + COLOR_CAND_STROKE + '" stroke-width="' + strokeW + '"/>' });
      } else if (d.chairSide === "E") {
        elements.push({ z: 2, s: '<rect x="' + (dx + dw) + '" y="' + dy + '" width="' + chrPx + '" height="' + dh + '" fill="' + COLOR_NSUP_FILL + '" fill-opacity="' + COLOR_NSUP_OPACITY + '" stroke="' + COLOR_CAND_STROKE + '" stroke-width="' + strokeW + '"/>' });
        elements.push({ z: 1, s: '<rect x="' + (dx + dw + chrPx) + '" y="' + dy + '" width="' + candPx + '" height="' + dh + '" fill="' + COLOR_CAND_FILL + '" fill-opacity="' + COLOR_CAND_OPACITY + '" stroke="' + COLOR_CAND_STROKE + '" stroke-width="' + strokeW + '"/>' });
      } else if (d.chairSide === "N") {
        elements.push({ z: 2, s: '<rect x="' + dx + '" y="' + (dy - chrPx) + '" width="' + dw + '" height="' + chrPx + '" fill="' + COLOR_NSUP_FILL + '" fill-opacity="' + COLOR_NSUP_OPACITY + '" stroke="' + COLOR_CAND_STROKE + '" stroke-width="' + strokeW + '"/>' });
        elements.push({ z: 1, s: '<rect x="' + dx + '" y="' + (dy - chrPx - candPx) + '" width="' + dw + '" height="' + candPx + '" fill="' + COLOR_CAND_FILL + '" fill-opacity="' + COLOR_CAND_OPACITY + '" stroke="' + COLOR_CAND_STROKE + '" stroke-width="' + strokeW + '"/>' });
      } else if (d.chairSide === "S") {
        elements.push({ z: 2, s: '<rect x="' + dx + '" y="' + (dy + dh) + '" width="' + dw + '" height="' + chrPx + '" fill="' + COLOR_NSUP_FILL + '" fill-opacity="' + COLOR_NSUP_OPACITY + '" stroke="' + COLOR_CAND_STROKE + '" stroke-width="' + strokeW + '"/>' });
        elements.push({ z: 1, s: '<rect x="' + dx + '" y="' + (dy + dh + chrPx) + '" width="' + dw + '" height="' + candPx + '" fill="' + COLOR_CAND_FILL + '" fill-opacity="' + COLOR_CAND_OPACITY + '" stroke="' + COLOR_CAND_STROKE + '" stroke-width="' + strokeW + '"/>' });
      }
    });
  } else {
    var wNSup = ((faces.west && faces.west.non_superposable_cm) || 0) * scale;
    var wCandPx = ((faces.west && faces.west.candidate_cm) || 0) * scale;
    var eNSup = ((faces.east && faces.east.non_superposable_cm) || 0) * scale;
    var eCandPx = ((faces.east && faces.east.candidate_cm) || 0) * scale;
    var nNSup = ((faces.north && faces.north.non_superposable_cm) || 0) * scale;
    var nCandPx = ((faces.north && faces.north.candidate_cm) || 0) * scale;
    var sNSup = ((faces.south && faces.south.non_superposable_cm) || 0) * scale;
    var sCandPx = ((faces.south && faces.south.candidate_cm) || 0) * scale;
    if (wNSup > 0) elements.push({ z: 2, s: '<rect x="' + (bx - wNSup) + '" y="' + by + '" width="' + wNSup + '" height="' + bh + '" fill="' + COLOR_NSUP_FILL + '" fill-opacity="' + COLOR_NSUP_OPACITY + '" stroke="' + COLOR_CAND_STROKE + '" stroke-width="' + strokeW + '"/>' });
    if (eNSup > 0) elements.push({ z: 2, s: '<rect x="' + (bx + bw) + '" y="' + by + '" width="' + eNSup + '" height="' + bh + '" fill="' + COLOR_NSUP_FILL + '" fill-opacity="' + COLOR_NSUP_OPACITY + '" stroke="' + COLOR_CAND_STROKE + '" stroke-width="' + strokeW + '"/>' });
    if (nNSup > 0) elements.push({ z: 2, s: '<rect x="' + bx + '" y="' + (by - nNSup) + '" width="' + bw + '" height="' + nNSup + '" fill="' + COLOR_NSUP_FILL + '" fill-opacity="' + COLOR_NSUP_OPACITY + '" stroke="' + COLOR_CAND_STROKE + '" stroke-width="' + strokeW + '"/>' });
    if (sNSup > 0) elements.push({ z: 2, s: '<rect x="' + bx + '" y="' + (by + bh) + '" width="' + bw + '" height="' + sNSup + '" fill="' + COLOR_NSUP_FILL + '" fill-opacity="' + COLOR_NSUP_OPACITY + '" stroke="' + COLOR_CAND_STROKE + '" stroke-width="' + strokeW + '"/>' });
    if (wNSup > 0 && wCandPx > 0) elements.push({ z: 1, s: '<rect x="' + (bx - wNSup - wCandPx) + '" y="' + by + '" width="' + wCandPx + '" height="' + bh + '" fill="' + COLOR_CAND_FILL + '" fill-opacity="' + COLOR_CAND_OPACITY + '" stroke="' + COLOR_CAND_STROKE + '" stroke-width="' + strokeW + '"/>' });
    if (eNSup > 0 && eCandPx > 0) elements.push({ z: 1, s: '<rect x="' + (bx + bw + eNSup) + '" y="' + by + '" width="' + eCandPx + '" height="' + bh + '" fill="' + COLOR_CAND_FILL + '" fill-opacity="' + COLOR_CAND_OPACITY + '" stroke="' + COLOR_CAND_STROKE + '" stroke-width="' + strokeW + '"/>' });
    if (nNSup > 0 && nCandPx > 0) elements.push({ z: 1, s: '<rect x="' + bx + '" y="' + (by - nNSup - nCandPx) + '" width="' + bw + '" height="' + nCandPx + '" fill="' + COLOR_CAND_FILL + '" fill-opacity="' + COLOR_CAND_OPACITY + '" stroke="' + COLOR_CAND_STROKE + '" stroke-width="' + strokeW + '"/>' });
    if (sNSup > 0 && sCandPx > 0) elements.push({ z: 1, s: '<rect x="' + bx + '" y="' + (by + bh + sNSup) + '" width="' + bw + '" height="' + sCandPx + '" fill="' + COLOR_CAND_FILL + '" fill-opacity="' + COLOR_CAND_OPACITY + '" stroke="' + COLOR_CAND_STROKE + '" stroke-width="' + strokeW + '"/>' });
  }
}

function renderBlockDesks(elements, bx, by, blockType, orientation, scale, startIndex) {
  var desks = getDeskRects(blockType);
  var orient = orientation || 0;
  if (orient !== 0) {
    var g0 = getBlockGeom(blockType);
    desks = transformDeskRects(desks, g0.eo, g0.ns, orient);
  }
  for (var di = 0; di < desks.length; di++) {
    desks[di].label = "WS" + String(startIndex + di + 1).padStart(2, "0");
    renderDesk(elements, bx, by, desks[di], scale);
  }
  return desks.length;
}

// --- End shared rendering functions ---

function renderPatternMiniSvg(p, scale, offsetX, offsetY) {
  // Rendering identical to editor: z-order, circulation zones, chairs, screens, distances
  // Switch BLOCK_DEFS to the pattern's standard for correct dimensions
  var savedDefs = BLOCK_DEFS;
  if (p.standard && BLOCK_DEFS_BY_STD[p.standard]) BLOCK_DEFS = BLOCK_DEFS_BY_STD[p.standard];
  var elements = [];
  var roomWcm = p.room_width_cm || 300;
  var roomHcm = p.room_depth_cm || 400;
  var roomW = roomWcm * scale;
  var roomH = roomHcm * scale;

  // Room background (z=0.05)
  elements.push({ z: 0.05, s: '<rect x="' + offsetX + '" y="' + offsetY +
    '" width="' + roomW + '" height="' + roomH +
    '" fill="' + COLOR_CAND_FILL + '" stroke="#4a4640" stroke-width="1"/>' });

  // Room dimension labels (z=10)
  elements.push({ z: 10, s: '<text x="' + (offsetX + roomW / 2) + '" y="' + (offsetY - 3) +
    '" text-anchor="middle" fill="' + COLOR_RULER + '" font-size="7" font-family="monospace">' +
    roomWcm + ' cm</text>' });
  elements.push({ z: 10, s: '<text x="' + (offsetX - 3) + '" y="' + (offsetY + roomH / 2) +
    '" text-anchor="middle" fill="' + COLOR_RULER + '" font-size="7" font-family="monospace"' +
    ' transform="rotate(-90,' + (offsetX - 3) + ',' + (offsetY + roomH / 2) + ')">' +
    roomHcm + ' cm</text>' });

  // Exclusion zones (z=5)
  (p.room_exclusions || []).forEach(function(z) {
    var zx = offsetX + z.x_cm * scale;
    var zy = offsetY + z.y_cm * scale;
    var zw = z.width_cm * scale;
    var zh = z.depth_cm * scale;
    elements.push({ z: 5, s: '<rect x="' + zx + '" y="' + zy +
      '" width="' + zw + '" height="' + zh +
      '" fill="#c05858" fill-opacity="0.25" stroke="#c05858" stroke-width="0.3"/>' });
  });

  // Windows — cyan line (z=6)
  (p.room_windows || []).forEach(function(w) {
    var wPos = wallSegment(w.face, w.offset_cm, w.width_cm, offsetX, offsetY, roomW, roomH, 1.5, scale);
    elements.push({ z: 6, s: '<line x1="' + wPos.x1 + '" y1="' + wPos.y1 +
      '" x2="' + wPos.x2 + '" y2="' + wPos.y2 +
      '" stroke="#50b8d0" stroke-width="2.5" stroke-linecap="round"/>' });
  });

  // Doors and openings (z=5.5 erases wall, z=6 draws)
  (p.room_openings || []).forEach(function(o) {
    var oPos = wallSegment(o.face, o.offset_cm, o.width_cm, offsetX, offsetY, roomW, roomH, 0, scale);
    var dw = o.width_cm * scale;
    // Erase wall under opening
    elements.push({ z: 5.5, s: '<line x1="' + oPos.x1 + '" y1="' + oPos.y1 +
      '" x2="' + oPos.x2 + '" y2="' + oPos.y2 +
      '" stroke="#1e1e1e" stroke-width="3"/>' });
    if (!o.has_door) {
      // Open bay — dashed green line
      elements.push({ z: 6, s: '<line x1="' + oPos.x1 + '" y1="' + oPos.y1 +
        '" x2="' + oPos.x2 + '" y2="' + oPos.y2 +
        '" stroke="#80c060" stroke-width="1" stroke-dasharray="4 3"/>' });
    } else {
      // Hinged door — simplified arc
      var hingeS = o.hinge_side || "left";
      var off = o.offset_cm * scale;
      if (o.face === "south") {
        var dx = offsetX + off;
        var dy = offsetY + roomH;
        var hx = (hingeS === "left") ? dx : dx + dw;
        var fx = (hingeS === "left") ? dx + dw : dx;
        var sw = (hingeS === "left") ? 0 : 1;
        if (!o.opens_inward) sw = 1 - sw;
        var ey = o.opens_inward ? dy - dw : dy + dw;
        elements.push({ z: 6, s: '<path d="M ' + fx + ' ' + dy +
          ' A ' + dw + ' ' + dw + ' 0 0 ' + sw + ' ' + hx + ' ' + ey +
          '" fill="none" stroke="#6e6a62" stroke-width="1.5" stroke-dasharray="6 3"/>' });
        elements.push({ z: 6, s: '<line x1="' + hx + '" y1="' + dy +
          '" x2="' + hx + '" y2="' + ey +
          '" stroke="#e4e0d8" stroke-width="1.5"/>' });
      } else if (o.face === "north") {
        var dx = offsetX + off;
        var dy = offsetY;
        var hx = (hingeS === "left") ? dx : dx + dw;
        var fx = (hingeS === "left") ? dx + dw : dx;
        var sw = (hingeS === "left") ? 1 : 0;
        if (!o.opens_inward) sw = 1 - sw;
        var ey = o.opens_inward ? dy + dw : dy - dw;
        elements.push({ z: 6, s: '<path d="M ' + fx + ' ' + dy +
          ' A ' + dw + ' ' + dw + ' 0 0 ' + sw + ' ' + hx + ' ' + ey +
          '" fill="none" stroke="#6e6a62" stroke-width="1.5" stroke-dasharray="6 3"/>' });
        elements.push({ z: 6, s: '<line x1="' + hx + '" y1="' + dy +
          '" x2="' + hx + '" y2="' + ey +
          '" stroke="#e4e0d8" stroke-width="1.5"/>' });
      } else if (o.face === "west") {
        var dx = offsetX;
        var dy = offsetY + off;
        var hy = (hingeS === "left") ? dy + dw : dy;
        var fy = (hingeS === "left") ? dy : dy + dw;
        var sw = (hingeS === "left") ? 0 : 1;
        if (!o.opens_inward) sw = 1 - sw;
        var ex = o.opens_inward ? dx + dw : dx - dw;
        elements.push({ z: 6, s: '<path d="M ' + dx + ' ' + fy +
          ' A ' + dw + ' ' + dw + ' 0 0 ' + sw + ' ' + ex + ' ' + hy +
          '" fill="none" stroke="#6e6a62" stroke-width="1.5" stroke-dasharray="6 3"/>' });
        elements.push({ z: 6, s: '<line x1="' + dx + '" y1="' + hy +
          '" x2="' + ex + '" y2="' + hy +
          '" stroke="#e4e0d8" stroke-width="1.5"/>' });
      } else if (o.face === "east") {
        var dx = offsetX + roomW;
        var dy = offsetY + off;
        var hy = (hingeS === "left") ? dy : dy + dw;
        var fy = (hingeS === "left") ? dy + dw : dy;
        var sw = (hingeS === "left") ? 1 : 0;
        if (!o.opens_inward) sw = 1 - sw;
        var ex = o.opens_inward ? dx - dw : dx + dw;
        elements.push({ z: 6, s: '<path d="M ' + dx + ' ' + fy +
          ' A ' + dw + ' ' + dw + ' 0 0 ' + sw + ' ' + ex + ' ' + hy +
          '" fill="none" stroke="#6e6a62" stroke-width="1.5" stroke-dasharray="6 3"/>' });
        elements.push({ z: 6, s: '<line x1="' + dx + '" y1="' + hy +
          '" x2="' + ex + '" y2="' + hy +
          '" stroke="#e4e0d8" stroke-width="1.5"/>' });
      }
    }
  });

  var rows = p.rows || [];
  var rowGaps = p.row_gaps_cm || [];
  var yRow = offsetY;
  var globalDeskIndex = 0;
  var blockRects = [];

  for (var ri = 0; ri < rows.length; ri++) {
    var row = rows[ri];
    var xBlock = offsetX;
    var rowMaxNS = 0;

    for (var bi = 0; bi < (row.blocks || []).length; bi++) {
      var b = row.blocks[bi];
      var g = getEffectiveGeom(b.type, b.orientation);
      var f = g.faces;
      var offsetNS = (b.offset_ns_cm || 0) * scale;
      if (b.gap_cm) xBlock += b.gap_cm * scale;

      var bx = xBlock;
      var by = yRow + offsetNS;
      var bw = g.eo * scale;
      var bh = g.ns * scale;
      blockRects.push({ x: bx, y: by, w: bw, h: bh });

      // Circulation zones per face (via shared renderBlockZones)
      renderBlockZones(elements, bx, by, bw, bh, b.type, b.orientation, f, scale, 0.3);

      // Opaque background block footprint (z=0.5)
      elements.push({ z: 0.5, s: '<rect x="' + bx + '" y="' + by +
        '" width="' + bw + '" height="' + bh + '" fill="#1e1e1e"/>' });

      // Block border (z=3)
      elements.push({ z: 3, s: '<rect x="' + bx + '" y="' + by +
        '" width="' + bw + '" height="' + bh +
        '" fill="none" stroke="' + COLOR_BLOCK_BORDER + '" stroke-width="0.5" stroke-dasharray="3 2"/>' });

      // Desks via shared renderBlockDesks (z=4,5,6)
      globalDeskIndex += renderBlockDesks(elements, bx, by, b.type, b.orientation, scale, globalDeskIndex);

      xBlock += bw;
      if (g.ns > rowMaxNS) rowMaxNS = g.ns;
    }

    yRow += rowMaxNS * scale;
    if (ri < rows.length - 1) {
      yRow += (rowGaps[ri] || 0) * scale;
    }
  }

  // Distances between neighboring blocks (z=7)
  // Rule V-01: distance shown iff nearest neighbor AND desk footprint
  // overlap on the perpendicular axis.
  // blockRects already contains the desk footprint (without zones).
  var labelFontSize = Math.max(5, Math.min(9, roomW * 0.07));
  for (var i = 0; i < blockRects.length; i++) {
    var a = blockRects[i];
    var nearestRightGap = Infinity, nearestRight = null;
    var nearestBelowGap = Infinity, nearestBelow = null;
    for (var j = 0; j < blockRects.length; j++) {
      if (i === j) continue;
      var bb = blockRects[j];
      // Right neighbor: NS desk overlap
      if (bb.x > a.x) {
        var gp = bb.x - (a.x + a.w);
        if (gp > 0.5 && gp < nearestRightGap) {
          var nsOv = Math.min(a.y + a.h, bb.y + bb.h) - Math.max(a.y, bb.y);
          if (nsOv > 0.5) { nearestRightGap = gp; nearestRight = bb; }
        }
      }
      // Below neighbor: EW desk overlap
      if (bb.y > a.y) {
        var gp2 = bb.y - (a.y + a.h);
        if (gp2 > 0.5 && gp2 < nearestBelowGap) {
          var eoOv = Math.min(a.x + a.w, bb.x + bb.w) - Math.max(a.x, bb.x);
          if (eoOv > 0.5) { nearestBelowGap = gp2; nearestBelow = bb; }
        }
      }
    }
    if (nearestRight) {
      var gcm = Math.round(nearestRightGap / scale);
      var lx = a.x + a.w + nearestRightGap / 2;
      var ovT = Math.max(a.y, nearestRight.y);
      var ovB = Math.min(a.y + a.h, nearestRight.y + nearestRight.h);
      elements.push({ z: 7, s: '<text x="' + lx.toFixed(1) + '" y="' + ((ovT + ovB) / 2 + labelFontSize * 0.35).toFixed(1) +
        '" text-anchor="middle" fill="' + COLOR_GAP_LABEL + '" font-size="' + labelFontSize + '" font-weight="bold" font-family="monospace">' + gcm + '</text>' });
    }
    if (nearestBelow) {
      var gcm2 = Math.round(nearestBelowGap / scale);
      var ovL = Math.max(a.x, nearestBelow.x);
      var ovR = Math.min(a.x + a.w, nearestBelow.x + nearestBelow.w);
      elements.push({ z: 7, s: '<text x="' + ((ovL + ovR) / 2).toFixed(1) + '" y="' + (a.y + a.h + nearestBelowGap / 2 + labelFontSize * 0.35).toFixed(1) +
        '" text-anchor="middle" fill="' + COLOR_GAP_LABEL + '" font-size="' + labelFontSize + '" font-weight="bold" font-family="monospace">' + gcm2 + '</text>' });
    }
  }

  // Block-to-wall distances (z=7) — Rule V-02:
  // For each block x each direction, show distance to wall UNLESS
  // another block (desk overlap on perpendicular axis) is between this
  // block and the wall, or the distance is zero.
  var wallColor = "#5090c0";
  for (var k = 0; k < blockRects.length; k++) {
    var br = blockRects[k];
    var wdirs = [
      { axis: "y", sign: -1, wallEdge: offsetY, bEdge: br.y, cross: "x", cSize: "w" },
      { axis: "y", sign:  1, wallEdge: offsetY + roomH, bEdge: br.y + br.h, cross: "x", cSize: "w" },
      { axis: "x", sign: -1, wallEdge: offsetX, bEdge: br.x, cross: "y", cSize: "h" },
      { axis: "x", sign:  1, wallEdge: offsetX + roomW, bEdge: br.x + br.w, cross: "y", cSize: "h" }
    ];
    for (var dd = 0; dd < wdirs.length; dd++) {
      var wd = wdirs[dd];
      var dist = wd.sign > 0 ? wd.wallEdge - wd.bEdge : wd.bEdge - wd.wallEdge;
      if (dist < 0.5) continue;
      var isBlocked = false;
      for (var m = 0; m < blockRects.length; m++) {
        if (m === k) continue;
        var ob = blockRects[m];
        var cOv = Math.min(br[wd.cross] + br[wd.cSize], ob[wd.cross] + ob[wd.cSize])
                - Math.max(br[wd.cross], ob[wd.cross]);
        if (cOv <= 0.5) continue;
        if (wd.sign > 0) {
          var oStart = wd.axis === "y" ? ob.y : ob.x;
          if (oStart >= wd.bEdge - 0.5 && oStart < wd.wallEdge) { isBlocked = true; break; }
        } else {
          var oEnd = wd.axis === "y" ? ob.y + ob.h : ob.x + ob.w;
          if (oEnd <= wd.bEdge + 0.5 && oEnd > wd.wallEdge) { isBlocked = true; break; }
        }
      }
      if (isBlocked) continue;
      var dcm = Math.round(dist / scale);
      var tx, ty;
      if (wd.axis === "y") {
        tx = br.x + br.w / 2;
        ty = wd.sign > 0 ? wd.bEdge + dist / 2 : wd.wallEdge + dist / 2;
      } else {
        tx = wd.sign > 0 ? wd.bEdge + dist / 2 : wd.wallEdge + dist / 2;
        ty = br.y + br.h / 2;
      }
      elements.push({ z: 7, s: '<text x="' + tx.toFixed(1) + '" y="' + (ty + labelFontSize * 0.35).toFixed(1) +
        '" text-anchor="middle" fill="' + wallColor + '" font-size="' + labelFontSize + '" font-family="monospace">' + dcm + '</text>' });
    }
  }

  // Bottom caption: desks + scoring (z=10)
  var sc = computePatternScoring(p);
  var cartFs = Math.max(6, Math.min(9, roomW * 0.06));
  var cartY = offsetY + roomH + cartFs + 2;
  var scoreBlue = "#5090c0";
  // Line 1: desk count + m²/desk
  var line1 = sc.nDesks + " desks";
  if (sc.nDesks > 0) line1 += " \u00b7 " + sc.m2pp.toFixed(1) + " m\u00b2/d";
  elements.push({ z: 10, s: '<text x="' + (offsetX + roomW / 2) + '" y="' + cartY +
    '" text-anchor="middle" fill="' + scoreBlue + '" font-size="' + cartFs + '" font-family="monospace">' +
    line1 + '</text>' });
  // Line 2: min passage
  if (sc.nDesks > 0) {
    elements.push({ z: 10, s: '<text x="' + (offsetX + roomW / 2) + '" y="' + (cartY + cartFs + 2) +
      '" text-anchor="middle" fill="' + scoreBlue + '" font-size="' + cartFs + '" font-family="monospace">' +
      'min passage ' + sc.minPassageCm + ' cm</text>' });
  }

  // Pattern name centered at top (z=10)
  var stdLabel = getStdLabel(p.standard);
  var titleFontSize = Math.max(6, Math.min(12, roomW * 0.06));
  elements.push({ z: 10, s: '<text x="' + (offsetX + roomW / 2) + '" y="' + (offsetY - 14) +
    '" text-anchor="middle" fill="' + COLOR_GAP_LABEL + '" font-size="' + titleFontSize +
    '" font-family="monospace">' + (p.name || "") + ' \u00b7 ' + stdLabel + '</text>' });

  // Restore BLOCK_DEFS
  BLOCK_DEFS = savedDefs;

  // Sort by z and assemble
  elements.sort(function(a, b) { return a.z - b.z; });
  return elements.map(function(e) { return e.s; }).join("\n");
}

function applyMatrixViewBox() {
  var svg = document.getElementById("matrixSvg");
  svg.setAttribute("viewBox", matrixViewBox.x + " " + matrixViewBox.y + " " + matrixViewBox.w + " " + matrixViewBox.h);
  updateMatrixRulers();
}

function updateMatrixRulers() {
  var m = matrixMeta;
  if (!m.widths.length) return;
  var container = document.getElementById("matrixContainer");
  var svgEl = document.getElementById("matrixSvg");
  var rect = svgEl.getBoundingClientRect();
  if (rect.width < 1) return;
  var scaleX = rect.width / matrixViewBox.w;
  var scaleY = rect.height / matrixViewBox.h;
  function svgToScreenX(sx) { return (sx - matrixViewBox.x) * scaleX; }
  function svgToScreenY(sy) { return (sy - matrixViewBox.y) * scaleY; }
  var baseFontSize = Math.max(10, Math.min(16, 15 * scaleX));

  // Ruler top (widths)
  var topEl = document.getElementById("matrixRulerTop");
  var topHtml = "";
  for (var c = 0; c < m.widths.length; c++) {
    var sx = svgToScreenX(m.colXs[c]);
    topHtml += '<span class="matrix-ruler-label" style="left:' + sx.toFixed(0) +
      'px;bottom:4px;transform:translateX(-50%);font-size:' + baseFontSize.toFixed(0) + 'px;">' +
      m.widths[c] + '</span>';
  }
  topEl.innerHTML = topHtml;

  // Ruler left (depths)
  var leftEl = document.getElementById("matrixRulerLeft");
  var leftHtml = "";
  for (var r = 0; r < m.depths.length; r++) {
    var sy = svgToScreenY(m.rowYs[r]) - 28;
    leftHtml += '<span class="matrix-ruler-label" style="top:' + sy.toFixed(0) +
      'px;right:6px;transform:translateY(-50%);font-size:' + baseFontSize.toFixed(0) + 'px;">' +
      m.depths[r] + '</span>';
  }
  leftEl.innerHTML = leftHtml;

  // Corner
  document.getElementById("matrixRulerCorner").innerHTML =
    '<span style="font-size:8px;color:var(--text-dim);">cm</span>';
}

function renderMatrixView() {
  var filtered = getFilteredPatterns();
  var svg = document.getElementById("matrixSvg");
  document.getElementById("catCount").textContent = filtered.length + " pattern(s)";

  if (filtered.length === 0) {
    svg.innerHTML = '<text x="50" y="40" fill="#6e6a62" font-size="12" font-family="monospace">No patterns.</text>';
    return;
  }

  // Collect distinct widths and depths, sorted
  var widthSet = {};
  var depthSet = {};
  filtered.forEach(function(p) {
    var w = p.room_width_cm || 0;
    var d = p.room_depth_cm || 0;
    widthSet[w] = true;
    depthSet[d] = true;
  });
  var widths = Object.keys(widthSet).map(Number).sort(function(a, b) { return a - b; });
  var depths = Object.keys(depthSet).map(Number).sort(function(a, b) { return a - b; });

  // Index for quick lookup
  var widthIdx = {};
  widths.forEach(function(w, i) { widthIdx[w] = i; });
  var depthIdx = {};
  depths.forEach(function(d, i) { depthIdx[d] = i; });

  // Build the matrix (pattern array per cell)
  var matrix = [];
  for (var r = 0; r < depths.length; r++) {
    matrix[r] = [];
    for (var c = 0; c < widths.length; c++) {
      matrix[r][c] = [];
    }
  }
  filtered.forEach(function(p) {
    var c = widthIdx[p.room_width_cm || 0];
    var r = depthIdx[p.room_depth_cm || 0];
    matrix[r][c].push(p);
  });

  // Grid dimensions
  var CELL_SCALE = 0.5;      // same scale as editor (SCALE=0.5)
  var CELL_PAD = 20;          // padding around each room
  var CELL_GAP = 8;           // spacing between patterns in the same cell
  var LABEL_W = 60;           // space for depth labels (left)
  var LABEL_H = 30;           // space for width labels (top)
  var MARGIN = 20;

  // Size of each cell: if multiple patterns, stack them horizontally
  var colWidths = widths.map(function(w, ci) {
    var maxCount = 1;
    for (var ri = 0; ri < depths.length; ri++) {
      if (matrix[ri][ci].length > maxCount) maxCount = matrix[ri][ci].length;
    }
    return maxCount * (w * CELL_SCALE) + (maxCount - 1) * CELL_GAP + CELL_PAD * 2;
  });
  var CARTOUCHE_H = 24;  // space for 2 scoring lines below the room
  var rowHeights = depths.map(function(d) { return d * CELL_SCALE + CELL_PAD * 2 + CARTOUCHE_H; });

  var totalW = MARGIN + LABEL_W + colWidths.reduce(function(a, b) { return a + b; }, 0) + MARGIN;
  var totalH = MARGIN + LABEL_H + rowHeights.reduce(function(a, b) { return a + b; }, 0) + MARGIN;

  // Store positions for HTML rulers
  var colXs = [];
  var cx = MARGIN + LABEL_W;
  for (var c = 0; c < widths.length; c++) {
    colXs.push(cx + colWidths[c] / 2);
    cx += colWidths[c];
  }
  var rowYs = [];
  var cy = MARGIN + LABEL_H;
  for (var r = 0; r < depths.length; r++) {
    rowYs.push(cy + rowHeights[r] / 2);
    cy += rowHeights[r];
  }
  matrixMeta = {
    widths: widths, depths: depths,
    colXs: colXs, rowYs: rowYs,
    colWidths: colWidths, rowHeights: rowHeights,
    labelW: LABEL_W, labelH: LABEL_H, margin: MARGIN,
  };

  var parts = [];
  // Axis labels are in HTML rulers (not in the SVG)

  // Cells
  cy = MARGIN + LABEL_H;
  for (var r = 0; r < depths.length; r++) {
    cx = MARGIN + LABEL_W;
    for (var c = 0; c < widths.length; c++) {
      // Cell border + clip to prevent overflow into adjacent cells
      var cellId = 'mc_' + r + '_' + c;
      parts.push('<clipPath id="' + cellId + '"><rect x="' + cx + '" y="' + cy +
        '" width="' + colWidths[c] + '" height="' + rowHeights[r] + '"/></clipPath>');
      parts.push('<rect x="' + cx + '" y="' + cy +
        '" width="' + colWidths[c] + '" height="' + rowHeights[r] +
        '" class="matrix-cell-border"/>');

      var patterns = matrix[r][c];
      if (patterns.length > 0) {
        var pieceW = widths[c] * CELL_SCALE;
        var pieceH = depths[r] * CELL_SCALE;
        parts.push('<g clip-path="url(#' + cellId + ')">');
        for (var pi = 0; pi < patterns.length; pi++) {
          var pieceX = cx + CELL_PAD + pi * (pieceW + CELL_GAP);
          var pieceY = cy + CELL_PAD;
          parts.push(renderPatternMiniSvg(patterns[pi], CELL_SCALE, pieceX, pieceY));
          // Transparent clickable zone to open in editor
          parts.push('<rect x="' + pieceX + '" y="' + pieceY +
            '" width="' + pieceW + '" height="' + pieceH +
            '" fill="transparent" style="cursor:pointer;" data-matrix-pattern="' +
            (patterns[pi].name || "") + '"/>');
        }
        parts.push('</g>');
      } else {
        parts.push('<text x="' + (cx + colWidths[c] / 2) + '" y="' + (cy + rowHeights[r] / 2 + 3) +
          '" text-anchor="middle" fill="#2a2826" font-size="10" font-family="monospace">\u2014</text>');
      }

      cx += colWidths[c];
    }
    cy += rowHeights[r];
  }

  // Initial viewBox = show everything
  matrixViewBox = { x: 0, y: 0, w: totalW, h: totalH };
  svg.innerHTML = parts.join("\n");
  applyMatrixViewBox();

  // Click on a room = open in editor
  svg.querySelectorAll("[data-matrix-pattern]").forEach(function(el) {
    el.addEventListener("click", function(e) {
      e.stopPropagation();
      var name = el.dataset.matrixPattern;
      if (!name) return;
      document.querySelector('.sub-tab-btn[data-subtab="catEditor"]').click();
      loadPattern(name);
    });
  });
}

function matrixZoom(e) {
  e.preventDefault();
  var svg = document.getElementById("matrixSvg");
  var rect = svg.getBoundingClientRect();
  var mx = (e.clientX - rect.left) / rect.width;
  var my = (e.clientY - rect.top) / rect.height;
  var factor = e.deltaY > 0 ? 1.15 : 0.87;
  var newW = matrixViewBox.w * factor;
  var newH = matrixViewBox.h * factor;
  matrixViewBox.x += (matrixViewBox.w - newW) * mx;
  matrixViewBox.y += (matrixViewBox.h - newH) * my;
  matrixViewBox.w = newW;
  matrixViewBox.h = newH;
  applyMatrixViewBox();
}

function matrixZoomBy(factor) {
  var svg = document.getElementById("matrixSvg");
  var newW = matrixViewBox.w * factor;
  var newH = matrixViewBox.h * factor;
  matrixViewBox.x += (matrixViewBox.w - newW) / 2;
  matrixViewBox.y += (matrixViewBox.h - newH) / 2;
  matrixViewBox.w = newW;
  matrixViewBox.h = newH;
  applyMatrixViewBox();
}

function matrixZoomFit() {
  // Recalculate viewBox to show everything
  renderMatrixView();
}

function initMatrixPanZoom() {
  var container = document.getElementById("matrixContainer");
  var svg = document.getElementById("matrixSvg");

  // Block pinch/wheel on catalogue grid
  container.addEventListener("wheel", function(e) { e.preventDefault(); }, { passive: false });

  svg.addEventListener("mousedown", function(e) {
    if (e.target.closest("[data-matrix-pattern]")) return;
    if (e.button !== 0) return;
    // Shift+drag = zoom rectangle
    if (zoomSelStart(e, svg, matrixViewBox, function() {
      applyMatrixViewBox();
    })) return;
    matrixPanning = true;
    matrixPanStart = { x: e.clientX, y: e.clientY };
    svg.classList.add("panning");
    e.preventDefault();
  });

  document.addEventListener("mousemove", function(e) {
    if (zoomSel.active && zoomSel.svg === svg) { zoomSelMove(e); return; }
    if (!matrixPanning) return;
    var svgEl = document.getElementById("matrixSvg");
    var rect = svgEl.getBoundingClientRect();
    var dx = e.clientX - matrixPanStart.x;
    var dy = e.clientY - matrixPanStart.y;
    matrixPanStart = { x: e.clientX, y: e.clientY };
    matrixViewBox.x -= dx * (matrixViewBox.w / rect.width);
    matrixViewBox.y -= dy * (matrixViewBox.h / rect.height);
    applyMatrixViewBox();
  });

  document.addEventListener("mouseup", function(e) {
    if (zoomSel.active && zoomSel.svg === svg) { zoomSelEnd(e); return; }
    if (matrixPanning) {
      matrixPanning = false;
      document.getElementById("matrixSvg").classList.remove("panning");
    }
  });
}
