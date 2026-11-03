"""難易度選択メニュー。"""

from ..difficulty import DIFFICULTIES


class MenuMixin:
    """難易度選択メニュー。"""

    def level_name(self, cfg):
        return self.text[cfg.key]

    def lives_label(self, cfg):
        if cfg.lives <= 1:
            return self.text["no_lives_label"]
        return self.text["lives_label"].format(lives=cfg.lives)

    def update_menu_text(self):
        lines = [self.text["menu_prompt"], ""]
        for i, cfg in enumerate(DIFFICULTIES):
            marker = ">" if i == self.menu_index else " "
            lines.append(f"{marker} {i + 1}. {self.level_name(cfg)}{self.lives_label(cfg)}")
            lines.append(self.text[f"{cfg.key}_desc"])
            lines.append("")
        self.menu_text.setText("\n".join(lines))

    def open_menu(self):
        self.state = "menu"
        self.camera_mode = "overview"
        self.clear_placed_decoys()
        self.message_text.setText("")
        self.menu_title.show()
        self.menu_text.show()
        self.update_menu_text()

    def move_menu(self, step):
        if self.state != "menu":
            return
        self.menu_index = (self.menu_index + step) % len(DIFFICULTIES)
        self.update_menu_text()

    def choose_difficulty(self, index):
        if self.state != "menu":
            return
        if index is not None:
            self.menu_index = index
        self.start_game(DIFFICULTIES[self.menu_index])
