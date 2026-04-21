import os
from typing import Optional
from PySide6.QtGui import QPixmap


class ResourceManager:
    def __init__(self):
        self.loaded_resources = {}

    def load_pixmap(self, path: str) -> Optional[QPixmap]:
        if path in self.loaded_resources:
            return self.loaded_resources[path]
        try:
            if not os.path.exists(path):
                print(f"图片文件不存在: {path}")
                return None
            pixmap = QPixmap(path)
            if not pixmap.isNull():
                self.loaded_resources[path] = pixmap
                return pixmap
            else:
                print(f"加载图片失败，文件可能已损坏: {path}")
        except Exception as e:
            print(f"加载图片失败 {path}: {e}")
        return None