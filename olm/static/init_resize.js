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

    // ---- Room tab: rv-sidebar resize handle ----
    (function () {
      var handle = document.getElementById("rvLeftResize");
      var panel = document.getElementById("rvRoomSidebar");
      if (!handle || !panel) return;

      var saved = localStorage.getItem("rvLeftPanelWidth");
      if (saved) {
        var parsed = parseInt(saved, 10);
        if (parsed >= 120 && parsed <= 350) panel.style.width = parsed + "px";
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
        var newW = Math.min(350, Math.max(120, _startW + (e.clientX - _startX)));
        panel.style.width = newW + "px";
      });

      document.addEventListener("mouseup", function () {
        if (!_dragging) return;
        _dragging = false;
        handle.classList.remove("active");
        document.body.style.cursor = "";
        var finalW = Math.min(350, Math.max(120, panel.offsetWidth));
        localStorage.setItem("rvLeftPanelWidth", String(finalW));
      });
    })();
  });
})();
