/**
 * ingestion.js — Floor plan ingestion viewer for the Import tab.
 *
 * Calls /api/ingestion/extract, renders results as SVG overlay
 * on the floor plan image. Uses same color conventions as the
 * pattern editor (renderRoomElements).
 */
(function () {
  'use strict';

  // --- State ---
  var ingState = {
    planPath: '',
    planUrl: '',
    planW: 0,
    planH: 0,
    scale: 0.5,
    threshold: 110,
    rooms: [],
    show: {
      bbox: true, window: true, door: true, opening: true,
      names: true, vrays: false, hrays: false, candidates: false,
      grid: true,
    },
    zoomRoom: '',
    merges: {},  // key: "roomA|roomB" → true if merge checked
    opacity: 0.3,
    overlayVisible: true,
    // Viewbox state for pan/zoom
    vb: { x: 0, y: 0, w: 1920, h: 1080 },
    pan: null, // { startX, startY, startVb }
  };

  // --- Colors (matching OLM conventions) ---
  var COLORS = {
    bbox:     '#ffffff',     // white
    window:   '#50b8d0',     // cyan (same as renderRoomElements)
    door:     '#58c080',     // --ok (green)
    opening:  '#c8a050',     // --accent (gold), dashed
    name:     '#ffffff',
    vray_n:   'rgba(0,200,0,0.4)',
    vray_s:   'rgba(0,150,200,0.4)',
    hray_w:   'rgba(200,0,0,0.4)',
    hray_e:   'rgba(200,100,0,0.4)',
    hit:      '#ffff00',
    candidate:'rgba(255,255,0,0.3)',
    seed:     '#58c080',
  };

  // --- Extract rooms from selected plan ---
  function extractRooms() {
    var planSel = document.getElementById('ingPlanSelect');
    var planPath = planSel ? planSel.value : '';
    if (!planPath) return;

    ingState.planPath = planPath;
    var scaleVal = document.getElementById('ingScale').value;
    ingState.scale = (scaleVal && parseFloat(scaleVal) > 0) ? parseFloat(scaleVal) : null;
    ingState.threshold = parseInt(document.getElementById('ingThreshold').value) || 110;

    var status = document.getElementById('ingStatus');
    status.textContent = 'Extracting...';

    var formData = new FormData();
    formData.append('plan_path', planPath);
    if (ingState.scale) formData.append('scale', ingState.scale);
    formData.append('threshold', ingState.threshold);

    fetch('/api/ingestion/debug', { method: 'POST', body: formData })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        // Display debug logs
        var debugLog = document.getElementById('ingDebugLog');
        if (data.logs && data.logs.length > 0) {
          debugLog.textContent = data.logs.join('\n');
        }

        if (data.error) {
          status.textContent = 'Error: ' + data.error;
          if (debugLog) debugLog.textContent = '[ERROR] ' + data.error;
          return;
        }
        ingState.rooms = data.rooms || [];
        ingState.planW = data.image_size[0];
        ingState.planH = data.image_size[1];
        ingState.planUrl = '/api/ingestion/plan/' + planPath;
        ingState.scale = data.scale_cm_per_px;
        ingState.vb = { x: 0, y: 0, w: ingState.planW, h: ingState.planH };
        // Update scale input with auto-detected value
        var scaleInput = document.getElementById('ingScale');
        if (scaleInput) scaleInput.value = ingState.scale;
        status.textContent = ingState.rooms.length + ' rooms — scale ' +
          ingState.scale + ' cm/px';
        renderIngestion();
        populateRoomsJson();
        updateIngRoomList();

        // Feed rooms into the floor plan pipeline (Review + Design)
        var json = document.getElementById('fpRoomsJson').value;
        if (json && typeof window.fpLoadAndMatch === 'function') {
          window.fpLoadAndMatch(json);
        }

        // Set overlay for Review/Design from the ingestion plan
        window.fpOverlay = {
          dataUrl: ingState.planUrl,
          pxPerCm: 1.0 / ingState.scale,
          imgW: ingState.planW,
          imgH: ingState.planH,
        };
        document.getElementById("fpOverlayToggle").checked = true;
        document.getElementById("rvOverlayToggle").checked = true;
      })
      .catch(function (e) {
        status.textContent = 'Error: ' + e;
        var debugLog = document.getElementById('ingDebugLog');
        if (debugLog) debugLog.textContent = '[ERROR] ' + e;
      });
  }

  // --- Room list (clickable, same style as Review) ---
  window.updateIngRoomList = updateIngRoomList;
  function updateIngRoomList() {
    var listEl = document.getElementById('ingRoomList');
    if (!listEl) return;
    var inRoomView = document.getElementById('ingRoomView') &&
      document.getElementById('ingRoomView').style.display !== 'none';
    var selectedName = inRoomView && window.fpData && window.fpData.rooms.length
      ? (window.fpData.rooms[window.fpData.currentIdx] || {}).name : '';
    var rooms = ingState.rooms.slice().sort(function(a, b) {
      return (a.name || '').localeCompare(b.name || '', undefined, { numeric: true });
    });
    var html = '';
    rooms.forEach(function(r) {
      var active = (inRoomView ? selectedName === r.name : ingState.zoomRoom === r.name)
        ? 'font-weight:bold;color:var(--accent);' : 'color:var(--text-dim);';
      var dims = r.width_cm + 'x' + r.depth_cm;
      html += '<div style="padding:2px 4px;cursor:pointer;' + active +
        '" data-ing-room="' + r.name + '">' + r.name +
        ' <span style="font-size:10px;color:var(--text-dim);">' + dims + '</span></div>';
    });
    // "All" entry — always visible, returns to plan view
    var allActive = (!inRoomView && !ingState.zoomRoom)
      ? 'font-weight:bold;color:var(--accent);' : 'color:var(--text-dim);';
    html = '<div style="padding:2px 4px;cursor:pointer;' + allActive +
      '" data-ing-room="">&#9664; All (' + rooms.length + ')</div>' + html;
    listEl.innerHTML = html;
    listEl.querySelectorAll('[data-ing-room]').forEach(function(el) {
      el.addEventListener('click', function() {
        var name = this.dataset.ingRoom;
        if (name) {
          // Select room in fpData and switch to room view
          if (window.fpData) {
            var rooms = window.fpData.rooms || [];
            for (var i = 0; i < rooms.length; i++) {
              if (rooms[i].name === name) {
                window.fpData.currentIdx = i;
                break;
              }
            }
          }
          if (window.ingShowRoomView) window.ingShowRoomView();
        } else {
          // "All" — back to plan view
          ingState.zoomRoom = '';
          if (window.ingShowPlanView) window.ingShowPlanView();
          zoomFit();
          updateIngRoomList();
        }
      });
    });
  }

  // --- Populate the rooms JSON textarea for matching ---
  function populateRoomsJson() {
    var textarea = document.getElementById('fpRoomsJson');
    if (!textarea) return;
    var rooms = ingState.rooms.map(function (r) {
      var windows = r.windows.map(function (w) {
        return {
          face: w.face,
          offset_cm: Math.round(w.offset_px * ingState.scale),
          width_cm: Math.round(w.width_px * ingState.scale),
        };
      });
      var openings = r.openings.map(function (o) {
        return {
          face: o.face,
          offset_cm: Math.round(o.offset_px * ingState.scale),
          width_cm: Math.round(o.width_px * ingState.scale),
          has_door: false,
        };
      });
      // Add doors as openings with has_door=true
      r.doors.forEach(function (d) {
        openings.push({
          face: d.face,
          offset_cm: Math.round(d.offset_px * ingState.scale),
          width_cm: Math.round(d.width_px * ingState.scale),
          has_door: true,
          opens_inward: d.opens_inward || true,
          hinge_side: d.hinge_side || 'left',
        });
      });
      return {
        name: r.name,
        width_cm: r.width_cm,
        depth_cm: r.depth_cm,
        windows: windows,
        openings: openings,
        exclusion_zones: [],
        exterior_faces: r.exterior_faces,
        corridor_face: r.corridor_face,
        bbox_px: r.bbox_px,
      };
    });
    textarea.value = JSON.stringify({ rooms: rooms }, null, 2);
  }

  // --- Render the ingestion results as SVG ---
  function renderIngestion() {
    var svg = document.getElementById('ingSvg');
    if (!svg) return;

    var W = ingState.planW;
    var H = ingState.planH;
    if (!W || !H) return;

    // Apply viewbox (zoom/pan state)
    var vb = ingState.vb;
    svg.setAttribute('viewBox', vb.x + ' ' + vb.y + ' ' + vb.w + ' ' + vb.h);

    var els = [];

    // Background: floor plan image (as overlay)
    if (ingState.overlayVisible && ingState.planUrl) {
      els.push('<image href="' + ingState.planUrl +
        '" x="0" y="0" width="' + W + '" height="' + H +
        '" opacity="' + ingState.opacity + '" />');
    }

    // Grid: 10cm dots + 1m lines (same style as pattern editor)
    if (ingState.show.grid && ingState.scale > 0) {
      var cmPerPx = ingState.scale;
      var step10cm = 10 / cmPerPx;    // 10cm in pixels
      var step1m = 100 / cmPerPx;     // 1m in pixels
      var vb = ingState.vb;
      var margin = Math.max(vb.w, vb.h) * 0.3;
      var gxS = Math.floor((vb.x - margin) / step10cm) * step10cm;
      var gyS = Math.floor((vb.y - margin) / step10cm) * step10cm;
      var gxE = vb.x + vb.w + margin;
      var gyE = vb.y + vb.h + margin;
      // 10cm dots (skip when zoomed out too far)
      if (vb.w / step10cm < 150) {
        for (var gx = gxS; gx <= gxE; gx += step10cm) {
          for (var gy = gyS; gy <= gyE; gy += step10cm) {
            els.push('<circle cx="' + gx.toFixed(1) + '" cy="' + gy.toFixed(1) +
              '" r="0.6" fill="#6e6a62"/>');
          }
        }
      }
      // 1m lines
      var mxS = Math.max(0, Math.floor(vb.x / step1m) * step1m);
      var myS = Math.max(0, Math.floor(vb.y / step1m) * step1m);
      for (var mx = mxS; mx <= gxE; mx += step1m) {
        els.push('<line x1="' + mx.toFixed(1) + '" y1="' + gyS.toFixed(1) +
          '" x2="' + mx.toFixed(1) + '" y2="' + gyE.toFixed(1) +
          '" stroke="#6e6a62" stroke-width="0.5"/>');
      }
      for (var my = myS; my <= gyE; my += step1m) {
        els.push('<line x1="' + gxS.toFixed(1) + '" y1="' + my.toFixed(1) +
          '" x2="' + gxE.toFixed(1) + '" y2="' + my.toFixed(1) +
          '" stroke="#6e6a62" stroke-width="0.5"/>');
      }
    }

    var show = ingState.show;
    var zoomRoom = ingState.zoomRoom;

    ingState.rooms.forEach(function (room) {
      if (zoomRoom && room.name !== zoomRoom) return;

      var x0 = room.bbox_px[0], y0 = room.bbox_px[1];
      var x1 = room.bbox_px[2], y1 = room.bbox_px[3];
      var w = x1 - x0, h = y1 - y0;
      var cx = room.seed_px[0], cy = room.seed_px[1];

      // Rays
      if (show.vrays || show.hrays) {
        room.hits.forEach(function (hit) {
          var hx = hit[0], hy = hit[1];
          if (hy < cy && show.vrays) {
            els.push('<line x1="' + hx + '" y1="' + cy + '" x2="' + hx +
              '" y2="' + hy + '" stroke="' + COLORS.vray_n +
              '" stroke-width="0.5"/>');
          } else if (hy > cy && show.vrays) {
            els.push('<line x1="' + hx + '" y1="' + cy + '" x2="' + hx +
              '" y2="' + hy + '" stroke="' + COLORS.vray_s +
              '" stroke-width="0.5"/>');
          } else if (hx < cx && show.hrays) {
            els.push('<line x1="' + cx + '" y1="' + hy + '" x2="' + hx +
              '" y2="' + hy + '" stroke="' + COLORS.hray_w +
              '" stroke-width="0.5"/>');
          } else if (hx > cx && show.hrays) {
            els.push('<line x1="' + cx + '" y1="' + hy + '" x2="' + hx +
              '" y2="' + hy + '" stroke="' + COLORS.hray_e +
              '" stroke-width="0.5"/>');
          }
        });
        // Hits as dots
        room.hits.forEach(function (hit) {
          var hx = hit[0], hy = hit[1];
          var isV = (hy !== cy), isH = (hx !== cx);
          if ((isV && show.vrays) || (isH && show.hrays)) {
            els.push('<circle cx="' + hx + '" cy="' + hy +
              '" r="1.5" fill="' + COLORS.hit + '"/>');
          }
        });
        // Seed
        els.push('<circle cx="' + cx + '" cy="' + cy +
          '" r="3" fill="' + COLORS.seed + '"/>');
      }

      // Room bbox
      if (show.bbox) {
        els.push('<rect x="' + x0 + '" y="' + y0 + '" width="' + w +
          '" height="' + h + '" fill="none" stroke="' + COLORS.bbox +
          '" stroke-width="1.5"/>');
      }

      // Windows (cyan, round linecap — same as renderRoomElements)
      if (show.window) {
        room.windows.forEach(function (win) {
          drawWallFeature(els, x0, y0, x1, y1, win.face,
            win.offset_px, win.width_px, '#50b8d0', 1.5, '', ' stroke-linecap="round"');
        });
      }

      // Openings (light green dashed — same as renderRoomElements)
      if (show.opening) {
        room.openings.forEach(function (op) {
          drawWallFeature(els, x0, y0, x1, y1, op.face,
            op.offset_px, op.width_px, '#80c060', 1, '4 3', '');
        });
      }

      // Doors (arc + leaf, same style as editor renderRoomElements)
      if (show.door) {
        room.doors.forEach(function (d) {
          var jh = d.jamb_hinge_px, jf = d.jamb_free_px;
          var dw = Math.abs(jf - jh);  // door width in px
          var swing = d.hinge_side || 'left';
          var inward = d.opens_inward !== false;

          if (d.face === 'south') {
            var hingeX = (swing === 'left') ? jh : jf;
            var freeX = (swing === 'left') ? jf : jh;
            var sweepDir = (swing === 'left') ? 0 : 1;
            if (!inward) sweepDir = 1 - sweepDir;
            var arcEndY = inward ? y1 - dw : y1 + dw;
            els.push('<path d="M ' + freeX + ' ' + y1 +
              ' A ' + dw + ' ' + dw + ' 0 0 ' + sweepDir + ' ' + hingeX + ' ' + arcEndY +
              '" fill="none" stroke="#6e6a62" stroke-width="1.5" stroke-dasharray="6 3"/>');
            els.push('<line x1="' + hingeX + '" y1="' + y1 +
              '" x2="' + hingeX + '" y2="' + arcEndY +
              '" stroke="#e4e0d8" stroke-width="1.5"/>');
          } else if (d.face === 'north') {
            var hingeX = (swing === 'left') ? jh : jf;
            var freeX = (swing === 'left') ? jf : jh;
            var sweepDir = (swing === 'left') ? 1 : 0;
            if (!inward) sweepDir = 1 - sweepDir;
            var arcEndY = inward ? y0 + dw : y0 - dw;
            els.push('<path d="M ' + freeX + ' ' + y0 +
              ' A ' + dw + ' ' + dw + ' 0 0 ' + sweepDir + ' ' + hingeX + ' ' + arcEndY +
              '" fill="none" stroke="#6e6a62" stroke-width="1.5" stroke-dasharray="6 3"/>');
            els.push('<line x1="' + hingeX + '" y1="' + y0 +
              '" x2="' + hingeX + '" y2="' + arcEndY +
              '" stroke="#e4e0d8" stroke-width="1.5"/>');
          } else if (d.face === 'west') {
            var hingeY = (swing === 'left') ? jf : jh;
            var freeY = (swing === 'left') ? jh : jf;
            var sweepDir = (swing === 'left') ? 0 : 1;
            if (!inward) sweepDir = 1 - sweepDir;
            var arcEndX = inward ? x0 + dw : x0 - dw;
            els.push('<path d="M ' + x0 + ' ' + freeY +
              ' A ' + dw + ' ' + dw + ' 0 0 ' + sweepDir + ' ' + arcEndX + ' ' + hingeY +
              '" fill="none" stroke="#6e6a62" stroke-width="1.5" stroke-dasharray="6 3"/>');
            els.push('<line x1="' + x0 + '" y1="' + hingeY +
              '" x2="' + arcEndX + '" y2="' + hingeY +
              '" stroke="#e4e0d8" stroke-width="1.5"/>');
          } else if (d.face === 'east') {
            var hingeY = (swing === 'left') ? jh : jf;
            var freeY = (swing === 'left') ? jf : jh;
            var sweepDir = (swing === 'left') ? 1 : 0;
            if (!inward) sweepDir = 1 - sweepDir;
            var arcEndX = inward ? x1 - dw : x1 + dw;
            els.push('<path d="M ' + x1 + ' ' + freeY +
              ' A ' + dw + ' ' + dw + ' 0 0 ' + sweepDir + ' ' + arcEndX + ' ' + hingeY +
              '" fill="none" stroke="#6e6a62" stroke-width="1.5" stroke-dasharray="6 3"/>');
            els.push('<line x1="' + x1 + '" y1="' + hingeY +
              '" x2="' + arcEndX + '" y2="' + hingeY +
              '" stroke="#e4e0d8" stroke-width="1.5"/>');
          }
        });
      }

      // Room name (coupled with bbox toggle)
      if (show.bbox) {
        var mx = (x0 + x1) / 2, my = (y0 + y1) / 2;
        els.push('<text x="' + mx + '" y="' + my +
          '" text-anchor="middle" dominant-baseline="central" fill="' +
          COLORS.name + '" font-size="16" font-weight="bold" font-family="monospace" style="pointer-events:none;">' +
          room.name + '</text>');
      }

      // Clickable hit area (transparent rect on top)
      els.push('<rect x="' + x0 + '" y="' + y0 + '" width="' + w +
        '" height="' + h + '" fill="transparent" stroke="none" ' +
        'style="cursor:pointer;" data-room="' + room.name + '"/>');
    });

    // Merge checkboxes between contiguous rooms
    if (show.bbox && !zoomRoom) {
      var MERGE_TOL = 8; // px tolerance for shared wall detection
      var pairs = [];
      for (var i = 0; i < ingState.rooms.length; i++) {
        var ri = ingState.rooms[i];
        var ai = ri.bbox_px;
        for (var j = i + 1; j < ingState.rooms.length; j++) {
          var rj = ingState.rooms[j];
          var aj = rj.bbox_px;
          // Check if they share a vertical wall (east-west adjacency)
          var sharedV = Math.min(ai[3], aj[3]) - Math.max(ai[1], aj[1]);
          if (sharedV > MERGE_TOL &&
              (Math.abs(ai[2] - aj[0]) < MERGE_TOL || Math.abs(aj[2] - ai[0]) < MERGE_TOL)) {
            var wallX = Math.abs(ai[2] - aj[0]) < MERGE_TOL ? ai[2] : ai[0];
            var midY = (Math.max(ai[1], aj[1]) + Math.min(ai[3], aj[3])) / 2;
            pairs.push({ a: ri.name, b: rj.name, x: wallX, y: midY, orient: 'v' });
          }
          // Check if they share a horizontal wall (north-south adjacency)
          var sharedH = Math.min(ai[2], aj[2]) - Math.max(ai[0], aj[0]);
          if (sharedH > MERGE_TOL &&
              (Math.abs(ai[3] - aj[1]) < MERGE_TOL || Math.abs(aj[3] - ai[1]) < MERGE_TOL)) {
            var wallY = Math.abs(ai[3] - aj[1]) < MERGE_TOL ? ai[3] : ai[1];
            var midX = (Math.max(ai[0], aj[0]) + Math.min(ai[2], aj[2])) / 2;
            pairs.push({ a: ri.name, b: rj.name, x: midX, y: wallY, orient: 'h' });
          }
        }
      }
      pairs.forEach(function(p) {
        var key = p.a + '|' + p.b;
        var checked = ingState.merges[key] || false;
        var sz = 10;
        var fill = checked ? '#c8a050' : 'rgba(30,30,30,0.7)';
        var stroke = checked ? '#c8a050' : '#6e6a62';
        els.push('<rect x="' + (p.x - sz/2) + '" y="' + (p.y - sz/2) +
          '" width="' + sz + '" height="' + sz + '" rx="2" fill="' + fill +
          '" stroke="' + stroke + '" stroke-width="1" style="cursor:pointer;" data-merge="' + key + '"/>');
        if (checked) {
          els.push('<text x="' + p.x + '" y="' + (p.y + 1) +
            '" text-anchor="middle" dominant-baseline="central" fill="#1e1e1e" ' +
            'font-size="10" font-weight="bold" style="pointer-events:none;">&#10003;</text>');
        }
      });
    }

    svg.innerHTML = els.join('\n');

    // Click handler: merge checkboxes
    svg.querySelectorAll('[data-merge]').forEach(function(el) {
      el.addEventListener('click', function(e) {
        e.stopPropagation();
        var key = this.dataset.merge;
        ingState.merges[key] = !ingState.merges[key];
        renderIngestion();
      });
    });

    // Click handler: navigate to Room view
    svg.querySelectorAll('[data-room]').forEach(function(el) {
      el.addEventListener('click', function(e) {
        e.stopPropagation();
        var name = this.dataset.room;
        if (window.fpData) {
          var rooms = window.fpData.rooms || [];
          for (var i = 0; i < rooms.length; i++) {
            if (rooms[i].name === name) {
              window.fpData.currentIdx = i;
              break;
            }
          }
        }
        // Switch to room view
        if (window.ingShowRoomView) window.ingShowRoomView();
      });
    });
  }

  // --- Zoom/Pan ---
  function zoomFit() {
    var W = ingState.planW || 1920;
    var H = ingState.planH || 1080;
    if (ingState.zoomRoom) {
      var r = ingState.rooms.find(function (rm) { return rm.name === ingState.zoomRoom; });
      if (r) {
        var m = 50;
        ingState.vb = {
          x: r.bbox_px[0] - m, y: r.bbox_px[1] - m,
          w: r.bbox_px[2] - r.bbox_px[0] + 2 * m,
          h: r.bbox_px[3] - r.bbox_px[1] + 2 * m
        };
        renderIngestion();
        return;
      }
    }
    ingState.vb = { x: 0, y: 0, w: W, h: H };
    renderIngestion();
  }

  function zoomBy(factor) {
    var vb = ingState.vb;
    var cx = vb.x + vb.w / 2, cy = vb.y + vb.h / 2;
    vb.w *= factor;
    vb.h *= factor;
    vb.x = cx - vb.w / 2;
    vb.y = cy - vb.h / 2;
    renderIngestion();
  }

  function focusRoom(roomId) {
    // Find room by ID or name
    var room = ingState.rooms.find(function (r) {
      return r.name === roomId || r.name === 'room_' + roomId;
    });

    var infoEl = document.getElementById('ingFocusInfo');
    if (!room) {
      infoEl.textContent = '❌ Room ' + roomId + ' not found';
      return;
    }

    // Show seeds and rays for this room
    ingState.show.vrays = true;
    ingState.show.hrays = true;
    ingState.show.bbox = true;
    ingState.show.candidates = true;

    // Update checkboxes
    ['vrays', 'hrays', 'bbox', 'candidates'].forEach(function(prop) {
      var cb = document.getElementById('ing_' + prop);
      if (cb) cb.checked = true;
    });

    // Zoom to room
    var m = 30;
    ingState.vb = {
      x: room.bbox_px[0] - m,
      y: room.bbox_px[1] - m,
      w: room.bbox_px[2] - room.bbox_px[0] + 2 * m,
      h: room.bbox_px[3] - room.bbox_px[1] + 2 * m
    };

    // Show diagnostic info
    var hasSeed = room.seed !== undefined && room.seed !== null;
    var seedInfo = hasSeed
      ? 'Seed: (' + Math.round(room.seed[0]) + ', ' + Math.round(room.seed[1]) + ') ✓'
      : 'No seed found: OCR did not detect room code';
    infoEl.textContent = '✓ ' + room.name + ' | ' + seedInfo;

    renderIngestion();
  }

  function setupZoomPan() {
    var svg = document.getElementById('ingSvg');
    if (!svg) return;

    // Mouse wheel zoom disabled on this view
    // svg.addEventListener('wheel', function (e) { ... });

    // Mouse drag pan
    svg.addEventListener('mousedown', function (e) {
      if (e.button !== 0) return;
      ingState.pan = {
        startX: e.clientX, startY: e.clientY,
        startVb: { x: ingState.vb.x, y: ingState.vb.y,
                   w: ingState.vb.w, h: ingState.vb.h }
      };
      svg.style.cursor = 'grabbing';
    });

    window.addEventListener('mousemove', function (e) {
      if (!ingState.pan) return;
      var rect = svg.getBoundingClientRect();
      var dx = (e.clientX - ingState.pan.startX) / rect.width * ingState.pan.startVb.w;
      var dy = (e.clientY - ingState.pan.startY) / rect.height * ingState.pan.startVb.h;
      ingState.vb.x = ingState.pan.startVb.x - dx;
      ingState.vb.y = ingState.pan.startVb.y - dy;
      renderIngestion();
    });

    window.addEventListener('mouseup', function () {
      if (ingState.pan) {
        ingState.pan = null;
        var s = document.getElementById('ingSvg');
        if (s) s.style.cursor = 'grab';
      }
    });

    svg.style.cursor = 'grab';
  }

  // --- Helper: draw a wall feature (line outside the bbox) ---
  function drawWallFeature(els, x0, y0, x1, y1, face, offset, width,
                           color, strokeW, dash, extra) {
    var off = 3; // offset from bbox edge
    var dashAttr = dash ? ' stroke-dasharray="' + dash + '"' : '';
    var extraAttr = extra || '';
    if (face === 'north') {
      els.push('<line x1="' + (x0 + offset) + '" y1="' + (y0 - off) +
        '" x2="' + (x0 + offset + width) + '" y2="' + (y0 - off) +
        '" stroke="' + color + '" stroke-width="' + strokeW + '"' +
        dashAttr + extraAttr + '/>');
    } else if (face === 'south') {
      els.push('<line x1="' + (x0 + offset) + '" y1="' + (y1 + off) +
        '" x2="' + (x0 + offset + width) + '" y2="' + (y1 + off) +
        '" stroke="' + color + '" stroke-width="' + strokeW + '"' +
        dashAttr + extraAttr + '/>');
    } else if (face === 'west') {
      els.push('<line x1="' + (x0 - off) + '" y1="' + (y0 + offset) +
        '" x2="' + (x0 - off) + '" y2="' + (y0 + offset + width) +
        '" stroke="' + color + '" stroke-width="' + strokeW + '"' +
        dashAttr + extraAttr + '/>');
    } else if (face === 'east') {
      els.push('<line x1="' + (x1 + off) + '" y1="' + (y0 + offset) +
        '" x2="' + (x1 + off) + '" y2="' + (y0 + offset + width) +
        '" stroke="' + color + '" stroke-width="' + strokeW + '"' +
        dashAttr + extraAttr + '/>');
    }
  }

  // --- Toggle handler ---
  function setupToggles() {
    var keys = {
      r: 'bbox', w: 'window', d: 'door', o: 'opening',
      v: 'vrays', h: 'hrays', c: 'candidates',
      g: 'grid'
    };

    // Checkbox click handlers
    Object.keys(keys).forEach(function (key) {
      var id = 'ing_' + keys[key];
      var cb = document.getElementById(id);
      if (cb) {
        cb.addEventListener('change', function () {
          ingState.show[keys[key]] = cb.checked;
          renderIngestion();
        });
      }
    });

    // Overlay toggle + opacity slider
    var overlayToggle = document.getElementById('ingOverlayToggle');
    var opSlider = document.getElementById('ingOpacity');
    var opVal = document.getElementById('ingOpacityVal');
    if (overlayToggle) {
      overlayToggle.addEventListener('change', function () {
        ingState.overlayVisible = overlayToggle.checked;
        renderIngestion();
      });
    }
    if (opSlider) {
      opSlider.addEventListener('input', function () {
        ingState.opacity = parseInt(opSlider.value) / 100;
        if (opVal) opVal.textContent = opSlider.value + '%';
        renderIngestion();
      });
    }

    // Zoom buttons — use ingestion's own zoom functions
    var btnFit = document.getElementById('ingZoomFit');
    var btnIn = document.getElementById('ingZoomIn');
    var btnOut = document.getElementById('ingZoomOut');
    if (btnFit) btnFit.addEventListener('click', function () { zoomFit(); });
    if (btnIn) btnIn.addEventListener('click', function () { zoomBy(0.7); });
    if (btnOut) btnOut.addEventListener('click', function () { zoomBy(1.4); });

    // Keyboard shortcuts (only when Import tab is active)
    document.addEventListener('keydown', function (e) {
      var tab = document.getElementById('tabImport');
      if (!tab || !tab.classList.contains('active')) return;
      if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA'
          || e.target.tagName === 'SELECT') return;

      var prop = keys[e.key.toLowerCase()];
      if (prop) {
        ingState.show[prop] = !ingState.show[prop];
        var cb = document.getElementById('ing_' + prop);
        if (cb) cb.checked = ingState.show[prop];
        renderIngestion();
        return;
      }
      // Zoom keys
      if (e.key === '=' || e.key === '+') { zoomBy(0.7); return; }
      if (e.key === '-') { zoomBy(1.4); return; }
      if (e.key.toLowerCase() === 'f') { zoomFit(); return; }
    });

    // Room list is populated after extraction via updateIngRoomList()
  }

  // --- Load plan list ---
  function loadPlanList(callback) {
    fetch('/api/ingestion/plans')
      .then(function (r) { return r.json(); })
      .then(function (data) {
        var sel = document.getElementById('ingPlanSelect');
        if (!sel) return;
        sel.innerHTML = '<option value="">-- Select plan --</option>';
        (data.plans || []).forEach(function (p) {
          var opt = document.createElement('option');
          opt.value = p;
          opt.textContent = p;
          sel.appendChild(opt);
        });
        if (callback) callback();
      });
  }

  // --- Init ---
  document.addEventListener('DOMContentLoaded', function () {
    loadPlanList(function () {
      // DEV: auto-select plan 3 and extract
      var sel = document.getElementById('ingPlanSelect');
      if (sel) {
        for (var i = 0; i < sel.options.length; i++) {
          if (sel.options[i].value.indexOf('3') >= 0) {
            sel.selectedIndex = i;
            extractRooms();
            break;
          }
        }
      }
    });
    setupToggles();
    setupZoomPan();

    // Focus room feature
    var focusBtn = document.getElementById('ingFocusRoomBtn');
    var focusInput = document.getElementById('ingFocusRoomInput');
    if (focusBtn && focusInput) {
      function doFocus() {
        var roomId = focusInput.value.trim();
        if (!roomId) {
          document.getElementById('ingFocusInfo').textContent = 'Enter room ID';
          return;
        }
        focusRoom(roomId);
      }
      focusBtn.addEventListener('click', doFocus);
      focusInput.addEventListener('keypress', function(e) {
        if (e.key === 'Enter') doFocus();
      });
    }

    var btn = document.getElementById('ingBtnExtract');
    if (btn) btn.addEventListener('click', extractRooms);
  });

  // Expose for external use
  window.ingestionState = ingState;
  window.renderIngestion = renderIngestion;
  window.focusRoom = focusRoom;

})();
