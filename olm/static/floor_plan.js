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

  // Canonical abs ↔ south rotation lives in canonical_io.js (window.canonicalIO).

  // ── Natural alphanumeric sort ─────────────────────────────────────────
  function natSort(a, b) {
    return a.localeCompare(b, undefined, { numeric: true, sensitivity: "base" });
  }

  // ── Room preparation (no server round-trip) ─────────────────────────
  // Chantier A : lazy per-room matching. prepareFpRooms parses input,
  // canonicalises rooms, populates fpData.rooms with all_candidates=null
  // and by_standard=null. Matching happens lazily via ensureRoomMatched
  // when the Design tab displays a room.
  // Bimode: accepts Array (ingState.rooms) or JSON string (file upload).
  var _matchGeneration = 0;
  var _matchInFlight = {};

  function prepareFpRooms(arg) {
    _matchGeneration++;
    _matchInFlight = {};
    var _fpScale = (window.ingState && window.ingState.scale) || 0;
    var rooms;
    if (typeof arg === "string") {
      var parsed;
      try { parsed = JSON.parse(arg); } catch(e) {
        alertModal("Invalid JSON: " + e.message); return;
      }
      var roomsInput;
      if (Array.isArray(parsed.rooms)) {
        roomsInput = parsed.rooms;
      } else if (parsed.rooms && typeof parsed.rooms === 'object') {
        roomsInput = Object.keys(parsed.rooms).map(function (id) {
          return Object.assign({ name: id }, parsed.rooms[id]);
        });
      } else {
        roomsInput = [];
      }
      if (!roomsInput.length) {
        alertModal("No rooms found in JSON"); return;
      }
      rooms = roomsInput.map(function (r) {
        return (r.corridor_face_abs !== undefined)
          ? r
          : window.canonicalIO.fromStorage(r, _fpScale);
      });
    } else if (Array.isArray(arg)) {
      if (!arg.length) { alertModal("No rooms to match"); return; }
      rooms = arg.map(function (r) {
        return (r.corridor_face_abs !== undefined)
          ? r
          : window.canonicalIO.fromStorage(r, _fpScale);
      });
    } else {
      console.warn("prepareFpRooms: invalid argument", arg); return;
    }

    // Sort by alphanumeric name (non-mutating)
    rooms = rooms.slice().sort(function (a, b) {
      return natSort(a.name || "", b.name || "");
    });

    // Mark every room as unmatched (null = not yet matched; distinguished
    // from [] = matched with 0 candidates by ensureRoomMatched).
    rooms.forEach(function(r) {
      r.all_candidates = null;
      r.by_standard = null;
    });

    // D-130 : preserve current selection by name across replacement.
    var prevName = null;
    if (fpData.rooms && fpData.currentIdx != null &&
        fpData.rooms[fpData.currentIdx]) {
      prevName = fpData.rooms[fpData.currentIdx].name;
    }
    fpData.rooms = rooms;
    if (prevName) {
      var foundIdx = fpData.rooms.findIndex(function (r) {
        return r.name === prevName;
      });
      fpData.currentIdx = foundIdx >= 0 ? foundIdx : 0;
    } else {
      fpData.currentIdx = 0;
    }
    // Render views — candidates show placeholder until lazily matched.
    fpRenderCurrent();
    rvRenderCurrent();
    document.activeElement.blur();
  }

  // ── API room builder (shared by ensureRoomMatched & fpRematchRoom) ──
  // Merges openings + doors into a single openings[] with has_door flag,
  // as expected by the /api/floor-plan/match backend.
  function _buildApiRoom(r) {
    var apiOpenings = (r.openings || []).filter(function (o) {
      return o && o.face;
    }).map(function (o) {
      return Object.assign({}, o, { has_door: false });
    });
    (r.doors || []).forEach(function (d) {
      if (!d || !d.face) return;
      apiOpenings.push(Object.assign({}, d, {
        has_door: true,
        opens_inward: d.opens_inward !== false,
        hinge_side: d.hinge_side || "left",
      }));
    });
    return Object.assign({}, r, { openings: apiOpenings, doors: undefined });
  }

  // ── Single-room match fetch wrapper ───────────────────────────────────
  // Sends one room to /api/floor-plan/match and calls onDone(responseRoom)
  // or onDone(null) on error. Caller stores results as appropriate.
  function _matchSingleRoom(roomName, apiRoom, onDone) {
    if (window._perf) window._perf.mark("fetch /api/floor-plan/match : sent");
    fetch("/api/floor-plan/match", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ rooms: [apiRoom] }),
    })
    .then(function(r) { return r.json(); })
    .then(function(data) {
      if (window._perf) {
        window._perf.mark("fetch /api/floor-plan/match : parsed");
        if (data._perf) {
          window._perf.setExtra("server_match_ms", data._perf.total_ms);
        }
      }
      if (data.error || !data.rooms || !data.rooms.length) {
        console.warn("Match error for " + roomName + ":",
          data.error || "empty response");
        onDone(null);
        return;
      }
      onDone(data.rooms[0]);
    })
    .catch(function(e) {
      console.warn("Match network error for " + roomName + ":", e);
      onDone(null);
    });
  }

  // ── Lazy per-room matching ────────────────────────────────────────────
  // Matches a single room on demand. Cache: all_candidates !== null means
  // already matched. Guards concurrent fetches via _matchInFlight queue.
  // R1: stores ONLY all_candidates + by_standard — never rewrites geometry.
  function ensureRoomMatched(roomName, cb) {
    var room = null;
    for (var i = 0; i < fpData.rooms.length; i++) {
      if (fpData.rooms[i].name === roomName) { room = fpData.rooms[i]; break; }
    }
    if (!room) { if (cb) cb(); return; }
    // Already matched (including [] = matched with 0 candidates)
    if (room.all_candidates !== null) { if (cb) cb(); return; }
    // Match in flight for this room — queue callback
    if (_matchInFlight[roomName]) {
      if (cb) _matchInFlight[roomName].push(cb);
      return;
    }
    _matchInFlight[roomName] = cb ? [cb] : [];
    var gen = _matchGeneration;
    var apiRoom = _buildApiRoom(room);
    _matchSingleRoom(roomName, apiRoom, function(responseRoom) {
      // Discard if rooms were replaced (generation changed by prepareFpRooms)
      if (gen !== _matchGeneration) return;
      for (var j = 0; j < fpData.rooms.length; j++) {
        if (fpData.rooms[j].name === roomName) {
          if (responseRoom) {
            fpData.rooms[j].all_candidates =
              responseRoom.all_candidates || [];
            fpData.rooms[j].by_standard =
              responseRoom.by_standard || {};
          } else {
            fpData.rooms[j].all_candidates = [];
            fpData.rooms[j].by_standard = {};
          }
          break;
        }
      }
      var cbs = _matchInFlight[roomName] || [];
      delete _matchInFlight[roomName];
      cbs.forEach(function(fn) { fn(); });
    });
  }
  window.ensureRoomMatched = ensureRoomMatched;

  // Matches all unmatched rooms sequentially with progress feedback.
  // Used by fpExport before building the export payload.
  function ensureAllMatched(cb) {
    var unmatched = [];
    fpData.rooms.forEach(function(r) {
      if (r.all_candidates === null) unmatched.push(r.name);
    });
    if (!unmatched.length) { cb(); return; }
    var total = unmatched.length;
    var done = 0;
    function next() {
      if (done >= total) {
        setStatus("Matching complete.");
        cb();
        return;
      }
      setStatus("Matching " + (done + 1) + "/" + total + "...");
      ensureRoomMatched(unmatched[done], function() {
        done++;
        next();
      });
    }
    next();
  }
  window.ensureAllMatched = ensureAllMatched;

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
    // Amend mode : Plan area reste figée (valeur cartouche), seul le Bbox
    // évolue avec le resize utilisateur. rvRenderCurrent a déjà peuplé
    // rvRoomPlanArea au dernier refresh ; on ne met à jour que Bbox area
    // et Bbox size ici.
    var w = state.room_width_cm || 0;
    var d = state.room_depth_cm || 0;
    var bboxAreaEl = document.getElementById("rvRoomBboxArea");
    if (bboxAreaEl) bboxAreaEl.textContent = (w * d / 10000).toFixed(2);
    var bboxSizeEl = document.getElementById("rvRoomBboxSize");
    if (bboxSizeEl) bboxSizeEl.textContent = w + " × " + d;
  }

  // Recompute and refresh the Floor properties panel (room count + total
  // area m²) from fpRooms(). Extracted so it can be called on scale change
  // in ingestion.js without waiting for an async match round-trip — cf.
  // docs/INVESTIGATION_total_area_refresh.md.
  function updateFloorProperties() {
    var allRooms = fpRooms();
    var totalArea = 0;
    allRooms.forEach(function(r) {
      totalArea += (r.width_cm || 0) * (r.depth_cm || 0) / 10000;
    });
    var roomsEl = document.getElementById("rvFloorRooms");
    if (roomsEl) roomsEl.textContent = allRooms.length;
    var areaEl = document.getElementById("rvFloorArea");
    if (areaEl) areaEl.textContent = totalArea.toFixed(1);
  }
  window.updateFloorProperties = updateFloorProperties;

  // Returns the amendment marker text (without leading space) when the
  // user has amended the room's geometry (room.room_amended, set by
  // fpRematchRoom) and/or its layout (fpAmendments[name], set by Amend
  // Layout Save). Rendered as a separate badge by _setRoomLabel.
  function _amendmentSuffix(room) {
    if (!room) return "";
    var geo = !!room.room_amended;
    var lay = !!fpAmendments[room.name];
    if (geo && lay) return "Room & Layout amended";
    if (geo) return "Room amended";
    if (lay) return "Layout amended";
    return "";
  }

  // Sets the room label as a base name + optional small "amended" badge.
  // The badge sits next to (not inside) the bold room-label box, so
  // appending it does not force the label cell to widen.
  function _setRoomLabel(elId, roomName, room) {
    var el = document.getElementById(elId);
    if (!el) return;
    // Inner text span if present (preserves the chevron sibling),
    // else fall back to the label element itself.
    var textEl = document.getElementById(elId + "Text") || el;
    textEl.textContent = roomName;
    // Amend badge: place INSIDE the label box (between the text span
    // and the chevron) so it stays visually attached to the room name.
    var badgeId = elId + "_amendBadge";
    var existing = document.getElementById(badgeId);
    var marker = _amendmentSuffix(room);
    if (!marker) {
      if (existing && existing.parentNode) existing.parentNode.removeChild(existing);
      return;
    }
    if (!existing) {
      existing = document.createElement("span");
      existing.id = badgeId;
      existing.className = "fp-amend-tag";
      // Insert right after the text span (before the chevron, if any).
      if (textEl !== el && textEl.parentNode === el) {
        el.insertBefore(existing, textEl.nextSibling);
      } else {
        el.appendChild(existing);
      }
    }
    existing.textContent = marker;
  }

  function rvRenderCurrent() {
    // v0.5.34 instrumentation : la capture demarre au clic d'onglet (init.js).
    // Ici on marque seulement (rvRenderCurrent tourne dans la session active).
    if (window._perf) window._perf.mark("rvRenderCurrent enter");
    // Floor properties always refreshed (independent of selected room).
    updateFloorProperties();
    if (window._perf) window._perf.mark("updateFloorProperties");

    var room = fpCurrent();
    if (!room) {
      _setRoomLabel("rvRoomLabel", "-", null);
      document.getElementById("rvNavInfo").textContent = "0 / 0";
      document.getElementById("rvCanvas").innerHTML = "";
      return;
    }

    // Update ingestion room list to reflect current selection
    if (window.updateIngRoomList) window.updateIngRoomList();

    // Use amended data if available
    var roomData = fpRoomAmendments[room.name] || room;

    // Charge le seed + les hits depuis ingState pour la vue Room — sans ça,
    // V-Rays / H-Rays ne dessinent rien tant qu'on n'a pas cliqué sur
    // "Adjust room" ou relancé un Rescan dans la vue Room.
    if (typeof window.loadRoomHitsAndSeedFromIngState === "function") {
      window.loadRoomHitsAndSeedFromIngState(roomData);
    }
    if (window._perf) window._perf.mark("loadRoomHitsAndSeed");

    // Render room SVG in canvas (empty room, no blocks)
    var reviewSubtab = document.getElementById("tabFpReview");
    if (reviewSubtab && reviewSubtab.classList.contains("active")) {
      fpRenderEmptyRoom(roomData, document.getElementById("rvCanvas"));
    }
    if (window._perf) window._perf.mark("fpRenderEmptyRoom (sync)");

    // Navigation — same amendment-kinds label as Office view.
    _setRoomLabel("rvRoomLabel", roomData.name || "(unnamed)", room);
    document.getElementById("rvNavInfo").textContent =
      (fpData.currentIdx + 1) + " / " + fpRooms().length;

    // Room dimensions (D-135 rider : 3 champs distincts — Plan area =
    // cartouche JSON immuable ; Bbox area/size = valeurs courantes du
    // bbox, modifiables via scan ou resize utilisateur).
    var w = roomData.width_cm || 0;
    var d = roomData.depth_cm || 0;
    var planArea = (typeof roomData.plan_area_m2 === "number" && roomData.plan_area_m2 > 0)
      ? roomData.plan_area_m2.toFixed(2)
      : "-";
    document.getElementById("rvRoomPlanArea").textContent = planArea;
    document.getElementById("rvRoomBboxArea").textContent = (w * d / 10000).toFixed(2);
    document.getElementById("rvRoomBboxSize").textContent = w + " × " + d;

    // R-12 B: room already canonical in fpData (via fromStorage at load).
    var localRoom = roomData;
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
    // D-122 P4 : openings ne contient plus de doors (invariant canonique).
    (localRoom.openings || []).forEach(function(o) {
      var f = faceMap[o.face] || o.face || "?";
      dsl += "\nOPENING " + f + " " + (o.offset_cm || 0) + " " + (o.width_cm || 90);
    });
    // Doors séparées (convention fromStorage / v3 JSON).
    (localRoom.doors || []).forEach(function(d) {
      var f = faceMap[d.face] || d.face || "?";
      var dir = d.opens_inward !== false ? "INT" : "EXT";
      // NF convention: L/R = swing direction (hinge left → swings right → "R")
      var side = (d.hinge_side === "left") ? "R" : "L";
      dsl += "\nDOOR " + f + " " + (d.offset_cm || 0) + " " + (d.width_cm || 90) + " " + dir + " " + side;
    });
    (localRoom.exclusion_zones || []).forEach(function(e) {
      dsl += "\nEXCLUSION " + (e.x_cm || 0) + " " + (e.y_cm || 0) + " " + (e.width_cm || 0) + " " + (e.depth_cm || 0);
    });
    document.getElementById("rvRoomDsl").value = dsl;
  }

  // ── Standard filter ────────────────────────────────────────────────────
  function fpGetStandardFilter() {
    return getCurrentStandard();
  }

  // ── Selected solution panel ──────────────────────────────────────────
  function _updateSelectedSolution(candidate, amendment) {
    var container = document.getElementById("fpSelectedSolution");
    if (!container) return;
    var c = amendment || candidate;
    if (!c) {
      container.innerHTML =
        '<div style="color:var(--text-dim);font-size:var(--fs-xs);' +
        'padding:4px 0;">No selection</div>';
      return;
    }
    var rg = c.room_grade || c.circulation_grade || "F";
    var gradeClass = "fp-grade-" + rg;
    var badge = "";
    if (amendment && amendment.saved) badge = "Saved";
    else if (amendment) badge = "Amended";
    var badgeHtml = badge
      ? '<span style="font-size:var(--fs-xs);color:var(--accent);">' +
        badge + '</span>'
      : '';
    container.innerHTML =
      '<div class="fp-candidate selected" tabindex="-1" style="border:1px solid ' +
      'var(--accent);border-radius:4px;cursor:pointer;">' +
        '<div style="display:flex;justify-content:space-between;' +
        'align-items:center;">' +
          '<span class="fp-c-name">' + c.pattern_name + '</span>' +
          badgeHtml +
        '</div>' +
        '<div class="fp-c-stats">' +
          c.n_desks + ' desks &middot; ' + c.m2_per_desk +
          ' m&sup2;/d &middot; ' +
          '<span class="fp-c-grade ' + gradeClass + '">' +
          rg + '</span>' +
          ' &middot; ' + getStdLabel(c.standard) +
        '</div>' +
      '</div>';
    // Click → render this solution in SVG
    container.querySelector(".fp-candidate").addEventListener("click",
      function() {
        var room = fpCurrent();
        if (!room) return;
        document.querySelectorAll("#fpCandidatesList .fp-candidate")
          .forEach(function(el) { el.classList.remove("selected"); });
        fpRenderSvg(room, c);
      });
  }

  // ── Render current room ────────────────────────────────────────────────
  window.fpRenderCurrent = fpRenderCurrent;
  function fpRenderCurrent() {
    var room = fpCurrent();
    if (!room) {
      _setRoomLabel("fpRoomLabel", "-", null);
      document.getElementById("fpNavInfo").textContent = "0 / 0";
      document.getElementById("fpCandidatesList").innerHTML =
        '<div class="fp-no-match">Load a room JSON file from the Input tab</div>';
      document.getElementById("fpCanvas").innerHTML = "";
      return;
    }

    // Update room list highlight in Design
    if (window.updateIngRoomList) window.updateIngRoomList();



    // Standard filter: always current_standard (no DOM radio to reset)

    // Action buttons always enabled. Handlers branch on candidate presence :
    // - Add pattern : with candidate → edit existing; without → blank pattern.
    // - Amend layout : with candidate → amend existing; without → empty room.
    document.getElementById("fpBtnEditPattern").disabled = false;
    document.getElementById("fpBtnAdjustLayout").disabled = false;
    // Show Discard if amendment exists, hide Save layout on room change
    var amendment = fpAmendments[room.name];
    var discardBtn = document.getElementById("fpBtnDiscard");
    discardBtn.style.display = amendment ? "" : "none";
    if (amendment && amendment.saved) {
      discardBtn.textContent = "Revert save";
      discardBtn.title = "Remove saved layout choice";
    } else if (amendment) {
      discardBtn.textContent = "Revert amendment";
      discardBtn.title = "Revert to original matching result";
    }
    document.getElementById("fpBtnSaveLayout").style.display = "none";

    // Selected solution panel
    _updateSelectedSolution(null, amendment);

    // Navigation
    // Amendment kinds (room.room_amended = geometry, fpAmendments[name] = layout).
    // fpRoomAmendments is a canonical data cache, not a user-amendment signal.
    _setRoomLabel("fpRoomLabel", room.name || "(unnamed)", room);
    document.getElementById("fpNavInfo").textContent =
      (fpData.currentIdx + 1) + " / " + fpRooms().length;
    // Reset candidate before re-render to avoid stale value leaking into
    // Amend Layout / Add pattern handlers when the new room has no
    // candidate (firstCand.click() below would otherwise leave the
    // previous room's candidate in fpCurrentCandidate).
    fpCurrentCandidate = null;

    // Candidates: real list if cached, placeholder if not yet matched.
    // D3(a) guard inside fpRenderCandidates handles null all_candidates.
    fpRenderCandidates(room);

    // R5: synchronous auto-select.
    var _amend = fpAmendments[room.name];
    if (_amend) {
      // Saved/amended solution — show immediately (no match needed).
      var selCard = document.querySelector(
        "#fpSelectedSolution .fp-candidate");
      if (selCard) selCard.click();
    } else if (room.all_candidates !== null) {
      // Already matched (from cache) — select first candidate.
      var firstCand = document.querySelector(
        "#fpCandidatesList .fp-candidate");
      if (firstCand) {
        firstCand.click();
      } else {
        fpRenderEmptyRoom(room, document.getElementById("fpCanvas"));
      }
    } else {
      // Not yet matched — show empty room while waiting.
      fpRenderEmptyRoom(room, document.getElementById("fpCanvas"));
    }

    // Lazy match: trigger fetch only when Design tab is active.
    // At import time the user is on Import tab — no match fired.
    // When user switches to Design, init.js calls fpRenderCurrent again.
    if (room.all_candidates === null) {
      var designTab = document.getElementById("tabLytDesign");
      if (designTab && designTab.classList.contains("active")) {
        var matchRoomName = room.name;
        ensureRoomMatched(matchRoomName, function() {
          // Race guard: discard if user navigated to another room.
          var cur = fpCurrent();
          if (!cur || cur.name !== matchRoomName) return;
          fpRenderCandidates(cur);
          // Auto-select first candidate if no saved amendment.
          if (!fpAmendments[cur.name]) {
            var firstCand = document.querySelector(
              "#fpCandidatesList .fp-candidate");
            if (firstCand) firstCand.click();
          }
        });
      }
    }
  }

  function fpRenderEmptyRoom(room, targetSvg) {
    // R-12 B: room already canonical in fpData (via fromStorage at load).
    // Editor et Review partagent le même repère canonique.
    var localRoom = room;
    state.rows = [];
    state.row_gaps_cm = [];
    state.furniture = [];
    state.selectedFurniture = -1;
    state.room_width_cm = localRoom.width_cm;
    state.room_depth_cm = localRoom.depth_cm;
    state.room_windows = localRoom.windows || [];
    // D-122 P4 : openings et doors séparés dans le state, même invariant
    // que fpData / ingState post-fromStorage.
    state.room_openings = (localRoom.openings || []).slice();
    state.room_doors = (localRoom.doors || []).slice();
    state.room_exclusions = localRoom.exclusion_zones || [];
    state.room_transparents = localRoom.transparent_zones || [];
    // D-122 P3 : state.corridor_face_abs seul (corridor_face canon = "south").
    state.corridor_face_abs = room.corridor_face_abs || "";
    state.selectedRow = 0;
    state.selectedBlock = -1;

    // Inject overlay if active (check both Design and Review toggles)
    // Auto-align: use bbox_px to offset the plan image so the room aligns at (0,0)
    var fpOvChecked = document.getElementById("fpOverlayToggle").checked;
    var rvOvChecked = document.getElementById("rvOverlayToggle").checked;
    if (window.fpOverlay && (fpOvChecked || rvOvChecked)) {
      var ov = window.fpOverlay;
      var fpOvOpacity = parseInt(document.getElementById("rvOverlayOpacity").value) ||
        parseInt(document.getElementById("fpOverlayOpacity").value) || 15;
      // bbox_px gives the room position in the plan image (pixels)
      var ovOffX = 0, ovOffY = 0;
      if (room.bbox_px) {
        ovOffX = room.bbox_px[0] / ov.pxPerCm;  // px → cm
        ovOffY = room.bbox_px[1] / ov.pxPerCm;
      }
      // D-247 : hide-detection-colors → withCleanParam adds &clean=1 so the
      // server neutralises exterior/corridor colours on the overlay.
      state.overlay = {
        dataUrl: window.withCleanParam(ov.dataUrl),
        pxPerCm: ov.pxPerCm, opacity: fpOvOpacity,
        offsetX: ovOffX, offsetY: ovOffY, imgW: ov.imgW, imgH: ov.imgH,
      };
    } else {
      state.overlay = null;
    }

    // v0.5.33 instrumentation : sonde l'overlay (type/taille/dims/decode).
    if (window._perf) window._perf.probeImage(state.overlay && state.overlay.dataUrl);
    render(targetSvg);
    // Delay zoomFit to ensure the SVG container is laid out
    requestAnimationFrame(function() {
      if (window._perf) window._perf.mark("rAF: before zoomFit");
      zoomFit(targetSvg);
      if (window._perf) window._perf.mark("rAF: after zoomFit");
    });
  }

  // ── Candidate list ─────────────────────────────────────────────────────
  function fpRenderCandidates(room) {
    var container = document.getElementById("fpCandidatesList");
    // D3(a): guard for unmatched rooms (null = not yet matched).
    // Distinct from [] = matched with 0 candidates (falls through to
    // "No matching patterns" below).
    if (!room.all_candidates) {
      container.innerHTML =
        '<div class="fp-no-match">Matching in progress...</div>';
      return;
    }
    var stdFilter = fpGetStandardFilter();

    // Candidate list: pure catalogue data, never affected by amendments.
    var candidates = room.all_candidates.slice();

    if (stdFilter) {
      candidates = candidates.filter(function(c) { return c.standard === stdFilter; });
    }

    var gradeOrd = { A: 0, B: 1, C: 2, D: 3, E: 4, F: 5 };
    function gradeVal(g) { return g in gradeOrd ? gradeOrd[g] : 6; }
    var fitOrd = {fitting: 0, oversize_1axis: 1, oversize_2axes: 2};
    function fitVal(c) { return fitOrd[c.fit_class] != null ? fitOrd[c.fit_class] : (c.oversize ? 1 : 0); }
    candidates.sort(function(a, b) {
      // D-299: feasible before infeasible (unreachable desks or critical passage)
      var ia = (a.min_passage_cm <= 0) || a.passage_grade === "F" ? 1 : 0;
      var ib = (b.min_passage_cm <= 0) || b.passage_grade === "F" ? 1 : 0;
      if (ia !== ib) return ia - ib;
      // Fitting first, then oversize_1axis, then oversize_2axes
      var fa = fitVal(a), fb = fitVal(b);
      if (fa !== fb) return fa - fb;
      // Within oversize groups: overflow ascending
      if (fa > 0) {
        var od = (a.overflow_cm || 0) - (b.overflow_cm || 0);
        if (od !== 0) return od;
      }
      if (b.n_desks !== a.n_desks) return b.n_desks - a.n_desks;
      var gd = gradeVal(a.room_grade || a.circulation_grade) - gradeVal(b.room_grade || b.circulation_grade);
      if (gd !== 0) return gd;
      var pd = (b.min_passage_cm || 0) - (a.min_passage_cm || 0);
      if (pd !== 0) return pd;
      var md = (a.m2_per_desk || 99) - (b.m2_per_desk || 99);
      if (md !== 0) return md;
      return (a.pattern_name || "").localeCompare(b.pattern_name || "");
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
      var rg = c.room_grade || c.circulation_grade || "F";
      var gradeClass = "fp-grade-" + rg;
      var classes = "fp-candidate";
      if (c.oversize) classes += " fp-oversize";
      if (isBest) classes += " selected best";
      return '<div class="' + classes + '" tabindex="-1" data-fp-cand="' + i + '">' +
        '<div style="display:flex;justify-content:space-between;align-items:center;">' +
          '<span class="fp-c-name">' + c.pattern_name + '</span>' +
        '</div>' +
        '<div class="fp-c-stats">' +
          c.n_desks + ' desks &middot; ' + c.m2_per_desk + ' m&sup2;/d &middot; ' +
          '<span class="fp-c-grade ' + gradeClass + '">' + rg + '</span>' +
          (c.fit_class === "oversize_1axis" ? ' &middot; +' + Math.round(c.overflow_cm) + 'cm (1 axis)' : '') +
          (c.fit_class === "oversize_2axes" ? ' &middot; +' + Math.round(c.overflow_cm) + 'cm (2 axes)' : '') +
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
        document.getElementById("fpBtnSaveLayout").style.display = "";
      });
    });
  }

  // ── SVG rendering ──────────────────────────────────────────────────────
  // Currently displayed candidate (for keyboard navigation in list)
  var fpCurrentCandidate = null;

  // D-286: source catalogue name of the currently selected candidate (or
  // null). Reset to null on every Office room render (see fpRenderRoom).
  // Used by the Catalogue tab to pre-select the matching card.
  window.fpGetSelectedPatternName = function() {
    return (fpCurrentCandidate && fpCurrentCandidate.pattern_name) || null;
  };

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
    setActiveStandard(pat.standard || candidate.standard || getStandards()[0] || "");
    state.room_windows = pat.room_windows || [];
    // D-122 P4 : pattern catalogue stocke openings combiné → split.
    _splitOpeningsIntoState(pat.room_openings);
    state.room_exclusions = pat.room_exclusions || [];
    state.corridor_face_abs = room.corridor_face_abs || "";
    state.name = candidate.pattern_name || pat.name || "";
    state._savedName = null;
    state.selectedRow = 0;
    state.selectedBlock = -1;
    // D-256: load furniture from candidate (cabinets in saved_layout)
    state.furniture = JSON.parse(JSON.stringify(candidate.furniture || []));
    state.selectedFurniture = -1;

    document.getElementById("roomWidth").value = state.room_width_cm;
    document.getElementById("roomDepth").value = state.room_depth_cm;
    document.getElementById("autoName").textContent = state.name;

    // Inject floor plan overlay if visible
    var fpOvToggle = document.getElementById("fpOverlayToggle");
    if (window.fpOverlay && fpOvToggle && fpOvToggle.checked) {
      var ov = window.fpOverlay;
      // D-125 : offset depuis bbox_px (même convention que fpRenderEmptyRoom,
      // ligne 318-321) ; le champ _overlayOffsetX/Y n'était jamais défini
      // côté producteur → 0 → état overlay corrompu et partagé avec rvCanvas
      // (race post-Save via fpRematchRoom async).
      var roomOvX = 0, roomOvY = 0;
      if (room.bbox_px) {
        roomOvX = room.bbox_px[0] / ov.pxPerCm;
        roomOvY = room.bbox_px[1] / ov.pxPerCm;
      }
      var fpOvOpacity = parseInt(document.getElementById("fpOverlayOpacity").value) || 15;
      // Always use ov.dataUrl (-SD enhanced version, no detection colors).
      // User requirement 2026-05-19.
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

  function _fmtDim(v) { return v == null ? "n/a" : v.toFixed(2); }

  // Green / orange / red by value, aligned with the grade thresholds
  // (A/B ≥ 0.75, C/D ≥ 0.45, E/F below).
  function _scoreColor(v) {
    if (v >= 0.75) return "var(--ok)";
    if (v >= 0.45) return "var(--warn)";
    return "var(--bad)";
  }

  // One score row: label + coloured mini-bar + value. v is a 0–1 note that
  // drives the bar width and colour; text overrides the printed value
  // (e.g. "82 %"). v == null → "n/a" (dimension not applicable).
  function _scoreRow(label, v, text) {
    if (v == null) {
      return '<div class="fp-score-row"><span class="fp-score-label">' +
        label + '</span><span class="fp-score-na">' + (text || "n/a") +
        '</span></div>';
    }
    var pct = Math.max(0, Math.min(100, Math.round(v * 100)));
    return '<div class="fp-score-row"><span class="fp-score-label">' +
      label + '</span><span class="fp-score-bar"><span class="fp-score-fill" ' +
      'style="width:' + pct + '%;background:' + _scoreColor(v) + ';"></span>' +
      '</span><span class="fp-score-val">' + (text || v.toFixed(2)) +
      '</span></div>';
  }

  // Row without a bar — for unbounded / categorical metrics (no 0→max scale).
  function _valueRow(label, text) {
    return '<div class="fp-score-row"><span class="fp-score-label">' +
      label + '</span><span class="fp-row-val">' + text + '</span></div>';
  }

  // Fit summary from the 4-state classification (D-285/oversize).
  function _fmtFit(c) {
    if (c.fit_class === "oversize_1axis") {
      return "+" + Math.round(c.overflow_cm || 0) + "cm (1 axis)";
    }
    if (c.fit_class === "oversize_2axes") {
      return "+" + Math.round(c.overflow_cm || 0) + "cm (2 axes)";
    }
    return c.oversize ? "oversize" : "fits";
  }

  function _gradeTooltip(c) {
    var rg = c.room_grade || c.circulation_grade || "F";
    var cs = c.composite_score != null ? c.composite_score.toFixed(2) : "?";
    var lines = [
      "Grade " + rg + " \u2014 composite " + cs,
      "\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500",
      "Accessibility   : " + _fmtDim(c.dim_reachability),
      "Passage comfort : " + _fmtDim(c.dim_passage),
      "Natural light   : " + _fmtDim(c.dim_light),
      "Back to door    : " + _fmtDim(c.dim_back_door),
      "Face to wall    : " + _fmtDim(c.dim_face_wall),
      "\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500",
      "A \u2265 0.90 \u00b7 B \u2265 0.75 \u00b7 C \u2265 0.60 \u00b7 D \u2265 0.45 \u00b7 E \u2265 0.30",
    ];
    return lines.join("\n");
  }

  function fpUpdateInfo(room, candidate) {
    var area = (room.width_cm * room.depth_cm / 10000).toFixed(1);
    document.getElementById("fpInfoDims").textContent = room.width_cm + " x " + room.depth_cm + " cm";
    document.getElementById("fpInfoArea").textContent = area;
    document.getElementById("fpInfoPattern").textContent = candidate.pattern_name || "-";
    document.getElementById("fpInfoStandard").textContent = getStdLabel(candidate.standard) || "-";
    document.getElementById("fpInfoDesks").textContent = candidate.n_desks || "-";
    document.getElementById("fpInfoM2").textContent = candidate.m2_per_desk ? candidate.m2_per_desk.toFixed(1) : "-";
    // D-293: Grade en tête du panneau Scores (lettre + barre composite)
    var rg = candidate.room_grade || candidate.circulation_grade || "-";
    var compositeVal = candidate.composite_score;
    var gradeHtml = (rg === "-") ? '<div class="fp-score-row"><span class="fp-score-label">Grade</span><span class="fp-score-na">-</span></div>' :
      '<div class="fp-score-row" title="' + _gradeTooltip(candidate).replace(/"/g, '&quot;') + '" style="cursor:help;">' +
      '<span class="fp-score-label">Grade</span>' +
      '<span class="fp-c-grade fp-grade-' + rg + '" style="margin-right:6px;">' + rg + '</span>' +
      '<span class="fp-score-bar"><span class="fp-score-fill" style="width:' +
        (compositeVal != null ? Math.round(compositeVal * 100) : 0) + '%;background:' +
        _scoreColor(compositeVal != null ? compositeVal : 0) + ';"></span></span>' +
      '<span class="fp-score-val">' + (compositeVal != null ? compositeVal.toFixed(2) : "-") + '</span></div>';

    // Score breakdown (per-criterion notes 0–1) as coloured mini-bars.
    document.getElementById("fpScores").innerHTML = gradeHtml +
      _scoreRow("Accessibility", candidate.dim_reachability) +
      _scoreRow("Passage comfort", candidate.dim_passage) +
      _scoreRow("Natural light", candidate.dim_light) +
      _scoreRow("Back to door", candidate.dim_back_door) +
      _scoreRow("Face to wall", candidate.dim_face_wall);

    // Metrics: Connectivity is a 0–100 % → coloured bar; the others are
    // unbounded ratios / areas / categorical → plain values (no bar).
    var conn = candidate.connectivity_pct;
    var det = candidate.worst_detour;
    var fr = candidate.largest_free_rect_m2;
    document.getElementById("fpMetrics").innerHTML =
      _valueRow("Min passage",
                candidate.min_passage_cm ? candidate.min_passage_cm + " cm" : "-") +
      _scoreRow("Connectivity", conn != null ? conn / 100 : null,
                conn != null ? Math.round(conn) + " %" : null) +
      _valueRow("Worst detour",
                (det != null && isFinite(det)) ? det.toFixed(2) : "n/a") +
      _valueRow("Free area", fr != null ? fr.toFixed(1) + " m²" : "-") +
      _valueRow("Fit", _fmtFit(candidate));

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
  // Re-match a single room with amended geometry.
  // amendedRoom is already in API format (openings merged with has_door,
  // doors deleted) — passed directly to _matchSingleRoom.
  window.fpRematchRoom = function(roomName, amendedRoom) {
    _matchSingleRoom(roomName, amendedRoom, function(responseRoom) {
      if (!responseRoom) {
        setStatus("Re-matching error for \"" + roomName + "\".");
        return;
      }
      // D-122 P5 : réponse canonique ; D-122 P4 : split openings.
      var split = window.splitOpeningsToFrontEnd(
        responseRoom.openings || []);
      for (var i = 0; i < fpData.rooms.length; i++) {
        if (fpData.rooms[i].name === roomName) {
          fpData.rooms[i].width_cm = responseRoom.width_cm;
          fpData.rooms[i].depth_cm = responseRoom.depth_cm;
          fpData.rooms[i].windows = responseRoom.windows;
          fpData.rooms[i].openings = split.openings;
          fpData.rooms[i].doors = split.doors;
          fpData.rooms[i].exclusion_zones = responseRoom.exclusion_zones;
          fpData.rooms[i].all_candidates = responseRoom.all_candidates;
          fpData.rooms[i].by_standard = responseRoom.by_standard;
          fpData.rooms[i].room_amended = true;
          break;
        }
      }
      delete fpAmendments[roomName];
      fpRenderCurrent();
      rvRenderCurrent();
      setStatus(
        "Room \"" + roomName + "\" re-matched with amended geometry.");
    });
  };

  function fpExport() {
    if (!fpRooms().length) { alertModal("No results to export"); return; }
    // D2/D3(b): match all unmatched rooms before building export payload.
    ensureAllMatched(function() { _doFpExport(); });
  }

  function _doFpExport() {
    var gradeOrd = { A: 0, B: 1, C: 2, D: 3, E: 4, F: 5 };
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
              room_grade: best.room_grade,
              composite_score: best.composite_score,
              connectivity_pct: best.connectivity_pct,
              min_passage_cm: best.min_passage_cm,
              worst_detour: best.worst_detour,
              largest_free_rect_m2: best.largest_free_rect_m2,
              dim_reachability: best.dim_reachability,
              dim_passage: best.dim_passage,
              passage_grade: best.passage_grade,
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
            room_grade: c.room_grade,
            composite_score: c.composite_score,
            connectivity_pct: c.connectivity_pct,
            min_passage_cm: c.min_passage_cm,
            worst_detour: c.worst_detour,
            largest_free_rect_m2: c.largest_free_rect_m2,
            dim_reachability: c.dim_reachability,
            dim_passage: c.dim_passage,
            passage_grade: c.passage_grade,
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

    // Standard filter is now a static badge (no listener needed)

    // Grid toggle sync across all tabs (Review, Design, Editor)
    function syncGridToggle(checked) {
      state.gridVisible = checked;
      ['gridToggle', 'fpGridToggle', 'rvGridToggle'].forEach(function(id) {
        var el = document.getElementById(id);
        if (el) el.checked = checked;
      });
    }

    window.syncGridToggle = syncGridToggle;

    // Overlay toggle sync across all tabs
    function syncOverlayToggle(checked) {
      ['fpOverlayToggle', 'rvOverlayToggle', 'edOverlayToggle'].forEach(function(id) {
        var el = document.getElementById(id);
        if (el) el.checked = checked;
      });
    }
    window.syncOverlayToggle = syncOverlayToggle;

    // Overlay opacity sync across all tabs
    function syncOverlayOpacity(value) {
      ['fpOverlayOpacity', 'rvOverlayOpacity', 'edOverlayOpacity'].forEach(function(id) {
        var el = document.getElementById(id);
        if (el) el.value = value;
      });
      ['fpOverlayOpacityVal', 'rvOverlayOpacityVal', 'edOverlayOpacityVal'].forEach(function(id) {
        var el = document.getElementById(id);
        if (el) el.textContent = value + '%';
      });
    }
    window.syncOverlayOpacity = syncOverlayOpacity;

    // Default overlay/grid state applied on startup and on every plan load.
    // Persisted in localStorage (Settings → Display). Defaults: overlay on,
    // grid on, opacity 15%. User can re-toggle manually after load.
    function _ovDefBool(key, dflt) {
      try {
        var v = localStorage.getItem(key);
        return v === null ? dflt : (v === "1");
      } catch (e) { return dflt; }
    }
    function _ovDefInt(key, dflt) {
      try {
        var n = parseInt(localStorage.getItem(key), 10);
        return isNaN(n) ? dflt : n;
      } catch (e) { return dflt; }
    }
    function applyOverlayGridDefaults() {
      syncOverlayToggle(_ovDefBool("olm_defaultOverlayVisible", true));
      syncGridToggle(_ovDefBool("olm_defaultGridVisible", true));
      syncOverlayOpacity(_ovDefInt("olm_defaultOverlayOpacity", 15));
      if (typeof window.fpRenderCurrent === "function") window.fpRenderCurrent();
      if (typeof window.rvRenderCurrent === "function") window.rvRenderCurrent();
    }
    window.applyOverlayGridDefaults = applyOverlayGridDefaults;
    // Apply once at startup so toggles/sliders reflect saved settings.
    applyOverlayGridDefaults();

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
      saveConfigField("circulation_visible", e.target.checked);
      var room = fpCurrent();
      if (room && fpCurrentCandidate) {
        fpRenderSvg(room, fpCurrentCandidate);
      }
    });

    // Synthetic blank pattern sized to the room — used when no matching
    // candidate exists and the user clicks Add pattern / Amend layout.
    function _snapFloor(v) { return Math.floor(v / GRID_STEP_CM) * GRID_STEP_CM; }
    function _snapCeil(v) { return Math.ceil(v / GRID_STEP_CM) * GRID_STEP_CM; }
    function _snapOpening(o) {
      var s = Object.assign({}, o);
      if (s.offset_cm != null) s.offset_cm = _snapFloor(s.offset_cm);
      if (s.width_cm != null) s.width_cm = _snapCeil(s.width_cm);
      return s;
    }
    function _blankPatternFromRoom(room) {
      var openings = (room.openings || []).map(function (o) {
        return Object.assign(_snapOpening(o), { has_door: false });
      });
      (room.doors || []).forEach(function (d) {
        if (d && d.face) {
          openings.push(Object.assign(_snapOpening(d), { has_door: true }));
        }
      });
      return {
        name: "",
        rows: [],
        row_gaps_cm: [],
        room_width_cm: Math.floor((room.width_cm || 0) / GRID_STEP_CM) * GRID_STEP_CM,
        room_depth_cm: Math.floor((room.depth_cm || 0) / GRID_STEP_CM) * GRID_STEP_CM,
        standard: "",
        room_windows: (room.windows || []).map(_snapOpening),
        room_openings: openings,
        room_exclusions: room.exclusion_zones || [],
      };
    }

    // Add pattern: a catalogue pattern keeps the room's doors but drops plain
    // openings and exclusion zones (room-specific, not part of a reusable
    // pattern). Doors are merged into room_openings with has_door=true.
    function _stripRoomFeatures(pattern) {
      var doorsOnly = (pattern.room_openings || []).filter(function(o) {
        return o.has_door;
      });
      return Object.assign({}, pattern, {
        room_openings: doorsOnly,
        room_exclusions: [],
      });
    }

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
        switchToEditorWithPattern(_stripRoomFeatures(fpCurrentCandidate.pattern));
        return;
      }
      // No candidate → open editor with a blank pattern dimensioned to the room.
      var room = fpCurrent();
      if (room) {
        switchToEditorWithPattern(_stripRoomFeatures(_blankPatternFromRoom(room)));
      }
    });
    document.getElementById("fpBtnAdjustLayout").addEventListener("click", function() {
      var room = fpCurrent();
      if (!room) return;
      if (fpCurrentCandidate && fpCurrentCandidate.pattern) {
        enterAmendMode(room, fpCurrentCandidate);
        return;
      }
      // No candidate → enter amend mode with a blank pattern.
      var stds = (typeof getStandards === "function") ? getStandards() : [];
      enterAmendMode(room, {
        pattern: _blankPatternFromRoom(room),
        standard: stds[0] || "",
      });
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
      syncOverlayToggle(this.checked);
      fpRenderCurrent();
    });
    document.getElementById("fpOverlayOpacity").addEventListener("input", function() {
      syncOverlayOpacity(this.value);
      fpRenderCurrent();
    });
    // Review refresh — exposed on window for inline handlers
    window._rvRefresh = function() {
      // Sync toggles across all tabs
      var rvGrid = document.getElementById("rvGridToggle");
      if (rvGrid) syncGridToggle(rvGrid.checked);
      var rvOv = document.getElementById("rvOverlayToggle");
      if (rvOv) syncOverlayToggle(rvOv.checked);
      var rvOp = document.getElementById("rvOverlayOpacity");
      if (rvOp) syncOverlayOpacity(rvOp.value);
      // Re-render
      var room = fpCurrent();
      if (!room) return;
      var roomData = fpRoomAmendments[room.name] || room;
      fpRenderEmptyRoom(roomData, document.getElementById("rvCanvas"));
    };

    // --- Minimap refresh hook ---
    window._minimapRefresh = function () {
      if (!window.renderMinimap) return;
      var ov = window.fpOverlay || null;
      // Use the -SD plan (no cartouches) for the minimap.
      var ist = window.ingState;
      if (ov && ist && ist.planPathEnhanced) {
        var sdUrl = '/api/image?path=' + encodeURIComponent(ist.planPathEnhanced);
        ov = Object.assign({}, ov, { dataUrl: sdUrl });
      }
      var room = fpCurrent();
      var roomData = room ? (fpRoomAmendments[room.name] || room) : null;
      var rooms = fpRooms();
      var vb = state.viewBox;

      // Detect which view is active to pick the right canvas.
      var rvTab = document.getElementById("tabFpReview");
      if (rvTab && rvTab.classList.contains("active")) {
        window.renderMinimap("rvMinimapCanvas", "rvMinimap",
                             roomData, rooms, ov);
      }
      var fpTab = document.getElementById("tabLytDesign");
      if (fpTab && fpTab.classList.contains("active")) {
        window.renderMinimap("fpMinimapCanvas", "fpMinimap",
                             roomData, rooms, ov);
      }
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
    document.getElementById("fpBtnBackRoom").addEventListener("click", function() {
      window.ingShowRoomView();
    });

    // Esc steps back one panel — mirror of the Pattern editor's Esc → Card view.
    // Room → Floor, Office → Room. Inhibited in amend modes (which keep their
    // own Esc to cancel/deselect) and when a modal/popup is open.
    document.addEventListener("keydown", function(e) {
      if (e.key !== "Escape") return;
      if (e.target.tagName === "INPUT" || e.target.tagName === "TEXTAREA") return;
      if (state.amendMode || state.roomAmendMode) return;
      var openPopup = ["olmModalBackdrop", "candidateHelpBackdrop", "rvRoomPopup"]
        .some(function(id) {
          var el = document.getElementById(id);
          return el && el.style.display !== "none";
        });
      if (openPopup) return;
      var tab = document.querySelector(".tab-btn.active");
      if (!tab) return;
      if (tab.dataset.tab === "fpReview") {
        e.preventDefault();
        window.ingShowPlanView();
      } else if (tab.dataset.tab === "lytDesign") {
        e.preventDefault();
        window.ingShowRoomView();
      }
    });

    document.getElementById("fpBtnSaveLayout").addEventListener("click", function() {
      var room = fpCurrent();
      if (!room || !fpCurrentCandidate) return;
      var c = fpCurrentCandidate;
      fpAmendments[room.name] = {
        pattern_name: c.pattern_name,
        standard: c.standard,
        n_desks: c.n_desks,
        m2_per_desk: c.m2_per_desk,
        circulation_grade: c.circulation_grade,
        room_grade: c.room_grade,
        composite_score: c.composite_score,
        dim_reachability: c.dim_reachability,
        dim_passage: c.dim_passage,
        passage_grade: c.passage_grade,
        dim_light: c.dim_light,
        dim_back_door: c.dim_back_door,
        dim_face_wall: c.dim_face_wall,
        connectivity_pct: c.connectivity_pct,
        min_passage_cm: c.min_passage_cm,
        worst_detour: c.worst_detour,
        largest_free_rect_m2: c.largest_free_rect_m2,
        desks: c.desks || [],
        pattern: c.pattern,
        saved: true,
      };
      document.getElementById("fpBtnSaveLayout").style.display = "none";
      var discardBtn = document.getElementById("fpBtnDiscard");
      discardBtn.style.display = "";
      discardBtn.textContent = "Revert save";
      discardBtn.title = "Remove saved layout choice";
      _updateSelectedSolution(null, fpAmendments[room.name]);
      setStatus("Layout saved for room \"" + room.name + "\".");
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
        if (json) prepareFpRooms(json);
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
        prepareFpRooms(ev.target.result);
      };
      reader.readAsText(file);
    });

    // Standard filter
    document.querySelectorAll('input[name="fpStandard"]').forEach(function(radio) {
      radio.addEventListener("change", function() { fpRenderCurrent(); });
    });

    // Keyboard nav — Design tab (Left/Right = rooms, Up/Down = candidates)
    document.addEventListener("keydown", function(e) {
      var designTab = document.getElementById("tabLytDesign");
      var reviewSubtab = document.getElementById("tabFpReview");
      var inDesign = designTab && designTab.classList.contains("active");
      var inReview = reviewSubtab && reviewSubtab.classList.contains("active");
      if (!inDesign && !inReview) return;
      if (e.target.tagName === "INPUT" || e.target.tagName === "TEXTAREA") return;
      // D-146 : en mode Room amend (édition d'une pièce), désactiver la
      // navigation flèches gauche/droite entre pièces — évite la perte
      // silencieuse des modifications en cours quand l'user passe à la
      // pièce suivante sans savoir qu'il sort du mode édition.
      var inRoomAmend = !!(window.editorState &&
        window.editorState.roomAmendMode);
      if (inRoomAmend) return;
      if (e.key === "ArrowLeft") { e.preventDefault(); fpGo(-1); }
      else if (e.key === "ArrowRight") { e.preventDefault(); fpGo(1); }
      else if (inDesign && (e.key === "ArrowUp" || e.key === "ArrowDown")) {
        e.preventDefault();
        var selCard = document.querySelector("#fpSelectedSolution .fp-candidate");
        var container = document.getElementById("fpCandidatesList");
        var items = Array.from(container.querySelectorAll(".fp-candidate"));
        // Build unified list: selected solution (index -1) + candidates
        var selActive = selCard && !items.some(function(el) {
          return el.classList.contains("selected");
        });
        var curIdx = selActive ? -1 : -2;
        items.forEach(function(el, i) {
          if (el.classList.contains("selected")) curIdx = i;
        });
        var nextIdx = e.key === "ArrowUp" ? curIdx - 1 : curIdx + 1;
        // Clamp: -1 = selected solution (if exists), 0..n = candidates
        var minIdx = selCard ? -1 : 0;
        if (nextIdx < minIdx) nextIdx = minIdx;
        if (nextIdx >= items.length) nextIdx = items.length - 1;
        if (nextIdx === curIdx) return;
        if (nextIdx === -1 && selCard) {
          // Activate selected solution
          items.forEach(function(el) { el.classList.remove("selected"); });
          selCard.click();
          selCard.focus();
        } else if (nextIdx >= 0 && nextIdx < items.length) {
          items[nextIdx].click();
          items[nextIdx].scrollIntoView({ block: "nearest" });
          items[nextIdx].focus();
        }
      }
      else if (inDesign && e.key === "Enter") {
        e.preventDefault();
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
            syncOverlayToggle(true);
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
          prepareFpRooms(json);
        }
      })
      .catch(function() {});
  });

  // Expose for ingestion integration
  window.prepareFpRooms = prepareFpRooms;
})();
