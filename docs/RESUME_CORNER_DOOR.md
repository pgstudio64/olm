# Prompt de reprise — Porte de coin attribuée à la mauvaise face

## Contexte

Session du 2026-05-14, D-197 à D-198c.

## Problème

Cas concret : pièce preprocessed, corridor_face=south, rect [740,1126,939,1299].
Une porte physiquement dans le mur SUD (près du coin SE) est détectée sur la face EAST par le ray-cast (les rays horizontaux captent l'arc mais pas les rays verticaux → "no_arc_hits" sur south).
Le diagnostic montre : EAST OK doors=1, SOUTH/NORTH/WEST REJECTED=no_arc_hits.

## Ce qui est livré (v0.4.81, stable)

- D-197 : fix offset canonique per-face flip (canonical_io.js, canonical.py, 5 autres sites)
- D-197b : corner dedup (si 2 faces détectent → garde le meilleur wall_fill_ratio) + max door width 120cm
- Le corner dedup ne peut PAS aider ici car une seule face détecte la porte

## Ce qui a été tenté et retiré (3 tentatives, 3 reverts)

1. **D-198** (_scan_wall_gaps dans comb_detection.py) : scannait les 4 murs au bbox edge pour trouver les gaps, puis réattribuait. PROBLÈME : le bbox edge de la face détectée (east) ne coïncide pas avec le vrai mur (wall_px=985 vs bbox x1=940) → le scan trouvait du vide partout → faux gaps → pas de reassign.

2. **D-198b** : retiré le check "current face has gap" pour forcer le reassign. PROBLÈME : trop agressif, plein de portes correctes réattribuées à tort → régression massive.

3. **D-198c** (_reassign_corner_door_from_opening dans extract.py) : croisait portes et openings déjà détectées. Si porte au coin + opening sur face adjacente au même coin → réattribuer. PROBLÈME : consommait l'ouverture (la retirait de la liste) mais le door reassign ne prenait pas toujours effet (probablement un écart de dimensions entre les deux call sites extract_room_features et le pipeline preprocessed). Résultat : ouverture disparue, porte inchangée.

## Piste recommandée (non explorée)

L'ouverture (opening) est la clé — c'est le seul indicateur fiable de quel mur a le trou. Mais l'approche D-198c a un défaut structurel : elle consomme l'ouverture avant de confirmer que le reassign a fonctionné. Il faudrait soit :

- **(a)** Ne consommer l'ouverture qu'APRÈS avoir confirmé le reassign dans le résultat final
- **(b)** Travailler dans un seul endroit du pipeline (pas 2 call sites avec des dimensions différentes)
- **(c)** Approche différente : au lieu de réattribuer la porte, simplement SUPPRIMER la porte sur east et CONVERTIR l'ouverture south en porte (en lui ajoutant les attributs arc : hinge_side, opens_inward). C'est plus simple et évite le problème de réattribution.

## Fichiers clés

- `olm/ingestion/comb_detection.py` : `_detect_doors_on_face` (détection arc), `expand_door_arcs` (pipeline phase 3), `_dedup_corner_doors`
- `olm/ingestion/extract.py` : `extract_room_features` (rescan), pipeline preprocessed (~ligne 1390-1430), `_filter_openings_overlapping_doors`
- `olm/core/detection_config.py` : max_door_width_cm=120, min_door_width_cm=55

## Diagnostic de référence

```
=== EAST === OK doors=1
rect: [740,1126,939,1299] face_len: 173 door_width: 43
tolerance: 0.35, seeds: none, total_hits: 94
wall_px: 985, wall_hits: 66
arc_hits: 20, arc_span: 39, range: [1261,1299]

=== SOUTH === REJECTED=no_arc_hits
=== NORTH === REJECTED=no_arc_hits
=== WEST === REJECTED=no_arc_hits
```
