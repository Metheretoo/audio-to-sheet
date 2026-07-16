/**
 * app.js — Logique principale de l'application AudioScore
 *
 * Responsabilités :
 *  - Gestion upload (drag & drop + sélection)
 *  - Appel de l'API Flask (/api/transcribe/start + SSE /api/transcribe/progress/<job_id>)
 *  - Affichage de la progression TEMPS RÉEL par étapes
 *  - Câblage de la barre d'outils (éditeur)
 *  - Export PDF (impression navigateur) et MIDI (API)
 *  - Raccourcis clavier
 *  - Toasts de notification
 */

'use strict';

/* ═══════════════════════════════════════════════════════════════════════════
   Initialisation
   ═══════════════════════════════════════════════════════════════════════════ */
let renderer = null;
let editor = null;
let player = null;
let currentJobId = null;
let currentEventSource = null;

document.addEventListener('DOMContentLoaded', () => {
  /* Notification onglet (alerte de fin) */
  window.originalDocumentTitle = document.title || 'AudioScore';
  window.addEventListener('focus', () => {
    if (document.title !== window.originalDocumentTitle) {
      document.title = window.originalDocumentTitle;
    }
  });

  /* Vérification VexFlow */
  if (typeof Vex === 'undefined' || !Vex.Flow) {
    showToast(
      '❌ VexFlow introuvable. Vérifiez que start.bat a bien téléchargé le fichier.',
      'error', 8000
    );
    return;
  }

  renderer = new ScoreRenderer('score-container');
  editor = new ScoreEditor(renderer);

  initUploadZone();
  initThresholdSlider();
  initTranscriptionOptions();
  initToolbar();
  initKeyboardShortcuts();
  fetchDeviceInfo();
});

/* ═══════════════════════════════════════════════════════════════════════════
   Détection de la carte graphique
   ═══════════════════════════════════════════════════════════════════════════ */
async function fetchDeviceInfo() {
  const badge = document.getElementById('device-badge');
  const icon = document.getElementById('device-icon');
  const label = document.getElementById('device-label');
  if (!badge) return;

  try {
    const res = await fetch('/api/device');
    const data = await res.json();

    const device = data.device_type || 'unknown';
    const name = data.device_name || device.toUpperCase();

    // Icônes selon le type de device
    const icons = { cuda: '🟢', mps: '🔵', cpu: '🟡', unknown: '🔴' };
    icon.textContent = icons[device] ?? '⚙️';
    label.textContent = name;

    // Classe CSS colorée
    badge.classList.remove('device-cuda', 'device-mps', 'device-cpu', 'device-unknown');
    badge.classList.add(`device-${device}`);

    // Tooltip détaillé
    const labels = { cuda: 'NVIDIA CUDA', mps: 'Apple Metal (MPS)', cpu: 'Processeur (CPU)', unknown: 'Inconnu' };
    badge.title = `Accélérateur IA : ${labels[device] ?? device} — ${name}`;

  } catch {
    icon.textContent = '⚙️';
    label.textContent = 'GPU inconnu';
    badge.classList.add('device-unknown');
    badge.title = 'Impossible de contacter le backend';
  }
}


/* ═══════════════════════════════════════════════════════════════════════════
   Zone d'upload
   ═══════════════════════════════════════════════════════════════════════════ */
function initUploadZone() {
  const dropZone = document.getElementById('drop-zone');
  const fileInput = document.getElementById('file-input');
  const transBtn = document.getElementById('btn-transcribe');
  const filenameEl = document.getElementById('selected-filename');

  let selectedFile = null;

  /* Sélection via l'input */
  fileInput.addEventListener('change', (e) => {
    const file = e.target.files[0];
    if (file) selectFile(file);
  });

  /* Clic sur la drop-zone */
  dropZone.addEventListener('click', (e) => {
    if (e.target.id !== 'file-label' && !e.target.closest('#file-label')) {
      fileInput.click();
    }
  });

  dropZone.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' || e.key === ' ') fileInput.click();
  });

  /* Drag & drop */
  ['dragenter', 'dragover'].forEach(ev => {
    dropZone.addEventListener(ev, (e) => {
      e.preventDefault();
      dropZone.classList.add('dragover');
    });
  });

  ['dragleave', 'drop'].forEach(ev => {
    dropZone.addEventListener(ev, (e) => {
      e.preventDefault();
      dropZone.classList.remove('dragover');
    });
  });

  dropZone.addEventListener('drop', (e) => {
    const file = e.dataTransfer.files[0];
    if (file) selectFile(file);
  });

  function selectFile(file) {
    const ext = file.name.split('.').pop().toLowerCase();
    if (!['mp3', 'wav', 'flac'].includes(ext) &&
      !file.type.includes('audio')) {
      showToast('⚠️ Veuillez sélectionner un fichier MP3, WAV ou FLAC.', 'error');
      return;
    }
    selectedFile = file;
    filenameEl.textContent = `📁 ${file.name}  (${formatSize(file.size)})`;
    transBtn.disabled = false;
  }

  /* Bouton "Transcrire" */
  transBtn.addEventListener('click', () => {
    if (!selectedFile) return;
    startTranscription(selectedFile);
  });

  /* Bouton "Nouveau fichier" */
  document.getElementById('btn-new-upload')?.addEventListener('click', () => {
    if (player) player.stop();
    showSection('upload');
    selectedFile = null;
    fileInput.value = '';
    filenameEl.textContent = 'Aucun fichier sélectionné';
    transBtn.disabled = true;
    currentJobId = null;
    window.currentScoreData = null;
    // Réinitialiser les blocs V2
    const timeSigSel = document.getElementById('time-sig');
    if (timeSigSel) delete timeSigSel.dataset.userOverride;
    const meterBadge = document.getElementById('meter-auto-badge');
    if (meterBadge) meterBadge.style.display = 'none';
    const tempoInfo = document.getElementById('tempo-detected-info');
    if (tempoInfo) tempoInfo.style.display = 'none';
    const sliderPanel = document.getElementById('tempo-adjust-panel');
    if (sliderPanel) sliderPanel.style.display = 'none';
    const warnPanel = document.getElementById('transcription-warnings');
    if (warnPanel) warnPanel.style.display = 'none';
  });
}

/* ═══════════════════════════════════════════════════════════════════════════
   Slider de seuil
   ═══════════════════════════════════════════════════════════════════════════ */
function initThresholdSlider() {
  const slider = document.getElementById('onset-threshold');
  const display = document.getElementById('threshold-display');
  if (!slider || !display) return;
  slider.addEventListener('input', () => {
    display.textContent = parseFloat(slider.value).toFixed(2);
  });
}

/* ═══════════════════════════════════════════════════════════════════════════
   Options de transcription
   ═══════════════════════════════════════════════════════════════════════════ */
function initTranscriptionOptions() {
  const hqCheckbox = document.getElementById('hq-piano-mode');
  let _updatingFromPresetMatch = false; // Guard against cascade
  const presetBtns = document.querySelectorAll('.preset-btn');

  // Elements advanced settings
  const useDemucsCb = document.getElementById('use-demucs');
  const removeShortCb = document.getElementById('remove-short-notes');
  const minNoteInput = document.getElementById('min-note-duration');
  const mergeNearCb = document.getElementById('merge-near-notes');
  const mergeGapInput = document.getElementById('merge-gap-ms');
  const splitHandsCb = document.getElementById('split-hands');
  const detectTempoCb = document.getElementById('detect-tempo');
  const detectMeterCb = document.getElementById('detect-meter');
  const detectKeyCb = document.getElementById('detect-key');
  const enableRubato = document.getElementById('enable-rubato');
  const enableTriplets = document.getElementById('enable-triplets');
  const showChordsCb = document.getElementById('show-chords');
  const thresholdSlider = document.getElementById('onset-threshold');

  function getTranscriberValue() {
    const radio = document.querySelector('input[name="transcriber"]:checked');
    return radio ? radio.value : 'piano_transcription';
  }

  function setTranscriberValue(val) {
    const radio = document.querySelector(`input[name="transcriber"][value="${val}"]`);
    if (radio) radio.checked = true;
  }

  function getQuantizationValue() {
    const radio = document.querySelector('input[name="quantization"]:checked');
    return radio ? radio.value : 'standard';
  }

  function setQuantizationValue(val) {
    const radio = document.querySelector(`input[name="quantization"][value="${val}"]`);
    if (radio) radio.checked = true;
  }

  function applyPreset(presetName) {
    presetBtns.forEach(btn => {
      if (btn.dataset.preset === presetName) {
        btn.classList.add('active');
      } else {
        btn.classList.remove('active');
      }
    });

    if (presetName === 'rapide') {
      setTranscriberValue('basic_pitch');
      if (useDemucsCb) useDemucsCb.checked = false;
      setQuantizationValue('light');
      if (removeShortCb) removeShortCb.checked = false;
      if (mergeNearCb) mergeNearCb.checked = false;
      if (splitHandsCb) splitHandsCb.checked = false;
      if (detectTempoCb) detectTempoCb.checked = false;
      if (detectKeyCb) detectKeyCb.checked = false;
      if (enableRubato) enableRubato.checked = false;
      if (enableTriplets) enableTriplets.checked = false;
      if (thresholdSlider) thresholdSlider.value = 0.50;
    } else if (presetName === 'equilibre') {
      setTranscriberValue('piano_transcription');
      if (useDemucsCb) useDemucsCb.checked = false;
      setQuantizationValue('standard');
      if (removeShortCb) removeShortCb.checked = false;
      if (minNoteInput) minNoteInput.value = 20;
      if (mergeNearCb) mergeNearCb.checked = false;
      if (mergeGapInput) mergeGapInput.value = 10;
      if (splitHandsCb) splitHandsCb.checked = true;
      if (detectTempoCb) detectTempoCb.checked = true;
      if (detectKeyCb) detectKeyCb.checked = true;
      if (enableRubato) enableRubato.checked = false;
      if (enableTriplets) enableTriplets.checked = false;
      if (thresholdSlider) thresholdSlider.value = 0.50;
    } else if (presetName === 'classique') {
      setTranscriberValue('piano_transcription');
      if (useDemucsCb) useDemucsCb.checked = false;
      setQuantizationValue('light');
      if (removeShortCb) removeShortCb.checked = false;
      if (minNoteInput) minNoteInput.value = 20;
      if (mergeNearCb) mergeNearCb.checked = false;
      if (mergeGapInput) mergeGapInput.value = 10;
      if (splitHandsCb) splitHandsCb.checked = true;
      if (detectTempoCb) detectTempoCb.checked = true;
      if (detectKeyCb) detectKeyCb.checked = true;
      if (enableRubato) enableRubato.checked = true;
      if (enableTriplets) enableTriplets.checked = true;
      if (thresholdSlider) thresholdSlider.value = 0.25;
    } else if (presetName === 'studio') {
      setTranscriberValue('piano_transcription');
      if (useDemucsCb) useDemucsCb.checked = true;
      setQuantizationValue('standard');
      if (removeShortCb) removeShortCb.checked = false;
      if (minNoteInput) minNoteInput.value = 20;
      if (mergeNearCb) mergeNearCb.checked = false;
      if (mergeGapInput) mergeGapInput.value = 10;
      if (splitHandsCb) splitHandsCb.checked = true;
      if (detectTempoCb) detectTempoCb.checked = true;
      if (detectKeyCb) detectKeyCb.checked = true;
      if (enableRubato) enableRubato.checked = true;
      if (enableTriplets) enableTriplets.checked = true;
      if (thresholdSlider) thresholdSlider.value = 0.50;
    } else if (presetName === 'jazz') {
      setTranscriberValue('piano_transcription');
      if (useDemucsCb) useDemucsCb.checked = false;
      setQuantizationValue('heavy'); // Arrondi à la croche
      if (removeShortCb) removeShortCb.checked = false;
      if (minNoteInput) minNoteInput.value = 20;
      if (mergeNearCb) mergeNearCb.checked = false;
      if (mergeGapInput) mergeGapInput.value = 10;
      if (splitHandsCb) splitHandsCb.checked = true;
      if (detectTempoCb) detectTempoCb.checked = true;
      if (detectKeyCb) detectKeyCb.checked = true;
      if (enableRubato) enableRubato.checked = false;
      if (enableTriplets) enableTriplets.checked = false;
      if (thresholdSlider) thresholdSlider.value = 0.50;
    }

    // Mettre à jour l'affichage du seuil
    const display = document.getElementById('threshold-display');
    if (display && thresholdSlider) {
      display.textContent = parseFloat(thresholdSlider.value).toFixed(2);
    }

    toggleManualFields();
  }

  function toggleManualFields() {
    const tempoOverrideItem = document.getElementById('tempo-override-item');
    if (tempoOverrideItem) {
      if (detectTempoCb && detectTempoCb.checked) {
        tempoOverrideItem.style.opacity = '0.5';
        tempoOverrideItem.style.pointerEvents = 'none';
        const tempoInput = document.getElementById('tempo-override');
        if (tempoInput) tempoInput.value = '';
      } else {
        tempoOverrideItem.style.opacity = '1';
        tempoOverrideItem.style.pointerEvents = 'auto';
      }
    }
  }

  // ── Affichage pédale / accords : bascule instantanée, sans re-transcrire ──
  // (l'utilisateur peut activer/désactiver ces annotations à tout moment,
  // y compris après une transcription déjà terminée)
  const showPedalCb = document.getElementById('show-pedal');
  const showChordsCbToggle = document.getElementById('show-chords');

  function refreshDisplayToggles() {
    if (!renderer) return;
    renderer.showPedals = showPedalCb ? showPedalCb.checked : true;
    renderer.showChordSymbols = showChordsCbToggle ? showChordsCbToggle.checked : false;
    if (window.currentScoreData) {
      renderer.render(window.currentScoreData);
    }
  }
  if (showPedalCb) showPedalCb.addEventListener('change', refreshDisplayToggles);
  if (showChordsCbToggle) showChordsCbToggle.addEventListener('change', refreshDisplayToggles);

  presetBtns.forEach(btn => {
    btn.addEventListener('click', () => {
      applyPreset(btn.dataset.preset);
    });
  });

  const allControls = [
    useDemucsCb, removeShortCb, minNoteInput, mergeNearCb, mergeGapInput,
    splitHandsCb, detectTempoCb, detectKeyCb, thresholdSlider, enableRubato, enableTriplets
  ];

  allControls.forEach(ctrl => {
    if (!ctrl) return;
    ctrl.addEventListener('change', () => {
      checkPresetMatch();
      toggleManualFields();
    });
    if (ctrl.tagName === 'INPUT' && (ctrl.type === 'number' || ctrl.type === 'range')) {
      ctrl.addEventListener('input', () => {
        checkPresetMatch();
        toggleManualFields();
      });
    }
  });

  document.querySelectorAll('input[name="transcriber"]').forEach(r => {
    r.addEventListener('change', () => {
      checkPresetMatch();
      toggleManualFields();
    });
  });

  document.querySelectorAll('input[name="quantization"]').forEach(r => {
    r.addEventListener('change', () => {
      checkPresetMatch();
      toggleManualFields();
    });
  });

  function checkPresetMatch() {
    const currentTranscriber = getTranscriberValue();
    const currentDemucs = useDemucsCb ? useDemucsCb.checked : false;
    const currentQuantization = getQuantizationValue();
    const currentRemoveShort = removeShortCb ? removeShortCb.checked : false;
    const currentMergeNear = mergeNearCb ? mergeNearCb.checked : false;
    const currentSplitHands = splitHandsCb ? splitHandsCb.checked : false;
    const currentDetectTempo = detectTempoCb ? detectTempoCb.checked : false;
    const currentDetectKey = detectKeyCb ? detectKeyCb.checked : false;
    const currentenableRubato = enableRubato ? enableRubato.checked : false;
    const currentenableTriplets = enableTriplets ? enableTriplets.checked : false;
    const currentThreshold = thresholdSlider ? parseFloat(thresholdSlider.value) : 0.50;

    // Utiliser le flag pour bloquer la cascade hqCheckbox→applyPreset
    const setHqChecked = (val) => {
      if (hqCheckbox && hqCheckbox.checked !== val) {
        _updatingFromPresetMatch = true;
        hqCheckbox.checked = val;
        _updatingFromPresetMatch = false;
      }
    };

    if (
      currentTranscriber === 'piano_transcription' &&
      currentDemucs === true &&
      currentQuantization === 'standard' &&
      currentRemoveShort === false &&
      currentMergeNear === false &&
      currentSplitHands === true &&
      currentDetectTempo === true &&
      currentDetectKey === true &&
      currentenableRubato === true &&
      currentenableTriplets === true
    ) {
      presetBtns.forEach(btn => btn.classList.toggle('active', btn.dataset.preset === 'studio'));
      setHqChecked(true);
    }
    else if (
      currentTranscriber === 'piano_transcription' &&
      currentDemucs === false &&
      currentQuantization === 'standard' &&
      currentRemoveShort === false &&
      currentMergeNear === false &&
      currentSplitHands === true &&
      currentDetectTempo === true &&
      currentDetectKey === true &&
      currentenableRubato === false &&
      currentenableTriplets === false
    ) {
      presetBtns.forEach(btn => btn.classList.toggle('active', btn.dataset.preset === 'equilibre'));
      setHqChecked(false);
    }
    else if (
      currentTranscriber === 'basic_pitch' &&
      currentDemucs === false &&
      currentQuantization === 'light' &&
      currentRemoveShort === false &&
      currentMergeNear === false &&
      currentSplitHands === false &&
      currentDetectTempo === false &&
      currentDetectKey === false &&
      currentenableRubato === false &&
      currentenableTriplets === false
    ) {
      presetBtns.forEach(btn => btn.classList.toggle('active', btn.dataset.preset === 'rapide'));
      setHqChecked(false);
    }
    else if (
      currentTranscriber === 'piano_transcription' &&
      currentDemucs === true &&
      currentQuantization === 'light' &&
      currentRemoveShort === false &&
      currentMergeNear === false &&
      currentSplitHands === true &&
      currentDetectTempo === true &&
      currentDetectKey === true &&
      currentenableRubato === true &&
      currentenableTriplets === true &&
      Math.abs(currentThreshold - 0.25) < 0.01
    ) {
      presetBtns.forEach(btn => btn.classList.toggle('active', btn.dataset.preset === 'classique'));
      setHqChecked(false);
    }
    else if (
      currentTranscriber === 'piano_transcription' &&
      currentDemucs === true &&
      currentQuantization === 'heavy' &&
      currentRemoveShort === false &&
      currentMergeNear === false &&
      currentSplitHands === true &&
      currentDetectTempo === true &&
      currentDetectKey === true &&
      currentenableRubato === false &&
      currentenableTriplets === false &&
      Math.abs(currentThreshold - 0.50) < 0.01
    ) {
      presetBtns.forEach(btn => btn.classList.toggle('active', btn.dataset.preset === 'jazz'));
      setHqChecked(false);
    }
    else {
      // Paramètres personnalisés — pas de preset actif
      presetBtns.forEach(btn => btn.classList.remove('active'));
      setHqChecked(false);
    }
  }

  applyPreset('equilibre');
}

/* ═══════════════════════════════════════════════════════════════════════════
   Transcription — Version SSE (temps réel)
   ═══════════════════════════════════════════════════════════════════════════ */
async function startTranscription(file) {
  if (player) player.stop();
  showSection('loading');
  resetProgressUI();

  // Nettoyer les fichiers temporaires du job précédent
  try {
    await fetch('/api/cleanup', { method: 'POST' });
  } catch (_) { /* non bloquant */ }

  const formData = new FormData();
  formData.append('audio', file);

  /* Paramètres */
  const threshold = document.getElementById('onset-threshold')?.value || '0.5';
  const timeSig = document.getElementById('time-sig')?.value || '4/4';
  const tempoInput = document.getElementById('tempo-override')?.value || '';
  const keySig = document.getElementById('key-sig-upload')?.value || 'C';

  // Marquer le sélecteur de mesure comme défini par l'utilisateur
  // si la valeur n'est pas 4/4 (valeur par défaut) — permet au système V2
  // de ne pas l'écraser avec l'auto-détection
  const timeSigEl = document.getElementById('time-sig');
  if (timeSigEl && timeSig !== '4/4') {
    timeSigEl.dataset.userOverride = '1';
  } else if (timeSigEl) {
    delete timeSigEl.dataset.userOverride;
  }

  const transcriber = document.querySelector('input[name="transcriber"]:checked')?.value || 'piano_transcription';
  const useDemucs = document.getElementById('use-demucs')?.checked ? 'true' : 'false';
  const removeShortNotes = document.getElementById('remove-short-notes')?.checked ? 'true' : 'false';
  const minNoteDuration = document.getElementById('min-note-duration')?.value || '50';
  const mergeNearNotes = document.getElementById('merge-near-notes')?.checked ? 'true' : 'false';
  const mergeGapMs = document.getElementById('merge-gap-ms')?.value || '30';
  const quantization = document.querySelector('input[name="quantization"]:checked')?.value || 'standard';
  const splitHands = document.getElementById('split-hands')?.checked ? 'true' : 'false';
  const detectTempo = document.getElementById('detect-tempo')?.checked ? 'true' : 'false';
  const detectMeter = document.getElementById('detect-meter')?.checked ? 'true' : 'false';
  const detectKey = document.getElementById('detect-key')?.checked ? 'true' : 'false';
  const enableRubato = document.getElementById('enable-rubato')?.checked ? 'true' : 'false';
  const enableTriplets = document.getElementById('enable-triplets')?.checked ? 'true' : 'false';

  formData.append('onset_threshold', threshold);
  formData.append('time_sig', timeSig);
  formData.append('key_sig', keySig);
  if (tempoInput) formData.append('tempo', tempoInput);

  formData.append('transcriber', transcriber);
  formData.append('use_demucs', useDemucs);
  formData.append('remove_short_notes', removeShortNotes);
  formData.append('minimum_note_duration', minNoteDuration);
  formData.append('merge_near_notes', mergeNearNotes);
  formData.append('merge_gap_ms', mergeGapMs);
  formData.append('quantization_level', quantization);
  formData.append('split_hands', splitHands);
  formData.append('detect_tempo', detectTempo);
  formData.append('detect_meter', detectMeter);
  formData.append('detect_key', detectKey);
  formData.append('enable_rubato', enableRubato);
  formData.append('enable_triplets', enableTriplets);

  // ── Noms lisibles des modèles ──────────────────────────────────────
  const MODEL_LABELS = {
    'piano_transcription': 'Piano Transcription (CRNN)',
    'basic_pitch': 'Basic Pitch (Spotify)',
    'transkun': 'Transkun (Transformer)',
    'hft': 'HFT-Transformer',
    'mt3': 'MT3 (Google)',
    'ensemble': 'Ensemble multi-modèles',
  };
  const modelLabel = MODEL_LABELS[transcriber] || transcriber;

  // ── Simulation de progression (mode synchrone sans SSE) ──────────
  // Phases : upload(0→10%), chargement modèle(10→25%),
  //          transcription IA(25→80%), post-traitement(80→92%), export(92→97%)
  const phases = [
    { pct: 10,  step: `📤 Envoi du fichier…`,                    ms: 800  },
    { pct: 25,  step: `🧠 Chargement modèle — ${modelLabel}…`,   ms: 4000 },
    { pct: 80,  step: `🎵 Transcription IA — ${modelLabel}…`,    ms: 45000},
    { pct: 92,  step: `📐 Quantification & séparation mains…`,   ms: 5000 },
    { pct: 97,  step: `💾 Construction partition…`,              ms: 3000 },
  ];

  let phaseIdx = 0;
  let currentPct = 0;
  let phaseStartTime = Date.now();

  const progressTimer = setInterval(() => {
    if (phaseIdx >= phases.length) return;
    const phase = phases[phaseIdx];
    const elapsed = Date.now() - phaseStartTime;
    const ratio = Math.min(1, elapsed / phase.ms);
    const pct = currentPct + ratio * (phase.pct - currentPct);

    updateProgress(pct);

    if (ratio >= 1) {
      currentPct = phase.pct;
      phaseStartTime = Date.now();
      setLoadingStep(phase.step);
      phaseIdx++;
    }
  }, 100);

  // Afficher immédiatement le premier message + lancer le fetch
  setLoadingStep(`📤 Envoi du fichier…`);
  updateProgress(0);

  try {
    const response = await fetch('/api/transcribe', {
      method: 'POST',
      body: formData,
    });

    clearInterval(progressTimer);

    if (!response.ok) {
      const err = await response.json().catch(() => ({ error: response.statusText }));
      throw new Error(err.error || `Erreur HTTP ${response.status}`);
    }

    const data = await response.json();

    if (!data.success) {
      throw new Error(data.error || 'Échec de la transcription');
    }

    // Sauter à 100% avant d'afficher le résultat
    updateProgress(100);
    setLoadingStep(`✅ Terminé — ${modelLabel}`);

    // Traiter le résultat directement
    handleTranscriptionResult(data);

  } catch (err) {
    clearInterval(progressTimer);
    showSection('upload');
    showToast(`❌ Erreur : ${err.message}`, 'error', 8000);
    console.error('[Transcription]', err);

    if (document.hidden) {
      document.title = `(1) ❌ Erreur - ${window.originalDocumentTitle}`;
    }
  }
}

async function connectSSE(jobId) {
  return new Promise((resolve, reject) => {
    const eventSource = new EventSource(`/api/transcribe/progress/${jobId}`);
    currentEventSource = eventSource;

    eventSource.onopen = () => {
      console.log('[SSE] Connexion établie');
    };

    eventSource.addEventListener('progress', (event) => {
      try {
        const data = JSON.parse(event.data);
        handleProgressEvent(data);
      } catch (e) {
        console.warn('[SSE] Erreur parsing progress:', e);
      }
    });

    eventSource.addEventListener('heartbeat', (event) => {
      // Heartbeat reçu, connexion vivante
    });

    eventSource.addEventListener('error', (event) => {
      console.error('[SSE] Erreur:', event);
      // Ne pas rejeter ici, laisser onerror gérer
    });

    eventSource.onerror = (event) => {
      if (eventSource.readyState === EventSource.CLOSED) {
        console.log('[SSE] Connexion fermée');
        // La connexion se ferme normalement à la fin
      }
    };

    // Écouter aussi les messages sans type (compatibilité)
    eventSource.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        if (data.type === 'progress') {
          handleProgressEvent(data);
        } else if (data.type === 'complete' || data.type === 'error') {
          // Le résultat final sera récupéré via /api/transcribe/result
          eventSource.close();
          currentEventSource = null;
          fetchResult(jobId).then(resolve).catch(reject);
        }
      } catch (e) {
        console.warn('[SSE] Erreur parsing message:', e);
      }
    };
  });
}

function handleProgressEvent(data) {
  const { stage, stage_index, total_stages, percent, message, elapsed, stage_elapsed, metadata } = data;

  // Mettre à jour la barre de progression
  updateProgress(percent);

  // Mettre à jour le texte de l'étape
  setLoadingStep(message);

  // Mettre à jour le badge d'étape si présent
  updateStageBadges(stage, stage_index, total_stages);

  // Afficher des infos spécifiques selon l'étape
  if (metadata) {
    handleStageMetadata(stage, metadata);
  }
}

function updateStageBadges(currentStage, currentIndex, totalStages) {
  const stages = [
    { id: 'load_audio', label: 'Chargement' },
    { id: 'demucs', label: 'Demucs' },
    { id: 'transcribe', label: 'Transcription' },
    { id: 'quantize', label: 'Quantification' },
    { id: 'split_hands', label: 'Séparation mains' },
    { id: 'build_score', label: 'Partition' },
    { id: 'export', label: 'Export' },
  ];

  stages.forEach((s, i) => {
    const badge = document.getElementById(`stage-${s.id}`);
    if (!badge) return;

    badge.classList.remove('active', 'completed', 'pending');
    if (i < currentIndex) {
      badge.classList.add('completed');
    } else if (i === currentIndex) {
      badge.classList.add('active');
    } else {
      badge.classList.add('pending');
    }
  });
}

function handleStageMetadata(stage, metadata) {
  // Afficher des infos spécifiques selon l'étape
  if (stage === 'demucs' && metadata.model) {
    setLoadingStep(`Séparation Demucs (${metadata.model})...`);
  } else if (stage === 'transcribe' && metadata.model) {
    setLoadingStep(`Transcription IA (${metadata.model})...`);
  }
}

async function fetchResult(jobId) {
  try {
    const response = await fetch(`/api/transcribe/result/${jobId}`);
    if (!response.ok) {
      if (response.status === 202) {
        // Encore en cours, attendre un peu et réessayer
        await sleep(500);
        return fetchResult(jobId);
      }
      const err = await response.json().catch(() => ({ error: response.statusText }));
      throw new Error(err.error || `Erreur HTTP ${response.status}`);
    }

    const result = await response.json();
    handleTranscriptionResult(result);
  } catch (err) {
    showSection('upload');
    showToast(`❌ Erreur : ${err.message}`, 'error', 8000);
    console.error('[Transcription Result]', err);
  }
}

function handleTranscriptionResult(result) {
  const { success, score_data, output_files, error, processing_time } = result;

  if (!success) {
    showSection('upload');
    showToast(`❌ Erreur : ${error}`, 'error', 8000);
    return;
  }

  if (!score_data || !score_data.measures || score_data.measures.length === 0) {
    showSection('upload');
    showToast('❌ Aucune note détectée. Essayez un seuil de détection plus bas.', 'error', 8000);
    return;
  }

  currentJobId = score_data.jobId;

  /* Légère pause pour que la barre atteigne 100% */
  sleep(400).then(() => {
    showSection('score');

    // La clé réellement utilisée est celle retournée par le backend
    // (auto-détection Krumhansl-Schmuckler) — pas forcément celle du formulaire
    const detectedKey = score_data.keySignature || 'C';
    const keySigToolbar = document.getElementById('key-sig-toolbar');
    if (keySigToolbar) {
      keySigToolbar.value = detectedKey;
    }
    // Synchroniser l'affichage pédale / accords avec les cases à cocher
    // avant le premier rendu (débrayage possible ensuite sans re-transcrire).
    if (renderer) {
      const showPedalCb = document.getElementById('show-pedal');
      const showChordsCb = document.getElementById('show-chords');
      renderer.showPedals = showPedalCb ? showPedalCb.checked : true;
      renderer.showChordSymbols = showChordsCb ? showChordsCb.checked : false;
    }
    editor.loadScore(score_data);
    // Après loadScore (qui reset l'armure), réappliquer la clé détectée
    if (editor && typeof editor.setKeySignature === 'function') {
      editor.setKeySignature(detectedKey);
    }

    // ── Nouvelles fonctionnalités V2 (rétrocompatibles) ──────────────
    // Stocker scoreData globalement pour le slider tempo
    window.currentScoreData = score_data;
    if (score_data.tempoMapMethod) {
      updateTempoDisplay(score_data);
      initTempoSlider(score_data.tempo);
    }
    if (score_data.detectedMeter) {
      updateDetectedMeter(score_data.detectedMeter);
    }
    displayWarnings(score_data.warnings);
    // ─────────────────────────────────────────────────────────────────

    showToast(
      `✅ Partition générée — ${score_data.totalMeasures} mesure(s) · ${score_data.tempo} BPM · ${processing_time.toFixed(1)}s`,
      'success'
    );

    if (document.hidden) {
      document.title = `(1) ✅ Terminée ! - ${window.originalDocumentTitle}`;
    }
  });
}

function cancelTranscription() {
  if (!currentJobId) return;

  fetch(`/api/transcribe/cancel/${currentJobId}`, { method: 'POST' })
    .then(() => {
      if (currentEventSource) {
        currentEventSource.close();
        currentEventSource = null;
      }
      showSection('upload');
      showToast('⏹️ Transcription annulée', 'info');
    })
    .catch(err => {
      showToast(`❌ Erreur annulation : ${err.message}`, 'error');
    });
}

/* ═══════════════════════════════════════════════════════════════════════════
   UI Progression
   ═══════════════════════════════════════════════════════════════════════════ */
function resetProgressUI() {
  updateProgress(0);
  setLoadingStep('Initialisation…');
  // Réinitialiser les badges d'étapes
  ['load_audio', 'demucs', 'transcribe', 'quantize', 'split_hands', 'build_score', 'export'].forEach(id => {
    const badge = document.getElementById(`stage-${id}`);
    if (badge) {
      badge.classList.remove('active', 'completed');
      badge.classList.add('pending');
    }
  });
}

function updateProgress(pct) {
  const fill = document.getElementById('progress-fill');
  if (fill) fill.style.width = `${Math.min(100, Math.max(0, pct))}%`;
}

function setLoadingStep(text) {
  const el = document.getElementById('loading-step');
  if (el) el.textContent = text;
}

/* ═══════════════════════════════════════════════════════════════════════════
   V2 — Affichage dynamique du tempo détecté (badge + barre de confiance)
   ═══════════════════════════════════════════════════════════════════════════ */
function updateTempoDisplay(scoreData) {
  const infoDiv = document.getElementById('tempo-detected-info');
  if (!infoDiv) return;

  // BPM affiché
  const bpmEl = document.getElementById('tempo-detected-value');
  if (bpmEl) bpmEl.textContent = `${scoreData.tempo} BPM`;

  // Badge méthode : couleur selon la source
  const methodBadge = document.getElementById('tempo-method-badge');
  const methodColors = {
    'madmom': { label: 'TempoMap Pro', color: '#22c55e', bg: 'rgba(34,197,94,0.15)' },
    'librosa_advanced': { label: 'TempoMap Standard', color: '#f59e0b', bg: 'rgba(245,158,11,0.15)' },
    'fallback': { label: 'Estimation basique', color: '#ef4444', bg: 'rgba(239,68,68,0.15)' },
  };
  const m = methodColors[scoreData.tempoMapMethod] || { label: scoreData.tempoMapMethod, color: '#94a3b8', bg: 'rgba(148,163,184,0.12)' };
  if (methodBadge) {
    methodBadge.textContent = m.label;
    methodBadge.style.color = m.color;
    methodBadge.style.background = m.bg;
    methodBadge.style.borderColor = m.color;
  }

  // Barre de confiance
  const confBar = document.getElementById('tempo-confidence-bar');
  const confLabel = document.getElementById('tempo-confidence-label');
  if (confBar && scoreData.tempoConfidence !== undefined) {
    const pct = Math.round(scoreData.tempoConfidence * 100);
    confBar.style.width = `${pct}%`;
    // Couleur de la barre selon la confiance
    confBar.style.background = pct >= 80 ? '#22c55e'
      : pct >= 55 ? '#f59e0b'
        : '#ef4444';
    if (confLabel) confLabel.textContent = `${pct}%`;
  }

  // Plage de tempo
  const rangeEl = document.getElementById('tempo-range-label');
  if (rangeEl && scoreData.tempoRange) {
    rangeEl.textContent = `Plage : ${Math.round(scoreData.tempoRange[0])}–${Math.round(scoreData.tempoRange[1])} BPM`;
    rangeEl.style.display = 'block';
  }

  infoDiv.style.display = 'block';
}

/* ═══════════════════════════════════════════════════════════════════════════
   V2 — Slider de tempo post-transcription (sans re-analyse)
   ═══════════════════════════════════════════════════════════════════════════ */
let _originalTempo = 120;

function initTempoSlider(detectedTempo) {
  const panel = document.getElementById('tempo-adjust-panel');
  const slider = document.getElementById('tempo-slider');
  const output = document.getElementById('tempo-slider-output');
  const reset = document.getElementById('tempo-slider-reset');
  if (!panel || !slider) return;

  _originalTempo = detectedTempo;
  slider.value = detectedTempo;
  if (output) output.textContent = `${detectedTempo} BPM`;
  panel.style.display = 'block';

  // Supprimer les anciens listeners en clonant (évite les doublons)
  const newSlider = slider.cloneNode(true);
  slider.parentNode.replaceChild(newSlider, slider);
  const newReset = reset ? reset.cloneNode(true) : null;
  if (reset && newReset) reset.parentNode.replaceChild(newReset, reset);

  // 1. Événement 'input' : met à jour le texte à l'écran en temps réel pendant le glissement de la souris
  newSlider.addEventListener('input', () => {
    const newTempo = parseInt(newSlider.value);
    const out = document.getElementById('tempo-slider-output');
    if (out) out.textContent = `${newTempo} BPM`;
    const bpmEl = document.getElementById('tempo-detected-value');
    if (bpmEl) bpmEl.textContent = `${newTempo} BPM`;
  });

  // 2. Événement 'change' : applique la modification de tempo SEULEMENT au relâchement de la souris
  newSlider.addEventListener('change', () => {
    const oldTempo = (editor && editor.scoreData) ? (editor.scoreData.tempo || 120) : 120;
    const newTempo = parseInt(newSlider.value);

    // Mettre à jour les structures de données du tempo en priorité
    if (window.currentScoreData) window.currentScoreData.tempo = newTempo;
    if (editor && editor.scoreData) editor.scoreData.tempo = newTempo;
    if (player) {
      player._scoreData = editor.getScoreData();
    }

    if (player && player.isPlaying) {
      // Calculer la position actuelle en beats
      let elapsed;
      if (player.isPaused) {
        elapsed = player._pauseTime;
      } else {
        elapsed = player.audioCtx.currentTime - player._startTime;
      }
      const currentBeat = elapsed * (oldTempo / 60.0);

      // Calculer le nouvel elapsed en secondes
      const newElapsed = currentBeat * (60.0 / newTempo);

      // Reconstruire les événements audio du player avec le nouveau tempo
      player._events = player._buildEvents(player._scoreData);
      player._totalTime = Math.max(...player._events.map(e => e.time + e.duration)) + 0.5;

      if (player.isPaused) {
        player._pauseTime = newElapsed;
      } else {
        // En lecture active : couper les sons et recaler la lecture
        player._stopAllSound();
        player._scheduledNoteKeys = new Set();
        player._startTime = player.audioCtx.currentTime - newElapsed;
        player._scheduleNotes(newElapsed);
      }
    }

    // Re-rendre le visuel de la partition
    if (typeof window.rerenderScore === 'function') {
      window.rerenderScore(window.currentScoreData || (editor && editor.scoreData));
    }
  });

  if (newReset) {
    newReset.addEventListener('click', () => {
      newSlider.value = _originalTempo;
      const out = document.getElementById('tempo-slider-output');
      if (out) out.textContent = `${_originalTempo} BPM`;
      newSlider.dispatchEvent(new Event('input'));
    });
  }
}

/* ═══════════════════════════════════════════════════════════════════════════
   V2 — Affichage de la mesure auto-détectée
   ═══════════════════════════════════════════════════════════════════════════ */
function updateDetectedMeter(detectedMeter) {
  const [num, den] = detectedMeter;
  const timeSigSelect = document.getElementById('time-sig');
  const badge = document.getElementById('meter-auto-badge');

  // Mettre à jour le sélecteur seulement si l'utilisateur n'a pas forcé une valeur
  if (timeSigSelect && !timeSigSelect.dataset.userOverride) {
    const targetVal = `${num}/${den}`;
    // Vérifier si la valeur existe dans les options
    const hasOption = Array.from(timeSigSelect.options).some(o => o.value === targetVal);
    if (hasOption) {
      timeSigSelect.value = targetVal;
      if (badge) badge.style.display = 'inline';
    }
  }
}

/* ═══════════════════════════════════════════════════════════════════════════
   V2 — Affichage des avertissements de transcription
   ═══════════════════════════════════════════════════════════════════════════ */
function displayWarnings(warnings) {
  const panel = document.getElementById('transcription-warnings');
  const list = document.getElementById('warnings-list');
  if (!panel || !list) return;

  if (!warnings || warnings.length === 0) {
    panel.style.display = 'none';
    return;
  }

  list.innerHTML = '';
  warnings.forEach(msg => {
    const li = document.createElement('li');
    li.textContent = msg;
    list.appendChild(li);
  });
  panel.style.display = 'block';
}

/* ═══════════════════════════════════════════════════════════════════════════
   Barre d'outils
   ═══════════════════════════════════════════════════════════════════════════ */
function initToolbar() {
  /* Transposer */
  document.getElementById('btn-up')?.addEventListener('click', () => {
    editor.transposeSelected(1);
  });
  document.getElementById('btn-down')?.addEventListener('click', () => {
    editor.transposeSelected(-1);
  });

  /* Durées */
  document.querySelectorAll('.dur-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      const dur = btn.dataset.dur;
      editor.setDurationSelected(dur);
      document.querySelectorAll('.dur-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
    });
  });

  /* Pointée */
  document.getElementById('btn-dot')?.addEventListener('click', () => {
    editor.toggleDotSelected();
  });

  /* Main */
  document.getElementById('btn-hand-r')?.addEventListener('click', () => {
    editor.assignHandSelected('treble');
    showToast('Note déplacée → main droite (Sol)', 'info');
  });
  document.getElementById('btn-hand-l')?.addEventListener('click', () => {
    editor.assignHandSelected('bass');
    showToast('Note déplacée → main gauche (Fa)', 'info');
  });

  /* Ajouter Note / Silence */
  document.getElementById('btn-add-note')?.addEventListener('click', () => {
    editor.insertNoteAfterSelected(false);
  });
  document.getElementById('btn-add-rest')?.addEventListener('click', () => {
    editor.insertNoteAfterSelected(true);
  });

  /* Supprimer */
  document.getElementById('btn-delete')?.addEventListener('click', () => {
    editor.deleteSelected();
  });

  /* Undo / Redo */
  document.getElementById('btn-undo')?.addEventListener('click', () => editor.undo());
  document.getElementById('btn-redo')?.addEventListener('click', () => editor.redo());

  /* Armure (tonalité) — toolbar */
  const keySigToolbar = document.getElementById('key-sig-toolbar');
  if (keySigToolbar) {
    keySigToolbar.addEventListener('change', () => {
      editor.setKeySignature(keySigToolbar.value);
      showToast(`🎼 Armure changée : ${keySigToolbar.value}`, 'info', 2500);
    });
  }

  /* Déplacement temporel ◄ ► */
  document.getElementById('btn-shift-left')?.addEventListener('click', () => {
    editor.shiftNoteTime(-1);
  });
  document.getElementById('btn-shift-right')?.addEventListener('click', () => {
    editor.shiftNoteTime(+1);
  });

  /* Drag & drop SVG */
  if (typeof renderer !== 'undefined' && renderer && typeof renderer.enableDragDrop === 'function') {
    renderer.enableDragDrop(editor);
  }

  /* Export PDF */
  document.getElementById('btn-export-pdf')?.addEventListener('click', exportPdf);

  /* Export MIDI */
  document.getElementById('btn-export-midi')?.addEventListener('click', exportMidi);

  /* ── Lecture (Play/Pause) ─────────────────────────────────────────── */
  player = new ScorePlayer(renderer);

  document.getElementById('btn-play-pause')?.addEventListener('click', () => {
    const scoreData = editor.getScoreData();
    if (!scoreData) {
      showToast('Aucune partition à lire.', 'error');
      return;
    }
    player.togglePlayPause(scoreData);
  });

  /* Timeline scrubbing */
  const timeline = document.getElementById('playback-timeline');
  if (timeline) {
    timeline.addEventListener('click', (e) => {
      const rect = timeline.getBoundingClientRect();
      const pct = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
      player.seekTo(pct);
    });
  }
}

/* ═══════════════════════════════════════════════════════════════════════════
   Export MIDI
   ═══════════════════════════════════════════════════════════════════════════ */
async function exportMidi() {
  const scoreData = editor.getScoreData();
  if (!scoreData) {
    showToast('⚠️ Aucune partition à exporter.', 'error');
    return;
  }

  showToast('🎵 Génération du MIDI en cours…', 'info');

  try {
    const response = await fetch('/api/export-midi', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(scoreData),
    });

    if (!response.ok) {
      const err = await response.json().catch(() => ({}));
      throw new Error(err.error || `Erreur HTTP ${response.status}`);
    }

    /* Déclencher le téléchargement */
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'partition_piano.mid';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);

    showToast('✅ Fichier MIDI téléchargé !', 'success');

  } catch (err) {
    showToast(`❌ Erreur export MIDI : ${err.message}`, 'error', 6000);
    console.error('[MIDI Export]', err);
  }
}

/* ═══════════════════════════════════════════════════════════════════════════
   Export PDF — Portrait A4, lignes justifiées (toutes à 100% sauf la dernière)
   ═══════════════════════════════════════════════════════════════════════════ */
function exportPdf() {
  const scoreData = editor ? editor.getScoreData() : null;
  if (!scoreData || !scoreData.measures || scoreData.measures.length === 0) {
    showToast('⚠️ Aucune partition à exporter.', 'error');
    return;
  }

  showToast('🖨️ Préparation du PDF…', 'info');

  // ── Cible : 5 mesures par ligne ──────────────────────────────────────────
  const PDF_MPR = 5;
  const RENDER_W = PDF_MPR * ScoreRenderer.STAVE_W
    + ScoreRenderer.FIRST_EXTRA
    + ScoreRenderer.MARGIN_X * 2;          // ≈ 1410 px
  const SVG_H = ScoreRenderer.ROW_HEIGHT
    + ScoreRenderer.MARGIN_Y * 2 + 30;     // ≈ 342 px

  const numRows = Math.ceil(scoreData.measures.length / PDF_MPR);
  const rowSvgStrings = [];

  // Mesure vide pour padder les lignes incomplètes → VexFlow étire à pleine largeur
  const [tsNum, tsDen] = scoreData.timeSignature || [4, 4];
  const emptyMeasure = {
    treble: [{
      id: '__pad_t__', keys: ['d/5'], durationStr: 'w', dots: 0,
      isRest: true, startBeat: 0, duration: 4, midiPitch: null,
      hand: 'treble', amplitude: 0
    }],
    bass: [{
      id: '__pad_b__', keys: ['f/3'], durationStr: 'w', dots: 0,
      isRest: true, startBeat: 0, duration: 4, midiPitch: null,
      hand: 'bass', amplitude: 0
    }],
  };

  for (let row = 0; row < numRows; row++) {
    const rowMeasures = scoreData.measures.slice(row * PDF_MPR, (row + 1) * PDF_MPR);
    const paddedMeasures = rowMeasures.slice();
    while (paddedMeasures.length < PDF_MPR) paddedMeasures.push(emptyMeasure);

    const rowScoreData = Object.assign({}, scoreData, {
      measures: paddedMeasures, totalMeasures: paddedMeasures.length,
    });

    const div = document.createElement('div');
    div.id = '__pdf_row_' + row + '__';
    div.style.cssText = 'position:absolute;left:-9999px;top:0;width:1px;visibility:hidden;';
    document.body.appendChild(div);

    const rowRenderer = new ScoreRenderer(div.id);
    rowRenderer._forcedMPR = PDF_MPR;   // court-circuite le calcul clientWidth dans renderer.js
    rowRenderer.render(rowScoreData);

    const svgEl = div.querySelector('svg');
    if (svgEl) {
      svgEl.setAttribute('viewBox', '0 0 ' + RENDER_W + ' ' + SVG_H);
      svgEl.setAttribute('width', RENDER_W);
      svgEl.removeAttribute('height');
      svgEl.setAttribute('preserveAspectRatio', 'xMinYMin meet');
      svgEl.style.cssText = 'display:block;width:100%;height:auto;';
      rowSvgStrings.push(svgEl.outerHTML);
    }

    document.body.removeChild(div);
  }

  const rowSvgsHtml = rowSvgStrings
    .map(svg => '<div class="score-row">' + svg + '</div>')
    .join('\n');

  const meta = `Tempo : ${scoreData.tempo} BPM · ${scoreData.timeSignature[0]}/${scoreData.timeSignature[1]} · Tonalité : ${scoreData.keySignature || 'C'} · ${scoreData.totalMeasures} mesure(s)`;

  const printWindow = window.open('', '_blank', 'width=900,height=1200');
  if (!printWindow) {
    showToast('❌ Fenêtre bloquée par le navigateur. Autorisez les popups.', 'error', 6000);
    return;
  }

  printWindow.document.write(`<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="UTF-8"/>
  <title>AudioScore — Partition Piano</title>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    @page { size: A4 portrait; margin: 12mm 12mm; }
    body { background: #fff; font-family: Georgia, serif; color: #111; padding: 4mm 6mm; }
    h1 { font-size: 14pt; text-align: center; margin-bottom: 2mm; letter-spacing: 0.04em; }
    .meta { text-align: center; font-size: 8pt; color: #555; margin-bottom: 3mm; }
    .score-wrap { width: 100%; }
    /* Chaque ligne treble+bass = bloc inséparable */
    .score-row {
      display: block;
      width: 100%;
      break-inside: avoid;
      page-break-inside: avoid;
      margin-bottom: 0;
    }
    /* Toutes les lignes à 100% — le viewBox gère le ratio */
    .score-row svg { display: block; width: 100% !important; height: auto !important; }
    @media print {
      body { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
    }
  </style>
</head>
<body>
  <h1>🎹 Partition Piano — AudioScore</h1>
  <p class="meta">${meta}</p>
  <div class="score-wrap">${rowSvgsHtml}</div>
  <script>window.onload = function(){ setTimeout(function(){ window.print(); window.close(); }, 600); };<\/script>
</body>
</html>`);
  printWindow.document.close();
}

/* ═══════════════════════════════════════════════════════════════════════════
   Raccourcis clavier
   ═══════════════════════════════════════════════════════════════════════════ */
function initKeyboardShortcuts() {
  document.addEventListener('keydown', (e) => {
    const section = getVisibleSection();
    if (section !== 'score') return;

    /* Éviter les conflits avec les champs de saisie */
    if (['INPUT', 'TEXTAREA', 'SELECT'].includes(e.target.tagName)) return;

    switch (true) {
      case e.key === 'ArrowUp':
        e.preventDefault();
        editor.transposeSelected(1);
        break;
      case e.key === 'ArrowDown':
        e.preventDefault();
        editor.transposeSelected(-1);
        break;
      case e.ctrlKey && e.key === 'ArrowRight':
        e.preventDefault();
        editor.shiftNoteTime(+1);
        break;
      case e.ctrlKey && e.key === 'ArrowLeft':
        e.preventDefault();
        editor.shiftNoteTime(-1);
        break;
      case e.key === 'ArrowRight' && !e.ctrlKey:
        e.preventDefault();
        editor.selectNextNote();
        break;
      case e.key === 'ArrowLeft' && !e.ctrlKey:
        e.preventDefault();
        editor.selectPrevNote();
        break;
      case e.key === ' ':
        e.preventDefault();
        if (player) {
          const scoreData = editor.getScoreData();
          if (scoreData) player.togglePlayPause(scoreData);
        }
        break;
      case e.key === 'Delete' || e.key === 'Backspace':
        e.preventDefault();
        editor.deleteSelected();
        break;
      case (e.ctrlKey || e.metaKey) && e.key === 'z' && !e.shiftKey:
        e.preventDefault();
        editor.undo();
        break;
      case (e.ctrlKey || e.metaKey) && (e.key === 'y' || (e.key === 'z' && e.shiftKey)):
        e.preventDefault();
        editor.redo();
        break;
      case (e.ctrlKey || e.metaKey) && (e.key === 'c' || e.key === 'C'):
        e.preventDefault();
        editor.copySelected();
        break;
      case (e.ctrlKey || e.metaKey) && (e.key === 'v' || e.key === 'V'):
        e.preventDefault();
        editor.pasteAfterSelected();
        break;
      case e.key === 'w' || e.key === 'W':
        editor.setDurationSelected('w');
        break;
      case e.key === 'h' || e.key === 'H':
        editor.setDurationSelected('h');
        break;
      case e.key === 'q' || e.key === 'Q':
        editor.setDurationSelected('q');
        break;
      case e.key === '8':
        editor.setDurationSelected('8');
        break;
      case e.key === '6':
        editor.setDurationSelected('16');
        break;
      case e.key === '.':
        editor.toggleDotSelected();
        break;
      case e.key === 'Escape':
        editor.clearSelection();
        if (player && player.isPlaying) player.stop();
        break;
    }
  });
}

/* ═══════════════════════════════════════════════════════════════════════════
   Gestion des sections (visibilité)
   ═══════════════════════════════════════════════════════════════════════════ */
function showSection(name) {
  document.getElementById('upload-section')?.classList.toggle('hidden', name !== 'upload');
  document.getElementById('loading-section')?.classList.toggle('hidden', name !== 'loading');
  document.getElementById('score-section')?.classList.toggle('hidden', name !== 'score');
}

function getVisibleSection() {
  if (!document.getElementById('score-section')?.classList.contains('hidden')) return 'score';
  if (!document.getElementById('loading-section')?.classList.contains('hidden')) return 'loading';
  return 'upload';
}

/* ═══════════════════════════════════════════════════════════════════════════
   Utilitaires
   ═══════════════════════════════════════════════════════════════════════════ */
function formatSize(bytes) {
  if (bytes < 1024) return `${bytes} o`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} Ko`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} Mo`;
}

function formatTime(seconds) {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${s.toString().padStart(2, '0')}`;
}

function sleep(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

/* ═══════════════════════════════════════════════════════════════════════════
   Toasts (notifications)
   ═══════════════════════════════════════════════════════════════════════════ */
function showToast(message, type = 'info', duration = 4000) {
  const container = document.getElementById('toast-container');
  if (!container) return;

  const toast = document.createElement('div');
  toast.className = `toast toast-${type}`;
  toast.textContent = message;
  container.appendChild(toast);

  // Animation d'entrée
  requestAnimationFrame(() => toast.classList.add('show'));

  // Auto-suppression : On gère directement via setTimeout (sans transitionend)
  // car l'animation CSS ne définissait pas de transition de sortie.
  setTimeout(() => {
    toast.style.opacity = '0';
    toast.style.transform = 'translateY(10px) scale(0.95)';
    toast.style.transition = 'opacity 0.3s ease, transform 0.3s ease';
    
    // Le retrait du DOM après l'animation de sortie
    setTimeout(() => toast.remove(), 300);
  }, duration);
}