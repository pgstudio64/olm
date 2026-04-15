# SRS Placement — solver_lab

## Objectif

Développer et valider un algorithme CP-SAT (OR-Tools) pour le placement optimal
de postes de travail dans une pièce, avant intégration dans le système OLO complet.

## Entrées

- Géométrie de la pièce : dimensions (L × l), obstacles, marges
- Éléments architecturaux : fenêtres (position + largeur), portes (position + sens ouverture)
- Postes à placer : dimensions, orientation préférée, équipe d'appartenance
- Paramètres de résolution : time_limit, stratégie de blocs, pondérations des scores

## Sorties

- Liste de postes placés : position (x, y), orientation, score individuel
- Score global de la solution
- Métriques : nb postes, m²/poste, taux d'occupation, violations soft
- Rapport HTML + plan ASCII

## Exigences fonctionnelles

| ID | Exigence |
|----|----------|
| F-01 | Placer le maximum de postes dans la pièce |
| F-02 | Respecter toutes les hard constraints (ES-*, PS-*) |
| F-03 | Maximiser le score de confort (soft constraints) |
| F-04 | Priorité aux blocs de 4, puis 2, puis 1 |
| F-05 | Orientation préférentielle : dos aux fenêtres |
| F-06 | Rapport HTML généré après chaque résolution |
| F-07 | Plan ASCII affiché en terminal |
| F-08 | Scénarios JSON rechargeables sans redémarrage |

## Exigences de visualisation

| ID | Exigence |
|----|----------|
| V-01 | **Distances inter-blocs** : une distance est affichée entre deux blocs si et seulement si (1) l'un est le plus proche voisin de l'autre dans une direction cardinale (droite ou bas), et (2) les emprises physiques des desks des deux blocs se chevauchent sur l'axe perpendiculaire à la direction (chevauchement EO pour des voisins verticaux, chevauchement NS pour des voisins horizontaux). Les zones de circulation/recul ne participent pas au test de chevauchement. |
| V-02 | **Distances blocs-murs** : pour chaque bloc, afficher la distance au mur le plus proche dans chaque direction cardinale, sauf si un autre bloc est plus proche du mur dans cette direction (déduplication). |
| V-03 | **Couleurs** : scores en bleu (`#5090c0`), distances en jaune doré (`COLOR_GAP_LABEL`), jamais de coloration vert/jaune/rouge par seuils (exception : circulation). |

## Exigences non fonctionnelles

| ID | Exigence |
|----|----------|
| NF-01 | Temps de résolution ≤ 30 s pour une pièce ≤ 100 m² |
| NF-02 | 100 % local, pas de dépendance réseau |
| NF-03 | Python 3.10+, compatible Anaconda Windows |
