"""NScripter / ONScripter（0.txt…9.txt 或 nscript.dat）→ galbook/1。老游戏、同人作品很多是这个。

nscript.dat 每字节 XOR 0x84 就是文本。认的写法：
  *label   ;注释   一行多条用 : 分隔
  文字行（不以英文指令开头）；行尾 \\ 换页、@ 等点击；【名字】「…」 或 名字「…」 认说话人
  select "文字",*l1,"文字",*l2 …（可跨行）  selgosub 同上但是调用  selnum %v,"a","b"（把序号写进变量）
  goto *l  gosub *l  return  jumpf/jumpb（~ 标记）不支持会报
  mov %0,1  add/sub/mul/div %0,1  inc/dec %0   if 条件 指令 / notif 条件 指令
  bg "x.bmp",1 / bg black,1   ld l|c|r,":a;x.bmp",1   cl l|c|r|a,1   bgm "x" / stop
  end → 结局；reset / definereset → 回标题
%0-%199 是本局变量 f.v*；%200 起（globalon 的全局区）当系统变量 s.v*；$n 字符串 → f.str*
"""
import os
import re

from .common import SceneB, Assets, is_h_title


def _readb(p):
    with open(p, "rb") as f:
        return f.read()

CMD = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\b\s*(.*)$")
GLOBAL_BORDER = 200


def load_script(src):
    """返回脚本全文（str）和来源说明。"""
    p = None
    for name in ("nscript.dat", "nscript.___"):
        for dp, _, fns in os.walk(src):
            for fn in fns:
                if fn.lower() == name:
                    p = os.path.join(dp, fn)
                    break
    if p:
        with open(p, "rb") as fh:
            raw = bytes(b ^ 0x84 for b in fh.read())
        return _dec(raw), os.path.basename(p)
    parts = []
    for dp, _, fns in os.walk(src):
        for fn in sorted(fns):
            if re.match(r"^\d{1,2}\.txt$", fn.lower()):
                parts.append((int(fn.split(".")[0]), os.path.join(dp, fn)))
    if not parts:
        raise ValueError("没找到 nscript.dat 或 0.txt")
    return "\n".join(_dec(_readb(p)) for _, p in sorted(parts)), "%d 个 N.txt" % len(parts)


def _dec(raw):
    for e in ("utf-8-sig", "cp932", "gbk"):
        try:
            return raw.decode(e)
        except UnicodeDecodeError:
            pass
    return raw.decode("cp932", "replace")


def var(tok):
    tok = tok.strip()
    m = re.match(r"^%(\d+)$", tok)
    if m:
        n = int(m.group(1))
        return ("s.v%d" if n >= GLOBAL_BORDER else "f.v%d") % n
    m = re.match(r"^\$(\d+)$", tok)
    if m:
        return "f.str%s" % m.group(1)
    return None


def conv_expr(e):
    e = re.sub(r"%(\d+)", lambda m: var("%" + m.group(1)), e)
    e = re.sub(r"\$(\d+)", lambda m: var("$" + m.group(1)), e)
    e = re.sub(r"(?<![=!<>])=(?!=)", "==", e)
    e = e.replace("<>", "!=")
    e = re.sub(r"(?<!&)&(?!&)", "&&", e)
    return e


def _split_colon(line):
    out, cur, q = [], [], False
    for ch in line:
        if ch == '"':
            q = not q
        if ch == ":" and not q:
            out.append("".join(cur))
            cur = []
        elif ch == ";" and not q:
            break
        else:
            cur.append(ch)
    out.append("".join(cur))
    return [x.strip() for x in out if x.strip()]


def _args(s):
    out, cur, q = [], [], False
    for ch in s:
        if ch == '"':
            q = not q
            cur.append(ch)
        elif ch == "," and not q:
            out.append("".join(cur).strip())
            cur = []
        else:
            cur.append(ch)
    if cur or out:
        out.append("".join(cur).strip())
    return out


def _unq(s):
    s = s.strip()
    return s[1:-1] if len(s) >= 2 and s[0] == '"' and s[-1] == '"' else s


class Importer(object):
    def __init__(self, src, assets=None, entry="start"):
        self.src, self.assets, self.entry = src, assets or Assets(), entry
        self.warnings, self.unknown = [], {}
        self.stats = {"files": 1, "says": 0, "choices": 0, "options": 0, "jumps": 0, "calls": 0, "sets": 0, "ifs": 0}
        self.system_vars = set()
        self.buf = []

    def build(self):
        text, origin = load_script(self.src)
        self.stats["origin"] = origin
        b = SceneB("script", "script")
        lines = text.splitlines()
        i = 0
        in_define = False
        while i < len(lines):
            s = lines[i].strip()
            i += 1
            if not s or s.startswith(";"):
                continue
            if s.startswith("*"):
                self._flush(b)
                name = s[1:].split()[0].split(":")[0]
                in_define = name.lower() == "define"
                b.add("label", name=name.lower())
                continue
            if in_define:
                continue
            # select 跨行：行尾逗号就接下一行
            while re.match(r"^(select|selgosub|selnum|csel)\b", s, re.I) and s.rstrip().endswith(",") and i < len(lines):
                s = s.rstrip() + lines[i].strip()
                i += 1
            if CMD.match(s) and not re.match(r"^[A-Za-z]+[「『]", s):
                for part in _split_colon(s):
                    self._cmd(b, part)
            else:
                self._text(b, s)
        self._flush(b)
        start = SceneB("__start__", "开始", tags=["system"])
        start.add("label", name="top")
        labels = {op["name"] for op in b.ops if op["op"] == "label"}
        ent = self.entry if self.entry in labels else ("start" if "start" in labels else None)
        if not ent:
            raise ValueError("脚本里没有 *start")
        start.add("jump", scene="script", label=ent)
        scenes = {"__start__": start.data(), "script": b.data()}
        meta = {"format": "galbook/1", "title": "", "engine": "nscripter", "importer": "galbook-nscripter-1",
                "entry": {"scene": "__start__", "label": "top"},
                "scenes": {k: {"title": v["title"], "tags": v["tags"]} for k, v in scenes.items()},
                "routes": [], "system_vars": sorted(self.system_vars),
                "stats": dict(self.stats, unknown=sorted(self.unknown.items(), key=lambda x: -x[1])[:20],
                              assets=self.assets.report()),
                "warnings": self.warnings[:200]}
        return meta, scenes

    def _text(self, b, s):
        page = s.endswith("\\") or s.endswith("@")
        t = s.rstrip("\\@").replace("@", "")
        t = re.sub(r"#[0-9A-Fa-f]{6}", "", t)
        self.buf.append(t)
        if page or True:
            self._flush(b)

    def _flush(self, b):
        t = "".join(self.buf).strip()
        self.buf = []
        if not t:
            return
        who = ""
        m = re.match(r"^【([^】]{1,16})】\s*(.*)$", t) or re.match(r"^([^「『\s]{1,8})([「『].*)$", t)
        if m:
            who, t = m.group(1), m.group(2)
        b.add("say", who=who, text=t)
        self.stats["says"] += 1

    def _jump_label(self, tok):
        tok = tok.strip()
        return tok[1:].lower() if tok.startswith("*") else None

    def _cmd(self, b, s):
        m = CMD.match(s)
        if not m:
            return self._text(b, s)
        c, rest = m.group(1).lower(), m.group(2).strip()
        a = _args(rest) if rest else []
        if c in ("goto", "gosub"):
            lb = self._jump_label(rest)
            if lb:
                self._flush(b)
                b.add("jump" if c == "goto" else "call", label=lb)
                self.stats["jumps" if c == "goto" else "calls"] += 1
        elif c == "return":
            self._flush(b)
            b.add("ret")
        elif c in ("select", "selgosub", "csel"):
            self._flush(b)
            opts = []
            for k in range(0, len(a) - 1, 2):
                lb = self._jump_label(a[k + 1])
                if lb:
                    opts.append({"text": _unq(a[k]), "goto": {"label": lb}})
            if c == "selgosub":
                # 调用式：选完 gosub，回来接着往下
                ret = "__selret%d" % len(b.ops)
                for o in opts:
                    o["goto"] = {"label": "__selcall_%s_%d" % (o["goto"]["label"], len(b.ops))}
                b.add("choice", id="c%d" % len(b.ops), options=opts)
                b.add("jump", label=ret)
                for o, k in zip(opts, range(0, len(a) - 1, 2)):
                    b.add("label", name=o["goto"]["label"])
                    b.add("call", label=self._jump_label(a[k + 1]))
                    b.add("jump", label=ret)
                b.add("label", name=ret)
            else:
                b.add("choice", id="c%d" % len(b.ops), options=opts)
            self.stats["choices"] += 1
            self.stats["options"] += len(opts)
        elif c == "selnum":
            self._flush(b)
            v = var(a[0]) if a else None
            opts = [{"text": _unq(x), "set": "%s = %d" % (v, k)} for k, x in enumerate(a[1:])] if v else []
            if opts:
                b.add("choice", id="c%d" % len(b.ops), options=opts)
                self.stats["choices"] += 1
                self.stats["options"] += len(opts)
        elif c in ("mov", "add", "sub", "mul", "div", "mod"):
            v = var(a[0]) if a else None
            if v and len(a) > 1:
                rhs = conv_expr(a[1])
                e = {"mov": "%s = %s", "add": "%s += %s", "sub": "%s -= %s", "mul": "%s *= %s"}.get(c)
                e = (e % (v, rhs)) if e else ("%s = %s %s %s" % (v, v, "/" if c == "div" else "%", rhs))
                b.add("set", expr=e)
                self.stats["sets"] += 1
                if v.startswith("s."):
                    self.system_vars.add(v[2:])
        elif c in ("inc", "dec"):
            v = var(rest)
            if v:
                b.add("set", expr="%s %s= 1" % (v, "+" if c == "inc" else "-"))
        elif c in ("if", "notif"):
            mm = re.match(r"^(.*?)\s+((?:goto|gosub|mov|add|sub|inc|dec|end|return|reset|select)\b.*)$", rest, re.I)
            if not mm:
                self.unknown["if"] = self.unknown.get("if", 0) + 1
                return
            cond = conv_expr(mm.group(1))
            if c == "notif":
                cond = "!(%s)" % cond
            n0 = len(b.ops)
            self._cmd(b, mm.group(2))
            for op in b.ops[n0:]:
                op["if"] = cond if "if" not in op else "(%s) && (%s)" % (cond, op["if"])
            self.stats["ifs"] += 1
        elif c == "bg":
            self._flush(b)
            nm = _unq(a[0]) if a else ""
            b.add("sprites_clear")
            b.add("bg", img=None if nm.lower() in ("black", "white", "") or nm.startswith("#") else (self.assets.find(nm) or nm))
        elif c == "ld":
            self._flush(b)
            if len(a) >= 2:
                f = _unq(a[1]).split(";")[-1]
                b.add("sprite", name=a[0], img=self.assets.find(f) or f, pos={"l": "left", "c": "center", "r": "right"}.get(a[0], a[0]))
        elif c == "cl":
            if a and a[0] == "a":
                b.add("sprites_clear")
            elif a:
                b.add("sprite", name=a[0], img=None)
        elif c in ("bgm", "mp3loop", "mp3", "play"):
            b.add("bgm", name=_unq(a[0]) if a else None)
        elif c in ("stop", "mp3stop", "playstop"):
            b.add("bgm", name=None)
        elif c == "end":
            self._flush(b)
            b.add("end", kind="ending", how="end")
        elif c in ("reset", "definereset"):
            self._flush(b)
            b.add("end", kind="title", how="reset")
        elif c in ("jumpf", "jumpb", "tablegoto"):
            self.warnings.append("%s 不支持（只能人工改成 goto）: %s" % (c, s))
        elif c in ("wait", "delay", "click", "lr_trap", "trap", "print", "effect", "dwave", "dwaveloop", "wave",
                   "waveloop", "wavestop", "btndef", "btn", "btnwait", "btnwait2", "spbtn", "lsp", "csp", "msp",
                   "amsp", "vsp", "texton", "textoff", "textclear", "erasetextwindow", "setwindow", "setwindow2",
                   "monocro", "nega", "quake", "quakex", "quakey", "locate", "br", "saveon", "saveoff", "rmode",
                   "skipoff", "clickvoice", "voicevol", "bgmvol", "sevol", "humanz", "windoweffect", "puttext",
                   "game", "caption", "versionstr", "globalon", "nsa", "ns2", "ns3", "numalias", "stralias",
                   "defaultspeed", "menuselectcolor", "menusetwindow", "savenumber", "rmenu", "kidokuskip",
                   "mode_saya", "effectblank", "maxkaisoupage", "underline", "transmode", "textspeed",
                   "setcursor", "abssetcursor", "linepage", "linepage2", "systemcall", "savegame", "loadgame",
                   "chvol", "selectcolor", "selectvoice", "automode", "filelog", "labellog", "kidokumode",
                   "shadedistance", "usewheel", "useescspc", "getcursorpos", "time", "date", "getparam", "itoa",
                   "atoi", "len", "mid", "cmp", "add_", "for", "next", "break", "dim", "movl", "rnd", "rnd2"):
            pass
        else:
            self.unknown[c] = self.unknown.get(c, 0) + 1


def build(src, assets=None, entry="start", **_):
    return Importer(src, assets, entry or "start").build()
