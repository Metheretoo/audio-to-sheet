# Phase 3 — Détection de tonalité et quantization

## Objectif
Implémenter la détection de tonalité (Krumhansl-Schmuckler) et améliorer la quantization avec contexte musical.

## Fichiers concernés
- `v3-specs/phases/tonality_detector.py` — Détection de tonalité
- `backend/quantizer.py` — Quantization avec contexte musical

## Fonctionnalités
1. Détection de tonalité (key + mode) via Krumhansl-Schmuckler
2. Quantization avec durées naturelles (demi-temps, triplets, notes pointées)
3. Gestion des micro-détails (accents, nuances)
4. Lissage des transitions
5. Validation spectrale

## Tests
- Test avec morceau en majeur
- Test avec morceau en mineur
- Test avec demi-temps
- Test avec triplets
- Test avec silences parasites

## Statut
- [x] tonality_detector.py créé et corrigé (ajout de _get_pianochord_corr)
- [x] quantizer.py avec contexte musical
- [ ] Tests unitaires