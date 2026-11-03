# フォルダを直接実行（uv run src/stealth_game）したときは相対importが使えないので、絶対importにする
from stealth_game import main

if __name__ == "__main__":
    main()
