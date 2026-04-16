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
    // Bbox editor state
    bboxEditor: {
      selectedName: null,      // name of room being edited, or null
      mode: 'idle',            // 'idle' | 'moving' | 'resizing'
      handle: null,            // 'nw' | 'ne' | 'sw' | 'se' (when resizing)
      dragStart: null,         // { mouseX, mouseY, bbox: [x0,y0,x1,y1] }
      preDragBbox: null,       // bbox_px snapshot before current drag (for Enter-cancel)
      sessionStartBbox: null,  // bbox_px snapshot at selection entry (for Escape session-restore)
    },
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

  // --- Coordinate conversion: screen → SVG viewBox ---
  function screenToIngSvg(evt) {
    var svg = document.getElementById('ingSvg');
    if (!svg) return { x: 0, y: 0 };
    var pt = svg.createSVGPoint();
    pt.x = evt.clientX;
    pt.y = evt.clientY;
    var ctm = svg.getScreenCTM();
    if (!ctm) return { x: 0, y: 0 };
    return pt.matrixTransform(ctm.inverse());
  }

  // --- Populate plan dropdown (flat list, sorted alphabetically) ---
  function populateDropdown(plans) {
    var sel = document.getElementById('ingPlanIdSelect');
    if (!sel) return;

    sel.innerHTML = '';

    if (!plans || plans.length === 0) {
      var none = document.createElement('option');
      none.value = '';
      none.disabled = true;
      none.selected = true;
      none.textContent = 'No plans available';
      sel.appendChild(none);
      sel.disabled = true;
      return;
    }

    sel.disabled = false;
    var placeholder = document.createElement('option');
    placeholder.value = '';
    placeholder.textContent = '— Select a plan —';
    sel.appendChild(placeholder);

    var sorted = plans.slice().sort(function(a, b) {
      return a.id.localeCompare(b.id, undefined, { sensitivity: 'base' });
    });
    sorted.forEach(function(p) {
      var opt = document.createElement('option');
      opt.value = p.id;
      opt.textContent = p.id;
      opt.dataset.mode = p.effective_mode || 'ocr';
      sel.appendChild(opt);
    });
  }

  function loadPlansDropdown() {
    fetch('/api/plans')
      .then(function(r) { return r.json(); })
      .then(function(data) {
        ingState._plansMeta = {};
        (data.plans || []).forEach(function(p) {
          ingState._plansMeta[p.id] = p;
        });
        populateDropdown(data.plans || []);
      });
  }

  // --- Extract rooms via plan_id (OCR mode) ---
  function extractRooms() {
    var sel = document.getElementById('ingPlanIdSelect');
    var planId = sel ? sel.value : '';
    var debugLog = document.getElementById('ingDebugLog');
    if (!planId) {
      if (debugLog) debugLog.textContent = '[ERROR] No plan selected.';
      return;
    }

    // Route by effective_mode stored in the selected option's data-mode attribute
    var selectedOpt = sel ? sel.options[sel.selectedIndex] : null;
    var mode = selectedOpt ? (selectedOpt.dataset.mode || 'ocr') : 'ocr';
    if (mode === 'preprocessed') {
      extractRoomsPreprocessed();
      return;
    }

    // Confirm before OCR (can be slow; no JSON available for this plan)
    var ok = confirm(
      'No JSON file found for this plan. Processing the input with Optical Character ' +
      'Recognition \u2014 this may take a few seconds. Continue?'
    );
    if (!ok) {
      if (sel) sel.value = '';
      return;
    }

    var status = document.getElementById('ingStatus');
    if (status) status.textContent = 'Extracting...';

    var formData = new FormData();
    formData.append('plan_id', planId);

    fetch('/api/import/ocr', { method: 'POST', body: formData })
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
        ingState.planUrl = data.image_path
          ? '/api/image?path=' + encodeURIComponent(data.image_path)
          : '';
        ingState.scale = data.scale_cm_per_px;
        ingState.vb = { x: 0, y: 0, w: ingState.planW, h: ingState.planH };
        // Update header badge with selected plan ID
        var hdrEl = document.getElementById('hdrCurrentPlan');
        if (hdrEl) hdrEl.textContent = planId;
        var btnSave = document.getElementById('btnSavePlan');
        if (btnSave) btnSave.style.display = '';
        var btnClose = document.getElementById('btnClosePlan');
        if (btnClose) btnClose.style.display = '';
        var eraseWrap = document.getElementById('eraseWrapper');
        if (eraseWrap) eraseWrap.style.display = '';
        if (status) status.textContent = ingState.rooms.length + ' rooms — scale ' +
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
    var reviewSubtab = document.getElementById('tabFpReview');
    var inRoomView = reviewSubtab && reviewSubtab.classList.contains('active');
    var selectedName = inRoomView && window.fpData && window.fpData.rooms.length
      ? (window.fpData.rooms[window.fpData.currentIdx] || {}).name : '';
    var beSel = ingState.bboxEditor.selectedName;
    var rooms = ingState.rooms.slice().sort(function(a, b) {
      return (a.name || '').localeCompare(b.name || '', undefined, { numeric: true });
    });
    var html = '';
    rooms.forEach(function(r) {
      var isBboxSel = beSel === r.name;
      var isNavSel = inRoomView && selectedName === r.name;
      var isZoom = !inRoomView && ingState.zoomRoom === r.name;
      var active = (isBboxSel || isNavSel || isZoom)
        ? 'font-weight:bold;color:var(--accent);' : 'color:var(--text-dim);';
      var dims = r.width_cm + 'x' + r.depth_cm;
      var manualTag = r.manual ? ' <span style="font-size:9px;color:var(--accent2,#c8a050);">M</span>' : '';
      html += '<div style="display:flex;align-items:center;gap:4px;padding:2px 4px 2px 4px;margin-right:16px;' + active +
        '"><span style="flex:1;cursor:pointer;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" data-ing-room="' + r.name + '">' +
        r.name + manualTag + ' <span style="font-size:10px;color:var(--text-dim);">' + dims + '</span></span>' +
        '<span class="room-del" data-ing-del="' + r.name +
        '" title="Delete room" style="cursor:pointer;color:var(--bad);padding:0 6px;font-size:14px;font-weight:bold;flex-shrink:0;">&times;</span></div>';
    });
    // "All" entry — always visible, returns to plan view
    var allActive = (!inRoomView && !ingState.zoomRoom)
      ? 'font-weight:bold;color:var(--accent);' : 'color:var(--text-dim);';
    html = '<div style="padding:2px 4px;cursor:pointer;' + allActive +
      '" data-ing-room="">&#9664; All (' + rooms.length + ')</div>' + html;
    _wireRoomListEl(document.getElementById('ingRoomList'), html, 'import');
    _wireRoomListEl(document.getElementById('rvRoomList'), html, 'review');
  }

  function _wireRoomListEl(listEl, html, context) {
    if (!listEl) return;
    listEl.innerHTML = html;
    if (context === 'review') {
      listEl.querySelectorAll('.room-del').forEach(function(el) { el.remove(); });
    }
    // Auto-scroll to selected room in both Import and Review
    var selected = listEl.querySelector('[style*="font-weight:bold"]');
    if (selected) selected.scrollIntoView({ block: 'nearest' });
    listEl.querySelectorAll('[data-ing-room]').forEach(function(el) {
      el.addEventListener('click', function() {
        var name = this.dataset.ingRoom;
        if (name) {
          // If bbox editor is active, switch selection to this room
          if (ingState.bboxEditor.selectedName !== null) {
            var listSelRoom = ingState.rooms.find(function(r) { return r.name === name; });
            ingState.bboxEditor.selectedName = name;
            ingState.bboxEditor.sessionStartBbox = listSelRoom ? listSelRoom.bbox_px.slice() : null;
            ingState.bboxEditor.mode = 'idle';
            ingState.bboxEditor.dragStart = null;
            updateIngRoomList();
            renderIngestion();
            return;
          }
          // Otherwise navigate to room view
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
    listEl.querySelectorAll('[data-ing-del]').forEach(function(el) {
      el.addEventListener('click', function(e) {
        e.stopPropagation();
        var name = this.dataset.ingDel;
        deleteIngRoom(name);
      });
    });
  }

  // --- Manual add / delete a room ---
  // Staging flow: read ID from #ingNewRoomId, compute stub size/position,
  // push to ingState.rooms, select for bbox editing immediately.
  function addIngRoom() {
    var input = document.getElementById('ingNewRoomId');
    var helpEl = document.getElementById('ingAddRoomHelp');

    var ERR_COLOR = 'var(--bad)';
    var OK_COLOR = 'var(--text-dim)';
    var OK_MSG = 'Stub placed above the plan. Drag body to move, drag corners to resize.';

    function showHelp(msg, color) {
      if (helpEl) { helpEl.textContent = msg; helpEl.style.color = color; }
    }

    if (!input) return;
    var name = input.value.trim();
    if (!name) {
      // Auto-increment: find max numeric ID among existing rooms
      var maxId = 0;
      ingState.rooms.forEach(function(r) {
        var n = parseInt(r.name, 10);
        if (!isNaN(n) && n > maxId) maxId = n;
      });
      var suggested = String(maxId + 1);
      name = prompt('Enter room ID:', suggested);
      if (!name) return;
      name = name.trim();
      if (!name) return;
      input.value = name;
    }
    if (ingState.rooms.some(function(r) { return r.name === name; })) {
      showHelp('⚠ Room "' + name + '" already exists.', ERR_COLOR);
      return;
    }
    showHelp(OK_MSG, OK_COLOR);

    // Stub size: average of existing rooms, or fallback 400×500 cm
    var wCm = 400, dCm = 500;
    if (ingState.rooms.length > 0) {
      var totalW = 0, totalD = 0;
      ingState.rooms.forEach(function(r) { totalW += (r.width_cm || 0); totalD += (r.depth_cm || 0); });
      wCm = Math.round(totalW / ingState.rooms.length);
      dCm = Math.round(totalD / ingState.rooms.length);
      if (wCm < 50) wCm = 400;
      if (dCm < 50) dCm = 500;
    }

    var scale = ingState.scale || 0.5;  // cm/px
    var pxPerCm = 1.0 / scale;
    var wPx = Math.round(wCm * pxPerCm);
    var hPx = Math.round(dCm * pxPerCm);

    // Position: above the bounding box of all existing rooms, 50 cm margin
    var x0, y0;
    var marginPx = Math.round(50 * pxPerCm);
    if (ingState.rooms.length > 0) {
      var minX = Infinity, minY = Infinity, maxX = -Infinity;
      ingState.rooms.forEach(function(r) {
        if (r.bbox_px[0] < minX) minX = r.bbox_px[0];
        if (r.bbox_px[1] < minY) minY = r.bbox_px[1];
        if (r.bbox_px[2] > maxX) maxX = r.bbox_px[2];
      });
      x0 = Math.round((minX + maxX) / 2 - wPx / 2);
      y0 = Math.round(minY - hPx - marginPx);
    } else {
      var W = ingState.planW || 1920;
      var H = ingState.planH || 1080;
      x0 = Math.round(W / 2 - wPx / 2);
      y0 = Math.round(H / 2 - hPx / 2);
    }

    var x1 = x0 + wPx;
    var y1 = y0 + hPx;
    var cxPx = (x0 + x1) / 2;
    var cyPx = (y0 + y1) / 2;

    ingState.rooms.push({
      name: name,
      bbox_px: [x0, y0, x1, y1],
      width_px: wPx,
      height_px: hPx,
      width_cm: wCm,
      depth_cm: dCm,
      surface_m2: parseFloat(((wCm * dCm) / 10000).toFixed(2)),
      seed_px: [cxPx, cyPx],
      seed: [cxPx, cyPx],
      windows: [],
      openings: [],
      doors: [],
      exterior_faces: [],
      corridor_face: null,
      hits: [],
      manual: true,
    });

    // Immediately select the new stub for bbox editing
    var addedRoom = ingState.rooms.find(function(r) { return r.name === name; });
    ingState.bboxEditor.selectedName = name;
    ingState.bboxEditor.sessionStartBbox = addedRoom ? addedRoom.bbox_px.slice() : null;
    ingState.bboxEditor.mode = 'idle';
    ingState.bboxEditor.handle = null;
    ingState.bboxEditor.dragStart = null;

    // Clear input
    input.value = '';

    // Pan to show the stub if it is above the current viewport
    if (ingState.vb.y > y0 - marginPx) {
      ingState.vb = Object.assign({}, ingState.vb, { y: y0 - marginPx });
    }

    populateRoomsJson();
    updateIngRoomList();
    renderIngestion();

    // Re-trigger matching so the new room appears in Review/Design
    var json = document.getElementById('fpRoomsJson').value;
    if (json && typeof window.fpLoadAndMatch === 'function') {
      window.fpLoadAndMatch(json);
    }
  }
  window.addIngRoom = addIngRoom;

  function deleteIngRoom(name) {
    if (!confirm('Delete room "' + name + '"?')) return;
    var idx = ingState.rooms.findIndex(function (r) { return r.name === name; });
    if (idx < 0) return;
    ingState.rooms.splice(idx, 1);
    if (ingState.focusedRoom === name) ingState.focusedRoom = null;
    if (ingState.zoomRoom === name) ingState.zoomRoom = '';
    populateRoomsJson();
    updateIngRoomList();
    renderIngestion();

    var json = document.getElementById('fpRoomsJson').value;
    if (json && typeof window.fpLoadAndMatch === 'function') {
      window.fpLoadAndMatch(json);
    }
  }
  window.deleteIngRoom = deleteIngRoom;

  // --- Populate the rooms JSON textarea for matching ---
  function populateRoomsJson() {
    var textarea = document.getElementById('fpRoomsJson');
    if (!textarea) return;
    var rooms = ingState.rooms.map(function (r) {
      var windows = (r.windows || []).map(function (w) {
        return {
          face: w.face,
          offset_cm: Math.round(w.offset_px * ingState.scale),
          width_cm: Math.round(w.width_px * ingState.scale),
        };
      });
      var openings = (r.openings || []).map(function (o) {
        return {
          face: o.face,
          offset_cm: Math.round(o.offset_px * ingState.scale),
          width_cm: Math.round(o.width_px * ingState.scale),
          has_door: false,
        };
      });
      // Add doors as openings with has_door=true
      (r.doors || []).forEach(function (d) {
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

    // Full-viewport background to avoid white edges when viewbox extends beyond image
    els.push('<rect x="' + vb.x + '" y="' + vb.y + '" width="' + vb.w + '" height="' + vb.h +
      '" fill="#1e1e1e"/>');

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
      var mxS = Math.floor((vb.x - margin) / step1m) * step1m;
      var myS = Math.floor((vb.y - margin) / step1m) * step1m;
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
      // When focused on a room, hide all others
      if (ingState.focusedRoom && room.name !== ingState.focusedRoom) return;

      var x0 = room.bbox_px[0], y0 = room.bbox_px[1];
      var x1 = room.bbox_px[2], y1 = room.bbox_px[3];
      var w = x1 - x0, h = y1 - y0;
      var seedPx = room.seed_px || room.seed;
      var cx = seedPx ? seedPx[0] : (x0 + x1) / 2;
      var cy = seedPx ? seedPx[1] : (y0 + y1) / 2;

      // Rays
      if (show.vrays || show.hrays) {
        (room.hits || []).forEach(function (hit) {
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
        (room.hits || []).forEach(function (hit) {
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
        (room.windows || []).forEach(function (win) {
          drawWallFeature(els, x0, y0, x1, y1, win.face,
            win.offset_px, win.width_px, '#50b8d0', 1.5, '', ' stroke-linecap="round"');
        });
      }

      // Openings (light green dashed — same as renderRoomElements)
      if (show.opening) {
        (room.openings || []).forEach(function (op) {
          drawWallFeature(els, x0, y0, x1, y1, op.face,
            op.offset_px, op.width_px, '#80c060', 1, '4 3', '');
        });
      }

      // Doors (arc + leaf, same style as editor renderRoomElements)
      if (show.door) {
        (room.doors || []).forEach(function (d) {
          var jh = d.jamb_hinge_px, jf = d.jamb_free_px;
          if (jh == null || jf == null || isNaN(jh) || isNaN(jf)) return;
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
      var isBeSelected = ingState.bboxEditor.selectedName === room.name;
      var bodyCursor = isBeSelected ? 'move' : 'pointer';
      els.push('<rect x="' + x0 + '" y="' + y0 + '" width="' + w +
        '" height="' + h + '" fill="transparent" stroke="none" ' +
        'style="cursor:' + bodyCursor + ';" data-room="' + room.name +
        '" data-bbox-body="' + room.name + '"/>');
    });

    // Bbox editor overlay — dashed selection border + corner handles
    var be = ingState.bboxEditor;
    if (be.selectedName) {
      var selRoom = null;
      ingState.rooms.forEach(function(r) { if (r.name === be.selectedName) selRoom = r; });
      if (selRoom) {
        var bx0 = selRoom.bbox_px[0], by0 = selRoom.bbox_px[1];
        var bx1 = selRoom.bbox_px[2], by1 = selRoom.bbox_px[3];
        // Selection dashed border
        els.push('<rect x="' + bx0 + '" y="' + by0 +
          '" width="' + (bx1 - bx0) + '" height="' + (by1 - by0) +
          '" fill="none" stroke="#58c080" stroke-width="2" stroke-dasharray="4 4"' +
          ' style="pointer-events:none;"/>');
        // Corner handles (10 SVG units square)
        var hs = 10;
        var corners = [
          { h: 'nw', cx: bx0, cy: by0, cur: 'nw-resize' },
          { h: 'ne', cx: bx1, cy: by0, cur: 'ne-resize' },
          { h: 'sw', cx: bx0, cy: by1, cur: 'sw-resize' },
          { h: 'se', cx: bx1, cy: by1, cur: 'se-resize' },
        ];
        corners.forEach(function(c) {
          els.push('<rect x="' + (c.cx - hs / 2) + '" y="' + (c.cy - hs / 2) +
            '" width="' + hs + '" height="' + hs +
            '" fill="#58c080" stroke="none"' +
            ' data-bbox-handle="' + c.h + '" data-bbox-room="' + be.selectedName + '"' +
            ' style="cursor:' + c.cur + ';"/>');
        });
      }
    }

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
          '" stroke="' + stroke + '" stroke-width="1" style="cursor:pointer;" data-merge="' + key + '">' +
          '<title>Add the combination of the two adjacent rooms to the list of rooms to be designed as if the wall between the two would have been removed</title>' +
          '</rect>');
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

    // Mousedown on bbox body: select or start move
    svg.querySelectorAll('[data-bbox-body]').forEach(function(el) {
      el.addEventListener('mousedown', function(e) {
        if (e.button !== 0) return;
        e.stopPropagation();  // prevent pan from starting
        var name = this.dataset.bboxBody;
        var be = ingState.bboxEditor;
        if (be.selectedName === name) {
          // Start moving
          var room = ingState.rooms.find(function(r) { return r.name === name; });
          if (!room) return;
          var p = screenToIngSvg(e);
          be.preDragBbox = room.bbox_px.slice();
          be.mode = 'moving';
          be.dragStart = { mouseX: p.x, mouseY: p.y, bbox: room.bbox_px.slice() };
        } else {
          // Select this room for bbox editing
          var clickSelRoom = ingState.rooms.find(function(r) { return r.name === name; });
          be.selectedName = name;
          be.sessionStartBbox = clickSelRoom ? clickSelRoom.bbox_px.slice() : null;
          be.mode = 'idle';
          be.handle = null;
          be.dragStart = null;
          renderIngestion();
        }
      });
      // dblclick is handled via delegated listener on ingSvg (setupZoomPan)
    });

    // Mousedown on corner handle: start resize
    svg.querySelectorAll('[data-bbox-handle]').forEach(function(el) {
      el.addEventListener('mousedown', function(e) {
        if (e.button !== 0) return;
        e.stopPropagation();
        var handle = this.dataset.bboxHandle;
        var roomName = this.dataset.bboxRoom;
        var room = ingState.rooms.find(function(r) { return r.name === roomName; });
        if (!room) return;
        var p = screenToIngSvg(e);
        var be = ingState.bboxEditor;
        be.preDragBbox = room.bbox_px.slice();
        be.mode = 'resizing';
        be.handle = handle;
        be.dragStart = { mouseX: p.x, mouseY: p.y, bbox: room.bbox_px.slice() };
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

  // Recompute a room's width_cm/depth_cm/surface_m2 from its bbox_px + ingState.scale.
  function _updateRoomDims(room) {
    var b = room.bbox_px;
    var wPx = b[2] - b[0];
    var hPx = b[3] - b[1];
    room.width_px = wPx;
    room.height_px = hPx;
    room.width_cm = Math.round(wPx * ingState.scale);
    room.depth_cm = Math.round(hPx * ingState.scale);
    room.surface_m2 = parseFloat(((room.width_cm * room.depth_cm) / 10000).toFixed(2));
  }

  function setupZoomPan() {
    var svg = document.getElementById('ingSvg');
    if (!svg) return;

    // Delegated dblclick: navigate to Review (survives re-renders)
    svg.addEventListener('dblclick', function(e) {
      // Use bbox editor selection (set by the 1st mousedown) rather than e.target
      // which may point to a different element after the re-render
      var name = ingState.bboxEditor.selectedName;
      if (!name) {
        var body = e.target.closest('[data-bbox-body]');
        if (!body) return;
        name = body.dataset.bboxBody;
      }
      e.stopPropagation();
      ingState.bboxEditor.selectedName = null;
      ingState.bboxEditor.mode = 'idle';
      if (window.fpData) {
        var rooms = window.fpData.rooms || [];
        for (var i = 0; i < rooms.length; i++) {
          if (rooms[i].name === name) {
            window.fpData.currentIdx = i;
            break;
          }
        }
      }
      var reviewBtn = document.querySelector('.tab-btn[data-tab="fpReview"]');
      if (reviewBtn) reviewBtn.click();
    });

    svg.addEventListener('wheel', function (e) {
      e.preventDefault();
      var factor = e.deltaY > 0 ? 1.15 : 0.87;
      var vb = ingState.vb;
      // Clamp: don't zoom out beyond 2x the plan size
      if (factor > 1) {
        var maxW = (ingState.planW || 1000) * 2;
        if (vb.w * factor > maxW) return;
      }
      var rect = svg.getBoundingClientRect();
      var mx = vb.x + (e.clientX - rect.left) / rect.width * vb.w;
      var my = vb.y + (e.clientY - rect.top) / rect.height * vb.h;
      vb.x = mx - (mx - vb.x) * factor;
      vb.y = my - (my - vb.y) * factor;
      vb.w *= factor;
      vb.h *= factor;
      renderIngestion();
    }, { passive: false });

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

    // Click on SVG background: deselect bbox editor (attached once here)
    svg.addEventListener('click', function(e) {
      var be = ingState.bboxEditor;
      if (!be.selectedName) return;
      if (!e.target.dataset.bboxBody && !e.target.dataset.bboxHandle) {
        be.selectedName = null;
        be.sessionStartBbox = null;
        be.mode = 'idle';
        be.dragStart = null;
        renderIngestion();
      }
    });
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
      var tab = document.getElementById('tabFpImport');
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

  // --- Init ---
  document.addEventListener('DOMContentLoaded', function () {
    setupToggles();
    setupZoomPan();

    // Keyboard shortcuts for bbox editor (arrows = move, Delete = remove, Escape = deselect)
    document.addEventListener('keydown', function(e) {
      // Ignore when focus is in a form field
      var tag = document.activeElement && document.activeElement.tagName;
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;

      var be = ingState.bboxEditor;

      if (e.key === 'Escape') {
        if (be.selectedName) {
          // Restore room to position at session-start (before first drag of this selection).
          // preDragBbox handles Enter-cancel for the current drag; sessionStartBbox handles
          // Escape-restore across multiple successive drags.
          var cancelRoom = ingState.rooms.find(function(r) { return r.name === be.selectedName; });
          if (cancelRoom && be.sessionStartBbox) {
            cancelRoom.bbox_px = be.sessionStartBbox.slice();
            _updateRoomDims(cancelRoom);
          }
          // Cancel and deselect
          be.mode = 'idle';
          be.handle = null;
          be.dragStart = null;
          be.preDragBbox = null;
          be.sessionStartBbox = null;
          be.selectedName = null;
          populateRoomsJson();
          updateIngRoomList();
          renderIngestion();
        }
        return;
      }

      if (e.key === 'Enter') {
        if (be.selectedName) {
          // Commit and deselect
          be.mode = 'idle';
          be.handle = null;
          be.dragStart = null;
          be.preDragBbox = null;
          be.sessionStartBbox = null;
          be.selectedName = null;
          populateRoomsJson();
          updateIngRoomList();
          renderIngestion();
        }
        return;
      }

      if (!be.selectedName) return;

      if (e.key === 'Delete' || e.key === 'Backspace') {
        e.preventDefault();
        deleteIngRoom(be.selectedName);
        return;
      }

      var arrows = { ArrowUp: [0, -1], ArrowDown: [0, 1], ArrowLeft: [-1, 0], ArrowRight: [1, 0] };
      if (!arrows[e.key]) return;
      e.preventDefault();

      // TODO: use window.GRID_STEP_CM if exposed by editor.js; fallback to 10 cm
      var stepCm = (typeof window.GRID_STEP_CM === 'number' ? window.GRID_STEP_CM : 10);
      var stepPx = stepCm / (ingState.scale || 0.5);
      var dir = arrows[e.key];
      var dx = dir[0] * stepPx;
      var dy = dir[1] * stepPx;

      var room = ingState.rooms.find(function(r) { return r.name === be.selectedName; });
      if (!room) return;
      var b = room.bbox_px;
      var nx0 = b[0] + dx, ny0 = b[1] + dy, nx1 = b[2] + dx, ny1 = b[3] + dy;
      room.bbox_px = [nx0, ny0, nx1, ny1];
      room.x0 = nx0; room.y0 = ny0; room.x1 = nx1; room.y1 = ny1;
      var cxNew = (nx0 + nx1) / 2, cyNew = (ny0 + ny1) / 2;
      room.seed_px = [cxNew, cyNew];
      room.seed = [cxNew, cyNew];
      populateRoomsJson();
      updateIngRoomList();
      renderIngestion();
    });

    // Global bbox drag: mousemove + mouseup
    window.addEventListener('mousemove', function(e) {
      var be = ingState.bboxEditor;
      if (!be.selectedName || be.mode === 'idle' || !be.dragStart) return;
      var p = screenToIngSvg(e);
      var dx = p.x - be.dragStart.mouseX;
      var dy = p.y - be.dragStart.mouseY;
      var orig = be.dragStart.bbox;
      var MIN_PX = 50;
      var room = ingState.rooms.find(function(r) { return r.name === be.selectedName; });
      if (!room) return;
      var nx0 = orig[0], ny0 = orig[1], nx1 = orig[2], ny1 = orig[3];
      if (be.mode === 'moving') {
        nx0 = orig[0] + dx; ny0 = orig[1] + dy;
        nx1 = orig[2] + dx; ny1 = orig[3] + dy;
      } else if (be.mode === 'resizing') {
        if (be.handle === 'nw') {
          nx0 = Math.min(orig[2] - MIN_PX, orig[0] + dx);
          ny0 = Math.min(orig[3] - MIN_PX, orig[1] + dy);
        } else if (be.handle === 'ne') {
          nx1 = Math.max(orig[0] + MIN_PX, orig[2] + dx);
          ny0 = Math.min(orig[3] - MIN_PX, orig[1] + dy);
        } else if (be.handle === 'sw') {
          nx0 = Math.min(orig[2] - MIN_PX, orig[0] + dx);
          ny1 = Math.max(orig[1] + MIN_PX, orig[3] + dy);
        } else if (be.handle === 'se') {
          nx1 = Math.max(orig[0] + MIN_PX, orig[2] + dx);
          ny1 = Math.max(orig[1] + MIN_PX, orig[3] + dy);
        }
      }
      room.bbox_px = [nx0, ny0, nx1, ny1];
      // Update derived fields live
      var wPx = nx1 - nx0;
      var hPx = ny1 - ny0;
      room.width_px = wPx;
      room.height_px = hPx;
      room.width_cm = Math.round(wPx * ingState.scale);
      room.depth_cm = Math.round(hPx * ingState.scale);
      room.surface_m2 = parseFloat(((room.width_cm * room.depth_cm) / 10000).toFixed(2));
      var cxNew = (nx0 + nx1) / 2;
      var cyNew = (ny0 + ny1) / 2;
      room.seed_px = [cxNew, cyNew];
      room.seed = [cxNew, cyNew];
      renderIngestion();
    });

    window.addEventListener('mouseup', function() {
      var be = ingState.bboxEditor;
      if (be.mode === 'idle') return;
      be.mode = 'idle';
      be.handle = null;
      be.dragStart = null;
      be.preDragBbox = null;
      // Commit: update JSON + list
      populateRoomsJson();
      updateIngRoomList();
      renderIngestion();
    });

    // Peuplement du dropdown et auto-import au changement de sélection
    loadPlansDropdown();
    var planSel = document.getElementById('ingPlanIdSelect');
    if (planSel) {
      planSel.addEventListener('change', function () {
        if (planSel.value) extractRooms();
      });
    }

    var btnAddRoom = document.getElementById('ingBtnAddRoom');
    if (btnAddRoom) btnAddRoom.addEventListener('click', addIngRoom);

    var newRoomInput = document.getElementById('ingNewRoomId');
    if (newRoomInput) {
      newRoomInput.addEventListener('keypress', function(e) {
        if (e.key === 'Enter') addIngRoom();
      });
    }

    var btnDevExport = document.getElementById('ingBtnDevExportV3');
    if (btnDevExport) btnDevExport.addEventListener('click', devExportV3Json);
  });

  // --- DEV · Export v3 JSON (see docs/specs/PREPROCESSED_JSON_SPEC.md §5) ---
  // Serializes ingState.rooms into the v3 JSON format and triggers a browser
  // download. Development helper — not part of the production save flow.
  function devExportV3Json() {
    if (!ingState.rooms || ingState.rooms.length === 0) {
      alert('No rooms to export. Load a floor plan first.');
      return;
    }

    var hdr = document.getElementById('hdrCurrentPlan');
    var planName = hdr ? hdr.textContent.trim() : '';
    var fileHint = planName ? (planName + '.png') : 'plan.png';

    // v3 format: rooms is an object keyed by room id. No `id` / `code` fields
    // inside values (id is the key, code is a Settings filter). See
    // docs/specs/PREPROCESSED_JSON_SPEC.md.
    var roomsDict = {};
    ingState.rooms.forEach(function (r) {
      var roomId = r.name || '';
      if (!roomId) return;

      // Cartouche seed: prefer seed_px, else seed, else bbox center
      var seed;
      if (Array.isArray(r.seed_px) && r.seed_px.length === 2) {
        seed = [Math.round(r.seed_px[0]), Math.round(r.seed_px[1])];
      } else if (Array.isArray(r.seed) && r.seed.length === 2) {
        seed = [Math.round(r.seed[0]), Math.round(r.seed[1])];
      } else if (Array.isArray(r.bbox_px) && r.bbox_px.length === 4) {
        seed = [
          Math.round((r.bbox_px[0] + r.bbox_px[2]) / 2),
          Math.round((r.bbox_px[1] + r.bbox_px[3]) / 2),
        ];
      } else {
        seed = [0, 0];
      }

      // Surface as string "N.NN m2" — v3 keeps the string form, OLS parses on read
      var surfaceStr = '';
      if (typeof r.surface_m2 === 'number' && r.surface_m2 > 0) {
        surfaceStr = r.surface_m2.toFixed(2) + ' m2';
      }

      // v3 rename: seed_px [x,y] → seed_x / seed_y (two scalar fields)
      var roomObj = { surface: surfaceStr, seed_x: seed[0], seed_y: seed[1] };

      if (Array.isArray(r.bbox_px) && r.bbox_px.length === 4) {
        roomObj.bbox_px = r.bbox_px.map(function (v) { return Math.round(v); });
      }

      // canonical_top_face: derive from the primary door's face.
      // primary = first door in the list (OCR detects at most one main door per room).
      // opposite face becomes the canonical top (D-83: corridor at bottom, windows at top).
      if (Array.isArray(r.doors) && r.doors.length > 0 && r.doors[0].face) {
        var OPPOSITE = { north: 'south', south: 'north', east: 'west', west: 'east' };
        roomObj.canonical_top_face = OPPOSITE[r.doors[0].face] || 'north';
      }

      if (Array.isArray(r.doors) && r.doors.length > 0) {
        roomObj.doors = r.doors.map(function (d) {
          // v3 rename: label_px [x,y] → label_x / label_y. The OCR pipeline
          // doesn't produce a door label seed — omitted entirely per omission rule.
          var o = { face: d.face, offset_px: d.offset_px, width_px: d.width_px };
          if (d.hinge_side) o.hinge_side = d.hinge_side;
          if (typeof d.opens_inward === 'boolean') o.opens_inward = d.opens_inward;
          return o;
        });
      }
      if (Array.isArray(r.openings) && r.openings.length > 0) {
        roomObj.openings = r.openings.map(function (o) {
          return { face: o.face, offset_px: o.offset_px, width_px: o.width_px };
        });
      }
      if (Array.isArray(r.windows) && r.windows.length > 0) {
        roomObj.windows = r.windows.map(function (w) {
          return { face: w.face, offset_px: w.offset_px, width_px: w.width_px };
        });
      }
      roomsDict[roomId] = roomObj;
    });

    // Omission convention: optional metadata (building_id, floor_id,
    // north_angle_deg) is absent from the JSON, not empty-string/0.
    var out = {
      file: fileHint,
      page_width_px: ingState.planW || 0,
      page_height_px: ingState.planH || 0,
      rooms: roomsDict,
    };

    var json = JSON.stringify(out, null, 2);
    var blob = new Blob([json], { type: 'application/json' });
    var url = URL.createObjectURL(blob);
    var a = document.createElement('a');
    a.href = url;
    var stem = planName || 'plan';
    a.download = stem + '.json';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }
  window.devExportV3Json = devExportV3Json;


  // --- Import préprocessé (plan_id ou upload fichiers) ---
  function extractRoomsPreprocessed() {
    var sel = document.getElementById('ingPlanIdSelect');
    var planId = sel ? sel.value : '';
    var status = document.getElementById('ingStatus');
    var debugLog = document.getElementById('ingDebugLog');

    if (status) status.textContent = 'Import...';

    var formData = new FormData();

    if (!planId) {
      if (status) status.textContent = 'Error: no plan selected';
      return;
    }
    // Mode plan_id : le backend résout les chemins depuis project/plans/
    formData.append('plan_id', planId);

    fetch('/api/import/preprocessed', { method: 'POST', body: formData })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (data.error) {
          if (status) status.textContent = 'Error: ' + data.error;
          return;
        }
        ingState.rooms = data.rooms || [];
        if (status) status.textContent = ingState.rooms.length + ' room(s) imported';

        // Header badge
        if (planId) {
          var hdrEl2 = document.getElementById('hdrCurrentPlan');
          if (hdrEl2) hdrEl2.textContent = planId;
          var btnSave2 = document.getElementById('btnSavePlan');
          if (btnSave2) btnSave2.style.display = '';
          var btnClose2 = document.getElementById('btnClosePlan');
          if (btnClose2) btnClose2.style.display = '';
          var eraseWrap2 = document.getElementById('eraseWrapper');
          if (eraseWrap2) eraseWrap2.style.display = '';
        }

        // Canvas dimensions, scale, viewbox — alignés sur le flux OCR
        if (Array.isArray(data.image_size) && data.image_size.length === 2) {
          ingState.planW = data.image_size[0];
          ingState.planH = data.image_size[1];
        }
        if (typeof data.scale_cm_per_px === 'number' && data.scale_cm_per_px > 0) {
          ingState.scale = data.scale_cm_per_px;
        }
        // Focus auto : si des pièces ont des bbox, cadrer sur leur enveloppe
        var hasBoxes = ingState.rooms.some(function(r) { return r.bbox_px && r.bbox_px[2] > r.bbox_px[0]; });
        if (hasBoxes) {
          var minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
          ingState.rooms.forEach(function(r) {
            if (!r.bbox_px) return;
            if (r.bbox_px[0] < minX) minX = r.bbox_px[0];
            if (r.bbox_px[1] < minY) minY = r.bbox_px[1];
            if (r.bbox_px[2] > maxX) maxX = r.bbox_px[2];
            if (r.bbox_px[3] > maxY) maxY = r.bbox_px[3];
          });
          var pad = Math.max(maxX - minX, maxY - minY) * 0.10;
          ingState.vb = { x: minX - pad, y: minY - pad, w: maxX - minX + 2 * pad, h: maxY - minY + 2 * pad };
        } else {
          ingState.vb = { x: 0, y: 0, w: ingState.planW || 1000, h: ingState.planH || 1000 };
        }

        // Overlay par défaut = le PNG enhanced s'il est disponible, sinon l'overlay standard.
        // (le toggle enhanced/plain sera ajouté plus tard — cf TODO)
        var overlaySrc = data.enhanced_path || data.image_path || data.overlay_path;
        if (overlaySrc) {
          ingState.planUrl = '/api/image?path=' +
            encodeURIComponent(overlaySrc);
        }

        renderIngestion();
        populateRoomsJson();
        updateIngRoomList();

        var json = document.getElementById('fpRoomsJson').value;
        if (json && typeof window.fpLoadAndMatch === 'function') {
          window.fpLoadAndMatch(json);
        }

        // fpOverlay pour Review/Design (même mécanique que flux OCR)
        window.fpOverlay = {
          dataUrl: ingState.planUrl,
          pxPerCm: ingState.scale ? 1.0 / ingState.scale : 1.0,
          imgW: ingState.planW,
          imgH: ingState.planH,
        };
        var fpTog = document.getElementById('fpOverlayToggle');
        if (fpTog) fpTog.checked = true;
        var rvTog = document.getElementById('rvOverlayToggle');
        if (rvTog) rvTog.checked = true;
      })
      .catch(function (e) {
        if (status) status.textContent = 'Error: ' + e;
      });
  }

  // Expose for external use
  window.ingestionState = ingState;
  window.renderIngestion = renderIngestion;

})();
