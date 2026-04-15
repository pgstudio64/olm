# TODO — OLM (Office Layout Matching)

Dernière mise à jour : 2026-04-05

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

### R-01 : Renommage OLO → OLM + séparation open source / spécifique (D-67, D-68)

- [x] Créer la structure `olm/` (open source) + `project/` (spécifique)
- [x] Migrer le code vers `olm/` (core/, server/, static/, templates/)
- [x] Migrer les données spécifiques (catalogue, plans, config) vers `project/`
- [x] Migrer la documentation interne vers `docs/`
- [x] Ajouter `LICENSE` (MIT)
- [x] Ajouter `README.md`, `pyproject.toml`
- [x] Ajouter `.gitignore` pour exclure `project/` de la publication

### R-03 : Score composite densité / confort paramétrable

- [x] Remplacer la sélection lexicographique par un score pondéré : `w_density × density + w_comfort × comfort`
- [x] Ajouter les poids dans Settings > Matching
- [x] Champs numériques dans l'interface (`cfgWDensity`, `cfgWComfort`)
- [x] Recalcul en temps réel au changement de poids

### R-04 : Floor Plan — 4 sous-onglets (Import / Review / Match / Export)

#### Import

Objectif : ingestion simplifiée — rectangles + murs + fenêtres + ouvertures. Pas de zones interdites (ajoutées en Review).

- [x] Upload image (PNG/JPEG) ou PDF (rasterisé via pymupdf)
- [x] Bouton **Load** → lance l'extraction (OCR ou Préprocessé selon `ingestion_mode`) → affiche les pièces détectées → permet correction noms/dimensions
- [x] Import JSON manuel (textarea ou upload fichier) — conservé de l'existant
- [ ] **Bug overlay (post-simplification Import)** : `/api/import/ocr` renvoie `image_path=""` et unlink le temp file, l'overlay n'est plus affiché. Fix : persister le PNG uploadé (ou rasterisé depuis PDF) dans un dossier servi, renvoyer un chemin exploitable par le frontend.
- [ ] **Régénérer `project/plans/test_floorplan3.png`** à l'échelle cible `ingestion.scale_cm_per_px=0.5` (actuellement les surfaces totales tombent à ~10 m² → le fichier est resté sur une ancienne échelle). Valider que les cartouches 3 lignes (D-81) sont conformes.
- [ ] **Restructuration 4 sous-onglets Floor Plan** : renommer top-level `tabImport` en "Floor Plan", créer une nav de sous-onglets (Import / Review / Match / Export), déplacer le contenu actuel de `tabDesign` dans Match, et celui de `tabExport` dans Export. Les top-level Design et Export disparaissent. Catalogue reste top-level séparé. Adapter `init.js` et tous les sélecteurs `.click()` programmatiques.
- [ ] **Liste des pièces (Review) redimensionnable** : ajouter une poignée de resize horizontale sur le panneau latéral de la liste des pièces ; largeur par défaut = 70 % de la largeur actuelle (soit −30 %), min/max raisonnables, persistance localStorage.

Abandonné (inutile) : saisie manuelle d'échelle (cm/px ou points de calage) et saisie de code pièce à l'import — l'échelle vient de `plan_scale` du JSON v2 en Préprocessé ou des métadonnées OCR, le code pièce vient de Settings.

#### Review

Objectif : amender les pièces importées avant matching. Remplace l'ancien "Adjust room" (D-63).

- [x] Liste des pièces avec navigation previous/next
- [x] Rendu SVG de la pièce (rvCanvas séparé)
- [x] Édition dimensions via DSL pièce
- [x] Propriétés pièce (width, depth, area) + propriétés étage (total rooms, area)
- [ ] CRUD ouvertures : ajout, suppression, déplacement, type (porte/baie)
- [ ] **Outil zone interdite** (souris) : mode "Add forbidden zone" (select function dans la toolbar), dessin par clic + drag → rectangle aligné sur la grille. Cliquer ailleurs désactive le mode.
- [ ] Sélection d'une zone interdite existante → poignée de déplacement, touche Delete pour supprimer
- [ ] **Pas de redimensionnement souris** : pour modifier la taille d'une zone interdite, passer par le DSL pièce (ligne `EXCLUSION x y w h` éditable). La souris ne fait que positionner, déplacer, supprimer — cohérent avec la logique "édition visuelle simple, géométrie précise via DSL".
- [x] Sauvegarde des amendements (bouton Save)

#### Match

Deux actions distinctes sur un candidat :
- **Edit pattern** : le modèle n'est pas bon → bascule vers l'éditeur pour modifier le pattern (comportement actuel)
- **Amend layout** : le pattern est bon mais la solution pour cette pièce nécessite des ajustements (poteau, obstacle…) → édition en place dans Match sans quitter le contexte

- [ ] **Amend layout en place dans Match** : rester dans le fpCanvas, sélection de blocs/postes, suppression (Delete), sauvegarde de l'amendement, puis continuer avec les autres pièces — pas de bascule vers l'éditeur
- [x] Navigation pièces, filtre standard, rendu SVG (fpCanvas), liste candidats, score composite
- [ ] Affichage du poids densité/confort utilisé

#### Export

- [x] Export JSON : résultat complet du matching (pièces, candidats retenus, métriques)
- [ ] Export CSV : tableau tabulaire importable dans Excel
- [ ] Export PDF : fond de plan raster + overlay aménagement
- [ ] Traçabilité des amendements : log des pièces modifiées manuellement

### R-05 : Module d'ingestion — Dual-mode (OCR + Préprocessé)

#### Mode OCR — Validation Tesseract sur test_floorplan3 (D-73)

- [ ] Rejouer l'extraction OCR sur `test_floorplan3.png` avec la nouvelle configuration Tesseract (whitelist typée, désactivation des dictionnaires `load_system_dawg=0` / `load_freq_dawg=0`, upscale x2 LANCZOS) décrite dans D-73
- [ ] Vérifier que les 28 pièces sont correctement détectées (numéro + surface exacts)
- [ ] Comparer avec le résultat pré-D-73 (régression éventuelle sur les codes courts type `"2"` vs `"m2"`)
- [ ] Documenter les écarts dans `specs/RASTER_EXTRACTION_SPEC.md` si besoin
- [ ] Si régression : ajuster les regex `_RE_ROOM_CODE` / `_RE_ROOM_NUMBER` / `_RE_SURFACE` ou la whitelist

#### Mode OCR — Cartouche 3 lignes (D-81)

Passer le format de cartouche du Mode OCR de **5 lignes** (code / N REEL / N THEO / surface / id) à **3 lignes** (code / surface / id). Les lignes N REEL et N THEO ne sont pas exploitées par OLS et créent de l'ambiguïté pour l'OCR (confusion avec les numéros de pièce courts).

Nouveau format (voir `specs/INGESTION_HYPOTHESES.md` §H-09 mis à jour) :

```
Ligne 1 : "14"        ← code pièce (paramétrable via room_code)
Ligne 2 : "14.28 m2"  ← surface avec suffixe " m2" explicite
Ligne 3 : "237"       ← identifiant de pièce (chiffres + suffixe alpha optionnel)
```

Ce format est **identique** au format du Mode Préprocessé (`code_line1` / `surface_line2` / `id_line3`, cf. `PREPROCESSED_JSON_SPEC.md` §3) — les deux modes partagent désormais la même sémantique de cartouche, ce qui simplifie le parsing et permet un code d'extraction commun.

Tâches :

- [ ] Adapter l'algorithme de regroupement en cartouche dans `olm/ingestion/extract.py` (et/ou `test_comb.py`) : ne plus rechercher 5 textes empilés mais 3, et ignorer tout texte intermédiaire restant à l'ancien format
- [ ] S'assurer que la whitelist Tesseract et les regex `_RE_ROOM_CODE` / `_RE_SURFACE` / `_RE_ROOM_NUMBER` (D-73) sont alignées : la whitelist contient les caractères nécessaires aux 3 lignes uniquement, les regex filtrent les tokens valides
- [ ] Vérifier la tolérance aux plans contenant encore l'ancien format 5 lignes : loguer un warning "anciennes lignes REEL/THEO détectées et ignorées" pour traçabilité
- [ ] Revalider sur `test_floorplan3.png` (couplé à la validation D-73 ci-dessus) — les 28 pièces doivent toujours être détectées avec le nouveau format
- [ ] Mettre à jour les tests OCR dans `olm/tests/` pour le format 3 lignes
- [ ] Aucune migration données nécessaire : le changement est en lecture (parsing), pas en écriture

#### Mode Préprocessé (D-74)

**Convention de nommage des fichiers** (à respecter à l'import et en interne) :

Un jeu Mode Préprocessé est composé de **deux PNG** + le JSON v2 :

| Fichier | Rôle |
|---|---|
| `<plan_id>.png` | **Fichier d'affichage** — conserve les cartouches, labels, cotes, bref le plan tel que l'humain le lit. C'est celui montré par défaut en **overlay** dans Review/Match. Le nom de base (`<plan_id>`) sert d'identifiant de référence du floor plan (clé stable pour R-11, round trip). |
| `<plan_id>_enhanced.png` | **Fichier algorithmique** — pas de cartouches, extérieur peint en bleu ciel `preprocessed_exterior_rgb`, couloirs en vert `preprocessed_corridor_rgb`. C'est celui consommé par l'extraction ray-cast / détection de pièces. |
| `<plan_id>.json` | JSON v2 (rooms, doors, all_text_blocks, métadonnées ROOT, `olm_state`). |

Règle : l'utilisateur fournit `<plan_id>.png` à l'import, OLM résout automatiquement `<plan_id>_enhanced.png` et `<plan_id>.json` dans le même dossier. Erreur explicite si l'un des deux est absent. Jamais de fichier enhanced affiché à l'utilisateur sauf mode debug.

Tâches :
- [ ] Adopter la convention `<plan_id>.png` / `<plan_id>_enhanced.png` dans le loader Mode Préprocessé (`extract_rooms_from_preprocessed()`)
- [ ] Route `/api/import/preprocessed` : prendre `<plan_id>.png` comme entrée principale, résoudre les deux autres par convention de nommage
- [ ] UI Review/Match : afficher `<plan_id>.png` comme overlay par défaut (pas l'enhanced)
- [ ] Mode debug (Settings > Ingestion ou query param) : bascule d'affichage vers `_enhanced.png` pour diagnostic visuel
- [ ] Générateur de plan de test (ci-dessous) : produire les deux PNG avec cette convention de nommage
- [ ] Documenter la convention dans `specs/PREPROCESSED_JSON_SPEC.md`

---

Implémentation du système dual-mode ingestion. ✅ Complété 2026-04-12

- [x] Créer enum `IngestionMode` dans `olm/core/types.py` (OCR | Preprocessed)
- [x] Fonction `extract_rooms_from_preprocessed()` dans `olm/ingestion/extract.py` : parser JSON pièces + charger PNG overlay/enhanced
- [x] Valider le JSON d'entrée (structure, champs obligatoires : room_id, area, seed position)
- [x] Routes API : POST `/api/import/ocr` (image + scale) et POST `/api/import/preprocessed` (JSON + overlays)
- [x] Frontend : dropdown "Input Mode" dans Settings > Ingestion
- [x] Deux panels upload distinct pour Mode OCR et Mode Préprocessé
- [x] Refresh UI au changement de mode

**Notes v1** :
- Mode préprocessé v1 : bbox dégénérée (seed = NW, pas de scale disponible) — amélioration v2 nécessaire
- Validation JSON complète : clé "rooms" + champs obligatoires par pièce + existence des PNG
- Tests de validation passent (3 cas d'erreur + 2 pièces nominal)

#### Générateur de plan de test pour Mode Préprocessé

**Stratégie révisée (2026-04-14)** : découper en deux morceaux indépendants pour débloquer le pipeline sans attendre le générateur complet.

**(A) Bouton DEV "Export v3 JSON"** — implémenté côté frontend (onglet Load, contour orange vif). Sérialise l'état courant de l'OCR Mode (`ingState.rooms` y compris éditions manuelles bbox / add / delete) dans un JSON v3 conforme à `PREPROCESSED_JSON_SPEC.md`. Téléchargement direct navigateur sous `<plan_stem>.json`. Permet de produire instantanément le JSON d'un plan sans dépendance externe. Voir §5 de `PREPROCESSED_JSON_SPEC.md`.

- [x] Bouton dev frontend exposé (Load panel)
- [x] Sérialisation v3 (code/surface/id/seed_px + bbox_px + doors/openings/windows imbriqués)
- [x] Téléchargement comme Blob navigateur

**(B) PNG `_enhanced` — création manuelle** pour l'instant :

- [ ] Produire `<plan_id>_enhanced.png` manuellement dans un éditeur d'image (Photoshop, GIMP, Affinity) à partir du PNG overlay :
  - Effacer les cartouches (tampon ou fill blanc)
  - Flood fill extérieur en bleu ciel RGB(135,206,235)
  - Flood fill couloirs en vert RGB(193,247,179)
  - Sauvegarder en PNG sans transparence à côté du PNG overlay
- [ ] Une fois disponible, valider le chargement en Mode Préprocessé via la route `/api/import/preprocessed`

**(C) Automatisation future (optionnelle)** — générateur CLI qui enchaîne A + B automatiquement :

- [ ] Script `olm/tools/make_preprocessed_test.py` prenant un PNG Mode OCR et produisant le triplet (`<plan_id>.png`, `<plan_id>_enhanced.png`, `<plan_id>.json`)
- [ ] Étapes B automatisées : effacement cartouches via `clean_text_from_image()`, flood fill extérieur bleu ciel depuis les bords, détection couloirs (stratégie à définir — flood fill manuel via clics ou auto par exclusion des zones blanches non-pièces)
- [ ] Validation end-to-end : charger le triplet produit → vérifier cohérence avec le résultat du Mode OCR sur le même plan

#### Exploitation avancée du PNG enhanced et du JSON v2 (D-77)

En Mode Préprocessé, les couleurs du PNG enhanced et les métadonnées du JSON permettent de simplifier considérablement le pipeline ray-cast.

**Ray-casting traversant les portes via `doors[]`** :

Problème : dans le pipeline ray-cast actuel, un ray qui rencontre un trait de porte s'arrête sur ce trait au lieu d'atteindre le vrai mur derrière.

Solution : pour chaque porte du JSON v2 (`doors[]`), définir une zone de transparence autour du label porte (`pixels_x/y`, `width_px/height_px` + marge). Les pixels dans cette zone sont ignorés par le ray-cast → le ray traverse la porte et s'arrête correctement :
- sur la frontière blanc-vert si la porte donne sur un couloir
- sur le mur de la pièce voisine si la porte est mitoyenne

Tâches :
- [ ] Indexer les portes par `associated_room` à l'import
- [ ] Construire un masque de transparence (zone de porte) par pièce
- [ ] Modifier le ray-cast (phase 2) pour ignorer les pixels à l'intérieur du masque porte
- [ ] Tester sur un plan avec portes multiples (pièce + couloir + pièce mitoyenne)
- [ ] Valider que la détection d'ouverture n'est plus perturbée par le trait de porte

**Paramétrage des couleurs sémantiques (Settings > Ingestion)** :

Les codes RGB de l'extérieur bleu ciel et du couloir vert doivent être exposés comme paramètres éditables dans Settings > Ingestion (section Mode Préprocessé), avec les valeurs par défaut :
- `preprocessed_exterior_rgb` : `[135, 206, 235]`
- `preprocessed_corridor_rgb` : `[193, 247, 179]`

Motivation : l'outil de preprocessing externe peut évoluer ou plusieurs prestataires peuvent adopter des conventions différentes. Ne pas figer ces constantes dans le code.

Tâches :
- [ ] Ajouter les champs `preprocessed_exterior_rgb` et `preprocessed_corridor_rgb` dans `project/config.json`
- [ ] Exposer dans la section Settings > Ingestion (inputs RGB triples ou color picker)
- [ ] Faire consommer ces valeurs par le pipeline d'extraction préprocessé (masques et règles d'arrêt ray-cast)
- [ ] Persistance cohérente avec les autres paramètres Settings

**Détection fenêtres en Mode Préprocessé — revoir la logique entière** :

La logique actuelle du Mode OCR (flood fill depuis les bords + analyse de texture transversale sur murs périphériques — `RASTER_EXTRACTION_SPEC.md` §6.6) n'est plus adaptée au Mode Préprocessé. L'extérieur coloré en bleu ciel change radicalement le raisonnement : la fenêtre n'est plus distinguée par sa texture mais par **la nature de ce qu'elle borde** (bleu → façade → candidat fenêtre).

Questions à trancher avant implémentation :
- Une fenêtre est-elle toujours reconnaissable par sa texture (traits parallèles) ou le preprocessing peut-il l'avoir altérée ?
- Comment distinguer un mur plein donnant sur façade d'une fenêtre si les deux bordent du bleu ? Conserver l'analyse de texture uniquement sur les segments façade, ou trouver un signal plus fiable (largeur d'ouverture, tracé discontinu) ?
- Les portes-fenêtres donnant sur l'extérieur sont-elles dans `doors[]` ou traitées comme fenêtres ? Règle à définir.
- Les cours intérieures : doivent-elles être distinguées de l'extérieur principal pour l'éclairage naturel, ou traitées identiquement ?
- Pour le matching : tous les murs donnant sur du bleu génèrent-ils des contraintes "façade" (poste orienté, distance au mur) indépendamment de la présence d'une fenêtre ?

Tâches :
- [ ] Atelier de conception : redéfinir le modèle « fenêtre » en Mode Préprocessé (entrées, signaux, sortie)
- [ ] Documenter la nouvelle logique dans `RASTER_EXTRACTION_SPEC.md` (section dédiée Mode Préprocessé)
- [ ] Implémenter la détection : ray-cast context-aware + règle d'arrêt sur bleu + classification du segment bordant
- [ ] Valider sur plan avec cours intérieure (fenêtres donnant sur la cour doivent être détectées)
- [ ] Valider sur plan avec porte-fenêtre / baie vitrée
- [ ] Comparer avec le résultat du Mode OCR sur le même plan pour non-régression

**Analyse couloirs via le vert** :

Tâches :
- [ ] Détecter la couleur verte RGB(193,247,179) sur les segments de mur → identifie immédiatement les portes sur couloir
- [ ] Plus de classification texture nécessaire pour ces segments

**Exploitation `all_text_blocks[]` (v2 bonus)** :

- [ ] Extraire les cotes (texte numérique proche d'un trait de cote) pour calibration indépendante du plan_scale
- [ ] Détecter labels de zones spéciales (sanitaires, locaux techniques, escaliers) pour filtrage auto

---

#### Analyse : Artefacts arc de porte dans PNG enhanced (D-75)

Le preprocessing supprime les cartouches mais génère des artefacts aux arcs de porte (traits partiellement effacés).

Tâches :
- [ ] Examiner le processus de preprocessing externe : à quel stade les arcs disparaissent-ils ?
- [ ] Proposer une stratégie de récupération : post-traitement Hough circles, filtre morpho, wall-tracing amélioré ?
- [ ] Tester la robustesse du wall-tracing actuel (D-76) face aux arcs incomplets
- [ ] Documenter les limites acceptables dans `specs/RASTER_EXTRACTION_SPEC.md`

#### Zones interdites — promotion automatique des petits artefacts (D-80)

Les plans réels comportent fréquemment des obstacles internes qu'il ne faut ni confondre avec les murs (ils briseraient la détection du rectangle) ni ignorer en aménagement (un poste ne peut pas être placé dessus). Cas d'école : **les poteaux au milieu d'un grand open space**.

Le concept unifie deux mécanismes — un automatique et un manuel — qui aboutissent à la même structure de données (`EXCLUSION x y w h`) et au même traitement aval.

**Promotion automatique en zone interdite** (pendant l'ingestion)

Un nouveau paramètre `min_size_artifact_cm2` (section Settings > Ingestion) définit la taille minimale d'un obstacle "significatif". Tout artefact détecté à l'intérieur d'une pièce dont la surface est **inférieure** à ce seuil est :
- **Pas considéré comme un mur** lors de la phase ray-cast — les rays l'ignorent (ils "traversent")
- **Automatiquement inséré comme zone interdite** (`EXCL`) dans la pièce extraite

Effet dans la phase "rectangle inscrit" (`RASTER_EXTRACTION_SPEC.md` §7.1) : le détecteur peut maintenant englober un grand rectangle traversant un poteau — le rectangle est correct, et le poteau devient une exclusion locale plutôt qu'une entaille dans la bbox.

Effet dans la phase de matching : les exclusions issues de petits artefacts sont prises en compte par `effective_dimensions()` (D-62 existe déjà) et par le scoring de couverture. Le matching **ne part pas de zéro** pour ces pièces : il propose le meilleur pattern open space global, en ignorant localement les postes qui collideraient avec les poteaux. L'utilisateur lève les conflits résiduels via Amend layout (Match en place).

**Amendement manuel** (en Review)

L'utilisateur peut à tout moment ajouter des zones interdites non détectées via l'outil souris de la section Review (cf. R-04 > Review ci-dessus). Utilisé pour :
- Les obstacles que l'ingestion n'a pas repérés (mobilier fixe, gaines, escaliers)
- L'ajustement visuel d'une exclusion auto mal positionnée (supprimer → redessiner)

**Paramètres à introduire dans Settings > Ingestion** :

| Paramètre | Défaut | Rôle |
|---|---|---|
| `min_size_artifact_cm2` | `2500` (50×50 cm) | Seuil de promotion auto en zone interdite. En dessous → `EXCL`. Au-dessus → mur ou obstacle majeur détecté normalement. |
| `artifact_promotion_enabled` | `true` | Active/désactive la promotion auto (fallback en cas de sur-détection) |

Tâches :

- [ ] Ajouter `min_size_artifact_cm2` et `artifact_promotion_enabled` dans `project/config.json` + Settings > Ingestion
- [ ] Modifier la phase de détection des artefacts post ray-cast (section « Détection des zones interdites » ci-dessous) pour appliquer le seuil :
  - Taille < seuil → émettre une `EXCL` au lieu d'un obstacle bloquant les rays
  - Taille ≥ seuil → traitement actuel (obstacle significatif, potentiellement un mur interne)
- [ ] S'assurer que la phase rectangle inscrit traite les pixels promus en `EXCL` comme "intérieur libre" (les rays passent à travers)
- [ ] Vérifier que `effective_dimensions()` (D-62) et le scoring de couverture gèrent correctement les `EXCL` issues de promotion auto
- [ ] UX Match : badge visuel sur les pièces contenant des `EXCL` promues (signalement "poteau détecté, vérifier manuellement")
- [ ] Test sur open space avec poteaux : matching doit proposer un pattern + l'amendement manuel doit permettre de déplacer/supprimer les postes en conflit
- [ ] Documenter dans `RASTER_EXTRACTION_SPEC.md` §7.1 et §7.3 l'effet de la promotion sur la détection du rectangle utile
- [ ] Documenter dans `PATTERN_DSL_SPEC.md` / `ROOM_DSL_SPEC.md` que `EXCLUSION` peut être d'origine auto ou manuelle (marqueur optionnel `EXCLUSION ... auto`)

#### Détection des zones interdites (post ray-cast)

Approche en 3 phases, exécutée **après** la détection des contours de la pièce (phases 1-3 du ray-cast) :

Phase A — Extraction + binarisation de l'intérieur de la pièce :
- Cropper l'image au rectangle englobant détecté
- Binariser (seuil Otsu) → matrice binaire (1 = encre, 0 = vide)
- Effacer les murs extérieurs (déjà connus) pour ne garder que l'encre intérieure

Phase B — Discrétisation en grille de cellules :
- Grille de cellules carrées de 5 cm (`CELL_SIZE_CM = 5`)
- Taux de remplissage par cellule → marquer OCCUPIED si > `FILL_THRESHOLD` (10%)
- Résultat : matrice binaire de cellules

Phase C — Couverture rectangulaire gloutonne :
- Boucle : trouver le plus grand rectangle de cellules OCCUPIED (algo histogramme O(n×m))
- Accepter si taux de remplissage du rectangle > `MERGE_THRESHOLD` (30%) — permet de capturer les cagibis morcelés (murs + porte + hachures)
- Ignorer les rectangles < `MIN_AREA_CELLS` (4 cellules = 10×10 cm)
- Marquer les cellules couvertes, itérer

Paramètres : `CELL_SIZE_CM=5`, `FILL_THRESHOLD=0.10`, `MERGE_THRESHOLD=0.30`, `MIN_AREA_CELLS=4`, `MAX_ITERATIONS=50`

Tâches :
- [ ] Implémenter phase A (crop + binarisation + effacement murs)
- [ ] Implémenter phase B (grille de cellules + taux de remplissage)
- [ ] Implémenter phase C (couverture rectangulaire gloutonne, algo histogramme)
- [ ] Intégrer dans le pipeline extract.py (après detect_room_three_phase)
- [ ] Visualiser les zones détectées dans le viewer
- [ ] Tester sur le plan synthétique (poteaux, débarras, L-shapes)

#### Robustesse aux arcs de porte (post-traitement ray-cast)

Problème : les arcs de porte (quarts de cercle, rayon 70-93 cm) interceptent les rays avant le vrai mur → encoches dans la bbox détectée. Un arc n'affecte qu'un petit groupe de rays (5-20°) tandis qu'un mur est touché de manière continue.

Approche retenue : **post-traitement par consensus médian** (pas de modification du ray-cast) :

1. Collecter **tous les hits** le long de chaque ray (pas seulement le premier) → `hits[i] = [d1, d2, ..., dk]`
2. Retenir `d_max[i]` (distance max = mur le plus lointain)
3. Pour chaque ray, comparer `d_max[i]` à la médiane des `d_max` des voisins (fenêtre ±5 rays)
4. Si cohérent (écart < 15 cm) → garder. Sinon → chercher dans `hits[i]` la distance la plus proche de la médiane. Si aucun hit → interpoler.

Paramètres : `NEIGHBOR_WINDOW=5`, `WALL_TOLERANCE_CM=15`

Alternative (si insuffisant) : pré-traitement par `cv2.HoughCircles` pour effacer les arcs avant le scan. Plus complexe, à implémenter seulement si le post-traitement ne suffit pas.

Tâches :
- [ ] Modifier le ray-cast phase 2 pour collecter tous les hits (pas seulement le premier)
- [ ] Implémenter le filtre médian sur d_max avec fenêtre de voisins
- [ ] Mode debug : visualiser rays corrigés (rouge) vs non corrigés (vert)
- [ ] Tester sur plan synthétique avec arcs de porte

#### Détection des cours intérieures

Les cours intérieures sont des zones extérieures enclavées dans le bâtiment. Les fenêtres donnant sur une cour doivent être détectées comme fenêtres (2 traits), même si le flood fill depuis les bords de l'image ne les atteint pas.

- [ ] Identifier les particularités graphiques des cours intérieures sur les plans réels
- [ ] Adapter le flood fill : après le fill depuis les bords, détecter les zones blanches non-remplies qui ne sont ni des pièces ni des corridors → candidats cours intérieures
- [ ] Marquer les cours comme extérieur (même traitement que la façade pour la détection fenêtres)
- [ ] Tester sur un plan avec cour intérieure

#### Autres améliorations ingestion

- [ ] Test avec OCR réel (easyocr) sur un plan réel
- [ ] Support PDF : rasterisation via `pymupdf` (prioritaire) ou extraction vectorielle (bonus)
- [ ] Import IFC (`ifcopenshell`) : extraction IfcSpace/IfcDoor/IfcWindow + calage raster
- [ ] Export IFC enrichi : round-trip avec mobilier (IfcFurnishingElement)

### R-11 : Full round trip — Persistance des amendements dans le JSON

Objectif : garantir qu'à un re-import d'un plan déjà travaillé, l'utilisateur retrouve **toutes les sélections et amendements** précédents sans recalcul automatique. L'outil devient stateful : chaque session enrichit le JSON qui sert ensuite de source de vérité.

**Identification du plan** : par nom du fichier PNG (pas de hash, pas de contenu). Deux imports successifs de `test_floorplan3.png` sont considérés comme le même plan.

**Persistance** : l'état (sélections de patterns, amendements layout, amendements géométrie, zones interdites ajoutées en Review, fusions Merge) est **sauvegardé dans le fichier JSON** accompagnant le PNG (Mode Préprocessé) ou dans un JSON sidecar (Mode OCR). L'export = la sauvegarde.

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
    },
    "merges": [ { "ids": ["238", "239"], "merged_name": "238+239" }, ... ]
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

- [ ] Schéma `olm_state` dans le JSON (extension non-breaking de PREPROCESSED_JSON_SPEC v2)
- [ ] Fonction `merge_state_into_rooms()` : à l'import, fusionner `olm_state.rooms_state` avec les pièces extraites
- [ ] Fonction `build_olm_state()` : à l'export, sérialiser l'état courant (sélections + amendements) dans la structure `olm_state`
- [ ] Modifier la route `/api/import/preprocessed` : parser et renvoyer `olm_state` si présent
- [ ] Modifier la route d'export pour produire un JSON enrichi avec `olm_state` à jour
- [ ] UI : badge "Nouveau" sur les pièces sans état + warning listant les orphelines
- [ ] UI : bouton "Reset" par pièce pour supprimer son état et revenir au candidat auto
- [ ] Mode OCR : sidecar `test_floorplan3_state.json` à côté du PNG (puisque pas de JSON d'entrée)
- [ ] Test end-to-end : import → sélection + amendement → export → re-import → vérifier réhydratation
- [ ] Test diff : import → sélection → modifier le JSON (ajouter/supprimer pièces) → re-import → vérifier warnings
- [ ] Documenter dans `PREPROCESSED_JSON_SPEC.md` la section `olm_state`

### R-09 : Identify merges — Fusion de pièces mitoyennes

Fonctionnalité nouvelle dans l'étape ③ du workflow.

Principe :
1. Afficher le plan d'étage complet (toutes les pièces positionnées) avec zoom/pan
2. Détecter automatiquement les murs mitoyens (deux pièces partageant un segment de mur)
3. Afficher une checkbox au milieu de chaque mur mitoyen
4. L'utilisateur coche un mur → les deux pièces sont fusionnées en une pièce plus grande
5. La pièce fusionnée ("Pièce A + Pièce B") est ajoutée à la liste avec le tag "merged"
6. Les pièces merged passent par le même processus (Review → Match → Export) que les pièces réelles

Pré-requis : les pièces doivent être positionnées sur le plan (données d'import avec coordonnées x,y).

Tâches :

- [ ] Algorithme de détection des murs mitoyens (segments communs entre bbox adjacentes)
- [ ] Géométrie de fusion : enveloppe des deux pièces, suppression du mur commun, recalcul fenêtres/portes/exclusions
- [ ] Vue plan complet zoomable avec checkboxes sur les murs mitoyens
- [ ] Création de la pièce merged dans la liste (nom composé, tag merged)
- [ ] Intégration dans le pipeline (Review/Match/Export voient les pièces merged)

### R-10 : Splash screen

- [ ] Ajouter un paramètre `splash_page` dans `config.json` (chemin vers un fichier HTML)
- [ ] Afficher la page au lancement, bouton "Start" ou dismiss
- [ ] Si absent ou vide, aucun splash

### Vérification : rotation des patterns dans les solutions

- [ ] Auditer `catalogue_matcher.py` : vérifier que les rotations 90°/180°/270° des patterns sont testées lors du matching (pas seulement les miroirs E-O)
- [ ] Si absent, ajouter la rotation comme axe de recherche dans le pipeline

### R-06 : Généralisation de l'outil

L'outil est un matcher générique de layouts de pièces vers des patterns d'aménagement simples (pas uniquement des bureaux).

- [ ] Vocabulaire générique dans l'UI : "workspace" au lieu de "desk", "layout" au lieu de "pattern"
- [ ] Paramétrage du type d'élément placé (desk, table, poste, workstation…) via Settings
- [ ] Paramétrage des métriques affichées (m²/personne, score, grade…)
- [ ] Documenter l'API et le format JSON pour des usages hors bureaux

### R-07 : Packaging et déploiement

Dépendances identifiées :

| Package | Rôle | Installation |
|---|---|---|
| `flask` | Serveur web | pip |
| `Pillow` | Traitement image | pip |
| `numpy` | Calcul | pip |
| `jinja2` | Templates HTML | pip (dépendance flask) |
| `easyocr` | OCR (optionnel, ingestion) | pip |
| `pymupdf` | PDF (optionnel, ingestion) | pip |

Note : `ortools` n'est plus nécessaire dans le produit (solveur CP-SAT réservé au `solver_lab/` de R&D).

Tâches :

- [ ] Créer `requirements.txt` avec dépendances exactes
- [ ] Créer `install.bat` : `python -m venv venv && venv\Scripts\pip install -r requirements.txt`
- [ ] Créer `launch.bat` : `venv\Scripts\python -m olm.server` (démarrage serveur, Ctrl+C = arrêt)
- [ ] Vérifier compatibilité Anaconda sans admin
- [ ] Tester le cycle complet : install → launch → utilisation → fermer

---

## PRIORITÉ HAUTE — Ingestion (R-05)

Intégrer le pipeline d'extraction raster dans l'onglet Import et compléter le POC.

Voir la section R-05 ci-dessus pour le détail des tâches.

### Tâche prioritaire — Coloration programmatique du PNG enhanced

Écrire un utilitaire Python qui prend en entrée `test_floorplan_preprocessed_enhanced.png` (ou tout autre PNG du même type — cartouches déjà effacés) et colorie :
- **Extérieur du bâtiment** en bleu ciel RGB(135, 206, 235) via flood fill depuis les 4 coins de l'image (les zones blanches atteintes depuis les bords sans franchir un mur noir deviennent "extérieur").
- **Couloirs intérieurs** en vert RGB(193, 247, 179). Stratégie à choisir : (a) sélection manuelle par clic dans une UI simple, (b) détection automatique par exclusion — toutes les zones blanches restantes qui ne sont PAS des pièces (pas de cartouche OCR associé à proximité) sont des couloirs, ou (c) paramétrage de points-seeds dans un fichier d'accompagnement. L'option (b) est la plus automatique.

Objectif : produire un outil CLI utilisable sur n'importe quel plan sans intervention manuelle (ou avec intervention minimale), qui débloque complètement le test end-to-end du Mode Préprocessé. Pendant ce temps, l'utilisateur peut créer le PNG à la main via un éditeur d'image.

Emplacement recommandé : `olm/tools/colorize_enhanced_png.py` (CLI avec argparse, lit un PNG + JSON v3 optionnel, écrit un PNG colorisé).

Tâches :
- [ ] Charger le PNG avec Pillow, obtenir l'array numpy des pixels
- [ ] Flood fill depuis les 4 coins de l'image sur les pixels blancs → zones "extérieur"
- [ ] Peindre l'extérieur en RGB(135, 206, 235)
- [ ] Optionnel : lire le JSON v3 pour récupérer les positions des cartouches → pour chaque zone blanche connexe restante, vérifier si un cartouche OCR est à l'intérieur → si oui c'est une pièce (rester blanc), sinon c'est un couloir (peindre en vert RGB(193, 247, 179))
- [ ] Sauvegarder le PNG résultat avec suffixe `_colorized.png` (ou écraser l'input si option `--in-place`)
- [ ] Test sur `test_floorplan_preprocessed_enhanced.png`

---

## Priorité moyenne — Revue UX et refactoring restants

### Revue UX (restant)

- [ ] Bug : Design Layout ne rote pas correctement les patterns selon l'orientation de la porte. Si la porte est en haut, les patterns devraient être rotatés mais ils conservent leur orientation par défaut (bureau sur la porte). À auditer dans le pipeline matching + rendu (fpCanvas).
- [ ] Tester le floor plan de référence (`project/plans/test_floorplan.png`) — valider visuellement le matching sur un cas réaliste
- [ ] Adapter le texte/label de chaque onglet workflow (ex: premier onglet → "Review" au lieu de "Import")
- [x] Bug : zone de recul de chaise (chair clearance) apparaît sous la grille dans la vue Design Layout — corriger le z-order (FIXÉ 2026-04-07 : fond opaque #1e1e1e z=0.5 masque grille sous blocs)
- [x] Bug : pointillés de l'arc de porte doivent avoir la même épaisseur que le pointillé vert d'ouverture (free opening) (FIXÉ 2026-04-07 : stroke-width 1.5 + dasharray 6 3)
- [ ] UX : mettre une boîte de la couleur du canvas sous les dimensions d'une pièce dans Import floor plan
- [ ] UX : afficher les unités sur la grille en mode Design Layout (-1m, -2m, etc.)
- [ ] **Orientation canonique des pièces** (D-83) : dans Review et Design, toute pièce est affichée avec couloir en bas et fenêtres en haut. Rotation purement visuelle (0°/90°/180°/270° + miroir éventuel) déduite de la face de la porte principale. Coordonnées internes inchangées. Helper `computeRoomViewTransform(room)` appliqué au groupe racine SVG de `rvCanvas` et `fpCanvas`. Overlays (grille, outil zone interdite, curseur) cohérents avec le référentiel transformé. Heuristique porte principale à définir si plusieurs portes.
- [ ] **Toggle overlay enhanced / plain** (Mode Préprocessé) : en vue Room level avec rotation canonique active, les cartouches de l'overlay plein (`<plan_id>.png`) apparaissent à l'envers. Afficher par défaut l'overlay `<plan_id>_enhanced.png` (sans cartouches, visuellement propre sous rotation). Ajouter un toggle dans la toolbar du canvas Room level pour basculer vers l'overlay plein si l'utilisateur veut lire les numéros dans leur orientation native. Documenté dans `PREPROCESSED_JSON_SPEC.md` §"Suffixe réservé `_enhanced`".
- [ ] **Standard par défaut** (Settings > General) : paramètre `default_standard` (id de standard, ex. `"SITE"`). À l'ouverture de Design layout, le filtre standards se positionne sur ce standard au lieu de "All standards". L'utilisateur peut toujours basculer manuellement vers All ou un autre standard. Rappel : un bureau peut déjà satisfaire plusieurs standards à la fois (un pattern SITE-4 qui n'entre pas dans la pièce peut laisser la place à un AFNOR-3 plus confortable) — le filtrage multi-standards existant reste la source de vérité, ce paramètre ne change que la *vue initiale*.
- [ ] **Couleur par standard** (Settings) : associer une couleur à chaque standard, utilisée pour l'affichage du nom du pattern/solution à la place de la couleur texte par défaut
- [ ] **UI 100 % anglais** : toute chaîne visible par l'utilisateur doit être en anglais. Supprimer les résidus français (labels, tooltips, boutons, textes d'aide, messages d'erreur, noms d'options dans les dropdowns — ex : "OCR (analyse d'image)" → "OCR (image analysis)"). Auditer `olm/templates/*.html` et `olm/static/*.js`. Les commentaires de code et la doc interne (`docs/`) restent en français.
- [ ] **Structurer le panneau Settings en catégories** (drawer à droite) : une section **General** + **une section par onglet top-level** (aujourd'hui : Floorplan, Layout). Le contenu actuel est un mur de champs peu organisés. Cible :
  - **General** : `room_code`, `default_door_width_cm`, `desk_width_cm`, `desk_depth_cm`, `grid_cell_cm`, `default_standard`, couleurs par standard
  - **Floorplan** : tout ce qui touche à l'ingestion et à la vue du plan — `input_mode` (ocr/preprocessed), `scale_cm_per_px`, `threshold`, `pdf_render_dpi`, `min_size_artifact_cm2`, `artifact_promotion_enabled`, `preprocessed_exterior_rgb`, `preprocessed_corridor_rgb`
  - **Layout** : paramètres de matching et design — `w_density`, `w_comfort`, seuils de couverture, standards ES-*/PS-* par standard
  Le drawer Settings actuel est structuré en "sections" mais pas alignées sur les onglets. Refondre pour que la structure du panneau suive exactement l'arborescence des onglets, avec titres de section clairs et séparateurs visuels. Quand on ajoute un nouvel onglet, on ajoute naturellement sa section dans Settings.
- [x] ~~**Mode OCR/Preprocessed → paramètre Settings**~~ — **Obsolète (D-85)** : remplacé par l'auto-détection par fichier (PNG seul → OCR, PNG + JSON récent → Preprocessed). Plus de toggle, plus de paramètre Settings dédié.
- [ ] **Renommage sous-onglets Floorplan** : `Import` → `Floor level`, `Review` → `Room level`. Et séparation stricte des responsabilités :
  - **Floor level** : vue globale du plan. L'utilisateur peut **uniquement** ajouter/supprimer des pièces et modifier leur **position et taille** (bbox editor). Pas d'édition de caractéristiques internes.
  - **Room level** : vue par pièce. L'utilisateur modifie **toutes les autres caractéristiques** : dimensions internes via DSL, ouvertures (portes/baies/fenêtres), zones interdites. Pas de déplacement ni de redimensionnement global de la pièce.
  Cette séparation clarifie le mental model et évite les doubles ergonomies qui se chevauchent actuellement.

### Refactoring architecture frontend — Découplage des vues

- [ ] Fonctions de rendu pures (données en entrée, SVG en sortie) — plus de dépendance au state global
- [ ] Supprimer le mécanisme snapshot/restore léger de l'état éditeur

---

## Étapes existantes non impactées

### Étape 10 : Minimize room size

- [ ] Calcul de la pièce minimale par pattern par standard (ES-04/05/06/08/09)
- [ ] Prise en compte des sticks
- [ ] Usage unitaire : Ctrl+M dans l'éditeur (pattern courant)
- [ ] Usage groupé : sélection multiple dans le catalogue → minimize all selected
- [ ] Usage batch : minimize all — recalcule la taille minimale de tous les patterns du catalogue
- [ ] Feedback visuel : afficher l'ancienne et la nouvelle taille, nombre de patterns modifiés

### Recalibration patterns SITE (D-56)

- [ ] Recalculer les tailles minimales avec les nouvelles distances
- [ ] Vérifier/recréer les patterns SITE existants

---

## Après le prototype — Industrialisation

### Nettoyage

- [ ] Supprimer les anciens modèles (`Room` dans `solver/model.py`, `RoomDims` dans `debt_model.py`)
- [ ] Supprimer le code abandonné (matcher.py, static_matcher.py, debt_model.py)

### Documentation

- [ ] Réécriture SRS alignée sur OLM
- [ ] Réécriture SDS alignée sur OLM
- [ ] SPEC_matcher.md
- [ ] Mise à jour CHANGELOG

---

## Phases conditionnelles (R&D dans solver_lab/)

### Phase 2 — CP-SAT résiduel

- [ ] CP-SAT sur zones libres après matching statique
- [ ] Blocs complémentaires sur zones résiduelles

### Phase 3 — Géométrie stochastique

- [ ] MCMC warm-started depuis catalogue
- [ ] Fonction d'énergie : densité + circulation + confort

---

## Diagnostics en attente

- [ ] 10 tests en échec (debt_model, matcher) — potentiellement obsolètes
