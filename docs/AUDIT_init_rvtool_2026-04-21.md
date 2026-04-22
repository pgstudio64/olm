# Audit dette technique — `olm/static/init_rvtool.js`

Date : 2026-04-21 (post-D-135). Fichier ~1344 lignes, module Room amend mode
(resize/CRUD zones, placement ouvertures, re-scan). Audit passif.

---

## 1. Magic numbers

| Ligne | Valeur | Contexte | Constante proposée |
|---|---|---|---|
| 32 | `5` | Snap fin resize room (cm) | `ROOM_RESIZE_SNAP_CM` (isolée, à formaliser) |
| 196 | `10` | Snap placement opening (cm) | `WALL_SNAP_CM` (isolée) |
| 105 | `"#2a9d8f"` | Stroke teal ghost rect | `GHOST_RECT_COLOR` |
| 107 | `"4 4"` | Dash array ghost rect | `GHOST_RECT_DASH` |
| 818 | `100` | Largeur défaut window (cm) | `DEFAULT_WINDOW_WIDTH_CM` |
| 819 / 384 | `90` fallback | Largeur défaut door/opening | Supprimer fallback hard, rely sur `APP_CONFIG` |
| 507 | `10000` | Conversion cm² → m² | `SQ_CM_PER_SQ_M` |
| 1289 | `5` | Multiplicateur Shift+Flèche | `ARROW_KEY_SHIFT_MULTIPLIER` |

## 2. Duplications

### A. Pattern « type-based array lookup » (3 copies identiques)
Lignes 701-703, 724-726, 751-753 — même switch `type ∈ {window, door, ?}` sur 3
arrays du state.

**Action** : helper `_getOpeningArray(type)`.

### B. DSL append/replace redondant
`rvDslAppendExcl` / `rvDslAppendTransparent` / `rvDslReplaceExcl` /
`rvDslDeleteExcl` (L-57-98) répètent la même logique split/find/rejoin.

**Action** : helpers `_findLineIndexByPattern(...)`, `_appendDslLine(...)`.

### C. Resize rectangle par coin (4 branches)
Transparent zone resize L-1012-1031 vs exclusion zone resize L-1157-1176 :
code presque identique pour NW/NE/SW/SE.

**Action** : helper `_resizeRectByHandle(rect, dx, dy, handle, min, roomW, roomD)`.

## 3. Fonctions très longues (à découper)

| Lignes | Fonction | Longueur | Phase |
|---|---|---|---|
| 308-535 | `reanalyzeBtn` handler click | **~227 l.** | setup → fetch → merge → update |
| 641-902 | `rvCvEl` mousedown | **~261 l.** | 11 branches if/else (transpHandle, openingDelete…) |
| 962-1179 | `document` mousemove | **~217 l.** | 9 branches |

**Action priorité 1** : extraire les branches mousedown/mousemove en
`_handleXxxMousedown(e, p)` chacun ~30 lignes. Refactor mécanique, risque bas
(peu de logique cross-handler).

## 4. Logique fragile

- **L-509** : `window.fpOverlay.pxPerCm` accédé sans null-check → risque NRE
  si l'overlay n'est pas encore initialisé. Ajouter garde.
- **L-791-794** : snapshot profond du state pour room resize via
  `JSON.stringify` — clone `windows/openings/doors/exclusions` mais
  **pas les transparents** ; à vérifier si c'est intentionnel.
- **L-1110-1140** : le shift appliqué aux features pendant room resize ne
  touche pas les zones transparentes → décalage visuel potentiel.
- **L-1187, 1193, 1199** : appels `_rvCommitFromState()` et
  `rvApplyDslAsync()` sans try/catch → si le DSL parse échoue, le state UI
  diverge silencieusement.

## 5. Schéma `rvTool` non documenté

`rvTool = { mode, drawStart, selectedIndex, dragOffset, … }` — 8+
sous-attributs (`openingMove`, `openingResize`, `roomResizeStart`,
`transpDrag`, `transpResize`, etc.) ajoutés au fil des features sans contrat
écrit. Lecture difficile. Documenter L-14 en un commentaire structuré.

## 6. Redéfinitions fréquentes

- `var W/D = state.room_width_cm/depth_cm` → ~12 sites locaux. Accepté
  (scopes séparés) mais cosmétique.
- `var ov2 = window.fpOverlay` (L-509) : alias temporaire pour 2 accès.
  Inliner `window.fpOverlay.pxPerCm` directement.

---

## Top 5 priorités recommandées

| # | Action | Impact | Effort | Risque |
|---|---|---|---|---|
| 1 | Extraire les branches mousedown/mousemove en sous-handlers nommés (`_handleXxxMousedown/_Mousemove`) | très haut (lisibilité) | moyen | bas |
| 2 | Helper `_getOpeningArray(type)` + `_resizeRectByHandle(...)` | moyen | bas | très bas |
| 3 | try/catch + null-check `window.fpOverlay` autour de `rvApplyDslAsync()` et `.pxPerCm` | haut (robustesse D-135-like) | bas | très bas |
| 4 | Bloc CONSTANTS (`GHOST_RECT_COLOR/DASH`, `DEFAULT_WINDOW_WIDTH_CM`, `SQ_CM_PER_SQ_M`, `ARROW_KEY_SHIFT_MULTIPLIER`) | moyen | bas | très bas |
| 5 | Documenter schéma `rvTool` en commentaire structuré | bas | très bas | très bas |

Items 2, 4, 5 actionnables en session autonome (risque < bas). Item 1 à faire
avec validation step-by-step. Item 3 préventif, aligné sur le pattern D-135
rider (mutations d'état fragile).
