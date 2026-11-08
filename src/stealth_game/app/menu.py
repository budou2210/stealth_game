"""難易度選択メニュー。"""

from ..difficulty import MENU_LEVELS


class MenuMixin:
    """難易度選択メニュー。"""

    def level_name(self, cfg):
        return self.text[cfg.key]

    def lives_label(self, cfg):
        if cfg.time_attack:  # 捕まる仕組みがないので、ライフの表示もしない
            return ""
        if cfg.lives <= 1:
            return self.text["no_lives_label"]
        return self.text["lives_label"].format(lives=cfg.lives)

    def setting_state(self, enabled):
        return self.text["setting_on"] if enabled else self.text["setting_off"]

    def toggle_noise_range(self):
        """設定：足音の範囲の表示を切り替える（ゲームを閉じるまで有効）。"""
        self.show_noise_range = not self.show_noise_range
        if self.state == "menu":
            self.update_menu_text()

    def update_menu_text(self):
        setting = self.text["noise_range_setting"].format(state=self.setting_state(self.show_noise_range))
        lines = [self.text["menu_prompt"], setting, self.text["replay_prompt"], ""]
        for i, cfg in enumerate(MENU_LEVELS):
            marker = ">" if i == self.menu_index else " "
            best = self.best_times.get(cfg.key)
            best_label = self.text["best_label"].format(time=best) if best is not None else ""
            if self.has_best_replay(cfg):
                best_label += self.text["replay_mark"]
            lines.append(f"{marker} {i + 1}. {self.level_name(cfg)}{self.lives_label(cfg)}{best_label}")
            desc = self.text[f"{cfg.key}_desc"]
            if desc:  # 説明が空なら行を出さない
                lines.append(desc)
            lines.append("")
        self.menu_text.setText("\n".join(lines))

    def open_menu(self):
        self.stop_replay()
        self.clear_ghost()
        self.state = "menu"
        self.camera_mode = "overview"
        self.reset_audio()
        self.clear_placed_decoys()
        self.message_text.setText("")
        self.set_title_visible(False)
        self.menu_title.show()
        self.menu_text.show()
        self.controls_text.show()
        self.credit_text.show()
        self.set_play_hud_visible(False)
        self.update_menu_text()

    def move_menu(self, step):
        if self.state != "menu":
            return
        self.menu_index = (self.menu_index + step) % len(MENU_LEVELS)
        self.play_sound("cursor")
        self.update_menu_text()

    def choose_difficulty(self, index):
        if self.state != "menu":
            return
        if index is not None:
            self.menu_index = index
        self.play_sound("confirm")
        self.start_game(MENU_LEVELS[self.menu_index])
