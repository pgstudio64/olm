# Decisions.md — OLM

Journal des décisions de conception du projet OLM (Office Layout Matching).
Chaque entrée indique la date, la décision, la justification et l'impact.

> **Note** : Décisions historiques (D-01 à D-60, architectures antérieures CP-SAT et refactoring) archivées dans `Decisions_archive.md`.

---

## D-124 · Re-ancrage des zones canoniques après re-analyze (2026-04-21)

### Décision

Après un `re-analyze` (unitaire ou batch), les zones `exclusion_zones` /
`transparent_zones` sont re-projetées pour préserver leur **position absolue
dans l'image du plan**, au lieu de rester figées en room-local cm (qui dérive
dès que le bbox détecté change).

Le pipeline géométrique :
```
canon (old) → abs-room-local (old) → abs-image-cm → abs-room-local (new) → canon (new)
```

Trois composants :
1. `canonicalIO.rotateRectInv(rect, cfAbs, absW, absD)` — inverse exact de
   `rotateRect`, exposé publiquement comme 3e primitive de rotation. Satisfait
   `rotateRectInv(rotateRect(r, cf, W, D), cf, W, D) ≡ r` (4 auto-tests
   round-trip).
2. `window.reanchorCanonicalZones(zones, oldBbox, oldCf, newBbox, newCf, scale)`
   — helper partagé dans `olm/static/ingestion.js`, source unique de la
   conversion.
3. Appelé depuis `init_rvtool.js` (re-analyze unitaire) et `ingestion.js`
   (re-analyze batch), propagé à `state.room_exclusions/transparents`,
   `r.exclusion_zones/transparent_zones`, `am.*` et `fpData.rooms[i].*`.

### Justification

Symptôme utilisateur (D-108+ itérations) : « après un re-analyze, la zone se
déplace ». Root cause : zones stockées en canonique **room-local**, donc
ancrées au coin NW canonique. Quand re-analyze décale le bbox de N px
(typiquement ±3-5 px), le NW canonique se déplace dans l'image tandis que le
overlay raster se repositionne dessus — les zones qui couvraient un escalier
sur le plan se retrouvent à côté.

Solution adoptée : préserver la sémantique « la zone couvre CE feature du
plan » en reprojetant automatiquement lors des mutations de bbox / corridor_face.
Le cas bbox-inchangé + cf-inchangé est l'identité (dx=dy=0, rotation identité),
sans overhead détectable.

### Impact

- **Fichiers modifiés** : 3 JS (+74 lignes net).
  - `olm/static/canonical_io.js` : +28 lignes (rotateRectInv + 4 tests).
  - `olm/static/ingestion.js` : +60 lignes (helper + wiring batch).
  - `olm/static/init_rvtool.js` : +11 lignes (wiring unitaire).
- **Rétrocompatibilité** : JSON v3 sur disque inchangé. Les zones déjà stockées
  (non reanchorées) restent valides pour leur contexte d'origine.
- **Tests** : 12 → 16 auto-tests `canonical_io.js`, tous verts. Flask import OK.
  Python 132/139 (7 failures pré-existantes hors scope).
- **Hors scope** :
  - Symptôme 1 (zone se place décalée nord au clic) : non reproduit sur code,
    instrumentation browser requise.
  - Bug latent `transparent_zones` envoyées au backend en canonique au lieu
    d'abs pour les pièces non-south (mask mal positionné pendant la détection).
    Ne se manifeste pas sur pièces south testées ; à corriger séparément.

---

## D-123 · Perf Re-analyze All + fix bug has_door POST matching (2026-04-20)

### Fix bug — openings transformées en portes à la sauvegarde JSON

**Symptôme** : l'utilisateur modifie des ouvertures dans Room amend,
sauvegarde sur disque, ferme/rouvre le projet → les ouvertures sont
apparues comme de **grandes portes** dans la pièce.

**Cause** : après les changements P4 (séparation openings/doors en
state) et P5 (envoi canonique au matching), `fpLoadAndMatch` envoyait
les openings canoniques au `/api/floor-plan/match` **sans** champ
`has_door`. Or le backend (`app.py:1415`) construit
`OpeningSpec(..., has_door=o.get("has_door", True), ...)` — valeur
**défaut True**. Tous les openings étaient donc interprétés comme des
portes par le matcher ; la réponse contenait `has_door=true` partout.

Le split post-réponse de `fpLoadAndMatch` (introduit en P5) poussait
alors tout vers `r.doors` : `fpData.rooms[i].openings = []`,
`.doors = [toutes les ouvertures]`. À l'entrée en Room amend, le
state se retrouvait avec `state.room_doors = toutes les ouvertures`.
Au Save amendment, `ingState.rooms[i]` était écrasé, puis la
sauvegarde disque sérialisait les ouvertures dans la clé `doors` du
JSON v3. Au reload, doors arrivaient comme portes avec leurs
dimensions originales, souvent larges (d'où « grandes portes »).

**Fix** : `fpLoadAndMatch` pose désormais `has_door=false` explicite
sur les openings et `has_door=true` sur les doors avant le POST, puis
supprime `doors` du payload. Aligne avec
`serializeForMatching` et `editor.js:save()` (déjà corrects). 1 seul
fichier modifié (`floor_plan.js:78`).

**Impact** : sauvegarde/rechargement fonctionnels. Les pièces non-south
amendées ne corrompent plus l'état au retour de matching.

### Perf Re-analyze All — binarisation partagée (×9.8)

**Décision** : `/api/room/reanalyze_batch` calcule la binarisation
globale + `remove_non_ortho` une seule fois par batch, puis les
partage à toutes les pièces via le nouveau paramètre
`binary_precomputed` de `extract_room_features`. Les masques
room-locaux (portes + zones transparentes) sont appliqués en zéro-out
numpy sur une copie de la base partagée.

**Justification** : `remove_non_ortho` (cv2.connectedComponents sur
image 1920×1080) dominait le coût de chaque pièce (~830 ms sur M4,
extrapolé ~8 s sur cible). Appelé 28 fois → ~230 s pour un
Re-analyze All. La binarisation et le cleanup sont identiques pour
toutes les pièces (même image source) — les seules différences sont
les masques locaux (petites zones).

**Bench mesuré** (MacBook M4, `test_floorplan_preprocessed-SD.png`,
1920×1080, 10 pièces) :
- Classic : 831 ms/pièce × 10 = 8 317 ms
- Batch : 831 ms précompute + 15 ms/pièce × 10 = 846 ms
- **Speedup ×9.83**. Extrapolation 28 pièces : 23 s → 1.3 s sur M4,
  ~230 s → ~13 s sur cible (CPU 10× plus lent).

**Changements** :
- `olm/ingestion/extract.py:extract_room_features` : nouveau param
  optionnel `binary_precomputed`. Si fourni, saute la binarisation +
  `remove_non_ortho` ; les masques sont appliqués par zéro-out numpy
  sur une copie room-local de la base.
- Refactor interne : les rectangles de masque (doors + transparent
  zones) sont d'abord collectés en liste, puis appliqués soit via PIL
  (pipeline classique), soit via numpy slicing (pipeline batch).
- `olm/server/app.py:/api/room/reanalyze_batch` : précalcule
  `_binary_global` avant la boucle, passe `binary_precomputed` à
  chaque appel `extract_room_features`.
- Rétrocompat : signature par défaut `binary_precomputed=None` →
  comportement identique (utilisé par `/api/room/reanalyze` unitaire,
  non touché).

**Equivalence fonctionnelle vérifiée** : smoke test (plan synthétique
+ plan réel) produit un `bbox_px` identique entre les deux chemins,
nombres d'ouvertures / portes identiques.

**Caveat** : cas-limite théorique — un composant non-orthogonal
partiellement recouvert par un masque serait traité différemment
entre les deux chemins. Dans le pipeline classique, le masque coupe
le composant avant `remove_non_ortho` et le reste peut devenir
orthogonal. Dans le pipeline batch, le composant a déjà été retiré
globalement. Diff négligeable sur des plans réels (masques petits =
door width, non-orthos = arcs de porte toujours retirés dans les
deux cas).

---

## D-122 · R-14 P1→P7 — canonicalIO consolidé complet (2026-04-20)

Refactor R-14 complet : 7 phases livrées dans la foulée. Spec de
synthèse : `docs/specs/CANONICAL_STATE.md`. Tests auto 12/12 OK.
Validation visuelle / fonctionnelle en browser recommandée avant
commit final.

### P7 — Spec CANONICAL_STATE.md + tests

**Décision** : `docs/specs/CANONICAL_STATE.md` (nouveau) devient la
spec de référence du repère canonique. `CANONICAL_STATE_REFACTOR.md`
(R-12, D-117) reste en archive. La spec documente la structure d'une
pièce canonique, les 4 frontières I/O, l'API `canonicalIO` et
6 antipatterns interdits.

**Tests** : 12 auto-tests dans `canonical_io.js` (4 round-trips × 4
faces + 8 rotations × 4 faces). Exécutables depuis console browser
ou Node (snippet dans la spec §4). Tests Python canonique
(`test_canonical.py`) 19/19 également verts (backend module qui
reste dead code après P5, conservé comme référence).

### P5 — Frontend envoie canonique au matching

**Décision** : `/api/floor-plan/match` reçoit désormais des pièces en
repère CANONIQUE (corridor_face = "south", width_cm/depth_cm post-swap
pour east/west, faces d'openings rotées). Le `toStorage` préalable
dans `serializeForMatching` et `editor.js:save()` est supprimé. Le
backend matcher, qui supposait déjà canonique par convention interne,
voit enfin une entrée cohérente.

**Justification** : avant P5, le frontend envoyait de l'absolu
(via `_toAbsRooms` / `toStorage`) à un matcher qui raisonne canonique.
Les scores étaient corrects **par accident pour les pièces south
uniquement** — les autres avaient des swaps W↔D incohérents et des
faces d'openings qui ne correspondaient pas au catalogue. Symptôme
typique : « No matching patterns » ou candidats faussement positifs
pour les pièces non-south (D-121 diagnostic).

**Changements** :
- `ingestion_serialize.js` : ajout `_canonRooms()` (retourne
  `ingState.rooms` tel quel) ; `serializeForMatching` l'utilise à la
  place de `_toAbsRooms()`. `_toAbsRooms()` reste pour
  `serializeForStorage` (JSON v3 disque = absolu, inchangé).
- `editor.js:save()` : `amendedRoom` construit depuis `canonRoom`
  directement (combinaison openings+doors pour le contrat API qui
  reste avec `has_door`). Plus de `toStorage` préalable.
- `floor_plan.js:fpLoadAndMatch` : sur la réponse, si le backend
  renvoie openings combinés avec `has_door`, split en `r.openings` +
  `r.doors` pour rester cohérent avec l'invariant P4.
- `floor_plan.js:fpRematchRoom` : idem, split de `newRoom.openings`
  avant injection dans `fpData.rooms[i]`.
- `app.py:/api/floor-plan/match` docstring : contrat canonique
  explicité. Aucune canonicalisation backend ajoutée (redondant si
  frontend respecte le contrat).

**Impact** :
- Matching désormais correct pour toutes les orientations de pièce,
  pas seulement south.
- Le champ `corridor_face_abs` est inclus dans le payload pour
  traçabilité ; ignoré par le backend (champ excédentaire autorisé
  sur les dicts Python).
- JSON v3 sur disque reste en repère absolu (séparation claire des
  deux canaux).

### P4 — Séparation openings/doors uniforme dans le state

**Décision** : `state.room_doors` introduit comme collection parallèle
à `state.room_openings`. `has_door:true` banni du state — toutes les
portes vivent exclusivement dans `state.room_doors`. Même invariant
appliqué à `ingState.rooms[i]`, `fpData.rooms[i]`, `fpRoomAmendments`
(déjà acquis post-fromStorage), `amendments[name]` (pour les
préservations au re-analyze batch).

**Justification** : le combine+split aux frontières
(`enterRoomAmendMode` / `save()` / batch re-analyze) était la source
des bugs doors invisibles (pièces 906, 915). Une structure uniforme
élimine les points de conversion oubliables. Le backend (DSL parse,
catalogue sur disque, matching API) conserve la forme combinée via
`has_door` — P5 pourra unifier la couche transport.

**Changements** :
- `editor.js` : `state.room_doors: []` dans les defaults +
  `_splitOpeningsIntoState` helper (split combinée→séparée), utilisé
  par `loadPattern` / `loadPatternFromData` / `applyRoomDSL`.
- `editor.js:buildRoomDSL` itère `state.room_doors` séparément.
- `editor.js:renderRoomElements` : 2 boucles distinctes (openings,
  doors). Handles emit `type="door"` en plus de window/opening.
- `editor.js:buildPatternPayload` : concatène doors dans
  `room_openings` (avec `has_door:true`) pour l'API catalogue
  (format fichier patterns inchangé).
- `editor.js:save()` : `canonRoom.doors = state.room_doors` directement,
  plus de filter.
- `editor.js:enterRoomAmendMode` / `floor_plan.js:enterRoomAmendMode`
  / `fpRenderEmptyRoom` / load pattern : openings + doors séparés.
- `init_rvtool.js:clampFeature` sur les 3 collections ;
  `_stateToDsl` 2 boucles ; re-analyze lit/écrit `manualO` +
  `preservedDoors` depuis `state.room_doors` sans filter ; CRUD
  (push door, delete, resize, move) cible la bonne collection via
  `type === "door"`.
- `init_rvtool.js:roomResizeStart` snapshot inclut `doors`, le résize
  recalcule leurs offsets aussi.
- `ingestion.js:computeCanonicalReanalyzeResult` : `feat()` ne tagge
  plus `has_door` — sortie déjà séparée. Batch re-analyze utilise
  `prevOp`/`prevDr`, écrit directement dans `r.openings` / `r.doors`
  + `am.openings` / `am.doors` (plus de re-split à la fin).
- `shared.js` doorCells itère `state.room_doors`.
- `init.js` default room + snapshot save/restore incluent `room_doors`.

**Conservé (frontières API) avec `has_door`** :
- `ingestion_serialize.js:serializeForMatching` (payload POST pour
  `/api/floor-plan/match` — P5 pourra unifier).
- `catalogue.js:260` (format fichier patterns sur disque).
- `editor.js:buildPatternPayload` (catalogue save API).

### P6 — Helpers publics de rotation + suppression conversions ad-hoc

**Décision** : `canonicalIO` expose désormais `rotatePoint` / `rotateRect`
pour couvrir la rotation abs → canon des points et rectangles
room-local (coords cm relatives au bbox), qui ne sont pas couverts par
`fromStorage` / `toStorage` (ces derniers opèrent sur offset_cm de face).
`pointAbsToCanon` (ingestion.js:79) et `_absToCanon2` (editor.js:1910)
sont supprimés, remplacés par des appels directs aux helpers publics.

**Justification** : les conversions locales dupliquaient la matrice de
rotation — risque identique au bug fix de P3 (« corridor fallback »
masquait le repère absolu) mais silencieux : une divergence de la
matrice passerait inaperçue. Une seule implémentation.

**Changements** :
- `canonical_io.js` : ajout `rotatePoint(pt, cfAbs, absW, absD)` et
  `rotateRect(rect, cfAbs, absW, absD)`. 8 assertions auto-test
  couvrent les 4 faces × 2 helpers.
- `ingestion.js` `computeCanonicalReanalyzeResult` : rotation hits /
  seed / auto_door_masks via les helpers publics (suppression
  `pointAbsToCanon` + bloc rect inline).
- `editor.js` chargement state hits / seed : rotation via helper
  public (suppression `_absToCanon2`).
- `_canonicalAngle` local (editor.js) non migré pour l'instant — la
  convention d'angle CSS du rendu SVG diverge ; migration différée
  pour cohérence avec un test visuel.

### P3 — Renommage corridor_face_abs + retrait lecture ambiguë

**Décision** : rename global `original_corridor_face` → `corridor_face_abs`
dans tout le front + endpoint `/api/room/orientation-check`. Suppression
de la lecture ambiguë `room.original_corridor_face || room.corridor_face`
qui masquait le vrai repère absolu derrière le `"south"` canonique
constant.

**Justification** : `room.corridor_face` canonique vaut toujours
`"south"` post-`fromStorage` ; l'utiliser comme fallback faisait
silencieusement passer des rooms non-south pour des rooms south dans
plusieurs chemins (rotation hits/seed dans `enterRoomAmendMode`,
détection de repère au batch re-analyze). Le rename force un nom non
ambigu (`_abs` = « absolu »).

**Changements** :
- 6 fichiers JS renommés : `canonical_io.js`, `ingestion_serialize.js`,
  `floor_plan.js`, `ingestion.js`, `editor.js`, `init_rvtool.js`.
- 4 lectures ambiguës supprimées (editor.js `_canonicalAngle`,
  `_absToCanon2`, `save()`, init_rvtool.js re-analyze).
- `state.corridor_face` retiré (n'avait plus de lecteur).
- API `/api/room/orientation-check` : champ `original_corridor_face` →
  `corridor_face_abs` (request + response). Seul client = le front.
- JSON v3 sur disque conservé inchangé (`corridor_face` = absolu).
- Tests round-trip 4/4 OK.

### P2 — Fusion bbox_abs_px / seed_abs_px

**Décision** : suppression des champs `bbox_abs_px` / `seed_abs_px`.
`bbox_px` / `seed_px` portent désormais seuls les coords image absolues
(jamais rotés, image inchangée par la rotation canonique).

**Justification** : duplication sans valeur ajoutée. `canonical_io.js`
créait `bbox_abs_px` = copie de `bbox_px`, puis `toStorage` les
fusionnait (fallback). Risque de désynchronisation avéré en session
précédente (fix pièce 922 : `bbox_abs_px` stale écrasait `bbox_px` à
jour après re-analyze).

**Changements** :
- `canonical_io.js`: `fromStorage` ne crée plus `bbox_abs_px` /
  `seed_abs_px` ; `toStorage` lit `bbox_px` / `seed_px` directement.
- `ingestion.js` batch re-analyze : `r.bbox_abs_px` supprimé.
- `floor_plan.js` `fpLoadAndMatch` : preserve bbox_px / seed_px.
- `editor.js` save : écrit `bbox_px` / `seed_px` uniquement.
- `init_rvtool.js` orientation-check : fallback bbox_abs_px retiré.
- Tests round-trip 4/4 OK.

### P1 — Rotation offset_px intégrée à canonicalIO (2026-04-20)

**Décision** : `canonicalIO.fromStorage(room, scale)` et
`canonicalIO.toStorage(room, scale)` acceptent désormais le paramètre
`scale` (cm/px) et recalculent `offset_px` / `width_px` depuis
`offset_cm × pxPerCm` en interne, en cohérence avec la rotation
`offset_cm` qu'elles appliquent déjà. Plus besoin de recalcul ad-hoc
à la sérialisation ou au rendu.

**Justification** : phase P1 du plan R-14 (D-121). Suppression d'une
source de bugs récurrents : `toStorage` ne rotait pas les px, imposant
un recalcul manuel dans 2 sites (`ingestion_serialize.js:_pxFromCm`
et `ingestion.js:_renderFeat` / `_renderPxPerCm`). Un oubli aurait
silencieusement décalé les features du rendu Floor.

**Changements** :
- `olm/static/canonical_io.js` : helper `_syncPx`, signature étendue
  des deux fonctions, tests round-trip enrichis avec `offset_px` /
  `width_px` (4/4 OK via Node).
- `olm/static/ingestion_serialize.js` : `_toAbsRooms()` passe `scale`
  à `toStorage` ; `serializeForStorage` lit `r.offset_px` /
  `r.width_px` directement (fini `_pxFromCm`).
- `olm/static/ingestion.js` : `_renderRoom` supprime `_renderFeat` et
  `_renderPxPerCm`, délègue entièrement à `toStorage(room, scale)`.
- `olm/static/ingestion.js` : `computeCanonicalReanalyzeResult` passe
  `scale` à `fromStorage`.
- `olm/static/ingestion.js` : import préprocessé passe
  `data.scale_cm_per_px` à `fromStorage`.
- `olm/static/floor_plan.js` : `fpLoadAndMatch` passe
  `ingState.scale` à `fromStorage`.
- `olm/static/editor.js` : save Room amend passe `ingState.scale` à
  `toStorage`.

**Impact** :
- Une seule formule `offset_px = round(offset_cm × pxPerCm)` dans le
  front, colocalisée avec la rotation `offset_cm`.
- Signature rétrocompat : `scale` omis → px laissés intacts (les
  tests fragments sans scale continuent de passer).
- Pas de changement du format JSON v3 sur disque.
- `editor.js:_enrichCanon` reste (maintenance canonique du state,
  pas un abs↔canon) — à revoir en P4 / P6.

---

## D-121 · Plan de refactor canonique unifié — R-14 (2026-04-20)

**Décision** : après 4 sessions successives de fixes sur le repère canonique
(D-117, D-120, + 3 commits même journée), acter que l'architecture R-12 a
atteint sa limite de viabilité et planifier un refactor structurel en 7
phases. Spec complète dans `docs/specs/CANONICAL_REFACTOR_PLAN.md`.

**Justification** :

Symptômes récurrents liés à la même cause racine (**absence de frontière
unique et de structures uniformes**) :
- Pièce 902 door mauvais côté (Floor render canonique face ≠ absolu).
- Pièce 915 NaN flood + door→opening (séparation openings/doors cassée au
  batch re-analyze ; guards !isNaN manquants).
- Pièce 922 bbox mal dessinée (bbox_abs_px stale écrase bbox_px à jour
  dans toStorage).
- Pièce 906 door invisible DSL/visu Review (state.room_openings non
  combiné avec doors séparées à l'entrée amend).
- Pièce 906 180° flip post-Save (fpRoomAmendments stockait absolu
  alors que consumers attendent canonique).
- Contrat /api/floor-plan/match faussé silencieusement (front envoie
  absolu, backend matcher suppose canonique, résultats corrects par
  accident seulement pour pièces south).

**Causes identifiées** :
1. Conversions éparpillées : 8-12 sites font leur propre rotation
   ad-hoc (pointAbsToCanon, _absToCanon2, _canonicalAngle, _pxFromCm,
   FACE_MAPS locales dupliquées).
2. Champs redondants désynchronisables : `bbox_px`/`bbox_abs_px`,
   `seed_px`/`seed_abs_px`, `corridor_face`/`original_corridor_face`.
3. Structures non uniformes : `state.room_openings` combine les doors
   via `has_door:true`, alors que `ingState.rooms[i].openings` et
   `.doors` sont séparés. Re-combine / re-split à chaque frontière,
   avec oublis systémiques.
4. `toStorage` ne rote pas `offset_px` — recalcul ad-hoc à la
   sérialisation, oubli possible dans d'autres chemins.
5. Contrat front/back implicite et non documenté.

**Plan R-14** (7 phases) :
- P1 Rotation `offset_px` intégrée à canonicalIO (supprime ad-hoc).
- P2 Fusion `bbox_abs_px` / `seed_abs_px` (suppression redondance).
- P3 Renommage `original_corridor_face` → `corridor_face_abs`, retrait
  du `corridor_face` canonique stocké (dérivable).
- P4 Séparation openings/doors uniforme dans `state.room_*`
  (introduction `state.room_doors`, fini `has_door:true` dans state).
- P5 Contrat front/back : /api/floor-plan/match canonicalise via
  `canonical.py` backend (actuellement orphelin).
- P6 Suppression des conversions ad-hoc.
- P7 Tests round-trip étendus + spec CANONICAL_STATE.md.

**Impact** :
- ~6 jours de travail concentré, découpé en commits isolés et testables.
- Disparition par construction des 6 symptômes actuels + leakage latents.
- Simplification : une seule forme canonique partout, une seule frontière.

**Points ouverts à arbitrer** (avant exécution) :
- Backend `/api/room/reanalyze` reste en absolu (pragmatique, travaille
  sur coords image).
- JSON v3 sur disque reste en absolu (évite migration). Seul le
  renommage `original_corridor_face` → `corridor_face_abs` impacte.
- `scale` toujours disponible aux call sites canonicalIO (confirmé).

---

## D-120 · Consolidation R-12 C1 → C4 : canonical_io source unique (2026-04-20)

**Décision** : finaliser le refactor R-12 (D-117) en éliminant toute la
duplication de la rotation abs ↔ canon et le round-trip inutile du
matching. `canonical_io.js` devient la seule source pour les matrices de
rotation ; le textarea `fpRoomsJson` perd son rôle de pivot d'échange.

**C1** · suppression du code mort `_canonicalizeRoom` / `_decanonicalizeRoom`
+ matrices `_FACE_MAPS` / `_INV_FACE_MAPS` de `floor_plan.js`. L'unique
consommateur restant (`editor.js:save()` en Room amend) bascule sur
`canonicalIO.toStorage`. Correction du bug latent sur `origCf` : après
R-12, `ramend.originalRoom.corridor_face === "south"` (canon), il faut
lire `original_corridor_face` en priorité — sans quoi toutes les
rotations de save étaient annulées pour les pièces non-south. La
propagation vers `ingRooms` / `fpData` est rendue cohérente avec
l'invariant canonique (dims canoniques, `corridor_face:"south"`,
`bbox_abs_px` mis à jour — plus d'écrasement en repère absolu qui
provoquait une double rotation à l'export).

**C2** · réécriture de `computeCanonicalReanalyzeResult` en wrapper
mince autour de `canonicalIO.fromStorage`. La matrice `FACE_MAPS`
locale et la fonction `toCanonFeat` (doublons de la frontière canonique)
disparaissent. Seul le post-traitement des points / rectangles relatifs
au bbox (`hits`, `seed_cm`, `auto_door_masks`) reste local car hors
scope de `fromStorage`. Bug prevCf éliminé par construction : un seul
chemin de canonicalisation.

**C3** · fusion des deux sérialiseurs de pièces dans un module unique
`ingestion_serialize.js` (renommé depuis `ingestion_export.js`). Nouvelle
API : `window.olmSerialize.{serializeForMatching, serializeForStorage}`
retourne la structure pure ; `populateRoomsJson` et `devExportV3Json`
deviennent de minces wrappers UI. La ligne `toStorage(r)` n'apparaît
plus qu'à un seul endroit (`_toAbsRooms()`).

**C4** · bimode `fpLoadAndMatch(arg)` : accepte un `Array` de pièces
(appel interne depuis `ingState.rooms`) ou une string JSON (legacy :
file upload, reload button, auto-dev). Pour le path Array, la
canonicalisation est idempotente — appliquée seulement aux pièces sans
`original_corridor_face` (OCR). Les 6 call sites internes dans
`ingestion.js` passent désormais `ingState.rooms` au lieu de la valeur
du textarea. Plus de stringify / parse / fromStorage redondant dans
le chemin de matching interne.

**Justification** :

Le refactor R-12 (D-117) a posé les frontières `fromStorage` /
`toStorage` mais laissé vivre en parallèle : (1) le code mort
`_canonicalizeRoom` / `_decanonicalizeRoom` ; (2) la matrice locale
dans `computeCanonicalReanalyzeResult` ; (3) un sérialiseur dédoublé ;
(4) un round-trip textarea systématique. Chaque chemin dupliqué est
une fenêtre de divergence (bug prevCf D-116, bug origCf mis à jour en
C1). Réduire à une source unique élimine ces bugs par construction.

**Impact** :
- Suppression de ~180 lignes de code (matrices dupliquées, helpers morts).
- Fichier `ingestion_export.js` renommé en `ingestion_serialize.js`.
- Bimode `fpLoadAndMatch` : path string legacy préservé pour les appels
  externes (file upload, reload, dev auto-load).
- Le textarea `fpRoomsJson` garde un rôle informatif (debug visibility).

**Dette restante** (hors C1-C4) :
- `offset_px` / `width_px` non rotés par `toStorage` : incohérence
  offset_cm / offset_px dans l'export v3 pour les pièces non-south.
  Non-bloquant (populateRoomsJson préfère offset_cm pour le matching).
- Fusion `bbox_px` / `bbox_abs_px`, `seed_px` / `seed_abs_px` : refactor
  plus lourd des consommateurs overlay, à faire en bloc ultérieurement.
- Bug Save physique (élément fantôme intercepte les clics) : confirmé
  non-lié à C1-C4 ; à investiguer séparément.

---

## D-119 · Auto-test d'orientation canonique via couleurs sémantiques (2026-04-20)

**Décision** : introduire un test runtime qui vérifie automatiquement
l'invariant « posture humaine » du refactor R-12 en échantillonnant les
couleurs sémantiques du PNG -SD bordant le bbox absolu de chaque pièce.

Trois vérifications :
1. **Corridor au sud canon** : la bande juste au-delà de la face absolue
   correspondant au sud canon doit être majoritairement verte
   (`corridor_rgb`, défaut RGB 193,247,179).
2. **Extérieur au nord canon (si façade externe attendue)** : la bande
   au-delà de la face absolue correspondant au nord canon doit être
   majoritairement bleue (`exterior_rgb`, défaut RGB 135,206,235).
3. **Fenêtres côté bleu** : chaque fenêtre canon doit être positionnée
   sur une portion de mur bordée de bleu côté extérieur.

Chaque vérification retourne un ratio (0..1) et un verdict (ok/warn/skip)
selon des seuils configurables.

**Justification** :

Le refactor R-12 repose sur un invariant simple mais impliquant plusieurs
couches (fromStorage, rendu, rotation overlay, flux re-analyze). Une
régression dans n'importe laquelle casse la « posture humaine ». Les
bugs observés sur 903 et 922 montrent qu'un diagnostic visuel cas par
cas consomme beaucoup de temps et laisse passer des cas limites (cours
intérieures, pièces enclavées, détection corridor ambiguë).

Les couleurs sémantiques du PNG -SD sont déjà la **source de vérité**
métier : corridor = vert, extérieur = bleu. Les exploiter comme oracle
de test convertit une observation manuelle en validation automatique,
par pièce, reproductible.

**Impact** :
- Nouveau module `olm/ingestion/orientation_check.py` (fonction pure).
- Endpoint `/api/room/orientation-check` (diagnostic ponctuel).
- Extension optionnelle `/api/floor-plan/orientation-report` (batch).
- UI minimal : bouton dans Room toolbar + badge de résultat ; version
  avancée en rapport agrégé.
- Chantier R-13 (TODO.md) à créer.

Limitations connues à documenter :
- Cours intérieures peuvent border du bleu sans être la façade principale.
- Pièces enclavées (pas de façade extérieure) : check extérieur skippé.
- Pièces sans `original_corridor_face` (corridor détecté absent) : test
  non applicable.

---

## D-118 · Re-analyze uniforme + zone transparente comme primitive de modélisation (2026-04-20)

**Décision** : le re-analyze conserve un comportement unique
indépendant de l'origine de la pièce (ingestion auto, ajout manuel
Floor, fusion de pièces). Toute modification structurelle (mur à
déposer, ouverture à créer à travers un mur existant) passe par la
**zone transparente** posée sur le mur concerné — pas de cas
particulier dans l'algo re-analyze.

En complément, un **toggle « lock bbox »** (checkbox ou bouton
secondaire « Re-analyze openings only ») permet à l'utilisateur de
faire tourner le ray-cast sans adopter le nouveau bbox/dimensions
retournés. Même pipeline backend ; seule la branche finale du merge
côté frontend est conditionnelle.

**Justification** :

La tentation de traiter différemment les pièces manuelles (pas de
seed robuste → ne pas redétecter le bbox) conduit à deux algorithmes
divergents, difficiles à maintenir et à tester. La zone transparente
est une abstraction propre :

1. **Expression d'intention explicite** : poser une zone sur un mur =
   « ce mur n'existe plus pour l'analyse géométrique ». Acte de
   conception, pas de magie implicite.
2. **Réversibilité** : l'utilisateur peut activer/désactiver la zone
   pour comparer avant/après une dépose. Un cas particulier figé dans
   le code empêche cette expérimentation.
3. **Cohérence métier** : modéliser une modification structurelle =
   modéliser la modification. Le modèle reflète la réalité.
4. **Pas de bugs silencieux** : si une pièce manuelle a un seed
   problématique, un mode « ne touche pas au bbox » masque le problème
   au lieu de le révéler.

Le toggle lock bbox couvre les deux besoins légitimes (raffiner
uniquement les portes post-repositionnement manuel OU voir la
proposition de bbox unifié du ray-cast) sans scission d'algo.

**Impact** :
- Aucun changement backend (même endpoint `/api/room/reanalyze`).
- Frontend Room toolbar : ajouter un toggle à côté de « Re-analyze »
  (ex: checkbox « lock size »). Quand coché, les champs
  `state.room_width_cm / depth_cm`, `originalRoom.bbox_px / width_cm /
  depth_cm`, `state.overlay.offsetX / offsetY` ne sont pas mis à jour
  depuis `canon.bbox_px` ; seuls windows/openings/doors/hits/seed_cm
  sont adoptés.
- Tâche à ajouter dans R-04 Review (TODO.md).

---

## D-117 · Refactor repère canonique unifié — posture humaine invariante (2026-04-20)

**Décision** : refondre le state frontend pour qu'il vive dans un unique
repère canonique (`corridor_face = "south"`), avec deux frontières uniques
de rotation abs ↔ canon : une à l'entrée (chargement JSON, retour
re-analyze), une à la sortie (save, re-analyze outbound). Voir
`docs/specs/CANONICAL_STATE_REFACTOR.md` pour le plan détaillé en 3 étapes
(A introduction frontières, B retrait rotations dans consommateurs, C
rotation CSS de l'overlay plan).

**Principe directeur** : « devant chaque porte, la même posture humaine ».
Quelle que soit l'aile du bâtiment (N, E, O, S), la pièce est présentée
avec son corridor d'accès en bas. L'utilisateur se place mentalement sur
le pas de la porte, face à l'intérieur — contexte invariant pour le
raisonnement d'aménagement, quelle que soit la pièce examinée.

**Justification** : l'architecture actuelle applique les rotations à
plusieurs endroits (rendu Review, éditeur, save, re-analyze) avec des
cas particuliers multipliés (swap W/H ou pas, flip des offsets, inversion
hinge_side). La pièce 922 a révélé un désalignement structurel entre
dimensions canoniques et position overlay absolue : le rectangle dessiné
(723×204 canonique) ne recouvrait pas la pièce physique (204×723 absolu).
Les fix ponctuels empilent la complexité ; un seul pivot d'I/O élimine
toute la classe de bugs.

**Impact** :
- Introduction de `fromStorage(room)` / `toStorage(room)` remplaçant
  progressivement `_canonicalizeRoom` / `_decanonicalizeRoom`.
- State mémoire unifié : `corridor_face === "south"` partout,
  `original_corridor_face` mémorise le repère de sauvegarde.
- Overlay plan : rotation CSS de l'image de fond selon
  `original_corridor_face` (seul endroit où la rotation persiste au
  rendu).
- Fichiers impactés : `floor_plan.js`, `editor.js`, `init_rvtool.js`,
  `ingestion.js`, `ingestion_export.js`.
- Chantier R-12 (TODO.md) à créer.

---

## D-116 · Helper reanalyze partagé batch + unitaire (2026-04-20)

**Décision** : factoriser la canonicalisation abs → canon de la re-analyze
dans une fonction unique `computeCanonicalReanalyzeResult(data,
corridorFace, scale)` consommée par le re-analyze unitaire
(`init_rvtool.js`) et le batch floor (`ingestion.js`). Les deux
appliquent le même pipeline : canonicalisation des features,
mise à jour de corridor_face depuis doors[0] (D-113), adoption du
nouveau bbox, consommation des portes redétectées.

**Justification** : le batch re-analyze (`ingBtnReanalyzeAll`)
appliquait le résultat en coords absolues sans canonicalisation, avec :
- features tournées (90/180/270°) pour toute pièce non-south corridor ;
- portes détectées ignorées ;
- nouveau bbox jamais adopté ;
- corridor_face jamais mis à jour.

Les deux appelants divergeaient mécaniquement alors qu'ils ont la même
responsabilité logique. Le helper partagé élimine la divergence et
facilite les évolutions futures (le refactor canonical D-117 le
réécrira en `fromStorage`).

**Impact** :
- `olm/static/ingestion.js` : helper `computeCanonicalReanalyzeResult`
  exposé sur `window`.
- `olm/static/init_rvtool.js` : bloc re-analyze unitaire réduit (~100
  lignes → ~40) et délégué au helper.
- `olm/server/app.py` : endpoint batch accepte `door_width_cm`.

---

## D-115 · Surface cartouche vs surface bbox — pièces non-rectangulaires (2026-04-20)

**Décision** : découpler la surface issue du cartouche PDF (vérité
terrain figée) de la surface dérivée du bbox (calculée à chaque
resize/re-analyze). Deux champs distincts en state et en JSON :

| Champ | Source | Mutation | Usage |
|---|---|---|---|
| `surface_m2` (state) / `surface` (JSON) | Cartouche PDF, parsé à l'import | Jamais écrit après l'import | Affichage UI, scoring, export |
| `surface_m2_bbox` (state) / `surface_bbox` (JSON) | `width_cm × depth_cm / 10000` | Recalculé à chaque mutation du bbox | Matching (géométrie physique) |

**Justification** : aujourd'hui, chaque mutation du bbox (bbox editor,
re-analyze) écrasait `room.surface_m2` avec la valeur dérivée. Le
champ cartouche (44.28 m² pour une pièce non-rectangulaire, ex. pièce
305) était perdu au premier save — remplacé par la surface du
rectangle bbox inscrit (~9 m²). **L'information métier officielle
disparaissait à chaque itération.**

Justification du split :
- Les pièces physiques ne sont pas toutes rectangulaires (décrochés,
  alcôves, formes en L). Le cartouche donne la surface vraie ; le
  bbox donne le rectangle inscrit exploitable par l'algo.
- Le **matching** travaille sur le rectangle (placement de blocs) →
  consomme `surface_m2_bbox`.
- Le **scoring, l'affichage, l'export** communiquent la réalité
  physique → consomment `surface_m2` (cartouche).
- Les pièces créées ex nihilo (sans cartouche) ont `surface_m2 = 0` →
  fallback affichage sur `surface_m2_bbox`.

**Impact** :
- `olm/ingestion/extract.py` : `extract_rooms_from_preprocessed`
  retourne désormais les deux champs.
- Frontend : `_updateRoomDims`, bbox editor, helper reanalyze écrivent
  dans `surface_m2_bbox` (plus jamais dans `surface_m2`).
- `ingestion_export.js` : écrit `surface` (cartouche) + `surface_bbox`
  (bbox).
- `PREPROCESSED_JSON_SPEC.md` : champ `surface_bbox` ajouté (Save-only,
  optionnel).

---

## D-114 · canonical_top_face explicite écrase la détection couleur (2026-04-19)

**Décision** : si `canonical_top_face` est explicitement présent dans le JSON
d'une pièce, `corridor_face` est dérivé comme son opposé et écrase la
détection automatique par couleur (`_detect_face_colors`).

**Justification** : la détection couleur (pixels verts corridor sur les bords
de la bbox) peut se tromper — par exemple pour une pièce mitoyenne à un
couloir coloré qui n'est pas son corridor d'accès réel. `canonical_top_face`
manuel devient le mécanisme d'override propre.

**Impact** : fix propre pour les pièces mal orientées (929, 900, 902…).
Écriture du champ recalculée à chaque export JSON (`ingestion_export.js`)
depuis `doors[0].face`. Lecture fait foi.

---

## D-113 · Auto-mise à jour corridor_face à la re-analyze (2026-04-19)

**Décision** : à la fin d'une re-analyze, si au moins une porte est détectée,
`corridor_face` est mis à jour avec `doors[0].face` AVANT la canonicalisation
des autres features. La porte principale pointe par convention vers le
corridor.

**Justification** : permettait aux pièces sans doors/canonical_top_face au
JSON de se corriger toute seule après re-analyze. Avant, elles restaient
mal orientées.

**Impact** : la canonicalisation (windows/openings/doors/hits/seed) utilise
la bonne face dès sa mise à jour. Propagé à `ingState.rooms` et `fpData.rooms`
au save pour que Floor reflète l'orientation à jour.

---

## D-112 · Canonicalisation cohérente re-analyze → state (2026-04-19)

**Décision** : la re-analyze retourne des coordonnées **absolues** (dans le
repère image brut). Le state frontend stocke en **canoniques** (corridor
toujours au sud). La transformation absolu → canonique est appliquée dans
le handler de re-analyze avant merge dans le state.

**Éléments canonicalisés** : `face`, `offset_cm`, `hinge_side` pour
openings/windows/doors, points (hits + seed), rectangles
(auto_door_masks_px), dimensions (swap width/depth pour east/west corridor).

**Justification** : avant, pour corridor ≠ south, la re-analyze injectait
des coords absolues dans le state canonique → features affichées tournées
de 90° / 180° / 270° (symétrie pure observée).

**Impact** : pour toute pièce non-south corridor, la re-analyze produit
maintenant un rendu cohérent avec l'affichage canonique. Également
appliqué au chargement depuis `ingState.rooms` à l'entrée d'amendment.

---

## D-111 · Règle métier fenêtre ↔ opening exclusives par face (2026-04-19)

**Décision** : dans `extract_room_features`, si une face possède au moins
une fenêtre détectée, toutes les openings de cette face sont supprimées
(considérées comme artefacts du double trait de fenêtre).

**Justification** : le dessin d'une fenêtre (double trait parallèle avec
petit décalage du mur) génère souvent de faux "openings" à cause de la
discontinuité perçue par `_classify_wall_direct`. Règle simple : une face
ne peut pas avoir les deux à la fois.

**Impact** : pipeline plus propre. L'utilisateur peut ajouter manuellement
une opening sur une face vitrée via le CRUD si un cas limite se présente.

---

## D-110 · Re-analyze redétecte les portes à chaque run (2026-04-19)

**Décision** : le handler `/api/room/reanalyze` reçoit `doors_px = []` (vide)
depuis le frontend. Les anciennes portes ne sont plus envoyées pour
masquage préventif. `expand_door_arcs` tourne toujours et redétecte.

**Justification** : l'ancien comportement (préservation des auto doors)
masquait les arcs de porte avec des zones transparentes → la redétection
ne pouvait plus les trouver. Les erreurs de détection initiales étaient
alors figées.

**Impact** : redétection fraîche à chaque re-analyze. Les portes manuelles
(origin="manual") restent préservées dans le state, mais pas envoyées au
backend pour masquage.

---

## D-109 · Re-analyze expose les portes détectées (2026-04-19)

**Décision** : `extract_room_features` retourne le champ `doors` (liste
des portes détectées par `expand_door_arcs`) quand l'appelant n'a pas
fourni `doors_px`.

**Justification** : à minima, la re-analyze doit faire ce que l'import
OCR fait. Avant, les portes trouvées par le comb étaient discardées.

**Impact** : le frontend merge les doors détectées comme
`openings[has_door=true, origin=auto]`. Réutilisé par la règle D-113 pour
mettre à jour `corridor_face`.

---

## D-108 · DetectionConfigCm — paramètres de détection centralisés en cm (2026-04-19)

**Décision** : nouveau module `olm/core/detection_config.py` avec dataclass
`DetectionConfigCm` regroupant 18 seuils d'ingestion en cm (ou unités
naturelles : degrés, niveaux gris). Méthode `to_px(scale_cm_per_px)` pour
conversion en px au runtime.

**Paramètres migrés** : min_opening_width, min_opening_depth, min_window_width,
min_obstacle_width, max_absorb, wall_depth, snap_search, mode_tolerance,
morph_dilate, comb_step, coarse_step, ray_margin, max_ray, door_probe_depth,
door_group_gap, door_wall_margin, default_door_width, cartouche_margin.

**Consommation** :
- `extract.py` : `_classify_wall_direct` + `_merge_adjacent_segments` lisent
  `cfg.to_px(scale)` à chaque appel.
- `test_comb.py` : `_apply_detection_config(scale)` met à jour les
  constantes module au début de `detect_room`.

**Justification** : les constantes hardcodées en px étaient incohérentes
d'une échelle à l'autre. Le bug fatal `max_absorb_px=120` (= 355 cm à
scale 2.96 cm/px, absorbait toute porte < 3 m) n'aurait jamais existé
avec des seuils en cm. Base de règles normatives en cm, source unique
de vérité, surchargeable via `project/config.json` (section `room_detection`,
wire-up UI à faire).

**Impact** : comportement stable à toutes les échelles. Défauts calibrés
pour scale ~3 cm/px (usage courant). À l'avenir, exposer les 4 seuils
métier (binarize threshold, min opening/window, default door width) dans
Settings UI, garder les 14 autres comme paramètres fichier.

---

## D-107 · Re-analyze pièce par pièce avec ray-cast — version fonctionnelle (2026-04-19)

**Décision** : livrer d'abord la **ré-analyse par pièce** (D-104 étendu) avec un vrai ray-cast, plutôt que le refactor global de l'import Préprocessé (D-105 Phase 1+2). Avantage : scope circonscrit, résultat visible immédiatement sur une pièce à la fois, pas de régression de l'import.

**Implémentation livrée** :

- `extract_room_features(image, seed_px, bbox_px, scale, transparent_zones_cm, doors_px, door_width_cm, threshold, step_px)` :
  - Peint des zones transparentes utilisateur + **zones transparentes automatiques aux portes** (rect `door_width_cm × door_width_cm` centré sur le milieu de la porte, débordant inside pour couvrir l'arc).
  - Binarise.
  - Utilise **`test_comb.detect_room`** (même algo éprouvé que l'import OCR) depuis le seed → nouveau bbox + hits (comb complet).
  - Classifie les murs avec `_classify_wall_direct` sur le nouveau bbox.
  - Fallback couleur : fenêtre unique full-face si une face borde du bleu extérieur et qu'aucune fenêtre n'est détectée.
  - Retourne : `bbox_px`, `seed_px`, `windows`, `openings`, `hits`, `auto_door_masks_px` (pour debug).

- **Endpoint `/api/room/reanalyze`** : accepte `seed_px`, `bbox_px`, `scale_cm_per_px`, `transparent_zones`, `doors`, `door_width_cm`, `threshold`.

- **Frontend (Re-analyze en Room amend mode)** :
  - Envoie `seed` + `bbox` + `doors` (enrichies depuis le JSON) + `transparent_zones` (user) + `door_width_cm`.
  - Adopte le nouveau bbox retourné → met à jour `state.room_width_cm/depth_cm` et `originalRoom.bbox_px`.
  - Préserve les éléments `origin: "manual"` (D-104), filtre via `deleted_auto_signatures`.
  - Stocke `room_hits` et `room_seed_cm` en coords room-local pour visualisation V/H-rays.

- **V-Rays / H-Rays toggles** en Room toolbar. Render axis-aligned parallèle (pas un éventail depuis le seed) : pour chaque hit, la V-ray part de `(hit.x, seed.y)` au `hit` ; la H-ray part de `(seed.x, hit.y)` au `hit`. Couleur par direction (N vert, S bleu, W rouge, E orange).

- **Masques auto-portes visualisés** : rect orange hachuré sur la pièce quand `state.room_auto_door_masks` est rempli. Utile pour debug l'effet du masquage sur le ray-cast.

- **Propagation scale** : lorsque l'utilisateur change `drawing_scale`, `fpOverlay.pxPerCm` est recalculé en plus de `ingState.scale` — sinon l'overlay ne suit pas au resize.

- **Test plan** : `project/plans/test_floorplan_preprocessed.json` — room 917 a reçu `seed_x/seed_y` sur sa porte (272, 305) pour valider le pipeline.

**Bug important résolu** : `_classify_wall_direct` retourne des segments dont `start_px/end_px` sont DÉJÀ relatifs au début de la face (pas en coords absolues image). Le code calculait un offset erroné en soustrayant `face_origin_px`, résultant en offsets négatifs/hors bbox.

**Scope restant (D-105 global import)** : le refactor de `extract_rooms_from_preprocessed` pour que l'import produise aussi les hits + bboxes recalculés reste à faire. La re-analyze par pièce donne déjà un chemin propre pour l'utilisateur : importer (garde JSON tel quel) → ouvrir chaque pièce → re-analyze.

---

## D-106 · Leçons tirées d'une tentative d'implémentation Phase 1 de D-105 (2026-04-19)

**Contexte** : tentative d'implémenter D-105 Phase 1 (ray-cast depuis seeds + classification murs + fenêtres combinées) sans traiter encore les portes (Phase 2). Le commit WIP a été **reverted** (`9f3d6a9` → `edb3fb9`) après constat que l'approche en deux phases produit un résultat cassé intermédiaire.

**Ce qui ne marchait pas** :

1. **Ray-cast qui s'échappe par les portes** : pour les pièces avec portes ouvrant sur un couloir, les rayons traversent la porte et trouvent un mur très lointain (autre pièce, extérieur). Résultat : bboxes gigantesques qui chevauchent plusieurs pièces réelles. Impact visuel : rooms de couloir (WC, cuisine, escaliers, archives…) qui prennent la moitié de l'étage.
2. **Match endpoint qui hang** : les dimensions dégénérées (ou démesurées) font boucler ou ralentir drastiquement `match_room` qui itère le catalogue pour chaque pièce. Sur 30 pièces avec certaines à 30m × 30m, le match ne renvoyait jamais. fpData restait sur les données d'une session précédente → impression que "rien ne se passe".
3. **Hot-reload Flask en mode debug** tue les requêtes en cours dès qu'on sauvegarde un `.py`. Conseil : tester avec `FLASK_DEBUG=0` pendant les phases d'intégration.
4. **`remove_non_ortho` sur l'image entière est coûteux / crashe sur gros plan** : la boucle Python sur les connected components + `cv2.minAreaRect` ne passe pas à l'échelle. Pour les re-analyses batch, skip l'appel ou l'appliquer uniquement sur le crop.

**Enseignements** :

- **Phase 1 et Phase 2 sont indissociables** : sans masquage des portes (Phase 2), le ray-cast (Phase 1) donne des bboxes inutilisables pour les pièces ayant des portes larges ou des ouvertures non-triviales. Il faut livrer les deux phases ensemble.
- **Besoin de seeds de porte dans le JSON v3** : la spec actuelle (`doors: [{seed_x, seed_y}]`) n'est pas respectée par le fichier `test_floorplan_preprocessed.json` qui a des doors en format OCR enrichi (`face`, `offset_px`, `width_px`). Régénérer ce fichier avec seeds est un pré-requis à Phase 2.
- **Tests end-to-end sur gros plan dès le début** : les effets d'échelle (80 pièces, image 5000+ px, catalogue de centaines de patterns) font émerger des bugs absents sur les petits jeux de test. Tester tôt avec le test_floorplan_preprocessed (30 pièces) est utile.
- **Alternative envisagée** : détection d'échappée par couleur (arrêter les rayons à la transition vers vert couloir / bleu extérieur). Rejetée au profit du plan original D-105 (seeds de porte + zones transparentes), plus robuste et plus fidèle à la sémantique des plans.

**État actuel** : code revert à `edb3fb9`. Pipeline Préprocessé lit toujours le JSON directement (windows/openings OCR-enrichies non recalculées). À reprendre en session dédiée avec les deux phases ensemble.

**Décisions de conception prises pendant la session (à ne pas redécouvrir)** :

1. **Point d'entrée fiable Préprocessé** = `seed_x/seed_y` pièce + `seed_x/seed_y` portes + `id` + `surface` + couleurs `-SD` (bleu extérieur, vert couloir). Tout le reste (`bbox_px`, `windows`, `openings`) doit être **recalculé**, même si le JSON en contient (bootstrap OCR non fiable).
2. **Fenêtres** : algo combiné = texture (primaire) + fallback couleur bleue pour fenêtre full-face si rien détecté. Ne PAS basculer en "full-face" par défaut dès que la face borde du bleu — les bureaux ont souvent plusieurs fenêtres séparées à détecter finement.
3. **Portes** : pas de détection d'arc. Seeds JSON → snap à la face la plus proche, largeur = `default_door_width_cm`. Zone transparente auto au seed, couvrant l'ouverture + l'arc, largeur = profondeur = `default_door_width_cm`.
4. **`default_door_width_cm`** : paramètre global Settings General, 90 cm par défaut. Utilisé partout (CRUD manuel D-103, genération auto portes D-105, zone transparente d'arc).
5. **`origin` → `modified: bool`** : renommage décidé (cohérent avec "amended"). Préservé via cache par clé `(type, face, offset_cm, width_cm)` dans `_rvCommitFromState` à travers le round-trip DSL. **Absent de la DSL** (transparent pour l'utilisateur), présent dans le JSON v3 au save.
6. **Suppressions manuelles d'auto-détectés** : `deleted_auto_signatures` (liste de clés) par pièce → filtrés aux ré-analyses suivantes, évite la réapparition. Persisté dans `olm_state` (TODO).
7. **Batch re-analyze** : un seul POST `/api/room/reanalyze_batch` avec tous les rooms (pas de chunks), image + binary chargés **1× côté serveur**, sliced per-room. `remove_non_ortho` **skippé** (trop coûteux par crop, trop coûteux global). Compromis accepté : les arcs non filtrés dans re-analyze → Phase 2 y remédie via zones transparentes auto au seed de porte.
8. **`extract_room_features`** : paramètre `binary_global` optionnel → fast path sans remove_non_ortho quand l'appelant a déjà le binary. Zones transparentes appliquées au slice via zéro-out du mask (pas de peinture PIL).
9. **Recalibration de `cm_per_px`** à l'import Préprocessé : médiane des `sqrt(surface_m2 * 10000 / area_px)` sur les bboxes ray-cast valides. Remplace le `plan_scale`/JSON legacy.
10. **Garde-fou min/max dimensions** : rooms avec `width_cm < 100` ou `depth_cm < 100` → fallback surfacique. Rooms démesurées (`> 15 m`) → à implémenter en Phase 2 via masquage portes.
11. **Phase 1 et Phase 2 doivent être livrées ensemble** : l'échec de cette session montre qu'une Phase 1 seule donne des bboxes cassées inutilisables (ray-cast s'échappe). Ne pas redémarrer sans le masquage des portes.
12. **Développement / tests** : `FLASK_DEBUG=0` pendant les intégrations pour éviter que le hot-reload tue les requêtes en cours. Tester **tôt** sur le gros plan (30 pièces) pour détecter les problèmes d'échelle.
13. **Alternative "détection par couleur"** (stopper les rayons à la transition vers vert/bleu) : **rejetée**. Moins robuste, ne respecte pas la sémantique architecturale (un rayon qui traverse une porte devrait s'arrêter au mur opposé masqué, pas à la peinture du couloir).
14. **Pré-requis Phase 2** : régénérer `test_floorplan_preprocessed.json` avec `doors: [{seed_x, seed_y}]`. Actuellement les doors sont au format OCR enrichi (`face`, `offset_px`, `width_px`). Les seeds peuvent être dérivés par un outil séparé depuis les enriched data + bbox OCR, **mais** ça doit être fait avant le développement du pipeline D-105.
15. **V/H-rays en Room** : toggles à gauche du canvas toolbar (comme en Floor). Les hits sont exposés par le pipeline préprocessé via `room.hits` (4 points seed → bords du bbox), convertis en coords room-local cm au chargement de la pièce. Colors : N=vert, S=bleu, W=rouge, E=orange. Seed = cercle vert, hits = disques jaunes.
16. **Style I/O disque** : **une seule ouverture** de l'image par pipeline. Jamais `PIL.Image.open()` dans une boucle par pièce. Charger 1× globalement, passer `image_arr` ou `binary_global` en paramètre aux fonctions per-room. Règle qui a divisé le temps de re-analyze par ~N (avec N = nombre de pièces).

---

## D-105 · Pipeline Préprocessé refondu — ray-cast depuis seeds + sémantique couleurs + portes via seeds (2026-04-19)

**Contexte** : l'implémentation actuelle de `extract_rooms_from_preprocessed` (et par ricochet `extract_room_features` pour D-104) suppose que le JSON v3 contient des `bbox_px` / `windows` / `openings` fiables. **C'est faux** : ces champs viennent d'une passe OCR antérieure utilisée pour bootstrapper le fichier Préprocessé et ne sont **pas** la source de vérité. En Mode Préprocessé, les **seules entrées fiables** sont :

- `seed_x / seed_y` de la pièce (obligatoire)
- `id` / `surface` de la pièce
- `seed` de chaque porte (coordonnées pixel)
- Couleurs du `-SD.png` : bleu ciel = extérieur, vert clair = couloir

Les contours de la pièce (bbox), la position exacte des fenêtres et des ouvertures **doivent être recalculés** par un ray-cast sur le `-SD`.

**Décision** : refondre le pipeline Préprocessé pour qu'il exploite ces invariants plutôt que de faire confiance au JSON. Architecture cible :

1. **Ray-cast depuis le seed de la pièce** sur le `-SD` binarisé → détermine le bbox.
2. **Zones transparentes** appliquées avant binarisation :
   - Zones utilisateur (`transparent_zones`, D-103)
   - **Zones transparentes auto-générées au seed de chaque porte**, côté pièce (dos au couloir), pour permettre aux rayons de traverser la porte et toucher le mur extérieur derrière. Remplace la détection d'arc de porte.
3. **Classification des murs** via `_classify_wall_direct` sur le bbox détecté.
4. **Fenêtres enrichies par la couleur** : un mur qui borde du bleu extérieur est promu en fenêtre même si la texture est ambiguë (dans ce cas la couleur arbitre, priorité sur texture).
5. **Portes déterminées depuis les seeds JSON** : pas d'analyse d'arc. Chaque seed de porte est snappé à la face la plus proche du bbox, une porte de largeur nominale (cf. `default_door_width_cm`) est créée à cette position.
6. **`corridor_face` et `exterior_faces`** via `_detect_face_colors` (existant, vert/bleu).

**Avantages par rapport à OCR** :

- Pas besoin d'OCR sur les cartouches (id / surface déjà dans JSON).
- Pas besoin d'effacer les cartouches (déjà effacés dans `-SD`).
- Détection des portes simplifiée (seeds + zone transparente auto), pas d'algo d'arc.
- Détection des fenêtres fiabilisée via la couleur extérieure bleue.

**Impact sur D-104 (Re-analyze)** : `extract_room_features` doit aussi suivre ce pipeline. L'endpoint `/api/room/reanalyze` prendra en entrée (en plus du bbox initial si disponible) les **seeds** (pièce + portes). En pratique, le re-analyze peut même se contenter du seed + door seeds et recalculer le bbox, rendant l'entrée bbox optionnelle.

**Précisions complémentaires (2026-04-19)** :

- **Portes — zone transparente auto** : en plus d'être déduite depuis le seed de porte (pour permettre aux rayons de traverser l'ouverture), une zone transparente est posée **automatiquement au niveau de l'arc de porte** pour que les rayons ne soient pas bloqués par le trait d'arc dessiné. Position : centrée sur le seed de porte, largeur = largeur de porte standard (paramètre général `default_door_width_cm` initialisé à 90 cm), profondeur = largeur de porte (arc = 90°). Orientation : côté pièce, dos au couloir.
- **Largeur de porte standard** : nouveau paramètre global `default_door_width_cm` = 90 cm par défaut. Utilisé aussi bien pour l'ajout manuel (D-103) que pour la largeur automatique générée depuis le seed JSON et la géométrie de la zone transparente d'arc.
- **Fenêtres — algo combiné** : on garde la détection par transitions de texture (D-105 pipeline) comme source primaire, parce qu'il y a souvent **plusieurs fenêtres individuelles** le long d'une façade de bureau (ne pas tout rabattre en une unique fenêtre). La couleur bleue extérieure sert de **fallback** : si la face borde du bleu mais qu'on n'a détecté aucune fenêtre (pattern de dessin complexe, vitrage masqué, etc.), on pose **une fenêtre unique couvrant toute la face**.
- **Convention de nommage** : renommer le champ `origin: "auto" | "manual"` en un booléen `modified: true/false` (cohérence avec le reste du code qui parle d'éléments "amended" / "modified"). Semantique identique. À propager dans le frontend (state, merge logic D-104) et dans le JSON v3 lorsque la persistance sera ajoutée.

**Scope** : cette refonte est un chantier à part entière, non livré dans la séquence D-104. Voir TODO `R-05` pour les sous-tâches.

**Impact** : `olm/ingestion/extract.py` (nouveau pipeline), `olm/server/app.py` (endpoints), éventuellement `docs/specs/PREPROCESSED_JSON_SPEC.md` (clarifier fiabilité des champs).

---

## D-104 · Re-analyze ciblée d'une pièce avec préservation des manuels (2026-04-19)

**Décision** : Ajout d'une fonction de **ré-analyse** automatique des fenêtres et ouvertures d'une pièce, sans perdre les modifications manuelles de l'utilisateur ni relancer tout le plan.

**Workflow cible (R-04 Review)** : l'utilisateur importe un plan, constate des pièces mal analysées à cause d'artefacts ou de zones à ignorer. Il place manuellement des zones interdites (rouge) et des zones transparentes (vert, artefacts à ignorer). Il clique "Re-analyze" → l'algo rejoue la détection windows/openings pour cette pièce en tenant compte des zones transparentes. Il ajuste ensuite manuellement.

**Séparation auto / manuel** : chaque fenêtre / porte / ouverture porte un champ `origin: "auto" | "manual"` :
- Initialement, l'extraction produit des éléments `origin: "auto"`.
- Toute création, drag ou resize via l'UI bascule l'élément en `origin: "manual"`.
- La ré-analyse remplace uniquement les `origin: "auto"` ; les manuels sont réinjectés tels quels.
- Un élément `auto` supprimé par l'utilisateur est enregistré dans `state.deleted_auto_signatures` (signature `type|face|offset|width`) pour être filtré aux ré-analyses suivantes et ne pas réapparaître.

**Invisible à l'utilisateur dans la DSL** : le champ `origin` n'est **pas** serialisé dans la DSL (qui reste user-friendly). Il est préservé à travers le round-trip DSL via un cache par clé `(type, face, offset_cm, width_cm)` dans `_rvCommitFromState`. Pour la persistance inter-sessions, `origin` devra être inclus dans le JSON v3 (`olm_state`) — à faire.

**Architecture backend** : nouvelle fonction `extract_room_features(image, bbox, scale, transparent_zones)` dans `olm/ingestion/extract.py`. Implémentation **ciblée B2** (pas un filtre sur une extraction complète) :
- Copie l'image, peint les zones transparentes en blanc (255).
- Binarise.
- Appelle `_classify_wall_direct` pour chaque face (N/S/E/W) sur le bbox donné — pas de ray-cast, pas d'OCR, pas de détection de bbox (déjà connu).
- Les doors ne sont **pas** redétectées (la détection d'arc sort du périmètre de la classification directe). Le frontend préserve les doors existantes.

**Route Flask** : `POST /api/room/reanalyze` prend `{plan_path, bbox_px, scale_cm_per_px, transparent_zones, threshold}` et renvoie `{windows, openings}`.

**Trade-off accepté** : les doors ne peuvent pas être re-détectées par ce flux. Workflow pour l'utilisateur : supprimer et redessiner la porte si besoin (cohérent avec D-103 : pas de toggle de type, suppression + re-création).

**Impact** : [extract.py](../olm/ingestion/extract.py), [app.py](../olm/server/app.py), [init_rvtool.js](../olm/static/init_rvtool.js), [editor.js](../olm/static/editor.js), [ingestion.js](../olm/static/ingestion.js), [pattern_editor.html](../olm/templates/pattern_editor.html).

---

## D-103 · Room amend mode — CRUD ouvertures + zones (exclusion rouge / transparent vert) (2026-04-19)

**Décisions** :

- **CRUD graphique ouvertures** en Room amend mode (fenêtres, portes, ouvertures simples) :
  - Ligne de clic transparente large sur chaque ouverture → sélection sans poignée pré-affichée (évite la confusion "toutes actives").
  - Poignée circulaire + badge × (suppression) sur l'élément sélectionné uniquement.
  - Drag de la poignée → déplacement le long du mur (snap GRID_STEP_CM, clamp).
  - Poignées carrées aux extrémités → redimensionnement par le début/la fin du mur (snap, MIN=GRID_STEP_CM).
  - Suppression via badge × ou touche Delete/Backspace.
  - Changement de type non supporté (supprimer + redessiner couvre le besoin — décidé avec l'utilisateur).

- **Zones transparentes** : artefacts graphiques à ignorer sur le plan, rendu vert semi-transparent (`#58c080`). Backend DSL : nouveau keyword `TRANSPARENT x y w h` stocké dans `RoomSpec.transparent_zones: list[ExclusionZone]` (réutilise la même dataclass, `physical=False`). Frontend : `state.room_transparents`, interactions identiques aux `room_exclusions` (sélection, drag, 4 poignées de resize NW/NE/SW/SE, delete).

- **UI unifiée d'ajout** : dropdown **"Add room items ▾"** dans la toolbar Room amend mode, remplace les 4 boutons individuels. Items : Window, Door, Opening, Exclusion zone (red), Transparent zone (green).

- **Rendu — traits à taille constante** : `vector-effect="non-scaling-stroke"` sur murs / fenêtres / portes / ouvertures / effacement mur sous ouverture, et cap de taille des points de grille à 2 px via `_currentZf`. Les poignées et badges sont dimensionnés en pixels CSS via `_currentZf`.

- **Zoom fit par défaut** : pièce + 20% de sa hauteur en haut/bas et 20% de sa largeur à gauche/droite (anciennement pixels absolus + correction d'aspect-ratio qui rapetissait le rendu). Zoom out clamp assoupli à 3× la vue fitée par défaut.

- **Labels dimension pièce** : déplacés sous la pièce (width) et à gauche (depth), offset augmenté à 48 px pour ne plus masquer les poignées d'ouvertures.

- **Poignées de coin pièce** : taille portée à ~10 px CSS constants (auparavant 2 unités SVG qui devenaient invisibles au zoom arrière).

- **UX divers** : entrée "All" retirée des listes Room et Office (conservée en Import), largeur min panneau gauche Room/Office 180 px, panneau droit 263 px, Pattern Editor min left 216 / min right 259.

**Impact** : [editor.js](../olm/static/editor.js), [init_rvtool.js](../olm/static/init_rvtool.js), [render_shared.js](../olm/static/render_shared.js), [room_dsl.py](../olm/core/room_dsl.py), [room_model.py](../olm/core/room_model.py), [app.py](../olm/server/app.py), [pattern_editor.html](../olm/templates/pattern_editor.html), [init_resize.js](../olm/static/init_resize.js).

---

## D-102 · Rulers mètres unifiés + resize colonnes persistant (2026-04-19)

**Décisions UX** regroupées (canvas SVG partagé Room/Office/PatternEditor) :

- **Rulers mètres** : un seul système. Les rulers HTML autour du SVG (haut/bas/gauche/droite) sont la référence unique ; les labels "1m"/"2m" dessinés dans le canvas à L.850-866 ont été supprimés (redondance). Origine (0,0) = coin NW de la pièce (`state._roomNW` stocké au render). Valeurs négatives affichées à gauche/au-dessus, positives à droite/en-dessous.
- **Tab switch Office** : `fpRenderCurrent()` est déclenché quand l'onglet `lytDesign` devient actif — auparavant l'onglet restait sur son état précédent (ancienne pièce, overlay non rafraîchi).
- **Rulers au 1er affichage** : `updateRulers` est appelée via un rAF au switch d'onglet `fpReview`/`lytDesign` pour éviter `wrapRect.width=0` au render initial (tab caché).
- **Resize colonnes** : panneaux latéraux synchronisés Room ↔ Office (même clé `leftPanelWidthShared` / `rightPanelWidthShared`) pour éviter le décalage du canvas au switch. Pattern Editor a ses propres clés (`peLeftWidth`, `peRightWidth`). Persistance localStorage sur toutes les sessions.
- **Liste des pièces** : entrée "All" (retour Floor) retirée de Room et Office (conservée uniquement dans Import où elle a du sens).

**Impact** : [editor.js](../olm/static/editor.js), [init.js](../olm/static/init.js), [init_resize.js](../olm/static/init_resize.js), [ingestion.js](../olm/static/ingestion.js), [pattern_editor.html](../olm/templates/pattern_editor.html), [style.css](../olm/static/style.css).

---

## D-101 · Overlay par niveau — Floor = PNG standard, Room/Office = PNG -SD (2026-04-19)

**Décision** : En Mode Préprocessé, l'affichage du plan diffère selon l'onglet actif :

- **Floor** (fpImport) : PNG `<plan_id>.png` — version lisible par l'humain avec cartouches, labels, cotes.
- **Room** (fpReview) et **Office** (lytDesign) : PNG `<plan_id>-SD.png` — version sans description (cartouches effacés, extérieur bleu ciel, couloirs verts) utilisée aussi par l'algo d'extraction.

**Implémentation** : `ingState.planUrl` (consommé par `renderIngestion` pour Floor) reçoit `overlay_path` ; `window.fpOverlay.dataUrl` (consommé par `floor_plan.js` pour Room et `editor.js` pour Office) reçoit `enhanced_path`. Fallback croisé si l'un des deux manque. Mode OCR inchangé (un seul PNG partout).

**Justification** : respecte la convention D-74 / D-84 — l'utilisateur voit le plan métier au niveau Floor, la version algorithmique aux niveaux détaillés où les cartouches parasiteraient la lecture des pièces et aménagements.

**Impact** : [ingestion.js:1393-1413](../olm/static/ingestion.js#L1393-L1413). Pas de changement backend (l'API renvoyait déjà les deux chemins séparément).

---

## D-100 · Suppression du concept de fusion de pièces — remplacement par resize + commentaires (2026-04-18)

**Décision** : Abandonner R-09 (Identify merges) et toute gestion d'associations de pièces dans l'application. Le besoin — "étudier l'aménagement d'une pièce résultant de la suppression de murs entre 2+ pièces réelles" — est couvert par la combinaison :

- **Resize + Add/Delete room** : l'utilisateur ajoute une pièce virtuelle (bouton Add room dans Floor), la redimensionne par-dessus deux pièces existantes (poignées D-99), travaille l'aménagement dans Office. Deux issues : soit il garde la pièce test et supprime les deux pièces d'origine, soit il abandonne et supprime la pièce test.
- **Champ commentaires markdown** par pièce (à implémenter) : `comments_md` dans chaque entrée `rooms.{id}` du JSON v3 + section dédiée dans le rapport final. L'utilisateur y trace le raisonnement ("pièce 237+238 fusionnée suite à demande client — suppression du mur mitoyen", etc.).

**Justification** : un système de merge nécessiterait : IDs composés, gestion de la géométrie de fusion (recalcul de fenêtres/portes/exclusions, validation de mitoyenneté), tag "merged" dans la liste, passage par le pipeline Review/Office/Export avec des garde-fous partout. Coût élevé pour un cas d'usage rare. Le workflow resize + delete + commentaire couvre 95 % du besoin avec zéro dette technique, et laisse le contexte métier à un humain via le champ commentaires.

**Trade-off accepté** : pas de traçabilité machine-lisible des fusions (on ne peut pas générer un rapport "X rooms réelles → Y rooms effectives"). Le commentaire markdown suffit pour un audit humain.

**Impact** :
- `docs/TODO.md` : section R-09 "Identify merges" retirée.
- `docs/TODO.md` : nouvelle feature "champ commentaires markdown par pièce + rapport".
- `docs/TODO.md` : TODO Room→Floor sync (bug découvert en testant D-99 : le resize Room ne se reflétait pas dans Floor).
- `docs/SRS.md` : à mettre à jour pour documenter le workflow "resize + delete = suppression de murs".

---

## D-99 · Room resize — poignée SE pour ajustements fins (2026-04-18)

**Décision** : En Room amend mode, ajout d'une poignée de redimensionnement SE à la pièce, permettant la modification des dimensions `state.room_width_cm` / `state.room_depth_cm` à la souris.

- Répartition des rôles : **Floor = ajustements grossiers** (bbox editor du plan global), **Room = ajustements fins** (4 poignées de la pièce + 4 poignées pour chaque zone d'exclusion).
- **4 poignées** (NW/NE/SW/SE) dessinées aux coins de la pièce pendant l'amend mode. Rouge, 2×2 SVG units.
- **Render offset** (`state.roomRenderOffset`) : pendant le drag d'un coin autre que SE, le point NW de la pièce se déplace visuellement — l'overlay reste fixe, le contenu (fenêtres, portes, ouvertures, zones d'exclusion) est translaté pour conserver sa position absolue. L'offset persiste à travers les commits dans une même session d'amend, reset à l'entrée/sortie du mode.
- **Snap fin** : 5 cm pour le déplacement de la pièce (vs 10 cm ailleurs).
- **Clampage** : `MIN_CM = GRID_STEP_CM`. Pas de max. À la sortie du drag, toute ouverture ou zone d'exclusion qui dépasse les nouvelles dimensions est clamped aux bords.
- **Anti-interférence** : mousedown sur une poignée neutralise `setupPan` et `state.isPanning` ; le handler mousemove du pan globalise un early-return quand `rvTool.mode === "roomResizing"`.
- **Propagation Floor → Room** : à la sauvegarde de l'amendement (bouton Save room), `ingState.rooms[x].bbox_px` et `fpData.rooms[x]` sont recalculés depuis les nouvelles dimensions + offset. Seul le cas `corridor_face = south` est traité ; les autres orientations nécessitent un axis-remapping (TODO).
- À la fin du drag : régénération complète de la DSL (`_stateToDsl`) + `rvApplyDslAsync()` → backend re-parse + re-render.

**Justification** : workflow en deux passes. L'utilisateur délimite d'abord grossièrement chaque pièce dans Floor (bbox editor existant), puis affine la géométrie dans Room où l'échelle de la pièce remplit le canvas et les petites corrections sont plus précises. Sans cette feature, toute correction fine passait par l'édition manuelle de la DSL `ROOM WxD`.

**Impact** :
- `olm/static/editor.js` : rendu des 4 poignées dans `_renderImpl` (z=9.2) conditionné par `isReview && state.roomAmendMode`. Application de `state.roomRenderOffset` sur `roomX/roomY`. Pinning du centre de rotation de l'overlay aux dimensions originales pour éviter le drift en présence de rotation D-83. Propagation bbox_px vers `ingState.rooms` dans `save()`.
- `olm/static/init_rvtool.js` : mode `roomResizing` + handlers mousedown/mousemove/mouseup pour `[data-room-handle]`, helper `_clampContentsToRoom`, helper `_stateToDsl`.
- `olm/static/init.js` : garde anti-pan pendant `roomResizing`, garde `[data-room-handle]` dans `setupPan`, reset du render offset quand le mode amend sort.

---

## D-98 · Split ingestion.js — ingestion_scale + ingestion_export (2026-04-18)

**Décision** : Phase 4 du refactoring front-end D-94. Extraction de deux modules auto-contenus depuis `ingestion.js` (1605 l.) :

- `olm/static/ingestion_scale.js` (~90 l.) : helpers purs de parsing et conversion d'échelle (`parseDrawingScale`, `computeCmPerPx`, `getDrawingScale`, `getRenderDpi`, `suggestDrawingScale`). Exposés via `window.olmScale.*`.
- `olm/static/ingestion_export.js` (~125 l.) : `devExportV3Json` — sérialisation `ingState.rooms` vers le format JSON v3 + téléchargement. Exposé via `window.devExportV3Json` (utilisé par le bouton Save dans `init.js`). D-95 écrit `drawing_scale_text` et `drawing_scale_measured` depuis `ingState.scale`.

`ingestion.js` passe de 1605 → 1432 l. Le reste (renderIngestion, extractRooms/Preprocessed, room CRUD, toggles, init wiring) demeure couplé à `COLORS` local, `ingState` local et aux helpers mutuellement dépendants — extraire au-delà nécessiterait une exposition étendue sur `window`, pire que le couplage actuel.

**Justification** : les deux extraits sont des "feuilles" du graphe de dépendance (scale : pures fonctions ; export : une fonction top-level). ROI élevé (thématisation claire, ingestion.js plus lisible) sans risque de régression.

**Impact** :
- Nouveau `olm/static/ingestion_scale.js`.
- Nouveau `olm/static/ingestion_export.js`.
- `olm/static/ingestion.js` −173 l.
- `olm/templates/pattern_editor.html` : chargement des 2 nouveaux scripts avant `ingestion.js`.

---

## D-97 · Split init.js — init_rvtool + init_resize (2026-04-18)

**Décision** : Phase 3 du refactoring front-end D-94. Extraction de deux modules auto-contenus depuis `init.js` (1082 l.) :

- `olm/static/init_rvtool.js` (~300 l.) : outil zones d'exclusion pour le Room amend mode (placing/drawing/selected/dragging/resizing), incluant les handlers clavier (flèches = déplacer, Delete/Backspace = supprimer, Escape = désélectionner/annuler, Enter = commit). Capture-phase sur le `keydown` pour préempter la navigation Room/Office de `floor_plan.js`.
- `olm/static/init_resize.js` (~100 l.) : les deux drag-handles de redimensionnement des panneaux gauches (Floor + Room), déjà encapsulés en IIFE avant extraction.

Fixes UX associés (rvtool) :
- Couleur sélection zone : rouge (`#c05858`) au lieu de vert.
- Poignées de redimensionnement aux 4 coins (drag = resize, `MIN_CM = GRID_STEP_CM`). Taille 2×2 SVG units (−75 % vs proto initial).
- Clampage complet à la pièce (drag + resize + flèches) sur les 4 faces, plus seulement W/N.
- Enter (Retour) désélectionne (commit), complément à Escape (annulation).
- Bouton renommé "Add exclusion zone" (au lieu de "+ Zone").

`init.js` passe de 1082 → 724 l. Le reste (orchestration `init()`, onglets, amend mode global, catalogue, erase) reste dans `init.js` — couplage plus fort au flow d'init, extraction risquée sans gain net.

**Justification** : les deux modules extraits étaient déjà thématiquement autonomes (rvtool seule consomme `state.roomAmendMode`, `SCALE`, `GRID_STEP_CM`, `render()` via globals ; resize ne dépend que du DOM). Les laisser dans `init.js` rendait le fichier difficile à naviguer (1000+ lignes) sans bénéfice architectural.

**Impact** :
- Nouveau `olm/static/init_rvtool.js`.
- Nouveau `olm/static/init_resize.js`.
- `olm/static/init.js` −358 l.
- `olm/static/editor.js` : couleur sélection + 4 poignées SVG rendues dans `renderRoomElements`.
- `olm/templates/pattern_editor.html` : chargement des 2 nouveaux scripts après `init.js`.

---

## D-96 · render_shared.js — primitives SVG partagées (2026-04-18)

**Décision** : Création de `olm/static/render_shared.js` (phase 2 du refactoring front-end D-94). Expose `renderShared.doorSvg()` et `renderShared.gridSvg()` pour centraliser la logique de rendu dupliquée entre `editor.js` et `ingestion.js`.

- `doorSvg(face, hingeCoord, freeCoord, wallCoord, swingSide, opensInward, leafOffsetMag)` → retourne `[arcPath, leafLine]`. West wall inverse la relation swing↔hinge-coord (convention héritée).
- `gridSvg({ vb, cmPerPx, dotColor?, lineColor?, marginRatio?, minStartAt0? })` → retourne `{ dots, lines }` séparés pour que l'appelant applique des z-indices différents (editor : dots z=-0.5, lines z=-0.4).
- Constantes exposées : `COLOR_DOOR_ARC`, `COLOR_DOOR_LEAF`, `COLOR_WINDOW`, `COLOR_OPENING`.

**Justification** : 172 lignes de rendu porte/grille étaient dupliquées entre `editor.js` et `ingestion.js`. Toute correction (couleur, style, géométrie) devait être portée manuellement dans deux endroits. Single source of truth = moins de risque de désynchronisation.

**Impact** :
- `olm/static/render_shared.js` : nouveau fichier (~175 lignes).
- `olm/static/editor.js` : -70 lignes (portes + grille).
- `olm/static/ingestion.js` : -50 lignes (portes + grille).
- `pattern_editor.html` : `render_shared.js` chargé après `block_svg.js`, avant les modules qui l'utilisent.

---

## D-95 · Échelle de dessin — l'input UI prime et écrase les deux champs JSON (2026-04-18)

**Décision** : Option D. Le champ `drawing_scale` de l'UI permet à l'utilisateur d'outrepasser les valeurs présentes dans le JSON v3 préprocessé. Toute édition du champ est immédiatement propagée à `ingState.rooms` ET à `fpData.rooms` (Room/Office restent synchronisés). À la sauvegarde (Save / Export), les deux champs `drawing_scale_text` ET `drawing_scale_measured` du JSON sont écrits depuis la valeur courante de `ingState.scale` — les anciennes valeurs mesurées sont écrasées.

**Justification** : D-91 avait fait primer `drawing_scale_measured` sur le texte saisi, au motif que la règle mesurée sur le plan est « plus fiable ». En pratique l'utilisateur a besoin de pouvoir corriger une mesure erronée ou imposer une échelle de référence, et de persister cette correction. Faire primer l'UI est cohérent avec le reste de l'outil (toute modification manuelle l'emporte sur les valeurs auto). L'écrasement des deux champs à la sauvegarde supprime le risque de divergence au re-import.

**Impact** :
- `ingestion.js` : `_applyDrawingScale` propage désormais les nouvelles dims à `fpData.rooms` (fix bug — Room/Office affichaient des dimensions stales après changement d'échelle).
- `ingestion.js` : `devExportV3Json` ajoute `drawing_scale_text` et `drawing_scale_measured` au JSON exporté.
- D-91 — priorité `measured > text` au backend (`app.py:694-720`) reste valide pour le tout premier import d'un fichier préprocessé tiers, mais ne pose plus de conflit durable : dès le premier Save, les deux champs convergent.

---

## D-94 · Refactoring front-end — store unifié + découpage modules (2026-04-18)

**Décision** : Lancement d'un refactoring front-end en 6 phases pour consolider les fondations avant les prochaines features (R-11 round trip notamment).

- **P0** (ce commit) : suppression de `matching_viewer.html` (1138 l., dead code — route `/matching` jamais référencée depuis HTML/JS) + route Flask associée.
- **P1** : création de `olm/static/store.js` — store unifié `olmStore` remplaçant les 5 globals `ingState`, `fpData`, `fpOverlay`, `fpAmendments`, `fpRoomAmendments` (232 occurrences, 4 fichiers). Pattern `set(path, value)` + `subscribe(path, cb)`. Migration progressive via shims de compat sur `window.*`.
- **P2** : extraction `render_shared.js` — primitives SVG communes (porte, fenêtre, ouverture, grille) dupliquées entre `editor.js`, `ingestion.js`, `floor_plan.js`.
- **P3** : split `init.js` (1088 l.) → `init_tabs.js`, `init_rvtool.js`, `init_amend.js` + bootstrap réduit.
- **P4** : split `ingestion.js` (1605 l.) → `ingestion_render.js`, `ingestion_import.js`, `ingestion_scale.js`.
- **P5-P6** (optionnelles) : split `floor_plan.js` et `editor.js` selon besoin.

**Justification** : 5 sources de vérité sur l'état du plan, fichiers de 1000-1850 lignes, rendu et state entremêlés. R-11 (persistance des amendements dans le JSON) exige un état sérialisable cohérent — le bon moment pour consolider. Phasage itératif (pas de big-bang), chaque phase est commitable et testable isolément.

**Impact** : suppression `olm/templates/matching_viewer.html`, route `/matching` retirée de `olm/server/app.py`, arborescence `CLAUDE.md` mise à jour.

---

## D-93 · Settings restructuration + poids scoring Office (2026-04-17)

**Décision** : Refonte du panneau Settings et ajout des poids de scoring.

- Standards dans General : radio default + label éditable par ligne, sans clé technique affichée.
- Settings Floor : Plans directory élargi, DPI centré, "Standard colors" (ex-Semantic colors) avec descriptions.
- Settings Office : 5 poids de matching — Density, Comfort (existants), Back to door, Natural light, Face to wall (nouveaux, défaut 0 = inactifs).
- Export intégré dans General.
- Toolbar Floor masquée tant qu'aucun plan n'est chargé.

**Justification** : Settings organisé par onglet applicatif. Poids de scoring préparés dans l'UI avant implémentation des détections correspondantes.

**Impact** : `pattern_editor.html`, `config.js`, `init.js`, `ingestion.js`.

---

## D-91 · Convention fichiers -SD + drawing_scale_measured (2026-04-17)

**Décision** : Refonte de la convention de nommage des fichiers préprocessés et de la gestion de l'échelle.

- PNG standard `<plan_id>.png` (avec cartouches) + PNG `<plan_id>-SD.png` (Sans Description, pour l'algo). Remplace l'ancien suffixe `_enhanced`.
- JSON v3 : `drawing_scale` renommé `drawing_scale_text`, ajout `drawing_scale_measured` (cm/px depuis la règle de 5m) et `orientation` (degrés par rapport au nord).
- `drawing_scale_measured` prioritaire sur le calcul text+DPI, avec log warning si divergence > 20%.

**Justification** : Le preprocessing externe fournit une échelle mesurée sur la règle du plan, plus fiable que l'échelle textuelle. Le suffixe `-SD` est plus explicite que `_enhanced`.

**Impact** : `config.json`, `app.py`, `ingestion.js`, `extract.py`, JSON de test mis à jour. Convention `-SD` propagée dans TODO et code.

---

## D-92 · Renommage sous-onglets + restructuration Settings (2026-04-17)

**Décision** : Renommage des sous-onglets et alignement des Settings.

- Sous-onglets : Floor, **Room** (ex-Rooms), **Office** (ex-Design), Catalogue.
- Settings : General (+ Export intégré) | Floor, Office, Catalogue. Séparateur visuel entre General et les onglets applicatifs.
- Standard par défaut pré-sélectionné dans Office à chaque changement de pièce.
- Bouton Export ajouté à droite de Save dans la barre d'actions.

**Justification** : Cohérence nommage entre onglets et Settings. "Office" reflète mieux le rôle (aménagement de bureau). Export est un paramètre global, pas un onglet dédié.

**Impact** : `pattern_editor.html`, `init.js`, `floor_plan.js`.

---

## D-90 · Option B layout — navigation gauche, détail droite (2026-04-16)

**Décision** : Réorganisation des colonnes selon le pattern "navigation à gauche, détail à droite".

- **Floor** : colonne unique à gauche (plan selector, scale, floor properties, room list). Pas de colonne droite — un seul objet (le plan), pas de séparation utile.
- **Rooms** : room list à gauche, room props + DSL + adjust à droite.
- **Design** : room list + candidates à gauche, room info + layout info + workstations à droite. Room list ajoutée au-dessus des candidates pour navigation cohérente avec Rooms.
- **Catalogue Editor** : inchangé.

**Justification** : Cohérence "je sélectionne à gauche, je vois le détail à droite" (pattern IDE). Floor est une exception car il n'y a qu'un objet à consulter.

**Impact** :
- `olm/templates/pattern_editor.html` : colonne droite ajoutée dans Rooms, room list ajoutée dans Design
- `olm/static/ingestion.js` : room list Design câblée (clic = changement de pièce sans changer d'onglet)
- `olm/static/floor_plan.js` : fpRenderCurrent appelle updateIngRoomList

---

## D-89 · Navigation UX — onglets, sous-onglets, hover, descriptions (2026-04-16)

**Décision** : Refonte UX de la navigation par onglets.

- Renommage Import → Floor, Review → Rooms (plus court, plus clair).
- Sous-onglets Catalogue : sub-tab-bar séparée (l'approche inline D-89 initiale a été abandonnée — trop de conflits visuels). Description italique à droite. Actif en gras + jaune.
- Zone hover des onglets étendue via pseudo-element `::before` (-8px top, -5px latéral) — pas de changement visuel, meilleure réactivité.
- Onglets Review/Design masqués (`display:none`) tant qu'aucun plan n'est chargé. Sections Scale/Floor Properties/Room List conditionnelles.
- Contraste onglets renforcé : actif #e8c46a, inactif #6a655c.
- Standard par défaut configurable (`default_standard` dans config.json + Settings).
- Dézoom limité au fitViewBox × 1.1.
- Double-click plan Import : détection par timer mousedown (400ms) au lieu du dblclick natif (cassé par re-render).

**Impact** :
- `olm/static/style.css` : couleurs onglets, pseudo-element hover, sub-tab-bar, descriptions italiques
- `olm/templates/pattern_editor.html` : renommage onglets, description sous-onglets
- `olm/static/init.js` : descriptions sous-onglets, handlers
- `olm/static/ingestion.js` : masquage conditionnel, dblclick timer
- `olm/static/config.js` : default_standard wiring
- `project/config.json` : `default_standard: "SITE"`

---

## D-88 · Drawing scale — échelle explicite du plan (2026-04-16)

**Décision** : L'échelle du plan est désormais un paramètre explicite `drawing_scale` (format `"1 : 100"`) combiné au `render_dpi` (DPI de rastérisation du PDF, 300 par défaut).

**Formule** : `cm_per_px = 2.54 × scale_number / render_dpi`

**Sources d'échelle par priorité** :
1. **Champ UI** `drawing_scale` dans Import (sous le sélecteur de plan) — saisi par l'utilisateur
2. **Estimation médiane** — si le champ est vide, le backend calcule cm_per_px à partir des surfaces m² et des bbox (formule existante). L'échelle estimée est rétro-affichée dans le champ en jaune (warning) avec mention "may be inaccurate".
3. **Fallback 0.5** — si aucune donnée disponible

**render_dpi** : configurable dans Settings > Floorplan (défaut 300). Correspond au DPI utilisé pour rastériser le PDF source en PNG.

Modifier le champ `drawing_scale` après import recalcule **immédiatement** les dimensions de toutes les pièces (via `ingState.scale` et `_updateRoomDims`), sans re-import.

**Justification** : La déduction par médiane des surfaces était le seul chemin et produisait des échelles incorrectes quand les bbox ne collaient pas exactement aux pièces. Un paramètre explicite élimine cette source d'erreur pour les plans dont l'échelle est connue.

**Impact** :
- `project/config.json` : ajout `drawing_scale` (string) et `render_dpi` (int) dans `ingestion`
- `olm/templates/pattern_editor.html` : champ Drawing scale dans Import + champ Render DPI dans Settings > Floorplan
- `olm/static/ingestion.js` : parsing, envoi au backend, recalcul live, suggestion inverse
- `olm/server/app.py` : routes OCR et Preprocessed acceptent `drawing_scale` + `render_dpi`
- `olm/ingestion/extract.py` : supporte `_override_cm_per_px` dans json_data

---

## D-87 · Solidification D-83 — overlay, state, port Python + tests (2026-04-16)

**Décision** : Correction des bugs résiduels de l'orientation canonique (D-83) et port de la logique en Python avec couverture de tests.

**Corrections** :
- **Overlay décalé 90°/270°** : ajout d'un `translate` compensatoire `(w-h)/2` lors de la rotation de l'overlay PNG pour corridor east/west. Sans cela, l'image était décalée d'une demi-pièce car les dimensions canonicalisées (w/h swappés) ne correspondaient plus au cadre de l'overlay original.
- **corridor_face perdu après Save** : `enterRoomAmendMode()` ne propageait pas `corridor_face` dans `state`, et `fpRoomAmendments` ne conservait pas `corridor_face` sur les données amendées. Résultat : après Save, la rotation overlay revenait à 0°.

**Port Python** :
- Module `olm/core/canonical.py` : `canonicalize_room()` et `decanonicalize_room()`, port fidèle de la logique JS (`floor_plan.js`). Réutilisable côté serveur (matching, export).
- 19 tests pytest (`olm/tests/test_canonical.py`) : round-trip pour les 4 orientations, dimensions, face mapping, exclusion zones, rooms minimales.

**Justification** : Les bugs étaient visibles sur toute pièce avec corridor east/west (≈50 % des pièces typiques). Le port Python garantit la cohérence JS/Python et permet des tests automatisés.

**Impact** :
- `olm/static/editor.js` : 3 lignes modifiées (translate overlay, state.corridor_face dans enterRoomAmendMode, corridor_face dans amendedRoom).
- `olm/core/canonical.py` : nouveau module.
- `olm/tests/test_canonical.py` : nouveau fichier de tests.

---

## D-86 · Portes principales/secondaires et orientation canonique (2026-04-15)

**Décision** : Classification des ouvertures en deux catégories et orientation canonique des pièces dans Review et Design.

**Catégories d'ouvertures** :

| Catégorie | Définition | Rôle |
|---|---|---|
| **Principale** | Ouverture/porte donnant sur le couloir (zone verte dans le PNG enhanced) | Définit le **sud** du référentiel canonique de la pièce |
| **Secondaire** | Ouverture/porte entre bureaux (zone blanche — pièce voisine) | N'affecte pas l'orientation canonique |

**Orientation canonique** :
- Dans les vues Review et Design, toute pièce est affichée avec la porte principale en bas (sud) et les fenêtres en haut (nord)
- L'utilisateur "entre" visuellement par le bas de l'écran
- Rotation purement visuelle (0°/90°/180°/270°) déduite de la face réelle de la porte principale sur le plan d'étage
- Coordonnées internes de la pièce inchangées

**Détection de la porte principale** :
- Mode Préprocessé : la face qui borde la zone verte (couloir) dans le PNG enhanced est la face principale
- Mode OCR : heuristique existante `corridor_face` (première face avec une porte détectée)
- Le champ `corridor_face` (déjà présent dans `DetectedRoom` et transmis au frontend) porte cette information

**Justification** : Les patterns sont conçus dans un référentiel canonique (couloir au sud, fenêtres au nord). L'affichage canonique garantit que le rendu visuel correspond toujours à cette convention, quelle que soit l'orientation réelle sur le plan d'étage. Pas besoin de rotation dans le pipeline de matching — seul le rendu est transformé.

**Impact** :
- `corridor_face` devient la source de vérité pour l'orientation
- Helper JS `computeCanonicalRotation(corridorFace)` retourne l'angle de rotation
- Wrapper `<g transform="rotate(...)">` appliqué au contenu des canvas `rvCanvas` et `fpCanvas`
- L'overlay (image du plan) est inclus dans le groupe transformé
- ViewBox ajusté après rotation si nécessaire

---

## D-61 · Navigation : 2 onglets principaux + sous-onglets (2026-04-03)

**Décision** : Restructuration de la navigation en 2 onglets principaux (Floor Plan / Office Layout) avec sous-onglets. Interface traduite en anglais.
**Justification** : Clarifier la navigation entre le workflow d'analyse par étage et l'édition de patterns.
**Impact** : `pattern_editor.html` restructuré, onglet actif en fond accent.

## D-62 · Exclusions périphériques réduisent les dimensions effectives de la pièce (2026-04-03)

**Décision** : Une exclusion qui longe un mur sur toute sa largeur ou profondeur réduit la dimension effective de la pièce pour la sélection des patterns candidats dans le matching. Exemple : `EXCL 0 0 400 30` sur une pièce de 400×500 → profondeur effective = 470 cm.
**Justification** : Permet de modéliser proprement un obstacle le long d'un mur (poteau, gaine, retrait) sans changer les dimensions brutes de la pièce. Le matching sélectionne alors des patterns plus petits, adaptés à l'espace réellement utilisable.
**Impact** : Fonction `effective_dimensions()` ajoutée dans `catalogue_matcher.py`, utilisée par `_fits_in_room()`.

## D-63 · Workflow d'amendement : Amend layout + Adjust room (2026-04-03)

**Décision** : Deux workflows d'amendement distincts dans Floor Plan / Matching :
- **Amend layout** : éditer la solution (blocs) pour une pièce donnée, sauver comme amendement local, possibilité de Discard.
- **Adjust room** : éditer la géométrie de la pièce (dimensions, ouvertures, exclusions), sauver et relancer le matching.
Les amendements sont stockés côté client (pas en base). Le nom de la pièce porte "(amended)" quand la géométrie a été modifiée. Un amendement de layout masque les candidats automatiques et affiche uniquement la solution amendée.
**Justification** : Séparer clairement l'édition du pattern source (Edit pattern → éditeur catalogue) de l'ajustement contextuel à une pièce (Amend layout / Adjust room). L'utilisateur peut corriger les erreurs d'ingestion (Adjust room) ou affiner le placement (Amend layout) sans polluer le catalogue.
**Impact** : `enterAmendMode()`, `enterRoomAmendMode()`, `fpAmendments`, `fpRoomAmendments`, `fpRematchRoom()` dans `pattern_editor.html`. Boutons : Adjust room | Edit pattern, Amend layout, Discard amendment.

## D-64 · Overlay raster du plan d'étage (2026-04-03)

**Décision** : Le plan d'étage raster est chargé comme entrée dans Floor Plan / Input (image + échelle px/cm). Il s'affiche en filigrane derrière la pièce dans le matching (checkbox Overlay + slider opacité) et automatiquement en mode Adjust room (opacité 30%). Par défaut désactivé en Floor Plan, activé en Room Amend.
**Justification** : Permet à l'utilisateur de vérifier visuellement que l'interprétation de chaque pièce est correcte en la superposant au plan réel. Si l'overlay ne colle pas, c'est l'ingestion qu'il faut corriger (via Adjust room), pas l'overlay qu'on déplace.
**Impact** : `state.overlay`, `window.fpOverlay` dans `pattern_editor.html`. Route `/test_floor_plan.png` pour le dev.

## D-65 · Settings : paramètres d'espacement éditables et persistés (2026-04-03)

**Décision** : Les 11 paramètres d'espacement (ES-01 à PS-04) de chaque standard sont éditables depuis un onglet Settings dans Office Layout. Les modifications sont sauvées immédiatement dans `spacing_overrides.json` (delta par rapport aux défauts) et prises en compte par le rendu et le matching sans redémarrage.
**Justification** : Permettre d'ajuster les contraintes d'espacement sans modifier le code Python. Les fallbacks hardcodés en JS ont été supprimés — tout passe par `CURRENT_SPACING` chargé depuis l'API.
**Impact** : `spacing_config.py` : `update_config()`, `reset_config()`, persistence JSON. `pattern_server.py` : POST `/api/spacing`. `pattern_editor.html` : onglet Settings, `renderSpacingSettings()`.

## D-66 · VISION_LLM_IO_SPEC : spécification entrées/sorties LLM Vision (2026-04-03)

**Décision** : Création de `specs/VISION_LLM_IO_SPEC.md` documentant le format JSON et DSL attendu en sortie du LLM Vision pour l'ingestion des plans d'étage. Couvre le système de coordonnées NW→SE, la structure pièce/fenêtres/ouvertures/exclusions, les cas particuliers (pièces en L, sens des portes) et les règles de validation.
**Justification** : Fournir un contrat clair pour le module d'ingestion futur. Réutilise le format JSON déjà consommé par le pipeline de matching et le DSL de `room_dsl.py`.
**Impact** : `specs/VISION_LLM_IO_SPEC.md`. La tâche TODO "Définir le prompt-type pour le LLM vision" est partiellement couverte.

---

## D-67 · Refactoring frontend : un canvas SVG par vue (2026-04-04)

**Décision** : Chaque vue (Editor, Review, Match) possède son propre élément SVG statique. Le canvas unique déplacé par appendChild entre les vues est supprimé.
**Justification** : Le mécanisme de déplacement DOM (moveCanvasToFloorPlan, moveCanvasToReview, moveCanvasToEditor) avec snapshot/restore de l'état éditeur était la source de 80% des bugs UX (état fantôme, pièce vide au retour, mode Adjust qui switch d'onglet). Les canvas séparés éliminent cette classe de bugs.
**Impact** : Les fonctions de rendu (render, zoomFit, updateViewBox, zoomIn, zoomOut) acceptent un paramètre optionnel targetSvg. Le CSS inline est externalisé, le JS est découpé en 4 modules. Le save/restore de l'état éditeur est simplifié (state-only, plus de DOM).

---

## D-68 · Navigation : 5 étapes workflow + Edit catalogue (2026-04-05)

**Décision** : L'interface passe de 2 onglets principaux (Floor Plan / Office Layout) à 6 onglets plats : ①Import floor plan, ②Review rooms, ③Identify merges, ④Design layout, ⑤Export results, + Edit catalogue (séparé visuellement). Chaque onglet workflow porte un numéro dans un cercle coloré. Un bandeau description dynamique s'affiche sous le header. Le catalogue a 3 sous-onglets : Card view, Grid view, Pattern editor.
**Justification** : Le workflow en 5 étapes rend le processus explicite et guidé. La séparation du catalogue (outil de création) du workflow (processus d'aménagement) clarifie les rôles. Les sous-onglets Cards/Grid remplacent le toggle précédent.
**Impact** : Tous les sélecteurs programmatiques (`.click()`) dans editor.js, floor_plan.js, catalogue.js, init.js migrés vers les nouveaux `data-tab`/`data-subtab`. Les gardes canvas/clavier inversées (autorisent uniquement Catalogue > Editor). L'onglet Merge est un placeholder.

---

## D-69 · Convention desk : width = face large, depth = avant-arrière (2026-04-05)

**Décision** : `DESK_W_CM` = 180 cm (largeur, face large gauche-droite), `DESK_D_CM` = 80 cm (profondeur, avant-arrière vers l'écran). Le mapping config.json → code est direct (pas d'inversion).
**Justification** : Aligne la convention interne sur la perspective de l'utilisateur assis au bureau. Les labels Settings "Desk width" et "Desk depth" correspondent à l'intuition humaine.
**Impact** : Toutes les formules de blocs dans pattern_generator.py inversées (eo = f(D), ns = f(W)). getDeskRects dans block_geometry.js adapté. _BLOCK_DESK_FACTORS dans app.py recalcule dynamiquement les dimensions de blocs quand desk width/depth changent dans les Settings.

---

## D-70 · Design tokens CSS et polices constantes (2026-04-05)

**Décision** : Toutes les valeurs visuelles (couleurs, tailles de police, espacements) sont définies comme CSS custom properties dans `:root` et utilisées partout via `var()`. Les tailles de police dans les SVG sont compensées par `zf = 1 / min(pxW/vbW, pxH/vbH)` pour rester constantes quel que soit le zoom ou la taille de la pièce.
**Justification** : Élimine les incohérences visuelles entre vues (font-size 10px ici, 12px là), les valeurs en dur répétées (6 blocs inline identiques pour les inputs Settings), et le problème de textes illisibles en zoom out ou trop gros en zoom in.
**Impact** : 7 niveaux de taille de police (`--fs-xs` à `--fs-room`), 7 niveaux d'espacement (`--sp-xs` à `--sp-page`), classes utilitaires (`.settings-input`, `.btn-toolbar`, `.btn-cancel`, `.edit-mode`). `window._currentZf` partagé entre `editor.js` et `block_svg.js`.

---

## D-71 · Rulers HTML fixes hors du SVG (2026-04-05)

**Décision** : Les graduations métriques (0m, 1m, 2m...) sont rendues en HTML (`<span>` positionnés absolument) dans un `ruler-box` div autour du SVG, et non plus comme éléments `<text>` dans le SVG.
**Justification** : Les labels SVG se déplaçaient avec le pan et changeaient de taille avec le zoom. Les labels HTML restent fixes aux bords du canvas et leur taille est constante.
**Impact** : `_ensureRulers(svg)` crée dynamiquement un `ruler-box` autour de chaque SVG (éditeur, Design, Review). `updateRulers(svg)` recalcule les positions via `svg.getScreenCTM()`. Les rulers sont mis à jour à chaque render, zoom et pan.

---

## D-72 · Renommage UI : Office Layout Studio (2026-04-05)

**Décision** : Le nom affiché dans l'interface est "Office Layout Studio" (OLS). Le package Python reste `olm`.
**Justification** : "Matching" est un terme technique interne qui n'apparaît pas dans le workflow utilisateur. "Studio" reflète l'aspect interactif de l'outil sans prétention.
**Impact** : Titre `<title>` et header modifiés. Package et imports inchangés.

---

## D-73 · OCR Tesseract : whitelist typée + désactivation dictionnaires + upscale x2 (2026-04-12)

**Décision** : Tesseract configuré avec whitelist de caractères (chiffres + tirets), dictionnaires désactivés, upscale x2 pour améliorer la reconnaissance des cartouches.
**Justification** : Améliorer la robustesse de l'extraction des pièces depuis le PNG d'origine face aux cartouches non-standard.
**Impact** : `extract.py`, paramètres OCR module.

---

## D-74 · Dual-mode ingestion : Mode OCR vs Mode Préprocessé (2026-04-12)

**Décision** : OLS accepte deux modes d'ingestion pour un plan d'étage donné :

1. **Mode OCR** (existant, par défaut) :
   - Entrée : un fichier PNG du plan brut comprenant cartouches
   - Traitement : ray-cast 3 phases + OCR optionnel cartouches
   - Sortie : liste des pièces détectées (width, depth, area, seed position)

2. **Mode Préprocessé** (nouveau) :
   - Entrées : 
     - Fichier JSON contenant liste des pièces (id, surface, seed position)
     - Fichier PNG overlay (plan officiel du bâtiment)
     - Fichier PNG "_enhanced" (PNG overlay avec cartouches supprimés, extérieur bleu RGB(135,206,235), couloirs vert RGB(193,247,179))
   - Traitement : parsing JSON directement, analyse du PNG enhanced pour affiner topologie
   - Sortie : liste des pièces (directement du JSON)

Le mode est sélectionné via une dropdown "Input Mode: [OCR | Preprocessed]" dans le panneau Settings (section "Ingestion").

**Justification** : 
- Mode OCR : gérer les plans existants sans prétraitement. OCR optionnel permet de critiquer visuellement les cartouches.
- Mode Préprocessé : réduire l'impact des artefacts OCR en utilisant des données structurées externes. Le PNG enhanced facilite l'analyse topologique (fenêtres/portes/couloirs). Cartouches préalablement supprimés en preprocessing.

**Impact** : 
- `olm/ingestion/extract.py` : deux fonctions parallèles (`extract_rooms_from_raster_ocr`, `extract_rooms_from_preprocessed`)
- `olm/server/app.py` : routes POST `/api/import/ocr` et `/api/import/preprocessed`
- `pattern_editor.html` : deux formulaires upload distincts (radio buttons ou onglets), refresh du rendu côté client
- `olm/core/types.py` : enum `IngestionMode = {"ocr", "preprocessed"}` dans `RoomSpec`
- Note : artefacts au niveau des arcs de portes dans le PNG enhanced requis étude spécifique (D-75)

---

## D-85 · Auto-détection OCR / Preprocessed par fichier — mode invisible à l'UI (2026-04-15)

**Décision** : Suppression du sélecteur de mode global (OCR / Preprocessed) dans l'UI et dans Settings. Le mode est désormais **détecté automatiquement par plan** selon la règle :
- PNG seul (pas de JSON compagnon) → mode **OCR**
- PNG + JSON compagnon **plus récent que le PNG** (`JSON.mtime > PNG.mtime`, strictement) → mode **Preprocessed** (= chargement rapide depuis JSON)
- PNG + JSON compagnon plus ancien que le PNG → le JSON est **considéré comme obsolète** → fallback **OCR** automatique (retoucher le PNG force une re-ingestion)

**Le mode est invisible à l'UI** : le dropdown Load présente une **liste plate** triée alphabétiquement, sans sections ni badges de mode. L'utilisateur clique sur un plan, OLS fait ce qu'il faut selon le `effective_mode` détecté.

Note : une fois R-11 (Save) implémenté, OLS écrira un JSON à côté de chaque PNG après la première sauvegarde. Le JSON deviendra donc la norme pour tous les plans déjà ouverts. La distinction OCR/Preprocessed perd sa pertinence UX — d'où le choix de la rendre invisible.

**Confirmation avant extraction OCR** : lorsque l'utilisateur sélectionne un plan dont le `effective_mode` est `"ocr"` (pas de JSON), afficher une `confirm()` navigateur avec un message type `"No JSON file found for this plan. Processing the input with Optical Character Recognition — this may take a few seconds. Continue?"`. Si l'utilisateur annule, l'extraction n'est pas lancée et la sélection est réinitialisée. En mode `"preprocessed"`, pas de confirmation — le chargement est rapide.

**Format JSON unique** : seul le format v3 est valide. Si un JSON est présent mais au format v2 (ancien), l'extraction échoue avec une erreur explicite. Pas de fallback silencieux ni de compatibilité descendante — voir `PREPROCESSED_JSON_SPEC.md`.

**Justification** :
- **Simplicité utilisateur** : le fichier "sait" son mode. Plus de toggle à se rappeler, plus d'erreur "j'ai choisi le mauvais mode".
- **Gestion naturelle des cas limites** : regénération d'un PNG → mtime change → JSON devient obsolète → refresh OCR automatique.
- **Alignement avec la règle doc unique source** : pas de divergence possible entre un "paramètre de mode" et l'état réel des fichiers.
- **Paramètre `plans_dir`** exposé dans Settings pour permettre à l'utilisateur de pointer vers un dossier externe de plans (usage multi-postes sur disque partagé).

**Impact** :
- `olm/server/app.py` : route `GET /api/plans` enrichie d'un champ `effective_mode` (`"ocr"` ou `"preprocessed"`) par plan, déduit de la présence et du mtime du JSON. `PLANS_DIR` lit désormais `ingestion.plans_dir` depuis `config.json` (avec fallback `"project/plans"`).
- `olm/static/ingestion.js` : suppression du `#ingModeSelect`, de `ingState.ingestionMode`, de `rebuildPlansDropdown(mode)`, de `renderImportPanel`. Le dropdown est peuplé une seule fois via `<optgroup>`. La fonction d'extraction route vers OCR ou Preprocessed selon `effective_mode` de l'option sélectionnée.
- `olm/templates/pattern_editor.html` : suppression de `#ingModeSelect` et de son label.
- `project/config.json` : ajout de la clé `ingestion.plans_dir`.
- `olm/ingestion/extract.py` : le parser v3 lève une `ValueError` explicite si les champs `code_line1` / `surface_line2` / `id_line3` (v2) sont détectés dans le JSON — message indiquant que seul le format v3 est supporté.

---

## D-84 · JSON v3 simplifié + règle "docs = source unique de vérité" (2026-04-14)

**Décision** : Refonte du format JSON Mode Préprocessé en v3, avec simplification radicale :

- ROOT : suppression de `plan_scale`, `dpi`, `scale_factor`, `rotation_angle`, `page_width_pts`, `page_height_pts`, `total_*`, `all_text_blocks[]`. Conservés : `file`, `building_id`, `floor_id`, `page_width_px`, `page_height_px`, `rooms[]`.
- Échelle `cm_per_px` **déduite côté OLS** à partir des surfaces m² détectées (médiane sur pièces mesurables), plus besoin de la fournir dans le fichier.
- `rooms` devient un **objet indexé par `room_id`** (plus un array), aligné avec `olm_state.rooms_state`. Lookup O(1), unicité garantie par le format, disparition du champ `id` redondant dans chaque valeur.
- **Orientation** : ajout de `north_angle_deg` au ROOT (angle entre haut de l'image et nord géographique, purement métadonnée) et de `canonical_top_face` par pièce (face image devenant le haut de la vue canonique D-83). `canonical_top_face` est auto-dérivé côté OLS depuis la face opposée à la porte principale, donc Save-enrichi uniquement. Valeurs discrètes `north`/`south`/`east`/`west` (pas d'angle libre — garde la rotation bbox orthogonale).
- Per room : aplatissement du cartouche en champs plats (plus les objets imbriqués `code_line1` / `surface_line2` / `id_line3`). Ajout de `seed_px` direct + `bbox_px` optionnel. Suppression de toutes les métadonnées typographiques (`font_size`, `font_name`, `color_rgb`) et du référentiel points PDF (`points_*`, `width_pt`, `height_pt`). Le champ `code` (ex: `"14"`) est également supprimé : c'est un filtre interne du Settings OLS, pas une donnée à persister.
- Ouvertures (`doors`, `openings`, `windows`) **imbriquées dans chaque room**, plus d'`associated_room` cross-référence.
- Schéma `door` scindé Input (`label_px` seul) vs Save (enrichi par OLS avec `face`, `offset_px`, `width_px`, `hinge_side`, `opens_inward`). Un fichier Save est un fichier Input enrichi — ré-import idempotent.
- `hits[]` (points d'intersection ray-cast) jamais persistés : recalculables.

En parallèle, ajout d'une **règle générale** dans `CLAUDE.md` : toute information utile à long terme vit **dans `docs/` uniquement**. L'utilisateur n'a rien à noter de son côté. Les fichiers du repo sont la source de vérité unique. En cas de conflit entre conversation et `docs/`, `docs/` fait foi.

**Justification** :
- Le format v2 exposait trop d'informations jamais consommées par OLS (métadonnées PDF, fontes, référentiel points), ce qui compliquait la production manuelle ou par un preprocessing tiers et rendait le ré-import fragile.
- La règle "docs = source unique" évite la divergence conversation ↔ spec et garantit qu'un nouveau contributeur (humain ou agent) peut se caler uniquement sur les fichiers du repo.
- La décision va de pair avec l'implémentation du bouton DEV "Export v3 JSON" (onglet Load, contour orange vif) qui sérialise l'état de l'OCR en v3 et permet de tester le Mode Préprocessé end-to-end sans preprocessing externe.

**Impact** :
- `docs/specs/PREPROCESSED_JSON_SPEC.md` réécrit en v3 (référence unique).
- `CLAUDE.md` enrichi d'une section "Documentation = source unique de vérité".
- `docs/TODO.md` : section "Générateur de plan de test" restructurée en 3 morceaux (A : bouton DEV implémenté, B : PNG enhanced manuel, C : script CLI futur).
- Bouton DEV "Export v3 JSON" ajouté dans `olm/templates/pattern_editor.html` (contour orange vif `#ff6600`) et handler `devExportV3Json()` dans `olm/static/ingestion.js`.
- Téléchargement navigateur direct (Blob), nom fichier = stem du plan courant.
- `extract_rooms_from_preprocessed()` dans `olm/ingestion/extract.py` **à adapter** pour le schéma v3 (tâche suivante) : parser les 3 champs plats `code`/`surface`/`id`, utiliser `seed_px` directement, skipper le ray-cast si `bbox_px` présent, skipper la détection porte si `face/offset_px/...` déjà enrichis.

---

## D-83 · Orientation canonique des pièces en Review et Design : couloir en bas, fenêtres en haut (2026-04-14)

**Décision** : Toute pièce affichée dans les onglets **Review** et **Design** est systématiquement orientée avec :
- La **porte d'entrée (couloir) en bas**
- Les **fenêtres en haut**
- Optionnellement, des fenêtres à gauche et/ou droite

L'utilisateur est toujours placé à la position "entrant par la porte", donc **"devant soi = haut de l'écran"**. La vue subit une rotation de 0°, 90°, 180° ou 270° (et éventuellement un miroir horizontal) par rapport au repère du plan d'origine pour respecter cette convention, quel que soit le placement réel de la pièce dans le plan.

Cette rotation est **purement visuelle** : les coordonnées internes (bbox, DSL pièce, exclusions, etc.) restent inchangées dans le repère natif du plan. Seul le rendu SVG applique une transformation.

**Justification** :
- **Cohérence cognitive** : l'utilisateur n'a pas à ré-interpréter mentalement l'orientation à chaque pièce, ce qui est particulièrement critique quand on enchaîne la revue ou le design de dizaines de pièces.
- **Aligne la vue sur l'intuition métier** : "devant soi" = là où on va poser les postes (vers les fenêtres), "derrière soi" = là où on entre. C'est l'angle naturel d'un aménageur.
- **Stabilise la lecture des patterns** : dans le catalogue, les patterns sont tous dessinés avec cette même convention (porte en bas, fenêtres en haut) — la correspondance pattern ↔ pièce devient directe.
- **Simplifie la comparaison de candidats** : comparer plusieurs solutions pour une même pièce ou une même solution appliquée à plusieurs pièces se fait désormais à orientation constante.

**Impact** :
- Nouveau helper côté rendering : `computeRoomViewTransform(room)` qui retourne la matrice de rotation/miroir à appliquer au rendu SVG, déduite de la position de la porte principale (face `bottom` cible) et des fenêtres (face `top` cible).
- `rvCanvas` (Review) et `fpCanvas` (Design) appliquent cette transformation au groupe racine du SVG.
- Les overlays (grille, règles, labels, pointeurs souris pour l'outil zone interdite) doivent être cohérents avec le référentiel transformé — ajustements à prévoir dans `editor.js` et `init.js`.
- Si une pièce a plusieurs portes, la porte côté couloir principal est choisie comme référence (heuristique à définir : porte avec le segment mural le plus long adjacent à un corridor, ou porte marquée `primary` dans le DSL si ajouté plus tard).
- L'outil Match dans Design continue de rendre les patterns dans la même orientation canonique — pas de rotation additionnelle à ce niveau.

**Non impacté** :
- Vue globale du plan dans Load : aucune rotation, le plan reste dans son orientation d'origine (on doit pouvoir le comparer visuellement au scan PNG).
- Export JSON / PDF : géométrie dans le repère natif du plan (pas la vue tournée).

---

## D-82 · R-01 finalisé — README racine + pyproject valide (2026-04-14)

**Décision** : Clôture du chantier R-01 (renommage OLO → OLM + séparation OSS/privé). `olm/README.md` est promu en `README.md` à la racine du dépôt. `pyproject.toml` corrigé : `build-backend = "setuptools.build_meta"` (l'ancienne valeur `"setuptools.backends._legacy:_Backend"` était invalide) et `readme = "README.md"`. Le `.gitignore` existant couvre déjà l'exclusion de `project/`, `docs/`, `solver_lab/`, `CLAUDE.md`, `CLAUDE_IMPLEMENTER.md` et `.claude/`.

**Justification** : Un README à la racine est la convention GitHub (page d'accueil du dépôt) ; avoir le README dans un sous-dossier casse l'affichage. Le build-backend erroné empêchait tout build wheel/sdist. Aucun autre fichier n'était à créer côté `.gitignore`.

**Impact** : R-01 entièrement cochée dans `TODO.md`. `pyproject.toml` devient buildable (`python -m build` fonctionnel). Aucun changement de code produit.

---

## D-81 · Cartouche OCR à 3 lignes — suppression N REEL / N THEO (2026-04-14)

**Décision** : Le format du cartouche Mode OCR passe de 5 lignes à **3 lignes**, alignées sur le format Mode Préprocessé :

```
Ligne 1 : code pièce     (ex: "14", paramétrable via room_code)
Ligne 2 : surface        (ex: "14.28 m2", suffixe " m2" explicite)
Ligne 3 : identifiant    (ex: "237", "12a", "1AB")
```

Les lignes **N REEL** (nombre de personnes réel) et **N THEO** (nombre théorique) qui figuraient dans l'ancien format 5 lignes sont **supprimées**.

**Justification** :

- **Non exploitées** : N REEL et N THEO ne sont consommées par aucun module du pipeline OLS (ni matching, ni rendu, ni export)
- **Source d'ambiguïté OCR** : des chiffres courts isolés (`"2"`, `"3"`) au milieu du cartouche créent des faux positifs quand Tesseract parse les numéros de pièce (D-73 a mitigé mais n'a pas éliminé le risque)
- **Unification avec le Mode Préprocessé** : le format Préprocessé est déjà à 3 lignes (`code_line1` / `surface_line2` / `id_line3`, cf. D-77). L'alignement simplifie le parsing, permet un code d'extraction commun entre les deux modes, et réduit la surface de maintenance
- **Pas de régression métier** : N REEL et N THEO étaient une information d'occupation que ni le matching ni l'utilisateur ne manipulent. L'aménagement est piloté par la surface et les standards d'espacement, pas par un nombre théorique d'occupants

**Impact** :

- `specs/INGESTION_HYPOTHESES.md` §H-09 : mise à jour du format cartouche et ajout d'une note historique sur l'ancien format 5 lignes
- `olm/ingestion/extract.py` / `test_comb.py` : algorithme de regroupement adapté (chercher 3 textes empilés au lieu de 5)
- Whitelist Tesseract + regex D-73 : déjà cohérentes (elles ciblent uniquement code / surface / id), vérification finale nécessaire
- Tolérance rétrocompatible : si l'OCR détecte 5 lignes (ancien plan), loguer un warning et ignorer les 2 lignes intermédiaires
- R-05 (TODO.md) : nouvelle sous-section « Mode OCR — Cartouche 3 lignes » avec 6 tâches
- Alignement des deux modes : Mode OCR et Mode Préprocessé partagent désormais la même sémantique de cartouche à 3 lignes, facilitant les évolutions futures (unification possible du parsing)

---

## D-80 · Zones interdites : promotion auto des petits artefacts + UX Review (2026-04-14)

**Décision** : Les zones interdites (`EXCL`) peuvent avoir **deux origines** convergeant vers la même structure de données et le même traitement aval :

**1. Promotion automatique en ingestion**

Un paramètre `min_size_artifact_cm2` (défaut : 2500 = 50×50 cm, éditable dans Settings > Ingestion) définit le seuil en dessous duquel un artefact détecté à l'intérieur d'une pièce est automatiquement promu en zone interdite plutôt que traité comme mur ou obstacle majeur.

Effet dans le pipeline :
- **Phase ray-cast / rectangle inscrit** : les pixels de l'artefact sont traités comme de l'intérieur libre — les rays les traversent et la bbox de la pièce peut englober un grand rectangle utile même s'il contient un poteau. Plus d'entaille dans la géométrie pour cause de petit obstacle.
- **Phase matching** : l'exclusion générée est prise en compte par `effective_dimensions()` (D-62) et par le scoring de couverture. Le matching **ne part pas de zéro** — il propose le meilleur pattern open space global, en ignorant les postes qui collideraient avec les poteaux. L'utilisateur lève les conflits résiduels via Amend layout en place (D-63).

Cas d'usage typique : **grand open space avec poteaux structurels**. Aujourd'hui ces pièces génèrent soit des bbox tronquées soit aucun matching ; demain elles bénéficient d'un pattern de référence + un amendement local sur les zones des poteaux.

**2. Amendement manuel en Review**

L'utilisateur peut ajouter / déplacer / supprimer des zones interdites à la souris dans l'onglet Review via un outil sélectionnable dans la toolbar (mode "Add forbidden zone", dessin par clic + drag). **Pas de redimensionnement souris** : pour modifier la taille, passer par le DSL pièce (ligne `EXCL x y w h` éditable). Cohérence avec la philosophie "édition visuelle simple, géométrie précise via DSL".

Cas d'usage : obstacles non détectés par l'ingestion (mobilier fixe, gaines, escaliers) ou correction d'une exclusion auto mal positionnée.

**Justification** :

Les plans réels contiennent régulièrement des obstacles internes (poteaux, gaines) qui ne doivent ni briser la détection du rectangle ni être ignorés en aménagement. Traiter ces obstacles comme des murs donne des bbox absurdes (morcelées) ; les ignorer donne des placements invalides (postes sur un poteau). La solution est d'introduire une classe intermédiaire — la zone interdite — avec un critère de taille pour décider automatiquement.

Le double mécanisme (auto + manuel) donne de la robustesse : l'auto couvre les cas courants sans intervention, le manuel rattrape les cas limites. La même structure `EXCL` à la fin garantit qu'un seul pipeline aval (matching, rendu, export) traite les deux cas de façon identique.

Le choix "pas de redimensionnement souris" est délibéré : la souris est excellente pour positionner et supprimer, médiocre pour dimensionner précisément. Le DSL reste la source de vérité pour les dimensions exactes — l'UI souris n'y apporterait qu'une imprécision déroutante.

**Impact** :

- `project/config.json` + Settings > Ingestion : nouveaux paramètres `min_size_artifact_cm2` (2500) et `artifact_promotion_enabled` (true)
- Pipeline ingestion (`olm/ingestion/extract.py`) : la phase de détection des artefacts intérieurs applique le seuil et émet soit une `EXCL`, soit un obstacle bloquant les rays
- Pipeline rectangle inscrit (`RASTER_EXTRACTION_SPEC.md` §7.1) : les pixels promus en `EXCL` sont considérés comme intérieur libre pendant la recherche du rectangle utile
- `catalogue_matcher.py` : `effective_dimensions()` (D-62) déjà compatible — pas de changement requis, juste validation
- UI Review : outil souris "Add forbidden zone" (toolbar), sélection + Delete, pas de redimensionnement souris, redim via DSL
- UI Match : badge visuel sur les pièces avec `EXCL` promues auto (signalement "poteau détecté, vérifier")
- Spec DSL pièce : marqueur optionnel `EXCL auto` pour tracer l'origine (auto vs manuel) — utile pour le round trip D-78 et le reset utilisateur
- R-04 Review (TODO.md) : clarification de l'outil souris (pas de redimensionnement)
- R-05 (TODO.md) : nouvelle sous-section « Zones interdites — promotion automatique des petits artefacts » avec les tâches d'implémentation

---

## D-79 · Ray-casting context-aware en Mode Préprocessé (2026-04-14)

**Décision** : En Mode Préprocessé, le pipeline ray-cast devient **context-aware** — il exploite simultanément l'image binarisée et des informations sémantiques externes pour produire un résultat plus robuste. Deux mécanismes indissociables :

**1. Zones de transparence de porte via `doors[]`**

Pour chaque porte du JSON v2 (`doors[]` avec `associated_room`), construire un masque rectangulaire centré sur `(pixels_x, pixels_y)`, de dimensions `(width_px, height_px)` + marge. Les pixels à l'intérieur de ce masque sont **ignorés** par le ray-cast : les rays traversent la porte au lieu de s'arrêter sur le trait d'huisserie ou l'arc de cercle.

Effet : le ray s'arrête sur le vrai mur derrière la porte — mur de la pièce mitoyenne, frontière couloir, ou façade — et le segment couvert par le masque **est** automatiquement classifié comme ouverture (pas de détection d'arc a posteriori).

**2. Arrêt sur frontières sémantiques (blanc↔vert et blanc↔bleu)**

Le PNG enhanced introduit deux couleurs sémantiques au-delà du binaire noir/blanc :
- **Vert RGB(193,247,179)** : couloirs
- **Bleu ciel RGB(135,206,235)** : extérieur du bâtiment (et cours intérieures)

Le ray-cast s'arrête quand il rencontre l'un de ces trois états non-blancs (noir, vert, bleu). La **couleur d'arrêt qualifie immédiatement la nature du mur rencontré** :
- Noir → mur plein ou mitoyen
- Vert → mur sur couloir
- Bleu → mur façade (candidat fenêtre — analyse de texture uniquement sur ces segments)

**Justification** :

Le ray-cast pur décrit dans `RASTER_EXTRACTION_SPEC.md` §4–10 reste valide pour le Mode OCR, mais souffre de deux faiblesses sur lesquelles des heuristiques coûteuses ont été construites :
- Détection des arcs de porte a posteriori (§6.5) — fragile si l'arc est partiellement effacé (D-75)
- Détection de la face couloir (§7.3) — nécessite un flood fill et des heuristiques de connectivité

Le Mode Préprocessé dispose d'informations que le Mode OCR n'a pas (positions de portes du PDF source, coloration sémantique de l'outil de preprocessing). Les exploiter explicitement comme inputs du ray-cast — plutôt que comme étapes de classification post-hoc — simplifie radicalement le pipeline, neutralise D-75 en Mode Préprocessé, et rend la détection de la face couloir triviale et 100 % fiable. Les cours intérieures sont gérées gratuitement puisque peintes en bleu comme l'extérieur.

Le pipeline context-aware **enrichit** le ray-cast plutôt que de le remplacer : c'est toujours un ray-cast, avec des règles d'arrêt enrichies et un masque de transparence préalable. Aucune nouvelle primitive géométrique, uniquement une lecture plus riche de l'image.

**Impact** :

- `docs/specs/RASTER_EXTRACTION_SPEC.md` : section 11bis ajoutée (Ray-casting context-aware) décrivant les 4 états sémantiques, la règle d'arrêt enrichie, et le schéma des deux pipelines (pur vs context-aware)
- R-05 (TODO.md) : tâches d'implémentation déjà présentes dans la section « Exploitation avancée du PNG enhanced et du JSON v2 »
- Sections 6.5 et 7.3 inutilisées en Mode Préprocessé (toujours utilisées en Mode OCR)
- Section 6.6 (texture fenêtre) conservée mais restreinte aux segments pré-filtrés par la couleur bleu
- Les constantes RGB(193,247,179) et RGB(135,206,235) deviennent des paramètres critiques de l'ingestion — à exposer dans Settings > Ingestion pour le Mode Préprocessé

---

## D-78 · Navigation 3 onglets + Full round trip via olm_state (2026-04-14)

**Décision** : Deux changements d'architecture liés qui remplacent partiellement D-68 :

**1. Navigation simplifiée en 3 onglets plats** (au lieu de 5 étapes workflow) :

```
Floor plan  │  Office layout  │  Export     ‖    Catalogue [Cards | Grid | Editor]
```

- **Floor plan** regroupe Import + Review + Merge (sous-onglets internes)
- **Office layout** regroupe Design + Match (sous-onglets internes)
- **Export** reste autonome
- **Catalogue** séparé visuellement (inchangé)

Suppression de la numérotation pédagogique (cercles colorés) et des descriptions d'onglets par étape.

**2. Full round trip via `olm_state` dans le JSON** :

L'outil devient stateful. À chaque export, les sélections et amendements sont **sauvegardés dans le JSON v2** du plan sous une clé `olm_state` (extension non-breaking). À la réouverture, le système réhydrate l'état au lieu de recalculer un delta automatique.

- **Identification du plan** : nom du fichier PNG (pas de hash)
- **Clé de pièce** : `id_line3.text` (ex: `"237"`, `"22K"`)
- **Persistance** : clé `olm_state` dans le JSON v2 (Mode Préprocessé) ou sidecar JSON à côté du PNG (Mode OCR)
- **Politique de diff à la réouverture** :
  - Pièces présentes dans les deux → réhydratation des sélections/amendements
  - Pièces nouvelles (dans le JSON, absentes de `olm_state`) → badge "Nouveau", candidat automatique
  - Pièces orphelines (dans `olm_state`, absentes du JSON) → warning listant les disparues, choix utilisateur (nettoyage ou conservation)
- **Reset** : bouton par pièce pour supprimer son état et revenir au candidat auto

Structure (extension non-breaking du format v2) :
```json
{
  // ... champs v2 existants ...
  "olm_state": {
    "version": 1,
    "plan_file": "test_floorplan3.png",
    "last_saved": "2026-04-14T10:32:00Z",
    "rooms_state": {
      "237": {
        "selected_pattern_id": "B2_AFNOR_4",
        "layout_amendments": [...],
        "geometry_amendments": {...},
        "forbidden_zones": [...]
      }
    },
    "merges": [ {"ids": ["238", "239"], "merged_name": "238+239"}, ... ]
  }
}
```

**Justification** :

Sur le renommage 3 onglets : la structure 5 étapes (D-68) était pédagogique mais trop rigide. Trois onglets reflètent mieux les deux domaines métier réels (préparation du plan vs aménagement) + l'export comme action finale, et permettent une navigation plus libre pour un utilisateur régulier.

Sur le full round trip : le workflow actuel perd tout le travail entre deux imports, ce qui est inacceptable pour un usage réel. Persister l'état dans le JSON qui accompagne le plan garantit l'autonomie totale (pas de DB, pas de state serveur), reste cohérent avec l'esprit 100 % local de l'outil, et transforme l'export en simple sauvegarde. Le JSON devient source de vérité — simple, robuste, portable.

**Impact** :

- R-08 (TODO.md) refondu pour la nav 3 onglets — remplace ses tâches initiales
- R-11 (TODO.md) nouveau : 11 sous-tâches pour le round trip
- `PREPROCESSED_JSON_SPEC.md` : section `olm_state` à documenter
- Code frontend (init.js, editor.js, floor_plan.js, catalogue.js) : refonte sélecteurs `data-tab`/`data-subtab`
- Code backend : `merge_state_into_rooms()` + `build_olm_state()` + enrichissement des routes import/export
- D-68 partiellement obsolète (le workflow 5 étapes est remplacé ; les autres décisions de D-68 restent valides)

---

## D-77 · Format JSON preprocessé v2 — structure rooms/doors (2026-04-14)

**Décision** : La structure JSON du Mode Préprocessé évolue vers une forme v2 qui remplace D-76 :

- Clé principale `cartouches` → `rooms`
- Plus de wrapper `center` : chaque room contient directement `code_line1`, `surface_line2`, `id_line3`
- Chaque ligne porte ses propres métadonnées typographiques (`font_name`, `color_rgb`)
- `scale` → `scale_factor` (renommage, sens inchangé = dpi/72)
- Nouveaux champs ROOT : `total_text_blocks`, `total_rooms`, `total_doors`, `all_text_blocks[]`, `doors[]`
- Le centre du cartouche n'est plus fourni explicitement — OLS le calcule : `cx = moyenne(pixels_x des 3 lignes)`, `cy = surface_line2.pixels_y`

Exemple room v2 :
```json
{
  "code_line1":    {"text": "14",       "pixels_x": 1234, "pixels_y": 560, ...},
  "surface_line2": {"text": "14.28 m2", "pixels_x": 1234, "pixels_y": 575, ...},
  "id_line3":      {"text": "237",      "pixels_x": 1234, "pixels_y": 590, ...}
}
```

**Justification** : Le nouveau format est plus proche de la structure brute extraite par l'outil de preprocessing (pas de wrapper artificiel). Inclut les portes (`doors[]`) pour exploitation future (déduction des ouvertures) et tous les blocs texte PDF (`all_text_blocks[]`) pour analyses futures (cotes, labels).

**Impact** :
- `olm/ingestion/extract.py` : `extract_rooms_from_preprocessed()` refactorisée + helper `_room_center_from_lines()` ajouté
- `docs/specs/PREPROCESSED_JSON_SPEC.md` : réécrite pour v2 (section historique des versions ajoutée)
- `room_id` primaire = `id_line3.text` (plus de fallback vers `cartouche.number`)
- Validation : `rooms` (liste), chaque room doit avoir `code_line1`/`surface_line2`/`id_line3` avec `pixels_x/y`
- `doors[]` loggées mais non exploitées v1
- D-76 marquée obsolète (remplacée par D-77)

---

## D-76 · Format JSON cartouches pour Mode Préprocessé (2026-04-12) [OBSOLÈTE]

> ⚠️ Remplacée par D-77 (2026-04-14). Conservée pour historique.

**Décision** : Le JSON d'entrée du Mode Préprocessé suit une structure "cartouches" (et non "rooms") avec métadonnées globales du PDF + liste de cartouches détectés. Le facteur cm réel par pixel est calculé via `cm_per_px = (2.54/dpi) * plan_scale_ratio` — le champ `scale` (= dpi/72) n'est PAS utilisé pour cette conversion (c'est un facteur interne PDF→raster).

Structure principale :
```json
{
  "file", "building_id", "floor_id",
  "plan_scale": "1:N",     // N = ratio plan/réel
  "dpi": 300,              // convention PNG fournis
  "scale": 4.167,          // dpi/72 (non utilisé pour cm/px)
  "rotation_angle": 0,
  "page_width_pts", "page_height_pts",
  "page_width_px", "page_height_px",
  "total_cartouches",
  "cartouches": [
    {
      "number": "916",
      "center": {
        "number", "line1", "line2", "line3",
        "pixels_x", "pixels_y",
        "width_px", "height_px", "font_size"
      },
      "components": []
    }
  ]
}
```

Chaque `lineN` contient `{text, pixels_x, pixels_y, font_size}`. `line1.text` = code pièce (ex: "14"), `line2.text` = surface ("14.28 m2"), `line3.text` = numéro de pièce.

**Justification** : Aligne OLS sur le format produit par l'outil de preprocessing externe. Utiliser `dpi+plan_scale` plutôt que `scale` garantit une conversion correcte (scale=dpi/72 est un facteur interne au rendu PDF, pas un ratio géométrique).

**Impact** :
- `olm/ingestion/extract.py` : `extract_rooms_from_preprocessed()` refactorisée (helpers `_parse_plan_scale_ratio`, `_cm_per_px_from_metadata`, `_parse_surface_m2`)
- `docs/specs/PREPROCESSED_JSON_SPEC.md` : spec complète créée
- Validation : clé `cartouches`, liste, `center.pixels_x/y` obligatoires
- Bbox : carré centré sur seed, côté = √(surface_m2 × 10000) / cm_per_px
- Convention : PNG fournis en 300 DPI par défaut

---

## D-75 · Artefacts arc de porte dans PNG enhanced (TBD)

**Décision** : À définir après analyse — le preprocessing supprime les cartouches mais introduit des artefacts au niveau des arcs de porte (disparition partielle).

**Justification** : Comprendre la cause des artefacts pour adapter le post-traitement ou la stratégie de detection wall-tracing.

**Impact** : Tâche R-05 « Robustesse aux arcs de porte » intègre l'analyse de ces artefacts.

**Décision** : L'appel Tesseract dans `find_seeds_by_ocr` utilise systématiquement :
- `tessedit_char_whitelist` couvrant exactement les 3 types de tokens attendus dans les cartouches :
  - Code pièce : 2 chiffres + lettre optionnelle → `"14"`, `"14c"`, `"12d"`
  - Numéro de pièce : 1-3 chiffres, ou 2 chiffres + lettre, ou 1 chiffre + 2 lettres → `"916"`, `"12a"`, `"1AB"`
  - Surface : nombre décimal → `"14.28 m2"`
  - Whitelist résultante : `0123456789.,abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ ` (espace inclus pour `m2`)
- `load_system_dawg=0` + `load_freq_dawg=0` — désactivation explicite des dictionnaires anglais/fréquents. La whitelist seule est insuffisante quand des lettres sont présentes : Tesseract continue à biaiser les résultats vers des mots de dictionnaire.
- Upscale x2 (LANCZOS) avant OCR, coordonnées TSV divisées par 2 en sortie
- `--oem 3` explicite, `--psm 11` conservé

**Algorithme de matching room number** : les candidats sont triés par longueur décroissante puis distance croissante (priorité aux tokens longs). Cela évite qu'un token court comme `"2"` (extrait de `"m2"`) batte un vrai numéro `"916"` simplement parce qu'il est plus proche dans le cartouche.

**Justification** : La whitelist restreint l'espace de reconnaissance aux caractères effectivement présents dans les cartouches. La désactivation des dictionnaires supprime les corrections orthographiques parasites. L'upscale améliore la reconnaissance sur le texte de petite taille (10-20 px → 20-40 px), conforme aux recommandations Tesseract (≥ 300 DPI). Les regex `_RE_ROOM_CODE`, `_RE_ROOM_NUMBER`, `_RE_SURFACE` documentent les patterns attendus et servent à filtrer/classer les tokens en post-traitement.

**Impact** : 28 pièces correctement détectées sur `test_floorplan3.png`, numéros et surfaces exacts. Constantes `TESSERACT_UPSCALE`, `TESSERACT_CHAR_WHITELIST` et regex `_RE_*` définies au niveau module dans `test_comb.py`.
