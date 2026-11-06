"""运行时：把剧本往前推，遇到选项停下等 agent 选。

状态（state，可 JSON 序列化，存档就是它的拷贝）：
  scene, pc          当前位置
  stack              call 的返回栈 [[scene, pc], ...]
  f                  本局变量（随存档走）
  vis                画面 {"bg", "cg", "sprites": {名字: {"img", "pos"}}, "bgm"}
  pending            正在等的选项 {"scene", "pc", "id", "options": [{"i", "text", "k"}], "shown_at"}
  ended              结束信息 {"kind", "name"} 或 None
  turn               已经读过的台词句数（本局）
  choices            本局做过的选择 [{"scene", "title", "id", "text", "i", "reason", "turn", "think_s"}]
  log                最近 300 句回想 [{"who", "text", "scene"}]
  rewind             最近 30 个选项点的快照（回溯用）
  opts               {"h": "fold"|"full"|"skip", "mode": "normal"|"ironman", "hints": bool, "lang": "zh"|"en"}
系统变量 s（通关标记等，跨周目）和已读记录 seen 不在 state 里，按 agent 存在档案中。
"""
import copy
import re
import time

from .expr import evaluate, assign, ExprError
from .ir import StoryError

MAX_OPS_PER_CALL = 500000
LOG_KEEP = 300
REWIND_KEEP = 30
H_FOLD_TEXT = "〔此处略（H 场景，new 时传 h=full 可展开）〕"
H_FOLD_TEXT_EN = "〔Adult scene folded — start with h=full to show it〕"

_RB = re.compile(r"\[rb,([^,\]]+),([^\]]*)\]")
_TAG = re.compile(r"\[[A-Za-z]+(?:,[^\]]*)?\]")


def plain(text):
    """[rb,汉字,假名] → 汉字；其余 [xx,..] 标签去掉。"""
    t = _RB.sub(lambda m: m.group(1), text or "")
    return _TAG.sub("", t)


class PlayError(ValueError):
    pass


H_MODES = ("fold", "full", "skip")
MODES = ("normal", "ironman")


def make_opts(h="fold", mode="normal", hints=False, lang="zh", **_):
    """一局的玩法选项（new 时定，存进存档）。
    h      H 场景：fold 折叠成一行（默认）/ full 照常 / skip 整段跳过不提示
    mode   normal 可存读档回溯 / ironman 铁人：不能读档、不能回溯，选了就认
    hints  选项旁标「选过」「新内容」（像很多游戏的已选标记）
    lang   文本接口的语言 zh / en"""
    return {"h": h if h in H_MODES else "fold", "mode": mode if mode in MODES else "normal",
            "hints": str(hints).lower() in ("1", "true", "yes", "on"), "lang": lang if lang in ("zh", "en") else "zh"}


def new_state(story, h="fold", **opts):
    e = story.entry or {}
    sid, pc = story.resolve(e.get("scene"), e.get("label"))
    return {"scene": sid, "pc": pc, "stack": [], "f": {}, "vis": {"bg": None, "cg": None, "sprites": {}, "bgm": None},
            "pending": None, "ended": None, "turn": 0, "choices": [], "log": [], "rewind": [],
            "opts": make_opts(h=h, **opts), "started": time.time(), "h_shown": None}


# ---------- 已读记录：每个场景一组区间 [[a,b],...]（闭区间，pc 编号） ----------
def seen_has(seen, sid, pc):
    for a, b in seen.get(sid, ()):
        if a <= pc <= b:
            return True
        if a > pc:
            return False
    return False


def seen_add(seen, sid, pc):
    rs = seen.setdefault(sid, [])
    for i, (a, b) in enumerate(rs):
        if a <= pc <= b:
            return False
        if pc == b + 1:
            rs[i][1] = pc
            if i + 1 < len(rs) and rs[i + 1][0] == pc + 1:
                rs[i][1] = rs[i + 1][1]
                del rs[i + 1]
            return True
        if pc == a - 1:
            rs[i][0] = pc
            return True
        if pc < a:
            rs.insert(i, [pc, pc])
            return True
    rs.append([pc, pc])
    return True


def _snapshot(state):
    snap = {k: copy.deepcopy(v) for k, v in state.items() if k not in ("rewind", "log")}
    snap["log_len"] = len(state.get("log", []))
    return snap


def advance(story, state, sysv, seen, n=20, skip_read=False):
    """往前推进，最多收 n 句「新」台词；遇到选项 / 结束就停。
    skip_read=True：已读过的句子快进不计数（像游戏里的「跳过已读」），停在第一句没读过的或选项上。
    返回 {"lines": [...], "skipped": 已读快进句数, "choice": ..., "ended": ..., "events": [...]}"""
    out, events = [], []
    skipped = 0
    if state.get("pending"):
        return _result(story, state, out, skipped, events)
    if state.get("ended"):
        return _result(story, state, out, skipped, events)
    budget = MAX_OPS_PER_CALL
    while budget > 0:
        budget -= 1
        sc = story.scene(state["scene"])
        pc = state["pc"]
        if pc >= len(sc.ops):
            if state["stack"]:
                state["scene"], state["pc"] = state["stack"].pop()
                continue
            state["ended"] = {"kind": "stop", "name": "场景 %s 走到底且没有跳转" % sc.title}
            break
        op = sc.ops[pc]
        state["pc"] = pc + 1
        cond = op.get("if")
        k = op.get("op")
        if cond and k != "choice":
            try:
                if not evaluate(cond, state["f"], sysv):
                    continue
            except ExprError as e:
                events.append({"warn": str(e)})
                continue
        if k == "say":
            hm = state["opts"].get("h")
            if "h" in sc.tags and hm != "full":
                if hm != "skip" and state.get("h_shown") != sc.id:
                    state["h_shown"] = sc.id
                    line = {"who": "", "text": H_FOLD_TEXT_EN if state["opts"].get("lang") == "en" else H_FOLD_TEXT,
                            "scene": sc.id, "pc": pc, "folded": True}
                    out.append(line)
                    _log(state, line)
                seen_add(seen, sc.id, pc)
                continue
            was = seen_has(seen, sc.id, pc)
            seen_add(seen, sc.id, pc)
            state["turn"] += 1
            line = {"who": op.get("who") or "", "text": op.get("text") or "", "scene": sc.id, "pc": pc}
            if op.get("voice"):
                line["voice"] = op["voice"]
            _log(state, line)
            if skip_read and was:
                skipped += 1
                continue
            line["vis"] = _vis_brief(state["vis"])
            out.append(line)
            if len(out) >= n:
                break
        elif k == "bg":
            state["vis"]["bg"] = op.get("img")
            state["vis"]["cg"] = None
        elif k == "cg":
            state["vis"]["cg"] = op.get("img")
            if op.get("img"):
                events.append({"cg": op["img"]})
        elif k == "sprite":
            if op.get("img"):
                state["vis"]["sprites"][op.get("name", "?")] = {"img": op["img"], "pos": op.get("pos") or "center"}
            else:
                state["vis"]["sprites"].pop(op.get("name", "?"), None)
        elif k == "sprites_clear":
            state["vis"]["sprites"] = {}
        elif k == "bgm":
            state["vis"]["bgm"] = op.get("name")
        elif k == "label":
            nm = op.get("name") or ""
            if nm and not nm.startswith("__"):
                state["label"] = nm
        elif k == "set":
            try:
                for name in assign(op.get("expr", ""), state["f"], sysv):
                    events.append({"set": name})
            except ExprError as e:
                events.append({"warn": str(e)})
        elif k == "jump":
            state["scene"], state["pc"] = story.resolve(op.get("scene"), op.get("label"), sc.id)
        elif k == "call":
            state["stack"].append([sc.id, state["pc"]])
            state["scene"], state["pc"] = story.resolve(op.get("scene"), op.get("label"), sc.id)
        elif k == "ret":
            if state["stack"]:
                state["scene"], state["pc"] = state["stack"].pop()
        elif k == "event":
            events.append({"event": op.get("name"), "arg": op.get("arg")})
        elif k == "end":
            state["ended"] = {"kind": op.get("kind") or "ending", "scene": sc.id,
                              "name": op.get("name") or ("%s·%s" % (sc.title, state["label"]) if state.get("label") and state["label"] != sc.title else sc.title)}
            if op.get("how"):
                state["ended"]["how"] = op["how"]
            break
        elif k == "choice":
            opts = []
            for j, o in enumerate(op.get("options") or []):
                try:
                    ok = evaluate(o.get("if"), state["f"], sysv)
                except ExprError as e:
                    events.append({"warn": str(e)})
                    ok = False
                if ok:
                    opts.append({"i": len(opts) + 1, "text": plain(o.get("text", "")), "k": j})
            if not opts:
                continue
            if len(opts) == 1 and op.get("auto_single"):
                state["pc"] = pc
                _take(story, state, sysv, sc, op, opts[0], reason="（只有一个可选，自动）", auto=True)
                continue
            state["pc"] = pc
            state["pending"] = {"scene": sc.id, "pc": pc, "id": op.get("id") or ("c%d" % pc),
                                "prompt": op.get("prompt") or "", "options": opts, "shown_at": time.time()}
            state["rewind"].append(_snapshot(state))
            del state["rewind"][:-REWIND_KEEP]
            break
    else:
        raise PlayError("一次推进执行了 %d 条指令还没停，剧本可能有死循环（%s#%d）"
                        % (MAX_OPS_PER_CALL, state["scene"], state["pc"]))
    return _result(story, state, out, skipped, events)


def _take(story, state, sysv, sc, op, opt, reason="", auto=False):
    o = op["options"][opt["k"]]
    if o.get("set"):
        assign(o["set"], state["f"], sysv)
    g = o.get("goto") or {}
    shown = (state.get("pending") or {}).get("shown_at")
    state["choices"].append({"scene": sc.id, "title": sc.title, "id": op.get("id") or "", "text": opt["text"],
                             "i": opt["i"], "of": None, "reason": (reason or "")[:500], "turn": state["turn"],
                             "think_s": round(time.time() - shown, 1) if shown else None, "auto": auto})
    state["pending"] = None
    if g:
        state["scene"], state["pc"] = story.resolve(g.get("scene"), g.get("label"), sc.id)
    else:
        state["pc"] = state["pc"] + 1


def choose(story, state, sysv, i, reason=""):
    p = state.get("pending")
    if not p:
        raise PlayError("现在没有选项可选")
    try:
        i = int(i)
    except (TypeError, ValueError):
        raise PlayError("i 要填选项编号（1 开始）")
    opt = next((o for o in p["options"] if o["i"] == i), None)
    if opt is None:
        raise PlayError("没有第 %d 个选项（共 %d 个）" % (i, len(p["options"])))
    sc = story.scene(p["scene"])
    op = sc.ops[p["pc"]]
    state["pc"] = p["pc"]
    _take(story, state, sysv, sc, op, opt, reason)
    state["choices"][-1]["of"] = len(p["options"])
    return state["choices"][-1]


def rewind(state, steps=1):
    """回到第 steps 个之前的选项点（1 = 最近一次的选项，重新选）。"""
    rw = state.get("rewind") or []
    if not rw:
        raise PlayError("还没有可回溯的选项点")
    steps = max(1, min(int(steps), len(rw)))
    snap = rw[-steps]
    keep = rw[:-steps] + [snap]
    log = state.get("log", [])[:snap.get("log_len", 0)]
    new = copy.deepcopy({k: v for k, v in snap.items() if k != "log_len"})
    new["rewind"] = keep
    new["log"] = log
    if new.get("pending"):
        new["pending"]["shown_at"] = time.time()
    return new


def _log(state, line):
    lg = state.setdefault("log", [])
    lg.append({"who": line["who"], "text": line["text"], "scene": line["scene"]})
    if len(lg) > LOG_KEEP + 50:
        del lg[:-LOG_KEEP]


def _vis_brief(vis):
    return {"bg": vis.get("bg"), "cg": vis.get("cg"),
            "sprites": [dict(name=k, **v) for k, v in (vis.get("sprites") or {}).items()]}


def where(story, state):
    sc = story.scenes.get(state.get("scene"))
    return {"scene": state.get("scene"), "title": sc.title if sc else "", "route": sc.route if sc else "",
            "turn": state.get("turn", 0)}


def peek(story, state, recent=5):
    """不推进，只看当前在哪、有没有待选的选项（旁观 / status 用）。"""
    r = _result(story, state, [], 0, [])
    r["recent"] = [{"who": x.get("who", ""), "text": x.get("text", "")} for x in (state.get("log") or [])[-recent:]]
    return r


def _result(story, state, lines, skipped, events):
    r = {"lines": lines, "skipped": skipped, "where": where(story, state), "vis": _vis_brief(state["vis"])}
    if state.get("pending"):
        p = state["pending"]
        r["choice"] = {"id": p["id"], "prompt": p.get("prompt", ""),
                       "options": [{"i": o["i"], "text": o["text"]} for o in p["options"]]}
    if state.get("ended"):
        r["ended"] = state["ended"]
    ev = [e for e in events if "warn" not in e and "cg" not in e]
    cgs = [e["cg"] for e in events if "cg" in e]
    if cgs:
        r["cg_seen"] = cgs
    warns = [e["warn"] for e in events if "warn" in e]
    if ev:
        r["events"] = ev[-20:]
    if warns:
        r["warnings"] = warns[:10]
    return r
