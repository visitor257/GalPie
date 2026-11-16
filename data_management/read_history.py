"""已读文本记录（READED）。

用途：快进/跳过遇到未读内容自动停止，不跳过未读部分。
与存档完全独立：saves/{标题}_{识别码}_READED.gpreaded（JSON），全局加载，
不随存档删除——删档重开、二周目快进仍生效。

内存结构：set of "包|line:page:scene_idx" 字符串（O(1) 判定/标记）
磁盘结构：{"包|line:page": [scene_idx, ...], ...}（按页聚合，便于查看/合并）
包标识：主作用保留 id ":main:"，附加内容用 settings.extra_content 的键名
        （与存档 data[13] 同一套口径）。旧版主作用的是裸 key（无 "|"），
        加载时自动补上 ":main:|" 前缀，不会丢已读进度。
"""
import json
import os


def _story_file_prefix(controller):
    """文件名前缀：与 save_load_system 同一套净化规则（空格->-，下划线->+）。"""
    settings = (getattr(controller, "_main_data", None) or controller.story_data or {}).get("settings", {"window_title": "GalPie", "identify_code": ""})
    story_name = settings.get("window_title", "GalPie").replace(" ", "-").replace("_", "+")
    story_id = settings.get("identify_code", "").replace(" ", "-").replace("_", "+")
    return f"{story_name}_{story_id}"


def read_history_path(controller):
    """已读记录文件路径：saves/{标题}_{识别码}_READED.gpreaded"""
    return os.path.join("saves", f"{_story_file_prefix(controller)}_READED.gpreaded")


def load_read_history(controller):
    """加载已读记录到内存 set。文件缺失/损坏/格式不符 -> 返回空 set（不抛异常）。

    迁移：旧版主作 key 没有包前缀（如 "main:1:0"、页键 "main:1"），
    统一补成 ":main:|..."，与新版一致 —— 不迁移就会让老玩家的已读进度全部失效
    （快进会重新停在所有地方）。
    """
    result = set()
    path = read_history_path(controller)
    try:
        if not os.path.exists(path):
            return result
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return result
        for page_key, idxs in data.items():
            if not isinstance(page_key, str) or not isinstance(idxs, list):
                continue
            key = page_key if "|" in page_key else f":main:|{page_key}"
            for idx in idxs:
                result.add(f"{key}:{idx}")
    except Exception as e:
        print(f"读取已读记录失败: {e}")
    return result


def save_read_history(controller, read_set):
    """把内存 set 写盘，组织成 {"包|line:page": [idx, ...]}（每页 idx 按数值排序）。
    内存里的 key 已是 "包|line:page:idx"，rsplit(":", 1) 后页键里天然带着包前缀。
    """
    by_page = {}
    for key in read_set:
        parts = key.rsplit(":", 1)
        if len(parts) != 2:
            continue
        by_page.setdefault(parts[0], []).append(parts[1])
    for k in by_page:
        by_page[k] = sorted(by_page[k], key=lambda x: int(x) if str(x).isdigit() else 0)
    try:
        if not os.path.exists("saves"):
            os.mkdir("saves")
        path = read_history_path(controller)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(by_page, f, ensure_ascii=False, indent=1)
    except Exception as e:
        print(f"保存已读记录失败: {e}")
