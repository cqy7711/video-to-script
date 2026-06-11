#!/bin/bash
# Video to Script — 双击启动
# 拖拽视频文件到终端窗口，或启动后在 app 里选择文件

PYTHON="/Users/11065343/.workbuddy/binaries/python/envs/default/bin/python3"
APP_DIR="/Users/11065343/WorkBuddy/2026-06-11-19-53-05/video-to-script-app"

# 检查依赖
echo "🔍 检查依赖..."
MISSING=()
for pkg in PySide6 whisper moviepy scenedetect openai; do
    if ! "$PYTHON" -c "import $pkg" 2>/dev/null; then
        MISSING+=("$pkg")
    fi
done

if [ ${#MISSING[@]} -gt 0 ]; then
    echo "📦 安装缺失依赖: ${MISSING[*]}"
    /Users/11065343/.workbuddy/binaries/python/envs/default/bin/pip install -q PySide6 openai-whisper moviepy imageio-ffmpeg scenedetect opencv-python-headless openai
fi

echo "🎬 启动 Video to Script..."
cd "$APP_DIR"
exec "$PYTHON" main.py
