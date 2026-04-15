# Decisions_archive.md — OLM

Décisions historiques archivées (D-01 à D-60).

Ces décisions documentent les architectures antérieures (CP-SAT solver, refactoring frontend initial, D-01 à D-60 de mars-avril 2026). 
Conservées pour traçabilité historique, mais **non actives** dans les sessions courantes.

Voir `Decisions.md` pour les décisions actives (D-61+).

---

# Decisions.md — solver_lab

Journal des décisions de conception prises sur le sous-projet `solver_lab/`.
Chaque entrée indique la date, la décision, la justification et l'impact.

---

## D-01 · Moteur d'optimisation : OR-Tools CP-SAT (2026-03-17)

**Décision** : OR-Tools CP-SAT est le seul moteur d'optimisation autorisé.
**Justification** : Élimine toute heuristique maison (BFS, DFS, backtracking, greedy…), garantit l'optimalité ou la faisabilité prouvée, et est disponible via `pip install ortools` sans droits admin.
**Impact** : Toute contrainte ou fonctionnalité nouvelle doit être exprimée en variables/contraintes CP-SAT. Si ce n'est pas faisable, poser la question avant d'implémenter.

---

## D-02 · Contrainte AFNOR 8 m²/poste : indicateur informatif, non bloquante (2026-03-17)

**Décision** : La surface minimale de 8 m²/poste (AFNOR NF X35-102, open space) n'est pas encodée comme hard constraint.
**Justification** : Inaccessible légalement dans la majorité des contextes clients. Son respect reste une décision humaine a posteriori.
**Impact** : La métrique `m²/poste` est calculée et affichée dans le rapport à titre informatif uniquement (IN-01 dans `CONSTRAINTS.md`).

---

## D-03 · Grille discrète à 10 cm (2026-03-17)

**Décision** : `cell_size_m = 0.10` (10 cm par cellule), configurable via `SolverParams`.
**Justification** : Résolution suffisante pour les dimensions de mobilier de bureau (bureau 180×80 cm → 18×8 cellules). Compromis entre précision et nombre de candidats.
**Impact** : Sur une pièce 5.5×5.0 m → grille 55×50 = 2 750 cellules, ~5 600 candidats. Temps de résolution < 3 s sur ce scénario.

---

## D-04 · Stratégie de placement par blocs canoniques (2026-03-17)

**Décision** : Les candidats sont générés par blocs entiers (BLOC_4 → BLOC_2_COTE → BLOC_2_FACE → BLOC_1), pas poste par poste.
**Justification** : Réduit l'espace de recherche, impose un alignement naturel, et reflète les pratiques réelles d'aménagement.
**Impact** : 4 blocs × leurs rotations = 10 formes canoniques. Un bloc occupe une emprise rectangulaire incluant les dégagements ; le non-chevauchement est garanti par la contrainte cellulaire CP-SAT.

---

## D-05 · Emprise du bloc inclut les dégagements (2026-03-17)

**Décision** : Les dimensions `footprint_w` / `footprint_d` de chaque `BlockShape` intègrent les dégagements réglementaires (tirage de chaise, allée secondaire).
**Justification** : Simplifie le modèle CP-SAT : la contrainte de non-chevauchement des emprises suffit à garantir toutes les distances requises sans contraintes additionnelles de distance.
**Impact** : ~~Le BLOC_4 mesure 3.65 × 4.82 m~~ → Corrigé par D-25 : BLOC_4 eo=2×W=160 cm, ns=2×D=360 cm ; emprise totale avec zones = 2×CHR+2×PAS+160 × 2×PAS+360 = 480×540 cm.

---

## D-06 · Objectif : maximiser postes en priorité, puis score de confort (2026-03-17)

**Décision** : Fonction objectif = `nb_postes × 1000 + score_orientation`.
**Justification** : Le coefficient 1000 garantit que maximiser le nombre de postes prime toujours sur le score de confort. Le score d'orientation (±20 pts) ne peut pas faire basculer le nombre de postes.
**Impact** : Le solveur choisit toujours la solution avec le plus grand nombre de postes ; à nombre égal, il préfère les orientations dos aux fenêtres.

---

## D-07 · Zone d'exclusion porte = 1 m (ES-08) (2026-03-17)

**Décision** : Une zone de 1.0 m devant chaque porte est exclue du placement.
**Justification** : ES-08 (sécurité incendie) impose ≥ 1 m de dégagement libre devant les issues.
**Impact** : Implémenté dans `_door_exclusion_zones()` ; tout candidat dont l'emprise chevauche cette zone est écarté avant construction du modèle CP-SAT.

---

## D-08 · Reproductibilité : 1 seul thread de recherche (2026-03-17)

**Décision** : `num_search_workers = 1` pour CP-SAT.
**Justification** : Garantit des résultats identiques d'une exécution à l'autre sur le même scénario, indispensable pour les tests et la comparaison de scénarios.
**Impact** : Légère perte de performance sur les grandes pièces (pas de parallélisme). Peut être relevé si le temps de résolution dépasse NF-01 (30 s).

---

## D-09 · Scoring calculé a posteriori (hors CP-SAT) (2026-03-17)

**Décision** : Les scores de confort individuels (`score_desk`) sont calculés après la résolution, pas intégrés comme soft constraints CP-SAT pondérées.
**Justification** : Simplification du modèle. Seul un hint d'orientation grossier (±20 pts) est injecté dans l'objectif CP-SAT ; le scoring complet (visibilité collègues, vue porte, etc.) est calculé sur la solution retenue.
**Impact** : Le score affiché dans le rapport peut différer de l'objectif CP-SAT optimisé. Le scoring complet sert à l'analyse et à l'affichage, non à la recherche.

---

## D-10 · Typage explicite des cellules de la grille — `CellType` (2026-03-17)

**Décision** : Ajout d'une énumération `CellType` (`FREE=0`, `WALL=1`, `FOOTPRINT=2`, `DOOR=3`) dans `model.py` et d'une matrice numpy `grid: np.ndarray` construite a posteriori dans `build_grid()` (`cpsat_solver.py`). La grille est exposée via `PlacementResult.grid`.
**Justification** : Infrastructure requise pour la future contrainte de connectivité piétonne (garantir que chaque cellule `FREE` est accessible depuis une porte). La grille typée remplace la représentation implicite par les limites `ROWS`/`COLS`.
**Impact** :
- La grille n'entre pas dans le modèle CP-SAT — elle est construite après `solver.solve()`, sans modifier les variables ni les contraintes.
- Le dictionnaire `cell_to_candidates` coexiste avec `grid` : le premier sert au modèle CP-SAT, le second à la visualisation et à la connectivité.
- Ordre de construction : `FOOTPRINT` en premier, puis `WALL` périmétrique (écrase les blocs sur le bord), puis `DOOR` (écrase le mur). Le périmètre prime toujours sur les emprises, garantissant `grid[0,0] == WALL` même si un bloc est placé à la limite de la pièce.
- Pas de type `CHAIR` distinct : les chaises sont incluses dans `FOOTPRINT` (décision susceptible d'évoluer).

---

## D-11 · ~~SUPERSÉDÉE par D-12 puis D-13~~ · Connectivité piétonne — pré-filtrage géométrique hors CP-SAT (2026-03-17)

**Décision** : La garantie de connectivité piétonne est implémentée comme un pré-filtrage géométrique en Python pur dans `_compute_corridor_cells()`, au même titre que `_door_exclusion_zones()` (D-07). CP-SAT ne voit pas ce problème.
**Justification** : La contrainte de connectivité exprimée en flot CP-SAT (variables de flot sur ~11 000 arcs) alourdissait le modèle sans garantir le respect du budget temps NF-01 (30 s). Le pré-filtrage est exact, déterministe, et n'ajoute aucune variable au modèle.
**Méthode** :
1. BFS depuis toutes les portes sur la grille vide pour calculer les distances.
2. Pour chaque cellule intérieure navigable, mesurer la largeur libre locale dans les axes H et V.
3. Si largeur ≤ 80 cm (AFNOR NF X35-102) dans l'un des axes → cellule de corridor intouchable.
4. Tout candidat dont l'emprise couvre au moins une cellule de corridor est éliminé avant la construction du modèle CP-SAT.
**Impact** :
- `corridor_cells: Set[Tuple[int, int]]` transmis à `PlacementResult.corridor_cells` pour visualisation uniquement.
- N'apparaît pas dans les métriques ni dans les contraintes CP-SAT.
- `build_grid()` reste inchangée.

---

## D-13 · Placement simultané postes + corridors — refonte du solveur (2026-03-17)

**Décision** : Introduire les corridors comme objets CP-SAT à part entière (`BlockShape.is_corridor = True`), placés simultanément avec les postes dans une résolution unique (sans boucle).
**Justification** :
- D-12 (boucle de coupes) n'assurait que la connectivité a posteriori ; aucune garantie d'accessibilité de chaque poste.
- Le nouveau modèle garantit structurellement que chaque poste actif est adjacent à un corridor (C-2) et que le réseau de corridors atteint une porte (C-3 flux CP-SAT).
**Contraintes CP-SAT ajoutées** :
- C-1 Non-chevauchement global : `sum(bvars + cvars sur la cellule) <= 1`
- C-2 Accessibilité côté chaise : `b_i <= sum(c_j couvrant côté chaise de b_i)`, une contrainte par orientation présente dans le bloc.
- C-3 Connexité : flux `f_ij ∈ [0, N_COR]` sur paires de corridors adjacents (bordure partagée ≥ 0,80 m) ; `door_source_j` pour corridors porte-adjacents ; `sum(flux entrants) + door_source_j >= c_j`.
**Objectif** : `maximize sum(b_i × nb_postes × 1000 − b_i × hint_distance_porte)`.
- `hint_distance_porte` = int(dist_euclidienne_m × 10) × poids // 10, max ≈ 220 ≪ 1000 (ne change pas le nb de postes).
**Impact** :
- Suppression de `_find_connectivity_cuts` et de la boucle de coupes (D-12 remplacé).
- `build_grid()` étendu : `CellType.CORRIDOR = 4` pour les cellules corridor actif.
- Nouvelles métriques : `nb_corridors`, `avg_distance_to_door_m` (BFS sur FREE + CORRIDOR).
- `PlacementResult.corridors` : liste `[(x_m, y_m, w_m, d_m)]` pour visualisation SVG/ASCII.
- Le catalogue corridor génère 12 types (6 longueurs × 2 orientations), production ≈ 12 000–20 000 candidats sur une pièce 5,5 × 5 m.

---

## D-14 · Catalogue de patterns pré-calculés — CP-SAT résiduel uniquement (2026-03-18)

**Décision** : Le placement principal repose sur un catalogue de patterns canoniques
pré-calculés et validés. CP-SAT n'intervient qu'en résiduel sur les zones libres
résiduelles après adaptation du pattern à la pièce.
**Justification** : L'approche CP-SAT full-room (D-13) produisait des temps de
résolution incompatibles avec un usage production sur de grandes pièces. Le catalogue
réduit l'espace de recherche à un ensemble fini de configurations validées.
**Impact** : Nouveau pipeline en deux temps — génération catalogue / adaptation pièce.
Les modules solver.py et cpsat_solver.py deviennent des composants résiduels.

---

## D-15 · Sélection des patterns par dominance de Pareto (2026-03-18)

**Décision** : Les patterns du catalogue sont évalués sur trois critères —
m²/poste (minimiser), grade circulation (maximiser), score confort (maximiser).
La sélection finale utilise la dominance de Pareto sur ces trois dimensions.
**Justification** : Aucun critère unique ne capture la qualité d'un aménagement.
La dominance de Pareto évite d'imposer des pondérations arbitraires.
**Impact** : Le scoring multi-critères est calculé a posteriori (cohérent avec D-09).
Un front de Pareto est exposé dans le rapport — Patrick choisit parmi les
solutions non dominées.

---

## D-16 · Modèle de dette de circulation (2026-03-18)

**Décision** : Lors de la génération d'un pattern, les blocs sont positionnés avec
leurs zones candidates complètes (emprise gonflée). Le dépassement de l'emprise
cible est accepté si et seulement si il est entièrement attribuable à des zones
candidates supprimables. La dette est résorbée a posteriori par analyse de flux.
**Justification** : Permet de générer des configurations denses sans rejeter
prématurément des solutions valides. La suppression des zones redondantes est
déterministe et contrôlée.
**Impact** : Deux issues possibles à la résolution de la dette — solution valide
(dette résorbée) ou rejet (dette résiduelle). Pas de bouclage pour combler les
zones libres résiduelles : c'est un signal que la génération initiale est
sous-optimale.

---

## D-17 · Orientation Option B — bureaux NS, regard E/W (2026-03-19)

**Décision** : Les bureaux sont orientés NS (profondeur 180 cm dans l'axe NS).
Les utilisateurs regardent EST ou OUEST. La rotation est portée par le pattern
entier — jamais appliquée aux blocs individuels.
**Justification** : Option B retenue après comparaison des configurations possibles.
La profondeur NS d'une rangée = 180 cm (faible profondeur), ce qui maximise le
nombre de rangées dans une pièce de profondeur standard.
**Impact** : Les blocs s'enchaînent dans l'axe EO. Les débattements chaise (70 cm)
sont dans l'axe EO, internes aux blocs. La décomposition NS d'un double-row =
90+180+90+180+90 = 630 cm.

---

## D-19 · Compression aux minima AFNOR avant redistribution du slack (2026-03-19)

**Décision** : Après résolution de la dette (D-16), tous les blocs et postes sont
resserrés aux distances minimales normatives (compression fonctionnelle). Le slack
résiduel est ensuite redistribué pour homogénéiser les espacements et maximiser
la largeur des zones de circulation.
**Justification** : La compression révèle les zones libres résiduelles liées à la
topologie de la pièce. La redistribution est fonctionnelle, pas esthétique —
elle maximise la praticabilité des circulations.
**Impact** : Deux sous-étapes distinctes et séquentielles dans le pipeline
d'adaptation. La compression est calculable sans CP-SAT.

---

## D-20 · Rotations et symétries de patterns (2026-03-20)

**Décision** : Le nombre d'orientations générées par pattern dépend de la symétrie
des faces des blocs constituants.
- Blocs à faces symétriques (BLOC_2_FACE, BLOC_4, BLOC_6 — N=S et E=W) :
  2 orientations distinctes (0° et 90°).
- Blocs à faces asymétriques (BLOC_2_COTE, BLOC_1) :
  4 orientations distinctes (0°, 90°, 180°, 270°).
- Miroir EO : généré uniquement pour les patterns dont la rangée nord ≠ rangée sud
  (ex. P_B4_B4B2F). Redondant et non généré pour les patterns nord=sud.
Aucune orientation n'est exclue a priori pour des raisons normatives ou
topologiques. C'est le scoring multi-critères (D-15) qui différenciera les
orientations favorables.
**Justification** : Cohérent avec D-01 (le solveur et les scores font le travail,
pas des règles d'exclusion amont) et D-17 (rotation portée par le pattern entier).
**Impact** : Le catalogue passe de N à 2N entrées pour les patterns actuels
(blocs symétriques). Les identifiants JSON incluent le suffixe d'orientation :
P_B4_B4__R0, P_B4_B4__R90, P_B4_B4B2F__R0, P_B4_B4B2F__R90,
P_B4_B4B2F__MIRROR. La fonction de rotation n'est pas encore implémentée —
ce ticket ouvre l'implémentation.

---

## D-12 · ~~SUPERSÉDÉE par D-13~~ · Connectivité piétonne — boucle de coupes post-résolution (2026-03-17)

> **Note** : cette décision est placée ici par ordre de numérotation. Elle a été créée après D-11, remplaçant D-11. Elle-même a été remplacée par D-13.

**Décision** : La connectivité piétonne est garantie par une boucle de coupes CP-SAT insérée après `solver.solve()`. À chaque itération : BFS Python depuis les portes sur les cellules FREE/DOOR, détection des blocs isolés (aucune cellule adjacente atteignable), ajout d'une coupe `sum(bvars) <= N-1` par bloc isolé (bloc isolé + blocs barrière connectés). La boucle tourne jusqu'à convergence ou épuisement du budget temps.
**Justification** : Remplace `_compute_corridor_cells()` (D-11), qui ne détectait aucun corridor sur les pièces ouvertes des scénarios actuels. La boucle de coupes fonctionne sur toutes les géométries et ne nécessite aucune hypothèse sur la forme de la pièce.
**Impact** :
- `_compute_corridor_cells()` supprimée ; `corridor_cells` retiré de `PlacementResult`.
- Nouvelles métriques : `nb_iterations` (nombre de résolutions CP-SAT) et `nb_coupes` (nombre de coupes ajoutées).
- Le budget temps `SolverParams.time_limit_s` est partagé entre toutes les itérations via `remaining = time_limit_s - elapsed`.
- Sur `square_room` : convergence en 4 itérations, 3 coupes. Sur `base_room` et `narrow_room` : convergence dès la 1ère itération (0 coupe).

## D-18 · ~~SUPPRIMÉE~~ · Tolérance ±10% sur physical_eo/ns (2026-03-19)

> Remplacée par D-21.

---

## D-21 · Règle de matching catalogue → pièce (2026-03-27)

> Remplace D-18.

**Décision** : Un pattern est retenu pour une pièce de dimensions `room_eo × room_ns` si :
`min_eo <= room_eo <= total_eo` ET `min_ns <= room_ns <= total_ns`.
**Définitions** :
- `min_eo = west.non_superposable_cm + physical_eo_cm + east.non_superposable_cm`
- `min_ns = physical_ns_cm`
- `total_eo`, `total_ns` = emprise complète du catalogue (toutes zones candidates incluses)
**Justification** : Toutes les zones candidates sont supprimables a priori. Les bornes sont dérivées de la géométrie — aucune tolérance arbitraire.
**Impact** : D-18 (tolérance ±10%) supprimée.

---

## D-22 · Sémantique CellType pour les zones non-superposables (2026-03-27)

**Décision** : Les zones de débattement chaise (70 cm, orange) sont mappées en `CellType.CORRIDOR` dans la grille synthétique de `debt_model.py`, et non en `CellType.FOOTPRINT`.
**Justification** : Ces zones sont physiquement franchissables. La contrainte qu'elles portent est une interdiction de superposition de mobilier, pas une obstruction physique. Les mapper en FOOTPRINT isolerait les corridors E/W adjacents.
**Impact** : Corrige SPEC_debt_model.md §4 Phase 2a : remplacer `CellType.DESK` par `CellType.CORRIDOR`.

---

## D-23 · Algorithme de ranking Pareto : fronts itératifs NSGA-II (2026-03-27)

**Décision** : Le champ `pareto_rank` de `MatchResult` est calculé par fronts itératifs selon l'algorithme NSGA-II. Rang 1 = solutions non dominées sur (sqm_per_desk ↓, circulation_grade_cm ↑). Rang 2 = non dominées après retrait du rang 1, etc.
**Justification** : Un rang binaire (dominé / non-dominé) ne permet pas de trier les résultats de manière utile quand plusieurs fronts existent.
**Impact** : `_assign_pareto_ranks()` dans `matcher.py`. Tri final = `pareto_rank ASC, sqm_per_desk ASC`.

---

## D-24 · Phase 3 : redistribution du slack aux zones actives (2026-03-27)

**Décision** : Après compaction (Phase 2c), le slack résiduel est redistribué proportionnellement aux zones candidates actives sur chaque axe indépendamment.
**Algorithme** :
- Si aucune zone active → slack reste libre.
- Si zones actives → `bonus = (free × zone_cm / total_initial) // CELL_CM × CELL_CM`.
- Invariants : `eo_cm + free_eo_cm == room.eo_cm` ; zones multiples de CELL_CM.
**Justification** : Maximise la praticabilité des circulations sans dépasser l'emprise de la pièce.
**Impact** : `_redistribute_slack()` dans `debt_model.py`. Le slack orphelin (aucune zone active) n'est pas redistribué.

---

## D-25 · Langage formel de description des blocs et patterns (2026-03-27)

**Décision** : Les blocs et patterns sont décrits dans un langage formel
géométrique servant de source de vérité pour le code, les specs et les dessins SVG.

Repère commun (mis à jour D-26) :
  Origine (0,0) = coin **Nord-Ouest** de l'emprise fixe du bloc ou pattern.
  x positif → EST, y positif → **SUD**.
  Orientations : 0°, 90°, 180°, 270° (rotation horaire).

Constantes (point de modification unique) :
  W   = DESK_W_CM           — dimension d'un bureau dans l'axe du regard
  D   = DESK_D_CM           — dimension d'un bureau perpendiculaire au regard
  CHR = CHAIR_CLEARANCE_CM  — zone fixe, débattement chaise
  PAS = PASSAGE_CM          — zone candidate, passage

Définition d'un bloc :
  Chaque bureau est décrit par son regard et sa position (coin NW du bureau).
  L'emprise fixe = physique + zones fixes (CHR) sur les faces concernées.
  Les zones candidates sont décrites explicitement en coordonnées relatives.
  Les dimensions physiques et les zones fixes sont déduites des regards et
  positions — elles ne sont pas déclarées explicitement.

  BUREAU (convention regard=EST, repère NW D-26) :
    B1 : regard=EST, pos=(0, 0)
    zones :
      W : type=fixe,      rect=[(-CHR, 0),  (0,      D)  ]
      N : type=candidate, rect=[(0, -PAS),  (W,      0)  ]
      S : type=candidate, rect=[(0,    D),  (W,   D+PAS) ]

  BLOC_2_FACE :
    B1 : regard=EST,   pos=(0, 0)
    B2 : regard=OUEST, pos=(W, 0)
    zones :
      W : type=fixe,      rect=[(-CHR,    0), (0,      D)  ]
      E : type=fixe,      rect=[(2W,      0), (2W+CHR, D)  ]
      N : type=candidate, rect=[(0,    -PAS), (2W,     0)  ]
      S : type=candidate, rect=[(0,       D), (2W,  D+PAS) ]

  BLOC_4 :
    B1 : regard=EST,   pos=(0,  0)
    B2 : regard=OUEST, pos=(W,  0)
    B3 : regard=EST,   pos=(0,  D)
    B4 : regard=OUEST, pos=(W,  D)
    zones :
      W : type=fixe,      rect=[(-CHR,    0), (0,       2D)  ]
      E : type=fixe,      rect=[(2W,      0), (2W+CHR,  2D)  ]
      N : type=candidate, rect=[(0,    -PAS), (2W,       0)  ]
      S : type=candidate, rect=[(0,      2D), (2W,   2D+PAS) ]

  BLOC_6 :
    B1 : regard=EST,   pos=(0,   0)
    B2 : regard=OUEST, pos=(W,   0)
    B3 : regard=EST,   pos=(0,   D)
    B4 : regard=OUEST, pos=(W,   D)
    B5 : regard=EST,   pos=(0,  2D)
    B6 : regard=OUEST, pos=(W,  2D)
    zones :
      W : type=fixe,      rect=[(-CHR,    0), (0,       3D)  ]
      E : type=fixe,      rect=[(2W,      0), (2W+CHR,  3D)  ]
      N : type=candidate, rect=[(0,    -PAS), (2W,       0)  ]
      S : type=candidate, rect=[(0,      3D), (2W,   3D+PAS) ]

Définition d'un pattern :
  Le premier bloc a ref=origine.
  Les suivants sont positionnés en relatif :
    ref=NOM_INSTANCE, axe=direction, dist=distance entre emprises fixes.
  La distance canonique entre deux blocs indépendants est 2×PAS
  (chaque bloc porte sa propre zone candidate de chaque côté).
  Le debt model réduit cette distance vers PAS ou 0 selon le contexte.

  Exemple (repère NW D-26, la seconde rangée est au sud) :
    P_B4_B4 :
      BLOC_4_A : bloc=BLOC_4, orientation=0°, ref=origine
      BLOC_4_B : bloc=BLOC_4, orientation=0°, ref=BLOC_4_A, axe=SUD, dist=2×PAS

    P_B4_B2F :
      BLOC_4_A  : bloc=BLOC_4,     orientation=0°, ref=origine
      BLOC_2F_A : bloc=BLOC_2_FACE, orientation=0°, ref=BLOC_4_A, axe=EST, dist=2×PAS

**Correction impliquée** :
  BLOC_4 et BLOC_6 ont leurs dimensions EO/NS inversées dans le code actuel.
  Corrections dans pattern_generator.py (voir spec de correction associée) :
    BLOC_4 : eo_cm = DESK_W_CM * 2,  ns_cm = DESK_D_CM * 2
    BLOC_6 : eo_cm = DESK_W_CM * 2,  ns_cm = DESK_D_CM * 3
    compose_row : ns = max(b.ns_cm for b in blocks)

---

## D-26 · Changement de repère : NW→SE (2026-03-28)

**Décision** : Le repère de référence pour le projet OLO passe de SW→NE à **NW→SE**.
- Origine (0,0) = coin **Nord-Ouest** de l'emprise fixe du bloc ou pattern
- x positif → **Est** (inchangé)
- y positif → **Sud** (inversé)
- Convention cohérente avec numpy/images (row 0 = haut = nord)

**Justification** : La stratégie de placement démarre au nord (près de la fenêtre)
et progresse vers le sud. L'origine NW est plus naturelle pour cet algorithme et
aligne le repère formel avec la convention numpy utilisée dans `debt_model.py`.

**Impact** :
- D-25 : descriptions formelles mises à jour (zones N et S inversées)
- `pattern_generator.py` : aucun changement (utilise des labels, pas des coordonnées)
- `debt_model.py` : aucun changement (utilisait déjà NW origin dans la rasterisation)
- `cpsat_solver.py` : utilise encore SW origin — migration à faire lors de l'intégration du solveur résiduel (Temps 2)
- `render_html.py` : inversion y à supprimer une fois cpsat_solver.py migré
- `model.py` : commentaire `y_m` à mettre à jour (« axe Nord » → « axe Sud »)
    

## D-27 · Changement de repère : NW→SE (2026-03-28)
 — Workflow et architecture agentique

### Workflow VS Code (décision immédiate)
- **ARCHITECT** : extension Claude Code (panneau graphique VS Code)
- **IMPLEMENTER** : terminal CLI dans VS Code
- **Validation SVG** : Live Server conservé (Option B déjà pratiquée)
- **Web search** : reste sur claude.ai si besoin ponctuel, pas de MCP serveur pour l'instant

### Structure projet
- Pas de restructuration avant les premiers résultats sur salles réelles
- Réévaluer en entrée de phase industrielle

### Sub-agents Claude Code (décision phase 2)
- Ne pas utiliser maintenant : les points de validation visuelle intermédiaires 
  doivent rester sous contrôle humain
- Pertinent en phase industrielle quand :
  1. Specs D-25 et invariants pipeline figés et éprouvés
  2. Tâches répétitives en batch (N salles, N variantes)
  3. Validation humaine hors de la boucle chaude
- Cas d'usage cible : orchestrateur enchaînant génération → dette → 
  compression → SVG → rapport sur catalogue de salles

### MCP serveur recherche web
- ROI insuffisant pour la phase actuelle
- Réévaluer en phase industrielle si besoins sectoriels non anticipés

---

## D-28 · Approche statique en priorité — trois phases de placement (2026-03-28)

**Décision** : Le placement de postes de travail dans les pièces repose sur
trois phases successives, de complexité croissante. La phase 1 (statique) est
la priorité immédiate. Les phases 2 et 3 sont conditionnées aux résultats de
la phase précédente.

### Phase 1 — Approche statique (priorité immédiate)

**Principe** : un catalogue de ~200 patterns fixes (600-800 avec miroirs/rotations),
créés manuellement dans un outil interactif HTML. Chaque pattern stocke :
- Géométrie : positions des postes et blocs dans le repère D-26
- Dimensions minimales de pièce dans les 3 standards (AFNOR, KARDHAM, LOCAL)
- Métadonnées : nombre de postes, type de blocs, configuration de portes

**Pipeline de placement** :
1. Matching : plus grand pattern compatible (rectangle) pour la pièce et le standard
2. Suppression des postes intersectant les zones interdites de la pièce
3. Calcul des circulations et scores de confort
4. Rééquilibrage : redistribution des postes pour occuper l'espace harmonieusement
5. Validation humaine

**Boucle d'enrichissement du catalogue** :
- Si une zone résiduelle significative reste après placement → alerte
- L'expert crée un nouveau pattern dans l'outil interactif
- Re-matching avec le catalogue enrichi
- Le catalogue converge naturellement vers la couverture des cas réels

**Optimisations de symétrie** (générées automatiquement à la sauvegarde) :
- Rotation 90° de chaque pattern
- Miroir EO (porte gauche ↔ porte droite)
- Miroir NS si pertinent

**Outillage critique** :
- Éditeur interactif HTML (glisser-déposer, calcul instantané des scores)
- Gestion du catalogue : duplication, modification, suppression, filtrage
- Templates paramétriques (ex : rangée de N×BLOC_4, N ajustable)
- Visualisation en mosaïque de tout le catalogue
- Recalcul des dimensions minimales en batch lors d'une mise à jour de standard

**Justification** : rapport complexité/valeur très favorable. ~85% des pièces
sont rectangulaires et couvertes directement. Les cas limites sont traités par
enrichissement du catalogue plutôt que par un algorithme complexe.

### Précisions Phase 1 (2026-03-29)

**Matching large→petit** : le matching peut se faire avec des patterns plus
grands que la pièce. On superpose le pattern à la pièce (avec décalages E/S
et rotations/symétries), et on ne conserve que les postes strictement à
l'intérieur et sans conflit avec les zones interdites. Une session de matching
d'un seul pattern peut générer de nombreux sous-patterns. Déduplication par
description textuelle (le décalage de quelques cm n'est pas discriminant car
le rééquilibrage ajustera). Cela réduit potentiellement le catalogue de
~200 à ~20-30 méga-patterns.

**Granularité du matching = poste unitaire, pas bloc** : quand un bloc de 4
postes est proche d'une zone interdite (ex : porte sud-ouest), seul le poste
en conflit est supprimé. Il reste un groupe de 3 postes. Les notions de
pattern et sous-pattern doivent être formalisées.

**Pipeline de scoring** : la circulation est scorée **après** le rééquilibrage,
pas avant. Sans cela, les sous-patterns avec des bords dégradés seraient
injustement éliminés alors qu'ils pourraient devenir les meilleurs résultats
après redistribution des postes dans l'espace disponible.
Pipeline :
1. Générer tous les sous-patterns valides
2. Pré-filtre léger (chemin porte→postes possible)
3. Rééquilibrer chaque sous-pattern dans la pièce
4. Scorer circulation + confort (après rééquilibrage)
5. Sélectionner le meilleur

**Priorité circulation > esthétique** : l'objectif principal du rééquilibrage
est la maximisation de la taille des zones de circulation. L'esthétique et
l'équilibrage ne sont considérés qu'une fois le seuil de confort atteint
(≥ 120 cm, passage multi-personnes).

**DSL de création de patterns** : les patterns sont décrits ligne par ligne
(du nord vers le sud), chaque ligne listant les postes et blocs d'ouest en
est. Le système calcule le placement initial en fonction des emprises et
des marges. L'utilisateur ajuste ensuite visuellement (pas de 10 cm ou 50 cm,
grille en pointillés optionnelle). Ce DSL peut aussi servir de format de
stockage si on y ajoute les coordonnées NW de chaque élément.

**Zones interdites des entrées** :
- Porte battante (90 cm) : zone libre = largeur porte × profondeur selon standard.
  GROUP = 180 cm, SITE = 100 cm. Sens d'ouverture (gauche/droite) affecte l'arc.
- Ouverture libre (largeur variable) : pas de zone d'exclusion — gérée par
  l'analyse de circulation.

**Renommage des standards** :
- AFNOR → **AFNOR ADVICE** (caractère consultatif)
- KARDHAM → **GROUP** (standard interne du groupe)
- LOCAL → **SITE** (spécifique au site client)

### Phase 2 — Approche dynamique avec zones candidates (conditionnelle)

**Principe** : réintroduire le modèle de dette (D-16) et CP-SAT résiduel sur
les pièces que l'approche statique ne couvre pas bien (formes en L, T, U avec
zones interdites complexes).

**Déclencheur** : si le taux de pièces non couvertes par le catalogue statique
dépasse un seuil significatif en production réelle.

**Travail existant réutilisable** :
- `debt_model.py` (phases 1-3) — mis en pause, pas supprimé
- `matcher.py` (logique de matching Pareto)

### Phase 3 — Géométrie stochastique (hybride opérationnel)

**Principe** : utiliser la géométrie stochastique comme **outil de complétion**
après le matching statique — remplir les zones résiduelles, ajuster les
positions. Approche hybride : le catalogue statique sert de warm start pour
une chaîne MCMC (Metropolis-Hastings / recuit simulé).

**Outils mathématiques** : processus de points durs (hard-core, Gibbs),
processus germes-grains (rectangles orientés), MCMC avec propositions
intelligentes (grille 10 cm, orientations cardinales, blocs entiers).

**Objectif double** :
- Opérationnel : compléter les zones que le catalogue statique ne couvre pas
- Culturel : explorer le potentiel des méthodes stochastiques pour le placement

**Impact** :
- Le travail sur le pipeline catalogue (pattern_generator, circulation, scoring)
  reste pertinent dans les trois phases
- debt_model.py et CP-SAT résiduel sont mis en pause, pas supprimés
- L'investissement Phase 1 se concentre sur l'outillage de catalogue (éditeur
  interactif, DSL, gestion des patterns)

---

## D-29 · Format de stockage et DSL des patterns (2026-03-29)

**Décision** : Les patterns sont stockés en **JSON** (format d'implémentation) avec conversion bidirectionnelle vers un **DSL texte** (format d'interface et de manipulation humaine).

**Format JSON** : chaque pattern contient une liste de rangées (`rows`), chaque rangée contient une liste de blocs avec type, orientation et `gap_cm` (distance entre emprises, chaînage séquentiel). Les gaps inter-rangées sont dans `row_gaps_cm`.

**Format DSL** : compact, une ligne par pattern. `,` sépare les éléments d'une rangée, `;` sépare les rangées. Un nombre = distance en cm. `@N` = orientation. Exemples :
- `P_B4_B2F: BLOC_4, 180, BLOC_2_FACE`
- `P_B4_B4: BLOC_4; 180; BLOC_4`

**Justification** : les gaps relatifs (distance entre emprises) plutôt que des positions absolues évitent de recalculer tout le pattern quand on ajuste un couloir de circulation. Le DSL compact permet la manipulation par copier-coller et la lisibilité humaine. La bijection DSL ↔ JSON est directe.

**Impact** : spec complète dans `specs/PATTERN_DSL_SPEC.md`. Le nombre de postes et les dimensions d'emprise sont calculés à l'instanciation (non stockés). L'ancien format de catalogue (`output/catalogue.json`) sera migré.

---

## D-30 · Renommage BLOC_4→BLOC_4_FACE / BLOC_6→BLOC_6_FACE et ajout BLOC_3_COTE (2026-03-30)

**Décision** : Renommage de BLOC_4 en BLOC_4_FACE et BLOC_6 en BLOC_6_FACE. Ajout de BLOC_3_COTE (3 postes côte à côte, regard identique, colonne unique, asymétrique).

**Justification** : Le suffixe `_FACE` explicite la configuration face à face (regards convergents) par opposition à `_COTE` (regards identiques, côte à côte). BLOC_3_COTE complète le catalogue pour les rangées de 3 postes non appariés, utile pour les zones résiduelles ou pièces étroites.

**Impact** : Renommage mécanique propagé dans `pattern_generator.py`, `solver/cpsat_solver.py`, `solver/config_dsl.py`, tous les fichiers de tests et toutes les specs. BLOC_3_COTE est asymétrique (face E absente ≠ face W fixe) → 4 orientations possibles. Non ajouté aux patterns existants pour l'instant.

---

## D-31 · Décalage NS individuel par bloc dans le DSL (2026-03-31)

**Décision** : Chaque bloc d'une rangée peut porter un décalage nord-sud individuel par rapport à la ligne de base de sa rangée. Le décalage est exprimé en cm, par pas de 10 cm, dans la notation `SUD<N>` ou `NORD<N>` (ex : `SUD20`, `NORD30`).

**Notation DSL** : le décalage suit le bloc (et son orientation éventuelle), séparé par un espace. Exemples :
- `BLOC_4_FACE SUD20` → décalé de 20 cm vers le sud
- `BLOC_2_FACE@90 NORD10` → orienté 90° et décalé de 10 cm vers le nord
- `BLOC_4_FACE` → pas de décalage (0 cm par défaut)

**Format JSON** : champ `offset_ns_cm` dans chaque entrée de bloc. Positif = sud, négatif = nord. Absent ou 0 = pas de décalage.

**Justification** : Permet de modéliser des patterns où un bloc est décalé verticalement par rapport aux autres de sa rangée (ex : bloc aligné sur une porte ou une fenêtre), tout en conservant la structure de rangées. Le pas de 10 cm est cohérent avec la grille (D-03).

**Impact** : Extension de `PATTERN_DSL_SPEC.md` (grammaire + exemples). Mise à jour du parseur DSL (`pattern_dsl.py`) et de l'éditeur (`pattern_editor.html`). Le décalage est pris en compte dans le calcul de l'emprise NS totale du pattern.

---

## D-32 · Renommage "zone candidate" → "zone minimale de circulation" (2026-03-31)

**Décision** : Le terme "zone candidate" (hérité de l'approche dette/slack D-16) est
abandonné. Le champ `candidate_cm` dans `FaceZone` désigne désormais une **zone
minimale de circulation** : obligatoire, extensible mais pas réductible.

**Terminologie mise à jour** :
- ~~zone candidate~~ → **zone minimale de circulation**
- ~~supprimable~~ → **extensible** (le scoring/rééquilibrage peut l'agrandir)
- "zone fixe" (non-superposable, débattement chaise) reste inchangé

**Rôle au matching** : seule l'emprise physique + zones fixes (fauteuil) doit
tenir dans la pièce. Les zones minimales de circulation ne sont PAS vérifiées au
matching — c'est le scoring/rééquilibrage (étape 4) qui détermine si la
circulation est suffisante et repositionne les blocs de manière optimale.

**Justification** : L'approche statique (D-28) ne résout pas de dette de zones.
Les zones de passage existent toujours physiquement mais leur dimensionnement
est géré par l'heuristique de circulation, pas par un modèle de dette. Le terme
"candidate" (supprimable a priori) induisait en erreur.

**Impact** :
- `pattern_generator.py` : commentaires FaceZone mis à jour, factory methods
  renommées (`candidate_only` → `circulation_only`, `chair_and_passage` →
  `chair_and_circulation`)
- `block_constants.js` : commentaires `COLOR_CAND_*` mis à jour
- `static_matcher.py` : vérification emprise = physique + zones fixes uniquement
- Le champ `candidate_cm` est conservé dans le code pour compatibilité
- Légendes des viewers mises à jour


---

## D-34 · Pipeline de rééquilibrage : équilibrage + descente locale (2026-03-31)

**Décision** : Le repositionnement des blocs après matching suit deux étapes :
- Étape 0 : équilibrage à équidistance sur les deux axes (géométrie pure).
- Étape 1 : descente locale par déplacements unitaires (10 cm, N/S/E/W) guidés par le score de circulation. Pas de multi-pas ni de look-ahead. La distinction allées principales (160 cm) vs secondaires (90 cm) dans le scoring crée un gradient naturel vers les bonnes solutions.

**Justification** : Avec 2-6 blocs par pièce, l'espace de solutions est petit. L'équilibrage initial place les blocs dans une configuration viable. La descente locale optimise la circulation sans risque d'explosion combinatoire. Les maxima locaux sont peu probables grâce aux paliers normatifs (90 cm, 160 cm) qui créent des gradients forts. Si insuffisant en pratique, une exploration brute force avec élagage sera envisagée.

**Impact** : Nouveau module à créer. OR-Tools CP-SAT n'est pas nécessaire pour ce problème (géométrie déterministe, pas d'optimisation combinatoire). Les non-chevauchements sont vérifiés par calcul géométrique direct.

---

## D-33 · Pas de miroir EO/NS au matching, enrichissement du catalogue (2026-03-31)

**Décision** : Le matching statique ne génère pas de miroirs (EO ni NS) des patterns. Les 4 rotations (R0, R90, R180, R270) sont suffisantes. Les configurations de blocs perpendiculaires (ex : BLOC_1 regard nord + BLOC_1 regard est) sont couvertes par des patterns dédiés dans le catalogue.

**Justification** : Le miroir est redondant avec les rotations pour les blocs symétriques (BLOC_2/4/6_FACE). Pour les sous-patterns multi-blocs perpendiculaires, le miroir produit de nouvelles combinaisons mais la complexité induite (rejet des doublons alignés, explosion combinatoire) ne justifie pas le gain. Enrichir le catalogue avec quelques patterns bien choisis est plus simple, plus lisible et plus contrôlable.

**Impact** : Pas de fonction `mirror_blocks_eo` dans `static_matcher.py`. `generate_rotations()` reste à 4 variantes. La couverture des configurations perpendiculaires est assurée par le catalogue, pas par le matching.

---

## D-35 · Abandon de l'approche « gros pattern » (2026-04-01)

**Décision** : Abandon de l'approche consistant à créer de grands patterns
couvrant un espace maximal puis à matcher les pièces a posteriori par
superposition et suppression de postes hors-pièce.

**Justification** : La déduplication des sous-patterns issus de la
superposition fait perdre la sémantique souhaitée du pattern (disposition
intentionnelle des blocs par rapport aux murs, circulation pensée pour la
taille de pièce). Le travail d'adaptation a posteriori est trop important
et les résultats ne reflètent pas un aménagement conçu pour la pièce cible.

**Impact** : Le code de matching existant (`static_matcher.py`,
`matching_viewer.html`) reste dans le dépôt à titre de référence mais n'est
plus sur le chemin critique. L'approche est remplacée par D-36.

---

## D-36 · Pattern = pièce + standard (2026-04-01)

**Décision** : Un pattern est désormais associé à :
- Une **taille de pièce** (largeur × profondeur, saisie manuelle ou via boutons +/−)
- Une **géométrie de pièce** (décrite par un DSL de description de pièce, à créer)
- Un **standard d'aménagement** unique (AFNOR ADVICE, GROUP ou SITE)

L'éditeur de patterns affiche le standard appliqué en haut de la colonne gauche,
avec la taille de pièce associée. Un pattern est conçu *pour* une pièce précise,
pas adapté a posteriori.

**Justification** : Conception intentionnelle > adaptation mécanique. Un
aménageur pense la disposition des blocs en fonction de la pièce cible et de
ses contraintes normatives. Le pattern résultant porte cette intention.

**Impact** : Refonte de l'éditeur de patterns. Le format de stockage JSON
doit inclure `room_width_cm`, `room_depth_cm`, `room_geometry_dsl` et
`standard` (enum). Le DSL de pattern existant reste valide pour la
description des blocs.

---

## D-37 · Éditeur de patterns : vue pièce + vue catalogue (2026-04-01)

**Décision** : L'éditeur de patterns propose deux modes de visualisation :

1. **Vue pièce** : aménagement d'une pièce unique avec son standard.
   Trois cases à cocher (AFNOR ADVICE / GROUP / SITE) à gauche du zoom
   pour sélectionner le standard actif (un seul à la fois). Affichage
   des scores de circulation et du scoring en temps réel.

2. **Vue catalogue** : tous les patterns affichés sur une grande grille
   navigable (zoom + pan). Organisation matricielle :
   - Lignes : profondeur croissante (petite en haut, grande en bas)
   - Colonnes : largeur croissante (petite à gauche, grande à droite)
   - Filtres : bornes de taille, caractéristiques de pièce, standard

   Cette vue donne une vision globale de la couverture du catalogue.

**Justification** : La vue pièce permet la conception intentionnelle
(D-36). La vue catalogue permet d'identifier les lacunes et les
redondances dans le catalogue.

**Impact** : Refonte significative de `pattern_editor.html`. La vue
catalogue nécessite un canvas scrollable/zoomable avec rendu de
miniatures de tous les patterns.

---

## D-38 · DSL enrichi : attribut « collé au mur » — notation @S (2026-04-01)

**Décision** : Le DSL de pattern est enrichi d'un attribut « stick »
indiquant qu'un bloc se positionne naturellement collé à un mur ou une
fenêtre. Notation : `@S` suivi de la direction — `@SN`, `@SS`, `@SE`, `@SO`.

Plusieurs directions sont cumulables pour un bloc dans un coin :
`BLOC_4_FACE @SN @SO` (collé au mur nord et au mur ouest).

Dans l'éditeur, le bloc sélectionné dispose de 4 cases à cocher
(N, S, E, O) pour activer/désactiver les sticks dans chaque direction.

**Justification** : Information essentielle pour le matching et
l'adaptation. Lors du calage d'un pattern dans une pièce réelle, les
blocs marqués « stick » sont positionnés en premier, contre le mur
correspondant. Les autres blocs sont repositionnés par
homothétie/équilibrage.

**Impact** : Extension de `PATTERN_DSL_SPEC.md` (grammaire, JSON, exemples).
Mise à jour du parseur DSL et de l'éditeur (cases à cocher par bloc).
Le matching utilise cette information pour le calage initial.

---

## D-39 · Matching : plus grand pattern compatible (2026-04-01)

**Décision** : Le matching d'une pièce réelle sélectionne le pattern
dont la taille de pièce associée est la plus grande tout en restant
inférieure ou égale à la pièce cible. Les symétries (rotations, miroirs)
sont prises en compte. Si un poste tombe dans une zone interdite, il
peut être supprimé individuellement.

**Justification** : Le pattern le plus grand maximise le nombre de postes
tout en garantissant la faisabilité géométrique. La suppression unitaire
de postes en zone interdite (déjà implémentée dans l'approche précédente)
reste pertinente.

**Impact** : Le matching devient un tri + filtre sur les métadonnées du
catalogue (taille, standard, géométrie) plutôt qu'une superposition
géométrique exhaustive. Plus simple et plus rapide.

---

## D-40 · Adaptation pattern → pièce : calage murs + homothétie (2026-04-01)

**Décision** : L'adaptation d'un pattern candidat à une pièce réelle suit
deux étapes :
1. **Calage aux murs** : les blocs marqués « collé au mur » (D-38) sont
   positionnés contre les murs correspondants de la pièce cible.
2. **Homothétie** : les blocs intérieurs sont redistribués pour occuper
   l'espace disponible entre les blocs calés.

Cas simple (blocs collés uniquement N et E) : translation directe.
Cas complexe (blocs collés sur 3-4 murs) : maximisation du collage
aux murs, les blocs intérieurs absorbent l'espace résiduel.

**Justification** : Approche naturelle qui préserve l'intention
d'aménagement du pattern tout en s'adaptant aux dimensions exactes
de la pièce. L'homothétie maintient les proportions de circulation.

**Impact** : Nouveau module d'adaptation à créer. Dépend de D-38
(attribut « collé au mur »).

---

## D-41 · Visualisation circulation : largeur proportionnelle (2026-04-01)

**Décision** : La visualisation de la circulation dans l'éditeur et le
viewer n'utilise plus de couleurs mais la **largeur du tracé** pour
représenter la taille des zones de circulation. Les chemins sont des
courbes continues dont la largeur varie proportionnellement à la largeur
réelle de la zone : large quand la circulation est aisée, étroit quand
elle se resserre. Forme de flèches continues, pas de segments droits.

**Justification** : Plus intuitif qu'un code couleur. La variation de
largeur donne une lecture immédiate de la praticabilité des passages
sans nécessiter de légende.

**Impact** : Refonte du rendu des chemins dans le viewer. Le calcul
de `widths_per_cell` (déjà présent dans `circulation_analysis.py`)
alimente le rendu à largeur variable.

---

## D-42 · Analyse de couverture : catalogue vs plans réels (2026-04-01)

**Décision** : À partir des plans réels, produire une liste de descriptions
de pièces (dimensions, géométrie, caractéristiques) et mesurer le taux
de couverture du catalogue. Identifier les pièces pas ou mal couvertes
pour guider l'enrichissement du catalogue.

**Justification** : Le catalogue doit être représentatif des pièces réelles.
Sans cette analyse, on risque de construire des patterns pour des tailles
de pièces rares tout en laissant des tailles fréquentes non couvertes.

**Impact** : Script d'analyse à créer. Entrée : descriptions de pièces
issues des plans. Sortie : rapport de couverture (pièces couvertes,
partiellement couvertes, non couvertes) avec recommandations
d'enrichissement.

---

## D-43 · Interface de revue pièce par pièce (étage complet) (2026-04-01)

**Décision** : Lors du traitement d'un plan d'étage complet, produire
une interface de revue qui permet de naviguer de pièce en pièce
(previous/next), de visualiser la proposition d'aménagement, et
éventuellement de l'amender via l'éditeur de pièce avant export du
résultat final.

**Justification** : La validation humaine pièce par pièce est nécessaire
avant l'export. L'expert doit pouvoir ajuster rapidement un aménagement
sans reprendre tout le processus.

**Impact** : Nouvelle interface HTML. Réutilise les composants de l'éditeur
de pièce (vue pièce de D-37). L'export final agrège les aménagements
validés/amendés de toutes les pièces.

---

## D-44 · DSL de description de pièce (2026-04-01)

**Décision** : Un DSL texte décrit la géométrie d'une pièce indépendamment
du standard d'aménagement. Mots-clés : `PIECE`, `FEN`, `PORTE`, `BAIE`, `EXCL`.
Commentaires avec `--`. Spec complète dans `specs/ROOM_DSL_SPEC.md`.

Le DSL ne contient **pas** le standard — celui-ci est choisi séparément
dans l'éditeur ou le pipeline.

Les zones d'exclusion (`EXCL`) sont **déclaratives** : elles ne sont pas
prises en compte dans le pattern lui-même. C'est au moment du matching
que les superpositions éventuelles sont résolues (suppression unitaire
de postes en conflit).

**Justification** : Séparer la description géométrique de la pièce du
standard permet de réutiliser la même pièce avec différents standards.
Les zones d'exclusion (tuyaux, poteaux) sont rares et spécifiques à
chaque pièce réelle — les traiter au matching évite de polluer le
catalogue de patterns.

**Impact** : Nouveau module `room_dsl.py` (parseur + sérialiseur).
Spec dans `specs/ROOM_DSL_SPEC.md`. Le textarea "DSL Pièce" dans
l'éditeur utilise ce format. Bidirectionnel avec `RoomSpec` de
`room_model.py`.

## D-45 · Circulation : Dijkstra 8-connexe pondéré, chemins au centre des couloirs (2026-04-01)

**Décision** : Le calcul de circulation utilise un Dijkstra 8-connexe (pas BFS 4-connexe) avec coût pondéré par la distance aux obstacles (quadratique : `10 / (1 + distToWall²)`). Les chemins passent naturellement au centre des couloirs, éliminant les escaliers.

**Justification** : Un BFS 4-connexe produit des chemins en escalier (zigzag H-V) et longe les murs. Le Dijkstra 8-connexe avec pondération produit des chemins réalistes que les humains emprunteraient.

**Impact** : `computeCirculationInfo()` dans `pattern_editor.html`. Lissage Douglas-Peucker (tolérance 3.5px) + polylignes SVG `stroke-linejoin="round"`.

## D-46 · Circulation : coloration vert/ambre/rouge basée sur ES-06 (2026-04-01)

**Décision** : Les chemins de circulation sont colorés selon la largeur du corridor vs `passage_cm` (ES-06) du standard actif :
- Vert : largeur > passage_cm (confortable)
- Ambre : largeur = passage_cm (conforme mais juste)  
- Rouge : largeur < passage_cm (non conforme)

Propagation : une fois ambre/rouge sur un chemin, ça le reste jusqu'au poste (l'expérience utilisateur est dégradée dès la difficulté rencontrée).

**Justification** : Un aménagement bien optimisé a des corridors exactement au standard → ambre. Vert = marge supplémentaire. Rouge = non conforme.

**Impact** : `circColor()`, `circGrade()`, rendu des arêtes dans `_renderImpl()`. La largeur est mesurée sur une grille sans zones de recul (espace total entre emprises de blocs).

## D-47 · Scores en bleu, distances en jaune doré, pas de coloration par seuils (2026-04-01)

**Décision** : Les métriques de scoring (m²/poste, passage min) sont affichées en bleu uniforme (`var(--accent2)`). Les distances (blocs-blocs, blocs-murs) sont en jaune doré (`COLOR_GAP_LABEL`). Pas de vert/jaune/rouge par seuils de conformité.

**Justification** : La coloration par seuils ne fait pas sens pour l'utilisateur dans l'éditeur — les distances sont informatives, pas normatives. Exception : la circulation utilise vert/ambre/rouge car c'est un indicateur visuel de qualité du chemin.

## D-48 · Matching : pipeline sélection → miroir → suppression → homothétie → scoring (2026-04-01)

**Décision** : Le matching pièce réelle → catalogue suit un pipeline en 8 étapes :
1. Sélection des patterns dont l'emprise ≤ pièce cible
2. Filtrage par intersection non nulle (repère commun 0,0)
3. Miroir E-O pour couvrir porte gauche/droite
4. Suppression des postes en zone interdite
5. Calage murs (blocs sticky) + homothétie distances inter-blocs
6. Analyse circulation + confort
7. Sélection meilleure solution
8. Calcul du plus grand rectangle vide résiduel (m²) — critère d'optimisation

**Justification** : Approche systématique qui maximise la réutilisation du catalogue tout en adaptant à la géométrie spécifique de chaque pièce.

**Impact** : Nouveau module à implémenter. Le rectangle vide résiduel est un indicateur clé pour dire si la pièce peut être encore optimisée.

## D-49 · ES-04 = distance totale desk→extrémité zone (fauteuil inclus) (2026-04-01)

**Décision** : ES-04 (`passage_behind_one_row_cm`) est la distance totale du bord du desk au bord extérieur de la zone, incluant les 70cm de recul du fauteuil + le passage libre.
- AFNOR = 160cm (90 passage + 70 fauteuil)
- GROUP = 120cm (50 + 70)
- SITE = 100cm (30 + 70)

**Impact** : `spacing_config.py` docstring clarifiée. La vérification de conformité compare à cette valeur totale.

---

## D-50 · Convention de nommage des patterns (2026-04-01)

**Décision** : Format de nom = `{W}x{D}_{STANDARD}[_{k}O]_{n}` où :
- `{W}x{D}` = largeur × profondeur en cm
- `{STANDARD}` = AFNOR, GROUP ou SITE
- `{k}O` = nombre d'ouvertures si ≥ 2 (omis pour 1 ouverture, cas par défaut)
- `{n}` = incrément auto-compacté dans le groupe (même taille + standard + nb ouvertures)

Compactage : à chaque sauvegarde, les incréments sont renumérotés 1, 2, 3… sans trous dans le groupe.

**Justification** : Permet plusieurs patterns pour une même pièce (configurations de portes différentes, solutions alternatives) tout en gardant un nommage automatique, cohérent et lisible.
**Impact** : Le code de sauvegarde du catalogue doit générer le nom automatiquement et compacter les incréments existants du groupe.

---

## D-51 · Boucle retour matching → catalogue (backlog enrichissement) (2026-04-01)

**Décision** : Après le matching, un rapport qualifie chaque pièce mal couverte avec la raison (`NO_FIT`, `LOW_DENSITY`, `LOW_SCORE`) et génère un backlog de patterns à créer.
**Justification** : Permet un enrichissement ciblé du catalogue au lieu d'une création de patterns à l'aveugle.
**Impact** : L'Étape 4 (analyse de couverture) intègre ce rapport. Le backlog alimente directement l'éditeur de patterns.

---

## D-52 · Floor plan viewer : onglets intégrés dans la même app Flask (2026-04-01)

**Décision** : Le viewer de revue par étage et l'éditeur de catalogue cohabitent dans la même application Flask avec navigation par onglets (pas de multi-fenêtres).
**Justification** : État partagé en mémoire, pas de synchronisation inter-fenêtres, plus simple pour un prototype.
**Impact** : L'Étape 5 (interface de revue) est développée comme un onglet supplémentaire du studio existant. Les patterns candidats d'une pièce sont cliquables pour basculer vers l'onglet éditeur.

---

## D-53 · Import/export du catalogue de patterns (2026-04-01)

**Décision** : Export = téléchargement direct du JSON. Import = upload JSON avec merge (les patterns importés s'ajoutent ; en cas de conflit de nom, le nommage auto D-50 renumérotation s'applique).
**Justification** : Le catalogue est déjà en JSON, l'export est gratuit. Le merge évite de perdre le travail existant.
**Impact** : Deux boutons dans l'interface catalogue (Import / Export). La validation de schéma est nécessaire à l'import.

---

## D-54 · Pipeline de matching catalogue → pièce réelle (2026-04-01)

**Décision** : Module `catalogue_matcher.py` implémente le pipeline en 7 étapes :
1. Sélection (emprise ≤ pièce + front Pareto par dimensions)
2. Miroir E-O (orientations, sticks, types ortho)
3. Calage sticks + homothétie (interpolation linéaire entre ancres)
4. Suppression unitaire de postes en zone interdite
5. Scoring (circulation via `circulation_analysis.analyse()` + m²/poste)
6. Sélection du meilleur (n_desks max → grade circ → m²/poste min)
7. Rectangle vide résiduel (algorithme histogramme maximal)

Croisement 3 standards × pièce → point d'entrée `match_room()`.
**Justification** : Remplace l'ancien `matcher.py`/`static_matcher.py` (abandonné D-35). Pipeline déterministe, pas d'optimisation maison.
**Impact** : `catalogue_matcher.py` est autonome, importe `circulation_analysis`, `pattern_generator`, `room_model`, `spacing_config`.

---

## D-55 · Stratégie de peuplement du catalogue : du bas vers le haut (2026-04-01)

**Décision** : Le catalogue est construit en partant de la plus petite pièce viable pour chaque assemblage de blocs × standard. Chaque pattern est créé à la taille minimale de pièce qui accueille l'assemblage avec les espacements normatifs. Le front de Pareto du matching garantit que le pattern le plus grand qui rentre dans la pièce cible est automatiquement sélectionné. Le calage sticks + homothétie adapte le pattern aux pièces plus grandes que sa taille minimale.
**Justification** : Assure une couverture continue de l'espace des tailles de pièces avec un nombre minimal de patterns. Chaque pattern couvre toutes les pièces entre sa taille minimale et la taille minimale du pattern suivant (qui offre plus de postes).
**Impact** : Spec complète dans `specs/CATALOGUE_STRATEGY.md`. Le cycle enrichissement = matching → couverture → backlog → nouveaux patterns.

---

## D-56 · Mise à jour des distances standard SITE (2026-04-01)

**Décision** : Ajustement des espacements SITE pour refléter les pratiques terrain :
- ES-03 (accès poste seul → mur) : 80 → **90 cm** (70 CHR + 20 cm)
- ES-04 (passage derrière 1 rangée) : 100 → **140 cm** (70 CHR + 70 cm passage)
- ES-05 (passage 2 rangées dos à dos) : inchangé **160 cm** (70 + 20 + 70)
- ES-06 (passage inter-blocs côté écran) : 80 → **90 cm**
- ES-07 (enclavement) : 80 → **90 cm**
- ES-11 (séparation min entre blocs) : 80 → **90 cm**
**Justification** : Les valeurs précédentes (80 cm) étaient trop serrées pour un passage confortable côté écran et pour l'accès d'un poste seul dos à un mur.
**Impact** : Les tailles minimales de pièces pour les patterns SITE augmentent. Les patterns existants doivent être recalculés avec les nouvelles valeurs.

---

## D-57 · Extraction dsl_common.py : helpers partagés entre parseurs DSL (2026-04-01)

**Décision** : Création de `dsl_common.py` qui centralise `DSLError` (classe d'erreur de base), `strip_comment` (suppression commentaires `--`) et `parse_int` (conversion token → entier). `pattern_dsl.py` importe `DSLError` et `strip_comment` depuis ce module. `room_dsl.py` importe les trois et `RoomDSLError` hérite désormais de `DSLError` (au lieu de `Exception`).
**Justification** : Élimination de la duplication entre les deux parseurs DSL. La classe d'erreur commune permet un `except DSLError` unique pour attraper les erreurs des deux DSL.
**Impact** : Aucune rupture d'API — les imports existants (`from pattern_dsl import DSLError`, `from room_dsl import RoomDSLError`) restent fonctionnels. `RoomDSLError` est maintenant attrapable via `except DSLError`.

## D-58 · Floor Plan réutilise le canvas éditeur (2026-04-02)

**Décision** : L'onglet Floor Plan réutilise le même canvas SVG et les mêmes fonctions de rendu (`_renderImpl`) que l'éditeur, par déplacement DOM du canvas entre onglets. Les boutons d'édition (rotation, déplacement, suppression) sont masqués en mode Floor Plan. La sélection de blocs par clic et clavier est désactivée.
**Justification** : Garantir un rendu strictement identique (grille, règle, zones, desks, distances, circulation) entre éditeur et Floor Plan, sans duplication de code.
**Impact** : `fpRenderSvg` charge le pattern adapté dans `state` et appelle `render()`. Le canvas est déplacé dans `fp-canvas-wrap` quand Floor Plan est actif, remis dans `canvas-col` sinon.

## D-59 · Extraction renderBlockZones + renderBlockDesks (2026-04-02)

**Décision** : Extraction de deux fonctions partagées entre `_renderImpl` et `renderPatternMiniSvg` : `renderBlockZones(elements, bx, by, bw, bh, blockType, orientation, faces, scale, strokeW)` pour le rendu des zones nsup+candidate, et `renderBlockDesks(elements, bx, by, blockType, orientation, scale, startIndex)` pour le rendu des desks.
**Justification** : Élimination de ~130 lignes de code dupliqué entre les deux fonctions de rendu. Le paramètre `strokeW` permet 0.5 (éditeur) vs 0.3 (miniatures catalogue). Fix du bug de la zone sud candidate dans `renderPatternMiniSvg` (largeur/hauteur inversées).
**Impact** : Les fonctions sont définies avant `renderPatternMiniSvg` et utilisées par les deux rendus. Aucun changement visuel sauf correction du bug zone sud.

## D-60 · Règles d'affichage des distances V-01/V-02 (2026-04-02)

**Décision** : Formalisation des règles d'affichage des distances dans l'éditeur (ajoutées dans `SRS_placement.md`) : V-01 (inter-blocs) = distance affichée ssi plus proche voisin ET chevauchement desk sur l'axe perpendiculaire ; V-02 (blocs-murs) = distance au mur sauf si un autre bloc (emprise visuelle desk+zones) est entre ce bloc et le mur ; V-03 = scores en bleu, distances en jaune doré.
**Justification** : Les distances entre blocs non adjacents (ex: 540cm entre rangées) polluaient la lecture. La définition formelle garantit la cohérence entre éditeur, catalogue et floor plan.
**Impact** : Code mis à jour dans `_renderImpl` et `renderPatternMiniSvg`.

