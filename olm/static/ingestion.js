/**
 * ingestion.js — Floor plan ingestion viewer for the Import tab.
 *
 * Calls /api/ingestion/extract, renders results as SVG overlay
 * on the floor plan image. Uses same color conventions as the
 * pattern editor (renderRoomElements).
 */
(function () {
  'use strict';

  // --- Shared re-analyze canonicalisation (D-112/D-113) ---------------------
  // Used by both the unitary room re-analyze (init_rvtool.js) and the batch
  // floor re-analyze below. Takes the absolute-coord backend payload and
  // returns canonical-space (corridor always south) features + dims + debug
  // geometry. The caller handles merge with manual/preserved items.
  // R-12 C2 : la rotation abs → canon est déléguée à canonicalIO.fromStorage
  // (source unique). Ce helper encapsule :
  //   1) détection du corridor (porte principale ou prevCorridorFace),
  //   2) construction d'un room-like absolu à partir du payload backend,
  //   3) passage par fromStorage pour obtenir la géométrie canonique,
  //   4) post-traitement des points / rectangles relatifs au bbox
  //      (hits / seed / auto_door_masks — non gérés par fromStorage).
  function computeCanonicalReanalyzeResult(data, prevCorridorFace, scale) {
    var corridor = (data.doors && data.doors.length && data.doors[0].face)
      ? data.doors[0].face : (prevCorridorFace || '');
    var bbox = data.bbox_px || null;
    var absW = bbox ? (bbox[2] - bbox[0]) * scale : 0;
    var absD = bbox ? (bbox[3] - bbox[1]) * scale : 0;

    // --- 1) Construction du room-like absolu + canonicalisation ---
    function slim(o) {
      return { face: o.face, offset_cm: o.offset_cm, width_cm: o.width_cm };
    }
    function slimDoor(d) {
      return {
        face: d.face, offset_cm: d.offset_cm, width_cm: d.width_cm,
        hinge_side: d.hinge_side, opens_inward: d.opens_inward !== false,
      };
    }
    var roomAbs = {
      corridor_face: corridor,
      width_cm: Math.round(absW),
      depth_cm: Math.round(absD),
      bbox_px: bbox,
      seed_px: data.seed_px,
      windows: (data.windows || []).map(slim),
      openings: (data.openings || []).map(slim),
      doors: (data.doors || []).map(slimDoor),
    };
    var canon = (window.canonicalIO && window.canonicalIO.fromStorage)
      ? window.canonicalIO.fromStorage(roomAbs, scale)
      : { width_cm: roomAbs.width_cm, depth_cm: roomAbs.depth_cm,
          windows: [], openings: [], doors: [] };

    function feat(e, extra) {
      return Object.assign({
        face: e.face,
        offset_cm: Math.max(0, Math.round(e.offset_cm || 0)),
        width_cm: Math.max(0, Math.round(e.width_cm || 0)),
        origin: 'auto',
      }, extra || {});
    }
    // D-122 P4 : openings et doors sortent séparés (has_door banni du state).
    var windowsCanon = (canon.windows || []).map(function (w) { return feat(w); });
    var openingsCanon = (canon.openings || []).map(function (o) {
      return feat(o);
    });
    var doorsCanon = (canon.doors || []).map(function (d) {
      return feat(d, {
        hinge_side: d.hinge_side,
        opens_inward: d.opens_inward !== false,
      });
    });

    // --- 2) Post-traitement points / rectangles relatifs au bbox ---
    // fromStorage ne touche pas hits / seed / auto_door_masks_px (ils sont
    // exprimés en px image, pas en cm room-local). Délégation à canonicalIO
    // (D-122 P6 : source unique, plus de rotation ad-hoc locale).
    var _rotP = window.canonicalIO.rotatePoint;
    var _rotR = window.canonicalIO.rotateRect;
    var hits = null, seed_cm = null;
    if (data.hits && bbox) {
      var hbx0 = bbox[0], hby0 = bbox[1];
      hits = data.hits.map(function (h) {
        var p = _rotP(
          { x: (h[0] - hbx0) * scale, y: (h[1] - hby0) * scale },
          corridor, absW, absD);
        return { x_cm: p.x, y_cm: p.y };
      });
      if (data.seed_px) {
        var sC = _rotP(
          { x: (data.seed_px[0] - hbx0) * scale,
            y: (data.seed_px[1] - hby0) * scale },
          corridor, absW, absD);
        seed_cm = { x_cm: sC.x, y_cm: sC.y };
      }
    }
    var masks = null;
    if (data.auto_door_masks_px && bbox) {
      var rbx0 = bbox[0], rby0 = bbox[1];
      masks = data.auto_door_masks_px.map(function (rc) {
        var rr = _rotR(
          { x: (rc[0] - rbx0) * scale, y: (rc[1] - rby0) * scale,
            width: (rc[2] - rc[0]) * scale, depth: (rc[3] - rc[1]) * scale },
          corridor, absW, absD);
        return { x_cm: rr.x, y_cm: rr.y,
                 width_cm: rr.width, depth_cm: rr.depth };
      });
    }
    return {
      corridor_face: corridor,
      bbox_px: bbox,
      width_cm: Math.round(canon.width_cm || 0),
      depth_cm: Math.round(canon.depth_cm || 0),
      windows: windowsCanon,
      openings: openingsCanon,
      doors: doorsCanon,
      hits: hits,
      seed_cm: seed_cm,
      auto_door_masks: masks,
    };
  }
  window.computeCanonicalReanalyzeResult = computeCanonicalReanalyzeResult;

  // --- Zone re-anchoring after re-analyze -----------------------------------
  // Après un re-analyze, le bbox détecté (et éventuellement corridor_face_abs)
  // peut changer. Les zones (exclusion / transparent) sont stockées en repère
  // CANONIQUE room-local ; pour qu'elles restent sur les mêmes features du
  // plan (position absolue image), il faut les reprojeter.
  //
  // Pipeline : canon (old) → abs-room-local (old) → abs-image-cm → abs-room-
  // local (new) → canon (new). Utilise canonicalIO.rotateRectInv /
  // rotateRect (source unique des matrices).
  //
  // @param {Array} zones    - zones canoniques [{x_cm,y_cm,width_cm,depth_cm}].
  // @param {Array} oldBbox  - bbox absolu avant re-analyze [x0,y0,x1,y1] (px).
  // @param {string} oldCf   - corridor_face_abs avant re-analyze.
  // @param {Array} newBbox  - bbox absolu après re-analyze [x0,y0,x1,y1] (px).
  // @param {string} newCf   - corridor_face_abs après re-analyze.
  // @param {number} scale   - cm/px (ingState.scale).
  // @returns {Array} zones canoniques reprojetées.
  function reanchorCanonicalZones(zones, oldBbox, oldCf, newBbox, newCf, scale) {
    if (!zones || !zones.length) return zones || [];
    if (!oldBbox || !newBbox || !(scale > 0)) return zones;
    var cio = window.canonicalIO;
    if (!cio || !cio.rotateRectInv || !cio.rotateRect) return zones;
    var oldAbsW = (oldBbox[2] - oldBbox[0]) * scale;
    var oldAbsD = (oldBbox[3] - oldBbox[1]) * scale;
    var newAbsW = (newBbox[2] - newBbox[0]) * scale;
    var newAbsD = (newBbox[3] - newBbox[1]) * scale;
    var dx = (oldBbox[0] - newBbox[0]) * scale;
    var dy = (oldBbox[1] - newBbox[1]) * scale;
    return zones.map(function (z) {
      var absOld = cio.rotateRectInv(
        { x: z.x_cm || 0, y: z.y_cm || 0,
          width: z.width_cm || 0, depth: z.depth_cm || 0 },
        oldCf || '', oldAbsW, oldAbsD);
      var absNew = { x: absOld.x + dx, y: absOld.y + dy,
                     width: absOld.width, depth: absOld.depth };
      var canon = cio.rotateRect(absNew, newCf || '', newAbsW, newAbsD);
      return {
        x_cm: Math.round(canon.x),
        y_cm: Math.round(canon.y),
        width_cm: Math.round(canon.width),
        depth_cm: Math.round(canon.depth),
      };
    });
  }
  window.reanchorCanonicalZones = reanchorCanonicalZones;

  // Convertit une liste de zones canoniques (room-local, corridor sud) vers
  // le repère ABSOLU room-local (corridor_face_abs = cfAbs). Utilisé avant
  // envoi au backend /api/room/reanalyze{,_batch} qui interprète les zones
  // comme abs-room-local (cf. extract.py:1757-1766).
  // Pour cfAbs ∈ {"", "south"} retourne l'identité.
  function canonicalZonesToAbs(zones, cfAbs, absW, absD) {
    if (!zones || !zones.length) return zones || [];
    var cio = window.canonicalIO;
    if (!cio || !cio.rotateRectInv) return zones;
    return zones.map(function (z) {
      var abs = cio.rotateRectInv(
        { x: z.x_cm || 0, y: z.y_cm || 0,
          width: z.width_cm || 0, depth: z.depth_cm || 0 },
        cfAbs || '', absW, absD);
      return {
        x_cm: abs.x, y_cm: abs.y,
        width_cm: abs.width, depth_cm: abs.depth,
      };
    });
  }
  window.canonicalZonesToAbs = canonicalZonesToAbs;

  // --- Drawing scale helpers (extracted to ingestion_scale.js, D-94 P4) ---
  var parseDrawingScale     = window.olmScale.parseDrawingScale;
  var computeCmPerPx        = window.olmScale.computeCmPerPx;
  var getDrawingScale       = window.olmScale.getDrawingScale;
  var getRenderDpi          = window.olmScale.getRenderDpi;
  var _suggestDrawingScale  = window.olmScale.suggestDrawingScale;

  /**
   * Show/hide plan-dependent UI sections and enable/disable Review+Design tabs.
   * Called after import or plan close.
   */
  function updatePlanDependentUI() {
    var hasRooms = ingState.rooms && ingState.rooms.length > 0;
    // Import panel sections — skip while the plan popup is open (it owns
    // the display state of these elements while active).
    var popupOpen = (function () {
      var pop = document.getElementById('ingPlanPopup');
      return pop && pop.style.display !== 'none';
    })();
    var sections = document.getElementById('ingPlanSections');
    if (sections && !popupOpen) sections.style.display = hasRooms ? '' : 'none';
    // Review and Design tabs: hidden when no plan loaded
    ['fpReview', 'lytDesign'].forEach(function(tab) {
      var btn = document.querySelector('.tab-btn[data-tab="' + tab + '"]');
      if (btn) btn.style.display = hasRooms ? '' : 'none';
    });
  }
  window.updatePlanDependentUI = updatePlanDependentUI;

  // --- State (D-94: owned by olmStore) ---
  // Full shape (rooms, show, vb, bboxEditor, …) is declared in store.js.
  var ingState = window.ingState;

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

  // --- Populate plan list (scrollable clickable items, filterable) ---
  var _plansCache = [];

  function _getSelectedPlan() {
    return ingState._selectedPlan || { id: '', mode: '' };
  }
  function _setSelectedPlan(id, mode) {
    ingState._selectedPlan = { id: id || '', mode: mode || '' };
    var disp = document.getElementById('ingPlanDisplayText');
    if (disp) disp.textContent = id || '— Select a plan —';
    _renderPlanList();
  }
  var _HIDE_IDS = ['ingPlanSections'];
  function _openPlanPopup() {
    var pop = document.getElementById('ingPlanPopup');
    if (!pop || pop.style.display !== 'none') return;
    pop.style.display = '';
    _HIDE_IDS.forEach(function (id) {
      var el = document.getElementById(id);
      if (!el) return;
      if (el._prevDisplay === undefined) el._prevDisplay = el.style.display;
      el.style.display = 'none';
    });
    var searchEl = document.getElementById('ingPlanSearch');
    if (searchEl) { searchEl.value = ''; _renderPlanList(); searchEl.focus(); }
  }
  function _closePlanPopup() {
    var pop = document.getElementById('ingPlanPopup');
    if (!pop || pop.style.display === 'none') return;
    pop.style.display = 'none';
    _HIDE_IDS.forEach(function (id) {
      var el = document.getElementById(id);
      if (el) el._prevDisplay = undefined;
    });
    // Reconsolider l'affichage selon l'état courant (rooms chargées ou non).
    updatePlanDependentUI();
  }

  function _renderPlanList() {
    var listEl = document.getElementById('ingPlanList');
    if (!listEl) return;
    var searchEl = document.getElementById('ingPlanSearch');
    var filter = (searchEl && searchEl.value || '').toLowerCase().trim();
    var selId = _getSelectedPlan().id;

    if (!_plansCache.length) {
      listEl.innerHTML =
        '<div style="padding:6px;color:var(--text-dim);">No plans available</div>';
      return;
    }
    var html = '';
    _plansCache.forEach(function (p) {
      if (filter && p.id.toLowerCase().indexOf(filter) === -1) return;
      var active = (p.id === selId);
      var style = 'padding:4px 6px;cursor:pointer;border-bottom:1px solid var(--border);';
      if (active) style += 'background:var(--accent);color:var(--bg);font-weight:bold;';
      html += '<div class="plan-item" data-plan-id="' + p.id + '" data-plan-mode="' +
        (p.effective_mode || 'ocr') + '" style="' + style + '">' +
        p.id + '</div>';
    });
    if (!html) {
      html = '<div style="padding:6px;color:var(--text-dim);">No match</div>';
    }
    listEl.innerHTML = html;
    listEl.querySelectorAll('.plan-item').forEach(function (el) {
      el.addEventListener('click', function () {
        _setSelectedPlan(this.dataset.planId, this.dataset.planMode);
        _closePlanPopup();
        extractRooms();
      });
    });
  }

  function populateDropdown(plans) {
    _plansCache = (plans || []).slice().sort(function (a, b) {
      return a.id.localeCompare(b.id, undefined, { sensitivity: 'base' });
    });
    _renderPlanList();
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
    var sel = _getSelectedPlan();
    var planId = sel.id;
    var debugLog = document.getElementById('ingDebugLog');
    if (!planId) {
      if (debugLog) debugLog.textContent = '[ERROR] No plan selected.';
      return;
    }

    var mode = sel.mode || 'ocr';
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
      _setSelectedPlan('', '');
      return;
    }

    var status = document.getElementById('ingStatus');
    if (status) status.textContent = 'Extracting...';

    var formData = new FormData();
    formData.append('plan_id', planId);
    var ds = getDrawingScale();
    if (ds) formData.append('drawing_scale', ds);
    formData.append('render_dpi', String(getRenderDpi()));

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
        ingState.planPath = data.image_path || "";
        ingState.planPathEnhanced = data.image_path || "";
        ingState.scale = data.scale_cm_per_px;
        _suggestDrawingScale(data.scale_cm_per_px);
        ingState.vb = { x: 0, y: 0, w: ingState.planW, h: ingState.planH };
        // Update header badge with selected plan ID
        var hdrEl = document.getElementById('hdrCurrentPlan');
        if (hdrEl) hdrEl.textContent = planId;
        var btnSave = document.getElementById('btnSavePlan');
        if (btnSave) btnSave.style.display = '';
        var btnExport = document.getElementById('btnExportPlan');
        if (btnExport) btnExport.style.display = '';
        var btnClose = document.getElementById('btnClosePlan');
        if (btnClose) btnClose.style.display = '';
        var eraseWrap = document.getElementById('eraseWrapper');
        if (eraseWrap) eraseWrap.style.display = '';
        var ingTb = document.getElementById('ingToolbar');
        if (ingTb) ingTb.style.display = '';
        if (status) status.textContent = ingState.rooms.length + ' rooms — scale ' +
          ingState.scale + ' cm/px';
        renderIngestion();
        populateRoomsJson();
        updateIngRoomList();
        updatePlanDependentUI();

        // Feed rooms into the floor plan pipeline (Review + Design)
        if (typeof window.fpLoadAndMatch === 'function') {
          window.fpLoadAndMatch(ingState.rooms);
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
  // window.ingState is already exposed by store.js (D-94).
  function updateIngRoomList() {
    var reviewSubtab = document.getElementById('tabFpReview');
    var designTab = document.getElementById('tabLytDesign');
    var inRoomView = (reviewSubtab && reviewSubtab.classList.contains('active')) ||
                     (designTab && designTab.classList.contains('active'));
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
    _wireRoomListEl(document.getElementById('fpDesignRoomList'), html, 'design');
  }

  function _wireRoomListEl(listEl, html, context) {
    if (!listEl) return;
    listEl.innerHTML = html;
    if (context === 'review' || context === 'design') {
      listEl.querySelectorAll('.room-del').forEach(function(el) { el.remove(); });
      // "All" entry (back to plan view) only makes sense in Import.
      var allEntry = listEl.querySelector('[data-ing-room=""]');
      if (allEntry) allEntry.remove();
    }
    // Auto-scroll to selected room
    var selected = listEl.querySelector('[style*="font-weight:bold"]');
    if (selected) selected.scrollIntoView({ block: 'nearest' });
    listEl.querySelectorAll('[data-ing-room]').forEach(function(el) {
      el.addEventListener('click', function() {
        var name = this.dataset.ingRoom;
        if (name) {
          if (window.fpData) {
            var rooms = window.fpData.rooms || [];
            for (var i = 0; i < rooms.length; i++) {
              if (rooms[i].name === name) {
                window.fpData.currentIdx = i;
                break;
              }
            }
          }
          if (context === 'design') {
            // Stay on Design, re-render current room
            if (window.fpRenderCurrent) window.fpRenderCurrent();
            if (window.rvRenderCurrent) window.rvRenderCurrent();
            updateIngRoomList();
          } else if (context === 'import') {
            // "All" entry handled below; named room → go to Review
            if (window.ingShowRoomView) window.ingShowRoomView();
          } else {
            if (window.ingShowRoomView) window.ingShowRoomView();
          }
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
    if (typeof window.fpLoadAndMatch === 'function') {
      window.fpLoadAndMatch(ingState.rooms);
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

    if (typeof window.fpLoadAndMatch === 'function') {
      window.fpLoadAndMatch(ingState.rooms);
    }
  }
  window.deleteIngRoom = deleteIngRoom;

  // populateRoomsJson (matching textarea) lives in ingestion_serialize.js
  // (R-12 C3). Exposé sur window, on récupère une référence locale pour les
  // nombreux call sites de ce module.
  var populateRoomsJson = window.populateRoomsJson;

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
      var gridParts = window.renderShared.gridSvg({
        vb: ingState.vb,
        cmPerPx: ingState.scale,
        marginRatio: 0.3,
      });
      gridParts.dots.forEach(function (s) { els.push(s); });
      gridParts.lines.forEach(function (s) { els.push(s); });
    }

    var show = ingState.show;
    var zoomRoom = ingState.zoomRoom;

    // R-12 / D-122 P1 : ingState.rooms est en repère canonique. Le Floor
    // overlay rend dans le repère ABSOLU (raster). toStorage(room, scale)
    // retourne une pièce absolue avec offset_px / width_px déjà recalculés.
    function _renderRoom(roomCanon) {
      if (roomCanon.corridor_face_abs !== undefined &&
          window.canonicalIO) {
        return window.canonicalIO.toStorage(roomCanon, ingState.scale);
      }
      return roomCanon;
    }

    ingState.rooms.forEach(function (roomCanon) {
      var room = _renderRoom(roomCanon);
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
          if (win.offset_px == null || win.width_px == null ||
              isNaN(win.offset_px) || isNaN(win.width_px)) return;
          drawWallFeature(els, x0, y0, x1, y1, win.face,
            win.offset_px, win.width_px, '#50b8d0', 1.5, '', ' stroke-linecap="round"');
        });
      }

      // Openings (light green dashed — same as renderRoomElements)
      if (show.opening) {
        (room.openings || []).forEach(function (op) {
          if (op.offset_px == null || op.width_px == null ||
              isNaN(op.offset_px) || isNaN(op.width_px)) return;
          if (show.bbox) eraseWallSegment(els, x0, y0, x1, y1, op.face, op.offset_px, op.width_px);
          drawWallFeature(els, x0, y0, x1, y1, op.face,
            op.offset_px, op.width_px, '#80c060', 1, '4 3', '');
        });
      }

      // Doors (arc + leaf) — delegate to render_shared.
      // Supports two door field conventions:
      //   OCR (test_comb):   jamb_hinge_px + jamb_free_px
      //   Preprocessed:      offset_px + width_px (same shape as openings)
      if (show.door) {
        (room.doors || []).forEach(function (d) {
          var jh, jf, doorOffsetFromStart, doorWidth;
          if (d.jamb_hinge_px != null && d.jamb_free_px != null &&
              !isNaN(d.jamb_hinge_px) && !isNaN(d.jamb_free_px)) {
            jh = d.jamb_hinge_px;
            jf = d.jamb_free_px;
            var along0_ocr = (d.face === 'south' || d.face === 'north') ? x0 : y0;
            doorOffsetFromStart = Math.min(jh, jf) - along0_ocr;
            doorWidth = Math.abs(jf - jh);
          } else if (d.offset_px != null && d.width_px != null &&
                     !isNaN(d.offset_px) && !isNaN(d.width_px)) {
            var along0 = (d.face === 'south' || d.face === 'north') ? x0 : y0;
            jh = along0 + d.offset_px;
            jf = along0 + d.offset_px + d.width_px;
            doorOffsetFromStart = d.offset_px;
            doorWidth = d.width_px;
          } else {
            return;
          }
          // Erase wall under the door bay so the opening shows through the bbox
          if (show.bbox) eraseWallSegment(els, x0, y0, x1, y1, d.face, doorOffsetFromStart, doorWidth);
          var swing = d.hinge_side || 'left';
          var inward = d.opens_inward !== false;
          // Resolve hinge/free coords from jambs + swing + face convention
          // (west wall inverts jh/jf selection, mirroring editor's logic).
          var swingLeft = (swing === 'left');
          var westInvert = (d.face === 'west');
          var hingeCoord = (swingLeft !== westInvert) ? jh : jf;
          var freeCoord  = (swingLeft !== westInvert) ? jf : jh;
          var wallCoord;
          if (d.face === 'south') wallCoord = y1;
          else if (d.face === 'north') wallCoord = y0;
          else if (d.face === 'east') wallCoord = x1;
          else /* west */ wallCoord = x0;
          var parts = window.renderShared.doorSvg(
            d.face, hingeCoord, freeCoord, wallCoord, swing, inward, 0);
          els.push(parts[0]);
          els.push(parts[1]);
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
          // Double-click detection: if 2nd mousedown on same room within 400ms → open in Review
          var now = Date.now();
          if (be._lastSelectTime && (now - be._lastSelectTime) < 400) {
            be._lastSelectTime = 0;
            be.selectedName = null;
            be.mode = 'idle';
            // Navigate to this room in Review
            if (window.fpData) {
              var fpRooms = window.fpData.rooms || [];
              for (var fi = 0; fi < fpRooms.length; fi++) {
                if (fpRooms[fi].name === name) { window.fpData.currentIdx = fi; break; }
              }
            }
            if (window.ingShowRoomView) window.ingShowRoomView();
            return;
          }
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
          be._lastSelectTime = Date.now();
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

    svg.addEventListener('wheel', function (e) {
      e.preventDefault();
      var factor = e.deltaY > 0 ? 1.15 : 0.87;
      var vb = ingState.vb;
      // Clamp: don't zoom out beyond 1.1x the plan size
      if (factor > 1) {
        var maxW = (ingState.planW || 1000) * 1.1;
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
      // Defensive: if no mouse button is actually pressed, clear stuck pan
      // state (mouseup can be missed e.g. when released outside viewport).
      if (e.buttons === 0) {
        ingState.pan = null;
        svg.style.cursor = 'grab';
        return;
      }
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
  // Erase a segment of the bbox wall at the door/opening location so the
  // gap is visible through the white rectangle. Background color matches
  // the SVG background so it effectively "cuts" the stroke.
  function eraseWallSegment(els, x0, y0, x1, y1, face, offset, width) {
    var ERASE_COLOR = '#1e1e1e';
    var ERASE_W = 2;  // slightly thicker than bbox stroke (1.5) to fully cover
    if (face === 'north') {
      els.push('<line x1="' + (x0 + offset) + '" y1="' + y0 +
        '" x2="' + (x0 + offset + width) + '" y2="' + y0 +
        '" stroke="' + ERASE_COLOR + '" stroke-width="' + ERASE_W + '"/>');
    } else if (face === 'south') {
      els.push('<line x1="' + (x0 + offset) + '" y1="' + y1 +
        '" x2="' + (x0 + offset + width) + '" y2="' + y1 +
        '" stroke="' + ERASE_COLOR + '" stroke-width="' + ERASE_W + '"/>');
    } else if (face === 'west') {
      els.push('<line x1="' + x0 + '" y1="' + (y0 + offset) +
        '" x2="' + x0 + '" y2="' + (y0 + offset + width) +
        '" stroke="' + ERASE_COLOR + '" stroke-width="' + ERASE_W + '"/>');
    } else if (face === 'east') {
      els.push('<line x1="' + x1 + '" y1="' + (y0 + offset) +
        '" x2="' + x1 + '" y2="' + (y0 + offset + width) +
        '" stroke="' + ERASE_COLOR + '" stroke-width="' + ERASE_W + '"/>');
    }
  }

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
    updatePlanDependentUI();  // initial state: hide sections, disable tabs

    // Drawing scale field: recalculate room dimensions on change
    var dsField = document.getElementById('ingDrawingScale');
    if (dsField) {
      // Pre-fill from config if available
      var cfgDs = ((window.APP_CONFIG || {}).ingestion || {}).drawing_scale_text || '';
      if (cfgDs) {
        var cfgNum = parseDrawingScale(cfgDs);
        if (cfgNum > 0) {
          dsField.value = '1 : ' + cfgNum;
          dsField.style.color = 'var(--text)';
        }
      }

      // On focus: select only the number part (after "1 : ")
      dsField.addEventListener('focus', function() {
        var val = this.value;
        var m = val.match(/^1\s*:\s*/);
        if (m) {
          var start = m[0].length;
          var self = this;
          setTimeout(function() { self.setSelectionRange(start, val.length); }, 0);
        }
      });

      // On blur/change: reformat to "1 : <number>" and apply
      function _applyDrawingScale() {
        var scaleNum = parseDrawingScale(dsField.value);
        if (scaleNum > 0) {
          dsField.value = '1 : ' + scaleNum;
          dsField.style.color = 'var(--text)';
        }
        var dpi = getRenderDpi();
        if (scaleNum > 0 && dpi > 0 && ingState.rooms.length > 0) {
          ingState.scale = computeCmPerPx(scaleNum, dpi);
          // Propage aussi la nouvelle échelle dans fpOverlay (utilisé par
          // Room / Office pour positionner l'overlay du plan).
          if (window.fpOverlay && ingState.scale > 0) {
            window.fpOverlay.pxPerCm = 1.0 / ingState.scale;
          }
          ingState.rooms.forEach(function(r) {
            if (r.bbox_px) _updateRoomDims(r);
          });
          // D-95: propagate new dims to fpData.rooms so Room/Office reads fresh
          // values next time they render. The actual re-render happens when the
          // user switches to those tabs (triggered by existing tab handlers).
          if (window.fpData && window.fpData.rooms && window.fpData.rooms.length) {
            var byName = {};
            ingState.rooms.forEach(function(r) { byName[r.name] = r; });
            window.fpData.rooms.forEach(function(fr) {
              var src = byName[fr.name];
              if (src) {
                fr.width_cm = src.width_cm;
                fr.depth_cm = src.depth_cm;
                fr.surface_m2 = src.surface_m2;
              }
            });
          }
          updateIngRoomList();
          renderIngestion();
          populateRoomsJson();
          // Propager les offsets re-scalés (windows / openings) dans
          // fpData.rooms — sans quoi Room et Office gardent les anciennes
          // valeurs cm.
          if (typeof window.fpLoadAndMatch === 'function') {
            window.fpLoadAndMatch(ingState.rooms);
          }
          var info = document.getElementById('ingScaleInfo');
          if (info) info.textContent = scaleNum +
            ' → ' + ingState.scale.toFixed(4) + ' cm/px (at ' + dpi + ' DPI)';
        }
        saveConfigField(["ingestion", "drawing_scale_text"], dsField.value);
      }
      dsField.addEventListener('change', _applyDrawingScale);
      dsField.addEventListener('blur', function() {
        var scaleNum = parseDrawingScale(this.value);
        if (scaleNum > 0) this.value = '1 : ' + scaleNum;
      });
    }

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
      // Defensive: clear stuck drag state if no button is actually pressed
      if (e.buttons === 0) {
        be.mode = 'idle';
        be.handle = null;
        be.dragStart = null;
        be.preDragBbox = null;
        return;
      }
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

    // Peuplement de la liste + filtre de recherche + toggle popup.
    loadPlansDropdown();
    var searchEl = document.getElementById('ingPlanSearch');
    if (searchEl) {
      searchEl.addEventListener('input', _renderPlanList);
    }
    var displayEl = document.getElementById('ingPlanDisplay');
    if (displayEl) {
      displayEl.addEventListener('click', function (e) {
        e.stopPropagation();
        var pop = document.getElementById('ingPlanPopup');
        if (pop && pop.style.display === 'none') _openPlanPopup();
        else _closePlanPopup();
      });
    }
    // Escape pour fermer la popup.
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') _closePlanPopup();
    });
    window._ingSetSelectedPlan = _setSelectedPlan;
    window._ingGetSelectedPlan = _getSelectedPlan;

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

    // --- Batch re-analyze (Floor level) ---
    var btnReanAll = document.getElementById('ingBtnReanalyzeAll');
    if (btnReanAll) {
      btnReanAll.addEventListener('click', async function () {
        if (!ingState.rooms || !ingState.rooms.length) return;
        if (!ingState.planPathEnhanced || !ingState.scale) {
          alert('Re-analyze unavailable: missing plan path or scale.');
          return;
        }
        if (!confirm('Re-analyze ' + ingState.rooms.length +
          ' room(s)? Auto windows/openings will be replaced; manual edits ' +
          'and deleted-auto signatures are preserved.')) return;
        var statusEl = document.getElementById('ingStatus');
        btnReanAll.disabled = true;
        var origLabel = btnReanAll.textContent;
        var amendments = (window.fpRoomAmendments = window.fpRoomAmendments || {});
        var ok = 0, fail = 0;
        function _sig(k, e) {
          return k + '|' + e.face + '|' +
            (e.offset_cm || 0) + '|' + (e.width_cm || 0);
        }
        var doorWidthCm = ((window.APP_CONFIG || {}).default_door_width_cm) || 90;
        try {
          var payload = {
            plan_path: ingState.planPathEnhanced,
            scale_cm_per_px: ingState.scale,
            door_width_cm: doorWidthCm,
            rooms: [],
          };
          var validRooms = [];
          ingState.rooms.forEach(function (r) {
            if (!r.bbox_px || r.bbox_px.length !== 4 ||
                r.bbox_px[2] <= r.bbox_px[0] || r.bbox_px[3] <= r.bbox_px[1]) {
              fail++;
              return;
            }
            var am = amendments[r.name];
            var seedPx = r.seed_px || r.seed ||
              (r.seed_x != null && r.seed_y != null
                ? [r.seed_x, r.seed_y] : null);
            // D-124 suite : transparent_zones converties canon → abs avant
            // envoi backend (extract.py interprète en abs-room-local).
            var rCfAbs = r.corridor_face_abs || '';
            var rAbsW = (r.bbox_px[2] - r.bbox_px[0]) * ingState.scale;
            var rAbsD = (r.bbox_px[3] - r.bbox_px[1]) * ingState.scale;
            var rawTransparents = (am && am.transparent_zones) || [];
            var absTransparents = window.canonicalZonesToAbs
              ? window.canonicalZonesToAbs(
                  rawTransparents, rCfAbs, rAbsW, rAbsD)
              : rawTransparents;
            payload.rooms.push({
              name: r.name,
              bbox_px: r.bbox_px,
              seed_px: seedPx,
              transparent_zones: absTransparents,
            });
            validRooms.push(r);
          });
          if (statusEl) statusEl.textContent =
            'Re-analyzing ' + validRooms.length + ' room(s)...';

          var resp = await fetch('/api/room/reanalyze_batch', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
          });
          if (!resp.ok) throw new Error('HTTP ' + resp.status);
          var dataAll = await resp.json();
          if (dataAll.error) throw new Error(dataAll.error);

          var resultsByName = {};
          (dataAll.results || []).forEach(function (res) {
            resultsByName[res.name] = res;
          });

          validRooms.forEach(function (r) {
            var res = resultsByName[r.name];
            if (!res || res.error) { fail++; return; }
            var am = amendments[r.name];
            var deleted = new Set((am && am.deleted_auto_signatures) || []);
            // D-122 P4 : collections séparées partout (windows / openings / doors).
            var prevW = (am && am.windows)  || r.windows  || [];
            var prevOp = (am && am.openings) || r.openings || [];
            var prevDr = (am && am.doors)   || r.doors   || [];
            var manualW = prevW.filter(function (w) { return w.origin === 'manual'; });
            var manualO = prevOp.filter(function (o) { return o.origin === 'manual'; });
            // D-110 : préserver uniquement les doors explicitement "manual".
            var preservedDoors = prevDr.filter(function (d) { return d.origin === 'manual'; });

            // Canonicalise abs → canon. R-12 : le helper attend le
            // corridor_face ABSOLU (res vient du backend en absolu).
            // D-122 P3 : corridor_face_abs unique source du repère absolu.
            var prevCfAbs = r.corridor_face_abs || '';
            var canon = window.computeCanonicalReanalyzeResult(
              res, prevCfAbs, ingState.scale);

            var newW = canon.windows.filter(function (w) {
              return !deleted.has(_sig('window', w));
            });
            var newO = canon.openings.filter(function (o) {
              return !deleted.has(_sig('opening', o));
            });
            // Portes auto redétectées seulement si aucune manuelle n'existe.
            var newDoors = preservedDoors.length ? [] : canon.doors;

            var mergedW = newW.concat(manualW);
            var mergedOpenings = newO.concat(manualO);
            var mergedDoors = newDoors.concat(preservedDoors);

            // D-124 : re-ancrage des zones avant mutation du bbox.
            // Capture l'ancien repère (bbox + cf) pour re-projeter les zones.
            var oldBboxR = r.bbox_px ? r.bbox_px.slice() : null;
            var oldCfR = prevCfAbs;
            var newCfR = canon.corridor_face || prevCfAbs || '';
            var reanchored = null;
            if (canon.bbox_px && oldBboxR && window.reanchorCanonicalZones) {
              reanchored = {
                exclusion_zones: window.reanchorCanonicalZones(
                  r.exclusion_zones || [], oldBboxR, oldCfR,
                  canon.bbox_px, newCfR, ingState.scale),
                transparent_zones: window.reanchorCanonicalZones(
                  r.transparent_zones || [], oldBboxR, oldCfR,
                  canon.bbox_px, newCfR, ingState.scale),
              };
            }

            r.windows = mergedW;
            r.openings = mergedOpenings;
            r.doors = mergedDoors;
            if (reanchored) {
              r.exclusion_zones = reanchored.exclusion_zones;
              r.transparent_zones = reanchored.transparent_zones;
            }
            // Adopter le nouveau bbox + dims + corridor_face (D-113).
            if (canon.bbox_px) {
              r.bbox_px = canon.bbox_px;
              r.width_cm = canon.width_cm;
              r.depth_cm = canon.depth_cm;
              r.width_px = canon.bbox_px[2] - canon.bbox_px[0];
              r.height_px = canon.bbox_px[3] - canon.bbox_px[1];
              r.surface_m2_bbox = parseFloat(
                ((canon.width_cm * canon.depth_cm) / 10000).toFixed(2));
            }
            // D-113 + R-12 : canon.corridor_face est le repère ABSOLU
            // détecté. En state canonique, corridor_face reste "south" ;
            // corridor_face_abs pilote la rotation overlay.
            if (canon.corridor_face) {
              r.corridor_face_abs = canon.corridor_face;
              r.corridor_face = "south";
            }

            if (am) {
              // D-122 P4 : amendments gardent les 3 collections séparées
              // (même invariant que ingState / fpData, pas de re-split).
              am.windows = mergedW;
              am.openings = mergedOpenings;
              am.doors = mergedDoors;
              if (reanchored) {
                am.exclusion_zones = reanchored.exclusion_zones;
                am.transparent_zones = reanchored.transparent_zones;
              }
              if (canon.corridor_face) {
                am.corridor_face_abs = canon.corridor_face;
                am.corridor_face = "south";
              }
            }
            if (window.fpData && window.fpData.rooms) {
              var fr = window.fpData.rooms.find(function (x) { return x.name === r.name; });
              if (fr) {
                fr.windows = mergedW;
                fr.openings = mergedOpenings;
                fr.doors = mergedDoors;
                if (reanchored) {
                  fr.exclusion_zones = reanchored.exclusion_zones;
                  fr.transparent_zones = reanchored.transparent_zones;
                }
                if (canon.bbox_px) {
                  fr.bbox_px = canon.bbox_px;
                  fr.width_cm = canon.width_cm;
                  fr.depth_cm = canon.depth_cm;
                }
                if (canon.corridor_face) {
                  fr.corridor_face_abs = canon.corridor_face;
                  fr.corridor_face = "south";
                }
              }
            }
            ok++;
          });
          renderIngestion();
          populateRoomsJson();
          if (typeof window.fpLoadAndMatch === 'function') {
            window.fpLoadAndMatch(ingState.rooms);
          }
          if (statusEl) statusEl.textContent =
            'Re-analyze done: ' + ok + ' OK, ' + fail + ' failed.';
        } catch (err) {
          console.error(err);
          if (statusEl) statusEl.textContent = 'Error: ' + err.message;
        } finally {
          btnReanAll.disabled = false;
          btnReanAll.textContent = origLabel;
        }
      });
    }
  });

  // devExportV3Json + populateRoomsJson vivent dans ingestion_serialize.js
  // (D-94 P4, R-12 C3). Exposés sur window pour init.js (Save/Export) et
  // conservés en variables locales pour les call sites de ce module.
  var devExportV3Json = window.devExportV3Json;


  // --- Import préprocessé (plan_id ou upload fichiers) ---
  function extractRoomsPreprocessed() {
    var planId = _getSelectedPlan().id;
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
    var ds2 = getDrawingScale();
    if (ds2) formData.append('drawing_scale', ds2);
    formData.append('render_dpi', String(getRenderDpi()));

    fetch('/api/import/preprocessed', { method: 'POST', body: formData })
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (data.error) {
          if (status) status.textContent = 'Error: ' + data.error;
          return;
        }
        var _impScale = (typeof data.scale_cm_per_px === 'number' &&
                         data.scale_cm_per_px > 0)
          ? data.scale_cm_per_px : 0;
        ingState.rooms = (data.rooms || []).map(function (r) {
          return window.canonicalIO.fromStorage(r, _impScale);
        });
        if (status) status.textContent = ingState.rooms.length + ' room(s) imported';

        // Header badge
        if (planId) {
          var hdrEl2 = document.getElementById('hdrCurrentPlan');
          if (hdrEl2) hdrEl2.textContent = planId;
          var btnSave2 = document.getElementById('btnSavePlan');
          if (btnSave2) btnSave2.style.display = '';
          var btnExport2 = document.getElementById('btnExportPlan');
          if (btnExport2) btnExport2.style.display = '';
          var btnClose2 = document.getElementById('btnClosePlan');
          if (btnClose2) btnClose2.style.display = '';
          var eraseWrap2 = document.getElementById('eraseWrapper');
          if (eraseWrap2) eraseWrap2.style.display = '';
          var ingTb2 = document.getElementById('ingToolbar');
          if (ingTb2) ingTb2.style.display = '';
        }

        // Canvas dimensions, scale, viewbox — alignés sur le flux OCR
        if (Array.isArray(data.image_size) && data.image_size.length === 2) {
          ingState.planW = data.image_size[0];
          ingState.planH = data.image_size[1];
        }
        if (typeof data.scale_cm_per_px === 'number' && data.scale_cm_per_px > 0) {
          ingState.scale = data.scale_cm_per_px;
          _suggestDrawingScale(data.scale_cm_per_px);
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

        // Floor = PNG standard (overlay_path avec cartouches).
        // Room/Office = PNG -SD (enhanced_path sans description). Fallback croisé si l'un manque.
        var _toUrl = function (p) {
          return p ? '/api/image?path=' + encodeURIComponent(p) : '';
        };
        var overlayUrl = _toUrl(data.overlay_path || data.image_path);
        var enhancedUrl = _toUrl(data.enhanced_path);
        ingState.planUrl = overlayUrl || enhancedUrl;
        // Chemins bruts serveur (pour /api/room/reanalyze qui lit le PNG -SD).
        ingState.planPath = data.overlay_path || data.image_path || "";
        ingState.planPathEnhanced = data.enhanced_path || ingState.planPath;

        renderIngestion();
        populateRoomsJson();
        updateIngRoomList();
        updatePlanDependentUI();

        if (typeof window.fpLoadAndMatch === 'function') {
          window.fpLoadAndMatch(ingState.rooms);
        }

        // fpOverlay pour Review/Design = PNG -SD si disponible, sinon fallback overlay standard.
        window.fpOverlay = {
          dataUrl: enhancedUrl || overlayUrl,
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
