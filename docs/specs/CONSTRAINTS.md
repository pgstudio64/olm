# Catalogue des contraintes de placement

> **Principe** : l'objectif de l'algorithme est de **maximiser le nombre de postes**
> placés dans une pièce. La contrainte AFNOR NF X35-102 de 8 m²/poste en open space
> n'est **pas** un hard constraint — elle est inaccessible légalement dans la majorité
> des contextes clients et son respect reste une décision humaine a posteriori.
> La surface par poste est affichée dans le rapport à titre informatif (IN-01).
>
> Les hard constraints sont exclusivement celles relatives aux dégagements physiques,
> à la circulation, à la sécurité et à l'ergonomie.
>
> En cas de divergence entre INRS ED950 et AFNOR NF X35-102, l'AFNOR fait foi.

---

## 1. Contraintes physiques et sécurité — PS (universelles)

Ces contraintes s'appliquent quel que soit le standard d'aménagement.

| Code  | Description                                                       | Valeur             | Source            |
|-------|-------------------------------------------------------------------|--------------------|-------------------|
| PS-01 | Non-superposition des postes                                      | —                  | Physique          |
| PS-02 | Postes entièrement dans la pièce                                  | —                  | Physique          |
| PS-03 | Exclusion des zones non utilisables (poteaux, gaines…)            | —                  | Physique          |
| PS-04 | Largeur couloir principal (accessibilité PMR)                     | ≥ 140 cm           | Sécurité          |
| PS-05 | Passage civière                                                   | ≥ 90 cm × 200 cm  | INRS              |
| PS-06 | Distance maximale vers une sortie                                 | ≤ 30 m             | Sécurité incendie |
| PS-07 | Chemin continu praticable depuis l'entrée vers chaque poste       | —                  | Sécurité          |
| PS-08 | Chemin continu depuis chaque poste vers une sortie                | —                  | Sécurité incendie |
| PS-09 | Non-chevauchement des emprises de chaise entre postes voisins     | —                  | Physique          |

---

## 2. Contraintes d'espacement par standard d'aménagement — ES

Ces contraintes varient selon le standard d'aménagement appliqué. La colonne
AFNOR ADVICE contient les valeurs de référence (NF X35-102). Les colonnes GROUP
et SITE sont à renseigner avec les valeurs spécifiques.

### Accès aux postes

| Code  | Description                                              | AFNOR ADVICE | GROUP | SITE | Source           |
|-------|----------------------------------------------------------|-------------|-------|------|------------------|
| ES-01 | Débattement chaise (composante de base)                  | 70 cm       | 70 cm     | 70 cm    | AFNOR NF X35-102 |
| ES-02 | Accès frontal (s'asseoir / se lever)                     | 60 cm       | 60 cm     | 60 cm    | Ergonomie        |
| ES-03 | Accès poste seul dos à un mur (CHR + marge)              | 100 cm      | 90 cm     | 90 cm    | AFNOR NF X35-102 |
| ES-04 | Passage derrière 1 rangée occupée (CHR + PAS)            | 160 cm      | 120 cm    | 140 cm    | AFNOR NF X35-102 |
| ES-05 | Passage entre 2 rangées dos à dos (CHR + gap + CHR)      | 230 cm      | 180 cm    | 160 cm    | AFNOR NF X35-102 |
| ES-06 | Passage entre deux blocs distincts (inter-blocs)         | 90 cm       | 90 cm     | 90 cm    | AFNOR NF X35-102 |
| ES-07 | Aucun poste enclavé sans passage suffisant               | 90 cm       | 90 cm     | 90 cm    | Accessibilité    |

> **Décomposition AFNOR** : ES-04 = ES-01 + ES-06 (70 + 90 = 160 cm).
> ES-05 = ES-01 + ES-06 + ES-01 (70 + 90 + 70 = 230 cm).
> **Décomposition SITE** : ES-03 = CHR + 20 (70 + 20 = 90 cm).
> ES-04 = CHR + 70 passage (70 + 70 = 140 cm). ES-05 = CHR + 20 + CHR (70 + 20 + 70 = 160 cm).

### Portes et entrées

| Code  | Description                                              | AFNOR ADVICE | GROUP  | SITE   | Source   |
|-------|----------------------------------------------------------|-------------|--------|--------|----------|
| ES-08 | Zone libre devant porte (profondeur d'exclusion)         | 180 cm      | 180 cm | 120 cm | Sécurité |

### Distances au mur

| Code  | Description                                              | AFNOR ADVICE | GROUP | SITE | Source    |
|-------|----------------------------------------------------------|-------------|-------|------|-----------|
| ES-09 | Distance bord latéral de table → mur                     | 20 cm       | 10 cm     | 0 cm    | Ergonomie |

### Blocs

| Code  | Description                                              | AFNOR ADVICE | GROUP | SITE | Source           |
|-------|----------------------------------------------------------|-------------|-------|------|------------------|
| ES-10 | Taille maximale d'un bloc                                | 4 postes    | 6 postes     | 6 postes    | AFNOR NF X35-102 |
| ES-11 | Séparation minimale entre blocs distincts                | 90 cm       | 90 cm     | 90 cm    | AFNOR NF X35-102 |

> **Note ES-10** : les blocs de 6 postes face à face (BLOC_6_FACE) génèrent
> des perturbations verbales en diagonale pour les postes du milieu. BLOC_6_FACE
> est exclu du catalogue par défaut, réintroductible en dérogatoire.

---

## 3. Contraintes de modélisation — MO

Règles internes au système, non normatives.

| Code  | Description                                                   | Valeur                        | Source        |
|-------|---------------------------------------------------------------|-------------------------------|---------------|
| MO-01 | Orientation valide (multiples de 90°)                         | {0°, 90°, 180°, 270°}         | Modélisation  |
| MO-02 | Alignement sur grille modulaire                               | Multiple du pas de grille     | Modélisation  |
| MO-03 | Alignement en rangée (bords partagés colinéaires)             | —                             | Esthétique    |
| MO-04 | Espacement uniforme entre tables d'une même rangée            | = constante de rangée         | Esthétique    |
| MO-05 | Profondeur de rangée homogène (face à face)                   | P₁ + espace central = cste    | Esthétique    |
| MO-06 | Distance bord à bord, postes face à face                      | ≥ 5 cm                        | Modélisation  |
| MO-07 | Chaque table appartient à exactement un bloc                  | —                             | Modélisation  |
| MO-08 | Tables d'un même bloc géographiquement contiguës              | —                             | Organisation  |
| MO-09 | Forme de bloc dans le catalogue autorisé                      | cf. BLOCS_SPEC.md             | Modélisation  |
| MO-10 | Espacement intra-bloc (cohérence de groupe)                   | ≤ 5 cm                        | Esthétique    |
| MO-11 | Non-collision des chaises adjacentes au recul simultané       | —                             | Ergonomie     |
| MO-12 | Distance table → fenêtre (ouverture libre)                    | Ouverture non bloquée         | Exploitation  |

---

## 4. Soft constraints — Confort visuel — SV

| Code  | Description                                     | Score    |
|-------|-------------------------------------------------|----------|
| SV-01 | Écran face aux fenêtres (éblouissement)         | −20 pts  |
| SV-02 | Écran dos aux fenêtres (contre-jour réduit)     | +20 pts  |
| SV-03 | Vue sur l'extérieur depuis le poste             | +10 pts  |
| SV-04 | Dos à une porte ouverte                         | −30 pts  |
| SV-05 | Face à une porte (vue de contrôle)              | +10 pts  |

---

## 5. Soft constraints — Interaction sociale — SS

| Code  | Description                                            | Score   |
|-------|--------------------------------------------------------|---------|
| SS-01 | Visibilité des collègues adjacents                     | +10 pts |
| SS-02 | Angle de vue < 90° entre postes voisins                | +8 pts  |
| SS-03 | Regroupement par équipe / projet                       | +15 pts |
| SS-04 | Accès zone collaborative ≤ 7 m                         | +10 pts |

---

## 6. Soft constraints — Esthétique & Cohérence spatiale — SE

| Code  | Description                                                                  | Score   |
|-------|------------------------------------------------------------------------------|---------|
| SE-01 | Symétrie de disposition dans une rangée (axe explicitement modélisé)         | +5 pts  |
| SE-02 | Absence de poste solitaire isolé (distance ≤ 200 cm d'au moins une table)   | +8 pts  |

---

## 7. Indicateur informatif (non bloquant) — IN

| Code  | Description                    | Valeur      | Source           | Rôle                                  |
|-------|--------------------------------|-------------|------------------|---------------------------------------|
| IN-01 | Surface par poste open space   | 8 m²/poste  | AFNOR NF X35-102 | Affiché dans le rapport, non appliqué |

---

## Dimensions de référence du poste

| Élément               | Valeur          | Source           |
|-----------------------|-----------------|------------------|
| Bureau standard       | 180 cm × 80 cm  | AFNOR NF X35-102 |
| Distance interpersonnelle latérale | 140 cm min / 160 cm rec | AFNOR NF X35-102 |

---

## Table de correspondance ancien → nouveau

| Ancien | Nouveau | Ancien  | Nouveau | Ancien  | Nouveau |
|--------|---------|---------|---------|---------|---------|
| HC-01  | PS-01   | HC-15   | MO-01   | SC-V01  | SV-01   |
| HC-02  | PS-02   | HC-16   | MO-02   | SC-V02  | SV-02   |
| HC-03  | PS-03   | HC-17   | MO-03   | SC-V03  | SV-03   |
| HC-04  | PS-04   | HC-18   | MO-04   | SC-V04  | SV-04   |
| HC-06  | PS-05   | HC-19   | MO-05   | SC-V05  | SV-05   |
| HC-08  | PS-06   | HC-20   | MO-06   | SC-S01  | SS-01   |
| HC-12  | PS-07   | HC-26   | MO-07   | SC-S02  | SS-02   |
| HC-13  | PS-08   | HC-27   | MO-08   | SC-S03  | SS-03   |
| HC-24  | PS-09   | HC-29   | MO-09   | SC-S04  | SS-04   |
| HC-10  | ES-01   | HC-30   | MO-10   | SC-E01  | SE-01   |
| HC-09  | ES-02   | HC-11   | MO-11   | SC-E02  | SE-02   |
| HC-05a | ES-03   | HC-23   | MO-12   | INFO-01 | IN-01   |
| HC-05b | ES-04   |         |         |         |         |
| HC-05c | ES-05   |         |         |         |         |
| HC-05d | ES-06   |         |         |         |         |
| HC-14  | ES-07   |         |         |         |         |
| HC-07  | ES-08   |         |         |         |         |
| HC-22  | ES-09   |         |         |         |         |
| HC-28  | ES-10   |         |         |         |         |
| HC-25  | ES-11   |         |         |         |         |
