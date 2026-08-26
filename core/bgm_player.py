# -*- coding: utf-8 -*-
"""BGM 播放器：多路音频 + 音量淡入/淡出。主菜单与剧情共用。

对应剧情 JSON 的配置：
  - menu.bgm（主菜单）：{bgm: 路径, in: 入场效果, out: 停止效果}，固定用 id "menu"
  - 场景级 bgm（剧情）：[{id, in/out, delay}]，id 来自 story_and_position.bgm 定义表
in/out 效果："normal"（直接）| "gradient"（1 秒淡变）| ["gradient", 秒]
每路独立，可同时播放；循环播放；同 id 重复播放 = 重启覆盖。
"""
from PySide6.QtCore import QObject, QUrl, QVariantAnimation
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput


class BgmPlayer(QObject):
    """多路背景音乐播放器：每个 id 一路，可同时播放；循环；支持音量淡入/淡出。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._channels = {}  # {id: {"player": ..., "out": ..., "anim": ...}}

    def play(self, bgm_id, path, fade_in=None):
        """播放指定 id 的 bgm。同 id 重复调用 = 重启覆盖（先停旧的再播）。
        fade_in 为秒数时从 0 音量淡入，None 直接以 1.0 音量播放。"""
        self._hard_stop_channel(bgm_id)
        player = QMediaPlayer(self)
        out = QAudioOutput(self)
        out.setVolume(0.0 if fade_in else 1.0)
        player.setAudioOutput(out)
        player.setSource(QUrl.fromLocalFile(path))
        player.errorOccurred.connect(
            lambda e, s, _id=bgm_id: self._on_error(_id, s))
        player.mediaStatusChanged.connect(
            lambda st, _id=bgm_id: self._on_media_status(_id, st))
        player.play()
        self._channels[bgm_id] = {"player": player, "out": out, "anim": None, "path": path}
        if fade_in:
            self._animate_volume(bgm_id, 0.0, 1.0, fade_in)

    def stop(self, bgm_id=None, fade_out=None):
        """停止指定 id 的 bgm（None/"" = 全部停止）。
        fade_out 为秒数时先淡出（音量 1->0）再停止，None 直接停。
        指定 id 未在播 -> 空操作。"""
        if bgm_id in (None, ""):
            for cid in list(self._channels.keys()):
                self.stop(cid, fade_out)
            return
        if bgm_id not in self._channels:
            return  # 未在播：空操作
        if fade_out:
            ch = self._channels[bgm_id]
            cur = ch["out"].volume() if ch["out"] is not None else 1.0
            self._animate_volume(bgm_id, cur, 0.0, fade_out,
                                 on_finished=lambda: self._hard_stop_channel(bgm_id))
        else:
            self._hard_stop_channel(bgm_id)

    def playing_ids(self):
        """当前在播（含淡出中）的 id 列表。"""
        return list(self._channels.keys())

    def playing_path(self, bgm_id):
        """指定 id 当前在播的音频路径（未在播返回 None）。"""
        ch = self._channels.get(bgm_id)
        return ch.get("path") if ch is not None else None

    def is_active(self) -> bool:
        """是否还有任何播放器实例（播放中或淡出中）。"""
        return bool(self._channels)

    # ---------- 内部 ----------

    def _animate_volume(self, bgm_id, frm, to, seconds, on_finished=None):
        ch = self._channels.get(bgm_id)
        if ch is None:
            return
        anim = QVariantAnimation(self)
        anim.setDuration(max(1, int(seconds * 1000)))
        anim.setStartValue(float(frm))
        anim.setEndValue(float(to))
        anim.valueChanged.connect(lambda v, _id=bgm_id: self._apply_volume(_id, v))
        if on_finished:
            anim.finished.connect(on_finished)
        ch["anim"] = anim
        anim.start()

    def _apply_volume(self, bgm_id, v):
        ch = self._channels.get(bgm_id)
        if ch is not None and ch["out"] is not None:
            try:
                ch["out"].setVolume(float(v))
            except Exception:
                pass

    def _on_error(self, bgm_id, error_string):
        print(f"BGM 播放错误 [{bgm_id}]: {error_string}")

    def _on_media_status(self, bgm_id, status):
        """循环播放：播完一遍（EndOfMedia）回到开头继续播。"""
        if status == QMediaPlayer.MediaStatus.EndOfMedia:
            ch = self._channels.get(bgm_id)
            if ch is not None:
                try:
                    ch["player"].setPosition(0)
                    ch["player"].play()
                except Exception:
                    pass

    def _hard_stop_channel(self, bgm_id):
        ch = self._channels.pop(bgm_id, None)
        if ch is None:
            return
        anim = ch.get("anim")
        if anim is not None:
            try:
                anim.stop()
                anim.disconnect()
            except Exception:
                pass
        player = ch.get("player")
        if player is not None:
            try:
                player.stop()
                player.disconnect()
            except Exception:
                pass
            player.deleteLater()
        out = ch.get("out")
        if out is not None:
            try:
                out.deleteLater()
            except Exception:
                pass
