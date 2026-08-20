# -*- coding: utf-8 -*-
"""主菜单 BGM 播放器：单路音频 + 音量淡入/淡出。

对应剧情 JSON 的 menu.bgm 配置：
  - bgm: 音频文件路径（相对 story 目录）
  - in:  入场效果 "normal"（直接播放）| "gradient"（淡入）| ["gradient", 秒]
  - out: 停止效果 "normal"（直接停）| "gradient"（淡出）| ["gradient", 秒]
只写 "gradient" 时默认 1 秒完成淡入/淡出。
"""
from PySide6.QtCore import QObject, QUrl, QVariantAnimation
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput


class BgmPlayer(QObject):
    """主菜单背景音乐播放器（单路）。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._player = None
        self._out = None
        self._anim = None

    def play(self, path, fade_in=None):
        """播放 bgm。fade_in 为秒数时从 0 音量淡入，None 直接以 1.0 音量播放。"""
        self._hard_stop()
        player = QMediaPlayer(self)
        out = QAudioOutput(self)
        out.setVolume(0.0 if fade_in else 1.0)
        player.setAudioOutput(out)
        player.setSource(QUrl.fromLocalFile(path))
        player.errorOccurred.connect(self._on_error)
        player.mediaStatusChanged.connect(self._on_media_status)
        player.play()
        self._player, self._out = player, out
        if fade_in:
            self._animate_volume(0.0, 1.0, fade_in)

    def stop(self, fade_out=None):
        """停止 bgm。fade_out 为秒数时先淡出（音量 1->0）再停止，None 直接停。"""
        if self._player is None:
            return
        if fade_out:
            cur = self._out.volume() if self._out is not None else 1.0
            self._animate_volume(cur, 0.0, fade_out, on_finished=self._hard_stop)
        else:
            self._hard_stop()

    def is_active(self) -> bool:
        """是否还有播放器实例（播放中或淡出中）。"""
        return self._player is not None

    # ---------- 内部 ----------

    def _animate_volume(self, frm, to, seconds, on_finished=None):
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(max(1, int(seconds * 1000)))
        self._anim.setStartValue(float(frm))
        self._anim.setEndValue(float(to))
        self._anim.valueChanged.connect(lambda v: self._apply_volume(v))
        if on_finished:
            self._anim.finished.connect(on_finished)
        self._anim.start()

    def _apply_volume(self, v):
        if self._out is not None:
            try:
                self._out.setVolume(float(v))
            except Exception:
                pass

    def _on_error(self, error, error_string):
        print(f"主菜单 BGM 播放错误: {error_string}")

    def _on_media_status(self, status):
        """循环播放：播完一遍（EndOfMedia）回到开头继续播。"""
        if status == QMediaPlayer.MediaStatus.EndOfMedia:
            try:
                self._player.setPosition(0)
                self._player.play()
            except Exception:
                pass

    def _hard_stop(self):
        if self._anim is not None:
            try:
                self._anim.stop()
                self._anim.disconnect()
            except Exception:
                pass
            self._anim = None
        if self._player is not None:
            try:
                self._player.stop()
                self._player.disconnect()
            except Exception:
                pass
            self._player.deleteLater()
            self._player = None
        if self._out is not None:
            try:
                self._out.deleteLater()
            except Exception:
                pass
            self._out = None
