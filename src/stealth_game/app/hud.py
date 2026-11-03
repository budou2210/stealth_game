"""画面上の文字・警戒度メーター。"""

import os

from direct.gui.DirectGui import DirectWaitBar
from direct.gui.OnscreenText import OnscreenText
from panda3d.core import Filename, TextNode

from ..texts import TEXTS
from ..theme import FONT_CANDIDATES, MENU_TEXT_BG


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
        OnscreenText(
            text=self.text["controls"], parent=self.a2dBottomLeft, pos=(0.05, 0.04),
            scale=0.04, fg=(0.8, 0.8, 0.8, 1), shadow=(0, 0, 0, 1),
            align=TextNode.ALeft, font=self.font,
        )
        OnscreenText(
            text=self.text["alert"], parent=self.a2dBottomCenter, pos=(-0.78, 0.115),
            scale=0.05, fg=(1, 1, 1, 1), shadow=(0, 0, 0, 1),
            align=TextNode.ARight, font=self.font,
        )
        self.alert_bar = DirectWaitBar(
            parent=self.a2dBottomCenter, pos=(0, 0, 0.13), scale=0.7,
            range=1.0, value=0.0, barColor=(0.3, 0.9, 0.3, 1),
        )
        self.message_text = OnscreenText(
            text="", pos=(0, 0.1), scale=0.12, fg=(1, 1, 1, 1),
            shadow=(0, 0, 0, 1), mayChange=True, font=self.font,
        )
        self.menu_title = OnscreenText(
            text=self.text["title"], pos=(0, 0.62), scale=0.16, fg=(1, 1, 1, 1),
            shadow=(0, 0, 0, 1), bg=MENU_TEXT_BG, font=self.font,
        )
        self.menu_text = OnscreenText(
            text="", pos=(0, 0.38), scale=0.06, fg=(1, 1, 1, 1),
            shadow=(0, 0, 0, 1), bg=MENU_TEXT_BG, mayChange=True, font=self.font,
        )

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
                helpers=self.helper_status(),
            )
        )
        self.hint_text.setText(self.text[self.hint_key()])
        top = max(guard.alert for guard in self.guards)
        self.alert_bar["value"] = top
        self.alert_bar["barColor"] = (min(1.0, 0.3 + top), max(0.1, 0.9 - top), 0.2, 1)

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

    def hint_key(self):
        if self.notice_timer > 0:
            return self.notice_key
        if self.player.safe:
            return "safe"
        if self.is_hunting_phase():
            return "hunt"
        return "exit_open" if self.has_all_items() else "exit_hint"
