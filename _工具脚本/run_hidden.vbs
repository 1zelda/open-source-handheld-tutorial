' run_hidden.vbs - run a py.exe script without any console window, append output to a log.
' usage: wscript.exe run_hidden.vbs <script.py> <log.txt> [extra args...]
' Why: py.exe is a console program; Task Scheduler shows its window at logon/time triggers.
' Closing that window sends CTRL_CLOSE_EVENT and kills the task (exit code 3221225786).
' pythonw/pyw cannot be used because these scripts call print() and sys.stdout is None there.
Option Explicit
Dim a, cmd, sh, rc, i, py, logPath, scriptPath, fso, f, logDir, stamp

Set a = WScript.Arguments
If a.Count < 2 Then WScript.Quit 2

scriptPath = a(0)
logPath = a(1)
py = "C:\Windows\py.exe"

Set fso = CreateObject("Scripting.FileSystemObject")
logDir = fso.GetParentFolderName(logPath)
If Not fso.FolderExists(logDir) Then fso.CreateFolder logDir

' ASCII-only stamp: python writes UTF-8 into the same file, so keep this line ASCII
stamp = "----- run at " & Year(Now) & "-" & Right("0" & Month(Now), 2) & "-" & Right("0" & Day(Now), 2) & _
        " " & Right("0" & Hour(Now), 2) & ":" & Right("0" & Minute(Now), 2) & ":" & Right("0" & Second(Now), 2) & " -----"
Set f = fso.OpenTextFile(logPath, 8, True)
f.WriteLine stamp
f.Close

Set sh = CreateObject("WScript.Shell")
' force UTF-8 so Chinese output stays readable; inherited by the python child
On Error Resume Next
sh.Environment("PROCESS")("PYTHONIOENCODING") = "utf-8"
On Error GoTo 0

' 0 = SW_HIDE, True = wait so the task reports the real exit code and duration
cmd = Chr(34) & py & Chr(34) & " -3 " & Chr(34) & scriptPath & Chr(34)
For i = 2 To a.Count - 1
    cmd = cmd & " " & Chr(34) & a(i) & Chr(34)
Next
cmd = "cmd /c " & Chr(34) & cmd & " >> " & Chr(34) & logPath & Chr(34) & " 2>&1" & Chr(34)

rc = sh.Run(cmd, 0, True)
WScript.Quit rc
