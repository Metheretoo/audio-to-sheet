' AudioScore.vbs - Lance le serveur Flask et ouvre l'interface web
' Double-cliquez pour démarrer l'application audio-to-sheet

Set WshShell = CreateObject("WScript.Shell")
Set oHTTP   = CreateObject("MSXML2.XMLHTTP")

' ── Vérifier si le serveur est déjà en ligne ─────────────────────────────────
Dim serverRunning
serverRunning = False
On Error Resume Next
oHTTP.Open "GET", "http://localhost:5000/api/health", False
oHTTP.Send
If Err.Number = 0 And oHTTP.Status = 200 Then
    serverRunning = True
End If
On Error GoTo 0

If serverRunning Then
    ' Serveur déjà en route → ouvrir seulement le navigateur
    WshShell.Run "http://localhost:5000"
Else
    ' ── Tuer d'éventuelles instances zombie de app.py ────────────────────────
    ' (évite les conflits de port si un ancien processus est resté bloqué)
    WshShell.Run "cmd /c taskkill /F /FI ""COMMANDLINE eq *backend\app.py*"" >nul 2>&1", 0, True
    WScript.Sleep 500

    ' ── Démarrer le serveur Flask en arrière-plan (fenêtre masquée) ──────────
	WshShell.Run "cmd /c cd /d ""D:\IA\Antigravity\audio-to-sheet"" && set PYTHONIOENCODING=utf-8 && call venv\Scripts\activate.bat && python backend\app.py", 0

    ' ── Attendre que le serveur réponde (jusqu'à 30 s) ───────────────────────
    Dim tries, ready
    tries = 0
    ready = False
    Do While tries < 30 And Not ready
        WScript.Sleep 1000
        tries = tries + 1
        On Error Resume Next
        oHTTP.Open "GET", "http://localhost:5000/api/health", False
        oHTTP.Send
        If Err.Number = 0 And oHTTP.Status = 200 Then
            ready = True
        End If
        On Error GoTo 0
    Loop

    ' ── Ouvrir le navigateur ─────────────────────────────────────────────────
    WshShell.Run "http://localhost:5000"
End If

Set oHTTP   = Nothing
Set WshShell = Nothing