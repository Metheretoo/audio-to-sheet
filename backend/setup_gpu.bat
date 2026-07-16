@echo off
chcp 65001 >nul
echo.
echo ============================================================
echo   Installation GPU Intel ARC - audio-to-sheet
echo ============================================================
echo.

REM Vérifier si conda est disponible
where conda >nul 2>nul
if %errorlevel% equ 0 (
    echo [INFO] Conda detecte, utilisation de l'environnement existant.
    call conda activate v3 2>nul
    if %errorlevel% neq 0 (
        echo [WARN] Environnement v3 introuvable, creation...
        call conda create -n v3 python=3.10 -y
        call conda activate v3
    )
) else (
    echo [INFO] Conda non detecte, utilisation de pip standard.
)

echo.
echo [1/4] Desinstallation de PyTorch CPU...
pip uninstall torch torchaudio torchvision -y 2>nul

echo.
echo [2/4] Installation de PyTorch avec support XPU (Intel ARC)...
pip install torch torchaudio torchvision --index-url https://download.pytorch.org/whl/xpu

if %errorlevel% neq 0 (
    echo.
    echo [ERROR] L'installation de PyTorch XPU a echoue.
    echo        Verifiez votre connexion internet.
    goto :error
)
echo [OK] PyTorch XPU installe.

echo.
echo [3/4] Note: IPEX est Linux-only sur Windows, PyTorch XPU inclut les optimisations.

echo.
echo [4/4] Verification des devices disponibles...
python -c "
import torch
print('PyTorch version:', torch.__version__)
print('CUDA disponible:', torch.cuda.is_available())

try:
    has_xpu = hasattr(torch, 'xpu') and torch.xpu.is_available()
    print('XPU (Intel) disponible:', has_xpu)
    if has_xpu:
        print('Device:', torch.xpu.get_device_name(0))
except Exception as e:
    print('XPU erreur:', e)

if not torch.cuda.is_available():
    try:
        has_xpu = hasattr(torch, 'xpu') and torch.xpu.is_available()
        if not has_xpu:
            print()
            print('ATTENTION: Aucun GPU detecte !')
            print('Pour utiliser votre Intel ARC A770:')
            print('  1. Verifiez que le pilote Intel est installe')
            print('  2. Installez IPEX: pip install intel-extension-for-pytorch')
            print('  3. Redemarrez le serveur')
    except:
        pass
"

echo.
echo [5/4] Mise a jour des dependances...
pip install -r requirements.txt 2>nul || echo [WARN] Erreur installation dependances

echo.
echo ============================================================
echo   Installation terminee !
echo   Pour verifier:  python backend/validate_gpu.py
echo   Pour demarrer:   run_prod.bat
echo ============================================================
echo.
pause
goto :end

:error
echo.
echo [ERROR] L'installation GPU a echoue.
echo          Verifiez que:
echo            1. Le pilote Intel ARC est installe (derniere version)
echo            2. Windows 10/11 avec le kit de commandes Intel GPU
echo            3. Votre carte est bien une Intel ARC (A770, A750, etc.)
echo.

:end
