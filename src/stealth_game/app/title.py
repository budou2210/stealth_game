"""タイトル画面（起動したときだけ出す。Enterで難易度選択へ）。"""

import math
from pathlib import Path

from direct.gui.OnscreenImage import OnscreenImage
from direct.gui.OnscreenText import OnscreenText
from panda3d.core import Filename

TITLE_IMAGE = Path(__file__).resolve().parents[1] / "assets" / "images" / "title.jpg"
TITLE_IMAGE_ASPECT = 2000 / 1447  # 画像の横÷縦
PROMPT_BLINK_RATE = 2.5  # 「Enterキーでスタート」を点滅させる速さ（1秒あたりの回数）


def cover_scale(window_aspect, image_aspect):
    """画像を縦横比を保ったまま画面いっぱいに広げる倍率 (横, 縦)。はみ出した分は切れる。

    render2d は画面の縦横を -1〜1 で表すので、倍率1で画面の端から端まで届く。
    """
    if window_aspect > image_aspect:  # 画面の方が横長：横を合わせ、上下を切る
        return 1.0, window_aspect / image_aspect
    return image_aspect / window_aspect, 1.0  # 画面の方が縦長：縦を合わせ、左右を切る


class TitleMixin:
    """タイトル画面。"""

    def setup_title(self):
        self.title_image = None
        if TITLE_IMAGE.exists():
            path = Filename.fromOsSpecific(str(TITLE_IMAGE)).getFullpath()
            self.title_image = OnscreenImage(image=path, parent=self.render2d)
        else:
            print(f"タイトル画像が見つからないので、画像なしで表示します: {TITLE_IMAGE}")
        self.title_aspect = None  # 画像の大きさを最後に合わせたときの画面の縦横比
        self.title_logo = OnscreenText(
            text=self.text["title"], pos=(0, 0.62), scale=0.2, fg=(1, 1, 1, 1),
            shadow=(0, 0, 0, 1), font=self.font,
        )
        self.title_prompt = OnscreenText(
            text=self.text["title_prompt"], pos=(0, -0.85), scale=0.07, fg=(1, 1, 1, 1),
            shadow=(0, 0, 0, 1), font=self.font,
        )
        self.title_time = 0.0
        self.set_title_visible(False)

    def set_title_visible(self, visible):
        nodes = [self.title_logo, self.title_prompt]
        if self.title_image is not None:
            nodes.append(self.title_image)
        for node in nodes:
            if visible:
                node.show()
            else:
                node.hide()

    def open_title(self):
        self.state = "title"
        self.title_time = 0.0
        self.menu_title.hide()
        self.menu_text.hide()
        self.controls_text.hide()
        self.credit_text.show()
        self.set_play_hud_visible(False)
        self.set_title_visible(True)

    def leave_title(self):
        """Enter：難易度選択へ進む。"""
        if self.state != "title":
            return
        self.play_sound("confirm")
        self.open_menu()

    def update_title(self, dt):
        """画像を画面いっぱいに合わせ（ウィンドウの大きさが変わったときだけ）、案内を点滅させる。"""
        self.title_time += dt
        aspect = self.getAspectRatio()
        if self.title_image is not None and aspect != self.title_aspect:
            self.title_aspect = aspect
            sx, sy = cover_scale(aspect, TITLE_IMAGE_ASPECT)
            self.title_image.setScale(sx, 1, sy)
        visible = math.sin(self.title_time * PROMPT_BLINK_RATE * 2 * math.pi) > -0.3
        if visible:
            self.title_prompt.show()
        else:
            self.title_prompt.hide()
