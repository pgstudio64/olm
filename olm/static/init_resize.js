"use strict";
// ========================================================================
// INIT RESIZE — Floor / Room left-sidebar resize handles (D-94 P3)
// ========================================================================
//
// Extracted from init.js. Two independent drag handles that let the user
// resize the left panel in Floor (fpLeftInfoCol) and Room (rvRoomSidebar).
// Widths are persisted in localStorage.
// ========================================================================

(function () {
  document.addEventListener("DOMContentLoaded", function () {
    // ---- Floor tab: fp-info-col resize handle ----
    (function () {
      var handle = document.getElementById("fpLeftResize");
      var panel = document.getElementById("fpLeftInfoCol");
      if (!handle || !panel) return;

      var saved = localStorage.getItem("fpLeftPanelWidth");
      if (saved) {
        var parsed = parseInt(saved, 10);
        if (parsed >= 100 && parsed <= 400) panel.style.width = parsed + "px";
      }

      var _dragging = false;
      var _startX = 0;
      var _startW = 0;

      handle.addEventListener("mousedown", function (e) {
        if (e.button !== 0) return;
        _dragging = true;
        _startX = e.clientX;
        _startW = panel.offsetWidth;
        handle.classList.add("active");
        document.body.style.cursor = "col-resize";
        e.preventDefault();
      });

      document.addEventListener("mousemove", function (e) {
        if (!_dragging) return;
        var newW = Math.min(400, Math.max(100, _startW + (e.clientX - _startX)));
        panel.style.width = newW + "px";
      });

      document.addEventListener("mouseup", function () {
        if (!_dragging) return;
        _dragging = false;
        handle.classList.remove("active");
        document.body.style.cursor = "";
        var finalW = Math.min(400, Math.max(100, panel.offsetWidth));
        localStorage.setItem("fpLeftPanelWidth", String(finalW));
      });
    })();

    // ---- Room + Office tabs: shared left-sidebar width ----
    // Deux panneaux (rvRoomSidebar en Room, fpDesignSidebar en Office) qui
    // partagent la même largeur via localStorage pour éviter le décalage du
    // canvas au switch entre les onglets. Deux handles, une seule largeur.
    (function () {
      var MIN_W = 120, MAX_W = 350;
      var KEY = "leftPanelWidthShared";
      var panels = [
        document.getElementById("rvRoomSidebar"),
        document.getElementById("fpDesignSidebar"),
      ].filter(Boolean);
      if (!panels.length) return;

      var currentW = 170;
      var saved = parseInt(localStorage.getItem(KEY), 10);
      if (saved >= MIN_W && saved <= MAX_W) currentW = saved;

      function applyWidth(w) {
        currentW = Math.min(MAX_W, Math.max(MIN_W, w));
        panels.forEach(function (p) { p.style.width = currentW + "px"; });
      }
      applyWidth(currentW);

      function bindHandle(handleId) {
        var handle = document.getElementById(handleId);
        if (!handle) return;
        var dragging = false, startX = 0, startW = 0;
        handle.addEventListener("mousedown", function (e) {
          if (e.button !== 0) return;
          dragging = true;
          startX = e.clientX;
          startW = currentW;
          handle.classList.add("active");
          document.body.style.cursor = "col-resize";
          e.preventDefault();
        });
        document.addEventListener("mousemove", function (e) {
          if (!dragging) return;
          applyWidth(startW + (e.clientX - startX));
        });
        document.addEventListener("mouseup", function () {
          if (!dragging) return;
          dragging = false;
          handle.classList.remove("active");
          document.body.style.cursor = "";
          localStorage.setItem(KEY, String(currentW));
        });
      }

      bindHandle("rvLeftResize");
      bindHandle("fpDesignLeftResize");
    })();

    // ---- Room + Office: shared right info-col width ----
    (function () {
      var MIN_W = 150, MAX_W = 520;
      var KEY = "rightPanelWidthShared";
      var panels = [
        document.getElementById("rvRightInfoCol"),
        document.getElementById("fpInfoCol"),
      ].filter(Boolean);
      if (!panels.length) return;

      var currentW = 252;
      var saved = parseInt(localStorage.getItem(KEY), 10);
      if (saved >= MIN_W && saved <= MAX_W) currentW = saved;

      function applyWidth(w) {
        currentW = Math.min(MAX_W, Math.max(MIN_W, w));
        panels.forEach(function (p) { p.style.width = currentW + "px"; });
      }
      applyWidth(currentW);

      function bindHandle(handleId) {
        var handle = document.getElementById(handleId);
        if (!handle) return;
        var dragging = false, startX = 0, startW = 0;
        handle.addEventListener("mousedown", function (e) {
          if (e.button !== 0) return;
          dragging = true;
          startX = e.clientX;
          startW = currentW;
          handle.classList.add("active");
          document.body.style.cursor = "col-resize";
          e.preventDefault();
        });
        document.addEventListener("mousemove", function (e) {
          if (!dragging) return;
          applyWidth(startW - (e.clientX - startX));
        });
        document.addEventListener("mouseup", function () {
          if (!dragging) return;
          dragging = false;
          handle.classList.remove("active");
          document.body.style.cursor = "";
          localStorage.setItem(KEY, String(currentW));
        });
      }

      bindHandle("rvRightResize");
      bindHandle("fpRightResize");
    })();

    // ---- Pattern Editor: independent left / right column resize ----
    (function () {
      var main = document.getElementById("peMain");
      if (!main) return;
      var LEFT_KEY = "peLeftWidth", RIGHT_KEY = "peRightWidth";
      var MIN_L = 216, MAX_L = 420, MIN_R = 259, MAX_R = 520;
      var leftW = parseInt(localStorage.getItem(LEFT_KEY), 10);
      var rightW = parseInt(localStorage.getItem(RIGHT_KEY), 10);
      if (!(leftW >= MIN_L && leftW <= MAX_L)) leftW = 220;
      if (!(rightW >= MIN_R && rightW <= MAX_R)) rightW = 260;

      function applyCols() {
        main.style.gridTemplateColumns =
          leftW + "px 8px 1fr 8px " + rightW + "px";
      }
      applyCols();

      function bindHandle(handleId, which) {
        var handle = document.getElementById(handleId);
        if (!handle) return;
        var dragging = false, startX = 0, startW = 0;
        handle.addEventListener("mousedown", function (e) {
          if (e.button !== 0) return;
          dragging = true;
          startX = e.clientX;
          startW = which === "left" ? leftW : rightW;
          handle.classList.add("active");
          document.body.style.cursor = "col-resize";
          e.preventDefault();
        });
        document.addEventListener("mousemove", function (e) {
          if (!dragging) return;
          var delta = e.clientX - startX;
          if (which === "left") {
            leftW = Math.min(MAX_L, Math.max(MIN_L, startW + delta));
          } else {
            rightW = Math.min(MAX_R, Math.max(MIN_R, startW - delta));
          }
          applyCols();
        });
        document.addEventListener("mouseup", function () {
          if (!dragging) return;
          dragging = false;
          handle.classList.remove("active");
          document.body.style.cursor = "";
          localStorage.setItem(which === "left" ? LEFT_KEY : RIGHT_KEY,
            String(which === "left" ? leftW : rightW));
        });
      }

      bindHandle("peLeftResize", "left");
      bindHandle("peRightResize", "right");
    })();
  });
})();
