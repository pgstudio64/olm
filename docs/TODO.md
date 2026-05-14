# TODO — OLM (Office Layout Matching)

## Cible produit (D-188, 2026-05-14)

OLM = **outil interne mono-utilisateur, robustesse « bonne, pas critique »**. Cycle de modifications standard. Pas de multi-user, pas d'auth, pas d'HTTPS, pas d'i18n / a11y, pas de bundling Windows autonome. Détails dans [Decisions.md § D-188](Decisions.md).

## Roadmap consolidée (post-P0, post-audit v2)

Audit v2 dans [AUDIT_2026-05-v2.md](AUDIT_2026-05-v2.md). P0 livré (D-184/185/186/187 + tests P0.1/P0.2). Trois phases restantes :

### Phase 0 — Filet anti-régression (~5 h, préalable Phase 1)
- Renforcer assertions tests `/api/room/reanalyze` (structure complète des `windows[]`, `doors[]`, `openings[]`).
- Renforcer assertions tests `/api/floor-plan/match` (présence `all_candidates`, `desks`, scores numériques).
- Investiguer les 7 tests pré-existants cassés (`test_pattern_generator.py`, `test_catalogue_matcher.py`).

### Phase 1 — Solidification (~42 h)
- [x] **P1.1** ~~Casser le cycle `extract.py ↔ test_comb.py`~~ — D-189, v0.4.53. Renommage `comb_detection.py`, extraction `wall_classify.py`, suppression `main()`/`draw_debug_*`.
- [x] **P1.2** ~~Split `olm/server/app.py` en `olm/server/services/`~~ — D-190, v0.4.54. 2184 → 675 l. (-69 %). 5 modules : config_service (372), serialization (93), catalogue_service (269), matching_service (212), ingestion_service (968). 202 tests, 40 routes, 0 cycle.
- **P1.3** Tests `olm/core/circulation_analysis.py` (grades A-F, détours, violations) — couverture 0 % → 80 % cible (~8 h).
- **P1.4** Cleanup 77 `addEventListener` côté front sans `removeEventListener` (~7 h).
- [x] **P1.5** ~~Remplacer `traceback.print_exc()` par `logger.exception()`~~ — integre dans P1.2, v0.4.54. 0 restant dans `app.py`.

### Phase 2 — Robustesse opérationnelle (~40 h)
- **Verrou mono-utilisateur** : état en mémoire Flask (pas de lock file → reset au redémarrage = pas de blocage post-crash). Cookie session, page « OLM déjà en cours d'utilisation » + bouton « Prendre le contrôle », idle timeout 30 min (~4 h).
- **Validation jsonschema** à l'import JSON v3 (~12 h).
- **Écritures atomiques** temp+rename + `.bak` sur save (~5 h).
- **`MAX_CONTENT_LENGTH` Flask + whitelist MIME upload** (PNG/JPEG/PDF) (~2 h).
- **Logger Python + `RotatingFileHandler`** (pas JSON, format standard) (~6 h).
- **Endpoint `/health`** (config lisible, catalogue valide) (~2 h).
- **GitHub Actions basique** : `ruff check` + `pytest` au push (~3 h).
- **`USER_GUIDE.md`** : workflow import → review → export, captures intégrées (~6 h).

**Total restant : ~87 h sur 2-3 mois.**

**Cible couverture tests** : 60 % sur `olm/core` et `olm/server`.

## Chantiers documentaires en suspens

- Q-EX-1 à Q-EX-5 : préciser EF-EX-02 (export package PNG/PDF + CSV) — voir [SRS § 3.9](SRS.md).
- EF-VW-03 : inventorier les champs affichés en vue Office (donne la structure du CSV d'export).
- SDS.md à réécrire **après** Phase 1 (chantier DOC-E à planifier).

## Hors périmètre D-188 (réévaluables si besoin évolue)

- Authentification multi-utilisateur (`flask-login`).
- WSGI prod (gunicorn / waitress).
- HTTPS / TLS.
- File de travaux (`dramatiq`, `rq`) pour OCR longues.
- PyInstaller bundling Windows autonome.
- Internationalisation (Flask-Babel).
- Accessibilité WCAG AA.
- Logging structuré JSON / Prometheus metrics / ZIP diagnostic.

---

## Contexte replay v0.4.5 (2026-04-26 → 2026-04-29)

Rollback sur v0.4.5 (`be08ec0`) après régressions D-143→D-147. Replay
sélectif terminé. D-154 + D-155 + D-156 ajoutés post-replay.

| Unité | Statut | Notes |
|---|---|---|
| D-143 (classify_step_cm) | **Rejoué** | `classify_step_cm=15.0` + `image-rendering: pixelated` |
| D-144 (pxScale overlays) | **Déjà appliqué** | pxScale présent dans ingestion.js |
| D-145 (binary_for_arcs + seeds anchoring) | **Rejoué** | dual binary, `_seed_scan_range`, seed_x/seed_y, batch raw |
| D-146 (flèches désactivées Room amend) | **Rejoué** | `window.editorState` + guard floor_plan.js |
| D-147 (R²-fit detection) | **NE PAS rejouer** | cassé — reconcevoir après stabilisation |
| D-148 (cartouches OCR rescan) | **Commité** | eb9897a |
| D-149 (cm-only frontend) | **Commité** | eb9897a |
| D-150 (snap search + dead code cleanup) | **Commité** | eb9897a |

**Backups** : branche `backup-pre-replay` (à `72cd9a6`), stash pré-reset,
`/tmp/olm-pre-replay/`.

**Plan de replay détaillé** :
`~/.claude/plans/est-il-possible-de-repartir-zippy-elephant.md`.

**Bugs connus** :
- *H-rays débordants* (room 900 big) : rays H s'étendent ×100 au-delà de la pièce
- *Gel UI ArrowRight* sur dernière pièce en Room view
- ~~*Rescan all (Floor) ne re-OCR pas*~~ → D-154 : mode source persistant dans le JSON, propagé au batch rescan
- ~~*Scale OCR faux (DPI inconnu)*~~ → D-155 : auto-calibration depuis surfaces annotées
- ~~*Overlay invisible sur plans haute résolution*~~ → D-155 : pxScale appliqué à tous les strokes/fonts
- ~~*Fenêtres sud/est invisibles en Floor view*~~ → D-156 : bug JS string concat dans `drawWallFeature` (`parseFloat`)
- ~~*Preprocessed : aucune fenêtre après rescan*~~ → D-156 : `color_img` chargé depuis -SD, pas depuis overlay
- ~~*Fausses fenêtres sur murs intérieurs preprocessed*~~ → D-156 : filtre extérieur bleu + suppression fallback full-face
- ~~*Import preprocessed sans bbox : pièces carrées sans features*~~ → D-157 : `extract_room_features` complet à l'import (ray-cast + fenêtres + ouvertures + portes)

**Défauts production restants (2026-04-29)** :
- ~~*D2 — Door seeds invisibles en Floor*~~ → D-158 : toggle Seeds séparé + rendu door seeds en Floor et Room.
- *D4 — Portes mal identifiées / pièce réduite côté sud* : détection de portes imprécise, bbox tronqué au sud sur certaines pièces
- ~~*D8 — Rays invisibles en Floor après Rescan All*~~ : corrigé par le refactoring 3 couches SVG (session 2026-05-11).
- ~~*D9 — Message seuil binarisation décale les paramètres*~~ : corrigé session 2026-05-11 (span déplacé dans le div flex).

**Retours tests production (2026-05-08)** :

*Problème critique — Échelle :*
- Échelle auto-détectée souvent fausse (1:157 au lieu de 1:300). Forte sensibilité du rescan à l'échelle. La détection (fenêtres, portes) dépend beaucoup de l'échelle correcte.
- → Utiliser l'échelle indiquée sur le plan quand elle est présente (priorité sur l'auto-calibration).

*K — Cas à traiter (par pièce) :*
- K2 — Poteau 20 cm côté fenêtre : centres vus comme ouvertures. Après mise à l'échelle : vert en haut + porte 508 cm à la place de la fenêtre. → **Poteaux** : min_obstacle_width_cm à implémenter dans le ray-cast.
- K3 — ~~Fenêtre dépasse le mur de 10 cm~~ D-158. Grande ouverture au sud → **D-159 opening depth validation** devrait reclasser en mur.
- K4 — Grande porte détectée quand la fenêtre fait un arrondi. → Utiliser le bleu extérieur pour discriminer.
- K5 — ~~Décalage de demi-hauteur vers le haut~~ → **D-159 other_seeds** passé au rescan (les rays ne dépassent plus les pièces voisines). À revalider.
- K6 — Orientation KO pour toutes les pièces de l'aile ouest (bleu à gauche). Poteau 20 cm, porte non reconnue même après ajustement mur + rescan. Reconnue après mise à l'échelle.
- K8 — Porte non détectée alors que les rays la voient très bien.
- K12 — ~~Inversion complète du dessin/rays~~ → **D-159 other_seeds** (même cause que K5). À revalider.
- K14 — Non détection de la porte (partiellement invisible sur le plan).
- K16 — Non détection de la porte (partiellement invisible sur le plan).
- K25 — ~~Inversion complète de la détection~~ → **D-159 other_seeds** (même cause que K5). À revalider.
- K77 — Modification manuelle de la pièce : sauvegarde décalée de 40 cm en dessous de la position apparente.

*Orientation :*
- D-162 (closest-first orientation) : codé dans v0.4.22, **à valider sur prod** quand la plate-forme pourra récupérer la nouvelle version.

*Transversal :*
- ~~Seeds de porte jamais visibles sur le plan~~ → D-158 (toggle Seeds, door seeds en Floor+Room).
- ~~Inversions détection/affichage récurrentes (K5, K12, K25)~~ → D-159 other_seeds au rescan. Cause : rays traversaient les pièces voisines, pas un problème d'orientation canonique.
- Portes partiellement dessinées sur le plan non détectées (K14, K16) → seuil de détection arc trop strict ?

*R — Réglés :*
- ~~Arcs de porte non noirs sur certains plans~~ → D-158 binarize_threshold 110→140 (configurable dans Settings).
- Échelle auto-détectée fausse (1:300 au lieu de 1:200 sur un autre plan) — même famille que le problème critique ci-dessus.
- Selon l'échelle, la détection est plus ou moins efficace (ex: fenêtres non identifiées).

**PRIORITÉ CRITIQUE** :
- **PERF — Import preprocessed 2× plus lent** : régression perf constatée sur plans réalistes après v0.4.45. Analyser et corriger. Profiler `extract_rooms_from_preprocessed` et `extract_room_features`.
- ~~**Ouverture parasite à chaque porte**~~ : corrigé D-174 — `_filter_openings_overlapping_doors`.
- **Ouverture impossible → recherche du mur derrière** : quand une ouverture couvre plus de ~70% de la longueur d'une face non-couloir, c'est un artefact de détection (ray-cast traversant vers la pièce voisine). Dans un bureau réel, une face latérale ou de fond n'est jamais ouverte à 70%+. Au lieu de remplacer bêtement par un mur plein, chercher le mur réel derrière l'ouverture (il peut être incomplet — ex. mur avec porte ou décalé). Seuil paramétrable dans detection_config.
- **Zones d'exclusion manuelles KO dans Room** : l'ajout manuel d'une zone d'exclusion via le dessin à la souris produit des coordonnées fantaisistes et la zone n'est pas visible. À investiguer (conversion coordonnées écran → room-local).
- ~~**Fenêtres simples KO si bbox trop loin du bleu**~~ : corrigé D-177 — `_face_is_exterior` remplace la bande fixe 50 cm par un scan directionnel proportionnel au bbox avec vérification de seeds.

**Bugs prioritaires** :
- ~~**B1 — Inversion ouest/est en mode Room**~~ : corrigé D-169 v0.4.34.
- ~~**B2 — Import / ouverture plan pas propre**~~ : corrigé session 2026-05-11.
- **B3 — Import preprocessed lent sans rescan** : un import preprocessed sans rescan (tout est dans le JSON) devrait être quasi-instantané. Actuellement c'est lent. À analyser.
- **B4 — Zoom out Floor dépasse le plan** : en mode Floor, le zoom out ne devrait pas aller au-delà de la taille du plan. Limiter le dézoom max pour que le plan remplisse la vue.

**Chantiers identifiés (non traités)** :
- ~~*Paramètres OCR dans Settings*~~ → D-155 : `cartouche_margin_cm` et `text_skip_margin_cm` exposés dans Floor > OCR Detection. Propagés au backend via `_get_detection_overrides()` → `DetectionConfigCm.from_dict()`.
- *Format JSON v3 en cm primary* (portes/ouvertures/fenêtres : `offset_px`/`width_px` → cm source de vérité)
- *Couleurs vert/bleu pour améliorer détection preprocessed* (valider portes sur face verte, fenêtres sur face bleue)

---

Dernière mise à jour : 2026-04-29 (D-157 : import preprocessed détection complète)

> Renommage OLO → OLM (D-67). Le projet est un planificateur d'aménagement de bureaux, pas un optimiseur au sens mathématique. Le nom reflète l'ensemble des fonctionnalités : ingestion, matching, revue, export.

Orientation stratégique : **pattern = pièce + standard** (D-35/D-36). Chaque pattern est conçu pour une pièce de taille, géométrie et standard donnés.

Stratégie de peuplement du catalogue (D-55) : construction du bas vers le haut — chaque pattern est créé à la taille minimale de pièce pour un assemblage de blocs donné. Le front de Pareto du matching sélectionne automatiquement le meilleur. Voir `specs/CATALOGUE_STRATEGY.md`.

---

## Architecture cible

### Séparation open source / spécifique (D-68)

Deux parties distinctes dans le système de fichiers :

```
olm/                              ← OPEN SOURCE (licence MIT)
├── LICENSE                       ← MIT
├── README.md
├── pyproject.toml
├── requirements.txt
├── install.bat                   ← Windows : crée le venv + installe
├── launch.bat                    ← Windows : démarre le serveur
├── src/
│   └── olm/
│       ├── core/                 ← modèles, matching, scoring, circulation
│       ├── ingestion/            ← pipeline extraction raster (ray-cast)
│       ├── rendering/            ← SVG, PDF
│       ├── server/               ← Flask app, API, templates HTML/JS
│       └── config/               ← defaults, schema validation, paramètres
├── static/                       ← JS partagé (block_svg, block_constants…)
├── templates/                    ← HTML
└── tests/

project/                          ← SPÉCIFIQUE (non publié)
├── standards/                    ← définitions des standards métier
│   ├── std_1.json                ← ex-AFNOR_ADVICE
│   ├── std_2.json                ← ex-GROUP
│   └── std_3.json                ← ex-SITE
├── catalogue/
│   └── patterns.json
├── config.json                   ← paramètres spécifiques (room_code, labels…)
├── test_rooms.json
└── plans/                        ← plans raster de test

docs/                             ← INTERNE (non publié)
├── SRS.md, SDS.md, TODO.md
├── specs/
├── Decisions.md
└── CHANGELOG.md
```

### Interface : 2 onglets principaux + Settings

```
┌─────────────────────────────────────────────────────────────────── ⚙ ┐
│  Floor Plan  │  Office Layout  │                              Settings │
├──────────────┴─────────────────┘                                      │
│                                                                       │
│  Floor Plan sous-onglets :                                            │
│  ┌────────┬────────┬────────┬────────┐                                │
│  │ Import │ Review │ Match  │ Export │                                │
│  └────────┴────────┴────────┴────────┘                                │
│                                                                       │
│  Office Layout sous-onglets :                                         │
│  ┌───────────┬─────────┐                                              │
│  │ Catalogue │ Editor  │                                              │
│  └───────────┴─────────┘                                              │
└───────────────────────────────────────────────────────────────────────┘
```

### Paramètres centralisés (Settings ⚙)

Panneau accessible via la roue dentée, organisé en sections :

| Section | Paramètres |
|---|---|
| **General** | `room_code` (défaut "14"), `default_door_width_cm` (90), `desk_width_cm` (80), `desk_depth_cm` (180), `grid_cell_cm` (10) |
| **Standards** | Nombre, noms affichés (label_1, label_2, label_3), valeurs ES-*/PS-* par standard |
| **Matching** | Poids densité vs confort (`w_density`, `w_comfort`), seuils de couverture |
| **Ingestion** | Échelle, seuil binarisation, pas ray-cast, code pièce |
| **Export** | Formats activés (JSON, CSV, PDF), options PDF |

Migration de paramétrage : bouton "Upgrade to new standard" qui lit le paramétrage actuel, applique les nouveaux defaults, affiche le diff et demande validation.

---


---

## Chantiers actifs — Refonte OLM

### R-12 consolidation — réduction de dette (C1 → C4) ✅ D-120

Livrée en 2026-04-20 (D-120). Quatre étapes réalisées :

- [x] **C1** — `_canonicalizeRoom` / `_decanonicalizeRoom` +
  `_FACE_MAPS` / `_INV_FACE_MAPS` supprimés de `floor_plan.js`.
  `editor.js save()` (Room amend) bascule sur `canonicalIO.toStorage`.
  Bug latent corrigé : `origCf` lu depuis `original_corridor_face` en
  priorité (corridor_face est toujours "south" en canon R-12).
- [x] **C2** — `computeCanonicalReanalyzeResult` réécrit en wrapper
  mince autour de `fromStorage`. Matrice `FACE_MAPS` locale disparue.
- [x] **C3** — Fusion des sérialiseurs dans `ingestion_serialize.js`
  (renommé). Nouvelle API `window.olmSerialize`.
- [x] **C4** — `fpLoadAndMatch` bimode (string legacy / Array direct).
  Call sites internes (ingestion.js) passent `ingState.rooms`. Textarea
  devient informatif.

**Dette différée (non bloquante)** :
- Fusion `bbox_px` / `bbox_abs_px` et `seed_px` / `seed_abs_px` en un
  seul champ : refactor plus lourd des consommateurs overlay, à faire
  en bloc plus tard.
- ~~`offset_px` non rotés par `toStorage`~~ ✅ livré : recalculé à la
  sérialisation dans `serializeForStorage`.
- ~~Amendements Room perdus à l'export v3~~ ✅ livré : `editor.js save()`
  propage windows/openings/doors/zones vers `ingState.rooms`.
- Bug **bouton Save** : clic programmatique fonctionne, clic physique
  non intercepté (`document.elementFromPoint` retourne undefined à
  la position du bouton). Confirmé non-lié à C1-C4 après consolidation.
  À investiguer séparément — probablement un overlay transparent qui
  capture les events (pas de liseré `:hover`, pas de click).
  *Note : D-132 « Save button fullscreen » mentionne un fix dans la
  session D-121 ; vérifier si le bug physique est encore reproductible.*
- [x] Bouton **Check orient.** ajouté et fonctionnel (stylé en mode
  dev discret, gris foncé, D-135 rider).

### R-14 : Refactor canonique unifié (D-121) — ✅ LIVRÉ (D-122 P1-P7 + D-134 rider P6)

Plan complet : `docs/specs/CANONICAL_REFACTOR_PLAN.md`.

Origine : 4 sessions de fixes sur le repère canonique (D-117, D-120, +
3 commits même journée) révèlent l'absence d'une frontière unique, de
structures uniformes, et d'un contrat front/back explicite. Les 6
symptômes observés (902/915/922/906/...) partagent la même cause
racine. Refactor structurel en 7 phases.

- [x] **P1 — Rotation `offset_px` intégrée à canonicalIO** ✅ 2026-04-20
  (D-122). Signature `fromStorage(room, scale)` / `toStorage(room,
  scale)` ; helper `_syncPx` interne recalcule
  `offset_px = round(offset_cm × pxPerCm)` après la rotation de
  `offset_cm`. Recalculs ad-hoc supprimés dans `_pxFromCm` et
  `_renderFeat` ; tous les call sites passent désormais `scale`.
  Tests round-trip 4/4 OK avec `offset_px` intégré aux samples.
- [x] **P2 — Fusion `bbox_abs_px` / `seed_abs_px`** ✅ 2026-04-20
  (D-122). Champs redondants supprimés ; `bbox_px` / `seed_px` seules
  coords image absolues (jamais rotés). Adapté dans canonical_io,
  editor.js save, init_rvtool re-analyze, ingestion batch re-analyze,
  fpLoadAndMatch.
- [x] **P3 — Renommage `original_corridor_face` → `corridor_face_abs`** ✅
  2026-04-20 (D-122). Rename global front + endpoint
  `/api/room/orientation-check`. Lectures ambiguës
  `room.original_corridor_face || room.corridor_face` supprimées (4
  sites : _canonicalAngle, _absToCanon2, editor.save, init_rvtool
  re-analyze). `state.corridor_face` retiré. JSON v3 disque inchangé.
- [x] **P4 — Séparation openings/doors uniforme dans state** ✅
  2026-04-20 (D-122). `state.room_doors` introduit comme collection
  séparée ; `has_door:true` banni du state. `buildRoomDSL`,
  `_stateToDsl`, `renderRoomElements`, CRUD, `_rvCommitFromState`,
  batch re-analyze et amendments adaptés. Combine+split aux
  frontières supprimés. Forme combinée conservée uniquement aux
  frontières API externes (matching, catalogue disque).
- [x] **P5 — Contrat front/back `/api/floor-plan/match`** ✅
  2026-04-20 (D-122). Frontend envoie du canonique (suppression
  `toStorage` préalable dans `serializeForMatching` + `editor.save`).
  Backend suppose canonique (docstring explicité) ; pas de
  `canonicalize_room()` ajoutée côté Python (redondant si frontend
  respecte le contrat). `fpLoadAndMatch` / `fpRematchRoom` splittent
  l'openings combiné reçu pour préserver l'invariant P4.
- [x] **P6 — Suppression des conversions ad-hoc** ✅ 2026-04-20
  (D-122). Helpers publics `canonicalIO.rotatePoint` /
  `canonicalIO.rotateRect` ajoutés (8 assertions auto-test).
  `pointAbsToCanon` (ingestion.js) et `_absToCanon2` (editor.js)
  supprimés.
  **Complément P6 livré 2026-04-21 (D-134)** : `_canonicalAngle`
  migré comme `canonicalIO.canonAngle` (5 auto-tests). Editor.js
  devient wrapper mince de la source unique.
  FACE_MAPS restent dans canonical_io (sources uniques) et ne sont
  plus dupliquées ailleurs.
- [x] **P7 — Tests round-trip complets + spec** ✅ 2026-04-20
  (D-122). Nouveau `docs/specs/CANONICAL_STATE.md` (structure, 4
  frontières I/O, API publique, 6 antipatterns). 12 auto-tests dans
  `canonical_io.js` (4 round-trips + 8 rotations), tous verts via
  Node. Tests Python `test_canonical.py` 19/19.

Arbitrages figés post-livraison :
- Backend `/api/room/reanalyze` reste en absolu (pragmatique, validé).
- JSON v3 sur disque reste en absolu, renommage `original_corridor_face`
  → `corridor_face_abs` appliqué côté frontend uniquement.
- `scale` passe bien à tous les call sites canonicalIO.

### R-13 : Auto-test d'orientation canonique (D-119)

Objectif : valider automatiquement l'invariant « posture humaine » R-12
via les couleurs sémantiques du PNG -SD. Évite les régressions silencieuses
sur fromStorage / rendu / rotation / flux re-analyze.

- [x] **Étape 1 — Test corridor sud canon (minimal)** ✅ D-119 (commit 48b2377).
  `olm/ingestion/orientation_check.py:check_corridor_south`.
- [x] **Étape 2 — Test extérieur nord canon** ✅ D-119.
  `check_exterior_north` + `check_all_faces` diagnostic.
- [x] **Étape 3 — Test fenêtres côté bleu** ✅ 2026-04-21 (D-133).
  `check_windows_exterior(path, bbox_px, ocf, windows_canon, scale)`
  itère sur les fenêtres canoniques, mappe chaque face canon → face abs
  via `_CANON_TO_ABS`, échantillonne la bande restreinte à la largeur
  fenêtre, retourne verdict (ok/partial/fail) + détail par fenêtre.
- [x] **Endpoints** ✅ `/api/room/orientation-check` (1 pièce, D-119)
  enrichi en D-133 avec param `windows` + `scale_cm_per_px` optionnels.
  Batch `/api/floor-plan/orientation-report` ajouté en D-133 avec
  résumé (n_ok/n_warn/n_fail + failing names).
- [ ] **UI** : bouton Room toolbar `Check orient.` existant (étape 2 R-13).
  À ajouter : bouton Floor toolbar pour le rapport batch + vue
  aggrégée avec pièces failing listées. Pas bloquant pour la validation
  automatique — la CLI/curl suffit en attendant.
- [ ] **Documentation** : seuils et faux-positifs (cours intérieures,
  pièces enclavées) dans la spec.

### R-12 : Repère canonique unifié — posture humaine invariante (D-117) — ✅ ABSORBÉ dans R-14

Le plan R-12 initial (étapes A/B/C) a été remplacé par le refactor structurel
R-14 P1-P7 (D-122, rider P6 en D-134). Les étapes A/B/C sont livrées
implicitement :
- [x] **Étape A** (fromStorage/toStorage coexistence) → devenu `canonicalIO.fromStorage/toStorage` en R-14 P1.
- [x] **Étape B** (retrait `_canonicalizeRoom`/`_decanonicalizeRoom`) → R-12 C1 (D-120).
- [x] **Étape C** (rotation CSS overlay) → livré par `canonicalIO.canonAngle` + rotation SVG (D-134).
- [x] Matrices mutualisées dans `olm/static/canonical_io.js` (R-14 P6).

Renommage `corridor_face` (state) → `_canonical_south` **non retenu** :
le state garde `corridor_face = "south"` invariant + `corridor_face_abs`
pour l'orientation réelle (D-122 P3).

### R-04 : Floor Plan — 4 sous-onglets (Import / Review / Match / Export)

#### Import

Objectif : ingestion simplifiée — rectangles + murs + fenêtres + ouvertures. Pas de zones interdites (ajoutées en Review).

- [x] ~~Bug overlay post-simplification Import~~ — corrigé : overlays persistés dans `olm_overlays/` ([app.py:594-600](../olm/server/app.py#L594-L600)).
- [x] ~~Bug Save inactif après pan/scale/fullscreen~~ — non reproduit au 2026-04-19.

- [x] ~~**Grille 1m côté négatif invisible (Floor)**~~ : corrigé — refactor gridSvg en SVG patterns, couverture complète y compris coordonnées négatives.

Abandonné (inutile) : saisie manuelle d'échelle (cm/px ou points de calage) et saisie de code pièce à l'import — l'échelle vient de `plan_scale` du JSON v2 en Préprocessé ou des métadonnées OCR, le code pièce vient de Settings.

#### Review

Objectif : amender les pièces importées avant matching. Remplace l'ancien "Adjust room" (D-63).

- [x] CRUD ouvertures : ajout, suppression, déplacement, redimensionnement (D-103). Changement de type non implémenté (on supprime et on redessine).
- [x] **Zones interdites et transparentes (Room)** : zones interdites (rouge, `EXCLUSION`) et zones transparentes (vert, `TRANSPARENT`) définissables dans Room amend mode via le dropdown "Add room items" (D-103).
- [x] **Bug zones d'exclusion — déplacement vertical intempestif** ✅
  2026-04-21 (D-124) — les deux symptômes fixés par le re-ancrage des
  zones à la position absolue image après re-analyze
  (`reanchorCanonicalZones`, pipeline canon → abs → abs(new) → canon(new)).
  - Symptôme 2 (re-analyze) : root cause directe — zones restaient en
    canonique room-local alors que le bbox détecté dérivait dans l'image.
  - Symptôme 1 (placement décalé nord au clic) : cause commune, pas un
    bug de placement. L'état des zones avait déjà dérivé via un
    re-analyze antérieur ; le placement suivant héritait de coordonnées
    canoniques pointant sur un feature décalé. Validé par l'utilisateur
    après D-124.
- [x] **Relance analyse pièce (Room)** (D-104 puis D-107) : bouton "Re-analyze" en Room amend mode fait un ray-cast depuis seed via `comb_detection.detect_room`, masque auto portes + zones transparentes, recalcule bbox + windows + openings. V/H-rays visualisables. Masques debug affichés.
- [x] **Préserver les modifications manuelles** (D-104) : chaque élément porte `origin: "auto"|"manual"` ; la ré-analyse remplace uniquement les auto et respecte `deleted_auto_signatures` pour éviter la réapparition d'éléments auto supprimés.
- [x] **Persistance `origin` dans le JSON v3** ✅ 2026-04-21 (D-131).
  `WindowSpec` / `OpeningSpec` portent `origin: str | None = None`.
  `serializeForStorage` et `/api/floor-plan/match` parse/emit le champ.
  Round-trip canonical_io validé.
- [x] **Re-analyze + resize pièce** ✅ 2026-04-21 (D-127). Propagation du
  bbox effectif user au backend (`canonBboxUser → rotateRectInv → +origBbox →
  effBbox`). Le backend détecte dans la zone éditée et non dans l'ancien
  bbox. S'applique aux deux modes Lock et non-Lock.
- [x] ~~**Persistence Save room : bbox_px non mis à jour si resize**~~ ✅
  2026-04-21 (D-127 limite levée). Écriture unique et inconditionnelle de
  `fpRoomAmendments[name]` en fin du bloc Room amend save, priorité à
  `fpData.rooms[fr]` si existe (plus riche), fallback à `canonRoom` enrichi
  du `newBbox` sinon. Investigation :
  [`docs/INVESTIGATION_D127_save_bbox.md`](INVESTIGATION_D127_save_bbox.md).
- [x] ~~**Zoom arrière bloqué trop tôt (Review / Room)**~~ ✅ 2026-04-21.
  Limite zoom-out passée de 3× à 5× `state._fitViewBox.w` dans
  `zoomOut()` ([editor.js:2191](olm/static/editor.js#L2191)).
- [x] ~~**Re-analyze instable — 2 passes quasi systématiques**~~ ✅ fixé
  2026-04-20 : bug dans le filtre `preservedDoors` (init_rvtool.js /
  ingestion.js). Utilisait `o.origin !== "auto"` → capturait les doors
  initiales (origin:undefined) et bloquait la redétection au 1er appel.
  Passé à `o.origin === "manual"`, cohérent avec `manualW` / `manualO`.
- [x] **Perf Re-analyze All** ✅ 2026-04-20 (D-123). Mesuré ×9.83
  speedup sur M4 : 831 ms/pièce → 15 ms/pièce + 831 ms one-shot
  précompute. Extrapolation 28 pièces sur cible CPU 10× plus lent :
  ~230 s → ~13 s. Mise en œuvre : `extract_room_features` accepte
  `binary_precomputed`, `/api/room/reanalyze_batch` calcule
  binarisation + `remove_non_ortho` une fois en amont.
- [x] **Toggle « lock bbox » sur Re-analyze (D-118)** ✅ 2026-04-21 (D-126).
  Checkbox dans la Room toolbar. Quand coché, le re-analyze ne modifie pas
  `state.room_width_cm/depth_cm`, `originalRoom.bbox_px`, `corridor_face_abs`
  ni l'overlay ; seuls les openings/windows/doors/hits sont adoptés. Reset
  automatique à la sortie de l'amend mode.
- [x] ~~**Re-analyze : fusionner Re-analyze + lock-bbox dans un dropdown**~~
  → résolu autrement (D-135, 2026-04-21). Renommage `Re-analyze` → `Rescan`
  et `Lock bbox` → `Lock walls`, visible à côté du bouton Rescan (Room et
  Floor). Checkbox pré-cochée selon `walls_user_edited` (Room) ou
  `first_scan_done` (Floor), avec persistance JSON v3.
- [x] **Bouton Close** : ferme le projet courant avec confirmation (warning unsaved changes implicite).
- [x] **Bouton Erase** (All / Layout only) avec confirmation.

#### Layout général

- [ ] **Taille minimale de la zone centrale (plan / pièce)** : définir un
  seuil min raisonnable pour la zone d'affichage du plan (Floor) ou de
  la pièce (Room / Office). En-dessous, soit scroll horizontal/vertical
  sur la zone, soit empêcher que les panneaux latéraux ne la rabotent
  jusqu'à l'invisibilité. Cas d'usage : fenêtre rétrécie ou écrans
  étroits.

#### Office (ex-Match/Design)

- [ ] **Bug "No matching patterns"** : le matching ne trouve aucun candidat — investiguer pourquoi (échelle, dimensions, catalogue vide ou incompatible ?)
- [ ] **Amend layout en place** : éditer la solution directement dans Office (sélection de blocs/postes, suppression Delete, sauvegarde), sans basculer vers l'éditeur de patterns

#### Export

- [ ] Export CSV : tableau tabulaire importable dans Excel (inclut traçabilité des amendements manuels)
- [ ] Export PDF : fond de plan raster + overlay aménagement

### R-05 : Module d'ingestion — Dual-mode (OCR + Préprocessé)

#### Mode OCR — Validation Tesseract sur test_floorplan3 (D-73)

- [ ] Rejouer l'extraction OCR sur `test_floorplan3.png` avec la nouvelle configuration Tesseract (D-73)
- [ ] Vérifier que les 28 pièces sont correctement détectées (numéro + surface exacts)
- [ ] **Taille minimale ouvertures/portes** : filtrer les ouvertures et portes détectées automatiquement en dessous de 60 cm (seuil paramétrable). Exception : ouverture < 60 cm acceptée si elle est directement connectée à une autre ouverture (entrée commune pour 2 pièces contiguës).

#### Mode OCR — Cartouche 3 lignes (D-81)

Passer de 5 lignes à 3 lignes (code / surface / id). Format identique au Mode Préprocessé.

- [ ] Adapter le regroupement cartouche (5→3 lignes) + revalider sur test_floorplan3.png + mettre à jour les tests

#### Mode Préprocessé (D-74)

**Convention de nommage des fichiers** (à respecter à l'import et en interne) :

Un jeu Mode Préprocessé est composé de **deux PNG** + le JSON :

| Fichier | Rôle |
|---|---|
| `<plan_id>.png` | **Fichier d'affichage** — conserve les cartouches, labels, cotes, bref le plan tel que l'humain le lit. C'est celui montré par défaut en **overlay** dans Review/Match. Le nom de base (`<plan_id>`) sert d'identifiant de référence du floor plan (clé stable pour R-11, round trip). |
| `<plan_id>-SD.png` | **Fichier algorithmique** (Sans Description) — pas de cartouches, extérieur peint en bleu ciel `preprocessed_exterior_rgb`, couloirs en vert `preprocessed_corridor_rgb`. C'est celui consommé par l'extraction ray-cast / détection de pièces. |
| `<plan_id>.json` | JSON v3 (rooms dict indexé, `drawing_scale_text`, `drawing_scale_measured`, `orientation`, `olm_state`). |

Règle : l'utilisateur fournit `<plan_id>.png` à l'import, OLM résout automatiquement `<plan_id>-SD.png` et `<plan_id>.json` dans le même dossier. Erreur explicite si l'un des deux est absent. Jamais de fichier -SD affiché à l'utilisateur sauf mode debug.

Tâches :
- [x] **Overlay par niveau** : Floor affiche `<plan_id>.png` (standard), Room et Office affichent `<plan_id>-SD.png` (sans description)

---


**(C) Automatisation future (optionnelle)** — générateur CLI qui enchaîne A + B automatiquement :

- [ ] Script `olm/tools/make_preprocessed_test.py` prenant un PNG Mode OCR et produisant le triplet (`<plan_id>.png`, `<plan_id>-SD.png`, `<plan_id>.json`)
- [ ] Étapes B automatisées : effacement cartouches via `clean_text_from_image()`, flood fill extérieur bleu ciel depuis les bords, détection couloirs (stratégie à définir — flood fill manuel via clics ou auto par exclusion des zones blanches non-pièces)
- [ ] Validation end-to-end : charger le triplet produit → vérifier cohérence avec le résultat du Mode OCR sur le même plan

#### Exploitation avancée du PNG -SD et du JSON v3 (D-77)

- [ ] **Ray-casting traversant les portes** : masque de transparence sur les zones de porte (via `doors[]` du JSON) pour que le ray-cast atteigne le vrai mur derrière le trait de porte
- [ ] **Détection fenêtres Mode Préprocessé** : refondre la logique — le bleu extérieur change le raisonnement (mur bordant du bleu = façade → candidat fenêtre). Distinguer mur plein / fenêtre / baie vitrée sur segments façade.
- [ ] **Détection couloirs via le vert** : segment de mur bordant du vert RGB(193,247,179) = porte sur couloir, sans classification texture

---

#### Topologies de bâtiment — Mode Préprocessé

Le preprocessing et les règles de détection (fenêtres, corridor, extérieur)
doivent tenir compte de la variété des topologies réelles. À passer en revue
et documenter avant d'industrialiser le Mode Préprocessé.

- [ ] **Bâtiment classique (barre, plot, L)** : fenêtres vers l'extérieur
  périphérique (bleu ciel), corridor central (vert). Cas de référence.
- [ ] **Cours intérieures** : zones extérieures enclavées dans le bâtiment,
  non atteintes par le flood fill depuis les bords. Doivent être peintes en
  bleu comme l'extérieur périphérique pour que la détection fenêtres
  fonctionne côté cour.
- [ ] **Patios / atriums vitrés** : zones intérieures traversées par la
  lumière mais entourées de surfaces vitrées. Choix de coloration à
  arbitrer (bleu extérieur, vert corridor, ou statut dédié ?).
- [ ] **Mezzanines / demi-niveaux** : pièces sur plusieurs niveaux sur le
  même plan. Impact sur l'unicité du `plan_id` et les bbox si elles se
  chevauchent.
- [ ] **Bâtiments mitoyens / parties communes** : murs mitoyens à
  distinguer des murs pleins internes ; absence de façade sur certaines
  faces. Règle de détection fenêtre à adapter.
- [ ] **Parking / techniques / circulations non occupables** : exclure du
  matching. Marquage à définir (room_code dédié, filtre par surface, ou
  coloration spéciale).
- [ ] **… cas à collecter au fil des plans réels** — ouvrir la liste à
  mesure que des topologies nouvelles apparaissent.

Pour chaque topologie, documenter dans
`docs/specs/RASTER_EXTRACTION_SPEC.md` ou une spec dédiée : règle de
coloration attendue dans le PNG -SD, comportement du ray-cast, règle de
détection fenêtre / corridor.

#### Robustesse ingestion

- [ ] **Arcs de porte** : le preprocessing génère des artefacts aux arcs de porte → post-traitement par consensus médian sur les hits du ray-cast (filtrer les encoches causées par les arcs)
- [ ] **Cours intérieures** : détecter les zones extérieures enclavées dans le bâtiment (non atteintes par le flood fill depuis les bords) et les marquer comme extérieur pour la détection fenêtres

### R-11 : Full round trip — Persistance des amendements dans le JSON

Objectif : garantir qu'à un re-import d'un plan déjà travaillé, l'utilisateur retrouve **toutes les sélections et amendements** précédents sans recalcul automatique. L'outil devient stateful : chaque session enrichit le JSON qui sert ensuite de source de vérité.

**Identification du plan** : par nom du fichier PNG (pas de hash, pas de contenu). Deux imports successifs de `test_floorplan3.png` sont considérés comme le même plan.

**Persistance** : l'état (sélections de patterns, amendements layout, amendements géométrie, zones interdites ajoutées en Review, commentaires markdown) est **sauvegardé dans le fichier JSON** accompagnant le PNG (Mode Préprocessé) ou dans un JSON sidecar (Mode OCR). L'export = la sauvegarde. (Fusions de pièces retirées — voir D-100.)

**Structure de l'état dans le JSON** (extension non-breaking du format v2) :

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
      },
      "22K": { ... }
    }
  }
}
```

**Clé de pièce** : `id_line3.text` (ex: `"237"`, `"22K"`). Stable entre imports tant que le fichier de preprocessing reste cohérent.

**Politique de diff à la réouverture** :
- Pièces **présentes dans les deux** (JSON actuel et `olm_state`) → réhydrater sélection + amendements
- Pièces **nouvelles** (présentes dans le JSON, absentes de `olm_state`) → démarrer vierge, marquer visuellement (badge "Nouveau")
- Pièces **orphelines** (présentes dans `olm_state`, absentes du JSON actuel) → warning listant les pièces disparues, proposer nettoyage ou conservation (au cas où le plan a été régénéré avec une erreur)
- L'utilisateur peut toujours **réinitialiser** une pièce (reset state) pour revenir au candidat automatique

Tâches :

- [ ] Fonction `build_olm_state()` : à l'export, sérialiser l'état courant (sélections + amendements) dans la structure `olm_state`
- [ ] Modifier la route d'export pour produire un JSON enrichi avec `olm_state` à jour
- [ ] UI : badge "Nouveau" sur les pièces sans état + warning listant les orphelines
- [ ] Test end-to-end : import → sélection + amendement → export → re-import → vérifier réhydratation

### Commentaires markdown par pièce (remplace R-09 — voir D-100)

Pour couvrir le cas "étudier l'aménagement en supprimant des murs entre pièces", on utilise maintenant le workflow **resize + Add/Delete room** (D-99 + Add room existant) plutôt qu'un système de merge. Un champ commentaires libre permet à l'utilisateur de tracer son raisonnement.

- [ ] **Champ `comments_md`** dans chaque entrée `rooms.{id}` du JSON v3 préprocessé + UI dans Room (textarea markdown associé à la pièce courante, sauvegardé avec l'amendement).
- [ ] **Section "Commentaires"** dans le rapport final PDF/CSV : rendu markdown par pièce, inclus si non vide.
- [ ] **SRS** : documenter le workflow officiel "suppression de murs = resize + delete + commentaire" (D-100).

### Room → Floor propagation pour orientations non-south (D-99)

- [ ] Étendre la propagation `bbox_px` de `save()` (Room amend) aux rooms avec `corridor_face ∈ {north, east, west}`. Nécessite un axis-remapping (les dimensions locales après canonicalisation ne correspondent pas directement aux axes du plan).

### Save v3 export préserve les champs inconnus

- [ ] `devExportV3Json` reconstruit le JSON à partir de `ingState` mais **écrase** les champs non gérés par le frontend (notamment `orientation`). Correctif : conserver une référence au JSON d'origine (au moment de l'import) et merger les champs manquants à la sauvegarde.



### R-07 : Packaging et déploiement

- [ ] Packaging Windows sans admin : `requirements.txt`, `install.bat`, `launch.bat`, validation Anaconda, test cycle complet

---

## Priorité moyenne — Revue UX et refactoring restants

### Revue UX (restant)

- [ ] **Pipeline Préprocessé refondu (D-105)** — gros chantier :
  - [ ] `extract_rooms_from_preprocessed` : ray-cast depuis seed sur `-SD` binarisé au lieu de lire `bbox_px` du JSON.
  - [ ] Zone transparente auto-générée à chaque seed de porte (côté pièce, dos au couloir) appliquée avant binarisation → les rays traversent les portes. Largeur = `default_door_width_cm` (paramètre général, défaut 90 cm), profondeur = même valeur (arc de 90°). Cette zone absorbe **aussi** le trait d'arc qui bloquerait sinon les rayons.
  - [ ] `_classify_wall_direct` appliqué sur le bbox recalculé.
  - [ ] Fenêtres — algo combiné :
    - [ ] Détection par transitions de texture (primaire) pour identifier les fenêtres individuelles dans une façade (cas standard : plusieurs fenêtres séparées).
    - [ ] Fallback couleur : si la face borde du bleu extérieur (`exterior_rgb`) et qu'aucune fenêtre n'a été détectée par texture, poser **une fenêtre unique couvrant toute la face**.
  - [ ] Portes depuis seeds JSON, snap à la face la plus proche, largeur = `default_door_width_cm`. Pas de détection par arc.
  - [ ] **Nouveau paramètre global `default_door_width_cm`** dans Settings (onglet General), valeur par défaut 90 cm, utilisé aussi bien pour CRUD manuel (D-103) que pour la zone transparente auto-porte et la largeur auto des portes depuis seeds.
  - [ ] **Renommer `origin: "auto"|"manual"` en `modified: bool`** (cohérence avec "amended" existant). Propager : `state.room_windows[i].modified`, `state.room_openings[i].modified`, merge logic D-104, JSON v3 (quand persistance ajoutée).
  - [ ] `extract_room_features` (re-analyze D-104) : aligner sur ce pipeline (seed + door seeds en entrée).
  - [ ] Endpoints `/api/room/reanalyze` et `/api/room/reanalyze_batch` : accepter `seed_px` et `door_seeds_px` ; bbox devient optionnel.
  - [ ] Produire `hits` (ray-cast) pour V/H-rays en Préprocessé (résolu par la refonte ci-dessus).
  - [ ] Mettre à jour `docs/specs/PREPROCESSED_JSON_SPEC.md` : clarifier quels champs sont entrée fiable vs dérivés.
- [ ] **Ray-cast via `-SD.png` (Mode OCR + Mode Préprocessé)** : (fusion de
  deux entrées doublon)
  - Mode **Préprocessé** : `extract_rooms_from_preprocessed` ne génère
    pas de `room.hits` actuellement. Faire un ray-cast léger sur le PNG
    `-SD` pour peupler les hits et rendre les cases V-rays / H-rays de
    Floor fonctionnelles.
  - Mode **OCR** : si `<plan_id>-SD.png` existe dans `project/plans/`,
    l'utiliser comme source pour l'algo de détection / ray-cast au lieu
    de supprimer les cartouches manuellement — rendu plus propre.
- [ ] **Nettoyer handlers de couplage de pièces (Floorplan)** : D-100 a supprimé le concept de merge mais il reste des handlers dans le code Floor (couplage/association de pièces). Les retirer.
- [ ] **Fine-tuning taille éléments graphiques** : ajuster les épaisseurs de traits (murs, fenêtres, portes, arcs), diamètre des ronds de grille, taille des poignées/badges pour un rendu visuellement agréable à tous les niveaux de zoom. Actuellement : non-scaling-stroke appliqué partout + cap sur les dots grille à 2 px.
- [x] ~~**Total area en m² non rafraîchi au changement d'échelle**~~ ✅
  2026-04-21. Extraction de `updateFloorProperties()` dans
  `floor_plan.js` (exposé sur `window`), appelé directement depuis
  `_applyDrawingScale` (ingestion.js) et en tête de `rvRenderCurrent`
  (hors du early-return `if (!room)`). Investigation :
  [`docs/INVESTIGATION_total_area_refresh.md`](INVESTIGATION_total_area_refresh.md).
- [ ] **Édition contours au niveau Room** : ajouter la capacité de modifier les contours de la pièce dans Room (même outil que l'édition bbox dans Floor)

- [ ] **Bug position pièce 305 dans Office** : la pièce 305 est positionnée en (0,0) dans Office alors qu'elle est correctement placée dans Floor et Room. Semble arriver lorsqu'il y a un match automatique.
- [ ] **Bug orientation pièce 922** (à re-tester après R-14). Entrée datée
  2026-04-17, antérieure au refactor R-14 (D-121 → D-134). Chaîne actuelle
  mathématiquement correcte :
  `canonical_top_face="west"` → backend `corridor_face="east"` (OPPOSITE) →
  frontend `corridor_face_abs="east"` → `canonicalIO.canonAngle("east") = 90°`
  → west image rendu en haut (north) ✓. Probablement résolu en passant. À
  re-vérifier visuellement sur la pièce 922 ; si le bug persiste, il est
  ailleurs dans le rendu (overlay pxPerCm ? bbox non rotaté ?).
- [ ] Bug : Design Layout ne rote pas correctement les patterns selon l'orientation de la porte. Si la porte est en haut, les patterns devraient être rotatés mais ils conservent leur orientation par défaut (bureau sur la porte). À auditer dans le pipeline matching + rendu (fpCanvas).
- [ ] **Rendu homogène Import/Review/Design** : utiliser le même rendu détaillé (arcs de porte, fenêtres épaisses, ouvertures) dans Import que dans Review/Design. Niveau de détail adaptatif selon le zoom : détails complets quand on zoome sur une pièce, traits simplifiés quand on voit tout le plan. Adapter l'épaisseur des traits au niveau de zoom pour rester lisible à toutes les échelles.
- [ ] **Ajout manuel d'un seed** dans Floor/Room : besoin pour les pièces ajoutées à la main (nouveau contour sans cartouche OCR détecté) — permettre de placer le seed avec un clic pour que la re-analyze puisse partir.
- [x] ~~**Afficher le seed (disque vert) dès l'activation V-Rays ou H-Rays**~~ ✅
  2026-04-21. Le push du cercle seed est sorti du bloc `if (room_hits)` et
  conditionné uniquement à `state.room_seed_cm && (showVrays || showHrays)`
  ([editor.js:238-246](olm/static/editor.js#L238-L246)).

### Refactoring architecture frontend — poursuite éventuelle

- [x] **State unique** (D-94 P1) : store `olmStore` unifié.
- [x] **Découpage JS** (D-94 P2/P3/P4) : `render_shared.js`, `init_rvtool.js`, `init_resize.js`, `ingestion_scale.js`, `ingestion_export.js`.
- [ ] Éventuellement : extraction supplémentaire de `renderIngestion` (330 l.) depuis `ingestion.js` — demande exposition étendue de helpers locaux, ROI plus faible qu'aux phases précédentes.
- [ ] Fonctions de rendu pures (sans dépendance au state global) — chantier long, à évaluer selon les besoins futurs.

---

## Étapes existantes non impactées

### Peuplement du catalogue (priorité haute)

- [ ] **Minimize room size** : calcul de la pièce minimale par pattern par standard, Ctrl+M unitaire + batch "minimize all", feedback visuel
- [ ] **Recalibration patterns SITE** (D-56) : recalculer les tailles minimales avec les nouvelles distances, vérifier/recréer les patterns SITE

---

## Après le prototype — Industrialisation

- [ ] **Nettoyage** : supprimer les anciens modèles et code abandonné (solver/model.py, debt_model.py, matcher.py, static_matcher.py)
- [ ] **Documentation** : réécriture SRS/SDS alignée OLM, SPEC_matcher.md

---

## Phases conditionnelles (R&D dans solver_lab/)

- [ ] **Phase 2** : CP-SAT résiduel sur zones libres après matching statique
- [ ] **Phase 3** : géométrie stochastique (MCMC warm-started depuis catalogue)

---

## Priorités proposées (triage 2026-04-21)

Consolidation post-D-135. Liste non exhaustive, à arbitrer par l'utilisateur.

### Court terme (bugs bloquants UX / régressions potentielles)

0. ~~**Double-clic Floor → Room**~~ : corrigé session 2026-05-11.
1. ~~**Persistance bbox resize**~~ : corrigé session 2026-05-11 (sync fpRoomAmendments).
2. **Bug "No matching patterns"** (R-04 Office) : aucun candidat trouvé. Investigation prioritaire.
3. **Bug bouton Save (clic physique)** (dette R-12) : à revérifier.

### Court terme (dette technique à faible risque)

4. **Rationalisation des constantes-rustines** (rapport
   [`docs/audit_constants_rustines.md`](audit_constants_rustines.md)) :
   audit complet de ~30 valeurs numériques en dur (9 critiques, 14 modérées).
   Priorité : **mode preprocessed** (le mode OCR dépend de constantes
   additionnelles qui seront traitées dans un second temps).
   - [x] **Triple binarize_threshold** : ~~unifier les 3 sources (comb_detection L52,
     extract.py L204, extract.py L1834) sur `detection_config.binarize_threshold`.~~
     → D-187 : defaut 140 → 110 aligne config.json. Source unique resolue.
   - [x] **Défauts px module comb_detection** (L52-59) : ~~remplacer les `XX_PX = N`
     par des valeurs dérivées de `DEFAULT_DETECTION_CONFIG_CM.to_px(scale)`
     ou faire échouer si `_apply_detection_config` n'a pas été appelée.~~
     → P0.3 livré : 14 constantes → None + `_ensure_config_applied()` guard.
   - [ ] **Défauts px dans extract.py** : convertir en cm les signatures
     (`margin_px=8`, `tolerance=40`, `max_depth=30`, `min_component_px=5`,
     `max_absorb_px=120`, `max_dist=500`).
   - [ ] **Multiplicateurs `step_px`** : `gap_threshold = 3 * step_px` et
     `min_count = 3` → exprimer en cm via `detection_config`
     (`pillar_group_gap_cm`, `min_pillar_hits` dérivé).
   - [ ] **Seuils ratio sans nom** : `ARC_MONOTONICITY_RATIO = 0.7`,
     bornes OCR `(0.5, 2000.0)`, angle filtre `5°` dupliqué → nommer et
     centraliser dans `detection_config`.
   - [ ] **Grades circulation A-F** : extraire le tableau
     `(palier, connectivité_pct, worst_detour)` dans `matching_config`.
   - [ ] **Calibration scale** : exposer `MIN_CALIB_SURFACE_M2` dans
     `project/config.json`.
   - [x] Assertion défensive : `_ensure_config_applied()` dans `comb_detection.py` (ex-`test_comb.py`, renommé D-189).
5. **Audit ingestion.js — actions faciles** (rapport
   [`docs/AUDIT_ingestion_2026-04-21.md`](AUDIT_ingestion_2026-04-21.md)) :
   - Bloc CONSTANTS en tête de fichier (magic numbers identifiés :
     zooms, double-click delay, padding, seuils px…).
   - Supprimer `_rotR` non utilisé (L-80).
   - Fusion `extractRooms` / `extractRoomsPreprocessed` via un helper
     `_setupPostExtractionUI(planId)` (~50 lignes dédupliquées).
   - Renommage variables ambiguës (`am` → `amendments`, `_sig` →
     `_createOpeningSignature`, etc.).
6. [x] ~~**Fonction `_syncRoomToAllStores(name, updates)`**~~ ✅ 2026-04-21.
   Nouveau module [`olm/static/room_sync_helpers.js`](../olm/static/room_sync_helpers.js)
   expose `syncRoomToAllStores(name, updates, fallbackCanonRoom)` +
   `splitOpeningsToFrontEnd(combined)`. Migré partout :
   - `ingestion.js` handler batch Rescan all (~80 l. de triple mutation
     → 30 l. déclaratives + 1 appel).
   - `editor.js save()` Room amend (intègre fix D-127 + D-135 rider
     par construction, `editor.js` passe de 2323 → 2280 l.).
   - `floor_plan.js` : `fpRematchRoom()` + `fpLoadAndMatch()` split
     via `splitOpeningsToFrontEnd` (source unique).

### Moyen terme (features)

7. **R-11 Full round trip — `olm_state`** : chantier stratégique pour
   la persistance des amendements entre sessions. Prérequis à toute
   montée en charge utilisateur.
8. **Commentaires markdown par pièce** (R-09 obsolète → D-100) : petit
   chantier, utile, encore non attaqué.
9. **Export PDF** (R-04 Export) : fond de plan raster + overlay
   aménagement. Demande utilisateur récurrente.

### Long terme (refondations)

10. **Pipeline Préprocessé refondu (D-105)** : gros chantier incluant
    ray-cast depuis seed + détection fenêtres combinée texture/couleur.
    Sous-items encore tous à faire.
11. **R-07 Packaging Windows sans admin** : préalable au déploiement
    sur le poste cible.

---
