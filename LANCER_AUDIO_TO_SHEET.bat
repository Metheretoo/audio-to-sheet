@echo off
title AudioScore - Demarrage Docker (NVIDIA)
echo ===================================================
echo     Audio-to-Sheet - Serveur IA (Version Docker)
echo ===================================================
echo.
echo Verification de Docker...
docker --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERREUR] Docker n'est pas installe ou n'est pas en cours d'execution.
    echo Veuillez lancer "Docker Desktop" avant d'executer ce script.
    pause
    exit /b
)

echo.
echo Lancement du conteneur...
echo (Le premier lancement prendra du temps pour telecharger les 5Go de PyTorch et CUDA)
docker compose up --build

pause
