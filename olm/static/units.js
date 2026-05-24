// ============================================================================
// units.js — D-274 Lot 1 : source unique conversions px <-> cm (JS)
// ============================================================================
// Expose window.INCH_TO_CM, pxToCm, cmToPx, drawingScaleToCmPerPx,
// cmPerPxToScaleText.
//
// Convention d'unite : cm_per_px (cm par pixel) est l'echelle maitre.
// Regle d'arrondi : half-up (Math.round), identique au Python units.py.
// ============================================================================
(function () {

  var INCH_TO_CM = 2.54;

  /**
   * Convertit une valeur en pixels vers des centimetres (arrondi entier).
   * @param {number} pxVal  - Valeur en pixels.
   * @param {number} cmPerPx - Echelle (cm par pixel).
   * @returns {number} Valeur en cm, arrondie half-up.
   */
  function pxToCm(pxVal, cmPerPx) {
    return Math.round(pxVal * cmPerPx);
  }

  /**
   * Convertit une valeur en centimetres vers des pixels (arrondi entier).
   * @param {number} cmVal  - Valeur en centimetres.
   * @param {number} cmPerPx - Echelle (cm par pixel).
   * @returns {number} Valeur en px, arrondie half-up.
   */
  function cmToPx(cmVal, cmPerPx) {
    if (!(cmPerPx > 0)) return 0;
    return Math.round(cmVal / cmPerPx);
  }

  /**
   * Calcule cm_per_px depuis un ratio d'echelle et un DPI.
   * @param {number} scaleNumber - Facteur d'echelle (ex. 100 pour 1:100).
   * @param {number} dpi         - Resolution de rendu (points par pouce).
   * @returns {number} cm_per_px (0 si invalide).
   */
  function drawingScaleToCmPerPx(scaleNumber, dpi) {
    if (!(scaleNumber > 0) || !(dpi > 0)) return 0;
    return INCH_TO_CM * scaleNumber / dpi;
  }

  /**
   * Inverse : cm_per_px + DPI -> texte "1 : N".
   * @param {number} cmPerPx - Echelle cm par pixel.
   * @param {number} dpi     - Resolution de rendu.
   * @returns {string} "1 : N" ou "" si invalide.
   */
  function cmPerPxToScaleText(cmPerPx, dpi) {
    if (!(cmPerPx > 0) || !(dpi > 0)) return "";
    var n = Math.round(cmPerPx * dpi / INCH_TO_CM);
    return n > 0 ? "1 : " + n : "";
  }

  // -- Exposition publique ------------------------------------------------
  window.INCH_TO_CM = INCH_TO_CM;
  window.pxToCm = pxToCm;
  window.cmToPx = cmToPx;
  window.drawingScaleToCmPerPx = drawingScaleToCmPerPx;
  window.cmPerPxToScaleText = cmPerPxToScaleText;

}());
