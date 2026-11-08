"""キー入力。"""

import sys

from panda3d.core import KeyboardButton, ModifierButtons

from ..difficulty import MENU_LEVELS


def ascii_button(char):
    try:
        return KeyboardButton.asciiKey(char)
    except TypeError:
        return KeyboardButton.asciiKey(char.encode())


class InputMixin:
    """キーの割り当てと、押した瞬間の判定。"""

    def bind_events(self):
        # Shiftなどを押していてもキーのイベントが届くようにする
        # （そのままだと、忍び足中のRは "shift-r" という別のイベントになってしまう）
        self.mouseWatcherNode.setModifierButtons(ModifierButtons())
        for thrower in self.buttonThrowers:
            thrower.node().setModifierButtons(ModifierButtons())
        self.accept("escape", sys.exit)
        self.accept("r", self.restart_game)
        self.accept("m", self.open_menu)
        self.accept("v", self.on_replay_key)
        self.accept("arrow_up", self.move_menu, [-1])
        self.accept("arrow_down", self.move_menu, [1])
        for i in range(len(MENU_LEVELS)):
            self.accept(str(i + 1), self.choose_difficulty, [i])
        # Tab・Enter（メニューの決定）・Space・Eは毎フレーム押下状態を調べ、押した瞬間に動かす
        # （移動キーを押しっぱなしでも確実に反応させるため）

    def setup_keys(self):
        self.key_groups = {
            "up": [ascii_button("w"), KeyboardButton.up()],
            "down": [ascii_button("s"), KeyboardButton.down()],
            "left": [ascii_button("a"), KeyboardButton.left()],
            "right": [ascii_button("d"), KeyboardButton.right()],
            "sneak": [KeyboardButton.shift()],
            "overview": [KeyboardButton.tab()],
            "confirm": [KeyboardButton.enter()],
            "cloak": [ascii_button("e"), ascii_button(".")],
            "flash": [ascii_button("q"), ascii_button("/")],
            "decoy": [KeyboardButton.space(), ascii_button("\\")],
            "noise_range": [ascii_button("f")],
            "pause": [ascii_button("p")],
        }

    def pressed_now(self, name):
        """このフレームで押された瞬間ならTrue（押しっぱなしでは1回だけ）。"""
        down = self.is_down(name)
        was_down = self.keys_were_down.get(name, False)
        self.keys_were_down[name] = down
        return down and not was_down

    def poll_action_keys(self):
        """押した瞬間の操作。キーごとに毎回調べるので、他のキーと同時押しでも反応する。

        プレイ中に使ったお助けアイテムのキーを返す（リプレイの記録用）。
        """
        names = ("overview", "confirm", "decoy", "cloak", "flash", "noise_range", "pause")
        presses = self.replay_presses({name: self.pressed_now(name) for name in names})
        if presses["noise_range"]:  # 設定の切り替えは、メニューでもプレイ中でもできる
            self.toggle_noise_range()
        if presses["pause"]:
            self.toggle_pause()
            if self.state in ("play", "paused"):
                return frozenset()  # P を押したコマはゲームを進めないので、お助けアイテムなども使わない（リプレイと合わなくなる）
        if self.state == "title":
            if presses["confirm"]:
                self.leave_title()
            return frozenset()
        if self.state == "menu":
            if presses["confirm"]:
                self.choose_difficulty(None)
            return frozenset()
        if self.state == "paused":  # 一時停止中は、再開・やり直し・難易度選択・設定・終了だけ受け付ける
            return frozenset()
        if presses["overview"]:
            self.toggle_overview()
        if presses["decoy"]:
            self.place_decoy()
        if presses["cloak"]:
            self.use_cloak()
        if presses["flash"]:
            self.use_flash()
        return frozenset(name for name in ("decoy", "cloak", "flash") if presses[name])

    def is_down(self, name):
        replayed, down = self.replay_key_down(name)
        if replayed:  # ベスト記録の再生中は、移動と忍び足のキーを記録のとおりに押す
            return down
        watcher = self.mouseWatcherNode
        return any(watcher.isButtonDown(button) for button in self.key_groups[name])

    def read_input(self):
        dx = int(self.is_down("right")) - int(self.is_down("left"))
        dy = int(self.is_down("up")) - int(self.is_down("down"))
        return dx, dy
