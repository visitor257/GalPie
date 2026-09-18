"""资源读取 / 解密接口包 —— 引擎的唯一 hook。

引擎只从本包导入，不直接导入内部实现文件，
这样创作者替换 ``decrypt.py``（或编译成 ``decrypt.pyd``）时引擎侧零改动。

    引擎调用:  from res_crypto import read_resource_bytes
    创作者改:  res_crypto/decrypt.py
"""
from .decrypt import read_resource_bytes

__all__ = ["read_resource_bytes"]
