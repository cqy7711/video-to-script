"""设置对话框"""

import json
import os
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QLineEdit, QComboBox, QPushButton, QGroupBox,
    QFormLayout, QDialogButtonBox, QFileDialog
)
from PySide6.QtCore import Qt


SETTINGS_FILE = os.path.expanduser("~/.video-to-script-settings.json")
# Fallback to app directory if home dir is sandboxed
_SETTINGS_FILE_APP = os.path.join(os.path.dirname(__file__), "..", "settings.json")
_SETTINGS_FILE_APP = os.path.abspath(_SETTINGS_FILE_APP)

DEFAULT_SETTINGS = {
    "openai_api_key": "",
    "openai_base_url": "",
    "openai_model": "gpt-4o-mini",
    "whisper_model": "base",
    "scene_threshold": 35.0,
    "min_scene_duration": 2.0,
    "language": "",
    "cookie_file": "",
    "cookie_browser": "",      # 从浏览器自动读取Cookie（chrome/safari/edge/firefox等）
}


def _get_settings_file():
    """优先用 home 目录，权限不足时用应用目录"""
    try:
        if os.path.exists(SETTINGS_FILE):
            return SETTINGS_FILE
        # 测试 home 目录是否可写
        with open(SETTINGS_FILE, "w") as f:
            json.dump({}, f)
        os.remove(SETTINGS_FILE)
        return SETTINGS_FILE
    except Exception:
        return _SETTINGS_FILE_APP


def load_settings() -> dict:
    path = _get_settings_file()
    if os.path.exists(path):
        try:
            with open(path, "r") as f:
                saved = json.load(f)
                return {**DEFAULT_SETTINGS, **saved}
        except Exception:
            pass
    return DEFAULT_SETTINGS.copy()


def save_settings(settings: dict):
    path = _get_settings_file()
    with open(path, "w") as f:
        json.dump(settings, f, ensure_ascii=False, indent=2)


class SettingsDialog(QDialog):
    def __init__(self, settings: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("设置")
        self.setMinimumWidth(460)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        self.settings = settings.copy()
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(16)

        # OpenAI
        ai_group = QGroupBox("AI 分析")
        ai_layout = QFormLayout()
        ai_layout.setSpacing(10)

        key_row = QHBoxLayout()
        self.api_key_input = QLineEdit()
        self.api_key_input.setPlaceholderText("sk-...")
        self.api_key_input.setEchoMode(QLineEdit.Password)
        self.api_key_input.setText(self.settings.get("openai_api_key", ""))
        key_row.addWidget(self.api_key_input)

        toggle_btn = QPushButton("显示")
        toggle_btn.setFixedWidth(60)
        toggle_btn.setCheckable(True)
        def _toggle(checked):
            self.api_key_input.setEchoMode(QLineEdit.Normal if checked else QLineEdit.Password)
            toggle_btn.setText("隐藏" if checked else "显示")
        toggle_btn.toggled.connect(_toggle)
        key_row.addWidget(toggle_btn)
        ai_layout.addRow("API Key:", key_row)

        self.base_url_input = QLineEdit()
        self.base_url_input.setPlaceholderText("https://api.openai.com/v1（留空用默认）")
        self.base_url_input.setText(self.settings.get("openai_base_url", ""))
        ai_layout.addRow("API 地址:", self.base_url_input)

        base_hint = QLabel("💡 国内网络无法访问 OpenAI 时，可填入中转站地址")
        base_hint.setStyleSheet("color: #86868B; font-size: 11px;")
        base_hint.setWordWrap(True)
        ai_layout.addRow("", base_hint)

        self.model_combo = QComboBox()
        self.model_combo.addItems(["gpt-4o-mini", "gpt-4o", "gpt-4-turbo", "gpt-3.5-turbo", "deepseek-chat", "deepseek-reasoner"])
        idx = self.model_combo.findText(self.settings.get("openai_model", "gpt-4o-mini"))
        if idx >= 0:
            self.model_combo.setCurrentIndex(idx)
        ai_layout.addRow("模型:", self.model_combo)

        hint = QLabel("💡 填入 API Key 后可自动生成钩子分析、剧本和人物图谱")
        hint.setStyleSheet("color: #86868B; font-size: 11px;")
        hint.setWordWrap(True)
        ai_layout.addRow("", hint)

        ai_group.setLayout(ai_layout)
        layout.addWidget(ai_group)

        # Whisper
        whisper_group = QGroupBox("语音转写")
        whisper_layout = QFormLayout()
        whisper_layout.setSpacing(10)

        self.whisper_combo = QComboBox()
        self.whisper_combo.addItems(["tiny", "base", "small", "medium", "large"])
        idx = self.whisper_combo.findText(self.settings.get("whisper_model", "base"))
        if idx >= 0:
            self.whisper_combo.setCurrentIndex(idx)
        whisper_layout.addRow("Whisper 模型:", self.whisper_combo)

        model_hint = QLabel("tiny最快 | base平衡 | small推荐 | medium精确 | large最准")
        model_hint.setStyleSheet("color: #86868B; font-size: 11px;")
        whisper_layout.addRow("", model_hint)

        self.lang_combo = QComboBox()
        self.lang_combo.addItems(["自动检测", "中文", "英文", "日文", "韩文"])
        lang_map = {"": 0, "zh": 1, "en": 2, "ja": 3, "ko": 4}
        self.lang_combo.setCurrentIndex(lang_map.get(self.settings.get("language", ""), 0))
        whisper_layout.addRow("视频语言:", self.lang_combo)

        whisper_group.setLayout(whisper_layout)
        layout.addWidget(whisper_group)

        # 场景检测
        scene_group = QGroupBox("场景检测")
        scene_layout = QFormLayout()

        self.threshold_combo = QComboBox()
        self.threshold_combo.addItems(["25 (精细)", "30 (较精细)", "35 (推荐)", "40 (粗略)", "50 (极粗)"])
        threshold_map = {25: 0, 30: 1, 35: 2, 40: 3, 50: 4}
        self.threshold_combo.setCurrentIndex(threshold_map.get(int(self.settings.get("scene_threshold", 35)), 2))
        scene_layout.addRow("灵敏度:", self.threshold_combo)

        threshold_hint = QLabel("短剧推荐35，电影/长视频推荐25-30")
        threshold_hint.setStyleSheet("color: #86868B; font-size: 11px;")
        scene_layout.addRow("", threshold_hint)

        scene_group.setLayout(scene_layout)
        layout.addWidget(scene_group)

        # 视频下载
        download_group = QGroupBox("视频下载")
        download_layout = QFormLayout()
        download_layout.setSpacing(10)

        # ── 从浏览器读取 Cookie（推荐方式） ──
        browser_row = QHBoxLayout()
        self.cookie_browser_combo = QComboBox()
        self.cookie_browser_combo.addItems([
            "不使用", "Chrome", "Safari", "Edge", "Firefox", "Brave", "Opera", "Vivaldi"
        ])
        saved_browser = self.settings.get("cookie_browser", "")
        if saved_browser:
            idx = self.cookie_browser_combo.findText(saved_browser, Qt.MatchFixedString)
            if idx >= 0:
                self.cookie_browser_combo.setCurrentIndex(idx)
        else:
            self.cookie_browser_combo.setCurrentIndex(0)
        browser_row.addWidget(self.cookie_browser_combo)
        download_layout.addRow("浏览器 Cookie:", browser_row)

        browser_hint = QLabel(
            "🔒 推荐方式：直接从浏览器读取登录态（需浏览器已登录抖音/B站等）\n"
            "macOS 可能需要输入系统密码来解密 Cookie"
        )
        browser_hint.setStyleSheet("color: #86868B; font-size: 11px;")
        browser_hint.setWordWrap(True)
        download_layout.addRow("", browser_hint)

        # ── Cookie 文件（手动导出方式） ──
        cookie_row = QHBoxLayout()
        self.cookie_input = QLineEdit()
        self.cookie_input.setPlaceholderText("手动导出的 Cookie 文件路径（备选）...")
        self.cookie_input.setText(self.settings.get("cookie_file", ""))
        cookie_row.addWidget(self.cookie_input)
        cookie_browse = QPushButton("选择")
        cookie_browse.setFixedWidth(60)
        def _browse_cookie():
            path, _ = QFileDialog.getOpenFileName(self, "选择 Cookie 文件", "", "所有文件 (*);;文本文件 (*.txt)")
            if path:
                self.cookie_input.setText(path)
        cookie_browse.clicked.connect(_browse_cookie)
        cookie_row.addWidget(cookie_browse)
        download_layout.addRow("Cookie 文件:", cookie_row)

        cookie_hint = QLabel(
            '💡 抖音短剧需要登录才能下载完整剧集。优先选择「浏览器 Cookie」方式，'
            '无需手动导出。如浏览器方式不可用，可用浏览器插件导出 Cookie 文件。'
        )
        cookie_hint.setStyleSheet("color: #86868B; font-size: 11px;")
        cookie_hint.setWordWrap(True)
        download_layout.addRow("", cookie_hint)

        download_group.setLayout(download_layout)
        layout.addWidget(download_group)

        # 按钮
        btn_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btn_box.accepted.connect(self._accept)
        btn_box.rejected.connect(self.reject)
        layout.addWidget(btn_box)

    def _accept(self):
        self.settings["openai_api_key"] = self.api_key_input.text().strip()
        self.settings["openai_base_url"] = self.base_url_input.text().strip()
        self.settings["openai_model"] = self.model_combo.currentText()
        self.settings["whisper_model"] = self.whisper_combo.currentText()
        lang_map = {0: "", 1: "zh", 2: "en", 3: "ja", 4: "ko"}
        self.settings["language"] = lang_map.get(self.lang_combo.currentIndex(), "")
        threshold_map = {0: 25.0, 1: 30.0, 2: 35.0, 3: 40.0, 4: 50.0}
        self.settings["scene_threshold"] = threshold_map.get(self.threshold_combo.currentIndex(), 35.0)
        self.settings["cookie_file"] = self.cookie_input.text().strip()
        browser_text = self.cookie_browser_combo.currentText()
        self.settings["cookie_browser"] = "" if browser_text == "不使用" else browser_text
        try:
            save_settings(self.settings)
        except Exception as e:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "保存失败", f"设置保存失败：{e}\n设置将在本次运行中生效，但不会持久化保存。")
        self.accept()

    def get_settings(self) -> dict:
        return self.settings
