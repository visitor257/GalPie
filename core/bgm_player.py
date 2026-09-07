# -*- coding: utf-8 -*-
"""BGM 播放器：多路音频 + 音量淡入/淡出。主菜单与剧情共用。

对应剧情 JSON 的配置：
  - menu.bgm（主菜单）：{bgm: 路径, in: 入场效果, out: 停止效果}，固定用 id "menu"
  - 场景级 bgm（剧情）：[{id, in/out, delay}]，id 来自 story_and_position.bgm 定义表
in/out 效果："normal"（直接）| "gradient"（1 秒淡变）| ["gradient", 秒]
每路独立，可同时播放；循环播放；同 id 重复播放 = 重启覆盖。

音量模型（设置面板"背景音乐"音量条）：
  - 总音量 self._volume（0~1，全局）
  - 每路内部淡化系数 factor（0~1，仅由淡入/淡出动画驱动）
  - 实际输出音量 = factor * self._volume
因此播放中/淡变中调整总音量都实时生效，无需打断动画。
"""
from PySide6.QtCore import QObject, QUrl, QVariantAnimation
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput


class BgmPlayer(QObject):
    """多路背景音乐播放器：每个 id 一路，可同时播放；循环；支持音量淡入/淡出。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._channels = {}  # {id: {"player","out","anim","path","factor","_fadeout_cb"}}
        self._volume = 1.0   # 总音量（0.0~1.0）

    def set_volume(self, volume: float):
        """设置总音量并实时应用到当前所有在播/淡变中通道。
        淡入/淡出动画按淡化系数继续，输出 = factor * 新总音量。"""
        volume = max(0.0, min(1.0, float(volume)))
        self._volume = volume
        for ch in self._channels.values():
            out = ch.get("out")
            if out is not None:
                try:
                    out.setVolume(float(ch.get("factor", 1.0)) * self._volume)
                except Exception:
                    pass

    def play(self, bgm_id, path, fade_in=None):
        """播放指定 id 的 bgm。同 id 重复调用 = 重启覆盖（先停旧的再播）。
        fade_in 为秒数时淡化系数从 0 淡入到 1（音量 0->总音量），
        None 直接以总音量播放。"""
        self._hard_stop_channel(bgm_id)
        player = QMediaPlayer(self)
        out = QAudioOutput(self)
        factor = 0.0 if fade_in else 1.0
        out.setVolume(factor * self._volume)
        player.setAudioOutput(out)
        player.setSource(QUrl.fromLocalFile(path))
        player.errorOccurred.connect(
            lambda e, s, _id=bgm_id: self._on_error(_id, s))
        player.mediaStatusChanged.connect(
            lambda st, _id=bgm_id: self._on_media_status(_id, st))
        player.play()
        self._channels[bgm_id] = {"player": player, "out": out, "anim": None,
                                  "path": path, "factor": factor,
                                  "_fadeout_cb": None}
        if fade_in:
            self._animate_factor(bgm_id, 0.0, 1.0, fade_in)

    def stop(self, bgm_id=None, fade_out=None):
        """停止指定 id 的 bgm（None/"" = 全部停止）。
        fade_out 为秒数时先淡出（factor 当前值->0，音量->0）再停止，None 直接停。
        指定 id 未在播 -> 空操作。"""
        if bgm_id in (None, ""):
            for cid in list(self._channels.keys()):
                self.stop(cid, fade_out)
            return
        if bgm_id not in self._channels:
            return  # 未在播：空操作
        if fade_out:
            ch = self._channels[bgm_id]
            frm = float(ch.get("factor", 1.0))
            cb = lambda: self._hard_stop_channel(bgm_id)  # noqa: E731
            ch["_fadeout_cb"] = cb
            self._animate_factor(bgm_id, frm, 0.0, fade_out, on_finished=cb)
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

    def _animate_factor(self, bgm_id, frm, to, seconds, on_finished=None):
        """淡化系数动画：factor frm->to（0~1），逐帧 _apply_factor。"""
        ch = self._channels.get(bgm_id)
        if ch is None:
            return
        anim = QVariantAnimation(self)
        anim.setDuration(max(1, int(seconds * 1000)))
        anim.setStartValue(float(frm))
        anim.setEndValue(float(to))
        anim.valueChanged.connect(lambda v, _id=bgm_id: self._apply_factor(_id, v))
        if on_finished:
            anim.finished.connect(on_finished)
        old = ch.get("anim")
        if old is not None:
            try:
                old.stop()
                old.disconnect()
            except Exception:
                pass
        ch["anim"] = anim
        anim.start()

    def _apply_factor(self, bgm_id, factor):
        """动画帧回调：记录 factor 并输出 factor * 总音量。"""
        ch = self._channels.get(bgm_id)
        if ch is None:
            return
        ch["factor"] = float(factor)
        out = ch.get("out")
        if out is not None:
            try:
                out.setVolume(float(factor) * self._volume)
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
