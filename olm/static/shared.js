"use strict";
async function loadBlockDefs() {
  try {
    var resp = await fetch("/api/blocks?standard=" + encodeURIComponent(state.standard));
    if (resp.ok) {
      var data = await resp.json();
      BLOCK_DEFS = data.blocks || data || {};
      BLOCK_DEFS_BY_STD[state.standard] = BLOCK_DEFS;
    }
  } catch (e) {
    setStatus("Server unavailable - basic rendering (fallback).");
  }
}

async function loadAllBlockDefs() {
  var stds = getStandards();
  for (var i = 0; i < stds.length; i++) {
    try {
      var resp = await fetch("/api/blocks?standard=" + encodeURIComponent(stds[i]));
      if (resp.ok) {
        var data = await resp.json();
        BLOCK_DEFS_BY_STD[stds[i]] = data.blocks || data || {};
      }
    } catch (e) { /* ignore */ }
  }
}

// ========== CIRCULATION & SCORES ==========

function computeCirculationInfo() {
  // Rasterize the room, BFS from door, traffic + passage width per cell
  // In circulation mode: only block footprints are occupied (not fixed zones)
  var nd = totalDesks();
  if (nd === 0) return null;
  var cellCm = GRID_STEP_CM;
  var cols = Math.floor(state.room_width_cm / cellCm);
  var rowsN = Math.floor(state.room_depth_cm / cellCm);
  if (cols <= 0 || rowsN <= 0) return null;

  // 0 = free, 1 = occupied (block), 2 = exclusion
  var grid = [];
  for (var r = 0; r < rowsN; r++) {
    grid[r] = [];
    for (var c = 0; c < cols; c++) grid[r][c] = 0;
  }

  // Exclusions
  state.room_exclusions.forEach(function(z) {
    var c0 = Math.floor(z.x_cm / cellCm), r0 = Math.floor(z.y_cm / cellCm);
    var c1 = Math.ceil((z.x_cm + z.width_cm) / cellCm), r1 = Math.ceil((z.y_cm + z.depth_cm) / cellCm);
    for (var r = Math.max(0, r0); r < Math.min(rowsN, r1); r++)
      for (var c = Math.max(0, c0); c < Math.min(cols, c1); c++) grid[r][c] = 2;
  });

  // Blocks: footprint + chair setback zones as obstacles (BFS cannot traverse them)
  var deskCells = []; // {r, c, chairSide}
  var yRow = 0;
  for (var ri = 0; ri < state.rows.length; ri++) {
    var row = state.rows[ri];
    var xBlock = 0, rowMaxNS = 0;
    for (var bi = 0; bi < row.blocks.length; bi++) {
      var b = row.blocks[bi];
      var g = getEffectiveGeom(b.type, b.orientation);
      var f = g.faces;
      var offNS = b.offset_ns_cm || 0;
      if (b.gap_cm) xBlock += b.gap_cm;
      // Block footprint
      markGridRect(grid, xBlock, yRow + offNS, g.eo, g.ns, cellCm, cols, rowsN, 1);
      // Chair setback zones (non_superposable) = obstacles for circulation
      var wNS = (f.west && f.west.non_superposable_cm) || 0;
      var eNS = (f.east && f.east.non_superposable_cm) || 0;
      var nNS = (f.north && f.north.non_superposable_cm) || 0;
      var sNS = (f.south && f.south.non_superposable_cm) || 0;
      if (wNS > 0) markGridRect(grid, xBlock - wNS, yRow + offNS, wNS, g.ns, cellCm, cols, rowsN, 1);
      if (eNS > 0) markGridRect(grid, xBlock + g.eo, yRow + offNS, eNS, g.ns, cellCm, cols, rowsN, 1);
      if (nNS > 0) markGridRect(grid, xBlock, yRow + offNS - nNS, g.eo, nNS, cellCm, cols, rowsN, 1);
      if (sNS > 0) markGridRect(grid, xBlock, yRow + offNS + g.ns, g.eo, sNS, cellCm, cols, rowsN, 1);
      // Arrival point = just behind the chair (outer edge of setback zone)
      var desks = getDeskRects(b.type);
      var orient = b.orientation || 0;
      if (orient !== 0) {
        var g0 = getBlockGeom(b.type);
        desks = transformDeskRects(desks, g0.eo, g0.ns, orient);
      }
      for (var di = 0; di < desks.length; di++) {
        var d = desks[di];
        var faceKey = {N:"north",S:"south",E:"east",W:"west"}[d.chairSide];
        var faceData = f[faceKey] || {};
        var nsupCm = faceData.non_superposable_cm || 70;
        var deskCxCm = xBlock + d.x + d.w / 2;
        var deskCyCm = yRow + offNS + d.y + d.h / 2;
        // Try first just at the edge of the setback zone (perpendicular access)
        var chairR, chairC;
        if (d.chairSide === "W") {
          chairC = Math.floor((xBlock + d.x - nsupCm - 5) / cellCm);
          chairR = Math.floor(deskCyCm / cellCm);
        } else if (d.chairSide === "E") {
          chairC = Math.floor((xBlock + d.x + d.w + nsupCm + 5) / cellCm);
          chairR = Math.floor(deskCyCm / cellCm);
        } else if (d.chairSide === "N") {
          chairR = Math.floor((yRow + offNS + d.y - nsupCm - 5) / cellCm);
          chairC = Math.floor(deskCxCm / cellCm);
        } else {
          chairR = Math.floor((yRow + offNS + d.y + d.h + nsupCm + 5) / cellCm);
          chairC = Math.floor(deskCxCm / cellCm);
        }
        var fc = findNearestFreeCell(grid, chairR, chairC, cols, rowsN);
        // If not found, lateral access: arrive from an adjacent side of the setback zone
        if (!fc) {
          // Center of the setback zone (in cm)
          var zrMidX, zrMidY;
          if (d.chairSide === "W") { zrMidX = xBlock + d.x - nsupCm / 2; zrMidY = deskCyCm; }
          else if (d.chairSide === "E") { zrMidX = xBlock + d.x + d.w + nsupCm / 2; zrMidY = deskCyCm; }
          else if (d.chairSide === "N") { zrMidX = deskCxCm; zrMidY = yRow + offNS + d.y - nsupCm / 2; }
          else { zrMidX = deskCxCm; zrMidY = yRow + offNS + d.y + d.h + nsupCm / 2; }
          // Try the 4 sides just outside the setback zone, aligned on its center
          var latTries = [];
          if (d.chairSide === "W" || d.chairSide === "E") {
            // Arrive from north or south of setback zone, X-aligned on its center
            latTries.push({ r: Math.floor((deskCyCm - d.h / 2 - nsupCm - 5) / cellCm), c: Math.floor(zrMidX / cellCm) });
            latTries.push({ r: Math.floor((deskCyCm + d.h / 2 + nsupCm + 5) / cellCm), c: Math.floor(zrMidX / cellCm) });
          } else {
            latTries.push({ r: Math.floor(zrMidY / cellCm), c: Math.floor((deskCxCm - d.w / 2 - nsupCm - 5) / cellCm) });
            latTries.push({ r: Math.floor(zrMidY / cellCm), c: Math.floor((deskCxCm + d.w / 2 + nsupCm + 5) / cellCm) });
          }
          for (var lt = 0; lt < latTries.length && !fc; lt++) {
            fc = findNearestFreeCell(grid, latTries[lt].r, latTries[lt].c, cols, rowsN);
          }
        }
        if (fc) deskCells.push({ r: fc.r, c: fc.c, chairSide: d.chairSide });
      }
      xBlock += g.eo;
      if (g.ns > rowMaxNS) rowMaxNS = g.ns;
    }
    yRow += rowMaxNS;
    if (ri < state.rows.length - 1) yRow += state.row_gaps_cm[ri] || 0;
  }

  // Door cell: center of each door
  var doorCells = [];
  state.room_openings.forEach(function(o) {
    if (!o.has_door) return;
    var midCm = o.offset_cm + o.width_cm / 2;
    var dr, dc;
    if (o.face === "north") { dr = 0; dc = Math.floor(midCm / cellCm); }
    else if (o.face === "south") { dr = rowsN - 1; dc = Math.floor(midCm / cellCm); }
    else if (o.face === "west") { dr = Math.floor(midCm / cellCm); dc = 0; }
    else if (o.face === "east") { dr = Math.floor(midCm / cellCm); dc = cols - 1; }
    else return;
    dr = Math.max(0, Math.min(rowsN - 1, dr));
    dc = Math.max(0, Math.min(cols - 1, dc));
    var fc = findNearestFreeCell(grid, dr, dc, cols, rowsN);
    if (fc) doorCells.push(fc);
  });
  if (doorCells.length === 0) {
    var midC = Math.floor(cols / 2);
    var fc = findNearestFreeCell(grid, rowsN - 1, midC, cols, rowsN);
    if (fc) doorCells.push(fc);
  }

  // Distance to nearest obstacle (BFS from occupied cells and borders)
  var distToWall = [];
  for (var r = 0; r < rowsN; r++) { distToWall[r] = []; for (var c = 0; c < cols; c++) distToWall[r][c] = -1; }
  var wallQueue = [];
  var dirs8 = [[-1,0],[1,0],[0,-1],[0,1],[-1,-1],[-1,1],[1,-1],[1,1]];
  for (var r = 0; r < rowsN; r++) {
    for (var c = 0; c < cols; c++) {
      if (grid[r][c] !== 0) { distToWall[r][c] = 0; wallQueue.push({ r: r, c: c }); continue; }
      if (r === 0 || r === rowsN - 1 || c === 0 || c === cols - 1) {
        distToWall[r][c] = 0; wallQueue.push({ r: r, c: c });
      }
    }
  }
  var wHead = 0;
  while (wHead < wallQueue.length) {
    var cur = wallQueue[wHead++];
    for (var di = 0; di < 8; di++) {
      var nr = cur.r + dirs8[di][0], nc = cur.c + dirs8[di][1];
      if (nr < 0 || nr >= rowsN || nc < 0 || nc >= cols) continue;
      if (distToWall[nr][nc] >= 0) continue;
      distToWall[nr][nc] = distToWall[cur.r][cur.c] + 1;
      wallQueue.push({ r: nr, c: nc });
    }
  }

  // Dijkstra from door — low cost at corridor center, high near walls
  var dist = [], prev = [];
  for (var r = 0; r < rowsN; r++) { dist[r] = []; prev[r] = []; for (var c = 0; c < cols; c++) { dist[r][c] = -1; prev[r][c] = null; } }
  // Simple priority queue (array sorted by cost)
  var pq = [];
  doorCells.forEach(function(dc) { dist[dc.r][dc.c] = 0; pq.push({ r: dc.r, c: dc.c, cost: 0 }); });
  while (pq.length > 0) {
    // Extract min (partial sort)
    var minIdx = 0;
    for (var qi = 1; qi < pq.length; qi++) { if (pq[qi].cost < pq[minIdx].cost) minIdx = qi; }
    var cur = pq[minIdx];
    pq[minIdx] = pq[pq.length - 1]; pq.pop();
    if (cur.cost > dist[cur.r][cur.c] && dist[cur.r][cur.c] >= 0) continue;
    for (var di = 0; di < 8; di++) {
      var nr = cur.r + dirs8[di][0], nc = cur.c + dirs8[di][1];
      if (nr < 0 || nr >= rowsN || nc < 0 || nc >= cols) continue;
      if (grid[nr][nc] !== 0) continue;
      // Diagonal: verify both adjacent cells are free (no corner cutting)
      if (di >= 4) {
        if (grid[cur.r + dirs8[di][0]][cur.c] !== 0 || grid[cur.r][cur.c + dirs8[di][1]] !== 0) continue;
      }
      var dw = distToWall[nr][nc] || 0;
      var stepCost = di >= 4 ? 1.414 : 1.0; // diagonal = sqrt(2)
      var edgeCost = stepCost * 10.0 / (1 + dw * dw);
      var newCost = cur.cost + edgeCost;
      if (dist[nr][nc] < 0 || newCost < dist[nr][nc]) {
        dist[nr][nc] = newCost;
        prev[nr][nc] = { r: cur.r, c: cur.c };
        pq.push({ r: nr, c: nc, cost: newCost });
      }
    }
  }

  // Passage width: based on a grid that only marks blocks+exclusions (not setback zones)
  // because setback zones are part of the circulation space for measuring width
  var widthGrid = [];
  for (var r = 0; r < rowsN; r++) { widthGrid[r] = []; for (var c = 0; c < cols; c++) widthGrid[r][c] = 0; }
  // Mark exclusions
  state.room_exclusions.forEach(function(z) {
    var c0 = Math.floor(z.x_cm / cellCm), r0 = Math.floor(z.y_cm / cellCm);
    var c1 = Math.ceil((z.x_cm + z.width_cm) / cellCm), r1 = Math.ceil((z.y_cm + z.depth_cm) / cellCm);
    for (var r = Math.max(0, r0); r < Math.min(rowsN, r1); r++)
      for (var c = Math.max(0, c0); c < Math.min(cols, c1); c++) widthGrid[r][c] = 1;
  });
  // Mark blocks only (not setback zones)
  var yRow2 = 0;
  for (var ri = 0; ri < state.rows.length; ri++) {
    var row2 = state.rows[ri];
    var xBlock2 = 0, rowMaxNS2 = 0;
    for (var bi = 0; bi < row2.blocks.length; bi++) {
      var b2 = row2.blocks[bi];
      var g2 = getEffectiveGeom(b2.type, b2.orientation);
      var offNS2 = b2.offset_ns_cm || 0;
      if (b2.gap_cm) xBlock2 += b2.gap_cm;
      markGridRect(widthGrid, xBlock2, yRow2 + offNS2, g2.eo, g2.ns, cellCm, cols, rowsN, 1);
      xBlock2 += g2.eo;
      if (g2.ns > rowMaxNS2) rowMaxNS2 = g2.ns;
    }
    yRow2 += rowMaxNS2;
    if (ri < state.rows.length - 1) yRow2 += state.row_gaps_cm[ri] || 0;
  }
  var passWidth = [];
  for (var r = 0; r < rowsN; r++) { passWidth[r] = []; for (var c = 0; c < cols; c++) passWidth[r][c] = 0; }
  // Horizontal runs on the grid without setback zones
  for (var r = 0; r < rowsN; r++) {
    var start = -1;
    for (var c = 0; c <= cols; c++) {
      if (c < cols && widthGrid[r][c] === 0) { if (start < 0) start = c; }
      else {
        if (start >= 0) {
          var len = c - start;
          for (var k = start; k < c; k++) passWidth[r][k] = len;
          start = -1;
        }
      }
    }
  }
  // Vertical runs: min with horizontal
  for (var c = 0; c < cols; c++) {
    var start = -1;
    for (var r = 0; r <= rowsN; r++) {
      if (r < rowsN && widthGrid[r][c] === 0) { if (start < 0) start = r; }
      else {
        if (start >= 0) {
          var len = r - start;
          for (var k = start; k < r; k++) {
            if (len < passWidth[k][c] || passWidth[k][c] === 0) passWidth[k][c] = len;
          }
          start = -1;
        }
      }
    }
  }

  // Paths + traffic per edge
  // edges[r][c] = { traffic per outgoing direction, worst color }
  var traffic = [];
  for (var r = 0; r < rowsN; r++) { traffic[r] = []; for (var c = 0; c < cols; c++) traffic[r][c] = 0; }
  var passage = CURRENT_SPACING ? CURRENT_SPACING.passage_cm : 0;
  var corridor = CURRENT_SPACING ? CURRENT_SPACING.main_corridor_cm : 0;

  // Store paths for polyline rendering
  var paths = []; // [{points: [{r,c},...], worst: 0|1|2}]
  deskCells.forEach(function(dc) {
    var path = [];
    var r = dc.r, c = dc.c;
    while (r >= 0 && c >= 0 && dist[r][c] >= 0) {
      path.push({ r: r, c: c });
      traffic[r][c]++;
      var p = prev[r][c];
      if (!p) break;
      r = p.r; c = p.c;
    }
    // Worst color from door to workstation
    var worst = 0;
    for (var pi = path.length - 1; pi >= 0; pi--) {
      var pr = path[pi].r, pc = path[pi].c;
      var pw = passWidth[pr][pc] || 0;
      var widthCm = pw * cellCm;
      var cellWorst = 0;
      if (widthCm < passage) cellWorst = 2;
      else if (widthCm <= passage) cellWorst = 1;
      if (cellWorst > worst) worst = cellWorst;
    }
    paths.push({ points: path, worst: worst });
  });

  // Traffic per edge (segment between two adjacent cells)
  // Key = "r1,c1-r2,c2" (sorted), value = number of paths
  var edgeTraffic = {};
  paths.forEach(function(p) {
    for (var i = 0; i < p.points.length - 1; i++) {
      var a = p.points[i], b = p.points[i + 1];
      var key = Math.min(a.r, b.r) + "," + Math.min(a.c, b.c) + "-" + Math.max(a.r, b.r) + "," + Math.max(a.c, b.c);
      edgeTraffic[key] = (edgeTraffic[key] || 0) + 1;
    }
  });

  // Min passage and max traffic
  var minPassageCm = Infinity, maxTraffic = 1;
  for (var r = 0; r < rowsN; r++) {
    for (var c = 0; c < cols; c++) {
      if (dist[r][c] >= 0 && traffic[r][c] > 0) {
        var pw = passWidth[r][c] * cellCm;
        if (pw < minPassageCm) minPassageCm = pw;
      }
      if (traffic[r][c] > maxTraffic) maxTraffic = traffic[r][c];
    }
  }
  if (minPassageCm === Infinity) minPassageCm = 0;
  var maxEdgeTraffic = 1;
  for (var key in edgeTraffic) { if (edgeTraffic[key] > maxEdgeTraffic) maxEdgeTraffic = edgeTraffic[key]; }

  return { grid: grid, cols: cols, rows: rowsN, dist: dist, traffic: traffic,
           passWidth: passWidth, paths: paths, edgeTraffic: edgeTraffic,
           maxTraffic: maxTraffic, maxEdgeTraffic: maxEdgeTraffic, minPassageCm: minPassageCm };
}

function findNearestFreeCell(grid, r, c, cols, rowsN) {
  if (r >= 0 && r < rowsN && c >= 0 && c < cols && grid[r][c] === 0) return { r: r, c: c };
  for (var radius = 1; radius <= 15; radius++) {
    for (var dr = -radius; dr <= radius; dr++) {
      for (var dc = -radius; dc <= radius; dc++) {
        if (Math.abs(dr) !== radius && Math.abs(dc) !== radius) continue;
        var nr = r + dr, nc = c + dc;
        if (nr >= 0 && nr < rowsN && nc >= 0 && nc < cols && grid[nr][nc] === 0) return { r: nr, c: nc };
      }
    }
  }
  return null;
}

function markGridRect(grid, xCm, yCm, wCm, hCm, cellCm, cols, rowsN, val) {
  var c0 = Math.floor(xCm / cellCm);
  var r0 = Math.floor(yCm / cellCm);
  var c1 = Math.ceil((xCm + wCm) / cellCm);
  var r1 = Math.ceil((yCm + hCm) / cellCm);
  for (var r = Math.max(0, r0); r < Math.min(rowsN, r1); r++)
    for (var c = Math.max(0, c0); c < Math.min(cols, c1); c++)
      if (grid[r][c] === 0) grid[r][c] = val;
}

function computePatternScoring(p) {
  // Compute room-level scores for a catalogue pattern
  var nDesks = 0;
  (p.rows || []).forEach(function(r) {
    (r.blocks || []).forEach(function(b) { nDesks += countDesksInBlock(b.type) || 0; });
  });
  var roomArea = ((p.room_width_cm || 0) * (p.room_depth_cm || 0)) / 10000;
  var m2pp = nDesks > 0 ? roomArea / nDesks : 0;
  // Circulation: rasterize the room
  var cellCm = GRID_STEP_CM;
  var cols = Math.floor((p.room_width_cm || 0) / cellCm);
  var rowsN = Math.floor((p.room_depth_cm || 0) / cellCm);
  var freePct = 0, minPassageCm = 0;
  if (cols > 0 && rowsN > 0 && nDesks > 0) {
    var grid = [];
    for (var r = 0; r < rowsN; r++) { grid[r] = []; for (var c = 0; c < cols; c++) grid[r][c] = 0; }
    // Exclusion zones
    (p.room_exclusions || []).forEach(function(z) {
      var c0 = Math.floor(z.x_cm / cellCm), r0 = Math.floor(z.y_cm / cellCm);
      var c1 = Math.ceil((z.x_cm + z.width_cm) / cellCm), r1 = Math.ceil((z.y_cm + z.depth_cm) / cellCm);
      for (var r = Math.max(0, r0); r < Math.min(rowsN, r1); r++)
        for (var c = Math.max(0, c0); c < Math.min(cols, c1); c++) grid[r][c] = 2;
    });
    // Blocks + fixed zones
    var yRow = 0;
    for (var ri = 0; ri < (p.rows || []).length; ri++) {
      var row = p.rows[ri];
      var xBlock = 0, rowMaxNS = 0;
      for (var bi = 0; bi < (row.blocks || []).length; bi++) {
        var b = row.blocks[bi];
        var g = getEffectiveGeom(b.type, b.orientation);
        var f = g.faces;
        var offNS = b.offset_ns_cm || 0;
        if (b.gap_cm) xBlock += b.gap_cm;
        markGridRect(grid, xBlock, yRow + offNS, g.eo, g.ns, cellCm, cols, rowsN, 1);
        var wNS = (f.west && f.west.non_superposable_cm) || 0;
        var eNS = (f.east && f.east.non_superposable_cm) || 0;
        var nNS = (f.north && f.north.non_superposable_cm) || 0;
        var sNS = (f.south && f.south.non_superposable_cm) || 0;
        if (wNS > 0) markGridRect(grid, xBlock - wNS, yRow + offNS, wNS, g.ns, cellCm, cols, rowsN, 1);
        if (eNS > 0) markGridRect(grid, xBlock + g.eo, yRow + offNS, eNS, g.ns, cellCm, cols, rowsN, 1);
        if (nNS > 0) markGridRect(grid, xBlock, yRow + offNS - nNS, g.eo, nNS, cellCm, cols, rowsN, 1);
        if (sNS > 0) markGridRect(grid, xBlock, yRow + offNS + g.ns, g.eo, sNS, cellCm, cols, rowsN, 1);
        xBlock += g.eo;
        if (g.ns > rowMaxNS) rowMaxNS = g.ns;
      }
      yRow += rowMaxNS;
      if (ri < (p.rows || []).length - 1) yRow += (p.row_gaps_cm || [])[ri] || 0;
    }
    var totalCells = 0, freeCells = 0;
    for (var r = 0; r < rowsN; r++)
      for (var c = 0; c < cols; c++)
        if (grid[r][c] !== 2) { totalCells++; if (grid[r][c] === 0) freeCells++; }
    freePct = totalCells > 0 ? Math.round(freeCells * 100 / totalCells) : 0;
    // Min passage
    var mp = Infinity;
    for (var r = 0; r < rowsN; r++) {
      var run = 0;
      for (var c = 0; c <= cols; c++) {
        if (c < cols && grid[r][c] === 0) { run++; }
        else { if (run > 0 && run * cellCm < mp) mp = run * cellCm; run = 0; }
      }
    }
    for (var c = 0; c < cols; c++) {
      var run = 0;
      for (var r = 0; r <= rowsN; r++) {
        if (r < rowsN && grid[r][c] === 0) { run++; }
        else { if (run > 0 && run * cellCm < mp) mp = run * cellCm; run = 0; }
      }
    }
    minPassageCm = mp === Infinity ? 0 : mp;
  }
  return { nDesks: nDesks, m2pp: m2pp, freePct: freePct, minPassageCm: minPassageCm };
}

function scoringHtml(sc) {
  if (sc.nDesks === 0) return "";
  return '<span style="color:var(--accent2);">' + sc.m2pp.toFixed(1) + ' m\u00b2/p' +
    ' · passage min ' + sc.minPassageCm + ' cm</span>';
}

function distanceConformity(gapCm, role) {
  // Returns color based on conformity to the active standard
  // role: "between_blocks" (ES-06/ES-11), "block_wall" (ES-09), "between_rows" (ES-05)
  if (!CURRENT_SPACING) return COLOR_GAP_LABEL;
  if (role === "between_blocks") {
    var minSep = CURRENT_SPACING ? CURRENT_SPACING.min_block_separation_cm : 0;
    if (gapCm >= minSep) return "#58c080";       // ok green
    if (gapCm >= minSep * 0.8) return "#c8a050";  // warning
    return "#c05858";                              // non-compliant
  }
  if (role === "block_wall") {
    // ES-06: block-wall space serves as passage
    var minPass = CURRENT_SPACING ? CURRENT_SPACING.passage_cm : 0;
    if (gapCm >= minPass) return "#58c080";
    if (gapCm >= minPass * 0.8) return "#c8a050";
    return "#c05858";
  }
  if (role === "between_rows") {
    // ES-04: total desk-to-desk distance (includes 70cm chair setback + passage)
    var minPass = CURRENT_SPACING ? CURRENT_SPACING.passage_behind_one_row_cm : 0;
    if (gapCm >= minPass) return "#58c080";
    if (gapCm >= minPass * 0.8) return "#c8a050";
    return "#c05858";
  }
  return COLOR_GAP_LABEL;
}

function pushDistLabel(elements, x, y, valueCm, color) {
  var text = String(valueCm);
  var charW = 5.5, padX = 2, padY = 1, fontSize = 10;
  var bgW = text.length * charW + padX * 2;
  var bgH = fontSize + padY * 2;
  elements.push({ z: 6.9, s: '<rect x="' + (x - bgW / 2).toFixed(1) + '" y="' + (y - bgH + padY).toFixed(1) +
    '" width="' + bgW.toFixed(1) + '" height="' + bgH.toFixed(1) +
    '" rx="2" fill="#0e0e0d" fill-opacity="0.75"/>' });
  elements.push({ z: 7, s: '<text x="' + x.toFixed(1) + '" y="' + y.toFixed(1) +
    '" text-anchor="middle" fill="' + color +
    '" font-size="' + fontSize + '" font-weight="bold" font-family="monospace">' + valueCm + '</text>' });
}

function smoothPath(pts) {
  // Douglas-Peucker simplification then straight lines between remaining points
  if (pts.length < 2) return "";
  var simplified = douglasPeucker(pts, 3.5); // tolerance 3.5px
  var d = "M " + simplified[0].x.toFixed(1) + " " + simplified[0].y.toFixed(1);
  for (var i = 1; i < simplified.length; i++) {
    d += " L " + simplified[i].x.toFixed(1) + " " + simplified[i].y.toFixed(1);
  }
  return d;
}

function douglasPeucker(pts, epsilon) {
  if (pts.length <= 2) return pts.slice();
  // Find the point farthest from the first-last line
  var first = pts[0], last = pts[pts.length - 1];
  var maxDist = 0, maxIdx = 0;
  for (var i = 1; i < pts.length - 1; i++) {
    var d = pointToLineDist(pts[i], first, last);
    if (d > maxDist) { maxDist = d; maxIdx = i; }
  }
  if (maxDist > epsilon) {
    var left = douglasPeucker(pts.slice(0, maxIdx + 1), epsilon);
    var right = douglasPeucker(pts.slice(maxIdx), epsilon);
    return left.slice(0, left.length - 1).concat(right);
  }
  return [first, last];
}

function pointToLineDist(p, a, b) {
  var dx = b.x - a.x, dy = b.y - a.y;
  var len2 = dx * dx + dy * dy;
  if (len2 === 0) return Math.sqrt((p.x - a.x) * (p.x - a.x) + (p.y - a.y) * (p.y - a.y));
  var t = ((p.x - a.x) * dx + (p.y - a.y) * dy) / len2;
  t = Math.max(0, Math.min(1, t));
  var projX = a.x + t * dx, projY = a.y + t * dy;
  return Math.sqrt((p.x - projX) * (p.x - projX) + (p.y - projY) * (p.y - projY));
}

function circGrade(circ) {
  // Grade based on minimum passage vs active standard thresholds
  // A: above corridor (PS-04), B: above passage (ES-06), C: at passage,
  // D: below passage but >50%, F: critically below
  var minW = circ.minPassageCm;
  var passage = CURRENT_SPACING ? CURRENT_SPACING.passage_cm : 90;       // ES-06
  var corridor = CURRENT_SPACING ? CURRENT_SPACING.main_corridor_cm : 140; // PS-04
  if (minW >= corridor) return { grade: "A", color: "#58c080" };
  if (minW > passage)   return { grade: "B", color: "#7ab060" };
  if (minW >= passage)  return { grade: "C", color: "#c8a050" };
  if (minW >= passage * 0.5) return { grade: "D", color: "#c07040" };
  return { grade: "F", color: "#c05858" };
}

function circColor(ratio, maxTraffic, passWidthCells) {
  var widthCm = passWidthCells * GRID_STEP_CM;
  var passage = CURRENT_SPACING ? CURRENT_SPACING.passage_cm : 0;       // ES-06
  var corridor = CURRENT_SPACING ? CURRENT_SPACING.main_corridor_cm : 0; // PS-04
  if (widthCm < passage) return { fill: "#c05858", opacity: 0.50 };   // red — below ES-06
  if (widthCm < corridor && ratio > 0.3) return { fill: "#c8a050", opacity: 0.45 }; // amber — below PS-04 with traffic
  var norm = Math.min(1, ratio / (maxTraffic > 0 ? maxTraffic / passWidthCells : 1));
  var opacity = 0.20 + 0.30 * norm;
  return { fill: "#58c080", opacity: opacity };
}

// ========== ZOOM PAR SELECTION (Shift+drag) ==========

var zoomSel = { active: false, svg: null, viewBox: null, startPx: null, rectEl: null, applyFn: null };

function zoomSelStart(e, svgEl, viewBox, applyFn) {
  if (!e.shiftKey || e.button !== 0) return false;
  var rect = svgEl.getBoundingClientRect();
  zoomSel.active = true;
  zoomSel.svg = svgEl;
  zoomSel.viewBox = viewBox;
  zoomSel.applyFn = applyFn;
  zoomSel.startPx = { x: e.clientX, y: e.clientY, rect: rect };
  // Create the SVG rectangle
  var r = document.createElementNS("http://www.w3.org/2000/svg", "rect");
  r.classList.add("zoom-rect");
  var svgPt = pxToSvg(e.clientX, e.clientY, rect, viewBox);
  r.setAttribute("x", svgPt.x);
  r.setAttribute("y", svgPt.y);
  r.setAttribute("width", 0);
  r.setAttribute("height", 0);
  svgEl.appendChild(r);
  zoomSel.rectEl = r;
  e.preventDefault();
  return true;
}

function zoomSelMove(e) {
  if (!zoomSel.active) return;
  var rect = zoomSel.startPx.rect;
  var vb = zoomSel.viewBox;
  var p1 = pxToSvg(zoomSel.startPx.x, zoomSel.startPx.y, rect, vb);
  var p2 = pxToSvg(e.clientX, e.clientY, rect, vb);
  var x = Math.min(p1.x, p2.x), y = Math.min(p1.y, p2.y);
  var w = Math.abs(p2.x - p1.x), h = Math.abs(p2.y - p1.y);
  zoomSel.rectEl.setAttribute("x", x);
  zoomSel.rectEl.setAttribute("y", y);
  zoomSel.rectEl.setAttribute("width", w);
  zoomSel.rectEl.setAttribute("height", h);
}

function zoomSelEnd(e) {
  if (!zoomSel.active) return;
  var rect = zoomSel.startPx.rect;
  var vb = zoomSel.viewBox;
  var p1 = pxToSvg(zoomSel.startPx.x, zoomSel.startPx.y, rect, vb);
  var p2 = pxToSvg(e.clientX, e.clientY, rect, vb);
  // Remove the rectangle
  if (zoomSel.rectEl && zoomSel.rectEl.parentNode) {
    zoomSel.rectEl.parentNode.removeChild(zoomSel.rectEl);
  }
  var w = Math.abs(p2.x - p1.x), h = Math.abs(p2.y - p1.y);
  if (w > 2 && h > 2) {
    // Fit viewBox to selected zone, preserving aspect ratio
    var x = Math.min(p1.x, p2.x), y = Math.min(p1.y, p2.y);
    var svgRect = zoomSel.svg.getBoundingClientRect();
    var aspect = svgRect.width / svgRect.height;
    var selAspect = w / h;
    if (selAspect > aspect) {
      // Selection wider than SVG: adjust height
      var newH = w / aspect;
      y -= (newH - h) / 2;
      h = newH;
    } else {
      var newW = h * aspect;
      x -= (newW - w) / 2;
      w = newW;
    }
    vb.x = x; vb.y = y; vb.w = w; vb.h = h;
    if (zoomSel.applyFn) zoomSel.applyFn();
  }
  zoomSel.active = false;
  zoomSel.rectEl = null;
}

function pxToSvg(clientX, clientY, domRect, viewBox) {
  // Account for preserveAspectRatio="xMidYMid meet" letter-boxing:
  // the rendered content may not fill the full element bounding box.
  var elAspect = domRect.width / domRect.height;
  var vbAspect = viewBox.w / viewBox.h;
  var renderW, renderH, offsetX, offsetY;
  if (vbAspect > elAspect) {
    // ViewBox wider than element: horizontal fit, vertical letter-box
    renderW = domRect.width;
    renderH = domRect.width / vbAspect;
    offsetX = 0;
    offsetY = (domRect.height - renderH) / 2;
  } else {
    // ViewBox taller than element: vertical fit, horizontal letter-box
    renderH = domRect.height;
    renderW = domRect.height * vbAspect;
    offsetX = (domRect.width - renderW) / 2;
    offsetY = 0;
  }
  return {
    x: viewBox.x + (clientX - domRect.left - offsetX) / renderW * viewBox.w,
    y: viewBox.y + (clientY - domRect.top - offsetY) / renderH * viewBox.h
  };
}
