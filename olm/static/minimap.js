"use strict";
/**
 * Minimap — schematic plan thumbnail in Room (Review) and Office (Design).
 *
 * Uses the -SD plan image pre-processed at full resolution for grey
 * tones (rooms dark, exterior medium, corridor light).  Non-current
 * rooms filled to hide internal details.  Room outlines drawn as
 * 1px white lines.  Current room = filled orange.
 *
 * Click to toggle full / reduced size.  Starts collapsed.
 */
(function () {
  var MAX_DIM = 309;  // -10% (etait 343) — taille minimap Room/Office
  var COLLAPSED_RATIO = 1.67;
  var MARGIN_RATIO = 0.12;
  var _processedCanvas = null;
  var _processedUrl = "";
  var _processedScale = 1;  // src_image → processed_canvas scale factor (v0.5.28)
  // v0.5.31 : in-flight guard. Without it, 3 concurrent _ensurePlanImage
  // calls (Room render + Office render + resize) each decode + process the
  // full plan independently before the cache is set — 3× redundant work.
  // On a 30-megapixel plan on a slow machine that is ~20s freeze.
  var _processingUrl = null;
  var _processingCbs = [];
  var _collapsed = true;
  // Max dimension for processed canvas — avoids blocking the browser
  // 10-20s on big architectural plans (was iterating over millions of
  // pixels synchronously in a single tick). Minimap target ≤ 343 px so
  // downsampling to 1024 max is more than sufficient.
  var PROCESS_MAX_DIM = 1024;

  // 3 sizes derived from MAX_DIM and COLLAPSED_RATIO.
  var SIZE_L = MAX_DIM;
  var SIZE_M = Math.round(MAX_DIM / COLLAPSED_RATIO);
  var SIZE_S = Math.round(MAX_DIM / (COLLAPSED_RATIO * COLLAPSED_RATIO));
  var VIEWPORT_THRESHOLD = 2 * MAX_DIM;

  function _sizePair() {
    var tall = window.innerHeight > VIEWPORT_THRESHOLD;
    return tall ? [SIZE_M, SIZE_L] : [SIZE_S, SIZE_M];
  }

  var COL_BORDER = "rgba(255,255,255,0.5)";
  var COL_WALL   = "rgba(255,255,255,0.6)";
  var COL_ROOM   = "rgba(200,160,80,0.7)";

  var TONE_ROOM     = 14;
  var TONE_EXTERIOR = 35;
  var TONE_CORRIDOR = 56;

  function _isBlue(r, g, b) {
    return b > 150 && b > r + 30 && g > 120;
  }
  function _isGreen(r, g, b) {
    return g > 170 && g > r + 20 && g > b + 20;
  }

  // ── Pre-process plan (downsampled) ────────────────────
  // Returns {canvas, scale}. scale = src_image → processed_canvas factor.
  // Callers must scale source coords (env.x0/y0/W/H) by `scale` when
  // calling drawImage(canvas, sx, sy, sw, sh, ...).
  function _ensurePlanImage(url, cb) {
    if (_processedCanvas && _processedUrl === url) {
      cb({ canvas: _processedCanvas, scale: _processedScale });
      return;
    }
    // v0.5.31 : if a processing for this url is already in flight, queue the
    // callback instead of starting a redundant decode+process. Collapses N
    // concurrent first-time calls into a single heavy operation.
    if (_processingUrl === url) {
      _processingCbs.push(cb);
      return;
    }
    _processingUrl = url;
    _processingCbs = [cb];
    var img = new Image();
    img.onload = function () {
      // v0.5.28 perf : downsample large plans before pixel-by-pixel loop.
      // Was blocking the browser 10-20s on big plans (millions of pixels).
      var srcW = img.naturalWidth, srcH = img.naturalHeight;
      var s = Math.min(PROCESS_MAX_DIM / srcW, PROCESS_MAX_DIM / srcH, 1);
      var w = Math.max(1, Math.round(srcW * s));
      var h = Math.max(1, Math.round(srcH * s));
      var cvs = document.createElement("canvas");
      cvs.width = w;
      cvs.height = h;
      var ctx = cvs.getContext("2d");
      // drawImage with explicit size = browser downsamples natively (fast).
      ctx.drawImage(img, 0, 0, w, h);
      try {
        var id = ctx.getImageData(0, 0, w, h);
      } catch (e) {
        console.warn("Minimap: cannot read pixels", e);
        _processingUrl = null;
        var _errCbs = _processingCbs; _processingCbs = [];
        _errCbs.forEach(function (c) { c(null); });
        return;
      }
      var d = id.data;
      for (var i = 0; i < d.length; i += 4) {
        var r = d[i], g = d[i + 1], b = d[i + 2];
        var tone;
        if (_isBlue(r, g, b)) {
          tone = TONE_EXTERIOR;
        } else if (_isGreen(r, g, b)) {
          tone = TONE_CORRIDOR;
        } else {
          tone = TONE_ROOM;
        }
        d[i] = tone; d[i + 1] = tone; d[i + 2] = tone;
      }
      ctx.putImageData(id, 0, 0);
      _processedCanvas = cvs;
      _processedUrl = url;
      _processedScale = s;
      // v0.5.31 : flush all queued callbacks with the single processed result.
      _processingUrl = null;
      var _doneCbs = _processingCbs; _processingCbs = [];
      _doneCbs.forEach(function (c) { c({ canvas: cvs, scale: s }); });
    };
    img.onerror = function () {
      _processingUrl = null;
      var _failCbs = _processingCbs; _processingCbs = [];
      _failCbs.forEach(function (c) { c(null); });
    };
    img.src = url;
  }

  // ── Building envelope with balanced margins ───────────
  function _buildingEnvelope(allRooms, planW, planH) {
    var ex0 = Infinity, ey0 = Infinity, ex1 = -Infinity, ey1 = -Infinity;
    var count = 0;
    (allRooms || []).forEach(function (r) {
      var bb = r.bbox_px;
      if (!bb || bb.length < 4) return;
      if (bb[0] < ex0) ex0 = bb[0];
      if (bb[1] < ey0) ey0 = bb[1];
      if (bb[2] > ex1) ex1 = bb[2];
      if (bb[3] > ey1) ey1 = bb[3];
      count++;
    });
    if (!count) return null;
    var w = ex1 - ex0, h = ey1 - ey0;
    var desired = Math.max(w, h) * MARGIN_RATIO;
    var mL = Math.min(desired, ex0);
    var mR = Math.min(desired, planW - ex1);
    var mT = Math.min(desired, ey0);
    var mB = Math.min(desired, planH - ey1);
    var mx = Math.min(mL, mR);
    var my = Math.min(mT, mB);
    return { x0: ex0 - mx, y0: ey0 - my, x1: ex1 + mx, y1: ey1 + my };
  }

  // ── Rounded border ────────────────────────────────────
  function _drawBorder(ctx, cw, ch) {
    var br = 4;
    ctx.beginPath();
    ctx.moveTo(br, 0.5);
    ctx.lineTo(cw - br, 0.5);
    ctx.arcTo(cw - 0.5, 0.5, cw - 0.5, br, br);
    ctx.lineTo(cw - 0.5, ch - br);
    ctx.arcTo(cw - 0.5, ch - 0.5, cw - br, ch - 0.5, br);
    ctx.lineTo(br, ch - 0.5);
    ctx.arcTo(0.5, ch - 0.5, 0.5, ch - br, br);
    ctx.lineTo(0.5, br);
    ctx.arcTo(0.5, 0.5, br, 0.5, br);
    ctx.closePath();
    ctx.strokeStyle = COL_BORDER;
    ctx.lineWidth = 1;
    ctx.stroke();
  }

  // ── Main render ───────────────────────────────────────
  function renderMinimap(canvasId, containerId, currentRoom, allRooms,
                         overlay) {
    var container = document.getElementById(containerId);
    var canvas = document.getElementById(canvasId);
    if (!canvas || !container) return;

    if (!overlay || !overlay.dataUrl || !overlay.imgW || !overlay.imgH) {
      container.style.display = "none";
      return;
    }
    container.style.display = "";

    var planW = overlay.imgW;
    var planH = overlay.imgH;

    var env = _buildingEnvelope(allRooms, planW, planH);
    if (!env) { container.style.display = "none"; return; }
    var envW = env.x1 - env.x0;
    var envH = env.y1 - env.y0;
    if (envW <= 0 || envH <= 0) { container.style.display = "none"; return; }

    var pair = _sizePair();
    var maxDim = _collapsed ? pair[0] : pair[1];
    var ratio = Math.min(maxDim / envW, maxDim / envH);
    var cw = Math.max(40, Math.round(envW * ratio));
    var ch = Math.max(30, Math.round(envH * ratio));
    canvas.width = cw;
    canvas.height = ch;
    canvas.style.width = cw + "px";
    canvas.style.height = ch + "px";

    var ctx = canvas.getContext("2d");

    _ensurePlanImage(overlay.dataUrl, function (img) {
      if (!img) return;
      ctx.clearRect(0, 0, cw, ch);

      // Clip content to rounded rect so corners stay clean.
      var br = 4;
      ctx.save();
      ctx.beginPath();
      ctx.moveTo(br, 0);
      ctx.lineTo(cw - br, 0);
      ctx.arcTo(cw, 0, cw, br, br);
      ctx.lineTo(cw, ch - br);
      ctx.arcTo(cw, ch, cw - br, ch, br);
      ctx.lineTo(br, ch);
      ctx.arcTo(0, ch, 0, ch - br, br);
      ctx.lineTo(0, br);
      ctx.arcTo(0, 0, br, 0, br);
      ctx.closePath();
      ctx.clip();

      // Draw cropped pre-processed plan (grey tones).
      // v0.5.28 : img is now {canvas, scale} — scale source coords
      // because the processed canvas is downsampled.
      var _s = img.scale || 1;
      ctx.drawImage(img.canvas,
        env.x0 * _s, env.y0 * _s, envW * _s, envH * _s,
        0, 0, cw, ch);

      var ox = -env.x0 * ratio;
      var oy = -env.y0 * ratio;

      // Our rooms: 1px white outlines.
      ctx.strokeStyle = COL_WALL;
      ctx.lineWidth = 1;
      (allRooms || []).forEach(function (r) {
        var bb = r.bbox_px;
        if (!bb || bb.length < 4) return;
        ctx.strokeRect(ox + bb[0] * ratio, oy + bb[1] * ratio,
                       (bb[2] - bb[0]) * ratio, (bb[3] - bb[1]) * ratio);
      });

      // Current room: filled orange + windows.
      if (currentRoom && currentRoom.bbox_px) {
        var cb = currentRoom.bbox_px;
        ctx.fillStyle = COL_ROOM;
        ctx.fillRect(ox + cb[0] * ratio, oy + cb[1] * ratio,
                     (cb[2] - cb[0]) * ratio, (cb[3] - cb[1]) * ratio);

        // Windows on current room (blue, 1px collapsed / 3px expanded).
        // Windows are in canonical coords — convert to absolute via
        // rotateRectInv before drawing on the absolute-coords minimap.
        var wins = currentRoom.windows || [];
        var cio = window.canonicalIO;
        if (wins.length && overlay.pxPerCm && cio) {
          var ppc = overlay.pxPerCm;
          var wt = _collapsed ? 1 : 3;
          var cfAbs = currentRoom.corridor_face_abs || "";
          var canonW = currentRoom.width_cm || 0;
          var canonD = currentRoom.depth_cm || 0;
          var absW = (cfAbs === "east" || cfAbs === "west") ? canonD : canonW;
          var absD = (cfAbs === "east" || cfAbs === "west") ? canonW : canonD;
          ctx.fillStyle = "rgba(100,180,255,0.9)";
          wins.forEach(function (w) {
            var face = w.face;
            var offCm = w.offset_cm || 0;
            var widCm = w.width_cm || 0;
            if (widCm <= 0) return;
            // Build canonical rect (thin strip along the face).
            var cr;
            if (face === "north") {
              cr = { x: offCm, y: 0, width: widCm, depth: 0.1 };
            } else if (face === "south") {
              cr = { x: offCm, y: canonD - 0.1, width: widCm, depth: 0.1 };
            } else if (face === "west") {
              cr = { x: 0, y: offCm, width: 0.1, depth: widCm };
            } else if (face === "east") {
              cr = { x: canonW - 0.1, y: offCm, width: 0.1, depth: widCm };
            } else { return; }
            var ar = cio.rotateRectInv(cr, cfAbs, absW, absD);
            // Draw at absolute image position with fixed pixel thickness.
            var isH = ar.width > ar.depth;
            var dx = ox + (cb[0] + ar.x * ppc) * ratio;
            var dy = oy + (cb[1] + ar.y * ppc) * ratio;
            var dw = isH ? Math.max(1, ar.width * ppc * ratio) : wt;
            var dh = isH ? wt : Math.max(1, ar.depth * ppc * ratio);
            ctx.fillRect(dx, dy, dw, dh);
          });
        }

      }

      ctx.restore();
      _drawBorder(ctx, cw, ch);
    });
  }

  // ── Toggle ────────────────────────────────────────────
  function _initToggle(containerId) {
    var el = document.getElementById(containerId);
    if (!el) return;
    el.addEventListener("click", function () {
      _collapsed = !_collapsed;
      document.querySelectorAll(".minimap").forEach(function (m) {
        m.classList.toggle("collapsed", _collapsed);
      });
      if (window._minimapRefresh) window._minimapRefresh();
    });
    el.classList.add("collapsed");
  }

  _initToggle("rvMinimap");
  _initToggle("fpMinimap");

  window.renderMinimap = renderMinimap;
  window._minimapRefresh = null;
})();
