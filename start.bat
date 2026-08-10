@echo off
chcp 65001 >nul
title AI Director · 个人AI导演生产系统

echo.
echo  ╔══════════════════════════════════════════╗
echo  ║   AI Director · 个人AI导演生产系统       ║
echo  ║   小说 → 剧本 → 分镜 → 资产 → 视频      ║
echo  ╚══════════════════════════════════════════╝
echo.

:: 检查 Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [错误] 未检测到 Python，请先安装 Python 3.10+
    echo 下载地址: https://www.python.org/downloads/
    echo 安装时请勾选 "Add Python to PATH"
    pause
    exit /b 1
)

echo [1/4] 检查 Python 版本...
python --version
echo.

:: 准备虚拟环境（隔离依赖，避免污染系统 Python）
echo [2/4] 准备虚拟环境 (.venv)...
if not exist ".venv" (
    python -m venv .venv
    echo   已创建虚拟环境 .venv
) else (
    echo   复用已有 .venv
)
call .venv\Scripts\activate.bat
echo   已激活虚拟环境
echo.

:: 安装依赖
echo [3/4] 安装依赖（首次运行较慢）...
pip install -r requirements.txt -q 2>nul
if %errorlevel% neq 0 (
    echo 正在使用国内镜像安装...
    pip install -r requirements.txt -q -i https://pypi.tuna.tsinghua.edu.cn/simple
)
echo 依赖安装完成！
echo.

:: 启动服务
echo [4/4] 启动 AI Director...
echo.
echo  ╔══════════════════════════════════════════╗
echo  ║  浏览器访问: http://127.0.0.1:5000       ║
echo  ║  按 Ctrl+C 停止服务                      ║
echo  ╚══════════════════════════════════════════╝
echo.
echo  [提示] 默认离线模式(Mock)，无需任何 API Key 即可跑通全功能。
echo  [提示] 首次使用字幕/语音功能，faster-whisper 会自动下载语音模型(约数百 MB)，请保持联网。
echo  [提示] 要接入真实大模型：cp .env.example .env 并填入 Key，再把 AI_DIRECTOR_OFFLINE 改为 0。
echo.

set AI_DIRECTOR_OFFLINE=1
python app.py

pause
