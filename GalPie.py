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
                               QTextEdit, QFrame, QGraphicsRectItem, QGraphicsTextItem)
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
        
        self.itemList=[]

        # 启用鼠标交互
        self.setMouseTracking(True)
        self.setInteractive(True)

    def mousePressEvent(self, event):
        """传递鼠标事件到父窗口"""
        self.parent().mousePressEvent(event)
    
    def mouseMoveEvent(self, event):
        """传递鼠标移动事件"""
        # 这里可以处理鼠标悬停效果
        super().mouseMoveEvent(event)

    def update_bg_pos(self, bg_pos=[0,0]):
        self.bg_pos = bg_pos

    def add_item(self,pixmap,pos=List[int]):
        item=pixmap
        if type(pixmap)==QPixmap:
            item=AnimatedPixmapItem(pixmap)
            item.set_original_position(QPointF(pos[0],pos[1]))
        self.itemList.append(item)
    
    def show_items(self,changeEffect=None):
        for i in self.itemList:
            self.scene.addItem(i)
        self.prepare_change_effect(None,changeEffect,"add",self.itemList)
    
    def clear_items(self):
        for i in self.itemList:
            self.scene.removeItem(i)
        self.itemList=[]

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
                target_items = [self.character_items[char_id]]
            elif item == "bg":
                if not self.background_item:
                    return
                target_items = [self.background_item]
            elif type(item)==list:
                target_items=item
            else:
                return

            for target_item in target_items:
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
            if animate is None:
                continue
            self.active_animations.append(animate)
            # 添加安全检查
            try:
                animate.finished.connect(lambda a=animate: self.active_animations.remove(a) if a in self.active_animations else None)
                animate.start()
            except Exception as e:
                print(f"启动动画失败: {e}")
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


class MenuButtonItem(QGraphicsPixmapItem):
    """开始菜单按钮项，支持鼠标悬停效果"""
    def __init__(self, normal_pixmap, hover_pixmap=None):
        super().__init__(normal_pixmap)
        self.normal_pixmap = normal_pixmap
        self.hover_pixmap = hover_pixmap or normal_pixmap
        self.is_hovered = False
        self.click_handler = None  # 明确初始化点击处理器

        # 启用悬停事件
        self.setAcceptHoverEvents(True)

    def hoverEnterEvent(self, event):
        """鼠标悬停进入事件"""
        self.is_hovered = True
        if self.hover_pixmap:
            self.setPixmap(self.hover_pixmap)
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event):
        """鼠标悬停离开事件"""
        self.is_hovered = False
        self.setPixmap(self.normal_pixmap)
        super().hoverLeaveEvent(event)

    def mousePressEvent(self, event):
        """鼠标点击事件"""
        if event.button() == Qt.LeftButton and self.click_handler:
            self.click_handler()
        super().mousePressEvent(event)

    def set_click_handler(self, handler):
        """设置点击处理函数"""
        self.click_handler = handler


class GalGameWindow(QMainWindow):
    """Galgame 主窗口"""
    def __init__(self):
        super().__init__()
        self.story_data = None
        self.current_page = 0
        self.current_scene_index = 0
        self.current_storyline_id = None
        self.loaded_resources = {}
        self.base_path = Path(".")
        self.current_page_data = []
    
        # 新增：开始菜单相关
        self.is_in_menu = False  # 初始化为False，加载JSON后根据配置设置
        self.start_button = None
        self.title_item = None
        self.menu_bg_item = None
    
        # 播放状态控制
        self.is_text_finished = False
        self.is_audio_finished = False
        self.audio_timer = QTimer()
        self.audio_timer.setSingleShot(True)
    
        # 确保audio_timer不为None后再连接信号
        if self.audio_timer:
            self.audio_timer.timeout.connect(self.on_audio_finished)
    
        # 自动播放开关
        self.auto_play = False
        self.is_waiting_for_next_page = False
    
        # UI设置
        self.ui_settings = {
            "chatbox_style": None,
            "name_show_region": [[76, 60], [270, 149]],
            "words_show_region": [[310, 60], [805, 149]]
        }
    
        # UI控件
        self.name_label = None
        self.text_display = None
        self.chatbox_item = None
    
        self.setup_ui()
        self.load_story_file()
    
        self.window_size = [1280, 720]
        self.background_pos = [0, 0]
        
        self.language=None

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
        # 允许图形视图接收鼠标事件
        self.graphics_view.setFocusPolicy(Qt.StrongFocus)
        self.graphics_view.setMouseTracking(True)  # 启用鼠标跟踪

    def show_menu(self):
        """显示开始菜单"""
        self.is_in_menu = True
    
        # 清除场景中的所有项
        self.graphics_view.scene.clear()
    
        # 确保story_data存在
        if not self.story_data or "menu" not in self.story_data:
            print("错误：没有找到菜单配置")
            # 这里不应该直接开始故事，而是应该抛出异常或返回
            return
    
        try:
            # 加载菜单配置
            menu_data = self.story_data["menu"]
    
            # 设置菜单背景
            if "bg" in menu_data:
                bg_data = menu_data["bg"]
                full_bg_path = self.base_path / bg_data
                bg_pixmap = self.load_pixmap(str(full_bg_path))
                if bg_pixmap:
                    self.graphics_view.add_item(bg_pixmap,[(self.window_size[0]-bg_pixmap.width())//2, 0])
    
            # 设置标题（如果有）
            if "title" in menu_data:
                title_path = menu_data["title"][self.language]
                full_title_path = self.base_path / title_path
                title_pixmap = self.load_pixmap(str(full_title_path))
                if title_pixmap:
                    menu_pos = menu_data.get("menu_pos", {})
                    title_pos = menu_pos.get("title", [54, 48])
                    self.graphics_view.add_item(title_pixmap,title_pos)
    
            # 创建开始按钮
            self.create_start_button(menu_data)
            # self.graphics_view.show_items(menu_data.get("change",[[],None])[1])
            # self.graphics_view.start_pending_animations()
    
        except Exception as e:
            print(f"显示开始菜单失败: {e}")
            # 菜单显示失败，但不要直接开始故事
            # 可以显示错误信息或保持当前状态
            import traceback
            traceback.print_exc()

    def create_start_button(self, menu_data):
        """创建开始按钮"""
        # 加载按钮图片
        button_path = menu_data["button"]
        full_button_path = self.base_path / button_path
        button_pixmap = self.load_pixmap(str(full_button_path))
    
        if not button_pixmap:
            print(f"无法加载按钮图片: {full_button_path}")
            return
    
        # 加载按钮触碰图片（如果有）
        button_touched_path = menu_data.get("button_touched")
        touched_pixmap = None
        if button_touched_path:
            full_touched_path = self.base_path / button_touched_path
            touched_pixmap = self.load_pixmap(str(full_touched_path))
    
        # 获取按钮位置
        menu_pos = menu_data.get("menu_pos", {})
        button_data = menu_pos.get("start", [[115, 230],{self.language:"Game start"}])
        button_pos=button_data[0]
    
        # 创建按钮图形项
        self.start_button = MenuButtonItem(button_pixmap, touched_pixmap)
        if not self.start_button:
            print("创建开始按钮失败")
            return
    
        self.start_button.setPos(button_pos[0], button_pos[1])
        self.start_button.setZValue(2)
    
        # 确保clicked属性存在
        if not hasattr(self.start_button, 'clicked'):
            self.start_button.clicked = None
    
        # 设置点击处理程序
        self.start_button.set_click_handler(self.on_start_button_clicked)
        self.graphics_view.add_item(self.start_button,button_pos)
    
        # 添加开始游戏文字
        text_rgb = menu_data.get("text_rgb", [255, 255, 255])
        text_color = QColor(text_rgb[0], text_rgb[1], text_rgb[2])
    
        # 计算文字位置（居中于按钮）
        text_x = button_pos[0] + button_pixmap.width() // 2
        text_y = button_pos[1] + button_pixmap.height() // 2
    
        text_item = QGraphicsTextItem("开始游戏")
        text_item.setDefaultTextColor(text_color)
        text_item.setFont(QFont("Microsoft YaHei", 14, QFont.Bold))
    
        # 文字居中
        text_rect = text_item.boundingRect()
        text_item.setPos(text_x - text_rect.width() / 2, text_y - text_rect.height() / 2)
        text_item.setZValue(3)

        self.graphics_view.add_item(text_item)
        
        self.graphics_view.show_items(menu_data.get("change",[[],None])[1])
        self.graphics_view.start_pending_animations()

    def on_start_button_clicked(self):
        """开始按钮点击事件"""
        if self.is_in_menu:
            print("开始按钮被点击，准备淡出菜单")
            self.fade_out_menu()
    
    def fade_out_menu(self):
        """淡出开始菜单"""
        self.is_in_menu = False
        
        # 设置黑场过渡
        black=QPixmap(self.window_size[0],self.window_size[1])
        black.fill(QColor(0,0,0))
        
        self.graphics_view.clear_items()
        
        self.graphics_view.add_item(black,[0,0])
        self.graphics_view.show_items("gradient")
        self.graphics_view.start_pending_animations()
    
        # 设置黑场过渡时间，过渡后切换到游戏
        QTimer.singleShot(1500, self.start_game_after_fade)

    def start_game_after_fade(self):
        """淡出完成后开始游戏"""
        # 清除开始菜单的所有项
        self.graphics_view.clear_items()
    
        # 设置对话框区域
        self.setup_dialog_area()
    
        # 开始故事 - 但不要重复调用start_story()
        # 因为start_story()已经在其他地方被调用
        # 这里只需要重置状态并播放当前页
        self.current_page = 1
        self.current_scene_index = 0
        self.play_current_page()

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
    
            # 检查是否有开始菜单配置
            if "menu" in self.story_data:
                # 显示开始菜单
                self.show_menu()
                # 重要：显示开始菜单后直接返回，不要开始故事
                return
            else:
                # 没有开始菜单，直接开始故事
                self.setup_dialog_area()
                self.start_story()
    
        except Exception as e:
            print(f"加载JSON文件失败: {e}")
            import traceback
            traceback.print_exc()
            self.show_file_selection_dialog()

    def apply_settings(self):
        """应用设置"""
        if not self.story_data:
            return

        settings = self.story_data.get("settings", {})
        
        self.language=settings["language"][0]

        if "window_title" in settings:
            self.setWindowTitle(settings["window_title"])

        if "window_size" in settings:
            self.window_size = list(map(int, settings["window_size"].split('x')))
            self.resize(self.window_size[0], self.window_size[1])

    def start_story(self):
        """开始故事"""
        # 检查是否在开始菜单中
        if self.is_in_menu:
            print("警告：在开始菜单中尝试开始故事，已阻止")
            return
    
        self.goto_storyline_by_check_value()
        self.play_current_page()

    def goto_storyline_by_check_value(self):
        """根据storyline_id的值，获取最大值的故事线"""
        self.current_page = 1
        self.current_scene_index = 0
    
        # 检查是否有storyline_id配置
        storyline_data = self.story_data.get("story_and_position", {}).get("storyline_id", {})
        if storyline_data:
            # 获取storyline_id的最大值
            self.current_storyline_id = max(storyline_data, key=storyline_data.get)
    
            # 获取该故事线的第一页
            story = self.story_data["story_and_position"].get("story", {}).get(self.current_storyline_id, {})
            if story:
                first_page = next(iter(story))
                self.current_page = int(first_page)
        else:
            # 如果没有storyline_id配置，使用默认值
            self.current_storyline_id = "main"

    def play_current_page(self, specify_scene=None):
        """播放当前页"""
        # 检查是否在开始菜单中，如果是则不要开始游戏
        if self.is_in_menu:
            print("警告：在开始菜单中尝试播放页面，已阻止")
            return
    
        if "story_and_position" not in self.story_data:
            print("JSON格式错误：缺少story_and_position")
            return
    
        # 获取当前故事线
        if not self.current_storyline_id:
            self.goto_storyline_by_check_value()
    
        story = self.story_data["story_and_position"].get("story", {}).get(self.current_storyline_id,{})
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
        self.play_scene_sequence(specify_scene)

    def play_scene_sequence(self, specify_scene=None):
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

        scene = specify_scene
        if scene==None:
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
        
        # 数据结构：[窗口名, 识别码, 图片数据QPixmap->QByteArray, 当前storyline_id的各个值, storylineID, 页数, 说话人, 字幕, 日期, 时间]
        data=[settings.get("window_title", "GalPie").replace(" ","-").replace("_","+"), settings.get("identify_code", "").replace(" ","-").replace("_","+"), None, self.story_data.get("story_and_position",{}).get("storyline_id", None), self.current_storyline_id, str(self.current_page-1), None, None, QDateTime.currentDateTime().toString("yyyy-MM-dd"), QDateTime.currentDateTime().toString("HH-mm-ss")]
        
        # 截取窗口画面，并以二进制数据保存
        img=self.grab()
        byte_array = QByteArray()
        buffer = QBuffer(byte_array)
        buffer.open(QBuffer.WriteOnly)
        img.save(buffer, "PNG")
        save_img=byte_array.data()
        data[2]=save_img
        
        # 获取读取页的说话人和字幕
        page=self.current_page-1
        page_content=self.story_data.get("story_and_position",{}).get("story",{}).get(self.current_storyline_id,{}).get(str(page),None)[0].get("content",None)
        if page_content:
            if "speaking" in page_content:
                data[6]=page_content.get("speaking",None)
            else:
                data[6]=page_content.get("speaking_name",None)
            data[7]=page_content.get("words",None)
        
        # 保存存档文件
        if not os.path.exists("saves"):
            os.mkdir("saves")
        with open(f"./saves/{data[0]}_{data[1]}_{data[-2]}_{data[-1]}.gpsave","wb") as f:
            pickle.dump(data,f)
    
    def load_save(self, load_file_name=None):
        """读取存档"""
        if not load_file_name:
            # 未指定读取文件，读取最新存档（快速读档）
            save_files=self.get_this_story_saves_new_to_old()
            with open("./saves/"+save_files[0],"rb") as f:
                data=pickle.load(f)
            if data[3]:
                self.story_data["story_and_position"]["storyline_id"]=data[3]
            self.current_storyline_id=data[4]
            self.current_page=int(data[5])
            self.current_scene_index=0
            scene=self.build_last_scene()
            self.play_current_page(specify_scene=scene)
            self.play_current_page()
            return
    
    def build_last_scene(self):
        """场景回溯"""
        page=self.current_page
        scene=None
        first_page=next(iter(self.story_data.get("story_and_position",{}).get("story",{}).get(self.current_storyline_id,None)))
        if not first_page:
            first_page=str(page)
        current_storyline_story=self.story_data.get("story_and_position",{}).get("story",{}).get(self.current_storyline_id,None)

        # 获取上一个clear_all=true的场景
        now_scene=current_storyline_story.get(str(page),{})
        now_scene_clear_all=False
        while scene==None and str(page)!=first_page and not now_scene_clear_all:
            page-=1
            now_scene=current_storyline_story.get(str(page),{})
            for i in now_scene:
                if i.get("clear_all",False):
                    scene=now_scene
        
        # 若非本页，计算最终背景和角色状态
        if page!=self.current_page:
            page-=1
        while page!=self.current_page:
            page+=1
            now_scene=current_storyline_story.get(str(page),{})
            for i in now_scene:
                if i.get("bg",None):
                    scene[0]["bg"]=i.get("bg",None)
                if i.get("characters",None):
                    scene[0]["characters"]=i.get("characters",None)
                    for j in i.get("characters",None):
                        if i["characters"][j].get("animate",None):
                            for k in i["characters"][j].get("animate",None):
                                for l in k:
                                    if l.get("zoom",None):
                                        scene[0]["characters"][j]["zoom"]=l.get("zoom",None)
                                    if l.get("move",None):
                                        now_pos=scene[0]["characters"][j]["pos"]
                                        animate_pos=l.get("move",[[0,0]])+[now_pos]
                                        scene[0]["characters"][j]["pos"]=list(map(lambda *args: sum(args), *animate_pos))
        
        # 去除多余的场景内容
        if scene:
            scene=scene[0]
            scene["clear_all"]=True
            if not current_storyline_story.get(str(self.current_page), {})[0].get("change",None) and scene.get("change",None):
                del scene["change"]
            if "characters" in scene:
                for i in scene["characters"]:
                    if "animate" in scene["characters"][i]:
                        del scene["characters"][i]["animate"]
            scene["content"]={}
            scene["content"]["speaking"]={}
            scene["content"]["words"]={}
            for i in self.story_data["settings"]["language"]:
                scene["content"]["speaking"][i]=""
                scene["content"]["words"][i]=""
        
        return scene
    
    def get_this_story_saves_new_to_old(self, save_dir="./saves", content_check=False):
        """获取当前剧情的存档列表，从新至旧"""
        settings=self.story_data.get("settings",{"window_title": "GalPie","identify_code": ""})
        story_name=settings.get("window_title", "GalPie").replace(" ","-").replace("_","+")
        story_id=settings.get("identify_code", "").replace(" ","-").replace("_","+")
        result=[]
        processing={}

        if content_check:
            # 从文件内容检查，是否为该本剧情的存档文件
            for i in os.listdir(save_dir):
                if os.path.splitext(i)[-1]==".gpsave":
                    with open(i,"rb") as f:
                        data=pickle.load(f)
                    if data[0]==story_name and data[1]==story_id:
                        time_number_str=data[-2].replace("-","")+data[-1].replace("-","")
                        result.append(int(time_number_str))
                        processing[time_number_str]=i
        else:
            # 从文件名检查，是否为该本剧情的存档文件
            for i in os.listdir(save_dir):
                file_name_check=i.split("_")
                if os.path.splitext(i)[-1]==".gpsave" and file_name_check[0]==story_name and file_name_check[1]==story_id:
                    time_number_str=file_name_check[-2].replace("-","")+file_name_check[-1][0:-7].replace("-","")
                    result.append(int(time_number_str))
                    processing[time_number_str]=i
        
        # 进行时间排序，从新到旧
        result.sort(reverse=True)
        for i in range(len(result)):
            result[i]=processing[str(result[i])]
        
        return result

    def mousePressEvent(self, event):
        """鼠标点击事件处理"""
        print("鼠标点击事件触发")  # 调试信息
    
        if self.is_in_menu:
            # 在开始菜单中，点击任意位置触发开始游戏
            if event.button() == Qt.LeftButton:
                self.on_start_button_clicked()
            return
    
        if event.button() == Qt.LeftButton:
            self.handle_click()

    def keyPressEvent(self, event):
        """键盘事件处理 - 也支持空格键和回车键"""
        if self.is_in_menu:
            # 在开始菜单中，空格键和回车键也触发开始游戏
            if event.key() in (Qt.Key_Space, Qt.Key_Return, Qt.Key_Enter):
                self.on_start_button_clicked()
            return
        else:
            if event.key() in (Qt.Key_Space, Qt.Key_Return, Qt.Key_Enter):
                print("空格键或回车键按下")  # 调试信息
                self.handle_click()
            elif event.key() == Qt.Key_A:  # 按A键切换自动播放
                self.toggle_auto_play()
            elif event.key() == Qt.Key_F2: # F2键保存游戏
                self.save_game()
            elif event.key() == Qt.Key_F3: # F3键加载最新存档
                self.load_save()
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