from typing import Dict, Optional
from pathlib import Path
from PySide6.QtCore import QTimer, QDateTime, QByteArray, QBuffer
from PySide6.QtGui import QPixmap, QPainter, QColor
from PySide6.QtCore import Qt
from core.audio_player import AudioPlayer


class GameController:
    """游戏控制器，管理剧情推进、状态和逻辑"""
    def __init__(self, main_window):
        self.main_window = main_window
        self.story_data = None
        self.current_page = 0
        self.current_scene_index = 0
        self.current_storyline_id = None
        self.base_path = Path(".")
        self.current_page_data = []

        # 状态相关
        self.is_in_menu = False
        self.is_in_game = False

        # 播放状态控制
        self.is_text_finished = False
        self.is_audio_finished = False
        self.audio_timer = QTimer()
        self.audio_timer.setSingleShot(True)
        self.audio_timer.timeout.connect(self.on_audio_finished)
        # 音频播放器（audio.play_in_order 顺序+并行组播放）
        self.audio_player = AudioPlayer()
        # 空 id 角色动画的停留等待时长（毫秒）：无文本场景 + 空动画时使用
        self._pending_empty_anim_ms = 0

        # 自动播放开关
        self.auto_play = False
        self.is_waiting_for_next_page = False

        # 快进开关（模拟长按空格：定时器周期性触发 handle_click，快速推进场景）
        self.skip_mode = False
        self.skip_timer = QTimer()
        self.skip_timer.setInterval(50)
        self.skip_timer.timeout.connect(self._skip_tick)

        # 日志（backlog）：进入剧情时的起始页 + 已播放对话条目 [(说话人, 台词), ...]
        self.backlog_start_page = 1
        self.backlog_entries = []

        self.window_size = [1280, 720]
        # 逻辑分辨率：场景坐标定位基准（默认 1280x720，可由 JSON settings.window_size 覆盖）
        self.logical_size = [1280, 720]
        # 分辨率选项列表（JSON settings.window_size，index=0 为初始分辨率）
        self.resolution_options = []
        self.background_pos = [0, 0]
        self.language = None
        self.transition_color = [0, 0, 0]  # 转场底色（settings.transition_color），默认黑

        # 画面状态双变量（存档快照用）：
        #   scene_state（a）：随场景执行逐场景记录当前画面（bg id / 角色配置 / chatbox 可见性）
        #   page_state（b）：每页开始前由 a 赋值而来，代表"该页初始画面状态"，不受页内场景影响
        # 翻页时把 b 作为新页快照；存档存 b；读档直接按 b 构建画面。
        # 结构：
        #   {"bg": "咖啡馆",
        #    "characters": {"girl": {"form": "校服", "face": "平常", "pos": [x,y], "zoom": 1.5}},
        #    "chatbox_visible": True}
        self.scene_state = {"bg": None, "characters": {}, "chatbox_visible": True}
        self.page_state = {"bg": None, "characters": {}, "chatbox_visible": True}
        # 已生成的按页快照字典：{页号: page_state副本}，供存档时取当前页快照
        self.page_snapshots = {}

        # 结局模式：end 线播放期间为 True（禁快进），播完自动回主菜单
        self._in_ending = False

        # 计分（分支分数）：初始值来自 storyline_id_score（各分支的初始分），
        # 剧情中由选择（selection 的 score）增减，运行时仅存内存，存档时写入 data[12]。
        # 结构：{"main": 1.0, "girl": 1.0, ...}
        self.scores = {}
        # 选线判定阈值（storyline_settings.score_gap，缺省 0）：judge 路由中
        # 第一名 - 第二名 >= score_gap 才进入第一名的线，否则走保底线
        self.score_gap = 0.0
        # 选择等待状态：selection 场景显示选项按钮期间置 True，阻止点击推进剧情
        self.is_waiting_for_selection = False
        # 场景级 next 路由（如 ["main", "20"]）：当前场景播完后跳线跳页
        self.pending_next = None
        # 用户点击推进标志：文本显示完后点击 -> 停音频并立即进入下一页（跳过翻页等待）
        self._force_advance_immediate = False

    def set_story_data(self, data: Dict, base_path: Path):
        self.story_data = data
        self.base_path = base_path

    def apply_settings(self):
        if not self.story_data:
            return
        settings = self.story_data.get("settings", {})
        lang_cfg = settings.get("language", {})
        if isinstance(lang_cfg, dict):
            # 新格式：{语言id: 语言名称}，取第一个 id 为当前语言
            self.language = next(iter(lang_cfg)) if lang_cfg else "zh"
        else:
            # 兼容旧格式：列表 [id, ...]
            self.language = lang_cfg[0] if lang_cfg else "zh"
        if "window_title" in settings:
            self.main_window.setWindowTitle(settings["window_title"])
        # 转场底色：settings.transition_color（如 [0,0,0] 黑），缺省黑色
        tc = settings.get("transition_color", [0, 0, 0])
        if isinstance(tc, (list, tuple)) and len(tc) >= 3:
            self.transition_color = [int(c) for c in tc[:3]]
        else:
            self.transition_color = [0, 0, 0]
        self.main_window.apply_transition_color(self.transition_color)
        if "window_size" in settings:
            ws = settings["window_size"]
            if isinstance(ws, str):
                # 兼容旧格式：单个分辨率字符串
                res_list = [ws]
            else:
                # 新格式：列表，index=0 为初始（默认）分辨率
                res_list = list(ws)
            self.resolution_options = res_list
            # 初始分辨率 = 列表第一个；逻辑分辨率 = 初始分辨率（场景坐标基准）
            init_w, init_h = map(int, res_list[0].split('x'))
            self.logical_size = [init_w, init_h]
            self.window_size = [init_w, init_h]
            self.main_window.graphics_view.set_logical_size(
                self.logical_size[0], self.logical_size[1])
            self.main_window.resize(self.logical_size[0], self.logical_size[1])
        # 选线判定阈值：story_and_position.storyline_settings.score_gap（缺省 0）
        try:
            _sl = self.story_data.get("story_and_position", {}).get("storyline_settings", {}) or {}
            self.score_gap = float(_sl.get("score_gap", 0) or 0)
        except (TypeError, ValueError):
            self.score_gap = 0.0

    def start_story(self):
        if self.is_in_menu:
            print("警告：在开始菜单中尝试开始故事，已阻止")
            return
        self.goto_storyline_by_check_value()
        self.play_current_page()

    def goto_storyline_by_check_value(self):
        self.current_page = 1
        self.current_scene_index = 0
        # 进入剧情：重置日志（起始页记录 + 清空条目）
        self.backlog_start_page = 1
        self.backlog_entries = []
        # 进入剧情：重置画面状态（第 1 页初始：空背景、无角色、chatbox 可见）
        self.scene_state = {"bg": None, "characters": {}, "chatbox_visible": True}
        self.page_state = {"bg": None, "characters": {}, "chatbox_visible": True}
        self.page_snapshots = {}
        # 重置选择状态（选项页返回主菜单后，再进剧情时避免残留拦截点击/快进）
        self.is_waiting_for_selection = False
        self.pending_next = None
        self.main_window.hide_selection()
        # 重置结局模式（重新开始游戏时清除）
        self._in_ending = False
        # 重新开始：停止可能残留的音频
        self.audio_player.stop()
        self.audio_timer.stop()
        self._force_advance_immediate = False
        # 故事线配置：story_and_position.storyline_settings
        #   main_storyline：主线（游戏开始首先播放的线，缺省 "main"）
        #   storyline_id_score：各分支初始分数（计分用，缺省空 dict）
        _sl_settings = self.story_data.get("story_and_position", {}).get("storyline_settings", {}) or {}
        # 开局主线 = main_storyline 指定的线
        self.current_storyline_id = str(_sl_settings.get("main_storyline", "main") or "main")
        storyline_data = _sl_settings.get("storyline_id_score", {}) or {}
        # 播放主线第一页
        story = self.story_data["story_and_position"].get("story", {}).get(self.current_storyline_id, {})
        if story:
            first_page = next(iter(story))
            self.current_page = int(first_page)
        # 计分重置：各分支分数 = storyline_id_score 的初始值（仅计分用，不影响开局主线）
        self.scores = {}
        for branch, val in storyline_data.items():
            try:
                self.scores[branch] = float(val)
            except (TypeError, ValueError):
                self.scores[branch] = 0.0

    def play_current_page(self, specify_scene=None):
        if self.is_in_menu:
            print("警告：在开始菜单中尝试播放页面，已阻止")
            return
        # 结局线：真正开始播放 end 页时强制自动播放（点击进入/读档进入均生效）
        if getattr(self, "_in_ending", False) and not self.auto_play:
            self.auto_play = True
            print("结局线：强制开启自动播放")
            try:
                self.main_window._update_auto_play_icon()
            except Exception:
                pass
        if "story_and_position" not in self.story_data:
            print("JSON格式错误：缺少story_and_position")
            return
        if not self.current_storyline_id:
            self.goto_storyline_by_check_value()

        story = self.story_data["story_and_position"].get("story", {}).get(self.current_storyline_id, {})
        page_key = str(self.current_page)
        print(f"尝试播放页面: {page_key}")
        if page_key not in story:
            print("故事结束")
            return

        page_data = story[page_key]
        self.current_page_data = page_data
        self.current_scene_index = 0
        self.is_waiting_for_next_page = False
        self.play_scene_sequence(specify_scene)

    def play_scene_sequence(self, specify_scene=None):
        print(f"播放场景序列，当前场景索引: {self.current_scene_index}, 总场景数: {len(self.current_page_data)}")
        if self.current_scene_index >= len(self.current_page_data):
            # 本页（a 页）全部场景播完，进入下一页前：
            # 先检查页级 next 路由（如 ["main", "20"]）：有则跳线跳页，不走默认 +1
            if self.pending_next:
                nxt = self.pending_next
                self.pending_next = None
                immediate = self._force_advance_immediate
                self._force_advance_immediate = False
                self._jump_to(nxt, wait_if_no_autoplay=not immediate)
                return
            # 把逐场景状态 scene_state（a 页最终画面）记为 page_state（新页初始状态），
            # 并存为按页快照。读档时直接用该页快照构建画面。
            new_page = self.current_page + 1
            self.page_state = {
                "bg": self.scene_state.get("bg"),
                "characters": {k: dict(v) for k, v in self.scene_state.get("characters", {}).items()},
                "chatbox_visible": bool(self.scene_state.get("chatbox_visible", True)),
            }
            self.page_snapshots[new_page] = {
                "bg": self.page_state["bg"],
                "characters": {k: dict(v) for k, v in self.page_state["characters"].items()},
                "chatbox_visible": self.page_state["chatbox_visible"],
            }
            print(f"翻页快照: 页{new_page} 初始状态={self.page_state}")
            self.current_page = new_page
            self.current_scene_index = 0
            print(f"准备下一页: {self.current_page}")
            if self.auto_play or self._force_advance_immediate:
                self._force_advance_immediate = False
                self.play_current_page()
            else:
                self.is_waiting_for_next_page = True
                print("自动播放已关闭，等待用户点击进入下一页")
            return

        scene = specify_scene
        if scene is None:
            scene = self.current_page_data[self.current_scene_index]
        self.execute_scene(scene)

    def execute_scene(self, scene: Dict):
        print(f"执行场景 {self.current_scene_index}: {scene}")
        self.is_text_finished = False
        self.is_audio_finished = False
        self._pending_empty_anim_ms = 0

        # 清除所有角色和背景（如果需要）
        if scene.get("clear_all", False):
            self.main_window.graphics_view.clear_all()
            # 同步逐场景状态：画面清空（bg/角色重置，后续场景可再设置）
            self.scene_state["bg"] = None
            self.scene_state["characters"] = {}

        # 设置背景：字符串 = 背景 id（查 backgrounds 表加载图片）；
        # 字典 {"color": [r,g,b]} = 纯色背景（等价 h×w 纯色图片）
        if "bg" in scene:
            bg_name = scene["bg"]
            if isinstance(bg_name, dict) and "color" in bg_name:
                color = bg_name.get("color")
                if isinstance(color, (list, tuple)) and len(color) >= 3:
                    w, h = self.logical_size
                    bg_pixmap = QPixmap(w, h)
                    bg_pixmap.fill(QColor(int(color[0]), int(color[1]), int(color[2])))
                    self.background_pos = [0, 0]
                    self.main_window.graphics_view.update_bg_pos([0, 0])
                    self.main_window.graphics_view.set_background(bg_pixmap, scene.get("change", None))
                    # 同步逐场景状态：记录纯色背景配置（存 dict，读档/缩略图按同格式还原）
                    self.scene_state["bg"] = {"color": [int(c) for c in color[:3]]}
            elif isinstance(bg_name, str):
                backgrounds = self.story_data["story_and_position"].get("backgrounds", {})
                if bg_name in backgrounds:
                    bg_path = backgrounds[bg_name]
                    full_bg_path = self.base_path / bg_path
                    bg_pixmap = self.main_window.load_pixmap(str(full_bg_path))
                    if bg_pixmap:
                        self.background_pos = [(self.logical_size[0] - bg_pixmap.width()) // 2, 0]
                        self.main_window.graphics_view.update_bg_pos(self.background_pos)
                        self.main_window.graphics_view.set_background(bg_pixmap, scene.get("change", None))
                        # 同步逐场景状态：记录当前背景 id
                        self.scene_state["bg"] = bg_name
                    else:
                        print(f"无法加载背景图片: {full_bg_path}")
                else:
                    print(f"背景未定义: {bg_name}")

        # 设置角色（增量更新：clear_all=false 且渐变时，只更新变化的部分，未变化的保持不动）
        if "characters" in scene:
            characters_data = scene["characters"]
            character_defs = self.story_data["story_and_position"].get("character_and_motion", {})
            change_effect = scene.get("change", None)
            for char_id, char_info in characters_data.items():
                if char_id == "":
                    # 空 id 角色：不加载图片，仅计算动画总时长作为停留等待
                    # （无图空动画，视觉上画面保持当前状态动画时长）
                    anims = char_info.get("animate") or []
                    dur = self._calc_anim_duration(anims)
                    if dur > self._pending_empty_anim_ms:
                        self._pending_empty_anim_ms = dur
                    continue
                if char_id not in character_defs:
                    print(f"角色未定义: {char_id}")
                    continue
                new_final = self._character_final_state(char_id, char_info)
                old_final = self.scene_state["characters"].get(char_id)
                if old_final is not None and old_final == new_final:
                    # 配置未变化：保持当前显示不重建；若本场景带动画，直接对现有 item 播放
                    if char_info.get("animate"):
                        item = self.main_window.graphics_view.character_items.get(char_id)
                        if item is not None:
                            item.set_animations(char_info["animate"])
                    continue
                self.setup_character(char_id, char_info, character_defs[char_id], change_effect)
                # 同步逐场景状态：记录角色配置（form/face/pos/zoom，动画取最终值）
                self.scene_state["characters"][char_id] = new_final

        # 控制对话框可见性（新增功能）
        if "chatbox" in scene:
            chatbox_config = scene["chatbox"]
            print(f"[Controller] 处理 chatbox 配置: {chatbox_config}")
            visible = chatbox_config.get("visible", True)
            change_effect = chatbox_config.get("change", None)
            self.main_window.set_chatbox_visible(visible, change_effect)
            # 同步逐场景状态：记录对话框可见性
            self.scene_state["chatbox_visible"] = bool(visible)

        # 启动所有待执行的动画
        self.main_window.graphics_view.start_pending_animations()

        # 记录场景级 next 路由（如 cafe_girl 页2 的 ["main", "20"]）：
        # 本场景播完后跳线跳页，由 check_auto_advance -> advance_to_next_scene 消费
        if "next" in scene:
            self.pending_next = scene["next"]

        # 选择场景：显示选项按钮，等待玩家选择（不推进、不显示对话）
        if "selection" in scene:
            self.is_text_finished = False
            self.is_audio_finished = False
            self.is_waiting_for_selection = True
            self.main_window.show_selection(scene["selection"], self.on_selection_chosen)
            return

        # 显示对话内容（文本逐字显示，完成后回调置 is_text_finished）
        if "content" in scene:
            content = scene["content"]
            self.main_window.display_dialog(content)
        else:
            print("场景中没有对话内容，直接标记文本完成")
            self.is_text_finished = True

        # 音频播放（场景级 audio 配置）：
        #   json_mode=normal -> play_in_order 为多语言 dict，取当前语言，无文件则不播
        #   json_mode=judge   -> play_in_order 为模板二维列表，替换 <line>/<page>/<lang_id>，
        #                        当前语言无文件时回退 settings.default_audio_lang_id
        # 组内并行、组间顺序，全部播完回调 on_audio_finished
        audio_cfg = scene.get("audio")
        groups = self._resolve_audio_playlist(audio_cfg) if audio_cfg else None
        if groups:
            print(f"播放音频: {len(groups)} 组，共 {sum(len(g) for g in groups)} 路")
            self.is_audio_finished = False
            self.audio_player.play(groups, self.on_audio_finished)
        else:
            # 无有效音频：停止上一场景残留音频
            self.audio_player.stop()
            if self._pending_empty_anim_ms > 0:
                # 空动画等待：无文本场景 + 空 id 角色动画 -> 停留动画时长再继续
                # （复用音频计时机制：点击可跳过等待）
                wait = self._pending_empty_anim_ms
                self._pending_empty_anim_ms = 0
                print(f"场景中没有音频，空动画停留 {wait}ms")
                self.is_audio_finished = False
                self.audio_timer.start(wait)
            else:
                print("场景中没有音频，立即标记音频完成")
                self.is_audio_finished = True
                self.check_auto_advance()

    # ---------- 音频配置解析 ----------

    def _resolve_audio_playlist(self, audio_cfg):
        """解析场景 audio 配置为播放组列表 [[绝对路径, ...], ...]，无有效音频返回 None。

        json_mode=normal：play_in_order 为多语言 dict，只取当前语言（该语言无文件则不播放）；
        json_mode=judge  ：play_in_order 为模板二维列表，替换 <line>/<page>/<lang_id>，
                           当前语言文件缺失时回退 settings.default_audio_lang_id。
        """
        if not isinstance(audio_cfg, dict):
            return None
        mode = audio_cfg.get("json_mode", "normal")
        pio = audio_cfg.get("play_in_order")
        if mode == "judge":
            return self._resolve_judge_playlist(pio)
        # normal：多语言 dict，取当前语言
        if isinstance(pio, dict):
            pio = pio.get(self.language or "zh")
        return self._resolve_common_playlist(pio)

    def _resolve_common_playlist(self, pio):
        """通用解析：二维列表 [[path,...],...]，逐元素检查文件存在，组全空则跳过。"""
        if not isinstance(pio, list):
            return None
        groups = []
        for group in pio:
            if not isinstance(group, list):
                continue
            files = []
            for item in group:
                if not isinstance(item, str):
                    continue
                p = self._audio_full_path(item)
                if p is not None and p.exists():
                    files.append(str(p))
            if files:
                groups.append(files)
        return groups or None

    def _resolve_judge_playlist(self, pio):
        """judge 模式：替换 <line>/<page>/<lang_id>，先当前语言，缺失回退默认语言。"""
        if not isinstance(pio, list):
            return None
        line = self.current_storyline_id or "main"
        page = str(self.current_page)
        lang = self.language or "zh"
        groups = self._resolve_template_playlist(pio, line, page, lang)
        if groups:
            return groups
        # 当前语言无有效文件：尝试 default_audio_lang_id
        default_lang = None
        try:
            default_lang = (self.story_data or {}).get("settings", {}).get("default_audio_lang_id")
        except Exception:
            pass
        if default_lang and str(default_lang) != lang:
            groups = self._resolve_template_playlist(pio, line, page, str(default_lang))
            if groups:
                print(f"音频回退默认语言: {lang} -> {default_lang}")
                return groups
        return None

    def _resolve_template_playlist(self, pio, line, page, lang):
        """judge 模板替换：<line>/<page>/<lang_id> -> 实际值，逐元素检查文件存在。"""
        groups = []
        for group in pio:
            if not isinstance(group, list):
                continue
            files = []
            for item in group:
                if not isinstance(item, str):
                    continue
                path = item.replace("<line>", line).replace("<page>", page).replace("<lang_id>", lang)
                p = self._audio_full_path(path)
                if p is not None and p.exists():
                    files.append(str(p))
            if files:
                groups.append(files)
        return groups or None

    def _audio_full_path(self, rel):
        """音频相对路径基于 base_path（剧情 story 目录）解析，返回 Path 或 None。"""
        if not rel or not isinstance(rel, str):
            return None
        p = Path(rel)
        if p.is_absolute():
            return p
        return self.base_path / rel

    def _calc_anim_duration(self, anims) -> int:
        """计算动画总时长（毫秒）：组内取最大 time，组间求和。
        用于空 id 角色动画的停留等待时长。
        """
        total = 0.0
        if isinstance(anims, (list, tuple)):
            for group in anims:
                gmax = 0.0
                if isinstance(group, (list, tuple)):
                    for a in group:
                        if isinstance(a, dict):
                            try:
                                t = float(a.get("time", 0) or 0)
                                if t > gmax:
                                    gmax = t
                            except (TypeError, ValueError):
                                pass
                total += gmax
        return int(total * 1000)

    def setup_character(self, char_id: str, char_info: Dict, char_data: Dict, changeEffect=None):
        form_name = char_info["form"]
        face_info = char_info["face"]
        if isinstance(face_info, list):
            face_name = face_info[0]
        else:
            face_name = face_info

        pos = [char_info["pos"][0] + self.background_pos[0], char_info["pos"][1] + self.background_pos[1]]
        zoom = char_info.get("zoom", 1.0)
        animations = char_info.get("animate", [])

        form_pixmap = None
        if "form" in char_data and form_name in char_data["form"]:
            form_path = char_data["form"][form_name]
            full_form_path = self.base_path / form_path
            form_pixmap = self.main_window.load_pixmap(str(full_form_path))

        face_pixmap = None
        if "face" in char_data and face_name in char_data["face"]:
            face_path = char_data["face"][face_name]
            full_face_path = self.base_path / face_path
            face_pixmap = self.main_window.load_pixmap(str(full_face_path))

        if form_pixmap and face_pixmap:
            combined_pixmap = QPixmap(form_pixmap.size())
            combined_pixmap.fill(Qt.transparent)
            painter = QPainter(combined_pixmap)
            painter.setRenderHint(QPainter.Antialiasing)
            painter.setRenderHint(QPainter.SmoothPixmapTransform)
            painter.drawPixmap(0, 0, form_pixmap)
            painter.drawPixmap(0, 0, face_pixmap)
            painter.end()
            self.main_window.graphics_view.add_character(char_id, combined_pixmap, pos, zoom, animations, changeEffect)
        elif form_pixmap:
            self.main_window.graphics_view.add_character(char_id, form_pixmap, pos, zoom, animations, changeEffect)
        elif face_pixmap:
            self.main_window.graphics_view.add_character(char_id, face_pixmap, pos, zoom, animations, changeEffect)
        else:
            print(f"无法加载角色图片: {char_id}")

    def _character_final_state(self, char_id: str, char_info: Dict) -> Dict:
        """计算角色在场景中的最终状态（动画取最终值），用于快照记录。
        返回 {"form": ..., "face": ..., "pos": [x, y], "zoom": ...}
        pos 为未加背景偏移的原始坐标（与 JSON 一致），读档还原时由
        还原逻辑统一加背景偏移，避免背景变化导致坐标漂移。
        """
        face_info = char_info.get("face")
        face_name = face_info[0] if isinstance(face_info, list) else face_info
        # 初始 pos/zoom
        pos = [float(char_info.get("pos", [0, 0])[0]), float(char_info.get("pos", [0, 0])[1])]
        zoom = float(char_info.get("zoom", 1.0))
        # 动画最终值：遍历所有动画组，zoom 取最后一个 zoom 目标；move 累加位移
        for group in char_info.get("animate", []) or []:
            for anim in group or []:
                if anim.get("zoom") is not None:
                    zoom = float(anim["zoom"])
                move = anim.get("move")
                if move:
                    pos[0] += float(move[-1][0])
                    pos[1] += float(move[-1][1])
        return {
            "form": char_info.get("form"),
            "face": face_name,
            "pos": [int(pos[0]), int(pos[1])],
            "zoom": zoom,
        }

    def restore_snapshot(self, snapshot: Dict):
        # 读档：停止可能残留的音频
        self.audio_player.stop()
        self.audio_timer.stop()
        """读档后按快照恢复画面状态：清空场景、设置背景、摆放角色（无动画）、设置对话框可见性。
        同时更新 scene_state/page_state，使后续翻页快照链保持连贯。
        """
        # 先清空当前画面（背景+角色），避免旧状态残留
        self.main_window.graphics_view.clear_all()
        # 清理残留选择项：读档时若处于选择页，旧选项按钮必须移除，
        # 读到的目标页若也是选择页，会由 execute_scene 重新显示
        self.main_window.hide_selection()
        self.is_waiting_for_selection = False
        self.pending_next = None
        bg_name = snapshot.get("bg")
        characters = snapshot.get("characters", {}) or {}
        chatbox_visible = bool(snapshot.get("chatbox_visible", True))

        # 背景（字符串=背景 id；字典 {"color": [...]} = 纯色背景）
        if bg_name:
            if isinstance(bg_name, dict) and "color" in bg_name:
                color = bg_name.get("color")
                if isinstance(color, (list, tuple)) and len(color) >= 3:
                    w, h = self.logical_size
                    bg_pixmap = QPixmap(w, h)
                    bg_pixmap.fill(QColor(int(color[0]), int(color[1]), int(color[2])))
                    self.background_pos = [0, 0]
                    self.main_window.graphics_view.update_bg_pos([0, 0])
                    self.main_window.graphics_view.set_background(bg_pixmap)
            elif isinstance(bg_name, str):
                backgrounds = self.story_data.get("story_and_position", {}).get("backgrounds", {})
                if bg_name in backgrounds:
                    bg_path = backgrounds[bg_name]
                    full_bg_path = self.base_path / bg_path
                    bg_pixmap = self.main_window.load_pixmap(str(full_bg_path))
                    if bg_pixmap:
                        self.background_pos = [(self.logical_size[0] - bg_pixmap.width()) // 2, 0]
                        self.main_window.graphics_view.update_bg_pos(self.background_pos)
                        self.main_window.graphics_view.set_background(bg_pixmap)
        # 角色（按快照配置直接摆放，无动画）
        char_defs = self.story_data.get("story_and_position", {}).get("character_and_motion", {})
        for char_id, char_info in characters.items():
            if char_id not in char_defs:
                continue
            form_name = char_info.get("form")
            face_name = char_info.get("face")
            pos = list(char_info.get("pos", [0, 0]))
            zoom = float(char_info.get("zoom", 1.0))
            # 组装角色图（form+face 合成，同 setup_character）
            form_pixmap = None
            face_pixmap = None
            char_data = char_defs[char_id]
            if form_name and form_name in char_data.get("form", {}):
                form_pixmap = self.main_window.load_pixmap(
                    str(self.base_path / char_data["form"][form_name]))
            if face_name and face_name in char_data.get("face", {}):
                face_pixmap = self.main_window.load_pixmap(
                    str(self.base_path / char_data["face"][face_name]))
            combined = None
            if form_pixmap and face_pixmap and not form_pixmap.isNull() and not face_pixmap.isNull():
                combined = QPixmap(form_pixmap.size())
                combined.fill(Qt.transparent)
                p = QPainter(combined)
                p.setRenderHint(QPainter.Antialiasing)
                p.setRenderHint(QPainter.SmoothPixmapTransform)
                p.drawPixmap(0, 0, form_pixmap)
                p.drawPixmap(0, 0, face_pixmap)
                p.end()
            elif form_pixmap and not form_pixmap.isNull():
                combined = form_pixmap
            elif face_pixmap and not face_pixmap.isNull():
                combined = face_pixmap
            if combined is not None:
                # pos 为原始坐标（快照记录时未加背景偏移），加背景偏移摆放
                draw_pos = [pos[0] + self.background_pos[0], pos[1] + self.background_pos[1]]
                self.main_window.graphics_view.add_character(
                    char_id, combined, draw_pos, zoom, [], None)
        # 对话框可见性
        self.main_window.set_chatbox_visible(chatbox_visible)
        # 同步状态变量，使后续翻页快照链连贯
        self.scene_state = {
            "bg": bg_name,
            "characters": {k: dict(v) for k, v in characters.items()},
            "chatbox_visible": chatbox_visible,
        }
        self.page_state = {
            "bg": bg_name,
            "characters": {k: dict(v) for k, v in characters.items()},
            "chatbox_visible": chatbox_visible,
        }
        self.page_snapshots[self.current_page] = {
            "bg": bg_name,
            "characters": {k: dict(v) for k, v in characters.items()},
            "chatbox_visible": chatbox_visible,
        }
        print(f"快照恢复: 页{self.current_page} bg={bg_name} 角色={list(characters.keys())} chatbox={chatbox_visible}")

    def _resolve_next(self, nxt):
        """解析 next 路由为目标 [line, page]（返回 None 表示无法跳转/无跳转）。

        支持的格式：
          - 新格式 dict：{"direct": ["线", "页"]} 直接指向；
                         {"judge": ...} 判定路由（暂未实现，返回 None 占位）
          - 旧格式数组：["线", "页"]
        """
        # 结局标记：字符串 "end" 表示整个剧情的最后一页，播完自动回主菜单
        if isinstance(nxt, str) and nxt == "end":
            return ["__end__", 0]
        if isinstance(nxt, dict):
            if "direct" in nxt and isinstance(nxt["direct"], (list, tuple)) and len(nxt["direct"]) >= 2:
                return [str(nxt["direct"][0]), int(nxt["direct"][1])]
            if "judge" in nxt:
                return self._judge_next(nxt["judge"])
            return None
        if isinstance(nxt, (list, tuple)) and len(nxt) >= 2:
            return [str(nxt[0]), int(nxt[1])]
        return None

    def _judge_next(self, judge_list):
        """judge 判定路由：返回 [线id, 页码] 或 None。

        格式：{"judge": [[候选线列表], [保底线]]}
          - index 0：参加角逐的线（可多条），每条 [线id, 页码]
          - index 1：保底线，固定一条 [线id, 页码]
        判定：评比集合 = 候选线 + 保底线，取分值第一的线；
          第一名 - 第二名 >= score_gap -> 进第一名的线（其指定页）；
          否则 -> 进保底线（其指定页）。
        """
        try:
            candidates = judge_list[0] if isinstance(judge_list, (list, tuple)) and len(judge_list) >= 1 else None
            # 保底线：judge_list[1] 为 [[线, 页]]（固定一条），取 [0]
            fallback = None
            if isinstance(judge_list, (list, tuple)) and len(judge_list) >= 2:
                _fb_list = judge_list[1]
                if isinstance(_fb_list, (list, tuple)) and len(_fb_list) >= 1:
                    fallback = _fb_list[0]
            if not fallback or not isinstance(fallback, (list, tuple)) or len(fallback) < 2:
                print("next.judge 配置无效：缺少保底线")
                return None
            fb_line, fb_page = str(fallback[0]), int(fallback[1])
            # 评比集合：线id -> 页码（保底线并入；候选重复时保留首个）
            routes = {}
            if isinstance(candidates, (list, tuple)):
                for c in candidates:
                    if isinstance(c, (list, tuple)) and len(c) >= 2:
                        routes.setdefault(str(c[0]), int(c[1]))
            routes.setdefault(fb_line, fb_page)
            # 取各线当前分值（缺分按 0）
            scored = []
            for line, page in routes.items():
                try:
                    score = float(self.scores.get(line, 0.0) or 0.0)
                except (TypeError, ValueError):
                    score = 0.0
                scored.append((score, line, page))
            scored.sort(key=lambda x: x[0], reverse=True)
            first = scored[0]
            if len(scored) >= 2:
                second = scored[1]
                diff = first[0] - second[0]
                print(f"judge 判定: 候选={[(ln, sc) for sc, ln, _ in scored]} gap={self.score_gap} 第一={first[1]}({first[0]}) 第二={second[1]}({second[0]}) 差={diff}")
                if diff >= self.score_gap:
                    print(f"judge 结果: 进入 {first[1]}:{first[2]}")
                    return [first[1], first[2]]
            else:
                print(f"judge 判定: 仅一条线 {first[1]}({first[0]})，直接进入")
                return [first[1], first[2]]
            print(f"judge 结果: 分差不足，进入保底 {fb_line}:{fb_page}")
            return [fb_line, fb_page]
        except Exception as e:
            print(f"next.judge 判定失败: {e}")
            return None

    def _jump_to(self, nxt, wait_if_no_autoplay=False):
        """按 next 路由跳线跳页：支持 {"direct": [...]} 与旧 ["线", "页"] 格式。
        跳转后把当前画面状态（scene_state）记为目标页初始快照（page_state），
        保证读档/后续翻页的快照链连贯；然后从目标页第 0 场景开始播放。
        wait_if_no_autoplay=True：自动播放关闭时跳到目标页后等待用户点击
        （与正常翻页行为一致），用于"场景播完自动触发"的 next 路由；
        选项点击触发的跳转（wait=False）立即播放，因为用户刚主动选择过。
        """
        target = self._resolve_next(nxt)
        if target is None:
            return
        line, page = target[0], target[1]
        # 结局标记：剧情播放完毕，自动回主菜单（带转场渐变）
        if line == "__end__":
            self._finish_ending()
            return
        print(f"跳线路由: {self.current_storyline_id}:{self.current_page} -> {line}:{page}")
        self.current_storyline_id = line
        self.current_page = page
        self.current_scene_index = 0
        self.is_waiting_for_next_page = False
        # 结局线：进入 end 线即结局模式（禁快进）。
        # 注意：不在这里强制自动播放——从剧情页 next 跳入时（wait_if_no_autoplay=True）
        # 应先等待用户点击进入 end 页，点击后由 play_current_page 强制自动播放。
        if line == "end":
            self._in_ending = True
        # 目标页初始快照 = 当前画面状态（跳转瞬间 scene_state）
        self.page_state = {
            "bg": self.scene_state.get("bg"),
            "characters": {k: dict(v) for k, v in self.scene_state.get("characters", {}).items()},
            "chatbox_visible": bool(self.scene_state.get("chatbox_visible", True)),
        }
        self.page_snapshots[self.current_page] = {
            "bg": self.page_state["bg"],
            "characters": {k: dict(v) for k, v in self.page_state["characters"].items()},
            "chatbox_visible": self.page_state["chatbox_visible"],
        }
        print(f"跳线快照: 页{self.current_page} 初始状态={self.page_state}")
        # 自动播放关闭且要求等待：跳到目标页但不立即播放（与正常翻页一致）
        if wait_if_no_autoplay and not self.auto_play:
            self.is_waiting_for_next_page = True
            print("自动播放已关闭，跳转后等待用户点击进入")
            return
        self.play_current_page()

    def _finish_ending(self):
        """结局播放完毕：自动返回主菜单（带 transition_color 渐变转场）。"""
        print("剧情结束，返回主菜单")
        self.pending_next = None
        self.is_waiting_for_next_page = False
        self.main_window.fade_to_menu()

    def on_selection_chosen(self, option: Dict):
        """选择回调：玩家点了一个选项后调用。
        处理：关闭选择 UI、加分（score）、按 next 跳线（无 next 则继续本线下一场景）。
        """
        self.is_waiting_for_selection = False
        self.main_window.hide_selection()
        # 加分：score = [分支id, 数值]（如 ["girl", 0.5]）
        score = option.get("score")
        if isinstance(score, (list, tuple)) and len(score) >= 2:
            branch = str(score[0])
            try:
                val = float(score[1])
            except (TypeError, ValueError):
                val = 0.0
            self.scores[branch] = self.scores.get(branch, 0.0) + val
            print(f"选择加分: {branch} +{val} = {self.scores[branch]}")
        # 跳转：next 支持 {"direct": [...]} 新格式与旧 ["线", "页"] 数组；
        # 无 next 或无法解析则正常顺序（当前线下一场景/下一页）
        nxt = option.get("next")
        if nxt is not None and self._resolve_next(nxt) is not None:
            self._jump_to(nxt)
        else:
            self.advance_to_next_scene()

    def on_text_display_complete(self):
        print("文本显示完成")
        self.is_text_finished = True
        self.check_auto_advance()

    def on_audio_finished(self):
        print("音频播放完成")
        self.is_audio_finished = True
        self.check_auto_advance()

    def check_auto_advance(self):
        # 设置面板打开时：暂停自动前进（等关闭设置后由恢复逻辑接手推进）
        if getattr(self.main_window, "is_in_settings", False):
            print("设置面板打开中，暂停自动前进")
            return
        print(f"检查自动前进: 文本完成={self.is_text_finished}, 音频完成={self.is_audio_finished}")
        if self.is_text_finished and self.is_audio_finished:
            print("文本和音频都已完成，自动进入下一个场景")
            self.advance_to_next_scene()

    def advance_to_next_scene(self):
        self.audio_timer.stop()
        # 场景级 next 路由：本场景播完跳线（如 cafe_girl 页2 的 ["main", "20"]）。
        # 无自动播放时等待点击，与正常翻页行为一致
        if self.pending_next:
            nxt = self.pending_next
            self.pending_next = None
            immediate = self._force_advance_immediate
            self._force_advance_immediate = False
            self._jump_to(nxt, wait_if_no_autoplay=not immediate)
            return
        self.current_scene_index += 1
        self.play_scene_sequence()

    def handle_click(self):
        if not self.is_in_game:
            return
        if self.is_waiting_for_selection:
            print("选择等待中，忽略点击")
            return
        print(f"处理点击事件，文本完成: {self.is_text_finished}, 音频完成: {self.is_audio_finished}")
        print(f"等待下一页: {self.is_waiting_for_next_page}")
        if self.is_waiting_for_next_page:
            # 结局线：进入后强制正常速度自动播放（用户点击/自动进入均可）
            if self._in_ending and not self.auto_play:
                self.auto_play = True
                self.main_window._update_auto_play_icon()
                print("结局线：强制开启自动播放")
            print("正在等待进入下一页，立即进入下一页")
            self.is_waiting_for_next_page = False
            self.play_current_page()
            return
        if not self.is_text_finished:
            # 文本未显示完：只显示全文，不推进剧情
            print("文本未完成，立即完成显示")
            self.main_window.text_display.complete_display()
            return
        # 文本已显示完：停止音频（如有）并立即进入下一场景/下一页
        if not self.is_audio_finished:
            print("文本已完成，停止音频并进入下一页")
            self.audio_player.stop()
            self.audio_timer.stop()
            self.is_audio_finished = True
        self._force_advance_immediate = True
        self.advance_to_next_scene()

    def toggle_auto_play(self):
        # 互斥：开自动播放时，若快进开着则关闭快进（两模式不可同时开启）
        if not self.auto_play and self.skip_mode:
            self.skip_mode = False
            self.skip_timer.stop()
            print("互斥：自动播放开启，已关闭快进")
            self.main_window._update_skip_icon()
        self.auto_play = not self.auto_play
        status = "开启" if self.auto_play else "关闭"
        print(f"自动播放已{status}")
        if self.auto_play and self.is_waiting_for_next_page:
            self.play_current_page()

    def _skip_tick(self):
        """快进定时器 tick：模拟长按空格，周期性触发 handle_click。
        仅在剧情中且不在设置面板/菜单时生效。
        """
        if not self.is_in_game:
            return
        if self.main_window.is_in_settings:
            return
        if self.is_waiting_for_selection:
            return
        if self._in_ending:
            print("结局线：快进不可用")
            return
        self.handle_click()

    def toggle_skip_mode(self):
        # 互斥：开快进时，若自动播放开着则关闭自动播放（两模式不可同时开启）
        if not self.skip_mode and self.auto_play:
            self.auto_play = False
            print("互斥：快进开启，已关闭自动播放")
            self.main_window._update_auto_play_icon()
        self.skip_mode = not self.skip_mode
        status = "开启" if self.skip_mode else "关闭"
        print(f"快进模式已{status}")
        if self.skip_mode:
            self.skip_timer.start()
        else:
            self.skip_timer.stop()

    # 存档相关方法代理给 save_load_system
    def save_game(self):
        from data_management.save_load_system import save_game
        save_game(self)

    def save_game_to_slot(self, slot_index):
        """保存到指定格子（index 0-7）。"""
        from data_management.save_load_system import save_game
        save_game(self, slot_index)

    def get_slot_save_data(self, slot_index):
        """读取指定格子的存档 data（无存档返回 None）。"""
        from data_management.save_load_system import get_slot_save_data
        return get_slot_save_data(self, slot_index)

    def delete_slot_save(self, slot_index):
        """删除指定格子的存档文件。成功返回 True。"""
        from data_management.save_load_system import delete_slot_save
        return delete_slot_save(self, slot_index)

    def quick_save(self):
        """快速存档：覆盖式保存到固定 QUICK 槽（Q.Save 按钮 / 快捷键）。
        保存前若快进/自动播放开启，先关闭它们（避免保存瞬间画面/状态被推进干扰）。
        """
        # 需求：快进或自动播放时点快速保存 -> 停止/关闭快进或自动播放
        if getattr(self, "skip_mode", False):
            self.skip_mode = False
            if self.skip_timer.isActive():
                self.skip_timer.stop()
            print("快速保存：关闭快进")
            self.main_window._update_skip_icon()
        if getattr(self, "auto_play", False):
            self.auto_play = False
            print("快速保存：关闭自动播放")
            self.main_window._update_auto_play_icon()
        from data_management.save_load_system import quick_save_game
        quick_save_game(self)
        # 需求：保存完成后在 Q.Save 按钮上弹出圆角提示框（保存成功）
        self.main_window.show_quick_save_toast()

    def load_save(self, load_file_name=None):
        from data_management.save_load_system import load_save
        return load_save(self, load_file_name)

    def get_this_story_saves_new_to_old(self, save_dir="./saves", content_check=False):
        from data_management.save_load_system import get_this_story_saves_new_to_old
        return get_this_story_saves_new_to_old(self, save_dir, content_check)