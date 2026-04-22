import os
from pathlib import Path
from typing import Optional

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QLabel, QPushButton, QFileDialog,
    QGraphicsTextItem, QFrame, QGraphicsRectItem, QGraphicsPixmapItem, QApplication,
    QGraphicsOpacityEffect
)
from PySide6.QtCore import Qt, QTimer, QPropertyAnimation, QEasingCurve
from PySide6.QtGui import QPixmap, QColor, QFont, QBrush, QPen

from core.game_controller import GameController
from ui.graphics_view import GraphicsView, MenuButtonItem
from ui.widgets import TextDisplayWidget
from data_management.resource_manager import ResourceManager
from data_management.story_parser import load_ui_settings_from_data


class GalGameWindow(QMainWindow):
    """Galgame 主窗口"""
    def __init__(self):
        super().__init__()
        self.controller = GameController(self)
        self.resource_manager = ResourceManager()
        self.ui_settings = {
            "chatbox_style": None,
            "name_show_region": [[76, 60], [270, 149]],
            "words_show_region": [[310, 60], [805, 149]]
        }
        self.name_label = None
        self.text_display = None
        self.chatbox_item = None
        self.chatbox_widget_proxies = []  # 存储对话框相关的所有代理控件
        self.start_button = None
        self.title_item = None
        self.menu_bg_item = None
        self.graphics_view = None

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
        self.graphics_view.scene.clear()
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
                    self.graphics_view.add_item(bg_pixmap, [(self.controller.window_size[0] - bg_pixmap.width()) // 2, 0])
            if "title" in menu_data:
                title_path = menu_data["title"][self.controller.language]
                full_title_path = self.controller.base_path / title_path
                title_pixmap = self.load_pixmap(str(full_title_path))
                if title_pixmap:
                    menu_pos = menu_data.get("menu_pos", {})
                    title_pos = menu_pos.get("title", [54, 48])
                    self.graphics_view.add_item(title_pixmap, title_pos)
            self.create_start_button(menu_data)
        except Exception as e:
            print(f"显示开始菜单失败: {e}")
            import traceback
            traceback.print_exc()

    def create_start_button(self, menu_data):
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
        menu_pos = menu_data.get("menu_pos", {})
        button_data = menu_pos.get("start", [[115, 230], {self.controller.language: "Game start"}])
        button_pos = button_data[0]
        self.start_button = MenuButtonItem(button_pixmap, touched_pixmap)
        if not self.start_button:
            print("创建开始按钮失败")
            return
        self.start_button.setPos(button_pos[0], button_pos[1])
        self.start_button.setZValue(2)
        self.start_button.set_click_handler(self.on_start_button_clicked)
        self.graphics_view.add_item(self.start_button, button_pos)
        text_rgb = menu_data.get("text_rgb", [255, 255, 255])
        text_color = QColor(text_rgb[0], text_rgb[1], text_rgb[2])
        text_x = button_pos[0] + button_pixmap.width() // 2
        text_y = button_pos[1] + button_pixmap.height() // 2
        text_item = QGraphicsTextItem(button_data[1][self.controller.language])
        text_item.setDefaultTextColor(text_color)
        text_item.setFont(QFont("Microsoft YaHei", 14, QFont.Bold))
        text_rect = text_item.boundingRect()
        text_item.setPos(text_x - text_rect.width() / 2, text_y - text_rect.height() / 2)
        text_item.setZValue(3)
        text_item.setAcceptHoverEvents(False)
        self.graphics_view.add_item(text_item)
        self.graphics_view.show_items(menu_data.get("change", [[], None])[1])
        self.graphics_view.start_pending_animations()

    def on_start_button_clicked(self):
        if self.controller.is_in_menu:
            print("开始按钮被点击，准备淡出菜单")
            self.fade_out_menu()

    def fade_out_menu(self):
        self.controller.is_in_menu = False
        black = QPixmap(self.controller.window_size[0], self.controller.window_size[1])
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

        load_ui_settings_from_data(self)
        window_width, window_height = self.controller.window_size
        chatbox_pos = [0, 0]

        # 创建对话框背景
        if self.ui_settings["chatbox_style"]:
            chatbox_path = self.controller.base_path / self.ui_settings["chatbox_style"]
            chatbox_pixmap = self.load_pixmap(str(chatbox_path))
            if chatbox_pixmap and not chatbox_pixmap.isNull():
                self.chatbox_item = QGraphicsPixmapItem(chatbox_pixmap)
                chatbox_pos = [
                    (window_width - chatbox_pixmap.width()) // 2,
                    window_height - chatbox_pixmap.height()
                ]
                self.chatbox_item.setPos(chatbox_pos[0], chatbox_pos[1])
                self.chatbox_item.setZValue(10)
                self.graphics_view.scene.addItem(self.chatbox_item)
                print(f"使用自定义字幕框样式: {self.ui_settings['chatbox_style']}")
            else:
                print(f"无法加载自定义字幕框样式，使用默认样式")
                self.create_default_chatbox(window_width, window_height)
        else:
            self.create_default_chatbox(window_width, window_height)

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
            self.text_display.setFixedSize(words_size[0], words_size[1])
            self.text_display.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        else:
            self.text_display.setFixedSize(words_size[0], words_size[1])
        text_widget_proxy = self.graphics_view.scene.addWidget(self.text_display)
        text_widget_proxy.setZValue(12)
        text_widget_proxy.setPos(chatbox_pos[0] + words_pos[0], chatbox_pos[1] + words_pos[1])
        self.chatbox_widget_proxies.append(text_widget_proxy)

    def create_default_chatbox(self, window_width: int, window_height: int):
        dialog_bg = QGraphicsRectItem(0, 0, 1280, 220)
        dialog_bg.setBrush(QBrush(QColor(0, 0, 0, 180)))
        dialog_bg.setPen(QPen(Qt.NoPen))
        dialog_bg.setPos((window_width - 1280) // 2, window_height - 220)
        dialog_bg.setZValue(10)
        self.graphics_view.scene.addItem(dialog_bg)
        self.chatbox_item = dialog_bg

        name_bg = QGraphicsRectItem(0, 0, 200, 40)
        name_bg.setBrush(QBrush(QColor(0, 0, 0, 150)))
        name_bg.setPen(QPen(Qt.NoPen))
        name_bg.setPos((window_width - 1280) // 2 + 76, window_height - 220 + 20)
        name_bg.setZValue(11)
        self.graphics_view.scene.addItem(name_bg)
        # 注意：默认样式的名字背景不是独立的 chatbox_item，但为了统一管理，我们只把主背景存为 chatbox_item
        # 名字背景将随主背景一同控制（如果需要更精细控制，可扩展）

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
                # 为每个 item 创建或获取 QGraphicsOpacityEffect
                effect = item.graphicsEffect()
                if effect is None or not isinstance(effect, QGraphicsOpacityEffect):
                    effect = QGraphicsOpacityEffect()
                    item.setGraphicsEffect(effect)
    
                start_opacity = 0.0 if visible else 1.0
                end_opacity = 1.0 if visible else 0.0
    
                # 如果当前透明度已经是目标值，跳过动画
                if abs(effect.opacity() - end_opacity) < 0.01:
                    print(f"[Chatbox] 透明度已为目标值，跳过: {item}")
                    if not visible:
                        item.setVisible(False)
                    continue
    
                # 创建属性动画，作用于 effect 的 opacity 属性
                anim = QPropertyAnimation(effect, b"opacity")
                anim.setDuration(500)
                anim.setStartValue(start_opacity)
                anim.setEndValue(end_opacity)
                anim.setEasingCurve(QEasingCurve.InOutQuad)
    
                def on_finished(item=item, vis=visible, anim=anim):
                    if not vis:
                        item.setVisible(False)
                    # 从活动列表中移除动画
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
        speaking_name = ""
        if "speaking_name" in content:
            char_id = content["speaking_name"]
            char_data = self.controller.story_data["story_and_position"]["character_and_motion"].get(char_id, {})
            speaking_name = char_data.get("name", {}).get("zh", "")
        elif "speaking" in content:
            speaking_name = content["speaking"].get("zh", "")
        self.name_label.setText(speaking_name)
        words = content["words"].get("zh", "")
        self.text_display.set_text(words, self.controller.on_text_display_complete)

    def load_pixmap(self, path: str) -> Optional[QPixmap]:
        return self.resource_manager.load_pixmap(path)

    def mousePressEvent(self, event):
        print("鼠标点击事件触发")
        if self.controller.is_in_menu:
            super().mousePressEvent(event)
            return
        if event.button() == Qt.LeftButton:
            self.controller.handle_click()

    def keyPressEvent(self, event):
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