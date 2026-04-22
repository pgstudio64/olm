"use strict";
// ============================================================================
// ROOM_SYNC_HELPERS — unified mutations across the 3 room stores (D-135 rider
// derived from audits ingestion.js / init_rvtool.js / editor.js 2026-04-21).
//
// Three canonical stores cohabit in the frontend:
//   - window.ingState.rooms       : canonical rooms (corridor=south), coords
//                                    image absolute (bbox_px/seed_px).
//   - window.fpData.rooms         : same shape, augmented with match results.
//   - window.fpRoomAmendments[n]  : canonical snapshot priorité read by
//                                    rvRenderCurrent (floor_plan.js:211).
//
// Previous pattern: each save / batch-rescan / rematch path mutated the
// three stores independently, with different break conditions and silent
// skips if a room was missing from one of them. This caused the D-135 rider
// bug (amendments not receiving bbox/dims after batch destructive rescan)
// and the D-127 limitation (bbox_px stale if fpData empty at save time).
//
// This module centralises the pattern. Callers describe what changes
// (updates object); the helper ensures consistent propagation to all
// stores that contain the room, and warns if the room is missing
// everywhere.
// ============================================================================

(function () {

  /**
   * Apply updates atomically to ingState.rooms, fpData.rooms, and
   * fpRoomAmendments for a given room name.
   *
   * @param {string} roomName  - Target room name.
   * @param {Object} updates   - Fields to merge into the room object.
   *   Same keys as a canonical room (width_cm, depth_cm, bbox_px,
   *   windows, openings, doors, exclusion_zones, transparent_zones,
   *   corridor_face, corridor_face_abs, walls_user_edited, surface_m2,
   *   ...).
   * @param {Object} [fallbackCanonRoom] - Optional canonical room clone
   *   used to seed fpRoomAmendments if fpData.rooms does NOT contain
   *   roomName. Must already match canonical invariants (corridor="south",
   *   bbox_px in image coords). The fallback is merged with updates
   *   before cloning, so the amendments stay in sync with updates even
   *   when fpData is not yet populated.
   *
   * @returns {Object} { ingIdx, fpIdx, amendWritten } — useful for
   *   callers that need to post-process the mutated objects.
   */
  function syncRoomToAllStores(roomName, updates, fallbackCanonRoom) {
    var ingRooms = (window.ingState && window.ingState.rooms) || [];
    var fpRooms = (window.fpData && window.fpData.rooms) || [];
    var ingIdx = -1;
    var fpIdx = -1;
    for (var i = 0; i < ingRooms.length; i++) {
      if (ingRooms[i].name === roomName) { ingIdx = i; break; }
    }
    for (var j = 0; j < fpRooms.length; j++) {
      if (fpRooms[j].name === roomName) { fpIdx = j; break; }
    }
    if (ingIdx >= 0) Object.assign(ingRooms[ingIdx], updates);
    if (fpIdx >= 0) Object.assign(fpRooms[fpIdx], updates);

    // fpRoomAmendments is the canonical read for rvRenderCurrent.
    // Priority to fpData (richer: enriched offset_px, post-match
    // data). Fallback otherwise to the caller-provided canonRoom
    // enriched with updates — covers the "save before any match"
    // edge case (D-127 fix scenario).
    window.fpRoomAmendments = window.fpRoomAmendments || {};
    var amendWritten = false;
    if (fpIdx >= 0) {
      window.fpRoomAmendments[roomName] =
        JSON.parse(JSON.stringify(fpRooms[fpIdx]));
      amendWritten = true;
    } else if (fallbackCanonRoom) {
      var enriched = Object.assign({}, fallbackCanonRoom, updates);
      window.fpRoomAmendments[roomName] = JSON.parse(JSON.stringify(enriched));
      amendWritten = true;
    }

    if (ingIdx < 0 && fpIdx < 0) {
      console.warn(
        "[room_sync] room \"" + roomName +
        "\" not found in ingState.rooms or fpData.rooms — mutations skipped.");
    }
    return { ingIdx: ingIdx, fpIdx: fpIdx, amendWritten: amendWritten };
  }

  /**
   * Split a combined openings list (with has_door flag, backend format)
   * into two arrays : non-door openings + doors. Mirrors the canonical
   * frontend invariant (D-122 P4) that openings and doors live in
   * separate state collections.
   *
   * @param {Array} combined - Backend /api/floor-plan/match openings[]
   *   with has_door=true|false per entry.
   * @returns {{ openings: Array, doors: Array }}
   */
  function splitOpeningsToFrontEnd(combined) {
    var openings = [];
    var doors = [];
    (combined || []).forEach(function (o) {
      var c = Object.assign({}, o);
      delete c.has_door;
      if (o.has_door) doors.push(c);
      else openings.push(c);
    });
    return { openings: openings, doors: doors };
  }

  window.syncRoomToAllStores = syncRoomToAllStores;
  window.splitOpeningsToFrontEnd = splitOpeningsToFrontEnd;
})();
