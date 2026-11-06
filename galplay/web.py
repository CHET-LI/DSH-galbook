"""HTTP 接口：App(books, data).handle(method, path, query, body) -> (code, content_type, bytes) | None。
独立服务见 server.py；也能嵌进别的 http.server（不是 /play 开头的路径返回 None，交回原服务处理）。

JSON：  GET|POST /play/api/<书>/<agent>/<操作>      参数走 query 或 JSON body
        GET      /play/api/books                     能玩的书
        GET      /play/api/<书>/players              谁在玩、玩到哪（旁观用）
纯文本：GET      /play/t/<书>/<agent>?do=<操作>&...  给 agent 用，省 token（&lang=en 英文框架文字）
        GET      /play/t                             玩法说明（?lang=en）
页面：  GET      /play/                              人看的界面（看 agent 们在玩什么 / 自己玩）
"""
import json
import os
import re
import traceback
from urllib.parse import parse_qs, unquote

from . import engine, VERSION
from .i18n import t, msg
from .play import Library, ACTIONS
from .ir import StoryError
from .store import StoreError

HERE = os.path.dirname(os.path.abspath(__file__))
ERRS = (engine.PlayError, StoryError, StoreError, ValueError)
KW = ("n", "i", "steps", "slot", "note", "reason", "h", "mode", "hints", "lang", "text")

HELP = {"zh": """galplay —— 像人一样玩 galgame（%s）
每个 agent 用自己的名字玩，各自的进度、存档、通关记录互不影响，可以很多个同时玩。

纯文本接口（GET，一行一个操作）：
  /play/t/<书>/<你的名字>?do=status                 现在玩到哪
  /play/t/<书>/<你的名字>?do=persona&text=…         设人设（性格/口味），选项时会提醒你
  /play/t/<书>/<你的名字>?do=new                    新游戏，可选：
        &h=fold|full|skip    H 场景折叠(默认)/展开/整段跳过
        &mode=ironman        铁人模式：不能存读档和回溯，选了就认
        &hints=1             选项旁标「选过」「新内容」
        &lang=en             框架文字用英文
  /play/t/<书>/<你的名字>?do=next&n=20              往下读 n 句（最多 200）；&skip=1 跳过读过的；&img=1 带画面
  /play/t/<书>/<你的名字>?do=choose&i=2&reason=…    选第 2 个，reason 写一句你为什么这么选（i=random 随机）
  /play/t/<书>/<你的名字>?do=save&slot=3&note=…     存档（quick 或 1-99；到选项时会自动存 auto）
  /play/t/<书>/<你的名字>?do=load&slot=3            读档（auto / quick / 1-99）
  /play/t/<书>/<你的名字>?do=saves                  存档列表
  /play/t/<书>/<你的名字>?do=rewind                 回到上一个选项重新选（&steps=2 再往前）
  /play/t/<书>/<你的名字>?do=log&n=30               回想最近 n 句 + 做过的选择
  /play/t/<书>/<你的名字>?do=gallery                收集：结局 / 路线 / CG / 已读
  /play/t/<书>/<你的名字>?do=profile                通关记录、已读比例、「像不像人」的几个数
书单：/play/api/books

怎么玩得像人：
  * 一次读 20~40 句再停下来想想，别一口气读到选项；
  * 选项前回想一下角色和刚才发生的事，按你自己的人设选，reason 写真实理由；
  * 想看别的结局就存档 / 回溯，不要每次都选第 1 个。
""", "en": """galplay — play visual novels like a human (%s)
Each agent plays under its own name with separate progress, saves and clear flags. Many agents can play at once.

Plain-text API (GET, one action per request):
  /play/t/<book>/<name>?do=status                  where am I
  /play/t/<book>/<name>?do=persona&text=…          set your persona (shown to you at every choice)
  /play/t/<book>/<name>?do=new                     new game; options:
        &h=fold|full|skip    adult scenes folded (default) / shown / skipped silently
        &mode=ironman        no saving/loading/rewinding — choices are final
        &hints=1             mark options "picked before" / "new"
        &lang=en             English UI text
  /play/t/<book>/<name>?do=next&n=20               read n lines (max 200); &skip=1 skip read lines; &img=1 show visuals
  /play/t/<book>/<name>?do=choose&i=2&reason=…     pick option 2 and say why (i=random for random)
  /play/t/<book>/<name>?do=save&slot=3&note=…      save (quick or 1-99; slot auto is written at every choice)
  /play/t/<book>/<name>?do=load&slot=3             load (auto / quick / 1-99)
  /play/t/<book>/<name>?do=saves                   list saves
  /play/t/<book>/<name>?do=rewind                  back to the last choice (&steps=2 further back)
  /play/t/<book>/<name>?do=log&n=30                backlog + choices made
  /play/t/<book>/<name>?do=gallery                 endings / routes / CG / read ratio
  /play/t/<book>/<name>?do=profile                 stats and human-likeness numbers
Books: /play/api/books

Playing like a human:
  * read 20-40 lines at a time and pause, don't rush to the next choice;
  * before choosing, recall the characters and what just happened; choose as your persona would and give a real reason;
  * to see other endings, save or rewind — don't always pick option 1.
"""}


class App(object):
    def __init__(self, books_dir, data_dir, default_lang="zh"):
        self.lib = Library(books_dir, data_dir)
        self.default_lang = default_lang

    def handle(self, method, path, query, body=b""):
        """返回 (code, content_type, bytes)；不是 /play 的路径返回 None。"""
        if not (path == "/play" or path.startswith("/play/")):
            return None
        q = {k: v[-1] for k, v in parse_qs(query or "", keep_blank_values=True).items()}
        if body and method == "POST":
            try:
                j = json.loads(body.decode("utf-8") or "{}")
                if isinstance(j, dict):
                    q.update(j)
            except ValueError:
                return self._json(400, {"ok": False, "error": "body 不是 JSON / body is not JSON"})
        lang = q.get("lang") if q.get("lang") in ("zh", "en") else None
        parts = [unquote(p) for p in path.split("/") if p][1:]   # 先切再解码：名字里的 %2F 不会变成路径
        try:
            if not parts:
                return self._file(os.path.join(HERE, "static", "play.html"), "text/html; charset=utf-8")
            if parts[0] in ("t", "help"):
                if len(parts) > 3:
                    raise engine.PlayError("路径多了一段：/play/t/<书>/<名字>?do=…")
                if parts[0] == "help" or len(parts) < 3:
                    return self._text(200, HELP[lang or self.default_lang] % VERSION)
                return self._text_api(parts[1], parts[2], q, lang)
            if parts[0] == "api":
                if parts[1:] == ["books"]:
                    return self._json(200, {"ok": True, "version": VERSION, "books": self.lib.books()})
                if len(parts) == 3 and parts[2] == "players":
                    self.lib.story(parts[1])
                    return self._json(200, {"ok": True, "players": self.lib.store.agents(parts[1])})
                if len(parts) == 4 and parts[3] in ACTIONS:
                    r = self.lib.act(parts[1], parts[2], parts[3], **self._kw(q))
                    return self._json(200, r)
                return self._json(404, {"ok": False, "error": "没有这个接口 / no such endpoint", "help": "/play/t"})
        except ERRS as e:
            if parts and parts[0] == "t":
                lg = lang or self.default_lang
                return self._text(400, t(lg, "error", e=msg(lg, str(e))))
            return self._json(400, {"ok": False, "error": msg(lang or "zh", str(e))})
        except Exception as e:  # noqa
            traceback.print_exc()
            return self._json(500, {"ok": False, "error": "内部错误 / internal error: %s" % type(e).__name__})
        return self._json(404, {"ok": False, "error": "没有这个接口 / no such endpoint"})

    @staticmethod
    def _kw(q):
        kw = {}
        for k in KW:
            if k in q and q[k] is not None and (q[k] != "" or k == "text"):
                kw[k] = q[k]
        if str(q.get("skip", q.get("skip_read", ""))).lower() in ("1", "true", "yes"):
            kw["skip_read"] = True
        return kw

    def _text_api(self, book, agent, q, lang):
        do = q.get("do") or "status"
        if do not in ACTIONS:
            raise engine.PlayError("do 只能是：" + " ".join(ACTIONS))
        img = str(q.get("img", "")) in ("1", "true")
        kw = self._kw(q)
        if do != "new":
            kw.pop("lang", None)
        r = self.lib.act(book, agent, do, **kw)
        lg = lang or ((r.get("opts") or {}).get("lang")) or self._run_lang(book, agent) or self.default_lang
        return self._text(200, render_text(r, do, img, book, agent, lg))

    def _run_lang(self, book, agent):
        try:
            run = self.lib.store.peek_run(book, agent)
            return ((run or {}).get("opts") or {}).get("lang")
        except Exception:  # noqa
            return None

    @staticmethod
    def _json(code, obj):
        return code, "application/json; charset=utf-8", json.dumps(obj, ensure_ascii=False).encode("utf-8")

    @staticmethod
    def _text(code, s):
        return code, "text/plain; charset=utf-8", s.encode("utf-8")

    @staticmethod
    def _file(p, ct):
        with open(p, "rb") as f:
            return 200, ct, f.read()


def _img(p):
    return os.path.splitext(os.path.basename(p))[0] if p else None


def _vis_text(v, lang):
    bits = []
    if v.get("cg"):
        bits.append(t(lang, "vis_cg") + _img(v["cg"]))
    elif v.get("bg"):
        bits.append(t(lang, "vis_bg") + _img(v["bg"]))
    sp = [s.get("name", "") for s in v.get("sprites") or []]
    if sp:
        bits.append(t(lang, "vis_on") + t(lang, "sep").join(sp))
    return "〔" + "｜".join(bits) + "〕" if bits else ""


def _say(x, lang="zh"):
    tx = engine.plain(x.get("text", ""))
    return ("%s%s%s" % (x["who"], ": " if lang == "en" else "：", tx)) if x.get("who") else tx


def restyle(text, book, agent, style):
    """把文本里的「/play/t/书/名字?do=动作&k=v」提示改写成别的接法：
    style="cli"  → galplay do 动作 k=v      style="tool" → galplay_动作(k=v, …)      "http" 不变。"""
    if style not in ("cli", "tool"):
        return text
    pat = re.compile(r"/play/t/%s/%s\?do=(\w+)((?:&[^\s&（(]+)*)" % (re.escape(book), re.escape(agent)))

    def sub(m):
        args = [a for a in m.group(2).split("&") if a]
        args = [a.split("=", 1)[0] + '="%s"' % a.split("=", 1)[1].replace("+", " ") if "+" in a else a for a in args]
        if style == "cli":
            return " ".join(["galplay do " + m.group(1)] + args)
        return "galplay_%s(%s)" % (m.group(1), ", ".join(args))
    text = pat.sub(sub, text)
    return re.sub(r"(?<=[\s（(])&(\w+=)", r"\1", text)


def render_text(r, do, img, book, agent, lang="zh"):
    """把一次操作的结果写成给 agent 看的纯文本（一句一行，最省 token）。"""
    L = []
    base = "/play/t/%s/%s?do=" % (book, agent)
    st = r.get("state")
    if r.get("msg"):
        L.append(msg(lang, r["msg"]))
    if do == "choose":
        c = r["chosen"]
        L.append(t(lang, "you_chose", text=c["text"], i=c["i"], of=c.get("of") or "?"))
        L.append(t(lang, "cont", base=base))
        return "\n".join(L) + "\n"
    if do == "persona":
        p = r.get("persona") or ""
        L.append(t(lang, "persona_now", p=p) if p else t(lang, "persona_none", base=base))
        return "\n".join(L) + "\n"
    if do == "gallery":
        L.append(t(lang, "gallery", e=len(r["endings"]), et=r["endings_total"], names=t(lang, "sep").join(r["endings"]) or "-",
                   rs=len(r["routes_seen"]), rt=len(r["routes"]), routes=t(lang, "sep").join(r["routes_seen"]) or "-",
                   c=r["cg_seen"], ct=r["cg_total"], pct=r["read_ratio"] * 100, g=r["games"]))
        return "\n".join(L) + "\n"
    if do == "saves":
        if not r["saves"]:
            return t(lang, "no_saves") + "\n"
        for s in r["saves"]:
            L.append(t(lang, "save_row", slot=s["slot"], title=s.get("title", ""), turn=s.get("turn", "?"),
                       preview=s.get("preview", ""), note=(t(lang, "note") + s["note"]) if s.get("note") else ""))
        return "\n".join(L) + "\n"
    if do == "log":
        L += [_say(x, lang) for x in r["log"]]
        if r.get("choices"):
            L.append(t(lang, "log_choices"))
            for c in r["choices"]:
                L.append("· %s%s%s%s" % (c.get("title", ""), ": " if lang == "en" else "：", c["text"], t(lang, "reason", r=c["reason"]) if c.get("reason") else ""))
        return "\n".join(L) + "\n"
    if do == "profile":
        L.append(t(lang, "read", pct=r["read_ratio"] * 100, n=r["seen_scenes"]))
        s = r["stats"]
        L.append(t(lang, "stats", g=s.get("games", 0), l=s.get("lines", 0), c=s.get("choices", 0), s=s.get("saves", 0),
                   ld=s.get("loads", 0), rw=s.get("rewinds", 0)))
        if s.get("endings"):
            L.append(t(lang, "endings_seen") + t(lang, "sep").join(dict.fromkeys(e.get("name", "") for e in s["endings"])))
        if r.get("system_vars"):
            L.append(t(lang, "sysvars") + ", ".join("%s=%s" % kv for kv in r["system_vars"].items()))
        L.append(t(lang, "humanlike") + json.dumps(r["humanlike"], ensure_ascii=False))
        return "\n".join(L) + "\n"
    if do == "status" and not r.get("started"):
        L.append(t(lang, "not_started", title=r.get("title", ""), base=base))
        if r.get("saves"):
            L.append(t(lang, "has_saves", s=t(lang, "sep").join(r["saves"]), base=base))
        return "\n".join(L) + "\n"
    if do == "new" and r.get("opts"):
        o = r["opts"]
        L.append(t(lang, "opts", h=o.get("h"), mode=o.get("mode"), hints=int(bool(o.get("hints"))), lg=o.get("lang")))
    if r.get("recent"):
        L.append(t(lang, "recent_load"))
        L += [_say(x, lang) for x in r["recent"]]
        L.append("——")
    if do == "status" and st and st.get("recent"):
        L.append(t(lang, "recent"))
        L += [_say(x, lang) for x in st["recent"]]
        L.append("——")
    if st:
        w = st["where"]
        L.append(t(lang, "line_hdr", title=w.get("title", ""), turn=w.get("turn", 0)))
        if img and not st["lines"]:
            v = _vis_text(st.get("vis") or {}, lang)
            if v:
                L.append(v)
        last_vis = None
        for ln in st["lines"]:
            if img and ln.get("vis"):
                v = _vis_text(ln["vis"], lang)
                if v and v != last_vis:
                    L.append(v)
                    last_vis = v
            L.append(_say(ln, lang))
        if st.get("skipped"):
            L.append(t(lang, "skipped", n=st["skipped"]))
        for e in st.get("events") or []:
            if e.get("event") == "eyecatch" and e.get("arg"):
                L.append(t(lang, "ev_eyecatch", a=e["arg"]))
            elif e.get("event") == "endroll":
                L.append(t(lang, "ev_endroll"))
            elif e.get("event") == "clear":
                L.append(t(lang, "ev_clear", a=e.get("arg")))
        iron = (r.get("opts") or {}).get("mode") == "ironman"
        if st.get("choice"):
            c = st["choice"]
            L.append(t(lang, "choice_hdr", prompt=((": " if lang == "en" else "：") + c["prompt"]) if c.get("prompt") else ""))
            for o in c["options"]:
                mk = [t(lang, "mark_" + m) for m in o.get("marks", [])]
                L.append(" %d. %s%s" % (o["i"], o["text"], ("  〔%s〕" % t(lang, "sep").join(mk)) if mk else ""))
            if c.get("persona"):
                L.append(t(lang, "persona", p=c["persona"][:200]))
            L.append(t(lang, "choose_hint", base=base, auto="" if iron else t(lang, "auto_saved")))
        elif st.get("ended"):
            e = st["ended"]
            L.append(t(lang, "ended", name=e.get("name", ""), kind=t(lang, "kind_" + e.get("kind", "stop"))
                       if e.get("kind") in ("ending", "title", "stop") else e.get("kind")))
            L.append(t(lang, "after_end_iron" if iron else "after_end", base=base))
        elif do in ("next", "new", "load", "rewind", "status"):
            L.append(t(lang, "cont", base=base))
    return "\n".join(L) + "\n"
