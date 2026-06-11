"""主窗口 — 浅色简洁风"""

import os
import threading
import base64
from io import BytesIO
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QFrame,
    QLabel, QPushButton, QTabWidget, QTextEdit, QProgressBar,
    QFileDialog, QApplication
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QDragEnterEvent, QDropEvent, QImage

from core.pipeline import VideoToScriptPipeline, AnalysisResult
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


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Video to Script")
        self.setMinimumSize(860, 640)
        self.resize(960, 700)
        self.settings = load_settings()
        self.result = None
        self.is_analyzing = False
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

        # 拖拽 + 按钮
        input_layout = QHBoxLayout()
        input_layout.setSpacing(16)
        self.drop_zone = DropZone()
        self.drop_zone.setMinimumHeight(160)
        input_layout.addWidget(self.drop_zone, 3)

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
        input_layout.addLayout(right, 2)
        content_layout.addLayout(input_layout)

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
        self.step_label.setFixedWidth(200)
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
        name = os.path.basename(path)
        size = os.path.getsize(path) / (1024 * 1024)
        self.file_name_label.setText(f"📹 {name}")
        self.file_detail_label.setText(f"大小: {size:.1f}MB · 路径: {path}")
        self.analyze_btn.setEnabled(True)

    def _on_settings(self):
        dialog = SettingsDialog(self.settings, self)
        if dialog.exec() == SettingsDialog.Accepted:
            self.settings = dialog.get_settings()
            save_settings(self.settings)
            self._update_api_status()

    def _on_analyze(self):
        if self.is_analyzing or not hasattr(self, 'video_path'):
            return
        self.is_analyzing = True
        self.analyze_btn.setEnabled(False)
        self.analyze_btn.setText("⏳ 分析中...")
        self.progress_frame.setVisible(True)
        self.progress_bar.setValue(0)
        self.tab_widget.setVisible(True)

        steps = ["获取视频信息", "提取音频", "Whisper", "语音转写", "场景检测", "AI分析", "报告"]

        def progress_cb(msg):
            for i, step in enumerate(steps):
                if step in msg or any(s in msg for s in ["音频", "Whisper", "转写", "场景", "AI", "报告", "视频"]):
                    pct = int((i + 1) / len(steps) * 100)
                    break
            else:
                pct = self.progress_bar.value()
            self.progress_bar.setValue(min(pct, 95))

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
