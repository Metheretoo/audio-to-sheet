Set WshShell = CreateObject("WScript.Shell")
WshShell.Run Chr(34) & "run_prod.bat" & Chr(34), 0
Set WshShell = Nothing
CreateObject("WScript.Shell").Popup "Have fun !", 1, "(-_-)", vbOKOnly
