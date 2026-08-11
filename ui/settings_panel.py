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
import html as _html
from PySide6.QtWidgets import (
    QGraphicsPathItem, QGraphicsOpacityEffect, QGraphicsTextItem,
    QGraphicsProxyWidget, QTextEdit, QScrollBar, QGraphicsRectItem
)
from PySide6.QtCore import QRectF, QPropertyAnimation, QEasingCurve, Qt, QPointF
from PySide6.QtGui import QColor, QBrush, QPen, QFont, QPainter, QPixmap, QPainterPath, QPainterPathStroker, QTextOption

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
        # JSON 自定义配色（menu_pos.settings 第 3 项，default 预设模式也可配）：
        #   color       面板背景色 RGBA（覆盖 fill_color/fill_alpha）
        #   text_color  面板文字色 RGB（标题/标签/值；不含按钮文字）
        #   button_color 按钮底色 RGBA（底部按钮与箭头按钮；按钮文字按亮度自动切黑白）
        _cfg_color = self.config.get("color")
        if isinstance(_cfg_color, (list, tuple)) and len(_cfg_color) >= 3:
            self.config["fill_color"] = list(_cfg_color[:3])
            if len(_cfg_color) >= 4:
                self.config["fill_alpha"] = _cfg_color[3]
        _cfg_text = self.config.get("text_color")
        self._text_color = list(_cfg_text[:3]) if isinstance(_cfg_text, (list, tuple)) and len(_cfg_text) >= 3 else None
        _cfg_btn = self.config.get("button_color")
        self._button_color = list(_cfg_btn) if isinstance(_cfg_btn, (list, tuple)) and len(_cfg_btn) >= 3 else None
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

    def _text_rgb(self):
        """面板文字颜色（标题/标签/值，不含按钮文字）。
        JSON text_color 配置时用配置值，否则预设深灰 (30,30,30)。"""
        return self._text_color if self._text_color is not None else [30, 30, 30]

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
        tc = self._text_rgb()
        self._title_item.setBrush(QBrush(QColor(tc[0], tc[1], tc[2])))
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
        tc = self._text_rgb()
        self._language_label.setDefaultTextColor(QColor(tc[0], tc[1], tc[2]))
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
            QRectF(prev_x, btn_y, btn_w, btn_h), "lang_prev", self, opacity=255,
            button_color=self._button_color)
        self._language_next = SettingsButtonItem(
            QRectF(next_x, btn_y, btn_w, btn_h), "lang_next", self, opacity=255,
            button_color=self._button_color)
        self._language_prev.set_click_handler(self._on_lang_prev)
        self._language_next.set_click_handler(self._on_lang_next)
        self._add_button_text("◀", self._language_prev,
                              self._btn_text_normal_rgb(), QFont("Microsoft YaHei", 12, QFont.Bold))
        self._add_button_text("▶", self._language_next,
                              self._btn_text_normal_rgb(), QFont("Microsoft YaHei", 12, QFont.Bold))

        # 当前值（幼圆常规 16pt）：居中于 标签右边缘 与 左箭头左边缘 之间
        self._language_value = QGraphicsTextItem()
        self._language_value.setPlainText(self._lang_display_text())
        tc = self._text_rgb()
        self._language_value.setDefaultTextColor(QColor(tc[0], tc[1], tc[2]))
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
        tc = self._text_rgb()
        self._resolution_label.setDefaultTextColor(QColor(tc[0], tc[1], tc[2]))
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
            QRectF(prev_x, btn_y, btn_w, btn_h), "res_prev", self, opacity=255,
            button_color=self._button_color)
        self._resolution_next = SettingsButtonItem(
            QRectF(next_x, btn_y, btn_w, btn_h), "res_next", self, opacity=255,
            button_color=self._button_color)
        self._resolution_prev.set_click_handler(self._on_res_prev)
        self._resolution_next.set_click_handler(self._on_res_next)
        # 按钮文本（作为面板子项）
        self._add_button_text("◀", self._resolution_prev,
                              self._btn_text_normal_rgb(), QFont("Microsoft YaHei", 12, QFont.Bold))
        self._add_button_text("▶", self._resolution_next,
                              self._btn_text_normal_rgb(), QFont("Microsoft YaHei", 12, QFont.Bold))

        # 当前值（幼圆常规 16pt）：居中于 标签右边缘 与 左箭头左边缘 之间
        self._resolution_value = QGraphicsTextItem()
        self._resolution_value.setPlainText(self._res_display_text())
        tc = self._text_rgb()
        self._resolution_value.setDefaultTextColor(QColor(tc[0], tc[1], tc[2]))
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
            btn = SettingsButtonItem(rect, key, self, opacity=opacity,
                                     button_color=self._button_color)
            self.buttons.append(btn)
            # 重建后自动重绑已注册的点击处理器（语言/重置重建会丢 handler）
            handler = self._button_handlers.get(key)
            if handler:
                btn.set_click_handler(handler)
            # 文本作为面板子项，定位到按钮中心（初始色按按钮亮度规则）
            text = BUTTON_TEXTS[key].get(self.language, BUTTON_TEXTS[key]["zh"])
            self._add_button_text(text, btn,
                                  self._btn_text_normal_rgb(), QFont("Microsoft YaHei", 13, QFont.Bold))

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

    def _btn_text_normal_rgb(self):
        """按钮正常态文字色：有 button_color 时按亮度（sum<383 白 / ≥383 黑）；
        无 button_color 时预设 dark 模式为白。"""
        if self._button_color is not None:
            s = sum(self._button_color[:3])
            return [255, 255, 255] if s < 383 else [0, 0, 0]
        return [255, 255, 255]

    def _add_button_text(self, text, btn, rgb, font):
        """在按钮中心上方叠加文本。文本作为面板子项（与按钮平级），
        用按钮的面板局部坐标定位，避免嵌套子项在父项未入 scene 时的偏移。
        返回创建的文本 item。
        """
        label = QGraphicsTextItem()
        label.setPlainText(text)
        if len(rgb) >= 4:
            label.setDefaultTextColor(QColor(rgb[0], rgb[1], rgb[2], rgb[3]))
        else:
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
    _NORMAL_COLOR_LIGHT = [255, 255, 255]  # 浅色模式正常：白底
    _HOVER_COLOR_LIGHT = [0, 0, 0]         # 浅色模式悬停：黑底

    def _mode_normal_color(self):
        if self._button_color is not None:
            return list(self._button_color[:3])  # 正常时按钮底色 = JSON button_color 原值
        return self._NORMAL_COLOR_LIGHT if self._color_mode == "light" else self._NORMAL_COLOR

    def _mode_hover_color(self):
        if self._button_color is not None:
            return [255, 255, 255] if sum(self._button_color[:3]) < 383 else [0, 0, 0]  # 悬停切白/黑底
        return self._HOVER_COLOR_LIGHT if self._color_mode == "light" else self._HOVER_COLOR

    def __init__(self, rect: QRectF, key: str, parent=None, opacity=90, color_mode="dark", button_color=None):
        path = QPainterPath()
        path.addRoundedRect(rect, 12, 12)
        super().__init__(path, parent)
        self.key = key
        self.click_handler = None
        self._rect = rect
        self._opacity = opacity
        self._color_mode = color_mode
        self._button_color = list(button_color) if button_color else None  # "dark": 黑底白字（默认）；"light": 白底黑字
        self.is_hovered = False
        self._text_label = None
        self.setAcceptHoverEvents(True)
        self.setCursor(Qt.ArrowCursor)  # 悬停保持箭头光标，避免文本默认 IBeam
        self._apply_color()

    def _apply_color(self, color=None):
        """设置半透明底色。color 为 [r,g,b]；默认正常黑色。"""
        c = color or self._mode_normal_color()
        if self._button_color is not None:
            a = self._button_color[3] if len(self._button_color) > 3 else 255
        else:
            a = self._opacity
        self.setBrush(QBrush(QColor(c[0], c[1], c[2], a)))
        self.setPen(QPen(Qt.NoPen))

    def _set_text_color(self, white: bool):
        """设置文本颜色：正常/悬停在白色底时文字取深色。"""
        if self._text_label is None:
            return
        if self._button_color is not None:
            s = sum(self._button_color[:3])
            if s < 383:
                c = QColor(255, 255, 255, 255) if white else QColor(0, 0, 0, 255)
            else:
                c = QColor(0, 0, 0, 255) if white else QColor(255, 255, 255, 255)
            self._text_label.setDefaultTextColor(c)
            return
        if self._color_mode == "light":
            self._text_label.setDefaultTextColor(QColor(0, 0, 0) if white else QColor(255, 255, 255))
        else:
            self._text_label.setDefaultTextColor(QColor(255, 255, 255) if white else QColor(30, 30, 30))

    def hoverEnterEvent(self, event):
        self.is_hovered = True
        self._apply_color(self._mode_hover_color())
        self._set_text_color(False)  # 白色底 -> 深色文字
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event):
        self.is_hovered = False
        self._apply_color(self._mode_normal_color())
        self._set_text_color(True)   # 恢复白色文字
        super().hoverLeaveEvent(event)

    def reset_hover(self):
        """重置悬停状态（面板打开隐藏前调用，避免恢复可见时残留悬停样式）。"""
        self.is_hovered = False
        self._apply_color(self._mode_normal_color())
        self._set_text_color(True)   # 正常色文字

    def set_click_handler(self, handler):
        self.click_handler = handler

    def mousePressEvent(self, event):
        if not self.isVisible():
            # 面板（设置/日志）打开时底部按钮被隐藏：忽略点击，防止误触发
            event.ignore()
            return
        if event.button() == Qt.LeftButton and self.click_handler:
            self.click_handler()
            event.accept()
            return
        super().mousePressEvent(event)


class BacklogPanel(QGraphicsPathItem):
    """日志面板（同窗口内覆盖层，与 SettingsPanel 同尺寸同形状）。

    尺寸/形状：与设置面板一致（margin_ratio 0.1 -> 0.8*窗口，圆角半径 24）。
    填充颜色：来自 JSON bottom_menu.backlog_bgcolor（RGBA 列表），缺省白色半透明 [255,255,255,200]。
    左侧返回按钮：从顶到底，距面板边缘 10px，宽 = 面板宽 15%；文字 ◀ 换行 返回(zh) / Back(en/ja/ru)。
    点击返回按钮调用 on_back（由 main_window 传入，通常为关闭面板）。
    """

    def __init__(self, scene, bg_color=None, language="zh", on_back=None, parent=None):
        self._bg_color = list(bg_color) if bg_color else [255, 255, 255, 200]
        # 兼容 3 元素 RGB（无 alpha），补默认 alpha 200
        if len(self._bg_color) == 3:
            self._bg_color.append(200)
        self._size = [100, 100]
        self._corner_radius = 24
        self._margin_ratio = 0.1
        self._fade_duration = 500
        self._language = language if language in ("zh", "en", "ja", "ru") else "zh"
        self._on_back = on_back
        self._back_btn = None    # 左侧返回按钮
        self._back_label = None  # 返回按钮文字
        self._log_proxy = None   # 日志内容区（QGraphicsProxyWidget + QTextEdit）
        self._log_edit = None    # 日志 QTextEdit（只读）
        path = QPainterPath()
        path.addRoundedRect(QRectF(0, 0, self._size[0], self._size[1]),
                            self._corner_radius, self._corner_radius)
        super().__init__(path, parent)
        self.setBrush(QBrush(QColor(self._bg_color[0], self._bg_color[1],
                                    self._bg_color[2], self._bg_color[3])))
        self.setPen(QPen(Qt.NoPen))
        self.setZValue(60)  # 高于设置面板(20)和底部菜单(9)
        self._scene = scene
        self._anim = None

    def center_in_scene(self, scene_rect):
        """按距窗口边缘 margin_ratio（默认 10%）计算尺寸并居中（同设置面板）。"""
        w_avail = scene_rect.width()
        h_avail = scene_rect.height()
        w = max(10, int(w_avail * (1 - 2 * self._margin_ratio)))
        h = max(10, int(h_avail * (1 - 2 * self._margin_ratio)))
        self._size = [w, h]
        path = QPainterPath()
        path.addRoundedRect(QRectF(0, 0, w, h), self._corner_radius, self._corner_radius)
        self.setPath(path)
        x = scene_rect.left() + (w_avail - w) / 2
        y = scene_rect.top() + (h_avail - h) / 2
        self.setPos(x, y)
        self._build_back_button()

    def _build_back_button(self):
        """左侧返回按钮：从顶部到底部，距面板边缘 10px，宽 = 面板宽 15%。
        文字：◀ 换行 返回(zh) / Back(en/ja/ru)。点击调用 on_back。
        按钮与文字为场景独立 item，绝对位置 = 面板 pos + 局部偏移。
        """
        # 清除旧按钮/文字
        self._back_btn = None
        self._back_label = None

        w, h = self._size
        margin = 10
        btn_w = max(20, int(w * 0.15)) - 2 * margin  # 宽 15% 再留左右边距
        btn_h = h - 2 * margin                       # 从顶到底留上下边距
        rect = QRectF(margin, margin, btn_w, btn_h)

        # 按 backlog_bgcolor 亮度选配色：r+g+b>382 深色模式，否则浅色模式
        bg_sum = (self._bg_color[0] if len(self._bg_color) > 0 else 255) \
               + (self._bg_color[1] if len(self._bg_color) > 1 else 255) \
               + (self._bg_color[2] if len(self._bg_color) > 2 else 255)
        color_mode = "dark" if bg_sum > 382 else "light"
        btn = SettingsButtonItem(rect, "backlog_back", self, opacity=90, color_mode=color_mode)
        btn.set_click_handler(self._on_back if self._on_back else (lambda: None))
        self._back_btn = btn

        # 文字：两行（◀ 换行 返回/Back），幼圆字体，左右居中
        text = "◀\n" + ("返回" if self._language == "zh" else "Back")
        label = QGraphicsTextItem(text, self)
        # 正常文字色：dark 模式白字，light 模式黑字
        label.setDefaultTextColor(QColor(255, 255, 255) if color_mode == "dark" else QColor(0, 0, 0))
        font = QFont("幼圆")
        font.setPointSize(20)
        font.setBold(True)
        label.setFont(font)
        label.setAcceptHoverEvents(False)
        label.setTextInteractionFlags(Qt.NoTextInteraction)
        label.setCursor(Qt.ArrowCursor)
        # 左右居中：文档宽度 = 按钮宽，文字水平居中
        label.setTextWidth(rect.width())
        label.document().setDefaultTextOption(QTextOption(Qt.AlignCenter))
        br = label.boundingRect()
        label.setPos(rect.center().x() - rect.width() / 2,
                     rect.center().y() - br.height() / 2)
        self._back_label = label

        btn.setZValue(61)
        label.setZValue(62)
        btn._text_label = label  # 悬停变色：文字白色<->深色
        self._build_log_area()

    def _build_log_area(self):
        """构建日志内容区：返回按钮右侧，2 列（说话人 | 台词），只读、可滚动。"""
        # 清理旧日志区
        if self._log_proxy is not None and self._log_proxy.scene():
            self._scene.removeItem(self._log_proxy)
        self._log_proxy = None
        self._log_edit = None

        w, h = self._size
        margin = 10
        btn_w = max(20, int(w * 0.15)) - 2 * margin  # 返回按钮宽（与 _build_back_button 一致）
        # 日志区：返回按钮右侧到面板右边缘，留边距
        log_x = margin + btn_w + margin
        log_w = w - log_x - margin
        log_y = margin
        log_h = h - 2 * margin

        edit = QTextEdit()
        edit.setReadOnly(True)
        edit.setFrameShape(QTextEdit.NoFrame)
        edit.setStyleSheet(
            "QTextEdit { background: transparent; color: #000000; font-family: 幼圆; font-size: 22px; }"
        )
        edit.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        edit.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        edit.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard)
        # 内容初始空白
        edit.setPlainText("")

        proxy = QGraphicsProxyWidget(self)
        proxy.setWidget(edit)
        proxy.setPos(log_x, log_y)
        proxy.resize(log_w, log_h)
        proxy.setZValue(63)  # 高于返回按钮(61/62)，但低于面板 z=60 的父级子项无需额外
        self._log_proxy = proxy
        self._log_edit = edit

    def set_entries(self, entries):
        """填入日志条目：[(说话人, 台词), ...]，2 列 HTML 表格。
        字号 16px，行间距 padding 6px，行间 1px 分隔线；文字/分隔线颜色按背景亮度适配。
        初始滚动到最底部（最后一条对话）。
        """
        if self._log_edit is None:
            return
        bg_sum = sum(self._bg_color[:3])
        dark = bg_sum > 382  # 浅色背景 -> 深色文字；深色背景 -> 浅色文字
        text_color = "#000000" if dark else "#f0f0f0"
        border_color = "#999999" if dark else "#555555"
        rows = []
        for speaker, words in entries:
            sp = _html.escape(speaker) if speaker else "&nbsp;"
            wd = _html.escape(words).replace("\n", "<br>")
            rows.append(
                f'<tr>'
                f'<td width="28%" style="border-bottom:1px solid {border_color}; '
                f'padding:18px 4px; font-weight:bold; vertical-align:top; text-align:center;">{sp}</td>'
                f'<td style="border-bottom:1px solid {border_color}; '
                f'padding:18px 4px; vertical-align:top;">{wd}</td>'
                f'</tr>'
            )
        table = (
            f'<table width="100%" cellspacing="0" cellpadding="0" '
            f'style="border-collapse:collapse; font-family:幼圆; font-size:22px; color:{text_color};">'
            + "".join(rows) + '</table>'
        )
        self._log_edit.setHtml(table)
        # 初始滚到最底部（最后一条对话）
        sb = self._log_edit.verticalScrollBar()
        sb.setValue(sb.maximum())

    def fade_in(self, duration=None):
        """渐显：透明度 0 -> 100。"""
        if duration is None:
            duration = self._fade_duration
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
        """渐隐：透明度 100 -> 0，动画结束后调用 on_finished（若有）。"""
        if duration is None:
            duration = self._fade_duration
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

    def remove_from_scene(self):
        """从场景移除全部内容：返回按钮、返回文字、日志区、面板自身。"""
        for it in (self._back_btn, self._back_label):
            if it is not None and it.scene():
                self._scene.removeItem(it)
        self._back_btn = None
        self._back_label = None
        if self._log_proxy is not None:
            if self._log_proxy.scene():
                self._scene.removeItem(self._log_proxy)
            self._log_proxy = None
            self._log_edit = None
        if self.scene():
            self._scene.removeItem(self)


class SaveSlotItem(QGraphicsPathItem):
    """存档槽位按钮：上 50% 显示缩略图（无存档=灰底+SAVE 斜体字），
    下 50% 两行（各 25%）：上行对话文字（不含说话人），下行日期时间 + 垃圾桶删除按钮。
    底色 = button_color（saves_color），hover 时按亮度切白/黑底。
    """

    def __init__(self, rect: QRectF, key: str, parent=None, button_color=None,
                 saves_text_color=None, show_del=True):
        path = QPainterPath()
        path.addRoundedRect(rect, 12, 12)
        super().__init__(path, parent)
        self._show_del = show_del
        self.key = key
        self._rect = rect
        self._button_color = list(button_color) if button_color else [185, 122, 87, 255]
        if len(self._button_color) == 3:
            self._button_color.append(255)
        # 槽位文字颜色（台词/日期/垃圾桶/SAVE/确认文案），取 saves_text_color
        self._saves_text_color = list(saves_text_color) if saves_text_color else [255, 255, 255]
        if len(self._saves_text_color) == 3:
            self._saves_text_color.append(255)
        self._save_data = None      # 存档 data list（10 元素）或 None
        self._language = "zh"
        self.is_hovered = False
        self.click_handler = None
        self.delete_handler = None
        self.confirm_handler = None  # 覆盖确认红色确认按钮回调
        self._del_rect = QRectF()   # 垃圾桶点击区域（局部坐标）
        self._confirming = False    # 删除确认模式（点垃圾桶后进入）
        self._cancel_rect = QRectF()  # 取消按钮区域（局部坐标，确认模式）
        self._confirm_rect = QRectF() # 确认按钮区域（局部坐标，确认模式）
        self._cancel_hover = False    # 取消按钮悬停
        self._confirm_hover = False   # 确认按钮悬停
        self._confirm_mode = "delete"  # 确认模式文案: "delete"=确认删除 / "overwrite"=确认覆盖
        self.setAcceptHoverEvents(True)
        self.setCursor(Qt.ArrowCursor)
        self.setBrush(QBrush(QColor(*self._button_color)))
        self.setPen(QPen(Qt.NoPen))
        self.setZValue(21)

    def set_save_data(self, data, language="zh"):
        """设置存档数据（None=空槽位）。data 为存档 pickle 列表。"""
        self._save_data = data
        self._language = language if language in ("zh", "en", "ja", "ru") else "zh"
        # 数据变化时退出确认模式（如删除后刷新为空槽）
        self._confirming = False
        self._cancel_hover = False
        self._confirm_hover = False
        self._confirm_mode = "delete"  # 重置为删除确认（覆盖确认仅当次生效）
        self.update()

    def set_click_handler(self, handler):
        """设置点击回调（与 SettingsButtonItem 接口一致）。"""
        self.click_handler = handler

    def _words_text(self):
        """取当前语言台词（data[7] 多语言 dict 或 None）。"""
        if not self._save_data:
            return ""
        words = self._save_data[7] if len(self._save_data) > 7 else None
        if isinstance(words, dict):
            if self._language in words:
                return str(words[self._language])
            if "zh" in words:
                return str(words["zh"])
            for v in words.values():
                return str(v)
        return str(words) if words else ""

    def _datetime_text(self):
        """日期时间：data[8]=yyyy-MM-dd, data[9]=HH-mm-ss -> 'yyyy-MM-dd HH:mm:ss'"""
        if not self._save_data:
            return ""
        d = str(self._save_data[8]) if len(self._save_data) > 8 else ""
        t = str(self._save_data[9]) if len(self._save_data) > 9 else ""
        t = t.replace("-", ":")
        return (d + " " + t).strip()

    def _mode_normal_color(self):
        return list(self._button_color[:3])

    def _mode_hover_color(self):
        """hover 叠加色：根据 button_color 亮度决定浅/深叠加层。
        浅色叠加 = 向白混合 35%；深色叠加 = 向黑混合 35%。
        """
        s = self._button_color[:3]
        if sum(s) < 383:
            # 浅色叠加层：向白混合
            return [c + int((255 - c) * 0.35) for c in s]
        else:
            # 深色叠加层：向黑混合
            return [int(c * 0.65) for c in s]

    def hoverEnterEvent(self, event):
        self.is_hovered = True
        if self._confirming:
            pos = event.pos()
            self._cancel_hover = self._cancel_rect.contains(pos)
            self._confirm_hover = self._confirm_rect.contains(pos)
        self.setBrush(QBrush(QColor(*self._mode_hover_color())))
        self.update()
        super().hoverEnterEvent(event)

    def hoverMoveEvent(self, event):
        """确认模式下按钮间移动时更新悬停状态。"""
        if self._confirming:
            pos = event.pos()
            self._cancel_hover = self._cancel_rect.contains(pos)
            self._confirm_hover = self._confirm_rect.contains(pos)
            self.update()
        super().hoverMoveEvent(event)

    def hoverLeaveEvent(self, event):
        self.is_hovered = False
        self._cancel_hover = False
        self._confirm_hover = False
        self.setBrush(QBrush(QColor(*self._mode_normal_color())))
        self.update()
        super().hoverLeaveEvent(event)

    def reset_hover(self):
        self.is_hovered = False
        self.setBrush(QBrush(QColor(*self._mode_normal_color())))
        self.update()

    def paint(self, painter, option, widget):
        # 底色
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setBrush(self.brush())
        painter.setPen(QPen(Qt.NoPen))
        painter.drawRoundedRect(self._rect, 12, 12)

        r = self._rect
        # 槽位文字颜色：统一用 saves_text_color（不随 hover 切换）
        st = self._saves_text_color
        text_color = QColor(st[0], st[1], st[2], st[3] if len(st) > 3 else 255)

        # 上 50%：缩略图区域（与按钮边缘内缩 2px）
        top_h = r.height() * 0.5
        inset = 4
        thumb_rect = QRectF(r.x() + inset, r.y() + inset,
                            r.width() - 2 * inset, top_h - 2 * inset)
        if self._save_data and self._save_data[2]:
            # 有缩略图：缩放填充（KeepAspectRatioByExpanding + 居中裁切）
            pm = QPixmap()
            ok = pm.loadFromData(self._save_data[2])
            if ok and not pm.isNull():
                pm2 = pm.scaled(int(thumb_rect.width()), int(thumb_rect.height()),
                                Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
                # 居中裁切
                dx = (pm2.width() - thumb_rect.width()) / 2
                dy = (pm2.height() - thumb_rect.height()) / 2
                clip_path = QPainterPath()
                clip_path.addRoundedRect(thumb_rect, 8, 8)
                painter.setClipPath(clip_path)
                painter.drawPixmap(QRectF(thumb_rect.x() - dx, thumb_rect.y() - dy,
                                          pm2.width(), pm2.height()), pm2, QRectF(0, 0, pm2.width(), pm2.height()))
                painter.setClipping(False)
            else:
                self._paint_empty_thumb(painter, thumb_rect, text_color)
        else:
            self._paint_empty_thumb(painter, thumb_rect, text_color)

        # 下 50% 分两行（各 25%），中间横线
        bottom_top = r.y() + top_h
        line_y = r.y() + top_h + r.height() * 0.25
        # 横线
        painter.setPen(QPen(QColor(0, 0, 0, 60), 1))
        painter.drawLine(int(thumb_rect.x() + 6), int(line_y),
                         int(thumb_rect.right() - 6), int(line_y))
        painter.setPen(QPen(Qt.NoPen))

        # 上行：台词（25% 区域，确认模式时显示确认文字）
        if self._confirming:
            self._paint_confirm(painter, r, thumb_rect, line_y, text_color)
        else:
            words_rect = QRectF(thumb_rect.x() + 8, bottom_top + 3,
                                thumb_rect.width() - 16, r.height() * 0.25 - 6)
            painter.setPen(text_color)
            f = QFont("閫忔槑")
            f.setPointSize(10)
            painter.setFont(f)
            words = self._words_text()
            if words:
                # 简单截断 + 省略号
                fm = painter.fontMetrics()
                elided = fm.elidedText(words, Qt.ElideRight, int(words_rect.width()))
                painter.drawText(words_rect, Qt.AlignVCenter | Qt.AlignLeft, elided)

            # 下行：日期时间 + 垃圾桶
            
            dt_rect = QRectF(thumb_rect.x() + 8, line_y + 3,
                             thumb_rect.width() - 16, r.height() * 0.25 - 6)
            dt = self._datetime_text()
            if dt:
                painter.drawText(dt_rect, Qt.AlignVCenter | Qt.AlignLeft, dt)

            # 垃圾桶（有存档才显示）：右下角
            if self._save_data and self._show_del:
                del_size = 24
                del_rect = QRectF(r.right() - del_size - 4, r.bottom() - del_size - 4,
                                  del_size, del_size)
                self._del_rect = del_rect
                painter.setPen(text_color)
                df = QFont("閫忔槑")
                df.setPointSize(12)
                painter.setFont(df)
                painter.drawText(del_rect, Qt.AlignCenter, "🗑")

    def _paint_confirm(self, painter, r, thumb_rect, line_y, text_color):
        """删除确认模式：上行居中显示确认文字，下行两个按钮（取消/确认）。"""
        # 上行：确认文字（左右居中）
        words_rect = QRectF(thumb_rect.x() + 8, r.y() + r.height() * 0.5 + 3,
                            thumb_rect.width() - 16, r.height() * 0.25 - 6)
        painter.setPen(text_color)  # 确认文案也用 saves_text_color
        f = QFont("閫忔槑")
        f.setPointSize(10)
        painter.setFont(f)
        # 确认文案（按语言 + 模式：删除/覆盖）
        if self._confirm_mode == "overwrite":
            if self._language == "zh":
                confirm_text = "确认覆盖？"
            elif self._language == "ja":
                confirm_text = "上書きしますか？"
            elif self._language == "en":
                confirm_text = "Overwrite this save?"
            else:
                confirm_text = "Overwrite this save?"
        elif self._confirm_mode == "load":
            if self._language == "zh":
                confirm_text = "确认读取？"
            elif self._language == "ja":
                confirm_text = "読み込みますか？"
            elif self._language == "en":
                confirm_text = "Load this save?"
            else:
                confirm_text = "Load this save?"
        else:
            if self._language == "zh":
                confirm_text = "确认删除？"
            elif self._language == "ja":
                confirm_text = "削除しますか？"
            elif self._language == "en":
                confirm_text = "Delete this save?"
            else:
                confirm_text = "Delete this save?"
        painter.drawText(words_rect, Qt.AlignVCenter | Qt.AlignCenter, confirm_text)

        # 下行：两个按钮（取消 / 确认），左右各占一半，中间留 8px
        row_top = line_y + 2
        row_h = r.height() * 0.25 - 4
        btn_gap = 8
        total_w = thumb_rect.width() - 16
        half = (total_w - btn_gap) / 2
        cancel_rect = QRectF(thumb_rect.x() + 8, row_top, half, row_h)
        confirm_rect = QRectF(cancel_rect.right() + btn_gap, row_top, half, row_h)
        self._cancel_rect = cancel_rect
        self._confirm_rect = confirm_rect

        # 取消按钮：叠加灰色，白字；悬停更深（灰色叠加增强）
        cancel_alpha = 140 if not self._cancel_hover else 200
        cancel_bg = QColor(128, 128, 128, cancel_alpha)
        painter.setBrush(QBrush(cancel_bg))
        painter.setPen(QPen(Qt.NoPen))
        painter.drawRoundedRect(cancel_rect, 6, 6)
        # 确认按钮：红色底，白字；悬停叠加灰（红色上叠半透明灰）
        painter.setBrush(QBrush(QColor(200, 40, 40, 255)))
        painter.setPen(QPen(Qt.NoPen))
        painter.drawRoundedRect(confirm_rect, 6, 6)
        if self._confirm_hover:
            painter.setBrush(QBrush(QColor(128, 128, 128, 140)))
            painter.drawRoundedRect(confirm_rect, 6, 6)

        # 按钮文字
        if self._language == "zh":
            cancel_text, confirm_text2 = "取消", "确认"
        elif self._language == "ja":
            cancel_text, confirm_text2 = "キャンセル", "確認"
        else:
            cancel_text, confirm_text2 = "Cancel", "OK"
        painter.setPen(QColor(255, 255, 255, 255))
        f2 = QFont("閫忔槑")
        f2.setPointSize(9)
        painter.setFont(f2)
        painter.drawText(cancel_rect, Qt.AlignCenter, cancel_text)
        painter.drawText(confirm_rect, Qt.AlignCenter, confirm_text2)

    def _paint_empty_thumb(self, painter, thumb_rect, text_color):
        """无存档：灰色背景 + 深一档斜体 SAVE"""
        # 灰色背景（比按钮底色深一点）
        clip_path = QPainterPath()
        clip_path.addRoundedRect(thumb_rect, 8, 8)
        painter.save()
        painter.setClipPath(clip_path)
        painter.setBrush(QBrush(QColor(128, 128, 128, 255)))
        painter.setPen(QPen(Qt.NoPen))
        painter.drawRect(thumb_rect)
        painter.restore()
        # SAVE 斜体（比灰色背景深一点）
        f = QFont("閫忔槑")
        f.setPointSize(16)
        f.setItalic(True)
        f.setBold(True)
        painter.setFont(f)
        st = self._saves_text_color
        painter.setPen(QColor(st[0], st[1], st[2], st[3] if len(st) > 3 else 255))
        painter.drawText(thumb_rect, Qt.AlignCenter, "SAVE")

    def mousePressEvent(self, event):
        if not self.isVisible():
            event.ignore()
            return
        if event.button() == Qt.LeftButton:
            # 确认模式：只响应取消/确认按钮
            if self._confirming:
                if self._cancel_rect.contains(event.pos()):
                    self._confirming = False
                    self._cancel_hover = False
                    self._confirm_hover = False
                    self._confirm_mode = "delete"
                    self.update()
                    event.accept()
                    return
                if self._confirm_rect.contains(event.pos()):
                    # 覆盖确认 -> confirm_handler（删旧存新）；删除确认 -> delete_handler
                    handler = self.confirm_handler if self._confirm_mode in ("overwrite", "load") else self.delete_handler
                    if handler:
                        handler()
                    event.accept()
                    return
                # 确认模式：点确认以外的任意地方等同点取消
                self._confirming = False
                self._cancel_hover = False
                self._confirm_hover = False
                self._confirm_mode = "delete"
                self.update()
                event.accept()
                return
            # 垃圾桶区域点击 -> 进入确认模式
            if self._save_data and self._show_del and self._del_rect.contains(event.pos()):
                self._confirming = True
                self.update()
                event.accept()
                return
            if self.click_handler:
                self.click_handler()
                event.accept()
                return
        super().mousePressEvent(event)


class SavePanel(QGraphicsPathItem):
    """保存面板（同窗口内覆盖层，与 SettingsPanel/BacklogPanel 同尺寸同形状）。

    尺寸/形状：与设置面板一致（margin_ratio 0.1 -> 0.8*窗口，圆角半径 24）。
    填充颜色：来自 JSON ui.bottom_menu.save.color（RGBA 列表），缺省白色半透明 [255,255,255,217]。
    ui_mode: "default" 使用预设 UI（当前实现）；"custom" 规划中暂回落预设。
    左侧返回按钮：与日志面板一致（◀ 换行 返回/Back），点击调用 on_back。
    后续步骤将加入存档槽位列表（saves_color/saves_text_color/text_color/button_color 待用）。
    """

    def __init__(self, scene, bg_color=None, language="zh", on_back=None, saves_color=None,
                 text_color=None, saves_text_color=None, button_color=None,
                 on_main_menu=None, parent=None, mode="save"):
        self._mode = mode if mode in ("save", "load") else "save"
        self._on_load_slot = None
        self._bg_color = list(bg_color) if bg_color else [255, 255, 255, 217]
        # 兼容 3 元素 RGB（无 alpha），补默认 alpha 217
        if len(self._bg_color) == 3:
            self._bg_color.append(217)
        self._size = [100, 100]
        self._corner_radius = 24
        self._margin_ratio = 0.1
        self._fade_duration = 500
        self._language = language if language in ("zh", "en", "ja", "ru") else "zh"
        self._on_back = on_back
        self._back_btn = None
        self._saves_color = list(saves_color) if saves_color else [185, 122, 87, 255]
        if len(self._saves_color) == 3:
            self._saves_color.append(255)
        # 面板静态文字颜色（左上角标题等），取 bottom_menu.save.text_color，缺省 [30,30,30]
        self._text_color = list(text_color) if text_color else [30, 30, 30]
        if len(self._text_color) == 3:
            self._text_color.append(255)
        # 存档格文字颜色，取 bottom_menu.save.saves_text_color，缺省 [255,255,255]
        self._saves_text_color = list(saves_text_color) if saves_text_color else [255, 255, 255]
        if len(self._saves_text_color) == 3:
            self._saves_text_color.append(255)
        self._save_btns = []     # 2行x4个存档槽位按钮（SaveSlotItem）
        self._save_labels = []   # 对应文字标签（保留为空）
        self._title_label = None  # 左上角“保存游戏”标题
        self._saves_data = []    # 存档数据列表（与槽位对应，None=空）    # 左侧返回按钮
        self._save_files = []
        self._on_refresh = None
        self._on_save_to_slot = None  # 空槽点击保存回调(slot_index)
        self._on_delete_slot = None   # 删除格子存档回调(slot_index)
        self._on_overwrite_slot = None  # 覆盖确认回调(slot_index)：删旧存新
        self._back_label = None  # 返回按钮文字
        # 底部工具栏按钮颜色，取 bottom_menu.save.button_color，缺省 [0,0,0,255]
        self._button_color = list(button_color) if button_color else [0, 0, 0, 255]
        if len(self._button_color) == 3:
            self._button_color.append(255)
        self._on_main_menu = on_main_menu  # 主菜单按钮回调
        self._page_index = 0                # 当前存档页（0 基）
        self._total_pages = 1               # 总页数（1 基），+ 按钮可扩展
        self._bar_btns = []   # 底部工具栏按钮（◀ ▶ + 主菜单 返回）
        self._bar_labels = []  # 工具栏按钮文字标签
        self._page_label = None  # 页数数字文字
        path = QPainterPath()
        path.addRoundedRect(QRectF(0, 0, self._size[0], self._size[1]),
                            self._corner_radius, self._corner_radius)
        super().__init__(path, parent)
        self.setBrush(QBrush(QColor(self._bg_color[0], self._bg_color[1],
                                    self._bg_color[2], self._bg_color[3])))
        self.setPen(QPen(Qt.NoPen))
        self.setZValue(20)  # 与设置面板同层（高于底部菜单 z=10）
        self._scene = scene
        self._anim = None

    def center_in_scene(self, scene_rect):
        """按距窗口边缘 margin_ratio（默认 10%）计算尺寸并居中（同设置面板）。"""
        w_avail = scene_rect.width()
        h_avail = scene_rect.height()
        w = max(10, int(w_avail * (1 - 2 * self._margin_ratio)))
        h = max(10, int(h_avail * (1 - 2 * self._margin_ratio)))
        self._size = [w, h]
        path = QPainterPath()
        path.addRoundedRect(QRectF(0, 0, w, h), self._corner_radius, self._corner_radius)
        self.setPath(path)
        x = scene_rect.left() + (w_avail - w) / 2
        y = scene_rect.top() + (h_avail - h) / 2
        self.setPos(x, y)
        self._build_title()
        self._build_save_buttons()
        self._build_bottom_bar()

    def set_saves_data(self, saves, files=None):
        """设置当前页存档数据列表（长度=槽位数，元素为存档 data list 或 None）。
        调用后刷新各槽位显示与页数标签。"""
        self._saves_data = list(saves) if saves else []
        self._save_files = list(files) if files else []
        for i, btn in enumerate(self._save_btns):
            data = self._saves_data[i] if i < len(self._saves_data) else None
            btn.set_save_data(data, self._language)
        self._update_page_label()

    def set_total_pages(self, n):
        """设置总页数（1 基）。至少 1 页；只增不减（+ 按钮扩展的页保留）。"""
        n = max(1, int(n))
        if n > self._total_pages:
            self._total_pages = n
        if self._page_index >= self._total_pages:
            self._page_index = self._total_pages - 1
        self._update_page_label()

    def _update_page_label(self):
        """页数标签显示 <当前页>/<总页>（1 基）。"""
        if self._page_label is not None:
            self._page_label.setPlainText(f"{self._page_index + 1}/{self._total_pages}")

    def set_refresh_callback(self, cb):
        self._on_refresh = cb

    def set_load_slot_callback(self, cb):
        """设置加载模式下有存档格子点击回调：参数为全局格子 index。"""
        self._on_load_slot = cb

    def set_save_to_slot_callback(self, cb):
        """空槽点击保存回调：cb(slot_index)"""
        self._on_save_to_slot = cb

    def set_delete_slot_callback(self, cb):
        """删除格子存档回调：cb(slot_index)"""
        self._on_delete_slot = cb

    def set_overwrite_slot_callback(self, cb):
        """覆盖确认回调：cb(slot_index)，由 main_window 实现删旧存新"""
        self._on_overwrite_slot = cb

    def _on_slot_clicked(self, idx):
        """点击槽位（idx=页内局部 0-7）：空槽 -> 保存到该格；有存档 -> 覆盖确认。
        回调使用全局 index = 当前页*8 + 局部。"""
        data = self._saves_data[idx] if idx < len(self._saves_data) else None
        global_idx = self._page_index * 8 + idx
        if self._mode == "load":
            # 加载模式：有存档 -> 确认读取；空格无操作
            if data:
                btn = self._save_btns[idx] if idx < len(self._save_btns) else None
                if btn:
                    btn._confirm_mode = "load"
                    btn._confirming = True
                    btn.update()
            return
            return
        if data:
            # 有存档：进入覆盖确认模式
            btn = self._save_btns[idx] if idx < len(self._save_btns) else None
            if btn:
                btn._confirm_mode = "overwrite"
                btn._confirming = True
                btn.update()
            return
        # 空槽：保存到该格
        if self._on_save_to_slot:
            self._on_save_to_slot(global_idx)

    def _on_slot_delete(self, idx):
        """点击垃圾桶（idx=页内局部）：删除对应格子存档文件（全局 index）。"""
        if self._on_delete_slot:
            self._on_delete_slot(self._page_index * 8 + idx)

    def _on_slot_confirm_overwrite(self, idx):
        """确认按钮点击（idx=页内局部）：save 模式 -> 删旧存新；load 模式 -> 读档。"""
        global_idx = self._page_index * 8 + idx
        if self._mode == "load":
            if self._on_load_slot:
                self._on_load_slot(global_idx)
            return
        if self._on_overwrite_slot:
            self._on_overwrite_slot(global_idx)

    def _build_title(self):
        """左上角“保存游戏”标题：位于面板左上角（左侧 15% 区域内顶部）。
        字体幼圆，颜色 = text_color（bottom_menu.save.text_color，缺省 [30,30,30]）。
        多语言：zh=保存游戏 / en=Save / ja=セーブ（尽量短）。
        """
        # 清理旧标题
        if self._title_label is not None and self._title_label.scene():
            self._scene.removeItem(self._title_label)
        self._title_label = None
        w, h = self._size
        # 标题位于面板左上角，边距加大、字号加大
        title_x = 24
        title_y = 16
        if self._mode == "load":
            text = "加载游戏"
            if self._language == "en":
                text = "Load"
            elif self._language == "ja":
                text = "ロード"
            elif self._language == "ru":
                text = "Load"
        else:
            text = "保存游戏"
            if self._language == "en":
                text = "Save"
            elif self._language == "ja":
                text = "セーブ"
            elif self._language == "ru":
                text = "Save"
        label = QGraphicsTextItem(text, self)
        label.setFont(QFont("幼圆", 28, QFont.Bold))
        label.setDefaultTextColor(QColor(self._text_color[0], self._text_color[1],
                                         self._text_color[2], self._text_color[3] if len(self._text_color) > 3 else 255))
        label.setPos(title_x, title_y)
        label.setZValue(22)
        self._title_label = label

    def _build_save_buttons(self):
        """构建 2 行 x 4 个存档槽位按钮：每行高度 = 面板高度 35%。
        行间隙 = 行内按钮间距 = 10px；两行垂直居中（上下留白对称）。
        按钮底色 = saves_color（默认 [185,122,87,255] 棕色系）。
        按钮无文字（槽位数据后续接入）。
        """
        # 清理旧按钮
        for it in self._save_btns + self._save_labels:
            if it is not None and it.scene():
                self._scene.removeItem(it)
        self._save_btns = []
        self._save_labels = []

        w, h = self._size
        gap = 10                                # 行间隙 = 按钮间距 = 10px
        btn_h = int(h * 0.35)                   # 每行高度 = 面板高度 35%
        rows = 2
        cols = 4
        # 垂直：两行居中于中间 70% 区域（顶部 15% 标题区 ~ 底部 15% 工具栏之间）
        avail_top = int(h * 0.15)
        avail_h = int(h * 0.70)
        top = avail_top + int((avail_h - 2 * btn_h - gap) / 2)
        # 水平：左右边缘固定留 20px，4 个按钮均分剩余宽度（浮点保证右缘精确 20px），按钮间距 gap
        margin_x = 20
        btn_w = (w - 2 * margin_x - (cols - 1) * gap) / cols

        s = self._saves_color
        bg_sum = s[0] + s[1] + s[2]
        color_mode = "dark" if bg_sum > 382 else "light"  # 深色按钮用白字

        for r in range(rows):
            for c in range(cols):
                idx = r * cols + c
                x = margin_x + c * (btn_w + gap)
                y = top + r * (btn_h + gap)
                rect = QRectF(x, y, btn_w, btn_h)
                btn = SaveSlotItem(rect, f"save_slot_{self._page_index}_{idx}", self,
                                   button_color=s,
                                   saves_text_color=self._saves_text_color,
                                   show_del=True)
                btn.set_click_handler(lambda idx=idx: self._on_slot_clicked(idx))
                btn.delete_handler = lambda idx=idx: self._on_slot_delete(idx)
                btn.confirm_handler = lambda idx=idx: self._on_slot_confirm_overwrite(idx)
                self._save_btns.append(btn)
                # 无文字标签

    def _build_bottom_bar(self):
        """底部 15% 工具栏：
        左侧（从左1开始）：◀ 左箭头、页数数字（text_color）、▶ 右箭头、+ 加号
        右侧（从右1开始）：主菜单、返回
        按钮底色/文字色/hover 均按 button_color 亮度规则（sum<383 亮色底深字，>=383 深色底浅字）。
        页数数字用 text_color。
        """
        # 清理旧内容
        for it in self._bar_btns + self._bar_labels:
            if it is not None and it.scene():
                self._scene.removeItem(it)
        if self._page_label is not None and self._page_label.scene():
            self._scene.removeItem(self._page_label)
        self._bar_btns = []
        self._bar_labels = []
        self._page_label = None

        w, h = self._size
        bar_y = int(h * 0.85)
        bar_h = h - bar_y
        margin = 40                 # 翻页三按钮右移
        btn_h = int(bar_h * 0.50)   # 按钮高度 = 条高 50%（更矮）
        btn_y = bar_y + int((bar_h - btn_h) / 2)
        gap_b = 8
        btn_w = 44                  # 方形按钮（箭头/加号）

        bc = self._button_color
        # 按钮文字（多语言，尽量短）
        if self._language == "zh":
            menu_text = "主菜单"
            back_text = "返回"
        elif self._language == "ja":
            menu_text = "メニュー"
            back_text = "戻る"
        else:  # en/ru
            menu_text = "Menu"
            back_text = "Back"

        def make_btn(x, key, text=None, handler=None, width=None):
            bw = width if width is not None else btn_w
            rect = QRectF(x, btn_y, bw, btn_h)
            b = SettingsButtonItem(rect, key, self, button_color=bc)
            if handler:
                b.set_click_handler(handler)
            self._bar_btns.append(b)
            if text is not None:
                lbl = QGraphicsTextItem(text, self)
                lbl.setFont(QFont("幼圆", 11, QFont.Bold))
                # 文字颜色由按钮亮度规则决定（与 _set_text_color 一致）
                s = sum(bc[:3])
                lbl.setDefaultTextColor(QColor(255, 255, 255, 255) if s < 383 else QColor(0, 0, 0, 255))
                br = lbl.boundingRect()
                lbl.setPos(x + (bw - br.width()) / 2, btn_y + (btn_h - br.height()) / 2)
                lbl.setZValue(11)
                lbl.setTextInteractionFlags(Qt.NoTextInteraction)
                lbl.setAcceptHoverEvents(False)
                lbl.setCursor(Qt.ArrowCursor)
                b._text_label = lbl
                b._set_text_color(True)  # 同步正常态文字色
                self._bar_labels.append(lbl)
            return b

        # 左侧：◀ [页数] ▶ +（从左往右）
        x = margin
        make_btn(x, "save_page_prev", "◀", handler=lambda: self._change_page(-1)); x += btn_w + gap_b
        # 页数数字（纯文字，text_color）
        tc = self._text_color
        page_lbl = QGraphicsTextItem(f"{self._page_index + 1}/{self._total_pages}", self)
        page_lbl.setFont(QFont("幼圆", 11, QFont.Bold))
        page_lbl.setDefaultTextColor(QColor(tc[0], tc[1], tc[2], tc[3] if len(tc) > 3 else 255))
        page_lbl.setPos(x + 4, btn_y + (btn_h - page_lbl.boundingRect().height()) / 2)
        page_lbl.setZValue(11)
        page_lbl.setTextInteractionFlags(Qt.NoTextInteraction)
        page_lbl.setAcceptHoverEvents(False)
        page_lbl.setCursor(Qt.ArrowCursor)
        self._page_label = page_lbl
        # 按页数文字实际宽度推进（"5/5" 比 "1/1" 宽），避免被右侧按钮遮住
        x += page_lbl.boundingRect().width() + 8 + gap_b
        make_btn(x, "save_page_next", "▶", handler=lambda: self._change_page(1)); x += btn_w + gap_b
        if self._mode != "load":
            make_btn(x, "save_page_add", "+", handler=self._add_page)

        # 右侧：主菜单（右1，最右）、返回（右2）
        # 先设字体再量文字宽，保证按钮宽度足够容纳文字
        def text_w(t):
            tl = QGraphicsTextItem(t)
            tl.setFont(QFont("幼圆", 11, QFont.Bold))
            return tl.boundingRect().width()
        mw = text_w(menu_text) + 28
        bw = text_w(back_text) + 28
        rx = w - margin - mw
        make_btn(rx, "save_main_menu", menu_text, handler=self._on_main_menu, width=mw)
        rx -= mw + gap_b
        make_btn(rx, "save_back", back_text, handler=self._on_back, width=bw)

    def _change_page(self, delta):
        """环形翻页：右翻 (cur+1)%total（空页按右翻回到第 1 页），
        左翻 (cur-1+total)%total（第 1 页按左翻到总页）。"""
        total = max(1, self._total_pages)
        if total <= 1:
            return
        new_idx = (self._page_index + delta) % total
        if new_idx == self._page_index:
            return
        self._page_index = new_idx
        self._update_page_label()
        print(f"存档页切换到 {self._page_index + 1}/{self._total_pages}")
        self._refresh_data()

    def _add_page(self):
        """+ 按钮：仅总页数 +1，当前页保持不变（新增空白页，需手动翻页前往）。"""
        self._total_pages += 1
        self._update_page_label()
        print(f"新增存档页，总页数 {self._total_pages}，当前仍在第 {self._page_index + 1} 页")

    def _refresh_data(self):
        """翻页/加页后通知 main_window 按当前页重新拉取存档数据。"""
        if self._on_refresh:
            self._on_refresh()

    def _build_back_button(self):
        """左侧返回按钮：从顶到底，距面板边缘 10px，宽 = 面板宽 15%（同日志面板）。
        文字：◀ 换行 返回(zh) / Back(en/ja/ru)。点击调用 on_back。
        """
        # 清理旧按钮/文字
        for it in (self._back_btn, self._back_label):
            if it is not None and it.scene():
                self._scene.removeItem(it)
        self._back_btn = None
        self._back_label = None

        w, h = self._size
        margin = 10
        btn_w = max(20, int(w * 0.15)) - 2 * margin  # 宽 15% 再留左右边距
        btn_h = h - 2 * margin                       # 从顶到底留上下边距
        rect = QRectF(margin, margin, btn_w, btn_h)

        # 按 save.color 亮度选配色：r+g+b>382 深色模式，否则浅色模式
        bg_sum = (self._bg_color[0] if len(self._bg_color) > 0 else 255) \
               + (self._bg_color[1] if len(self._bg_color) > 1 else 255) \
               + (self._bg_color[2] if len(self._bg_color) > 2 else 255)
        color_mode = "dark" if bg_sum > 382 else "light"
        btn = SettingsButtonItem(rect, "save_back", self, opacity=90, color_mode=color_mode)
        btn.set_click_handler(self._on_back if self._on_back else (lambda: None))
        self._back_btn = btn

        # 文字：两行（◀ 换行 返回/Back），幼圆字体，左右居中
        text = "◀\n" + ("返回" if self._language == "zh" else "Back")
        label = QGraphicsTextItem(text, self)
        label.setDefaultTextColor(QColor(255, 255, 255) if color_mode == "dark" else QColor(0, 0, 0))
        font = QFont("幼圆")
        font.setPointSize(20)
        font.setBold(True)
        label.setFont(font)
        label.setAcceptHoverEvents(False)
        label.setTextInteractionFlags(Qt.NoTextInteraction)
        label.setCursor(Qt.ArrowCursor)
        label.setTextWidth(rect.width())
        label.document().setDefaultTextOption(QTextOption(Qt.AlignCenter))
        br = label.boundingRect()
        label.setPos(rect.center().x() - rect.width() / 2,
                     rect.center().y() - br.height() / 2)
        self._back_label = label

        btn.setZValue(21)
        label.setZValue(22)
        btn._text_label = label  # 悬停变色：文字白/黑切换

    def fade_in(self, duration=None):
        """渐显：透明度 0 -> 100。"""
        if duration is None:
            duration = self._fade_duration
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
        """渐隐：透明度 100 -> 0，动画结束后调用 on_finished（若有）。"""
        if duration is None:
            duration = self._fade_duration
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

    def remove_from_scene(self):
        """从场景移除全部内容：返回按钮、返回文字、标题、工具栏、面板自身。"""
        for it in (self._title_label, self._back_btn, self._back_label,
                   self._page_label) + tuple(self._bar_btns) + tuple(self._bar_labels):
            if it is not None and it.scene():
                self._scene.removeItem(it)
        for it in self._save_btns + self._save_labels:
            if it is not None and it.scene():
                self._scene.removeItem(it)
        self._back_btn = None
        self._back_label = None
        self._save_btns = []
        self._save_labels = []
        if self.scene():
            self._scene.removeItem(self)


# ---------------------------------------------------------------------------
# 确认框（Continue/Q.Load 等操作前的确认 UI）
# ---------------------------------------------------------------------------
# 配置来源：menu.menu_pos.qload 第 3 项 dict：
#   ui_mode      "default"（预设 UI，当前实现）
#   color        确认框底色 RGBA
#   text_color   第一行文字（"确认？"）颜色 RGB
#   cancel_color 取消按钮底色 RGB
#   confirm_color 确认按钮底色 RGB
# 遮罩：整窗叠加 settings.transition_color、透明度 50%
# 预设 UI 语言仅支持 zh/en/ja（超出回落 en）
CONFIRM_TEXTS = {
    "question": {"zh": "确认？", "en": "Confirm?", "ja": "確認？"},
    "cancel": {"zh": "取消", "en": "Cancel", "ja": "キャンセル"},
    "confirm": {"zh": "确认", "en": "Confirm", "ja": "確認"},
}


class ConfirmDialog(QGraphicsPathItem):
    """快速加载前的确认框（场景覆盖层）。
    由一层全屏遮罩（transition_color、50% 透明度）+ 居中圆角确认框组成：
      - 第一行："确认？"（zh/en/ja，预设 UI 仅支持这三种语言）
      - 第二行：取消 / 确认 两个圆角按钮
    按钮底色 cancel_color/confirm_color；文字颜色与悬停叠加按按钮亮度规则：
      sum(rgb) < 383  -> 白字，悬停向白混合 35%
      sum(rgb) >= 383 -> 黑字，悬停向黑混合 35%
    """

    Z_MASK = 70      # 遮罩层（盖过主菜单按钮/面板）
    Z_BOX = 71       # 确认框本体

    def __init__(self, scene, language="zh", config=None, transition_color=(0, 0, 0),
                 on_cancel=None, on_confirm=None):
        # 确认框本体（先构造，再 setZValue）
        super().__init__()
        self._scene = scene
        # 预设 UI 语言：仅支持 zh/en/ja，超出回落 en
        self.language = language if language in UI_LANGS else "en"
        cfg = config or {}
        self._box_color = list(cfg.get("color", [255, 255, 255, 217]))
        self._text_color = list(cfg.get("text_color", [30, 30, 30]))
        self._cancel_color = list(cfg.get("cancel_color", [255, 255, 255]))
        self._confirm_color = list(cfg.get("confirm_color", [30, 30, 30]))
        self.on_cancel = on_cancel
        self.on_confirm = on_confirm

        # 遮罩：整窗 transition_color、50% 透明度
        tc = list(transition_color or [0, 0, 0])
        self._mask = QGraphicsRectItem(0, 0, 0, 0)
        self._mask.setBrush(QBrush(QColor(tc[0], tc[1], tc[2], 128)))
        self._mask.setPen(QPen(Qt.NoPen))
        self._mask.setZValue(self.Z_MASK)
        scene.addItem(self._mask)

        scene.addItem(self)
        self.setZValue(self.Z_BOX)

    def center_in_scene(self, scene_rect: QRectF):
        """按场景尺寸定位：遮罩铺满，确认框居中。"""
        w, h = scene_rect.width(), scene_rect.height()
        self._mask.setRect(scene_rect)
        # 确认框：宽 40% 窗口、高 30% 窗口（上限 480x240），圆角 24
        box_w = min(int(w * 0.4), 480)
        box_h = min(int(h * 0.3), 240)
        x = scene_rect.x() + (w - box_w) / 2
        y = scene_rect.y() + (h - box_h) / 2
        self._box_rect = QRectF(x, y, box_w, box_h)

        # 圆角路径（圆角 24，与面板一致）
        path = QPainterPath()
        path.addRoundedRect(self._box_rect, 24, 24)
        self.setPath(path)
        box_color = self._box_color
        if len(box_color) >= 4:
            self.setBrush(QBrush(QColor(box_color[0], box_color[1], box_color[2], box_color[3])))
        else:
            self.setBrush(QBrush(QColor(box_color[0], box_color[1], box_color[2], 217)))
        self.setPen(QPen(Qt.NoPen))

        # 第一行："确认？"（左右居中）
        q_text = CONFIRM_TEXTS["question"].get(self.language, CONFIRM_TEXTS["question"]["en"])
        self._question_label = QGraphicsTextItem(q_text, self)
        tc = self._text_color
        self._question_label.setDefaultTextColor(QColor(tc[0], tc[1], tc[2]))
        self._question_label.setFont(QFont("Microsoft YaHei", 20, QFont.Bold))
        self._question_label.setTextWidth(-1)
        qr = self._question_label.boundingRect()
        self._question_label.setPos(
            self._box_rect.center().x() - qr.width() / 2,
            self._box_rect.y() + box_h * 0.18)
        self._question_label.setZValue(self.Z_BOX + 1)

        # 第二行：取消 / 确认 两个圆角按钮（左右居中，间距 20）
        btn_w = min(int(box_w * 0.3), 160)
        btn_h = int(box_h * 0.32)
        gap = 20
        total = btn_w * 2 + gap
        btn_y = self._box_rect.y() + box_h * 0.58
        left_x = self._box_rect.center().x() - total / 2

        self._cancel_btn = self._make_button(
            QRectF(left_x, btn_y, btn_w, btn_h),
            CONFIRM_TEXTS["cancel"].get(self.language, CONFIRM_TEXTS["cancel"]["en"]),
            self._cancel_color, "cancel")
        self._confirm_btn = self._make_button(
            QRectF(left_x + btn_w + gap, btn_y, btn_w, btn_h),
            CONFIRM_TEXTS["confirm"].get(self.language, CONFIRM_TEXTS["confirm"]["en"]),
            self._confirm_color, "confirm")

    def _make_button(self, rect, text, rgb, key):
        """创建圆角按钮（QGraphicsPathItem + 文字），按亮度规则定文字色。"""
        path = QPainterPath()
        path.addRoundedRect(rect, 12, 12)
        btn = QGraphicsPathItem(path, self)
        btn.setBrush(QBrush(QColor(rgb[0], rgb[1], rgb[2])))
        btn.setPen(QPen(Qt.NoPen))
        btn.setZValue(self.Z_BOX + 1)
        btn.setAcceptHoverEvents(True)
        btn.setCursor(Qt.ArrowCursor)
        btn._rgb = list(rgb)
        btn._key = key

        label = QGraphicsTextItem(text, btn)
        label.setDefaultTextColor(
            QColor(255, 255, 255) if sum(rgb[:3]) < 383 else QColor(0, 0, 0))
        label.setFont(QFont("Microsoft YaHei", 16, QFont.Bold))
        label.setTextWidth(-1)
        lr = label.boundingRect()
        label.setPos(rect.center().x() - lr.width() / 2,
                     rect.center().y() - lr.height() / 2)
        label.setZValue(self.Z_BOX + 2)
        label.setAcceptHoverEvents(False)
        label.setTextInteractionFlags(Qt.NoTextInteraction)
        label.setCursor(Qt.ArrowCursor)
        btn._label = label
        btn.mousePressEvent = self._make_press(btn)
        btn.hoverEnterEvent = self._make_hover(btn, True)
        btn.hoverLeaveEvent = self._make_hover(btn, False)
        return btn

    def _make_press(self, btn):
        def _press(event):
            if event.button() == Qt.LeftButton:
                if btn._key == "cancel" and self.on_cancel:
                    self.on_cancel()
                elif btn._key == "confirm" and self.on_confirm:
                    self.on_confirm()
                event.accept()
        return _press

    def _make_hover(self, btn, enter):
        def _hover(event):
            rgb = btn._rgb
            if enter:
                # 悬停：向白/黑混合 35%
                if sum(rgb[:3]) < 383:
                    hover = [c + int((255 - c) * 0.35) for c in rgb[:3]]
                else:
                    hover = [int(c * 0.65) for c in rgb[:3]]
                btn.setBrush(QBrush(QColor(hover[0], hover[1], hover[2])))
            else:
                btn.setBrush(QBrush(QColor(rgb[0], rgb[1], rgb[2])))
        return _hover

    def fade_in(self, duration=200):
        """遮罩+确认框一起淡入。"""
        effect = QGraphicsOpacityEffect()
        effect.setOpacity(0.0)
        self.setGraphicsEffect(effect)
        self._anim = QPropertyAnimation(effect, b"opacity")
        self._anim.setDuration(duration)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.setEasingCurve(QEasingCurve.InOutQuad)
        self._anim.start()

    def remove_from_scene(self):
        """从场景移除遮罩与确认框。"""
        if self._mask.scene():
            self._scene.removeItem(self._mask)
        if self.scene():
            self._scene.removeItem(self)
