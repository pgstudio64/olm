# Spécification des blocs canoniques — solver_lab

> **Mise à jour** : 2026-03-28 — Aligné avec D-25 (langage formel), D-26 (repère NW→SE)
> **Source de vérité** : ce fichier + Decisions.md D-25/D-26

---

## Repère (D-26)

- Origine (0,0) = coin **Nord-Ouest** de l'emprise fixe
- x positif → **Est**, y positif → **Sud**
- Convention cohérente avec numpy/images (row 0 = haut = nord)
- Orientation d'un poste = direction du regard de l'utilisateur

---

## Constantes dimensionnelles (D-25)

| Symbole | Constante code | Valeur | Description |
|---|---|---|---|
| W | `DESK_W_CM` | 80 cm | Largeur du poste dans l'axe du regard |
| D | `DESK_D_CM` | 180 cm | Profondeur du poste perpendiculaire au regard |
| CHR | `CHAIR_CLEARANCE_CM` | 70 cm | Zone fixe — débattement chaise (ES-01) |
| PAS | `PASSAGE_CM` | 90 cm | Zone candidate — passage (ES-06) |

---

## Modèle de dette de circulation (D-16)

Chaque bloc embarque des zones autour de son emprise physique :

| Type | Couleur | Nature | Exemple |
|---|---|---|---|
| Zone fixe | Orange `#FAC775` | Non superposable, non supprimable | Débattement chaise CHR=70 cm |
| Zone candidate | Bleu `#B5D4F4` | Supprimable si l'analyse de flux confirme la redondance | Passage PAS=90 cm |

Les zones candidates sont orientées par face (N, S, E, W). Après analyse de
circulation (Phase 2b), les zones inutiles sont supprimées et les blocs compactés.

Les zones fixes (orange) sont mappées en `CellType.CORRIDOR` dans la grille
synthétique — elles sont franchissables physiquement (D-22).

---

## Blocs canoniques

Tous les blocs ci-dessous utilisent la convention **regard=EST** à orientation 0°.
Les postes sont numérotés de haut (nord, y=0) en bas (sud, y croissant).

### BLOC_1 — 1 poste seul

```
B1 : regard=EST, pos=(0, 0)
zones :
  W : type=fixe,      rect=[(-CHR, 0),       (0,         D)  ]
      type=candidate, rect=[(-CHR-PAS30, 0),  (-CHR,      D)  ]
  N : type=candidate, rect=[(0, -PAS),        (W,         0)  ]
  S : type=candidate, rect=[(0,    D),        (W,      D+PAS) ]
```

| Mesure | Valeur |
|---|---|
| Emprise physique | W × D = 80 × 180 cm |
| Emprise fixe (avec CHR) | (CHR+W) × D = 150 × 180 cm |
| Emprise totale (avec PAS) | (PAS30+CHR+W) × (PAS+D+PAS) = 180 × 360 cm |

> PAS30 = 30 cm (ES-03, accès poste seul). Pas de zone candidate E (côté écran).

---

### BLOC_2_FACE — 2 postes face à face

```
B1 : regard=EST,   pos=(0, 0)
B2 : regard=OUEST, pos=(W, 0)
zones :
  W : type=fixe,      rect=[(-CHR,    0), (0,      D)  ]
  E : type=fixe,      rect=[(2W,      0), (2W+CHR, D)  ]
  N : type=candidate, rect=[(0,    -PAS), (2W,     0)  ]
  S : type=candidate, rect=[(0,       D), (2W,  D+PAS) ]
```

| Mesure | Valeur |
|---|---|
| Emprise physique | 2W × D = 160 × 180 cm |
| Emprise fixe (avec CHR) | (CHR+2W+CHR) × D = 300 × 180 cm |
| Emprise totale (avec PAS) | 300 × (PAS+D+PAS) = 300 × 360 cm |

---

### BLOC_3_COTE — 3 postes côte à côte (colonne unique)

```
B1 : regard=EST, pos=(0, 0)
B2 : regard=EST, pos=(0, D)
B3 : regard=EST, pos=(0, 2D)
zones :
  W : type=fixe,      rect=[(-CHR, 0),    (0,      3D)  ]
  E : absent
  N : type=candidate, rect=[(0, -PAS),    (W,       0)  ]
  S : type=candidate, rect=[(0,   3D),    (W,   3D+PAS) ]
```

| Mesure | Valeur |
|---|---|
| Emprise physique | W × 3D = 80 × 540 cm |
| Emprise fixe (avec CHR) | (CHR+W) × 3D = 150 × 540 cm |
| Emprise totale (avec PAS) | (CHR+W) × (PAS+3D+PAS) = 150 × 720 cm |

> Bloc **asymétrique** (face E absente ≠ face W fixe) — 4 orientations possibles.
> Pas de zone candidate E (côté écran).

---

### BLOC_4_FACE — 4 postes (2×2 dos à dos)

```
B1 : regard=EST,   pos=(0,  0)    ← poste NW
B2 : regard=OUEST, pos=(W,  0)    ← poste NE
B3 : regard=EST,   pos=(0,  D)    ← poste SW
B4 : regard=OUEST, pos=(W,  D)    ← poste SE
zones :
  W : type=fixe,      rect=[(-CHR,    0), (0,       2D)  ]
  E : type=fixe,      rect=[(2W,      0), (2W+CHR,  2D)  ]
  N : type=candidate, rect=[(0,    -PAS), (2W,       0)  ]
  S : type=candidate, rect=[(0,      2D), (2W,   2D+PAS) ]
```

| Mesure | Valeur |
|---|---|
| Emprise physique | 2W × 2D = 160 × 360 cm |
| Emprise fixe (avec CHR) | (CHR+2W+CHR) × 2D = 300 × 360 cm |
| Emprise totale (avec PAS) | 300 × (PAS+2D+PAS) = 300 × 540 cm |

Taille maximale d'îlot conforme AFNOR NF X35-102 (ES-10 : ≤ 4 postes).

---

### BLOC_6_FACE — 6 postes (3×2 dos à dos) — DÉROGATOIRE

```
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
```

| Mesure | Valeur |
|---|---|
| Emprise physique | 2W × 3D = 160 × 540 cm |
| Emprise fixe (avec CHR) | 300 × 540 cm |
| Emprise totale (avec PAS) | 300 × 720 cm |

> Non conforme ES-10 (AFNOR : perturbations verbales en diagonale).
> Exclu du catalogue par défaut. Réintroduction en cas dérogatoire uniquement.

---

## Tableau récapitulatif

| Bloc | Postes | Physique (EO×NS) | Fixe (avec CHR) | Totale (avec PAS) | ES-10 |
|---|---|---|---|---|---|
| BLOC_1 | 1 | 80 × 180 cm | 150 × 180 cm | 180 × 360 cm | ✅ |
| BLOC_2_FACE | 2 | 160 × 180 cm | 300 × 180 cm | 300 × 360 cm | ✅ |
| BLOC_3_COTE | 3 | 80 × 540 cm | 150 × 540 cm | 150 × 720 cm | ✅ |
| BLOC_4_FACE | 4 | 160 × 360 cm | 300 × 360 cm | 300 × 540 cm | ✅ |
| BLOC_6_FACE | 6 | 160 × 540 cm | 300 × 540 cm | 300 × 720 cm | ❌ |

---

## Formules d'emprise (génériques)

```
Pour tout bloc :
  min_eo   = CHR + eo_cm + CHR           = 2×CHR + eo_cm
  total_eo = CHR + PAS + eo_cm + PAS + CHR   (zones latérales non présentes actuellement)
  min_ns   = ns_cm
  total_ns = PAS + ns_cm + PAS           = ns_cm + 2×PAS

Pour un pattern compose_row([A, B]) :
  physical_eo = A.eo_cm + B.eo_cm
  physical_ns = max(A.ns_cm, B.ns_cm)
  min_eo      = 2×CHR + physical_eo
  total_eo    = 2×CHR + 2×PAS + physical_eo
  min_ns      = physical_ns
  total_ns    = physical_ns + 2×PAS
```

---

## FaceZone — structure de données

```python
@dataclass
class FaceZone:
    non_superposable_cm: int = 0    # zone fixe (CHR)
    candidate_cm: int = 0           # zone candidate (PAS)

@dataclass
class FaceCandidates:
    north: FaceZone
    south: FaceZone
    east:  FaceZone
    west:  FaceZone
```

Les blocs symétriques (BLOC_2_FACE, BLOC_4_FACE, BLOC_6_FACE) ont N=S et E=W.
Les blocs asymétriques (BLOC_1, BLOC_2_COTE, BLOC_3_COTE) ont 4 faces distinctes.

---

## Patterns — descriptions formelles (D-25)

Repère : origine (0,0) = coin Nord-Ouest de l'emprise fixe. x→EST, y→SUD.
Distance canonique entre deux blocs indépendants = 2×PAS.

Patterns simple rangée :

```
P_B4 :
  BLOC_4_FACE_A : bloc=BLOC_4_FACE, orientation=0°, ref=origine

P_B4_B2F :
  BLOC_4_FACE_A  : bloc=BLOC_4_FACE,      orientation=0°, ref=origine
  BLOC_2F_A : bloc=BLOC_2_FACE, orientation=0°, ref=BLOC_4_FACE_A, axe=EST, dist=2×PAS

P_B6 :
  BLOC_6_FACE_A : bloc=BLOC_6_FACE, orientation=0°, ref=origine

P_B6_B2F :
  BLOC_6_FACE_A  : bloc=BLOC_6_FACE,      orientation=0°, ref=origine
  BLOC_2F_A : bloc=BLOC_2_FACE, orientation=0°, ref=BLOC_6_FACE_A, axe=EST, dist=2×PAS
```

Patterns double rangée :

```
P_B4_B4 :
  BLOC_4_FACE_A : bloc=BLOC_4_FACE, orientation=0°, ref=origine
  BLOC_4_FACE_B : bloc=BLOC_4_FACE, orientation=0°, ref=BLOC_4_FACE_A, axe=SUD, dist=2×PAS

P_B4_B4B2F :
  BLOC_4_FACE_A  : bloc=BLOC_4_FACE,      orientation=0°, ref=origine
  BLOC_4_FACE_B  : bloc=BLOC_4_FACE,      orientation=0°, ref=BLOC_4_FACE_A,  axe=SUD, dist=2×PAS
  BLOC_2F_A : bloc=BLOC_2_FACE, orientation=0°, ref=BLOC_4_FACE_B,  axe=EST, dist=2×PAS

P_B4B2F_B4B2F :
  BLOC_4_FACE_A  : bloc=BLOC_4_FACE,      orientation=0°, ref=origine
  BLOC_2F_A : bloc=BLOC_2_FACE, orientation=0°, ref=BLOC_4_FACE_A,  axe=EST, dist=2×PAS
  BLOC_4_FACE_B  : bloc=BLOC_4_FACE,      orientation=0°, ref=BLOC_4_FACE_A,  axe=SUD, dist=2×PAS
  BLOC_2F_B : bloc=BLOC_2_FACE, orientation=0°, ref=BLOC_4_FACE_B,  axe=EST, dist=2×PAS

P_B2F_B2F :
  BLOC_2F_A : bloc=BLOC_2_FACE, orientation=0°, ref=origine
  BLOC_2F_B : bloc=BLOC_2_FACE, orientation=0°, ref=BLOC_2F_A, axe=SUD, dist=2×PAS

P_B2F_B4 :
  BLOC_2F_A : bloc=BLOC_2_FACE, orientation=0°, ref=origine
  BLOC_4_FACE_A  : bloc=BLOC_4_FACE,      orientation=0°, ref=BLOC_2F_A, axe=SUD, dist=2×PAS

P_B4B2F_B4 :
  BLOC_4_FACE_A  : bloc=BLOC_4_FACE,      orientation=0°, ref=origine
  BLOC_2F_A : bloc=BLOC_2_FACE, orientation=0°, ref=BLOC_4_FACE_A,  axe=EST, dist=2×PAS
  BLOC_4_FACE_B  : bloc=BLOC_4_FACE,      orientation=0°, ref=BLOC_4_FACE_A,  axe=SUD, dist=2×PAS
```

Catalogue complet :
- `PATTERNS` : 4 patterns simple rangée
- `PATTERNS_ALL` : 8 = base + rotations 90°
- `DOUBLE_ROW_PATTERNS` : 6 patterns double rangée
- `DOUBLE_ROW_PATTERNS_ALL` : ~18 = base + rotations 90° + miroirs EO
