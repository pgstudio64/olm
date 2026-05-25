/**
 * preview_modal.js — Lightbox for plan export preview.
 *
 * Opens a full-viewport overlay showing the composed PNG at fit-to-viewport
 * scale with zoom (wheel + buttons) and pan (drag) controls.
 *
 * Public API:
 *   window.openPreviewLightbox(blobUrl, imgW, imgH)
 *   window.closePreviewLightbox()
 */
(function () {
  'use strict';

  // ---------------------------------------------------------------------------
  // Constants
  // ---------------------------------------------------------------------------
  var ZOOM_MIN = 0.10;
  var ZOOM_MAX = 8.0;
  var ZOOM_WHEEL_FACTOR = 1.15;
  var ZOOM_BUTTON_FACTOR = 1.25;
  var VIEWPORT_PADDING = 40; // px margin around image for fit calculation

  // ---------------------------------------------------------------------------
  // State
  // ---------------------------------------------------------------------------
  var _zoom = 1;
  var _panX = 0;
  var _panY = 0;
  var _imgW = 0;
  var _imgH = 0;
  var _fitScale = 1;
  var _blobUrl = null;

  // Drag state
  var _dragging = false;
  var _didDrag = false;
  var _dragStartX = 0;
  var _dragStartY = 0;
  var _panStartX = 0;
  var _panStartY = 0;

  // Pinch (Safari gesture events) state
  var _gestureStartZoom = 1;
  var _gestureAnchorX = 0;
  var _gestureAnchorY = 0;

  // ---------------------------------------------------------------------------
  // DOM — built once, reused
  // ---------------------------------------------------------------------------
  var overlay = document.createElement('div');
  overlay.id = 'previewLightbox';
  overlay.className = 'preview-lightbox';
  overlay.style.display = 'none';

  var header = document.createElement('div');
  header.className = 'preview-lightbox-header';

  var title = document.createElement('span');
  title.textContent = 'Preview';
  title.className = 'preview-lightbox-title';

  var controls = document.createElement('span');
  controls.className = 'preview-lightbox-controls';

  var btnZoomOut = document.createElement('button');
  btnZoomOut.className = 'btn preview-lightbox-btn';
  btnZoomOut.textContent = '\u2212'; // minus sign
  btnZoomOut.title = 'Zoom out (-)';

  var zoomLabel = document.createElement('span');
  zoomLabel.className = 'preview-lightbox-zoom-label';
  zoomLabel.textContent = '100%';

  var btnZoomIn = document.createElement('button');
  btnZoomIn.className = 'btn preview-lightbox-btn';
  btnZoomIn.textContent = '+';
  btnZoomIn.title = 'Zoom in (+)';

  var btnFit = document.createElement('button');
  btnFit.className = 'btn preview-lightbox-btn';
  btnFit.textContent = 'Fit';
  btnFit.title = 'Fit to viewport';

  // Optional download button — shown only when openPreviewLightbox is called
  // with a downloadName (lets the user save the previewed image).
  var btnDownload = document.createElement('button');
  btnDownload.className = 'btn preview-lightbox-btn';
  btnDownload.textContent = '⬇ Download';
  btnDownload.title = 'Download image';
  btnDownload.style.display = 'none';
  var _downloadName = null;

  var btnClose = document.createElement('button');
  btnClose.className = 'btn preview-lightbox-btn preview-lightbox-close';
  btnClose.textContent = '\u2715'; // multiplication sign (x)
  btnClose.title = 'Close (Esc)';

  controls.appendChild(btnZoomOut);
  controls.appendChild(zoomLabel);
  controls.appendChild(btnZoomIn);
  controls.appendChild(btnFit);
  controls.appendChild(btnDownload);
  controls.appendChild(btnClose);

  header.appendChild(title);
  header.appendChild(controls);

  var viewport = document.createElement('div');
  viewport.className = 'preview-lightbox-viewport';

  var img = document.createElement('img');
  img.className = 'preview-lightbox-img';
  img.draggable = false;

  viewport.appendChild(img);
  overlay.appendChild(header);
  overlay.appendChild(viewport);
  document.body.appendChild(overlay);

  // ---------------------------------------------------------------------------
  // Helpers
  // ---------------------------------------------------------------------------
  function _computeFitScale() {
    var vw = viewport.clientWidth - VIEWPORT_PADDING * 2;
    var vh = viewport.clientHeight - VIEWPORT_PADDING * 2;
    if (vw <= 0 || vh <= 0 || _imgW <= 0 || _imgH <= 0) return 1;
    var fit = Math.min(vw / _imgW, vh / _imgH);
    return Math.min(fit, 1.0); // never upscale beyond 100%
  }

  function _applyTransform() {
    img.style.transform =
      'translate(' + _panX + 'px, ' + _panY + 'px) scale(' + _zoom + ')';
    zoomLabel.textContent = Math.round(_zoom * 100) + '%';
  }

  function _zoomTo(newZoom, anchorX, anchorY) {
    newZoom = Math.max(ZOOM_MIN, Math.min(ZOOM_MAX, newZoom));
    if (newZoom === _zoom) return;
    // Anchor: keep the point under (anchorX, anchorY) stable.
    var ratio = newZoom / _zoom;
    _panX = anchorX - ratio * (anchorX - _panX);
    _panY = anchorY - ratio * (anchorY - _panY);
    _zoom = newZoom;
    _applyTransform();
  }

  function _zoomCenter(factor) {
    var cx = viewport.clientWidth / 2;
    var cy = viewport.clientHeight / 2;
    _zoomTo(_zoom * factor, cx, cy);
  }

  function _fitToViewport() {
    _fitScale = _computeFitScale();
    _zoom = _fitScale;
    // Center the image
    _panX = (viewport.clientWidth - _imgW * _zoom) / 2;
    _panY = (viewport.clientHeight - _imgH * _zoom) / 2;
    _applyTransform();
  }

  // ---------------------------------------------------------------------------
  // Events — buttons
  // ---------------------------------------------------------------------------
  btnZoomIn.addEventListener('click', function () { _zoomCenter(ZOOM_BUTTON_FACTOR); });
  btnZoomOut.addEventListener('click', function () { _zoomCenter(1 / ZOOM_BUTTON_FACTOR); });
  btnFit.addEventListener('click', function () { _fitToViewport(); });
  btnDownload.addEventListener('click', function () {
    if (!_blobUrl || !_downloadName) return;
    var a = document.createElement('a');
    a.href = _blobUrl;
    a.download = _downloadName;
    a.click();
  });
  btnClose.addEventListener('click', function () { _close(); });

  // Click on backdrop (viewport outside image) closes — but not after a pan
  // (a drag that releases anywhere must not be treated as a close click).
  viewport.addEventListener('click', function (e) {
    if (_didDrag) return;
    if (e.target === viewport) _close();
  });

  // ---------------------------------------------------------------------------
  // Events — wheel zoom (anchored to cursor)
  // ---------------------------------------------------------------------------
  viewport.addEventListener('wheel', function (e) {
    e.preventDefault();
    var rect = viewport.getBoundingClientRect();
    var mx = e.clientX - rect.left;
    var my = e.clientY - rect.top;
    var factor;
    if (e.ctrlKey) {
      // Trackpad pinch (Chrome/Edge/Firefox + Windows precision touchpad):
      // delivered as ctrl+wheel, deltaY proportional to the pinch amount.
      factor = Math.exp(-e.deltaY / 100);
    } else {
      factor = e.deltaY < 0 ? ZOOM_WHEEL_FACTOR : (1 / ZOOM_WHEEL_FACTOR);
    }
    _zoomTo(_zoom * factor, mx, my);
  }, { passive: false });

  // ---------------------------------------------------------------------------
  // Events — pinch zoom via gesture events (Safari macOS only)
  // ---------------------------------------------------------------------------
  viewport.addEventListener('gesturestart', function (e) {
    e.preventDefault();
    _gestureStartZoom = _zoom;
    var rect = viewport.getBoundingClientRect();
    _gestureAnchorX = e.clientX - rect.left;
    _gestureAnchorY = e.clientY - rect.top;
  });
  viewport.addEventListener('gesturechange', function (e) {
    e.preventDefault();
    _zoomTo(_gestureStartZoom * e.scale, _gestureAnchorX, _gestureAnchorY);
  });
  viewport.addEventListener('gestureend', function (e) { e.preventDefault(); });

  // ---------------------------------------------------------------------------
  // Events — drag pan
  // ---------------------------------------------------------------------------
  viewport.addEventListener('mousedown', function (e) {
    if (e.target === viewport || e.target === img) {
      e.preventDefault();
      _dragging = true;
      _didDrag = false;
      _dragStartX = e.clientX;
      _dragStartY = e.clientY;
      _panStartX = _panX;
      _panStartY = _panY;
      viewport.style.cursor = 'grabbing';
    }
  });

  window.addEventListener('mousemove', function (e) {
    if (!_dragging) return;
    if (Math.abs(e.clientX - _dragStartX) > 3 ||
        Math.abs(e.clientY - _dragStartY) > 3) {
      _didDrag = true;
    }
    _panX = _panStartX + (e.clientX - _dragStartX);
    _panY = _panStartY + (e.clientY - _dragStartY);
    _applyTransform();
  });

  window.addEventListener('mouseup', function () {
    if (_dragging) {
      _dragging = false;
      viewport.style.cursor = 'grab';
    }
  });

  // ---------------------------------------------------------------------------
  // Events — keyboard (only when lightbox visible)
  // ---------------------------------------------------------------------------
  document.addEventListener('keydown', function (e) {
    if (overlay.style.display === 'none') return;
    if (e.key === 'Escape') {
      e.preventDefault();
      e.stopPropagation();
      _close();
    } else if (e.key === '+' || e.key === '=') {
      e.preventDefault();
      _zoomCenter(ZOOM_BUTTON_FACTOR);
    } else if (e.key === '-') {
      e.preventDefault();
      _zoomCenter(1 / ZOOM_BUTTON_FACTOR);
    }
  }, true); // capture phase to beat modal.js

  // ---------------------------------------------------------------------------
  // Public API
  // ---------------------------------------------------------------------------
  function _close() {
    overlay.style.display = 'none';
    _dragging = false;
    if (_blobUrl) {
      URL.revokeObjectURL(_blobUrl);
      _blobUrl = null;
    }
    img.src = '';
  }

  /**
   * Open the preview lightbox with the given blob URL.
   * @param {string} blobUrl — URL.createObjectURL result
   * @param {number} imgW — natural image width in pixels
   * @param {number} imgH — natural image height in pixels
   * @param {object} [opts] — { downloadName, title } to enable the Download
   *   button (saves the previewed blob) and override the header title.
   */
  window.openPreviewLightbox = function (blobUrl, imgW, imgH, opts) {
    // Revoke previous URL if any
    if (_blobUrl) {
      URL.revokeObjectURL(_blobUrl);
    }
    _blobUrl = blobUrl;
    _imgW = imgW;
    _imgH = imgH;

    _downloadName = (opts && opts.downloadName) || null;
    btnDownload.style.display = _downloadName ? '' : 'none';
    title.textContent = (opts && opts.title) || 'Preview';

    img.src = blobUrl;
    overlay.style.display = '';

    // Wait one frame for layout so viewport dimensions are correct
    requestAnimationFrame(function () {
      _fitToViewport();
    });
  };

  window.closePreviewLightbox = function () {
    _close();
  };
})();
