"""主窗口 — 浅色简洁风，支持本地文件和视频链接"""

import os
import threading
import base64
from io import BytesIO
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QFrame,
    QLabel, QPushButton, QTabWidget, QTextEdit, QProgressBar,
    QFileDialog, QApplication, QLineEdit, QStackedWidget
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QDragEnterEvent, QDropEvent, QImage

from core.pipeline import VideoToScriptPipeline, AnalysisResult
from core.downloader import download_video, get_video_info_only, detect_platform
from ui.settings_dialog import SettingsDialog, load_settings, save_settings


class DropZone(QFrame):
    file_dropped = Signal(str)

    def __init__(self):
        super().__init__()
        self.setAcceptDrops(True)
        self.setObjectName("dropZone")
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignCenter)
        layout.setSpacing(8)
        icon = QLabel("🎬")
        icon.setObjectName("dropIcon")
        icon.setAlignment(Qt.AlignCenter)
        layout.addWidget(icon)
        text = QLabel("拖拽视频文件到这里")
        text.setObjectName("dropText")
        text.setAlignment(Qt.AlignCenter)
        layout.addWidget(text)
        hint = QLabel("或者点击下方按钮选择文件 · 支持 MP4 / MOV / MKV / AVI / WEBM")
        hint.setObjectName("dropHint")
        hint.setAlignment(Qt.AlignCenter)
        hint.setWordWrap(True)
        layout.addWidget(hint)

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            url = event.mimeData().urls()[0]
            if url.isLocalFile():
                ext = os.path.splitext(url.toLocalFile())[1].lower()
                if ext in (".mp4", ".mov", ".mkv", ".avi", ".webm"):
                    self.setProperty("dragOver", True)
                    self.style().unpolish(self)
                    self.style().polish(self)
                    event.acceptProposedAction()

    def dragLeaveEvent(self, event):
        self.setProperty("dragOver", False)
        self.style().unpolish(self)
        self.style().polish(self)

    def dropEvent(self, event: QDropEvent):
        self.setProperty("dragOver", False)
        self.style().unpolish(self)
        self.style().polish(self)
        url = event.mimeData().urls()[0]
        self.file_dropped.emit(url.toLocalFile())


class URLInputZone(QFrame):
    """链接输入区域"""
    download_requested = Signal(str)  # URL
    preview_requested = Signal(str)   # URL

    def __init__(self):
        super().__init__()
        self.setObjectName("urlZone")
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # 标题
        header = QHBoxLayout()
        icon = QLabel("🔗")
        icon.setStyleSheet("font-size: 24px;")
        header.addWidget(icon)
        title = QLabel("粘贴视频链接")
        title.setStyleSheet("font-size: 15px; font-weight: 500; color: #1D1D1F;")
        header.addWidget(title)
        header.addStretch()
        # 平台标签
        self.platform_tag = QLabel("")
        self.platform_tag.setObjectName("platformTag")
        self.platform_tag.setStyleSheet(
            "font-size: 11px; padding: 2px 8px; border-radius: 4px; "
            "background-color: #F0F5FF; color: #007AFF; font-weight: 500;"
        )
        self.platform_tag.setVisible(False)
        header.addWidget(self.platform_tag)
        layout.addLayout(header)

        # 输入框
        url_layout = QHBoxLayout()
        url_layout.setSpacing(8)
        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("粘贴抖音/YouTube/B站/快手等视频链接...")
        self.url_input.setObjectName("urlInput")
        self.url_input.setStyleSheet(
            "QLineEdit { border: 1px solid #E5E5EA; border-radius: 8px; "
            "padding: 10px 14px; font-size: 13px; background-color: #FFFFFF; }"
            "QLineEdit:focus { border-color: #007AFF; }"
        )
        self.url_input.textChanged.connect(self._on_url_changed)
        url_layout.addWidget(self.url_input, 1)

        self.preview_btn = QPushButton("预览")
        self.preview_btn.setObjectName("urlPreviewBtn")
        self.preview_btn.setStyleSheet(
            "QPushButton { background-color: transparent; border: 1px solid #E5E5EA; "
            "border-radius: 8px; padding: 8px 16px; color: #636366; font-weight: 500; }"
            "QPushButton:hover { background-color: #F5F5F7; }"
            "QPushButton:disabled { color: #C7C7CC; }"
        )
        self.preview_btn.setEnabled(False)
        url_layout.addWidget(self.preview_btn)

        self.download_btn = QPushButton("⬇ 下载")
        self.download_btn.setObjectName("urlDownloadBtn")
        self.download_btn.setStyleSheet(
            "QPushButton { background-color: #007AFF; color: white; border: none; "
            "border-radius: 8px; padding: 8px 20px; font-weight: 500; }"
            "QPushButton:hover { background-color: #0066D6; }"
            "QPushButton:disabled { background-color: #B0D4FF; color: #E5E5EA; }"
        )
        self.download_btn.setEnabled(False)
        url_layout.addWidget(self.download_btn)
        layout.addLayout(url_layout)

        # 预览信息区
        self.preview_frame = QFrame()
        self.preview_frame.setObjectName("previewFrame")
        self.preview_frame.setStyleSheet(
            "QFrame { background-color: #F5F5F7; border-radius: 8px; padding: 8px 12px; }"
        )
        self.preview_frame.setVisible(False)
        pv_layout = QVBoxLayout(self.preview_frame)
        pv_layout.setSpacing(4)
        self.preview_title = QLabel("")
        self.preview_title.setStyleSheet("font-size: 13px; font-weight: 500;")
        pv_layout.addWidget(self.preview_title)
        self.preview_detail = QLabel("")
        self.preview_detail.setStyleSheet("font-size: 11px; color: #86868B;")
        self.preview_detail.setWordWrap(True)
        pv_layout.addWidget(self.preview_detail)
        layout.addWidget(self.preview_frame)

        # 支持平台提示
        hint = QLabel("支持 抖音 · YouTube · B站 · 快手 · 西瓜 · 微博 · TikTok · Instagram 等 1000+ 平台")
        hint.setStyleSheet("font-size: 10px; color: #AEAEB2;")
        hint.setWordWrap(True)
        layout.addWidget(hint)

    def _on_url_changed(self, text):
        has_url = bool(text.strip()) and text.strip().startswith("http")
        self.preview_btn.setEnabled(has_url)
        self.download_btn.setEnabled(has_url)
        # 实时识别平台
        if has_url:
            platform = detect_platform(text.strip())
            self.platform_tag.setText(platform)
            self.platform_tag.setVisible(True)
        else:
            self.platform_tag.setVisible(False)

    def show_preview(self, title, platform, duration, uploader):
        self.preview_frame.setVisible(True)
        self.preview_title.setText(f"📹 {title}")
        dur_str = f"{int(duration // 60)}:{int(duration % 60):02d}" if duration else "未知"
        self.preview_detail.setText(f"平台: {platform} · 时长: {dur_str} · 作者: {uploader}")


class InputSwitch(QFrame):
    """输入模式切换：本地文件 / 视频链接"""
    mode_changed = Signal(str)  # "local" or "url"

    def __init__(self):
        super().__init__()
        self.setObjectName("inputSwitch")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.local_btn = QPushButton("📁 本地文件")
        self.local_btn.setObjectName("switchBtnActive")
        self.local_btn.setCheckable(True)
        self.local_btn.setChecked(True)
        layout.addWidget(self.local_btn)

        self.url_btn = QPushButton("🔗 视频链接")
        self.url_btn.setObjectName("switchBtn")
        self.url_btn.setCheckable(True)
        layout.addWidget(self.url_btn)

        self.local_btn.clicked.connect(lambda: self._switch("local"))
        self.url_btn.clicked.connect(lambda: self._switch("url"))

    def _switch(self, mode):
        self.local_btn.setChecked(mode == "local")
        self.url_btn.setChecked(mode == "url")
        # 样式切换
        active_style = (
            "QPushButton { background-color: #007AFF; color: white; border: none; "
            "border-radius: 6px; padding: 6px 16px; font-weight: 500; font-size: 12px; }"
        )
        inactive_style = (
            "QPushButton { background-color: transparent; color: #86868B; border: none; "
            "border-radius: 6px; padding: 6px 16px; font-weight: 500; font-size: 12px; }"
            "QPushButton:hover { background-color: #F5F5F7; }"
        )
        self.local_btn.setStyleSheet(active_style if mode == "local" else inactive_style)
        self.url_btn.setStyleSheet(active_style if mode == "url" else inactive_style)
        self.mode_changed.emit(mode)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Video to Script")
        self.setMinimumSize(860, 640)
        self.resize(960, 700)
        self.settings = load_settings()
        self.result = None
        self.is_analyzing = False
        self.is_downloading = False
        self.video_path = ""
        self.video_source = ""  # "local" or "url"
        self._setup_ui()
        self._connect_signals()

    def _setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # 顶栏
        top_bar = QFrame()
        top_bar.setObjectName("topBar")
        top_bar.setFixedHeight(56)
        top_layout = QHBoxLayout(top_bar)
        top_layout.setContentsMargins(20, 0, 20, 0)
        title = QLabel("Video to Script")
        title.setObjectName("appTitle")
        top_layout.addWidget(title)
        subtitle = QLabel("视频转剧本")
        subtitle.setObjectName("appSubtitle")
        top_layout.addWidget(subtitle)
        top_layout.addStretch()
        self.settings_btn = QPushButton("⚙ 设置")
        self.settings_btn.setObjectName("settingsBtn")
        top_layout.addWidget(self.settings_btn)
        main_layout.addWidget(top_bar)

        # 内容
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(24, 20, 24, 24)
        content_layout.setSpacing(16)

        # 输入模式切换
        self.input_switch = InputSwitch()
        content_layout.addWidget(self.input_switch)

        # 输入区域（Stacked：本地 / 链接）
        self.input_stack = QStackedWidget()

        # Page 0: 本地文件
        local_page = QWidget()
        local_layout = QHBoxLayout(local_page)
        local_layout.setSpacing(16)
        self.drop_zone = DropZone()
        self.drop_zone.setMinimumHeight(140)
        local_layout.addWidget(self.drop_zone, 3)

        right = QVBoxLayout()
        right.setSpacing(12)
        self.file_info_frame = QFrame()
        self.file_info_frame.setObjectName("fileInfo")
        fi_layout = QVBoxLayout(self.file_info_frame)
        fi_layout.setSpacing(6)
        self.file_name_label = QLabel("尚未选择文件")
        self.file_name_label.setStyleSheet("font-weight: 500; font-size: 14px;")
        fi_layout.addWidget(self.file_name_label)
        self.file_detail_label = QLabel("")
        self.file_detail_label.setStyleSheet("color: #86868B; font-size: 12px;")
        fi_layout.addWidget(self.file_detail_label)
        self.api_status_label = QLabel("")
        self.api_status_label.setStyleSheet("font-size: 11px;")
        fi_layout.addWidget(self.api_status_label)
        fi_layout.addStretch()
        right.addWidget(self.file_info_frame)
        self.browse_btn = QPushButton("📁 选择文件")
        self.browse_btn.setObjectName("settingsBtn")
        right.addWidget(self.browse_btn)
        self.analyze_btn = QPushButton("▶ 开始分析")
        self.analyze_btn.setObjectName("analyzeBtn")
        self.analyze_btn.setEnabled(False)
        right.addWidget(self.analyze_btn)
        right.addStretch()
        local_layout.addLayout(right, 2)
        self.input_stack.addWidget(local_page)

        # Page 1: 视频链接
        url_page = QWidget()
        url_layout = QVBoxLayout(url_page)
        url_layout.setSpacing(12)
        self.url_zone = URLInputZone()
        url_layout.addWidget(self.url_zone)

        # 链接模式的文件信息
        self.url_file_info = QFrame()
        self.url_file_info.setObjectName("fileInfo")
        ufi_layout = QVBoxLayout(self.url_file_info)
        ufi_layout.setSpacing(6)
        self.url_file_name = QLabel("尚未下载视频")
        self.url_file_name.setStyleSheet("font-weight: 500; font-size: 14px;")
        ufi_layout.addWidget(self.url_file_name)
        self.url_file_detail = QLabel("")
        self.url_file_detail.setStyleSheet("color: #86868B; font-size: 12px;")
        ufi_layout.addWidget(self.url_file_detail)
        ufi_layout.addStretch()
        url_layout.addWidget(self.url_file_info)
        self.input_stack.addWidget(url_page)

        content_layout.addWidget(self.input_stack)

        # 进度
        progress_frame = QFrame()
        pf_layout = QHBoxLayout(progress_frame)
        pf_layout.setContentsMargins(0, 0, 0, 0)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFixedHeight(6)
        self.progress_bar.setTextVisible(False)
        pf_layout.addWidget(self.progress_bar)
        self.step_label = QLabel("")
        self.step_label.setObjectName("stepLabel")
        self.step_label.setFixedWidth(240)
        pf_layout.addWidget(self.step_label)
        self.progress_frame = progress_frame
        progress_frame.setVisible(False)
        content_layout.addWidget(progress_frame)

        # Tab
        self.tab_widget = QTabWidget()
        self.tab_widget.setVisible(False)
        self.transcript_tab = QTextEdit()
        self.transcript_tab.setObjectName("transcript")
        self.transcript_tab.setReadOnly(True)
        self.tab_widget.addTab(self.transcript_tab, "转写文本")
        self.scenes_tab = QTextEdit()
        self.scenes_tab.setReadOnly(True)
        self.tab_widget.addTab(self.scenes_tab, "场景切割")
        self.hooks_tab = QTextEdit()
        self.hooks_tab.setReadOnly(True)
        self.tab_widget.addTab(self.hooks_tab, "钩子分析")
        self.script_tab = QTextEdit()
        self.script_tab.setReadOnly(True)
        self.tab_widget.addTab(self.script_tab, "结构化剧本")
        self.characters_tab = QTextEdit()
        self.characters_tab.setReadOnly(True)
        self.tab_widget.addTab(self.characters_tab, "人物图谱")
        content_layout.addWidget(self.tab_widget, 1)

        # 底部
        bottom = QHBoxLayout()
        bottom.addStretch()
        self.export_md_btn = QPushButton("📄 导出 Markdown")
        self.export_md_btn.setObjectName("exportBtn")
        self.export_md_btn.setEnabled(False)
        bottom.addWidget(self.export_md_btn)
        content_layout.addLayout(bottom)

        main_layout.addWidget(content, 1)
        self._update_api_status()

    def _connect_signals(self):
        self.drop_zone.file_dropped.connect(self._on_file_dropped)
        self.browse_btn.clicked.connect(self._on_browse)
        self.analyze_btn.clicked.connect(self._on_analyze)
        self.settings_btn.clicked.connect(self._on_settings)
        self.export_md_btn.clicked.connect(self._on_export_md)
        self.input_switch.mode_changed.connect(self._on_mode_changed)
        self.url_zone.download_requested.connect(self._on_download_video)
        self.url_zone.preview_requested.connect(self._on_preview_url)
        self.url_zone.download_btn.clicked.connect(
            lambda: self.url_zone.download_requested.emit(self.url_zone.url_input.text().strip())
        )
        self.url_zone.preview_btn.clicked.connect(
            lambda: self.url_zone.preview_requested.emit(self.url_zone.url_input.text().strip())
        )

    def _on_mode_changed(self, mode):
        self.input_stack.setCurrentIndex(0 if mode == "local" else 1)
        # 更新分析按钮状态
        if mode == "local":
            self.analyze_btn.setEnabled(bool(self.video_path and self.video_source == "local"))
        else:
            self.analyze_btn.setEnabled(bool(self.video_path and self.video_source == "url"))

    def _update_api_status(self):
        if self.settings.get("openai_api_key"):
            self.api_status_label.setText("✅ AI 分析已就绪")
            self.api_status_label.setStyleSheet("color: #34C759; font-size: 11px;")
        else:
            self.api_status_label.setText("⚠️ 未配置 API Key（仅转写+场景检测）")
            self.api_status_label.setStyleSheet("color: #FF9500; font-size: 11px;")

    def _on_file_dropped(self, path):
        self._set_video_file(path)

    def _on_browse(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择视频文件", "", "视频文件 (*.mp4 *.mov *.mkv *.avi *.webm);;所有文件 (*)")
        if path:
            self._set_video_file(path)

    def _set_video_file(self, path):
        self.video_path = path
        self.video_source = "local"
        name = os.path.basename(path)
        size = os.path.getsize(path) / (1024 * 1024)
        self.file_name_label.setText(f"📹 {name}")
        self.file_detail_label.setText(f"大小: {size:.1f}MB · 路径: {path}")
        self.analyze_btn.setEnabled(True)

    def _on_preview_url(self, url):
        """预览链接信息（不下载）"""
        if not url or self.is_downloading:
            return

        self.url_zone.preview_btn.setEnabled(False)
        self.url_zone.preview_btn.setText("加载中...")

        def run():
            result = get_video_info_only(url)
            return result

        def on_done():
            self.url_zone.preview_btn.setEnabled(True)
            self.url_zone.preview_btn.setText("预览")
            # 在主线程更新 UI
            pass

        def worker():
            result = run()
            QApplication.invokeLater(lambda: self._handle_preview_result(result))

        threading.Thread(target=worker, daemon=True).start()

    def _handle_preview_result(self, result):
        self.url_zone.preview_btn.setEnabled(True)
        self.url_zone.preview_btn.setText("预览")
        if result.success:
            self.url_zone.show_preview(result.title, result.platform, result.duration, result.uploader)
        else:
            self.url_zone.preview_frame.setVisible(True)
            self.url_zone.preview_title.setText(f"❌ {result.error}")
            self.url_zone.preview_detail.setText("")

    def _on_download_video(self, url):
        """下载视频"""
        if not url or self.is_downloading or self.is_analyzing:
            return

        self.is_downloading = True
        self.url_zone.download_btn.setEnabled(False)
        self.url_zone.download_btn.setText("⏳ 下载中...")
        self.progress_frame.setVisible(True)
        self.progress_bar.setValue(5)
        self.step_label.setText("正在下载视频...")
        self.step_label.setStyleSheet("color: #007AFF; font-size: 12px;")

        cookie_file = self.settings.get("cookie_file", "")

        def run():
            return download_video(url, progress_cb=self._download_progress, cookie_file=cookie_file)

        def worker():
            result = run()
            QApplication.invokeLater(lambda: self._handle_download_result(result))

        threading.Thread(target=worker, daemon=True).start()

    def _download_progress(self, msg):
        """下载进度回调"""
        QApplication.invokeLater(lambda: self.step_label.setText(msg))
        # 根据消息更新进度条
        if "获取视频信息" in msg:
            QApplication.invokeLater(lambda: self.progress_bar.setValue(10))
        elif "下载" in msg and "%" in msg:
            try:
                pct = int(msg.split()[-1].replace("%", ""))
                download_pct = int(10 + pct * 0.5)  # 下载占 10-60%
                QApplication.invokeLater(lambda: self.progress_bar.setValue(download_pct))
            except (ValueError, IndexError):
                pass
        elif "合并" in msg:
            QApplication.invokeLater(lambda: self.progress_bar.setValue(60))

    def _handle_download_result(self, result):
        self.is_downloading = False
        self.url_zone.download_btn.setEnabled(True)
        self.url_zone.download_btn.setText("⬇ 下载")

        if result.success:
            self.video_path = result.video_path
            self.video_source = "url"
            size_mb = os.path.getsize(result.video_path) / (1024 * 1024)
            dur_str = f"{int(result.duration // 60)}:{int(result.duration % 60):02d}" if result.duration else "未知"
            self.url_file_name.setText(f"📹 {result.title}")
            self.url_file_detail.setText(
                f"平台: {result.platform} · 时长: {dur_str} · 大小: {size_mb:.1f}MB"
            )
            self.progress_bar.setValue(65)
            self.step_label.setText("✅ 视频下载完成，可以开始分析")
            self.step_label.setStyleSheet("color: #34C759; font-size: 12px;")
            # 自动切换到分析按钮可用
            self.analyze_btn.setEnabled(True)
        else:
            self.url_file_name.setText(f"❌ 下载失败")
            self.url_file_detail.setText(result.error)
            self.progress_bar.setValue(0)
            self.step_label.setText(f"❌ {result.error}")
            self.step_label.setStyleSheet("color: #FF3B30; font-size: 12px;")

    def _on_settings(self):
        dialog = SettingsDialog(self.settings, self)
        if dialog.exec() == SettingsDialog.Accepted:
            self.settings = dialog.get_settings()
            save_settings(self.settings)
            self._update_api_status()

    def _on_analyze(self):
        if self.is_analyzing or not self.video_path:
            return
        self.is_analyzing = True
        self.analyze_btn.setEnabled(False)
        self.analyze_btn.setText("⏳ 分析中...")
        self.progress_frame.setVisible(True)
        self.progress_bar.setValue(0)
        self.tab_widget.setVisible(True)

        # 如果是链接下载的视频，进度从65%开始
        start_pct = 65 if self.video_source == "url" else 0
        self.progress_bar.setValue(start_pct)

        steps = ["获取视频信息", "提取音频", "Whisper", "语音转写", "场景检测", "AI分析", "报告"]

        def progress_cb(msg):
            for i, step in enumerate(steps):
                if step in msg or any(s in msg for s in ["音频", "Whisper", "转写", "场景", "AI", "报告", "视频"]):
                    pct = start_pct + int((i + 1) / len(steps) * (100 - start_pct))
                    break
            else:
                pct = self.progress_bar.value()
            QApplication.invokeLater(lambda p=min(pct, 98): self.progress_bar.setValue(p))

        def run():
            pipeline = VideoToScriptPipeline(
                whisper_model=self.settings.get("whisper_model", "base"),
                scene_threshold=self.settings.get("scene_threshold", 35.0),
                min_scene_duration=self.settings.get("min_scene_duration", 2.0),
                openai_api_key=self.settings.get("openai_api_key", ""),
                openai_model=self.settings.get("openai_model", "gpt-4o-mini"),
                language=self.settings.get("language", "") or None,
            )
            self.result = pipeline.run(self.video_path, progress_cb=progress_cb)

        def on_done():
            self.is_analyzing = False
            self.analyze_btn.setEnabled(True)
            self.analyze_btn.setText("▶ 开始分析")
            self.progress_bar.setValue(100 if not self.result.error else 0)
            if self.result.error:
                self.step_label.setText(f"❌ {self.result.error}")
                self.step_label.setStyleSheet("color: #FF3B30; font-size: 12px;")
            else:
                self.step_label.setText("✅ 分析完成")
                self.step_label.setStyleSheet("color: #34C759; font-size: 12px;")
                self._display_results()
                self.export_md_btn.setEnabled(True)

        thread = threading.Thread(target=run, daemon=True)
        thread.start()

        def wait():
            thread.join()
            QApplication.invokeLater(on_done)

        threading.Thread(target=wait, daemon=True).start()

    def _display_results(self):
        if not self.result:
            return

        # 转写
        html = f"<h3>完整文本</h3><p>{self.result.transcript_text}</p><h3>带时间戳</h3>"
        for seg in self.result.transcript_segments:
            html += f'<p><span style="color:#007AFF;font-weight:600">[{seg["start"]}s - {seg["end"]}s]</span> {seg["text"]}</p>'
        self.transcript_tab.setHtml(html)

        # 场景
        shtml = f"<h3>共检测到 {len(self.result.scenes)} 个场景</h3>"
        for s in self.result.scenes:
            shtml += f'<p><b>场景{s.index}</b> · {s.start}s → {s.end}s <span style="color:#86868B">(时长{s.duration}s)</span></p>'
            if s.frame_path and os.path.exists(s.frame_path):
                img = QImage(s.frame_path)
                if not img.isNull():
                    buffer = BytesIO()
                    img.scaled(320, 180, Qt.KeepAspectRatio).save(buffer, "JPEG", quality=80)
                    b64 = base64.b64encode(buffer.getvalue()).decode()
                    shtml += f'<p><img src="data:image/jpeg;base64,{b64}" width="320" style="border-radius:6px;border:1px solid #E5E5EA"/></p>'
        self.scenes_tab.setHtml(shtml)

        # 钩子/剧本/人物
        self.hooks_tab.setMarkdown(self.result.hooks_analysis or "需要配置 OpenAI API Key")
        self.script_tab.setMarkdown(self.result.script_structure or "需要配置 OpenAI API Key")
        self.characters_tab.setMarkdown(self.result.character_map or "需要配置 OpenAI API Key")

    def _on_export_md(self):
        if not self.result or not self.result.full_report:
            return
        path, _ = QFileDialog.getSaveFileName(self, "导出报告", os.path.expanduser("~/Desktop/短剧拆解报告.md"), "Markdown (*.md)")
        if path:
            with open(path, "w", encoding="utf-8") as f:
                f.write(self.result.full_report)
            self.step_label.setText(f"✅ 已导出到 {os.path.basename(path)}")
            self.step_label.setStyleSheet("color: #34C759; font-size: 12px;")
