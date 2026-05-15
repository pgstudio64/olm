/**
 * modal.js — Centered modal overlay for OLM.
 *
 * Three modes:
 *   showModal(msg)    → wait mode (spinner, no buttons, call hideModal() to close)
 *   alertModal(msg)   → alert mode (OK button only, returns Promise resolved on OK)
 *   confirmModal(msg) → confirm mode (OK / Cancel, returns Promise<boolean>)
 */
(function () {
  'use strict';

  var backdrop = document.getElementById('olmModalBackdrop');
  var box = document.getElementById('olmModalBox');
  var msgEl = document.getElementById('olmModalMsg');
  var spinner = document.getElementById('olmModalSpinner');
  var btnBar = document.getElementById('olmModalBtns');
  var btnOk = document.getElementById('olmModalOk');
  var btnCancel = document.getElementById('olmModalCancel');

  var _confirmResolve = null;

  function _show(msg, mode, html) {
    if (html) { msgEl.innerHTML = msg; } else { msgEl.textContent = msg; }
    spinner.style.display = mode === 'wait' ? '' : 'none';
    btnBar.style.display = (mode === 'confirm' || mode === 'alert') ? '' : 'none';
    btnCancel.style.display = mode === 'confirm' ? '' : 'none';
    backdrop.style.display = '';
    box.style.display = '';
    if (mode === 'confirm' || mode === 'alert') btnOk.focus();
  }

  function _hide() {
    backdrop.style.display = 'none';
    box.style.display = 'none';
    if (_confirmResolve) {
      _confirmResolve(false);
      _confirmResolve = null;
    }
  }

  /** Show a wait modal (spinner). Call hideModal() to close. */
  window.showModal = function (msg) {
    _show(msg || 'Please wait...', 'wait');
  };

  /** Hide the current wait modal. */
  window.hideModal = function () {
    _confirmResolve = null;
    _hide();
  };

  /** Show an alert modal (OK only). Returns a Promise resolved on OK.
   *  If msg contains HTML tags, set useHtml=true. */
  window.alertModal = function (msg, useHtml) {
    return new Promise(function (resolve) {
      _confirmResolve = function () { resolve(); };
      _show(msg, 'alert', !!useHtml);
    });
  };

  /**
   * Show a confirm modal. Returns a Promise that resolves to true (OK)
   * or false (Cancel).
   */
  window.confirmModal = function (msg) {
    return new Promise(function (resolve) {
      _confirmResolve = resolve;
      _show(msg, 'confirm');
    });
  };

  btnOk.addEventListener('click', function () {
    var r = _confirmResolve;
    _confirmResolve = null;
    _hide();
    if (r) r(true);
  });

  btnCancel.addEventListener('click', function () {
    var r = _confirmResolve;
    _confirmResolve = null;
    _hide();
    if (r) r(false);
  });

  // Escape = Cancel in confirm mode, OK in alert mode, ignored in wait mode
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape' && backdrop.style.display !== 'none' && _confirmResolve) {
      e.preventDefault();
      // In alert mode (Cancel hidden), Escape acts as OK
      if (btnCancel.style.display === 'none') btnOk.click();
      else btnCancel.click();
    }
  });

  // Enter = OK in confirm mode
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Enter' && backdrop.style.display !== 'none' && _confirmResolve) {
      e.preventDefault();
      btnOk.click();
    }
  });
})();
