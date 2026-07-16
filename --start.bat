@echo off
setlocal EnableDelayedExpansion
title AudioScore — Transcription Piano
color 0B
cd /d "%~dp0"

echo.
echo  ============================================================
echo   ^>^>  AudioScore  --  Transcription Audio ^> Partition Piano
echo  ============================================================
echo.

REM ── Vérification Python ──────────────────────────────────────────────────
python --version >nul 2>&1
if errorlevel 1 (
    echo  [ERREUR] Python n'est pas detecte dans PATH.
    echo  Installez Python 3.9+ depuis : https://python.org
    echo.
    pause
    exit /b 1
)
for /f "tokens=2" %%v in ('python --version 2^>^&1') do set PY_VER=%%v
echo  [OK] Python detecte : %PY_VER%

REM ── Environnement virtuel ─────────────────────────────────────────────────
if not exist "venv\Scripts\activate.bat" (
    echo  [INFO] Creation de l'environnement virtuel...
    python -m venv venv
    if errorlevel 1 (
        echo  [ERREUR] Impossible de creer le venv.
        pause
        exit /b 1
    )
)

call venv\Scripts\activate.bat
echo  [OK] Environnement virtuel active.

REM ── Installation des dependances Python ───────────────────────────────────
echo  [INFO] Verification des dependances Python...
pip install -r backend\requirements.txt -q --disable-pip-version-check
if errorlevel 1 (
    echo  [ATTENTION] Certaines dependances n'ont pas pu etre installees.
    echo  Verifiez votre connexion internet pour la 1ere utilisation.
)
echo  [OK] Dependances Python prets.

REM ── Telechargement de VexFlow (une seule fois) ────────────────────────────
if not exist "frontend\js\lib\vexflow.js" (
    echo  [INFO] Telechargement de VexFlow 4 (necessaire une seule fois)...
    if not exist "frontend\js\lib" mkdir "frontend\js\lib"
    curl -L --silent --show-error ^
        "https://cdn.jsdelivr.net/npm/vexflow@4.2.3/build/cjs/vexflow.js" ^
        -o "frontend\js\lib\vexflow.js"
    if errorlevel 1 (
        echo  [ATTENTION] Echec du telechargement de VexFlow.
        echo  Connexion internet requise pour la premiere utilisation.
        echo  Reessayez apres avoir verifie votre connexion.
        pause
        exit /b 1
    )
    echo  [OK] VexFlow telecharge.
) else (
    echo  [OK] VexFlow deja present.
)

REM ── Creation des dossiers nécessaires ─────────────────────────────────────
if not exist "uploads"  mkdir uploads
if not exist "outputs"  mkdir outputs

REM ── Ouverture du navigateur (apres 2 secondes) ───────────────────────────
echo.
echo  [INFO] Ouverture du navigateur dans 2 secondes...
start "" /B cmd /c "timeout /t 2 /nobreak >nul && start http://localhost:5000"

REM ── Demarrage du serveur Flask ────────────────────────────────────────────
echo.
echo  ============================================================
echo   Serveur demarre sur : http://localhost:5000
echo   Appuyez sur Ctrl+C pour arreter.
echo  ============================================================
echo.
venv\Scripts\python.exe backend\app.py

REM ── Fin ───────────────────────────────────────────────────────────────────
echo.
echo  Serveur arrete. Appuyez sur une touche pour fermer.
pause >nul
