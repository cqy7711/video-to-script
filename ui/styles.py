"""浅色简洁风样式表"""

APP_STYLESHEET = """
QMainWindow {
    background-color: #FAFBFC;
}

QWidget {
    font-family: "SF Pro Text", "Helvetica Neue", "PingFang SC", sans-serif;
    font-size: 13px;
    color: #1D1D1F;
}

QFrame#topBar {
    background-color: #FFFFFF;
    border-bottom: 1px solid #E5E5EA;
    padding: 12px 20px;
}

QLabel#appTitle {
    font-size: 18px;
    font-weight: 600;
    color: #1D1D1F;
}

QLabel#appSubtitle {
    font-size: 12px;
    color: #86868B;
}

QFrame#dropZone {
    background-color: #FFFFFF;
    border: 2px dashed #D1D1D6;
    border-radius: 12px;
    min-height: 180px;
}

QFrame#dropZone[dragOver="true"] {
    border-color: #007AFF;
    background-color: #F0F5FF;
}

QLabel#dropIcon {
    font-size: 48px;
    color: #C7C7CC;
}

QLabel#dropText {
    font-size: 15px;
    color: #86868B;
}

QLabel#dropHint {
    font-size: 11px;
    color: #AEAEB2;
}

QFrame#fileInfo {
    background-color: #FFFFFF;
    border: 1px solid #E5E5EA;
    border-radius: 8px;
    padding: 10px 16px;
}

QPushButton#analyzeBtn {
    background-color: #007AFF;
    color: #FFFFFF;
    border: none;
    border-radius: 8px;
    padding: 10px 32px;
    font-size: 14px;
    font-weight: 500;
    min-height: 36px;
}

QPushButton#analyzeBtn:hover {
    background-color: #0066D6;
}

QPushButton#analyzeBtn:pressed {
    background-color: #0055B3;
}

QPushButton#analyzeBtn:disabled {
    background-color: #B0D4FF;
    color: #E5E5EA;
}

QPushButton#settingsBtn {
    background-color: transparent;
    border: 1px solid #E5E5EA;
    border-radius: 8px;
    padding: 8px 16px;
    color: #636366;
}

QPushButton#settingsBtn:hover {
    background-color: #F5F5F7;
}

QPushButton#exportBtn {
    background-color: #34C759;
    color: #FFFFFF;
    border: none;
    border-radius: 8px;
    padding: 8px 20px;
    font-weight: 500;
}

QPushButton#exportBtn:hover {
    background-color: #2DB84E;
}

QPushButton#exportBtn:disabled {
    background-color: #B8E6C8;
    color: #FFFFFF;
}

QProgressBar {
    border: none;
    border-radius: 4px;
    background-color: #E5E5EA;
    height: 8px;
    text-align: center;
}

QProgressBar::chunk {
    background-color: #007AFF;
    border-radius: 4px;
}

QLabel#stepLabel {
    font-size: 12px;
    color: #86868B;
}

QLabel#progressPercent {
    font-size: 12px;
    font-weight: 600;
    color: #007AFF;
}

QTabWidget::pane {
    border: 1px solid #E5E5EA;
    border-radius: 8px;
    background-color: #FFFFFF;
    padding: 4px;
}

QTabBar::tab {
    padding: 8px 20px;
    border: none;
    border-radius: 6px;
    color: #86868B;
    font-weight: 500;
    margin-right: 2px;
}

QTabBar::tab:selected {
    background-color: #007AFF;
    color: #FFFFFF;
}

QTabBar::tab:hover:!selected {
    background-color: #F5F5F7;
}

QTextEdit {
    border: none;
    background-color: transparent;
    padding: 16px;
    font-size: 13px;
    line-height: 1.6;
    color: #1D1D1F;
}

QTextEdit#transcript {
    font-family: "SF Mono", "Menlo", monospace;
    font-size: 12px;
}

QDialog {
    background-color: #FFFFFF;
}

QLineEdit {
    border: 1px solid #E5E5EA;
    border-radius: 6px;
    padding: 8px 12px;
    background-color: #FAFBFC;
}

QLineEdit:focus {
    border-color: #007AFF;
}

QComboBox {
    border: 1px solid #E5E5EA;
    border-radius: 6px;
    padding: 8px 12px;
    background-color: #FAFBFC;
}

QComboBox:focus {
    border-color: #007AFF;
}

QGroupBox {
    font-weight: 600;
    border: 1px solid #E5E5EA;
    border-radius: 8px;
    margin-top: 12px;
    padding-top: 20px;
}

QGroupBox::title {
    subcontrol-origin: margin;
    left: 16px;
    padding: 0 8px;
}
"""
