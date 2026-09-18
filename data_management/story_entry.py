"""剧情入口文件（EXORDIUM）的定位与解析。

约定
----
引擎根目录（与 GalPie.py 同级）有一个**无扩展名、全大写**的明文文件 ``EXORDIUM``，
内容为**一行**纯文本，写明剧情 JSON 的**逻辑路径**（相对于引擎根目录），例如::

    story/sample_create.json

- 空行、以及以 ``#`` 开头的注释行会被忽略；有效行必须**只有一行**。
- 本模块只负责「定位 + 语法/安全校验」，不碰解密，也**不检查目标文件是否真实存在**：
  加密版会对路径做映射/改名，逻辑路径在磁盘上本来就可能不存在，
  该检查由资源读取层（``res_crypto.read_resource_bytes``）与调用方负责。

引擎用法::

    from data_management.story_entry import load_story_path

    path = load_story_path()      # 无可用入口时返回 None，调用方自行兜底
    if path is not None:
        ...
"""

from pathlib import Path
from typing import Optional, Union

from res_crypto import read_resource_bytes

__all__ = ["ENTRY_NAME", "MAX_VALUE_LENGTH", "load_story_path"]

#: 入口文件名（引擎根目录下，无扩展名、全大写）
ENTRY_NAME = "EXORDIUM"

#: 内容长度上限（防御异常文件）
MAX_VALUE_LENGTH = 4096


def _effective_lines(text: str) -> list:
    """取出有效行：跳空行与 ``#`` 注释行，其余 strip 后返回。"""
    lines = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        lines.append(line)
    return lines


def _validate(value: str) -> Optional[str]:
    """校验入口内容，返回错误说明；合法则返回 None。"""
    if not value:
        return "内容为空"
    if len(value) > MAX_VALUE_LENGTH:
        return f"内容过长（超过 {MAX_VALUE_LENGTH} 字符）"
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in value):
        return "含控制字符"
    if ":" in value:
        return "不允许出现 ':'（避免盘符 / URL）"
    if value.startswith(("/", "\\")):
        return "不允许绝对路径"
    parts = [p for p in value.replace("\\", "/").split("/") if p not in ("", ".")]
    if not parts:
        return "内容为空"
    if ".." in parts:
        return "不允许 '..' 越界"
    return None


def load_story_path(base: Optional[Union[Path, str]] = None) -> Optional[Path]:
    """读取引擎根目录的 ``EXORDIUM``，返回剧情 JSON 的逻辑路径。

    返回 ``None`` 表示没有可用入口（文件缺失 / 读取失败 / 内容非法），
    调用方应回落到自己的兜底逻辑。**本函数不抛异常。**

    :param base: 引擎根目录，缺省为当前工作目录（与引擎里其它相对路径同基准）。
    """
    base_dir = Path(base) if base is not None else Path(".")
    entry = base_dir / ENTRY_NAME

    if not entry.is_file():
        return None

    try:
        text = read_resource_bytes(entry).decode("utf-8-sig")
    except Exception as e:  # 读取失败 / 解密失败 → 回落，不当成致命错误
        print(f"[story_entry] 读取入口文件 {ENTRY_NAME} 失败：{e}")
        return None

    lines = _effective_lines(text)
    if not lines:
        print(f"[story_entry] 入口文件 {ENTRY_NAME} 内容为空，忽略该入口")
        return None
    if len(lines) > 1:
        print(f"[story_entry] 入口文件 {ENTRY_NAME} 含多行内容（应为一行路径），忽略该入口")
        return None

    value = lines[0]
    error = _validate(value)
    if error:
        print(f"[story_entry] 入口文件 {ENTRY_NAME} 内容非法（{error}），忽略该入口")
        return None

    return Path(value)
