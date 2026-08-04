from typing import List, Dict
from PySide6.QtWidgets import QGraphicsView, QGraphicsScene, QGraphicsPixmapItem, QGraphicsOpacityEffect
from PySide6.QtOpenGLWidgets import QOpenGLWidget
from PySide6.QtCore import Qt, QTimer, QPointF, QPropertyAnimation, QEasingCurve
from PySide6.QtGui import QPixmap, QPainter, QTransform

from ui.animations import ease_in_out


class BackgroundPixmapItem(QGraphicsPixmapItem):
    """背景图片控件"""
    def __init__(self, pixmap=None):
        super().__init__(pixmap)
        self.original_pixmap = pixmap
        self.setZValue(-1)

    def set_pixmap(self, pixmap: QPixmap):
        self.original_pixmap = pixmap
        self.setPixmap(pixmap)

    def resize_to_fit_window(self, width: int, height: int, bg_pos=[0, 0]):
        if self.original_pixmap and not self.original_pixmap.isNull():
            scaled_pixmap = self.original_pixmap.scaled(
                width, height, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation
            )
            self.setPixmap(scaled_pixmap)
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
        self.animation_start_zoom = 1.0
        self.animation_start_pos = QPointF(0, 0)

    def set_zoom(self, zoom: float):
        self.current_zoom = zoom
        # 用 transform 缩放（GPU 变换，无 CPU 重采样）：左上角固定，向右下扩展
        # 与之前 setPixmap(scaled) 的左上角锚定行为一致，动画每帧不再重采样图片
        self.setTransform(QTransform().scale(zoom, zoom))

    def set_animations(self, animations: List):
        self.animations = animations
        if animations:
            self.start_animation_group(0)

    def start_animation_group(self, group_index: int):
        if group_index >= len(self.animations):
            return
        self.current_animation_group = self.animations[group_index]
        self.animation_start_time = 0
        self.animation_progress = 0
        self.animation_start_zoom = self.current_zoom
        self.animation_start_pos = self.pos()
        self.animation_timer.start(16)

    def update_animation(self):
        if not self.current_animation_group:
            self.animation_timer.stop()
            return
        self.animation_progress += 16
        group_duration = max(anim.get("time", 0) * 1000 for anim in self.current_animation_group)
        if self.animation_progress >= group_duration:
            current_index = self.animations.index(self.current_animation_group)
            self.start_animation_group(current_index + 1)
            return
        for animation in self.current_animation_group:
            self.apply_animation(animation)

    def apply_animation(self, animation: Dict):
        duration = animation.get("time", 0) * 1000
        if duration == 0:
            return
        progress = min(self.animation_progress / duration, 1.0)
        eased_progress = ease_in_out(progress)
        if "zoom" in animation:
            target_zoom = animation["zoom"]
            current_zoom = self.animation_start_zoom + (target_zoom - self.animation_start_zoom) * eased_progress
            self.set_zoom(current_zoom)
        if "move" in animation:
            move_path = animation["move"]
            if move_path and len(move_path) > 0:
                points_count = len(move_path)
                point_index = min(int(progress * points_count), points_count - 1)
                move_offset = move_path[point_index]
                new_pos = QPointF(
                    self.animation_start_pos.x() + move_offset[0],
                    self.animation_start_pos.y() + move_offset[1]
                )
                self.setPos(new_pos)

    def set_original_position(self, pos: QPointF):
        self.original_pos = pos
        self.setPos(pos)


class MenuButtonItem(QGraphicsPixmapItem):
    """开始菜单按钮项，支持鼠标悬停效果"""
    def __init__(self, normal_pixmap, hover_pixmap=None):
        super().__init__(normal_pixmap)
        self.normal_pixmap = normal_pixmap
        self.hover_pixmap = hover_pixmap or normal_pixmap
        self.is_hovered = False
        self.click_handler = None
        self.setAcceptHoverEvents(True)
        self.setCursor(Qt.ArrowCursor)  # 悬停保持箭头光标，避免文本默认 IBeam

    def hoverEnterEvent(self, event):
        self.is_hovered = True
        if self.hover_pixmap:
            self.setPixmap(self.hover_pixmap)
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event):
        self.is_hovered = False
        self.setPixmap(self.normal_pixmap)
        super().hoverLeaveEvent(event)

    def reset_hover(self):
        """重置悬停状态（退出设置界面等场景调用，避免返回时残留白框）。"""
        self.is_hovered = False
        self.setPixmap(self.normal_pixmap)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self.click_handler:
            self.click_handler()
            event.accept()
            return
        super().mousePressEvent(event)

    def set_click_handler(self, handler):
        self.click_handler = handler


class GraphicsView(QGraphicsView):
    """支持GPU加速的图形视图。

    场景使用固定逻辑分辨率（logical_size，默认 1280x720），所有场景元素
    按逻辑坐标定位；窗口实际尺寸变化时通过 fitInView 等比缩放填满视口。
    """
    def __init__(self, parent=None, background_pos=[0, 0], logical_size=[1280, 720]):
        super().__init__(parent)
        self.setViewport(QOpenGLWidget())
        self.setRenderHint(QPainter.Antialiasing)
        self.setRenderHint(QPainter.SmoothPixmapTransform)
        self.setRenderHint(QPainter.TextAntialiasing)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setFrameStyle(0)
        self.setStyleSheet("background-color: black;")
        self.scene = QGraphicsScene()
        self.logical_size = list(logical_size)
        # 固定逻辑场景矩形：所有元素按此坐标定位
        self.scene.setSceneRect(0, 0, self.logical_size[0], self.logical_size[1])
        self.setScene(self.scene)
        self.background_item = None
        self.character_items = {}
        self.bg_pos = background_pos
        self.pending_animations = []
        self.active_animations = []
        self.itemList = []
        self.setMouseTracking(True)
        self.setInteractive(True)
        # 只重绘变化区域（默认 FullViewportUpdate 每帧全量重绘，虚拟显卡下开销大）
        self.setViewportUpdateMode(QGraphicsView.BoundingRectViewportUpdate)
        # OpenGL viewport 可能忽略 item 光标：兜底强制箭头，避免悬停文本时 IBeam
        self.setCursor(Qt.ArrowCursor)
        self.viewport().setCursor(Qt.ArrowCursor)
        # 初始适配窗口
        self.fit_logical_rect()

    def fit_logical_rect(self):
        """将逻辑场景矩形等比缩放填满当前视口（超出部分裁切）。"""
        self.fitInView(0, 0, self.logical_size[0], self.logical_size[1],
                       Qt.KeepAspectRatioByExpanding)

    def set_logical_size(self, w, h):
        """更新逻辑分辨率并重建场景矩形。"""
        self.logical_size = [w, h]
        self.scene.setSceneRect(0, 0, w, h)
        self.fit_logical_rect()

    def mousePressEvent(self, event):
        super().mousePressEvent(event)
        if event.isAccepted():
            return
        self.parent().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        super().mouseMoveEvent(event)
        # 强制箭头光标：QGraphicsScene 悬停文本/按钮时可能把 viewport 光标改为
        # IBeam 等（尤其 OpenGL viewport 下），这里每次鼠标移动都覆盖回来
        if self.viewport().cursor().shape() != Qt.CursorShape.ArrowCursor:
            self.viewport().setCursor(Qt.ArrowCursor)
        self.setCursor(Qt.ArrowCursor)

    def update_bg_pos(self, bg_pos=[0, 0]):
        self.bg_pos = bg_pos

    def add_item(self, pixmap, pos=List[int]):
        item = pixmap
        if type(pixmap) == QPixmap:
            item = AnimatedPixmapItem(pixmap)
            item.set_original_position(QPointF(pos[0], pos[1]))
        self.itemList.append(item)

    def show_items(self, changeEffect=None):
        for i in self.itemList:
            self.scene.addItem(i)
        self.prepare_change_effect(None, changeEffect, "add", self.itemList)

    def clear_items(self):
        for i in self.itemList:
            self.scene.removeItem(i)
        self.itemList = []

    def set_background(self, pixmap: QPixmap, changeEffect=None):
        if self.background_item:
            self.scene.removeItem(self.background_item)
        self.background_item = BackgroundPixmapItem(pixmap)
        self.scene.addItem(self.background_item)
        self.fit_background()
        if changeEffect:
            self.prepare_change_effect(None, changeEffect, "add", "bg")

    def fit_background(self):
        # 背景按逻辑分辨率缩放（与场景坐标一致），窗口缩放由 fitInView 统一处理
        if self.background_item and self.scene.sceneRect().isValid():
            self.background_item.resize_to_fit_window(
                self.logical_size[0], self.logical_size[1], self.bg_pos)

    def add_character(self, char_id: str, pixmap: QPixmap, pos: List[int], zoom: float = 1.0, animations: List = None, changeEffect=None):
        if char_id in self.character_items:
            self.remove_character(char_id)
        item = AnimatedPixmapItem(pixmap)
        item.set_original_position(QPointF(pos[0], pos[1]))
        item.set_zoom(zoom)
        if animations:
            item.set_animations(animations)
        self.scene.addItem(item)
        self.character_items[char_id] = item
        if changeEffect:
            self.prepare_change_effect(char_id, changeEffect, "add", "character")

    def prepare_change_effect(self, char_id=None, changeEffect=None, mode="remove", item="character"):
        if changeEffect == "gradient":
            if item == "character":
                if char_id not in self.character_items:
                    return
                target_items = [self.character_items[char_id]]
            elif item == "bg":
                if not self.background_item:
                    return
                target_items = [self.background_item]
            elif type(item) == list:
                target_items = item
            else:
                return

            for target_item in target_items:
                effect = target_item.graphicsEffect()
                if effect is None or not isinstance(effect, QGraphicsOpacityEffect):
                    effect = QGraphicsOpacityEffect()
                    target_item.setGraphicsEffect(effect)
                start_value = 1.0 if mode == "remove" else 0.0
                end_value = 0.0 if mode == "remove" else 1.0
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
                self.pending_animations.append(animate)

    def start_pending_animations(self):
        for animate in self.pending_animations:
            if animate is None:
                continue
            self.active_animations.append(animate)
            try:
                animate.finished.connect(lambda a=animate: self.active_animations.remove(a) if a in self.active_animations else None)
                animate.start()
            except Exception as e:
                print(f"启动动画失败: {e}")
        self.pending_animations.clear()

    def remove_character(self, char_id: str):
        if char_id in self.character_items:
            character_item = self.character_items[char_id]
            if hasattr(character_item, 'animation_timer'):
                character_item.animation_timer.stop()
            self.scene.removeItem(self.character_items[char_id])
            del self.character_items[char_id]

    def clear_characters(self):
        for char_id in list(self.character_items.keys()):
            self.remove_character(char_id)

    def clear_bg(self):
        if self.background_item:
            self.scene.removeItem(self.background_item)
            self.background_item = None

    def clear_all(self):
        self.clear_characters()
        if self.background_item:
            self.scene.removeItem(self.background_item)
            self.background_item = None

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # 窗口尺寸变化：等比缩放逻辑场景填满视口
        self.fit_logical_rect()
        self.fit_background()