"""テスト共通の準備。

ロジック（World・A*・Guardなど）はPanda3Dなしで動くので、そのまま読み込む。
ゲーム全体（StealthGame）を動かすテストだけ、Panda3Dを MagicMock に差し替えて読み込む
（ウィンドウやGPUがなくても動かせるようにするため）。
"""

import sys
from unittest.mock import MagicMock

import pytest

from stealth_game.world import World

PANDA_MODULES = [
    "panda3d",
    "panda3d.core",
    "direct",
    "direct.gui",
    "direct.gui.DirectGui",
    "direct.gui.OnscreenText",
    "direct.showbase",
    "direct.showbase.ShowBase",
]


class FakeShowBase:
    """ShowBaseの代わり。知らない属性を聞かれたら MagicMock を返す。"""

    def __init__(self):
        lens = MagicMock()
        lens.getFov.return_value = (60.0, 46.8)
        self.camLens = lens
        self.buttonThrowers = []

    def getAspectRatio(self):
        return 1100 / 800

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        value = MagicMock()
        object.__setattr__(self, name, value)
        return value


@pytest.fixture(autouse=True)
def records_dir(tmp_path, monkeypatch):
    """ベストタイムは本物の保存先ではなく、テストごとの一時フォルダに書く。"""
    directory = tmp_path / "data"
    monkeypatch.setenv("STEALTH_GAME_DATA_DIR", str(directory))
    return directory


@pytest.fixture
def world():
    return World()


@pytest.fixture(scope="session")
def game_class():
    """Panda3Dを差し替えた状態で読み込んだ StealthGame。"""
    saved = {name: sys.modules.get(name) for name in PANDA_MODULES}
    app_modules = [m for m in sys.modules if m.startswith(("stealth_game.app", "stealth_game.render"))]
    for name in app_modules:
        del sys.modules[name]
    for name in PANDA_MODULES:
        sys.modules[name] = MagicMock()
    sys.modules["direct.showbase.ShowBase"].ShowBase = FakeShowBase
    # 操作説明の大きさを決めるのに文字列の長さを使うので、数値を返すようにしておく
    sys.modules["direct.gui.OnscreenText"].OnscreenText.return_value.textNode.getWidth.return_value = 60.0
    from stealth_game.app.game import StealthGame

    # 警戒度メーターの位置は描画から求めるので、固定値にしておく
    StealthGame.alert_bar_top = lambda self: -0.8
    yield StealthGame
    for name, module in saved.items():
        if module is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = module
