#!/bin/bash
# Video to Script — macOS 启动脚本
# 双击此文件即可启动应用
# 首次使用会自动安装所需依赖

set -e

# ─── 定位应用目录（兼容 symlink） ───
SCRIPT_PATH="$(cd "$(dirname "$0")" && pwd)"
APP_DIR="$(cd "$SCRIPT_PATH" && pwd)"

echo "=========================================="
echo "  🎬 Video to Script — 视频转剧本工具"
echo "=========================================="
echo ""

# ─── 检查 Python3 ───
PYTHON=""
if command -v python3 &>/dev/null; then
    PYTHON="$(command -v python3)"
    PY_VERSION="$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
    echo "✅ 检测到 Python $PY_VERSION ($PYTHON)"
elif command -v python &>/dev/null; then
    PYTHON="$(command -v python)"
    echo "✅ 检测到 Python ($PYTHON)"
else
    echo "❌ 未检测到 Python3，请先安装："
    echo "   方法1: 从 App Store 安装 Xcode Command Line Tools"
    echo "          打开终端运行: xcode-select --install"
    echo "   方法2: 从 https://www.python.org/downloads/ 下载安装"
    echo ""
    echo "按回车键退出..."
    read
    exit 1
fi

# ─── 检查 Python 版本 >= 3.9 ───
PY_MAJOR=$("$PYTHON" -c 'import sys; print(sys.version_info.major)')
PY_MINOR=$("$PYTHON" -c 'import sys; print(sys.version_info.minor)')
if [ "$PY_MAJOR" -lt 3 ] || ([ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 9 ]); then
    echo "❌ Python 版本过低 ($PY_MAJOR.$PY_MINOR)，需要 3.9+"
    echo "   请从 https://www.python.org/downloads/ 安装新版 Python"
    echo ""
    echo "按回车键退出..."
    read
    exit 1
fi

# ─── 检查 Homebrew ffmpeg（可选但推荐） ───
if command -v ffmpeg &>/dev/null; then
    echo "✅ 检测到 ffmpeg ($(ffmpeg -version | head -1))"
else
    echo "⚠️  未检测到 ffmpeg（应用会使用内置 ffmpeg，但安装系统版本更快）"
    echo "   可选安装: brew install ffmpeg"
fi

# ─── 检查/创建虚拟环境 ───
VENV_DIR="$APP_DIR/.venv"
if [ ! -d "$VENV_DIR" ]; then
    echo ""
    echo "📦 首次运行，正在创建虚拟环境并安装依赖..."
    echo "   （这可能需要几分钟，请耐心等待）"
    echo ""
    "$PYTHON" -m venv "$VENV_DIR"
    VENV_PIP="$VENV_DIR/bin/pip"
    "$VENV_PIP" install --upgrade pip -q
    "$VENV_PIP" install -r "$APP_DIR/requirements.txt" -q
    echo ""
    echo "✅ 依赖安装完成！"
fi

VENV_PYTHON="$VENV_DIR/bin/python3"

# ─── 检查依赖是否完整 ───
echo ""
echo "🔍 检查依赖..."
MISSING=()
for pkg in PySide6 whisper moviepy scenedetect openai yt_dlp; do
    if ! "$VENV_PYTHON" -c "import $pkg" 2>/dev/null; then
        MISSING+=("$pkg")
    fi
done

if [ ${#MISSING[@]} -gt 0 ]; then
    echo "📦 补充安装缺失依赖: ${MISSING[*]}"
    "$VENV_DIR/bin/pip" install -r "$APP_DIR/requirements.txt" -q
fi

echo "✅ 所有依赖就绪"
echo ""
echo "🎬 启动 Video to Script..."
echo ""

# ─── 启动应用 ───
cd "$APP_DIR"
exec "$VENV_PYTHON" main.py
