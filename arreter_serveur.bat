echo Recherche et arret du processus ecoutant sur le port 5000...
for /f "tokens=5" %%a in ('netstat -aon ^| findstr :5000') do (
    echo Arret du processus PID %%a
    taskkill /f /pid %%a
)
REM echo Termine.
REM pause