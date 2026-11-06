"""吉里吉里 KAG / TyranoScript（.ks）→ galbook/1。老游戏（KAG2/KAG3/KAGEX）和新的网页游戏（Tyrano）共用。

认的写法：
  *label|标题                        标签
  ; 注释    @tag a=b 整行指令    [tag a=b] 行内指令
  台词     【名字】「…」 / #名字（Tyrano，到下一个 # 为止） / [nm t="名字"] / @nm t=名字（KAGEX）
           [l] [p] [r] [cm] 断句；没写等待的行按一行一句
  选项     [link target=*x storage=y.ks exp="f.a=1"]文字[endlink] … [s]
           [glink text="文字" target=*x storage=… exp=…] … [s]（Tyrano）   [button graphic=… target=…]
  跳转     [jump storage= target= cond=]  [call …]  [return]  [s]（无选项时 = 停住）
  变量     [eval exp="f.x=1"]  sf.* = 系统变量（跨周目）→ s.*  tf.* → f.tf_*
           [if exp=…] [elsif exp=…] [else] [endif]   [ignore exp=…] [endignore]
  画面     [bg storage=]  @image storage= layer=base|0..n  [chara_show name= face=]  [chara_hide]
           [chara_mod]  [freeimage layer=]  [playbgm storage=] / @bgm  [cm] / [ct]
"""
import os
import re

from .common import SceneB, Assets, read_text, is_h_title

ATTR = re.compile(r'([A-Za-z_][\w\-]*)\s*=\s*("(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\'|[^\s\]]+)|([A-Za-z_][\w\-]*)')
TOK = re.compile(r"\[(?!\[)([^\]]*)\]|([^\[]+)|\[\[")


def parse_attrs(s):
    d = {}
    for m in ATTR.finditer(s):
        if m.group(1):
            v = m.group(2)
            if v[:1] in "\"'" and v[-1:] == v[:1]:
                v = v[1:-1]
            d[m.group(1).lower()] = v
        elif m.group(3):
            d[m.group(3).lower()] = True
    return d


def conv_expr(e):
    if e is None:
        return None
    e = str(e)
    e = re.sub(r"\bsf\.", "s.", e)
    e = re.sub(r"\btf\.", "f.tf_", e)
    e = re.sub(r"\bmp\.", "f.mp_", e)
    e = e.replace("===", "==").replace("!==", "!=")
    return e


def _target(at, cur):
    st = at.get("storage")
    sid = os.path.splitext(os.path.basename(st))[0] if st and st is not True else None
    tg = at.get("target")
    lb = tg[1:] if isinstance(tg, str) and tg.startswith("*") else (tg if isinstance(tg, str) else None)
    return sid, lb


class _Ctx(object):
    def __init__(self, sid):
        self.b = SceneB(sid, sid, tags=["h"] if is_h_title(sid) else [])
        self.buf = []
        self.who = ""
        self.hash_who = None
        self.links = []
        self.link_open = None
        self.ifs = []
        self.nif = 0
        self.sprites = {}


class Importer(object):
    def __init__(self, src, assets=None, entry=None):
        self.src, self.assets, self.entry = src, assets or Assets(), entry
        self.files = {}
        self.scenes = {}
        self.warnings = []
        self.unknown = {}
        self.stats = {"files": 0, "says": 0, "choices": 0, "options": 0, "jumps": 0, "calls": 0, "sets": 0, "ifs": 0}
        self.system_vars = set()

    def build(self):
        for dp, _, fns in os.walk(self.src):
            for fn in sorted(fns):
                if fn.lower().endswith(".ks"):
                    self.files[os.path.splitext(fn)[0]] = os.path.join(dp, fn)
        if not self.files:
            raise ValueError("没找到 .ks")
        for sid in sorted(self.files):
            self._parse(sid)
        ent = self.entry or next((x for x in ("first", "start", "main", "scenario") if x in self.files), sorted(self.files)[0])
        start = SceneB("__start__", "开始", tags=["system"])
        start.add("label", name="top")
        start.add("jump", scene=ent)
        self.scenes["__start__"] = start.data()
        meta = {"format": "galbook/1", "title": "", "engine": "kag", "importer": "galbook-kag-1",
                "entry": {"scene": "__start__", "label": "top"},
                "scenes": {k: {"title": v["title"], "tags": v["tags"]} for k, v in self.scenes.items()},
                "routes": [], "system_vars": sorted(self.system_vars),
                "stats": dict(self.stats, unknown=sorted(self.unknown.items(), key=lambda x: -x[1])[:20],
                              assets=self.assets.report()),
                "warnings": self.warnings[:200]}
        return meta, self.scenes

    # ---- 文本缓冲 ----
    def _flush(self, cx):
        t = "".join(cx.buf).strip()
        cx.buf = []
        if not t:
            return
        who = cx.who or cx.hash_who or ""
        m = re.match(r"^【([^】]{1,16})】\s*(.*)$", t)
        if m:
            who, t = m.group(1), m.group(2)
        cx.b.add("say", who=who, text=t)
        cx.who = ""
        self.stats["says"] += 1

    def _parse(self, sid):
        cx = _Ctx(sid)
        self.stats["files"] += 1
        text = read_text(self.files[sid])
        in_script = False
        for raw in text.splitlines():
            line = raw.rstrip("\r\n")
            s = line.strip()
            if in_script:
                if s.lower().startswith("[endscript") or s.lower().startswith("@endscript"):
                    in_script = False
                continue
            if not s or s.startswith(";") or s.startswith("//"):
                continue
            if s.startswith("*"):
                self._flush(cx)
                cx.b.add("label", name=s[1:].split("|")[0].strip())
                continue
            if s.startswith("#"):
                self._flush(cx)
                nm = s[1:].strip().split(":")[0]
                cx.hash_who = nm or None
                continue
            if s.startswith("@"):
                if s[1:].lower().startswith("iscript"):
                    in_script = True
                    continue
                name, _, rest = s[1:].partition(" ")
                self._tag(cx, name.lower(), parse_attrs(rest))
                continue
            if s.lower().startswith("[iscript"):
                in_script = True
                continue
            had_wait = False
            for m in TOK.finditer(s):
                if m.group(0) == "[[":
                    cx.buf.append("[")
                elif m.group(2) is not None:
                    if cx.link_open is not None:
                        cx.link_open["text"] += m.group(2)
                    else:
                        cx.buf.append(m.group(2))
                else:
                    inner = m.group(1).strip()
                    name, _, rest = inner.partition(" ")
                    name = name.lower()
                    if name in ("l", "p", "cm", "er", "ct"):
                        had_wait = True
                    self._tag(cx, name, parse_attrs(rest))
            if not had_wait and cx.buf and cx.link_open is None:
                self._flush(cx)        # 没写 [l]/[p] 的行：一行一句
        self._flush(cx)
        for lb in cx.ifs:
            cx.b.add("label", name=lb["end"])
        if cx.links:
            self._emit_choice(cx)
        self.scenes[sid] = cx.b.data()

    def _emit_choice(self, cx):
        opts = []
        for l in cx.links:
            o = {"text": l["text"].strip() or "(选项)", "goto": {"scene": l["sid"], "label": l["lb"]}}
            if l.get("exp"):
                o["set"] = conv_expr(l["exp"])
            if l.get("cond"):
                o["if"] = l["cond"]
            opts.append(o)
        cx.b.add("choice", id="c%d" % len(cx.b.ops), options=opts)
        self.stats["choices"] += 1
        self.stats["options"] += len(opts)
        cx.links = []

    @staticmethod
    def _link_cond(cx, at):
        """选项是攒到 [s] 才一起出的，所以要把外层 [if] 的条件记到每个选项上。"""
        cs = [c for lb in cx.ifs for c in [lb.get("cur")] if c]
        own = conv_expr(at.get("cond")) if isinstance(at.get("cond"), str) else None
        if own:
            cs.append(own)
        return " && ".join("(%s)" % c for c in cs) if cs else None

    def _tag(self, cx, name, at):
        cond = conv_expr(at.get("cond")) if isinstance(at.get("cond"), str) else None
        if name in ("l", "p"):
            self._flush(cx)
        elif name in ("r", "br"):
            cx.buf.append("\n") if cx.link_open is None else None
        elif name in ("cm", "er", "ct"):
            self._flush(cx)
        elif name in ("nm", "name", "ns"):
            t = at.get("t") or at.get("text") or at.get("name")
            if isinstance(t, str):
                cx.who = t
        elif name == "link":
            sid, lb = _target(at, cx.b.id)
            cx.link_open = {"text": "", "sid": sid, "lb": lb, "exp": at.get("exp"), "cond": self._link_cond(cx, at)}
        elif name == "endlink":
            if cx.link_open is not None:
                cx.links.append(cx.link_open)
                cx.link_open = None
        elif name in ("glink", "button"):
            sid, lb = _target(at, cx.b.id)
            txt = at.get("text") or at.get("graphic") or "(按钮)"
            if lb or sid:
                cx.links.append({"text": str(txt), "sid": sid, "lb": lb, "exp": at.get("exp"), "cond": self._link_cond(cx, at)})
        elif name == "s":
            self._flush(cx)
            if cx.links:
                self._emit_choice(cx)
            else:
                cx.b.add("end", kind="stop", name="[s] 停住（等待外部操作）")
        elif name in ("jump", "call"):
            self._flush(cx)
            sid, lb = _target(at, cx.b.id)
            op = cx.b.add(name, scene=sid if sid != cx.b.id else None, label=lb)
            if cond:
                op["if"] = cond
            self.stats["calls" if name == "call" else "jumps"] += 1
        elif name == "return":
            self._flush(cx)
            cx.b.add("ret")
        elif name == "eval":
            e = conv_expr(at.get("exp"))
            if e:
                op = cx.b.add("set", expr=e)
                if cond:
                    op["if"] = cond
                self.stats["sets"] += 1
                for m in re.finditer(r"\bs\.(\w+)\s*(?:=|\+=|-=)(?!=)", e):
                    self.system_vars.add(m.group(1))
        elif name in ("if", "ignore"):
            self._flush(cx)
            cx.nif += 1
            lb = {"next": "__if%d_n1" % cx.nif, "end": "__if%d_end" % cx.nif, "k": 1, "n": cx.nif}
            cx.ifs.append(lb)
            e = conv_expr(at.get("exp")) or "false"
            neg = e if name == "ignore" else "!(%s)" % e
            lb["cur"] = ("!(%s)" % e) if name == "ignore" else e
            lb["prev"] = [lb["cur"]]
            cx.b.add("jump", label=lb["next"], **{"if": neg})
            self.stats["ifs"] += 1
        elif name in ("elsif", "else"):
            self._flush(cx)
            if not cx.ifs:
                return
            lb = cx.ifs[-1]
            cx.b.add("jump", label=lb["end"])
            cx.b.add("label", name=lb["next"])
            lb["k"] += 1
            lb["next"] = "__if%d_n%d" % (lb["n"], lb["k"])
            notprev = " && ".join("!(%s)" % c for c in lb.get("prev", []))
            if name == "elsif":
                e = conv_expr(at.get("exp")) or "false"
                cx.b.add("jump", label=lb["next"], **{"if": "!(%s)" % e})
                lb["cur"] = "(%s) && (%s)" % (notprev, e) if notprev else e
                lb.setdefault("prev", []).append(e)
            else:
                lb["cur"] = notprev or None
        elif name in ("endif", "endignore"):
            self._flush(cx)
            if cx.ifs:
                lb = cx.ifs.pop()
                cx.b.add("label", name=lb["next"])
                cx.b.add("label", name=lb["end"])
        elif name == "bg" or (name == "image" and str(at.get("layer", "")).lower() in ("base", "background")):
            self._flush(cx)
            cx.b.add("bg", img=self.assets.find(at.get("storage")) if at.get("storage") else None)
        elif name == "image":
            self._flush(cx)
            layer = str(at.get("layer", "0"))
            cx.b.add("sprite", name="layer" + layer, img=self.assets.find(at.get("storage")), pos=at.get("pos") or "center")
        elif name in ("freeimage", "freelayer"):
            self._flush(cx)
            layer = str(at.get("layer", "0"))
            if layer in ("base", "background"):
                cx.b.add("bg", img=None)
            else:
                cx.b.add("sprite", name="layer" + layer, img=None)
        elif name in ("chara_show", "chara_mod"):
            self._flush(cx)
            nm = at.get("name", "?")
            face = at.get("face") or at.get("storage") or ""
            img = self.assets.find(at.get("storage")) if at.get("storage") else self.assets.find("%s_%s" % (nm, face) if face else str(nm))
            cx.b.add("sprite", name=str(nm), img=img or ("chara:%s%s" % (nm, (":" + face) if face else "")), pos=at.get("pos") or "center")
        elif name == "chara_hide":
            cx.b.add("sprite", name=str(at.get("name", "?")), img=None)
        elif name in ("chara_hide_all", "freeimage_all"):
            cx.b.add("sprites_clear")
        elif name in ("playbgm", "bgm", "fadeinbgm"):
            cx.b.add("bgm", name=at.get("storage") if isinstance(at.get("storage"), str) else None)
        elif name in ("stopbgm", "fadeoutbgm"):
            cx.b.add("bgm", name=None)
        elif name in ("gotostart", "close", "end"):
            self._flush(cx)
            cx.b.add("end", kind="title", how="[%s]" % name)
        elif name in ("macro", "endmacro", "wait", "wt", "trans", "wq", "quake", "move", "wm", "playse", "se", "ws",
                      "position", "font", "resetfont", "delay", "nowait", "endnowait", "locate", "current", "layopt",
                      "backlay", "style", "deffont", "defstyle", "history", "clearsysvar", "clearvar", "seopt",
                      "anim", "kanim", "wa", "vo", "voice", "playvoice", "mask", "mask_off", "chara_new", "chara_face",
                      "chara_config", "showmenubutton", "hidemenubutton", "title", "loadjs", "plugin", "skipstop",
                      "autostop", "cancelskip", "fadeoutse", "stopse", "filter", "free_filter", "layermode", "camera",
                      "reset_camera", "ptext", "free", "wait_cancel", "hidemessage", "showlog", "clickable", "dialog",
                      "image_tag", "emb", "ruby", "graph", "ch", "hch", "add", "rclick", "button_cancel", "cancel"):
            pass
        else:
            self.unknown[name] = self.unknown.get(name, 0) + 1


def build(src, assets=None, entry=None, **_):
    return Importer(src, assets, entry).build()
