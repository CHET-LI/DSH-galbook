"""Ren'Py（.rpy 源码）→ galplay/1。新游戏最常见的引擎之一；只吃 .rpy 源码（.rpyc 先用 unrpyc 反编译）。

认的写法：
  define e = Character("名字", …)          说话人
  image eileen happy = "eileen_happy.png"  图片名 → 文件
  default x = 0 / define persistent…       初始变量（persistent.* = 系统变量 → s.*）
  label name:                              标签（全局，跨文件）
  "旁白" / e "台词" / e happy "台词" / "名字" "台词"
  menu: / menu name:  （可选一句提问）+ "选项" [if 条件]: 块
  jump x / call x / return / pass
  $ x = 1 / $ persistent.y = True
  if 条件: / elif 条件: / else:
  scene bg room / show eileen happy [at left] / hide eileen / play music "x"
其它块（python:/init:/screen/transform/style/ATL）整块跳过。
"""
import os
import re

from .common import SceneB, Assets, read_text, is_h_title

STR = r'"(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\''
SAY = re.compile(r"^(?:(%s)|([A-Za-z_]\w*)(?:\s+[A-Za-z_][\w\s]*?)?)\s+(%s)(?:\s+with\s+\w+)?\s*$" % (STR, STR))
NARR = re.compile(r"^(%s)(?:\s+with\s+\w+)?\s*$" % STR)
SKIP_BLOCK = re.compile(r"^(init\b.*|python\b.*|screen\b.*|transform\b.*|style\b.*|translate\b.*|image\s+[^=]+:\s*$|"
                        r"layeredimage\b.*|testcase\b.*)$")


def _unq(s):
    s = s.strip()
    if len(s) >= 2 and s[0] in "\"'" and s[-1] == s[0]:
        s = s[1:-1]
    return s.replace('\\"', '"').replace("\\'", "'").replace("\\n", "\n")


def conv_expr(e):
    e = e.strip()
    parts = re.split(r"(%s)" % STR, e)
    out = []
    for i, p in enumerate(parts):
        if i % 2:
            out.append(p)
            continue
        p = re.sub(r"\bpersistent\.(\w+)", r"s.\1", p)
        p = re.sub(r"\bTrue\b", "true", p)
        p = re.sub(r"\bFalse\b", "false", p)
        p = re.sub(r"\bNone\b", "0", p)

        def rep(m):
            w = m.group(0)
            if w in ("and", "or", "not", "true", "false", "s", "f"):
                return w
            return "f." + w
        p = re.sub(r"(?<![\w.])(?!s\.)([A-Za-z_]\w*)(?![\w(])", rep, p)
        p = p.replace("f.s.", "s.")
        out.append(p)
    return "".join(out)


class _Line(object):
    __slots__ = ("ind", "text", "no")

    def __init__(self, ind, text, no):
        self.ind, self.text, self.no = ind, text, no


def _lines(src):
    out = []
    for no, raw in enumerate(src.splitlines(), 1):
        if not raw.strip():
            continue
        # 去掉行尾注释（不在字符串里的 #）
        s, q, buf = raw.rstrip(), None, []
        for ch in s:
            if q:
                buf.append(ch)
                if ch == q:
                    q = None
            elif ch in "\"'":
                q = ch
                buf.append(ch)
            elif ch == "#":
                break
            else:
                buf.append(ch)
        t = "".join(buf).rstrip()
        if not t.strip():
            continue
        ind = len(t) - len(t.lstrip(" \t").replace("\t", "    ")) if "\t" in t else len(t) - len(t.lstrip())
        out.append(_Line(ind, t.strip(), no))
    return out


class Importer(object):
    def __init__(self, src, assets=None, entry="start"):
        self.src, self.assets, self.entry = src, assets or Assets(), entry
        self.chars, self.images, self.defaults = {}, {}, []
        self.label_scene = {}
        self.scenes = {}
        self.warnings = []
        self.unknown = {}
        self.stats = {"files": 0, "says": 0, "choices": 0, "options": 0, "jumps": 0, "calls": 0, "sets": 0, "ifs": 0}
        self.system_vars = set()
        self.n = 0

    def build(self):
        files = []
        for dp, _, fns in os.walk(self.src):
            for fn in sorted(fns):
                if fn.endswith(".rpy"):
                    files.append(os.path.join(dp, fn))
        if not files:
            raise ValueError("没找到 .rpy")
        parsed = [(os.path.splitext(os.path.relpath(p, self.src))[0].replace(os.sep, "/"), _lines(read_text(p))) for p in files]
        for sid, ls in parsed:          # 第一遍：角色、图片、默认值、标签归属
            for ln in ls:
                if ln.ind == 0:
                    self._decl(ln.text, sid)
        for sid, ls in parsed:
            self.stats["files"] += 1
            b = SceneB(sid, sid, tags=["h"] if is_h_title(sid) else [])
            self._block(b, ls, 0, len(ls), top=True)
            b.add("end", kind="title", name="%s 走到文件末尾（Ren'Py 回到主菜单）" % sid)
            self.scenes[sid] = b.data()
        if self.entry not in self.label_scene:
            raise ValueError("没有入口标签 label %s" % self.entry)
        st = SceneB("__start__", "开始", tags=["system"])
        st.add("label", name="top")
        for name, val in self.defaults:
            st.add("set", expr="%s = %s" % (name, val))
        st.add("jump", scene=self.label_scene[self.entry], label=self.entry)
        self.scenes["__start__"] = st.data()
        meta = {"format": "galplay/1", "title": "", "engine": "renpy", "importer": "galplay-renpy-1",
                "entry": {"scene": "__start__", "label": "top"},
                "scenes": {k: {"title": v["title"], "tags": v["tags"]} for k, v in self.scenes.items()},
                "routes": [], "system_vars": sorted(self.system_vars),
                "stats": dict(self.stats, unknown=sorted(self.unknown.items(), key=lambda x: -x[1])[:20],
                              assets=self.assets.report()),
                "warnings": self.warnings[:200]}
        return meta, self.scenes

    def _decl(self, t, sid):
        m = re.match(r"^define\s+([A-Za-z_]\w*)\s*=\s*(?:Character|DynamicCharacter)\s*\(\s*(?:_\()?\s*(%s|None)" % STR, t)
        if m:
            self.chars[m.group(1)] = "" if m.group(2) == "None" else _unq(m.group(2))
            return
        m = re.match(r"^image\s+([^=]+?)\s*=\s*(%s)" % STR, t)
        if m:
            self.images[m.group(1).strip()] = _unq(m.group(2))
            return
        m = re.match(r"^(?:default|define)\s+(persistent\.)?([A-Za-z_]\w*)\s*=\s*(.+)$", t)
        if m and "Character" not in t:
            scope = "s." if m.group(1) else "f."
            try:
                val = conv_expr(m.group(3))
                if scope == "s.":
                    self.system_vars.add(m.group(2))
                    val = "%s%s == 0 && %s || %s%s" % (scope, m.group(2), val, scope, m.group(2)) if False else val
                if scope == "f.":
                    self.defaults.append((scope + m.group(2), val))
            except Exception:  # noqa
                pass
            return
        m = re.match(r"^label\s+([A-Za-z_][\w.]*)\s*(\(.*\))?\s*:", t)
        if m:
            self.label_scene.setdefault(m.group(1), sid)

    def _img(self, name):
        name = name.strip()
        f = self.images.get(name)
        if f:
            return self.assets.find(f) or f
        return self.assets.find(name.replace(" ", "_")) or self.assets.find(name) or ("image:" + name)

    def _end_of(self, ls, i, j):
        ind = ls[i].ind
        k = i + 1
        while k < j and ls[k].ind > ind:
            k += 1
        return k

    def _lab(self, kind):
        self.n += 1
        return "__%s%d" % (kind, self.n)

    def _block(self, b, ls, i, j, top=False):
        while i < j:
            ln = ls[i]
            t = ln.text
            end = self._end_of(ls, i, j)
            if top and ln.ind == 0 and not t.startswith("label "):
                i = end
                continue
            m = re.match(r"^label\s+([A-Za-z_][\w.]*)", t)
            if m:
                b.add("label", name=m.group(1))
                self._block(b, ls, i + 1, end)
                i = end
                continue
            if SKIP_BLOCK.match(t) or t.startswith("python:") or t.startswith("$ python"):
                i = end
                continue
            if re.match(r"^menu(\s+[A-Za-z_]\w*)?\s*:", t):
                self._menu(b, ls, i, end)
                i = end
                continue
            m = re.match(r"^(if|elif|else)\b\s*(.*?)\s*:$", t)
            if m and m.group(1) == "if":
                k = i
                done = self._lab("ifend")
                while k < j:
                    mm = re.match(r"^(if|elif|else)\b\s*(.*?)\s*:$", ls[k].text)
                    if not mm or ls[k].ind != ln.ind or (k != i and mm.group(1) == "if"):
                        break
                    e2 = self._end_of(ls, k, j)
                    nxt = self._lab("ifnext")
                    if mm.group(1) != "else":
                        b.add("jump", label=nxt, **{"if": "!(%s)" % conv_expr(mm.group(2))})
                        self.stats["ifs"] += 1
                    self._block(b, ls, k + 1, e2)
                    b.add("jump", label=done)
                    b.add("label", name=nxt)
                    k = e2
                b.add("label", name=done)
                i = k
                continue
            self._stmt(b, t)
            i = end if end > i + 1 and t.endswith(":") else i + 1

    def _menu(self, b, ls, i, end):
        prompt = ""
        opts = []
        done = self._lab("menuend")
        k = i + 1
        bodies = []
        while k < end:
            t = ls[k].text
            e2 = self._end_of(ls, k, end)
            m = re.match(r"^(%s)\s*(?:if\s+(.+?))?\s*:$" % STR, t)
            if m:
                lb = self._lab("opt")
                o = {"text": _unq(m.group(1)), "goto": {"label": lb}}
                if m.group(2):
                    o["if"] = conv_expr(m.group(2))
                opts.append(o)
                bodies.append((lb, k + 1, e2))
            elif SAY.match(t) or NARR.match(t):
                self._stmt(b, t)          # 菜单的提问句照常显示
                prompt = _unq((SAY.match(t) or NARR.match(t)).group(3 if SAY.match(t) else 1))
            elif t.startswith("set "):
                pass
            else:
                self.unknown["menu:" + t.split()[0]] = self.unknown.get("menu:" + t.split()[0], 0) + 1
            k = e2
        b.add("choice", id=self._lab("menu"), prompt=prompt, options=opts)
        self.stats["choices"] += 1
        self.stats["options"] += len(opts)
        for lb, s, e in bodies:
            b.add("label", name=lb)
            self._block(b, ls, s, e)
            b.add("jump", label=done)
        b.add("label", name=done)

    def _stmt(self, b, t):
        m = NARR.match(t)
        if m:
            b.add("say", who="", text=_unq(m.group(1)))
            self.stats["says"] += 1
            return
        m = SAY.match(t)
        if m and (m.group(1) or m.group(2) in self.chars or m.group(2) not in
                  ("scene", "show", "hide", "play", "stop", "queue", "voice", "jump", "call", "return", "with", "window", "pause", "nvl")):
            who = _unq(m.group(1)) if m.group(1) else self.chars.get(m.group(2), m.group(2))
            b.add("say", who=who, text=_unq(m.group(3)))
            self.stats["says"] += 1
            return
        w = t.split()
        k = w[0] if w else ""
        if k == "jump":
            if w[1] == "expression":
                self.warnings.append("jump expression 动态跳转没法静态解析：%s" % t)
                return
            sc = self.label_scene.get(w[1])
            if sc is None:
                self.warnings.append("跳到不存在的标签 %s" % w[1])
                return
            b.add("jump", scene=None if sc == b.id else sc, label=w[1])
            self.stats["jumps"] += 1
        elif k == "call":
            if len(w) > 1 and w[1] != "screen" and w[1] in self.label_scene:
                sc = self.label_scene[w[1]]
                b.add("call", scene=None if sc == b.id else sc, label=w[1])
                self.stats["calls"] += 1
        elif k == "return":
            b.add("ret")
            b.add("end", kind="title", how="return（回到主菜单）")
        elif k == "$":
            e = t[1:].strip()
            m2 = re.match(r"^(persistent\.)?([A-Za-z_]\w*)\s*(\+=|-=|=)\s*(.+)$", e)
            if m2:
                scope = "s." if m2.group(1) else "f."
                if scope == "s.":
                    self.system_vars.add(m2.group(2))
                b.add("set", expr="%s%s %s %s" % (scope, m2.group(2), m2.group(3), conv_expr(m2.group(4))))
                self.stats["sets"] += 1
            else:
                self.unknown["$"] = self.unknown.get("$", 0) + 1
        elif k == "scene":
            nm = re.sub(r"\s+(with|at|onlayer|behind|as)\b.*$", "", t[5:].strip())
            b.add("sprites_clear")
            b.add("bg", img=self._img(nm) if nm else None)
        elif k == "show":
            nm = re.sub(r"\s+(with|at|onlayer|behind|zorder|as)\b.*$", "", t[4:].strip())
            pos = re.search(r"\bat\s+(\w+)", t)
            if nm.startswith("bg "):
                b.add("bg", img=self._img(nm))
            elif nm and not nm.startswith("screen"):
                b.add("sprite", name=nm.split()[0], img=self._img(nm), pos=pos.group(1) if pos else "center")
        elif k == "hide":
            if len(w) > 1:
                b.add("sprite", name=w[1], img=None)
        elif k == "play" and len(w) > 2 and w[1] == "music":
            b.add("bgm", name=_unq(" ".join(w[2:]).split(" fade")[0]))
        elif k == "stop" and len(w) > 1 and w[1] == "music":
            b.add("bgm", name=None)
        elif k in ("pass", "with", "pause", "window", "voice", "play", "stop", "queue", "nvl", "centered", "extend",
                   "define", "default", "image", "init", "python", "camera", "renpy", "show_screen"):
            pass
        else:
            self.unknown[k] = self.unknown.get(k, 0) + 1


def build(src, assets=None, entry="start", **_):
    return Importer(src, assets, entry or "start").build()
