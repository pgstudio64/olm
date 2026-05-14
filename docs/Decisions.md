# Decisions.md — OLM

Journal des décisions de conception du projet OLM (Office Layout Matching).
Chaque entrée indique la date, la décision, la justification et l'impact.

> **Note** : Décisions historiques (D-01 à D-60, architectures antérieures CP-SAT et refactoring) archivées dans `Decisions_archive.md`.

---

## D-190 · Split app.py en services — P1.2 + P1.5 (2026-05-14)

**Decision** : `app.py` 2184 -> 675 l. (-69 %). Creation de `olm/server/services/` avec 5 modules : `config_service` (372 l.), `serialization` (93 l.), `catalogue_service` (269 l.), `matching_service` (212 l.), `ingestion_service` (968 l.). Routes Flask pures + delegation dans `app.py`. P1.5 integre : 12 `traceback.print_exc()` remplaces par `logger.exception()`.

**Justification** : preparation a l'industrialisation (D-188), modularite, testabilite par service, navigation facilitee. Le monolithe `app.py` (55 fonctions, 40 routes, 6 roles melanges) etait identifie comme dette critique par l'audit 2026-05.

**Impact** : `olm/server/app.py`, `olm/server/services/*` (nouveau), `olm/tests/conftest.py` (monkeypatch mis a jour). Aucune modification de contrat API (URL, payload, reponse). 202 tests pass, 40/40 routes preservees, 0 cycle d'import, smoke-test UI OK (Floor, Room, Rescan All, Office, Save). `app.py` reste a 675 l. (cible 500 indicative non atteinte) : le surplus est de la plomberie Flask non factorisable sans coupler les services a Flask. Cible revisee acceptee. Reference : ARCHITECTURE_TARGET.md par. 6.1.

---

## D-189 · P1.1 Renommage test_comb + extraction wall_classify (2026-05-14)

Decision : casser le cycle d'import bidirectionnel extract.py <-> test_comb.py. Trois actions :
1. Extraction de `WallSegment`, `_classify_wall_direct` et ses helpers dans `olm/ingestion/wall_classify.py` (nouveau module sans dependance vers extract ni comb_detection).
2. Renommage `test_comb.py` -> `comb_detection.py` (le nom test_comb pretait a confusion avec les vrais tests dans olm/tests/).
3. Suppression de `def main()`, `draw_debug_all`, `draw_debug_single` (redondants avec dev_viewer.py, utilisaient print()).

Justification : AUDIT_2026-05 / ARCHITECTURE_TARGET identifient ce cycle comme P1.1 (priorite haute). Le renommage clarifie le role du module (detection comb, pas test).

Impact : 10 sites d'import mis a jour (extract.py, app.py x6, test_extract.py, dev_viewer.py). Aucune modification fonctionnelle.

---

## D-188 · Cible produit : interne mono-utilisateur, bonne robustesse (2026-05-14)

Décision : OLM reste un produit interne mono-utilisateur, déployé sur le poste d'un utilisateur métier. Pas de multi-user, pas d'auth réseau, pas d'HTTPS, pas d'i18n, pas d'a11y, pas de bundling Windows autonome. Cible robustesse « bonne » (pas critique) : le cycle de modifications reste standard, les fixes se déploient comme aujourd'hui.

Verrou mono-utilisateur ajouté : empêche deux sessions simultanées d'écrire en conflit sur les mêmes plans. Implémentation par état en mémoire Flask (donc reset automatique au redémarrage, pas de blocage post-crash), cookie session, page « OLM déjà en cours d'utilisation » avec bouton « prendre le contrôle », idle timeout auto-release.

Justification : besoin métier identifié. Un outil interne sur poste utilisateur, pas un produit livrable.

Périmètre robustesse retenu (Phase 2, ~40 h après P1) :
- Verrou mono-utilisateur (~4 h).
- Validation jsonschema à l'import JSON v3 (~12 h).
- Écritures atomiques temp+rename + backup .bak sur save (~5 h).
- MAX_CONTENT_LENGTH Flask + whitelist MIME upload (~2 h).
- Logger Python standard avec RotatingFileHandler (~6 h).
- Endpoint `/health` (~2 h).
- GitHub Actions basique : ruff + pytest au push (~3 h).
- USER_GUIDE.md workflow utilisateur (~6 h).

Hors périmètre : flask-login, gunicorn, HTTPS, job queue, PyInstaller, i18n, a11y, ZIP diagnostic, JSON logs structurés. Réévaluables si le besoin métier évolue (ex. passage à 5+ utilisateurs).

Cible couverture tests : 60 % sur olm/core et olm/server (vs 50 % actuel), pas 80 %.

Impact : roadmap Phase 2 dans `AUDIT_2026-05-v2.md` § 5.3 (à mettre à jour) et `TODO.md`.

Référence : `AUDIT_2026-05-v2.md` § 6 scénario A recalibré.

---

## D-187 · Source unique binarize_threshold = 110 (2026-05-14)

Valeur terrain (config.json ingestion.binarize_threshold) = 110, defauts modules = 140. Alignement : detection_config.py default 140 → 110 (avec docstring expliquant que le defaut sert uniquement aux tests et CLI — en prod le serveur charge l'override depuis config.json), app.py fallback _get_default_threshold 140 → 110, config.js fallback UI 140 → 110. extract.py lit _DCFG.binarize_threshold (suit le default, inchange). test_comb.py deja None (D-186). Source unique : config.json > detection_config.py default. Aucun changement comportemental en production (le chemin serveur lit toujours config.json via overrides).

Impact : detection_config.py, app.py, config.js.

---

## D-186 · Suppression defauts px en dur test_comb.py (2026-05-14)

14 constantes px module (`BINARIZE_THRESHOLD`, `COMB_STEP_PX`, `MAX_RAY_PX`, `CARTOUCHE_MARGIN_PX`, `MIN_DOOR_ARC_HITS`, `MIN_OBSTACLE_WIDTH_PX`, `MIN_PILLAR_SIZE_PX`, `MAX_PILLAR_SIZE_PX`, `DOOR_PROBE_PX`, `DOOR_GROUP_GAP_PX`, `WALL_MARGIN_PX`, `COARSE_STEP_PX`, `RAY_MARGIN_PX`, `SNAP_SEARCH_PX`) remplacees par `None`. Nouveau guard `_ensure_config_applied()` leve `RuntimeError` si `_apply_detection_config` n'a pas ete appelee. Guard injecte dans `detect_room`, `find_seeds_by_ocr`, `comb_collect_hits`, `expand_door_arcs`, `binarize`. Default args `binarize(threshold=)`, `ray_single(max_dist=)`, `snap_rect_to_walls(search_px=)` passes a `None` avec resolution lazy. `extract_all_rooms`: lecture `BINARIZE_THRESHOLD` deplacee apres `_apply_detection_config`. Aucun changement comportemental — uniquement durcissement du chemin de configuration. Finding 🔴 audit constantes-rustines 2026-05-13.

Impact : `olm/ingestion/test_comb.py` uniquement.

---

## D-185 · UX fixes : grille, overlay -SD, zoom clamp Room (2026-05-14)

5 corrections UX. (1) Grille dots 10cm : bornes alignees sur step1m pour couvrir le meme espace que les lignes 1m ; rayon minimum proportionnel au viewport (`vb.w/1000`) pour garantir ~1.2px a l'ecran (etait invisible en Room et Floor a zoom out). (2) Overlay Room : utilise `planPathEnhanced` (PNG -SD) au lieu du PNG brut pour fpOverlay. (3) Toggle "Hide detection colors" aligne a gauche dans Settings. (4) `hideDetectionColors` default `false` (suppression lecture localStorage au demarrage). (5) Zoom in Room/Office clampe a 500 cm (5m) de largeur visible minimum.

Impact : `render_shared.js`, `ingestion.js`, `editor.js`, `store.js`, `pattern_editor.html`.

---

## D-184 · Centralisation constantes-rustines dans detection_config (2026-05-14)

Audit de robustesse : 30 constantes empiriques identifiees, 9 critiques, 14 moderees. Actions : (1) 7 nouveaux champs dans `DetectionConfigCm` (`pillar_group_gap_cm`, `arc_monotonicity_ratio`, `wall_thickness_max_cm`, `ocr_min/max_surface_m2`, `text_search_dist_cm`) + 4 champs derives dans `DetectionConfigPx`. (2) Deduplication : `binarize()` default 180→140 aligne config, `ORTHO_ANGLE_TOLERANCE` importe depuis config, `max_absorb_px` 120→60 aligne config. (3) `gap_threshold=3*step_px` → `pillar_group_gap_px` config, `len(group)<3` → `min_pillar_hits` config, `0.7` monotonie → `arc_monotonicity_ratio` config. (4) Grades A-F en tableau `CIRCULATION_GRADES`, constantes nommees `MIN_ISOLATED_AREA_M2`/`LARGE_ISOLATED_AREA_M2`. (5) Suppression code mort (`_group_pixels`, definitions dupliquees DOOR_PROBE/GROUP_GAP/WALL_MARGIN). Aucun changement de comportement a scale 0.5 cm/px.

Impact : `detection_config.py`, `test_comb.py`, `extract.py`, `circulation_analysis.py`.

---

## D-183 · Hide detection colors : general + Room/Office (2026-05-13)

Le toggle "Hide detection colors" passe de la section Developer a la section Rendering (parametres generaux). Desormais applique a Floor, Room et Office (pas seulement Floor). Le state `planUrlClean` est utilise dans `floor_plan.js` pour construire l'overlay Room et Office quand le toggle est actif. Le changement du toggle declenche un refresh immediat via `fpRenderCurrent()`. Default false, persiste via localStorage.

Impact : `pattern_editor.html` (checkbox deplacee), `floor_plan.js` (2 overlays), `config.js` (refresh Room/Office).

---

## D-182 · Minimap tailles adaptatives viewport (2026-05-13)

3 tailles de minimap (S/M/L) derivees de MAX_DIM et COLLAPSED_RATIO, sans constantes supplementaires. La paire active (collapsed/expanded) est choisie selon la hauteur du viewport : fenetre <= 2*MAX_DIM → paire (S, M), fenetre > 2*MAX_DIM → paire (M, L). Recalcule a chaque rendu, adaptatif au resize.

Impact : `minimap.js` (SIZE_S/M/L, VIEWPORT_THRESHOLD, _sizePair).

---

## D-181 · Minimap schematique Room/Office (2026-05-13)

Miniature du plan d'etage affichee dans le coin haut-gauche des vues Room et Office. Montre la position de la piece courante (rectangle orange) dans le contexte de l'etage. Fond noir avec 3 tons de gris (pieces sombres, exterieur moyen, couloir clair) depuis le PNG -SD. Contours 1px blancs des pieces detectees. Fenetres de la piece courante en bleu (1px plie, 3px deplie). Clic pour basculer entre taille pliee et depliee. Pre-traitement image au chargement du plan (cache). Conversion canonique→absolu via `rotateRectInv` pour les fenetres.

Impact : nouveau fichier `olm/static/minimap.js`, `pattern_editor.html` (2 canvas), `style.css` (.minimap), `editor.js` (hook _minimapRefresh), `floor_plan.js` (_minimapRefresh impl + plan -SD URL).

---

## D-180 · Filtre ouvertures impossibles (2026-05-13)

Quand des ouvertures couvrent plus de `max_opening_face_ratio` (defaut 0.7) d'une face non-couloir, sonde l'image binaire au-dela du bbox pour verifier si un mur existe derriere. Si majorite des sondes trouvent un mur → artefact ray-cast → suppression. Sinon vrai passage → conservation. Nouveau parametre `max_opening_face_ratio` dans `DetectionConfigCm`. Applique dans `extract_room_features` (param `corridor_face`) et `extract_rooms_from_preprocessed` (post color-detection). Frontend envoie `corridor_face` dans les payloads re-analyze. Tests unitaires 10/10.

Impact : `detection_config.py`, `extract.py` (_filter_impossible_openings), `app.py` (endpoints + overrides), `init_rvtool.js`, `ingestion.js`, `test_impossible_openings.py`.

---

## D-179 · Mode dev (--dev) et separation parametres dev/metier (2026-05-13)

Option `--dev` au lancement du serveur (`python -m olm.server.app --dev`). Active les outils developpeur : toggles Seeds/V-Rays/H-Rays/Rooms/Windows/Doors/Openings dans Import, Seeds/V-Rays/H-Rays dans Review, boutons Check orient et Diag. Parametres Settings separes : section "Developer" dans Floor (Hide detection colors, OCR Detection, Standard colors). Elements dev marques `.dev-only` (CSS) ou gardes JS (`APP_CONFIG.dev_mode`). Apparence distincte `.dev-ctrl` (bordure pointillee bleue).

Impact : `app.py` (argparse, DEV_MODE, /api/config), `config.js`, `style.css`, `pattern_editor.html`, `editor.js`.

---

## D-178 · Affichage plan sans couleurs de detection (2026-05-13)

Toggle "Hide detection colors" dans Settings > Floor > Rendering. Remplace les pixels bleu (exterior) et vert (corridor) par du blanc sur l'image affichee. Generation lazy au premier toggle ON via canvas + toBlob + createObjectURL. Detection inchangee (utilise les fichiers serveur originaux). Preference persistee en localStorage.

Impact : `ingestion.js` (_buildCleanPlanUrl), `config.js` (toggle binding), `store.js` (state), `pattern_editor.html` (checkbox).

---

## D-177 · Detection fenetre exterior par scan directionnel avec seeds (2026-05-13)

Remplace `_face_borders_color` (bande fixe 50 cm) par `_face_is_exterior` dans `extract_room_features`. Nouveau algo : pour chaque face, scanne rangee par rangee vers l'exterieur (distance max = dimension perpendiculaire du bbox). Si >30% de pixels bleus trouves avant tout seed d'une autre piece, la face est exterieure. Regle le probleme des fenetres non detectees quand la bbox est eloignee de la zone bleue (rangements exclus, murs epais).

Impact : `extract.py` — nouvelle fonction `_face_is_exterior`, remplace l'appel a `_face_borders_color` dans le flux fenetre.

---

## D-176 · Clustering multi-portes par face (2026-05-13)

`_detect_doors_on_face` peut desormais detecter N portes sur une meme face. Quand `arc_too_wide` est declenche (arc >80% de la face), les arc hits sont clusterises par gaps > `door_width_px / 2`. Chaque cluster est valide independamment (profil monotone, wall opening). Pas de nouvelle constante — reutilise `door_width_px`. Resout le cas de la piece 914 (2 portes sur face nord).

Impact : `test_comb.py` — `_detect_doors_on_face` restructure avec boucle sur clusters.

---

## D-175 · Suppression seed_fallback portes (2026-05-13)

Le mecanisme `seed_fallback` dans `_detect_doors_on_face` creait une porte fantome quand un seed de porte existait mais aucun arc n'etait detecte. Supprime : les seeds de porte relaxent les seuils de detection d'arc mais ne creent plus jamais de porte a eux seuls. Regle les portes fantomes sur 922 et 911.

Impact : `test_comb.py` — bloc seed_fallback supprime (lignes 1636-1658).

---

## D-174 · Filtrage openings chevauchant portes + min_door_width 55 cm (2026-05-13)

Deux corrections detection :
1. `_filter_openings_overlapping_doors` — supprime les openings dont l'intervalle [offset_cm, offset_cm+width_cm] chevauche une porte sur la meme face. Appelee dans `extract_room_features` et `extract_rooms_from_preprocessed`.
2. `min_door_width_cm` abaisse de 70 a 55 cm dans `detection_config.py`. Evite de filtrer des portes legitimement detectees dont l'arc est legerement sous-dimensionne sur des plans a petite echelle.

Impact : `extract.py` (nouvelle fonction + 2 appels), `detection_config.py` (seuil).

---

## D-173 · Nouvel algo detection portes par hits — WIP (2026-05-10)

### Contexte
Le probe de l'ancien algo (`_detect_doors_on_face`) scanne une seule ligne horizontale pour trouver les pixels d'arc. A l'echelle 2.54 cm/px (plan preprocessed 1:300), l'arc ne fait que 1-2 px d'epaisseur : le probe ne trouve que 2 pixels, la porte est filtree par `min_door_width_cm` (70 cm).

### Nouvel algo (D-169b reporte, commit source `5451fd0`)
Analyse les hits par direction (`dir_hits[face]`) au lieu de scanner des pixels dans la binary :
1. Mur = mode des coordonnees perpendiculaires des hits de la face
2. Hits plus courts que le mur = arc
3. Verification profil monotone, ouverture dans le mur
4. Largeur porte = etendue de la zone d'arc
5. `expand_door_arcs` recoit `dir_hits` + `snap_rect` (pre-poteaux)
6. `detect_room` passe `dir_hits` et `snap_rect`

### Etat : deploye, probleme ouvert
L'algo est en place dans le code. Il fonctionne quand l'arc est assez epais pour arreter les rays de la face. Il echoue quand les rays de la face ne sont pas arretes par l'arc (`no_arc_hits`). Observe sur pieces 916, 920, 914 du plan big_pillars : bbox raccourcie.

### Donnees diagnostiques (piece 914)
- rect: [5581,2475,6221,2985], seed: (5883,2684)
- South: wall_px=2985 (=rect.y1), wall_hits=59, pos=2996 count=48
- door_width_px=116, distance mur→couloir=11px
- Toutes les 4 faces rejetees (no_arc_hits ou arc_too_wide)
- Les hits visibles sur l'arc dans l'overlay ne sont pas dans `dir_hits['south']`

### Piste de fix identifiee
Quand `no_arc_hits` sur une face (aucun hit plus court que le mur), regarder les hits **au-dela du mur** (y > wall pour south). S'il y en a, c'est que des rays passent par des ouvertures. Les positions le long du mur de ces hits identifient les portes. La bbox s'etend a ces hits.

### Impact
- `test_comb.py` : `_detect_doors_on_face` reecrit, `expand_door_arcs` adapte pour `dir_hits` + `snap_rect`, `detect_room` passe `dir_hits` et `snap_rect`

---

## D-172 · Rotation des directions de hits + fix aller-retour portes au rescan (2026-05-10)

### Decision
1. Ajouter `rotateDir` / `rotateDirInv` dans `canonical_io.js` pour pivoter les directions de hits (n/s/e/w) en meme temps que les coordonnees.
2. Envoyer les portes en cm (pas px) au backend lors du rescan, avec miroir offset + flip charniere pour north/east.
3. `_renderRoom` appelle toujours `toStorage` pour garantir que `offset_px` est calcule depuis `offset_cm` pour toutes les pieces.
4. Supprimer le `westInvert` du rendu Floor — exception inutile maintenant que toutes les portes passent par `toStorage`.
5. Le backend restitue les portes fournies par le caller (au lieu de toujours re-detecter).

### Justification
- Les rays etaient invisibles pour les pieces avec couloir lateral (east/west) car les directions n'etaient pas pivotees avec les coordonnees.
- Les portes alternaient de position a chaque rescan car l'offset etait envoye en px canonique au backend, reconverti en cm au retour avec un miroir unilateral.
- Les portes disparaissaient en Floor apres rescan car `offset_px` etait perdu par `feat()` et `_renderRoom` ne recalculait pas les px pour les pieces sans corridor.
- Le `westInvert` etait une exception qui ne fonctionnait plus apres la generalisation de `_renderRoom`.

### Impact
- `canonical_io.js` : `rotateDir`, `rotateDirInv` exposes
- `ingestion.js` : rotation directions hits, conversion portes cm batch rescan, suppression westInvert, `_renderRoom` generalise
- `editor.js` : rotation directions hits dans `loadRoomHitsAndSeedFromIngState`
- `init_rvtool.js` : conversion portes cm rescan unitaire
- `extract.py` : restitution portes fournies

---

## D-171 · Enregistrer les hits stop_mask dans le fine comb (2026-05-10)

### Decision
Les fine rays arretes par le stop_mask (couleur couloir/exterieur) sont desormais enregistres dans dir_hits a `abs(d)`, au meme titre que les hits mur. Condition : `d < -1` (exclut `d == -1` = depart sur mur).

### Justification
Les rays qui traversent une ouverture dans un mur et touchent le vert du couloir retournaient une distance negative, silencieusement ignoree par `if d > 0`. Consequence : aucun ray visible a l'emplacement des ouvertures, rendant leur detection impossible visuellement. Le coarse scan n'utilise pas le stop_mask, donc il trouvait les murs au-dela du couloir, mais les fine rays etaient coupes avant.

### Impact
- `olm/ingestion/test_comb.py` : 8 blocs `elif d < -1` ajoutes dans la phase 2 fine comb (4 directions x 2 boucles)
- Les ouvertures sont maintenant visibles dans les rays (Room et Floor)
- Le nombre de hits augmente pour les pieces avec ouvertures sur couloir

---

## D-169 · Fix inversion est/ouest canonical_io (2026-05-09)

### Decision
Corriger la condition de flip d'offset dans `canonical_io.js` : remplacer `cf === "north" || cf === "west"` par `cf === "north" || cf === "east"` dans `fromStorage` (L225) et `toStorage` (L326). Le flip du hinge_side suit la meme condition.

### Justification
Verification geometrique : pour corridor_face="east" (rotation 90° horaire), le bout nord du mur absolu se retrouve au bout est du mur canonique sud — il faut inverser l'offset (mesure depuis l'ouest). Pour corridor_face="west" (90° anti-horaire), le bout nord se retrouve au bout ouest — pas besoin d'inverser. La condition etait inversee, causant une symetrie miroir des features sur les faces est/ouest en vue Room.

### Impact
- `canonical_io.js` : 2 lignes modifiees (fromStorage + toStorage)
- Affecte toutes les pieces avec corridor east ou west
- Round-trip toStorage(fromStorage(x)) garanti (modification symetrique)
- Corrige B1 dans TODO.md

---

## D-167 · Door detection diagnostics dans Diag (2026-05-09)

### Decision
Ajouter une section DOOR DETECTION au bouton Diag avec les donnees de chaque face : far_hits, wall_px, contact ratio, arc pixels, probe position, scan range, groups, raison de rejet (no_far_hits, too_few_wall_hits, too_much_contact, no_arc_pixels, no_seeds_for_face). Seuil de binarisation et door_width_px affiches.

### Justification
Le diagnostic des portes non detectees (arcs marron, seuil de binarisation, absence de hits) necessitait des prints debug temporaires. L'observabilite permanente dans Diag evite les allers-retours code/test.

### Impact
- `test_comb.py` : parametre `diag` ajoute a `_detect_doors_on_face` et `expand_door_arcs`, collecte progressive du dict de diagnostic.
- `app.py` : binarize_threshold et door_width_px ajoutes au diag.
- `init_rvtool.js` : section DOOR DETECTION dans l'affichage Diag.

---

## D-166 · Bbox extension par seed_caps (2026-05-09)

### Decision
Etendre le bbox du peigne (comb_collect_hits) jusqu'au seed voisin quand la distance coarse_mode est insuffisante. Les seed_caps servent de plancher (le bbox ne peut que grandir).

### Justification
Quand le seed est decentre et qu'un obstacle (meuble, texte) bloque les rays coarse sur la ligne du seed, le bbox coarse est trop petit et les rays fins ne couvrent pas toute la piece. L'extension par seed_caps garantit que les rays atteignent au moins le seed voisin.

### Impact
- `test_comb.py` : 8 lignes ajoutees apres le calcul du bbox dans comb_collect_hits.
- Pas de regression D-160 : D-160 reduisait le bbox, D-166 l'etend.

---

## D-165 · Detection poteaux + stop_mask + hits directionnels (2026-05-09)

### Decision
Detecter automatiquement les poteaux (piliers) sur les 4 faces de chaque piece via `_filter_pillar_hits`. Les hits de poteau sont retires des hits normaux et convertis en zones d'exclusion (cm) dans `extract_room_features`. Introduction d'un `stop_mask` dans `ray_single` pour arreter les rays sur les zones colorees (bleu exterieur, vert couloir) sans les compter comme mur. Les hits portent desormais leur direction (n/s/e/w).

### Justification
Sur les plans avec gros poteaux (room 923, 917, 900), les hits de poteau faussaient le bbox et empechaient le matching. Le stop_mask evite que les rays fuient a travers les portes vers les zones exterieures/couloir. Les hits directionnels eliminent l'heuristique abs(dy)>abs(dx) qui etait fausse pour les pieces hautes/etroites.

### Impact
- `test_comb.py` : CombResult dataclass, ray_single stop_mask, _filter_pillar_hits (gap_threshold 3*step), comb_collect_hits dir_hits
- `extract.py` : stop_mask depuis color_image, corridor_rgb, zones d'exclusion auto, hits annotes [x,y,"n"]
- `app.py` : corridor_rgb aux 3 appels, cache-bust timestamp
- `editor.js` : couleurs hits directionnels
- `ingestion.js` : COLORS hit_n/s/e/w
- `detection_config.py` : min/max_pillar_size_cm, comb_step_cm
- `config.js` / `pattern_editor.html` : Settings pillar

---

## D-164 · Fix Rescan All bbox tronqué — doors_px passées au batch (2026-05-09)

### Decision
Ne plus passer les portes existantes (`doors_px`) au backend lors du Rescan All batch. Le batch envoie `doors: []` comme le fait déjà le Rescan single.

### Justification
En batch, les portes existantes (souvent seed-only sans face) étaient passées au backend, ce qui construisait un `door_seeds` filtrant. `expand_door_arcs` skippait alors les faces non listées dans `door_seeds` (ligne 1322 de test_comb.py). Résultat : les arcs de porte non référencés n'étaient pas détectés, et le bbox restait tronqué (ex. room 900 : 397 cm au lieu de 472 cm). Le Rescan single n'avait pas ce problème car il envoyait `doorsPx = []`.

### Impact
- `olm/static/ingestion.js` : batch payload `doors: []` au lieu de `(amend.doors || r.doors)`.
- Rescan All et Rescan single produisent désormais le même bbox pour la même room.

---

## D-163 · Correction inversion east/west dans canonical_io.js (2026-05-09)

### Decision
Les 6 fonctions de rotation de `canonical_io.js` (rotatePoint, rotateRect,
rotateRectInv, canonAngle, xformZone, xformZoneBack) avaient les corps
east et west inverses. FACE_MAPS (correct) effectue une rotation 90 CW
pour east, mais rotatePoint effectuait 90 CCW — contradiction factuelle
prouvee par le test (0,0) qui donne des resultats differents.

Correction : swap des corps east/west dans les 6 fonctions + mise a jour
des expected values des tests auto. FACE_MAPS et offset mirror
(xformOpening/xformBack ligne 208/309) non modifies car corrects.

### Justification
Le bug causait un decalage vertical de 50% de l'overlay plan dans la vue
Room et une inversion des positions de porte pour toute piece avec
corridor east ou west. Preuve : point (0,0) avec W=300, D=500 et
corridor east donnait (0, 300) via rotatePoint mais FACE_MAPS produit
south->east (rotation 90 CW) qui devrait donner (500, 0).

### Impact
- `olm/static/canonical_io.js` : 6 fonctions corrigees + 3 jeux de tests
- Vue Room : overlay et positions correctes pour les pieces east/west
- Aucun impact sur FACE_MAPS ni sur la logique offset mirror

---

## D-162 · Closest-first orientation sans seuil de distance (2026-05-09)

### Décision
Remplacement de la logique de décision dans `_detect_face_colors` :
l'ancienne règle « exterior gagne toujours par face » est remplacée par un
algorithme closest-first global :
1. Tous les hits (12 scans) sont triés par distance croissante.
2. Le premier hit exterior et le premier hit corridor sont identifiés.
3. S'ils sont sur des faces opposées → pas d'ambiguïté.
4. S'ils ne sont pas opposés → le plus proche fait référence pour orienter.
5. Pas de seuil de distance.

### Justification
Les scans sans limite de distance traversent tout le plan et trouvent des
couleurs d'autres pièces (faux positifs). Exemple : pièce avec exterior à
l'ouest (48 px) et corridor à l'est (5 px), mais les scans nord/sud trouvaient
du bleu à 322-641 px → 4 faces classées exterior → orientation fausse.
L'approche closest-first résout le problème sans introduire de seuil arbitraire.

### Impact
- `olm/ingestion/extract.py` : logique de décision de `_detect_face_colors`
  réécrite. `exterior_faces` ne contient plus que la face du hit exterior le
  plus proche (pas toutes les faces ayant un hit exterior).

---

## D-161 · Corner-scan exact match pour la détection d'orientation (2026-05-08)

### Décision
Remplacement complet de `_detect_face_colors` (band sampling) par un algorithme
corner-scan avec match exact RGB :
- 12 scans : 4 coins × 2 directions perpendiculaires + 4 midpoints × 1 direction.
- Depuis chaque point, extraction numpy vectorisée du strip complet (ligne ou colonne).
- Match exact RGB (pas de tolérance) — les images preprocessed ont des couleurs
  programmatiques.
- Premier pixel bleu (extérieur) ou vert (couloir) trouvé détermine la face.
- Pas de seuil de distance, pas de seuil de pourcentage.

### Justification
Le band sampling échouait quand le bleu/vert était au-delà de la bande configurée.
La tolérance ±40 causait des faux positifs (gris 207,207,207 matchait le vert
corridor 193,247,179). L'exact match est sûr puisque les couleurs sont programmatiques.

### Impact
- `olm/ingestion/extract.py` : `_detect_face_colors` réécrite (12 corner-scans,
  exact match, numpy vectorisé). Signature simplifiée (plus de tolerance/kwargs).
- `olm/server/app.py` : endpoint diagnostic retourne `corner_hits` (12 scans).
- `olm/static/init_rvtool.js` : section CORNER SCAN dans le diagnostic.
- `CLAUDE.md` : règles ajoutées — expliquer l'algo + lister tous les choix d'implémentation.

---

## D-160 · Endpoint diagnostic + modal copyable (2026-05-08)

### Décision
- Endpoint `/api/debug/room-diagnostic` : re-exécute la détection sur une pièce
  et retourne un JSON avec coarse distances, hit counts, obstacles, portes, etc.
- Modal textarea (au lieu d'`alert()`) pour un diagnostic copyable depuis le
  navigateur.
- `diag` dict chaîné : `extract_room_features` → `detect_room` → `comb_collect_hits`.
- `ray_single_through` et `seed_caps` implémentés mais **désactivés** après
  régressions en prod (traversait les vrais murs, rétrécissait les pièces).
  `_opening_has_depth` désactivé aussi (rejetait toutes les ouvertures).

### Justification
Debug distant : les plans réels ne sont pas accessibles depuis la plateforme de
développement ; le diagnostic permet de valider sans publier à répétition.

### Impact
- `olm/server/app.py` : +endpoint `/api/debug/room-diagnostic`.
- `olm/templates/pattern_editor.html` : modal diagnostic + bouton Diag.
- `olm/static/init_rvtool.js` : handler Diag, formatage sections.
- `olm/ingestion/test_comb.py` : `diag` dans `detect_room`, `ray_single_through`
  présent mais non utilisé, `seed_caps` calculé pour diag seulement.

---

## D-159 · other_seeds au rescan + validation profondeur ouvertures (2026-05-08)

### Décision

1. **other_seeds passé au rescan** (unitaire et batch). Les rays du comb sont filtrés par les seeds des pièces voisines : un hit est rejeté s'il dépasse un seed voisin dans sa direction. Élimine les rays qui traversent les murs de séparation entre pièces.

2. **Validation profondeur des ouvertures**. Après classification, chaque opening est vérifiée : un probe perpendiculaire vers l'intérieur de la pièce vérifie qu'il y a au moins `min_opening_depth_cm` (défaut 60) de libre derrière. Si un obstacle (mur, fenêtre) est à moins de cette distance → reclassé en mur.

3. **Paramètres Settings** : `min_opening_depth_cm` et `min_obstacle_width_cm` exposés dans l'UI.

### Justification

Tests production (K5, K12, K25) : les rays dépassaient massivement les murs réels de la pièce parce que le rescan ne passait pas les seeds des pièces voisines comme condition d'arrêt. Le scan initial OCR et l'import preprocessed les passaient déjà — seul le rescan était affecté.

Les fausses ouvertures (K3) sont causées par des artefacts de dessin (poteaux, double-traits) où le mur ne fait que quelques cm d'épaisseur. La validation de profondeur les élimine.

### Impact

- `app.py` : rescan unitaire accepte `other_seeds_px`, batch construit `other_seeds` pour chaque pièce
- `init_rvtool.js` : envoie les seeds des autres pièces au rescan unitaire
- `ingestion.js` : envoie les doors (avec seed_x/y) dans le batch payload
- `extract.py` : `_opening_has_depth()` + appel dans `_classify_wall_direct`
- `detection_config.py` : `min_opening_depth_cm` 100→60

---

## D-158 · max_door_width + binarize_threshold + seeds toggle (2026-05-08)

### Décision

Trois ajouts liés à la détection de portes et à la visibilité des seeds :

1. **max_door_width_cm = 120** dans DetectionConfigCm. Les ouvertures > 120 cm détectées comme portes (ex. 508 cm) sont filtrées. Paramètre exposé dans Settings.
2. **binarize_threshold relevé de 110 à 140**. Les arcs de porte marron (grayscale ~125) n'étaient pas détectés avec le seuil 110. Paramètre exposé dans Settings.
3. **Seeds toggle séparé** de V-Rays/H-Rays. Affiche room seed (vert) et door seeds (orange) dans Floor et Room.

### Justification

Tests production (K cases) : portes non détectées (arcs marron sous seuil), fausses portes géantes (murs entiers classés porte), seeds invisibles pour diagnostic. Trois problèmes indépendants mais tous liés à la qualité de détection de portes.

### Impact

- `detection_config.py` : +`max_door_width_cm`, `binarize_threshold` 110→140
- `extract.py` : filtre min+max portes (preprocessed + detected), binarize depuis config, door seeds dans output, clamp fenêtres
- `app.py` : `_get_default_threshold()` module-level, overrides étendus
- `ingestion.js` / `editor.js` : toggle Seeds, door seeds Room, rays non clippés
- `pattern_editor.html` + `config.js` : champs Settings + checkboxes Seeds

---

## D-157 · Import preprocessed : détection complète sans bbox_px (2026-04-29)

### Décision

Quand un JSON preprocessed v3 ne contient pas de `bbox_px` pour une pièce, l'import (`extract_rooms_from_preprocessed`) exécute désormais le pipeline complet `extract_room_features` (ray-cast bbox + classification murs → fenêtres, ouvertures, portes) au lieu de créer un bbox carré fallback vide.

### Justification

En production, les JSON preprocessed n'ont pas de `bbox_px` (champ Save-only). L'ancien comportement créait des bbox carrés `sqrt(surface)` sans features — les pièces apparaissaient sans fenêtres ni portes. L'utilisateur devait faire un Rescan All pour obtenir des résultats exploitables. Le comportement attendu est que l'import produise des résultats complets, comme le fait le pipeline OCR.

### Impact

- `olm/ingestion/extract.py` : bloc D-157 (lignes ~1358-1394) appelle `extract_room_features` pour chaque pièce sans bbox, avec `other_seeds` des voisins. Les features détectées (windows, openings, doors) sont injectées dans le room_dict (lignes ~1462-1469), remplaçant les champs `_raw` vides du JSON.
- Image `-SD` binarisée une seule fois (partagée entre toutes les pièces, comme le batch rescan D-123).
- Aucune régression sur les JSON avec bbox existants (le bloc est skip si toutes les pièces ont déjà un bbox).

---

## D-156 · Filtrage fenêtres par zone extérieure + fix rendu sud/est (2026-04-29)

### Décision

1. **Filtrage extérieur des fenêtres** : en mode preprocessed, `extract_room_features` reçoit `color_image` (le plan -SD avec zones colorées) et `exterior_rgb`. Les fenêtres texture ne sont conservées que sur les faces bordant la zone extérieure (bleu sky blue ±40 tolerance, 30% match). En mode OCR, pas d'image couleur → comportement legacy (toutes les fenêtres texture conservées).
2. **Détection grayscale** : si l'image couleur fournie est en réalité grayscale (R=G=B sur un échantillon de 500 px), `rgb_arr` est mis à None → fallback legacy.
3. **Suppression du fallback full-face** : plus de fenêtre fictive créée automatiquement sur les faces extérieures sans fenêtre texture. Le filtre extérieur sert uniquement à éliminer les faux positifs, pas à créer des fenêtres sur des murs pleins.
4. **Fix rendu Floor sud/est** : `drawWallFeature` recevait `sFeatureOff` comme string (via `.toFixed(2)`). L'opérateur `+` faisait une concaténation de chaînes (`782 + "3.00"` = `"7823.00"`) au lieu d'une addition. Les fenêtres sud/est étaient dessinées hors écran. Fix : `parseFloat(featureOff)`.
5. **Version OLM dans Settings** : `__version__` exposé via `/api/config`, affiché dans le header Settings.
6. **`_apply_detection_config` avant tout ray-cast** : appelé quel que soit le mode (OCR ou preprocessed), avant `find_seeds_by_ocr`. Corrige les marges cartouche trop serrées.

### Justification

Le plan -SD preprocessed porte les zones bleues (extérieur) et vertes (corridor). L'overlay est le plan officiel (souvent grayscale). En D-155, `color_img` était chargé depuis l'overlay → 0% match bleu → aucune fenêtre. Le fix charge depuis le -SD (`plan_path`). Le bug de rendu sud/est est un classique JS : `.toFixed()` retourne un string, et `+` avec string fait de la concaténation.

### Impact

- `olm/ingestion/extract.py` : +2 params `color_image`/`exterior_rgb`, détection grayscale, filtre extérieur, suppression fallback
- `olm/server/app.py` : `_get_exterior_rgb()`, `color_img` chargé depuis plan_path, `_apply_detection_config` avant tout mode
- `olm/static/ingestion.js` : `parseFloat(featureOff)` dans `drawWallFeature`, cleanup console.log
- `olm/static/config.js` : affichage version Settings
- `olm/templates/pattern_editor.html` : span `settingsVersion`

---

## D-155 · Auto-calibration scale OCR + overlay indépendant de la résolution (2026-04-29)

### Décision

1. **Scale auto-calibré** : `extract_all_rooms` calcule toujours le scale à partir des surfaces annotées par OCR sur le plan (médiane), même quand un `scale_cm_per_px` est fourni. Le scale fourni sert uniquement de hint pour la détection (paramètres px via `_apply_detection_config`). Filtre : `surface_m2 ≥ 8 m²`, bbox > 20 px, pas au bord de l'image.
2. **Overlay ingestion pxScale-aware** : tous les strokes, fonts, handles et dash-arrays de l'overlay ingestion sont multipliés par `pxScale` (viewBox units / CSS pixel). Les constantes sont centralisées en haut du fichier. Résultat : apparence identique sur plan standard (1920 px) et big plan (7320 px).

### Justification

Le scale stocké dans `drawing_scale_measured` est calculé via `2.54 × scale_text / DPI`. Quand le DPI de l'image est inconnu (PNG sans métadonnées), le scale est faux (~20% d'erreur sur le plan OCR test). Les surfaces annotées sur le plan sont la vérité terrain et ne dépendent pas du DPI.

L'overlay utilisait des stroke-width hardcodés en unités viewBox → invisibles sur les plans haute résolution (7320+ px).

### Impact

- `test_comb.py` : constantes calibration (`MIN_CALIB_SURFACE_M2`, `CALIB_EDGE_MARGIN_PX`), auto-calibration toujours active
- `ingestion.js` : 12 constantes overlay (`OVERLAY_*`) + pré-calcul scalé dans `renderIngestion` + paramètres `eraseW`/`featureOff` passés aux helpers

---

## D-154 · Mode source persistant OCR/preprocessed + fix cartouche erasure ordering (2026-04-29)

### Décision

1. Chaque JSON plan porte un champ `"mode": "ocr"|"preprocessed"` (écrit manuellement). Ce champ est la source de vérité pour le comportement du rescan (effacement cartouche, etc.). Absent → défaut "preprocessed" (rétrocompat).
2. `/api/import/preprocessed` retourne `mode` depuis le JSON au frontend.
3. Le frontend met à jour `_selectedPlan.mode` depuis la réponse import → le batch rescan envoie le bon mode.
4. `_apply_detection_config(scale)` est appelé AVANT `find_seeds_by_ocr` partout (test_comb.py `extract_all_rooms`, app.py single + batch reanalyze). Corrige `CARTOUCHE_MARGIN_PX = 1` (valeur d'import stale).

### Justification

Le plan OCR `test_floorplan_ocr` avait un JSON compagnon issu d'une extraction précédente → l'app le chargeait en mode "preprocessed" → le batch rescan n'effaçait jamais les cartouches → les rays butaient sur le texte → pièces mal dimensionnées.

### Impact

- `test_floorplan_ocr.json` : ajout `"mode": "ocr"`
- `app.py` : import/preprocessed retourne `json_data.get("mode", "preprocessed")` ; `_apply_detection_config` avant `find_seeds_by_ocr` dans reanalyze + batch
- `test_comb.py` : `_apply_detection_config` déplacé avant `find_seeds_by_ocr`
- `ingestion.js` : `extractRoomsPreprocessed` met à jour `_selectedPlan.mode` depuis la réponse

---

## D-153 · Seeds portes préservées dans canonicalisation + filtre min_opening_width_cm (2026-04-27)

### Décision

Deux corrections post-replay :

1. `computeCanonicalReanalyzeResult` (ingestion.js) : `feat()` ne
   recopiait pas `seed_x`/`seed_y` des portes. Après un re-analyze,
   les seeds étaient perdues et invisibles dans le SVG. Fix : copie
   conditionnelle dans le bloc `doorsCanon`.

2. `extract_rooms_from_preprocessed` (extract.py) : filtre
   `min_opening_width_cm` appliqué aux openings, symétrique au filtre
   `min_door_width_cm` ajouté en D-148 pour les portes. Élimine les
   micro-ouvertures du JSON producer.

### Justification

(1) Les seeds de portes sont nécessaires pour l'ancrage visuel et le
rescan ciblé. Leur perte au passage canonique cassait le feedback UI.
(2) Cohérence : si les micro-portes sont filtrées, les micro-ouvertures
doivent l'être aussi (seuil : 24 cm, cf. `DetectionConfigCm`).

### Impact

- `olm/static/ingestion.js` : 2 lignes ajoutées dans `doorsCanon` map.
- `olm/ingestion/extract.py` : 2 lignes ajoutées après le filtre porte.
- Affecte le load preprocessed et le re-analyze.

---

## D-152 · extract_rooms_from_preprocessed utilise drawing_scale_measured (2026-04-27)

### Décision

`extract_rooms_from_preprocessed` utilisait une échelle déduite par médiane
des rapports surface/bbox (0.9519 sur big plan), alors que
`drawing_scale_measured` (0.7773) était disponible dans le JSON et utilisé
par le frontend. Les `offset_cm`/`width_cm` des fenêtres/ouvertures/portes
étaient donc enrichis avec un scale faux de 22%, produisant un rendu
incohérent entre le chargement initial et un rescan.

Fix : `drawing_scale_measured` est maintenant lu et injecté dans la chaîne
de priorités : `_override_cm_per_px` > `drawing_scale_measured` > médiane >
fallback 0.5.

### Justification

Le rendu utilise `offset_cm`/`width_cm` (pas les px) pour positionner les
fenêtres à l'écran. Un écart de 22% dans le scale source rend les fenêtres
visiblement plus larges au chargement qu'après un rescan. La médiane est un
estimateur brut, non nécessaire quand un scale mesuré est explicitement
disponible.

### Impact

- `olm/ingestion/extract.py` : 7 lignes ajoutées dans
  `extract_rooms_from_preprocessed` (parsing de `drawing_scale_measured`).
- Affecte le load initial de TOUS les plans preprocessed ayant un
  `drawing_scale_measured` dans le JSON.
- Comportement inchangé si le champ est absent (fallback médiane conservé).

---

## D-151 · Fix _group_pixels stale default + enrichissement seeds big JSON (2026-04-27)

### Décision

`_group_pixels(pixels, max_gap=DOOR_GROUP_GAP_PX)` capturait la valeur
initiale (25) à la définition, ignorant la mise à jour par
`_apply_detection_config`. Fix : passage explicite de la globale au
call site (`_detect_doors_on_face:1124`).

Enrichissement : détection d'arcs lancée sur les 30 pièces du big plan.
18/19 portes enrichies avec `seed_x`/`seed_y`. Seule 904 sans seed
(arc non détectable dans le -SD).

### Justification

Sur les plans à scale ≠ 0.5 cm/px (ex. big à 0.7773), `max_gap=25`
fragmentait les arcs en micro-groupes (pièce 915 : 2 portes de 8 et
7 px au lieu d'une de 103 px). Après fix, le gap correct (~97 px)
regroupe correctement l'arc.

### Impact

- `olm/ingestion/test_comb.py` : 1 ligne modifiée.
- `project/plans/test_floorplan_preprocessed_big.json` : 18 portes
  enrichies avec seed_x/seed_y.
- Régression potentielle : aucune (passage explicite d'une valeur
  déjà calculée correctement par `_apply_detection_config`).

---

## D-150 · Dernier seuil px hardcodé + nettoyage code mort extract.py + fix race condition scale OCR (2026-04-27)

### Décision

**1. Fix snap search hardcodé (`extract.py:762`)** :
`_classify_wall_direct` cherchait le mur dans un rayon fixe de ±3 px
(`range(-3, 4)`). À 0,78 cm/px (plan big), 3 px = 2,3 cm — insuffisant
pour trouver le mur → face entière classifiée "opening". Fix : utilise
`_cfg_local.snap_search_px` (issu de `snap_search_cm = 18.0`), déjà
calculé mais jamais branché. Dernier seuil px hardcodé dans le
classifier.

**2. Nettoyage code mort** :
- Suppression `classify_wall_segments()` (~140 lignes, jamais appelé —
  remplacé par `_classify_wall_direct` depuis D-108).
- Suppression `_build_exclusions()` (~60 lignes, jamais appelé).
- Suppression 5 constantes px mortes : `WALL_DEPTH_PX`,
  `MIN_OPENING_PX`, `MIN_OBSTACLE_PX`, `MODE_TOLERANCE_PX`,
  `SNAP_SEARCH_PX`.
- `_probe_wall_texture` : `depth` n'a plus de défaut px (l'unique
  appelant actif passe `_cfg_local.wall_depth_px`).

**3. Migration des 2 dernières constantes px actives** :
- `BINARIZE_THRESHOLD = 180` et `MORPH_DILATE_PX = 1` → paramètres de
  `binarize(threshold, morph_dilate_px)`. Le caller `extract_rooms`
  calcule `morph_dilate_px` depuis `DetectionConfigCm.morph_dilate_cm`.
  Le threshold OCR (180) reste distinct du threshold preprocessed (110).
- `text_margin = 10` → `text_skip_margin_cm = 6.0` (nouveau champ
  `DetectionConfigCm`, converti en px via `to_px()`).

**4. Fix race condition scale OCR** (`ingestion.js` + `init.js`) :
Le pré-remplissage du champ `ingDrawingScale` depuis
`APP_CONFIG.ingestion.drawing_scale_text` se faisait dans un handler
`DOMContentLoaded` enregistré AVANT le chargement du config (handler de
`init.js`). Résultat : champ vide → backend reçoit `scale=None` →
fallback 0,5 cm/px → pièces minuscules. Fix : pré-remplissage extrait
en `prefillDrawingScale()`, appelé depuis `init()` après
`loadAppConfig()`.

### Justification

L'invariant « comportement identique standard/big » était violé par le
seul seuil px restant dans le classifier. Le nettoyage du code mort
réduit la surface de maintenance (~200 lignes) et élimine les
constantes qui pouvaient créer de la confusion.

### Impact

- `extract.py` : ~200 lignes supprimées, `binarize()` paramétré.
- `detection_config.py` : +1 champ `text_skip_margin_cm`.
- `ingestion.js` : `prefillDrawingScale()` exposé.
- `init.js` : appel après config chargé.

---

## D-149 · Frontend cm-only + filtre `min_door_width_cm` + patch homothétique big JSON (2026-04-26)

### Décision

Migration des constantes métier frontend en cm + ajout d'un filtre
largeur minimale pour les portes au scan OCR et au load preprocessed
+ régénération du JSON `test_floorplan_preprocessed_big` par homothétie
depuis le standard.

**1. Frontend cm-only (`olm/static/ingestion.js`) :**
- `SHARED_WALL_TOLERANCE_CM = 4` (au lieu de `_PX = 8`) — tolérance
  d'adjacence pour fusion de murs entre pièces. Conversion dynamique
  en px à l'usage via `ingState.scale`.
- `BBOX_RESIZE_MIN_CM = 25` (au lieu de `_PX = 50`) — taille minimale
  bbox éditable.

**2. Backend OCR `n < 3` → seuil cm (`olm/core/detection_config.py` +
`olm/ingestion/test_comb.py`) :**
- Ajout `min_door_arc_width_cm = 45.0` dans `DetectionConfigCm`.
- Exposé en `min_door_arc_hits` dans `DetectionConfigPx` (= entier de
  hits, calculé `round(min_door_arc_width_cm / comb_step_cm)`).
- `_apply_detection_config` met à jour le global `MIN_DOOR_ARC_HITS`.
- `_detect_doors_on_face` utilise `MIN_DOOR_ARC_HITS` au lieu du
  hardcode `n < 3` (4 occurrences). Comportement strictement identique
  au scale 0.5 cm/px historique (45/15 = 3) ; correctement scale-invariant
  pour autres résolutions.

**3. Filtre `min_door_width_cm = 70` (`detection_config.py`,
`test_comb.py`, `extract.py`) :**
- Ajouté à `DetectionConfigCm` ; exposé en `min_door_width_px` dans
  `DetectionConfigPx`.
- Appliqué côté OCR scan initial (`extract_all_rooms`) après
  `detect_room` : portes `width_px < min_door_width_px` rejetées.
- Appliqué côté load preprocessed (`extract_rooms_from_preprocessed`)
  après `_enrich_px_cm` : portes `width_cm < min_door_width_cm`
  rejetées. Élimine les micro-portes dans les JSON producer corrompus.
- Symétrique aux filtres `min_opening_width_cm` et `min_window_width_cm`
  déjà existants côté OCR.

**4. `door_width_px` correctement transmis (`test_comb.py:1214`) :**
- `detect_room` était appelé sans `door_width_px`, retombait sur la
  valeur par défaut `23` (= 90 cm à scale 0.5). Sur les autres scales,
  l'algorithme cherchait des arcs de mauvaise taille → micro-portes.
- Désormais : `door_width_px=cfg.default_door_width_px` à chaque appel.

**5. Patch homothétique `test_floorplan_preprocessed_big.json` :**
- Le JSON v2 d'origine contenait 38 micro-portes (width 6-8 px = 3-4 cm)
  produit par un outil tiers buggé.
- Régénéré par homothétie depuis le standard (×3.8125 = 7320/1920) +
  recalibration de `drawing_scale_measured` à 0.7773 cm/px (= 2.9633/3.8125).
- Backup en `.bak`. Standard et big donnent maintenant le même nombre
  de portes/fenêtres/ouvertures avec dimensions équivalentes au cm près.

**6. Préservation auto windows/openings au rescan : tenté puis reverté.**
- Tentative : symétrique de `newDoors`, conserver les pré-existantes
  si canon vide.
- Reverté : la préservation cohabitait visuellement avec les openings
  parasites générés par `extract_room_features` (wall classifier qui
  échoue sur PNG `-SD` haute résolution) → résultat plus chargé sans
  résoudre le bug racine. Patches symptomatiques abandonnés au profit
  d'une vraie investigation à venir.

**7. Rays clippés au bbox au rendu Floor :**
- Le comb retourne tous les hits collectés, certains au-delà du bbox
  de la pièce. Sans clip, le rendu trace des rays qui débordent
  largement (visible sur plans HD avec `pxScale` qui rend les rays
  visibles). Filtre `_hitInBbox` au rendu nettoie l'overlay sans
  modifier la donnée.

### Justification

Tous ces points dérivent de l'invariant cm-everywhere et de la nécessité
que `test_floorplan_preprocessed.json` (standard) et
`test_floorplan_preprocessed_big.json` (big = haute résolution, mêmes
pièces) produisent un comportement strictement identique en mode
preprocessed.

### Impact

- Standard et big chargés en preprocessed produisent le même nombre
  de portes (19), ouvertures (53), fenêtres (66), au cm près.
- Mode OCR cartouches : scan initial et rescans détectent les mêmes
  ouvertures (cf. D-148).
- Régression connue non résolue (cf. TODO) : `extract_room_features`
  classifie mal les fenêtres sur PNG `-SD` haute résolution → Rescan
  all sur big génère des openings parasites couvrant des murs entiers.
  Workaround temporaire : ne pas faire Rescan all sur big.
- Non-régression : 135/142 tests Python passent (mêmes 7 échecs
  pré-existants v0.4.5).

### À faire en suivant

Cf. `docs/TODO.md` :
- Filtre `min_opening_width_cm` au load preprocessed (symétrique).
- Investiguer le wall classifier sur PNG `-SD` HD.
- Format JSON v3 cm primary (déprécier `*_px` métier).
- Caches runtime stale dans `test_comb.py` (renommer ou refactor).
- Gel UI sur ArrowRight dernière pièce dans Room.

### Status

**Non commité fin de session 2026-04-26.** En pause après plusieurs
tentatives de patches symptomatiques sur le rescan big preprocessed.

---

## D-148 · Rescan en mode OCR : reproduire l'erase cartouches + transmettre le scale au scan initial (2026-04-26)

### Décision

Deux corrections couplées, livrées comme unité hors replay v0.4.5
(préalable à la reprise de D-143).

**1. Backend — erase cartouches au rescan en mode OCR.**

- Le payload des endpoints `/api/room/reanalyze` et
  `/api/room/reanalyze_batch` reçoit désormais un champ
  `mode: "ocr" | "preprocessed"` (défaut serveur `"preprocessed"`).
- En mode `"ocr"`, le backend appelle `find_seeds_by_ocr(img)` pour
  obtenir les cartouches puis les blanchit AVANT la binarisation —
  unitaire via le nouveau paramètre `cartouche_bboxes_px` de
  `extract_room_features` (qui les ajoute à ses `mask_rects_px`),
  batch via `erase_cartouches(_gray_global, cart_bboxes)` en place
  avant la binarisation globale partagée.
- Frontend (`ingestion.js`, `init_rvtool.js`) : le payload des deux
  endpoints inclut `mode = ingState._selectedPlan.mode` (toujours
  défini après sélection via le dropdown).

**2. Backend — transmettre `scale_cm_per_px` à `_classify_wall_direct`
dans `extract_all_rooms`.**

`extract_all_rooms` ([test_comb.py:1174](../olm/ingestion/test_comb.py#L1174))
appelait `_classify_wall_direct(binary, binary, bbox, face, 5)` sans
transmettre le `scale_cm_per_px`, retombant donc sur la valeur par
défaut `0.5`. Sur un plan à scale réel ≠ 0.5, les seuils en cm de
`DEFAULT_DETECTION_CONFIG_CM` étaient convertis en px avec un mauvais
ratio → seuils trop larges → openings absorbés au lieu d'être
détectés. Désormais la fonction passe le `classify_scale =
scale_cm_per_px or 0.5` (fallback historique préservé si le caller
ne fournit pas de scale et qu'on est avant l'auto-détection).

### Justification

Symptôme initial : sur `test_floorplan_ocr.png` (mode OCR, pas de
JSON), un Rescan all sans Lock walls réduisait toutes les pièces à
des bandes étroites. Cause : `extract_room_features` ne reproduisait
pas le pré-traitement cartouches du scan initial (`extract_all_rooms`)
→ seed sur du texte solide → rays butent immédiatement.

Symptôme corollaire découvert pendant le fix : le scan initial trouvait
0 ouvertures là où les rescans en trouvaient 4. Cause : seuils de
classification calculés à scale 0.5 par défaut au lieu du scale réel
(3.675 cm/px sur ce plan, ×7.35).

### Impact

- Mode OCR : Rescan-all et Rescan-unit donnent des bbox numériquement
  identiques au scan initial (sur la pièce 901 de `test_floorplan_ocr`
  : bbox (147, 624, 224, 782) inchangée vs rescan).
- Mode OCR : scan initial et rescans détectent les **mêmes**
  windows / openings (4 openings sur 901 : N, S, 2× W).
- Mode préprocessé : aucun impact — le défaut serveur reste
  `"preprocessed"`, le erase OCR n'est pas exécuté, et les `-SD.png`
  ont déjà leurs cartouches blanchis externellement.
- Non-régression : 135/142 tests Python passent (mêmes 7 échecs
  pré-existants sur la baseline v0.4.5).

### À faire en unité séparée (TODO.md)

Sémantique de Rescan all (Floor) : aujourd'hui = re-extract features
sur les pièces déjà détectées avec leurs seeds/bboxes. Sémantique
attendue par l'utilisateur = re-OCR + redécouverte complète des
pièces (équivalent réouverture). Refonte non-triviale (nécessite
consolidation des amendments user côté JS).

---

## D-142 · `remove_non_ortho` travaille en local par composant (2026-04-21)

### Décision

La fonction `remove_non_ortho` ([extract.py:233](../olm/ingestion/extract.py#L233))
utilise désormais `cv2.connectedComponentsWithStats` (au lieu de
`connectedComponents`) pour lire la bbox de chaque composant connexe.
Chaque composant est ensuite traité dans sa **bbox locale**, pas sur
l'image entière :

```python
num, labels, stats, _ = cv2.connectedComponentsWithStats(binary_u8, 8)
for label_id in range(1, num):
    x, y, w, h = stats[label_id, [LEFT, TOP, WIDTH, HEIGHT]]
    local_labels = labels[y:y+h, x:x+w]
    local_mask = (local_labels == label_id)
    # minAreaRect, effacement sur la vue locale
```

### Justification

Sur un plan haute résolution (ex: 7320×3508 ≈ 25 Mpx, cas observé en
prod), le rescan unitaire prenait 4 minutes. Le goulot dominant était
ici : chaque itération faisait `labels == label_id` et `cleaned[labels
== label_id] = False`, soit deux balayages **O(total_pixels)** par
composant. Avec plusieurs centaines de composants, coût total **O(N ×
pixels)** — plusieurs milliards d'opérations.

En travaillant sur la bbox locale de chaque composant, le coût passe à
**O(somme_des_bbox_composants)**, typiquement 50-100× plus rapide sur
des plans où les composants sont petits devant l'image.

### Impact

- **Perf** : rescan unitaire attendu de l'ordre de 10-30 s au lieu de
  4 min sur un PNG 25 Mpx.
- **Sémantique inchangée** : même détection (angle via `minAreaRect`),
  même seuil `min_component_px`, même effacement pour composants
  non-orthogonaux.
- **Benchmark synthétique** (500 composants, 7320×3508) : 31 ms.
- **Non-régression** : 135/142 tests Python passent (7 échecs
  pré-existants hors scope).

---

## D-141 · Skip silencieux des ouvertures sans `face` dans la chaîne match (2026-04-21)

### Décision

Les endpoints `/api/floor-plan/match` (2 sites dans app.py) et les
fonctions frontend `serializeForMatching` / `fpLoadAndMatch` filtrent
désormais les entries `windows` / `openings` / `doors` dont le champ
`face` est absent. Ces entries viennent principalement du format JSON v3
**Input minimal** : doors avec uniquement `seed_x` / `seed_y`, non
enrichies par un ray-cast.

### Justification

Avant D-141, une porte au format Input provoquait un `KeyError: 'face'`
côté Python (symptôme « Error: 'face' » remonté par l'UI) dès qu'elle
arrivait dans le backend matcher. Le frontend combinait pourtant les
doors dans `openings[]` avec `has_door:true`, mais `face` undefined
devenait clé absente au `JSON.stringify`.

L'enrichissement ray-cast qui devrait attacher `face` / `offset_px` /
`width_px` aux doors depuis leur `seed_x/seed_y` (spec R-05 / D-105)
n'est pas encore implémenté. Entre-temps, le pipeline doit dégrader
proprement : les portes non-enrichies sont ignorées au matching plutôt
que de bloquer tout le plan.

### Impact

- **Robustesse** : les JSON v3 Input minimal chargent sans erreur.
- **Limitation acceptée** : les portes au format Input ne sont pas
  prises en compte dans le matching tant que l'enrichissement ray-cast
  n'est pas implémenté. Les murs + windows/openings enrichies restent
  matchés normalement.
- **Convergence 5 sites** : même filtre à 5 endroits (2 backend, 3
  frontend dans les 2 fichiers). Factoriser ce filtre est un TODO
  structurel.

---

## D-140 · `effective_mode = "preprocessed"` dès `has_json` (2026-04-21)

### Décision

La route backend `/api/plans` ([app.py:415](../olm/server/app.py#L415))
classe désormais un plan en `effective_mode = "preprocessed"` dès que le
JSON associé existe (`has_json == True`), sans regarder les `mtime`. La
condition précédente `json_mtime > png_mtime` est supprimée.

### Justification

La condition `mtime` visait à détecter un PNG ré-édité après le JSON pour
déclencher un re-OCR. En pratique cette heuristique est fragile :
- Copie inter-machine (déploiement prod) : les `mtime` reflètent l'ordre
  de copie, pas l'ordre d'édition.
- `git checkout` : tous les fichiers prennent le même `mtime`.
- Timezones / clock skew.
- Format de stockage filesystem variable.

En prod, l'user constatait un confirm « No JSON file found for this
plan » à chaque ouverture d'un plan copié tel quel. Le JSON était
présent, juste perçu comme obsolète par le backend.

### Impact

- **Déploiement prod** : le classement `preprocessed` est maintenant
  robuste aux copies de fichiers.
- **Non-régression** : si le user veut forcer un re-OCR, il peut
  supprimer explicitement le JSON.

---

## D-139 · Fix faux positif « No rooms found in JSON » au démarrage + tolérance dict/array (2026-04-21)

### Décision

Deux fixes pour résoudre le symptôme « No rooms found in JSON » observé à
l'ouverture de `localhost` sur une machine de production sans
`project/test_rooms.json` :

1. **Backend** — [`app.py:214-221`](../olm/server/app.py#L214-L221) :
   la route `/test_rooms.json` retourne désormais **HTTP 404** si le
   fichier est absent, au lieu de `{"rooms": []}` avec HTTP 200. Le
   fetch frontend utilise déjà `r.ok` et skip silencieusement sur
   404 ; le comportement rétablit celui attendu depuis l'origine.
2. **Frontend** — [`floor_plan.js`](../olm/static/floor_plan.js)
   `fpLoadAndMatch(string)` : accepte désormais `parsed.rooms` en
   **array** (format matching) **ou en dict** indexé par room_id
   (format storage v3). Le dict est normalisé au vol via `Object.keys`.
   Robustifie le chemin « Load JSON file » pour les fichiers v3 bruts.

### Justification

Sur la machine locale dev, `project/test_rooms.json` existe → pas de
symptôme. En prod (GitHub public filtré), le répertoire `project/` est
privé, donc `test_rooms.json` absent → la route renvoyait un array vide
→ fpLoadAndMatch alertait. L'alerte s'affichait à chaque ouverture de
la page, bloquant visuellement l'user.

La tolérance dict/array généralise : le chemin « Load JSON file » (drop
d'un fichier JSON dans l'UI) marchait déjà pour les JSON matching
(array), il marche maintenant aussi pour les JSON v3 bruts (dict).

### Impact

- **Déploiement** : résout le blocage au démarrage sur toute machine
  sans `project/test_rooms.json`.
- **UX** : plus d'alerte parasite à l'ouverture de la page.
- **Compat** : aucune régression — les consommateurs existants passaient
  déjà par `r.ok`, le dict reste la forme JSON v3 canonique.

---

## D-138 · Seed de porte `label_x / label_y` → `seed_x / seed_y` + round-trip rétabli (2026-04-21)

### Décision

Renommage dans le schéma JSON v3 des seeds de porte : `label_x` / `label_y`
deviennent `seed_x` / `seed_y` dans chaque `rooms[<id>].doors[<i>]`.
Convention uniforme avec le seed de pièce (déjà `seed_x` / `seed_y`).

Le round-trip Save/Load est rétabli : `ingestion_serialize.js` écrit
désormais explicitement `seed_x` / `seed_y` sur les doors si fournis, et
`extract.py` les parse à l'import. Les seeds survivent donc à chaque
cycle (avant : perdus à la première sauvegarde OLS car non inclus dans
`serializeForStorage`).

### Justification

- **Cohérence nominale** : un seul nom (`seed_x`/`seed_y`) pour tous
  les seeds (pièce, porte, futures ouvertures manuelles…). Le terme
  `label_*` était historiquement lié au texte label du cartouche de
  porte sur le plan scanné ; la sémantique « seed de ray-cast » est
  plus générale.
- **Persistance** : la spec documentait le round-trip mais le code
  frontend ne les sérialisait pas — bug silencieux découvert par
  inspection visuelle du JSON après Save.
- Coût quasi nul : 2 endroits backend (extract.py) + 2 lignes frontend
  (ingestion_serialize.js) + spec.

### Impact

- **Spec JSON v3** : passe à v3.2. Les exemples et la table des champs
  door utilisent désormais `seed_x` / `seed_y`.
- **Backend** : [`extract.py:1562-1564`](../olm/ingestion/extract.py#L1562-L1564)
  lit et pass-through les seeds renommés.
- **Frontend** : [`ingestion_serialize.js`](../olm/static/ingestion_serialize.js)
  écrit les seeds dans `roomObj.doors[<i>].seed_x` / `seed_y`.
- **Rétro-compat** : aucune — l'user a choisi « OK dernière version
  uniquement » pour les shims legacy. Les JSON v3.1 avec `label_x` /
  `label_y` ne seront plus lus (le champ sera ignoré, les portes
  chargées sans seed).

---

## D-137 · Métadonnées Floor `building_id` / `floor_id` / `north_angle_deg` wirées end-to-end (2026-04-21)

### Décision

Les 3 champs racine du JSON v3 documentés dans
[`docs/specs/PREPROCESSED_JSON_SPEC.md`](specs/PREPROCESSED_JSON_SPEC.md)
§1 mais jusqu'ici non-implémentés passent en wiring complet :

1. **Backend** ([`app.py`](../olm/server/app.py) `/api/import/preprocessed`) :
   retourne `building_id` (string), `floor_id` (string),
   `north_angle_deg` (float) lus depuis `json_data` — défauts `""` / `""`
   / `0` si absents.
2. **Frontend state** (`ingState.buildingId`, `ingState.floorId`,
   `ingState.northAngleDeg`) : seed au load Preprocessed, inchangés au
   load OCR (pas de source), reset à vide au Close plan.
3. **Sérialisation v3** ([`ingestion_serialize.js`](../olm/static/ingestion_serialize.js))
   : 3 champs écrits à la racine de l'objet `out` SEULEMENT si renseignés
   (convention d'omission, cohérent avec `first_scan_done`).
4. **UI** : section « Floor metadata » dans le panneau gauche Floor
   sous « Floor properties », 3 inputs (Building / Floor / North (°)),
   wiring bidirectionnel state ↔ inputs via `updateFloorMetadataUI()`
   (exposé sur `window` pour call des handlers load/reset).

### Justification

Les champs étaient spécifiés depuis plusieurs versions mais jamais
implémentés — ils disparaissaient à chaque round-trip Save/Load. L'user
a ouvert un JSON test en IDE et constaté leur absence. Avec ce wiring,
les métadonnées survivent à tous les cycles import/export et peuvent
être ajoutées ou corrigées depuis l'UI sans éditer le JSON à la main.

`north_angle_deg` reste purement métadonnée (voir spec §1) — n'affecte
pas la géométrie OLS. Il est destiné aux outils aval (ensoleillement,
orientation, ventilation) qui consommeront le JSON exporté.

### Impact

- **Code** : ~30 lignes ajoutées réparties sur 5 fichiers (app.py,
  ingestion.js, ingestion_serialize.js, init.js, pattern_editor.html).
- **Non-régression** : pass-through passif. Aucun call site existant
  ne dépend de ces champs.
- **Rétro-compatibilité JSON v3** : inchangée, les nouveaux champs
  sont optionnels (convention d'omission).

---

## D-136 · `room_sync_helpers.js` — source unique pour la mutation des 3 stores (2026-04-21)

### Décision

Nouveau module [`olm/static/room_sync_helpers.js`](../olm/static/room_sync_helpers.js)
expose deux helpers globaux :

- `window.syncRoomToAllStores(roomName, updates, fallbackCanonRoom?)` —
  mute en une opération atomique `ingState.rooms[i]`, `fpData.rooms[j]`,
  et `fpRoomAmendments[name]` pour la room cible. Priorité à `fpData`
  pour peupler `fpRoomAmendments` (version la plus riche) ; fallback au
  `canonRoom` enrichi des `updates` si `fpData` n'est pas peuplé. Warn
  console si la room n'est trouvée dans aucun store.
- `window.splitOpeningsToFrontEnd(combined)` — convertit la forme
  backend `openings[]` avec `has_door:bool` vers la forme state
  `{openings, doors}` (invariant D-122 P4). Source unique du split.

Migration de l'ensemble des call sites :
- [`ingestion.js`](../olm/static/ingestion.js) — handler batch Rescan
  all : ~80 lignes de triple mutation parallèle → 30 lignes
  déclaratives (dict `updates`) + 1 appel.
- [`editor.js` `save()`](../olm/static/editor.js) — Room amend : 3
  blocs séquentiels (ingRooms, fpData.rooms, fpRoomAmendments) + fix
  D-127 dédié absorbés dans l'appel unique.
- [`floor_plan.js`](../olm/static/floor_plan.js) — `fpRematchRoom()` et
  `fpLoadAndMatch()` consomment `splitOpeningsToFrontEnd`.

### Justification

Le pattern « muter les 3 stores en parallèle » est la racine structurelle
du bug D-135 rider (amendments pas propagés dans le handler batch post
Rescan destructif) et de la limite D-127 (`fpRoomAmendments` stale en
l'absence de `fpData` peuplé). Trois audits automatisés (ingestion.js,
init_rvtool.js, editor.js) du 2026-04-21 ont identifié ce pattern comme
priorité 2. Unifier la mutation à un point d'entrée :

- Rend impossible la divergence partielle entre stores (tous reçoivent
  les mêmes `updates`).
- Absorbe le fix D-127 par construction (fallback `canonRoom` systématique
  via le même chemin).
- Log warn explicite si la room est absente partout — détection précoce
  des futurs bugs de routage.

### Impact

- **Lignes économisées** :
  - `ingestion.js` : 2036 → 2008 (−28).
  - `editor.js`    : 2323 → 2280 (−43).
  - `floor_plan.js` : 994 → 976 (−18).
- **Non-régression** : `node --check` OK sur les 4 fichiers. Flask sert
  `/static/room_sync_helpers.js` (HTTP 200, 4875 bytes). Les comportements
  antérieurs (D-135 rider fix + D-127 fix) sont conservés — les tests
  user de référence (resize bbox → Save → re-ouvrir Review, batch Rescan
  avec Lock walls décoché) doivent rester verts.
- **Bonus UX dans le même commit de consolidation** : zoom arrière
  Review/Room passé de 3× à 5× `state._fitViewBox.w` ; seed visible dès
  V-Rays ou H-Rays activées (push sorti du bloc `room_hits`) ; bloc
  `EDITOR_CONSTANTS` (8 couleurs nommées + zoom + seed/hit radius) ;
  dead code `globalWestOffset` supprimé.

---

## D-135 · UX Scan / Lock walls + flags `walls_user_edited` & `first_scan_done` (2026-04-21)

### Décision

Refonte du vocabulaire et de la logique de re-détection raster, avec deux
nouveaux flags persistés dans le JSON v3 :

1. **Renommages UI** :
   - Floor : `Re-analyze all` → **Rescan all** (bouton `ingBtnReanalyzeAll`,
     ID conservé pour ne pas casser les call sites).
   - Room : `Re-analyze` → **Rescan** (bouton `rvBtnReanalyze`, ID conservé).
   - Room : `Add room items` → **Add items** (le contexte Room amend est
     déjà posé en en-tête, "room" redondant).
   - Room : checkbox `Lock bbox` → **Lock walls** (renommée
     `rvLockWalls` / `rvLockWallsWrap` pour cohérence).
   - Tous les libellés, tooltips et messages (`Rescan unavailable`,
     `Rescanning…`, `Rescan done`, `Rescan failed`) alignés.

2. **`walls_user_edited: bool`** — nouveau champ par pièce dans le JSON v3
   (racine `rooms[<id>]`). Cycle de vie :
   - `true` quand l'utilisateur resize la bbox via poignées en Room amend
     (init_rvtool.js mouseup `roomResizing`).
   - `false` après un Scan avec Lock walls **décoché** (scan destructif =
     les murs repartent de la détection automatique).
   - **Inchangé** après un Scan avec Lock walls coché (murs préservés,
     le flag user-edited reste valable).
   - À l'entrée en Room amend, la checkbox `Lock walls` est pré-cochée
     ssi `room.walls_user_edited === true`.

3. **`first_scan_done: bool`** — flag racine du JSON v3, persistant dans
   l'absolu :
   - Passe à `true` au premier Scan réussi (batch ou unitaire), reste `true`.
   - Contrôle la valeur par défaut de la case `ingLockWalls` (Floor) au
     chargement du plan. L'utilisateur peut la décocher pour lancer un
     scan destructif ; le flag racine ne repasse pas à `false`.
   - Effet de `ingLockWalls` sur le batch : `clip_to_bbox` envoyé au
     backend (`/api/room/reanalyze_batch`). Quand décoché, toutes les
     rooms scannées voient leur `walls_user_edited` remis à `false`.

### Justification

- « Re-analyze » recouvrait la fois la détection des murs et celle des
  ouvertures. Le renommage en « Scan » + « Lock walls » sépare nettement
  les deux intentions et évite que l'utilisateur relance par inadvertance
  un scan destructif qui écrase un bbox réglé à la main.
- `walls_user_edited` matérialise un état implicite : une pièce dont la
  géométrie a été ajustée manuellement doit, par défaut, être préservée
  aux scans ultérieurs. Sans flag persistant, le pré-cochage était
  volatile et perdu entre sessions.
- `first_scan_done` évite qu'un utilisateur ouvrant un plan déjà scanné
  perde toute sa géométrie en relançant « Scan all » distraitement
  (premier scan en session = case décochée précédemment, maintenant
  cochée par défaut).

### Impact

- **Frontend** :
  - `pattern_editor.html` : checkbox `ingLockWalls` dans la toolbar
    Floor, renommage des labels Lock bbox / Re-analyze.
  - `init_rvtool.js` : handler Scan Room met à jour `walls_user_edited`
    et `firstScanDone` ; mouseup resize marque `walls_user_edited=true`
    et coche automatiquement Lock walls.
  - `ingestion.js` : handler Scan all lit `ingLockWalls` et passe
    `clip_to_bbox` au backend ; reset `walls_user_edited` par pièce si
    scan destructif ; lecture de `first_scan_done` à l'import.
  - `ingestion_serialize.js` : sérialise `walls_user_edited` (par room)
    et `first_scan_done` (racine) dans le JSON v3.
  - `editor.js` : enter/exit Room amend mettent à jour l'état de la
    case `rvLockWalls` ; save propage `walls_user_edited` vers
    `ingRooms[]` et `fpData.rooms[]`.
  - `floor_plan.js` : `fpLoadAndMatch` préserve `walls_user_edited` à
    travers le re-match (non-retourné par `/api/floor-plan/match`).
  - `init.js` : Close plan reset `firstScanDone = false`.
- **Backend** (`app.py`) : `/api/import/preprocessed` retourne désormais
  `first_scan_done` (lu depuis `json_data`, défaut `False`). Aucun autre
  changement ; `/api/room/reanalyze_batch` acceptait déjà `clip_to_bbox`.
- **Schéma JSON v3** : deux champs ajoutés, sérialisation conditionnelle
  (absents = faux) pour rétro-compatibilité avec les plans antérieurs.
- **Non-régression** : les routes backend `/api/room/reanalyze*`
  inchangées ; les IDs HTML des boutons Scan (`ingBtnReanalyzeAll`,
  `rvBtnReanalyze`) conservés.

### Rider — bug fix batch amendments propagation

Découvert lors des tests : après un Scan all destructif (Lock walls
décoché), `fpData.rooms[i]` et `ingState.rooms[i]` recevaient bien les
nouvelles dims issues du ray-cast, mais `fpRoomAmendments[name]`
conservait les anciennes dims amendées. Or `rvRenderCurrent`
([floor_plan.js:200](olm/static/floor_plan.js#L200)) priorise
`fpRoomAmendments[name]` sur `fpData.rooms[i]` → la Review continuait
d'afficher les dims manuelles post-scan. Correction : propager aussi
`bbox_px / width_cm / depth_cm / width_px / height_px / surface_m2_bbox`
dans `am` au même titre que `windows/openings/doors/zones`.

---

## D-134 · R-14 P6 : `canonicalIO.canonAngle` (source unique rotation SVG) (2026-04-21)

### Décision

Le mapping `corridor_face_abs → angle SVG rotate` (south=0, east=90,
north=180, west=270) vit désormais dans `canonical_io.js` comme primitive
publique `canonicalIO.canonAngle(cfAbs)`.

`editor.js:_canonicalAngle` devient un wrapper mince (fallback si
canonicalIO non chargé). Le call site principal (overlay Room line 1044)
appelle directement `window.canonicalIO.canonAngle(...)`.

### Justification

Finalise P6 de R-14 (cf. D-121 / D-122) : la convention d'angle était
éparpillée en fonction locale dans editor.js alors que les matrices de
rotation (`FACE_MAPS`, `INV_FACE_MAPS`, `rotateRect`, `rotateRectInv`)
vivent déjà dans canonical_io.js. Incohérence levée.

### Impact

- **canonical_io.js** : +17 lignes (canonAngle + 5 auto-tests).
- **editor.js** : -1 fonction redondante → wrapper léger, call site
  inline préfère canonicalIO.
- **Tests** : 21/21 auto-tests canonical_io OK (16 → 21 avec les 5
  cas canonAngle).
- **Non-régression** : wrapper local conservé avec la même table pour
  les cas où canonical_io ne serait pas chargé (ordre de chargement
  scripts).

---

## D-133 · R-13 étape 3 + endpoint batch orientation-report (2026-04-21)

### Décision

Complément R-13 (auto-test d'orientation canonique D-119) :

1. **`check_windows_exterior(path, bbox, ocf, windows, scale)`** dans
   `olm/ingestion/orientation_check.py`. Itère sur les fenêtres en
   repère canonique, mappe chaque face canon → face absolue via
   `_CANON_TO_ABS[ocf]`, calcule la position pixel de la fenêtre, puis
   échantillonne une bande juste au-delà et mesure le ratio bleu
   (extérieur). Retourne verdict {ok | partial | fail} + détail par
   fenêtre.

2. **`/api/room/orientation-check`** étendu : accepte `windows` et
   `scale_cm_per_px` optionnels. Si fournis, invoque
   `check_windows_exterior` et ajoute `"windows"` à la réponse.

3. **`/api/floor-plan/orientation-report`** (batch) : nouveau endpoint.
   Pour chaque pièce du plan, calcule corridor_south + exterior_north +
   windows (si fournies), agrège un verdict par pièce, et retourne un
   résumé avec `n_total / n_ok / n_warn / n_fail + failing: [names]`.

### Justification

Étape 3 manquante pour compléter le triple-checkpoint R-13 : corridor
(sud), extérieur (nord), fenêtres (bleu). Le batch permet un audit
global du plan après ingestion ou rotation — utile pour détecter les
régressions silencieuses de rotation canonique avant qu'elles ne
remontent via des tickets utilisateur.

### Impact

- **orientation_check.py** : +113 lignes (`check_windows_exterior`).
- **app.py** : +85 lignes (endpoint batch + enrichissement single).
- **Tests** : 135/142 Python, pas de nouveau test ajouté (les fonctions
  nécessitent un PNG réel, tests E2E à faire via curl ou UI).

### Hors scope

- **UI Floor** pour visualiser le rapport batch agrégé : listé dans
  TODO.md comme suite, non bloquant.
- **Documentation** seuils et faux-positifs (cours intérieures) : à
  ajouter dans les specs R-13 quand le retour d'expérience existera.

---

## D-132 · Backend Re-analyze respecte bbox_px comme frontière (clip_to_bbox) (2026-04-21)

### Décision

Nouveau paramètre `clip_to_bbox: bool = False` à
`extract_room_features`. Quand `True`, le backend force solides (True)
tous les pixels hors de `bbox_px` dans le binary avant ray-cast. Les
rays de `_comb_detect_room` s'arrêtent aux bords du bbox user au lieu
de trouver les vrais murs au-delà.

Wiring :
- `/api/room/reanalyze` et `/api/room/reanalyze_batch` exposent le flag
  `clip_to_bbox` dans le body (default False).
- Frontend : `init_rvtool.js` Re-analyze envoie `clip_to_bbox:
  rvLockBbox.checked` → la case « Lock bbox » (D-126) active le clip.

### Justification

Bug utilisateur : avec Lock bbox ON sur une pièce rétrécie manuellement
(ex: 927 passée de ~350×500 à 242×308), Re-analyze détectait encore une
porte « fantôme » sur la face sud user. Hypothèse utilisateur (confirmée
par lecture de `extract.py:1809`) : le ray-cast opère sur le binary
global, `bbox_px` sert uniquement à positionner les masques — rien
n'empêche les rays de traverser les bords du bbox user et de trouver les
vrais murs au-delà.

Avec `clip_to_bbox=True`, la logique est simple et efficace : marquer
solides les 4 bandes extérieures au bbox dans le binary (copie locale
pour ne pas polluer `binary_precomputed` en batch). Les rays rencontrent
immédiatement un "mur" à la frontière du bbox → détection cantonnée au
bbox user.

### Impact

- **extract.py** : +1 kwarg, +15 lignes (clip logic via numpy slicing,
  binary.copy() pour isolation batch). Non-régression : default False.
- **app.py** : +1 lecture du flag dans chaque endpoint reanalyze, +1
  kwarg de passage.
- **init_rvtool.js** : +3 lignes, lecture checkbox.
- **Interaction avec D-129 (clamp)** : les openings hors bbox n'existent
  plus côté backend → D-129 devient largement no-op sur Lock ON, OK
  (ceinture + bretelles).
- **Batch** : `clip_to_bbox` exposé mais non utilisé par défaut côté
  frontend — batch garde sa sémantique de « reset auto-detect ». Opt-in
  possible ultérieurement si besoin.

---

## D-131 · Persistance `origin` dans JSON v3 (2026-04-21)

### Décision

Le champ `origin: "auto" | "manual"` sur chaque opening / window / door est
désormais persisté à travers toute la chaîne save/load/match :

- **Backend** (`OpeningSpec`, `WindowSpec`) : nouveau champ `origin: str |
  None = None` en fin de dataclass (keyword-only).
- **`/api/floor-plan/match`** : parse `origin` depuis le POST, l'émet dans
  la réponse uniquement si non-None (`**({"origin": x.origin} if x.origin
  else {})`).
- **`serializeForStorage` JSON v3** : inclut `origin` conditionnellement
  pour doors/openings/windows.
- **`canonicalIO.fromStorage/toStorage`** : déjà préservé via
  `Object.assign({}, o)`. Sample T1-south du round-trip enrichi avec
  `origin: "manual"/"auto"` pour valider.

### Justification

`origin` pilote la préservation des ouvertures manuelles au Re-analyze
(filtre `origin === "manual"` dans init_rvtool.js et ingestion.js batch).
Sans persistance, toute personnalisation utilisateur était perdue à la
session suivante : save → load → toutes les ouvertures redevenaient
`auto` par défaut, et le prochain Re-analyze les écrasait.

### Impact

- **Backend** : +2 champs dataclass, +4 lignes parsing/serialize app.py.
- **Frontend** : ingestion_serialize.js conditionnel sur `origin`,
  canonical_io.js sample enrichi.
- **Backward compat** : vieux JSON v3 sans `origin` → défaut None →
  non émis → pas de bruit.
- **Tests** : 3 nouveaux unit tests dans `test_room_model.py` (defaults,
  manual opening, manual window). Round-trip canonical_io 16/16 toujours OK.

---

## D-130 · Sync immédiat fpData + préservation currentIdx après bbox edit Floor (2026-04-21)

### Décision

Deux changements couplés pour corriger la race post-D-128 (commit bbox
edit → fpLoadAndMatch async) :

1. **Sync immédiat de fpData.rooms[i]** après le commit bbox edit mouseup,
   avant le fetch `/api/floor-plan/match`. La pièce éditée dans
   `ingState.rooms` est recopiée vers son homologue dans `fpData.rooms`
   (bbox_px, dims, openings, zones, seed_px).
2. **Préservation de `fpData.currentIdx` par NOM** à travers
   `fpLoadAndMatch` au lieu du reset systématique à 0.

### Justification

Deux bugs utilisateur reportés :

- « Je redimensionne 927 et si je double-clique dessus c'est 305 qui
  s'ouvre dans Review. » → Cause : fetch async résout avec
  `fpData.currentIdx = 0` ; 305 étant la 1re pièce alphabétique (natSort),
  elle s'affiche.
- « Je redimensionne 927, double-clic, elle s'ouvre mais apparaît entière
  (redimensionnement ignoré). » → Cause : pendant le gap async,
  `fpData.rooms[927]` est stale ; Review affiche la version pré-resize.

Les deux sont des races autour de `fpLoadAndMatch(ingState.rooms)` ajouté
en D-128. Le fetch backend peut prendre 100-500 ms ; l'utilisateur a
largement le temps de double-cliquer.

### Impact

- **floor_plan.js** : `fpLoadAndMatch` préserve currentIdx par name lookup
  (fallback 0 si la pièce a disparu). +10 lignes.
- **ingestion.js** : sync direct de fpData.rooms[i] sur commit bbox edit,
  avant le fetch. +20 lignes.
- **Idempotent** : le fetch arrive ensuite avec les mêmes données, override
  proprement.

---

## D-129 · Clamp openings acceptées par Re-analyze aux dims state (2026-04-21)

### Décision

Dans `init_rvtool.js`, clamp systématique des tableaux finaux
`newWindows.concat(manualW)` / `newOpenings.concat(manualO)` /
`newDoors.concat(preservedDoors)` aux dims courantes
`state.room_width_cm / depth_cm` avant assignation au state.

Helper `window.clampOpeningsToDims(openings, W, D)` extrait dans
`ingestion.js` (refactor de `clampRoomContentsToBbox` D-128 pour
réutilisation).

### Justification

Bug utilisateur D-126 Test 3 bis : Lock bbox ON + pièce rétrécie → openings
retournées par le backend extrêmement près du bord détecté, offset+width
dépassant la face réduite du bbox user locked. Résultat : portes / fenêtres
visuellement hors pièce.

Root cause : `canon.openings` sont dans le canon frame relative au **bbox
détecté par le backend**, pas au bbox user. Avec Lock, state dims restent
celles de l'user. Mismatch → overflow.

Clamp rend le comportement robuste pour :
- Lock ON : coupe les openings qui dépassent les dims user.
- Non-Lock : idempotent (dims adoptées = canon dims, openings déjà dans
  cette frame).
- Manuel concat : même clamp sur les manuels préservés, utile si un
  resize s'est glissé entre-temps.

### Impact

- **ingestion.js** : refactor `clampRoomContentsToBbox` en
  `clampOpeningsToDims` + `clampZonesToDims` (helpers publics) +
  orchestrateur. +15 lignes net.
- **init_rvtool.js** : 5 lignes avant les 3 assignations state.

---

## D-128 · Clamp openings/zones + sync fpData après bbox edit Floor (2026-04-21)

### Décision

Sur commit du bbox editor dans Floor (mouseup du drag des handles
NW/NE/SW/SE ou move), deux changements :

1. Nouveau helper `clampRoomContentsToBbox(room)` qui coupe les openings /
   windows / doors + zones au nouveau gabarit (rien de récupérable sous
   MIN_OPENING_CM = 10 cm n'est gardé).
2. Appel de `window.fpLoadAndMatch(ingState.rooms)` après le commit →
   `fpData.rooms` est re-synchronisé et les candidats re-matchés avec la
   nouvelle géométrie.

### Justification

Bug utilisateur : raccourcir une pièce dans Floor. Résultats observés :
- Les openings / portes / fenêtres dépassant les nouveaux murs restaient
  dans le state (visuellement hors pièce).
- Cliquer sur la pièce dans Review l'affichait avec ses dims/bbox
  d'origine, comme si le resize Floor n'avait rien changé.

Cause : le handler mouseup du bbox editor ne faisait que
`populateRoomsJson + updateIngRoomList + renderIngestion`. Aucune
propagation vers `fpData.rooms` (d'où Review stale), aucun clamp du
contenu de la pièce (d'où openings hors pièce).

### Impact

- **ingestion.js** : +45 lignes (clampRoomContentsToBbox helper + 2
  appels dans mouseup).
- **Limite** : clamp raisonne sur `room.width_cm/depth_cm` qui sont
  **absolus** dans ingState (le bbox editor les dérive de bbox_px). Pour
  corridor_face_abs ∈ {"", "south"} c'est identique au canonique (cas
  commun). Pour east/west/north la convention face N/S pouvant référer
  aux dims absolues ou canoniques, il y a un décalage potentiel —
  inconsistance pré-existante à corriger séparément.
- **Suppression d'openings** : si l'offset dépasse totalement le mur
  réduit, l'opening disparaît (aucune UI de récupération). Acceptable
  en proto.

---

## D-127 · Propagation du bbox effectif user au backend Re-analyze (2026-04-21)

### Décision

Sur Re-analyze unitaire (amend mode), calcul d'un `effBbox` qui intègre le
redimensionnement manuel fait par l'utilisateur (via `state.roomRenderOffset`
+ `state.room_width_cm / depth_cm`). Le backend reçoit ce bbox au lieu de
l'`origRoom.bbox_px` figé, donc détecte dans la zone vraiment éditée par
l'utilisateur.

### Pipeline

```
canonBboxUser = {x: roomRenderOffset.x, y: roomRenderOffset.y,
                 width: room_width_cm, depth: room_depth_cm}
   canonical frame (NW = canonical NW de la pièce originelle)

  ↓ canonicalIO.rotateRectInv(cfAbs, absOrigW, absOrigD)

absRel = {x, y, width, depth}  en cm, abs-room-local vs original NW

  ↓ × pxPerCm + origBbox[0,1]

effBbox = [x0, y0, x1, y1]  en px image absolus
```

`transparent_zones` sont ensuite converties canon→abs avec les nouvelles
dims effectives (`effAbsW / effAbsD`) au lieu des originelles. La re-ancrage
D-124 utilise aussi `effBbox` comme « vieux » repère (car les zones sont
relatives au canonical NW user).

### Justification

Test 3 D-126 : l'utilisateur raccourcit la pièce par le bas, coche Lock
bbox, clique Re-analyze. Attendu : la porte sud (qui était dans la zone
retirée) doit disparaître. Observé : porte persistait.

Cause : le backend recevait `origRoom.bbox_px` (bbox avant resize) et
détectait la porte originelle. Sans Lock : porte ré-appliquée dans la face
sud de la nouvelle pièce. Avec Lock : openings acceptées → même porte.

Avec D-127, backend reçoit `effBbox` → détecte dans la zone user, ne
trouve plus la porte → comportement attendu.

### Impact

- **init_rvtool.js** : +40 lignes. Calcul effBbox avant fetch, utilisé pour
  `bbox_px` payload, `transparent_zones` conversion, et reanchor D-124.
- **Pas de changement backend** ni batch : le batch re-analyze n'a pas
  de `roomRenderOffset` (hors amend mode).
- **Seed_px inchangé** : conservé comme repère image absolu. Cas edge : si
  le user shrunk tellement que la seed tombe hors de effBbox, le backend
  peut échouer proprement — à traiter séparément si besoin.
- **Limite connue** : au Save amend, `ramend.originalRoom.bbox_px` n'est
  pas mis à jour avec effBbox. Donc la persistence du resize dans JSON v3
  reste incomplète (dims persistent mais bbox_px reste originel). Bug
  latent à traiter séparément (listé dans TODO.md).

---

## D-126 · Toggle « Lock bbox » sur Re-analyze (2026-04-21)

### Décision

Case à cocher « Lock bbox » dans la Room toolbar (Review amend mode), à côté
du bouton Re-analyze. Quand cochée, le re-analyze ne modifie pas la géométrie
de la pièce : ni `bbox_px`, ni `width_cm` / `depth_cm`, ni
`corridor_face_abs`, ni `state.overlay.offsetX/Y`. Seuls les openings /
windows / doors / hits sont adoptés depuis la réponse backend.

### Justification

Use case D-118 : après un repositionnement manuel du bbox (drag NW corner de
la pièce) ou la dépose d'un mur modélisée via zone transparente,
l'utilisateur veut raffiner la détection des ouvertures **sans perdre** son
ajustement manuel. Sans lock, le re-analyze recalculait systématiquement le
bbox via ray-cast depuis le seed, écrasant le travail manuel.

Sémantique retenue : lock protège **toute la géométrie image-pixel** (bbox,
dims, overlay, cf). Les openings retournées par le backend restent dans leur
frame canonique d'origine ; si la détection backend a un écart mineur
(quelques px) avec le bbox utilisateur, les offsets seront très
approximativement corrects. Pour un écart important, l'utilisateur peut
décocher Lock et relancer.

### Impact

- **HTML** : nouveau `<label id="rvLockBboxWrap">` avec checkbox
  `rvLockBbox` après le bouton Re-analyze.
- **editor.js** : show/hide synchronisé avec l'amend mode (reset cleared à
  la sortie).
- **init_rvtool.js** : 2 sites gardés par `!lockBbox` :
  1. `amend.originalRoom.corridor_face_abs = canon.corridor_face` ;
  2. bloc bbox/dims/overlay/reanchor complet.
- **Rider** : reset `state.roomRenderOffset = {0,0}` dans la branche
  non-locked (re-analyze revient à la détection auto, donc le resize
  manuel antérieur doit aussi être reset sinon la pièce se retrouve
  visuellement décalée hors de l'overlay).
- **+12 lignes net**.

---

## D-125 · Fix race condition state.overlay partagé fp/rv (2026-04-21)

### Décision

`fpRenderSvg` ([floor_plan.js:470-486](../olm/static/floor_plan.js#L470-L486))
calcule désormais `state.overlay.offsetX/offsetY` depuis `room.bbox_px /
pxPerCm`, même convention que `fpRenderEmptyRoom:318-321`. Remplace
`room._overlayOffsetX || 0` — champ jamais initialisé côté producteur.

### Justification — race condition rvCanvas/fpCanvas

Symptôme utilisateur : après Save room puis pan sur le plan, l'overlay se
décale et la pièce arrive à (0,0) du plan raster.

Root cause : `state.overlay` est **partagé** entre les canvases (fpCanvas
Design / rvCanvas Review / canvas éditeur). Le flux Save room déclenche :
1. `rvRenderCurrent() → fpRenderEmptyRoom(rvCanvas)` synchrone : pose
   `state.overlay.offsetX/Y = bbox_px[0,1] / pxPerCm` (correct).
2. `fpRematchRoom(...)` en parallèle, `fetch` async ; à la résolution,
   appelle `fpRenderCurrent()` qui auto-clique le premier candidat →
   `fpRenderSvg(fpCanvas)`.
3. `fpRenderSvg` lisait `room._overlayOffsetX || 0` → jamais défini →
   `state.overlay.offsetX = 0, offsetY = 0`. **Écrase** l'état posé en 1.
4. Pan sur rvCanvas → mouseup → `render(rvCanvas)` → overlay rendu à
   (-0, -0) → la pièce (au NW en SVG coords) se retrouve alignée avec
   le pixel (0,0) du plan raster.

### Impact

- **Fix collatéral** : le rendu Design/fpCanvas avec overlay ON affichait
  aussi l'image mal alignée (top-left du raster au NW de la pièce) — bug
  silencieux pré-existant. Corrigé.
- **Pas de refactor architecture** : l'idée de splitter en
  `state.fpOverlay` / `state.rvOverlay` pour supprimer le shared-state
  reste pertinente mais non urgente. Notée pour plus tard si d'autres
  races émergent.
- **Fichiers modifiés** : 1 JS (+6 / -3 lignes).

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
- **Symptôme 1 fixé transitivement** (validé 2026-04-21 après tests user) : le
  « décalage nord au placement » n'était pas un bug du chemin de placement,
  mais une conséquence d'un re-analyze antérieur ayant dérivé les coordonnées
  stockées. Le chemin `rvScreenToRoomCm` → render est correct ; le re-ancrage
  D-124 supprime la source de dérive en amont.
- **Suite 2026-04-21 — fix `transparent_zones` canon→abs** : le backend
  `/api/room/reanalyze{,_batch}` (`extract.py:1757-1766`) interprète les zones
  en abs-room-local ; le frontend les stockait en canonique → mask mal
  positionné pendant la binarisation pour pièces non-south. Fix : helper
  `window.canonicalZonesToAbs(zones, cfAbs, absW, absD)` dans `ingestion.js`
  (map `rotateRectInv`, identité pour cfAbs ∈ {"", "south"}). Appliqué aux
  deux sites d'envoi (unitaire + batch). Latent sur pièces south testées
  jusqu'ici, invisible en surface mais corrige le masking des murs retirés
  pour orientations north/east/west.

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
