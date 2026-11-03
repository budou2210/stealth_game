"""難易度選択メニュー。"""

from ..difficulty import DIFFICULTIES, HIDDEN_DIFFICULTIES

SECRET_CODE = "LRLRLR"  # 隠し難易度を出すコマンド（←→←→←→）


class MenuMixin:
    """難易度選択メニュー。"""

    def menu_levels(self):
        """メニューに並べる難易度。隠しコマンドを入れた後は隠し難易度も末尾に出る。"""
        return DIFFICULTIES + HIDDEN_DIFFICULTIES if self.secret_unlocked else DIFFICULTIES

    def level_name(self, cfg):
        return self.text[cfg.key]

    def lives_label(self, cfg):
        if cfg.lives <= 1:
            return self.text["no_lives_label"]
        return self.text["lives_label"].format(lives=cfg.lives)

    def update_menu_text(self):
        levels = self.menu_levels()
        lines = [self.text["menu_prompt"].format(count=len(levels)), ""]
        for i, cfg in enumerate(levels):
            marker = ">" if i == self.menu_index else " "
            lines.append(f"{marker} {i + 1}. {self.level_name(cfg)}{self.lives_label(cfg)}")
            lines.append(self.text[f"{cfg.key}_desc"])
            lines.append("")
        self.menu_text.setText("\n".join(lines))

    def open_menu(self):
        self.state = "menu"
        self.camera_mode = "overview"
        self.secret_input = ""
        self.clear_placed_decoys()
        self.message_text.setText("")
        self.menu_title.show()
        self.menu_text.show()
        self.update_menu_text()

    def move_menu(self, step):
        if self.state != "menu":
            return
        self.menu_index = (self.menu_index + step) % len(self.menu_levels())
        self.update_menu_text()

    def enter_secret(self, key):
        """メニューで←→を押すたびに呼ばれる。コマンドがそろったら隠し難易度を出して選ぶ。"""
        if self.state != "menu" or self.secret_unlocked:
            return
        self.secret_input = (self.secret_input + key)[-len(SECRET_CODE):]
        if self.secret_input != SECRET_CODE:
            return
        self.secret_unlocked = True
        self.menu_index = len(DIFFICULTIES)  # 出てきた隠し難易度にカーソルを合わせる
        self.update_menu_text()

    def choose_difficulty(self, index):
        if self.state != "menu":
            return
        levels = self.menu_levels()
        if index is not None:
            if index >= len(levels):  # 隠し難易度は、出す前は数字キーでも選べない
                return
            self.menu_index = index
        self.start_game(levels[self.menu_index])
