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

  // ── Loading and matching ──────────────────────────────────────────────
  // R-12 C4 : bimode. Accepte soit :
  //   - un Array de pièces (appel interne depuis ingState.rooms) — pas de
  //     stringify / parse, pas de fromStorage redondant pour les pièces déjà
  //     canoniques (Préprocessé). Les pièces non-canoniques (mode OCR, sans
  //     corridor_face_abs) sont canonicalisées au vol.
  //   - une string JSON (legacy : file upload, reload button, auto-dev) —
  //     parse + fromStorage sur chaque pièce.
  function fpLoadAndMatch(arg) {
    var _fpScale = (window.ingState && window.ingState.scale) || 0;
    var rooms;
    if (typeof arg === "string") {
      var parsed;
      try { parsed = JSON.parse(arg); } catch(e) {
        alert("Invalid JSON: " + e.message); return;
      }
      if (!parsed.rooms || !parsed.rooms.length) {
        alert("No rooms found in JSON"); return;
      }
      rooms = parsed.rooms.map(function (r) {
        return (r.corridor_face_abs !== undefined)
          ? r
          : window.canonicalIO.fromStorage(r, _fpScale);
      });
    } else if (Array.isArray(arg)) {
      if (!arg.length) { alert("No rooms to match"); return; }
      rooms = arg.map(function (r) {
        return (r.corridor_face_abs !== undefined)
          ? r
          : window.canonicalIO.fromStorage(r, _fpScale);
      });
    } else {
      console.warn("fpLoadAndMatch: invalid argument", arg); return;
    }

    // Sort by alphanumeric name (non-mutating)
    rooms = rooms.slice().sort(function (a, b) {
      return natSort(a.name || "", b.name || "");
    });

    // Preserve fields from input (not returned by matching API)
    // D-122 P2 : bbox_px / seed_px uniquement (bbox_abs_px / seed_abs_px fusionnés).
    var bboxByName = {};
    var corridorByName = {};
    var seedByName = {};
    var doorsByName = {};
    var wallsEditByName = {};
    var planAreaByName = {};
    rooms.forEach(function(r) {
      if (r.bbox_px) bboxByName[r.name] = r.bbox_px;
      corridorByName[r.name] = r.corridor_face_abs || "";
      if (r.seed_px) seedByName[r.name] = r.seed_px;
      if (r.doors) doorsByName[r.name] = r.doors;
      wallsEditByName[r.name] = !!r.walls_user_edited;
      if (typeof r.plan_area_m2 === "number" && r.plan_area_m2 > 0) {
        planAreaByName[r.name] = r.plan_area_m2;
      }
    });

    document.getElementById("fpCandidatesList").innerHTML =
      '<div class="fp-no-match">Matching in progress...</div>';

    // D-122 P5 fix : backend OpeningSpec.has_door défaut = True → il faut
    // explicitement poser has_door=false pour les openings ET combiner
    // state.doors (has_door=true) dans openings[]. Sinon les openings
    // canoniques sont interprétés comme des portes et écrasent la
    // collection state.room_openings au retour (bug save JSON).
    var apiRooms = rooms.map(function (r) {
      var apiOpenings = (r.openings || []).map(function (o) {
        return Object.assign({}, o, { has_door: false });
      });
      (r.doors || []).forEach(function (d) {
        apiOpenings.push(Object.assign({}, d, {
          has_door: true,
          opens_inward: d.opens_inward !== false,
          hinge_side: d.hinge_side || "left",
        }));
      });
      return Object.assign({}, r, { openings: apiOpenings, doors: undefined });
    });

    fetch("/api/floor-plan/match", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ rooms: apiRooms }),
    })
    .then(function(r) { return r.json(); })
    .then(function(data) {
      if (data.error) { alert("Error: " + data.error); return; }
      // Sort results by name
      data.rooms.sort(function(a, b) { return natSort(a.name || "", b.name || ""); });
      // Re-attach canonical fields not returned by matching API.
      // D-122 P2 : bbox_px / seed_px = coords image absolues uniques.
      // D-122 P5 : réponse backend en canonique ; D-122 P4 impose
      // openings/doors séparés côté state → on split si retour combiné.
      data.rooms.forEach(function(r) {
        if (bboxByName[r.name]) r.bbox_px = bboxByName[r.name];
        if (seedByName[r.name]) r.seed_px = seedByName[r.name];
        r.corridor_face_abs = corridorByName[r.name] || "";
        r.corridor_face = "south";
        r.walls_user_edited = !!wallsEditByName[r.name];
        if (planAreaByName[r.name] != null) {
          r.plan_area_m2 = planAreaByName[r.name];
        }
        // Si le backend renvoie openings avec has_door, on split.
        if (Array.isArray(r.openings) && r.openings.some(function(o){ return o.has_door; })) {
          var _doors = [];
          var _ops = [];
          r.openings.forEach(function(o) {
            var c = Object.assign({}, o); delete c.has_door;
            if (o.has_door) _doors.push(c); else _ops.push(c);
          });
          r.openings = _ops;
          r.doors = _doors;
        } else if (doorsByName[r.name]) {
          r.doors = doorsByName[r.name];
        }
      });
      // D-130 : préserver la sélection courante par NOM à travers le
      // remplacement de fpData.rooms. Sans ça, chaque re-match (ex :
      // déclenché par bbox edit dans Floor) reset currentIdx = 0 → la
      // Review peut afficher une autre pièce que celle sur laquelle
      // l'utilisateur travaille.
      var prevName = null;
      if (fpData.rooms && fpData.currentIdx != null &&
          fpData.rooms[fpData.currentIdx]) {
        prevName = fpData.rooms[fpData.currentIdx].name;
      }
      fpData.rooms = data.rooms;
      if (prevName) {
        var foundIdx = fpData.rooms.findIndex(function (r) {
          return r.name === prevName;
        });
        fpData.currentIdx = foundIdx >= 0 ? foundIdx : 0;
      } else {
        fpData.currentIdx = 0;
      }
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

  function rvRenderCurrent() {
    // Floor properties always refreshed (independent of selected room).
    updateFloorProperties();

    var room = fpCurrent();
    if (!room) {
      document.getElementById("rvRoomLabel").textContent = "-";
      document.getElementById("rvNavInfo").textContent = "0 / 0";
      document.getElementById("rvCanvas").innerHTML = "";
      return;
    }

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
      var side = (d.hinge_side === "left") ? "L" : "R";
      dsl += "\nDOOR " + f + " " + (d.offset_cm || 0) + " " + (d.width_cm || 90) + " " + dir + " " + side;
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
    // R-12 B: room already canonical in fpData (via fromStorage at load).
    // Editor et Review partagent le même repère canonique.
    var localRoom = room;
    state.rows = [];
    state.row_gaps_cm = [];
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
    // D-122 P4 : pattern catalogue stocke openings combiné → split.
    _splitOpeningsIntoState(pat.room_openings);
    state.room_exclusions = pat.room_exclusions || [];
    state.corridor_face_abs = room.corridor_face_abs || "";
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
      // D-125 : offset depuis bbox_px (même convention que fpRenderEmptyRoom,
      // ligne 318-321) ; le champ _overlayOffsetX/Y n'était jamais défini
      // côté producteur → 0 → état overlay corrompu et partagé avec rvCanvas
      // (race post-Save via fpRematchRoom async).
      var roomOvX = 0, roomOvY = 0;
      if (room.bbox_px) {
        roomOvX = room.bbox_px[0] / ov.pxPerCm;
        roomOvY = room.bbox_px[1] / ov.pxPerCm;
      }
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
      // Replace the room data in fpData (D-122 P5 : réponse canonique ;
      // D-122 P4 : split openings combiné retour backend).
      var newRoom = data.rooms[0];
      var _nrDoors = [];
      var _nrOps = [];
      (newRoom.openings || []).forEach(function (o) {
        var c = Object.assign({}, o); delete c.has_door;
        if (o.has_door) _nrDoors.push(c); else _nrOps.push(c);
      });
      for (var i = 0; i < fpData.rooms.length; i++) {
        if (fpData.rooms[i].name === roomName) {
          fpData.rooms[i].width_cm = newRoom.width_cm;
          fpData.rooms[i].depth_cm = newRoom.depth_cm;
          fpData.rooms[i].windows = newRoom.windows;
          fpData.rooms[i].openings = _nrOps;
          fpData.rooms[i].doors = _nrDoors;
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
