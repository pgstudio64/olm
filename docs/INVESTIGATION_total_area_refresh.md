# Investigation — Bug TODO : Total area m² non rafraîchi au changement d'échelle

Date : 2026-04-21 (autonome post-D-135).

---

## Rappel du bug (TODO.md)

> Quand l'utilisateur modifie l'échelle (`drawing_scale`), le total area
> affiché reste sur l'ancienne valeur. À relier au recompute scale.

---

## Chaîne de dépendances

### Affichage `rvFloorArea`

Le texte DOM est mis à jour **uniquement** dans
[floor_plan.js:193-194](olm/static/floor_plan.js#L193-L194) :

```javascript
document.getElementById("rvFloorRooms").textContent = allRooms.length;
document.getElementById("rvFloorArea").textContent = totalArea.toFixed(1);
```

Ces deux lignes vivent dans `rvRenderCurrent()`. Elles sont précédées par un
early-return L-180-184 qui sort si `fpCurrent()` retourne null.

Les IDs `rvFloorRooms` / `rvFloorArea` — malgré leur préfixe `rv` — sont en
fait dans le panneau latéral de **Floor** (tab Import), voir
[pattern_editor.html:199-200](olm/templates/pattern_editor.html#L199-L200).

### Handler changement d'échelle

[ingestion.js:1403-1449](olm/static/ingestion.js#L1403-L1449) — `_applyDrawingScale()` :

1. Recalcule `ingState.scale = computeCmPerPx(scaleNum, dpi)`
2. `ingState.rooms.forEach(_updateRoomDims)` → nouvelles `width_cm`,
   `depth_cm`, `surface_m2` par pièce.
3. Propage vers `fpData.rooms[fr]` (width_cm, depth_cm, surface_m2).
4. Appelle `updateIngRoomList()` (refresh sidebar rooms) + `renderIngestion()` (re-dessine SVG Floor).
5. `populateRoomsJson()` (textarea debug).
6. **`fpLoadAndMatch(ingState.rooms)` — async fetch /api/floor-plan/match**.
7. Met à jour `ingScaleInfo`.

**Aucun appel direct à `rvRenderCurrent()`**. Les IDs `rvFloorRooms` /
`rvFloorArea` restent donc à leur ancienne valeur jusqu'au retour du
`fpLoadAndMatch` async.

## Où ça casse

Dans `fpLoadAndMatch` ([floor_plan.js:97-154](olm/static/floor_plan.js#L97-L154))
à la résolution du fetch :

```javascript
fpData.rooms = data.rooms;
// ...
fpRenderCurrent();
rvRenderCurrent();        // <-- ICI update rvFloorArea
```

Si :
- Le fetch match échoue ou est lent → retard ou absence de refresh.
- `fpCurrent()` retourne null (aucune room sélectionnée dans Review) → early-return ligne 184 → **`rvFloorArea` n'est jamais mis à jour**.
- Le serveur renvoie une liste vide ou une erreur.

Dans tous ces cas, `rvFloorArea` reste figé sur l'ancien total. C'est le bug
signalé.

## Fix proposé

### Approche A — Appel explicite dans `_applyDrawingScale` (minimal)

Ajouter un appel à `rvRenderCurrent()` juste après `renderIngestion()` dans
[ingestion.js:1437](olm/static/ingestion.js#L1437) :

```javascript
updateIngRoomList();
renderIngestion();
populateRoomsJson();
if (typeof window.rvRenderCurrent === 'function') window.rvRenderCurrent();
// ... puis fpLoadAndMatch async
```

**Avantage** : fix immédiat et local, le total area s'affiche dès le change
event sans attendre le fetch async.

**Limite** : l'early-return `if (!room) return` L-184 reste — si aucune room
sélectionnée, l'update n'a toujours pas lieu. À corriger séparément.

### Approche B — Déplacer l'update hors de `rvRenderCurrent`

Extraire un helper `_updateFloorProperties()` exécuté à deux endroits :
dans `rvRenderCurrent` (pour le cas nominal) et dans `_applyDrawingScale`
(pour forcer le refresh immédiat). Bypass l'early-return.

```javascript
function _updateFloorProperties() {
  var allRooms = fpRooms();
  var totalArea = 0;
  allRooms.forEach(function(r) {
    totalArea += (r.width_cm || 0) * (r.depth_cm || 0) / 10000;
  });
  document.getElementById("rvFloorRooms").textContent = allRooms.length;
  document.getElementById("rvFloorArea").textContent = totalArea.toFixed(1);
}
```

Puis sortir `_updateFloorProperties()` de l'early-return de `rvRenderCurrent`
(l'appeler en tout début de la fonction, avant le `if (!room) return`).

**Avantage** : correct dans tous les cas (pas de dépendance au flag
`fpCurrent()`).

**Effort** : 3 lignes supplémentaires, logique claire.

## Recommandation

**Approche B** — séparer le calcul des Floor properties (qui ne dépend que de
`fpRooms()`) du rendu Review. Cosmétique mais plus robuste. Si tu préfères le
minimal, l'Approche A est OK à court terme.

Points à tester après le fix :
- Charger plan, changer l'échelle dans Floor → total area m² doit refléter la
  nouvelle valeur immédiatement.
- Même test avec aucune room sélectionnée en Review (current room null).
- Même test avec `fpData` vide (edge case).
