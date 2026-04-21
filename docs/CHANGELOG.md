# CHANGELOG

Toutes les modifications notables de ce projet sont documentées ici.
Format basé sur [Keep a Changelog](https://keepachangelog.com/fr/1.0.0/).

---

## [Unreleased] — D-115 à D-131 (2026-04-20 → 2026-04-21)

### D-131 — Persistance `origin` dans JSON v3 (2026-04-21)

- **Bug** : le champ `origin` ("auto"|"manual") sur chaque opening/
  window/door était runtime seulement. Perdu au save/load JSON v3 →
  chaque Re-analyze post-reload écrasait les ouvertures personnalisées.
- **Fix** : ajout `origin: str | None = None` à `WindowSpec` et
  `OpeningSpec`. `/api/floor-plan/match` parse + émet le champ.
  `serializeForStorage` inclut `origin` conditionnellement.
  `canonicalIO.fromStorage/toStorage` préservait déjà via `Object.assign`.
- 3 tests unit ajoutés (`test_room_model.py`). Sample canonical_io
  round-trip enrichi avec origin.

### D-130 — Sync immédiat fpData + préservation currentIdx bbox edit (2026-04-21)

- **Bugs** : après resize d'une pièce dans Floor + D-128,
  (a) double-clic pouvait ouvrir 305 au lieu de 927 (currentIdx reset à 0),
  (b) la pièce s'ouvrait en Review avec son ancien bbox (fpData stale).
- **Fix** :
  (a) `fpLoadAndMatch` préserve `fpData.currentIdx` par NOM au lieu de
  le reset à 0.
  (b) Sync immédiat `fpData.rooms[i]` depuis `ingState.rooms[i]` sur
  commit bbox edit, avant le fetch async.

### D-129 — Clamp openings accepted par Re-analyze aux dims state (2026-04-21)

- **Bug Lock ON + pièce rétrécie** : openings retournées par le backend
  (dans le canon frame relative au bbox backend) pouvaient dépasser les
  dims state quand le bbox backend différait du effBbox user locked.
- **Fix** : `window.clampOpeningsToDims(openings, W, D)` extrait comme
  helper partagé (refactor D-128 interne). Appliqué dans init_rvtool.js
  avant assignation à state.room_windows/openings/doors. Non-Lock :
  idempotent. Lock : coupe les openings débordantes.

### D-128 — Clamp openings + sync fpData après bbox edit Floor (2026-04-21)

- **Bug** : resize d'une pièce dans Floor laissait les openings/windows/
  doors dépassant hors de la nouvelle pièce, et Review affichait toujours
  la pièce pré-resize.
- **Fix** : `clampRoomContentsToBbox(room)` coupe les ouvertures / zones
  au nouveau gabarit ; `fpLoadAndMatch(ingState.rooms)` re-match et
  synchronise `fpData.rooms` après chaque commit du bbox editor.

### D-127 — Propagation bbox effectif user au backend Re-analyze (2026-04-21)

- **Fix Test 3 D-126** : quand l'utilisateur résize en amend mode puis
  Re-analyze (avec ou sans Lock), le backend recevait l'ancien bbox_px
  et détectait les openings dans l'ancienne géométrie — incohérent avec
  le bbox redimensionné.
- Pipeline : `canonBboxUser → rotateRectInv → × pxPerCm → effBbox` envoyé
  au backend à la place de `origRoom.bbox_px`.
- `transparent_zones` conversion + re-ancrage D-124 utilisent aussi les
  dims effectives.
- **Limite connue** : `ramend.originalRoom.bbox_px` n'est pas mis à jour
  au Save — le resize persiste dans `dims` mais pas dans `bbox_px`. À
  traiter séparément.

### D-126 — Toggle Lock bbox sur Re-analyze (2026-04-21)

- Nouvelle checkbox « Lock bbox » Room toolbar (amend mode). Quand cochée,
  Re-analyze adopte uniquement les openings / windows / doors / hits
  redétectés ; bbox_px, dims, corridor_face_abs et overlay restent figés.
- Use case : raffiner les ouvertures après repositionnement manuel du bbox
  ou dépose d'un mur via zone transparente, sans perdre l'ajustement.
- Reset automatique de la checkbox à la sortie de l'amend mode.
- **Rider** : sur Re-analyze sans Lock, reset de `state.roomRenderOffset`
  à `{0,0}` en même temps que l'adoption du nouveau bbox/dims. Sans ce
  reset, un resize manuel préalable laissait la pièce visuellement
  décalée alors que les dims revenaient à l'auto-détection (pièce qui
  débordait dans le couloir).

### D-125 — Fix race state.overlay partagé fp/rv (2026-04-21)

- **Symptôme** : après Save room + pan, l'overlay se décale et la pièce
  arrive à (0,0) du plan raster.
- **Cause** : `fpRenderSvg` lisait `room._overlayOffsetX || 0` (champ
  jamais défini) → 0, écrasant l'état posé par `fpRenderEmptyRoom`. État
  partagé via `state.overlay` entre rvCanvas et fpCanvas. Race déclenchée
  par `fpRematchRoom` async post-Save.
- **Fix** : utiliser `room.bbox_px / pxPerCm` dans `fpRenderSvg` (même
  convention que `fpRenderEmptyRoom`). 4 lignes modifiées.

### D-124 — Re-ancrage des zones canoniques après re-analyze (2026-04-21)

- **Symptôme 2 « zones d'exclusion qui dérivent »** : après re-analyze, les
  zones restaient en canonique room-local alors que le bbox détecté se
  décalait dans l'image. Elles s'éloignaient des features du plan qu'elles
  couvraient initialement.
- **Fix** : pipeline canon → abs-room → abs-image → abs-room (new) → canon.
  Nouveau helper `canonicalIO.rotateRectInv(rect, cfAbs, absW, absD)` (source
  unique, 4 auto-tests round-trip) + `window.reanchorCanonicalZones` partagé
  par re-analyze unitaire (`init_rvtool.js`) et batch (`ingestion.js`).
  Propagé à `state.room_exclusions/transparents`, `r.*`, `am.*`, `fpData.*`.
- **Symptôme 1 (placement décalé nord)** : fixé transitivement. Même cause
  commune : zone stockée dérivait via re-analyze antérieur, pas bug de
  placement. Validé user 2026-04-21.
- **Suite — fix `transparent_zones` canon→abs** : helper
  `window.canonicalZonesToAbs` dans `ingestion.js` avant envoi backend (le
  backend attend abs-room-local, pas canon). Identité pour corridor sud.
- **Tests** : 16/16 auto-tests canonical_io OK. Identité préservée sur
  bbox/cf inchangés.



### Fixes session post-D-120

- **Pièce 902 door mauvais côté en Floor** : `renderIngestion` appliquait
  le rendu sur face canonique alors que le raster est en absolu. Fix :
  helper `_renderRoom` applique `toStorage()` + recompute `offset_px /
  width_px` par pièce à l'entrée du forEach.
- **Pièce 915 NaN flood SVG** : windows/openings sans `offset_px` →
  `<line x1="NaN">`. Fix : guards `!isNaN` cohérents avec doors.
- **Pièce 915 door rendue comme opening** : batch re-analyze écrivait
  `r.openings = mergedO` combiné, laissait `r.doors` stale. Fix : split
  `mergedO` → `mergedOpenings` + `mergedDoors` à l'injection dans
  ingState.rooms / fpData.rooms. bbox_abs_px synchronisé avec bbox_px.
- **Pièce 922 bbox trop basse sans clic** : `toStorage` écrasait
  systématiquement `bbox_px` par `bbox_abs_px`, même si bbox_px était
  plus à jour (post-re-analyze). Fix : bbox_abs_px / seed_abs_px
  deviennent fallback (utilisés uniquement si bbox_px / seed_px
  absents). Dette reportée à R-14 P2 (fusion des champs redondants).
- **Pièce 906 door invisible DSL/visu Review** : `fpRenderEmptyRoom` et
  `enterRoomAmendMode` écrivaient `state.room_openings = localRoom.openings`
  sans inclure `localRoom.doors` séparées. DSL (`rvRenderCurrent`)
  n'itérait que openings. Fix : combiner openings+doors (has_door:true)
  dans state + itérer les deux dans rvRenderCurrent DSL emission.
- **Pièce 906 180° flip post Save Room** : `fpRoomAmendments[name]`
  stockait `amendedRoom` (absolu post-toStorage) alors que consumers
  (fpRenderEmptyRoom) attendent canonique. Fix : stocker deep copy de
  `fpData.rooms[fr]` après propagation (canonique, cohérent avec
  invariant). `amendedRoom` (absolu) reste local pour `fpRematchRoom`.

### D-123 — Fix bug sauvegarde + perf Re-analyze All ×10

**Fix bug « openings transformées en portes au reload »** :

- `floor_plan.js:fpLoadAndMatch` pose maintenant `has_door=false`
  sur les openings et `has_door=true` sur les doors avant le POST à
  `/api/floor-plan/match`. Le backend (`OpeningSpec.has_door`
  défaut=True) interprétait auparavant les openings sans flag comme
  des portes, corrompant fpData/ingState au split de réponse → la
  sauvegarde écrivait les openings dans `doors` du JSON v3.

**Perf Re-analyze All (×9.8 mesuré sur M4)** :

- `extract_room_features` accepte un paramètre `binary_precomputed`.
  Si fourni, saute la binarisation globale + `remove_non_ortho`
  (opération dominante ~830 ms/appel sur 1920×1080).
- `/api/room/reanalyze_batch` calcule binary_global une seule fois
  puis partage à toutes les pièces. Masques room-locaux appliqués en
  zéro-out numpy sur une copie.
- Bench 10 pièces : 8 317 ms → 846 ms. Extrapolation 28 pièces sur
  cible CPU 10× plus lent : ~230 s → ~13 s.

### D-122 — R-14 complet (P1 → P7) livré

**P7 — Spec CANONICAL_STATE.md + tests** :

- Nouveau document `docs/specs/CANONICAL_STATE.md` : structure
  canonique, frontières I/O, API `canonicalIO`, 6 antipatterns
  interdits. Remplace `CANONICAL_STATE_REFACTOR.md` (R-12, archive).
- 12 auto-tests dans `canonical_io.js` (4 round-trips × 4 faces +
  8 rotatePoint/rotateRect × 4 faces). Tous verts.

**P5 — Frontend envoie canonique au matching** :

- `/api/floor-plan/match` reçoit désormais du canonique (fini le
  `toStorage` préalable dans `serializeForMatching` et
  `editor.js:save()`). Les scores sont corrects pour toutes les
  orientations, plus seulement south.
- `_canonRooms()` helper ajouté dans `ingestion_serialize.js` pour
  `serializeForMatching`. `_toAbsRooms()` reste pour
  `serializeForStorage` (JSON v3 disque = absolu, inchangé).
- `fpLoadAndMatch` + `fpRematchRoom` splittent l'openings combiné
  retourné par le backend pour préserver l'invariant P4.
- Backend `app.py:/api/floor-plan/match` : docstring du contrat
  canonique explicite. Pas de canonicalisation backend ajoutée
  (redondant si frontend respecte le contrat).

**P4 — Séparation openings/doors dans le state** :

- `state.room_doors` introduit comme collection parallèle à
  `state.room_openings`. `has_door:true` banni du state.
- Helper `_splitOpeningsIntoState` (editor.js) convertit la forme
  combinée (backend DSL / catalogue disque) vers les 2 collections.
- Rendu (editor.js / shared.js), DSL (editor.js / init_rvtool.js),
  CRUD (init_rvtool.js), enterRoomAmendMode, save, batch re-analyze
  utilisent les collections séparées directement.
- Combine+split aux frontières internes supprimés. Les combinaisons
  restantes sont aux frontières API (matching, catalogue disque),
  elles seront traitées par P5.

**P6 — Helpers publics de rotation canonicalIO** :

- `canonicalIO.rotatePoint(pt, cfAbs, absW, absD)` et
  `canonicalIO.rotateRect(rect, cfAbs, absW, absD)` exposés pour
  couvrir hits / seed / zones / auto_door_masks, non gérés par
  `fromStorage` / `toStorage` (qui opèrent sur offset_cm de face).
- `pointAbsToCanon` (ingestion.js) et `_absToCanon2` (editor.js)
  supprimés — remplacés par appels directs aux helpers publics.
- Tests auto-cover 8 cas (rotatePoint × 4 faces + rotateRect × 4 faces).
- `_canonicalAngle` local (editor.js) laissé en place — migration
  différée (convention d'angle SVG à valider visuellement).

**P3 — Rename `original_corridor_face` → `corridor_face_abs`** :

- 6 fichiers JS (canonical_io, ingestion_serialize, floor_plan,
  ingestion, editor, init_rvtool) + endpoint
  `/api/room/orientation-check` (request + response).
- 4 lectures ambiguës `room.original_corridor_face ||
  room.corridor_face` supprimées — elles masquaient silencieusement le
  "south" canonique pour le vrai repère absolu.
- `state.corridor_face` retiré (n'avait plus de lecteur post-rename).
- JSON v3 sur disque inchangé (`corridor_face` = absolu).

**P2 — Fusion `bbox_abs_px` / `seed_abs_px`** :

- Champs redondants supprimés ; `bbox_px` / `seed_px` seules coords
  image absolues (jamais rotés par la rotation canonique).
- Adapté dans `canonical_io.js`, `editor.js` save, `init_rvtool.js`
  orientation-check, `ingestion.js` batch re-analyze, `floor_plan.js`
  fpLoadAndMatch.
- Tests round-trip 4/4 OK.

**P1 — Rotation offset_px intégrée à canonicalIO** :

- **canonicalIO étendu avec `scale`** (`fromStorage(room, scale)` /
  `toStorage(room, scale)`). Recalcul `offset_px` / `width_px` =
  `round(offset_cm × pxPerCm)` colocalisé avec la rotation
  `offset_cm`. Fini les recalculs ad-hoc dans
  `ingestion_serialize.js:_pxFromCm` et
  `ingestion.js:_renderFeat/_renderPxPerCm`.
- **Call sites mis à jour** : `fpLoadAndMatch`, `_renderRoom`,
  `extractRoomsPreprocessed`, `computeCanonicalReanalyzeResult`,
  `_toAbsRooms`, `editor.js:save()` passent tous `ingState.scale`
  (ou `data.scale_cm_per_px` à l'import).
- **Tests round-trip étendus** : les 4 samples (south/north/east/west)
  portent désormais `offset_px` / `width_px` ; round-trip Node
  `fromStorage→toStorage` valide 4/4.
- Rétrocompatibilité : `scale` omis → px laissés intacts. Aucun
  changement du format JSON v3 sur disque.

### Planifié

- **D-121 / R-14 — Refactor canonique unifié** (plan complet :
  `docs/specs/CANONICAL_REFACTOR_PLAN.md`). 7 phases pour éliminer les
  causes racines des fixes récurrents : frontière unique canonicalIO,
  structures uniformes, champs redondants supprimés, contrat front/back
  explicite. ~6 jours de travail concentré. P1 livrée (2026-04-20).

## [Unreleased] — D-115 à D-120 (2026-04-20)

### Ajouté

- **D-120** : consolidation R-12 C1 → C4. `canonical_io.js` devient la
  source unique pour la rotation abs ↔ canon ; le textarea perd son
  rôle de pivot du matching.
  - **C1** : suppression de `_canonicalizeRoom` / `_decanonicalizeRoom`
    + `_FACE_MAPS` / `_INV_FACE_MAPS` dans `floor_plan.js`. `editor.js
    save()` (Room amend) bascule sur `canonicalIO.toStorage`. Correction
    du bug `origCf` latent depuis D-117 : lecture de
    `original_corridor_face` en priorité, sans quoi toutes les rotations
    de save étaient annulées pour les pièces non-south. Propagation
    vers `ingRooms` / `fpData` cohérente avec l'invariant canonique
    (dims canoniques, `corridor_face:"south"`, `bbox_abs_px` mis à
    jour) — plus d'écrasement qui causait une double rotation à l'export.
  - **C2** : `computeCanonicalReanalyzeResult` réécrit en wrapper mince
    autour de `fromStorage`. Matrice `FACE_MAPS` locale et fonction
    `toCanonFeat` supprimées. Bug prevCf (D-116) éliminé par
    construction : un seul chemin de canonicalisation.
  - **C3** : fusion `populateRoomsJson` + `devExportV3Json` dans
    `ingestion_serialize.js` (renommé depuis `ingestion_export.js`).
    Nouvelle API `window.olmSerialize.{serializeForMatching,
    serializeForStorage}`. Logique `toStorage` centralisée dans
    `_toAbsRooms()`.
  - **C4** : `fpLoadAndMatch` bimode (string legacy ou Array direct).
    Les 6 call sites internes dans `ingestion.js` passent désormais
    `ingState.rooms`. Plus de round-trip stringify / parse / fromStorage
    redondant dans le chemin de matching interne.
- **D-115** : séparation `surface_m2` (cartouche PDF, figée) vs
  `surface_m2_bbox` (calculée depuis bbox, dérive). Backend
  `extract.py` produit les deux. Frontend : consolidation du split
  partielle (encore des points d'écrasement côté JS à traiter en C3).
- **D-116** : helper partagé `computeCanonicalReanalyzeResult` pour
  le re-analyze unitaire (init_rvtool.js) et batch (ingestion.js).
  Endpoint batch accepte `door_width_cm`. **À remplacer par
  `fromStorage` en C2** (dette identifiée).
- **D-117** : refactor repère canonique unifié (R-12). Étapes A/B/C
  livrées : module `canonical_io.js` (fromStorage/toStorage avec 4
  round-trips testés), intégration aux frontières (fpLoadAndMatch,
  extractRoomsPreprocessed, devExportV3Json, populateRoomsJson),
  retrait `_canonicalizeRoom` des rendus, rotation overlay via
  `state.original_corridor_face`.
- **D-118** : re-analyze uniforme + zone transparente comme primitive
  de modélisation des modifications structurelles. Toggle "lock bbox"
  prévu pour préserver dimensions lors du raffinement d'ouvertures.
- **D-119** : auto-test d'orientation canonique via couleurs
  sémantiques du PNG -SD. Module `olm/ingestion/orientation_check.py`
  (check_corridor_south / check_exterior_north / check_all_faces),
  endpoint `/api/room/orientation-check`, bouton UI "Check orient."
  dans la Room toolbar (handler prêt, à tester après C1-C4).

### Corrigé

- Backend `extract_rooms_from_preprocessed` : ne dérive plus
  `corridor_face` depuis `openings[0].face` (arbitraire). Fallback
  via `_detect_face_colors` sur PNG enhanced (plus fiable).
- Enrichissement `offset_cm` / `width_cm` depuis `offset_px × scale`
  à l'import v3, pour que fromStorage trouve toujours des valeurs cm
  cohérentes à canonicaliser.
- `populateRoomsJson` repasse par `toStorage` avant sérialisation
  (symétrie avec devExportV3Json).
- Re-analyze (unitaire + batch) : `prevCf` passé au helper =
  `original_corridor_face` (repère absolu) au lieu de `corridor_face`
  (canon "south"). Résout la régression orientation post-re-analyze
  pour pièces non-south.
- Invariant `state.corridor_face === "south"` maintenu dans les flux
  re-analyze : `canon.corridor_face` alimente `original_corridor_face`
  partout (state, amendments, fpData.rooms, ingState.rooms).
- **Export v3 `offset_px` cohérent après rotation** : `serializeForStorage`
  recalcule `offset_px` / `width_px` depuis `offset_cm × pxPerCm` après
  le `toStorage` (toStorage ne touchait pas les px). Fallback sur px
  existants si offset_cm absent (rétrocompat OCR).
- **Amendements Room → `ingState.rooms` complétés** : la propagation
  dans `editor.js save()` inclut désormais windows, openings, doors
  (via has_door), exclusion_zones, transparent_zones. Avant : seuls
  bbox + dims + doors étaient propagés ; les édits manuels de fenêtres
  /ouvertures étaient perdus dans l'export v3.
- **Re-analyze nécessitant 2 passes** (bug utilisateur confirmé
  2026-04-20) : cause = filtre `preservedDoors` incohérent dans
  `init_rvtool.js` et `ingestion.js`. Utilisait `o.origin !== "auto"`
  qui capturait les doors initiales (origin:undefined depuis le backend
  match) comme "à préserver" → la 1re re-analyze ignorait les doors
  détectées. `_rvCommitFromState` retaguait ensuite en "auto" d'où le
  succès de la 2e passe. Fix : `o.origin === "manual"` (cohérent avec
  `manualW` / `manualO`).
- **Save button inactif en fullscreen** : header en `<table>` débordait
  le viewport en vue étroite, laissant les boutons Save/Export/Close
  hors-écran ou sous la zone de révélation du Chrome Mac fullscreen
  (top ~40px). Converti en flexbox avec `flex:1; min-width:0` à gauche
  (tab-description tronque en ellipsis) et `flex-shrink:0` à droite.
  Padding-top:30px sur la colonne droite pour décaler les boutons
  sous la zone de révélation.

### En cours

- **Bug Save physique** : `document.elementFromPoint` undefined à la
  position du bouton ; clic programmatique OK. Confirmé non-lié à
  C1-C4 (réglage indépendant à venir).
- **Dette R-12 différée** : fusion `bbox_px` / `bbox_abs_px` et
  `seed_px` / `seed_abs_px` (les deux couples restent en parallèle).
- Bugs P2 connus hors R-12 : re-analyze nécessite parfois 2 passes
  pour détecter les portes, zoom arrière bloqué trop tôt.

---

## [Unreleased] — D-108 à D-114 (2026-04-19)

### Ajouté

- **D-108** : `olm/core/detection_config.py` — paramètres de détection en cm,
  conversion px runtime via `DetectionConfigCm.to_px(scale)`. Regroupe 18 seuils
  auparavant hardcodés (min_opening_width, min_window_width, max_absorb, comb_step,
  door_*, snap_search, wall_depth, ray_margin…). Consommé par `extract.py` et
  `test_comb.py` (via `_apply_detection_config`).
- **D-109** : re-analyze expose les portes détectées (expand_door_arcs) quand
  l'appelant n'en fournit pas. À minima égalise l'import OCR.
- **D-110** : re-analyze redétecte les portes à chaque run — plus de
  préservation des auto doors (qui masquaient les arcs et empêchaient la
  redétection). Les portes manuelles (origin="manual") restent préservées.
- **D-111** : règle métier — une face ne peut pas avoir à la fois fenêtres et
  openings. Si coexistants, les openings sont des artefacts du double trait
  de fenêtre → supprimés.
- **D-112** : canonicalisation cohérente — la re-analyze retourne des coords
  ABSOLUES, le state frontend stocke en CANONIQUES. Transformation
  absolu → canonique appliquée à : openings/windows/doors (face, offset,
  hinge_side), hits + seed, auto_door_masks_px, width/depth (swap east/west).
  Idem au chargement depuis JSON.
- **D-113** : `corridor_face` auto-mis à jour à la re-analyze depuis
  `doors[0].face` — une pièce sans doors ni canonical_top_face au JSON
  se corrige toute seule après une re-analyze.
- **D-114** : `canonical_top_face` explicite dans le JSON prend priorité sur
  la détection couleur pour `corridor_face` (override manuel).

### Modifié

- `_merge_adjacent_segments` prend désormais `max_absorb_px` (avant hardcodé
  à 120 px = 355 cm à scale 2.96 → absorbait toute porte < 3 m). Défaut
  `max_absorb_cm = 30`.
- Save room : transformation canonique → absolu du shift + dims pour
  tous les corridor_face (auparavant seulement south/unset).
- Centre de rotation overlay figé sur le NW original pendant drag (évitait
  la rotation visuelle de l'overlay avec le shift).
- `save()` préserve `seed_px` dans `localRoom` / `amendedRoom` (sinon
  l'amendment stocké perd le seed et empêche la re-analyze suivante).
- Batch `reanalyze_batch` : signature `extract_room_features` corrigée,
  `seed_px` propagé depuis le frontend.
- Suppression du depth check openings (min_opening_depth) — rejetait à
  tort les portes mitoyennes quand le mur voisin était proche.

---

## [Unreleased] — D-101 à D-107 (2026-04-19)

### Ajouté

- **D-101** : overlay par niveau (Floor = PNG standard, Room/Office = PNG `-SD`).
- **D-102** : rulers mètres HTML unifiés (origine NW pièce) ; resize synchronisé panneaux Room/Office.
- **D-103** : CRUD graphique ouvertures ; zones exclusion rouge + transparentes verte (DSL `TRANSPARENT`) ; dropdown "Add room items" ; traits à taille constante.
- **D-104** : Re-analyze ciblée avec `origin: auto|manual` + `deleted_auto_signatures`.
- **D-105** (doc) : pipeline Préprocessé refondu — spec complète.
- **D-106** (doc) : leçons d'une Phase 1 tentative (revert).
- **D-107** : Re-analyze par pièce **fonctionnelle** : ray-cast `test_comb.detect_room` depuis seed, masquage auto portes, V/H-rays debug visualisation, masques debug, préservation manuels.

### Modifié

- `<select>` plans → liste filtrable inline.
- Zoom fit Room/Office : pièce + 20% padding. Clamp zoom-out à 3× vue fitée.
- Labels dimensions : width sous, depth à gauche, offset 48 px.
- fpOverlay.pxPerCm mis à jour sur scale change.

### Supprimé

- R-09 merges (D-100).
- Entrée "All" des listes Room/Office.

---

## [Unreleased] — D-94 refactoring front-end

### Supprimé
- `olm/templates/matching_viewer.html` (1138 lignes) et route Flask `/matching` associée — dead code, jamais référencé depuis HTML/JS (P0 du refactoring front-end, D-94).

### Ajouté (P1 — store unifié)
- `olm/static/store.js` : store unifié `olmStore` (get/set/subscribe/reset) regroupant les 5 états globaux auparavant éparpillés (`fpData`, `fpAmendments`, `fpRoomAmendments`, `fpOverlay`, `ingState`).
- Chargé en premier dans `pattern_editor.html` pour garantir que les globals de compat (`window.fpData`, etc.) existent au moment de l'init des autres modules.

### Modifié (P1)
- `floor_plan.js` / `ingestion.js` : suppression des inits locales redondantes, `ingState`/`fpData` sont maintenant des refs vers les sections du store.
- `init.js` : les 3 sites de reset (`Close`, `Erase All`, `Erase Layout`) appellent `olmStore.reset(...)` qui mute en place les objets — préserve l'identité des refs détenues par d'autres modules (corrige un bug latent où les refs devenaient stale après reset).

### Modifié (D-95 — échelle de dessin)
- L'input UI du champ `drawing_scale` prime désormais sur les valeurs du JSON v3 (Option D). À la sauvegarde, les deux champs `drawing_scale_text` et `drawing_scale_measured` sont écrasés par la valeur courante.
- `_applyDrawingScale` propage les nouvelles dimensions à `fpData.rooms` — les vues Room et Office restent synchronisées (corrige un bug d'affichage où les cm restaient stales après changement d'échelle).
- `devExportV3Json` émet désormais `drawing_scale_text` et `drawing_scale_measured` dans le JSON.

### UX
- `.sub-tab-bar` : `align-items: baseline` — les descriptions des sous-onglets (Catalogue) s'alignent sur la baseline des boutons au lieu d'être centrées verticalement.

### Refactor (D-96 — primitives SVG partagées, P2)
- Nouveau `olm/static/render_shared.js` : `doorSvg()` + `gridSvg()` + constantes couleurs partagées.
- `editor.js` et `ingestion.js` : 172 lignes de rendu porte/grille dupliquées factorisées en appels au module partagé (-70 l. editor, -50 l. ingestion).

### Fix (Floor + Pattern editor)
- `ingestion.js` : support du format door `offset_px`/`width_px` (mode préprocessé), en plus du format `jamb_hinge_px`/`jamb_free_px` (mode OCR) — les portes s'affichent désormais dans Floor en mode préprocessé.
- `ingestion.js` : ajout d'un `eraseWallSegment` qui casse le rectangle blanc de la bbox à l'emplacement des portes et openings (comportement déjà présent dans l'éditeur de patterns).
- `editor.js` : contour de pièce blanc dans le Pattern editor (précédemment gris #4a4640) pour cohérence avec Review/Office. Épaisseur réduite de 50 % (1.5 → 0.75 en éditeur, 2 → 1 en Review/Office).
- `editor.js` : murs passés de `z=0.05` à `z=4` (au-dessus des blocs, sous les ouvertures) — demande utilisateur.

### Refactor (D-97 — split init.js, P3)
- Nouveaux `olm/static/init_rvtool.js` (~300 l.) et `olm/static/init_resize.js` (~100 l.), extraits de `init.js` (1082 → 724 l.).
- `init_rvtool.js` : outil zones d'exclusion du Room amend mode, capture-phase sur keydown pour préempter la navigation Room/Office.

### UX (zones d'exclusion Room)
- Couleur sélection rouge (au lieu de vert), poignées de resize aux 4 coins (2×2 px), clampage complet aux 4 faces (drag + resize + flèches), Enter = commit, Escape = annulation. Bouton renommé "Add exclusion zone".

### Refactor (D-98 — split ingestion.js, P4)
- Nouveaux `olm/static/ingestion_scale.js` (~90 l., `window.olmScale.*`) et `olm/static/ingestion_export.js` (~125 l., `window.devExportV3Json`), extraits de `ingestion.js` (1605 → 1432 l.).

### Feature (D-99 — Room resize, 4 poignées)
- Room amend mode : 4 poignées rouges aux coins permettent de redimensionner ET déplacer la pièce à la souris (snap 5 cm). Contenu (fenêtres, portes, ouvertures, exclusions) translaté pour conserver ses positions absolues. Offset de rendu persistant dans la session d'amend. Clampage des ouvertures qui débordent après resize. Propagation `bbox_px` vers Floor à la sauvegarde (corridor south uniquement pour l'instant). Rationale : Floor = ajustements grossiers, Room = ajustements fins.

### Décision d'architecture (D-100)
- Abandon de R-09 (Identify merges) : le workflow resize + Add/Delete + commentaires markdown par pièce couvre le besoin "étudier la suppression de murs entre pièces" sans dette technique. TODO.md mis à jour (R-09 retiré, feature `comments_md` ajoutée).

---

## [v0.3.1] — 2026-04-17 : D-91→D-93

### Modifié
- Convention fichiers préprocessés : `_enhanced.png` → `-SD.png` (Sans Description).
- `config.json` : `drawing_scale` → `drawing_scale_text`.
- Sous-onglets renommés : Rooms → Room, Design → Office.
- Settings : Floorplan → Floor, Layout → Office, Export intégré dans General avec séparateur visuel.

### Ajouté
- `drawing_scale_measured` (cm/px) et `orientation` (degrés) dans le JSON v3 préprocessé.
- Priorité `drawing_scale_measured` > `drawing_scale_text` + DPI dans le calcul d'échelle, avec log warning si divergence > 20%.
- Bouton Export à droite de Save dans la barre d'actions.
- Standard par défaut pré-sélectionné dans Office à chaque changement de pièce.

### Amélioré (UX)
- Settings General : section Standards unifiée (radio default + label éditable par ligne).
- Settings Floor : Plans directory élargi, DPI centré, "Standard colors" avec descriptions.
- Settings Office : 3 nouveaux poids de scoring (back to door, natural light, face to wall).
- Toolbar Floor masquée tant qu'aucun plan chargé.

### Nettoyage
- TODO.md : 161 → 48 items (−70%), suppression des obsolètes, doublons, historique [x], sections spéculatives.

---

## [v0.3.0] — 2026-04-16 : D-87→D-90

### Corrigé
- Overlay PNG décalé d'une demi-pièce pour les pièces avec corridor east/west (rotation 90°/270°) — ajout d'un translate compensatoire dans `editor.js`.
- `corridor_face` perdu après Save en mode Room Amend — propagation dans `enterRoomAmendMode()` et `fpRoomAmendments`.

### Ajouté
- Module Python `olm/core/canonical.py` : port de `canonicalize_room()` / `decanonicalize_room()` depuis JS.
- 19 tests pytest round-trip dans `olm/tests/test_canonical.py`.

### Amélioré (UX)
- Couleur labels dimensions : `--text-dim` #6e6a62 → #908a7e, `COLOR_RULER` → #b0a898, labels SVG utilisent la constante.
- Hauteur onglets principaux : padding 10px → 14px. Sous-onglets : 4px → 8px (zone cliquable élargie).
- Contraste onglet actif : border-bottom 3px accent, hover fond surface2.
- Croix fermeture Settings : padding élargi + flex center (zone cliquable alignée).
- Add room : prompt auto-incrémenté basé sur max ID numérique existant.
- Dézoom limité : clamp zoom min 0.5 (Review/Design), clamp viewBox max 2× plan (Import).

### Corrigé (bugs)
- Plan fantôme : canvas rvCanvas/fpCanvas vidés quand aucune room n'est chargée.
- Esc bbox editor Import : restaure la position ET désélectionne la pièce.
- Review après Save : render() masque state.rows en Review hors mode édition, empêche l'affichage résiduel de blocs Design.
- Synchro liste gauche : auto-scroll étendu à Import (était limité à Review).
- Warning sortie Adjust room : confirm() bloque le changement d'onglet si modifications non sauvegardées.
- Double-click Import → Review : dblclick délégué sur ingSvg (survit aux re-renders SVG).
- Room list Review : hauteur alignée sur Import (210px, min/max/resize).
- Labels dimensions : rectangle de fond sombre pour lisibilité sur overlay.
- Grille Design : labels "1m", "2m"… le long des bords de la pièce.
- UI 100% anglais : 5 chaînes françaises dans ingestion.js traduites.

### Fonctionnalité (D-90)
- **Option B layout** : navigation à gauche, détail à droite. Floor = colonne unique. Rooms = room list gauche + détail droite. Design = room list + candidates gauche + info droite.

### Amélioré (UX navigation)
- Onglets : Floor / Room (renommés depuis Import / Review).
- Contraste onglets renforcé (actif #e8c46a, inactif #6a655c).
- Zone hover étendue via pseudo-element (::before) sans changement visuel.
- Sous-onglets Catalogue : taille ajustée, espace vertical, description italique à droite, actif en gras.
- Onglets Review/Design masqués sans plan chargé, sections Import conditionnelles.
- Room list hauteur 370px dans Floor et Room.
- Standard par défaut (SITE) dans le filtre Design.
- Dézoom limité au fitViewBox (110%).
- Double-click plan Import → Room (détection par timer mousedown 400ms).

### Fonctionnalité (D-88)
- **Drawing scale** : paramètre explicite `drawing_scale` (format "1 : 100") dans Import + `render_dpi` dans Settings > Floorplan. Formule `cm_per_px = 2.54 × scale / dpi`. Si non renseigné, estimation inverse affichée en jaune. Recalcul live des dimensions sans re-import.

---

## [Unreleased] — Conception 2026-04-14 / 2026-04-15 : D-78 à D-85

### Décisions d'architecture (tracées dans Decisions.md)

- **D-85** — Auto-détection OCR / Preprocessed par fichier, mode invisible à l'UI. Suppression du sélecteur de mode global et du paramètre Settings associé. Règle : PNG seul → OCR, PNG + JSON dont mtime > PNG.mtime → Preprocessed, sinon fallback OCR. Dropdown Load en liste plate triée alphabétiquement (pas de sections, pas de badges). Confirmation navigateur avant extraction OCR ("No JSON file found — Processing with Optical Character Recognition..."). Paramètre `ingestion.plans_dir` exposé dans Settings pour pointer vers un dossier externe. Format JSON v2 (legacy) explicitement rejeté par le parser avec message d'erreur clair.
- **D-84** — JSON v3 simplifié + règle "docs = source unique de vérité". `PREPROCESSED_JSON_SPEC.md` réécrit : suppression de `plan_scale`, `dpi`, `all_text_blocks`, métadonnées typographiques et référentiel points. Aplatissement du cartouche en 3 champs plats, imbrication des `doors/openings/windows` dans chaque room. Schéma door scindé Input (`label_px`) vs Save (enrichi OLS). Bouton DEV "Export v3 JSON" (contour orange vif) implémenté côté frontend pour sérialiser l'état OCR dans ce format. Règle générale ajoutée dans `CLAUDE.md` : toute information utile à long terme vit dans `docs/` uniquement.
- **v3.1 du JSON spec (2026-04-15)** — affinage : split `seed_px` / `label_px` (arrays `[x, y]`) en champs scalaires `seed_x` / `seed_y` / `label_x` / `label_y`. Marquage explicite Required/Optional/Save-only sur chaque champ. Convention d'omission formalisée (champ non renseigné = absent du JSON). `rooms` devient un objet indexé par room_id. Ajout de `canonical_top_face` (D-83) et `north_angle_deg`. Suffixe `_enhanced` réservé — les PNG `<plan_id>_enhanced.png` sont groupés avec leur parent par `/api/plans`.

### Implémentations livrées (2026-04-15)

- Parser `extract_rooms_from_preprocessed` réécrit pour le format v3 : lit l'objet rooms indexé par id, déduit `cm_per_px` depuis les surfaces m² des pièces déjà bboxées, skippe le ray-cast si `bbox_px` présent. Rejette le format v2 legacy avec `ValueError` explicite.
- Route `GET /api/plans` : enrichie avec `effective_mode` et `has_enhanced`, groupement du suffixe `_enhanced`, lit `ingestion.plans_dir` depuis `config.json` via `_get_plans_dir()`.
- Routes `/api/import/ocr` et `/api/import/preprocessed` : acceptent un paramètre `plan_id` qui résout les chemins depuis `plans_dir` (plus besoin d'upload de fichier multipart).
- Frontend Load : suppression du dropdown mode, liste plate des plans, confirmation navigateur avant OCR, bouton DEV Export v3 JSON (orange vif), badge plan courant dans le header.
- Nav 2+2 avec onglets principaux Floorplan / Layout (fond jaune doré, coins arrondis, alignement baseline du label avec les sous-onglets) + contenus Import/Review et Design/Catalogue. Bouton Save dans le header.
- Bbox editor générique : ajout/déplacement/redimensionnement de pièce à la souris, flèches clavier pour déplacer, Delete pour supprimer, Escape pour restaurer la position de début de session.
- Add room manuel avec stub 300×400 cm placé au-dessus du plan, bouton "Add" inline.
- Règle `_enhanced` comme suffixe réservé documentée dans `PREPROCESSED_JSON_SPEC.md`.
- Dual-pass OCR Tesseract (PSM 11 + PSM 6) + clustering ancré sur les surfaces avec fenêtre adaptative `h_med * 7` vertical — élimine le matching greedy qui cassait sur cartouches partiellement lus.
- **D-83** — Orientation canonique des pièces en Review et Design : couloir en bas / fenêtres en haut, l'utilisateur est toujours positionné "en entrant par la porte". Rotation purement visuelle appliquée au groupe racine SVG via un helper `computeRoomViewTransform(room)`. Coordonnées internes inchangées. Aligne la vue sur le référentiel des patterns du catalogue.
- **D-82** — Clôture R-01 : `olm/README.md` promu en `README.md` racine (convention GitHub), `pyproject.toml` corrigé (`build-backend = "setuptools.build_meta"`, `readme = "README.md"`). `.gitignore` déjà conforme (exclusion `project/`, `docs/`, `solver_lab/`, `CLAUDE*.md`, `.claude/`).
- **D-78** — Navigation 3 onglets (Floor plan / Office layout / Export) + full round trip via clé `olm_state` dans le JSON v2. Remplace partiellement le workflow 5 étapes de D-68. Identification du plan par nom fichier PNG, politique de diff explicite (réhydratation / badge "Nouveau" / warning orphelines).
- **D-79** — Ray-casting context-aware en Mode Préprocessé : zones de transparence de porte via `doors[]` + règle d'arrêt sémantique sur les frontières blanc↔vert (couloir) et blanc↔bleu (extérieur). `RASTER_EXTRACTION_SPEC.md` §11bis ajoutée.
- **D-80** — Zones interdites à double origine : promotion automatique des petits artefacts en ingestion (`min_size_artifact_cm2` défaut 2500) pour les open space avec poteaux, + outil souris Review (Add / move / Delete, pas de redimensionnement souris — DSL = source de vérité).
- **D-81** — Cartouche OCR aligné sur 3 lignes (code / surface / id), alignement avec le format Mode Préprocessé. Suppression de N REEL / N THEO non exploitées et sources d'ambiguïté OCR. `INGESTION_HYPOTHESES.md` §H-09 mise à jour.

### Session 2026-04-15 (après-midi)

#### UX / Interface
- Fusion header + barre d'onglets en une seule ligne (table layout). Suppression du titre "Office Layout Studio".
- Onglets agrandis (+20%), espacement ajusté entre groupes et sous-onglets.
- Fond des sous-onglets inactifs assombri pour meilleure lisibilité.
- Description de l'onglet actif affichée à droite des onglets.
- Bouton Save masqué tant qu'aucun plan n'est chargé. Bouton DEV Export v3 supprimé (redondant avec Save).
- Boutons Close et Erase (All / Layout only) ajoutés dans le header. Erase ne ferme plus le plan.
- Zoom molette souris dans Import (centré sur curseur).
- Focus auto sur la bbox des pièces en mode Préprocessé à l'ouverture.
- Double-click sur une pièce dans Import → navigation vers Review avec focus.
- Enter valide la sélection bbox dans Import. Esc annule en mode Adjust room.
- Re-trigger du matching après ajout/suppression de pièce dans Import.
- Prompt dialog si ajout de pièce sans ID. Placeholder "Room ID" simplifié.
- Marge haute colonne gauche Import/Review. Renommage "Floor plan" → "Current floorplan".
- Debug log supprimé de Import.
- Colonne gauche Review redimensionnable (poignée + localStorage) — instructions IMPLEMENTER.

#### Backend / Pipeline
- Endpoint `/api/image` sécurisé : ne sert que depuis `olm_overlays` et `PLANS_DIR` (réalpath + guard).
- Choix plan base/enhanced selon contexte : plan de base en Import, enhanced en overlay Review/Match.
- `corridor_face` calculé en mode Préprocessé depuis `doors[0].face` (au lieu de `""` en dur).
- Détection couleurs de face (`_detect_face_colors`) : échantillonnage pixels au-delà de chaque face de bbox dans le PNG enhanced pour détecter vert (couloir) et bleu (extérieur).
- Paramètres `preprocessed_exterior_rgb` et `preprocessed_corridor_rgb` dans config.json.
- Outil CLI `olm/tools/colorize_enhanced.py` : flood fill extérieur (bleu) + couloirs (vert) avec dilatation des murs pour boucher les portes.

#### Settings
- Drawer Settings restructuré en 5 onglets : General, Floorplan, Layout, Catalogue, Export.
- Couleurs sémantiques (exterior RGB, corridor RGB) exposées dans Settings > Floorplan avec preview.

#### Corrections
- Fix crash `fpBtnExport` manquant (guard `if` ajouté).
- Fix crash `fpOverlayStatus` null (guard ajouté).
- Fix lignes blanches fantômes : portes avec coordonnées `undefined` ignorées, rect fond SVG ajouté.
- Fix grille 1m : lignes à x=0/y=0 ne sont plus privilégiées.
- Fix Close : dropdown plan reset à la position placeholder.

#### Architecture (D-86)
- **D-86** — Classification portes principales (couloir/vert) vs secondaires (entre bureaux). `corridor_face` = source de vérité pour l'orientation canonique. Rotation D-83 préparée (code posé puis désactivée en attente du PNG enhanced colorisé).

### Documentation

- `docs/TODO.md` : R-08 refondu (nav 3 onglets), R-11 nouveau (round trip), R-05 enrichi (validation Tesseract D-73, cartouche 3 lignes D-81, zones interdites D-80, paramétrage couleurs RGB sémantiques, révision logique fenêtres, générateur de plan de test)
- `docs/specs/RASTER_EXTRACTION_SPEC.md` : section 11bis ray-casting context-aware
- `docs/specs/PREPROCESSED_JSON_SPEC.md` : section 6bis exploitations futures (portes, couleurs, all_text_blocks)
- `docs/specs/INGESTION_HYPOTHESES.md` §H-09 : cartouche 3 lignes

---

## [Unreleased] — Format JSON preprocessé v2 (D-77) (2026-04-14)

### Modifié (breaking)
- **`extract_rooms_from_preprocessed()`** : migré vers la structure v2 :
  - Clé principale `cartouches` → `rooms`
  - Plus de wrapper `center` : `code_line1` / `surface_line2` / `id_line3` directement sur la room
  - `room_id` primaire depuis `id_line3.text`
  - Seed du cartouche calculé via nouveau helper `_room_center_from_lines()` (moyenne pixels_x des 3 lignes, pixels_y de surface_line2)
  - Support ROOT : `total_text_blocks`, `total_rooms`, `total_doors`, `all_text_blocks[]`, `doors[]`
  - `scale_factor` (renommage de `scale`, non utilisé pour cm/px)
- **`docs/specs/PREPROCESSED_JSON_SPEC.md`** : réécrite pour la v2 avec section historique des versions

### Ajouté
- **`_room_center_from_lines()`** (`olm/ingestion/extract.py`) : calcule le centre d'un cartouche depuis ses 3 lignes
- Portes (`doors[]`) loggées à l'import (non exploitées v1)

---

## [Unreleased] — Format JSON cartouches pour Mode Préprocessé (D-76) (2026-04-12)

### Ajouté
- **`docs/specs/PREPROCESSED_JSON_SPEC.md`** : spec complète du format JSON cartouches (métadonnées globales, structure cartouche/center/lineN, conversion cm_per_px)
- **Helpers** (`olm/ingestion/extract.py`) : `_parse_plan_scale_ratio()`, `_cm_per_px_from_metadata()`, `_parse_surface_m2()`

### Modifié
- **`extract_rooms_from_preprocessed()`** : parse la structure `cartouches` (au lieu de `rooms`). Extrait `room_id` depuis `cartouche.number`, seed depuis `center.pixels_x/y`, surface parsée depuis `line2.text`. Bbox carrée centrée sur seed, côté calculé via `cm_per_px = (2.54/dpi) × plan_scale_ratio`. DPI par défaut 300.

---

## [Unreleased] — Dual-mode ingestion : Mode OCR + Mode Préprocessé (2026-04-12)

### Ajouté
- **`IngestionMode` enum** (`olm/core/types.py`) : `OCR` et `PREPROCESSED`
- **`extract_rooms_from_preprocessed()`** (`olm/ingestion/extract.py`) : parse JSON préprocessé + valide les PNG enhanced/overlay, retourne la liste de dicts pièces
- **Route `/api/import/ocr`** (`app.py`) : wraps le pipeline OCR existant, champ `floorplan_image` + `scale_cm_per_px`
- **Route `/api/import/preprocessed`** (`app.py`) : reçoit JSON + PNG enhanced + PNG overlay, retourne les pièces
- **Route `/api/import/preprocessed/image`** (`app.py`) : sert le PNG enhanced temporaire vers le navigateur
- **Dropdown Input Mode** (`pattern_editor.html`) : sélecteur "OCR / Préprocessé" en haut du panel Import
- **Formulaire préprocessé** (`pattern_editor.html`) : upload JSON + PNG enhanced + PNG overlay
- **`renderImportPanel()`** (`ingestion.js`) : affichage conditionnel OCR vs Préprocessé
- **`extractRoomsPreprocessed()`** (`ingestion.js`) : appel `/api/import/preprocessed`, intégration pipeline floor_plan

---

## [Unreleased] — OCR Tesseract : whitelist typée + désactivation dictionnaires (2026-04-12)

### Amélioré
- **Whitelist Tesseract** (`test_comb.py`) : couvre exactement les 3 types de tokens attendus — codes pièce (`14`, `14c`), numéros de pièce (`916`, `12a`, `1AB`), surfaces (`14.28 m2`). Whitelist : `0-9 . , a-z A-Z espace`
- **Désactivation dictionnaires** : `load_system_dawg=0` + `load_freq_dawg=0` — sans cela, Tesseract biaie les tokens vers des mots anglais même avec une whitelist contenant des lettres
- **Regex de validation** : `_RE_ROOM_CODE`, `_RE_ROOM_NUMBER`, `_RE_SURFACE` définies au niveau module, utilisées pour filtrer et classer les tokens OCR
- **Algorithme de matching** : tri des candidats numéro de pièce par longueur décroissante puis distance croissante — évite que des tokens courts (`"2"` de `"m2"`) battent de vrais numéros (`"916"`) plus éloignés
- **Upscale x2 LANCZOS** + ajustement des coordonnées TSV (÷2), timeout 30 s

### Impact
- 28 pièces correctement détectées sur `test_floorplan3.png`, numéros et surfaces exacts

---

## [Unreleased] — Matching restauré, UX fixes, Design Layout OK (2026-04-07)

### Corrigé
- **Catalogue vide** : restauré 20 patterns depuis commit 53d75bc (standards AFNOR_ADVICE, GROUP, SITE). Était vidé lors de D-68 (séparation open source)
- **isReview undefined** : renderRoomElements() appelée sans paramètre `isReview` → fixé en détectant `svg.id === 'rvCanvas'` dans _renderImpl()
- **fpBtnLoadJson null** : addEventListener() sur élément supprimé → protégé avec null check
- **Arc de porte UX** : stroke-width 0.8 → 1.5, dasharray 3 2 → 6 3 (4 fichiers : ingestion.js, catalogue.js, editor.js, matching_viewer.html) pour aligner avec pointillé green "open bay"
- **Design Layout grille** : ajout fond opaque #1e1e1e (z=0.5) masquant grille sous blocs + zones circulation

### Impact
- Design layout fonctionne de nouveau (affiche candidats matching)
- Arc de porte cohérent visuellement dans toutes les vues
- Matching disponible sur toutes les pièces (grande/petite taille)

---

## [Unreleased] — Revue UX complète, rulers, overlay Review (2026-04-05)

### Ajouté
- **Design tokens CSS** : palette, typographie (fs-xs→fs-room), espacements (sp-xs→sp-page) dans `:root`, propagés dans tout le CSS
- **Classes utilitaires** : `.settings-grid`, `.settings-input`, `.btn-toolbar`, `.btn-cancel`, `.help-link`, `.hint-text`, `.svg-canvas`, `.edit-mode`
- **Fauteuil SVG redesign B1-3** : assise arrondie (rx proportionnel) + dossier arc courbe, proportionnel au SCALE
- **Rulers HTML fixes** : barres haut/bas/gauche/droite avec labels de graduation, créées dynamiquement via `ruler-box`, indépendantes du zoom et du pan
- **Polices constantes** : distances inter-blocs, dimensions pièce, grille, labels de postes — taille visuelle constante via `zf = 1/svgScale` (compensation viewBox/pixel)
- **Dirty tracking** : indicateur `.edit-mode` (liseré ambre) quand un pattern a des modifications non sauvegardées, bouton Cancel visible
- **Overlay raster dans Review rooms** : toggle + opacité synchronisés avec Design layout, auto-coché au chargement
- **Pan souris** sur les 3 canvas (éditeur, Design, Review) via `setupPan()`
- **Tooltip DSL layout** : syntaxe complète (blocs, gaps, rotations, offsets NS, sticks, multi-rangées), centré à l'écran, croix de fermeture, scrollbar
- **Zoom fit** adapté au ratio d'aspect du SVG (plus de letterboxing), marges augmentées

### Modifié
- Renommage UI : **Office Layout Studio** (titre + `<title>`)
- Harmonisation Adjust room / Amend layout : classe `.edit-mode` commune, Cancel/Save cohérents
- Amend layout : onglet Design reste actif (pas Edit catalogue), sous-onglets cachés, sélection/clavier fonctionnels
- Cancel en amend layout retourne vers Design (pas Review)
- Amend sans modification : pas d'amendment créé
- Edit catalogue : retour sur Card view (pas Pattern editor)
- Écran SVG décalé vers l'intérieur du bureau, fenêtre SVG affinée (stroke-width 1.5)
- Tab buttons sans border-bottom (ligne unique avec desc bar), desc bar en italique
- Nettoyage inline styles massif (settings inputs ×6, cancel buttons ×3, zoom buttons ×9, help links, SVG canvas)
- Bug fix : filtre standard dans Design layout (listener manquant)
- Bug fix : state périmé au toggle Grid/Circ dans Design layout (re-render via fpRenderSvg)
- Bug fix : grille étendue au-delà du viewBox pour survivre au pan

---

## [Unreleased] — R-08 navigation, bug fixes, convention desk (2026-04-05)

### Ajouté
- **R-08 Navigation** : 6 onglets principaux (①Import ②Review ③Merge ④Design ⑤Export + Edit catalogue) avec numéros d'étape en cercles, bandeau description dynamique, nom "Office Layout Matching" dans le header (D-68)
- **Catalogue** : 3 sous-onglets Card view / Grid view / Pattern editor (remplace le toggle Cards/Grid)
- **Merge placeholder** : onglet ③ avec message "coming soon"
- **Desk dynamique** : desk width/depth, door width, grid cell size depuis Settings propagés en temps réel au rendu SVG et aux blocs serveur
- TODO enrichi : R-08, R-09 (Identify merges), R-10 (splash screen), audit rotation patterns, test floor plan

### Corrigé
- Pan (Shift+drag) : pointeur décalé ~50px → pxToSvg compense le letter-boxing preserveAspectRatio
- Review rooms : navigation clavier flèches restaurée
- Zoom buttons : event object passé comme SVG element → wrappé dans closure
- Convention desk : DESK_W=180 (largeur), DESK_D=80 (profondeur) — perspective humaine (D-69)

### Modifié
- 14 fichiers modifiés, +350/-169 lignes
- Tous les sélecteurs programmatiques migrés (floorPlan→design, officeLayout→catalogue, etc.)
- Gardes canvas/clavier inversées : autorisent uniquement Catalogue > Editor
- setCatalogueView/catalogueViewMode supprimés

---

## [Unreleased] — Refactoring frontend : découplage des vues (2026-04-04)

### Modifié
- CSS externalisé : pattern_editor.html inline `<style>` → olm/static/style.css (787 lignes)
- JS découpé en modules : catalogue.js (795 l.), shared.js (628 l.), config.js (211 l.), floor_plan.js (719 l.)
- 3 canvas SVG séparés : #canvas (éditeur), #fpCanvas (matching), #rvCanvas (review) — plus de déplacement DOM
- render(), zoomFit(), updateViewBox(), zoomIn(), zoomOut() paramétrés avec targetSvg optionnel
- Classe section-title unifiée (fp-sidebar-title supprimé), styles inline nettoyés, hr.sep supprimés
- Titres Review : "Review rooms" (pluriel), nom de pièce centré dans la nav bar
- Boutons Adjust room : Apply avant Syntax help, Save room/Cancel dans la nav bar avec liseré ambre
- Annulation automatique du mode amend quand on navigue hors de l'éditeur
- JS entièrement externalisé : editor.js (1562 l.), init.js (501 l.) — pattern_editor.html réduit de 5719 à 483 lignes, zéro script inline

### Supprimé
- moveCanvasToFloorPlan(), moveCanvasToReview(), moveCanvasToEditor(), updateCanvasLocation(), getActiveSubtab()
- _canvasInEditor guard, hr.sep (HTML + CSS), fp-sidebar-title (CSS), canvasDims (masqué)

### Corrigé
- updateViewBox() ne propageait pas le SVG cible dans _renderImpl → viewBox appliqué sur le mauvais canvas
- rvUpdateRoomInfo non exporté sur window → erreur "not defined" après extraction IIFE
- preserveAspectRatio="none" sur matrixSvg → patterns déformés en vue grille (corrigé en xMidYMid meet)

---

## [Unreleased] — Amend workflow, overlay, settings, exclusions périphériques (2026-04-03)

### Ajouté
- **Amend layout** : édition de solution en place pour une pièce, sauvegarde locale, Discard amendment (D-63)
- **Adjust room** : édition géométrie de pièce, re-matching automatique, pièces amendées marquées "(amended)" (D-63)
- **Overlay raster** : chargement image plan d'étage dans Floor Plan / Input, affichage en filigrane avec checkbox + opacité, actif par défaut en mode Adjust room (D-64)
- **Settings** : onglet Office Layout / Settings — paramètres d'espacement éditables par standard, persistés en JSON, prise en compte immédiate dans le rendu (D-65)
- **Exclusions périphériques** : une exclusion couvrant tout un côté réduit les dimensions effectives pour le matching (D-62)
- `specs/VISION_LLM_IO_SPEC.md` : spécification entrées/sorties pour le LLM Vision d'ingestion des plans (D-66)
- `generate_test_floor_plan.py` + `test_floor_plan.png` : raster de test 7 pièces alignées
- Aide DSL : tooltip hover avec exemple annoté ligne par ligne
- Zones de recul/circulation visibles en mode circulation (plus masquées)
- Auto-chargement `test_rooms.json` + `test_floor_plan.png` au démarrage (dev)
- Route `/specs/<filename>` et `/test_floor_plan.png` dans Flask

### Modifié
- Navigation : 2 onglets principaux (Floor Plan / Office Layout) + sous-onglets, onglet actif en fond accent (D-61)
- Interface traduite en anglais
- Boutons Floor Plan : Adjust room | Edit pattern, Amend layout, Discard amendment
- Boutons éditeur réordonnés : New, Load, Save, Duplicate, Delete + Cancel (mode amend)
- Nom du pattern centré au-dessus du canvas dans la colonne éditeur
- Liste Load triée comme le catalogue (depth asc, width asc, name)
- Sélection candidat : liseré ambre inset (compatible avec liseré vert "best")
- Load file à gauche dans Floor Plan / Input
- `spacing_config.py` : configs mutables, persistence `spacing_overrides.json`, `update_config()`, `reset_config()`
- `catalogue_matcher.py` : `effective_dimensions()` pour exclusions périphériques
- Suppression des fallbacks hardcodés (|| 90, || 140, || 160) dans le JS — tout via `CURRENT_SPACING`
- Deep copy des candidats dans `fpRenderSvg` et `switchToEditorWithPattern` (évite mutation par référence)

---

## [Unreleased] — Pipeline matching, éditeur, floor plan (2026-04-01)

### Ajouté
- `catalogue_matcher.py` : pipeline matching 7 étapes (D-54) — sélection Pareto, miroir E-O, calage sticks + homothétie, suppression unitaire postes, scoring circulation, sélection meilleur, rectangle résiduel
- `coverage_analysis.py` : analyse de couverture catalogue × pièces (COVERED/NO_FIT/LOW_DENSITY/LOW_SCORE), backlog d'enrichissement (D-51)
- `specs/CATALOGUE_STRATEGY.md` : stratégie peuplement catalogue du bas vers le haut (D-55)
- Convention de nommage automatique des patterns D-50 : `{W}x{D}_{STD}[_{k}O]_{n}` avec compactage
- Import/export catalogue JSON (D-53) : endpoints API + boutons interface
- Onglet Floor Plan dans `pattern_editor.html` : navigation prev/next, matching, candidats, export résultats, bouton Editer → éditeur
- Multi-portes : clustering cellules DOOR, BFS par cluster, meilleur chemin par poste
- Accès par poste individuel pour blocs ortho (BLOCK_2_ORTHO_R/L) dans la circulation
- DSL pattern v1.3 : gap initial autorisé, blocs ORTHO dans la grammaire
- Endpoint `/api/floor-plan/match` : matching catalogue × pièces avec positions desks
- Endpoint `/api/coverage` : analyse de couverture + backlog
- Endpoint `/api/catalogue/export` et `/api/catalogue/import`
- `test_rooms.json` : jeu de 7 pièces de test (250×350 à 1400×950)
- Decisions D-50 à D-55

### Modifié
- `pattern_server.py` : nommage auto au save, compactage après suppression, APIs import/export/coverage/floor-plan
- `pattern_editor.html` : 3 onglets (Catalogue/Éditeur/Floor Plan), boutons import/export
- `pattern_dsl.py` : gap avant premier bloc accepté (distance mur ouest)
- `PATTERN_DSL_SPEC.md` v1.3 : blocs ORTHO_R/L, gap initial, exemples enrichis
- `circulation_analysis.py` : accès ortho par poste, multi-portes via clustering
- `static_matcher.py` : BLOCK_2_ORTHO_R/L ajoutés dans `_BLOCKS`
- `catalogue/patterns.json` : noms migrés vers convention D-50
- `adapt_to_room()` : remplace la géométrie pièce par celle de la pièce cible
- `docs/SDS.md` : réécriture complète v3.0

---

## [Unreleased] — Audit documentation + nouveau workflow (2026-03-28)

### Ajouté
- D-26 : changement de repère NW→SE (origine Nord-Ouest, y→Sud)
- Workflow dual-instance ARCHITECT (Opus/VSCode) + IMPLEMENTER (Sonnet/terminal)
- `CLAUDE_IMPLEMENTER.md` : instructions de rôle pour l'instance terminal
- `solver_lab/TODO.md` : tâches + idées du week-end (vocabulaire, fonctions de base, standards)

### Modifié
- `CLAUDE.md` : section dual-instance, fichiers de référence solver_lab, règle Decisions.md auto, format prompts IMPLEMENTER
- `solver_lab/Decisions.md` : D-05 corrigée (dimensions post-D-25), D-11/D-12 marquées supersédées, D-18 marquée supprimée, D-21→D-25 format normalisé, D-25 mis à jour repère NW, D-26 ajoutée
- `solver_lab/specs/BLOCS_SPEC.md` : réécriture complète alignée D-25/D-26
- `solver_lab/specs/CONSTRAINTS.md` : §Stratégie mis à jour pour pipeline catalogue D-14
- `docs/SDS.md` : réécriture complète v2.0 (architecture actuelle, repère D-26)
- `solver_lab/solver/model.py` : commentaire y_m aligné D-26

### Supprimé
- `docs/BROWSER_CONTEXT.md` : obsolète (accès fichiers direct dans VSCode)
- `solver_lab/specs/BROWSER_CONTEXT.md` : idem, contenu migré dans TODO.md
- `AGENT.md` : fusionné dans CLAUDE.md

### Connu
- 10 tests en échec sur 501 (debt_model, matcher) — à diagnostiquer en session de travail

---

## [Unreleased] — solver_lab : refonte placement simultané postes + corridors (2026-03-17)

### Ajouté
- `CellType.CORRIDOR = 4` dans `model.py`
- `CorridorSpec` dataclass dans `model.py`
- `SolverParams.corridor_min_length_m` (défaut 1,50 m) et `corridor_min_width_m` (défaut 0,80 m)
- `ScoringWeights.distance_to_door` (défaut 30) — poids du hint pré-résolution
- `PlacementResult.corridors` : liste `[(x_m, y_m, w_m, d_m)]` des corridors placés
- `BlockShape.is_corridor` : flag pour distinguer postes et corridors
- `_build_corridor_catalogue(params)` : 12 blocs corridor (6 longueurs × 2 orientations)
- C-1 non-chevauchement global postes ∪ corridors dans `solve()`
- C-2 accessibilité côté chaise : chaque poste actif adjacent à au moins un corridor actif
- C-3 connexité corridors via flux CP-SAT : `f_ij ∈ [0, N]` + `door_source_j` pour corridors porte-adjacents
- Objectif : `nb_postes × 1000 − hint_distance_porte` (hint euclidien, max ≈ 220 ≪ 1 000)
- Métriques `nb_corridors` et `avg_distance_to_door_m` (BFS sur FREE + CORRIDOR post-résolution)
- Rendu corridor en bleu dans le SVG HTML et en `'-'` dans le plan ASCII
- Décision D-13 dans `solver_lab/Decisions.md`

### Modifié
- `build_grid()` : signature étendue pour recevoir candidats postes + corridors séparément ; marque CORRIDOR avant FOOTPRINT
- `solve()` : résolution unique (plus de boucle de coupes), budget temps partagé pour la résolution unique
- `run.py` : affichage des nouvelles métriques, chargement des nouveaux paramètres depuis JSON scénario

### Supprimé
- Boucle de coupes de connectivité (D-12) : remplacée par C-3 flux CP-SAT (D-13)
- `_find_connectivity_cuts()` supprimée de `cpsat_solver.py`

---

## [Unreleased] — Phase 0 : Setup

### Ajouté
- Structure complète du projet
- `CLAUDE.md` — contexte projet, workflow, conventions de code
- `docs/PROJECT_CHARTER.md` — vision, périmètre, jalons
- `docs/SRS.md` — exigences fonctionnelles et non-fonctionnelles (EF-01 à EF-09)
- `docs/SDS.md` — architecture en modules, structures de données, interfaces
- `docs/TEST_PLAN.md` — stratégie de test, 30+ cas de test, fixtures attendues
- `pyproject.toml` — dépendances (Pillow, ReportLab, pytest)
- `.gitignore` — cache OLO, Python, IDE
- Arborescence `src/olo/` avec sous-packages (models, ingestion, geometry, placement, rendering)
- Arborescence `tests/fixtures/` (plans, json, expected_outputs)

---

<!-- Template pour les prochaines phases :

## [0.x.0] — Phase N — Nom
### Ajouté
- ...
### Modifié
- ...
### Testé
- `tests/test_xxx.py` : couverture XX %

-->
