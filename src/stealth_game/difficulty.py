"""難易度の定義。"""

import math
from dataclasses import dataclass, replace


@dataclass(frozen=True)
class Difficulty:
    key: str  # TEXTSでの名前の引き当てに使う
    view_range: float  # 視界の長さ
    view_half_angle: float  # 視界の半角（ラジアン）
    sneak_view_rate: float  # 忍び足のとき視認距離にかける倍率
    hear_radius: float  # 走ったときの足音が届く距離
    alert_gain: float  # 視界に入っているときの警戒度の上がりやすさ
    chase_speed: float
    search_speed: float
    chase_lead_factors: tuple  # 追跡役ごとの先回りの強さ（0番が一番近い鬼）
    chase_replan: tuple  # 追跡中のA*再計算間隔(最小, 最大)
    lost_extrapolations: int  # 見失ったとき逃げた方向を先読みする最大回数
    lost_lookahead: float  # その先読みの距離
    search_wait: float  # 捜索地点での見回し時間
    ally_alert_radius: float  # 追跡中の鬼が仲間を呼べる距離
    ally_alert_max: int  # 1人の鬼が一度に呼べる仲間の数（近い順）。0なら無制限
    flank_avoid_cost: int  # 挟み撃ち：近い鬼の通る道のマスに足すA*のコスト。0なら挟み撃ちなし
    wanderers: bool  # 徘徊型（紫）を出すか
    smart_wander: bool  # 徘徊型がプレイヤー・アイテム・出口の近くを狙うか
    focus_rate: float  # smart_wanderのとき、目的地をその近くから選ぶ確率（0〜1）
    hunt_after_all_items: bool  # 全アイテム回収後、徘徊型が見失わずに追ってくるか
    lives: int  # ライフの数。1なら捕まった時点でゲームオーバー
    spot_delay: float  # 「！」を出してから追跡を始めるまでの秒数
    decoy_radius: float  # 音の罠が届く距離。0なら音の罠なし
    cloak: bool  # 透明化アイテムを出すか
    flash: bool  # スタン（アイテム）を出すか
    # 超越だけの仕掛け（devices.py）。ほかの難易度は初期値（なし）のまま
    sentries: bool = False  # 見張り番（動かずに向きだけ変える鬼）を区画ごとに1人置くか
    cameras: bool = False  # 監視カメラを区画ごとに1台付けるか
    timed_doors: bool = False  # 境目の真ん中の扉を、時間で開け閉めするか
    noisy_floors: int = 0  # 鳴る床の数。0ならなし
    # タイムアタック：鬼・お助けアイテム・仕掛け・安全地帯の扉・ライフ・警戒度メーターを使わず、
    # アイテム8個を集めて出口までのタイムだけを競う。一時停止（P）もできない
    time_attack: bool = False


# 難易度の詳細（メニューには雰囲気だけの説明を出し、中身はここに書く）
#
#   簡単   : 普通から紫の鬼（徘徊型）をなくしたもの。青い鬼10人だけ。ライフ3。
#   普通   : 基本。青10人＋紫6人。紫はランダムに徘徊。足音2.5。追跡3.1。ライフ2。
#   難しい : 激ムズの視界を弱め（長さ9・視野角75°・忍び足倍率0.72）、紫の鬼が
#            プレイヤー/未回収アイテム/出口の付近を狙う確率を10%に下げ、
#            足音での察知を3.0に下げ、「応援」を軽く（半径8・近くの2人まで）、
#            挟み撃ちをなくしたもの。
#            全アイテム回収後は紫の鬼が決して見失わない。ライフなし。
#   激ムズ : 地獄から、追跡速度を1割落とし(3.96)、「！」の後に0.5秒の間を置き、
#            お助けアイテム（透明化・音の罠。スタンは出ない）を加えたもの。ライフなし。
#   地獄   : 全力。視界10・視野角80°・警戒1.6倍・足音6.5・追跡4.4・応援16（人数無制限）・挟み撃ち。
#            「！」と同時に追跡。紫の鬼は30%の確率で注目地点を狙い、全アイテム回収後は
#            決して見失わない。お助けアイテムなし、ライフなし。
#
#   超越 : 地獄の見つかりやすさをさらに上げ（視界・視野角・忍び足の倍率・警戒・足音・注目地点）、
#            仕掛け（見張り番・監視カメラ・時間で開け閉めする扉・鳴る床）を加えたもの。
#            ボットがぎりぎりクリアできるように調整する（「理論上はクリアできる」難易度）。
#            見つかった後の強さ（追跡・応援・挟み撃ち）は地獄と同じ。
#
#   共通：鬼の速度（追跡・捜索）は、難易度ごとに定義の中で直接指定する（他の難易度から引き継がない）。
#         追跡速度は、地獄4.4、難しい・激ムズ3.96、普通・簡単3.1。巡回速度は全難易度共通（GUARD_PATROL_SPEED）。
#         地獄以外は「！」の後に0.5秒の間があり、お助けアイテムが出る
#         （簡単・普通は3種、難しい・激ムズはスタンを除く透明化・音の罠の2種）。
#         「応援」（追跡中の鬼が仲間に居場所を伝える）は、普通以下はなし、難しいは軽め。
#         激ムズ以上は挟み撃ち：遠い追っ手が近い鬼の道を避け、逃げる先へ回り込む。
#         全アイテム回収後に見失わずに追ってくる紫の鬼には、お助けアイテムが効かない。

# 普通：基本の難しさ
NORMAL = Difficulty(
    key="normal",
    view_range=8.0,
    view_half_angle=math.radians(35),
    sneak_view_rate=0.65,
    hear_radius=2.5,  # 難しい以下は足音での察知を大幅に下げる
    alert_gain=1.0,
    chase_speed=3.1,
    search_speed=2.8,
    chase_lead_factors=(0.3, 1.0, 1.6, 2.0),
    chase_replan=(0.1, 0.25),
    lost_extrapolations=2,
    lost_lookahead=5.0,
    search_wait=3.0,
    ally_alert_radius=0.0,  # 普通以下は「応援」なし
    ally_alert_max=0,
    flank_avoid_cost=0,
    wanderers=True,
    smart_wander=False,
    focus_rate=0.0,
    hunt_after_all_items=False,
    lives=2,
    spot_delay=0.5,
    decoy_radius=16.0,
    cloak=True,
    flash=True,
)

# 地獄：すべての強化が入った全力の難易度
HELL = Difficulty(
    key="hell",
    view_range=10.0,
    view_half_angle=math.radians(40),
    sneak_view_rate=0.8,
    hear_radius=6.5,
    alert_gain=1.6,
    chase_speed=4.4,
    search_speed=3.2,
    chase_lead_factors=(0.5, 1.2, 1.8, 2.4),
    chase_replan=(0.08, 0.18),
    lost_extrapolations=4,
    lost_lookahead=7.0,
    search_wait=5.0,
    ally_alert_radius=16.0,
    ally_alert_max=0,  # 無制限
    flank_avoid_cost=6,
    wanderers=True,
    smart_wander=True,
    focus_rate=0.3,  # 激ムズも同じ
    hunt_after_all_items=True,
    lives=1,
    spot_delay=0.0,  # 「！」は出すが、即座に追いかける
    decoy_radius=0.0,  # お助けアイテムなし
    cloak=False,
    flash=False,
)

# 激ムズ：地獄から、追跡速度を1割落とし、「！」の後に間を置き、
#        お助けアイテム（透明化・音の罠）を出すようにしたもの
VERY_HARD = replace(
    HELL,
    key="very_hard",
    chase_speed=3.96,
    search_speed=3.2,
    spot_delay=0.5,
    decoy_radius=16.0,  # 音の罠の範囲は全難易度で共通
    cloak=True,
    flash=False,  # スタンは出さない（難しいも同じ）
)

# 難しい：激ムズの視界を弱め、徘徊型が注目地点へ来る確率を下げ、
#        足音での察知を大幅に下げ、「応援」を軽くし、挟み撃ちをなくしたもの
HARD = replace(
    VERY_HARD,
    key="hard",
    chase_speed=3.96,
    search_speed=3.2,
    view_range=9.0,
    view_half_angle=math.radians(37.5),
    sneak_view_rate=0.72,
    focus_rate=0.1,
    hear_radius=3.0,  # 足音での察知を大幅に下げる（激ムズは6.5）
    ally_alert_radius=8.0,  # 「応援」は軽め（激ムズは16・無制限）
    ally_alert_max=2,
    flank_avoid_cost=0,  # 挟み撃ちなし
    decoy_radius=16.0,
)

# 簡単：普通から徘徊型をなくしたもの
EASY = replace(
    NORMAL,
    key="easy",
    chase_speed=3.1,
    search_speed=2.8,
    wanderers=False,
    lives=3,
)

# 超越：地獄の見つかりやすさをさらに上げ、仕掛けを加えたもの
TRANSCEND = replace(
    HELL,
    key="transcend",
    view_range=10.5,
    view_half_angle=math.radians(42.5),
    sneak_view_rate=0.85,
    hear_radius=7.0,
    alert_gain=1.8,
    focus_rate=0.4,
    sentries=True,
    cameras=True,
    timed_doors=True,
    noisy_floors=6,
)

DIFFICULTIES = [EASY, NORMAL, HARD, VERY_HARD, HELL, TRANSCEND]

# タイムアタック：鬼もお助けアイテムも出さず、アイテム8個（配置は毎回ランダム）を集めて出口までのタイムを競う。
# 鬼の数値は使わない（簡単のものをそのまま持つだけ）
TIME_ATTACK = replace(
    EASY,
    key="time_attack",
    wanderers=False,
    lives=1,
    decoy_radius=0.0,
    cloak=False,
    flash=False,
    time_attack=True,
)

# 難易度選択の一覧に並べるもの（難易度6つの下にタイムアタック）
MENU_LEVELS = DIFFICULTIES + [TIME_ATTACK]
DEFAULT_DIFFICULTY_INDEX = 1  # メニューで最初に選ばれている難易度（普通）
