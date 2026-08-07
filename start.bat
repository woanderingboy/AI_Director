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

echo [1/3] 检查 Python 版本...
python --version
echo.

:: 安装依赖
echo [2/3] 安装依赖（首次运行较慢）...
pip install -r requirements.txt -q 2>nul
if %errorlevel% neq 0 (
    echo 正在使用国内镜像安装...
    pip install -r requirements.txt -q -i https://pypi.tuna.tsinghua.edu.cn/simple
)
echo 依赖安装完成！
echo.

:: 启动服务
echo [3/3] 启动 AI Director...
echo.
echo  ╔══════════════════════════════════════════╗
echo  ║  浏览器访问: http://127.0.0.1:5000       ║
echo  ║  按 Ctrl+C 停止服务                      ║
echo  ╚══════════════════════════════════════════╝
echo.

set AI_DIRECTOR_OFFLINE=1
python app.py

pause
