#!/usr/bin/env python
"""
validate_gpu.py — Validation de la détection GPU pour audio-to-sheet

Usage:
    python backend/validate_gpu.py

Ce script vérifie les devices GPU disponibles et aide à diagnostiquer
les problèmes d'accélération matérielle.
"""

import sys
import os

def main():
    print("=" * 60)
    print("  Validation GPU - audio-to-sheet v3")
    print("=" * 60)
    print()
    
    # ── 1. Vérification PyTorch ──────────────────────────────────────────
    try:
        import torch
        print(f"[OK] PyTorch version: {torch.__version__}")
    except ImportError:
        print("[ERREUR] PyTorch n'est pas installe.")
        print("         Installez-le avec: pip install torch torchaudio")
        print("         Pour Intel ARC: pip install intel-extension-for-pytorch")
        sys.exit(1)
    
    # ── 2. Vérification CUDA (NVIDIA) ────────────────────────────────────
    cuda_available = torch.cuda.is_available()
    print()
    print("--- NVIDIA GPU (CUDA) ---")
    if cuda_available:
        print(f"[OK] CUDA est disponible")
        print(f"     Nombre de GPU: {torch.cuda.device_count()}")
        for i in range(torch.cuda.device_count()):
            print(f"     GPU {i}: {torch.cuda.get_device_name(i)}")
        print()
        print("  → Le projet utilisera automatiquement CUDA.")
    else:
        print("[INFO] CUDA non disponible (pas de GPU NVIDIA)")
    
    # ── 3. Vérification Intel XPU ────────────────────────────────────────
    print()
    print("--- INTEL GPU (XPU / IPEX) ---")
    
    has_xpu = hasattr(torch, 'xpu')
    if not has_xpu:
        print("[INFO] torch.xpu n'existe pas dans cette version de PyTorch.")
        print("      Cela est normal si vous utilisez PyTorch standard.")
        print()
        print("  Pour activer le GPU Intel ARC A770:")
        print("  1. Desinstallez PyTorch standard:")
        print("     pip uninstall torch torchaudio -y")
        print("  2. Installez PyTorch avec support Intel XPU:")
        print("     pip install torch torchaudio --index-url https://download.pytorch.org/whl/xpu")
    else:
        xpu_available = torch.xpu.is_available()
        if xpu_available:
            print(f"[OK] XPU (Intel GPU) est disponible")
            print(f"     Device: {torch.xpu.get_device_name(0)}")
            print()
            print("  -> Le projet utilisera automatiquement votre GPU Intel.")
        else:
            print("[INFO] XPU detecte mais non disponible.")
            print("      Verifiez que le pilote Intel ARC est installe.")
    
    # ── 4. Vérification Demucs ───────────────────────────────────────────
    print()
    print("--- DEMUCS (separation audio) ---")
    try:
        import demucs
        print(f"[OK] Demucs est installe")
    except ImportError:
        print("[WARN] Demucs n'est pas installe.")
        print("       Installez-le avec: pip install demucs")
    
    # ── 5. Vérification piano_transcription_inference ────────────────────
    print()
    print("--- PIANO TRANSCRIPTION ---")
    try:
        from piano_transcription_inference import PianoTranscription
        print(f"[OK] piano_transcription_inference est installe")
        
        # Tenter de créer un modèle pour vérifier le device
        print("  Test de creation du modele...")
        try:
            model = PianoTranscription(device="cpu")
            print("  [OK] Modele charge en CPU")
            
            # Vérifier si le modèle peut être déplacé sur GPU
            if has_xpu and xpu_available:
                try:
                    model = PianoTranscription(device="xpu:0")
                    print("  [OK] Modele charge en XPU (Intel GPU)")
                except Exception as e:
                    print(f"  [WARN] Echec chargement XPU: {e}")
            elif cuda_available:
                try:
                    model = PianoTranscription(device="cuda:0")
                    print("  [OK] Modele charge en CUDA (NVIDIA GPU)")
                except Exception as e:
                    print(f"  [WARN] Echec chargement CUDA: {e}")
        except Exception as e:
            print(f"  [ERREUR] Impossible de charger le modele: {e}")
            
    except ImportError:
        print("[WARN] piano_transcription_inference n'est pas installe.")
        print("       Installez-le avec: pip install git+https://github.com/qiuqiangkong/piano_transcription_inference")
    
    # ── 6. Résumé ────────────────────────────────────────────────────────
    print()
    print("=" * 60)
    print("  RESUME")
    print("=" * 60)
    
    if cuda_available:
        print("  GPU recommande: NVIDIA CUDA")
        print("  Device par defaut: cuda:0")
    elif has_xpu and xpu_available:
        print("  GPU recommande: Intel XPU")
        print("  Device par defaut: xpu:0")
    else:
        print("  ⚠️  AUCUN GPU detecte !")
        print("  Le projet fonctionnera en CPU (rapide mais lent).")
        print()
        print("  Options pour activer le GPU:")
        print("  Option 1 - NVIDIA GPU:")
        print("    pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu118")
        print()
        print("  Option 2 - Intel ARC A770:")
        print("    pip uninstall torch torchaudio -y")
        print("    pip install torch torchaudio --index-url https://download.pytorch.org/whl/xpu")
    
    print()
    print("=" * 60)
    print("  Validation terminee.")
    print("=" * 60)
    print()

if __name__ == "__main__":
    main()