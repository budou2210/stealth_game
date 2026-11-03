"""BGMと効果音（素材：魔王魂）。

音のファイルは assets/sounds/ に置く。見つからないファイルは鳴らさないだけで、ゲームは動く。
"""

from pathlib import Path

from panda3d.core import Filename

from ..constants import CLOAK_WARN_TIME, EXCLAIM_TIME
from ..guard import Guard

SOUND_DIR = Path(__file__).resolve().parents[1] / "assets" / "sounds"

# 音量は、ファイルごとの音の大きさ（音のある部分の平均）を測って揃えてある。
# BGMは平均 -19dB くらい、効果音は -20dB くらい（操作音は少し小さく、ジングルは少し大きく）になるようにした。
# 足音・お助けアイテムの出現は元の音が小さいので、音量を最大にしてもほかより小さい。

# BGM（ずっと繰り返す）: 名前 → (ファイル, 音量)。魔王魂のループ用の版を使う
# （通常版は最後に2〜3秒の無音があり、曲によっては終わりで小さくなっていくので、繰り返すと途切れる）
BGM_FILES = {
    "title": ("maou_loop_bgm_cyber19.ogg", 0.44),  # タイトル・難易度選択
    "sneak": ("maou_loop_bgm_cyber08.ogg", 0.34),  # 潜入中
    "chase": ("maou_loop_bgm_neorock80.ogg", 0.43),  # 追跡中・全アイテム回収後の狩り
}
# BGMはファイルを全部メモリに読み込んでから流す（少しずつ読み込む流し方だと、曲の終わりで頭に戻ったあと
# 最初の0.7秒ほどをくり返してしまい、ループしなかった）。3曲で約55MB（展開後の大きさ）
AUDIO_PRELOAD_THRESHOLD = 100_000_000  # 展開後の大きさがこれ以下の音は、全部読み込んでから流す（バイト）
RESUME_BGM = ("sneak",)  # 追跡の曲から戻ったとき、続きから流す曲（それ以外は頭から）
CHASE_BGM_HOLD = 3.0  # 追跡が終わってから、この秒数は追跡の曲を流し続ける（すぐ切り替わらないように）

# 効果音: 名前 → (ファイル, 音量)
SOUND_FILES = {
    "clear": ("maou_game_jingle02.ogg", 0.45),  # ジングル：クリア
    "lose": ("maou_se_jingle13.ogg", 0.4),  # ジングル：ゲームオーバー
    "new_record": ("maou_game_jingle09.ogg", 0.45),  # ジングル：新記録（クリアの後に続けて鳴らす）
    "footstep": ("maou_se_sound_footstep02.ogg", 1.0),  # 走る足音（1歩0.36秒。走っている間くり返す）
    "spotted": ("maou_se_sound_whistle01.ogg", 0.6),  # 警備員の「！」
    "item": ("maou_se_system49.ogg", 0.7),  # アイテムを拾う（8個目も同じ）
    "exit_open": ("maou_se_onepoint02.ogg", 1.0),  # 出口が開く
    "door": ("maou_se_sound_door02.ogg", 0.7),  # 安全地帯の扉が閉まる
    "caught": ("maou_se_onepoint06.ogg", 0.6),  # 捕まる
    "helper_appeared": ("maou_se_onepoint08.ogg", 1.0),  # お助けアイテムがマップに現れた
    "helper_pickup": ("maou_se_onepoint26.ogg", 0.5),  # お助けアイテムを拾う
    "cloak_warning": ("maou_se_sound_noise01.ogg", 0.5),  # 透明化の残り2秒（4.1秒の音。だんだん大きくする）
    "flash": ("maou_se_magic_thunder01.ogg", 0.6),  # スタンを使う
    "decoy_place": ("maou_se_sound_switch01.ogg", 1.0),  # 音の罠を置く
    "decoy_fire": ("maou_se_battle_explosion03.ogg", 0.9),  # 音の罠が鳴る
    "denied": ("maou_se_onepoint14.ogg", 0.5),  # お助けアイテムを使えなかった
    "cursor": ("maou_se_system34.ogg", 0.8),  # メニューのカーソル移動
    "confirm": ("maou_se_system13.ogg", 0.5),  # 難易度の決定
}
LOOP_SOUNDS = ("footstep", "cloak_warning")
JINGLES = ("clear", "lose", "new_record")
# クリアのジングルは6.5秒あるが、最後の2秒ほどは無音（と消えていく余韻）なので、
# 音がほぼ消えた4.0秒の時点で新記録のジングルを始める
NEW_RECORD_DELAY = 4.0
# 捕まる音（ガーン）は2.8秒。大きいのは最初の1.5秒なので、それが過ぎてからゲームオーバーのジングルを鳴らす
# （新記録・ゲームオーバーの文字も、ジングルと同時に出す）
LOSE_JINGLE_DELAY = 1.5
CLOAK_WARNING_START_VOLUME = 0.2  # 透明化の残り2秒の音は、この割合から元の音量まで大きくする
JINGLE_TASK = "jingle"


class AudioMixin:
    """BGMの切り替えと効果音。"""

    def setup_audio(self):
        self.bgm = {name: self.load_audio(file_name, music=True) for name, (file_name, _) in BGM_FILES.items()}
        self.sounds = {}
        self.sound_volumes = {}
        for name, (file_name, volume) in SOUND_FILES.items():
            self.sounds[name] = self.load_audio(file_name)
            self.sound_volumes[name] = volume
        for name in LOOP_SOUNDS:
            if self.sounds[name] is not None:
                self.sounds[name].setLoop(True)
        for name, sound in self.bgm.items():
            if sound is not None:
                sound.setLoop(True)
                sound.setVolume(BGM_FILES[name][1])
        files = [f for f, _ in [*BGM_FILES.values(), *SOUND_FILES.values()]]
        missing = [f for f in files if not (SOUND_DIR / f).exists()]
        if missing:
            print(f"音のファイルが {len(missing)} 個見つからないので、その音は鳴らしません（置き場所: {SOUND_DIR}）")
        self.bgm_name = None  # 今流している（一時停止中は止めている）曲
        self.bgm_playing = False
        self.bgm_positions = {}  # 曲を止めたときの再生位置（続きから流す曲用）
        self.chase_bgm_timer = 0.0
        self.loops_playing = set()

    def load_audio(self, file_name, music=False):
        path = SOUND_DIR / file_name
        if not path.exists():
            return None
        panda_path = Filename.fromOsSpecific(str(path)).getFullpath()
        try:
            return self.loader.loadMusic(panda_path) if music else self.loader.loadSfx(panda_path)
        except Exception as error:  # noqa: BLE001
            print(f"音のファイルを読み込めませんでした: {file_name}: {error}")
            return None

    # --- 効果音 ---------------------------------------------------------
    def play_sound(self, name, volume_rate=1.0):
        sound = self.sounds.get(name)
        if sound is None:
            return
        sound.setVolume(self.sound_volumes[name] * volume_rate)
        sound.play()

    def stop_sound(self, name):
        sound = self.sounds.get(name)
        if sound is not None:
            sound.stop()

    def set_loop(self, name, on, volume_rate=1.0):
        """くり返し鳴らす音を、onの間だけ鳴らす。"""
        sound = self.sounds.get(name)
        if sound is None:
            return
        if on:
            sound.setVolume(self.sound_volumes[name] * volume_rate)
            if name not in self.loops_playing:
                sound.play()
                self.loops_playing.add(name)
        elif name in self.loops_playing:
            sound.stop()
            self.loops_playing.discard(name)

    def run_later(self, delay, action):
        """delay秒後にactionを呼ぶ（ジングルとそれに合わせた画面の切り替え用。やり直すと取り消す）。"""
        self.taskMgr.doMethodLater(delay, lambda task: action(), JINGLE_TASK)

    def stop_jingles(self):
        """ジングル（と、これから鳴らす予定のジングル）を止める。やり直し・難易度選択に戻るとき用。"""
        self.taskMgr.remove(JINGLE_TASK)
        for name in JINGLES:
            self.stop_sound(name)

    # --- BGM ------------------------------------------------------------
    def chase_music_wanted(self):
        """追跡の曲を流す場面か（誰かが追跡中、または全アイテム回収後の狩り）。"""
        if self.is_hunting_phase():
            return True
        return any(g.state == Guard.CHASE and not g.is_stunned() for g in self.guards)

    def wanted_bgm(self):
        if self.state == "menu":
            return "title"
        if self.state in ("win", "lose", "caught"):  # 捕まったら、流れている曲にかかわらず一旦止める
            return None
        return "chase" if self.chase_bgm_timer > 0 else "sneak"

    def stop_bgm(self):
        """今の曲を止める（再生位置は覚えておく）。"""
        sound = self.bgm.get(self.bgm_name)
        if sound is not None and self.bgm_playing:
            self.bgm_positions[self.bgm_name] = sound.getTime()
            sound.stop()
        self.bgm_playing = False

    def update_bgm(self, dt):
        if self.state == "caught":
            self.chase_bgm_timer = 0.0  # スタート部屋に戻ったら、潜入の曲（の続き）から
        elif self.state == "play":
            if self.chase_music_wanted():
                self.chase_bgm_timer = CHASE_BGM_HOLD
            else:
                self.chase_bgm_timer = max(0.0, self.chase_bgm_timer - dt)
        name = self.wanted_bgm()
        if name != self.bgm_name:
            self.stop_bgm()
            self.bgm_name = name
        if self.state == "paused":
            self.stop_bgm()
            return
        sound = self.bgm.get(name)
        if sound is None or self.bgm_playing:
            return
        sound.setTime(self.bgm_positions.get(name, 0.0) if name in RESUME_BGM else 0.0)
        sound.play()
        self.bgm_playing = True

    def reset_audio(self):
        """新しいゲーム（やり直し・難易度選択）の始まり。ジングルを止め、潜入の曲は頭から流す。"""
        self.stop_jingles()
        self.chase_bgm_timer = 0.0
        self.bgm_positions = {}

    # --- 毎フレーム -----------------------------------------------------
    def update_audio(self, dt):
        self.update_bgm(dt)
        playing = self.state == "play"
        self.set_loop("footstep", playing and self.player.is_noisy())
        warning = playing and 0 < self.cloak_timer <= CLOAK_WARN_TIME
        progress = 1.0 - self.cloak_timer / CLOAK_WARN_TIME  # 残り2秒で0、切れる瞬間に1
        rate = CLOAK_WARNING_START_VOLUME + (1.0 - CLOAK_WARNING_START_VOLUME) * progress
        self.set_loop("cloak_warning", warning, volume_rate=rate)

    def play_event_sounds(self):
        """このフレームで「！」を出した警備員がいれば笛を鳴らす（何人いても1回）。"""
        if any(g.exclaim_timer >= EXCLAIM_TIME for g in self.guards):
            self.play_sound("spotted")
