@echo off
rem Start OpenList (127.0.0.1:5244) + the data board (127.0.0.1:8090), then open its netdisk tab.
rem Since 11-05 the cookie form lives inside the board's netdisk tab, not a second UI on 5320.
rem This launcher only brings the services up; it never reads, writes or prints a credential.
cd /d "%~dp0"
py -3 start_netdisk.py
echo.
echo (exit code %ERRORLEVEL%)
pause
