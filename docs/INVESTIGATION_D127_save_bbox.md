# Investigation — Bug D-127 : Save room ne persiste pas `bbox_px` après resize

Date : 2026-04-21 (autonome post-D-135).

---

## Rappel du bug (TODO.md)

> Au Save, `canonRoom.bbox_px` récupère toujours `ramend.originalRoom.bbox_px`
> (la valeur d'entrée en amend mode), pas le bbox effectif redimensionné.
> Résultat : les dims persistées dans fpData reflètent le resize, mais
> `bbox_px` reste à la position d'origine → désalignement potentiel avec
> l'overlay.

---

## Flux actuel dans `save()` ([editor.js:1452-1646](olm/static/editor.js#L1452-L1646))

1. **L-1471-1484** — construction de `canonRoom` avec
   `bbox_px: ramend.originalRoom.bbox_px.slice()` (= ancien bbox figé à
   l'entrée en Room amend).
2. **L-1505** — `fpRoomAmendments[name] = JSON.parse(JSON.stringify(canonRoom))`
   (snapshot avec **ancien bbox**).
3. **L-1522-1534** — switch sur `origCf` pour calculer `absShiftX/Y, absW/D`
   (équivalent manuel de `rotateRectInv`).
4. **L-1569-1573** — `newBbox = [nx0, ny0, nx1, ny1]` calculé correctement
   depuis `renderOffset` user.
5. **L-1579, L-1609** — `newBbox` propagé dans `ingRooms[ir].bbox_px` et
   `fpData.rooms[fr].bbox_px`.
6. **L-1627-1628** — `fpRoomAmendments[name] = JSON.parse(JSON.stringify(fpData.rooms[fr]))`
   (écrasement final avec bon bbox… **conditionnellement**).

## Où ça casse

L'écrasement ligne 1627-1628 n'a lieu **que si** :
- `scaleCmPerPx > 0`
- `newBbox !== null` (room trouvée dans `ingRooms`)
- `window.fpData && window.fpData.rooms` existe
- room avec `name === ramend.roomName` trouvée dans `fpData.rooms`

Si une de ces conditions échoue, `fpRoomAmendments[name]` garde **l'ancien bbox**
(stocké ligne 1505). Or `rvRenderCurrent` priorise
`fpRoomAmendments[name]` sur `fpData.rooms[i]`
([floor_plan.js:200](olm/static/floor_plan.js#L200)) — d'où le désalignement à
la réouverture de la Review.

## Validation mathématique du calcul actuel

La logique switch (L-1522-1534) est mathématiquement **équivalente à
`rotateRectInv`** de canonical_io.js. Vérification par orientation :

| `origCf` | save() | `rotateRectInv(canonBbox, cf, absW, absD)` |
|---|---|---|
| south | `absShiftX = cShiftX; absShiftY = cShiftY` | `x = cShiftX; y = cShiftY` ✅ |
| east  | `absShiftX = -cShiftY; absShiftY = cShiftX; absW=cD; absD=cW` | `x = absW - cShiftY - cD = -cShiftY; y = cShiftX` ✅ |
| north | `absShiftX = -cShiftX; absShiftY = -cShiftY` | `x = absW - cShiftX - cW = -cShiftX; y = absD - cShiftY - cD = -cShiftY` ✅ |
| west  | `absShiftX = cShiftY; absShiftY = -cShiftX; absW=cD; absD=cW` | `x = cShiftY; y = absD - cShiftX - cW = -cShiftX` ✅ |

Le calcul `newBbox` est donc **correct**. Le bug est uniquement dans la
**propagation conditionnelle** vers `fpRoomAmendments`.

## Fix proposé

### Approche A — Patcher canonRoom une fois newBbox connu (minimal)

Déplacer l'assignement `fpRoomAmendments[name] = …` APRÈS le calcul de
`newBbox`, en utilisant le newBbox à la place de l'ancien. Éliminer le
premier assignement ligne 1505.

```javascript
// supprimer L-1505
// fpRoomAmendments[ramend.roomName] = JSON.parse(JSON.stringify(canonRoom));

// … calcul newBbox …

// NOUVEAU, après L-1573 et avant d'entrer dans le bloc fpData :
if (newBbox) canonRoom.bbox_px = newBbox.slice();
fpRoomAmendments[ramend.roomName] = JSON.parse(JSON.stringify(canonRoom));
```

Puis supprimer le 2e `fpRoomAmendments = …` L-1627-1628 (devenu redondant).

**Avantage** : une seule source de vérité pour `fpRoomAmendments`, indépendant
de la présence de `fpData`. Le cas `scaleCmPerPx === 0` ou `newBbox === null`
garde l'ancien bbox (fallback identique à l'actuel).

### Approche B — Unifier via `rotateRectInv` (refactor)

Remplacer le switch L-1522-1534 par un appel à `canonicalIO.rotateRectInv`,
similaire à init_rvtool.js D-127. Plus propre architecturalement, **mais
plus de code touché** : je ne recommande pas en autonome.

---

## Recommandation

**Approche A** — patch chirurgical en 3 lignes (suppression L-1505,
insertion après newBbox, suppression L-1627-1628). Risque très faible, test
facile : resize Room → Save → re-ouvrir Review → vérifier alignement overlay.

Cas edge à tester :
- Room south simple (cas trivial, inchangé).
- Room east/west (swap dims, vérifier que newBbox est bien calculé).
- Room north (inversion complète).
- Save sans avoir rematché (fpData vide) — le bug existe exactement ici.

---

## Code de référence (extraits)

### editor.js:1471-1484 — construction actuelle
```javascript
var canonRoom = {
  name: ramend.roomName,
  width_cm: state.room_width_cm,
  depth_cm: state.room_depth_cm,
  // ...
  bbox_px: ramend.originalRoom.bbox_px
    ? ramend.originalRoom.bbox_px.slice()
    : null,  // ← stale
  seed_px: _origSeed ? _origSeed.slice() : null,
};
```

### init_rvtool.js:338-367 — calcul effBbox en D-127 (réutilisable)

Le handler de re-analyze dans init_rvtool.js fait déjà exactement ce calcul
via `rotateRectInv`. C'est la référence pour l'Approche B.
