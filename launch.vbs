Dim fso, dir, shell
Set fso   = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")

dir = fso.GetParentFolderName(WScript.ScriptFullName)

' Utilise pythonw.exe pour ne pas afficher de fenetre CMD
shell.Run "pythonw.exe """ & dir & "\main.py""", 0, False
