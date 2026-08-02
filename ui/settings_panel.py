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
from PySide6.QtGui import QColor, QBrush, QPen, QFont, QPainterPath, QPainterPathStroker

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
    "button_margin": 24,          # 按钮与面板侧边的间距
    "button_bottom_margin": 10,   # 按钮底边距白色圈底部的间距
    "button_gap": 24,             # 按钮之间的间距
    "title_top_margin": 15,       # 标题顶部距白色圈内边界的间距 (px)
    "title_left_ratio": 0.05,     # 标题左侧距白色圈内边界的比例（白圈内宽的 %）
    "title_size": 26,             # 标题字号 (pt)
    "title_stroke_width": 2.0,    # 标题描边宽度 (px)，用于幼圆加粗
    "column_gap": 20,             # 左右两列之间的间距 (px)
    "item_gap": 24,               # 设置项之间的垂直间距 (px)
    "res_label_size": 18,         # 设置项标签字号 (pt)
    "res_value_size": 16,         # 设置项值字号 (pt)
    "res_arrow_size": 14,         # 设置项切换箭头字号 (pt)
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

# 面板标题（多语言）
TITLE_TEXTS = {"zh": "游戏设置", "en": "Settings"}

# 分辨率选项（多语言，切换时循环；实际可选项由 JSON 配置，末尾自动追加"全屏"）
RESOLUTIONS = ["1280x720", "1366x768", "1600x900", "1920x1080"]
RESOLUTION_LABEL = {"zh": "分辨率", "en": "Resolution"}
FULLSCREEN_LABEL = {"zh": "全屏", "en": "Fullscreen"}
FULLSCREEN_KEY = "fullscreen"  # 内部标记：全屏选项（显示时用语言化文本）


class SettingsPanel(QGraphicsPathItem):
    """设置面板（场景覆盖层）。使用圆角路径实现圆角矩形。"""

    def __init__(self, scene, config=None, language="zh", current_resolution="1280x720",
                 resolution_options=None, parent=None):
        # 合并配置：优先自定义 config，缺省项回落到预设默认
        self.config = {**DEFAULT_PRESET, **(config or {})}
        self.language = language
        self.buttons = []   # 底部按钮列表
        # 分辨率选项：JSON 提供的分辨率列表 + 末尾"全屏"；无 JSON 时用默认列表
        base_opts = list(resolution_options) if resolution_options else list(RESOLUTIONS)
        self._res_options = base_opts + [FULLSCREEN_KEY]
        # 当前选项：先尝试原样匹配，再按显示文本匹配（"全屏" vs 语言化）
        self.current_resolution = self._normalize_res(current_resolution)
        self._resolution_handler = None  # 分辨率变更回调
        self._resolution_label = None    # "分辨率" 标签
        self._resolution_value = None    # 当前分辨率值文本
        self._resolution_prev = None     # 上一个分辨率按钮
        self._resolution_next = None     # 下一个分辨率按钮

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
        self._title_item = None   # 标题文本（_build_title 创建）

        # 白色内边框：距边缘 border_offset，宽 border_width（作为面板子项，随面板移动）
        self._border_item = None
        self._rebuild_border()

    def _normalize_res(self, value):
        """把当前分辨率值归一化到选项列表：
        - 已是选项值（如 "1280x720"）直接返回
        - 语言化的"全屏"（zh/en）映射为 FULLSCREEN_KEY
        - 其它不匹配时回落到选项第一个
        """
        if value in self._res_options:
            return value
        # 语言化全屏文本 -> 内部标记
        for key, label in FULLSCREEN_LABEL.items():
            if value == label:
                return FULLSCREEN_KEY
        return self._res_options[0]

    def _res_display_text(self):
        """当前选项的显示文本：全屏用语言化文本，窗口分辨率原样。"""
        if self.current_resolution == FULLSCREEN_KEY:
            return FULLSCREEN_LABEL.get(self.language, FULLSCREEN_LABEL["zh"])
        return self.current_resolution

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

    def _column_rects(self):
        """计算左右两列几何（白圈内空间，各 50%）。
        返回 (left_rect, right_rect) —— 面板局部坐标。
        """
        inner = self.config["border_offset"] + self.config["border_width"]
        gap = self.config.get("column_gap", 20)
        avail_w = self._size[0] - 2 * inner
        col_w = (avail_w - gap) / 2.0
        left = QRectF(inner, inner, col_w, self._size[1] - 2 * inner)
        right = QRectF(inner + col_w + gap, inner, col_w, self._size[1] - 2 * inner)
        return left, right

    def _build_title(self):
        """在左列顶部创建标题文本（左列第 1 个设置项）。
        顶部距白框内边界 title_top_margin，左侧距左列内边界 title_left_ratio * 列宽。
        使用 QGraphicsPathItem + 描边实现真正加粗（幼圆无粗体字重，Qt 伪粗体效果有限）。
        """
        inner = self.config["border_offset"] + self.config["border_width"]
        top = self.config.get("title_top_margin", 15)
        left_ratio = self.config.get("title_left_ratio", 0.05)
        left_rect, _ = self._column_rects()
        left = left_rect.left() + left_rect.width() * left_ratio
        text = TITLE_TEXTS.get(self.language, TITLE_TEXTS["zh"])

        # 幼圆 + 加粗（圆润字体，已安装系统字体）
        font = QFont("YouYuan")
        font.setBold(True)
        font.setPointSize(self.config.get("title_size", 26))

        # 生成文字路径 + 描边加粗（描边宽 title_stroke_width，默认 2.0）
        stroke_w = self.config.get("title_stroke_width", 2.0)
        path = QPainterPath()
        path.addText(QPointF(0, 0), font, text)
        if stroke_w > 0:
            stroker = QPainterPathStroker()
            stroker.setWidth(stroke_w)
            stroker.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            stroker.setCapStyle(Qt.PenCapStyle.RoundCap)
            path = stroker.createStroke(path).united(path)

        self._title_item = QGraphicsPathItem(path)
        self._title_item.setBrush(QBrush(QColor(255, 255, 255)))
        self._title_item.setPen(QPen(Qt.NoPen))
        self._title_item.setAcceptHoverEvents(False)
        self._title_item.setParentItem(self)
        # 路径以 (0,0) 为基线起点，需按 boundingRect 重新定位
        r = self._title_item.boundingRect()
        self._title_item.setPos(left - r.x(), inner + top - r.y())
        return self._title_item

    def _build_resolution(self):
        """在左列创建分辨率设置项（左列第 2 个设置项）。
        布局：
          - 标签"分辨率"（幼圆加粗）在左列内左侧
          - 当前值文本（幼圆常规）紧随标签
          - 左右两个小按钮（◀ ▶）用于切换分辨率
        """
        left_rect, _ = self._column_rects()
        inner = self.config["border_offset"] + self.config["border_width"]
        top = self.config.get("title_top_margin", 15)
        item_gap = self.config.get("item_gap", 24)

        # 第 1 项（标题）底部位置：inner+top + 标题高度
        title_h = self._title_item.boundingRect().height() if self._title_item else 0
        row_y = inner + top + title_h + item_gap
        row_h = 32

        label_text = RESOLUTION_LABEL.get(self.language, RESOLUTION_LABEL["zh"])
        # 标签（幼圆加粗 18pt）
        self._resolution_label = QGraphicsTextItem()
        self._resolution_label.setPlainText(label_text)
        self._resolution_label.setDefaultTextColor(QColor(255, 255, 255))
        lf = QFont("YouYuan")
        lf.setBold(True)
        lf.setPointSize(self.config.get("res_label_size", 18))
        self._resolution_label.setFont(lf)
        self._resolution_label.setAcceptHoverEvents(False)
        self._resolution_label.setParentItem(self)
        self._resolution_label.setTextWidth(-1)
        rl = self._resolution_label.boundingRect()
        self._resolution_label.setPos(left_rect.left(), row_y + (row_h - rl.height()) / 2)

        # 当前值（幼圆常规 16pt）
        self._resolution_value = QGraphicsTextItem()
        self._resolution_value.setPlainText(self._res_display_text())
        self._resolution_value.setDefaultTextColor(QColor(255, 255, 255))
        vf = QFont("YouYuan")
        vf.setPointSize(self.config.get("res_value_size", 16))
        self._resolution_value.setFont(vf)
        self._resolution_value.setAcceptHoverEvents(False)
        self._resolution_value.setParentItem(self)
        self._resolution_value.setTextWidth(-1)
        rv = self._resolution_value.boundingRect()
        # 值放在标签右侧
        val_x = left_rect.left() + rl.width() + 16
        self._resolution_value.setPos(val_x, row_y + (row_h - rv.height()) / 2)

        # 左右切换按钮（◀ ▶）放在左列右侧
        btn_w = 28
        btn_h = row_h
        btn_y = row_y
        prev_x = left_rect.right() - 2 * btn_w - 8
        next_x = left_rect.right() - btn_w
        self._resolution_prev = SettingsButtonItem(
            QRectF(prev_x, btn_y, btn_w, btn_h), "res_prev", self, opacity=80)
        self._resolution_next = SettingsButtonItem(
            QRectF(next_x, btn_y, btn_w, btn_h), "res_next", self, opacity=80)
        self._resolution_prev.set_click_handler(self._on_res_prev)
        self._resolution_next.set_click_handler(self._on_res_next)
        # 按钮文本（作为面板子项）
        self._add_button_text("◀", self._resolution_prev,
                              [255, 255, 255], QFont("Microsoft YaHei", 12, QFont.Bold))
        self._add_button_text("▶", self._resolution_next,
                              [255, 255, 255], QFont("Microsoft YaHei", 12, QFont.Bold))

    def _on_res_prev(self):
        idx = self._res_options.index(self.current_resolution)
        self.current_resolution = self._res_options[(idx - 1) % len(self._res_options)]
        self._update_resolution_display()

    def _on_res_next(self):
        idx = self._res_options.index(self.current_resolution)
        self.current_resolution = self._res_options[(idx + 1) % len(self._res_options)]
        self._update_resolution_display()

    def _update_resolution_display(self):
        if self._resolution_value is not None:
            self._resolution_value.setPlainText(self._res_display_text())
            self._resolution_value.setTextWidth(-1)
        if self._resolution_handler:
            # 回调传原始选项值（FULLSCREEN_KEY 或 "WxH"），由 main_window 决定全屏/窗口
            self._resolution_handler(self.current_resolution)

    def set_resolution_handler(self, handler):
        """绑定分辨率变更回调（main_window 中调用，实际执行窗口缩放）。"""
        self._resolution_handler = handler

    @property
    def res_options(self):
        """当前分辨率选项列表（含全屏，内部标记）。"""
        return list(self._res_options)

    def _clear_resolution_items(self):
        """移除分辨率设置项的文本与按钮（尺寸变化/关闭时调用）。"""
        for item in (self._resolution_label, self._resolution_value,
                     self._resolution_prev, self._resolution_next):
            if item is not None and item.scene():
                self._scene.removeItem(item)
        # 按钮文本（_text_label 是面板子项，需一并移除）
        for b in (self._resolution_prev, self._resolution_next):
            if b is not None:
                label = getattr(b, "_text_label", None)
                if label is not None and label.scene():
                    self._scene.removeItem(label)
        self._resolution_label = None
        self._resolution_value = None
        self._resolution_prev = None
        self._resolution_next = None

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
        # 按钮底边距白色框内边缘 button_bottom_margin
        y = h - inner - btn_h - self.config["button_bottom_margin"]

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
        # 移除旧标题（尺寸变化时重建）
        if self._title_item is not None and self._title_item.scene():
            self._scene.removeItem(self._title_item)
        self._title_item = None
        self._clear_resolution_items()
        self._build_buttons()
        self._build_title()
        self._build_resolution()
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
        if self._title_item is not None and self._title_item.scene():
            scene.removeItem(self._title_item)
            self._title_item = None
        self._clear_resolution_items()
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
