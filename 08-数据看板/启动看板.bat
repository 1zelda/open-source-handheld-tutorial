@echo off
chcp 936 >nul
title 开源掌机 · 数据看板 :8090    （这个黑窗口就是看板服务本体，别关）
cd /d "%~dp0"
set "LOG=%~dp0..\_scratch\看板-server.log"
if not exist "%~dp0..\_scratch" mkdir "%~dp0..\_scratch"
rem 已经在跑就直接开页面，别起第二个实例抢 8090
netstat -ano | findstr "127.0.0.1:8090" | findstr LISTENING >nul
if not errorlevel 1 (
  echo 看板已经在跑，直接打开页面。
  start "" http://127.0.0.1:8090/
  timeout /t 2 /nobreak >nul
  exit /b 0
)
set OPENED=
:loop
if not defined OPENED (
  set "OPENED=1"
  start "" http://127.0.0.1:8090/
)
echo [%date% %time%] 启动看板 >> "%LOG%"
py -3 看板.py --port 8090 >> "%LOG%" 2>&1
echo [%date% %time%] 进程退出了，3 秒后自动重启（原因看上面几行） >> "%LOG%"
timeout /t 3 /nobreak >nul
goto loop
