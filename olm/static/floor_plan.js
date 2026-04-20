"use strict";
// ========================================================================
// FLOOR PLAN VIEWER
// ========================================================================
(function() {
  // D-94: state owned by olmStore; these are live refs to store sections.
  var fpData = window.fpData;                // state.floor { rooms, currentIdx }
  // window.fpAmendments     — state.amendments.layout
  // window.fpRoomAmendments — state.amendments.room
  // window.fpOverlay        — state.plan.overlay (getter/setter)

  function fpRooms() { return fpData.rooms; }
  function fpCurrent() { return fpData.rooms[fpData.currentIdx] || null; }

  // ── D-83: Canonical room orientation (corridor at bottom) ─────────────
  var _FACE_MAPS = {
    north: { north: "south", south: "north", east: "west", west: "east" },
    east:  { north: "east",  east: "south",  south: "west", west: "north" },
    west:  { north: "west",  west: "south",  south: "east", east: "north" },
  };

  function _canonicalizeRoom(room) {
    var cf = room.corridor_face || "";
    if (!cf || cf === "south") return room;
    var faceMap = _FACE_MAPS[cf];
    if (!faceMap) return room;

    var copy = JSON.parse(JSON.stringify(room));
    var W = room.width_cm, D = room.depth_cm;
    var swap = (cf === "east" || cf === "west");
    if (swap) { copy.width_cm = D; copy.depth_cm = W; }

    function faceLen(face) {
      return (face === "north" || face === "south") ? W : D;
    }
    function xformOpening(o) {
      var r = Object.assign({}, o);
      r.face = faceMap[o.face] || o.face;
      if (cf === "north") {
        r.offset_cm = faceLen(o.face) - (o.offset_cm || 0) - (o.width_cm || 0);
      } else if (cf === "west") {
        r.offset_cm = faceLen(o.face) - (o.offset_cm || 0) - (o.width_cm || 0);
      }
      if ((cf === "north" || cf === "west") && o.hinge_side) {
        r.hinge_side = o.hinge_side === "left" ? "right" : "left";
      }
      return r;
    }

    copy.windows = (room.windows || []).map(xformOpening);
    copy.openings = (room.openings || []).map(xformOpening);

    function xformZone(e) {
      var ex = Object.assign({}, e);
      if (cf === "north") {
        ex.x_cm = W - e.x_cm - e.width_cm;
        ex.y_cm = D - e.y_cm - e.depth_cm;
      } else if (cf === "east") {
        ex.x_cm = e.y_cm; ex.y_cm = W - e.x_cm - e.width_cm;
        ex.width_cm = e.depth_cm; ex.depth_cm = e.width_cm;
      } else if (cf === "west") {
        ex.x_cm = D - e.y_cm - e.depth_cm; ex.y_cm = e.x_cm;
        ex.width_cm = e.depth_cm; ex.depth_cm = e.width_cm;
      }
      return ex;
    }
    if (room.exclusion_zones && room.exclusion_zones.length) {
      copy.exclusion_zones = room.exclusion_zones.map(xformZone);
    }
    if (room.transparent_zones && room.transparent_zones.length) {
      copy.transparent_zones = room.transparent_zones.map(xformZone);
    }

    copy.corridor_face = "south";
    copy._originalCorridorFace = cf;
    return copy;
  }

  // Inverse face maps: local face → absolute face
  var _INV_FACE_MAPS = {
    north: { north: "south", south: "north", east: "west", west: "east" },
    east:  { north: "west",  east: "north",  south: "east", west: "south" },
    west:  { north: "east",  east: "south",  south: "west", west: "north" },
  };

  function _decanonicalizeRoom(room, originalCorridorFace) {
    if (!originalCorridorFace || originalCorridorFace === "south") return room;
    var invMap = _INV_FACE_MAPS[originalCorridorFace];
    if (!invMap) return room;

    var copy = JSON.parse(JSON.stringify(room));
    var W = room.width_cm, D = room.depth_cm;
    var swap = (originalCorridorFace === "east" || originalCorridorFace === "west");
    if (swap) { copy.width_cm = D; copy.depth_cm = W; }

    function localFaceLen(face) {
      return (face === "north" || face === "south") ? W : D;
    }
    function xformBack(o) {
      var r = Object.assign({}, o);
      r.face = invMap[o.face] || o.face;
      if (originalCorridorFace === "north") {
        r.offset_cm = localFaceLen(o.face) - (o.offset_cm || 0) - (o.width_cm || 0);
        if (o.hinge_side) r.hinge_side = o.hinge_side === "left" ? "right" : "left";
      } else if (originalCorridorFace === "west") {
        r.offset_cm = localFaceLen(o.face) - (o.offset_cm || 0) - (o.width_cm || 0);
        if (o.hinge_side) r.hinge_side = o.hinge_side === "left" ? "right" : "left";
      }
      // east (90° CW): offset and hinge stay the same
      return r;
    }

    copy.windows = (room.windows || []).map(xformBack);
    copy.openings = (room.openings || []).map(xformBack);

    function xformZoneBack(e) {
      var ex = Object.assign({}, e);
      if (originalCorridorFace === "north") {
        var absW = swap ? D : W, absD = swap ? W : D;
        ex.x_cm = absW - e.x_cm - e.width_cm;
        ex.y_cm = absD - e.y_cm - e.depth_cm;
      } else if (originalCorridorFace === "east") {
        ex.x_cm = D - e.y_cm - e.depth_cm; ex.y_cm = e.x_cm;
        ex.width_cm = e.depth_cm; ex.depth_cm = e.width_cm;
      } else if (originalCorridorFace === "west") {
        ex.x_cm = e.y_cm; ex.y_cm = W - e.x_cm - e.width_cm;
        ex.width_cm = e.depth_cm; ex.depth_cm = e.width_cm;
      }
      return ex;
    }
    if (room.exclusion_zones && room.exclusion_zones.length) {
      copy.exclusion_zones = room.exclusion_zones.map(xformZoneBack);
    }
    if (room.transparent_zones && room.transparent_zones.length) {
      copy.transparent_zones = room.transparent_zones.map(xformZoneBack);
    }

    copy.corridor_face = originalCorridorFace;
    return copy;
  }
  window._canonicalizeRoom = _canonicalizeRoom;
  window._decanonicalizeRoom = _decanonicalizeRoom;

  // ── Natural alphanumeric sort ─────────────────────────────────────────
  function natSort(a, b) {
    return a.localeCompare(b, undefined, { numeric: true, sensitivity: "base" });
  }

  // ── Loading and matching ──────────────────────────────────────────────
  function fpLoadAndMatch(roomsJson) {
    var parsed;
    try { parsed = JSON.parse(roomsJson); } catch(e) {
      alert("Invalid JSON: " + e.message); return;
    }
    if (!parsed.rooms || !parsed.rooms.length) {
      alert("No rooms found in JSON"); return;
    }

    // Sort by alphanumeric name
    parsed.rooms.sort(function(a, b) { return natSort(a.name || "", b.name || ""); });

    // R-12 A.2: canonicalise input rooms before matching
    parsed.rooms = parsed.rooms.map(window.canonicalIO.fromStorage);

    // Preserve fields from input (not returned by matching API)
    var bboxByName = {};
    var corridorByName = {};
    var seedByName = {};
    var doorsByName = {};
    parsed.rooms.forEach(function(r) {
      if (r.bbox_abs_px) bboxByName[r.name] = r.bbox_abs_px;
      corridorByName[r.name] = r.original_corridor_face || "";
      if (r.seed_abs_px) seedByName[r.name] = r.seed_abs_px;
      if (r.doors) doorsByName[r.name] = r.doors;
    });

    document.getElementById("fpCandidatesList").innerHTML =
      '<div class="fp-no-match">Matching in progress...</div>';

    fetch("/api/floor-plan/match", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ rooms: parsed.rooms }),
    })
    .then(function(r) { return r.json(); })
    .then(function(data) {
      if (data.error) { alert("Error: " + data.error); return; }
      // Sort results by name
      data.rooms.sort(function(a, b) { return natSort(a.name || "", b.name || ""); });
      // Re-attach canonical fields not returned by matching API.
      // bbox_px / seed_px dupliquent bbox_abs_px / seed_abs_px : les
      // consommateurs de rendu (overlay, re-analyze) lisent encore bbox_px
      // pour le positionnement absolu. À consolider en étape B.
      data.rooms.forEach(function(r) {
        if (bboxByName[r.name]) {
          r.bbox_abs_px = bboxByName[r.name];
          r.bbox_px     = bboxByName[r.name];
        }
        if (seedByName[r.name]) {
          r.seed_abs_px = seedByName[r.name];
          r.seed_px     = seedByName[r.name];
        }
        if (doorsByName[r.name])   r.doors = doorsByName[r.name];
        r.original_corridor_face = corridorByName[r.name] || "";
        r.corridor_face = "south";
      });
      fpData.rooms = data.rooms;
      fpData.currentIdx = 0;
      // Render Review data (but stay on current tab)
      fpRenderCurrent();
      rvRenderCurrent();
      document.activeElement.blur();
    })
    .catch(function(e) { alert("Network error: " + e); });
  }

  // ── Navigation ─────────────────────────────────────────────────────────
  function fpGo(delta) {
    if (!fpRooms().length) return;
    fpData.currentIdx = (fpData.currentIdx + delta + fpRooms().length) % fpRooms().length;
    fpRenderCurrent();
    rvRenderCurrent();
  }

  // ── Review tab rendering ───────────────────────────────────────────────
  window.rvRenderCurrent = rvRenderCurrent;
  window.rvUpdateRoomInfo = rvUpdateRoomInfo;
  function rvUpdateRoomInfo() {
    document.getElementById("rvRoomWidth").textContent = state.room_width_cm;
    document.getElementById("rvRoomDepth").textContent = state.room_depth_cm;
    var area = (state.room_width_cm * state.room_depth_cm / 10000).toFixed(1);
    document.getElementById("rvRoomArea").textContent = area;
  }

  function rvRenderCurrent() {
    var room = fpCurrent();
    if (!room) {
      document.getElementById("rvRoomLabel").textContent = "-";
      document.getElementById("rvNavInfo").textContent = "0 / 0";
      document.getElementById("rvCanvas").innerHTML = "";
      return;
    }

    // Floor properties (computed once from all rooms)
    var allRooms = fpRooms();
    var totalArea = 0;
    allRooms.forEach(function(r) {
      totalArea += (r.width_cm || 0) * (r.depth_cm || 0) / 10000;
    });
    document.getElementById("rvFloorRooms").textContent = allRooms.length;
    document.getElementById("rvFloorArea").textContent = totalArea.toFixed(1);

    // Update ingestion room list to reflect current selection
    if (window.updateIngRoomList) window.updateIngRoomList();

    // Use amended data if available
    var roomData = fpRoomAmendments[room.name] || room;

    // Render room SVG in canvas (empty room, no blocks)
    var reviewSubtab = document.getElementById("tabFpReview");
    if (reviewSubtab && reviewSubtab.classList.contains("active")) {
      fpRenderEmptyRoom(roomData, document.getElementById("rvCanvas"));
    }

    // Navigation
    document.getElementById("rvRoomLabel").textContent = roomData.name || "(unnamed)";
    document.getElementById("rvNavInfo").textContent =
      (fpData.currentIdx + 1) + " / " + fpRooms().length;

    // Room dimensions
    document.getElementById("rvRoomWidth").textContent = roomData.width_cm || 0;
    document.getElementById("rvRoomDepth").textContent = roomData.depth_cm || 0;
    var area = ((roomData.width_cm || 0) * (roomData.depth_cm || 0) / 10000).toFixed(1);
    document.getElementById("rvRoomArea").textContent = area;

    // Room definition in local coordinates (D-83: canonicalized from absolute)
    var localRoom = _canonicalizeRoom(roomData);
    var dsl = "ROOM " + (localRoom.width_cm || 0) + "x" + (localRoom.depth_cm || 0);
    var faceMap = { north: "N", south: "S", east: "E", west: "W" };
    (localRoom.windows || []).forEach(function(w) {
      var f = faceMap[w.face] || w.face || "?";
      if (w.offset_cm === 0 && w.width_cm === (f === "N" || f === "S" ? localRoom.width_cm : localRoom.depth_cm)) {
        dsl += "\nWINDOW " + f;
      } else {
        dsl += "\nWINDOW " + f + " " + (w.offset_cm || 0) + " " + (w.width_cm || 0);
      }
    });
    (localRoom.openings || []).forEach(function(o) {
      var f = faceMap[o.face] || o.face || "?";
      if (o.has_door) {
        var dir = o.opens_inward ? "INT" : "EXT";
        var side = (o.hinge_side === "left") ? "L" : "R";
        dsl += "\nDOOR " + f + " " + (o.offset_cm || 0) + " " + (o.width_cm || 90) + " " + dir + " " + side;
      } else {
        dsl += "\nOPENING " + f + " " + (o.offset_cm || 0) + " " + (o.width_cm || 90);
      }
    });
    (localRoom.exclusion_zones || []).forEach(function(e) {
      dsl += "\nEXCLUSION " + (e.x_cm || 0) + " " + (e.y_cm || 0) + " " + (e.width_cm || 0) + " " + (e.depth_cm || 0);
    });
    document.getElementById("rvRoomDsl").value = dsl;
  }

  // ── Standard filter ────────────────────────────────────────────────────
  function fpGetStandardFilter() {
    var checked = document.querySelector('input[name="fpStandard"]:checked');
    return checked ? checked.value : "";
  }

  // ── Render current room ────────────────────────────────────────────────
  window.fpRenderCurrent = fpRenderCurrent;
  function fpRenderCurrent() {
    var room = fpCurrent();
    if (!room) {
      document.getElementById("fpRoomLabel").textContent = "-";
      document.getElementById("fpNavInfo").textContent = "0 / 0";
      document.getElementById("fpRoomSize").textContent = "-";
      document.getElementById("fpCandidatesList").innerHTML =
        '<div class="fp-no-match">Load a room JSON file from the Input tab</div>';
      document.getElementById("fpCanvas").innerHTML = "";
      return;
    }

    // Update room list highlight in Design
    if (window.updateIngRoomList) window.updateIngRoomList();

    // Reset standard filter to default on room change
    var defStd = (window.APP_CONFIG || {}).default_standard || "";
    if (defStd) {
      var radio = document.querySelector('input[name="fpStandard"][value="' + defStd + '"]');
      if (radio) radio.checked = true;
    }

    // Reset action buttons on room change
    document.getElementById("fpBtnEditPattern").disabled = true;
    document.getElementById("fpBtnAdjustLayout").disabled = true;
    // Show Discard if amendment exists
    var hasAmendment = !!fpAmendments[room.name];
    document.getElementById("fpBtnDiscard").style.display = hasAmendment ? "" : "none";

    // Navigation
    var roomLabel = room.name || "(unnamed)";
    if (room.room_amended || fpRoomAmendments[room.name]) roomLabel += " (amended)";
    document.getElementById("fpRoomLabel").textContent = roomLabel;
    document.getElementById("fpNavInfo").textContent =
      (fpData.currentIdx + 1) + " / " + fpRooms().length;
    document.getElementById("fpRoomSize").textContent =
      room.width_cm + " x " + room.depth_cm + " cm";

    // Candidates (sorted best first)
    fpRenderCandidates(room);

    // Automatically select the first candidate in the list
    var firstCand = document.querySelector("#fpCandidatesList .fp-candidate");
    if (firstCand) {
      firstCand.click();
    } else {
      // No candidates — render empty room (with overlay if active)
      fpRenderEmptyRoom(room, document.getElementById("fpCanvas"));
    }
  }

  function fpRenderEmptyRoom(room, targetSvg) {
    // D-83: convert absolute data to local coordinates for rendering
    var isEditor = targetSvg && targetSvg.id === "canvas";
    var localRoom = (!isEditor) ? _canonicalizeRoom(room) : room;
    state.rows = [];
    state.row_gaps_cm = [];
    state.room_width_cm = localRoom.width_cm;
    state.room_depth_cm = localRoom.depth_cm;
    state.room_windows = localRoom.windows || [];
    state.room_openings = localRoom.openings || [];
    state.room_exclusions = localRoom.exclusion_zones || [];
    state.room_transparents = localRoom.transparent_zones || [];
    state.corridor_face = room.corridor_face || "";
    state.selectedRow = 0;
    state.selectedBlock = -1;

    // Inject overlay if active (check both Design and Review toggles)
    // Auto-align: use bbox_px to offset the plan image so the room aligns at (0,0)
    var fpOvChecked = document.getElementById("fpOverlayToggle").checked;
    var rvOvChecked = document.getElementById("rvOverlayToggle").checked;
    if (window.fpOverlay && (fpOvChecked || rvOvChecked)) {
      var ov = window.fpOverlay;
      var fpOvOpacity = parseInt(document.getElementById("rvOverlayOpacity").value) ||
        parseInt(document.getElementById("fpOverlayOpacity").value) || 25;
      // bbox_px gives the room position in the plan image (pixels)
      var ovOffX = 0, ovOffY = 0;
      if (room.bbox_px) {
        ovOffX = room.bbox_px[0] / ov.pxPerCm;  // px → cm
        ovOffY = room.bbox_px[1] / ov.pxPerCm;
      }
      state.overlay = {
        dataUrl: ov.dataUrl, pxPerCm: ov.pxPerCm, opacity: fpOvOpacity,
        offsetX: ovOffX, offsetY: ovOffY, imgW: ov.imgW, imgH: ov.imgH,
      };
    } else {
      state.overlay = null;
    }

    render(targetSvg);
    // Delay zoomFit to ensure the SVG container is laid out
    requestAnimationFrame(function() { zoomFit(targetSvg); });
  }

  // ── Candidate list ─────────────────────────────────────────────────────
  function fpRenderCandidates(room) {
    var container = document.getElementById("fpCandidatesList");
    var stdFilter = fpGetStandardFilter();

    // If amendment exists for this room, show only the amendment + Discard
    var amendment = fpAmendments[room.name];
    if (amendment) {
      var gradeClass = "fp-grade-" + (amendment.circulation_grade || "F");
      container.innerHTML =
        '<div class="fp-candidate amended selected" data-fp-cand="0">' +
          '<div style="display:flex;justify-content:space-between;align-items:center;">' +
            '<span class="fp-c-name">' + amendment.pattern_name + '</span>' +
          '</div>' +
          '<div class="fp-c-stats">' +
            amendment.n_desks + ' desks &middot; ' + amendment.m2_per_desk + ' m&sup2;/d &middot; ' +
            '<span class="fp-c-grade ' + gradeClass + '">' + amendment.circulation_grade + '</span>' +
            ' &middot; ' + amendment.standard +
          '</div>' +
        '</div>';

      // Wire click to render SVG
      var candidates = [amendment];
      container.querySelector(".fp-candidate").addEventListener("click", function(e) {
        fpRenderSvg(room, amendment);
        document.getElementById("fpBtnEditPattern").disabled = true;
        document.getElementById("fpBtnAdjustLayout").disabled = false;
      });

      return;
    }

    var candidates = room.all_candidates.slice();

    if (stdFilter) {
      candidates = candidates.filter(function(c) { return c.standard === stdFilter; });
    }

    // Sort: n_desks desc, grade asc (A=best), passage min desc, m²/desk asc
    var gradeOrd = { A: 0, B: 1, C: 2, D: 3, F: 4 };
    function gradeVal(g) { return g in gradeOrd ? gradeOrd[g] : 5; }
    candidates.sort(function(a, b) {
      if (b.n_desks !== a.n_desks) return b.n_desks - a.n_desks;
      var gd = gradeVal(a.circulation_grade) - gradeVal(b.circulation_grade);
      if (gd !== 0) return gd;
      var pd = (b.min_passage_cm || 0) - (a.min_passage_cm || 0);
      if (pd !== 0) return pd;
      return (a.m2_per_desk || 99) - (b.m2_per_desk || 99);
    });

    if (!candidates.length) {
      container.innerHTML = '<div class="fp-no-match">No matching patterns</div>';
      return;
    }

    container.innerHTML = candidates.map(function(c, i) {
      var isBest = false;
      for (var std in room.by_standard) {
        if (room.by_standard[std] === c.pattern_name && c.standard === std) isBest = true;
      }
      var gradeClass = "fp-grade-" + (c.circulation_grade || "F");
      var classes = "fp-candidate";
      if (isBest) classes += " selected best";
      return '<div class="' + classes + '" data-fp-cand="' + i + '">' +
        '<div style="display:flex;justify-content:space-between;align-items:center;">' +
          '<span class="fp-c-name">' + c.pattern_name + '</span>' +
        '</div>' +
        '<div class="fp-c-stats">' +
          c.n_desks + ' desks &middot; ' + c.m2_per_desk + ' m&sup2;/d &middot; ' +
          '<span class="fp-c-grade ' + gradeClass + '">' + c.circulation_grade + '</span>' +
          ' &middot; ' + c.standard +
        '</div>' +
      '</div>';
    }).join("");

    // Click on a candidate -> display in SVG + enable action buttons
    container.querySelectorAll(".fp-candidate").forEach(function(el) {
      el.addEventListener("click", function(e) {
        var idx = parseInt(el.dataset.fpCand);
        var c = candidates[idx];
        container.querySelectorAll(".fp-candidate").forEach(function(e) { e.classList.remove("selected"); });
        el.classList.add("selected");
        fpRenderSvg(room, c);
        document.getElementById("fpBtnEditPattern").disabled = false;
        document.getElementById("fpBtnAdjustLayout").disabled = false;
      });
    });
  }

  // ── SVG rendering ──────────────────────────────────────────────────────
  // Currently displayed candidate (for keyboard navigation in list)
  var fpCurrentCandidate = null;

  function fpRenderSvg(room, candidate) {
    if (!candidate || !candidate.pattern) return;
    fpCurrentCandidate = candidate;

    // Load adapted pattern into state — deep copy to avoid mutating original
    var pat = JSON.parse(JSON.stringify(candidate.pattern));
    pat.room_width_cm = pat.room_width_cm || room.width_cm;
    pat.room_depth_cm = pat.room_depth_cm || room.depth_cm;
    if (!pat.room_exclusions && room.exclusion_zones) {
      pat.room_exclusions = JSON.parse(JSON.stringify(room.exclusion_zones));
    }

    // Switch BLOCK_DEFS to the candidate's standard
    if (candidate.standard && BLOCK_DEFS_BY_STD[candidate.standard]) {
      BLOCK_DEFS = BLOCK_DEFS_BY_STD[candidate.standard];
    }

    // Load into state (same logic as loadPatternFromData)
    state.rows = pat.rows || [];
    state.row_gaps_cm = pat.row_gaps_cm || [];
    state.room_width_cm = pat.room_width_cm;
    state.room_depth_cm = pat.room_depth_cm;
    state.standard = pat.standard || candidate.standard || getStandards()[0] || "";
    state.room_windows = pat.room_windows || [];
    state.room_openings = pat.room_openings || [];
    state.room_exclusions = pat.room_exclusions || [];
    state.corridor_face = room.corridor_face || "";
    state.name = candidate.pattern_name || pat.name || "";
    state._savedName = null;
    state.selectedRow = 0;
    state.selectedBlock = -1;

    document.getElementById("roomWidth").value = state.room_width_cm;
    document.getElementById("roomDepth").value = state.room_depth_cm;
    var radios = document.querySelectorAll('input[name="standard"]');
    radios.forEach(function(r) { r.checked = (r.value === state.standard); });
    document.getElementById("autoName").textContent = state.name;

    // Inject floor plan overlay if visible
    var fpOvToggle = document.getElementById("fpOverlayToggle");
    if (window.fpOverlay && fpOvToggle && fpOvToggle.checked) {
      var ov = window.fpOverlay;
      // Room offset within the floor plan (from room_amended or stored offsets)
      var roomOvX = room._overlayOffsetX || 0;
      var roomOvY = room._overlayOffsetY || 0;
      var fpOvOpacity = parseInt(document.getElementById("fpOverlayOpacity").value) || 25;
      state.overlay = {
        dataUrl: ov.dataUrl,
        pxPerCm: ov.pxPerCm,
        opacity: fpOvOpacity,
        offsetX: roomOvX,
        offsetY: roomOvY,
        imgW: ov.imgW,
        imgH: ov.imgH,
      };
    } else {
      state.overlay = null;
    }

    var _fpSvg = document.getElementById("fpCanvas");
    render(_fpSvg);
    zoomFit(_fpSvg);

    // Update info panel
    fpUpdateInfo(room, candidate);
  }

  function fpUpdateInfo(room, candidate) {
    var area = (room.width_cm * room.depth_cm / 10000).toFixed(1);
    document.getElementById("fpInfoDims").textContent = room.width_cm + " x " + room.depth_cm + " cm";
    document.getElementById("fpInfoArea").textContent = area;
    document.getElementById("fpInfoPattern").textContent = candidate.pattern_name || "-";
    document.getElementById("fpInfoStandard").textContent = candidate.standard || "-";
    document.getElementById("fpInfoDesks").textContent = candidate.n_desks || "-";
    document.getElementById("fpInfoM2").textContent = candidate.m2_per_desk ? candidate.m2_per_desk.toFixed(1) : "-";
    document.getElementById("fpInfoCirc").textContent = candidate.circulation_grade || "-";
    document.getElementById("fpInfoPassage").textContent = candidate.min_passage_cm ? candidate.min_passage_cm + " cm" : "-";

    // Workstation list
    var deskList = document.getElementById("fpDeskList");
    if (!candidate.desks || candidate.desks.length === 0) {
      deskList.innerHTML = '<div style="color:var(--text-dim);padding:8px;">No desks</div>';
      return;
    }
    var activeDesks = candidate.desks.filter(function(d) { return !d.removed; });
    var removedDesks = candidate.desks.filter(function(d) { return d.removed; });
    var html = "";
    var idx = 0;
    activeDesks.forEach(function(d) {
      idx++;
      var name = "WS" + String(idx).padStart(2, "0");
      html += '<div class="fp-desk-item">' +
        '<span class="fp-desk-name">' + name + '</span>' +
        '<span class="fp-desk-pos">' + d.x_cm + ', ' + d.y_cm + '</span>' +
        '</div>';
    });
    removedDesks.forEach(function(d) {
      idx++;
      var name = "WS" + String(idx).padStart(2, "0");
      html += '<div class="fp-desk-item removed">' +
        '<span class="fp-desk-name">' + name + '</span>' +
        '<span class="fp-desk-pos">removed</span>' +
        '</div>';
    });
    deskList.innerHTML = html;
  }

  // ── Export results ─────────────────────────────────────────────────────
  // Re-match a single room with amended geometry
  window.fpRematchRoom = function(roomName, amendedRoom) {
    fetch("/api/floor-plan/match", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ rooms: [amendedRoom] }),
    })
    .then(function(r) { return r.json(); })
    .then(function(data) {
      if (data.error || !data.rooms || !data.rooms.length) {
        setStatus("Re-matching error for \"" + roomName + "\".");
        return;
      }
      // Replace the room data in fpData
      var newRoom = data.rooms[0];
      for (var i = 0; i < fpData.rooms.length; i++) {
        if (fpData.rooms[i].name === roomName) {
          // Preserve original room reference but update geometry + candidates
          fpData.rooms[i].width_cm = newRoom.width_cm;
          fpData.rooms[i].depth_cm = newRoom.depth_cm;
          fpData.rooms[i].windows = newRoom.windows;
          fpData.rooms[i].openings = newRoom.openings;
          fpData.rooms[i].exclusion_zones = newRoom.exclusion_zones;
          fpData.rooms[i].all_candidates = newRoom.all_candidates;
          fpData.rooms[i].by_standard = newRoom.by_standard;
          fpData.rooms[i].room_amended = true;
          break;
        }
      }
      // Clear layout amendment if any (room geometry changed)
      delete fpAmendments[roomName];
      fpRenderCurrent();
      setStatus("Room \"" + roomName + "\" re-matched with amended geometry.");
    })
    .catch(function(e) { setStatus("Re-matching error: " + e); });
  };

  function fpExport() {
    if (!fpRooms().length) { alert("No results to export"); return; }

    var gradeOrd = { A: 0, B: 1, C: 2, D: 3, F: 4 };
    var exportData = {
      exported_at: new Date().toISOString(),
      n_rooms: fpRooms().length,
      rooms: fpRooms().map(function(room) {
        var roomResult = {
          name: room.name,
          width_cm: room.width_cm,
          depth_cm: room.depth_cm,
          best_by_standard: {},
          all_candidates: [],
        };

        // Best per standard
        for (var std in room.by_standard) {
          var bestName = room.by_standard[std];
          if (!bestName) {
            roomResult.best_by_standard[std] = null;
            continue;
          }
          var best = room.all_candidates.find(function(c) {
            return c.pattern_name === bestName && c.standard === std;
          });
          if (best) {
            roomResult.best_by_standard[std] = {
              pattern_name: best.pattern_name,
              n_desks: best.n_desks,
              m2_per_desk: best.m2_per_desk,
              circulation_grade: best.circulation_grade,
              connectivity_pct: best.connectivity_pct,
              min_passage_cm: best.min_passage_cm,
              worst_detour: best.worst_detour,
              largest_free_rect_m2: best.largest_free_rect_m2,
            };
          }
        }

        // All candidates (without full pattern to keep it lightweight)
        roomResult.all_candidates = room.all_candidates.map(function(c) {
          return {
            pattern_name: c.pattern_name,
            standard: c.standard,
            n_desks: c.n_desks,
            m2_per_desk: c.m2_per_desk,
            circulation_grade: c.circulation_grade,
            connectivity_pct: c.connectivity_pct,
            min_passage_cm: c.min_passage_cm,
            worst_detour: c.worst_detour,
            largest_free_rect_m2: c.largest_free_rect_m2,
            n_desks_active: c.desks ? c.desks.filter(function(d) { return !d.removed; }).length : c.n_desks,
          };
        });

        return roomResult;
      }),
    };

    // Summary table
    var summary = {};
    getStandards().forEach(function(s) { summary[s] = { rooms: 0, total_desks: 0 }; });
    exportData.rooms.forEach(function(r) {
      for (var std in r.best_by_standard) {
        var b = r.best_by_standard[std];
        if (b) { summary[std].rooms++; summary[std].total_desks += b.n_desks; }
      }
    });
    exportData.summary = summary;

    // Download
    var blob = new Blob([JSON.stringify(exportData, null, 2)], { type: "application/json" });
    var url = URL.createObjectURL(blob);
    var a = document.createElement("a");
    a.href = url;
    a.download = "matching_results.json";
    a.click();
    URL.revokeObjectURL(url);
  }

  // ── Init ───────────────────────────────────────────────────────────────
  document.addEventListener("DOMContentLoaded", function() {
    document.getElementById("fpBtnPrev").addEventListener("click", function() { fpGo(-1); });
    document.getElementById("fpBtnNext").addEventListener("click", function() { fpGo(1); });

    // Review tab navigation
    document.getElementById("rvBtnPrev").addEventListener("click", function() { fpGo(-1); });
    document.getElementById("rvBtnNext").addEventListener("click", function() { fpGo(1); });

    // Review canvas zoom
    var rvSvg = document.getElementById("rvCanvas");
    document.getElementById("rvZoomOut").addEventListener("click", function() { zoomOut(rvSvg); });
    document.getElementById("rvZoomFit").addEventListener("click", function() { zoomFit(rvSvg); });
    document.getElementById("rvZoomIn").addEventListener("click", function() { zoomIn(rvSvg); });

    // Matching canvas zoom
    var fpSvg = document.getElementById("fpCanvas");
    document.getElementById("fpZoomOut").addEventListener("click", function() { zoomOut(fpSvg); });
    document.getElementById("fpZoomFit").addEventListener("click", function() { zoomFit(fpSvg); });
    document.getElementById("fpZoomIn").addEventListener("click", function() { zoomIn(fpSvg); });

    // Standard filter — re-render candidates on change
    document.getElementById("fpStandardFilter").addEventListener("change", function() {
      fpRenderCurrent();
    });

    // Grid toggle sync across all tabs (Review, Design, Editor)
    function syncGridToggle(checked) {
      state.gridVisible = checked;
      ['gridToggle', 'fpGridToggle', 'rvGridToggle'].forEach(function(id) {
        var el = document.getElementById(id);
        if (el) el.checked = checked;
      });
    }
    document.getElementById("fpGridToggle").addEventListener("change", function(e) {
      syncGridToggle(e.target.checked);
      var room = fpCurrent();
      if (room && fpCurrentCandidate) {
        fpRenderSvg(room, fpCurrentCandidate);
      }
    });
    document.getElementById("fpCircToggle").addEventListener("change", function(e) {
      state.circVisible = e.target.checked;
      document.getElementById("circToggle").checked = e.target.checked;
      var room = fpCurrent();
      if (room && fpCurrentCandidate) {
        fpRenderSvg(room, fpCurrentCandidate);
      }
    });

    // Review tab — Adjust room (same function as before, now in Review)
    document.getElementById("rvBtnAdjustRoom").addEventListener("click", function() {
      var room = fpCurrent();
      if (room) {
        var roomData = fpRoomAmendments[room.name] || room;
        enterRoomAmendMode(roomData);
      }
    });
    document.getElementById("fpBtnEditPattern").addEventListener("click", function() {
      if (fpCurrentCandidate && fpCurrentCandidate.pattern) {
        switchToEditorWithPattern(fpCurrentCandidate.pattern);
      }
    });
    document.getElementById("fpBtnAdjustLayout").addEventListener("click", function() {
      var room = fpCurrent();
      if (room && fpCurrentCandidate && fpCurrentCandidate.pattern) {
        enterAmendMode(room, fpCurrentCandidate);
      }
    });
    // Floor plan overlay loading (elements may not exist if overlay is set via ingestion)
    var _fpBtnLoadOv = document.getElementById("fpBtnLoadOverlay");
    if (_fpBtnLoadOv) {
      _fpBtnLoadOv.addEventListener("click", function() {
        document.getElementById("fpOverlayFileInput").click();
      });
    }
    var _fpOvFileInput = document.getElementById("fpOverlayFileInput");
    if (_fpOvFileInput) {
      _fpOvFileInput.addEventListener("change", function(e) {
        var file = e.target.files[0];
        if (!file) return;
        var reader = new FileReader();
        reader.onload = function(ev) {
          var img = new Image();
          img.onload = function() {
            var scaleEl = document.getElementById("fpOverlayScale");
            var pxPerCm = scaleEl ? (parseFloat(scaleEl.value) || 2) : 2;
            window.fpOverlay = {
              dataUrl: ev.target.result,
              pxPerCm: pxPerCm,
              imgW: img.width,
              imgH: img.height,
            };
            var statusEl = document.getElementById("fpOverlayStatus");
            if (statusEl) statusEl.textContent = img.width + "x" + img.height + " px loaded";
          };
          img.src = ev.target.result;
        };
        reader.readAsDataURL(file);
      });
    }
    var _fpOvScale = document.getElementById("fpOverlayScale");
    if (_fpOvScale) {
      _fpOvScale.addEventListener("change", function() {
        if (window.fpOverlay) {
          window.fpOverlay.pxPerCm = parseFloat(this.value) || 2;
          fpRenderCurrent();
        }
      });
    }
    document.getElementById("fpOverlayToggle").addEventListener("change", function() {
      document.getElementById("rvOverlayToggle").checked = this.checked;
      fpRenderCurrent();
    });
    document.getElementById("fpOverlayOpacity").addEventListener("input", function() {
      document.getElementById("fpOverlayOpacityVal").textContent = this.value + "%";
      document.getElementById("rvOverlayOpacity").value = this.value;
      document.getElementById("rvOverlayOpacityVal").textContent = this.value + "%";
      if (document.getElementById("fpOverlayToggle").checked && state.overlay) {
        state.overlay.opacity = parseInt(this.value);
        render(document.getElementById('fpCanvas'));
      }
    });
    // Review refresh — exposed on window for inline handlers
    window._rvRefresh = function() {
      // Sync toggles
      var rvGrid = document.getElementById("rvGridToggle");
      if (rvGrid) syncGridToggle(rvGrid.checked);
      var rvOv = document.getElementById("rvOverlayToggle");
      var fpOv = document.getElementById("fpOverlayToggle");
      if (rvOv && fpOv) fpOv.checked = rvOv.checked;
      // Sync opacity
      var rvOp = document.getElementById("rvOverlayOpacity");
      var fpOp = document.getElementById("fpOverlayOpacity");
      if (rvOp && fpOp) {
        fpOp.value = rvOp.value;
        document.getElementById("fpOverlayOpacityVal").textContent = rvOp.value + "%";
      }
      // Re-render
      var room = fpCurrent();
      if (!room) return;
      var roomData = fpRoomAmendments[room.name] || room;
      fpRenderEmptyRoom(roomData, document.getElementById("rvCanvas"));
    };

    // --- Plan view / Room view toggle ---
    window.ingShowRoomView = function() {
      var reviewBtn = document.querySelector('.tab-btn[data-tab="fpReview"]');
      if (reviewBtn) reviewBtn.click();
      rvRenderCurrent();
      // Update ingestion room list to highlight selected room
      if (window.updateIngRoomList) window.updateIngRoomList();
    };
    window.ingShowPlanView = function() {
      var importBtn = document.querySelector('.tab-btn[data-tab="fpImport"]');
      if (importBtn) importBtn.click();
      if (window.updateIngRoomList) window.updateIngRoomList();
    };
    document.getElementById("rvBtnBack").addEventListener("click", function() {
      window.ingShowPlanView();
    });

    document.getElementById("fpBtnDiscard").addEventListener("click", function() {
      var room = fpCurrent();
      if (room) {
        delete fpAmendments[room.name];
        fpRenderCurrent();
      }
    });
    var btnExport = document.getElementById("fpBtnExport");
    if (btnExport) btnExport.addEventListener("click", fpExport);

    var btnLoadJson = document.getElementById("fpBtnLoadJson");
    if (btnLoadJson) {
      btnLoadJson.addEventListener("click", function() {
        var json = document.getElementById("fpRoomsJson").value.trim();
        if (json) fpLoadAndMatch(json);
      });
    }

    document.getElementById("fpBtnLoadFile").addEventListener("click", function() {
      document.getElementById("fpFileInput").click();
    });
    document.getElementById("fpFileInput").addEventListener("change", function(e) {
      var file = e.target.files[0];
      if (!file) return;
      var reader = new FileReader();
      reader.onload = function(ev) {
        document.getElementById("fpRoomsJson").value = ev.target.result;
        fpLoadAndMatch(ev.target.result);
      };
      reader.readAsText(file);
    });

    // Standard filter
    document.querySelectorAll('input[name="fpStandard"]').forEach(function(radio) {
      radio.addEventListener("change", function() { fpRenderCurrent(); });
    });

    // Keyboard nav — Design tab (Left/Right = rooms, Up/Down = candidates)
    document.addEventListener("keydown", function(e) {
      var officeLayoutTab = document.getElementById("tabOfficeLayout");
      var reviewSubtab = document.getElementById("tabFpReview");
      var inDesign = officeLayoutTab && officeLayoutTab.classList.contains("active");
      var inReview = reviewSubtab && reviewSubtab.classList.contains("active");
      if (!inDesign && !inReview) return;
      if (e.target.tagName === "INPUT" || e.target.tagName === "TEXTAREA") return;
      if (e.key === "ArrowLeft") { e.preventDefault(); fpGo(-1); }
      else if (e.key === "ArrowRight") { e.preventDefault(); fpGo(1); }
      else if (inDesign && (e.key === "ArrowUp" || e.key === "ArrowDown")) {
        e.preventDefault();
        var container = document.getElementById("fpCandidatesList");
        var items = container.querySelectorAll(".fp-candidate");
        if (!items.length) return;
        var curIdx = -1;
        items.forEach(function(el, i) { if (el.classList.contains("selected")) curIdx = i; });
        var nextIdx = e.key === "ArrowUp" ? curIdx - 1 : curIdx + 1;
        if (nextIdx < 0) nextIdx = 0;
        if (nextIdx >= items.length) nextIdx = items.length - 1;
        if (nextIdx !== curIdx) {
          items[nextIdx].click();
          items[nextIdx].scrollIntoView({ block: "nearest" });
        }
      }
    });

    // DEV: auto-load test floor plan image + rooms JSON
    fetch("test_floor_plan.png")
      .then(function(r) { return r.ok ? r.blob() : null; })
      .then(function(blob) {
        if (!blob) return;
        var reader = new FileReader();
        reader.onload = function(ev) {
          var img = new Image();
          img.onload = function() {
            window.fpOverlay = {
              dataUrl: ev.target.result,
              pxPerCm: 2,
              imgW: img.width,
              imgH: img.height,
            };
            var ovStatus = document.getElementById("fpOverlayStatus");
            if (ovStatus) ovStatus.textContent = img.width + "x" + img.height + " px loaded";
            var fpTog = document.getElementById("fpOverlayToggle");
            if (fpTog) fpTog.checked = true;
            var rvTog = document.getElementById("rvOverlayToggle");
            if (rvTog) rvTog.checked = true;
          };
          img.src = ev.target.result;
        };
        reader.readAsDataURL(blob);
      })
      .catch(function() {});
    fetch("test_rooms.json")
      .then(function(r) { return r.ok ? r.text() : null; })
      .then(function(json) {
        if (json) {
          document.getElementById("fpRoomsJson").value = json;
          fpLoadAndMatch(json);
        }
      })
      .catch(function() {});
  });

  // Expose for ingestion integration
  window.fpLoadAndMatch = fpLoadAndMatch;
})();
