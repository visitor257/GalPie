import os
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional, Any, Union
from math import sin, cos, pi
import pickle

from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                               QHBoxLayout, QLabel, QPushButton, QFileDialog,
                               QGraphicsView, QGraphicsScene, QGraphicsPixmapItem,
                               QTextEdit, QFrame, QGraphicsRectItem)
from PySide6.QtCore import Qt, QTimer, QPropertyAnimation, QEasingCurve, QRectF, QPoint, QPointF, QDateTime, QByteArray, QBuffer
from PySide6.QtGui import QPixmap, QPainter, QColor, QFont, QPen, QBrush, QTextCursor, QTransform
from PySide6.QtOpenGLWidgets import QOpenGLWidget
from PySide6.QtWidgets import QGraphicsOpacityEffect


class TextDisplayWidget(QTextEdit):
    """自定义文本显示控件，支持逐字显示效果"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setFrameStyle(QFrame.NoFrame)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setTextInteractionFlags(Qt.NoTextInteraction)

        # 设置字体和样式
        font = QFont("Microsoft YaHei", 14)
        self.setFont(font)
        self.setStyleSheet("""
            QTextEdit {
                background: transparent;
                color: white;
                border: none;
                padding: 10px;
            }
        """)

        self.full_text = ""
        self.displayed_text = ""
        self.char_index = 0
        self.timer = QTimer()
        self.timer.timeout.connect(self.display_next_char)
        self.char_delay = 30  # 毫秒

        # 文本显示完成后的回调函数
        self.on_display_complete = None

    def set_text(self, text: str, on_complete=None):
        """设置要显示的文本"""
        self.full_text = text
        self.displayed_text = ""
        self.char_index = 0
        self.on_display_complete = on_complete
        self.clear()

        if text:
            self.timer.start(self.char_delay)
        else:
            self.timer.stop()
            if self.on_display_complete:
                self.on_display_complete()

    def display_next_char(self):
        """显示下一个字符"""
        if self.char_index < len(self.full_text):
            self.displayed_text += self.full_text[self.char_index]
            self.char_index += 1
            self.setPlainText(self.displayed_text)

            # 自动滚动到底部
            cursor = self.textCursor()
            cursor.movePosition(QTextCursor.End)
            self.setTextCursor(cursor)
        else:
            self.timer.stop()
            if self.on_display_complete:
                self.on_display_complete()

    def complete_display(self):
        """立即完成文本显示"""
        self.timer.stop()
        self.displayed_text = self.full_text
        self.char_index = len(self.full_text)
        self.setPlainText(self.full_text)

        # 立即调用完成回调
        if self.on_display_complete:
            self.on_display_complete()

    def is_display_complete(self) -> bool:
        """检查文本是否显示完成"""
        return self.char_index >= len(self.full_text)


class BackgroundPixmapItem(QGraphicsPixmapItem):
    """背景图片控件"""
    def __init__(self, pixmap=None):
        super().__init__(pixmap)
        self.original_pixmap = pixmap
        self.setZValue(-1)  # 确保背景在最底层

    def set_pixmap(self, pixmap: QPixmap):
        """设置背景图片"""
        self.original_pixmap = pixmap
        self.setPixmap(pixmap)

    def resize_to_fit_window(self, width: int, height: int, bg_pos=[0,0]):
        """调整背景图片大小以适应窗口"""
        if self.original_pixmap and not self.original_pixmap.isNull():
            # 保持宽高比，填充整个区域
            scaled_pixmap = self.original_pixmap.scaled(
                width, height, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation
            )
            self.setPixmap(scaled_pixmap)
            # 背景图片始终放置在(0,0)位置
            self.setPos(bg_pos[0], bg_pos[1])


class AnimatedPixmapItem(QGraphicsPixmapItem):
    """支持缩放和动画的图形项"""
    def __init__(self, pixmap=None):
        super().__init__(pixmap)
        self.original_pixmap = pixmap
        self.current_zoom = 1.0
        self.original_pos = QPointF(0, 0)
        self.animations = []
        self.current_animation_group = None
        self.animation_timer = QTimer()
        self.animation_timer.timeout.connect(self.update_animation)
        self.animation_start_time = 0
        self.animation_progress = 0

        # 动画状态记录
        self.animation_start_zoom = 1.0
        self.animation_start_pos = QPointF(0, 0)

    def set_zoom(self, zoom: float):
        """设置缩放级别"""
        self.current_zoom = zoom
        if self.original_pixmap:
            # 计算缩放后的尺寸
            new_width = int(self.original_pixmap.width() * zoom)
            new_height = int(self.original_pixmap.height() * zoom)
            scaled_pixmap = self.original_pixmap.scaled(
                new_width, new_height, Qt.KeepAspectRatio, Qt.SmoothTransformation
            )
            self.setPixmap(scaled_pixmap)

    def set_animations(self, animations: List):
        """设置动画序列"""
        self.animations = animations
        if animations:
            self.start_animation_group(0)

    def start_animation_group(self, group_index: int):
        """开始播放动画组"""
        if group_index >= len(self.animations):
            # 所有动画组播放完毕
            return

        self.current_animation_group = self.animations[group_index]
        self.animation_start_time = 0
        self.animation_progress = 0

        # 记录动画开始时的状态
        self.animation_start_zoom = self.current_zoom
        self.animation_start_pos = self.pos()

        self.animation_timer.start(16)  # 约60fps

    def update_animation(self):
        """更新动画状态"""
        if not self.current_animation_group:
            self.animation_timer.stop()
            return

        # 更新动画进度
        self.animation_progress += 16  # 增加16毫秒

        # 检查当前动画组是否完成
        group_duration = max(anim.get("time", 0) * 1000 for anim in self.current_animation_group)
        if self.animation_progress >= group_duration:
            # 当前动画组完成，播放下一个组
            current_index = self.animations.index(self.current_animation_group)
            self.start_animation_group(current_index + 1)
            return

        # 应用当前动画组中的所有动画
        for animation in self.current_animation_group:
            self.apply_animation(animation)

    def apply_animation(self, animation: Dict):
        """应用单个动画效果"""
        duration = animation.get("time", 0) * 1000  # 转换为毫秒
        if duration == 0:
            return

        # 计算动画进度 (0.0 到 1.0)
        progress = min(self.animation_progress / duration, 1.0)

        # 使用缓动函数使动画更自然
        eased_progress = self.ease_in_out(progress)

        # 应用缩放动画
        if "zoom" in animation:
            target_zoom = animation["zoom"]

            # 从当前缩放值变化到目标缩放值
            current_zoom = self.animation_start_zoom + (target_zoom - self.animation_start_zoom) * eased_progress
            self.set_zoom(current_zoom)

        # 应用移动动画
        if "move" in animation:
            move_path = animation["move"]
            if move_path and len(move_path) > 0:
                # 计算当前应该应用哪个移动点
                points_count = len(move_path)
                point_index = min(int(progress * points_count), points_count - 1)
                move_offset = move_path[point_index]

                # 应用移动偏移
                new_pos = QPointF(
                    self.animation_start_pos.x() + move_offset[0],
                    self.animation_start_pos.y() + move_offset[1]
                )
                self.setPos(new_pos)

    def ease_in_out(self, t: float) -> float:
        """缓动函数：平滑的加速和减速"""
        return t * t * (3.0 - 2.0 * t)

    def set_original_position(self, pos: QPointF):
        """设置原始位置（用于动画计算）"""
        self.original_pos = pos
        self.setPos(pos)


class GraphicsView(QGraphicsView):
    """支持GPU加速的图形视图"""
    def __init__(self, parent=None, background_pos=[0,0]):
        super().__init__(parent)

        # 启用OpenGL加速
        self.setViewport(QOpenGLWidget())
        self.setRenderHint(QPainter.Antialiasing)
        self.setRenderHint(QPainter.SmoothPixmapTransform)
        self.setRenderHint(QPainter.TextAntialiasing)

        # 设置视图属性
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setFrameStyle(0)

        # 设置黑色背景
        self.setStyleSheet("background-color: black;")

        self.scene = QGraphicsScene()
        self.setScene(self.scene)

        # 存储图形项
        self.background_item = None
        self.character_items = {}

        self.bg_pos = background_pos
        self.pending_animations = []  # 临时存储待启动的动画
        self.active_animations = []  # 存储正在进行的动画，防止被GC回收

    def update_bg_pos(self, bg_pos=[0,0]):
        self.bg_pos = bg_pos

    def set_background(self, pixmap: QPixmap, changeEffect=None):
        """设置背景图片"""
        if self.background_item:
            self.scene.removeItem(self.background_item)

        # 创建专门的背景控件
        self.background_item = BackgroundPixmapItem(pixmap)
        self.scene.addItem(self.background_item)

        # 调整背景大小以适应视图
        self.fit_background()

        # 如果有转场效果，添加到待启动列表
        if changeEffect:
            self.prepare_change_effect(None, changeEffect, "add", "bg")

    def fit_background(self):
        """调整背景适应视图大小"""
        if self.background_item and self.sceneRect().isValid():
            # 获取视图大小
            view_size = self.size()
            # 调整背景大小
            self.background_item.resize_to_fit_window(view_size.width(), view_size.height(), self.bg_pos)

    def add_character(self, char_id: str, pixmap: QPixmap, pos: List[int], zoom: float = 1.0, animations: List = None, changeEffect=None):
        """添加角色，支持缩放和动画"""
        if char_id in self.character_items:
            self.remove_character(char_id)

        # 创建支持动画的图形项
        item = AnimatedPixmapItem(pixmap)
        item.set_original_position(QPointF(pos[0], pos[1]))
        item.set_zoom(zoom)

        if animations:
            item.set_animations(animations)

        self.scene.addItem(item)
        self.character_items[char_id] = item

        # 如果有转场效果，添加到待启动列表
        if changeEffect:
            self.prepare_change_effect(char_id, changeEffect, "add", "character")

    def prepare_change_effect(self, char_id=None, changeEffect=None, mode="remove", item="character"):
        """准备转场效果，但不立即启动动画"""
        if changeEffect == "gradient":
            if item == "character":
                if char_id not in self.character_items:
                    return
                target_item = self.character_items[char_id]
            elif item == "bg":
                if not self.background_item:
                    return
                target_item = self.background_item
            else:
                return

            # 创建或获取 opacity effect
            effect = target_item.graphicsEffect()
            if effect is None or not isinstance(effect, QGraphicsOpacityEffect):
                effect = QGraphicsOpacityEffect()
                target_item.setGraphicsEffect(effect)

            # 设置初始值
            start_value = 1.0 if mode == "remove" else 0.0
            end_value = 0.0 if mode == "remove" else 1.0

            # 创建动画，但不启动
            animate = QPropertyAnimation(effect, b"opacity")
            animate.setDuration(1000)
            animate.setStartValue(start_value)
            animate.setEndValue(end_value)
            animate.setEasingCurve(QEasingCurve.InOutQuad)

            if mode == "remove":
                def on_finished():
                    if item == "character":
                        self.remove_character(char_id)
                    elif item == "bg":
                        self.clear_bg()
                animate.finished.connect(on_finished)

            # 将动画添加到待启动列表
            self.pending_animations.append(animate)

    def start_pending_animations(self):
        """启动所有待启动的动画"""
        for animate in self.pending_animations:
            self.active_animations.append(animate)
            animate.finished.connect(lambda a=animate: self.active_animations.remove(a) if a in self.active_animations else None)
            animate.start()
        self.pending_animations.clear()

    def remove_character(self, char_id: str):
        """移除角色"""
        if char_id in self.character_items:
            # 停止角色动画
            character_item = self.character_items[char_id]
            if hasattr(character_item, 'animation_timer'):
                character_item.animation_timer.stop()

            self.scene.removeItem(self.character_items[char_id])
            del self.character_items[char_id]

    def clear_characters(self):
        """清除所有角色"""
        for char_id in list(self.character_items.keys()):
            self.remove_character(char_id)

    def clear_bg(self):
        if self.background_item:
            self.scene.removeItem(self.background_item)
            self.background_item = None

    def clear_all(self):
        """清除所有元素（背景和角色）"""
        self.clear_characters()
        if self.background_item:
            self.scene.removeItem(self.background_item)
            self.background_item = None

    def resizeEvent(self, event):
        """重写 resize 事件以保持背景适应"""
        super().resizeEvent(event)
        self.fit_background()


class GalGameWindow(QMainWindow):
    """Galgame 主窗口"""
    def __init__(self):
        super().__init__()
        self.story_data = None
        self.current_page = 0
        self.current_scene_index = 0
        self.loaded_resources = {}
        self.base_path = Path(".")
        self.current_page_data = []

        # 新增：播放状态控制
        self.is_text_finished = False  # 字幕是否播放完成
        self.is_audio_finished = False  # 音频是否播放完成
        self.audio_timer = QTimer()  # 模拟音频播放
        self.audio_timer.setSingleShot(True)
        self.audio_timer.timeout.connect(self.on_audio_finished)

        # 新增：自动播放开关
        self.auto_play = False  # 默认为关闭自动播放
        self.is_waiting_for_next_page = False  # 标记是否在等待进入下一页

        # 新增：UI设置
        self.ui_settings = {
            "chatbox_style": None,  # 字幕框样式图片路径
            "name_show_region": [[76, 60], [270, 149]],  # 名字显示区域，默认值
            "words_show_region": [[310, 60], [805, 149]]  # 文本显示区域，默认值
        }

        # UI控件
        self.name_label = None
        self.text_display = None
        self.chatbox_item = None

        self.setup_ui()
        self.load_story_file()

        self.window_size=[1280,720]
        self.background_pos=[0,0]

    def setup_ui(self):
        """设置用户界面"""
        self.setWindowTitle("GalPie")
        self.setGeometry(100, 100, 1280, 720)

        # 设置窗口背景为黑色
        self.setStyleSheet("background-color: black;")

        # 中央控件
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        # 主布局
        layout = QVBoxLayout(central_widget)
        layout.setContentsMargins(0, 0, 0, 0)

        # 图形视图
        self.graphics_view = GraphicsView()
        layout.addWidget(self.graphics_view)

        # 确保窗口可以接收焦点和鼠标事件
        self.setFocusPolicy(Qt.StrongFocus)
        self.graphics_view.setFocusPolicy(Qt.NoFocus)  # 防止图形视图抢焦点

    def setup_dialog_area(self):
        """设置对话框区域 - 在加载JSON后调用"""
        # 清除已有的对话框区域
        if self.chatbox_item:
            self.graphics_view.scene.removeItem(self.chatbox_item)
            self.chatbox_item = None

        # 加载UI设置
        self.load_ui_settings()

        # 获取窗口尺寸
        window_width, window_height = 1280, 720
        if self.story_data and "settings" in self.story_data:
            window_size = self.story_data["settings"].get("window_size", "1280x720")
            window_width, window_height = map(int, window_size.split('x'))

        chatbox_pos = [0, 0]

        # 创建对话框背景
        if self.ui_settings["chatbox_style"]:
            # 使用自定义字幕框样式
            chatbox_path = self.base_path / self.ui_settings["chatbox_style"]
            chatbox_pixmap = self.load_pixmap(str(chatbox_path))
            if chatbox_pixmap and not chatbox_pixmap.isNull():
                # 创建自定义字幕框
                self.chatbox_item = QGraphicsPixmapItem(chatbox_pixmap)
                # 计算居中位置
                chatbox_pos = [
                    (window_width - chatbox_pixmap.width()) // 2,
                    window_height - chatbox_pixmap.height()
                ]
                self.chatbox_item.setPos(chatbox_pos[0], chatbox_pos[1])  # 对话框位置
                self.chatbox_item.setZValue(10)  # 确保在最上层
                self.graphics_view.scene.addItem(self.chatbox_item)
                print(f"使用自定义字幕框样式: {self.ui_settings['chatbox_style']}")
            else:
                # 如果自定义样式加载失败，使用默认样式
                print(f"无法加载自定义字幕框样式，使用默认样式")
                self.create_default_chatbox(window_width, window_height)
        else:
            # 使用默认字幕框样式
            self.create_default_chatbox(window_width, window_height)

        # 名字显示区域
        name_region = self.ui_settings["name_show_region"]
        name_pos = name_region[0]  # 名字显示区域的左上角坐标
        name_size = [name_region[1][0] - name_region[0][0], name_region[1][1] - name_region[0][1]]  # 名字显示区域的大小

        # 文本显示区域
        words_region = self.ui_settings["words_show_region"]
        words_pos = words_region[0]  # 文本显示区域的左上角坐标
        words_size = [words_region[1][0] - words_region[0][0], words_region[1][1] - words_region[0][1]]  # 文本显示区域的大小

        # 如果名字标签不存在，创建它
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

            # 创建代理控件添加到场景中
            name_widget_proxy = self.graphics_view.scene.addWidget(self.name_label)
            name_widget_proxy.setZValue(12)  # 确保在背景之上
        else:
            # 更新名字标签大小
            self.name_label.setFixedSize(name_size[0], name_size[1])

        # 设置名字标签位置
        name_widget_proxy = self.name_label.graphicsProxyWidget()
        if name_widget_proxy:
            name_widget_proxy.setPos(chatbox_pos[0] + name_pos[0], chatbox_pos[1] + name_pos[1])

        # 如果文本显示控件不存在，创建它
        if not self.text_display:
            self.text_display = TextDisplayWidget()
            self.text_display.setFixedSize(words_size[0], words_size[1])

            # 创建代理控件添加到场景中
            text_widget_proxy = self.graphics_view.scene.addWidget(self.text_display)
            text_widget_proxy.setZValue(12)  # 确保在背景之上

            # 确保文本控件不会拦截鼠标事件
            self.text_display.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        else:
            # 更新文本显示控件大小
            self.text_display.setFixedSize(words_size[0], words_size[1])

        # 设置文本显示控件位置
        text_widget_proxy = self.text_display.graphicsProxyWidget()
        if text_widget_proxy:
            text_widget_proxy.setPos(chatbox_pos[0] + words_pos[0], chatbox_pos[1] + words_pos[1])

    def create_default_chatbox(self, window_width: int, window_height: int):
        """创建默认字幕框样式"""
        # 创建对话框背景（半透明黑色矩形）
        dialog_bg = QGraphicsRectItem(0, 0, 1280, 220)
        dialog_bg.setBrush(QBrush(QColor(0, 0, 0, 180)))
        dialog_bg.setPen(QPen(Qt.NoPen))
        dialog_bg.setPos((window_width - 1280) // 2, window_height - 220)  # 居中贴底
        dialog_bg.setZValue(10)  # 确保在最上层
        self.graphics_view.scene.addItem(dialog_bg)
        self.chatbox_item = dialog_bg

        # 名字显示区域背景
        name_bg = QGraphicsRectItem(0, 0, 200, 40)
        name_bg.setBrush(QBrush(QColor(0, 0, 0, 150)))
        name_bg.setPen(QPen(Qt.NoPen))
        name_bg.setPos((window_width - 1280) // 2 + 76, window_height - 220 + 20)  # 根据JSON中的位置调整
        name_bg.setZValue(11)
        self.graphics_view.scene.addItem(name_bg)

    def load_ui_settings(self):
        """加载UI设置"""
        if not self.story_data or "ui" not in self.story_data:
            print("使用默认UI设置")
            return

        ui_data = self.story_data["ui"]

        if "chatbox_and_words_position" in ui_data:
            chatbox_data = ui_data["chatbox_and_words_position"]

            # 加载字幕框样式图片
            if "chatbox" in chatbox_data:
                chatbox_path = chatbox_data["chatbox"]
                self.ui_settings["chatbox_style"] = chatbox_path
                print(f"加载字幕框样式: {chatbox_path}")

            # 加载名字显示区域
            if "name_show_region" in chatbox_data:
                self.ui_settings["name_show_region"] = chatbox_data["name_show_region"]
                print(f"加载名字显示区域: {self.ui_settings['name_show_region']}")

            # 加载文本显示区域
            if "words_show_region" in chatbox_data:
                self.ui_settings["words_show_region"] = chatbox_data["words_show_region"]
                print(f"加载文本显示区域: {self.ui_settings['words_show_region']}")

    def showEvent(self, event):
        """窗口显示时确保获得焦点"""
        super().showEvent(event)
        self.setFocus()

    def load_story_file(self):
        """加载故事文件"""
        story_dir = Path("story")
        json_files = list(story_dir.glob("*.json"))

        if json_files:
            # 自动加载第一个JSON文件
            self.load_json_file(json_files[0])
        else:
            # 弹出文件选择对话框
            self.show_file_selection_dialog()

    def show_file_selection_dialog(self):
        """显示文件选择对话框"""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "选择故事文件", "", "JSON Files (*.json)"
        )

        if file_path:
            self.load_json_file(Path(file_path))
        else:
            # 如果没有选择文件，退出程序
            QApplication.quit()

    def load_json_file(self, file_path: Path):
        """加载JSON文件"""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                self.story_data = json.load(f)

            # 设置基础路径为JSON文件所在目录
            self.base_path = file_path.parent

            # 应用设置
            self.apply_settings()

            # 设置对话框区域（在加载JSON后调用）
            self.setup_dialog_area()

            # 开始故事
            self.start_story()

        except Exception as e:
            print(f"加载JSON文件失败: {e}")
            self.show_file_selection_dialog()

    def apply_settings(self):
        """应用设置"""
        if not self.story_data:
            return

        settings = self.story_data.get("settings", {})

        if "window_title" in settings:
            self.setWindowTitle(settings["window_title"])

        if "window_size" in settings:
            self.window_size = list(map(int, settings["window_size"].split('x')))
            self.resize(self.window_size[0], self.window_size[1])

    def start_story(self):
        """开始故事"""
        self.current_page = 1
        self.current_scene_index = 0
        self.play_current_page()

    def play_current_page(self):
        """播放当前页"""
        if "story_and_position" not in self.story_data:
            print("JSON格式错误：缺少story_and_position")
            return

        story = self.story_data["story_and_position"].get("story", {})
        page_key = str(self.current_page)

        print(f"尝试播放页面: {page_key}")  # 调试信息

        if page_key not in story:
            # 故事结束
            print("故事结束")
            return

        page_data = story[page_key]
        self.current_page_data = page_data  # 保存当前页数据
        self.current_scene_index = 0
        self.is_waiting_for_next_page = False  # 重置等待标志

        # 立即播放场景序列，不添加任何延迟
        self.play_scene_sequence()

    def play_scene_sequence(self):
        """播放场景序列"""
        print(f"播放场景序列，当前场景索引: {self.current_scene_index}, 总场景数: {len(self.current_page_data)}")  # 调试信息

        if self.current_scene_index >= len(self.current_page_data):
            # 当前页所有场景播放完毕，准备下一页
            self.current_page += 1
            self.current_scene_index = 0
            print(f"准备下一页: {self.current_page}")  # 调试信息

            # 检查自动播放设置
            if self.auto_play:
                # 自动播放开启，立即进入下一页
                self.play_current_page()
            else:
                # 自动播放关闭，设置等待标志
                self.is_waiting_for_next_page = True
                print("自动播放已关闭，等待用户点击进入下一页")
            return

        scene = self.current_page_data[self.current_scene_index]
        self.execute_scene(scene)

    def execute_scene(self, scene: Dict):
        """执行单个场景"""
        print(f"执行场景 {self.current_scene_index}: {scene}")  # 调试信息

        # 重置播放状态
        self.is_text_finished = False
        self.is_audio_finished = False

        # 清除所有角色和背景（如果需要）
        if scene.get("clear_all", False):
            self.graphics_view.clear_all()

        # 设置背景
        if "bg" in scene:
            bg_name = scene["bg"]
            backgrounds = self.story_data["story_and_position"].get("backgrounds", {})
            if bg_name in backgrounds:
                bg_path = backgrounds[bg_name]
                full_bg_path = self.base_path / bg_path
                bg_pixmap = self.load_pixmap(str(full_bg_path))
                if bg_pixmap:
                    self.background_pos=[(self.window_size[0]-bg_pixmap.width())//2,0]
                    self.graphics_view.update_bg_pos(self.background_pos)
                    self.graphics_view.set_background(bg_pixmap, scene.get("change", None))
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

        # 启动所有待执行的动画
        self.graphics_view.start_pending_animations()

        # 显示对话内容
        if "content" in scene:
            content = scene["content"]
            self.display_dialog(content)

            # 检查是否有音频需要播放
            if self.has_audio(content):
                # 如果有音频，模拟音频播放
                audio_duration = 2000  # 默认2秒
                self.audio_timer.start(audio_duration)
            else:
                # 如果没有音频，立即标记音频完成
                print("场景中没有音频，立即标记音频完成")
                self.on_audio_finished()
        else:
            # 如果没有对话内容，直接标记为完成
            print("场景中没有对话内容，直接标记文本和音频完成")
            self.is_text_finished = True
            self.is_audio_finished = True
            self.check_auto_advance()

    def has_audio(self, content: Dict) -> bool:
        """检查场景是否有音频需要播放"""
        # 这里可以根据实际需要扩展音频检查逻辑
        # 目前暂时返回False，表示没有音频
        return False

    def setup_character(self, char_id: str, char_info: Dict, char_data: Dict, changeEffect=None):
        """设置角色 - 合并身体和面部，支持缩放和动画"""
        form_name = char_info["form"]
        face_info = char_info["face"]

        # 处理面部信息（可能是字符串或数组）
        if isinstance(face_info, list):
            face_name = face_info[0]
        else:
            face_name = face_info

        pos = [char_info["pos"][0]+self.background_pos[0], char_info["pos"][1]+self.background_pos[1]]
        zoom = char_info.get("zoom", 1.0)  # 默认缩放为1.0
        animations = char_info.get("animate", [])  # 动画配置

        # 加载服装（身体）
        form_pixmap = None
        if "form" in char_data and form_name in char_data["form"]:
            form_path = char_data["form"][form_name]
            full_form_path = self.base_path / form_path
            form_pixmap = self.load_pixmap(str(full_form_path))

        # 加载面部表情
        face_pixmap = None
        if "face" in char_data and face_name in char_data["face"]:
            face_path = char_data["face"][face_name]
            full_face_path = self.base_path / face_path
            face_pixmap = self.load_pixmap(str(full_face_path))

        # 合并身体和面部
        if form_pixmap and face_pixmap:
            # 创建一个新的QPixmap，大小与身体相同
            combined_pixmap = QPixmap(form_pixmap.size())
            combined_pixmap.fill(Qt.transparent)

            # 使用QPainter合并图片
            painter = QPainter(combined_pixmap)
            painter.setRenderHint(QPainter.Antialiasing)
            painter.setRenderHint(QPainter.SmoothPixmapTransform)

            # 先绘制身体
            painter.drawPixmap(0, 0, form_pixmap)

            # 再绘制面部
            painter.drawPixmap(0, 0, face_pixmap)

            painter.end()

            self.graphics_view.add_character(char_id, combined_pixmap, pos, zoom, animations, changeEffect)
        elif form_pixmap:
            # 只有身体，没有面部
            self.graphics_view.add_character(char_id, form_pixmap, pos, zoom, animations, changeEffect)
        elif face_pixmap:
            # 只有面部，没有身体
            self.graphics_view.add_character(char_id, face_pixmap, pos, zoom, animations, changeEffect)
        else:
            print(f"无法加载角色图片: {char_id}")

    def display_dialog(self, content: Dict):
        """显示对话"""
        # 获取说话人名字
        speaking_name = ""
        if "speaking_name" in content:
            char_id = content["speaking_name"]
            if char_id in self.story_data["story_and_position"]["character_and_motion"]:
                char_data = self.story_data["story_and_position"]["character_and_motion"][char_id]
                speaking_name = char_data["name"]["zh"]
        elif "speaking" in content:
            speaking_name = content["speaking"]["zh"]

        self.name_label.setText(speaking_name)

        # 获取对话文本
        words = content["words"]["zh"]

        # 设置文本显示完成后的回调
        self.text_display.set_text(words, self.on_text_display_complete)

    def on_text_display_complete(self):
        """文本显示完成后的回调函数"""
        print("文本显示完成")
        self.is_text_finished = True
        self.check_auto_advance()

    def on_audio_finished(self):
        """音频播放完成后的回调函数"""
        print("音频播放完成")
        self.is_audio_finished = True
        self.check_auto_advance()

    def check_auto_advance(self):
        """检查是否可以自动进入下一个场景"""
        print(f"检查自动前进: 文本完成={self.is_text_finished}, 音频完成={self.is_audio_finished}")  # 调试信息

        if self.is_text_finished and self.is_audio_finished:
            print("文本和音频都已完成，自动进入下一个场景")
            # 立即进入下一个场景，不添加任何延迟
            self.advance_to_next_scene()

    def advance_to_next_scene(self):
        """前进到下一个场景 - 移除所有延迟"""
        # 停止音频计时器
        self.audio_timer.stop()

        # 前进到下一个场景
        self.current_scene_index += 1

        # 立即播放场景序列，不添加延迟
        self.play_scene_sequence()

    def load_pixmap(self, path: str) -> Optional[QPixmap]:
        """加载图片资源"""
        if path in self.loaded_resources:
            return self.loaded_resources[path]

        try:
            # 检查文件是否存在
            if not os.path.exists(path):
                print(f"图片文件不存在: {path}")
                return None

            pixmap = QPixmap(path)
            if not pixmap.isNull():
                self.loaded_resources[path] = pixmap
                return pixmap
            else:
                print(f"加载图片失败，文件可能已损坏: {path}")
        except Exception as e:
            print(f"加载图片失败 {path}: {e}")

        return None
    
    def save_game(self):
        """存档"""
        settings=self.story_data.get("settings",{"window_title": "GalPie","identify_code": ""})
        
        # 数据结构：[窗口名, 识别码, 图片数据QPixmap->QByteArray, 页数, 说话人, 字幕, 日期, 时间]
        data=[settings.get("window_title", "GalPie").replace(" ","-").replace("_","+"), settings.get("identify_code", "").replace(" ","-").replace("_","+"), None, str(self.current_page-1), None, None, QDateTime.currentDateTime().toString("yyyy-MM-dd"), QDateTime.currentDateTime().toString("HH-mm-ss")]
        
        img=self.grab()
        byte_array = QByteArray()
        buffer = QBuffer(byte_array)
        buffer.open(QBuffer.WriteOnly)
        img.save(buffer, "PNG")
        save_img=byte_array.data()
        data[2]=save_img
        
        page=self.current_page-1
        page_content=self.story_data.get("story_and_position",{}).get("story",{}).get(str(page),None)[0].get("content",None)
        if page_content:
            if "speaking" in page_content:
                data[4]=page_content.get("speaking",None)
            else:
                data[4]=page_content.get("speaking_name",None)
            data[5]=page_content.get("words",None)
        
        if not os.path.exists("saves"):
            os.mkdir("saves")
        with open(f"./saves/{data[0]}_{data[1]}_{data[-2]}_{data[-1]}.gpsave","wb") as f:
            pickle.dump(data,f)

    def mousePressEvent(self, event):
        """鼠标点击事件处理"""
        print("鼠标点击事件触发")  # 调试信息
        if event.button() == Qt.LeftButton:
            self.handle_click()

    def keyPressEvent(self, event):
        """键盘事件处理 - 也支持空格键和回车键"""
        if event.key() in (Qt.Key_Space, Qt.Key_Return, Qt.Key_Enter):
            print("空格键或回车键按下")  # 调试信息
            self.handle_click()
        elif event.key() == Qt.Key_A:  # 按A键切换自动播放
            self.toggle_auto_play()
        elif event.key() == Qt.Key_F2:
            self.save_game()
        else:
            super().keyPressEvent(event)

    def toggle_auto_play(self):
        """切换自动播放开关"""
        self.auto_play = not self.auto_play
        status = "开启" if self.auto_play else "关闭"
        print(f"自动播放已{status}")

        # 如果自动播放开启且正在等待下一页，立即进入下一页
        if self.auto_play and self.is_waiting_for_next_page:
            self.play_current_page()

    def handle_click(self):
        """处理点击事件"""
        print(f"处理点击事件，文本完成: {self.is_text_finished}, 音频完成: {self.is_audio_finished}")  # 调试信息
        print(f"等待下一页: {self.is_waiting_for_next_page}")  # 调试信息

        # 检查是否在等待进入下一页
        if self.is_waiting_for_next_page:
            print("正在等待进入下一页，立即进入下一页")
            self.is_waiting_for_next_page = False
            self.play_current_page()
            return

        if not self.is_text_finished:
            # 如果文本没有显示完，立即完成显示
            print("文本未完成，立即完成显示")
            self.text_display.complete_display()
        elif not self.is_audio_finished:
            # 如果文本已完成但音频未完成，立即完成音频
            print("文本已完成，音频未完成，立即完成音频")
            self.on_audio_finished()
        else:
            # 文本和音频都已完成，进入下一个场景
            print("文本和音频都已完成，进入下一个场景")
            self.advance_to_next_scene()


def main():
    # 启用GPU加速
    QApplication.setAttribute(Qt.AA_UseOpenGLES)

    app = QApplication(sys.argv)

    # 创建故事目录（如果不存在）
    story_dir = Path("story")
    story_dir.mkdir(exist_ok=True)

    window = GalGameWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()