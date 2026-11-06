define a = Character("灯", color="#c8ffc8")
define m = Character("誠")
image bg sea = "bg_001.png"
default trust = 0
define persistent.clear_a = False

label start:
    scene bg sea
    play music "bgm001.ogg"
    "夜の海は、思ったより静かだった。"
    show akari smile at center
    a "こんな時間に、灯台まで来る人なんて珍しいね。"  # 注释
    m "……灯りが見えたから。"
    menu:
        a "少し手伝ってくれる？"
        "岩屋へ行く" if persistent.clear_a:
            jump cave
        "手伝う":
            $ trust += 1
            call talk
            jump help_end
        "今日は帰る":
            jump route_b

label talk:
    a "……灯りはね、消えたら終わりなの。"
    return

label help_end:
    if trust >= 1:
        $ persistent.clear_a = True
        "二人で灯りを守った。夜明けまで。"
    else:
        "なにも起きなかった。"
    return

label cave:
    "岩屋の奥で、古い航海日誌を見つけた。"
    return

init python:
    def unused():
        return 1
