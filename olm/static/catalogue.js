"use strict";
// ========== CATALOGUE ==========

// Breathing ratio for card miniature viewBox (fraction of largest dimension)
var MINI_VIEWBOX_BREATH = 0.04;

let catalogueData = [];


// --- Event delegation (P1.4) ---
// Single click handler on #catalogueGrid dispatches:
//   delete > warning > miniature (open) > card body (enlarge/shrink).
// Session-life: bound once, never re-bound.
var _catDelegationWired = false;
function _wireCatDelegation() {
  if (_catDelegationWired) return;
  _catDelegationWired = true;

  var grid = document.getElementById("catalogueGrid");
  if (grid) {
    grid.addEventListener("click", function(e) {
      // 1. Delete button
      var delBtn = e.target.closest(".card-delete");
      if (delBtn) {
        e.stopPropagation();
        var name = delBtn.dataset.delName;
        if (!name) return;
        confirmModal("Delete \"" + name + "\" from catalogue?")
          .then(function(ok) {
            if (!ok) return;
            fetch("/api/patterns/" + encodeURIComponent(name),
              { method: "DELETE" })
              .then(function(resp) {
                if (!resp.ok) throw new Error("Delete failed");
                loadCatalogue();
              })
              .catch(function(err) {
                setStatus("Delete error: " + err.message);
              });
          });
        return;
      }
      // 2. Overflow badge diagnostic (dev-mode only, D-240)
      var warn = e.target.closest(".card-warning");
      if (warn && APP_CONFIG.dev_mode) {
        e.stopPropagation();
        var card = warn.closest(".catalogue-card");
        if (card) {
          var pName = card.dataset.patternName;
          var pat = catalogueData.find(function(p) {
            return p.name === pName;
          });
          if (pat) OLM_DIAGS.run("pattern.footprint", pat);
        }
        return;
      }
      // 3. Click on miniature SVG → open pattern in editor
      var mini = e.target.closest(".card-mini-svg");
      if (mini) {
        var card = mini.closest(".catalogue-card");
        if (card) {
          var name = card.dataset.patternName;
          if (name) {
            document.querySelector(
              '.sub-tab-btn[data-subtab="catEditor"]').click();
            loadPattern(name);
          }
        }
        return;
      }
      // 4. Click elsewhere on card → toggle enlarge in-place
      var card = e.target.closest(".catalogue-card");
      if (card) {
        // Collapse any other enlarged card first
        var prev = grid.querySelector(".catalogue-card.card-enlarged");
        if (prev && prev !== card) prev.classList.remove("card-enlarged");
        card.classList.toggle("card-enlarged");
      }
    });
  }
}

async function loadCatalogue() {
  try {
    var resp = await fetch("/api/patterns");
    if (!resp.ok) throw new Error(await resp.text());
    var data = await resp.json();
    catalogueData = data.patterns || [];
    // First-launch banner: show when empty + default available
    var bannerEl = document.getElementById("catDefaultBanner");
    if (bannerEl) bannerEl.style.display = data.default_available ? "block" : "none";
    // Save-as-default button: visible only in --dev mode
    var saveDefEl = document.getElementById("btnCatSaveAsDefault");
    if (saveDefEl && typeof APP_CONFIG !== "undefined") {
      saveDefEl.style.display = APP_CONFIG.dev_mode ? "block" : "none";
    }
    try {
      renderCatalogue();
    } catch (renderErr) {
      console.error("renderCatalogue error:", renderErr);
      document.getElementById("catalogueGrid").innerHTML =
        '<div style="color:var(--bad);padding:24px;">Render error: ' + renderErr.message + '</div>';
    }
    if (window.peUpdateNavInfo) window.peUpdateNavInfo();
  } catch (err) {
    console.error("loadCatalogue error:", err);
    document.getElementById("catalogueGrid").innerHTML =
      '<div style="color:var(--bad);padding:24px;">Error: ' + err.message + '</div>';
  }
}

// Compute the drawing extent of a pattern in cm (footprint + outward door
// arcs, with an empty-pattern fallback to room dimensions). The breathing
// margin and the uniform square framing are applied globally in
// renderCatalogue so that a desk renders at the same pixel size on every card.
function _patternExtent(p) {
  var fp = computePatternFootprint(p);
  var roomW = p.room_width_cm || 300;
  var roomH = p.room_depth_cm || 400;
  // Fallback: empty pattern → use room dimensions
  var xMin = fp.xMin, xMax = fp.xMax, yMin = fp.yMin, yMax = fp.yMax;
  if (xMin === 0 && xMax === 0 && yMin === 0 && yMax === 0) {
    xMin = 0; yMin = 0; xMax = roomW; yMax = roomH;
  }
  // Extend for outward door arcs (radius = opening width, extends beyond room wall)
  (p.room_openings || []).forEach(function(o) {
    if (o.opens_inward || !o.has_door) return;
    var arcR = o.width_cm || 0;
    if (o.face === "north") { yMin = Math.min(yMin, -arcR); }
    else if (o.face === "south") { yMax = Math.max(yMax, roomH + arcR); }
    else if (o.face === "west") { xMin = Math.min(xMin, -arcR); }
    else if (o.face === "east") { xMax = Math.max(xMax, roomW + arcR); }
  });
  return { xMin: xMin, yMin: yMin, xMax: xMax, yMax: yMax };
}

function renderCatalogue() {
  var grid = document.getElementById("catalogueGrid");
  var filtered = getFilteredPatterns();

  // Sort: depth ascending, width ascending, then name ascending
  filtered.sort(function(a, b) {
    var da = (a.room_depth_cm || 0) - (b.room_depth_cm || 0);
    if (da !== 0) return da;
    var wa = (a.room_width_cm || 0) - (b.room_width_cm || 0);
    if (wa !== 0) return wa;
    return (a.name || "").localeCompare(b.name || "", undefined, { numeric: true });
  });

  var countEl = document.getElementById("catCount");
  if (countEl) {
    var total = catalogueData.length;
    countEl.textContent = (filtered.length === total)
      ? total + " pattern(s)"
      : filtered.length + " / " + total + " pattern(s)";
  }

  if (filtered.length === 0) {
    grid.innerHTML = '<div style="color:var(--text-dim);font-size:12px;' +
      'padding:24px;">No patterns.</div>';
    return;
  }

  // Uniform miniature scale: one square sized to the largest pattern extent,
  // so every desk renders at the same pixel size across all cards. Small
  // patterns sit centered with margin; the largest fills the square.
  var extByPattern = new Map();
  var maxExtentCm = 1;
  filtered.forEach(function(p) {
    var e = _patternExtent(p);
    extByPattern.set(p, e);
    maxExtentCm = Math.max(maxExtentCm, e.xMax - e.xMin, e.yMax - e.yMin);
  });
  var miniSideCm = maxExtentCm * (1 + MINI_VIEWBOX_BREATH * 2);

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

      var fitClass = p.fit_class || "ok";
      var cardClass = "catalogue-card" +
        (fitClass === "reject" ? " card-overflow" :
         fitClass === "tolere" ? " card-tolere" : "");
      html += '<div class="' + cardClass + '" data-pattern-name="' +
        (p.name || "") + '">';
      html += '<button class="card-delete" data-del-name="' +
        (p.name || "") + '" title="Delete">&times;</button>';

      // Miniature SVG: uniform square viewBox, pattern centered (noLabels)
      var ext = extByPattern.get(p);
      var offX = miniSideCm / 2 - (ext.xMin + ext.xMax) / 2;
      var offY = miniSideCm / 2 - (ext.yMin + ext.yMax) / 2;
      var svgContent = renderPatternMiniSvg(
        p, 1, offX, offY, { noLabels: true }
      );
      html += '<div class="card-mini-svg"><svg viewBox="0 0 ' +
        miniSideCm + ' ' + miniSideCm +
        '" preserveAspectRatio="xMidYMid meet">' +
        svgContent + '</svg></div>';

      html += '<div class="card-title">' + (p.name || "Unnamed") + '</div>';
      html += '<div class="card-info">' + nDesks + ' desks · ' +
        nBlocks + ' blocks · ' + std + ' · ' + w + 'x' + d + '</div>';
      var sc = computePatternScoring(p);
      if (sc.nDesks > 0) {
        html += '<div class="card-info">' + scoringHtml(sc) + '</div>';
      }
      if (fitClass === "reject")
        html += '<div class="card-warning">Overflow</div>';
      else if (fitClass === "tolere")
        html += '<div class="card-warning card-warning-tolere">Tight</div>';
      html += '</div>';
    });
    html += '</div></div>';
  });
  grid.innerHTML = html;

  // Event delegation handles card interactions (P1.4)
  _wireCatDelegation();
}

function getFilteredPatterns() {
  var stdFilter = getCurrentStandard();
  var minW = parseInt(document.getElementById("catFilterMinW").value) || 0;
  var maxW = parseInt(document.getElementById("catFilterMaxW").value) || Infinity;
  var minD = parseInt(document.getElementById("catFilterMinD").value) || 0;
  var maxD = parseInt(document.getElementById("catFilterMaxD").value) || Infinity;
  var minDesks = parseInt(document.getElementById("catFilterMinDesks").value) || 0;
  var maxDesks = parseInt(document.getElementById("catFilterMaxDesks").value) || Infinity;
  return catalogueData.filter(function(p) {
    if (stdFilter && p.standard !== stdFilter) return false;
    var w = p.room_width_cm || 0;
    var d = p.room_depth_cm || 0;
    if (w < minW || w > maxW) return false;
    if (d < minD || d > maxD) return false;
    if (minDesks > 0 || maxDesks < Infinity) {
      var nd = 0;
      (p.rows || []).forEach(function(r) {
        (r.blocks || []).forEach(function(b) { nd += countDesksInBlock(b.type) || 0; });
      });
      if (nd < minDesks || nd > maxDesks) return false;
    }
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

function renderPatternMiniSvg(p, scale, offsetX, offsetY, opts) {
  // Rendering identical to editor: z-order, circulation zones, chairs, screens, distances
  // opts.noLabels: suppress text elements (dimension labels, scoring, pattern name)
  // Switch BLOCK_DEFS to the pattern's standard for correct dimensions
  var _noLabels = opts && opts.noLabels;
  var savedDefs = BLOCK_DEFS;
  if (p.standard && BLOCK_DEFS_BY_STD[p.standard]) BLOCK_DEFS = BLOCK_DEFS_BY_STD[p.standard];
  var elements = [];
  var roomWcm = p.room_width_cm || 300;
  var roomHcm = p.room_depth_cm || 400;
  var roomW = roomWcm * scale;
  var roomH = roomHcm * scale;

  // Room background (z=0.05) — slightly lighter than block zones for contrast
  elements.push({ z: 0.05, s: '<rect x="' + offsetX + '" y="' + offsetY +
    '" width="' + roomW + '" height="' + roomH +
    '" fill="#1a1a1a" stroke="#4a4640" stroke-width="1"/>' });

  // Room dimension labels (z=10)
  if (!_noLabels) {
    elements.push({ z: 10, s: '<text x="' + (offsetX + roomW / 2) + '" y="' + (offsetY - 3) +
      '" text-anchor="middle" fill="' + COLOR_RULER + '" font-size="7" font-family="monospace">' +
      roomWcm + ' cm</text>' });
    elements.push({ z: 10, s: '<text x="' + (offsetX - 3) + '" y="' + (offsetY + roomH / 2) +
      '" text-anchor="middle" fill="' + COLOR_RULER + '" font-size="7" font-family="monospace"' +
      ' transform="rotate(-90,' + (offsetX - 3) + ',' + (offsetY + roomH / 2) + ')">' +
      roomHcm + ' cm</text>' });
  }

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
      blockRects.push({ x: bx, y: by, w: bw, h: bh, faces: f });

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

      // Lock nœud markers (D-221 / D-226). Show a small rope-knot on each
      // face where a stick is set AND the block actually touches the wall.
      var bSticks = b.sticks || [];
      if (bSticks.length > 0) {
        var isOrtho = (b.type === "BLOCK_2_ORTHO_R" || b.type === "BLOCK_2_ORTHO_L");
        function _zoneCm(faceObj) {
          if (isOrtho || !faceObj) return 0;
          return (faceObj.non_superposable_cm || 0) + (faceObj.candidate_cm || 0);
        }
        var xBlockCm = (bx - offsetX) / scale;
        var yBlockCm = (by - offsetY) / scale;
        var zN = _zoneCm(f.north);
        var zS = _zoneCm(f.south);
        var zW = _zoneCm(f.west);
        var zE = _zoneCm(f.east);
        var outerN = by - zN * scale;
        var outerS = by + bh + zS * scale;
        var outerW = bx - zW * scale;
        var outerE = bx + bw + zE * scale;
        var outerCx = (outerW + outerE) / 2;
        var outerCy = (outerN + outerS) / 2;
        // Fixed knot size in SVG units (mini view); editor uses 18*zf.
        var knotSize = 10;
        var knotInset = 4;
        var ksc = knotSize / 14;
        // Center the knot ON the wall so one loop sits on the desk and
        // the other loop sits outside the room.
        var knotFaces = [
          { face: "N", touches: (yBlockCm - zN === 0),
            cx: outerCx, cy: outerN, rot: 0 },
          { face: "S", touches: (yBlockCm + g.ns + zS === roomHcm),
            cx: outerCx, cy: outerS, rot: 0 },
          { face: "W", touches: (xBlockCm - zW === 0),
            cx: outerW, cy: outerCy, rot: 90 },
          { face: "E", touches: (xBlockCm + g.eo + zE === roomWcm),
            cx: outerE, cy: outerCy, rot: 90 },
        ];
        for (var kf = 0; kf < knotFaces.length; kf++) {
          var kk = knotFaces[kf];
          if (!kk.touches) continue;
          if (bSticks.indexOf(kk.face) < 0) continue;
          var kx = kk.cx - knotSize / 2;
          var ky = kk.cy - knotSize / 2;
          elements.push({ z: 10, s:
            '<g transform="translate(' + kx + ',' + ky + ') scale(' + ksc +
            ') rotate(' + kk.rot + ' 7 7)" pointer-events="none">' +
            '<rect x="-2" y="-1" width="18" height="19" rx="3" fill="rgba(0,0,0,0.6)"/>' +
            '<path d="M3,6 V4 a4,4 0 0,1 8,0 V6" fill="none" stroke="#c8a800"' +
            ' stroke-width="1.8" stroke-linecap="round"/>' +
            '<rect x="0" y="6" width="14" height="10" rx="2"' +
            ' fill="rgba(0,0,0,0.5)" stroke="#c8a800" stroke-width="0.7"/>' +
            '<circle cx="7" cy="11" r="1.6" fill="#c8a800"/>' +
            '</g>' });
        }
      }

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
      // D-233: A's east face vs B's west face
      var rcol = distanceConformity(gcm,
        getFacingFace(a.faces, "east"),
        getFacingFace(nearestRight.faces, "west"));
      elements.push({ z: 7, s: '<text x="' + lx.toFixed(1) + '" y="' + ((ovT + ovB) / 2 + labelFontSize * 0.35).toFixed(1) +
        '" text-anchor="middle" fill="' + rcol + '" font-size="' + labelFontSize + '" font-weight="bold" font-family="monospace">' + gcm + '</text>' });
    }
    if (nearestBelow) {
      var gcm2 = Math.round(nearestBelowGap / scale);
      var ovL = Math.max(a.x, nearestBelow.x);
      var ovR = Math.min(a.x + a.w, nearestBelow.x + nearestBelow.w);
      // D-233: A's south face vs B's north face
      var bcol = distanceConformity(gcm2,
        getFacingFace(a.faces, "south"),
        getFacingFace(nearestBelow.faces, "north"));
      elements.push({ z: 7, s: '<text x="' + ((ovL + ovR) / 2).toFixed(1) + '" y="' + (a.y + a.h + nearestBelowGap / 2 + labelFontSize * 0.35).toFixed(1) +
        '" text-anchor="middle" fill="' + bcol + '" font-size="' + labelFontSize + '" font-weight="bold" font-family="monospace">' + gcm2 + '</text>' });
    }
  }

  // Block-to-wall distances (z=7) — Rule V-02:
  // For each block x each direction, show distance to wall UNLESS
  // another block (desk overlap on perpendicular axis) is between this
  // block and the wall, or the distance is zero.
  for (var k = 0; k < blockRects.length; k++) {
    var br = blockRects[k];
    var wdirs = [
      { axis: "y", sign: -1, wallEdge: offsetY, bEdge: br.y, cross: "x", cSize: "w", face: "north" },
      { axis: "y", sign:  1, wallEdge: offsetY + roomH, bEdge: br.y + br.h, cross: "x", cSize: "w", face: "south" },
      { axis: "x", sign: -1, wallEdge: offsetX, bEdge: br.x, cross: "y", cSize: "h", face: "west" },
      { axis: "x", sign:  1, wallEdge: offsetX + roomW, bEdge: br.x + br.w, cross: "y", cSize: "h", face: "east" }
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
      // D-233: block face vs wall (null = wall)
      var wcol = distanceConformity(dcm,
        getFacingFace(br.faces, wd.face), null);
      elements.push({ z: 7, s: '<text x="' + tx.toFixed(1) + '" y="' + (ty + labelFontSize * 0.35).toFixed(1) +
        '" text-anchor="middle" fill="' + wcol + '" font-size="' + labelFontSize + '" font-family="monospace">' + dcm + '</text>' });
    }
  }

  // Door exclusion zone rectangles (D-208)
  drawDoorExclusionRects(
    elements, p.room_openings, p.standard,
    offsetX, offsetY, roomW, roomH, scale,
  );

  // Bottom caption: desks + scoring (z=10)
  if (!_noLabels) {
    var sc = computePatternScoring(p);
    var cartFs = Math.max(6, Math.min(9, roomW * 0.06));
    var cartY = offsetY + roomH + cartFs + 2;
    var scoreBlue = "#5090c0";
    var line1 = sc.nDesks + " desks";
    if (sc.nDesks > 0) line1 += " \u00b7 " + sc.m2pp.toFixed(1) + " m\u00b2/d";
    elements.push({ z: 10, s: '<text x="' + (offsetX + roomW / 2) + '" y="' + cartY +
      '" text-anchor="middle" fill="' + scoreBlue + '" font-size="' + cartFs +
      '" font-family="monospace">' + line1 + '</text>' });
    if (sc.nDesks > 0) {
      elements.push({ z: 10, s: '<text x="' + (offsetX + roomW / 2) + '" y="' +
        (cartY + cartFs + 2) + '" text-anchor="middle" fill="' + scoreBlue +
        '" font-size="' + cartFs + '" font-family="monospace">' +
        'min passage ' + sc.minPassageCm + ' cm</text>' });
    }
  }

  // Pattern name centered at top (z=10)
  if (!_noLabels) {
    var stdLabel = getStdLabel(p.standard);
    var titleFontSize = Math.max(6, Math.min(12, roomW * 0.06));
    elements.push({ z: 10, s: '<text x="' + (offsetX + roomW / 2) + '" y="' + (offsetY - 14) +
      '" text-anchor="middle" fill="' + COLOR_GAP_LABEL + '" font-size="' + titleFontSize +
      '" font-family="monospace">' + (p.name || "") + ' \u00b7 ' + stdLabel + '</text>' });
  }

  // Restore BLOCK_DEFS
  BLOCK_DEFS = savedDefs;

  // Sort by z and assemble
  elements.sort(function(a, b) { return a.z - b.z; });
  return elements.map(function(e) { return e.s; }).join("\n");
}

// --- Pattern Editor navigation (Prev / Next, width then depth ascending) ---

function _peSortedPatternsForStandard() {
  var std = typeof getCurrentStandard === "function" ? getCurrentStandard() : "";
  var list = (catalogueData || []).filter(function(p) {
    return !std || p.standard === std;
  });
  list.sort(function(a, b) {
    var aw = a.room_width_cm || 0;
    var bw = b.room_width_cm || 0;
    if (aw !== bw) return aw - bw;
    var ad = a.room_depth_cm || 0;
    var bd = b.room_depth_cm || 0;
    if (ad !== bd) return ad - bd;
    return (a.name || "").localeCompare(b.name || "");
  });
  return list;
}

window.peUpdateNavInfo = function() {
  var info = document.getElementById("peNavInfo");
  var prev = document.getElementById("peBtnPrev");
  var next = document.getElementById("peBtnNext");
  if (!info || !prev || !next) return;
  var list = _peSortedPatternsForStandard();
  var name = (typeof state !== "undefined" && state.name) ? state.name : "";
  var idx = list.findIndex(function(p) { return p.name === name; });
  var total = list.length;
  if (total === 0) {
    info.textContent = "0 / 0";
    prev.disabled = true;
    next.disabled = true;
    return;
  }
  if (idx < 0) {
    info.textContent = "- / " + total;
  } else {
    info.textContent = (idx + 1) + " / " + total;
  }
  prev.disabled = (total < 2);
  next.disabled = (total < 2);
};

window.peNavigate = function(direction) {
  var list = _peSortedPatternsForStandard();
  if (list.length === 0) return;
  var name = (typeof state !== "undefined" && state.name) ? state.name : "";
  var idx = list.findIndex(function(p) { return p.name === name; });
  if (idx < 0) idx = 0;
  else idx = (idx + direction + list.length) % list.length;
  if (typeof loadPattern === "function") loadPattern(list[idx].name);
};
