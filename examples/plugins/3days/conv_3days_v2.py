"""3days（data/script/*.txt，RealLive 系文本脚本）→ galbook/1。galbook build 插件。

  python3 -m galbook build --src <data/script> --out books/3days-v2/story \
          --plugin conv_3days_v2.py --engine 3days --strict

只做「转换」，不改引擎。翻译表：
  .select [map]  选项行…  .case k  …  .endsel   → choice（每个 option 一个 goto）
      case 体只有一条 .load X / .goto #L         → option.goto 直接指过去
      case 体还有别的                             → option.goto 指本场景标签 sel<n>_c<k>，
                                                   体结束处补 {"jump", label: sel<n>_end, "auto": true}
                                                   （这是 .case 的「执行完跳出 .endsel」语义，不是直线补跳）
      选项行 "文字\t图块\t1 条件"（title.map 那种） → text=第一列，option.if=条件
  .load X.txt                                    → jump scene=X
  .call X.txt                                    → call scene=X
  .goto #L                                       → jump label=L          #L → label
  .exit                                          → ret                   .quit → end(stop)
  .if C { … } / .if C 单行  .else { … } / .else 单行  → 块内每条 op 加 "if"（else 用 !(C)，嵌套用 &&）
      choice 在条件块里：条件同时并进每个 option 的 if（引擎对 choice 只看 option.if）
  ?v = expr                                      → set f.v = …
  .img0 X → bg   .img → bg null + sprites_clear   .img1..5 X → sprite name=img1..img5
  .bgm X → bgm   .voice X → 下一句 say 的 voice   .chapter T → 场景标题
  .system / .movie → event                        其余演出指令（wait/fade/se/…）→ 认识，丢掉
  名字:文本 → say（@ 是点击等待，去掉）            ; 开头 → 注释
文件走到底（最后一条不是无条件出口）：
  补 {"op": "ret", "auto": true}——RealLive 被 .call 的脚本走到文件尾就返回调用方；
  栈空时引擎对 ret 什么也不做，照样在这里停（= 交接里说的「让它自然停」），不接任何直线 jump。
编码：每个文件先整体按 utf-8-sig → cp932 → gbk → big5 → utf-16 试；
  这批脚本是「指令/变量名 cp932 + 正文 gbk」混写，整体解不干净时逐行按同一顺序试，
  「解得开且不出现半角片假名/希伯来文等明显乱码字符」才算成功；全失败用 errors="replace"，
  文件:行号 + 替换字符数写进 warnings，不崩。
"""
import os
import re

try:
    from galbook.importers.common import SceneB
    from galbook import expr as _expr
except Exception:  # 单独跑测试时
    SceneB = None
    _expr = None

NAME = "3days"
ENCODINGS = ("utf-8-sig", "cp932", "gbk", "big5", "utf-16")
# 明显乱码：半角片假名、希伯来/阿拉伯、私用区、C1 控制符、替换符
SUSPECT = re.compile(r"[\uff61-\uff9f\u0590-\u06ff\ue000-\uf8ff\u0080-\u009f\ufffd]")
IGNORED = {".wait", ".fade", ".fadein", ".fadeout", ".se", ".mode", ".filter", ".shake", ".flash", ".date",
           ".wipe", ".custom", ".env", ".reset", ".clear_img", "."}
VAR = re.compile(r"[A-Za-z_\u0080-\uffff][\w\u0080-\uffff]*")
TAGS = re.compile(r"\{rb:[^}]*\}|\[ruby[^\]]*\]|\[/?(?:color|c|font|b|i)[^\]]*\]|</?(?:color|font|ruby|rt|rb|b|i)[^>]*>|\\[cC]\[\d+\]")


# ---------------------------------------------------------------- 解码
# UTF-8 误解 GBK 双字节时落在 U+0080–07FF（希腊/西里尔/希伯来…：׷ ͻȻ һҧ 都是这么来的）
SUSPECT_UTF8 = re.compile(r"[\u0100-\u07ff]")


def _plausible(t, enc=None):
    if SUSPECT.search(t):
        return False
    if enc in ("utf-8", "utf-8-sig") and SUSPECT_UTF8.search(t):
        return False
    return True


KANA = re.compile(r"[\u3041-\u30ff]")


def _cp932_suspect(raw, t):
    """cp932 解得开但其实是 gbk 正文：所有双字节都落在 JIS 第二水准（首字节 E0-EF）且没有假名。"""
    if KANA.search(t):
        return False
    leads, i = [], 0
    while i < len(raw):
        b = raw[i]
        if 0x81 <= b <= 0x9F or 0xE0 <= b <= 0xFC:
            leads.append(b)
            i += 2
        else:
            i += 1
    return bool(leads) and all(0xE0 <= b <= 0xEF for b in leads)


def _try(raw):
    for e in ENCODINGS:
        try:
            t = raw.decode(e)
        except (UnicodeDecodeError, LookupError):
            continue
        if _plausible(t, e) and not (e == "cp932" and _cp932_suspect(raw, t)):
            return t, e
    return None, None


def decode_file(path):
    """→ (lines[str], how, warnings[])。

    整份是合法 UTF-8（带不带 BOM）或 UTF-16 BOM → 整份解。
    否则逐行按 ENCODINGS 顺序试：这批脚本「指令/变量名 cp932 + 正文 gbk」混写，
    整份用 gbk 也常常「解得开」，但 cp932 那几行会变成生僻汉字乱码（シーン回想→僔乕儞夞憐），
    所以不能信整份解码的结果。"""
    with open(path, "rb") as fh:
        raw = fh.read()
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return raw.decode("utf-16", "replace").splitlines(), "utf-16", []
    try:
        t = raw.decode("utf-8-sig")
        if _plausible(t, "utf-8-sig"):
            return t.splitlines(), "utf-8-sig", []
    except UnicodeDecodeError:
        pass
    out, warns, used = [], [], {}
    fn = os.path.basename(path)
    for i, b in enumerate(raw.split(b"\n"), 1):
        b = b.rstrip(b"\r")
        if not b:
            out.append("")
            continue
        s, e = _try(b)
        if s is None:
            s = b.decode("gbk", "replace")
            n = s.count("\ufffd") + len(SUSPECT.findall(s.replace("\ufffd", "")))
            warns.append({"file": fn, "line": i, "replaced": n, "text": s.strip()[:40]})
            e = "replace"
        if any(c > 0x7f for c in b):
            used[e] = used.get(e, 0) + 1
        out.append(s)
    return out, "+".join("%s:%d" % kv for kv in sorted(used.items())) or "ascii", warns


# ---------------------------------------------------------------- 解析成语句树
class Tok(object):
    __slots__ = ("s", "ln", "raw")

    def __init__(self, s, ln, raw):
        self.s, self.ln, self.raw = s, ln, raw


def _strip_cmd_comment(s):
    if s.startswith("."):
        m = re.search(r"\s;", s)
        if m:
            s = s[:m.start()]
    return s.strip()


def tokenize(lines):
    toks = []
    for i, line in enumerate(lines, 1):
        s = line.replace("\u3000", "\u3000").strip().lstrip("\ufeff")
        if not s or s.startswith(";"):
            continue
        s = _strip_cmd_comment(s)
        if not s:
            continue
        # "{ .goto #x }" 这种一行写完的，拆开
        if s.startswith("{") and len(s) > 1:
            toks.append(Tok("{", i, line))
            s = s[1:].strip()
            if not s:
                continue
        tail = s.endswith("}") and len(s) > 1 and s.startswith(".")
        if tail:
            toks.append(Tok(s[:-1].strip(), i, line))
            toks.append(Tok("}", i, line))
        else:
            toks.append(Tok(s, i, line))
    return toks


class ParseError(ValueError):
    pass


class Parser(object):
    def __init__(self, toks, fname):
        self.t, self.i, self.f = toks, 0, fname
        self.warn = []

    def peek(self):
        return self.t[self.i] if self.i < len(self.t) else None

    def next(self):
        tk = self.peek()
        self.i += 1
        return tk

    def block(self, stop=()):
        """读语句直到 stop 里的某个开头（不吃掉）或文件尾。"""
        out = []
        while True:
            tk = self.peek()
            if tk is None:
                return out
            if tk.s == "}" and "}" in stop:
                return out
            if any(tk.s == x or tk.s.startswith(x + " ") or tk.s.startswith(x + "\t") for x in stop if x != "}"):
                return out
            if tk.s == "}":
                self.next()
                self.warn.append("%s:%d 多余的 }（忽略）" % (self.f, tk.ln))
                continue
            out.append(self.stmt(stop))

    def body(self, stop):
        """.if/.else 后面：{ 块 } 或者单条语句。"""
        tk = self.peek()
        if tk is not None and tk.s == "{":
            self.next()
            b = self.block(stop=("}",))
            if self.peek() is not None and self.peek().s == "}":
                self.next()
            else:
                self.warn.append("%s:%d { 没有配对的 }" % (self.f, tk.ln))
            return b
        if tk is None:
            return []
        return [self.stmt(stop)]

    def stmt(self, stop=()):
        tk = self.next()
        s = tk.s
        if s == "{":                       # 孤立的块：当普通块处理
            b = self.block(stop=("}",))
            if self.peek() is not None and self.peek().s == "}":
                self.next()
            return ("block", tk, b)
        if re.match(r"\.if\b", s):
            cond = s[3:].strip()
            then = self.body(stop)
            els = None
            nx = self.peek()
            if nx is not None and re.match(r"\.else\b", nx.s):
                self.next()
                rest = nx.s[5:].strip()
                if rest.startswith(".if"):     # .else .if 写在一行
                    self.t.insert(self.i, Tok(rest, nx.ln, nx.raw))
                els = self.body(stop)
            return ("if", tk, cond, then, els)
        if re.match(r"\.else\b", s):
            self.warn.append("%s:%d .else 前面没有 .if（当成无条件块）" % (self.f, tk.ln))
            return ("block", tk, self.body(stop))
        if re.match(r"\.select\b", s):
            return self.select(tk)
        if re.match(r"\.(case|endsel)\b", s):
            self.warn.append("%s:%d %s 不在 .select 里（忽略）" % (self.f, tk.ln, s.split()[0]))
            return ("nop", tk)
        return ("line", tk)

    def select(self, tk):
        arg = tk.s[7:].strip()
        opts = []
        while True:
            nx = self.peek()
            if nx is None or nx.s.startswith(".") or nx.s in ("{", "}"):
                break
            self.next()
            opts.append(nx)
        cases = []
        while True:
            nx = self.peek()
            if nx is None:
                self.warn.append("%s:%d .select 没有 .endsel" % (self.f, tk.ln))
                break
            if re.match(r"\.endsel\b", nx.s):
                self.next()
                break
            m = re.match(r"\.case\s+(\d+)", nx.s)
            if m:
                self.next()
                b = self.block(stop=(".case", ".endsel", "}"))
                cases.append((int(m.group(1)), nx, b))
                if self.peek() is not None and self.peek().s == "}":
                    self.warn.append("%s:%d .select 在块结束前没有 .endsel" % (self.f, tk.ln))
                    break
                continue
            if nx.s == "}":
                self.warn.append("%s:%d .select 在块结束前没有 .endsel" % (self.f, tk.ln))
                break
            # .case 之前出现的其它指令：当普通语句（很少见）
            cases.append((0, nx, [self.stmt((".case", ".endsel", "}"))]))
        return ("select", tk, arg, opts, cases)


# ---------------------------------------------------------------- 表达式
def trans_expr(src):
    """3days 条件/赋值右边 → galbook expr：裸变量加 f.，& | 换成 && ||，单 = 变 ==。"""
    s = src.strip()
    s = s.replace("＝", "=").replace("！", "!").replace("＜", "<").replace("＞", ">")
    s = s.replace("<>", "!=")
    s = re.sub(r"(?<![&])&(?![&])", "&&", s)
    s = re.sub(r"(?<![|])\|(?![|])", "||", s)
    s = re.sub(r"(?<![=!<>])=(?!=)", "==", s)
    out, i = [], 0
    for m in VAR.finditer(s):
        out.append(s[i:m.start()])
        w = m.group(0)
        if w.lower() in ("and", "or", "not", "true", "false"):
            out.append(w)
        elif w[0].isdigit():
            out.append(w)
        else:
            out.append("f." + w)
        i = m.end()
    out.append(s[i:])
    return re.sub(r"\s+", " ", "".join(out)).strip()


def _fw_digits(s):
    return s.translate({ord(c): ord("0") + k for k, c in enumerate("０１２３４５６７８９")})


def trans_set(body):
    m = re.match(r"(.+?)\s*(\+=|-=|=)\s*(.+)$", body)
    if not m:
        return None
    name, op, val = m.group(1).strip(), m.group(2), m.group(3).strip()
    val = trans_expr(_fw_digits(val)).replace("==", "=")
    return "f.%s %s %s" % (name, op, val)


def _and(conds):
    cl = [c for c in conds if c]
    if not cl:
        return None
    if len(cl) == 1:
        return cl[0]
    return " && ".join("(%s)" % c for c in cl)


# ---------------------------------------------------------------- 文本
def clean_text(s):
    s = TAGS.sub("", s)
    s = s.replace("\x00", "")
    s = re.sub(r"@+", "", s)
    return s.strip(" \t\u3000")


def clean_option(s):
    s = s.split(";", 1)[0]
    s = s.split("\t", 1)[0] if "\t" in s.strip("\t") else s
    return clean_text(s)


def _target(arg):
    a = arg.split()[0] if arg.split() else ""
    return os.path.splitext(os.path.basename(a.replace("\\", "/")))[0]


# ---------------------------------------------------------------- 编译
class Compiler(object):
    def __init__(self, sid, fname, ctx):
        self.sc = SceneB(sid, sid) if SceneB else None
        self.ops = self.sc.ops if self.sc else []
        self.f, self.ctx = fname, ctx
        self.voice = None
        self.title = None

    def add(self, conds, op, **kw):
        d = {"op": op}
        d.update({k: v for k, v in kw.items() if v is not None})
        c = _and(conds)
        if c:
            d["if"] = c
        self.ops.append(d)
        self.ctx.ops[op] = self.ctx.ops.get(op, 0) + 1
        return d

    def cond(self, src, tk):
        e = trans_expr(_fw_digits(src))
        if _expr is not None:
            try:
                _expr.evaluate(e, {}, {})
            except Exception as ex:  # noqa
                self.ctx.unknown.append("%s:%d 条件翻不过来 %r → %r（%s）" % (self.f, tk.ln, src, e, ex))
        return e

    def run(self, stmts, conds):
        for st in stmts:
            k = st[0]
            if k == "line":
                self.line(st[1], conds)
            elif k == "block":
                self.run(st[2], conds)
            elif k == "if":
                _, tk, src, then, els = st
                c = self.cond(src, tk)
                self.ctx.n_if += 1
                self.run(then, conds + [c])
                if els is not None:
                    self.run(els, conds + ["!(%s)" % c])
            elif k == "select":
                self.select(st, conds)

    def select(self, st, conds):
        _, tk, arg, opt_toks, cases = st
        self.ctx.n_sel += 1
        n = self.ctx.n_sel
        cid = "sel%d" % n
        system = bool(arg)              # .select title.map / cg.map = 系统菜单（标题、鉴赏）
        by_k = {}
        for k, ctk, body in cases:
            if k == 0:                   # .case 前的游离语句：原样执行（在 choice 之前）
                self.run(body, conds)
                continue
            by_k.setdefault(k, body)
        options, bodies = [], []
        k = 0
        for otk in opt_toks:
            parts = [p for p in re.split(r"\t+", otk.raw.strip()) if p != ""]
            text = clean_option(parts[0] if parts else otk.s)
            if not text:
                continue
            k += 1
            ocond = None
            if len(parts) >= 3:          # "文字\t图块\t1 条件"
                m = re.match(r"\s*1\s+(.+)$", parts[2])
                if m:
                    ocond = self.cond(m.group(1).split(";")[0].strip(), otk)
                elif re.match(r"\s*1\s+0\s*$", parts[2]) or re.match(r"\s*0\s*$", parts[2]):
                    ocond = "false"
            elif len(parts) == 2:
                m = re.search(r"\s1\s+(\S+)\s*$", parts[1])
                if m:
                    ocond = self.cond(m.group(1), otk)
                elif re.search(r"\s1\s+0\s*$", parts[1]):
                    ocond = "false"
            body = by_k.get(k)
            o = {"text": text}
            oif = _and(conds + [ocond])
            if oif:
                o["if"] = oif
            simple = self._simple(body)
            if simple is not None:
                o["goto"] = simple
            elif body:
                o["goto"] = {"label": "%s_c%d" % (cid, k)}
                bodies.append((k, body))
            else:
                o["goto"] = {"label": "%s_end" % cid}
            options.append(o)
        for kk in sorted(by_k):
            if kk > k:
                self.ctx.warn.append("%s:%d %s 有 .case %d 但只有 %d 行选项文字" % (self.f, tk.ln, cid, kk, k))
        d = self.add(conds, "choice", id=cid, prompt="", options=options, src="%s:%d" % (self.f, tk.ln))
        if system:
            d["system"] = arg
            self.ctx.n_sys_sel += 1
        self.ctx.sel_list.append({"id": cid, "scene": self.sc.id if self.sc else "", "line": tk.ln,
                                  "system": arg or None, "options": [(o["text"], o["goto"]) for o in options]})
        for kk, body in bodies:
            self.add(conds, "label", name="%s_c%d" % (cid, kk))
            self.run(body, conds)
            last = self.ops[-1] if self.ops else {}
            if not (last.get("op") in ("jump", "ret", "end", "choice") and not last.get("if")):
                self.add(conds, "jump", label="%s_end" % cid, auto=True, note="case-break")
                self.ctx.n_case_break += 1
        self.add(conds, "label", name="%s_end" % cid)

    @staticmethod
    def _simple(body):
        if not body or len(body) != 1 or body[0][0] != "line":
            return None
        s = body[0][1].s
        m = re.match(r"\.load\s+(\S+)", s)
        if m:
            return {"scene": _target(m.group(1))}
        m = re.match(r"\.goto\s+#?(\S+)", s)
        if m:
            return {"label": m.group(1)}
        return None

    def line(self, tk, conds):
        s = tk.s
        if s.startswith("#"):
            self.add(conds, "label", name=s[1:].strip())
            return
        if s.startswith("?"):
            e = trans_set(s[1:].strip())
            if e is None:
                self.ctx.unknown.append("%s:%d 认不出的赋值 %r" % (self.f, tk.ln, s[:40]))
                return
            if _expr is not None:
                try:
                    _expr.assign(e, {}, {})
                except Exception as ex:  # noqa
                    self.ctx.unknown.append("%s:%d 赋值翻不过来 %r → %r（%s）" % (self.f, tk.ln, s, e, ex))
            self.add(conds, "set", expr=e)
            return
        if s.startswith("."):
            m = re.match(r"(\.[^\s]*)\s*(.*)$", s)
            cmd, arg = m.group(1), m.group(2).strip()
            src = "%s:%d" % (self.f, tk.ln)      # 出处：每条控制流都能对回原文行
            if cmd == ".load":
                self.add(conds, "jump", scene=_target(arg), src=src)
            elif cmd == ".call":
                self.add(conds, "call", scene=_target(arg), src=src)
            elif cmd == ".goto":
                self.add(conds, "jump", label=arg.lstrip("#").strip(), src=src)
            elif cmd == ".exit":
                self.add(conds, "ret", src=src)
            elif cmd == ".quit":
                self.add(conds, "end", kind="stop", name="quit", src=src)
            elif cmd == ".chapter":
                if arg and not self.title:
                    self.title = arg.split("\t")[0].strip()
            elif cmd == ".voice":
                self.voice = os.path.splitext(arg.replace("\\", "/").split("/")[-1].strip())[0] or None
            elif cmd == ".bgm":
                self.add(conds, "bgm", name=None if arg in ("", "fade", "stop") else arg.split()[0])
            elif cmd == ".img":
                if arg:
                    self.add(conds, "bg", img="assets/" + arg.split()[0])
                else:
                    self.add(conds, "bg", img=None)
                    self.add(conds, "sprites_clear")
            elif cmd == ".img0":
                self.add(conds, "bg", img=("assets/" + arg.split()[0]) if arg else None)
            elif re.match(r"\.img[1-9]$", cmd):
                self.add(conds, "sprite", name=cmd[1:], img=("assets/" + arg.split()[0]) if arg else None,
                         pos="center")
            elif cmd == ".system":
                self.add(conds, "event", name="system", arg=arg)
            elif cmd == ".movie":
                self.add(conds, "event", name="movie", arg=arg)
            elif cmd in IGNORED:
                self.ctx.ignored[cmd] = self.ctx.ignored.get(cmd, 0) + 1
            else:
                self.ctx.unknown.append("%s:%d %s" % (self.f, tk.ln, s[:40]))
            return
        # 台词
        who, text = "", s
        m = split_speaker(s, self.ctx.names)
        if m:
            who, text = m
        text = clean_text(text)
        if not text:
            return
        self.add(conds, "say", who=who, text=text, voice=self.voice)
        self.voice = None


NAME_BAD = re.compile(r"[\s。、，！!「」『』（）()…—―]")


def split_speaker(s, known=None):
    """名字:台词（半角冒号，原作写法）；全角「：」只在名字是半角写法里出现过的说话人时才拆。"""
    if ":" in s:
        a, b = s.split(":", 1)
        a = a.strip()
        if 0 < len(a) <= 12 and not NAME_BAD.search(a) and (not re.search(r"[？?]", a) or re.fullmatch(r"[？?]+", a)):
            return a, b
    if "：" in s:
        a, b = s.split("：", 1)
        a = a.strip()
        if b.strip() and ((known and a in known) or
                          (0 < len(a) <= 4 and not NAME_BAD.search(a) and a not in ("注", "译注", "注释"))):
            return a, b
    return None


class Ctx(object):
    def __init__(self):
        self.ops, self.ignored = {}, {}
        self.unknown, self.warn = [], []
        self.n_sel = self.n_sys_sel = self.n_if = self.n_case_break = self.n_eof_ret = 0
        self.sel_list = []
        self.names = set()


def detect(src):
    try:
        names = os.listdir(src)
    except OSError:
        return False, ""
    if "a-master.txt" in names and "b-master.txt" in names:
        return True, "3days：data/script 里有 a-master.txt / b-master.txt"
    return False, ""


def build(src, assets=None, entry=None, **opts):
    files = sorted(f for f in os.listdir(src) if f.lower().endswith(".txt"))
    ctx = Ctx()
    scenes, meta_sc = {}, {}
    enc_files, enc_mixed, decode_warns = {}, 0, []
    decoded = {f: decode_file(os.path.join(src, f)) for f in files}
    for f in files:
        for ln in decoded[f][0]:
            t = ln.strip()
            if t and t[0] not in ".;#?{}" and ":" in t:
                m = split_speaker(t)
                if m:
                    ctx.names.add(m[0])
    for f in files:
        sid = os.path.splitext(f)[0]
        lines, how, dw = decoded[f]
        if how.count(":") > 1:
            enc_mixed += 1
        enc_files[f] = how
        decode_warns.extend(dw)
        p = Parser(tokenize(lines), f)
        try:
            tree = p.block()
        except Exception as e:  # noqa  不许崩：整份当失败记下来
            ctx.warn.append("%s: 解析失败 %s: %s" % (f, type(e).__name__, e))
            tree = []
        ctx.warn.extend(p.warn)
        c = Compiler(sid, f, ctx)
        c.run(tree, [])
        last = c.ops[-1] if c.ops else {}
        if not (last.get("op") in ("jump", "ret", "end") and not last.get("if")):
            c.add([], "ret", auto=True, note="eof")
            ctx.n_eof_ret += 1
        title = c.title or sid
        c.sc.title = title
        if sid.startswith("sp_"):
            c.sc.tags.append("system")
        if "-hh-" in sid:
            c.sc.tags.append("h")
        scenes[sid] = c.sc.data()
        meta_sc[sid] = {"title": title, "tags": c.sc.tags, "route": ""}
    warnings = []
    if decode_warns:
        warnings.append("编码：%d 行在 %s 里都解不干净，按 gbk errors=replace 处理（%s）" % (
            len(decode_warns), "/".join(ENCODINGS),
            "；".join("%s:%d 替换 %d 字" % (w["file"], w["line"], w["replaced"]) for w in decode_warns[:20])))
    if enc_mixed:
        warnings.append("编码：%d 个文件是 cp932（指令/变量）+ gbk（正文）混写，按行解码" % enc_mixed)
    warnings.append("出口：%d 个场景文件尾补了 ret（auto，RealLive 文件尾=返回调用方；栈空时自然停），"
                    "%d 处 .case 体尾补了跳到 .endsel 的 jump（auto，note=case-break）；没有补任何跨场景直线 jump"
                    % (ctx.n_eof_ret, ctx.n_case_break))
    if ctx.n_sys_sel:
        warnings.append("选项：共 %d 个 .select，其中 %d 个是带图块的系统菜单（标题/鉴赏，choice 上有 system 字段）"
                        % (ctx.n_sel, ctx.n_sys_sel))
    warnings.extend(ctx.warn[:30])
    ent = entry or ("a-master" if "a-master" in scenes else sorted(scenes)[0])
    meta = {"format": "galbook/1", "title": "3days ～在逝去时间的另一端～", "engine": "reallive-text",
            "importer": "conv_3days_v2", "mode": "branch", "author": "Lass / 3days汉化组",
            "license": "素材版权归原厂", "entry": {"scene": ent, "label": None},
            "scenes": meta_sc, "routes": [], "system_vars": [],
            "stats": {"choices": ctx.n_sel, "system_choices": ctx.n_sys_sel, "if_blocks": ctx.n_if,
                      "eof_ret_auto": ctx.n_eof_ret, "case_break_auto": ctx.n_case_break,
                      "decode_replaced_lines": len(decode_warns), "mixed_encoding_files": enc_mixed,
                      "ignored": ctx.ignored, "unknown": ctx.unknown[:20], "scenes": len(scenes)},
            "warnings": warnings, "decode_warnings": decode_warns, "decode_by_file": enc_files, "selects": ctx.sel_list}
    return meta, scenes
