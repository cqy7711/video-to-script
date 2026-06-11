#!/bin/bash
# ============================================
# Video to Script — 打包分发脚本
# 同时生成 macOS 和 Windows 两个 ZIP 包
# ============================================

set -e

APP_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_NAME="Video-to-Script"
DIST_DIR="$APP_DIR/dist"
VERSION="2.1.7"

echo "=========================================="
echo "  📦 Video to Script v${VERSION} 打包工具"
echo "=========================================="
echo ""

# ─── 清理旧的构建 ───
if [ -d "$DIST_DIR" ]; then
    echo "🧹 清理旧的构建..."
    rm -rf "$DIST_DIR"
fi
mkdir -p "$DIST_DIR"

# ═══════════════════════════════════════
#  macOS 版本
# ═══════════════════════════════════════
echo ""
echo "🍎 打包 macOS 版本..."
echo ""

PKG_MAC="$DIST_DIR/${APP_NAME}-macOS"
mkdir -p "$PKG_MAC"

# ─── 复制核心文件 ───
cp -R "$APP_DIR/core" "$PKG_MAC/"
cp -R "$APP_DIR/ui" "$PKG_MAC/"
cp "$APP_DIR/main.py" "$PKG_MAC/"
cp "$APP_DIR/requirements.txt" "$PKG_MAC/"
cp "$APP_DIR/run.sh" "$PKG_MAC/"
cp "$APP_DIR/使用说明.md" "$PKG_MAC/"

# ─── 清理 ───
find "$PKG_MAC" -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
find "$PKG_MAC" -name "*.pyc" -delete 2>/dev/null || true
find "$PKG_MAC" -name ".DS_Store" -delete 2>/dev/null || true
[ -d "$PKG_MAC/.venv" ] && rm -rf "$PKG_MAC/.venv"

chmod +x "$PKG_MAC/run.sh"

# ─── 双击启动 ───
cat > "$PKG_MAC/双击启动.command" << 'LAUNCHER'
#!/bin/bash
# ========================================
# 🎬 Video to Script — 双击启动
# ========================================
#
# ⚠️ 如果双击后弹出「无法打开」提示：
#    请右键点击此文件 → 选择「打开」→ 点击「打开」确认
#    或者在终端运行: xattr -cr 文件夹路径
#
DIR="$(cd "$(dirname "$0")" && pwd)"
exec "$DIR/run.sh"
LAUNCHER
chmod +x "$PKG_MAC/双击启动.command"

# ─── macOS 安装前必读 ───
cat > "$PKG_MAC/安装前必读.txt" << 'README'
══════════════════════════════════════════
  🎬 Video to Script v2.1.7
  视频转剧本工具 — 安装前必读 (macOS)
══════════════════════════════════════════

▎三步开始使用

  第一步：安装 Python（如果还没有）
  ─────────────────────────────
  从 https://www.python.org/downloads/ 下载安装
  或在终端运行: xcode-select --install
  （需要 Python 3.9 或更高版本）

  第二步：启动应用
  ─────────────────────────────
  双击「双击启动.command」

  ⚠️ macOS 安全提示：
  如果双击后弹出「无法打开，因为无法验证开发者」：
  → 右键点击「双击启动.command」→ 选择「打开」→ 点击「打开」确认
  或者在终端运行以下命令解除限制：
    xattr -cr ~/Downloads/Video-to-Script-macOS/

  第三步：配置 AI 分析（首次使用）
  ─────────────────────────────
  启动后点击右上角 ⚙ 设置，填入：
  - API Key: 你的 DeepSeek API Key
  - API 地址: https://api.deepseek.com/v1
  - 模型: deepseek-chat

  API Key 获取: https://platform.deepseek.com/

▎首次启动说明
  第一次启动会自动安装依赖（约 3-5 分钟）
  Whisper 语音模型也会自动下载（约 150MB）
  之后启动只需几秒

▎详细使用说明
  请查看「使用说明.md」

▎系统要求
  - macOS 12.0 或更高版本
  - Python 3.9+
  - 约 2GB 磁盘空间（依赖+模型）

══════════════════════════════════════════
README

# ─── 打包 macOS ZIP ───
echo "📦 正在打包 macOS ZIP..."
cd "$DIST_DIR"
MAC_ZIP="${APP_NAME}-v${VERSION}-macOS.zip"
zip -r -q "$MAC_ZIP" "${APP_NAME}-macOS" -x "*.DS_Store"
MAC_SIZE=$(du -h "$MAC_ZIP" | cut -f1)
cp "$DIST_DIR/$MAC_ZIP" ~/Desktop/
echo "✅ macOS 版本已复制到桌面: ~/Desktop/$MAC_ZIP"

# ═══════════════════════════════════════
#  Windows 版本
# ═══════════════════════════════════════
echo ""
echo "🪟 打包 Windows 版本..."
echo ""

PKG_WIN="$DIST_DIR/${APP_NAME}-Windows"
mkdir -p "$PKG_WIN"

# ─── 复制核心文件 ───
cp -R "$APP_DIR/core" "$PKG_WIN/"
cp -R "$APP_DIR/ui" "$PKG_WIN/"
cp "$APP_DIR/main.py" "$PKG_WIN/"
cp "$APP_DIR/requirements.txt" "$PKG_WIN/"
cp "$APP_DIR/run.bat" "$PKG_WIN/"
cp "$APP_DIR/使用说明.md" "$PKG_WIN/"

# ─── 清理 ───
find "$PKG_WIN" -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
find "$PKG_WIN" -name "*.pyc" -delete 2>/dev/null || true
find "$PKG_WIN" -name ".DS_Store" -delete 2>/dev/null || true
[ -d "$PKG_WIN/.venv" ] && rm -rf "$PKG_WIN/.venv"

# ─── Windows 安装前必读 ───
cat > "$PKG_WIN/安装前必读.txt" << 'README'
══════════════════════════════════════════
  🎬 Video to Script v2.1.7
  视频转剧本工具 — 安装前必读 (Windows)
══════════════════════════════════════════

▎三步开始使用

  第一步：安装 Python（如果还没有）
  ─────────────────────────────
  从 https://www.python.org/downloads/ 下载安装
  （需要 Python 3.9 或更高版本）

  ⚠️ 安装时务必勾选「Add Python to PATH」！
  这是新手最常漏掉的一步！

  第二步：启动应用
  ─────────────────────────────
  双击「双击启动.bat」

  如果双击后闪退：
  → 请先确认 Python 已正确安装并在 PATH 中
  → 打开 CMD 运行: python --version
  → 如果提示"找不到命令"，说明安装时没勾选 PATH，需要重新安装

  第三步：配置 AI 分析（首次使用）
  ─────────────────────────────
  启动后点击右上角 ⚙ 设置，填入：
  - API Key: 你的 DeepSeek API Key
  - API 地址: https://api.deepseek.com/v1
  - 模型: deepseek-chat

  API Key 获取: https://platform.deepseek.com/

▎首次启动说明
  第一次启动会自动创建虚拟环境并安装依赖（约 3-5 分钟）
  Whisper 语音模型也会自动下载（约 150MB）
  之后启动只需几秒

▎常见问题

  Q: 双击 .bat 后一闪而过？
  A: Python 没有安装或不在 PATH 中。
     解决: 重新安装 Python，勾选「Add Python to PATH」

  Q: 提示"pip 安装失败"？
  A: 可能是网络问题。可以设置国内镜像：
     在 CMD 中运行:
     pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple

  Q: 安装 ffmpeg（可选但推荐）？
  A: 从 https://ffmpeg.org/download.html 下载 Windows 版
     解压后将 bin 目录添加到系统 PATH

▎详细使用说明
  请查看「使用说明.md」

▎系统要求
  - Windows 10 或更高版本
  - Python 3.9+（安装时勾选 Add to PATH）
  - 约 2GB 磁盘空间（依赖+模型）

══════════════════════════════════════════
README

# ─── 创建 Windows 双击启动 ───
cat > "$PKG_WIN/双击启动.bat" << 'LAUNCHER'
@echo off
chcp 65001 >nul 2>nul
title Video to Script
:: 双击此文件启动 Video to Script
DIR="%~dp0"
DIR=%DIR:~0,-1%
call "%DIR%\run.bat"
LAUNCHER

# ─── 打包 Windows ZIP ───
echo "📦 正在打包 Windows ZIP..."
cd "$DIST_DIR"
WIN_ZIP="${APP_NAME}-v${VERSION}-Windows.zip"
zip -r -q "$WIN_ZIP" "${APP_NAME}-Windows" -x "*.DS_Store"
WIN_SIZE=$(du -h "$WIN_ZIP" | cut -f1)
cp "$DIST_DIR/$WIN_ZIP" ~/Desktop/
echo "✅ Windows 版本已复制到桌面: ~/Desktop/$WIN_ZIP"

# ═══════════════════════════════════════
#  汇总
# ═══════════════════════════════════════
echo ""
echo "=========================================="
echo "  ✅ 全部打包完成！"
echo "=========================================="
echo ""
echo "  🍎 macOS:  ~/Desktop/$MAC_ZIP ($MAC_SIZE)"
echo "  🪟 Windows: ~/Desktop/$WIN_ZIP ($WIN_SIZE)"
echo ""
echo "  使用方法："
echo "  1. 解压对应的 ZIP 文件"
echo "  2. 先看「安装前必读.txt」"
echo "  3. macOS: 双击「双击启动.command」"
echo "     Windows: 双击「双击启动.bat」"
echo "  4. 首次会自动安装依赖"
echo "  5. 启动后在设置中配置 API Key"
echo ""
echo "=========================================="
