#!/bin/bash
echo ""
echo "  ╔══════════════════════════════════════════╗"
echo "  ║   AI Director · 个人AI导演生产系统       ║"
echo "  ║   小说 → 剧本 → 分镜 → 资产 → 视频      ║"
echo "  ╚══════════════════════════════════════════╝"
echo ""

# 检查 Python
if ! command -v python3 &> /dev/null; then
    echo "[错误] 未检测到 Python3"
    echo "Ubuntu/Debian: sudo apt install python3 python3-pip"
    echo "macOS: brew install python3"
    exit 1
fi

echo "[1/3] 检查 Python 版本..."
python3 --version
echo ""

echo "[2/3] 安装依赖..."
pip3 install -r requirements.txt -q 2>/dev/null || pip3 install -r requirements.txt -q -i https://pypi.tuna.tsinghua.edu.cn/simple
echo "依赖安装完成！"
echo ""

echo "[3/3] 启动 AI Director..."
echo ""
echo "  ╔══════════════════════════════════════════╗"
echo "  ║  浏览器访问: http://127.0.0.1:5000       ║"
echo "  ║  按 Ctrl+C 停止服务                      ║"
echo "  ╚══════════════════════════════════════════╝"
echo ""

export AI_DIRECTOR_OFFLINE=1
python3 app.py
