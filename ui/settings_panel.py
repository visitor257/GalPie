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
    "fill_color": [255, 255, 255],  # 面板填充色（白）
    "fill_alpha": 217,            # 面板填充不透明度 (0-255)，217 ≈ 8.5/10
    "fade_duration": 500,         # 渐变显示时长 ms
    "border_offset": 10,          # [废弃-白圈已去掉] 原白色边框距面板边缘距离，现仅作为元素内边距 (px)
    "border_width": 10,           # [废弃-白圈已去掉] 原白色边框宽度，现仅参与 inner 计算 (px)
    "border_color": [255, 255, 255],  # [废弃-白圈已去掉] 原白色边框颜色
    "border_alpha": 217,          # [废弃-白圈已去掉] 原边框不透明度
    "button_radius": 12,          # 底部按钮圆角半径
    "button_height": 48,          # 底部按钮高度
    "button_margin": 24,          # 按钮与面板侧边的间距
    "button_bottom_margin": 10,   # 按钮底边距白色圈底部的间距
    "button_gap": 24,             # 按钮之间的间距
    "title_top_margin": 15,       # 标题顶部距白色圈内边界的间距 (px)
    "title_left_ratio": 0.05,     # 标题左侧距白色圈内边界的比例（白圈内宽的 %）
    "item_left_margin": 10,       # 设置项左侧距白圈内边界的间距 (px)
    "title_size": 26,             # 标题字号 (pt)
    "title_stroke_width": 2.0,    # 标题描边宽度 (px)，用于幼圆加粗
    "column_gap": 20,             # 左右两列之间的间距 (px)
    "item_gap": 24,               # 设置项之间的垂直间距 (px)
    "res_label_size": 18,         # 设置项标签字号 (pt)
    "res_value_size": 16,         # 设置项值字号 (pt)
    "res_arrow_size": 14,         # 设置项切换箭头字号 (pt)
    "button_color": [0, 0, 0],    # 按钮底色
    "button_opacity": 255,        # 按钮底色不透明度 (0-255)，255 = 不透明
    "z": 20,                      # 面板 Z 值（高于菜单按钮）
}

# 底部按钮文本（多语言；预设 UI 支持 zh/en/ja/ru）
BUTTON_TEXTS = {
    "reset": {"zh": "恢复默认", "en": "Reset", "ja": "リセット", "ru": "Сброс"},
    "back": {"zh": "返回", "en": "Back", "ja": "戻る", "ru": "Назад"},
    "quit": {"zh": "主菜单", "en": "Main Menu", "ja": "メインメニュー", "ru": "Главное меню"},
}

# 面板标题（多语言）
TITLE_TEXTS = {"zh": "游戏设置", "en": "Settings", "ja": "ゲーム設定", "ru": "Настройки"}

# 语言选择器可选项（JSON settings.language 中可被选中的语言）
SUPPORTED_LANGS = ["zh", "en", "ja", "ru"]
# 预设 UI 界面显示语言（仅支持中英日；超出此范围的语言界面回落 en）
UI_LANGS = ["zh", "en", "ja"]
# 语言选择器中的语言自称（不随面板语言变）
LANG_NAMES = {"zh": "中文", "en": "English", "ja": "日本語", "ru": "Русский"}

# 分辨率选项（多语言，切换时循环；实际可选项由 JSON 配置，末尾自动追加"全屏"）
RESOLUTIONS = ["1280x720", "1366x768", "1600x900", "1920x1080"]
RESOLUTION_LABEL = {"zh": "分辨率", "en": "Resolution", "ja": "解像度", "ru": "Разрешение"}
LANGUAGE_LABEL = {"zh": "语言", "en": "Language", "ja": "言語", "ru": "Язык"}
FULLSCREEN_LABEL = {"zh": "全屏", "en": "Fullscreen", "ja": "全画面", "ru": "Во весь экран"}
FULLSCREEN_KEY = "fullscreen"  # 内部标记：全屏选项（显示时用语言化文本）


class SettingsPanel(QGraphicsPathItem):
    """设置面板（场景覆盖层）。使用圆角路径实现圆角矩形。"""

    def __init__(self, scene, config=None, language="zh", current_resolution="1280x720",
                 resolution_options=None, language_options=None, parent=None):
        # 合并配置：优先自定义 config，缺省项回落到预设默认
        self.config = {**DEFAULT_PRESET, **(config or {})}
        # 预设 UI 显示语言：仅支持 zh/en/ja，超出回落 en
        self.language = language if language in UI_LANGS else "en"
        self.buttons = []   # 底部按钮列表
        self._button_handlers = {}  # 底部按钮 key -> click_handler（重建后自动重绑）
        # 分辨率选项：JSON 提供的分辨率列表 + 末尾"全屏"；无 JSON 时用默认列表
        base_opts = list(resolution_options) if resolution_options else list(RESOLUTIONS)
        self._res_options = base_opts + [FULLSCREEN_KEY]
        # 当前选项：先尝试原样匹配，再按显示文本匹配（"全屏" vs 语言化）
        self.current_resolution = self._normalize_res(current_resolution)
        # 语言选项：JSON settings.language 字典 {语言id: 语言名称}（兼容旧列表 [id,...]）
        # 面板仅支持其中 zh/en/ja，其余回落 en；名称用于面板值显示（如"中文"）
        if isinstance(language_options, dict):
            self._lang_names = dict(language_options)      # id -> 显示名称
            self._lang_options = list(language_options)     # id 列表
        elif language_options:
            self._lang_names = {}
            self._lang_options = list(language_options)
        else:
            self._lang_names = {}
            self._lang_options = ["zh"]
        self._normalize_lang_options()
        # 语言选择器当前值：用原始传入语言归一化（勿用回落后的 self.language，
        # 否则 ru 等支持语言重开面板时会丢失选择值显示）
        self.current_language = self._normalize_lang(language)
        self._language_handler = None  # 语言变更回调
        self._language_label = None    # "语言"标签
        self._language_value = None    # 当前语言值文本
        self._language_prev = None     # 上一个语言按钮
        self._language_next = None     # 下一个语言按钮

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

        # 面板圆角矩形填充（fill_color + fill_alpha 透明度）
        fill = self.config["fill_color"]
        fill_a = self.config.get("fill_alpha", 255)
        self.setBrush(QBrush(QColor(fill[0], fill[1], fill[2], fill_a)))
        self.setPen(QPen(Qt.NoPen))
        self.setZValue(self.config["z"])
        self._scene = scene
        self._anim = None
        self._title_item = None   # 标题文本（_build_title 创建）

        # 白色内边框：距边缘 border_offset，宽 border_width（作为面板子项，随面板移动）
        self._border_item = None
        self._rebuild_border()

    def _normalize_lang_options(self):
        """归一化语言选项列表：去重、保留顺序；仅保留预设 UI 支持的语言（zh/en/ja）。
        其余语言（如 ru）不在可选项中——用户无法在面板中选到它们（选了界面也只能回落 en）。
        """
        seen = []
        for lang in self._lang_options:
            if lang not in seen and lang in SUPPORTED_LANGS:
                seen.append(lang)
        self._lang_options = seen if seen else ["zh"]
        # 名称映射同步过滤（仅保留可选项；无自定义名时回落内置 LANG_NAMES）
        self._lang_names = {k: v for k, v in self._lang_names.items() if k in self._lang_options}

    def _normalize_lang(self, value):
        """当前语言值归一化：在选项中直接返回；否则回落选项第一个。"""
        if value in self._lang_options:
            return value
        return self._lang_options[0]

    def _lang_display_text(self):
        """当前语言的显示文本：优先 JSON settings.language 自定义名称，
        否则内置 LANG_NAMES（语言自称，不随面板语言变），最后回落 id 本身。"""
        return (self._lang_names.get(self.current_language)
                or LANG_NAMES.get(self.current_language, self.current_language))

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
        """白色内边框已废弃（用户要求去掉）：不再绘制。
        保留方法与配置项，避免破坏依赖 inner=border_offset+border_width 的布局几何；
        仅负责清理已存在的边框项。
        """
        if self._border_item is not None:
            if self._border_item.scene():
                self._scene.removeItem(self._border_item)
            self._border_item = None

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
        self._title_item.setBrush(QBrush(QColor(30, 30, 30)))
        self._title_item.setPen(QPen(Qt.NoPen))
        self._title_item.setAcceptHoverEvents(False)
        self._title_item.setParentItem(self)
        # 路径以 (0,0) 为基线起点，需按 boundingRect 重新定位
        r = self._title_item.boundingRect()
        self._title_item.setPos(left - r.x(), inner + top - r.y())
        return self._title_item

    def _build_language(self):
        """在右列创建语言设置项（右列第 1 个设置项）。
        布局与分辨率项一致：标签"语言"（幼圆加粗）+ 左右切换按钮 + 当前值。
        语言选项 = JSON settings.language 中预设 UI 支持的部分（zh/en/ja）。
        """
        _, right_rect = self._column_rects()
        inner = self.config["border_offset"] + self.config["border_width"]
        top = self.config.get("title_top_margin", 15)
        # 右列第 1 项与左列标题同高区域对齐（顶部同一行）
        row_y = inner + top
        row_h = 32
        item_left_margin = self.config.get("item_left_margin", 10)

        label_text = LANGUAGE_LABEL.get(self.language, LANGUAGE_LABEL["en"])
        # 标签（幼圆加粗 18pt），距白圈内边界 item_left_margin
        self._language_label = QGraphicsTextItem()
        self._language_label.setPlainText(label_text)
        self._language_label.setDefaultTextColor(QColor(30, 30, 30))
        lf = QFont("YouYuan")
        lf.setBold(True)
        lf.setPointSize(self.config.get("res_label_size", 18))
        self._language_label.setFont(lf)
        self._language_label.setAcceptHoverEvents(False)
        self._language_label.setTextInteractionFlags(Qt.NoTextInteraction)  # 禁止文本交互，避免拦截鼠标
        self._language_label.setCursor(Qt.ArrowCursor)  # 悬停保持箭头，避免 IBeam
        self._language_label.setParentItem(self)
        self._language_label.setTextWidth(-1)
        rl = self._language_label.boundingRect()
        label_x = right_rect.left() + item_left_margin
        self._language_label.setPos(label_x, row_y + (row_h - rl.height()) / 2)

        # 左右切换按钮（◀ ▶）放在右列右侧；右箭头右边缘距白圈内边界 item_left_margin
        # （与左侧“分辨率”标签距白圈的距离一致），避免贴圈太近
        btn_w = 28
        btn_h = row_h
        btn_y = row_y
        prev_x = right_rect.right() - item_left_margin - 2 * btn_w - 8
        next_x = right_rect.right() - item_left_margin - btn_w
        self._language_prev = SettingsButtonItem(
            QRectF(prev_x, btn_y, btn_w, btn_h), "lang_prev", self, opacity=255)
        self._language_next = SettingsButtonItem(
            QRectF(next_x, btn_y, btn_w, btn_h), "lang_next", self, opacity=255)
        self._language_prev.set_click_handler(self._on_lang_prev)
        self._language_next.set_click_handler(self._on_lang_next)
        self._add_button_text("◀", self._language_prev,
                              [255, 255, 255], QFont("Microsoft YaHei", 12, QFont.Bold))
        self._add_button_text("▶", self._language_next,
                              [255, 255, 255], QFont("Microsoft YaHei", 12, QFont.Bold))

        # 当前值（幼圆常规 16pt）：居中于 标签右边缘 与 左箭头左边缘 之间
        self._language_value = QGraphicsTextItem()
        self._language_value.setPlainText(self._lang_display_text())
        self._language_value.setDefaultTextColor(QColor(30, 30, 30))
        vf = QFont("YouYuan")
        vf.setPointSize(self.config.get("res_value_size", 16))
        self._language_value.setFont(vf)
        self._language_value.setAcceptHoverEvents(False)
        self._language_value.setTextInteractionFlags(Qt.NoTextInteraction)  # 禁止文本交互，避免拦截鼠标
        self._language_value.setCursor(Qt.ArrowCursor)  # 悬停保持箭头，避免 IBeam
        self._language_value.setParentItem(self)
        self._language_value.setTextWidth(-1)
        rv = self._language_value.boundingRect()
        label_right = label_x + rl.width()
        gap_mid = (label_right + prev_x) / 2.0
        val_x = gap_mid - rv.width() / 2.0
        self._language_value.setPos(val_x, row_y + (row_h - rv.height()) / 2)

    def _on_lang_prev(self):
        idx = self._lang_options.index(self.current_language)
        self.current_language = self._lang_options[(idx - 1) % len(self._lang_options)]
        self._update_language_display()

    def _on_lang_next(self):
        idx = self._lang_options.index(self.current_language)
        self.current_language = self._lang_options[(idx + 1) % len(self._lang_options)]
        self._update_language_display()

    def _update_language_display(self):
        if self._language_value is not None:
            self._language_value.setPlainText(self._lang_display_text())
            self._language_value.setTextWidth(-1)
        if self._language_handler:
            # 回调传语言代码（如 zh/en/ja），由 main_window 更新 controller.language 并刷新面板
            self._language_handler(self.current_language)

    def set_language_handler(self, handler):
        """绑定语言变更回调（main_window 中调用，实际切换游戏语言并刷新面板 UI）。"""
        self._language_handler = handler

    @property
    def lang_options(self):
        """当前语言选项列表（预设 UI 支持的部分）。"""
        return list(self._lang_options)

    def _clear_language_items(self):
        """移除语言设置项的文本与按钮（尺寸变化/关闭/语言切换重建时调用）。"""
        for item in (self._language_label, self._language_value,
                     self._language_prev, self._language_next):
            if item is not None and item.scene():
                self._scene.removeItem(item)
        for b in (self._language_prev, self._language_next):
            if b is not None:
                label = getattr(b, "_text_label", None)
                if label is not None and label.scene():
                    self._scene.removeItem(label)
        self._language_label = None
        self._language_value = None
        self._language_prev = None
        self._language_next = None

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
        # 设置项左侧距白圈内边界的间距
        item_left_margin = self.config.get("item_left_margin", 10)

        # 第 1 项（标题）底部位置：inner+top + 标题高度
        title_h = self._title_item.boundingRect().height() if self._title_item else 0
        row_y = inner + top + title_h + item_gap
        row_h = 32

        label_text = RESOLUTION_LABEL.get(self.language, RESOLUTION_LABEL["zh"])
        # 标签（幼圆加粗 18pt），距白圈内边界 item_left_margin
        self._resolution_label = QGraphicsTextItem()
        self._resolution_label.setPlainText(label_text)
        self._resolution_label.setDefaultTextColor(QColor(30, 30, 30))
        lf = QFont("YouYuan")
        lf.setBold(True)
        lf.setPointSize(self.config.get("res_label_size", 18))
        self._resolution_label.setFont(lf)
        self._resolution_label.setAcceptHoverEvents(False)
        self._resolution_label.setTextInteractionFlags(Qt.NoTextInteraction)  # 禁止文本交互，避免拦截鼠标
        self._resolution_label.setCursor(Qt.ArrowCursor)  # 悬停保持箭头，避免 IBeam
        self._resolution_label.setParentItem(self)
        self._resolution_label.setTextWidth(-1)
        rl = self._resolution_label.boundingRect()
        label_x = left_rect.left() + item_left_margin
        self._resolution_label.setPos(label_x, row_y + (row_h - rl.height()) / 2)

        # 左右切换按钮（◀ ▶）放在左列右侧
        btn_w = 28
        btn_h = row_h
        btn_y = row_y
        prev_x = left_rect.right() - 2 * btn_w - 8
        next_x = left_rect.right() - btn_w
        self._resolution_prev = SettingsButtonItem(
            QRectF(prev_x, btn_y, btn_w, btn_h), "res_prev", self, opacity=255)
        self._resolution_next = SettingsButtonItem(
            QRectF(next_x, btn_y, btn_w, btn_h), "res_next", self, opacity=255)
        self._resolution_prev.set_click_handler(self._on_res_prev)
        self._resolution_next.set_click_handler(self._on_res_next)
        # 按钮文本（作为面板子项）
        self._add_button_text("◀", self._resolution_prev,
                              [255, 255, 255], QFont("Microsoft YaHei", 12, QFont.Bold))
        self._add_button_text("▶", self._resolution_next,
                              [255, 255, 255], QFont("Microsoft YaHei", 12, QFont.Bold))

        # 当前值（幼圆常规 16pt）：居中于 标签右边缘 与 左箭头左边缘 之间
        self._resolution_value = QGraphicsTextItem()
        self._resolution_value.setPlainText(self._res_display_text())
        self._resolution_value.setDefaultTextColor(QColor(30, 30, 30))
        vf = QFont("YouYuan")
        vf.setPointSize(self.config.get("res_value_size", 16))
        self._resolution_value.setFont(vf)
        self._resolution_value.setAcceptHoverEvents(False)
        self._resolution_value.setTextInteractionFlags(Qt.NoTextInteraction)  # 禁止文本交互，避免拦截鼠标
        self._resolution_value.setCursor(Qt.ArrowCursor)  # 悬停保持箭头，避免 IBeam
        self._resolution_value.setParentItem(self)
        self._resolution_value.setTextWidth(-1)
        rv = self._resolution_value.boundingRect()
        label_right = label_x + rl.width()
        gap_mid = (label_right + prev_x) / 2.0
        val_x = gap_mid - rv.width() / 2.0
        self._resolution_value.setPos(val_x, row_y + (row_h - rv.height()) / 2)

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
            # 重建后自动重绑已注册的点击处理器（语言/重置重建会丢 handler）
            handler = self._button_handlers.get(key)
            if handler:
                btn.set_click_handler(handler)
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
        self._clear_language_items()
        self._build_buttons()
        self._build_title()
        self._build_resolution()
        self._build_language()
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
        self._clear_language_items()
        if self.scene() == scene:
            scene.removeItem(self)

    def set_language(self, lang):
        """切换设置面板显示语言并重建全部 UI 文字。
        预设 UI 仅支持 zh/en/ja；超出范围的语言界面回落 en（但语言选择器值仍显示该语言自称）。
        由 main_window 的语言回调调用（controller.language 已更新）。
        """
        # 实际显示语言：预设 UI 支持才用，否则回落 en
        ui_lang = lang if lang in UI_LANGS else "en"
        self.language = ui_lang
        # 语言选择器当前值：仅在选项内时更新（选中的语言一定是选项内）
        self.current_language = self._normalize_lang(lang)
        # 重建全部 UI 文字（标题、底部按钮、分辨率项、语言项）
        if self._title_item is not None and self._title_item.scene():
            self._scene.removeItem(self._title_item)
        self._title_item = None
        self._clear_resolution_items()
        self._clear_language_items()
        # 重建底部按钮（文字随语言变）
        for b in list(self.buttons):
            label = getattr(b, "_text_label", None)
            if label is not None and label.scene():
                self._scene.removeItem(label)
            if b.scene():
                self._scene.removeItem(b)
        self.buttons = []
        self._build_buttons()
        self._build_title()
        self._build_resolution()
        self._build_language()

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
        label.setTextInteractionFlags(Qt.NoTextInteraction)  # 禁止文本交互，避免拦截鼠标
        label.setCursor(Qt.ArrowCursor)  # 文本悬停保持箭头，避免 IBeam
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
        btn._text_label = label  # 记录，便于后续调整（注意：必须挂到传入的 btn，而非 self.buttons[-1]）
        return label

    def button(self, key):
        """按 key（reset/back/quit）返回按钮 item；无则 None。"""
        for b in self.buttons:
            if b.key == key:
                return b
        return None

    def set_button_handler(self, key, handler):
        """注册底部按钮点击处理器并立即绑定。
        注册表保留 handler，语言切换/重置导致按钮重建后自动重绑。
        """
        self._button_handlers[key] = handler
        btn = self.button(key)
        if btn:
            btn.set_click_handler(handler)


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
        self.setCursor(Qt.ArrowCursor)  # 悬停保持箭头光标，避免文本默认 IBeam
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
