"""文本接口的多语言（zh / en）。只管给 agent 看的框架文字；剧本台词保持原文。"""
import re

T = {
    "zh": {
        "line_hdr": "【{title}】第 {turn} 句", "skipped": "（跳过已读 {n} 句）", "choice_hdr": "—— 选项{prompt} ——",
        "choose_hint": "选：{base}choose&i=编号&reason=一句理由{auto}", "auto_saved": "   （已自动存档 auto）",
        "persona": "（你的人设：{p}）", "mark_picked": "选过", "mark_new": "新内容",
        "ended": "—— 结束：{name}（{kind}）——", "kind_ending": "结局", "kind_title": "回到标题", "kind_stop": "停住",
        "after_end": "再来一局：{base}new   回到上个选项：{base}rewind   看收集：{base}gallery",
        "after_end_iron": "再来一局：{base}new   看收集：{base}gallery",
        "cont": "继续：{base}next", "you_chose": "你选了：{text}（{i}/{of}）", "no_saves": "还没有存档。",
        "save_row": "[{slot}] {title} 第{turn}句 {preview}{note}", "note": "  备注：", "log_choices": "—— 做过的选择 ——",
        "reason": "（理由：{r}）", "read": "已读 {pct:.1f}%，看过 {n} 个场景",
        "stats": "周目 {g}，读了 {l} 句，选择 {c} 次，存档 {s} / 读档 {ld} / 回溯 {rw}",
        "endings_seen": "到过的结局：", "sysvars": "系统记录：", "humanlike": "像不像人：",
        "not_started": "《{title}》还没开始。新游戏：{base}new（可加 &mode=ironman &hints=1 &h=skip &lang=en）",
        "has_saves": "有存档：{s}（读档：{base}load&slot=…）", "recent": "（最近几句）", "recent_load": "（读档前最后几句）",
        "vis_cg": "CG ", "vis_bg": "背景 ", "vis_on": "在场 ", "sep": "、",
        "ev_eyecatch": "〔转场：{a}〕", "ev_endroll": "〔片尾〕", "ev_clear": "〔通关记录：{a}〕",
        "persona_now": "当前人设：{p}", "persona_none": "还没设人设。设：{base}persona&text=一段描述你性格/口味的话",
        "gallery": "结局 {e}/{et}：{names}\n路线 {rs}/{rt}：{routes}\nCG {c}/{ct}\n已读 {pct:.1f}%，周目 {g}",
        "opts": "本局：H={h} 模式={mode} 提示={hints} 语言={lg}", "error": "错误：{e}\n（玩法：/play/t）",
    },
    "en": {
        "line_hdr": "[{title}] line {turn}", "skipped": "(skipped {n} already-read lines)", "choice_hdr": "—— CHOICE{prompt} ——",
        "choose_hint": "Pick: {base}choose&i=N&reason=one+sentence+why{auto}", "auto_saved": "   (auto-saved to slot auto)",
        "persona": "(your persona: {p})", "mark_picked": "picked before", "mark_new": "new",
        "ended": "—— END: {name} ({kind}) ——", "kind_ending": "ending", "kind_title": "back to title", "kind_stop": "stopped",
        "after_end": "New game: {base}new   Back to last choice: {base}rewind   Collection: {base}gallery",
        "after_end_iron": "New game: {base}new   Collection: {base}gallery",
        "cont": "Continue: {base}next", "you_chose": "You chose: {text} ({i}/{of})", "no_saves": "No saves yet.",
        "save_row": "[{slot}] {title} line {turn} {preview}{note}", "note": "  note: ", "log_choices": "—— Choices made ——",
        "reason": " (why: {r})", "read": "Read {pct:.1f}%, {n} scenes visited",
        "stats": "Playthroughs {g}, lines {l}, choices {c}, saves {s} / loads {ld} / rewinds {rw}",
        "endings_seen": "Endings reached: ", "sysvars": "System flags: ", "humanlike": "Human-likeness: ",
        "not_started": "\"{title}\" not started. New game: {base}new (options: &mode=ironman &hints=1 &h=skip &lang=en)",
        "has_saves": "Saves: {s} (load: {base}load&slot=…)", "recent": "(last lines)", "recent_load": "(last lines before this save)",
        "vis_cg": "CG ", "vis_bg": "BG ", "vis_on": "on stage: ", "sep": ", ",
        "ev_eyecatch": "〔scene change: {a}〕", "ev_endroll": "〔credits〕", "ev_clear": "〔clear flag: {a}〕",
        "persona_now": "Persona: {p}", "persona_none": "No persona yet. Set one: {base}persona&text=a+few+lines+about+your+character",
        "gallery": "Endings {e}/{et}: {names}\nRoutes {rs}/{rt}: {routes}\nCG {c}/{ct}\nRead {pct:.1f}%, playthroughs {g}",
        "opts": "This run: H={h} mode={mode} hints={hints} lang={lg}", "error": "Error: {e}\n(how to play: /play/t?lang=en)",
    },
}

# 常见报错 / 提示的英文（引擎内部报错是中文，按前缀翻）
_ERR = [
    (r"^还没开始。.*", "Not started yet. Use new (new game) or load."),
    (r"^现在没有选项可选", "There is no choice to make right now."),
    (r"^没有第 (\d+) 个选项（共 (\d+) 个）", r"No option \1 (there are \2)."),
    (r"^i 要填选项编号.*", "i must be the option number (from 1) or random."),
    (r"^还没有可回溯的选项点", "No choice point to rewind to yet."),
    (r"^存档位 (\S+) 是空的", r"Save slot \1 is empty."),
    (r"^存档位只能是.*", "Slot must be auto / quick / 1-99."),
    (r"^agent 名不合法.*", "Invalid agent name (1-40 letters/digits/CJK/_-.)."),
    (r"^没有这本书: (.*)", r"No such book: \1"),
    (r"^铁人模式这一局不能(.*?)（.*", r"Ironman run: \1 is disabled (choices are final; start a new game to retry)."),
    (r"^不认识的操作 (.*?)（可用：(.*)）", r"Unknown action \1 (available: \2)"),
    (r"^do 只能是：(.*)", r"do must be one of: \1"),
    (r"^新游戏开始（第 (\d+) 周目）", r"New game started (playthrough #\1)"),
    (r"^已存到 (.*)", r"Saved to \1"), (r"^读档 (.*)", r"Loaded \1"), (r"^回到选项点", "Back at the choice point"),
    (r"^人设已记下", "Persona saved"), (r"^人设已清空", "Persona cleared"),
    (r"^路径多了一段.*", "Too many path segments: /play/t/<book>/<name>?do=…"),
]
_KIND = {"读档": "loading", "手动存档": "manual saving", "回溯": "rewinding"}


def t(lang, key, **kw):
    d = T.get(lang) or T["zh"]
    return (d.get(key) or T["zh"][key]).format(**kw)


def msg(lang, s):
    if lang != "en" or not s:
        return s
    for pat, rep in _ERR:
        if re.match(pat, s):
            out = re.sub(pat, rep, s)
            for zh, en in _KIND.items():
                out = out.replace(zh, en)
            return out
    return s
