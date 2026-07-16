# audio-to-sheet — Spécifications V3

> **Dossier de référence pour les agents codeurs.**
> Chaque fichier `.md` de ce dossier est une directive autonome et suffisante pour implémenter une phase du projet.
> Un agent peut prendre en charge une phase sans lire tout le projet à condition de lire :
> 1. Ce `README.md`
> 2. Le fichier de phase qui lui est assigné
> 3. `ARCHITECTURE.md` pour comprendre les interfaces entre modules

---

## Contexte du projet

`audio-to-sheet` est une application web locale qui transcrit un fichier audio (piano) en partition lisible.

**Stack actuelle (V2)**
- Backend : Python / Flask (`backend/app.py`)
- Tempo Map : madmom/librosa (dépendances externes)
- Voice Engine : règles simples (seuils MIDI fixes)
- Quantizer : quantization brute
- Frontend : HTML + JS vanilla

**Problèmes V2 identifiés (à résoudre en V3)**
| Problème | Cause racine | Impact | Gain attendu |
|---|---|---|---|
| Voice Engine peu fiable | Règles simples, pas d'analyse harmonique | 40-50% de notes mal classées | 40-50% |
| Tempo Map dépendances externes | madmom/librosa non installés | Erreurs de tempo | 30-40% |
| Tempo Map drift non corrigé | Fallback IOI identique V1 | Drift sur le long terme | 30-40% |
| Quantization brutale | Pas de contexte musical | Durées artificielles | 35-45% |
| Pas de validation | Pas de tests unitaires | Bugs non détectés | N/A |

**Objectif V3**
- **Gain global : 40-60%** de qualité de la partition
- **100% gratuit et local** (pas de dépendances externes)
- **Pas de régression** par rapport à V2

---

## Structure de ce dossier

```
v3-specs/
├── README.md                    ← Ce fichier (point d'entrée)
├── ARCHITECTURE.md              ← Schéma du pipeline V3 et interfaces entre modules
├── PROGRESS.md                  ← Suivi d'avancement global (à maintenir à jour)
│
├── phases/
│   ├── PHASE-1-voice-engine.md      ← Voice Engine amélioré (40-50% gain)
│   ├── PHASE-2-tempo-map.md         ← Tempo Map pur Python (30-40% gain)
│   ├── PHASE-3-quantizer.md         ← Quantization contextuelle (35-45% gain)
│   ├── PHASE-4-midi-export.md       ← Génération MIDI pur Python
│   ├── PHASE-5-tests-validation.md  ← Tests unitaires et validation
│   ├── PHASE-6-api-rest.md          ← API REST Flask
│   └── PHASE-7-deploiement.md       ← Déploiement et packaging
│
└── references/
    ├── FAISABILITE.md           ← Limites techniques, ce qui est possible / impossible
    └── DEPENDENCIES.md          ← Librairies open source recommandées et pourquoi
```

---

## Ordre d'exécution des phases

```
PHASE 1 → PHASE 2 → PHASE 3 → PHASE 4 → PHASE 5 → PHASE 6 → PHASE 7
```

**Chaque phase doit être intégralement validée et testée avant de passer à la suivante.**

### Dépendances entre phases

| Phase | Prérequis | Notes |
|-------|-----------|-------|
| Phase 1 | Aucune | Cœur du système (détection voix) |
| Phase 2 | Phase 1 | Nécessite notes MIDI brutes de Phase 1 |
| Phase 3 | Phase 2 | Nécessite BPM et subdivisions |
| Phase 4 | Phase 3 | Nécessite notes quantisées |
| Phase 5 | Phase 4 | Tests sur pipeline complet |
| Phase 6 | Phase 5 | API intègre tout le pipeline |
| Phase 7 | Phase 6 | Déploiement de l'application complète |

---

## Règles pour les agents codeurs

1. **Ne jamais modifier les fichiers V2** sans créer d'abord le module V3 correspondant et valider son comportement.
2. **Respecter les interfaces définies dans `ARCHITECTURE.md`** — les contrats de données entre modules sont intangibles.
3. **Chaque nouveau module doit contenir** un bloc `if __name__ == "__main__"` avec un test minimal auto-exécutable.
4. **Les tests unitaires** sont décrits dans chaque fichier de phase. Les écrire avant le code (TDD léger).
5. **Langue** : code et commentaires en français (cohérence avec le projet V2). Noms de variables en anglais.
6. **Garantir la compatibilité** : le module V3 doit être rétrocompatible avec V2 (JSON VexFlow identique).
7. **Performance** : pas de dépendances externes (numpy uniquement, pas madmom/librosa).
8. **Tests** : chaque phase doit inclure des tests sur 50+ morceaux variés pour valider le gain.

---

## Métriques de succès

| Phase | Gain attendu | Métrique de validation |
|-------|--------------|------------------------|
| Phase 1 | 40-50% | 40-50% de notes correctes en LH/RH |
| Phase 2 | 30-40% | 30-40% de BPM corrects, pas de drift |
| Phase 3 | 35-45% | 35-45% de durées naturelles |
| Phase 4 | N/A | MIDI jouable, structure correcte |
| Phase 5 | N/A | 100% des tests verts, 50+ morceaux |
| Phase 6 | N/A | API fonctionnelle, docs à jour |
| Phase 7 | N/A | Installation sans erreur, Docker OK |

**Objectif global** : 40-60% de gain sur la qualité de la partition finale.

---

## État d'avancement

Voir `PROGRESS.md` pour le suivi détaillé de chaque phase.
