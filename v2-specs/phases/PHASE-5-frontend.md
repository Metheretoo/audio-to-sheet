# PHASE 5 — Adaptations Frontend

> **Agent assigné** : à définir
> **Statut** : `[ ]` À faire
> **Durée estimée** : 2-3h
> **Prérequis** : Phase 4 complète (le backend renvoie le nouveau JSON)
> **Fichiers à modifier** : `frontend/js/renderer.js`, `frontend/index.html`
> **Fichiers à ne PAS modifier** : `frontend/js/editor.js`, `frontend/js/app.js` (sauf indication)

---

## Objectif

Adapter l'interface utilisateur pour exploiter les nouvelles informations produites par le pipeline V2 : **tempo dynamique**, **mesure auto-détectée**, **indicateur de confiance**, et permettre les **ajustements post-transcription** sans relancer l'analyse complète.

---

## Contexte : ce que le backend V2 envoie maintenant

Le JSON retourné par `/api/transcribe` est enrichi (nouveaux champs optionnels, rétrocompatibles) :

```json
{
  "tempo": 118,
  "timeSignature": [4, 4],
  "keySignature": "G",
  "totalMeasures": 12,
  "measures": [...],

  // Champs NOUVEAUX ajoutés par V2 :
  "tempoMapMethod": "madmom",
  "tempoConfidence": 0.87,
  "tempoRange": [112, 126],
  "detectedMeter": [4, 4],
  "warnings": ["Tempo instable détecté entre 00:12 et 00:18"]
}
```

> Ces champs sont **optionnels** : si le backend ne les envoie pas, le frontend doit fonctionner normalement (rétrocompatibilité V1 garantie).

---

## Tâche 5.1 — Affichage dynamique du tempo détecté

**Fichier** : `frontend/index.html`

Localiser le bloc affichant le tempo (actuellement un champ input statique) et ajouter :

```html
<!-- Indicateur de tempo détecté automatiquement -->
<div id="tempo-detected-info" class="info-badge" style="display:none;">
  <span id="tempo-detected-value">-- BPM</span>
  <span id="tempo-method-badge" class="badge">--</span>
  <span id="tempo-confidence-bar" title="Confiance de détection"></span>
</div>
```

**Fichier** : `frontend/js/app.js` (section de réception de la réponse API)

Après réception du JSON de transcription, appeler :
```javascript
if (scoreData.tempoMapMethod) {
    updateTempoDisplay(scoreData);
}
```

**Nouvelle fonction à ajouter dans `app.js`** :
```javascript
function updateTempoDisplay(scoreData) {
    const infoDiv = document.getElementById('tempo-detected-info');
    if (!infoDiv) return;

    // BPM affiché
    document.getElementById('tempo-detected-value').textContent =
        `${scoreData.tempo} BPM`;

    // Badge méthode : 'madmom' → vert, 'librosa_advanced' → orange, 'fallback' → rouge
    const methodBadge = document.getElementById('tempo-method-badge');
    const methodColors = {
        'madmom':           { label: 'TempoMap Pro', color: '#2ecc71' },
        'librosa_advanced': { label: 'TempoMap Standard', color: '#f39c12' },
        'fallback':         { label: 'Estimation basique', color: '#e74c3c' }
    };
    const m = methodColors[scoreData.tempoMapMethod] || { label: scoreData.tempoMapMethod, color: '#95a5a6' };
    methodBadge.textContent = m.label;
    methodBadge.style.backgroundColor = m.color;

    // Plage de tempo si disponible
    if (scoreData.tempoRange) {
        infoDiv.title = `Plage détectée : ${scoreData.tempoRange[0]}–${scoreData.tempoRange[1]} BPM`;
    }

    infoDiv.style.display = 'flex';
}
```

---

## Tâche 5.2 — Affichage de la mesure auto-détectée

**Fichier** : `frontend/index.html`

Ajouter un badge à côté du sélecteur de mesure existant :

```html
<span id="meter-auto-badge" class="auto-detected-badge" style="display:none;">
  Auto-détecté ✓
</span>
```

**Fichier** : `frontend/js/app.js`

```javascript
// Après réception JSON :
if (scoreData.detectedMeter) {
    const [num, den] = scoreData.detectedMeter;
    // Mettre à jour le sélecteur de mesure si l'utilisateur n'a pas forcé une valeur
    const timeSigSelect = document.getElementById('time-sig-select');
    if (timeSigSelect && !timeSigSelect.dataset.userOverride) {
        timeSigSelect.value = `${num}/${den}`;
        document.getElementById('meter-auto-badge').style.display = 'inline';
    }
}
```

---

## Tâche 5.3 — Slider de tempo post-transcription

Permettre à l'utilisateur d'ajuster le tempo **sans relancer la transcription**.

> **Important** : ajuster le tempo ne re-analyse PAS l'audio. Il modifie uniquement la valeur `tempo` dans le `scoreData` côté frontend et met à jour l'affichage.

**Fichier** : `frontend/index.html` — ajouter dans le panneau de contrôle :

```html
<div id="tempo-adjust-panel" class="control-panel" style="display:none;">
  <label for="tempo-slider">Ajuster le tempo :</label>
  <input type="range" id="tempo-slider" min="40" max="240" step="1" value="120">
  <output id="tempo-slider-output">120 BPM</output>
  <button id="tempo-slider-reset">Réinitialiser</button>
</div>
```

**Fichier** : `frontend/js/app.js` — comportement du slider :

```javascript
let originalTempo = 120;

function initTempoSlider(detectedTempo) {
    const panel  = document.getElementById('tempo-adjust-panel');
    const slider = document.getElementById('tempo-slider');
    const output = document.getElementById('tempo-slider-output');
    const reset  = document.getElementById('tempo-slider-reset');

    if (!panel) return;
    originalTempo = detectedTempo;
    slider.value  = detectedTempo;
    output.textContent = `${detectedTempo} BPM`;
    panel.style.display = 'block';

    slider.addEventListener('input', () => {
        const newTempo = parseInt(slider.value);
        output.textContent = `${newTempo} BPM`;
        // Mettre à jour le scoreData sans re-transcrire
        if (window.currentScoreData) {
            window.currentScoreData.tempo = newTempo;
            // Demander au renderer de se rafraîchir avec le nouveau tempo
            if (typeof window.rerenderScore === 'function') {
                window.rerenderScore(window.currentScoreData);
            }
        }
    });

    reset.addEventListener('click', () => {
        slider.value = originalTempo;
        output.textContent = `${originalTempo} BPM`;
        slider.dispatchEvent(new Event('input'));
    });
}
```

---

## Tâche 5.4 — Affichage des warnings

**Fichier** : `frontend/index.html` — zone d'alertes :

```html
<div id="transcription-warnings" class="warnings-panel" style="display:none;">
  <h4>⚠ Avertissements de transcription</h4>
  <ul id="warnings-list"></ul>
</div>
```

**Fichier** : `frontend/js/app.js` :

```javascript
function displayWarnings(warnings) {
    if (!warnings || warnings.length === 0) return;
    const panel = document.getElementById('transcription-warnings');
    const list  = document.getElementById('warnings-list');
    if (!panel || !list) return;

    list.innerHTML = '';
    warnings.forEach(msg => {
        const li = document.createElement('li');
        li.textContent = msg;
        list.appendChild(li);
    });
    panel.style.display = 'block';
}
```

---

## Tâche 5.5 — Adaptation `renderer.js` (tempo variable)

> **Priorité basse** — à faire uniquement si le renderer utilise `scoreData.tempo` pour calculer des espacements visuels.

**Fichier** : `frontend/js/renderer.js`

Vérifier si `renderer.js` utilise `scoreData.tempo` pour autre chose que l'affichage du BPM. Si oui, s'assurer que le changement de tempo via le slider (Tâche 5.3) déclenche bien un re-rendu complet.

Exposer une fonction globale :
```javascript
// Dans renderer.js
window.rerenderScore = function(scoreData) {
    // Nettoyer l'affichage actuel
    clearRenderedScore();
    // Re-rendre avec les nouvelles données
    renderScore(scoreData);
};
```

---

## Styles CSS à ajouter

**Fichier** : `frontend/css/` (fichier existant à compléter)

```css
/* Badges et indicateurs V2 */
.info-badge {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 4px 10px;
    background: rgba(255,255,255,0.08);
    border-radius: 6px;
    font-size: 0.85rem;
}

.badge {
    padding: 2px 8px;
    border-radius: 12px;
    color: white;
    font-size: 0.75rem;
    font-weight: 600;
}

.auto-detected-badge {
    font-size: 0.75rem;
    color: #2ecc71;
    font-weight: 600;
}

.warnings-panel {
    background: rgba(231, 76, 60, 0.12);
    border-left: 3px solid #e74c3c;
    padding: 10px 14px;
    border-radius: 4px;
    margin-top: 10px;
}

.warnings-panel h4 {
    margin: 0 0 6px;
    color: #e74c3c;
    font-size: 0.9rem;
}

.warnings-panel ul {
    margin: 0;
    padding-left: 18px;
    font-size: 0.82rem;
    color: #c0392b;
}

/* Slider tempo */
#tempo-adjust-panel {
    display: flex;
    align-items: center;
    gap: 10px;
    margin-top: 8px;
}

#tempo-slider {
    flex: 1;
    max-width: 180px;
}

#tempo-slider-output {
    min-width: 60px;
    font-weight: 600;
}
```

---

## Tests de validation

| Test | Description | Attendu |
|---|---|---|
| 5.1 | Charger une transcription V2 | Badge tempo visible avec la méthode et la couleur |
| 5.1 | Charger une transcription V1 (ancienne) | Aucun badge visible (rétrocompatibilité) |
| 5.2 | Transcription en 3/4 | Sélecteur de mesure mis à jour + badge "Auto-détecté" |
| 5.3 | Déplacer le slider tempo | Valeur BPM mise à jour en temps réel, partition rafraîchie |
| 5.3 | Clic Reset | Retour au tempo original |
| 5.4 | Backend retourne `warnings` | Panel d'alertes visible avec les messages |
| 5.4 | Backend sans `warnings` | Panel masqué |
