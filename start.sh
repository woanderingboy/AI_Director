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
    echo "Ubuntu/Debian: sudo apt install python3 python3-pip python3-venv"
    echo "macOS: brew install python3"
    exit 1
fi

echo "[1/4] 检查 Python 版本..."
python3 --version
echo ""

# 准备虚拟环境（隔离依赖，避免污染系统 Python）
echo "[2/4] 准备虚拟环境 (.venv)..."
if [ ! -d ".venv" ]; then
    python3 -m venv .venv
    echo "  已创建虚拟环境 .venv"
else
    echo "  复用已有 .venv"
fi
# shellcheck disable=SC1091
source .venv/bin/activate
echo "  已激活虚拟环境"
echo ""

# 安装依赖
echo "[3/4] 安装依赖（首次运行较慢）..."
pip install -r requirements.txt -q 2>/dev/null || pip install -r requirements.txt -q -i https://pypi.tuna.tsinghua.edu.cn/simple
echo "依赖安装完成！"
echo ""

# 启动服务
echo "[4/4] 启动 AI Director..."
echo ""
echo "  ╔══════════════════════════════════════════╗"
echo "  ║  浏览器访问: http://127.0.0.1:5000       ║"
echo "  ║  按 Ctrl+C 停止服务                      ║"
echo "  ╚══════════════════════════════════════════╝"
echo ""
echo "  [提示] 默认离线模式(Mock)，无需任何 API Key 即可跑通全功能。"
echo "  [提示] 首次使用字幕/语音功能，faster-whisper 会自动下载语音模型(约数百 MB)，请保持联网。"
echo "  [提示] 要接入真实大模型：cp .env.example .env 并填入 Key，再把 AI_DIRECTOR_OFFLINE 改为 0。"
echo ""

export AI_DIRECTOR_OFFLINE=1
python app.py
