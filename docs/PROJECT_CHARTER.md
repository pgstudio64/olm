# PROJECT_CHARTER.md — Office Layout Optimizer (OLO)

**Version** : 1.0
**Date** : 2026-03-09
**Statut** : Approuvé

---

## 1. Vision et objectif

Générer automatiquement un plan d'aménagement de bureau optimisé au format PDF à partir d'un plan raster et d'une description JSON des pièces, en respectant les contraintes légales, les recommendations AFNOR NF X35-102 et INRS ED950.

---

## 2. Périmètre

### In scope
- Lecture d'une image raster (PNG, JPEG, TIFF) d'un plan d'étage
- Lecture d'un fichier JSON décrivant les pièces (polygones, affectations)
- Placement automatique des postes de travail sur grille discrète en optimisant le nombre de personnes par bureau
- Respect des contraintes et recommendations (surface, dégagements, circulations)
- Rotation des postes (0°, 90°, 180°, 270°)
- Cache à fingerprint géométrique (SHA-256)
- Génération d'un PDF superposant le plan et les postes placés
- Gnération d'un second PDF contenant dans des tableaux la description des pièces, de l'aménagement proposé pour chaque pièce, des métriques (nombre de personnes, surface par personne) et des scores d'agrément de la pièce et de chacun des postes, tableau de synthèse


### Out of scope (POC)
- Interface graphique interactive
- Import DWG / IFC / CAD
- Gestion multi-étages
- Optimisation multi-objectifs avancée (IA, ML)
- Connexion réseau ou service cloud
- Export vers d'autres formats (DXF, SVG, Excel)

---

## 3. Contraintes

| Type | Contrainte |
|---|---|
| Réglementaire | Contraintes de sécurité pour l'évacuation des personnes |
| Normative | Respect des recommandations AFNOR NF X35-102 |
| Normative | Respect des recommandations INRS ED 950 hors surface par personne |
| Technique | Python 3.10+, local only, pas de réseau |
| Interface | CLI uniquement (pas de GUI) |
| Performance | Plan 1 000 m² traité en < 30 secondes |
| Reproductibilité | Même entrée → même sortie |

---

## 4. Critères de succès

- Le PDF est généré sans erreur à partir des entrées valides
- Les postes placés respectent toutes les contraintes et recommandations (vérifiable visuellement)
- Le cache évite le recalcul à la deuxième exécution identique (< 1 s)
- Couverture de tests > 80 % sur les modules `geometry/` et `placement/`
- La CLI accepte `--plan`, `--rooms`, `--output` et produit le PDF attendu

---

## 5. Parties prenantes et rôles

| Rôle | Responsabilité |
|---|---|
| Product Owner | Définir les exigences, valider le POC |
| Développeur (assisté IA) | Implémenter, tester, documenter |
| Claude (LLM) | Générer le code module par module selon SDS + SRS |

---

## 6. Jalons du POC

| Phase | Description | Critère de complétion |
|---|---|---|
| Phase 0 — Setup | Environnement, structure, CI locale | `pytest` passe à vide |
| Phase 1 — Models | Entités métier (dataclasses) | Tests unitaires verts |
| Phase 2 — Ingestion | Lecture image + JSON | Tests TC-EF01 et TC-EF02 verts |
| Phase 3 — Geometry | Grille, fingerprint, transforms | Tests TC-EF03, TC-EF06, TC-EF07 verts |
| Phase 4 — Placement | Contraintes AFNOR + solver + cache | Tests TC-EF04, TC-EF05, TC-EF07 verts |
| Phase 5 — Rendering | Superposition + fichiers PDF | Tests TC-EF08, TC-EF09 verts |
| Phase 6 — Intégration | CLI end-to-end | Test système golden file vert |
| Phase 7 — POC validé | Revue qualité + démo | README complet, démo fonctionnelle |

---

## 7. Références

- AFNOR NF X35-102 — Conception ergonomique des espaces de travail en bureaux
- INRS ED 950 - Conception des lieux et des situations de travail
- [SRS.md](SRS.md) — Spécification des exigences
- [SDS.md](SDS.md) — Spécification de conception
- [TEST_PLAN.md](TEST_PLAN.md) — Plan de test
