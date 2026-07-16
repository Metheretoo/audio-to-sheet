# Faisabilité — Limites techniques du projet V2

> Ce document répond honnêtement à la question : **"jusqu'où peut-on aller ?"**
> Il doit être lu par tout agent avant de commencer une phase, pour calibrer ses ambitions.

---

## 🟢 Ce qui est réalisable de façon fiable

### 1. Suppression du drift temporel
**Niveau de confiance : élevé (90%)**

Le drift est causé par une division linéaire avec un tempo fixe. L'implémentation d'une `TempoMap` (Phase 1) résout ce problème mathématiquement. Si `madmom` est disponible et fonctionne bien sur le fichier audio, le drift sera quasi nul.

**Limite** : Sur des morceaux avec des changements de tempo très brusques (arrêts complets, pauses), la TempoMap peut perdre le fil. Solution : détecter ces pauses et segmenter la TempoMap.

---

### 2. Stabilité de la détection de tempo
**Niveau de confiance : élevé (85%)**

`madmom` avec `RNNBeatProcessor` est entraîné sur de la musique réelle et gère bien les variations de tempo locales. La détection du BPM global sera plus stable et cohérente entre un morceau entier et un extrait.

**Limite** : Sur de la musique très libre (rubato extrême, musique contemporaine), même madmom peut osciller. L'objectif est ±10% de stabilité, pas la perfection.

---

### 3. Écriture musicale plus propre (moins de micro-notes)
**Niveau de confiance : élevé (80%)**

La quantification sur grille de beats (pas sur secondes) élimine les micro-silences parasites. L'inférence par IOI local réduit drastiquement les notes "fantômes".

**Limite** : Des notes très courtes détectées par `piano_transcription_inference` (harmoniques, bruits de mécanisme) peuvent encore passer. Le filtre `CONFIDENCE_MIN` aide mais ne suffit pas toujours.

---

### 4. Détection automatique de la mesure (4/4 vs 3/4)
**Niveau de confiance : moyen-élevé (70%)**

`madmom` avec `DBNDownBeatTrackingProcessor` peut détecter les downbeats et en déduire la mesure. Fonctionne bien sur les rythmes réguliers.

**Limite** : Les mesures composées (6/8, 12/8) ou les changements de mesure en cours de morceau sont difficiles à détecter automatiquement. Prévoir un override manuel dans l'interface.

---

### 5. Amélioration de la séparation main gauche / droite
**Niveau de confiance : moyen (65%)**

L'approche multi-facteurs (registre + contour + position dans l'accord) sera meilleure que le seuil fixe MIDI 57. Sur la grande majorité des passages, le résultat sera correct.

**Limite** : Le croisement des mains (technique pianistique où la main gauche passe au-dessus de la droite) est impossible à détecter sans modèle ML spécifique. Ces passages resteront à corriger manuellement.

---

## 🟡 Ce qui sera amélioré mais restera imparfait

### 6. Gestion des accords enrichis (7ème, 9ème, altérés)
**Niveau de confiance : moyen (55%)**

La détection des fondamentales d'accords (Phase 3) améliore l'attribution main gauche/droite. Mais la détection précise de l'harmonie (est-ce un Dm7b5 ou un Fmaj7/A ?) est hors scope. La partition montrera les notes correctes mais pas nécessairement l'analyse harmonique "propre".

---

### 7. Gestion du rubato et des ritardandos
**Niveau de confiance : moyen (50%)**

La TempoMap "suit" le tempo réel, donc les notes seront mieux placées sur les temps même dans un ritardando. Mais la notation symbolique du ritardando (écrire "rit." ou "rall." sur la partition) n'est pas implémentée — il n'y a pas assez d'information pour distinguer un ritardando délibéré d'une simple variation de tempo.

**Ce qu'on peut faire** : détecter les zones où le tempo local ralentit de >15% sur 4+ beats et y ajouter un commentaire/flag pour que le musicien sache où regarder.

---

### 8. Correction des erreurs du transcripteur IA
**Niveau de confiance : faible-moyen (40%)**

Le module `piano_transcription_inference` a un taux d'erreur d'environ 3-6% sur les notes (F1 score ~0.97). Ces fausses détections (notes fantômes ou notes manquées) ne sont pas corrigeables sans ré-entraîner le modèle. Le pipeline V2 filtre les fausses détections les plus évidentes (courtes durées, faible amplitude) mais pas toutes.

---

## 🔴 Ce qui est quasi impossible avec cette approche

### 9. Zéro retouche manuelle
**Faisabilité : non (0%)**

La transcription automatique piano → partition n'existe pas encore à ce niveau de perfection, même dans les solutions commerciales. L'objectif réaliste est de **réduire les retouches de 70-80%**, pas de les éliminer.

Raisons :
- Les modèles de transcription font ~3-5% d'erreurs sur les notes
- Les ornements (trilles, mordants, gruppetti) sont quasi impossibles à transcrire
- Les liaisons de phrase et articulations (legato, staccato) sont perdues
- La mise en page musicale (groupements de croches, liaisons de prolongation) nécessite une relecture humaine

---

### 10. Gestion du croisement des mains
**Faisabilité : très faible (10%)**

Quand la main gauche joue une mélodie dans le registre aigu, ou que la main droite descend dans les graves, il est impossible de détecter ça sans vidéo ou capteurs sur les mains. L'algorithme de Phase 3 se trompera sur ces passages.

---

### 11. Notation des ornements
**Faisabilité : nulle**

Trilles, mordants, appoggiatures, arpèges de pédale — ces éléments sont fondus dans le signal audio et exigeraient un modèle ML dédié + données annotées qui n'existent pas en open source.

---

### 12. Ritardandos symboliques avec notation "rit."
**Faisabilité : très faible**

Détecter une tendance de ralentissement est possible. Mais décider si c'est un "rit." (notation musicale) ou juste une interprétation libre est subjectif et non-automatisable de façon fiable.

---

## Comparaison : V1 vs V2 vs Solution commerciale

| Critère | V1 (actuel) | V2 (objectif) | Solution commerciale |
|---|---|---|---|
| Drift temporel | Présent dès mesure 2-3 | Supprimé | Supprimé |
| Stabilité tempo | ±30% selon l'extrait | ±10% | ±5% |
| Écriture propre | 3-4/10 | 6-7/10 | 8-9/10 |
| Séparation LH/RH | 5/10 | 7/10 | 8/10 |
| Gestion rubato | Absente | Partielle | Bonne |
| Ornements | Absents | Absents | Partiels |
| Retouches nécessaires | ~70% des mesures | ~25% des mesures | ~10% des mesures |

> **Résumé** : La V2 fait passer la partition d'un état "illisible sans correction majeure" à "utilisable avec corrections mineures". C'est un gain réel et significatif pour un projet open source.

---

## Recommandations pour aller encore plus loin (V3 éventuelle)

Si la V2 est satisfaisante et que le projet continue :

1. **Intégrer Omnizart** (note detection plus fine, gère mieux les basses)
2. **Utiliser un modèle de séparation des mains** (piano-hands-separation, projet GitHub en développement)
3. **Ajouter une interface de correction rapide** : clic sur une note pour la déplacer d'une voix à l'autre
4. **Export MusicXML** via `music21` pour import dans MuseScore / Sibelius (édition pro)
