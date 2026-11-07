"""QLIE（.s 剧本）→ galbook/1。

在一部商业 QLIE 作品上逐条核对过的「AVGシステム」标准模板写法（同模板的作品很多）：
  台词   voice,名字＠别名,「台词」     （voice=none 表示无语音；名字＠后是真名，显示用＠前）
  旁白   不以 \\ ^ @ // 开头的行
  画面   ^bg0,名  ^mbg0,效果,名  ^chara,名字,表情,姿势,距离,位置,服装  ^clear  ^music
  选项   ^select,N,,选项1,选项2…  ^selectpre,编号  ^selectjmp
         → 跳到 select.s 的 @@<本文件名>_sel<编号>_<0起序号>，那里再 \\jmp 到 Route.s 同名标签
  流程   \\jmp,@@标签[,"文件"]  \\go 同 jmp  \\sub,@@标签,"文件"（调用）
         文件末尾 \\sub,@@!FilejumpName,self,SelfFileName + \\jmp,ResultStr[0],"シナリオ\\Route.s"
         = 跳到 Route.s 的 @@<本文件名>_end，再顺着往下走到下一个场景
  变量   \\cal,#X=1（# 开头是系统变量 = 跨周目，记到 s.X）  \\if,条件\\then … \\else … \\end
  开局   スクリプト\\RouteSelect\\main.s：常见写法是若干 #XXClearflag 都为 1 才出现隐藏线入口（条件照原文翻译，不写死）
认不出的指令不猜：计数后写进 stats.unknown，选项/跳转认不出写进 warnings。
"""
import os
import re

from .common import SceneB, Assets, read_text, is_h_title

INTERNAL = re.compile(r"^(Result\w*|Param\w*|Self\w*|_\w*)$")
IDENT = re.compile(r"(#?)\b([A-Za-z_][A-Za-z0-9_]*)\b(?!\s*\()")
IGNORED_CARET = {"se", "se0", "se1", "se2", "effect", "voicedir", "layoutchange", "d", "enchara", "mchara", "achara",
                 "evbgdef", "action", "action0", "action1", "caction0", "delaychara", "alphachara", "savetext", "date",
                 "bg1", "bg2", "bg3", "mbg1", "mbg2", "mbg3", "music1", "voice", "wait", "quake", "flash"}
IGNORED_BS = {"clk", "scp", "wait", "ret_", "l", "p", "a", "e", "var", "gvar", "svar", "del", "zero", "d", "us",
              "ui", "o", "play", "m", "v", "i", "ts", "tab", "sp", "vtn", "srct", "thrd", "stop", "lk", "mv", "ck",
              "dc", "t", "ans", "fexs", "vexs", "ddlg", "div", "fmt", "pos", "li", "ps", "vt", "vtv", "cc", "brk",
              "for", "next", "case", "default", "endswitch", "switch"}


def _split_args(s):
    out, cur, q = [], [], False
    for ch in s:
        if ch == '"':
            q = not q
            cur.append(ch)
        elif ch == "," and not q:
            out.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    out.append("".join(cur))
    return [x.strip() for x in out]


def _unq(s):
    s = (s or "").strip()
    return s[1:-1] if len(s) >= 2 and s[0] == s[-1] == '"' else s


def _file_stem(ref):
    """'シナリオ\\Route.s' → 'route'（小写，不带扩展名）"""
    ref = _unq(ref).replace("/", "\\")
    base = ref.rsplit("\\", 1)[-1]
    return os.path.splitext(base)[0].lower()


def translate_cond(c):
    """QLIE 条件 → galbook 表达式；含引擎内部变量（ResultStr 等）返回 None。"""
    c = c.strip()
    bad = []

    def rep(m):
        sharp, name = m.group(1), m.group(2)
        if name in ("and", "or", "not", "true", "false"):
            return m.group(0)
        if INTERNAL.match(name):
            bad.append(name)
            return name
        return ("s." if sharp else "f.") + name
    out = IDENT.sub(rep, c)
    out = re.sub(r"(?<![=!<>])=(?!=)", "==", out) if "==" not in out and "!=" not in out and "<=" not in out and ">=" not in out and "=" in out else out
    out = out.replace("&", " && ").replace("|", " || ").replace("&& &&", "&&").replace("|| ||", "||")
    out = re.sub(r"&&\s*&&", "&&", out)
    out = re.sub(r"\|\|\s*\|\|", "||", out)
    return None if bad else out


def translate_assign(c):
    m = re.match(r"^\s*(#?)([A-Za-z_]\w*)\s*(\+\+|--|\+=|-=|=)\s*(.*)$", c)
    if not m:
        return None
    sharp, name, op, rhs = m.groups()
    if INTERNAL.match(name):
        return None
    tgt = ("s." if sharp else "f.") + name
    if op == "++":
        return tgt + " += 1"
    if op == "--":
        return tgt + " -= 1"
    r = translate_cond(rhs) if rhs else None
    if r is None:
        return None
    return "%s %s %s" % (tgt, op, r)


class _FileCtx(object):
    def __init__(self, imp, path, sid):
        self.imp, self.path, self.sid = imp, path, sid
        self.title = sid
        self.b = SceneB(sid, sid, tags=["h"] if is_h_title(sid) else [], route=imp.route_of(sid))
        self.chara = {}
        self.sel_opts = None
        self.sel_no = None
        self.filejump = False
        self.ifs = []
        self.nif = 0
        self.cur_label = None
        self.last_scn_label = None


class Importer(object):
    def __init__(self, src, assets=None):
        self.src = src
        self.assets = assets or Assets()
        self.files = {}          # stem(lower) -> path
        self.sid_of = {}         # stem(lower) -> scene id（原文件名）
        self.scenes = {}
        self.warnings = []
        self.unknown = {}
        self.ignored = 0
        self.stats = {"files": 0, "says": 0, "dialogue": 0, "narration": 0, "choices": 0, "options": 0,
                      "jumps": 0, "calls": 0, "sets": 0, "ifs": 0, "untranslated_if": 0}
        self.title_labels = set()
        self.system_vars = set()
        self.scn_dir = None
        self.lib_dir = None

    # ---------- 找文件 ----------
    def scan(self):
        for dp, dn, fns in os.walk(self.src):
            for fn in fns:
                if fn.lower().endswith(".s"):
                    full = os.path.join(dp, fn)
                    if os.path.basename(dp).lower() in ("シナリオ", "scenario", "scn"):
                        stem = os.path.splitext(fn)[0]
                        self.files[stem.lower()] = full
                        self.sid_of[stem.lower()] = stem
                        self.scn_dir = dp
        if not self.files:
            raise ValueError("在 %s 下没找到 シナリオ/*.s" % self.src)

    def find_script(self, *parts):
        want = [p.lower() for p in parts]
        for dp, dn, fns in os.walk(self.src):
            for fn in fns:
                full = os.path.join(dp, fn)
                low = full.lower().replace("\\", "/")
                if all(w in low for w in want):
                    return full
        return None

    def route_of(self, sid):
        m = re.match(r"^(.+?ルート)", sid)
        if m:
            return m.group(1)
        return "" if sid.lower() not in ("route", "select") else "system"

    # ---------- 主流程 ----------
    def build(self):
        self.scan()
        rp = self.files.get("route")
        if rp:
            self._prescan_title_labels(rp)
        for stem in sorted(self.files):
            self._parse_file(stem)
        entry = self._build_start()
        routes = self._routes()
        meta = {"format": "galbook/1", "title": "", "engine": "qlie", "importer": "galbook-qlie-1",
                "entry": entry, "scenes": {sid: {"title": d["title"], "tags": d["tags"], "route": d["route"]}
                                           for sid, d in self.scenes.items()},
                "routes": routes, "system_vars": sorted(self.system_vars),
                "stats": dict(self.stats, ignored_cmds=self.ignored,
                              unknown=sorted(self.unknown.items(), key=lambda x: -x[1])[:20],
                              assets=self.assets.report()),
                "warnings": self.warnings[:200]}
        return meta, self.scenes

    def _prescan_title_labels(self, path):
        lines = [ln.strip() for ln in read_text(path).splitlines()]
        for i, ln in enumerate(lines):
            if ln.startswith("@@") and not ln.startswith("@@@"):
                nxt = [x for x in lines[i + 1:i + 4] if x and not x.startswith("//")]
                if nxt and re.match(r"^\\scp,sys\s+\\r\b", nxt[0]):
                    self.title_labels.add(ln[2:])

    def _parse_file(self, stem):
        path = self.files[stem]
        sid = self.sid_of[stem]
        cx = _FileCtx(self, path, sid)
        self.stats["files"] += 1
        text = read_text(path)
        for raw in text.splitlines():
            s = raw.strip()
            if not s or s.startswith("//") or s.startswith(";"):
                continue
            if s.startswith("@@@"):
                continue
            if s.startswith("@@"):
                name = s[2:].split()[0]
                cx.b.add("label", name=name)
                cx.cur_label = name
                if stem == "route" and not name.endswith("_end") and self.sid_of.get(name.lower()):
                    cx.last_scn_label = name
                continue
            if s.startswith("^"):
                self._caret(cx, s)
                continue
            if s.startswith("\\"):
                for part in re.split(r"\t+(?=\\)", s):
                    self._bs(cx, part.strip())
                continue
            self._text(cx, s)
        if cx.ifs:
            self.warnings.append("%s: 有 %d 个 \\if 没闭合" % (sid, len(cx.ifs)))
            for lb in cx.ifs:
                cx.b.add("label", name=lb["end"])
        self.scenes[sid] = cx.b.data()

    # ---------- 台词 / 旁白 ----------
    def _text(self, cx, s):
        parts = s.split(",", 2)
        if len(parts) == 3 and (parts[2][:1] in "「『（(" or parts[0] == "none" or re.match(r"^[A-Za-z]{1,6}H?_?\d+", parts[0])):
            voice, who, txt = parts
            who = who.split("＠")[0].strip()
            cx.b.add("say", who=who, text=txt.strip(), voice=None if voice == "none" else voice)
            self.stats["dialogue"] += 1
        else:
            cx.b.add("say", who="", text=s)
            self.stats["narration"] += 1
        self.stats["says"] += 1

    # ---------- ^ 指令 ----------
    def _caret(self, cx, s):
        head, _, rest = s[1:].partition(",")
        cmd = head.strip().lower()
        a = _split_args(rest) if rest else []
        if cmd in ("bg0", "bg"):
            self._bg(cx, a[0] if a else "")
        elif cmd == "mbg0":
            if len(a) >= 2 and a[1]:
                self._bg(cx, a[1])
        elif cmd == "chara":
            self._chara(cx, a)
        elif cmd == "clear":
            tgt = (a[0] if a else "").lower()
            if tgt in ("", "chara", "all"):
                cx.b.add("sprites_clear")
                cx.chara = {k: dict(v, shown=False) for k, v in cx.chara.items()}
            if tgt in ("all", "画像"):
                cx.b.add("cg", img=None)
        elif cmd == "music":
            cx.b.add("bgm", name=a[0] if a else None)
        elif cmd == "music0":
            cx.b.add("bgm", name=None)
        elif cmd == "select":
            cx.sel_opts = [x for x in a[2:] if x != ""]
        elif cmd == "selectpre":
            cx.sel_no = a[0] if a else "0"
        elif cmd == "selectjmp":
            self._selectjmp(cx)
        elif cmd in ("branchpre", "branchjmp", "routejmp"):
            self.warnings.append("%s: ^%s 这类按 flag 自动分支的写法还没接（本作没用到）" % (cx.sid, cmd))
        elif cmd in IGNORED_CARET:
            self.ignored += 1
        else:
            self.unknown["^" + cmd] = self.unknown.get("^" + cmd, 0) + 1

    def _bg(self, cx, name):
        name = _unq(name)
        if not name or name.lower() in ("bg_bl", "bg_wh", "黒", "白", "black", "white"):
            cx.b.add("bg", img=None)
            return
        img = self.assets.find(name)
        if img and not os.path.basename(img).lower().startswith("bg"):
            cx.b.add("cg", img=img)      # 事件 CG（KH01 / HN04 / SZ05e …）
        else:
            cx.b.add("bg", img=img)

    def _chara(self, cx, a):
        if not a or not a[0]:
            cx.b.add("sprites_clear")
            cx.chara = {}
            return
        name = a[0]
        if len(a) == 1:
            cx.b.add("sprite", name=name, img=None)
            cx.chara.pop(name, None)
            return
        st = cx.chara.setdefault(name, {"feel": "01", "pose": "01", "dist": "中", "pos": "center", "clothes": "01"})
        for k, i in (("feel", 1), ("pose", 2), ("dist", 3), ("pos", 4), ("clothes", 5)):
            if len(a) > i and a[i] and not a[i].startswith('"'):
                st[k] = a[i]
        stem = "立ち絵/%s/%s_%s_%s_%s_%s" % (st["dist"], name, st["dist"], st["clothes"], st["pose"], st["feel"])
        img = self.assets.find(stem)
        cx.b.add("sprite", name=name, img=img or None, pos=st["pos"])

    def _selectjmp(self, cx):
        opts = cx.sel_opts or []
        if not opts:
            self.warnings.append("%s: ^selectjmp 前没有 ^select" % cx.sid)
            return
        no = cx.sel_no if cx.sel_no is not None else "0"
        sel_sid = self.sid_of.get("select")
        options = []
        for i, t in enumerate(opts):
            lb = "%s_sel%s_%d" % (cx.sid, no, i)
            tgt = sel_sid if sel_sid and self._has_label(sel_sid, lb) else self.sid_of.get("route")
            options.append({"text": t, "goto": {"scene": tgt, "label": lb}})
        cx.b.add("choice", id="%s_sel%s" % (cx.sid, no), options=options)
        self.stats["choices"] += 1
        self.stats["options"] += len(options)
        cx.sel_opts, cx.sel_no = None, None

    def _has_label(self, sid, lb):
        path = self.files.get(sid.lower())
        if not path:
            return False
        return ("@@" + lb) in read_text(path)

    # ---------- \ 指令 ----------
    def _bs(self, cx, s):
        m = re.match(r"^\\([A-Za-z?]+)(?:,(.*))?$", s)
        if not m:
            self.unknown[s[:12]] = self.unknown.get(s[:12], 0) + 1
            return
        cmd, rest = m.group(1).lower(), m.group(2) or ""
        if cmd.startswith("if"):
            return self._if(cx, s)
        if cmd == "else":
            if not cx.ifs:
                self.warnings.append("%s: 多余的 \\else" % cx.sid)
                return
            top = cx.ifs[-1]
            cx.b.add("jump", label=top["end"])
            cx.b.add("label", name=top["else"])
            top["has_else"] = True
            return
        if cmd == "end":
            if not cx.ifs:
                return
            top = cx.ifs.pop()
            if not top.get("has_else"):
                cx.b.add("label", name=top["else"])
            cx.b.add("label", name=top["end"])
            return
        a = _split_args(rest) if rest else []
        if cmd in ("jmp", "go", "g"):
            return self._jmp(cx, a, call=False)
        if cmd == "sub":
            if a and a[0] == "@@!FilejumpName":
                cx.filejump = True
                return
            if a and a[0] == "@@!EyeCatch":
                arg = "・".join(x for x in a[2:] if x)
                cx.b.add("event", name="eyecatch", arg=arg or None)
                return
            if a and a[0] == "@@!MovieExcute":
                cx.b.add("event", name="movie", arg=a[2] if len(a) > 2 else None)
                return
            if len(a) >= 2 and "endroll" in a[1].lower():
                cx.b.add("event", name="endroll", arg=_unq(a[2]) if len(a) > 2 else None)
                return
            if len(a) >= 2 and _file_stem(a[1]) in self.files:
                return self._jmp(cx, a, call=True)
            self.ignored += 1
            return
        if cmd == "ret":
            cx.b.add("ret")
            return
        if cmd == "cal":
            expr = translate_assign(rest)
            if expr:
                cx.b.add("set", expr=expr)
                self.stats["sets"] += 1
                if expr.startswith("s."):
                    self.system_vars.add(expr[2:].split()[0])
                    if "clear" in expr.lower():
                        cx.b.add("event", name="clear", arg=expr[2:].split()[0])
            else:
                self.ignored += 1
            return
        if cx.sid.lower() == "route" and cmd in ("scp", "r"):
            return
        if cmd in IGNORED_BS or cmd.startswith("?"):
            self.ignored += 1
            return
        self.unknown["\\" + cmd] = self.unknown.get("\\" + cmd, 0) + 1

    def _if(self, cx, s):
        m = re.match(r"^\\if,(.*?)\\then\s*$", s)
        cond = m.group(1) if m else s[4:]
        self.stats["ifs"] += 1
        cx.nif += 1
        lb = {"else": "__if%d_else" % cx.nif, "end": "__if%d_end" % cx.nif}
        cx.ifs.append(lb)
        g = translate_cond(cond)
        if g is None:
            self.stats["untranslated_if"] += 1
            cx.b.add("jump", label=lb["else"])          # 看不懂的条件（引擎内部状态）一律当不成立
        else:
            cx.b.add("jump", label=lb["else"], **{"if": "!(%s)" % g})

    def _jmp(self, cx, a, call=False):
        if not a:
            return
        tgt = a[0]
        fstem = _file_stem(a[1]) if len(a) > 1 and a[1] not in ("self", "") else None
        sid = self.sid_of.get(fstem) if fstem else cx.sid
        if fstem and not sid:
            self.warnings.append("%s: 跳到未知文件 %s" % (cx.sid, a[1]))
            return
        if tgt.startswith("@@") and re.match(r"^@@[^+\s]+$", tgt):
            label = tgt[2:]
            if label.upper() == "TOP" and sid != cx.sid and not self._has_label(sid, label):
                label = None          # @@TOP = 文件开头
            if sid == cx.sid and label in self.title_labels:
                name = (cx.last_scn_label or "").replace("_end", "")
                cx.b.add("end", kind="ending", name=self.route_of(name) or name or "通关")
                return
            cx.b.add("call" if call else "jump", scene=None if sid == cx.sid else sid, label=label)
            self.stats["calls" if call else "jumps"] += 1
            return
        if tgt == "ResultStr[0]" and cx.filejump:
            if not self._has_label(sid, "%s_end" % cx.sid):
                # 例：demo.s（标题画面的自动演示）在 Route.s 里没有 _end 标签 → 回标题
                cx.b.add("end", kind="title", name="%s 结束（Route.s 里没有 %s_end）" % (cx.sid, cx.sid))
                return
            cx.b.add("jump", scene=sid, label="%s_end" % cx.sid)
            self.stats["jumps"] += 1
            return
        if tgt.replace(" ", "") == '_SelectLabel+"_"+ResultBtnInt' and cx.cur_label:
            cx.b.add("jump", scene=sid, label=cx.cur_label)
            self.stats["jumps"] += 1
            return
        self.warnings.append("%s: 看不懂的跳转目标 %s（标签 %s 之后）" % (cx.sid, tgt, cx.cur_label))

    # ---------- 开局 / 路线 ----------
    def _build_start(self):
        route_sid = self.sid_of.get("route")
        b = SceneB("__start__", "开始", tags=["system"], route="system")
        b.add("label", name="top")
        rs = self.find_script("routeselect", "main.s")
        targets, lock = [], None
        if rs and route_sid:
            t = read_text(rs)
            for m in re.finditer(r'\\go,@@(\w+),"([^"]+)"', t):
                if _file_stem(m.group(2)) == "route":
                    targets.append(m.group(1))
            m = re.search(r"\\if,([^\n]*?)\\then\s*\n(?:[^\n]*\n){0,4}?[^\n]*ResultStr\[0\]=\"Normal\"", t)
            if m:
                lock = translate_cond(m.group(1))
        if route_sid and targets:
            opts = []
            for lb in dict.fromkeys(targets):
                if lb.lower().endswith("normal"):
                    opts.insert(0, {"text": "从头开始（共通线）", "goto": {"scene": route_sid, "label": lb}})
                else:
                    nm = self._first_route_after(lb) or lb.split("_", 1)[-1]
                    o = {"text": "%s（通关其它线后解锁）" % nm, "goto": {"scene": route_sid, "label": lb}}
                    if lock:
                        o["if"] = "!(%s)" % lock
                    opts.append(o)
            b.add("choice", id="routeselect", prompt="选择开始的路线", options=opts, auto_single=True)
            self.stats["choices"] += 1      # 开局路线选择也是脚本（routeselect.s）里来的选择点，计数要对上 build 的校验
        elif route_sid:
            b.add("jump", scene=route_sid, label=None)
        else:
            first = sorted(self.sid_of.values())[0]
            b.add("jump", scene=first)
            self.warnings.append("没有 route.s，入口取了按名字排第一的剧本 %s" % first)
        self.scenes["__start__"] = b.data()
        return {"scene": "__start__", "label": "top"}

    def _first_route_after(self, label):
        ops = self.scenes.get(self.sid_of.get("route"), {}).get("ops", [])
        hit = False
        for op in ops:
            if op.get("op") == "label" and op.get("name") == label:
                hit = True
            elif hit and op.get("op") == "label" and self.route_of(op.get("name", "")) not in ("", "system"):
                return self.route_of(op["name"])
        return None

    def _routes(self):
        out, seen = [], set()
        for sid in self.scenes:
            r = self.route_of(sid)
            if r and r != "system" and r not in seen:
                seen.add(r)
                out.append({"id": r, "title": r})
        return out


def build(src, assets=None, **_):
    imp = Importer(src, assets)
    return imp.build()
