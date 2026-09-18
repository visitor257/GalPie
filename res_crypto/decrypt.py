"""资源读取 / 解密实现 —— 创作者唯一需要替换的文件。

契约
----
输入：业务层解析出的逻辑路径（如 ``story/res/bg/park.png``）
输出：**明文 bytes**

引擎里所有资源都必须经过这里读：
    - 剧情 JSON -> json.loads(read_resource_bytes(p).decode("utf-8"))
    - 图片      -> QPixmap.loadFromData(read_resource_bytes(p))
    - 音频      -> QBuffer + read_resource_bytes(p)

开源版实现
----------
资源即明文，直接读文件（clone 下来就能跑，不需要任何开关）。

加密版替换要点
--------------
把本文件整体替换掉即可（**只换函数体，不要在引擎里加 ``if 已加密:`` 分支**）：

1. 密钥不要硬编码成字符串——运行时拼装 / 派生，否则 strings 一扫就没了
2. 实现要编译掉（Cython / Nuitka）：发布时用 ``decrypt.pyd``（或 ``.so``）
   替换 ``decrypt.py``，不要留 .py 源码
3. 绝对不要"启动时一次性全解包到临时目录"——玩家会直接去 temp 里捞；
   保持按需解密到内存
4. 签名和返回类型保持不变：路径进、**明文 bytes** 出

路径也可以在这一层改写（哈希名 / 换扩展名 / 换目录），
这样开源版是"原样打开"，加密版是"映射 + 解密"，两边接口不变。

错误语义
--------
本函数**会抛异常**（``FileNotFoundError`` / ``OSError`` / 解密失败），
由调用方兜底：图片侧保持现有的 ``print + return None``，
音频侧捕获后静音跳过。不要在这里返回 ``None``。
"""
from pathlib import Path
from typing import Union

__all__ = ["read_resource_bytes"]


def read_resource_bytes(path: Union[str, Path]) -> bytes:
    """逻辑路径 -> 明文 bytes。开源版：原样读文件。"""
    return Path(path).read_bytes()
