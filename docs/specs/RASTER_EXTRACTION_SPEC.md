# RASTER_EXTRACTION_SPEC — Extraction automatique de pièces depuis un plan raster

Version 1.0 — 2026-04-03

## Objectif

Extraire automatiquement, depuis une image raster de plan d'étage, la liste des
pièces bureau avec leurs dimensions, positions pixel, ouvertures (portes, baies),
obstacles intérieurs et zones d'exclusion — sans intervention du LLM Vision.

Le résultat est directement exploitable par le pipeline OLO : filigrane (overlay
raster), matching catalogue, export final.

---

## 1. Hypothèses sur le plan d'entrée

| Hypothèse | Justification |
|---|---|
| Les murs sont rectilignes (horizontaux ou verticaux) | Plans architecturaux standards |
| Les pièces bureau contiennent le nombre `14` | Convention de numérotation métier constante entre bâtiments |
| Les portes sont représentées par un arc de cercle (quart de cercle) | Convention architecturale universelle |
| Les fenêtres ne sont pas identifiables par leur représentation graphique | Varie selon les bâtiments — détection indirecte |
| Les surfaces en m² peuvent être inscrites dans les pièces | Optionnel — exploité si présent |
| La résolution est suffisante (≥ 150 DPI) | Lisibilité des textes et traits |

---

## 2. Pipeline global

```
Raster (PNG / JPEG / PDF rasterisé)
  │
  ▼
ÉTAPE 1 — OCR
  │  Détecter tous les textes + bounding boxes pixel
  │  → inventaire des pièces ("14"), surfaces ("15.2"), labels ("B.4.01")
  │
  ▼
ÉTAPE 2 — Nettoyage
  │  Effacer les textes détectés de l'image
  │  → image sans texte (traits de murs uniquement)
  │
  ▼
ÉTAPE 3 — Binarisation
  │  Seuillage adaptatif → image N&B (mur = noir, intérieur = blanc)
  │
  ▼
ÉTAPE 4 — Ray-cast par pièce
  │  Depuis le centroïde de chaque "14" :
  │  → bbox_px, ouvertures, obstacles
  │
  ▼
ÉTAPE 5 — Enrichissement
  │  Association labels / surfaces aux pièces
  │  Dérivation faces extérieures depuis la classification murale
  │
  ▼
ÉTAPE 6 — Conversion en JSON OLO
  │  Application de l'échelle (px → cm)
  │  → rooms[] conforme à VISION_LLM_IO_SPEC §3
  │
  ▼
Sortie : JSON OLO + bbox_px par pièce
```

---

## 3. Étape 1 — OCR (détection de texte)

### 3.1 Outil

`easyocr` (Python, pip install, sans dépendance système) ou `pytesseract`
(nécessite Tesseract installé).

### 3.2 Sortie attendue

Pour chaque texte détecté :

```python
{
    "text": "14",
    "bbox_px": [x_min, y_min, x_max, y_max],
    "center_px": [cx, cy],
    "confidence": 0.95
}
```

### 3.3 Classification des textes

| Pattern | Signification | Utilisation |
|---|---|---|
| `"14"` (exactement) | Code pièce bureau | Point de départ du ray-cast |
| Nombre décimal (`"15.2"`, `"9.8"`) | Surface en m² | Validation croisée des dimensions |
| Label alphanumérique (`"B.4.01"`) | Identifiant de pièce | Champ `name` dans le JSON |
| Autre | Non pertinent | Ignoré |

### 3.4 Association label ↔ pièce

Un label (ex. `"B.4.01"`) est associé au `"14"` le plus proche
(distance euclidienne entre centroïdes). Seuil de distance max :
la diagonale du bbox de la pièce détectée en étape 4.

### 3.5 Association surface ↔ pièce

Même logique : le nombre décimal le plus proche du `"14"` est interprété
comme la surface en m² de cette pièce.

---

## 4. Étape 2 — Nettoyage de l'image

### 4.1 Objectif

Supprimer les textes pour ne garder que les traits structurels (murs, portes,
fenêtres, poteaux).

### 4.2 Méthode

Pour chaque bbox OCR détectée :
1. Dilater la bbox de quelques pixels (marge de sécurité)
2. Remplir la zone avec la couleur médiane des pixels environnants
   (ou blanc si le fond est uniforme)

### 4.3 Précaution

Ne pas effacer les arcs de porte : les arcs sont des traits fins courbes,
l'OCR ne les détecte pas comme du texte. Vérifier néanmoins que l'OCR ne
confond pas un arc avec un caractère (contrôle visuel sur les premiers plans).

---

## 5. Étape 3 — Binarisation

### 5.1 Méthode

Seuillage adaptatif (Gaussian, block size ~31, constante C ~10).
Ajustable par paramètre.

### 5.2 Résultat

Image binaire :
- **Noir (0)** : murs, cloisons, traits architecturaux
- **Blanc (255)** : intérieur des pièces, couloirs, vide

### 5.3 Post-traitement

- Dilatation morphologique (1-2 px) pour fermer les micro-interruptions
  dans les murs (traits fins mal binarisés)
- Pas de fermeture trop agressive : les ouvertures de portes doivent
  rester ouvertes

---

## 6. Étape 4 — Ray-cast par faisceau

### 6.1 Principe

Depuis le centroïde de chaque `"14"` détecté, on lance des faisceaux de
rays parallèles dans les 4 directions cardinales pour détecter les murs
de la pièce.

### 6.2 Algorithme — faisceau mono-directionnel

Pour une direction (ex. sud / +y) depuis le centroïde `(cx, cy)` :

```
Entrée :
  - image binaire (noir = mur, blanc = vide)
  - centroïde (cx, cy)
  - direction : sud (+y)
  - largeur du faisceau : W pixels (typiquement toute la largeur
    possible jusqu'aux murs perpendiculaires estimés)

Faisceau :
  Pour chaque x dans [cx - W/2 .. cx + W/2] :
    Lancer un ray vertical depuis (x, cy) vers le sud
    distance[x] = nombre de pixels blancs avant le premier pixel noir

Histogramme des distances :
  mode = valeur la plus fréquente de distance[]
  → c'est la distance au mur réel de la pièce

Profil transversal du mur :
  Pour chaque x, une fois le premier pixel noir atteint à distance[x] :
    Continuer le ray sur T pixels supplémentaires (T ≈ 20-30 px)
    Enregistrer le profil transversal : séquence de noir/blanc
    → sert à classifier le type de mur (voir §6.6)
```

### 6.3 Détermination de la largeur du faisceau

Problème : on ne connaît pas encore les murs perpendiculaires au moment
de lancer le premier faisceau.

Solution en 2 passes :
1. **Passe grossière** : faisceau large (ex. ±300 px) dans les 4 directions.
   Les modes donnent les 4 murs approximatifs → bbox grossière.
2. **Passe affinée** : faisceau limité à la largeur/hauteur de la bbox
   grossière. Les modes et profils sont recalculés avec précision.

### 6.4 Analyse du profil de distance — classification des anomalies

Pour chaque direction, le profil `distance[position]` le long du mur
révèle 3 types d'anomalies par rapport au mode (distance du mur réel) :

```
distance
    ▲
    │
D+  │          ┌────┐              ┌──┐
    │          │    │              │  │
D   │──────────┘    └──────────────┘  └──────── mode (mur réel)
    │
D-  │                      ┌──┐
    │                      │  │
    │──────────────────────┘  └─────────────────
    └──────────────────────────────────────────→ position le long du mur

         Ouverture 1          O2     Obstacle
       (rays > mode)      (> mode)  (rays < mode)
```

| Profil | Interprétation | Critère |
|---|---|---|
| `distance ≈ mode` | Mur plein | Écart < seuil bruit (3-5 px) |
| `distance > mode` (plateau) | Ouverture (porte ou baie) | Zone contiguë de rays dépassant le mode |
| `distance < mode` (plateau) | Obstacle (poteau, débarras) | Zone contiguë de rays en deçà du mode |
| `distance > mode` (profil courbe) | Arc de porte | Voir §6.5 |

### 6.5 Détection de l'arc de porte — signature du ray-cast

Sur un plan architectural, une porte est représentée par :
- une **interruption** dans le mur (l'ouverture)
- un **arc de cercle** (quart de cercle) indiquant le balayage du battant

L'arc est un trait fin dessiné sur le plan. Il est situé du côté vers lequel
la porte s'ouvre :
- `opens_inward = true` → arc à l'intérieur de la pièce
- `opens_inward = false` → arc à l'extérieur

#### 6.5.1 Porte ouvrant vers l'intérieur (cas courant)

L'arc est ENTRE le centroïde et le mur. Certains rays du faisceau
rencontrent l'arc AVANT le mur.

```
Vue en plan (porte sur mur sud, ouvre vers l'intérieur, charnière à gauche) :

     intérieur de la pièce
            │
            │     ╭───╮  ← arc (trait noir sur le raster)
            │     │    
   ─────────╯     ╰──────  ← mur sud avec interruption
                            
     extérieur (couloir)
```

Profil de distance du faisceau allant vers le sud :

```
distance
    ▲
    │     
D+  │                ██         ← rays traversant l'ouverture (> mode)
    │               █  █            (ne rencontrent ni mur ni arc)
D   │███████████████    ████████ ← mode = mur réel
    │              █             ← rays touchant l'arc (< mode)
    │             █                  (distance décroissante : arc courbe)
    │            █                   
    └───────────────────────────→ position le long du mur
                 ←─ ouverture ─→
     charnière ──╯              ╰── côté libre
```

Ce que le profil montre dans la zone de l'ouverture (de gauche à droite) :

1. **Côté charnière** : le ray touche l'arc près de la paroi → distance
   légèrement inférieure au mode, puis décroissante en suivant la
   courbure (l'arc s'éloigne du mur en s'éloignant de la charnière)
2. **Zone de transition** : l'arc s'incurve vers l'intérieur → les rays
   s'arrêtent de plus en plus tôt (distance décroissante, profil courbe)
3. **Côté libre** : au-delà du rayon de l'arc, les rays ne touchent plus
   l'arc ni le mur → ils traversent l'ouverture (distance > mode)

#### 6.5.2 Signature mathématique de l'arc

L'arc est un quart de cercle de rayon R (= largeur de la porte, ~90 cm
en pixels). Pour un ray à la position `p` le long du mur, mesuré depuis
la charnière :

```
distance_arc(p) = D_mur - sqrt(R² - p²)    pour 0 ≤ p ≤ R
```

Où `D_mur` est la distance au mur (mode). Le profil suit une courbe
en racine carrée inversée — c'est la signature discriminante.

#### 6.5.3 Distinction arc vs obstacle rectangulaire

| Critère | Arc de porte | Obstacle (poteau/débarras) |
|---|---|---|
| Forme du profil | Courbe (racine carrée) | Plateau rectangulaire |
| Bord d'attaque | Progressif (tangent au mur) | Abrupt (marche) |
| Présence d'ouverture adjacente | Oui (rays > mode à côté) | Non (mur continu) |
| Largeur typique | 80-100 px (90 cm porte) | Variable |

Test de discrimination :
1. Calculer le R² du fit circulaire sur le profil décroissant
2. Si R² > 0.85 et qu'une ouverture (rays > mode) est adjacente → **arc de porte**
3. Sinon → **obstacle**

#### 6.5.4 Extraction des paramètres de la porte

Depuis le profil détecté :

| Paramètre | Extraction |
|---|---|
| `face` | Direction du faisceau (sud → `"south"`, etc.) |
| `offset_cm` | Position de début de l'ouverture le long du mur, convertie en cm |
| `width_cm` | Largeur de l'ouverture (zone rays > mode), convertie en cm |
| `has_door` | `true` si un profil d'arc est détecté, `false` sinon (baie libre) |
| `opens_inward` | `true` si l'arc est côté intérieur (rays < mode), `false` si non détecté côté intérieur |
| `hinge_side` | Côté où le profil courbe commence (gauche ou droite de l'ouverture) |

#### 6.5.5 Porte ouvrant vers l'extérieur

L'arc est à l'EXTÉRIEUR de la pièce. Le faisceau depuis l'intérieur ne
voit PAS l'arc — il voit seulement l'ouverture (rays > mode) sans profil
courbe côté intérieur.

```
Profil :
distance
    ▲
D+  │         ████████████     ← ouverture plate (pas d'arc visible)
D   │█████████            █████ ← mode
    └──────────────────────────→
```

→ Ouverture détectée, mais `opens_inward` ne peut pas être déterminé
par le ray-cast intérieur seul.

Solution : lancer un **ray-cast complémentaire depuis l'extérieur**
(quelques pixels au-delà du mur, dans la direction opposée) et chercher
le profil d'arc. Si détecté → `opens_inward = false`.

Si non détecté des deux côtés → `has_door = false` (baie libre).

### 6.6 Analyse de la texture transversale du mur — détection des fenêtres

#### 6.6.1 Principe

Les murs pleins et les fenêtres ont une signature graphique différente
en coupe transversale (perpendiculaire au mur, dans le prolongement du ray) :

```
Mur plein :      ████████         → 1 bande noire épaisse
                 (4-8 px)

Fenêtre :        ██░░██░░██       → 2-3 bandes noires fines espacées
                 (2-3 px chacune, espaces 2-4 px)

Ouverture :      (rien)           → pas de noir (ou trait très fin)
```

#### 6.6.2 Algorithme

Pour chaque ray ayant atteint le mur (distance ≈ mode) :

1. Extraire les T pixels (T ≈ 20-30) au-delà du premier pixel noir
   → vecteur binaire `profil_transversal[0..T]`
2. Compter les **transitions noir→blanc** dans ce vecteur :
   - 0 transition = bande noire unique → **mur plein**
   - 1-2 transitions = 2-3 bandes alternées → **fenêtre**
   - Profil presque tout blanc → **ouverture** (déjà détectée en §6.4)

#### 6.6.3 Agrégation le long du mur

Le profil transversal est calculé pour chaque ray du faisceau. On agrège
par zones contiguës le long du mur :

```
position le long du mur nord :
  ┌─────────────┬──────────────┬────────────────┬──────────┐
  │  mur plein  │   fenêtre    │   mur plein    │  porte   │
  │ 1 bande     │  2-3 bandes  │  1 bande       │ ouvert.  │
  └─────────────┴──────────────┴────────────────┴──────────┘
  0            120           350              450         540
```

Une zone est classée **fenêtre** si > 70% des rays dans cette zone
ont un profil multi-bandes.

#### 6.6.4 Extraction des paramètres de la fenêtre

| Paramètre | Extraction |
|---|---|
| `face` | Direction du faisceau |
| `offset_cm` | Position de début de la zone multi-bandes, convertie en cm |
| `width_cm` | Largeur de la zone multi-bandes, convertie en cm |

#### 6.6.5 Tableau récapitulatif — classification complète d'un mur

Le faisceau dans une direction donne, pour chaque position le long du
mur, deux informations complémentaires :

| Distance (§6.4) | Texture transversale (§6.6) | Classification |
|---|---|---|
| ≈ mode | 1 bande épaisse | **Mur plein** |
| ≈ mode | 2-3 bandes fines | **Fenêtre** |
| > mode (plateau) | — | **Ouverture (baie libre)** |
| > mode + profil courbe adjacent | — | **Porte** (§6.5) |
| < mode (plateau) | — | **Obstacle** (poteau/débarras) |
| < mode (profil courbe) | — | **Arc de porte** (§6.5) |

---

## 7. Étape 5 — Enrichissement

### 7.1 Rectangle brut vs rectangle utile

Le ray-cast produit deux rectangles distincts par pièce :

**Rectangle brut** (`bbox_px`) : les 4 murs détectés (mode des distances
dans chaque direction). C'est le contour physique de la pièce.

**Rectangle utile** (`usable_bbox_px`) : le rectangle brut amputé des
zones non plaçables :
- Zones d'exclusion (poteaux, débarras — §6.4 rays < mode)
- Zones de débattement de porte (quart de cercle, rayon = largeur porte)

Le rectangle utile est le plus grand rectangle inscrit dans la zone
plaçable. Il correspond à la zone effective utilisée par le pipeline
de matching (`effective_dimensions()` dans `catalogue_matcher.py`).

```
┌──────────────────────────────┐  ← bbox_px (rectangle brut)
│                    ┌────┐    │
│                    │excl│    │  ← poteau
│                    └────┘    │
│  ┌─────────────────────┐     │
│  │                     │     │  ← usable_bbox_px (rectangle utile)
│  │                     │     │
│  │                     │     │
│  └─────────────────────┘     │
│ ╭─╮                          │  ← zone porte (exclue)
│ │ │                          │
├─╯ ╰──────── ─────────────────┤
    ↑ porte
```

### 7.2 Dérivation des faces extérieures

Les faces extérieures sont dérivées directement de la classification
murale (§6.6) : **une face avec au moins un segment fenêtre est
considérée extérieure**.

Cette approche remplace le sondage au-delà des murs (probes vers le
fond de l'image) qui imposait la contrainte que l'extérieur du
bâtiment soit accessible depuis les bords de l'image (ancienne H-06).

Avantages :
- Fonctionne avec les cours intérieures (fenêtres sans connexion
  aux bords de l'image)
- Fonctionne avec les plans partiels ou recadrés
- Plus simple (pas de seuils de luminosité fond/intérieur)

Limite : une face extérieure **sans fenêtre** (mur aveugle extérieur)
n'est pas détectée. Cette information est rarement exploitée par le
pipeline de matching (seules les faces avec fenêtres influencent le
scoring de confort visuel SV-01 à SV-03).

### 7.3 Détection de la face couloir (`corridor_face`)

La face donnant sur le couloir est déduite de la porte principale :

1. Identifier la porte principale = la première ouverture avec
   `has_door = true` (ou la plus large si plusieurs)
2. La face de cette porte = `corridor_face`

Validation croisée :
- `corridor_face` devrait être **opposée** à une face extérieure ou à
  une face avec fenêtres (schéma classique : fenêtres côté façade,
  porte côté couloir)
- Si `corridor_face` est la même qu'une face extérieure → signaler
  une incohérence (pièce atypique ou erreur de détection)

### 7.4 Orientation globale de la pièce

En combinant les informations des sections précédentes, chaque pièce
reçoit une orientation résumée :

```
              exterior_faces (fenêtres / façade)
                       ↑
         ┌─────────────────────────┐
         │                         │
  side   │        zone utile       │  side
         │                         │
         └────────────┬────────────┘
                      │
              corridor_face (porte)
```

Règles de déduction :

| Cas | `corridor_face` | `exterior_faces` | Orientation |
|---|---|---|---|
| Standard | sud | nord | Fenêtres au nord, couloir au sud |
| Standard inversé | nord | sud | Fenêtres au sud, couloir au nord |
| Pièce d'angle | sud | nord + est | Fenêtres N+E, couloir au sud |
| Pièce intérieure | sud | (aucune) | Pas de fenêtres, couloir au sud |
| Pièce traversante | — | nord + sud | Fenêtres des deux côtés |

Cette orientation est exploitable par le scoring (contraintes SV —
confort visuel) : les postes avec écran face aux fenêtres sont
pénalisés.

### 7.2 Détection des pièces communicantes

Quand le ray-cast détecte une grande ouverture (> 140 cm) sans arc de
porte, et que le label au-delà n'est pas un couloir → deux pièces
communicantes reliées par une baie libre.

Chaque pièce conserve sa propre bbox ; l'ouverture est enregistrée comme :

```json
{ "face": "east", "offset_cm": 50, "width_cm": 200, "has_door": false }
```

### 7.3 Zones d'exclusion

Les obstacles détectés en §6.4 (rays < mode, profil rectangulaire) sont
convertis en `exclusion_zones` :

```json
{
    "x_cm": <offset depuis le mur ouest>,
    "y_cm": <offset depuis le mur nord>,
    "width_cm": <largeur>,
    "depth_cm": <profondeur>
}
```

Pour un obstacle détecté sur un seul faisceau (ex. poteau contre le mur
sud), le ray-cast perpendiculaire fournit la dimension manquante.

---

## 8. Étape 6 — Conversion en JSON OLO

### 8.1 Échelle

L'utilisateur fournit l'échelle par l'un de ces moyens :
- `scale_cm_per_px` directe
- 2 points de calage (cliqués sur le raster + coordonnées réelles)
- 1 dimension connue (ex. "cette porte fait 90 cm") → on mesure la porte
  en pixels → ratio

### 8.2 Sortie

Format identique à `VISION_LLM_IO_SPEC` §3, avec un champ additionnel
`bbox_px` par pièce pour le positionnement sur le raster :

```json
{
    "name": "B.4.01",
    "width_cm": 310,
    "depth_cm": 480,
    "bbox_px": [120, 45, 430, 525],
    "usable_bbox_px": [120, 45, 430, 445],
    "windows": [
        { "face": "north", "offset_cm": 120, "width_cm": 200 }
    ],
    "openings": [
        { "face": "south", "offset_cm": 0, "width_cm": 90,
          "has_door": true, "opens_inward": true, "hinge_side": "left" }
    ],
    "exclusion_zones": [
        { "x_cm": 250, "y_cm": 0, "width_cm": 40, "depth_cm": 40 }
    ],
    "exterior_faces": ["north"],
    "corridor_face": "south"
}
```

| Champ | Description |
|---|---|
| `bbox_px` | Rectangle brut `[x_min, y_min, x_max, y_max]` en pixels |
| `usable_bbox_px` | Rectangle utile (hors exclusions et zones de porte) |
| `exterior_faces` | Faces donnant sur l'extérieur du bâtiment (§7.2) |
| `corridor_face` | Face donnant sur le couloir, déduite de la porte principale (§7.3) |

Le champ `bbox_px` est `[x_min, y_min, x_max, y_max]` en pixels sur le
raster d'origine.

---

## 9. Validation et cohérence croisée

| Contrôle | Méthode |
|---|---|
| Surface cohérente | `width_cm × depth_cm` ≈ `surface_m2 × 10000` (±15%) |
| Ouvertures dans les murs | `offset_cm + width_cm ≤ longueur du mur` |
| Exclusions dans la pièce | Coordonnées incluses dans la bbox |
| Portes bilatérales | Chaque porte détectée sur un mur d'une pièce devrait correspondre à une ouverture sur le mur d'en face (couloir ou pièce adjacente) |
| Pas de chevauchement | Aucune bbox ne chevauche une autre bbox (sauf pièces communicantes) |

---

## 10. Limites connues

| Limite | Impact | Mitigation |
|---|---|---|
| Murs très fins ou en pointillés | Rays ne détectent pas le mur | Ajuster binarisation / dilatation |
| Pièce sans le code `14` | Pièce ignorée | Ajout manuel ou détection d'autres codes |
| Porte coulissante (pas d'arc) | Pas de `has_door` | Détectée comme baie libre |
| Pièce très petite (< 6 m²) | Faisceau trop étroit | Réduire le nombre de rays min |
| Arc de porte partiellement effacé | Fit circulaire dégradé | Abaisser le seuil R² ou fallback LLM |

---

## 11. Dépendances techniques

| Composant | Bibliothèque | Installation |
|---|---|---|
| OCR | `easyocr` | `pip install easyocr` |
| Image | `Pillow` | déjà installé |
| Binarisation | `Pillow` ou `opencv-python-headless` | `pip install opencv-python-headless` |
| Morphologie | `Pillow` ou `opencv-python-headless` | idem |
| Fit circulaire | `numpy` | déjà installé |

Note : `opencv-python-headless` s'installe sans dépendance GUI ni droits
admin (`pip install opencv-python-headless`).

---

## 11bis. Ray-casting context-aware (Mode Préprocessé — D-77, D-79)

Le pipeline ray-cast décrit aux sections 4–10 ci-dessus est le pipeline **"pur"** utilisé en **Mode OCR** : seule l'image binarisée pilote l'arrêt des rays, et toute la classification (mur / fenêtre / porte / ouverture) se fait a posteriori sur le profil de distances et la texture transversale.

En **Mode Préprocessé** (D-74), le ray-cast devient **context-aware** : il exploite simultanément l'image binarisée et des informations sémantiques externes pour produire un résultat plus robuste, sans renoncer au ray-cast comme primitive de base. Deux mécanismes concrets :

### 11bis.1 Zones de transparence de porte via `doors[]`

**Problème en ray-cast pur** : les traits de porte (montant d'huisserie, arcs de cercle) interceptent le ray avant qu'il n'atteigne le vrai mur. La section 6.5 décrit la signature mathématique de l'arc pour détecter ce cas a posteriori, mais la détection reste fragile quand les arcs sont partiellement effacés (D-75).

**Solution Mode Préprocessé** : le JSON v2 fournit `doors[]` où chaque porte porte son label, sa position pixel et ses dimensions (`pixels_x/y`, `width_px`, `height_px`) + un champ `associated_room` qui relie la porte à sa pièce parente via `id_line3.text`.

On construit un **masque de transparence** par pièce :
- Pour chaque porte de `doors[]` associée à la pièce courante
- Un rectangle centré sur `(pixels_x, pixels_y)`, de dimensions `(width_px, height_px)` + marge
- Les pixels à l'intérieur de ce rectangle sont **ignorés** par le ray-cast (considérés comme vide)

**Effet** :
- Le ray traverse sans obstacle la zone d'ouverture de porte
- Il s'arrête naturellement sur le **vrai mur** derrière la porte (mur de la pièce mitoyenne ou frontière couloir — cf 11bis.2)
- La détection d'ouverture devient directe : tout segment correspondant à un masque de porte **est** une ouverture, sans avoir à distinguer arc vs obstacle

**Différence avec 6.5** : la section 6.5 reste utilisée en Mode OCR pour détecter les arcs a posteriori. En Mode Préprocessé, elle est contournée par l'information explicite de `doors[]`.

### 11bis.2 Arrêt sur la frontière blanc↔vert du couloir

**Problème en ray-cast pur** : la détection de la face couloir (section 7.3) nécessite une analyse post-extraction pour identifier quelle face de la pièce donne sur un couloir, via flood fill depuis les bords + heuristiques de connectivité.

**Solution Mode Préprocessé** : le PNG enhanced peint les couloirs en **vert RGB(193,247,179)** et l'extérieur du bâtiment en **bleu ciel RGB(135,206,235)**. Le ray-cast travaille donc sur une image à 4 états sémantiques au lieu de 2 :

| Pixel | Sens |
|---|---|
| **Blanc** | Intérieur de pièce (parcours libre du ray) |
| **Noir** | Mur (arrêt du ray, classification mur plein ou fenêtre via texture) |
| **Vert** | Couloir (arrêt du ray — la frontière blanc↔vert **est** un mur de pièce donnant sur couloir) |
| **Bleu ciel** | Extérieur bâtiment (arrêt du ray — la frontière blanc↔bleu **est** une façade, candidat fenêtre) |

**Règle d'arrêt enrichie** : un ray s'arrête quand il rencontre l'un de ces trois états non-blancs. À l'arrêt, la couleur rencontrée qualifie immédiatement la nature du mur :

- Vert → mur couloir (la section 7.3 devient triviale)
- Bleu → mur façade (candidat fenêtre — l'analyse de texture transversale de 6.6 ne s'exécute que sur ces segments)
- Noir → mur plein ou mitoyen

**Effet combiné avec 11bis.1** : quand un ray traverse la zone de transparence d'une porte (11bis.1), il continue jusqu'à rencontrer :
- Le mur de la pièce mitoyenne (noir → porte entre deux pièces)
- La frontière couloir (vert → porte sur couloir)
- L'extérieur (bleu → improbable pour une porte, signale un cas d'erreur)

Le type d'ouverture est donc **déterminé par la couleur d'arrêt**, sans classification a posteriori.

### 11bis.3 Impact sur le pipeline

Le ray-cast context-aware **ne remplace pas** le ray-cast pur — il l'enrichit via deux pré-étapes optionnelles :

```
Mode OCR :
   PNG brut → ocr → clean → binarize → ray-cast pur → classification a posteriori

Mode Préprocessé :
   PNG enhanced + JSON v2 → build masques portes (11bis.1)
                        → ray-cast context-aware (11bis.2)
                        → classification directe par couleur d'arrêt
```

Les sections 6.5 (détection arc de porte) et 7.3 (détection face couloir) deviennent inutilisées en Mode Préprocessé. La section 6.6 (texture fenêtre) reste utilisée mais uniquement sur les segments déjà filtrés comme façade par la couleur bleu ciel.

**Gains attendus** :
- Robustesse face aux arcs partiellement effacés (D-75 neutralisé pour le Mode Préprocessé)
- Détection de la face couloir triviale et 100 % fiable
- Cours intérieures gérées automatiquement (peintes en bleu comme l'extérieur)
- Pipeline plus court et plus rapide (moins de passes de classification)

---

## 12. Intégration avec le pipeline existant

```
                    ┌─────────────────────┐
                    │  Plan raster (PNG)   │
                    └─────────┬───────────┘
                              │
                    ┌─────────▼───────────┐
                    │  RASTER_EXTRACTION   │  ← cette spec
                    │  (OCR + ray-cast)    │
                    └─────────┬───────────┘
                              │
                    ┌─────────▼───────────┐
                    │  JSON OLO + bbox_px  │
                    └─────────┬───────────┘
                              │
               ┌──────────────┼──────────────┐
               ▼              ▼              ▼
        Floor Plan       catalogue       Export
        Input            matcher.py      (PDF/CSV)
        (filigrane)      (matching)
```

Le JSON produit est identique à celui de `VISION_LLM_IO_SPEC` — les deux
pipelines (LLM Vision et Raster Extraction) sont interchangeables.
L'utilisateur choisit celui qui convient selon la qualité du plan et les
outils disponibles.
