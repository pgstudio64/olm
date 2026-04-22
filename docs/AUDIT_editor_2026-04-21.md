# Audit dette technique — `olm/static/editor.js`

Date : 2026-04-21 (post-D-135). Fichier ~2264 lignes, module éditeur patterns
+ Room amend enter/exit/save. Audit passif.

---

## 1. Code mort

| Ligne | Problème |
|---|---|
| 572 | `globalWestOffset = 0` commenté "obsolete", jamais utilisé |
| 1095 | Commentaire orphelin `zoomLevel display removed — simplified toolbar` |
| 2084 | `state._savedName = null;` dans `duplicatePattern()` — redondant |

## 2. Magic numbers

Bloc `EDITOR_CONSTANTS` à créer. Principaux :

**Geometry / handles** :
| Ligne | Valeur | Constante |
|---|---|---|
| 278-282 | 6, 14, 10 (× hzf) | `OPENING_HANDLE_R_PX`, `OPENING_CLICKW_PX`, `OPENING_DELFS_PX` |
| 398 | 2 | `EXCLUSION_OUTLINE_WIDTH_PX` |
| 845-846 | 10 | `CORNER_HANDLE_R_PX` |
| 863 | 48 | `DIM_LABEL_OFFSET_PX` |
| 906-907 | 1.0, 1.5 | `CIRC_STROKE_MIN`, `CIRC_STROKE_NOMINAL` |
| 989 | 2.5 | `HIT_DISC_RADIUS_PX` |
| 1015, 1134 | 100 | `METER_VISUAL_PX` |
| 2153, 2171 | 0.8, 1.25 | `ZOOM_IN_FACTOR`, `ZOOM_OUT_FACTOR` |
| 2190-2200 | 0.2, 35, 50, 15, 30 | `FITVIEW_PAD_*` |

**Couleurs** (hard-codées, à regrouper `COLOR_*`) :
`#50b8d0` (window cyan), `#80c060` (opening vert), `#1e1e1e` (mur noir),
`#58c080` (good), `#c05858` (danger), `#c8a050` (neutral), `#ffffff` (wall),
`#0e0e0d` (label BG).

## 3. Duplications — synchronisation fragile cross-stores

**Pattern critique (lié au bug D-135 rider)** : `save()` L-1535-1637 mute 3
stores en parallèle (ingRooms[ir], fpData.rooms[fr], fpRoomAmendments[name])
avec **8 affectations identiques copiées-collées** par store.

Si la boucle `break` à L-1568 / L-1605 échoue (room non trouvée), mutation
silencieusement sautée, aucun log. C'est exactement le pattern qui a causé
D-135 rider.

**Duplication secondaire** : `_splitOpeningsIntoState()` (editor.js L-1758)
dupliquée dans `fpRematchRoom()` (floor_plan.js L-581-584).

**Action stratégique** : module utilitaire `room_sync_helpers.js`
- `_syncRoomToAllStores(roomName, updates)` — unifié, try/catch, warn.
- `_splitOpeningsToFrontEnd(combinedList)` — source unique pour split has_door.
- `_buildCanonicalRoom(state, bbox, seed)` — factory canonRoom.

Importé dans editor.js + floor_plan.js + ingestion.js.

## 4. Fonctions longues (> 80 lignes)

| Fonction | Lignes |
|---|---|
| `_renderImpl()` | L-535-1096 (**~562 lignes**) : à splitter en `_renderBlocks()`, `_renderRoomElements()`, `_computeDistanceLabels()` |
| `save()` | L-1452-1720 (**~269 lignes**) : 3 modes (room amend / layout amend / pattern save) — splitter en `_saveRoomAmend()`, `_saveLayoutAmend()`, `_savePattern()` |
| `renderRoomElements()` | L-169-417 (**~249 lignes**) : 5 sections (windows / openings / doors / V-rays / handles) |

## 5. Nommage ambigu

| Actuel | Proposition |
|---|---|
| `ramend` (L-1455) | `roomAmendState` |
| `amendedRoom` (L-1488) | `roomPayloadForBackend` |
| `ir` / `fr` (L-1562, 1604) | `ingIdx` / `fpIdx` |
| `_pxOf(cm)` (L-1539) | `_cmToPx(cm)` |
| `_enrichCanon(e)` (L-1547) | `_addPixelOffsets(opening)` |

## 6. Cycles d'état fragiles

**Trois sources de vérité** cohabitent :
- `ingState.rooms` — canonique.
- `fpData.rooms` — canonique + résultats match.
- `fpRoomAmendments` — snapshot canonique mis à jour sur save().

**Scénarios fragiles non testés** :
1. User save room mais Floor Plan tab jamais chargé → `fpData.rooms` vide →
   mutation L-1603 sautée silencieusement.
2. `fpRematchRoom` redondant avec save() → double propagation divergente.

**Action** :
- Initialiser `window.fpRoomAmendments = {}` au boot (pas inline L-1505).
- `_syncRoomToAllStores()` avec try/catch + warn si aucun store ne trouve le
  nom.

## 7. Construction canonRoom inefficiente

L-1470-1505 : `canonRoom` construit champ par champ, puis `amendedRoom =
Object.assign({}, canonRoom, …)`, puis `JSON.parse(JSON.stringify(canonRoom))`
L-1505 pour `fpRoomAmendments` (clone profond alors que canonRoom est déjà
neuf).

**Action** : factory `_buildCanonicalRoom(state, bbox, seed)` retournant objet
unique réutilisable.

---

## Top 5 priorités recommandées

| # | Action | Impact | Effort | Risque |
|---|---|---|---|---|
| 1 | Bloc `EDITOR_CONSTANTS` + couleurs nommées | maintenance +++ | très bas | zéro |
| 2 | `_syncRoomToAllStores(name, updates)` + try/catch — unifie aussi ingestion.js et floor_plan.js | robustesse +++ (prévient D-135 rider bis) | moyen (50-80 l.) | bas (besoin tests) |
| 3 | Splitter `save()` en `_saveRoomAmend` / `_saveLayoutAmend` / `_savePattern` | clarté ++ | moyen | moyen |
| 4 | Renommages ambigus (`ramend`, `ir`/`fr`, `_pxOf`, `_enrichCanon`) | clarté ++ | bas | bas |
| 5 | Supprimer dead code (`globalWestOffset`, orphelin L-1095) | hygiène | très bas | zéro |

**Stratégie suggérée** :
- Priorités 1 + 5 en un premier commit (zéro risque, gain immédiat).
- Priorité 2 en second commit (critique, testable isolément).
- Priorités 3 + 4 en dernier (plus délicat, validation complète).

---

## Cross-check ingestion.js / init_rvtool.js / editor.js

**Converge** :
- D-122 P4 (split openings/doors) dupliqué à 3 endroits → helper partagé.
- D-122 P2 (bbox_px / seed_px uniques) bien suivi.
- R-12 (corridor="south" canonique) cohérent entre stores.

**Divergence** :
- `ingestion.js` a un patch D-135 rider pour bbox_px / dims dans amendments
  (post-Oct. 2026-04-21). `editor.js` save() a le même problème mais n'a pas
  encore reçu le même traitement.
- `fpRematchRoom()` (floor_plan.js) mute fpData inline — devrait passer par
  le même `_syncRoomToAllStores()`.

**Recommandation** : module commun `olm/static/room_sync_helpers.js` (~200
lignes) importé partout. Priorité 2 ci-dessus.
