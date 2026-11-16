from typing import List, Dict
from PySide6.QtWidgets import QGraphicsView, QGraphicsScene, QGraphicsPixmapItem, QGraphicsOpacityEffect
from PySide6.QtOpenGLWidgets import QOpenGLWidget
from PySide6.QtCore import Qt, QTimer, QPointF, QRectF, QPropertyAnimation, QVariantAnimation, QEasingCurve
from PySide6.QtCore import QSequentialAnimationGroup, QPauseAnimation
from PySide6.QtGui import QPixmap, QPainter, QColor

from ui.animations import ease_in_out


def _make_fade_animation(effect, start, end, duration_ms, delay_ms=0):
    """构造「先等 delay_ms，再用 duration_ms 从 start 变到 end」的不透明度动画。

    QPropertyAnimation 本身没有延迟启动，用 QSequentialAnimationGroup + addPause 拼出来；
    有无延迟都返回 QAbstractAnimation，调用方统一当动画对象用（start/finished 都一样）。
    """
    fade = QPropertyAnimation(effect, b"opacity")
    fade.setDuration(max(int(duration_ms), 1))
    fade.setStartValue(float(start))
    fade.setEndValue(float(end))
    fade.setEasingCurve(QEasingCurve.InOutQuad)
    if delay_ms and float(delay_ms) > 0:
        group = QSequentialAnimationGroup()
        group.addPause(max(int(delay_ms), 1))
        group.addAnimation(fade)
        return group
    return fade


def _sample_move_path(move_path, t):
    """按进度 t（0~1）在 move 路径上取相对位移（线性插值）。

    路径的 N 个点把时长均分成 N 段，第 i 个点在第 (i+1)/N 处到达，
    起点偏移视为 (0, 0)。
    ⚠️ 只有一个点时，必须从 0 插值到该点（整段时长匀速走完），
    否则会在第一帧直接跳到终点（0.5s 的平移看起来像“瞬间完成”）。
    """
    n = len(move_path)
    t = min(max(float(t), 0.0), 1.0)
    idx = min(int(t * n), n - 1)
    local = t * n - idx
    p0 = move_path[idx - 1] if idx > 0 else (0, 0)
    p1 = move_path[idx]
    try:
        x0, y0 = float(p0[0]), float(p0[1])
        x1, y1 = float(p1[0]), float(p1[1])
    except (TypeError, ValueError, IndexError):
        return (0.0, 0.0)
    return (x0 + (x1 - x0) * local, y0 + (y1 - y0) * local)


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
        if self.original_pixmap:
            new_width = int(self.original_pixmap.width() * zoom)
            new_height = int(self.original_pixmap.height() * zoom)
            scaled_pixmap = self.original_pixmap.scaled(
                new_width, new_height, Qt.KeepAspectRatio, Qt.SmoothTransformation
            )
            self.setPixmap(scaled_pixmap)

    def set_animations(self, animations: List):
        self.animations = animations
        if animations:
            self.start_animation_group(0)

    def start_animation_group(self, group_index: int):
        if group_index >= len(self.animations):
            # 最后一组放完：彻底停掉（否则定时器会继续空转）
            self.current_animation_group = None
            self.animation_timer.stop()
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
            # 收尾：按 t=1.0 补一次，保证最后一帧精确落在终点值上
            # （不补的话会停在前一个 tick，如 move 128 只走到 127.98）
            self.animation_progress = group_duration
            for animation in self.current_animation_group:
                self.apply_animation(animation)
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
                ox, oy = _sample_move_path(move_path, eased_progress)
                self.setPos(QPointF(self.animation_start_pos.x() + ox,
                                    self.animation_start_pos.y() + oy))

    def set_original_position(self, pos: QPointF):
        self.original_pos = pos
        self.setPos(pos)


class AnimatedBackgroundItem(AnimatedPixmapItem):
    """新语法背景（bg 为对象，带 zoom/start_pos/animate）。

    与角色不同：zoom 用矢量 setScale（不逐帧重采样大图）。
    坐标口径：缩放后图片视为 (宽*zoom, 高*zoom)，item 的 pos 存
    「显示区域左上角在该图上的坐标」的负值，所以 move 动画直接沿用父类的
    「组起点 + 相对位移」逻辑。
    """

    def __init__(self, pixmap=None):
        super().__init__(pixmap)
        self.setZValue(-1)
        self._region_pos = [0.0, 0.0]

    def set_zoom(self, zoom: float):
        self.current_zoom = float(zoom)
        self.setScale(self.current_zoom)

    def set_region_pos(self, pos):
        """设置显示区域左上角（放大后图片坐标系）。"""
        self._region_pos = [float(pos[0]), float(pos[1])]
        self.setPos(-self._region_pos[0], -self._region_pos[1])

    def start_animation_group(self, group_index: int):
        super().start_animation_group(group_index)
        # 动画起点用「取景起点」（正值），不用 item.pos（存的是它的负值）。
        # 否则 move 会叠在负坐标上：往右平移 640 会把图像推到 x=+640，
        # 左边露出 640px 空白（看上去像背景被错位/放大）。
        self.animation_start_pos = QPointF(self._region_pos[0], self._region_pos[1])

    def apply_animation(self, animation: Dict):
        """与角色动画同构，但位移作用在「取景起点」上（move 是相对位移）。"""
        duration = animation.get("time", 0) * 1000
        if duration == 0:
            return
        progress = min(self.animation_progress / duration, 1.0)
        eased_progress = ease_in_out(progress)
        if "zoom" in animation:
            target_zoom = animation["zoom"]
            self.set_zoom(self.animation_start_zoom +
                          (target_zoom - self.animation_start_zoom) * eased_progress)
        if "move" in animation:
            move_path = animation["move"]
            if move_path and len(move_path) > 0:
                ox, oy = _sample_move_path(move_path, eased_progress)
                self.set_region_pos([self.animation_start_pos.x() + ox,
                                     self.animation_start_pos.y() + oy])

    def resize_to_fit_window(self, width: int, height: int, bg_pos=[0, 0]):
        """分辨率变化：用原图按 KeepAspectRatioByExpanding 重排，再套沿用取景。"""
        if self.original_pixmap is None or self.original_pixmap.isNull():
            return
        fitted = self.original_pixmap.scaled(
            width, height, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
        self.setPixmap(fitted)
        self.set_region_pos(self._region_pos)


class SlideWipeItem(QGraphicsPixmapItem):
    """slide 转场遮罩：持有一张「前」画面，按分割线裁剪出自己该露的那一侧。

    分割线从起点侧向终点侧移动（如 right -> left：竖线从最右移到最左）；
    progress 0 -> 1。旧画面占据「终点侧的反侧」——即线扫过之前的那块，
    因此：起点 right 时旧图占 [0, L]，起点 left 时占 [L, W]，
    恰好对应「竖线到最左时旧画面完全消失」。

    边界装饰（slide_element）：可选的元素列表，沿分割线绘制，用来给滑动的那条
    边界做外观。每个元素：
        {"area": [[x1,y1],[x2,y2]], "color": [r,g,b,a]}
    坐标系以「分割线上的原点」为 (0,0)：
      - horizontal（竖线）：原点 = 竖线最高点（y=0 处）；x 无限（写相对位移），
        y 有限（0..height），负值从末行倒数：-1 = height，-2 = height-1 …
      - vertical（横线）：原点 = 横线最左点（x=0 处）；y 无限（写相对位移），
        x 有限（0..width），负值从末列倒数：-1 = width，-2 = width-1 …
    列表顺序即层数：index 0 在最底层，后面的画在上面。
    """

    def __init__(self, pixmap, axis="horizontal", start="right", end="left",
                 elements=None):
        super().__init__(pixmap)
        self.setZValue(1000)
        self._axis = axis
        self._start = start
        self._end = end
        self._progress = 0.0
        self._elements = self._normalize_elements(elements or [])
        self._bound_rect = self._calc_bounding_rect()

    # ---------- slide_element 解析 ----------

    @staticmethod
    def _resolve_tail(v, limit):
        """有限轴上的负值倒数：-1 = limit（最后一个有限值），-2 = limit-1 …"""
        return float(limit) + 1.0 + v if v < 0 else float(v)

    def _normalize_elements(self, elements):
        """把 JSON 里的元素列表规整成 [{x0,x1,y0,y1,color}]，解析失败的跳过。

        horizontal：x0/x1 为「相对竖线的位移」，y0/y1 为绝对像素（含负数倒数）；
        vertical：  y0/y1 为「相对横线的位移」，x0/x1 为绝对像素（同规则）。
        """
        pm = self.pixmap()
        w = pm.width() if pm is not None else 0
        h = pm.height() if pm is not None else 0
        out = []
        if not isinstance(elements, (list, tuple)):
            return out
        for el in elements:
            if not isinstance(el, dict):
                continue
            area = el.get("area")
            if not (isinstance(area, (list, tuple)) and len(area) >= 2):
                continue
            try:
                ax, ay = float(area[0][0]), float(area[0][1])
                bx, by = float(area[1][0]), float(area[1][1])
            except (TypeError, ValueError, IndexError):
                continue
            if self._axis == "vertical":
                # x 有限（绝对像素，支持 -1 = width），y 相对横线
                x0, x1 = self._resolve_tail(ax, w), self._resolve_tail(bx, w)
                y0, y1 = ay, by
            else:
                # y 有限（绝对像素，支持 -1 = height），x 相对竖线
                x0, x1 = ax, bx
                y0, y1 = self._resolve_tail(ay, h), self._resolve_tail(by, h)
            color = el.get("color")
            qcolor = QColor(0, 0, 0, 255)
            if isinstance(color, (list, tuple)) and len(color) >= 3:
                try:
                    alpha = int(color[3]) if len(color) >= 4 else 255
                    qcolor = QColor(int(color[0]), int(color[1]), int(color[2]), alpha)
                except (TypeError, ValueError):
                    qcolor = QColor(0, 0, 0, 255)
            out.append({"x0": min(x0, x1), "x1": max(x0, x1),
                        "y0": min(y0, y1), "y1": max(y0, y1),
                        "color": qcolor})
        return out

    def _calc_bounding_rect(self):
        """包围盒：整帧 + 元素随边界扫过全程时可能覆的区域。"""
        pm = self.pixmap()
        w = pm.width() if pm is not None else 0
        h = pm.height() if pm is not None else 0
        if not self._elements:
            return QRectF(0, 0, w, h)
        if self._axis == "vertical":
            x0 = min([e["x0"] for e in self._elements] + [0])
            x1 = max([e["x1"] for e in self._elements] + [w])
            y0 = min([e["y0"] for e in self._elements] + [0])
            y1 = max([e["y1"] for e in self._elements] + [0]) + h
            return QRectF(x0, y0, x1 - x0, y1 - y0)
        x0 = min([e["x0"] for e in self._elements] + [0])
        x1 = max([e["x1"] for e in self._elements] + [0]) + w
        y0 = min([e["y0"] for e in self._elements] + [0])
        y1 = max([e["y1"] for e in self._elements] + [h])
        return QRectF(x0, y0, x1 - x0, y1 - y0)

    def boundingRect(self):
        return self._bound_rect

    def _line_pos(self, w, h):
        """当前分割线位置（horizontal 返回 x，vertical 返回 y）。"""
        p = self._progress
        if self._axis == "vertical":
            return h * (1.0 - p) if self._start in ("bottom", "down") else h * p
        return w * (1.0 - p) if self._start in ("right",) else w * p

    def set_progress(self, value):
        self._progress = max(0.0, min(1.0, float(value)))
        self.update()

    def paint(self, painter, option, widget=None):
        pm = self.pixmap()
        if pm is None or pm.isNull():
            return
        w, h = pm.width(), pm.height()
        p = self._progress
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        if self._axis == "vertical":
            # 横线上下移动：top -> bottom / bottom -> top
            if self._start in ("bottom", "down"):
                line = h * (1.0 - p)      # 从下往上：旧图留在上方
                rect = QRectF(0, 0, w, line)
            else:
                line = h * p              # 从上往下：旧图留在下方
                rect = QRectF(0, line, w, h - line)
        else:
            if self._start in ("right",):
                line = w * (1.0 - p)      # 从右往左：旧图留在左侧
                rect = QRectF(0, 0, line, h)
            else:
                line = w * p              # 从左往右：旧图留在右侧
                rect = QRectF(line, 0, w - line, h)
        painter.save()
        painter.setClipRect(rect)
        painter.drawPixmap(0, 0, pm)
        painter.restore()

        # 边界装饰：不裁剪（元素可以同时压在新旧两侧），按列表顺序叠放
        if self._elements:
            line = self._line_pos(w, h)
            painter.save()
            painter.setPen(Qt.NoPen)
            for el in self._elements:
                rw = el["x1"] - el["x0"]
                rh = el["y1"] - el["y0"]
                if rw <= 0 or rh <= 0:
                    continue
                if self._axis == "vertical":
                    rect_el = QRectF(el["x0"], line + el["y0"], rw, rh)
                else:
                    rect_el = QRectF(line + el["x0"], el["y0"], rw, rh)
                painter.fillRect(rect_el, el["color"])
            painter.restore()


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
        self.slide_item = None
        self.slide_animation = None
        self.bg_pos = background_pos
        self.pending_animations = []
        self.active_animations = []
        self.itemList = []
        self.setMouseTracking(True)
        self.setInteractive(True)
        # OpenGL viewport 可能忽略 item 光标：兜底强制箭头，避免悬停文本时 IBeam
        self.setCursor(Qt.ArrowCursor)
        self.viewport().setCursor(Qt.ArrowCursor)
        # 初始适配窗口
        self.fit_logical_rect()

    def fit_logical_rect(self):
        """将逻辑场景矩形等比缩放填满当前视口（超出部分裁切）。"""
        self.fitInView(0, 0, self.logical_size[0], self.logical_size[1],
                       Qt.KeepAspectRatio)

    def set_background_color(self, color):
        """Set window base color (stylesheet only).

        NOTE: do NOT set QGraphicsScene.backgroundBrush - otherwise clearing the
        scene (e.g. returning to main menu) would show a full-screen solid color,
        causing an abrupt "direct color switch". After clearing, transition
        elements (fade_out_menu color block / main menu gradient) take over.
        """
        rgb = ",".join(str(int(c)) for c in color[:3])
        self.setStyleSheet(f"background-color: rgb({rgb});")
    def set_logical_size(self, w, h):
        """更新逻辑分辨率并重建场景矩形。"""
        self.logical_size = [w, h]
        self.scene.setSceneRect(0, 0, w, h)
        self.fit_logical_rect()

    def mousePressEvent(self, event):
        # "⊙"隐藏模式：任意位置点击（左键/右键）恢复显示，不推进剧情、不触发右键返回
        mw = self.window()
        if mw is not None and getattr(mw, "_ui_hidden", False):
            if event.button() in (Qt.LeftButton, Qt.RightButton):
                mw._on_ui_hidden_click()
                event.accept()
                return
        # 右键 = 返回：设置/日志/保存/加载面板打开时，触发对应关闭函数
        if event.button() == Qt.RightButton:
            mw = self.window()
            handled = False
            if mw is not None:
                if getattr(mw, "is_in_settings", False):
                    mw.close_settings_panel()
                    handled = True
                elif getattr(mw, "is_in_save", False):
                    mw.close_save_panel()
                    handled = True
                elif getattr(mw, "is_in_backlog", False):
                    mw.close_backlog_panel()
                    handled = True
            if handled:
                event.accept()
                return
        super().mousePressEvent(event)
        if event.isAccepted():
            # 事件被场景 item 接受（accepted=True）。接受事件的 item 可通过
            # scene.mouseGrabberItem() 获取：若是 QGraphicsProxyWidget
            # （对话框文字/名字区域，QTextEdit/QLabel 消费了点击做文本选择/光标），
            # 剧情中点击对话框应推进剧情 → 重置事件为未接受，走下方转发链
            # （parent().mousePressEvent → 冒泡到主窗口 → handle_click）。
            # 若接受者是真实按钮（SettingsButtonItem 等），按钮已自行处理 click_handler，不转发。
            from PySide6.QtWidgets import QGraphicsProxyWidget
            item = self.scene.mouseGrabberItem()
            if isinstance(item, QGraphicsProxyWidget):
                event.setAccepted(False)
            else:
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
        return item

    def show_items(self, changeEffect=None, bg_color=None):
        """显示 itemList 中所有项；changeEffect 为转场效果名（如 "gradient" 淡入）。
        bg_color 非空时：先在底层铺一个纯色块（立即显示、不参与淡入、z=-5），
        菜单项从该颜色上淡入；缺省不铺（露出视口黑色背景）。
        """
        if bg_color is not None:
            w, h = self.logical_size
            block = QPixmap(w, h)
            block.fill(QColor(bg_color[0], bg_color[1], bg_color[2]))
            bg_item = AnimatedPixmapItem(block)
            bg_item.set_original_position(QPointF(0, 0))
            bg_item.setZValue(-5)
            bg_item._is_color_block = True
            self.itemList.insert(0, bg_item)
            # 转场淡入完成后移除黑块，避免残留（如从设置返回主菜单时旧黑块还在）
            _chg = self.parse_change(changeEffect)
            if _chg["name"] == "gradient" and _chg["ms"]:
                # 黑块跟随「新画面淡入」的节奏：延迟 + 时长 + 余量
                QTimer.singleShot(_chg["this_ms"] + _chg["ms"] + 200,
                                  lambda bi=bg_item: self._remove_color_block(bi))
        for i in self.itemList:
            self.scene.addItem(i)
        targets = [i for i in self.itemList if not getattr(i, "_is_color_block", False)]
        self.prepare_change_effect(None, changeEffect, "add", targets)

    def clear_items(self):
        for i in self.itemList:
            self.scene.removeItem(i)
        self.itemList = []

    def _remove_color_block(self, item):
        """转场完成后移除纯色底块（若还在场景中/列表中）。"""
        try:
            if item.scene() is not None:
                self.scene.removeItem(item)
        except Exception:
            pass
        try:
            self.itemList.remove(item)
        except ValueError:
            pass

    @staticmethod
    def parse_change(changeEffect):
        """解析 change 配置，返回字典：
            {"name": 效果名, "ms": 时长毫秒, "last_ms": 旧图延迟毫秒, "this_ms": 新图延迟毫秒}
        支持：
          "gradient"                                   -> 默认 1000ms，两边都不延迟
          ["gradient", 0.8]                            -> 800ms
          ["gradient", {"time": 0.5,
                        "start_change": {"last": 0.1, "this": 0}}]
                 time = 两边淡出/淡入的时长（秒，缺省=默认 1000ms）
                 start_change.last = 「旧画面」延迟多少秒才开始淡出
                 start_change.this = 「新画面/自己」延迟多少秒才开始淡入
                 例：last=0.1 / this=0 / time=0.5
                     旧画面 0.1s 开始淡出、0.6s 淡完；新画面 0s 开始淡入、0.5s 淡完
        无效配置 -> name=None。
        """
        info = {"name": None, "ms": 1000, "last_ms": 0, "this_ms": 0}
        if isinstance(changeEffect, str):
            info["name"] = changeEffect
            return info
        if not (isinstance(changeEffect, (list, tuple)) and len(changeEffect) >= 1):
            return info
        info["name"] = changeEffect[0]
        if len(changeEffect) < 2:
            return info
        opt = changeEffect[1]
        if isinstance(opt, dict):
            # 新语法：{"time": 秒, "start_change": {"last": 秒, "this": 秒}}
            try:
                t = float(opt.get("time", 1.0))
            except (TypeError, ValueError):
                t = 1.0
            info["ms"] = max(int(t * 1000), 1)
            sc = opt.get("start_change")
            if isinstance(sc, dict):
                for key, field in (("last", "last_ms"), ("this", "this_ms")):
                    try:
                        info[field] = max(int(float(sc.get(key, 0) or 0) * 1000), 0)
                    except (TypeError, ValueError):
                        info[field] = 0
            return info
        # 旧语法：["gradient", 秒数]
        try:
            info["ms"] = max(int(float(opt) * 1000), 1)
        except (TypeError, ValueError):
            info["ms"] = 1000
        return info

    @staticmethod
    def _parse_change_effect(changeEffect):
        """兼容旧调用：返回 (效果名, 时长毫秒)。需要延迟信息请用 parse_change。"""
        info = GraphicsView.parse_change(changeEffect)
        if info["name"] is None:
            return None, None
        return info["name"], info["ms"]

    def set_background(self, pixmap: QPixmap, changeEffect=None):
        if self.background_item:
            self.scene.removeItem(self.background_item)
        self.background_item = BackgroundPixmapItem(pixmap)
        self.scene.addItem(self.background_item)
        self.fit_background()
        if changeEffect:
            self.prepare_change_effect(None, changeEffect, "add", "bg")

    def render_snapshot(self) -> QPixmap:
        """把当前场景整帧渲成图片（供 slide 转场做「前」画面）。"""
        w, h = self.logical_size
        pm = QPixmap(w, h)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        self.scene.render(p, QRectF(0, 0, w, h), QRectF(0, 0, w, h))
        p.end()
        return pm

    def start_slide_wipe(self, old_pixmap: QPixmap, slide: dict):
        """slide 转场：场景已搭好，把「前」画面盖在上面做遮罩并向一侧收回。

        slide：{"axis": "horizontal"/"vertical", "start": "right",
                "end": "left", "duration": 秒, "slide_element": [...]}
        """
        self.clear_slide_wipe()
        if old_pixmap is None or old_pixmap.isNull():
            return
        item = SlideWipeItem(old_pixmap, axis=slide.get("axis", "horizontal"),
                             start=slide.get("start", "right"),
                             end=slide.get("end", "left"),
                             elements=slide.get("slide_element"))
        self.scene.addItem(item)
        self.slide_item = item
        anim = QVariantAnimation()
        anim.setDuration(int(float(slide.get("duration", 1.0)) * 1000))
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.InOutQuad)
        anim.valueChanged.connect(item.set_progress)
        anim.finished.connect(self.clear_slide_wipe)
        self.slide_animation = anim
        anim.start()

    def clear_slide_wipe(self):
        anim = getattr(self, "slide_animation", None)
        if anim is not None:
            try:
                anim.stop()
            except Exception:
                pass
            self.slide_animation = None
        item = getattr(self, "slide_item", None)
        if item is not None:
            if item.scene() is not None:
                self.scene.removeItem(item)
            self.slide_item = None

    def fit_background(self):
        # 背景按逻辑分辨率缩放（与场景坐标一致），窗口缩放由 fitInView 统一处理
        if self.background_item and self.scene.sceneRect().isValid():
            if hasattr(self.background_item, "resize_to_fit_window"):
                self.background_item.resize_to_fit_window(
                    self.logical_size[0], self.logical_size[1], self.bg_pos)

    def set_background_ext(self, pixmap: QPixmap, zoom: float = 1.0, region_pos=(0, 0),
                           animations: List = None, changeEffect=None):
        """新语法背景：pixmap 为原图，内部先适配逻辑分辨率，再按 zoom 缩放取景。

        region_pos：显示区域左上角在「缩放后图片」上的坐标（默认由调用方算好居中）。
        animations：与角色动画同构（move 为相对位移，zoom 为绝对值）。
        """
        if self.background_item:
            self.scene.removeItem(self.background_item)
        w, h = self.logical_size
        fitted = pixmap.scaled(w, h, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
        item = AnimatedBackgroundItem(fitted)
        # 保留原图：分辨率变化时按原图重排
        item.original_pixmap = pixmap
        item.set_region_pos(region_pos)
        item.set_zoom(zoom)
        self.background_item = item
        self.scene.addItem(item)
        if animations:
            item.set_animations(animations)
        if changeEffect:
            self.prepare_change_effect(None, changeEffect, "add", "bg")

    def add_character(self, char_id: str, pixmap: QPixmap, pos: List[int], zoom: float = 1.0, animations: List = None, changeEffect=None):
        old_item = self.character_items.get(char_id)
        change = self.parse_change(changeEffect)
        change_name, change_ms = change["name"], change["ms"]
        if change_name == "gradient" and old_item is not None:
            # 渐变替换（增量更新）：旧图留在底层淡出，新图叠在上面淡入（双向交叉）。
            # 延迟语义：start_change.last = 旧图延迟多久开始淡出；
            #            start_change.this = 新图延迟多久开始淡入；
            #            time = 两边各自的淡出/淡入时长。
            item = AnimatedPixmapItem(pixmap)
            item.set_original_position(QPointF(pos[0], pos[1]))
            item.set_zoom(zoom)
            if animations:
                item.set_animations(animations)
            self.scene.addItem(item)
            self.character_items[char_id] = item
            # 旧图压到新图之下（背景 z=-1 之上），并停止其动画
            old_item.setZValue(item.zValue() - 0.5)
            old_item.animation_timer.stop()
            # 记录待移除旧图：淡入完成（或清场）时统一移除，避免中途再次替换造成残留
            if not hasattr(self, "_stale_characters"):
                self._stale_characters = {}
            self._stale_characters.setdefault(char_id, []).append(old_item)
            # 双向交叉淡化：新图延迟 this 后 0 -> 1，旧图延迟 last 后 1 -> 0
            effect = QGraphicsOpacityEffect()
            # QGraphicsOpacityEffect 默认 opacity 是 0.7，不显式置 0 会在动画启动前闪一帧
            effect.setOpacity(0.0)
            item.setGraphicsEffect(effect)
            animate = _make_fade_animation(effect, 0.0, 1.0, change_ms, change["this_ms"])

            # 旧图同步淡出：从它当前的透明度开始（快速连续替换时从半透明处接着淡，不跳回 1.0）
            old_effect = old_item.graphicsEffect()
            if not isinstance(old_effect, QGraphicsOpacityEffect):
                old_effect = QGraphicsOpacityEffect()
                # 默认 0.7，必须先置成 1.0（= 旧图当前完全可见），否则淡出一开始就“暗一下”
                old_effect.setOpacity(1.0)
                old_item.setGraphicsEffect(old_effect)
            fade_out = _make_fade_animation(old_effect, old_effect.opacity(), 0.0,
                                            change_ms, change["last_ms"])

            def _on_finished(char_id=char_id, item=item):
                # 淡入/淡出完成：若该角色当前显示的仍是此新图，则移除所有待移除旧图
                if self.character_items.get(char_id) is item:
                    stale = self._stale_characters.pop(char_id, [])
                    for s in stale:
                        if s.scene() is not None:
                            self.scene.removeItem(s)
            # 旧图得等“旧图淡出”跑完才能移除：延迟较长时若提前移除，旧图会“啪”地消失
            if change["last_ms"] + change_ms >= change["this_ms"] + change_ms:
                fade_out.finished.connect(_on_finished)
            else:
                animate.finished.connect(_on_finished)
            self.pending_animations.append(fade_out)
            self.pending_animations.append(animate)
            return
        # 无渐变或首次添加：原逻辑直接替换
        if old_item is not None:
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
        change = self.parse_change(changeEffect)
        if change["name"] == "gradient":
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

            # 延迟语义：淡出（remove）= 旧画面 → 用 start_change.last；
            #           淡入（add）  = 新画面 → 用 start_change.this
            delay_ms = change["last_ms"] if mode == "remove" else change["this_ms"]
            for target_item in target_items:
                effect = target_item.graphicsEffect()
                if effect is None or not isinstance(effect, QGraphicsOpacityEffect):
                    effect = QGraphicsOpacityEffect()
                    # QGraphicsOpacityEffect 默认 opacity 是 0.7，不显式置起始值会先“暗一下”
                    effect.setOpacity(1.0 if mode == "remove" else 0.0)
                    target_item.setGraphicsEffect(effect)
                start_value = 1.0 if mode == "remove" else 0.0
                end_value = 0.0 if mode == "remove" else 1.0
                animate = _make_fade_animation(effect, start_value, end_value,
                                               change["ms"], delay_ms)
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
        # 顺带清理该角色的待移除旧图（渐变替换残留）
        stale = getattr(self, "_stale_characters", {}).pop(char_id, [])
        for s in stale:
            if s.scene() is not None:
                self.scene.removeItem(s)

    def clear_characters(self):
        for char_id in list(self.character_items.keys()):
            self.remove_character(char_id)
        # 清理渐变替换残留的旧图（淡入未完成时被清场）
        for char_id, stale_list in list(getattr(self, "_stale_characters", {}).items()):
            for s in stale_list:
                if s.scene() is not None:
                    self.scene.removeItem(s)
        self._stale_characters = {}

    def clear_bg(self):
        if self.background_item:
            self.scene.removeItem(self.background_item)
            self.background_item = None

    def clear_all(self):
        self.clear_characters()
        self.clear_slide_wipe()
        if self.background_item:
            self.scene.removeItem(self.background_item)
            self.background_item = None

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # 窗口尺寸变化：等比缩放逻辑场景填满视口
        self.fit_logical_rect()
        self.fit_background()