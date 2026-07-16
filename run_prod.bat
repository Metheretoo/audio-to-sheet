@echo off
cd /d "%~dp0"

echo [1/4] Activation venv...
call venv\Scripts\activate

echo [2/4] Verification dependances...
python -c "import flask, numpy, mido" 2>nul
if errorlevel 1 (
    echo [INFO] Installation des dependances...
    python -m pip install --upgrade pip
    python -m pip install -r backend/requirements.txt
)

echo [3/4] Verification GPU XPU...
python -c "import torch; print('XPU:', torch.xpu.is_available() if hasattr(torch,'xpu') else False)"

echo [4/4] Lancement serveur...
python backend\app.py

pause