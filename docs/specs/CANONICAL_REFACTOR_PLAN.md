# Canonical Repère — Plan de refactor (D-121)

Date : 2026-04-20.
Status : **P1 → P7 livrées (D-122)**. Refactor R-14 complet.
Validation visuelle / fonctionnelle en browser recommandée avant
commit final.

## 0. État d'avancement (2026-04-20)

| Phase | Scope | Statut |
|-------|-------|--------|
| P1 | `scale` dans canonicalIO, suppression `_pxFromCm`, `_renderFeat` | ✅ livré |
| P2 | Fusion `bbox_abs_px` → `bbox_px`, `seed_abs_px` → `seed_px` | ✅ livré |
| P3 | Rename `original_corridor_face` → `corridor_face_abs`, lecture ambiguë retirée | ✅ livré |
| P4 | `state.room_doors` séparé, `has_door:true` banni du state | ✅ livré |
| P5 | `/api/floor-plan/match` reçoit canonique, `toStorage` préalable supprimé | ✅ livré |
| P6 | `canonicalIO.rotatePoint` / `rotateRect`, suppression ad-hoc | ✅ livré |
| P7 | Spec `CANONICAL_STATE.md` + tests round-trip (12/12) | ✅ livré |

Tests round-trip `canonical_io.js` : 4 rooms × 4 corridors + 8 helpers =
**16 auto-tests, tous OK** (lancer `window.RUN_CANONICAL_IO_TESTS = true;`
avant chargement du script ou via Node :
`node -e "global.window={RUN_CANONICAL_IO_TESTS:true};require('./olm/static/canonical_io.js')"`).

## 1. Diagnostic

Le projet manipule deux repères pour les pièces :

- **Absolu (raster)** — coordonnées image du plan, orientation bâtiment. Produit par les `extract_*` du backend, consommé par le Floor overlay et le matching.
- **Canonique (corridor-south)** — toutes les pièces normalisées avec corridor en bas (`corridor_face === "south"`). Produit/consommé par l'éditeur, le rendu Room, le DSL, le matching du catalogue.

**4 sessions successives de fixes (D-117, D-120, + 3 commits cette session)** ont progressivement révélé que la conception actuelle **n'a pas de frontière unique** : les conversions sont éparpillées, les structures de données portent des champs redondants désynchronisables, et les contrats (qui est canonique ? qui est absolu ?) sont implicites et non documentés.

### 1.1 Structures de données (inventaire)

| Structure | Repère | Openings/Doors | Champs redondants |
|-----------|--------|----------------|-------------------|
| `ingState.rooms[i]` | canonique | séparés | `bbox_px` + `bbox_abs_px` ; `seed_px` + `seed_abs_px` ; `corridor_face` ("south") + `original_corridor_face` (absolu) |
| `fpData.rooms[i]` | canonique | séparés | idem |
| `fpRoomAmendments[name]` | canonique (depuis 2026-04-20) | séparés | idem |
| `state.room_*` (Room amend / Pattern) | canonique | **combinés** via `has_door:true` | — |
| `amend.originalRoom` | canonique (copie de fpData) | séparés | idem fpData |

### 1.2 Conversions (inventaire)

1. `canonical_io.js:fromStorage` — officielle abs → canon.
2. `canonical_io.js:toStorage` — officielle canon → abs (ne rote PAS `offset_px`).
3. `ingestion.js:pointAbsToCanon` — ad-hoc pour hits/seed/auto_door_masks.
4. `editor.js:_absToCanon2` — ad-hoc pour hits/seed Room amend.
5. `editor.js:_canonicalAngle` — angle CSS overlay rotation.
6. `ingestion_serialize.js:_pxFromCm` — recalcul `offset_px` depuis `offset_cm × pxPerCm` à l'export.
7. `ingestion.js:_renderRoom` (_renderFeat) — idem à l'affichage Floor.
8. `floor_plan.js:enterRoomAmendMode` / `fpRenderEmptyRoom` — combine openings+doors pour state.
9. `editor.js:save()` — re-split state → openings séparé / doors séparé à la persistance.
10. `init_rvtool.js:_stateToDsl` — lit state.room_openings combiné.
11. `ingestion.js:batch re-analyze` — split mergedO → mergedOpenings + mergedDoors.
12. `canonical.py` (backend) — code mort, jamais appelé.

### 1.3 Violations de contrat front/back

- Frontend envoie à `/api/floor-plan/match` des rooms en **absolu** (via `serializeForMatching` → `_toAbsRooms` → `toStorage`), mais le catalogue est défini en **canonique**. Le matcher compare face absolue vs face canonique → résultats corrects par accident pour les pièces south, potentiellement faussés pour les autres.
- Backend `extract_*` produit de l'absolu. Frontend `fromStorage` le canonicalise au load. OK.
- Backend `/api/room/reanalyze` attend / retourne de l'absolu. OK.
- Backend `/api/floor-plan/match` devrait canonicaliser ses inputs mais ne le fait pas (`canonical.py` existe mais n'est pas appelé).

### 1.4 Symptômes observés cette session (tous vissés sur les 1.1–1.3)

- Pièce 902 : door du mauvais côté dans Floor (mismatch canonique face vs absolu raster).
- Pièce 915 : flood d'erreurs NaN SVG (`offset_px` undefined sur windows/openings post-re-analyze).
- Pièce 915 : door rendue comme opening (r.doors vidé au batch re-analyze, has_door:true déplacé dans r.openings).
- Pièce 922 : bbox dessinée trop bas puis bien à la sélection (`bbox_abs_px` stale écrase `bbox_px` à jour dans toStorage).
- Pièce 906 : door invisible dans DSL Review / visu Review (state.room_openings non combiné avec doors séparées).
- Pièce 906 : 180° flip post Save room (fpRoomAmendments stockait l'absolu post-toStorage alors que consumers attendent canonique).

## 2. Proposition

### 2.1 Principes directeurs

1. **Une seule frontière de conversion** : `canonical_io` reste la source unique, mais elle doit connaître `scale` pour roter aussi `offset_px` / `width_px` et éliminer le recalcul ad-hoc.
2. **Une seule forme canonique** dans tout le frontend : toutes les structures (`ingState`, `fpData`, `fpRoomAmendments`, `state.room_*`) stockent le **même format canonique avec la même représentation** (openings et doors séparés ; `has_door:true` banni du state).
3. **`bbox_abs_px` / `seed_abs_px` supprimés** : on ne garde que `bbox_px` / `seed_px`, toujours en coords image absolues (cohérent avec `original_corridor_face` qui est absolu). En canonique, bbox_px reste absolu parce que l'image raster ne tourne pas — la rotation est visuelle (CSS).
4. **Contrat front/back explicite** : `/api/floor-plan/match` canonicalise ses inputs via `canonical.py` (backend). Le frontend envoie tel quel — plus de `toStorage` avant POST.
5. **DSL construit sans fusion** : `buildRoomDSL` / `_stateToDsl` lisent windows/openings/doors/zones depuis state mais `state.openings` et `state.doors` sont séparés, on ajoute les DOOR lines depuis state.doors.

### 2.2 Nouvelle structure de données (unifiée)

```
Room = {
  name: string,
  width_cm, depth_cm: number (canonical, after east/west swap)
  bbox_px: [x0, y0, x1, y1]    // image raster absolute coords (never rotated)
  seed_px: [x, y]               // idem
  corridor_face_abs: "north"|"south"|"east"|"west"|""  // stored, absolute
  corridor_face: "south"        // canonical invariant (optional — derived)
  windows: Opening[]            // all in canonical (face/offset_cm/width_cm rotated)
  openings: Opening[]           // non-door openings only
  doors: Door[]                 // separate, canonical face
  exclusion_zones: Zone[]       // canonical (x_cm/y_cm rotated)
  transparent_zones: Zone[]
  hits?: {x_cm, y_cm}[]         // optional, canonical room-local
  seed_cm?: {x_cm, y_cm}
  auto_door_masks?: Rect[]
}
```

Renommages proposés (pour clarté) :
- `original_corridor_face` → `corridor_face_abs`. L'absolu est la vraie valeur stockée, le canonique est toujours "south" par définition du repère — il n'a même pas besoin d'être stocké.
- Suppression de `bbox_abs_px` / `seed_abs_px`. `bbox_px` / `seed_px` suffisent (image coords inchangés par la rotation canonique).

### 2.3 API `canonicalIO` étendue

```js
window.canonicalIO = {
  fromStorage(room, scale),   // abs → canon. Rote offset_px aussi. scale cm/px.
  toStorage(room, scale),     // canon → abs. Rote offset_px aussi.
  rotatePoint(pt, cf_abs),    // helper public pour hits/seed/masks
  rotateRect(rect, cf_abs),   // helper public pour zones
  FACE_MAPS, INV_FACE_MAPS,
};
```

Suppression de `pointAbsToCanon` / `_absToCanon2` / `_pxFromCm` dupliqués. Tous passent par les helpers publiés.

### 2.4 Structure state Room amend (simplifiée)

```js
state.room_windows: Opening[]    // canonical
state.room_openings: Opening[]   // NON-DOOR ONLY (fini has_door:true)
state.room_doors: Door[]         // séparé
state.room_exclusions: Zone[]
state.room_transparents: Zone[]
state.corridor_face_abs: string
```

Bénéfices :
- Alignement avec `ingState.rooms[i]` / `fpData.rooms[i]` → plus de "re-combine au load / re-split au save".
- `buildRoomDSL` et `_stateToDsl` itèrent séparément les trois collections.
- Les renderers SVG partagés aussi.

### 2.5 Plan d'exécution par phases

**Phase P1 — Rotation des px (canonical_io)**
- Étendre `fromStorage` / `toStorage` à rôter `offset_px` / `width_px` depuis `offset_cm × pxPerCm` en interne.
- Injecter `scale` dans la signature.
- Supprimer le recalcul dans `ingestion_serialize.js:serializeForStorage` et `ingestion.js:_renderRoom`.
- Tests round-trip étendus (ajouter `offset_px` au SAMPLES).

**Phase P2 — Fusion `bbox_abs_px` / `seed_abs_px`**
- Supprimer ces champs. Partout où ils sont utilisés (canonical_io fromStorage/toStorage, editor.js save, init_rvtool re-analyze, ingestion batch re-analyze), lire directement `bbox_px` / `seed_px`.
- Garantir qu'ils ne sont jamais rotés accidentellement.

**Phase P3 — Renommage `original_corridor_face` → `corridor_face_abs`**
- Rename global dans le front + doc.
- Supprimer `corridor_face` stocké (dérivé toujours "south" en canonique, "absolu" au storage).
- Nettoyer la lecture ambiguë `room.original_corridor_face || room.corridor_face` qui a été la cause de plusieurs bugs.

**Phase P4 — Séparation openings/doors dans state**
- Introduire `state.room_doors`. Supprimer `has_door:true` dans state.room_openings.
- Adapter `buildRoomDSL`, `_stateToDsl`, renderRoomElements, `_rvCommitFromState` (sig keys), la logique d'édition CRUD (add window / door / opening).
- Supprimer la combinaison `_lrOpenings.concat(_lrDoors)` dans `enterRoomAmendMode` / `fpRenderEmptyRoom`.
- Supprimer le re-split dans `editor.js save()`.

**Phase P5 — Contrat front/back `/api/floor-plan/match`**
- Frontend envoie en canonique (stoppe le `toStorage` préalable).
- Backend `catalogue_matcher` appelle `canonicalize_room()` sur chaque input avant matching.
- Mettre en cohérence serializeForMatching (simplification : format canonique uniforme avec openings + doors séparés).

**Phase P6 — Nettoyage conversions ad-hoc**
- Supprimer `pointAbsToCanon` (ingestion.js), `_absToCanon2` (editor.js) — utiliser `canonicalIO.rotatePoint` / `rotateRect`.
- Centraliser `_canonicalAngle` dans canonical_io.
- Supprimer les maps `FACE_MAPS` éparpillées.

**Phase P7 — Tests & doc**
- Tests unitaires Node : round-trip rooms complètes (pas juste fragments).
- Spec CANONICAL_STATE.md (remplace CANONICAL_STATE_REFACTOR.md existante) : structure unique documentée, contrats explicites, antipatterns interdits.
- Cleanup `canonical.py` backend : invoquer depuis /api/floor-plan/match ou supprimer si canonicalisation restée côté front.

### 2.6 Estimation

7 phases, découpables en petits commits isolés, chacun testable :
- P1 : 1 journée (changement ciblé canonical_io + tests)
- P2 : 1 journée (suppression champs redondants, grep-and-replace discipliné)
- P3 : 0.5 journée (renommage mécanique)
- P4 : 1.5 journée (refactor state, touche buildRoomDSL / rendering / CRUD)
- P5 : 0.5 journée (contrat explicite, petite modif back + front)
- P6 : 0.5 journée (suppression doublons conversions)
- P7 : 1 journée (doc + tests)

Total : ~6 jours de travail concentré, bien découpé. Sans précipitation.

### 2.7 Bénéfices attendus

- Une seule frontière abs ↔ canon (canonical_io).
- Plus de champs redondants → impossible de se désynchroniser.
- Structure de données uniforme partout → plus de "mais pas là" bugs.
- Contrat front/back documenté → plus de matching faussé silencieusement.
- Les 6 symptômes rencontrés cette session (et autres latents) disparaissent par construction.

## 3. Points ouverts à arbitrer avant démarrage

- **Backend : fournir canonique ou absolu en /api/room/reanalyze ?** Actuellement absolu. Si le frontend standardise en canonique, le backend pourrait accepter canonique directement — mais il faut le convertir pour le pipeline `extract_room_features` qui travaille sur des coords image. Probablement garder absolu au niveau de l'endpoint, canonicaliser en sortie avec le même canonicalIO-equivalent Python (`canonical.py` ressuscité).
- **Versionnage du JSON v3** : est-ce qu'on change le format JSON sur disque ? Actuellement absolu. Si oui, migration des fichiers existants. Recommandation : garder absolu sur disque, canonicaliser au load (comme actuellement via fromStorage). Seul le renommage `original_corridor_face` → `corridor_face_abs` impacterait les JSON.
- **Rotation des `offset_px`** : P1 assume qu'on dispose toujours de `scale` au moment des conversions. C'est vrai dans tous les call sites identifiés (ingState.scale accessible). À confirmer.
