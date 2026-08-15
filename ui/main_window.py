import os
import pickle
from pathlib import Path
from typing import Optional

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFileDialog,
    QGraphicsTextItem, QFrame, QGraphicsRectItem, QGraphicsPixmapItem, QApplication,
    QGraphicsOpacityEffect, QComboBox, QSlider, QGraphicsPathItem
)
from PySide6.QtCore import Qt, QTimer, QPropertyAnimation, QEasingCurve, QRectF
from PySide6.QtGui import QPixmap, QColor, QFont, QBrush, QPen, QTextCursor, QFontMetrics

from core.game_controller import GameController
from ui.graphics_view import GraphicsView, MenuButtonItem
from ui.widgets import TextDisplayWidget
from ui.settings_panel import SettingsPanel, SettingsButtonItem, BacklogPanel, SavePanel, FULLSCREEN_KEY, ConfirmDialog
from data_management.resource_manager import ResourceManager
from data_management.story_parser import load_ui_settings_from_data
from data_management.save_load_system import (save_settings_file, load_settings_file,
                                              get_this_story_saves_new_to_old)


# 设置面板的 JSON 自定义配置读取（预留接口，后续开发）
def load_settings_ui(self):
    """读取设置界面配置，返回面板配置 dict。
    优先读 menu_pos.settings 第 3 项（ui_mode 等）；分辨率选项已迁至 settings.window_size 列表。
    兼容旧字段 settings.ui（或 settings_ui）。
    ui_mode: "default"=预设界面（当前开发中的面板）；"custom"=JSON 自定义（规划中，暂未实现，同样回落预设）。
    default 模式下，index=2 的 dict 可提供：color（面板背景色 RGBA）、text_color（文字颜色 RGB，
    不含按钮文字）、button_color（按钮底色 RGBA，按钮文字按亮度自动切黑白）。
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
        # default 预设界面：透传 color/text_color/button_color（若配置），其余项走预设默认
        return dict(cfg)
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
        self.bottom_menu_buttons = []  # 底部菜单条上的按钮（按钮+文字 item），语言切换时重建
        self.start_button = None
        self.title_item = None
        self.menu_bg_item = None
        self.graphics_view = None
        self.settings_panel = None  # 当前设置面板（场景内）
        self.is_in_settings = False  # 是否正在设置界面中
        self.backlog_panel = None  # 当前日志面板（场景内）
        self.is_in_backlog = False  # 是否正在日志界面中
        self.save_panel = None  # 当前保存面板（场景内）
        self.is_in_save = False  # 是否正在保存界面中
        self.confirm_dialog = None  # 当前确认框（继续游戏等操作前）
        # "⊙"隐藏开关：隐藏对话框+底部菜单，任意点击恢复
        self._ui_hidden = False
        self._ui_hidden_chatbox_was = True  # 进入隐藏时对话框可见性（恢复用）
        self._auto_play_paused = False  # 打开设置时是否暂停了自动播放（关闭后恢复）
        self.menu_button_items = []  # 菜单按钮及其文本 item（打开设置时隐藏）
        self.settings_ui_config = {}  # 设置界面配置（menu_pos.settings 第 3 项：ui_mode/resolution 等）

        self.setup_ui()
        self.load_story_file()

    def apply_transition_color(self, color):
        """应用 settings.transition_color 为窗口/视图底色（默认黑色，转场时显示）。"""
        rgb = ",".join(str(int(c)) for c in color[:3])
        self.setStyleSheet(f"background-color: rgb({rgb});")
        if self.graphics_view:
            self.graphics_view.set_background_color(color)

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
            self._apply_saved_settings()
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

    def _apply_saved_settings(self):
        """游戏开始时应用已保存的设置（saves/settings_<标题>_<识别码>.gpsetting）。
        无此文件 -> 按默认值启动（apply_settings 已设定）。
        有则覆盖分辨率/语言；文件里无效的设置项值回落默认。
        """
        data = load_settings_file(self.controller)
        if not data:
            return
        # 语言：文件 data[3]，验证是否在 JSON settings.language 可选范围内
        lang_cfg = self.controller.story_data.get("settings", {}).get("language", {})
        lang_options = list(lang_cfg) if isinstance(lang_cfg, dict) else list(lang_cfg)
        saved_lang = data[3]
        if saved_lang and saved_lang in lang_options:
            self.controller.language = saved_lang
            print(f"设置文件: 应用语言 {saved_lang}")
        else:
            print(f"设置文件: 语言 {saved_lang!r} 无效，回落默认 {self.controller.language}")
        # 分辨率：文件 data[2]，"WxH" 或 "fullscreen"
        saved_res = data[2]
        if saved_res == "fullscreen":
            self.showFullScreen()
            print("设置文件: 应用全屏")
        elif saved_res and "x" in saved_res:
            try:
                w, h = map(int, saved_res.split("x"))
            except (ValueError, AttributeError):
                w = h = None
            if w and h and self.controller.resolution_options:
                # 仅在 JSON 可选分辨率列表内才应用（无效回落默认）
                if saved_res in self.controller.resolution_options:
                    self.controller.window_size = [w, h]
                    self.resize(w, h)
                    print(f"设置文件: 应用分辨率 {saved_res}")
                else:
                    print(f"设置文件: 分辨率 {saved_res!r} 不在可选列表，回落默认")
            elif w and h:
                # 无分辨率选项列表时：直接应用（窗口尺寸按 WxH）
                self.controller.window_size = [w, h]
                self.resize(w, h)
                print(f"设置文件: 应用分辨率 {saved_res}")
            else:
                print(f"设置文件: 分辨率 {saved_res!r} 无效，回落默认")
        else:
            print(f"设置文件: 分辨率 {saved_res!r} 无效，回落默认")

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
            "load": self.open_load_panel,
            "qload": self._on_qload_button_clicked,  # 快速加载：功能开发中
            "settings": self.open_settings,
            "quit": self._quit_game,
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
            text_item.setTextInteractionFlags(Qt.NoTextInteraction)
            text_item.setCursor(Qt.ArrowCursor)  # 悬停保持箭头，避免 IBeam
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
        if self.is_in_backlog:
            return
        # 隐藏背后菜单按钮（主菜单按钮 + 剧情底部按钮）
        self._set_menu_buttons_visible(False)
        self._set_bottom_menu_visible(False)
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
        # 打开设置面板：暂停自动播放/快进（返回剧情后恢复）
        self._auto_play_paused = getattr(self.controller, "auto_play", False)
        if self.controller.auto_play:
            self.controller.auto_play = False
            print("设置打开：暂停自动播放")
            self._update_auto_play_icon()
        if getattr(self.controller, "skip_mode", False):
            self.controller.skip_timer.stop()
            print("设置打开：暂停快进")

    def _bind_settings_buttons(self, panel):
        """为设置面板底部按钮绑定点击行为。
        用 set_button_handler 注册：语言切换/重置重建按钮后自动重绑，不会丢 handler。
        """
        panel.set_button_handler("reset", self._reset_settings)
        panel.set_button_handler("back", self.close_settings_panel)
        panel.set_button_handler("quit", self._back_to_menu)

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

    def _back_to_menu(self):
        """返回主菜单：关闭设置面板、停止自动播放/快进、重置剧情状态，
        重建并显示开始菜单（含开始游戏按钮）。
        注意：不能在按钮点击回调里同步 removeItem 面板（PySide6 硬崩溃），
        全部清理延后到事件循环空闲（QTimer.singleShot 0）再执行。
        """
        print("返回主菜单")
        # 立即标记：设置/保存已关闭（防止期间再操作）
        self.is_in_settings = False
        self.settings_panel = None
        self.is_in_save = False
        self.save_panel = None
        # 先停止自动播放/快进定时器（安全，不碰场景）
        if self.controller.skip_mode:
            self.controller.skip_mode = False
            self.controller.skip_timer.stop()
        if self.controller.auto_play:
            self.controller.auto_play = False
        self._auto_play_paused = False
        # 重置剧情状态
        self.controller.is_in_game = False
        self.controller.is_waiting_for_next_page = False
        self.controller.audio_timer.stop()
        self.controller.current_page = 1
        self.controller.current_scene_index = 0
        # 退出剧情时清空日志（回到主菜单即丢弃本次对话记录）
        self.controller.backlog_entries = []
        self.controller.backlog_start_page = 1
        # 注意：text_display/name_label 等不在同步阶段置 None，
        # 由 _clear_scene_and_show_menu 停掉逐字 timer 后再清引用。
        # 延后到事件循环空闲：清空场景所有 item（含设置面板/chatbox/proxy/底部
        # 菜单），再重建主菜单。避免在按钮点击回调栈内删除面板导致硬崩溃。
        from PySide6.QtCore import QTimer
        QTimer.singleShot(0, self._clear_scene_and_show_menu)

    def _clear_scene_and_show_menu(self):
        """（事件循环空闲时）清空场景并显示主菜单。"""
        # 先停掉逐字 timer 并断开信号：scene.clear() 删除 QGraphicsProxyWidget 时
        # 会销毁内嵌 QTextEdit；若 timer 还在跑，timeout 信号会触发已失效 Python
        # 回调导致硬崩溃（0xC0000409）。
        if self.text_display is not None:
            try:
                self.text_display.timer.stop()
                self.text_display.timer.timeout.disconnect()
            except Exception:
                pass
        self.graphics_view.scene.clear()
        self.graphics_view.itemList.clear()
        self.graphics_view.character_items.clear()
        self.graphics_view.background_item = None
        # 清空对话框 widget 引用（C++ 对象已被 scene.clear 销毁）
        self.name_label = None
        self.text_display = None
        self.chatbox_item = None
        self.bottom_menu_item = None
        self.chatbox_widget_proxies.clear()
        self.bottom_menu_buttons = []
        self.menu_button_items = []
        self.menu_bg_item = None
        self.show_menu()

    def _quit_game(self):
        """退出游戏：先弹确认框（确认 -> 真正退出；取消 -> 关闭）。"""
        print("退出游戏：弹出确认框")
        self._open_confirm_dialog(
            question={
                "zh": "确认退出？",
                "en": "Quit?",
                "ja": "終了しますか？",
            },
            on_confirm=self._do_quit,
        )

    def _do_quit(self):
        """确认退出：关闭确认框后真正退出。"""
        print("退出游戏：确认")
        from PySide6.QtCore import QTimer
        dlg = getattr(self, "confirm_dialog", None)
        if dlg:
            self.confirm_dialog = None
            QTimer.singleShot(0, lambda: self._remove_qload_dialog(dlg))
        QApplication.quit()

    def _open_confirm_dialog(self, question=None, on_confirm=None, on_cancel=None):
        """通用确认框：读取 ui.confirm_ui 配置，创建遮罩 + 确认 UI。

        question: None（默认"确认？"）或多语言 dict / 单语言 str
        on_confirm/on_cancel: 确认/取消回调（取消缺省为关闭确认框）
        """
        # 面板互斥：已有其他面板打开时不重复叠加
        if getattr(self, "is_in_settings", False) or getattr(self, "is_in_save", False) \
                or getattr(self, "is_in_backlog", False) or getattr(self, "confirm_dialog", None):
            return
        # 读取确认 UI 配置（ui.confirm_ui 节点）
        cfg = None
        try:
            ui_data = self.controller.story_data.get("ui", {})
            cu = ui_data.get("confirm_ui") if isinstance(ui_data, dict) else None
            if isinstance(cu, dict):
                cfg = dict(cu)
        except Exception:
            pass
        scene_rect = self.graphics_view.sceneRect()
        if scene_rect.isNull():
            scene_rect = QRectF(0, 0, self.width(), self.height())
        dlg = ConfirmDialog(
            self.graphics_view.scene,
            language=self.controller.language or "zh",
            config=cfg,
            transition_color=self.controller.transition_color,
            on_cancel=on_cancel or self._close_qload_confirm,
            on_confirm=on_confirm,
            question=question,
        )
        dlg.center_in_scene(scene_rect)
        dlg.fade_in()
        self.confirm_dialog = dlg
        print("确认框已打开")

    def _on_bottom_qload_clicked(self):
        """底部菜单 Q.Load 按钮：与主菜单"继续游戏"一致，弹确认框，确认后读最新档。

        剧情中读档由 load_save 内部完成（restore_snapshot + play_current_page），
        读档后恢复底部菜单可见。
        """
        print("底部 Q.Load：弹出确认框")
        # 无存档时不弹确认框，直接无反应
        if not get_this_story_saves_new_to_old(self.controller):
            return
        self._open_confirm_dialog(on_confirm=self._confirm_qload)

    def _on_qload_button_clicked(self):
        """主菜单"继续游戏/快速加载"按钮：弹出确认框（遮罩 + 确认 UI）。
        确认 -> 读最新存档（同 F3）；取消 -> 关闭确认框回到主菜单。
        确认框配置来源：ui.confirm_ui 节点（ui_mode="default" 预设 UI）。
        """
        # 无存档时不弹确认框，直接无反应
        if not get_this_story_saves_new_to_old(self.controller):
            return
        self._open_confirm_dialog(on_confirm=self._confirm_qload)

    def _close_qload_confirm(self):
        """取消：关闭确认框（移除遮罩+确认框），回到主菜单。
        注意：不能在按钮点击回调里同步 removeItem（PySide6 硬崩溃），
        延后到事件循环空闲执行。
        """
        dlg = getattr(self, "confirm_dialog", None)
        if dlg:
            self.confirm_dialog = None
            from PySide6.QtCore import QTimer
            QTimer.singleShot(0, lambda: self._remove_qload_dialog(dlg))
        print("继续游戏：已取消")

    def _confirm_qload(self):
        """确认：关闭确认框并读最新存档（同 F3：QSAVE 恒排最前）。
        主菜单读档路径与加载面板一致：fade 转场后 _show_loaded_scene。
        """
        dlg = getattr(self, "confirm_dialog", None)
        if dlg:
            self.confirm_dialog = None
            from PySide6.QtCore import QTimer
            QTimer.singleShot(0, lambda: self._remove_qload_dialog(dlg))
        print("继续游戏：确认，读取最新存档")
        ok = self.controller.load_save()
        if not ok:
            print("继续游戏：没有可用存档")
            return
        if self.controller.is_in_menu:
            # 主菜单读档：fade 转场后进入剧情（与加载面板一致）
            self.controller.is_in_menu = False
            tc = self.controller.transition_color
            if not tc:
                tc = [0, 0, 0]
            w, h = self.controller.logical_size
            color_block = QPixmap(w, h)
            color_block.fill(QColor(tc[0], tc[1], tc[2]))
            self.graphics_view.clear_items()
            self.graphics_view.add_item(color_block, [0, 0])
            self.graphics_view.show_items("gradient")
            self.graphics_view.start_pending_animations()
            QTimer.singleShot(1500, lambda: self._show_loaded_scene())
        else:
            self._set_bottom_menu_visible(True)

    def _remove_qload_dialog(self, dlg):
        """（事件循环空闲时）移除确认框。"""
        try:
            dlg.remove_from_scene()
        except Exception:
            pass

    def _on_resolution_changed(self, resolution):
        """分辨率变更：全屏标记 -> 全屏模式；"WxH" -> 窗口化并缩放。
        resolution: FULLSCREEN_KEY（全屏）或形如 "1280x720" 的字符串。
        """
        if resolution == FULLSCREEN_KEY:
            self.showFullScreen()
            print("已切换为全屏模式")
            save_settings_file(self.controller)
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
        save_settings_file(self.controller)

    def _on_language_changed(self, lang):
        """语言变更：更新 controller.language，刷新设置面板 UI 文字，
        并标记菜单需要重建（关闭设置面板后按新语言重建菜单）。
        对话字幕按语言取词（display_dialog 已按 language 读取）。
        """
        if lang == self.controller.language:
            return
        self.controller.language = lang
        print(f"语言已切换: {lang}")
        save_settings_file(self.controller)
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
        """面板渐隐完成后：移除面板 + 菜单按钮渐显。
        语言切换后：菜单中重建主菜单；剧情中刷新底部菜单按钮文字（不跳转）。
        返回剧情后：恢复打开设置前暂停的自动播放/快进。
        """
        if panel.scene():
            self.graphics_view.scene.removeItem(panel)
        # 恢复设置打开前暂停的自动播放/快进（仅当仍在剧情中）
        if self.controller.is_in_game and not self.controller.is_in_menu:
            if getattr(self, "_auto_play_paused", False) and not self.controller.auto_play:
                self.controller.auto_play = True
                print("设置关闭：恢复自动播放")
                # 若正停在等待下一页：立即推进（与 toggle_auto_play 开启时一致）
                if self.controller.is_waiting_for_next_page:
                    self.controller.play_current_page()
                # 若当前场景文本+音频已完成但被设置暂停卡住：恢复后立即推进
                elif self.controller.is_text_finished and self.controller.is_audio_finished:
                    self.controller.advance_to_next_scene()
                self._update_auto_play_icon()
            if getattr(self.controller, "skip_mode", False) and not self.controller.skip_timer.isActive():
                self.controller.skip_timer.start()
                print("设置关闭：恢复快进")
        self._auto_play_paused = False
        # 恢复底部菜单按钮可见（面板关闭）；若另一面板已打开则保持隐藏
        if not self.is_in_settings and not self.is_in_backlog:
            self._set_bottom_menu_visible(True)
            if self.controller.is_in_menu:
                self._set_menu_buttons_visible(True)
        if getattr(self, "_menu_language_dirty", False):
            # 语言已切换
            self._menu_language_dirty = False
            if self.controller.is_in_menu:
                # 主菜单：按新语言重建整个菜单（标题图片/按钮文字）
                self.show_menu()
            else:
                # 剧情中：刷新底部菜单按钮文字（若存在）
                self._refresh_bottom_menu_buttons()
                # 重新渲染当前对话（名称/字幕按新语言取词，直接显示全文不重播逐字）
                self._refresh_current_dialog()
            return
        self._set_menu_buttons_fade_in()

    def _refresh_bottom_menu_buttons(self):
        """按当前 controller.language 重建底部菜单按钮文字（剧情中语言切换后）。"""
        if not self.bottom_menu_buttons:
            return
        bm = self.ui_settings.get("bottom_menu")
        if not bm:
            return
        # 复用创建逻辑：清除并重建（按钮位置不变）
        window_width, window_height = self.controller.logical_size
        ratio = float(bm.get("height_ratio", 0.03))
        menu_h = max(1, int(round(window_height * ratio)))
        extend = int(bm.get("extend", 50))
        self._create_bottom_menu_buttons(window_width, window_height, menu_h, extend)

    def toggle_auto_play_button(self):
        """底部菜单自动播放开关：切换状态并更新图标（关 ▷ / 开 ▶）。"""
        self.controller.toggle_auto_play()
        self._update_auto_play_icon()

    def _update_auto_play_icon(self):
        """按当前 auto_play 状态更新底部菜单自动播放按钮图标。"""
        icon = "▶" if getattr(self.controller, "auto_play", False) else "▷"
        for it in self.bottom_menu_buttons:
            if isinstance(it, QGraphicsTextItem) and it.toPlainText() in ("▷", "▶"):
                it.setPlainText(icon)
                return

    def toggle_skip_button(self):
        """底部菜单快进开关：切换状态并更新图标（关 ▷▷ / 开 ▶▶）。"""
        self.controller.toggle_skip_mode()
        self._update_skip_icon()

    def _translate_backlog_entries(self, entries):
        """把日志原始条目按当前语言翻译为 [(说话人文本, 台词文本), ...]。
        条目格式：
          (speaker_key, words_map)
            speaker_key: ("char", char_id) 角色标识 或 ("map", speak_dict) 说话人字典
            words_map: 台词多语言字典
        兼容旧格式 (已翻译文本, 已翻译文本) 直接透传。
        """
        lang = self.controller.language or "zh"
        result = []
        for entry in entries:
            try:
                speaker_key, words = entry
            except (ValueError, TypeError):
                continue
            # 说话人
            if isinstance(speaker_key, tuple) and len(speaker_key) == 2 and speaker_key[0] == "char":
                char_id = speaker_key[1]
                char_data = {}
                try:
                    char_data = self.controller.story_data["story_and_position"]["character_and_motion"].get(char_id, {})
                except Exception:
                    pass
                names = char_data.get("name", {})
                speaker = names.get(lang) or names.get("zh", "") or ""
            elif isinstance(speaker_key, tuple) and len(speaker_key) == 2 and speaker_key[0] == "map":
                speak_map = speaker_key[1]
                speaker = speak_map.get(lang) or speak_map.get("zh", "") or next(iter(speak_map.values()), "")
            else:
                # 兼容旧格式：已是翻译后文本
                speaker = speaker_key if isinstance(speaker_key, str) else ""
            # 台词
            if isinstance(words, dict):
                text = words.get(lang) or words.get("zh", "") or next(iter(words.values()), "")
            else:
                text = words if isinstance(words, str) else ""
            result.append((speaker, text))
        return result

    def toggle_backlog_button(self):
        """底部菜单日志/Backlog 按钮：打开日志面板（与设置面板同尺寸同形状，颜色取 backlog_bgcolor）。"""
        if self.is_in_backlog:
            return
        if self.is_in_settings:
            return
        # 隐藏剧情底部菜单按钮（面板打开期间不可点击）
        self._set_bottom_menu_visible(False)
        # 读取 backlog_bgcolor（RGBA 列表），缺省白色半透明
        bg_color = [255, 255, 255, 200]
        try:
            bm = (self.ui_settings or {}).get("bottom_menu") or {}
            if "backlog_bgcolor" in bm:
                bg_color = list(bm["backlog_bgcolor"])
        except Exception:
            pass
        panel = BacklogPanel(self.graphics_view.scene, bg_color=bg_color,
                            language=self.controller.language or "zh",
                            on_back=self.close_backlog_panel)
        scene_rect = self.graphics_view.sceneRect()
        if scene_rect.isNull():
            scene_rect = QRectF(0, 0, self.width(), self.height())
        panel.center_in_scene(scene_rect)
        # 填入日志：按当前语言翻译全部条目（存的是原始多语言数据，显示时统一翻译，
        # 避免中途切语言导致新旧日志语言混排）
        panel.set_entries(self._translate_backlog_entries(getattr(self.controller, "backlog_entries", [])))
        self.graphics_view.scene.addItem(panel)
        panel.fade_in()
        self.backlog_panel = panel
        self.is_in_backlog = True
        # 打开日志面板：暂停自动播放/快进（返回剧情后恢复）
        self._auto_play_paused = getattr(self.controller, "auto_play", False)
        if self.controller.auto_play:
            self.controller.auto_play = False
            print("日志打开：暂停自动播放")
            self._update_auto_play_icon()
        if getattr(self.controller, "skip_mode", False):
            self.controller.skip_timer.stop()
            print("日志打开：暂停快进")
        print("日志面板已打开")

    def close_backlog_panel(self):
        """关闭日志面板：先渐隐（100->0），再移除。"""
        if self.is_in_backlog and self.backlog_panel:
            panel = self.backlog_panel
            self.backlog_panel = None
            panel.fade_out(on_finished=lambda: self._finish_close_backlog(panel))
            self.is_in_backlog = False

    def _finish_close_backlog(self, panel):
        """日志面板渐隐完成后：移除面板（含返回按钮/文字）+ 恢复暂停的自动播放/快进。"""
        panel.remove_from_scene()
        # 恢复底部菜单按钮可见（面板关闭）；若另一面板已打开则保持隐藏
        if not self.is_in_settings and not self.is_in_backlog:
            self._set_bottom_menu_visible(True)
        if self.controller.is_in_game and not self.controller.is_in_menu:
            if getattr(self, "_auto_play_paused", False) and not self.controller.auto_play:
                self.controller.auto_play = True
                print("日志关闭：恢复自动播放")
                if self.controller.is_waiting_for_next_page:
                    self.controller.play_current_page()
                elif self.controller.is_text_finished and self.controller.is_audio_finished:
                    self.controller.advance_to_next_scene()
                self._update_auto_play_icon()
            if getattr(self.controller, "skip_mode", False) and not self.controller.skip_timer.isActive():
                self.controller.skip_timer.start()
                print("日志关闭：恢复快进")
        self._auto_play_paused = False


    def _load_saves_data(self, page=0):
        """读取本故事 8 个格子的存档 data（按格子 index 顺序，无存档=None）。
        快速存档（QSAVE，index=-1）不显示在保存面板。
        """
        import re as _re
        saves_data = []
        save_files = []
        max_slot_index = -1
        slot_map = {}
        base = self._slot_fname_base()
        try:
            for fname in os.listdir("saves"):
                m = _re.search(r"_SLOT(\d+)\.gpsave$", fname)
                if not m:
                    continue
                if not fname.startswith(base):
                    continue
                idx = int(m.group(1))
                slot_map[idx] = fname
                if idx > max_slot_index:
                    max_slot_index = idx
        except OSError:
            pass
        for local in range(8):
            gidx = page * 8 + local
            fname = slot_map.get(gidx)
            if fname:
                data = None
                try:
                    with open(os.path.join("saves", fname), "rb") as f:
                        data = pickle.load(f)
                except Exception:
                    data = None
                saves_data.append(data if isinstance(data, list) and len(data) >= 10 else None)
                save_files.append(fname)
            else:
                saves_data.append(None)
                save_files.append(None)
        return saves_data, save_files, max_slot_index

    def _slot_fname_base(self):
        """存档文件名的标题_识别码 前缀（与 save_load_system 命名一致）。"""
        settings = (self.controller.story_data or {}).get("settings", {})
        story_name = settings.get("window_title", "GalPie").replace(" ", "-").replace("_", "+")
        story_id = settings.get("identify_code", "").replace(" ", "-").replace("_", "+")
        return f"{story_name}_{story_id}"

    def open_load_panel(self):
        """打开加载面板（主菜单/剧情中均可）：布局与保存面板一致，mode=load。
        点有存档格子 -> 确认读取；空格无操作；不显示垃圾桶；无加号按钮。
        配置来源：menu.menu_pos.load 的第 3 项 dict。"""
        if self.is_in_save or self.is_in_settings or self.is_in_backlog:
            return
        self._set_menu_buttons_visible(False)
        self._set_bottom_menu_visible(False)
        save_cfg = None
        try:
            # 加载界面配置来源：menu.menu_pos.load 的第 3 项 dict
            menu_data = self.controller.story_data.get("menu", {})
            mp = menu_data.get("menu_pos", {}) if isinstance(menu_data, dict) else {}
            _load_cfg = mp.get("load")
            if isinstance(_load_cfg, list) and len(_load_cfg) >= 3 and isinstance(_load_cfg[2], dict):
                save_cfg = dict(_load_cfg[2])
        except Exception:
            pass
        bg_color = [255, 255, 255, 217]
        if save_cfg and isinstance(save_cfg.get("color"), (list, tuple)) and len(save_cfg["color"]) >= 3:
            bg_color = list(save_cfg["color"])
            if len(bg_color) == 3:
                bg_color.append(217)
        saves_color = [185, 122, 87, 255]
        if save_cfg and isinstance(save_cfg.get("saves_color"), (list, tuple)) and len(save_cfg["saves_color"]) >= 3:
            saves_color = list(save_cfg["saves_color"])
            if len(saves_color) == 3:
                saves_color.append(255)
        text_color = [30, 30, 30]
        if save_cfg and isinstance(save_cfg.get("text_color"), (list, tuple)) and len(save_cfg["text_color"]) >= 3:
            text_color = list(save_cfg["text_color"])
        saves_text_color = [255, 255, 255]
        if save_cfg and isinstance(save_cfg.get("saves_text_color"), (list, tuple)) and len(save_cfg["saves_text_color"]) >= 3:
            saves_text_color = list(save_cfg["saves_text_color"])
        button_color = [0, 0, 0, 255]
        if save_cfg and isinstance(save_cfg.get("button_color"), (list, tuple)) and len(save_cfg["button_color"]) >= 3:
            button_color = list(save_cfg["button_color"])
            if len(button_color) == 3:
                button_color.append(255)
        panel = SavePanel(self.graphics_view.scene, bg_color=bg_color,
                          language=self.controller.language or "zh",
                          on_back=self.close_save_panel,
                          saves_color=saves_color,
                          text_color=text_color,
                          saves_text_color=saves_text_color,
                          button_color=button_color,
                          on_main_menu=self._back_to_menu,
                          mode="load")
        scene_rect = self.graphics_view.sceneRect()
        if scene_rect.isNull():
            scene_rect = QRectF(0, 0, self.width(), self.height())
        panel.center_in_scene(scene_rect)
        self.graphics_view.scene.addItem(panel)
        panel.fade_in()
        self.save_panel = panel
        self.is_in_save = True
        saves_data, save_files, max_slot_index = self._load_saves_data(0)
        panel.set_total_pages((max_slot_index // 8) + 1)
        panel.set_saves_data(saves_data, save_files)
        panel.set_refresh_callback(self._refresh_save_panel)
        panel.set_load_slot_callback(self._on_load_from_slot)
        panel.set_delete_slot_callback(self._on_delete_slot)
        panel.set_overwrite_slot_callback(self._on_overwrite_slot)
        print("加载面板已打开")
    def _on_load_from_slot(self, slot_index):
        """Load panel slot click: load save. From main menu, fade to transition
        color block first, then fade into story (same as start game)."""
        fname = self._slot_fname(slot_index)
        ok = self.controller.load_save(fname)
        if not ok:
            print(f"load failed: {fname}")
            return
        print(f"save loaded: {fname}")
        # close load panel
        if self.save_panel:
            panel = self.save_panel
            self.save_panel = None
            self.is_in_save = False
            try:
                panel.remove_from_scene()
            except Exception:
                pass
        if self.controller.is_in_menu:
            # from main menu: fade to transition color block, then into story
            self.controller.is_in_menu = False
            tc = self.controller.transition_color
            if not tc:
                tc = [0, 0, 0]
            w, h = self.controller.logical_size
            color_block = QPixmap(w, h)
            color_block.fill(QColor(tc[0], tc[1], tc[2]))
            self.graphics_view.clear_items()
            self.graphics_view.add_item(color_block, [0, 0])
            self.graphics_view.show_items("gradient")
            self.graphics_view.start_pending_animations()
            QTimer.singleShot(1500, lambda: self._show_loaded_scene())
        else:
            self._set_bottom_menu_visible(True)

    def _show_loaded_scene(self):
        """After fade: build dialog area and restore snapshot画面, then play current page once."""
        self.graphics_view.clear_items()
        self.setup_dialog_area()
        self.controller.is_in_game = True
        # 恢复读档快照画面（load_save 时已存到 last_loaded_snapshot，
        # 此处重建 dialog area 后重新应用，避免 clear_items 清掉画面）
        snap = getattr(self.controller, "last_loaded_snapshot", None)
        if snap:
            self.controller.restore_snapshot(snap)
        self.controller.play_current_page()
    def _slot_fname(self, slot_index):
        """构造指定格子的存档文件名（无存档也可能不存在）。"""
        settings = self.controller.story_data.get("settings", {"window_title": "GalPie", "identify_code": ""})
        story_name = settings.get("window_title", "GalPie").replace(" ", "-").replace("_", "+")
        story_id = settings.get("identify_code", "").replace(" ", "-").replace("_", "+")
        return f"{story_name}_{story_id}_SLOT{slot_index}.gpsave"

    def open_save_panel(self):
        """打开保存面板（同窗口内覆盖层，与设置面板同尺寸同形状，颜色取 bottom_menu.save.color）。
        ui_mode="default" 使用预设 UI（当前实现）；"custom" 规划中暂回落预设。
        """
        if self.is_in_save:
            return
        if self.is_in_settings or self.is_in_backlog:
            return
        # 隐藏底部菜单按钮（面板打开期间不可点击）
        self._set_menu_buttons_visible(False)
        self._set_bottom_menu_visible(False)
        # 读取 bottom_menu.save 配置（ui_mode/color 等）
        save_cfg = None
        try:
            bm = (self.ui_settings or {}).get("bottom_menu") or {}
            if isinstance(bm, dict):
                _s = bm.get("save")
                if isinstance(_s, dict):
                    save_cfg = dict(_s)
        except Exception:
            pass
        # save.color -> 面板背景色（RGBA），缺省白色半透明 [255,255,255,217]
        bg_color = [255, 255, 255, 217]
        if save_cfg and isinstance(save_cfg.get("color"), (list, tuple)) and len(save_cfg["color"]) >= 3:
            bg_color = list(save_cfg["color"])
            if len(bg_color) == 3:
                bg_color.append(217)
        # save.saves_color -> 存档槽位按钮底色（RGBA），缺省 [185,122,87,255]
        saves_color = [185, 122, 87, 255]
        if save_cfg and isinstance(save_cfg.get("saves_color"), (list, tuple)) and len(save_cfg["saves_color"]) >= 3:
            saves_color = list(save_cfg["saves_color"])
            if len(saves_color) == 3:
                saves_color.append(255)
        # save.text_color -> 面板静态文字颜色（左上角标题等），缺省 [30,30,30]
        text_color = [30, 30, 30]
        if save_cfg and isinstance(save_cfg.get("text_color"), (list, tuple)) and len(save_cfg["text_color"]) >= 3:
            text_color = list(save_cfg["text_color"])
        # save.saves_text_color -> 存档格文字颜色（台词/日期/垃圾桶/SAVE），缺省 [255,255,255]
        saves_text_color = [255, 255, 255]
        if save_cfg and isinstance(save_cfg.get("saves_text_color"), (list, tuple)) and len(save_cfg["saves_text_color"]) >= 3:
            saves_text_color = list(save_cfg["saves_text_color"])
        # save.button_color -> 底部工具栏按钮底色（RGBA），缺省 [0,0,0,255]
        button_color = [0, 0, 0, 255]
        if save_cfg and isinstance(save_cfg.get("button_color"), (list, tuple)) and len(save_cfg["button_color"]) >= 3:
            button_color = list(save_cfg["button_color"])
            if len(button_color) == 3:
                button_color.append(255)
        panel = SavePanel(self.graphics_view.scene, bg_color=bg_color,
                          language=self.controller.language or "zh",
                          on_back=self.close_save_panel,
                          saves_color=saves_color,
                          text_color=text_color,
                          saves_text_color=saves_text_color,
                          button_color=button_color,
                          on_main_menu=self._back_to_menu)
        scene_rect = self.graphics_view.sceneRect()
        if scene_rect.isNull():
            scene_rect = QRectF(0, 0, self.width(), self.height())
        panel.center_in_scene(scene_rect)
        self.graphics_view.scene.addItem(panel)
        panel.fade_in()
        self.save_panel = panel
        self.is_in_save = True
        # 读取本故事存档列表（按格子顺序，快速存档不显示），填充槽位
        saves_data, save_files, max_slot_index = self._load_saves_data(0)
        panel.set_total_pages((max_slot_index // 8) + 1)
        panel.set_saves_data(saves_data, save_files)
        panel.set_refresh_callback(self._refresh_save_panel)
        panel.set_save_to_slot_callback(self._on_save_to_slot)
        panel.set_delete_slot_callback(self._on_delete_slot)
        panel.set_overwrite_slot_callback(self._on_overwrite_slot)
        # 打开保存面板：暂停自动播放/快进（返回剧情后恢复）
        self._auto_play_paused = getattr(self.controller, "auto_play", False)
        if self.controller.auto_play:
            self.controller.auto_play = False
            print("保存面板打开：暂停自动播放")
            self._update_auto_play_icon()
        if getattr(self.controller, "skip_mode", False):
            self.controller.skip_timer.stop()
            print("保存面板打开：暂停快进")
        print("保存面板已打开")

    def _refresh_save_panel(self):
        if not self.save_panel or not self.is_in_save:
            return
        page = getattr(self.save_panel, "_page_index", 0)
        saves_data, save_files, max_slot_index = self._load_saves_data(page)
        self.save_panel.set_total_pages((max_slot_index // 8) + 1)
        self.save_panel.set_saves_data(saves_data, save_files)

    def _on_save_to_slot(self, slot_index):
        """保存面板空槽点击：保存当前进度到指定格子。"""
        self.controller.save_game_to_slot(slot_index)
        print(f"已保存到格子 {slot_index}")
        self._refresh_save_panel()

    def _on_delete_slot(self, slot_index):
        """保存面板垃圾桶点击（确认后）：删除指定格子存档。"""
        ok = self.controller.delete_slot_save(slot_index)
        if ok:
            print(f"已删除格子 {slot_index} 的存档")
        else:
            print(f"删除格子 {slot_index} 失败/无存档")
        self._refresh_save_panel()

    def _on_overwrite_slot(self, slot_index):
        """保存面板覆盖确认：删旧存新（先删该格旧存档，再保存当前进度到该格）。"""
        self.controller.delete_slot_save(slot_index)
        self.controller.save_game_to_slot(slot_index)
        print(f"已覆盖格子 {slot_index}")
        self._refresh_save_panel()

    def close_save_panel(self):
        """关闭保存面板：先渐隐（100->0），再移除。"""
        if self.is_in_save and self.save_panel:
            panel = self.save_panel
            self.save_panel = None
            panel.fade_out(on_finished=lambda: self._finish_close_save_panel(panel))
            self.is_in_save = False
        else:
            self._set_bottom_menu_visible(True)

    def _finish_close_save_panel(self, panel):
        """保存面板渐隐完成后：移除面板 + 恢复底部菜单按钮 + 恢复暂停的自动播放/快进。"""
        panel.remove_from_scene()
        # 恢复底部菜单按钮可见（面板已关）；若另一面板已打开则保持隐藏
        if not self.is_in_settings and not self.is_in_backlog and not self.is_in_save:
            self._set_bottom_menu_visible(True)
            if self.controller.is_in_menu:
                # 与设置面板返回一致：主菜单按钮淡入显示
                self._set_menu_buttons_fade_in()
        # 恢复打开保存面板前暂停的自动播放/快进（仅当仍在剧情中）
        if self.controller.is_in_game and not self.controller.is_in_menu:
            if getattr(self, "_auto_play_paused", False) and not self.controller.auto_play:
                self.controller.auto_play = True
                print("保存面板关闭：恢复自动播放")
                if self.controller.is_waiting_for_next_page:
                    self.controller.play_current_page()
                elif self.controller.is_text_finished and self.controller.is_audio_finished:
                    self.controller.advance_to_next_scene()
                self._update_auto_play_icon()
            if getattr(self.controller, "skip_mode", False) and not self.controller.skip_timer.isActive():
                self.controller.skip_timer.start()
                print("保存面板关闭：恢复快进")
        self._auto_play_paused = False

    def _set_bottom_menu_visible(self, visible: bool):
        """隐藏/显示底部菜单按钮及其文字。面板（设置/日志）打开时隐藏，关闭时恢复。"""
        for it in self.bottom_menu_buttons:
            # 隐藏前重置悬停状态，避免恢复可见时残留悬停样式（如白底）
            if not visible and isinstance(it, SettingsButtonItem):
                it.reset_hover()
            if it.scene():
                it.setVisible(visible)

    def _toggle_ui_hidden(self):
        """"⊙"开关：隐藏/恢复 对话框+底部菜单。

        进入隐藏：记录当前对话框可见性（剧情中对话框可能本来就隐藏，如过场页），
        隐藏对话框与底部菜单；恢复时按记录状态还原，不强制显示。
        """
        if self._ui_hidden:
            self._restore_ui()
            return
        # 记录对话框当前可见性（chatbox_item 可能不存在，如主菜单）
        was = True
        try:
            if self.chatbox_item is not None and self.chatbox_item.scene():
                was = bool(self.chatbox_item.isVisible())
        except Exception:
            was = True
        self._ui_hidden_chatbox_was = was
        # 隐藏对话框 + 底部菜单（按钮 + 菜单条本体）
        if self.chatbox_item is not None and self.chatbox_item.scene():
            self.set_chatbox_visible(False)
        self._set_bottom_menu_visible(False)
        if self.bottom_menu_item is not None and self.bottom_menu_item.scene():
            self.bottom_menu_item.setVisible(False)
        self._ui_hidden = True
        print(f"UI 隐藏：对话框原可见性={was}")

    def _restore_ui(self):
        """恢复 UI（任意点击触发）：恢复底部菜单 + 按记录状态恢复对话框。"""
        if not self._ui_hidden:
            return
        self._set_bottom_menu_visible(True)
        if self.bottom_menu_item is not None and self.bottom_menu_item.scene():
            self.bottom_menu_item.setVisible(True)
        try:
            if self.chatbox_item is not None and self.chatbox_item.scene():
                self.set_chatbox_visible(self._ui_hidden_chatbox_was)
        except Exception:
            pass
        self._ui_hidden = False
        print("UI 恢复显示")

    def _on_ui_hidden_click(self):
        """隐藏模式下任意位置点击：仅恢复显示，不推进剧情。"""
        self._restore_ui()

    def _update_skip_icon(self):
        """按当前 skip_mode 状态更新底部菜单快进按钮图标。"""
        icon = "▶▶" if getattr(self.controller, "skip_mode", False) else "▷▷"
        for it in self.bottom_menu_buttons:
            if isinstance(it, QGraphicsTextItem) and it.toPlainText() in ("▷▷", "▶▶"):
                it.setPlainText(icon)
                return

    def show_quick_save_toast(self, duration: int = 1500):
        """快速保存完成后，在 Q.Save 按钮上方弹出圆角提示框（保存成功）。
        多语言：zh=保存成功 / en=Save successful / ja=Save完成（保留 Save 字样）。
        提示框挂在场景上，停留 duration 毫秒后自动渐隐移除。
        """
        # 找到 Q.Save 按钮（bottom_quick_save），在其上方定位
        btn = None
        for it in self.bottom_menu_buttons:
            if getattr(it, "key", None) == "bottom_quick_save":
                btn = it
                break
        if btn is None:
            return
        # 多语言文案
        lang = self.controller.language or "zh"
        if lang == "zh":
            text = "保存成功"
        elif lang == "ja":
            text = "Save完成"
        else:
            text = "Save successful"
        # 测量文字宽高
        font = QFont("Microsoft YaHei", 12, QFont.Bold)
        fm = QFontMetrics(font)
        tw = fm.horizontalAdvance(text)
        th = fm.height()
        pad_x, pad_y = 12, 8
        box_w = tw + 2 * pad_x
        box_h = th + 2 * pad_y
        # 位置：Q.Save 按钮上方居中（按钮 _rect 为场景坐标，pos 恒 0,0）
        btn_rect = btn._rect
        cx = btn_rect.center().x()
        top = btn_rect.top()
        x = cx - box_w / 2
        y = top - box_h - 6  # 按钮上方留 6px 间距
        scene = self.graphics_view.scene
        # 若旧 toast 未消失先移除（避免叠加）
        if getattr(self, "_qsave_toast", None) is not None:
            self._remove_qsave_toast()
        # 圆角底框（半透明黑）
        from PySide6.QtGui import QPainterPath
        path = QPainterPath()
        path.addRoundedRect(QRectF(0, 0, box_w, box_h), 10, 10)
        box = QGraphicsPathItem(path)
        # 框颜色：bottom_menu.color（RGBA），缺省半透明黑
        _bm_cfg = ((self.ui_settings or {}).get("bottom_menu") or {})
        _bm_col = _bm_cfg.get("color") if isinstance(_bm_cfg, dict) else None
        if _bm_col and len(_bm_col) >= 3:
            _bma = _bm_col[3] if len(_bm_col) > 3 else 255
            box.setBrush(QBrush(QColor(_bm_col[0], _bm_col[1], _bm_col[2], _bma)))
        else:
            box.setBrush(QBrush(QColor(0, 0, 0, 200)))
        box.setPen(QPen(Qt.NoPen))
        box.setPos(x, y)
        box.setZValue(70)  # 高于设置面板(20)/日志(60)，确保可见
        scene.addItem(box)
        # 文字
        label = QGraphicsTextItem(text)
        # 文字颜色：按框底色的 r+g+b 亮度规则（<383 白字，>=383 黑字）
        _bsum = sum(_bm_col[:3]) if (_bm_col and len(_bm_col) >= 3) else 0
        if _bm_col and len(_bm_col) >= 3 and _bsum >= 383:
            label.setDefaultTextColor(QColor(0, 0, 0, 255))
        else:
            label.setDefaultTextColor(QColor(255, 255, 255, 255))
        label.setFont(font)
        label.setTextInteractionFlags(Qt.NoTextInteraction)
        label.setAcceptHoverEvents(False)
        label.setCursor(Qt.ArrowCursor)
        label.setPos(x + (box_w - label.boundingRect().width()) / 2,
                     y + (box_h - label.boundingRect().height()) / 2)
        label.setZValue(71)
        scene.addItem(label)
        self._qsave_toast = (box, label)
        # 自动消失：先停留 duration，再渐隐 300ms 后移除
        def _fade_out():
            if getattr(self, "_qsave_toast", None) is None:
                return
            effect = QGraphicsOpacityEffect()
            for it in self._qsave_toast:
                it.setGraphicsEffect(effect)
            anim = QPropertyAnimation(effect, b"opacity")
            anim.setDuration(300)
            anim.setStartValue(1.0)
            anim.setEndValue(0.0)
            anim.finished.connect(self._remove_qsave_toast)
            self._qsave_toast_anim = anim
            anim.start()
        QTimer.singleShot(duration, _fade_out)

    def _remove_qsave_toast(self):
        """移除快速保存提示框（含渐隐动画清理）。"""
        if getattr(self, "_qsave_toast", None) is None:
            return
        for it in self._qsave_toast:
            it.setGraphicsEffect(None)
            if it.scene():
                self.graphics_view.scene.removeItem(it)
        self._qsave_toast = None



    def _refresh_current_dialog(self):
        """剧情中语言切换后：用当前场景的 content 重新渲染对话（名称/字幕按新语言取词）。
        直接显示新语言全文，不重播逐字动画，不触发自动前进。
        当前场景无对话时无操作。
        """
        if self.text_display is None or self.name_label is None:
            return
        try:
            page_data = self.controller.current_page_data
            idx = self.controller.current_scene_index
            if not page_data or idx >= len(page_data):
                return
            scene = page_data[idx]
            content = scene.get("content")
            if not content:
                return
            # 直接按新语言取词（与 display_dialog 同逻辑），避免 set_text 重启逐字动画/触发回调
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
            # 直接写入全文（不动逐字 timer / 回调 / is_text_finished）
            self.text_display.timer.stop()
            self.text_display.full_text = words
            self.text_display.displayed_text = words
            self.text_display.char_index = len(words)
            self.text_display.setPlainText(words)
            cursor = self.text_display.textCursor()
            cursor.movePosition(QTextCursor.End)
            self.text_display.setTextCursor(cursor)
        except Exception as e:
            print(f"刷新当前对话失败: {e}")

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
        # use transition_color block with gradient fade-in (like old black block)
        tc = self.controller.transition_color
        if not tc:
            tc = [0, 0, 0]
        w, h = self.controller.logical_size
        color_block = QPixmap(w, h)
        color_block.fill(QColor(tc[0], tc[1], tc[2]))
        self.graphics_view.clear_items()
        self.graphics_view.add_item(color_block, [0, 0])
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
            self.name_label.setCursor(Qt.ArrowCursor)  # 悬停保持箭头，避免 IBeam
            self.name_label.setAttribute(Qt.WA_TransparentForMouseEvents, True)  # 名字不拦截鼠标
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
            # 对话框文字区域不拦截鼠标：widget 本身 + QTextEdit 内部 viewport 都设透明，
            # 否则点击文字会被 QTextEdit 消费（accepted），GraphicsView 不转发主窗口 → 点击无反应
            self.text_display.setAttribute(Qt.WA_TransparentForMouseEvents, True)
            self.text_display.viewport().setAttribute(Qt.WA_TransparentForMouseEvents, True)
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
        填充色 = color（RGBA，默认 [0,0,0,255]）。顶边位于 chatbox 底边处。
        菜单条向下额外延伸 EXTEND_PX（默认 50px），避免窗口宽高比偏离 16:9 时
        底部露边/亚像素缝隙；fitInView 仍按 1280x720 适配，延伸部分随场景裁切。
        返回菜单条顶边到逻辑底边的距离（menu_h，px）；未配置时返回 0。
        """
        bm = self.ui_settings.get("bottom_menu")
        if not bm or not isinstance(bm, dict):
            return 0
        if bm.get("mode", "default") != "default":
            return 0
        # 高度：默认 3% 逻辑高度；支持自定义比例
        ratio = float(bm.get("height_ratio", 0.03))
        menu_h = max(1, int(round(window_height * ratio)))
        # 向下延伸量：默认 50px；配置 extend 可覆盖（0 关闭）
        extend = int(bm.get("extend", 50))
        # 颜色：默认 [0,0,0,255]（不透明黑）；RGBA 四元素
        color = bm.get("color", [0, 0, 0, 255])
        if len(color) < 3:
            color = [0, 0, 0, 255]
        r, g, b = color[0], color[1], color[2]
        a = color[3] if len(color) > 3 else 255
        item = QGraphicsRectItem(0, 0, window_width, menu_h + extend)
        item.setBrush(QBrush(QColor(r, g, b, a)))
        item.setPen(QPen(Qt.NoPen))
        item.setPos(0, window_height - menu_h)  # 顶边不变（chatbox 底边处），向下延伸
        item.setZValue(9)  # 低于对话框(z=10)，紧贴窗口底部
        self.graphics_view.scene.addItem(item)
        self.bottom_menu_item = item
        # 扩展场景渲染矩形：保证延伸部分可渲染（fitInView 仍按逻辑尺寸适配，不受影响）
        scene_rect = self.graphics_view.scene.sceneRect()
        if scene_rect.height() < window_height + extend:
            self.graphics_view.scene.setSceneRect(0, 0, window_width, window_height + extend)
        # 底部菜单按钮：最右侧第一个 = 设置（预设 UI，多语言与设置面板一致）
        self._create_bottom_menu_buttons(window_width, window_height, menu_h, extend)
        print(f"底部菜单(default): 高 {menu_h}px (ratio={ratio}) 延伸 {extend}px，颜色 rgba({r},{g},{b},{a})")
        return menu_h

    def _create_bottom_menu_buttons(self, window_width: int, window_height: int,
                                    menu_h: int, extend: int = 50):
        """创建底部菜单条上的按钮（预设 default UI）。
        从右到左：⊙(右1) | 日志(右2) | 设置(右3) | 快进(右4) | 自动播放(右5) | 加载(右6) | 保存(右7) | Q.Load(右8) | Q.Save(右9)。
        按钮文字随 controller.language 变化（多语言与设置面板一致）。
        """
        # 清除旧按钮及文字
        for it in list(self.bottom_menu_buttons):
            if it.scene():
                self.graphics_view.scene.removeItem(it)
        self.bottom_menu_buttons = []

        # 按钮配色：读取 bottom_menu.button_color（RGBA）；缺失则保持原 dark 模式
        _bm_cfg = (self.ui_settings or {}).get("bottom_menu") or {}
        _bc = _bm_cfg.get("button_color") if isinstance(_bm_cfg, dict) else None
        button_color = list(_bc) if _bc else None
        normal_text_color = None
        if button_color is not None:
            normal_text_color = QColor(255, 255, 255, 255) if sum(button_color[:3]) < 383 else QColor(0, 0, 0, 255)

        # 按钮布局：右缘贴菜单条右边缘（留 margin），垂直居中于菜单条可视区
        margin = 12
        btn_h = max(18, menu_h - 2 * margin)
        y = (window_height - menu_h) + (menu_h - btn_h) / 2  # 菜单条顶边 + 垂直居中

        def make_label(text: str, font_size: int = 12, text_color=None) -> "QGraphicsTextItem":
            label = QGraphicsTextItem(text)
            label.setDefaultTextColor(text_color if text_color is not None else QColor(255, 255, 255))
            label.setFont(QFont("Microsoft YaHei", font_size, QFont.Bold))
            label.setAcceptHoverEvents(False)
            label.setTextInteractionFlags(Qt.NoTextInteraction)  # 文字不拦截点击
            label.setCursor(Qt.ArrowCursor)  # 悬停保持箭头，避免 IBeam
            label.setTextWidth(-1)
            return label

        # --- "⊙"隐藏开关按钮（最右侧右1）：隐藏/恢复 对话框+底部菜单 ---
        hide_label = make_label("⊙", font_size=14, text_color=normal_text_color)
        hr = hide_label.boundingRect()
        hide_btn_w = max(btn_h, hr.width() + 16)
        hide_rect = QRectF(window_width - margin - hide_btn_w, y, hide_btn_w, btn_h)
        hide_btn = SettingsButtonItem(hide_rect, "bottom_ui_hidden", opacity=200, button_color=button_color)
        hide_btn.setZValue(10)
        hide_btn.set_click_handler(self._toggle_ui_hidden)
        self.graphics_view.scene.addItem(hide_btn)
        self.bottom_menu_buttons.append(hide_btn)

        hide_label.setPos(hide_rect.center().x() - hr.width() / 2,
                          hide_rect.center().y() - hr.height() / 2)
        hide_label.setZValue(11)
        self.graphics_view.scene.addItem(hide_label)
        self.bottom_menu_buttons.append(hide_label)
        hide_btn._text_label = hide_label  # 悬停变色用

        # --- 日志/Backlog按钮（右2）：文字 日志(zh) / Backlog(en/ja) ---
        lang = self.controller.language or "zh"
        backlog_text = "日志" if lang == "zh" else "Backlog"
        backlog_label = make_label(backlog_text, text_color=normal_text_color)
        bkr = backlog_label.boundingRect()
        backlog_btn_w = max(40, bkr.width() + 24)
        backlog_rect = QRectF(hide_rect.left() - margin - backlog_btn_w, y, backlog_btn_w, btn_h)
        backlog_btn = SettingsButtonItem(backlog_rect, "bottom_backlog", opacity=200, button_color=button_color)
        backlog_btn.setZValue(10)
        backlog_btn.set_click_handler(self.toggle_backlog_button)
        self.graphics_view.scene.addItem(backlog_btn)
        self.bottom_menu_buttons.append(backlog_btn)

        backlog_label.setPos(backlog_rect.center().x() - bkr.width() / 2,
                             backlog_rect.center().y() - bkr.height() / 2)
        backlog_label.setZValue(11)
        self.graphics_view.scene.addItem(backlog_label)
        self.bottom_menu_buttons.append(backlog_label)
        backlog_btn._text_label = backlog_label  # 悬停变色用

        # --- 设置按钮（最右侧） ---
        text = "设置"
        lang = self.controller.language or "zh"
        if lang in ("en", "ja"):
            text = {"en": "Settings", "ja": "設定"}[lang]
        elif lang == "ru":
            text = "Settings"  # 预设 UI 不支持俄语，回落英语
        label = make_label(text, text_color=normal_text_color)
        text_rect = label.boundingRect()
        # 按钮宽 = 文字宽 + 左右 padding（至少 40px，保留中文基准宽）
        btn_w = max(40, text_rect.width() + 24)
        x = backlog_rect.left() - margin - btn_w  # 日志按钮左侧（右2）

        rect = QRectF(x, y, btn_w, btn_h)
        btn = SettingsButtonItem(rect, "bottom_settings", opacity=200, button_color=button_color)
        btn.setZValue(10)  # 与 chatbox 同层，在菜单条(9)之上
        btn.set_click_handler(self.open_settings)
        self.graphics_view.scene.addItem(btn)
        self.bottom_menu_buttons.append(btn)

        # 文字：挂场景，按钮 _rect 中心定位（SettingsButtonItem pos 恒 (0,0)）
        r = label.boundingRect()
        label.setPos(rect.center().x() - r.width() / 2, rect.center().y() - r.height() / 2)
        label.setZValue(11)
        self.graphics_view.scene.addItem(label)
        self.bottom_menu_buttons.append(label)
        btn._text_label = label  # 悬停变色用（_set_text_color 需要）

        # --- 快进开关按钮（设置按钮左侧，右3）：▷▷ 关闭 / ▶▶ 开启 ---
        # 先创建图标文字量宽：▷▷ 是双字符，按钮宽需按文字自适应（最小保持方形 btn_h）
        skip_on = getattr(self.controller, "skip_mode", False)
        skip_icon = "▶▶" if skip_on else "▷▷"
        skip_label = make_label(skip_icon, font_size=14, text_color=normal_text_color)
        sr = skip_label.boundingRect()
        skip_btn_w = max(btn_h, sr.width() + 16)
        skip_rect = QRectF(x - margin - skip_btn_w, y, skip_btn_w, btn_h)
        skip_btn = SettingsButtonItem(skip_rect, "bottom_skip", opacity=200, button_color=button_color)
        skip_btn.setZValue(10)
        skip_btn.set_click_handler(self.toggle_skip_button)
        self.graphics_view.scene.addItem(skip_btn)
        self.bottom_menu_buttons.append(skip_btn)

        skip_label.setPos(skip_rect.center().x() - sr.width() / 2,
                          skip_rect.center().y() - sr.height() / 2)
        skip_label.setZValue(11)
        self.graphics_view.scene.addItem(skip_label)
        self.bottom_menu_buttons.append(skip_label)
        skip_btn._text_label = skip_label  # 悬停变色用

        # --- 自动播放开关按钮（快进按钮左侧，右4） ---
        auto_btn_w = btn_h  # 方形图标按钮
        auto_rect = QRectF(skip_rect.left() - margin - auto_btn_w, y, auto_btn_w, btn_h)
        auto_btn = SettingsButtonItem(auto_rect, "bottom_auto_play", opacity=200, button_color=button_color)
        auto_btn.setZValue(10)
        auto_btn.set_click_handler(self.toggle_auto_play_button)
        self.graphics_view.scene.addItem(auto_btn)
        self.bottom_menu_buttons.append(auto_btn)

        # 图标：▷ 关闭（未播放）/ ▶ 开启（播放中），随状态切换
        icon = "▶" if getattr(self.controller, "auto_play", False) else "▷"
        icon_label = make_label(icon, font_size=14, text_color=normal_text_color)
        ir = icon_label.boundingRect()
        icon_label.setPos(auto_rect.center().x() - ir.width() / 2,
                          auto_rect.center().y() - ir.height() / 2)
        icon_label.setZValue(11)
        self.graphics_view.scene.addItem(icon_label)
        self.bottom_menu_buttons.append(icon_label)
        auto_btn._text_label = icon_label  # 悬停变色用

        # --- 加载按钮（自动播放按钮左侧，右5）：中文 加载 / 日语 ロード / 其余语言 Load ---
        # 功能与主菜单"加载游戏"一致：复用 open_load_panel（主菜单/剧情中均可打开）
        if lang == "zh":
            load_text = "加载"
        else:  # en / ja / ru
            load_text = "Load"
        load_label = make_label(load_text, text_color=normal_text_color)
        load_r = load_label.boundingRect()
        load_btn_w = max(40, load_r.width() + 24)
        load_rect = QRectF(auto_rect.left() - margin - load_btn_w, y, load_btn_w, btn_h)
        load_btn = SettingsButtonItem(load_rect, "bottom_load", opacity=200, button_color=button_color)
        load_btn.setZValue(10)
        load_btn.set_click_handler(self.open_load_panel)
        self.graphics_view.scene.addItem(load_btn)
        self.bottom_menu_buttons.append(load_btn)

        load_label.setPos(load_rect.center().x() - load_r.width() / 2,
                          load_rect.center().y() - load_r.height() / 2)
        load_label.setZValue(11)
        self.graphics_view.scene.addItem(load_label)
        self.bottom_menu_buttons.append(load_label)
        load_btn._text_label = load_label  # 悬停变色用

        # --- 保存按钮（加载按钮左侧，右6）：仅中文 保存，其余语言一律英文 Save ---
        save_text = "保存" if lang == "zh" else "Save"
        save_label = make_label(save_text, text_color=normal_text_color)
        save_r = save_label.boundingRect()
        save_btn_w = max(40, save_r.width() + 24)
        save_rect = QRectF(load_rect.left() - margin - save_btn_w, y, save_btn_w, btn_h)
        save_btn = SettingsButtonItem(save_rect, "bottom_save", opacity=200, button_color=button_color)
        save_btn.setZValue(10)
        save_btn.set_click_handler(self.open_save_panel)
        self.graphics_view.scene.addItem(save_btn)
        self.bottom_menu_buttons.append(save_btn)

        save_label.setPos(save_rect.center().x() - save_r.width() / 2,
                          save_rect.center().y() - save_r.height() / 2)
        save_label.setZValue(11)
        self.graphics_view.scene.addItem(save_label)
        self.bottom_menu_buttons.append(save_label)
        save_btn._text_label = save_label  # 悬停变色用

        # --- 快速加载 Q.Load 按钮（保存按钮左侧，右7）：固定文字 Q.Load ---
        # 功能开发中：暂不绑定逻辑，点击仅打印提示
        qload_text = "快速加载" if lang == "zh" else "Q.Load"
        qload_label = make_label(qload_text, text_color=normal_text_color)
        qload_r = qload_label.boundingRect()
        qload_btn_w = max(40, qload_r.width() + 24)
        qload_rect = QRectF(save_rect.left() - margin - qload_btn_w, y, qload_btn_w, btn_h)
        qload_btn = SettingsButtonItem(qload_rect, "bottom_quick_load", opacity=200, button_color=button_color)
        qload_btn.setZValue(10)
        qload_btn.set_click_handler(self._on_bottom_qload_clicked)
        self.graphics_view.scene.addItem(qload_btn)
        self.bottom_menu_buttons.append(qload_btn)

        qload_label.setPos(qload_rect.center().x() - qload_r.width() / 2,
                           qload_rect.center().y() - qload_r.height() / 2)
        qload_label.setZValue(11)
        self.graphics_view.scene.addItem(qload_label)
        self.bottom_menu_buttons.append(qload_label)
        qload_btn._text_label = qload_label  # 悬停变色用

        # --- 快速保存 Q.Save 按钮（Q.Load 按钮左侧，右8）：仅中文 快速保存，其余语言一律英文 Q.Save ---
        qsave_text = "快速保存" if lang == "zh" else "Q.Save"
        qsave_label = make_label(qsave_text, text_color=normal_text_color)
        qsave_r = qsave_label.boundingRect()
        qsave_btn_w = max(40, qsave_r.width() + 24)
        qsave_rect = QRectF(qload_rect.left() - margin - qsave_btn_w, y, qsave_btn_w, btn_h)
        qsave_btn = SettingsButtonItem(qsave_rect, "bottom_quick_save", opacity=200, button_color=button_color)
        qsave_btn.setZValue(10)
        qsave_btn.set_click_handler(self.controller.quick_save)
        self.graphics_view.scene.addItem(qsave_btn)
        self.bottom_menu_buttons.append(qsave_btn)

        qsave_label.setPos(qsave_rect.center().x() - qsave_r.width() / 2,
                           qsave_rect.center().y() - qsave_r.height() / 2)
        qsave_label.setZValue(11)
        self.graphics_view.scene.addItem(qsave_label)
        self.bottom_menu_buttons.append(qsave_label)
        qsave_btn._text_label = qsave_label  # 悬停变色用


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
        # 说话人原始标识：用于日志面板按当前语言重新翻译
        #   ("char", char_id) 角色标识；("map", speak_dict) 说话人字典
        speaker_key = None
        if "speaking_name" in content:
            char_id = content["speaking_name"]
            speaker_key = ("char", char_id)
            char_data = self.controller.story_data["story_and_position"]["character_and_motion"].get(char_id, {})
            names = char_data.get("name", {})
            speaking_name = names.get(lang) or names.get("zh", "")
        elif "speaking" in content:
            speak_map = content["speaking"]
            speaker_key = ("map", dict(speak_map))
            speaking_name = speak_map.get(lang) or speak_map.get("zh", "")
        self.name_label.setText(speaking_name)
        words_map = content["words"]
        words = words_map.get(lang) or words_map.get("zh", "")
        self.text_display.set_text(words, self.controller.on_text_display_complete)
        # 记录日志条目（说话人原始标识, 台词多语言字典）——空台词不记。
        # 存原始数据而非翻译后文本：日志面板打开时按当前语言统一翻译，
        # 避免中途切语言导致日志新旧语言混排。
        if words:
            self.controller.backlog_entries.append((speaker_key, dict(words_map)))

    def load_pixmap(self, path: str) -> Optional[QPixmap]:
        return self.resource_manager.load_pixmap(path)

    def mousePressEvent(self, event):
        print("鼠标点击事件触发")
        if self.is_in_backlog:
            # 日志面板打开时：仅区分面板内/外点击
            if self.backlog_panel:
                scene_pos = self.graphics_view.mapToScene(event.position().toPoint())
                if self.backlog_panel.contains(self.backlog_panel.mapFromScene(scene_pos)):
                    # 点击面板内部：不关闭（后续供日志条目使用）
                    return
            # 点击面板外部：关闭日志
            self.close_backlog_panel()
            return
        if self.is_in_settings:
            # 设置面板打开时：背景菜单按钮已隐藏，仅区分面板内/外点击
            if self.settings_panel:
                scene_pos = self.graphics_view.mapToScene(event.position().toPoint())
                if self.settings_panel.contains(self.settings_panel.mapFromScene(scene_pos)):
                    # 点击面板内部：不关闭（后续供内嵌控件使用）
                    return
            # 点击面板外部：关闭设置
            self.close_settings_panel()
            return
        if self.is_in_save:
            # 保存面板打开时：仅区分面板内/外点击（面板内后续供存档槽位使用）
            if self.save_panel:
                scene_pos = self.graphics_view.mapToScene(event.position().toPoint())
                if self.save_panel.contains(self.save_panel.mapFromScene(scene_pos)):
                    return
            # 点击面板外部：关闭保存面板
            self.close_save_panel()
            return
        if self.controller.is_in_menu:
            super().mousePressEvent(event)
            return
        if event.button() == Qt.LeftButton:
            self.controller.handle_click()

    def keyPressEvent(self, event):
        if self.is_in_backlog:
            # 日志面板打开时：Esc 关闭
            if event.key() == Qt.Key_Escape:
                self.close_backlog_panel()
            super().keyPressEvent(event)
            return
        if self.is_in_settings:
            # 设置面板打开时：Esc 关闭
            if event.key() == Qt.Key_Escape:
                self.close_settings_panel()
            super().keyPressEvent(event)
            return
        if self.is_in_save:
            # 保存面板打开时：Esc 关闭
            if event.key() == Qt.Key_Escape:
                self.close_save_panel()
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
                self._update_auto_play_icon()
            elif event.key() == Qt.Key_S:
                self.controller.toggle_skip_mode()
                self._update_skip_icon()
            elif event.key() == Qt.Key_F2:
                self.controller.save_game()
            elif event.key() == Qt.Key_F3:
                self.controller.load_save()
            else:
                super().keyPressEvent(event)