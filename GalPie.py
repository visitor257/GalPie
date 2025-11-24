import os
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional, Any

from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                               QHBoxLayout, QLabel, QPushButton, QFileDialog,
                               QGraphicsView, QGraphicsScene, QGraphicsPixmapItem,
                               QTextEdit, QFrame, QGraphicsRectItem)
from PySide6.QtCore import Qt, QTimer, QPropertyAnimation, QEasingCurve, QRectF, QPoint
from PySide6.QtGui import QPixmap, QPainter, QColor, QFont, QPen, QBrush, QTextCursor
from PySide6.QtOpenGLWidgets import QOpenGLWidget


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


class GraphicsView(QGraphicsView):
    """支持GPU加速的图形视图"""
    def __init__(self, parent=None):
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

        self.scene = QGraphicsScene()
        self.setScene(self.scene)

        # 存储图形项
        self.background_item = None
        self.character_items = {}

    def set_background(self, pixmap: QPixmap):
        """设置背景图片"""
        if self.background_item:
            self.scene.removeItem(self.background_item)

        self.background_item = QGraphicsPixmapItem(pixmap)
        self.scene.addItem(self.background_item)
        self.scene.setSceneRect(self.background_item.boundingRect())
        self.fit_background()

    def fit_background(self):
        """调整背景适应视图大小"""
        if self.background_item and self.sceneRect().isValid():
            self.fitInView(self.sceneRect(), Qt.KeepAspectRatioByExpanding)

    def add_character(self, char_id: str, pixmap: QPixmap, pos: List[int]):
        """添加角色"""
        if char_id in self.character_items:
            self.remove_character(char_id)

        item = QGraphicsPixmapItem(pixmap)
        item.setPos(pos[0], pos[1])
        self.scene.addItem(item)
        self.character_items[char_id] = item

    def remove_character(self, char_id: str):
        """移除角色"""
        if char_id in self.character_items:
            self.scene.removeItem(self.character_items[char_id])
            del self.character_items[char_id]

    def clear_characters(self):
        """清除所有角色"""
        for char_id in list(self.character_items.keys()):
            self.remove_character(char_id)

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

        # 新增：播放状态控制
        self.is_text_finished = False  # 字幕是否播放完成
        self.is_audio_finished = False  # 音频是否播放完成
        self.audio_timer = QTimer()  # 模拟音频播放
        self.audio_timer.setSingleShot(True)
        self.audio_timer.timeout.connect(self.on_audio_finished)

        # 新增：自动播放开关
        self.auto_play = False  # 默认为开启自动播放
        self.is_waiting_for_next_page = False  # 标记是否在等待进入下一页

        self.setup_ui()
        self.load_story_file()

    def setup_ui(self):
        """设置用户界面"""
        self.setWindowTitle("Galgame Engine")
        self.setGeometry(100, 100, 1280, 720)

        # 中央控件
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        # 主布局
        layout = QVBoxLayout(central_widget)
        layout.setContentsMargins(0, 0, 0, 0)

        # 图形视图
        self.graphics_view = GraphicsView()
        layout.addWidget(self.graphics_view)

        # 对话框区域
        self.setup_dialog_area()

        # 确保窗口可以接收焦点和鼠标事件
        self.setFocusPolicy(Qt.StrongFocus)
        self.graphics_view.setFocusPolicy(Qt.NoFocus)  # 防止图形视图抢焦点

    def setup_dialog_area(self):
        """设置对话框区域"""
        # 创建对话框背景（半透明黑色矩形）
        dialog_bg = QGraphicsRectItem(0, 0, 1280, 220)
        dialog_bg.setBrush(QBrush(QColor(0, 0, 0, 180)))
        dialog_bg.setPen(QPen(Qt.NoPen))
        dialog_bg.setPos(0, 500)  # 对话框位置
        dialog_bg.setZValue(10)  # 确保在最上层
        self.graphics_view.scene.addItem(dialog_bg)

        # 名字显示区域背景
        name_bg = QGraphicsRectItem(0, 0, 200, 40)
        name_bg.setBrush(QBrush(QColor(0, 0, 0, 150)))
        name_bg.setPen(QPen(Qt.NoPen))
        name_bg.setPos(76, 520)  # 根据JSON中的位置调整
        name_bg.setZValue(11)
        self.graphics_view.scene.addItem(name_bg)

        # 名字显示标签
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
        self.name_label.setFixedSize(200, 40)

        # 文本显示区域
        self.text_display = TextDisplayWidget()
        self.text_display.setFixedSize(500, 100)  # 在这里设置固定大小

        # 创建代理控件添加到场景中
        name_widget_proxy = self.graphics_view.scene.addWidget(self.name_label)
        name_widget_proxy.setPos(76, 520)
        name_widget_proxy.setZValue(12)  # 确保在背景之上

        text_widget_proxy = self.graphics_view.scene.addWidget(self.text_display)
        text_widget_proxy.setPos(310, 520)
        text_widget_proxy.setZValue(12)  # 确保在背景之上

        # 确保文本控件不会拦截鼠标事件
        self.text_display.setAttribute(Qt.WA_TransparentForMouseEvents, True)

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
        window_size = settings.get("window_size", "1280x720")

        if window_size:
            width, height = map(int, window_size.split('x'))
            self.resize(width, height)

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
                    self.graphics_view.set_background(bg_pixmap)
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
                    self.setup_character(char_id, char_info, character_defs[char_id])
                else:
                    print(f"角色未定义: {char_id}")

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

    def setup_character(self, char_id: str, char_info: Dict, char_data: Dict):
        """设置角色 - 合并身体和面部"""
        form_name = char_info["form"]
        face_info = char_info["face"]

        # 处理面部信息（可能是字符串或数组）
        if isinstance(face_info, list):
            face_name = face_info[0]
        else:
            face_name = face_info

        pos = char_info["pos"]

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

            # 再绘制面部（假设面部和身体大小相同，位置对齐）
            painter.drawPixmap(0, 0, face_pixmap)

            painter.end()

            self.graphics_view.add_character(char_id, combined_pixmap, pos)
        elif form_pixmap:
            # 只有身体，没有面部
            self.graphics_view.add_character(char_id, form_pixmap, pos)
        elif face_pixmap:
            # 只有面部，没有身体
            self.graphics_view.add_character(char_id, face_pixmap, pos)
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