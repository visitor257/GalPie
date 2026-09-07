# -*- coding: utf-8 -*-
"""顺序 + 并行音频播放器。

对应剧情 JSON 的 audio.play_in_order 二维列表语义：
  - 内层列表：同时播放（并行），如 [["1.wav","2.wav"]] -> 1、2 一起播
  - 外层列表：顺序播放（前一组全部播完后播下一组），
    如 [["1.wav"],["2.wav","3.wav"]] -> 播完 1 再同时播 2、3
全部组播完后触发 on_all_finished 回调。
"""
from PySide6.QtCore import QObject, QUrl
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput


class AudioPlayer(QObject):
    """多路音频播放器：groups = [[绝对路径, ...], ...]。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._players = []        # 当前组的所有 player
        self._outs = []           # 与 _players 对应的 QAudioOutput（音量实时调整用）
        self._groups = []         # 剩余组队列
        self._done_count = 0      # 当前组剩余未播完的路数
        self._on_all_finished = None
        self._stopping = False
        self._volume = 1.0        # 总音量（0.0~1.0，设置面板"语音"音量条）

    def set_volume(self, volume: float):
        """设置总音量并应用到当前所有在播输出（实时生效）。"""
        self._volume = max(0.0, min(1.0, float(volume)))
        for out in self._outs:
            try:
                out.setVolume(self._volume)
            except Exception:
                pass

    def play(self, groups, on_all_finished=None):
        """开始播放。groups 为空时立即触发完成回调。"""
        self.stop()
        self._on_all_finished = on_all_finished
        self._groups = [g for g in groups if g]
        self._stopping = False
        if not self._groups:
            self._all_finished()
            return
        self._play_next_group()

    def stop(self):
        """停止并清理所有播放（不触发完成回调）。"""
        self._stopping = True
        self._groups = []
        self._on_all_finished = None
        self._clear_players()

    def is_playing(self) -> bool:
        """是否还有音频在播放（含排队中的组）。"""
        return bool(self._players) or bool(self._groups)

    # ---------- 内部 ----------

    def _play_next_group(self):
        self._clear_players()
        if not self._groups:
            self._all_finished()
            return
        group = self._groups.pop(0)
        self._done_count = len(group)
        for path in group:
            player = QMediaPlayer(self)
            out = QAudioOutput(self)
            out.setVolume(self._volume)
            player.setAudioOutput(out)
            player.setSource(QUrl.fromLocalFile(path))
            player.mediaStatusChanged.connect(self._on_status)
            player.errorOccurred.connect(self._on_error)
            player.play()
            self._players.append(player)
            self._outs.append(out)

    def _on_status(self, status):
        if self._stopping:
            return
        if status in (QMediaPlayer.MediaStatus.EndOfMedia,
                      QMediaPlayer.MediaStatus.InvalidMedia,
                      QMediaPlayer.MediaStatus.NoMedia):
            self._one_done()

    def _on_error(self, error, error_string):
        if self._stopping:
            return
        print(f"音频播放错误: {error_string}")
        self._one_done()

    def _one_done(self):
        self._done_count -= 1
        if self._done_count <= 0:
            self._play_next_group()

    def _clear_players(self):
        for p in self._players:
            try:
                p.disconnect()
            except Exception:
                pass
            try:
                p.stop()
            except Exception:
                pass
            p.deleteLater()
        self._players = []
        for out in self._outs:
            try:
                out.deleteLater()
            except Exception:
                pass
        self._outs = []

    def _all_finished(self):
        cb = self._on_all_finished
        self._on_all_finished = None
        if cb:
            cb()
