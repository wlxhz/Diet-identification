Option Explicit

Dim fso, shell, shellApp, projectRoot, appUrl, pythonExe, appPath
Dim candidates, candidate, request, attempt, ready

Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")
Set shellApp = CreateObject("Shell.Application")

projectRoot = fso.GetParentFolderName(WScript.ScriptFullName)
appUrl = "http://127.0.0.1:5100"
appPath = fso.BuildPath(projectRoot, "app.py")
pythonExe = ""

candidates = Array( _
    fso.BuildPath(projectRoot, ".venv\Scripts\pythonw.exe"), _
    fso.BuildPath(projectRoot, ".venv\Scripts\python.exe"), _
    "C:\Users\czy08\AppData\Local\hermes\hermes-agent\venv\Scripts\pythonw.exe", _
    "C:\Users\czy08\AppData\Local\hermes\hermes-agent\venv\Scripts\python.exe" _
)

For Each candidate In candidates
    If fso.FileExists(candidate) Then
        pythonExe = candidate
        Exit For
    End If
Next

ready = IsApplicationReady(appUrl)

If Not ready Then
    If pythonExe = "" Then
        MsgBox "Python was not found. The admin application cannot start.", vbCritical, "Admin application error"
        WScript.Quit 1
    End If

    shell.CurrentDirectory = projectRoot
    shell.Environment("PROCESS")("PYTHONUTF8") = "1"
    shell.Run Q(pythonExe) & " " & Q(appPath), 0, False

    For attempt = 1 To 100
        WScript.Sleep 200
        If IsApplicationReady(appUrl) Then
            ready = True
            Exit For
        End If
    Next
End If

If ready Then
    shellApp.ShellExecute appUrl, "", "", "open", 1
    WScript.Quit 0
End If

MsgBox "The admin application did not start. Please try again.", vbCritical, "Admin application error"
WScript.Quit 1

Function IsApplicationReady(url)
    On Error Resume Next
    Dim http
    Set http = CreateObject("WinHttp.WinHttpRequest.5.1")
    http.SetTimeouts 300, 300, 300, 300
    http.Open "GET", url, False
    http.Send
    IsApplicationReady = (Err.Number = 0 And http.Status >= 200 And http.Status < 500)
    Err.Clear
    On Error GoTo 0
End Function

Function Q(value)
    Q = Chr(34) & value & Chr(34)
End Function
