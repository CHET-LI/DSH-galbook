;灯台・KAG 版
*start|はじまり
[bg storage="bg_001"]
[playbgm storage="bgm001.ogg"]
夜の海は、思ったより静かだった。[p]
[chara_show name="灯" face="smile"]
#灯
こんな時間に、灯台まで来る人なんて珍しいね。[p]
#
@eval exp="f.trust=0"
[if exp="sf.clearA==1"]
[glink text="岩屋へ行く（灯火のあとで解锁）" target=*cave]
[endif]
[link target=*help exp="f.trust+=1"]手伝う[endlink][r]
[link storage="route_b.ks" target=*top]今日は帰る[endlink]
[s]
*help
【灯】ありがとう。[l]
[call target=*sub_talk]
[if exp="f.trust>=1"]
@jump target=*end_a
[else]
@jump storage="route_b.ks" target=*top
[endif]
*sub_talk
#灯
……灯りはね、消えたら終わりなの。[p]
#
[return]
*end_a
[eval exp="sf.clearA=1"]
二人で灯りを守った。夜明けまで。[p]
[gotostart]
*cave
岩屋の奥で、古い航海日誌を見つけた。[p]
[gotostart]
