@echo off
rem 双击启动本地数据看板(只读)。关掉这个黑窗口 = 停止服务。
cd /d "%~dp0"
py -3 看板.py --open
if errorlevel 1 (
  echo.
  echo 启动失败:检查是否装了 Python 3,或 8090 端口是否已被占用。
  echo 换端口:py -3 看板.py --open --port 8123
  pause
)
