import os
from typing import Optional
from PySide6.QtGui import QPixmap

from res_crypto import read_resource_bytes


class ResourceManager:
    def __init__(self):
        self.loaded_resources = {}

    def load_pixmap(self, path: str) -> Optional[QPixmap]:
        """加载图片（键=物理路径，命中缓存直接返回）。

        资源读取统一走 res_crypto.read_resource_bytes（开源版=直接读文件，
        加密版=映射+解密），本函数不关心资源是否加密。
        """
        if path in self.loaded_resources:
            return self.loaded_resources[path]
        try:
            data = read_resource_bytes(path)
            pixmap = QPixmap()
            if pixmap.loadFromData(data):
                self.loaded_resources[path] = pixmap
                return pixmap
            print(f"加载图片失败，文件可能已损坏: {path}")
        except FileNotFoundError:
            print(f"图片文件不存在: {path}")
        except Exception as e:
            print(f"加载图片失败 {path}: {e}")
        return None
