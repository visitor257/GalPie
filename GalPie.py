import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt

from ui.main_window import GalGameWindow


def main():
    # 启用GPU加速
    QApplication.setAttribute(Qt.AA_UseOpenGLES)

    app = QApplication(sys.argv)

    # 创建故事目录（如果不存在）
    story_dir = Path("story")
    story_dir.mkdir(exist_ok=True)

    window = GalGameWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()