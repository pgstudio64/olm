# Specification du format de piece -- DSL texte

> **Version** : 1.0 -- 2026-04-01
> **Decision** : D-44

---

## 1. Grammaire

```
room_dsl    := piece_line NL element*
piece_line  := "PIECE" WS INTEGER "x" INTEGER
element     := window | door | opening | exclusion | COMMENT | EMPTY_LINE
window      := "FEN" WS FACE WS INTEGER WS INTEGER
door        := "PORTE" WS FACE WS INTEGER WS INTEGER WS OPEN_DIR WS HINGE
opening     := "BAIE" WS FACE WS INTEGER WS INTEGER
exclusion   := "EXCL" WS INTEGER WS INTEGER WS INTEGER WS INTEGER
FACE        := "N" | "S" | "E" | "O"
OPEN_DIR    := "INT" | "EXT"
HINGE       := "G" | "D"
INTEGER     := [0-9]+
NL          := "\n"
WS          := " "+
COMMENT     := "--" .*
EMPTY_LINE  := WS* NL
```

---

## 2. Regles

- Un element par ligne.
- Les lignes vides et les commentaires (`--`) sont ignores.
- `PIECE` doit etre la premiere ligne non vide et non commentaire.
  - Le premier entier est la largeur (ouest vers est), le second la profondeur (nord vers sud).
  - Dimensions en centimetres.
- Les faces sont designees par `N` (nord), `S` (sud), `E` (est), `O` (ouest).
- Le standard de placement (AFNOR, minimal, etc.) n'est pas encode dans le DSL piece.
  Le standard est choisi separement dans l'editeur ou le pipeline.

### FEN (fenetre)

```
FEN <FACE> <offset> <largeur>
```

- `offset` : distance en cm depuis l'extremite ouest (faces N/S) ou nord (faces E/O).
- `largeur` : largeur de la fenetre en cm.

### PORTE (porte battante)

```
PORTE <FACE> <offset> <largeur> <OPEN_DIR> <HINGE>
```

- `offset` et `largeur` : memes conventions que `FEN`.
- `OPEN_DIR` : sens d'ouverture -- `INT` (vers l'interieur) ou `EXT` (vers l'exterieur).
- `HINGE` : cote du gond vu depuis l'interieur -- `G` (gauche) ou `D` (droite).

### BAIE (ouverture libre)

```
BAIE <FACE> <offset> <largeur>
```

- Ouverture sans battant (passage libre entre deux espaces).
- Memes conventions d'offset et largeur que `FEN`.

### EXCL (zone d'exclusion)

```
EXCL <x> <y> <largeur> <profondeur>
```

- Rectangle interdit au placement, exprime dans le repere local de la piece
  (origine = coin nord-ouest, x vers est, y vers sud).
- `x`, `y` : coin nord-ouest de la zone d'exclusion.
- `largeur` : dimension ouest vers est.
- `profondeur` : dimension nord vers sud.
- Les zones d'exclusion sont declaratives : elles sont resolues au moment du matching,
  pas dans le pattern.

---

## 3. Exemples

### 3.1 Piece simple

Bureau standard 300 x 480 cm, une porte au sud, fenetre pleine largeur au nord.

```
-- Bureau standard
PIECE 300x480
FEN N 0 300
PORTE S 105 90 INT G
```

### 3.2 Piece d'angle

Piece d'angle 500 x 400 cm, fenetres au nord et a l'est, deux portes au sud.

```
-- Piece d'angle avec deux facades vitrees
PIECE 500x400
FEN N 50 400
FEN E 50 300
PORTE S 50 90 INT G
PORTE S 350 90 INT D
```

### 3.3 Piece avec obstacle

Piece 400 x 500 cm avec une gaine technique (poteau/colonne) dans le coin nord-est.

```
-- Piece avec gaine technique
PIECE 400x500
FEN N 0 400
PORTE S 155 90 INT G
EXCL 350 0 50 50
```

### 3.4 Piece avec ouverture libre

Grande piece 600 x 400 cm avec une baie libre a l'ouest communiquant avec la piece adjacente.

```
-- Open space communiquant
PIECE 600x400
FEN N 50 500
PORTE S 255 90 INT G
BAIE O 100 200
```

---

## 4. Correspondance avec RoomSpec (room_model.py)

Le DSL est **bidirectionnel** : un texte DSL peut etre parse en `RoomSpec` et un `RoomSpec`
peut etre serialise en DSL.

### Table de correspondance

| DSL | RoomSpec |
|---|---|
| `PIECE <W>x<D>` | `RoomSpec(width_cm=W, depth_cm=D)` |
| `FEN <F> <off> <w>` | `WindowSpec(face=F, offset_cm=off, width_cm=w)` |
| `PORTE <F> <off> <w> INT G` | `OpeningSpec(face=F, offset_cm=off, width_cm=w, has_door=True, opens_inward=True, hinge_side=LEFT)` |
| `PORTE <F> <off> <w> INT D` | `OpeningSpec(face=F, offset_cm=off, width_cm=w, has_door=True, opens_inward=True, hinge_side=RIGHT)` |
| `PORTE <F> <off> <w> EXT G` | `OpeningSpec(face=F, offset_cm=off, width_cm=w, has_door=True, opens_inward=False, hinge_side=LEFT)` |
| `PORTE <F> <off> <w> EXT D` | `OpeningSpec(face=F, offset_cm=off, width_cm=w, has_door=True, opens_inward=False, hinge_side=RIGHT)` |
| `BAIE <F> <off> <w>` | `OpeningSpec(face=F, offset_cm=off, width_cm=w, has_door=False)` |
| `EXCL <x> <y> <w> <d>` | `ExclusionZone(x_cm=x, y_cm=y, width_cm=w, depth_cm=d)` |

### Correspondance des faces

| DSL | Face (enum) |
|---|---|
| `N` | `Face.NORTH` |
| `S` | `Face.SOUTH` |
| `E` | `Face.EAST` |
| `O` | `Face.WEST` |

### Correspondance des gonds

| DSL | HingeSide (enum) |
|---|---|
| `G` | `HingeSide.LEFT` |
| `D` | `HingeSide.RIGHT` |

### Champs RoomSpec non couverts par le DSL

Les champs suivants de `RoomSpec` ne sont pas exprimes dans le DSL piece :

| Champ | Raison |
|---|---|
| `name` | Identifiant libre, gere par le pipeline |
| `code` | Code reglementaire, gere par le pipeline |
| `direction` | Orientation batiment, gere par le pipeline |
| `raster_nw_x_px` | Coordonnees raster, gere par le pipeline |
| `raster_nw_y_px` | Coordonnees raster, gere par le pipeline |
| `ExclusionZone.physical` | Toujours `True` dans le DSL (obstacles declares) ; `False` = zones fictives generees par le pipeline |
