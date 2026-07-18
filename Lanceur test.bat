@echo off
REM ============================================================================
REM  Lancer_AudioScore.bat  -  Remplacant de AudioScore.vbs
REM  A placer a la RACINE du projet (a cote du dossier backend\).
REM  Difference cle : la CONSOLE RESTE VISIBLE -> vous voyez les logs en direct
REM  (onset reellement applique, quantizer, methode tempo, pedale, warnings).
REM  Chemin PORTABLE : utilise le dossier du script (%~dp0), plus de D:\IA\... en dur.
REM ============================================================================

title AudioScore - Serveur (logs en direct)
chcp 65001 >nul
cd /d "%~dp0"

echo ============================================================
echo   AudioScore - demarrage du serveur
echo   Dossier : %CD%
echo ============================================================
echo.

REM --- 1. Tuer une eventuelle instance zombie du serveur -----------------------
taskkill /F /FI "COMMANDLINE eq *backend\app.py*" >nul 2>&1

REM --- 2. Activer l'environnement virtuel (si present) -------------------------
if exist "venv\Scripts\activate.bat" (
    call "venv\Scripts\activate.bat"
) else (
    echo [!] venv introuvable - utilisation du Python systeme
)

REM --- 3. Encodage UTF-8 pour les logs (accents, symboles musicaux) ------------
set PYTHONIOENCODING=utf-8

REM --- 4. Ouvrir le navigateur automatiquement une fois le serveur pret --------
REM     (fenetre separee qui attend 5 s puis ouvre l'interface)
start "" cmd /c "timeout /t 5 >nul & start "" http://localhost:5000"

echo Serveur en cours de demarrage... l'interface s'ouvrira dans ~5 secondes.
echo Laissez CETTE fenetre ouverte : elle affiche les logs de transcription.
echo Pour arreter le serveur : fermez cette fenetre ou faites Ctrl+C.
echo ------------------------------------------------------------
echo.

REM --- 5. Lancer le serveur EN AVANT-PLAN (logs visibles) ----------------------
python backend\app.py

echo.
echo ------------------------------------------------------------
echo Le serveur s'est arrete.
pause
