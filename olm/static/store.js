"use strict";
// ========================================================================
// OLM STORE — unified front-end state (D-94, phase 1)
// ========================================================================
//
// Replaces 5 scattered globals:
//   window.fpData            → state.floor
//   window.fpAmendments      → state.amendments.layout
//   window.fpRoomAmendments  → state.amendments.room
//   window.fpOverlay         → state.plan.overlay
//   window.ingState          → state.ingestion
//
// API :
//   olmStore.get(path)                → deep read ("floor.rooms")
//   olmStore.set(path, value)         → deep write + notify
//   olmStore.subscribe(path, cb)      → subscribe, returns unsubscribe fn
//   olmStore.reset(section)           → reset a named section in place
//                                       (preserves object identity for
//                                        callers holding a long-lived ref)
//   olmStore._state                   → escape hatch for migration
//
// Loaded FIRST (before block_constants.js) to guarantee window.fp* /
// window.ingState exist when downstream modules initialize.
// ========================================================================

(function () {
  // ---- Default shapes (kept in functions to rebuild on reset) ----
  function defaultFloor() {
    return { rooms: [], currentIdx: 0 };
  }
  function defaultPlanOverlay() {
    return null; // { dataUrl, pxPerCm, imgW, imgH }
  }
  function defaultAmendLayout() {
    return {}; // { roomName: { candidate, pattern } }
  }
  function defaultAmendRoom() {
    return {}; // { roomName: { name, width_cm, depth_cm, windows, openings, exclusion_zones } }
  }
  function defaultIngestion() {
    return {
      planPath: "",
      planUrl: "",
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
      zoomRoom: "",
      merges: {},
      opacity: 0.3,
      overlayVisible: true,
      vb: { x: 0, y: 0, w: 1920, h: 1080 },
      pan: null,
      bboxEditor: {
        selectedName: null,
        mode: "idle",
        handle: null,
        dragStart: null,
        preDragBbox: null,
        sessionStartBbox: null,
      },
    };
  }

  // ---- State root ----
  var state = {
    plan: { overlay: defaultPlanOverlay() },
    floor: defaultFloor(),
    amendments: { layout: defaultAmendLayout(), room: defaultAmendRoom() },
    ingestion: defaultIngestion(),
    ui: {},
  };

  // ---- Subscribers (path → Set<cb>) ----
  var subs = new Map();

  function getByPath(path) {
    if (!path || path === "") return state;
    var parts = path.split(".");
    var cur = state;
    for (var i = 0; i < parts.length; i++) {
      if (cur == null) return undefined;
      cur = cur[parts[i]];
    }
    return cur;
  }

  function setByPath(path, value) {
    var parts = path.split(".");
    var last = parts.pop();
    var cur = state;
    for (var i = 0; i < parts.length; i++) {
      if (cur[parts[i]] == null) cur[parts[i]] = {};
      cur = cur[parts[i]];
    }
    cur[last] = value;
    notify(path);
  }

  function notify(path) {
    // Notify the exact path and every ancestor, plus root ("*")
    var parts = path.split(".");
    for (var i = parts.length; i > 0; i--) {
      var p = parts.slice(0, i).join(".");
      var set = subs.get(p);
      if (set) {
        set.forEach(function (cb) {
          try { cb(getByPath(p), p); } catch (e) { console.error("[olmStore] subscriber error", e); }
        });
      }
    }
    var root = subs.get("*");
    if (root) {
      root.forEach(function (cb) {
        try { cb(state, path); } catch (e) { console.error("[olmStore] subscriber error", e); }
      });
    }
  }

  function subscribe(path, cb) {
    if (!subs.has(path)) subs.set(path, new Set());
    subs.get(path).add(cb);
    return function unsubscribe() {
      var s = subs.get(path);
      if (s) s.delete(cb);
    };
  }

  // Reset a section IN PLACE (preserves object identity so long-lived
  // local references — e.g. var fpData in floor_plan.js, var ingState
  // in ingestion.js — stay valid after a reset).
  function resetInPlace(target, fresh) {
    // Clear all own keys, then copy fresh keys back
    Object.keys(target).forEach(function (k) { delete target[k]; });
    Object.keys(fresh).forEach(function (k) { target[k] = fresh[k]; });
  }

  function reset(section) {
    switch (section) {
      case "floor":
        resetInPlace(state.floor, defaultFloor());
        notify("floor");
        return;
      case "amendments":
        resetInPlace(state.amendments.layout, defaultAmendLayout());
        resetInPlace(state.amendments.room, defaultAmendRoom());
        notify("amendments");
        return;
      case "amendments.layout":
        resetInPlace(state.amendments.layout, defaultAmendLayout());
        notify("amendments.layout");
        return;
      case "amendments.room":
        resetInPlace(state.amendments.room, defaultAmendRoom());
        notify("amendments.room");
        return;
      case "plan.overlay":
        state.plan.overlay = null;
        notify("plan.overlay");
        return;
      case "ingestion":
        resetInPlace(state.ingestion, defaultIngestion());
        notify("ingestion");
        return;
      case "all":
        reset("floor");
        reset("amendments");
        reset("plan.overlay");
        reset("ingestion");
        return;
      default:
        console.warn("[olmStore] reset: unknown section", section);
    }
  }

  // ---- Public API ----
  window.olmStore = {
    get: getByPath,
    set: setByPath,
    subscribe: subscribe,
    reset: reset,
    _state: state,
  };

  // ---- Backward-compat globals (phase 1) ----
  // Downstream modules still read/write these names. We expose them as
  // live references to the store's internal objects. Reset helpers above
  // mutate in place so these references remain valid across resets.
  window.fpData = state.floor;
  window.fpAmendments = state.amendments.layout;
  window.fpRoomAmendments = state.amendments.room;
  window.ingState = state.ingestion;

  // fpOverlay is routinely reassigned (e.g. `window.fpOverlay = {...}`
  // or `window.fpOverlay = null`), so expose it as a getter/setter that
  // forwards to state.plan.overlay — no caller keeps a long-lived ref.
  Object.defineProperty(window, "fpOverlay", {
    configurable: true,
    get: function () { return state.plan.overlay; },
    set: function (v) { state.plan.overlay = v; notify("plan.overlay"); },
  });
})();
