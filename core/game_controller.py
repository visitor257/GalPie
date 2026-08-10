from typing import Dict, Optional
from pathlib import Path
from PySide6.QtCore import QTimer, QDateTime, QByteArray, QBuffer
from PySide6.QtGui import QPixmap, QPainter
from PySide6.QtCore import Qt


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
        storyline_data = self.story_data.get("story_and_position", {}).get("storyline_id", {})
        if storyline_data:
            self.current_storyline_id = max(storyline_data, key=storyline_data.get)
            story = self.story_data["story_and_position"].get("story", {}).get(self.current_storyline_id, {})
            if story:
                first_page = next(iter(story))
                self.current_page = int(first_page)
        else:
            self.current_storyline_id = "main"

    def play_current_page(self, specify_scene=None):
        if self.is_in_menu:
            print("警告：在开始菜单中尝试播放页面，已阻止")
            return
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
            if self.auto_play:
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

        # 清除所有角色和背景（如果需要）
        if scene.get("clear_all", False):
            self.main_window.graphics_view.clear_all()
            # 同步逐场景状态：画面清空（bg/角色重置，后续场景可再设置）
            self.scene_state["bg"] = None
            self.scene_state["characters"] = {}

        # 设置背景
        if "bg" in scene:
            bg_name = scene["bg"]
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

        # 设置角色
        if "characters" in scene:
            characters_data = scene["characters"]
            character_defs = self.story_data["story_and_position"].get("character_and_motion", {})
            for char_id, char_info in characters_data.items():
                if char_id in character_defs:
                    self.setup_character(char_id, char_info, character_defs[char_id], scene.get("change", None))
                    # 同步逐场景状态：记录角色配置（form/face/pos/zoom，动画取最终值）
                    self.scene_state["characters"][char_id] = self._character_final_state(
                        char_id, char_info)
                else:
                    print(f"角色未定义: {char_id}")

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

        # 显示对话内容
        if "content" in scene:
            content = scene["content"]
            self.main_window.display_dialog(content)
            if self.has_audio(content):
                audio_duration = 2000  # 默认2秒
                self.audio_timer.start(audio_duration)
            else:
                print("场景中没有音频，立即标记音频完成")
                self.on_audio_finished()
        else:
            print("场景中没有对话内容，直接标记文本和音频完成")
            self.is_text_finished = True
            self.is_audio_finished = True
            self.check_auto_advance()

    def has_audio(self, content: Dict) -> bool:
        # 音频功能暂未实现
        return False

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
        """读档后按快照恢复画面状态：清空场景、设置背景、摆放角色（无动画）、设置对话框可见性。
        同时更新 scene_state/page_state，使后续翻页快照链保持连贯。
        """
        # 先清空当前画面（背景+角色），避免旧状态残留
        self.main_window.graphics_view.clear_all()
        bg_name = snapshot.get("bg")
        characters = snapshot.get("characters", {}) or {}
        chatbox_visible = bool(snapshot.get("chatbox_visible", True))

        # 背景
        if bg_name:
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
        self.current_scene_index += 1
        self.play_scene_sequence()

    def handle_click(self):
        if not self.is_in_game:
            return
        print(f"处理点击事件，文本完成: {self.is_text_finished}, 音频完成: {self.is_audio_finished}")
        print(f"等待下一页: {self.is_waiting_for_next_page}")
        if self.is_waiting_for_next_page:
            print("正在等待进入下一页，立即进入下一页")
            self.is_waiting_for_next_page = False
            self.play_current_page()
            return
        if not self.is_text_finished:
            print("文本未完成，立即完成显示")
            self.main_window.text_display.complete_display()
        elif not self.is_audio_finished:
            print("文本已完成，音频未完成，立即完成音频")
            self.on_audio_finished()
        else:
            print("文本和音频都已完成，进入下一个场景")
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