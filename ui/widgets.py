from PySide6.QtWidgets import QTextEdit, QFrame
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont, QTextCursor


class TextDisplayWidget(QTextEdit):
    """自定义文本显示控件，支持逐字显示效果"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setFrameStyle(QFrame.NoFrame)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setTextInteractionFlags(Qt.NoTextInteraction)
        font = QFont("Microsoft YaHei", 14)
        self.setFont(font)
        self.setStyleSheet("""
            QTextEdit {
                background: transparent;
                color: white;
                border: none;
                padding: 10px;
            }
        """)
        self.full_text = ""
        self.displayed_text = ""
        self.char_index = 0
        self.timer = QTimer()
        self.timer.timeout.connect(self.display_next_char)
        self.char_delay = 30
        self.on_display_complete = None

    def set_text(self, text: str, on_complete=None):
        self.full_text = text
        self.displayed_text = ""
        self.char_index = 0
        self.on_display_complete = on_complete
        self.clear()
        if text:
            self.timer.start(self.char_delay)
        else:
            self.timer.stop()
            if self.on_display_complete:
                self.on_display_complete()

    def display_next_char(self):
        if self.char_index < len(self.full_text):
            self.displayed_text += self.full_text[self.char_index]
            self.char_index += 1
            self.setPlainText(self.displayed_text)
            cursor = self.textCursor()
            cursor.movePosition(QTextCursor.End)
            self.setTextCursor(cursor)
        else:
            self.timer.stop()
            if self.on_display_complete:
                self.on_display_complete()

    def complete_display(self):
        self.timer.stop()
        self.displayed_text = self.full_text
        self.char_index = len(self.full_text)
        self.setPlainText(self.full_text)
        if self.on_display_complete:
            self.on_display_complete()

    def is_display_complete(self) -> bool:
        return self.char_index >= len(self.full_text)