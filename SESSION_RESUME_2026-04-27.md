Contexte : le projet OLM a été rollback sur v0.4.5 (commit `be08ec0`, D-142) le 2026-04-26 après accumulation de régressions D-143 a D-147. Un replay selectif est en cours. L'etat actuel du code est au commit `eb9897a` qui applique D-148 + D-149 + D-150 directement sur v0.4.5, hors du plan de replay initial.

Lire `docs/TODO.md` section "Contexte replay v0.4.5" pour l'etat detaille de chaque unite.

Etat du replay :
- D-148 (cartouches OCR rescan) : COMMITE dans eb9897a. Le mode OCR rescan re-erase les cartouches avant binarisation. Param `cartouche_bboxes_px` ajoute a `extract_room_features`. Endpoint `/api/room/reanalyze` et batch acceptent le champ `mode`.
- D-149 (race condition OCR scale) : COMMITE dans eb9897a. `ingestion.js` DOMContentLoaded pre-fill supprime (causait lecture d'APP_CONFIG vide). Nouvelle fonction `window.prefillDrawingScale()` appelee par `init.js` apres `loadAppConfig()`.
- D-150 (snap search cm-only + cleanup) : COMMITE dans eb9897a. Dernier hardcode px (`range(-3, 4)`) remplace par `_cfg_local.snap_search_px` dans `_classify_wall_direct`. Suppression 200 lignes de code mort (`classify_wall_segments`, `_build_exclusions`). `binarize()` parametree (threshold + morph_dilate_px). Migration `MORPH_DILATE_PX` et `text_margin` vers detection_config.
- D-143 (classify_step_cm) : PAS REJOUE. Le commit `72cd9a6` sur la branche `backup-pre-replay` contient ce changement. A cherry-pick : `git cherry-pick 72cd9a6`. Scope : parametre `classify_step_cm` scale-aware dans `extract_room_features`.
- D-144 (pxScale overlays CSS-px) : DEJA APPLIQUE. `pxScale` present dans `ingestion.js`. Les overlays (rays, hits, bbox, handles) sont dimensionnes en pixels CSS. Pas besoin de rejouer.
- D-145 (binary_for_arcs + seeds anchoring) : PAS REJOUE. Scope : nouvelle binaire `binary_for_arcs` (pre-`remove_non_ortho`) pour `expand_door_arcs`, `_seed_scan_range` pour scoper le scan autour des seeds, batch partage binary_raw. Fichiers : extract.py, test_comb.py, app.py, ingestion.js, init_rvtool.js. Source : hunks dans le diff sauvegarde dans `/tmp/olm-pre-replay/uncommitted.diff`.
- D-146 (fleches desactivees Room amend) : PAS REJOUE. Scope : fleches gauche/droite desactivees en Room amend mode. Fichier : `olm/static/floor_plan.js`. Source : hunk dans le diff.
- D-147 (R2-fit detection) : NE PAS REJOUER. Casse (regressions bbox 922, seeds invisibles). A reconcevoir apres stabilisation.

Taches pour cette session :
1. Cherry-pick D-143 (`git cherry-pick 72cd9a6`) et tester.
2. Rejouer D-145 (binary_for_arcs) depuis les hunks sauvegardes. Attention : les hunks D-145 dans extract.py etaient entremeles avec D-147 dans l'ancien diff. Strategie : appliquer uniquement les ajouts D-145 (binary_for_arcs, binary_raw_precomputed, suppression auto_door_masks_px) sans toucher au remplacement de `_detect_doors_on_face`.
3. Rejouer D-146 (fleches amend) depuis le hunk.
4. Tester end-to-end apres chaque unite (pytest + test UI sur test_floorplan_preprocessed + big).
5. Quand le replay est termine, evaluer les chantiers identifies dans TODO.md (JSON v3 cm primary, couleurs vert/bleu, caches test_comb.py, regeneration big JSON).

Fichiers cles modifies dans D-148/149/150 (pour reference) :
- `olm/ingestion/extract.py` : binarize() parametree, _classify_wall_direct snap search, code mort supprime, cartouche_bboxes_px
- `olm/core/detection_config.py` : text_skip_margin_cm ajoute
- `olm/server/app.py` : champ mode dans reanalyze/reanalyze_batch, OCR erase avant binarisation
- `olm/static/ingestion.js` : prefillDrawingScale, suppression pre-fill DOMContentLoaded
- `olm/static/init.js` : appel prefillDrawingScale apres loadAppConfig

Plan de replay detaille encore disponible dans : `~/.claude/plans/est-il-possible-de-repartir-zippy-elephant.md`
