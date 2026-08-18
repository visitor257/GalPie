import os
import pickle
from PySide6.QtCore import QDateTime, QByteArray, QBuffer, Qt, QRectF
from PySide6.QtGui import QPixmap, QPainter, QFont, QColor, QPainterPath


def _render_scene_thumbnail(controller):
    """按当前页初始快照（controller.page_state）离屏渲染画面，返回 PNG 字节（供存档 data[2] 使用）。
    不依赖窗口截图，与运行时渲染逻辑一致：
      - 默认逻辑分辨率画布（logical_size）
      - 背景 KeepAspectRatioByExpanding 缩放铺满 + 居中偏移
      - 角色 form+face 透明合成，按快照 zoom 缩放、按快照位置绘制
    仅包含背景和角色（不含对话框/文字/底部菜单）。
    任何资源缺失时降级跳过对应元素，不抛异常。
    """
    w, h = controller.logical_size
    canvas = QPixmap(w, h)
    canvas.fill(Qt.transparent)
    painter = QPainter(canvas)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setRenderHint(QPainter.SmoothPixmapTransform)
    painter.setRenderHint(QPainter.TextAntialiasing)

    try:
        story_data = controller.story_data or {}
        spa = story_data.get("story_and_position", {})
        # 快照：翻页时记录的当前页初始画面（bg id / 角色最终配置 / chatbox 可见性）
        snap = getattr(controller, "page_state", {}) or {}
        bg_name = snap.get("bg")
        characters = snap.get("characters", {}) or {}

        # ---- 背景（字符串=背景 id；字典 {"color": [...]} = 纯色） ----
        if bg_name:
            if isinstance(bg_name, dict) and "color" in bg_name:
                color = bg_name.get("color")
                if isinstance(color, (list, tuple)) and len(color) >= 3:
                    painter.fillRect(0, 0, w, h, QColor(int(color[0]), int(color[1]), int(color[2])))
            else:
                bg_path = spa.get("backgrounds", {}).get(bg_name)
                if bg_path:
                    bg_pixmap = QPixmap(str(controller.base_path / bg_path))
                    if not bg_pixmap.isNull():
                        # 同 GraphicsView.fit_background：KeepAspectRatioByExpanding 铺满
                        scaled = bg_pixmap.scaled(
                            w, h, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
                        bg_pos = [(w - bg_pixmap.width()) // 2, 0]
                        painter.drawPixmap(bg_pos[0], bg_pos[1], scaled)

        # ---- 角色（快照中已是动画最终 zoom/位置） ----
        char_defs = spa.get("character_and_motion", {})
        bg_offset_x = 0
        if isinstance(bg_name, str) and spa.get("backgrounds", {}).get(bg_name):
            bg_pixmap2 = QPixmap(str(controller.base_path / spa["backgrounds"][bg_name]))
            if not bg_pixmap2.isNull():
                bg_offset_x = (w - bg_pixmap2.width()) // 2
        for char_id, char_info in characters.items():
            char_data = char_defs.get(char_id, {})
            form_name = char_info.get("form")
            face_name = char_info.get("face")
            pos = list(char_info.get("pos", [0, 0]))
            zoom = float(char_info.get("zoom", 1.0))

            form_pixmap = None
            if form_name and form_name in char_data.get("form", {}):
                form_pixmap = QPixmap(str(controller.base_path / char_data["form"][form_name]))
            face_pixmap = None
            if face_name and face_name in char_data.get("face", {}):
                face_pixmap = QPixmap(str(controller.base_path / char_data["face"][face_name]))

            combined = None
            if form_pixmap and not form_pixmap.isNull() and face_pixmap and not face_pixmap.isNull():
                combined = QPixmap(form_pixmap.size())
                combined.fill(Qt.transparent)
                cp = QPainter(combined)
                cp.setRenderHint(QPainter.Antialiasing)
                cp.setRenderHint(QPainter.SmoothPixmapTransform)
                cp.drawPixmap(0, 0, form_pixmap)
                cp.drawPixmap(0, 0, face_pixmap)
                cp.end()
            elif form_pixmap and not form_pixmap.isNull():
                combined = form_pixmap
            elif face_pixmap and not face_pixmap.isNull():
                combined = face_pixmap

            if combined is not None:
                scaled_char = combined.scaled(
                    max(1, int(combined.width() * zoom)),
                    max(1, int(combined.height() * zoom)),
                    Qt.KeepAspectRatio, Qt.SmoothTransformation)
                painter.drawPixmap(int(pos[0] + bg_offset_x), int(pos[1]), scaled_char)

    finally:
        painter.end()

    byte_array = QByteArray()
    buffer = QBuffer(byte_array)
    buffer.open(QBuffer.WriteOnly)
    canvas.save(buffer, "PNG")
    return byte_array.data()


def save_settings_file(controller):
    """保存设置内容到 saves/<window_title>_<identify_code>_SETTINGS.gpsetting。
    结构类似存档：
      data[0] = window_title（净化后）
      data[1] = identify_code（净化后）
      data[2] = 分辨率（"WxH" 字符串；全屏时为 FULLSCREEN_KEY "fullscreen"）
      data[3] = 语言（语言 id，如 zh/en/ja）
    设置一旦变更（分辨率/语言）即调用本函数写盘。
    """
    settings = controller.story_data.get("settings", {"window_title": "GalPie", "identify_code": ""})
    story_name = settings.get("window_title", "GalPie").replace(" ", "-").replace("_", "+")
    story_id = settings.get("identify_code", "").replace(" ", "-").replace("_", "+")
    # 当前分辨率：全屏用 FULLSCREEN_KEY 标记，否则 WxH 字符串
    win = controller.main_window
    if win.isFullScreen():
        res = "fullscreen"
    else:
        res = "{}x{}".format(controller.window_size[0], controller.window_size[1])
    lang = controller.language
    data = [story_name, story_id, res, lang]
    if not os.path.exists("saves"):
        os.mkdir("saves")
    with open(f"./saves/{story_name}_{story_id}_SETTINGS.gpsetting", "wb") as f:
        pickle.dump(data, f)


def load_settings_file(controller):
    """运行时读取设置文件 saves/<window_title>_<identify_code>_SETTINGS.gpsetting。
    若无此文件，返回 None（按默认值启动）；若有则返回 data 列表。
    data[2] 分辨率、data[3] 语言；其中无效值由调用方按默认值回落。
    """
    settings = controller.story_data.get("settings", {"window_title": "GalPie", "identify_code": ""})
    story_name = settings.get("window_title", "GalPie").replace(" ", "-").replace("_", "+")
    story_id = settings.get("identify_code", "").replace(" ", "-").replace("_", "+")
    path = f"./saves/{story_name}_{story_id}_SETTINGS.gpsetting"
    if not os.path.exists(path):
        return None
    try:
        with open(path, "rb") as f:
            data = pickle.load(f)
        # 校验结构：标题/识别码匹配才生效
        if not isinstance(data, list) or len(data) < 4:
            return None
        if data[0] != story_name or data[1] != story_id:
            return None
        return data
    except Exception:
        return None


def save_game(controller, slot_index=0):
    settings = controller.story_data.get("settings", {"window_title": "GalPie", "identify_code": ""})
    data = [
        settings.get("window_title", "GalPie").replace(" ", "-").replace("_", "+"),
        settings.get("identify_code", "").replace(" ", "-").replace("_", "+"),
        None,
        (controller.story_data.get("story_and_position", {}).get("storyline_settings", {}) or {}).get("storyline_id_score", None),
        controller.current_storyline_id,
        str(controller.current_page - 1),
        None,
        None,
        QDateTime.currentDateTime().toString("yyyy-MM-dd"),
        QDateTime.currentDateTime().toString("HH-mm-ss")
    ]
    # data[2]：离屏搭建当前页初始画面（按 page_state 快照渲染），替代窗口截图
    data[2] = _render_scene_thumbnail(controller)
    # data[6]/[7]：与缩略图一致，取"当前实际画面"所在页的台词。
    # 等待点击进入下一页时（is_waiting_for_next_page=True），current_page 已是下一页、
    # 画面仍停在上一页播完状态——回退一页，保证台词与画面（缩略图）对应。
    render_page = controller.current_page
    if getattr(controller, "is_waiting_for_next_page", False):
        render_page = max(1, render_page - 1)
    page_content = controller.story_data.get("story_and_position", {}).get("story", {}).get(
        controller.current_storyline_id, {}).get(str(render_page), [{}])[0].get("content", None)
    if page_content:
        if "speaking" in page_content:
            data[6] = page_content.get("speaking", None)
        else:
            data[6] = page_content.get("speaking_name", None)
        data[7] = page_content.get("words", None)
    # 格子存档：文件名 {标题}_{识别码}_SLOT{index}.gpsave，data 末尾记录 index
    data.append(slot_index)
    # data[11]：当前页初始画面快照（翻页时记录的 page_state），读档按此构建画面
    data.append({
        "bg": controller.page_state.get("bg"),
        "characters": {k: dict(v) for k, v in controller.page_state.get("characters", {}).items()},
        "chatbox_visible": bool(controller.page_state.get("chatbox_visible", True)),
    })
    # data[12]：计分（分支分数，内存态随剧情增减），读档恢复。
    # 无计分机制的剧情（controller 无 scores 属性）存空 dict，不影响旧档兼容。
    data.append(dict(getattr(controller, "scores", None) or {}))
    if not os.path.exists("saves"):
        os.mkdir("saves")
    with open(f"./saves/{data[0]}_{data[1]}_SLOT{slot_index}.gpsave", "wb") as f:
        pickle.dump(data, f)


def quick_save_game(controller):
    """快速存档：与 save_game 相同内容，但存到固定文件名
    saves/<window_title>_<identify_code>_QSAVE.gpsave（覆盖式快速槽）。
    get_this_story_saves_new_to_old 会识别 QSAVE 文件名并排在最前，
    保证 F3/load_save 读档总是读到最近一次快速存档。
    """
    settings = controller.story_data.get("settings", {"window_title": "GalPie", "identify_code": ""})
    data = [
        settings.get("window_title", "GalPie").replace(" ", "-").replace("_", "+"),
        settings.get("identify_code", "").replace(" ", "-").replace("_", "+"),
        None,
        (controller.story_data.get("story_and_position", {}).get("storyline_settings", {}) or {}).get("storyline_id_score", None),
        controller.current_storyline_id,
        str(controller.current_page - 1),
        None,
        None,
        QDateTime.currentDateTime().toString("yyyy-MM-dd"),
        QDateTime.currentDateTime().toString("HH-mm-ss")
    ]
    # data[2]：离屏搭建当前页初始画面（按 page_state 快照渲染），替代窗口截图
    data[2] = _render_scene_thumbnail(controller)
    # data[6]/[7]：与缩略图一致，取"当前实际画面"所在页的台词。
    # 等待点击进入下一页时（is_waiting_for_next_page=True），current_page 已是下一页、
    # 画面仍停在上一页播完状态——回退一页，保证台词与画面（缩略图）对应。
    render_page = controller.current_page
    if getattr(controller, "is_waiting_for_next_page", False):
        render_page = max(1, render_page - 1)
    page_content = controller.story_data.get("story_and_position", {}).get("story", {}).get(
        controller.current_storyline_id, {}).get(str(render_page), [{}])[0].get("content", None)
    if page_content:
        if "speaking" in page_content:
            data[6] = page_content.get("speaking", None)
        else:
            data[6] = page_content.get("speaking_name", None)
        data[7] = page_content.get("words", None)
    # 快速存档：index = -1（不在保存面板显示）
    data.append(-1)
    # data[11]：当前页初始画面快照
    data.append({
        "bg": controller.page_state.get("bg"),
        "characters": {k: dict(v) for k, v in controller.page_state.get("characters", {}).items()},
        "chatbox_visible": bool(controller.page_state.get("chatbox_visible", True)),
    })
    # data[12]：计分（与 save_game 一致，见 save_game 注释）
    data.append(dict(getattr(controller, "scores", None) or {}))
    if not os.path.exists("saves"):
        os.mkdir("saves")
    with open(f"./saves/{data[0]}_{data[1]}_QSAVE.gpsave", "wb") as f:
        pickle.dump(data, f)


def load_save(controller, load_file_name=None):
    """读档。load_file_name 为 None 时读最新档（QSAVE 优先）；
    指定文件名时支持：绝对路径、相对 saves/ 的裸文件名。
    成功返回 True，无可用存档/读档失败返回 False。"""
    fpath = None
    if load_file_name:
        # 有参数：解析指定文件路径
        cand = os.path.normpath(load_file_name)
        if os.path.isabs(cand):
            fpath = cand if os.path.exists(cand) else None
        else:
            p1 = os.path.join("saves", cand)
            if os.path.exists(p1):
                fpath = p1
            elif os.path.exists(cand):
                fpath = cand
        if fpath is None:
            print(f"读档失败：找不到文件 {load_file_name}")
            return False
    else:
        # 无参数：读最新档
        save_files = get_this_story_saves_new_to_old(controller)
        if not save_files:
            print("读档失败：没有可用的存档")
            return False
        fpath = os.path.join("saves", save_files[0])
    try:
        with open(fpath, "rb") as f:
            data = pickle.load(f)
    except Exception as e:
        print(f"读档失败：{e}")
        return False
    if not isinstance(data, list) or len(data) < 6:
        print("读档失败：存档数据损坏")
        return False
    if data[3]:
        controller.story_data["story_and_position"].setdefault("storyline_settings", {})["storyline_id_score"] = data[3]
    controller.current_storyline_id = data[4]
    # data[5] 存档时存的是 current_page - 1（第 1 页存 0），读档 +1 还原
    controller.current_page = int(data[5]) + 1
    # 兜底：旧档异常值（如 0 或负数）修正为 1
    if controller.current_page < 1:
        controller.current_page = 1
    controller.current_scene_index = 0
    # 读档时清空日志：只保留读档后新播的对话
    controller.backlog_entries = []
    controller.backlog_start_page = controller.current_page
    # 计分恢复：新档 data[12] 为分数 dict；旧档（无此字段）不恢复，保持内存默认
    if len(data) > 12 and isinstance(data[12], dict):
        controller.scores = dict(data[12])
    # 读档：按存档快照（data[11]）恢复画面状态，再播当前页第 0 场景（只播一遍）
    snapshot = data[11] if len(data) > 11 and isinstance(data[11], dict) else None
    if snapshot is None:
        # 旧档（无快照）：退化为空画面（读档后由当前页场景自行铺画面）
        snapshot = {"bg": None, "characters": {}, "chatbox_visible": True}
    # 保存快照供主菜单读档路径（_show_loaded_scene）在重建 dialog area 后重新应用
    controller.last_loaded_snapshot = {
        "bg": snapshot.get("bg"),
        "characters": {k: dict(v) for k, v in (snapshot.get("characters") or {}).items()},
        "chatbox_visible": bool(snapshot.get("chatbox_visible", True)),
    }
    if controller.is_in_menu:
        # 主菜单读档：此时不播放（is_in_menu 会阻止），画面恢复交给 _show_loaded_scene
        return True
    controller.restore_snapshot(snapshot)
    controller.play_current_page()
    return True


def get_this_story_saves_new_to_old(controller, save_dir="./saves", content_check=False):
    """返回本故事全部存档文件名，按时间新->旧排序。
    兼容两种命名：
      - 格子存档：{标题}_{识别码}_SLOT{index}.gpsave
      - 快速存档：{标题}_{识别码}_QSAVE.gpsave（恒排最前）
    排序依据：读每个文件 data[-2]/data[-1]（日期/时间），QSAVE 用极大值。
    """
    settings = controller.story_data.get("settings", {"window_title": "GalPie", "identify_code": ""})
    story_name = settings.get("window_title", "GalPie").replace(" ", "-").replace("_", "+")
    story_id = settings.get("identify_code", "").replace(" ", "-").replace("_", "+")
    result = []
    processing = {}
    # saves 目录不存在时直接返回空列表（首次运行/未存档时常见）
    if not os.path.isdir(save_dir):
        return result
    for i in os.listdir(save_dir):
        if os.path.splitext(i)[-1] != ".gpsave":
            continue
        parts = i.split("_")
        if len(parts) < 2 or parts[0] != story_name or parts[1] != story_id:
            continue
        try:
            with open(os.path.join(save_dir, i), "rb") as f:
                data = pickle.load(f)
        except Exception:
            continue
        if not isinstance(data, list) or len(data) < 2:
            continue
        if data[0] != story_name or data[1] != story_id:
            continue
        # QSAVE（快速存档）：恒排最前
        if parts[-1].startswith("QSAVE"):
            time_number_str = "99999999999999"
        else:
            # 时间索引随存档结构变化：
            #   新档 len>=13：末尾 [-1]=scores dict, [-2]=快照 dict, [-3]=slot_index, [-4]=时间, [-5]=日期
            #   旧档 len==12：末尾 [-1]=快照 dict, [-2]=slot_index, [-3]=时间, [-4]=日期
            #   旧档 len==11：末尾 [-1]=slot_index(int), [-2]=时间, [-3]=日期
            if len(data) >= 13 and isinstance(data[-1], dict):
                d_idx = -5
            elif len(data) >= 12 and isinstance(data[-1], dict):
                d_idx = -4
            elif len(data) >= 11 and isinstance(data[-1], int):
                d_idx = -3
            else:
                d_idx = -2
            d = str(data[d_idx]).replace("-", "")
            t = str(data[d_idx + 1]).replace("-", "")
            time_number_str = d + t
        result.append(int(time_number_str))
        processing[time_number_str] = i
    result.sort(reverse=True)
    for k in range(len(result)):
        result[k] = processing[str(result[k])]
    return result


def get_slot_save_data(controller, slot_index):
    """读取指定格子的存档 data（无存档返回 None）。
    文件名：saves/{标题}_{识别码}_SLOT{index}.gpsave
    """
    settings = controller.story_data.get("settings", {"window_title": "GalPie", "identify_code": ""})
    story_name = settings.get("window_title", "GalPie").replace(" ", "-").replace("_", "+")
    story_id = settings.get("identify_code", "").replace(" ", "-").replace("_", "+")
    fname = f"{story_name}_{story_id}_SLOT{slot_index}.gpsave"
    fpath = os.path.join("saves", fname)
    if not os.path.exists(fpath):
        return None
    try:
        with open(fpath, "rb") as f:
            data = pickle.load(f)
        if isinstance(data, list) and len(data) >= 10:
            return data
        return None
    except Exception:
        return None


def delete_slot_save(controller, slot_index):
    """删除指定格子的存档文件。成功返回 True，无文件/失败返回 False。"""
    settings = controller.story_data.get("settings", {"window_title": "GalPie", "identify_code": ""})
    story_name = settings.get("window_title", "GalPie").replace(" ", "-").replace("_", "+")
    story_id = settings.get("identify_code", "").replace(" ", "-").replace("_", "+")
    fname = f"{story_name}_{story_id}_SLOT{slot_index}.gpsave"
    fpath = os.path.join("saves", fname)
    try:
        if os.path.exists(fpath):
            os.remove(fpath)
            return True
    except Exception:
        pass
    return False
