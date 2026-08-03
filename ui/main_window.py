import os
from pathlib import Path
from typing import Optional

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFileDialog,
    QGraphicsTextItem, QFrame, QGraphicsRectItem, QGraphicsPixmapItem, QApplication,
    QGraphicsOpacityEffect, QComboBox, QSlider
)
from PySide6.QtCore import Qt, QTimer, QPropertyAnimation, QEasingCurve, QRectF
from PySide6.QtGui import QPixmap, QColor, QFont, QBrush, QPen

from core.game_controller import GameController
from ui.graphics_view import GraphicsView, MenuButtonItem
from ui.widgets import TextDisplayWidget
from ui.settings_panel import SettingsPanel, FULLSCREEN_KEY
from data_management.resource_manager import ResourceManager
from data_management.story_parser import load_ui_settings_from_data


# 设置面板的 JSON 自定义配置读取（预留接口，后续开发）
def load_settings_ui(self):
    """读取设置界面配置，返回面板配置 dict。
    优先读 menu_pos.settings 第 3 项（ui_mode 等）；分辨率选项已迁至 settings.window_size 列表。
    兼容旧字段 settings.ui（或 settings_ui）。
    ui_mode: "default"=预设界面（当前开发中的面板）；"custom"=JSON 自定义（规划中，暂未实现，同样回落预设）。
    """
    story_data = self.controller.story_data
    if not story_data:
        return None
    # 1) menu_pos.settings 第 3 项（新配置入口）
    menu = story_data.get("menu", {})
    menu_pos = menu.get("menu_pos", {})
    settings_btn = menu_pos.get("settings")
    if isinstance(settings_btn, list) and len(settings_btn) >= 3 and isinstance(settings_btn[2], dict):
        cfg = settings_btn[2]
        ui_mode = cfg.get("ui_mode", "default")
        if ui_mode == "custom":
            # 自定义界面：规划中，暂未实现 -> 回落预设（后续在此返回解析后的配置 dict）
            print("设置界面 ui_mode=custom：自定义解析暂未实现，使用预设界面")
            return None
        return None  # default 预设界面；分辨率选项由 settings.window_size 提供（controller 已解析）
    # 2) 旧字段 settings.ui / settings_ui
    ui_cfg = story_data.get("settings", {}).get("ui")
    if not ui_cfg:
        return None
    if ui_cfg == "preset" or ui_cfg is True:
        return None  # 使用预设
    if isinstance(ui_cfg, dict):
        # 供后续自定义解析使用，目前仅透传
        return ui_cfg
    return None


class GalGameWindow(QMainWindow):
    """Galgame 主窗口"""
    def __init__(self):
        super().__init__()
        self.controller = GameController(self)
        self.resource_manager = ResourceManager()
        self.ui_settings = {
            "chatbox_style": None,
            "name_show_region": [[76, 60], [270, 149]],
            "words_show_region": [[310, 60], [805, 149]],
            "bottom_menu": None,   # ui.bottom_menu 配置（mode/color 等），None=不显示底部菜单
        }
        self.name_label = None
        self.text_display = None
        self.text_speed_delay = 30  # 文字显示延迟(ms/字)，设置对话框可调，创建文本控件时应用
        self.chatbox_item = None
        self.chatbox_widget_proxies = []  # 存储对话框相关的所有代理控件
        self.bottom_menu_item = None  # 剧情中底部菜单条（ui.bottom_menu 预设模式）
        self.start_button = None
        self.title_item = None
        self.menu_bg_item = None
        self.graphics_view = None
        self.settings_panel = None  # 当前设置面板（场景内）
        self.is_in_settings = False  # 是否正在设置界面中
        self.menu_button_items = []  # 菜单按钮及其文本 item（打开设置时隐藏）
        self.settings_ui_config = {}  # 设置界面配置（menu_pos.settings 第 3 项：ui_mode/resolution 等）

        self.setup_ui()
        self.load_story_file()

    def setup_ui(self):
        self.setWindowTitle("GalPie")
        self.setGeometry(100, 100, 1280, 720)
        self.setStyleSheet("background-color: black;")
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)
        layout.setContentsMargins(0, 0, 0, 0)
        self.graphics_view = GraphicsView(self)
        layout.addWidget(self.graphics_view)
        self.setFocusPolicy(Qt.StrongFocus)
        self.graphics_view.setFocusPolicy(Qt.StrongFocus)
        self.graphics_view.setMouseTracking(True)

    def showEvent(self, event):
        super().showEvent(event)
        self.setFocus()

    def load_story_file(self):
        story_dir = Path("story")
        json_files = list(story_dir.glob("*.json"))
        if json_files:
            self.load_json_file(json_files[0])
        else:
            self.show_file_selection_dialog()

    def show_file_selection_dialog(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "选择故事文件", "", "JSON Files (*.json)"
        )
        if file_path:
            self.load_json_file(Path(file_path))
        else:
            QApplication.quit()

    def load_json_file(self, file_path: Path):
        import json
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                story_data = json.load(f)
            self.controller.set_story_data(story_data, file_path.parent)
            self.controller.apply_settings()
            if "menu" in story_data:
                self.show_menu()
                self.controller.is_in_menu = True
                return
            else:
                self.setup_dialog_area()
                self.controller.start_story()
                self.controller.is_in_game = True
        except Exception as e:
            print(f"加载JSON文件失败: {e}")
            import traceback
            traceback.print_exc()
            self.show_file_selection_dialog()

    def show_menu(self):
        self.controller.is_in_menu = True
        self.graphics_view.clear_items()
        self.menu_button_items = []  # 重建菜单，清空旧按钮记录
        if not self.controller.story_data or "menu" not in self.controller.story_data:
            print("错误：没有找到菜单配置")
            return
        try:
            menu_data = self.controller.story_data["menu"]
            if "bg" in menu_data:
                bg_data = menu_data["bg"]
                full_bg_path = self.controller.base_path / bg_data
                bg_pixmap = self.load_pixmap(str(full_bg_path))
                if bg_pixmap:
                    ls = self.controller.logical_size
                    self.graphics_view.add_item(bg_pixmap, [(ls[0] - bg_pixmap.width()) // 2, 0])
            if "title" in menu_data:
                # 标题图按语言取；无对应语言图时回退 zh（多语言共用一张标题图）
                title_dict = menu_data["title"]
                title_path = title_dict.get(self.controller.language) or title_dict.get("zh")
                if not title_path:
                    title_path = next(iter(title_dict.values()))
                full_title_path = self.controller.base_path / title_path
                title_pixmap = self.load_pixmap(str(full_title_path))
                if title_pixmap:
                    menu_pos = menu_data.get("menu_pos", {})
                    title_pos = menu_pos.get("title", [54, 48])
                    self.graphics_view.add_item(title_pixmap, title_pos)
            self.create_menu_buttons(menu_data)
        except Exception as e:
            print(f"显示开始菜单失败: {e}")
            import traceback
            traceback.print_exc()

    def create_menu_buttons(self, menu_data):
        """根据 menu_pos 中的按钮定义（start/settings/...）创建菜单按钮"""
        # 先解析 settings 按钮的附加配置（第 3 项），独立于图片加载，保证总能读取
        menu_pos = menu_data.get("menu_pos", {})
        settings_btn = menu_pos.get("settings")
        if isinstance(settings_btn, list) and len(settings_btn) >= 3 and isinstance(settings_btn[2], dict):
            self.settings_ui_config = dict(settings_btn[2])

        button_path = menu_data["button"]
        full_button_path = self.controller.base_path / button_path
        button_pixmap = self.load_pixmap(str(full_button_path))
        if not button_pixmap:
            print(f"无法加载按钮图片: {full_button_path}")
            return
        button_touched_path = menu_data.get("button_touched")
        touched_pixmap = None
        if button_touched_path:
            full_touched_path = self.controller.base_path / button_touched_path
            touched_pixmap = self.load_pixmap(str(full_touched_path))

        text_rgb = menu_data.get("text_rgb", [255, 255, 255])
        text_color = QColor(text_rgb[0], text_rgb[1], text_rgb[2])

        # 按钮类型 -> 点击处理函数
        handlers = {
            "start": self.on_start_button_clicked,
            "settings": self.open_settings,
        }

        for key, button_data in menu_pos.items():
            if key == "title":
                continue
            if not isinstance(button_data, list) or len(button_data) < 2:
                continue
            button_pos = button_data[0]
            texts = button_data[1]
            if not isinstance(texts, dict) or not texts:
                continue

            button_item = MenuButtonItem(button_pixmap, touched_pixmap)
            button_item.setPos(button_pos[0], button_pos[1])
            button_item.setZValue(2)
            handler = handlers.get(key)
            if handler:
                button_item.set_click_handler(handler)
            self.graphics_view.add_item(button_item, button_pos)
            self.menu_button_items.append(button_item)

            text = texts.get(self.controller.language, next(iter(texts.values())))
            text_item = QGraphicsTextItem(text)
            text_item.setDefaultTextColor(text_color)
            text_item.setFont(QFont("Microsoft YaHei", 14, QFont.Bold))
            text_rect = text_item.boundingRect()
            text_item.setPos(
                button_pos[0] + button_pixmap.width() // 2 - text_rect.width() / 2,
                button_pos[1] + button_pixmap.height() // 2 - text_rect.height() / 2
            )
            text_item.setZValue(3)
            text_item.setAcceptHoverEvents(False)
            self.graphics_view.add_item(text_item)
            self.menu_button_items.append(text_item)

        self.graphics_view.show_items(menu_data.get("change", [[], None])[1])
        self.graphics_view.start_pending_animations()

    def _set_menu_buttons_visible(self, visible: bool):
        """隐藏/显示菜单按钮及其文本。打开设置时隐藏，关闭时恢复。
        隐藏前重置按钮的悬停状态，避免返回按钮时残留悬停样式（如白框）。
        """
        for it in self.menu_button_items:
            if not visible and isinstance(it, MenuButtonItem):
                it.reset_hover()
            if it.scene():
                it.setVisible(visible)

    def open_settings(self):
        """在游戏窗口中打开设置面板（同窗口覆盖层，非弹窗）。
        支持 JSON 自定义配置（预留），缺省时使用预设 UI。
        """
        if self.is_in_settings:
            return
        # 隐藏背后菜单按钮
        self._set_menu_buttons_visible(False)
        # 预留：读取 JSON 自定义配置（当前为 None -> 使用预设 UI）
        custom_config = load_settings_ui(self)
        # 分辨率选项：来自 JSON settings.window_size 列表（controller 已解析，index=0 为初始）；空则面板用内置列表
        res_options = list(self.controller.resolution_options) if self.controller.resolution_options else None
        # 语言选项：JSON settings.language 字典 {语言id: 语言名称}（兼容旧列表）
        # 面板仅支持其中 zh/en/ja，其余回落 en；名称用于面板显示（如"中文"）
        lang_cfg = self.controller.story_data.get("settings", {}).get("language", {"zh": "中文"}) if self.controller.story_data else {"zh": "中文"}
        lang_options = lang_cfg if isinstance(lang_cfg, dict) else list(lang_cfg)
        # 当前分辨率：全屏时用"全屏"标记，否则 WxH 字符串
        if self.isFullScreen():
            cur_res = FULLSCREEN_KEY
        else:
            cur_res = "{}x{}".format(self.controller.window_size[0], self.controller.window_size[1])
        panel = SettingsPanel(self.graphics_view.scene, config=custom_config,
                              language=self.controller.language,
                              current_resolution=cur_res,
                              resolution_options=res_options,
                              language_options=lang_options)
        # 居中显示（内部会创建底部按钮）
        scene_rect = self.graphics_view.sceneRect()
        if scene_rect.isNull():
            scene_rect = QRectF(0, 0, self.width(), self.height())
        panel.center_in_scene(scene_rect)
        self.graphics_view.scene.addItem(panel)
        # 绑定底部按钮行为 + 分辨率变更 + 语言变更
        self._bind_settings_buttons(panel)
        panel.set_resolution_handler(self._on_resolution_changed)
        panel.set_language_handler(self._on_language_changed)
        panel.fade_in()
        self.settings_panel = panel
        self.is_in_settings = True

    def _bind_settings_buttons(self, panel):
        """为设置面板底部按钮绑定点击行为。"""
        btn_reset = panel.button("reset")
        if btn_reset:
            btn_reset.set_click_handler(self._reset_settings)
        btn_back = panel.button("back")
        if btn_back:
            btn_back.set_click_handler(self.close_settings_panel)
        btn_quit = panel.button("quit")
        if btn_quit:
            btn_quit.set_click_handler(self._quit_game)

    def _reset_settings(self):
        """恢复默认设置：文字速度回默认（30ms/字）、语言回第一个。"""
        self.text_speed_delay = 30
        if self.text_display is not None:
            self.text_display.char_delay = 30
        lang_cfg = self.controller.story_data.get("settings", {}).get("language", {"zh": "中文"})
        if lang_cfg:
            default_lang = next(iter(lang_cfg)) if isinstance(lang_cfg, dict) else lang_cfg[0]
            self.controller.language = default_lang
            # 面板 UI 同步回默认语言
            if self.settings_panel is not None:
                self.settings_panel.set_language(self.controller.language)
            self._menu_language_dirty = True
        print("设置已恢复默认")

    def _quit_game(self):
        """退出游戏。"""
        print("退出游戏")
        QApplication.quit()

    def _on_resolution_changed(self, resolution):
        """分辨率变更：全屏标记 -> 全屏模式；"WxH" -> 窗口化并缩放。
        resolution: FULLSCREEN_KEY（全屏）或形如 "1280x720" 的字符串。
        """
        if resolution == FULLSCREEN_KEY:
            self.showFullScreen()
            print("已切换为全屏模式")
            return
        try:
            w, h = map(int, resolution.split("x"))
        except (ValueError, AttributeError):
            return
        self.controller.window_size = [w, h]
        if self.isFullScreen():
            # 从全屏退出：先恢复窗口，再延迟 resize（等 showNormal 生效）
            self.showNormal()
            from PySide6.QtCore import QTimer
            QTimer.singleShot(0, lambda: self.resize(w, h))
        else:
            self.resize(w, h)
        print(f"分辨率已切换: {resolution}")

    def _on_language_changed(self, lang):
        """语言变更：更新 controller.language，刷新设置面板 UI 文字，
        并标记菜单需要重建（关闭设置面板后按新语言重建菜单）。
        对话字幕按语言取词（display_dialog 已按 language 读取）。
        """
        if lang == self.controller.language:
            return
        self.controller.language = lang
        print(f"语言已切换: {lang}")
        # 刷新设置面板 UI（标题/按钮/标签文字随新语言变）
        if self.settings_panel is not None:
            self.settings_panel.set_language(lang)
        # 标记菜单需按新语言重建（关闭面板时执行）
        self._menu_language_dirty = True

    def close_settings_panel(self):
        """关闭设置面板：设置 UI 先渐变消失（100->0），再让菜单按钮渐变显示。"""
        if self.is_in_settings and self.settings_panel:
            panel = self.settings_panel
            self.settings_panel = None
            panel.fade_out(on_finished=lambda: self._finish_close_settings(panel))
            self.is_in_settings = False
        else:
            # 理论不可达；兜底直接恢复
            self._set_menu_buttons_visible(True)

    def _finish_close_settings(self, panel):
        """面板渐隐完成后：移除面板 + 菜单按钮渐显。"""
        if panel.scene():
            self.graphics_view.scene.removeItem(panel)
        if getattr(self, "_menu_language_dirty", False):
            # 语言已切换：按新语言重建整个菜单（标题图片/按钮文字）
            self._menu_language_dirty = False
            self.show_menu()
            return
        self._set_menu_buttons_fade_in()

    def _set_menu_buttons_fade_in(self, duration=500):
        """菜单按钮（含文本）渐变显示：透明度 0 -> 100。"""
        for it in self.menu_button_items:
            it.setVisible(True)
            effect = QGraphicsOpacityEffect()
            effect.setOpacity(0.0)
            it.setGraphicsEffect(effect)
            anim = QPropertyAnimation(effect, b"opacity")
            anim.setDuration(duration)
            anim.setStartValue(0.0)
            anim.setEndValue(1.0)
            anim.setEasingCurve(QEasingCurve.InOutQuad)
            anim.finished.connect(lambda a=anim, i=it: self._clear_menu_fade_effect(a, i))
            if not hasattr(self, "_menu_fade_anims"):
                self._menu_fade_anims = []
            self._menu_fade_anims.append(anim)
            anim.start()

    def _clear_menu_fade_effect(self, anim, item):
        """菜单按钮渐显完成后清理效果与动画引用。"""
        item.setGraphicsEffect(None)
        if hasattr(self, "_menu_fade_anims") and anim in self._menu_fade_anims:
            self._menu_fade_anims.remove(anim)

    def on_start_button_clicked(self):
        # 若设置面板打开，点击开始游戏时关闭它
        if self.is_in_settings:
            self.close_settings_panel()
        if self.controller.is_in_menu:
            print("开始按钮被点击，准备淡出菜单")
            self.fade_out_menu()

    def fade_out_menu(self):
        self.controller.is_in_menu = False
        black = QPixmap(self.controller.logical_size[0], self.controller.logical_size[1])
        black.fill(QColor(0, 0, 0))
        self.graphics_view.clear_items()
        self.graphics_view.add_item(black, [0, 0])
        self.graphics_view.show_items("gradient")
        self.graphics_view.start_pending_animations()
        QTimer.singleShot(1500, self.start_game_after_fade)

    def start_game_after_fade(self):
        self.graphics_view.clear_items()
        self.setup_dialog_area()
        self.controller.current_page = 1
        self.controller.current_scene_index = 0
        self.controller.play_current_page()
        self.controller.is_in_game = True

    def setup_dialog_area(self):
        # 清除旧对话框元素
        if self.chatbox_item:
            self.graphics_view.scene.removeItem(self.chatbox_item)
            self.chatbox_item = None
        # 清空代理列表
        for proxy in self.chatbox_widget_proxies:
            self.graphics_view.scene.removeItem(proxy)
        self.chatbox_widget_proxies.clear()
        # 清除旧底部菜单条
        if self.bottom_menu_item:
            self.graphics_view.scene.removeItem(self.bottom_menu_item)
            self.bottom_menu_item = None

        load_ui_settings_from_data(self)
        window_width, window_height = self.controller.logical_size
        chatbox_pos = [0, 0]

        # 底部菜单（default 预设）：对话框下方、紧贴窗口底部的色带；
        # 有底部菜单时对话框整体上移 menu_h，避免重叠
        menu_h = self._create_bottom_menu(window_width, window_height)

        # 创建对话框背景
        if self.ui_settings["chatbox_style"]:
            chatbox_path = self.controller.base_path / self.ui_settings["chatbox_style"]
            chatbox_pixmap = self.load_pixmap(str(chatbox_path))
            if chatbox_pixmap and not chatbox_pixmap.isNull():
                self.chatbox_item = QGraphicsPixmapItem(chatbox_pixmap)
                chatbox_pos = [
                    (window_width - chatbox_pixmap.width()) // 2,
                    window_height - menu_h - chatbox_pixmap.height()
                ]
                self.chatbox_item.setPos(chatbox_pos[0], chatbox_pos[1])
                self.chatbox_item.setZValue(10)
                self.graphics_view.scene.addItem(self.chatbox_item)
                print(f"使用自定义字幕框样式: {self.ui_settings['chatbox_style']}")
            else:
                print(f"无法加载自定义字幕框样式，使用默认样式")
                self.create_default_chatbox(window_width, window_height, menu_h)
        else:
            self.create_default_chatbox(window_width, window_height, menu_h)

        name_region = self.ui_settings["name_show_region"]
        name_pos = name_region[0]
        name_size = [name_region[1][0] - name_region[0][0], name_region[1][1] - name_region[0][1]]
        words_region = self.ui_settings["words_show_region"]
        words_pos = words_region[0]
        words_size = [words_region[1][0] - words_region[0][0], words_region[1][1] - words_region[0][1]]

        # 创建名字标签
        if not self.name_label:
            self.name_label = QLabel()
            self.name_label.setStyleSheet("""
                QLabel {
                    color: white;
                    background: transparent;
                    padding: 5px 10px;
                    border-radius: 5px;
                    font-size: 16px;
                    font-weight: bold;
                }
            """)
            self.name_label.setAlignment(Qt.AlignCenter)
            self.name_label.setFixedSize(name_size[0], name_size[1])
        else:
            self.name_label.setFixedSize(name_size[0], name_size[1])
        name_widget_proxy = self.graphics_view.scene.addWidget(self.name_label)
        name_widget_proxy.setZValue(12)
        name_widget_proxy.setPos(chatbox_pos[0] + name_pos[0], chatbox_pos[1] + name_pos[1])
        self.chatbox_widget_proxies.append(name_widget_proxy)

        # 创建文本显示控件
        if not self.text_display:
            self.text_display = TextDisplayWidget()
            self.text_display.char_delay = self.text_speed_delay
            self.text_display.setFixedSize(words_size[0], words_size[1])
            self.text_display.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        else:
            self.text_display.setFixedSize(words_size[0], words_size[1])
        text_widget_proxy = self.graphics_view.scene.addWidget(self.text_display)
        text_widget_proxy.setZValue(12)
        text_widget_proxy.setPos(chatbox_pos[0] + words_pos[0], chatbox_pos[1] + words_pos[1])
        self.chatbox_widget_proxies.append(text_widget_proxy)

    def create_default_chatbox(self, window_width: int, window_height: int, menu_h: int = 0):
        dialog_bg = QGraphicsRectItem(0, 0, 1280, 220)
        dialog_bg.setBrush(QBrush(QColor(0, 0, 0, 180)))
        dialog_bg.setPen(QPen(Qt.NoPen))
        dialog_bg.setPos((window_width - 1280) // 2, window_height - menu_h - 220)
        dialog_bg.setZValue(10)
        self.graphics_view.scene.addItem(dialog_bg)
        self.chatbox_item = dialog_bg

        name_bg = QGraphicsRectItem(0, 0, 200, 40)
        name_bg.setBrush(QBrush(QColor(0, 0, 0, 150)))
        name_bg.setPen(QPen(Qt.NoPen))
        name_bg.setPos((window_width - 1280) // 2 + 76, window_height - menu_h - 220 + 20)
        name_bg.setZValue(11)
        self.graphics_view.scene.addItem(name_bg)
        # 注意：默认样式的名字背景不是独立的 chatbox_item，但为了统一管理，我们只把主背景存为 chatbox_item
        # 名字背景将随主背景一同控制（如果需要更精细控制，可扩展）

    def _create_bottom_menu(self, window_width: int, window_height: int) -> int:
        """创建剧情底部菜单条（ui.bottom_menu 预设 default 模式）。
        宽度 100%，高度 = 逻辑高度 × bottom_menu.height_ratio（默认 0.03），
        填充色 = color（RGBA，默认 [0,0,0,255]）。紧贴窗口底部。
        返回菜单条高度（px）；未配置时返回 0。
        """
        bm = self.ui_settings.get("bottom_menu")
        if not bm or not isinstance(bm, dict):
            return 0
        if bm.get("mode", "default") != "default":
            return 0
        # 高度：默认 3% 逻辑高度；支持自定义比例
        ratio = float(bm.get("height_ratio", 0.03))
        menu_h = max(1, int(round(window_height * ratio)))
        # 颜色：默认 [0,0,0,255]（不透明黑）；RGBA 四元素
        color = bm.get("color", [0, 0, 0, 255])
        if len(color) < 3:
            color = [0, 0, 0, 255]
        r, g, b = color[0], color[1], color[2]
        a = color[3] if len(color) > 3 else 255
        item = QGraphicsRectItem(0, 0, window_width, menu_h)
        item.setBrush(QBrush(QColor(r, g, b, a)))
        item.setPen(QPen(Qt.NoPen))
        item.setPos(0, window_height - menu_h)
        item.setZValue(9)  # 低于对话框(z=10)，紧贴窗口底部
        self.graphics_view.scene.addItem(item)
        self.bottom_menu_item = item
        print(f"底部菜单(default): 高 {menu_h}px (ratio={ratio})，颜色 rgba({r},{g},{b},{a})")
        return menu_h

    def _stop_chatbox_animations_for(self, item):
        """停止并清理作用于指定 item（或其 effect）上的进行中 chatbox 动画。
        避免旧动画在新动画启动后继续改变透明度，导致显示/隐藏状态错乱。
        """
        if not hasattr(self, '_active_chatbox_animations'):
            self._active_chatbox_animations = []
            return
        keep = []
        for anim in self._active_chatbox_animations:
            target = anim.targetObject()
            # 动画作用于 item 的 graphicsEffect，target 是 effect；需比对 item 的 effect
            effect = item.graphicsEffect()
            if target is effect:
                anim.stop()
            else:
                keep.append(anim)
        self._active_chatbox_animations = keep

    def set_chatbox_visible(self, visible: bool, change_effect: Optional[str] = None):
        """
        设置对话框的可见性，支持转场效果。
        :param visible: True 显示，False 隐藏
        :param change_effect: 转场效果名称，如 "gradient"
        """
        print(f"[Chatbox] 设置可见性: visible={visible}, effect={change_effect}")
        items = []
        if self.chatbox_item and self.chatbox_item.scene():
            items.append(self.chatbox_item)
        else:
            print("[Chatbox] chatbox_item 无效或不在场景中")
        for proxy in self.chatbox_widget_proxies:
            if proxy.scene():
                items.append(proxy)
            else:
                print("[Chatbox] 代理控件不在场景中")
    
        if not items:
            print("[Chatbox] 没有可用的对话框项，无法更改可见性")
            return
    
        # 保存动画对象的列表，防止被垃圾回收
        if not hasattr(self, '_active_chatbox_animations'):
            self._active_chatbox_animations = []

        if change_effect == "gradient":
            for item in items:
                # 先停止该 item 上所有进行中的 chatbox 动画，避免旧动画继续改变透明度
                self._stop_chatbox_animations_for(item)

                effect = item.graphicsEffect()
                if effect is None or not isinstance(effect, QGraphicsOpacityEffect):
                    effect = QGraphicsOpacityEffect()
                    item.setGraphicsEffect(effect)
        
                # 如果是显示操作，先确保 item 可见（否则透明度动画无法显示）
                if visible:
                    item.setVisible(True)
        
                start_opacity = 0.0 if visible else 1.0
                end_opacity = 1.0 if visible else 0.0
        
                # 直接跳到起始透明度，再启动动画（保证从明确状态开始，不受旧动画残留值影响）
                effect.setOpacity(start_opacity)
        
                anim = QPropertyAnimation(effect, b"opacity")
                anim.setDuration(500)  # 您的当前时长设置
                anim.setStartValue(start_opacity)
                anim.setEndValue(end_opacity)
                anim.setEasingCurve(QEasingCurve.InOutQuad)
        
                def on_finished(item=item, vis=visible, anim=anim):
                    if not vis:
                        item.setVisible(False)
                    if anim in self._active_chatbox_animations:
                        self._active_chatbox_animations.remove(anim)
        
                anim.finished.connect(on_finished)
                self._active_chatbox_animations.append(anim)
                anim.start()
                print(f"[Chatbox] 启动渐变动画: item={item}, start={start_opacity}, end={end_opacity}")
        else:
            # 无转场效果，直接设置可见性并清除特效
            for item in items:
                item.setGraphicsEffect(None)
                item.setOpacity(1.0)
                item.setVisible(visible)
            print(f"[Chatbox] 直接设置可见性: {visible}")

    def display_dialog(self, content: dict):
        lang = self.controller.language or "zh"
        speaking_name = ""
        if "speaking_name" in content:
            char_id = content["speaking_name"]
            char_data = self.controller.story_data["story_and_position"]["character_and_motion"].get(char_id, {})
            names = char_data.get("name", {})
            speaking_name = names.get(lang) or names.get("zh", "")
        elif "speaking" in content:
            speak_map = content["speaking"]
            speaking_name = speak_map.get(lang) or speak_map.get("zh", "")
        self.name_label.setText(speaking_name)
        words_map = content["words"]
        words = words_map.get(lang) or words_map.get("zh", "")
        self.text_display.set_text(words, self.controller.on_text_display_complete)

    def load_pixmap(self, path: str) -> Optional[QPixmap]:
        return self.resource_manager.load_pixmap(path)

    def mousePressEvent(self, event):
        print("鼠标点击事件触发")
        if self.is_in_settings:
            # 设置面板打开时：背景菜单按钮已隐藏，仅区分面板内/外点击
            if self.settings_panel:
                scene_pos = self.graphics_view.mapToScene(event.position().toPoint())
                if self.settings_panel.contains(scene_pos):
                    # 点击面板内部：不关闭（后续供内嵌控件使用）
                    return
            # 点击面板外部：关闭设置
            self.close_settings_panel()
            return
        if self.controller.is_in_menu:
            super().mousePressEvent(event)
            return
        if event.button() == Qt.LeftButton:
            self.controller.handle_click()

    def keyPressEvent(self, event):
        if self.is_in_settings:
            # 设置面板打开时：Esc 关闭
            if event.key() == Qt.Key_Escape:
                self.close_settings_panel()
            super().keyPressEvent(event)
            return
        if self.controller.is_in_menu:
            super().keyPressEvent(event)
            return
        elif self.controller.is_in_game:
            if event.key() in (Qt.Key_Space, Qt.Key_Return, Qt.Key_Enter):
                print("空格键或回车键按下")
                self.controller.handle_click()
            elif event.key() == Qt.Key_A:
                self.controller.toggle_auto_play()
            elif event.key() == Qt.Key_F2:
                self.controller.save_game()
            elif event.key() == Qt.Key_F3:
                self.controller.load_save()
            else:
                super().keyPressEvent(event)