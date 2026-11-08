"""画面上の文字・警戒度メーター。"""

import os

from direct.gui.DirectGui import DirectWaitBar
from direct.gui.OnscreenText import OnscreenText
from panda3d.core import CardMaker, Filename, TextNode, TransparencyAttrib

from ..constants import HELPER_MAX_HELD
from ..texts import TEXTS
from ..theme import (
    CONTROLS_MARGIN,
    CONTROLS_SCALE,
    FONT_CANDIDATES,
    MENU_TEXT_BG,
    PAUSE_DIM_COLOR,
)


def find_font_path():
    for path in FONT_CANDIDATES:
        if os.path.exists(path):
            return path
    return None


class HudMixin:
    """HUD（文字・メーター）の作成と更新。"""

    def setup_hud(self):
        font_path = find_font_path()
        self.font = None
        self.text = TEXTS["en"]
        if font_path is not None:
            self.font = self.load_japanese_font(font_path)
            if self.font is not None:
                self.text = TEXTS["ja"]
        self.status_text = OnscreenText(
            text="", parent=self.a2dTopLeft, pos=(0.05, -0.09), scale=0.06,
            fg=(1, 1, 1, 1), shadow=(0, 0, 0, 1), align=TextNode.ALeft,
            mayChange=True, font=self.font,
        )
        self.hint_text = OnscreenText(
            text="", parent=self.a2dTopLeft, pos=(0.05, -0.17), scale=0.045,
            fg=(1, 0.9, 0.5, 1), shadow=(0, 0, 0, 1), align=TextNode.ALeft,
            mayChange=True, font=self.font,
        )
        self.controls_text = OnscreenText(
            text="", parent=self.a2dBottomLeft, pos=(CONTROLS_MARGIN, 0.04),
            scale=CONTROLS_SCALE, fg=(0.8, 0.8, 0.8, 1), shadow=(0, 0, 0, 1),
            align=TextNode.ALeft, mayChange=True, font=self.font,
        )
        self.controls_layout = None  # 操作説明を最後に並べたときの (文字, 画面の縦横比)
        self.alert_label = OnscreenText(
            text=self.text["alert"], parent=self.a2dBottomCenter, pos=(-0.78, 0.115),
            scale=0.05, fg=(1, 1, 1, 1), shadow=(0, 0, 0, 1),
            align=TextNode.ARight, font=self.font,
        )
        self.alert_bar = DirectWaitBar(
            parent=self.a2dBottomCenter, pos=(0, 0, 0.13), scale=0.7,
            range=1.0, value=0.0, barColor=(0.3, 0.9, 0.3, 1),
        )
        # 一時停止中に画面全体を暗くする板（文字より奥に置く）
        card = CardMaker("pause_dim")
        card.setFrame(-4, 4, -1, 1)
        self.pause_dim = self.aspect2d.attachNewNode(card.generate(), -10)
        self.pause_dim.setColor(*PAUSE_DIM_COLOR)
        self.pause_dim.setTransparency(TransparencyAttrib.MAlpha)
        self.pause_dim.hide()
        self.message_text = OnscreenText(
            text="", pos=(0, 0.1), scale=0.12, fg=(1, 1, 1, 1),
            shadow=(0, 0, 0, 1), mayChange=True, font=self.font,
        )
        self.menu_title = OnscreenText(
            text=self.text["title"], pos=(0, 0.72), scale=0.14, fg=(1, 1, 1, 1),
            shadow=(0, 0, 0, 1), bg=MENU_TEXT_BG, font=self.font,
        )
        # 素材のクレジット（魔王魂の利用規約で表記が必要）。難易度選択の画面の右下に出す
        self.credit_text = OnscreenText(
            text=self.text["credit"], parent=self.a2dBottomRight, pos=(-0.05, 0.1),
            scale=0.04, fg=(0.8, 0.8, 0.8, 1), shadow=(0, 0, 0, 1),
            align=TextNode.ARight, font=self.font,
        )
        self.menu_text = OnscreenText(
            text="", pos=(0, 0.5), scale=0.038, fg=(1, 1, 1, 1),  # 難易度6つとタイムアタック（説明つき）が操作説明に重ならない大きさ
            shadow=(0, 0, 0, 1), bg=MENU_TEXT_BG, mayChange=True, font=self.font,
        )

    def set_play_hud_visible(self, visible):
        """プレイ中だけの表示（状態・ヒント・警戒度）。メニューでは隠して、難易度の一覧と重ならないようにする。"""
        meter = not self.difficulty.time_attack  # タイムアタックは鬼がいないので警戒度メーターを出さない
        for node in (self.status_text, self.hint_text, self.alert_label, self.alert_bar):
            if visible and (meter or node not in (self.alert_label, self.alert_bar)):
                node.show()
            else:
                node.hide()

    def load_japanese_font(self, font_path):
        """フォントを読み込む。失敗したらNone（英語表示に切り替わる）。"""
        panda_path = Filename.fromOsSpecific(font_path).getFullpath()
        try:
            return self.loader.loadFont(panda_path)
        except Exception as error:  # noqa: BLE001
            print(f"フォントを読み込めなかったので英語表示にします: {error}")
            return None

    def update_hud(self):
        self.status_text.setText(
            self.text["status"].format(
                level=self.level_name(self.difficulty),
                items=len(self.items_collected),
                total=len(self.item_cells),
                time=self.elapsed,
                lives=self.lives_status(),
                helpers=self.helper_status() + self.ghost_status(),
            )
        )
        self.hint_text.setText(self.hint_line())
        self.update_controls_text()
        if self.state == "paused":
            self.pause_dim.show()
        else:
            self.pause_dim.hide()
        top = max((guard.alert for guard in self.guards), default=0.0)
        self.alert_bar["value"] = top
        self.alert_bar["barColor"] = (min(1.0, 0.3 + top), max(0.1, 0.9 - top), 0.2, 1)

    def controls_line(self):
        """操作説明。プレイ中はその難易度で使えるお助けアイテムだけ、メニューでは全種類を載せる。"""
        if self.replay is not None:
            return self.text["replay_controls"]
        if self.state != "menu" and self.difficulty.time_attack:
            return "  ".join([self.text["time_attack_controls_move"], self.text["time_attack_controls_system"]])
        kinds = list(HELPER_MAX_HELD) if self.state == "menu" else self.helper_kinds()
        parts = [self.text["controls_move"]]
        parts += [self.text[f"{kind}_controls"] for kind in kinds]
        parts.append(self.text["controls_system"])
        return "  ".join(parts)

    def update_controls_text(self):
        """操作説明を書き換え、画面の幅に収まる大きさにする。

        文字かウィンドウの縦横比が変わったときだけ行う（毎フレームの文字の作り直しを避ける）。
        """
        line = self.controls_line()
        aspect = self.getAspectRatio()
        if (line, aspect) == self.controls_layout:
            return
        self.controls_layout = (line, aspect)
        self.controls_text.setText(line)
        available = 2 * aspect - 2 * CONTROLS_MARGIN  # 画面の横幅から左右の余白を引いた長さ
        width = self.controls_text.textNode.getWidth()  # 大きさ1のときの文字列の長さ
        self.controls_text.setScale(min(CONTROLS_SCALE, available / width) if width > 0 else CONTROLS_SCALE)

    def helper_status(self):
        parts = [
            self.text[f"{kind}_status"].format(count=self.held[kind])
            for kind in self.helper_kinds()
        ]
        if self.cloak_timer > 0:
            parts.append(self.text["cloak_active"].format(time=self.cloak_timer))
        return "".join(parts)

    def lives_status(self):
        if self.difficulty.lives <= 1:
            return ""
        return self.text["lives_status"].format(lives=self.lives)

    def hint_line(self):
        key = self.hint_key()
        if key != "both_appeared":
            return self.text[key]
        labels = [self.text[f"{kind}_label"] for kind in self.notice_kinds]
        return self.text[key].format(kinds=self.text["label_separator"].join(labels))

    def hint_key(self):
        if self.notice_timer > 0:
            return self.notice_key
        if self.player.safe:
            return "safe"
        if self.is_hunting_phase():
            return "hunt"
        return "exit_open" if self.has_all_items() else "exit_hint"
