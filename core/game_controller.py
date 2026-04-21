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

        self.window_size = [1280, 720]
        self.background_pos = [0, 0]
        self.language = None

    def set_story_data(self, data: Dict, base_path: Path):
        self.story_data = data
        self.base_path = base_path

    def apply_settings(self):
        if not self.story_data:
            return
        settings = self.story_data.get("settings", {})
        self.language = settings["language"][0]
        if "window_title" in settings:
            self.main_window.setWindowTitle(settings["window_title"])
        if "window_size" in settings:
            self.window_size = list(map(int, settings["window_size"].split('x')))
            self.main_window.resize(self.window_size[0], self.window_size[1])

    def start_story(self):
        if self.is_in_menu:
            print("警告：在开始菜单中尝试开始故事，已阻止")
            return
        self.goto_storyline_by_check_value()
        self.play_current_page()

    def goto_storyline_by_check_value(self):
        self.current_page = 1
        self.current_scene_index = 0
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
            self.current_page += 1
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

        # 设置背景
        if "bg" in scene:
            bg_name = scene["bg"]
            backgrounds = self.story_data["story_and_position"].get("backgrounds", {})
            if bg_name in backgrounds:
                bg_path = backgrounds[bg_name]
                full_bg_path = self.base_path / bg_path
                bg_pixmap = self.main_window.load_pixmap(str(full_bg_path))
                if bg_pixmap:
                    self.background_pos = [(self.window_size[0] - bg_pixmap.width()) // 2, 0]
                    self.main_window.graphics_view.update_bg_pos(self.background_pos)
                    self.main_window.graphics_view.set_background(bg_pixmap, scene.get("change", None))
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
                else:
                    print(f"角色未定义: {char_id}")

        # 控制对话框可见性（新增功能）
        if "chatbox" in scene:
            chatbox_config = scene["chatbox"]
            print(f"[Controller] 处理 chatbox 配置: {chatbox_config}")
            visible = chatbox_config.get("visible", True)
            change_effect = chatbox_config.get("change", None)
            self.main_window.set_chatbox_visible(visible, change_effect)

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

    def on_text_display_complete(self):
        print("文本显示完成")
        self.is_text_finished = True
        self.check_auto_advance()

    def on_audio_finished(self):
        print("音频播放完成")
        self.is_audio_finished = True
        self.check_auto_advance()

    def check_auto_advance(self):
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
        self.auto_play = not self.auto_play
        status = "开启" if self.auto_play else "关闭"
        print(f"自动播放已{status}")
        if self.auto_play and self.is_waiting_for_next_page:
            self.play_current_page()

    # 存档相关方法代理给 save_load_system
    def save_game(self):
        from data_management.save_load_system import save_game
        save_game(self)

    def load_save(self, load_file_name=None):
        from data_management.save_load_system import load_save
        load_save(self, load_file_name)

    def build_last_scene(self):
        from data_management.save_load_system import build_last_scene
        return build_last_scene(self)

    def get_this_story_saves_new_to_old(self, save_dir="./saves", content_check=False):
        from data_management.save_load_system import get_this_story_saves_new_to_old
        return get_this_story_saves_new_to_old(self, save_dir, content_check)