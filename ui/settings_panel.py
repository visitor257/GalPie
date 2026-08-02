# -*- coding: utf-8 -*-
"""
设置面板（同窗口内覆盖层）。

设计目标：
- 设置界面显示在主窗口的 QGraphicsView 场景内，而非弹窗。
- 支持两种配置来源：
    1. 预设 UI（preset）：未提供自定义配置时，使用内置默认样式。
    2. 自定义 UI（custom）：后续从 JSON 的 settings_ui 配置读取，预留接口。
- 当前实现预设 UI：一块木色圆角长方形居中显示，渐变（透明度 0->100，约 0.5 秒）出现。
- 面板底部部署 3 个半透明圆角按钮：恢复默认、返回、退出游戏。

本模块负责"面板容器 + 渐变显示 + 底部按钮"，具体设置项控件后续逐步加入。
"""
from PySide6.QtWidgets import (
    QGraphicsPathItem, QGraphicsOpacityEffect, QGraphicsTextItem
)
from PySide6.QtCore import QRectF, QPropertyAnimation, QEasingCurve, Qt, QPointF
from PySide6.QtGui import QColor, QBrush, QPen, QFont, QPainterPath

# 预设默认配置（木色圆角矩形）
DEFAULT_PRESET = {
    "margin_ratio": 0.1,          # 面板距窗口边缘的比例（四边各留 10%），面板宽高 = 0.8 * 窗口
    "corner_radius": 24,          # 面板圆角半径
    "fill_color": [139, 90, 43],  # 木色 (木棕)
    "fade_duration": 500,         # 渐变显示时长 ms
    "border_offset": 10,          # 白色边框距面板边缘的距离 (px)
    "border_width": 10,           # 白色边框宽度 (px)
    "border_color": [255, 255, 255],  # 白色边框颜色
    "button_radius": 12,          # 底部按钮圆角半径
    "button_height": 48,          # 底部按钮高度
    "button_margin": 24,          # 按钮与面板底部/侧边的间距
    "button_gap": 24,             # 按钮之间的间距
    "button_color": [0, 0, 0],    # 按钮底色
    "button_opacity": 90,         # 按钮底色透明度 (0-255)，较低透明度
    "z": 20,                      # 面板 Z 值（高于菜单按钮）
}

# 底部按钮文本（多语言）
BUTTON_TEXTS = {
    "reset": {"zh": "恢复默认", "en": "Reset"},
    "back": {"zh": "返回", "en": "Back"},
    "quit": {"zh": "退出游戏", "en": "Quit"},
}


class SettingsPanel(QGraphicsPathItem):
    """设置面板（场景覆盖层）。使用圆角路径实现圆角矩形。"""

    def __init__(self, scene, config=None, language="zh", parent=None):
        # 合并配置：优先自定义 config，缺省项回落到预设默认
        self.config = {**DEFAULT_PRESET, **(config or {})}
        self.language = language
        self.buttons = []   # 底部按钮列表

        # 初始占位尺寸（后续 center_in_scene 会按场景重新计算）
        self._size = [100, 100]
        path = QPainterPath()
        path.addRoundedRect(QRectF(0, 0, self._size[0], self._size[1]),
                            self.config["corner_radius"], self.config["corner_radius"])
        super().__init__(path, parent)

        # 木色圆角矩形填充
        fill = self.config["fill_color"]
        self.setBrush(QBrush(QColor(fill[0], fill[1], fill[2])))
        self.setPen(QPen(Qt.NoPen))
        self.setZValue(self.config["z"])
        self._scene = scene
        self._anim = None

        # 白色内边框：距边缘 border_offset，宽 border_width（作为面板子项，随面板移动）
        self._border_item = None
        self._rebuild_border()

    def _rebuild_border(self):
        """重建白色内边框：距面板边缘 border_offset 处，宽 border_width 的白色框。
        用 10px 宽白色 pen 描边一个 inset 矩形：
        笔宽 border_width，笔中心在 inset 矩形上，向两侧各扩展 border_width/2，
        因此白色带从 inset - bw/2 到 inset + bw/2。
        要求白色框内侧距面板边缘 border_offset：即 inset - bw/2 = offset -> inset = offset + bw/2。
        这样白色框距面板边缘最近处为 offset（内侧），总宽 bw。
        """
        w, h = self._size
        offset = self.config["border_offset"]
        width = self.config["border_width"]
        # 面板尺寸过小时跳过
        if w < 2 * (offset + width) or h < 2 * (offset + width):
            if self._border_item is not None:
                if self._border_item.scene():
                    self._scene.removeItem(self._border_item)
                self._border_item = None
            return
        # 笔中心线位置：inset = offset + width/2，使白色带内侧恰好在 offset 处
        inset = offset + width / 2.0
        radius = max(2, self.config["corner_radius"] - offset)
        path = QPainterPath()
        rect = QRectF(inset, inset, w - 2 * inset, h - 2 * inset)
        path.addRoundedRect(rect, radius, radius)
        if self._border_item is None:
            self._border_item = QGraphicsPathItem(path, self)
            bc = self.config["border_color"]
            self._border_item.setBrush(QBrush(Qt.NoBrush))
            pen = QPen(QColor(bc[0], bc[1], bc[2]))
            pen.setWidthF(width)
            self._border_item.setPen(pen)
            # 边框略高于面板本体
            self._border_item.setZValue(1)
        else:
            self._border_item.setPath(path)

    def _rebuild_path(self):
        """按当前 _size 重建圆角路径。"""
        radius = self.config["corner_radius"]
        path = QPainterPath()
        path.addRoundedRect(QRectF(0, 0, self._size[0], self._size[1]), radius, radius)
        self.setPath(path)
        # 同步重建白色内边框
        self._rebuild_border()

    def _build_buttons(self):
        """在面板底部创建半透明圆角按钮（作为面板子 item）。
        布局基准从"木色大框"改为"白色圈内空间"：
          白色框内边界 = border_offset + border_width，按钮在此区域内 4 等分——
          恢复默认 占第 1 格、返回 占第 3 格、退出游戏 占第 4 格（第 2 格留空）。
        文本直接作为面板子项（与按钮平级），定位在按钮中心上方，
        避免嵌套子项在父项未入 scene 时的偏移问题。
        """
        w, h = self._size
        btn_h = self.config["button_height"]
        margin = self.config["button_margin"]
        opacity = self.config["button_opacity"]
        # 白色框内边界（面板局部坐标）
        inner = self.config["border_offset"] + self.config["border_width"]

        # 白色框内可用宽，4 等分格子，按钮宽 = 25% * 内宽（各留 margin 内边距）
        avail_w = w - 2 * inner
        cell_w = avail_w / 4.0
        btn_w = cell_w - margin   # 每个格子内留一点边距
        btn_w = max(20, btn_w)
        # 按钮底边距白色框内边缘 margin
        y = h - inner - btn_h - margin

        # (key, 所在格子索引 0~3)
        placements = [("reset", 0), ("back", 2), ("quit", 3)]

        for key, cell_idx in placements:
            x = inner + cell_idx * cell_w + margin / 2
            rect = QRectF(x, y, btn_w, btn_h)
            btn = SettingsButtonItem(rect, key, self, opacity=opacity)
            self.buttons.append(btn)
            # 文本作为面板子项，定位到按钮中心
            text = BUTTON_TEXTS[key].get(self.language, BUTTON_TEXTS[key]["zh"])
            self._add_button_text(text, btn,
                                  [255, 255, 255], QFont("Microsoft YaHei", 13, QFont.Bold))

    def center_in_scene(self, scene_rect):
        """按距窗口边缘 margin_ratio（默认 10%）计算尺寸并居中，并创建底部按钮。
        scene_rect: 场景可显示区域矩形。
        """
        w_avail = scene_rect.width()
        h_avail = scene_rect.height()
        margin = self.config["margin_ratio"]
        w = max(10, int(w_avail * (1 - 2 * margin)))
        h = max(10, int(h_avail * (1 - 2 * margin)))
        self._size = [w, h]
        self._rebuild_path()
        # 移除旧按钮及其文本（尺寸变化时重建）
        for b in list(self.buttons):
            label = getattr(b, "_text_label", None)
            if label is not None and label.scene():
                self._scene.removeItem(label)
            if b.scene():
                self._scene.removeItem(b)
        self.buttons = []
        self._build_buttons()
        x = scene_rect.left() + (w_avail - w) / 2
        y = scene_rect.top() + (h_avail - h) / 2
        self.setPos(x, y)

    def fade_in(self, duration=None):
        """渐变显示：透明度 0 -> 100。面板及子按钮一起渐显。"""
        if duration is None:
            duration = self.config["fade_duration"]
        effect = QGraphicsOpacityEffect()
        effect.setOpacity(0.0)
        self.setGraphicsEffect(effect)
        self._anim = QPropertyAnimation(effect, b"opacity")
        self._anim.setDuration(duration)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.setEasingCurve(QEasingCurve.InOutQuad)
        self._anim.start()

    def fade_out(self, on_finished=None, duration=None):
        """渐变消失：透明度 100 -> 0。动画结束后调用 on_finished（若有），
        并保留面板（由调用方在回调中移除以配合后续动画）。"""
        if duration is None:
            duration = self.config["fade_duration"]
        effect = self.graphicsEffect()
        if not isinstance(effect, QGraphicsOpacityEffect):
            effect = QGraphicsOpacityEffect()
            effect.setOpacity(1.0)
            self.setGraphicsEffect(effect)
        self._anim = QPropertyAnimation(effect, b"opacity")
        self._anim.setDuration(duration)
        self._anim.setStartValue(effect.opacity())
        self._anim.setEndValue(0.0)
        self._anim.setEasingCurve(QEasingCurve.InOutQuad)
        self._anim.finished.connect(lambda: self._on_fade_out_done(on_finished))
        self._anim.start()

    def _on_fade_out_done(self, on_finished):
        if on_finished:
            on_finished()

    def close_panel(self, scene=None):
        """从场景中移除面板（含子按钮、白色边框）。"""
        if scene is None:
            scene = self._scene
        if self._border_item is not None and self._border_item.scene():
            scene.removeItem(self._border_item)
            self._border_item = None
        if self.scene() == scene:
            scene.removeItem(self)

    def _add_button_text(self, text, btn, rgb, font):
        """在按钮中心上方叠加文本。文本作为面板子项（与按钮平级），
        用按钮的面板局部坐标定位，避免嵌套子项在父项未入 scene 时的偏移。
        返回创建的文本 item。
        """
        label = QGraphicsTextItem()
        label.setPlainText(text)
        label.setDefaultTextColor(QColor(rgb[0], rgb[1], rgb[2]))
        label.setFont(font)
        label.setAcceptHoverEvents(False)
        # 文本作为面板子项，随面板移动/显示
        label.setParentItem(self)
        # 按钮是面板子项，图形从面板局部 (btn._rect.x, btn._rect.y) 开始
        # 按钮图形中心（面板局部坐标）
        btn_center = QPointF(btn._rect.x() + btn._rect.width() / 2,
                             btn._rect.y() + btn._rect.height() / 2)
        # 强制排版后再取尺寸
        label.setTextWidth(-1)
        r = label.boundingRect()
        label.setPos(btn_center.x() - r.width() / 2, btn_center.y() - r.height() / 2)
        self.buttons[-1]._text_label = label  # 记录，便于后续调整
        return label

    def button(self, key):
        """按 key（reset/back/quit）返回按钮 item；无则 None。"""
        for b in self.buttons:
            if b.key == key:
                return b
        return None


class SettingsButtonItem(QGraphicsPathItem):
    """设置面板底部的半透明圆角按钮，支持鼠标悬停反馈（底色变白）。"""

    # 正常/悬停底色（半透明）
    _NORMAL_COLOR = [0, 0, 0]      # 黑色半透明
    _HOVER_COLOR = [255, 255, 255]  # 白色半透明

    def __init__(self, rect: QRectF, key: str, parent=None, opacity=90):
        path = QPainterPath()
        path.addRoundedRect(rect, 12, 12)
        super().__init__(path, parent)
        self.key = key
        self.click_handler = None
        self._rect = rect
        self._opacity = opacity
        self.is_hovered = False
        self._text_label = None
        self.setAcceptHoverEvents(True)
        self._apply_color()

    def _apply_color(self, color=None):
        """设置半透明底色。color 为 [r,g,b]；默认正常黑色。"""
        c = color or self._NORMAL_COLOR
        self.setBrush(QBrush(QColor(c[0], c[1], c[2], self._opacity)))
        self.setPen(QPen(Qt.NoPen))

    def _set_text_color(self, white: bool):
        """设置文本颜色：正常/悬停在白色底时文字取深色。"""
        if self._text_label is not None:
            self._text_label.setDefaultTextColor(QColor(255, 255, 255) if white else QColor(30, 30, 30))

    def hoverEnterEvent(self, event):
        self.is_hovered = True
        self._apply_color(self._HOVER_COLOR)
        self._set_text_color(False)  # 白色底 -> 深色文字
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event):
        self.is_hovered = False
        self._apply_color(self._NORMAL_COLOR)
        self._set_text_color(True)   # 恢复白色文字
        super().hoverLeaveEvent(event)

    def set_click_handler(self, handler):
        self.click_handler = handler

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self.click_handler:
            self.click_handler()
            event.accept()
            return
        super().mousePressEvent(event)
