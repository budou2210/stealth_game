"""ベスト記録のリプレイ（遊んでいる間の記録と、難易度選択の画面からの再生）。

記録：ゲームを始めた時点の乱数の状態と、プレイ中（捕まって止まっている間も含む）の1コマごとの
「時間の長さ・押していたキー・押した瞬間のお助けアイテムのキー」を残す。ベストを更新したら保存する。
再生：同じ乱数の状態から始め、記録した時間の長さとキーで1コマずつ進める。
視点（Tab）・足音の範囲（F）・一時停止（P）は再生中も自由に使える（展開には影響しない）。
"""

import random

from panda3d.core import ClockObject

from ..difficulty import MENU_LEVELS
from ..replays import (
    HELD_KEYS,
    PRESS_KEYS,
    decode_inputs,
    encode_inputs,
    load_replay,
    replay_path,
    save_replay,
)

MAX_CATCH_UP = 0.25  # 再生が遅れたとき、1回の更新で追いつこうとする時間の上限（秒）
TIME_TOLERANCE = 0.05  # 再生のクリアタイムが記録とこれ以上ずれたら「合わなくなった」とみなす


class ReplayMixin:
    def setup_replay(self):
        self.recording = None  # 今のプレイの記録
        self.replay = None  # 再生中のリプレイ（再生していなければ None）
        self.replay_frame = 0  # 次に使う記録のコマ
        self.replay_inputs = None  # 今のコマで使う (押していたキー, 押した瞬間のキー)
        self.replay_pending = 0.0
        self.replay_ended = False
        self.replay_cache = {}  # {難易度のkey: リプレイ}（メニューで毎回ファイルを読まないため）

    # --- 記録 -----------------------------------------------------------
    def begin_recording(self, random_state):
        self.recording = {
            "difficulty": self.difficulty.key,
            "random_state": random_state,
            "dts": [],
            "codes": [],
        }

    def record_frame(self, dt, presses):
        """プレイ中の1コマを記録する（再生中は記録しない）。"""
        if self.replay is not None or self.recording is None:
            return
        held = {name for name in HELD_KEYS if self.is_down(name)}
        self.recording["dts"].append(dt)
        self.recording["codes"].append(encode_inputs(held, presses))

    def save_best_replay(self):
        """ベストを更新したとき、このプレイの記録をその難易度のリプレイとして保存する。"""
        if self.recording is None:
            return
        replay = dict(self.recording, time=self.elapsed)
        if save_replay(replay_path(self.difficulty.key), replay):
            self.replay_cache[self.difficulty.key] = replay

    # --- 再生 -----------------------------------------------------------
    def best_replay(self, key):
        if key not in self.replay_cache:
            self.replay_cache[key] = load_replay(replay_path(key))
        return self.replay_cache[key]

    def has_best_replay(self, cfg):
        """そのベストタイムのリプレイがあるか（リプレイの機能を入れる前のベストタイムには、リプレイがない）。"""
        replay = self.best_replay(cfg.key)
        best = self.best_times.get(cfg.key)
        return replay is not None and best is not None and abs(replay["time"] - best) < 1e-6

    def play_best_replay(self):
        """メニューの V：選んでいる難易度のベスト記録を再生する。"""
        if self.state != "menu":
            return
        cfg = MENU_LEVELS[self.menu_index]
        if not self.has_best_replay(cfg):
            self.play_sound("denied")
            return
        self.play_sound("confirm")
        self.replay = self.best_replay(cfg.key)
        self.start_replay()

    def start_replay(self):
        """リプレイを最初から再生する。"""
        self.replay_frame = 0
        self.replay_inputs = None
        self.replay_pending = 0.0
        self.replay_ended = False
        cfg = next(c for c in MENU_LEVELS if c.key == self.replay["difficulty"])
        random.setstate(self.replay["random_state"])
        self.start_game(cfg, random_state=self.replay["random_state"])

    def stop_replay(self):
        self.replay = None
        self.replay_inputs = None

    def replay_key_down(self, name):
        """再生中に記録から押すキーなら (True, 押しているか)。そうでなければ (False, None)。"""
        if self.replay is None or name not in HELD_KEYS:
            return False, None
        held = self.replay_inputs[0] if self.replay_inputs else ()
        return True, name in held

    def replay_presses(self, presses):
        """再生中は、お助けアイテムのキーを押した瞬間を記録のとおりにする。"""
        if self.replay is None:
            return presses
        recorded = self.replay_inputs[1] if self.replay_inputs else ()
        for name in PRESS_KEYS:
            presses[name] = name in recorded
        return presses

    def replay_tick(self, real_dt):
        """再生中の毎フレームの更新。プレイ中は記録した時間の長さで、実際の時間に合わせて進める。"""
        if self.state not in ("play", "caught"):
            self.replay_inputs = None
            self.step(real_dt)  # 一時停止中・クリアの後など（記録は使わない）
            return
        self.replay_pending = min(self.replay_pending + real_dt, MAX_CATCH_UP)
        while self.replay is not None and self.state in ("play", "caught"):
            if self.replay_frame >= len(self.replay["dts"]):
                self.end_replay_mismatch()  # 記録が終わったのに、まだクリアしていない
                return
            dt = self.replay["dts"][self.replay_frame]
            if self.replay_pending < dt:
                return
            self.replay_pending -= dt
            self.replay_inputs = decode_inputs(self.replay["codes"][self.replay_frame])
            before = self.state
            self.step(dt)
            if self.replay_used_frame(before):
                self.replay_frame += 1

    def replay_used_frame(self, before):
        """今の step で記録のコマを使ったか（P で一時停止したコマは、ゲームが進まないので使っていない）。"""
        return before in ("play", "caught") and self.last_step_played

    def end_replay_mismatch(self):
        if self.replay_ended:
            return
        self.replay_ended = True
        self.state = "win" if self.state == "win" else "lose"
        self.stop_bgm()
        self.message_text.setText(self.text["replay_mismatch"])

    def on_replay_win(self):
        """再生のクリア。ベストタイムには関係しない。"""
        self.state = "win"
        self.stop_bgm()
        self.play_sound("clear")
        if abs(self.elapsed - self.replay["time"]) > TIME_TOLERANCE:
            self.end_replay_mismatch()
            return
        self.replay_ended = True
        self.message_text.setText(self.text["replay_end"].format(time=self.elapsed))
