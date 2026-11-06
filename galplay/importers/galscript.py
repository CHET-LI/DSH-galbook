"""galscript（.gal）：一种人手能写、程序好生成的剧本格式 → galplay/1。

用途：①自己写互动故事给 agent 玩；②给没有现成导入器的引擎写转换脚本时，先转成 .gal 再导入（最省事）。

  # 注释                         title: 书名   （第一个场景前的 key: value 是书的信息）
  === 场景id 标题                 新场景（一个文件可多个；不写就是一个场景 main）
  @route 路线名   @tag h          给当前场景标路线 / 标签（h = H 场景，默认折叠）
  * 标签                          跳转目标
  灯：「台词」   或   灯: 台词     台词（名字 ≤12 字、不含空格和句读；用全角「：」或「: 」）
  其它行                          旁白
  @bg 文件  @cg 文件  @show 名字 文件 [位置]  @hide 名字  @clear  @bgm 名字|none  @event 名 参数
  $ f.trust += 1; s.clear_a = 1   改变量（f. 本周目 / s. 跨周目）
  ? 提示语                        选项开始（可省提示语，直接写 - 行也行）
  - 选项文字 -> 目标 [if 条件] [do 赋值]
  -> 目标 [if 条件]               跳转；目标 = 标签 / 场景id / 场景id#标签
                                  （先找本场景标签，再找同名场景，再找全局唯一标签；找不到 build 校验会报出来）
  call 目标   return
  @end ending 结局名   @end title   @end stop
文件编码 UTF-8（也认 cp932/GBK）。多个 .gal 文件按文件名排序依次读入，第一个文件的第一个场景是入口。"""
import os
import re

from .common import SceneB, Assets, read_text

NAME = "galscript"
SAY = re.compile(r"^([^\s：:「『。，、！？!?,…—]{1,12})(?:：|:\s)\s*(.+)$")
SAY_Q = re.compile(r"^([^\s：:「『（(。，、！？!?,…—]{1,12})([「『].*)$")
OPT = re.compile(r"^-\s*(.+?)\s*->\s*(\S+)(?:\s+if\s+(.+?))?(?:\s+do\s+(.+))?\s*$")
JMP = re.compile(r"^->\s*(\S+)(?:\s+if\s+(.+))?\s*$")


def detect(src):
    for dp, _, fn in os.walk(src):
        if any(f.lower().endswith(".gal") for f in fn):
            return True, "有 galscript 剧本（.gal）"
    return False, ""


def _target(t, here):
    if "#" in t:
        sc, _, lb = t.partition("#")
        return {"scene": sc or None, "label": lb or None}
    return {"scene": None, "label": t}


def build(src, assets=None, **_):
    assets = assets or Assets()
    files = []
    for dp, _, fn in os.walk(src):
        files += [os.path.join(dp, f) for f in fn if f.lower().endswith(".gal")]
    files.sort()
    if not files:
        raise ValueError("%s 里没有 .gal 文件" % src)
    scenes, order, meta_kv, warnings = {}, [], {}, []
    stats = {"files": len(files), "says": 0, "choices": 0, "options": 0, "jumps": 0, "calls": 0, "sets": 0}
    sysv = set()
    cur, pend = None, None   # pend = 正在攒的 choice op

    def new_scene(sid, title):
        nonlocal cur
        if sid in scenes:
            raise ValueError("场景 id 重复：%s" % sid)
        cur = SceneB(sid, title or sid)
        scenes[sid] = cur
        order.append(sid)

    def fix_targets(op, here):
        g = op.get("goto") if op.get("op") == "choice" else None
        return g

    for path in files:
        rel = os.path.relpath(path, src)
        for no, raw in enumerate(read_text(path).splitlines(), 1):
            line = raw.strip()
            where = "%s:%d" % (rel, no)
            if not line or line.startswith("#"):
                continue
            if pend is not None and not (line.startswith("- ") or line == "-" or line.startswith("-\t")):
                pend = None
            if cur is None and not line.startswith("===") and re.match(r"^[A-Za-z_]+:\s", line) and not scenes:
                k, _, v = line.partition(":")
                meta_kv[k.strip()] = v.strip()
                continue
            if line.startswith("==="):
                bits = line[3:].strip().split(None, 1)
                if not bits:
                    warnings.append("%s: === 后面要写场景 id" % where)
                    continue
                new_scene(bits[0], bits[1] if len(bits) > 1 else bits[0])
                continue
            if cur is None:
                new_scene("main", meta_kv.get("title", "main"))
            for m in re.findall(r"\b(s\.[A-Za-z_]\w*)", line):
                sysv.add(m[2:])
            if line.startswith("* "):
                cur.add("label", name=line[2:].strip())
            elif line.startswith("@"):
                w = line[1:].split()
                c, a = w[0].lower(), w[1:]
                if c == "route":
                    cur.route = " ".join(a)
                elif c == "tag":
                    cur.tags += a
                elif c in ("bg", "cg"):
                    img = None if not a or a[0].lower() == "none" else (assets.find(a[0]) or a[0])
                    cur.add(c, img=img)
                elif c == "show" and len(a) >= 2:
                    cur.add("sprite", name=a[0], img=assets.find(a[1]) or a[1], pos=a[2] if len(a) > 2 else "center")
                elif c == "hide" and a:
                    cur.add("sprite", name=a[0], img=None)
                elif c == "clear":
                    cur.add("sprites_clear")
                elif c == "bgm":
                    cur.add("bgm", name=None if not a or a[0].lower() == "none" else a[0])
                elif c == "event" and a:
                    cur.add("event", name=a[0], arg=" ".join(a[1:]) or None)
                elif c == "end":
                    kind = a[0] if a and a[0] in ("ending", "title", "stop") else "ending"
                    cur.add("end", kind=kind, name=" ".join(a[1:]) or None)
                else:
                    warnings.append("%s: 不认识的指令 @%s" % (where, c))
            elif line.startswith("$"):
                cur.add("set", expr=line[1:].strip())
                stats["sets"] += 1
            elif line.startswith("?") or line.startswith("- ") or line == "-":
                if pend is None:
                    pend = cur.add("choice", id="c%d" % len(cur.ops), prompt=line[1:].strip() if line.startswith("?") else "",
                                   options=[])
                    stats["choices"] += 1
                if line.startswith("-"):
                    m = OPT.match(line)
                    if not m:
                        warnings.append("%s: 选项要写成「- 文字 -> 目标」" % where)
                        continue
                    o = {"text": m.group(1), "goto": _target(m.group(2), cur.id)}
                    if m.group(3):
                        o["if"] = m.group(3)
                    if m.group(4):
                        o["set"] = m.group(4)
                    pend["options"].append(o)
                    stats["options"] += 1
            elif line.startswith("->"):
                m = JMP.match(line)
                if not m:
                    warnings.append("%s: 跳转要写成「-> 目标」" % where)
                    continue
                g = _target(m.group(1), cur.id)
                cur.add("jump", scene=g["scene"], label=g["label"], **({"if": m.group(2)} if m.group(2) else {}))
                stats["jumps"] += 1
            elif line.startswith("if ") and "->" in line:
                cond, _, tg = line[3:].rpartition("->")
                g = _target(tg.strip(), cur.id)
                cur.add("jump", scene=g["scene"], label=g["label"], **{"if": cond.strip()})
                stats["jumps"] += 1
            elif line.startswith("call "):
                g = _target(line[5:].strip(), cur.id)
                cur.add("call", scene=g["scene"], label=g["label"])
                stats["calls"] += 1
            elif line == "return":
                cur.add("ret")
            else:
                m = SAY.match(line) or SAY_Q.match(line)
                if m:
                    cur.add("say", who=m.group(1), text=m.group(2).strip())
                else:
                    cur.add("say", who="", text=line)
                stats["says"] += 1
    # 场景之间默认按顺序接上（没写结尾的场景走到下一个）
    for a, b in zip(order, order[1:]):
        ops = scenes[a].ops
        if not ops or ops[-1]["op"] not in ("jump", "end", "ret"):
            scenes[a].add("jump", scene=b, label=None)
    last = scenes[order[-1]].ops
    if not last or last[-1]["op"] not in ("jump", "end", "ret"):
        scenes[order[-1]].add("end", kind="title", how="走到最后")
    # 目标解析：先找本场景的标签，再找同名场景，再找全局唯一的标签；都没有就原样留给校验报错
    labels = {sid: {op["name"] for op in b.ops if op["op"] == "label"} for sid, b in scenes.items()}

    def resolve(g, sid):
        if g.get("scene") is None and g.get("label") is not None and g["label"] not in labels[sid]:
            lb = g["label"]
            if lb in scenes:
                g["scene"], g["label"] = lb, None
            else:
                owners = [s2 for s2, ls in labels.items() if lb in ls]
                if len(owners) == 1:
                    g["scene"] = owners[0]
    for sid, b in scenes.items():
        for op in b.ops:
            if op["op"] == "choice":
                for o in op["options"]:
                    resolve(o["goto"], sid)
                    o["goto"]["scene"] = o["goto"]["scene"] or sid
                    if o["goto"].get("label") is None:
                        o["goto"].pop("label")
            elif op["op"] in ("jump", "call") and "scene" not in op:
                g = {"scene": None, "label": op.get("label")}
                resolve(g, sid)
                if g["scene"]:
                    op["scene"] = g["scene"]
                    if g["label"] is None:
                        op.pop("label", None)
    routes, seen_r = [], set()
    for sid in order:
        r = scenes[sid].route
        if r and r not in seen_r:
            seen_r.add(r)
            routes.append({"id": r, "title": r, "start": {"scene": sid, "label": None}})
    data = {k: v.data() for k, v in scenes.items()}
    meta = {"format": "galplay/1", "title": meta_kv.get("title", ""), "engine": "galscript", "importer": "galplay-galscript-1",
            "entry": {"scene": order[0], "label": None},
            "scenes": {k: {"title": v["title"], "tags": v["tags"], "route": v["route"]} for k, v in data.items()},
            "routes": routes, "system_vars": sorted(sysv),
            "stats": dict(stats, unknown=[], assets=assets.report()), "warnings": warnings[:200]}
    for k in ("author", "license", "lang"):
        if k in meta_kv:
            meta[k] = meta_kv[k]
    return meta, data
