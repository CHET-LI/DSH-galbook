"""对外的「玩」操作：new / next / choose / save / load / saves / rewind / log / status / profile / click。
web.py 和命令行都调这里。每个操作在 agent 自己的锁里完成。"""
import copy
import os
import random
import time

from . import engine
from .expr import evaluate, assign, ExprError
from .ir import load_story, StoryError
from .importers import legacy
from .store import Store, StoreError

READONLY = ("status", "saves", "log", "profile", "gallery")
ACTIONS = ("new", "next", "choose", "save", "load", "saves", "rewind", "log", "status", "profile", "persona", "gallery", "click")
SLUG_OK = lambda s: bool(s) and "/" not in s and "\\" not in s and not s.startswith(".")


class Library(object):
    def __init__(self, books_dir, data_dir, demo=None):
        self.books_dir = books_dir
        self.store = Store(data_dir)
        # 装完就能玩：books 不存在或空的时候，自动装自带演示书（npm 包场景）
        # 关掉：demo=False，或环境变量 GALBOOK_NO_DEMO=1（命令行 --no-demo 就是设这个）
        if demo is None:
            from .demo_boot import demo_enabled
            demo = demo_enabled()
        try:
            if not demo:
                raise StopIteration
            import sys as _sys
            from .demo_boot import empty, ensure_demo_books
            if empty(books_dir):
                n = ensure_demo_books(books_dir)
                if n:
                    # 只能写 stderr：MCP 走 stdio 时 stdout 是协议通道
                    print("（books 目录是空的，已自动装入 %d 本演示书；不想要：--no-demo 或 GALBOOK_NO_DEMO=1）" % n,
                          file=_sys.stderr)
        except (Exception, StopIteration):
            pass

    # ---- 书 ----
    def books(self):
        out = []
        if not os.path.isdir(self.books_dir):
            return out
        for slug in sorted(os.listdir(self.books_dir)):
            try:
                st = self.story(slug)
            except Exception as e:  # noqa
                if os.path.isfile(os.path.join(self.books_dir, slug, "book.json")):
                    out.append({"slug": slug, "playable": False, "error": str(e)[:200]})
                continue
            out.append({"slug": slug, "title": st.title or slug, "mode": st.mode, "engine": st.meta.get("engine", ""),
                        "scenes": len(st.scenes), "routes": [r.get("title") for r in st.routes],
                        "players": len(self.store.agents(slug)),
                        "problem_count": len(st.problems), "problems": st.problems[:20],
                        "choices": st.op_counts.get("choice", 0), "jumps": st.op_counts.get("jump", 0),
                        "warnings": st.warnings})
        return out

    def story(self, slug):
        if not SLUG_OK(slug):
            raise StoryError("书名不合法: %r" % slug)
        d = os.path.join(self.books_dir, slug)
        if os.path.isfile(os.path.join(d, "story", "story.json")):
            return load_story(os.path.join(d, "story"))
        if os.path.isfile(os.path.join(d, "book.json")):
            return legacy.load(d)
        raise StoryError("没有这本书: %s" % slug)

    # ---- 玩 ----
    def act(self, slug, agent, action, **kw):
        story = self.story(slug)
        fn = getattr(self, "_a_" + action, None)
        if fn is None:
            raise engine.PlayError("不认识的操作 %r（可用：%s）" % (action, " ".join(ACTIONS)))
        with self.store.session(slug, agent, readonly=action in READONLY) as S:
            r = fn(story, S, **kw)
            r.setdefault("book", slug)
            r.setdefault("agent", agent)
            return r

    def _need_run(self, S):
        if not S.run:
            raise engine.PlayError("还没开始。先 new（新游戏）或 load（读档）")
        return S.run

    def _a_new(self, story, S, h="fold", mode="normal", hints="0", lang=None, **_):
        st = engine.new_state(story, h=h, mode=mode, hints=hints, lang=lang or S.profile.get("lang") or "zh")
        S.set_run(st)
        S.profile["stats"]["games"] = S.profile["stats"].get("games", 0) + 1
        r = self._advance_clicks(story, S, st, 0, False)
        S.profile["stats"]["lines"] = S.profile["stats"].get("lines", 0) + len(r["lines"])
        self._decorate(story, S, st, r)
        return {"ok": True, "msg": "新游戏开始（第 %d 周目）" % S.profile["stats"]["games"], "state": r,
                "opts": st["opts"], "system_vars": S.profile["s"]}

    def _a_next(self, story, S, n=20, skip_read=False, **_):
        st = self._need_run(S)
        if st.get("ended"):
            # 已经结束：幂等返回，不再吐一遍同样的结尾（灵犀实测反馈）
            return {"ok": True, "no_new": True, "msg": "已经结束了，没有新内容（想换条路：rewind / load / new）",
                    "state": {"lines": [], "ended": st["ended"]}}
        n = max(1, min(int(n or 20), 200))
        before_end = st.get("ended")
        st.pop("_click", None)          # 上一批的「可点」只在那一批有效（原作的点击也只在那一句上）
        r = self._advance_clicks(story, S, st, n, bool(skip_read))
        S.touch_run()
        S.profile["stats"]["lines"] = S.profile["stats"].get("lines", 0) + len(r["lines"])
        if r.get("choice") and not (st.get("_autosaved_at") == [st["scene"], st["pc"], st["turn"]]):
            st["_autosaved_at"] = [st["scene"], st["pc"], st["turn"]]
            S.save_slot("auto", self._meta(story, st, "到选项自动存"))
        if r.get("cg_seen"):
            got = S.profile.setdefault("cg", [])
            got.extend(c for c in dict.fromkeys(r["cg_seen"]) if c not in got)
        self._decorate(story, S, st, r)
        if st.get("ended") and not before_end:
            e = st["ended"]
            S.profile["stats"].setdefault("endings", []).append({"kind": e.get("kind"), "name": e.get("name"),
                                                                 "t": time.time(), "turn": st.get("turn")})
        return {"ok": True, "state": r, "opts": st.get("opts")}

    # ---- 点击（特殊机制：比如某句台词时点时钟，才会出现隐藏选项）----
    @staticmethod
    def _click_of(story, ln):
        try:
            return story.scene(ln["scene"]).ops[ln["pc"]].get("click")
        except Exception:  # noqa
            return None

    def _advance_clicks(self, story, S, st, n, skip_read):
        """和 engine.advance 一样推进；剧本里没有 click 时零开销。
        有 click 的句子且条件成立：那一行带上 mark=◇，并把「刚读完那一句」的状态存进 st["_click"]，
        之后 do=click 就回到那一刻再点。返回的内容和不带 click 时完全一样（不提前停、不解释）。"""
        sysv, seen = S.profile["s"], S.profile["seen"]
        if not has_clicks(story):
            return engine.advance(story, st, sysv, seen, n=n, skip_read=skip_read)
        st0, sv0 = copy.deepcopy(st), copy.deepcopy(sysv)
        r = engine.advance(story, st, sysv, seen, n=n, skip_read=skip_read)
        cand = [j for j, ln in enumerate(r["lines"]) if not ln.get("folded") and self._click_of(story, ln)]
        if not cand:
            return r
        # 有候选：从推进前的状态逐段重放，在每个候选句停一下，按「那一刻」的变量判断能不能点
        st.clear(); st.update(st0)
        sysv.clear(); sysv.update(sv0)
        parts, done = [], 0
        for j in cand:
            seg = engine.advance(story, st, sysv, seen, n=j + 1 - done, skip_read=skip_read)
            parts.append(seg)
            done += len(seg["lines"])
            if done != j + 1 or seg.get("choice") or seg.get("ended"):
                break                               # 重放和第一次不一致（不该发生）：不标记，照常往下
            ln = seg["lines"][-1]
            ck = self._click_of(story, ln)
            try:
                ok = evaluate(ck.get("if"), st["f"], sysv)
            except ExprError:
                ok = False
            if ok:
                ln["mark"] = "◇"
                snap = {k: v for k, v in st.items() if k != "_click"}
                st["_click"] = {"scene": ln["scene"], "pc": ln["pc"], "state": copy.deepcopy(snap),
                                "s": copy.deepcopy(sysv)}
        if done < n and not (parts and (parts[-1].get("choice") or parts[-1].get("ended"))):
            parts.append(engine.advance(story, st, sysv, seen, n=n - done, skip_read=skip_read))
        out = dict(parts[-1])
        out["lines"] = [ln for p in parts for ln in p["lines"]]
        out["skipped"] = sum(p.get("skipped", 0) for p in parts)
        for k in ("cg_seen", "events", "warnings"):
            v = [x for p in parts for x in (p.get(k) or [])]
            if v:
                out[k] = v
        return out

    def _a_click(self, story, S, **_):
        st = self._need_run(S)
        c = st.get("_click")
        if not c:
            return {"ok": True, "msg": "点了一下，什么也没发生。", "clicked": False}
        ck = (story.scene(c["scene"]).ops[c["pc"]].get("click") or {}) if c["scene"] in story.scenes else {}
        new = c["state"]
        sysv = S.profile["s"]
        sysv.clear(); sysv.update(c.get("s") or {})
        if ck.get("set"):
            try:
                assign(ck["set"], new["f"], sysv)
            except ExprError as e:
                raise engine.PlayError("点击效果执行失败：%s" % e)
        cid = str(ck.get("id") or "%s#%s" % (c["scene"], c["pc"]))
        new["f"]["click_" + cid] = 1                  # 存档里记下：这一局在这里点过
        found = S.profile.setdefault("clicks", [])    # 跨周目记下：发现过哪些
        if cid not in found:
            found.append(cid)
        g = ck.get("goto") or {}
        if g:
            new["scene"], new["pc"] = story.resolve(g.get("scene"), g.get("label"), c["scene"])
        new.pop("pending", None)
        S.set_run(new)
        S.profile["stats"]["clicks"] = S.profile["stats"].get("clicks", 0) + 1
        return {"ok": True, "msg": "点了一下。", "clicked": True, "where": engine.where(story, new)}

    def _a_choose(self, story, S, i=None, reason="", **_):
        st = self._need_run(S)
        st.pop("_click", None)
        p = st.get("pending")
        if p and str(i).lower() == "random":
            i = random.choice(p["options"])["i"]
            reason = reason or "（随机）"
        key = None
        if p:
            o = next((o for o in p["options"] if str(o["i"]) == str(i)), None)
            if o is not None:
                key = "%s:%s:%s" % (p["scene"], p["pc"], o["k"])
        c = engine.choose(story, st, S.profile["s"], i, reason or "")
        if key:
            picked = S.profile.setdefault("picked", [])
            if key not in picked:
                picked.append(key)
        S.touch_run()
        S.profile["stats"]["choices"] = S.profile["stats"].get("choices", 0) + 1
        if reason:
            S.profile["stats"]["reasons"] = S.profile["stats"].get("reasons", 0) + 1
        return {"ok": True, "chosen": c, "where": engine.where(story, st)}

    def _a_save(self, story, S, slot="quick", note="", **_):
        st = self._need_run(S)
        self._ironman(S, "手动存档")
        S.save_slot(slot, self._meta(story, st, note))
        S.profile["stats"]["saves"] = S.profile["stats"].get("saves", 0) + 1
        return {"ok": True, "msg": "已存到 %s" % slot, "where": engine.where(story, st)}

    def _ironman(self, S, what):
        if S.run and (S.run.get("opts") or {}).get("mode") == "ironman":
            raise engine.PlayError("铁人模式这一局不能%s（选了就认；想重来就 new）" % what)

    def _a_load(self, story, S, slot="quick", **_):
        self._ironman(S, "读档")
        d = S.load_slot(slot)
        st = d["state"]
        if st.get("scene") not in story.scenes:
            raise engine.PlayError("这个存档指向的场景 %r 在当前剧本里没有了（剧本重建过？）" % st.get("scene"))
        if st.get("pending"):
            st["pending"]["shown_at"] = time.time()
        S.set_run(st)
        S.profile["stats"]["loads"] = S.profile["stats"].get("loads", 0) + 1
        r = self._advance_clicks(story, S, st, 0, False)
        self._decorate(story, S, st, r)
        return {"ok": True, "msg": "读档 %s" % slot, "meta": d.get("meta"), "state": r, "opts": st.get("opts"),
                "recent": [dict(who=x["who"], text=x["text"]) for x in st.get("log", [])[-5:]]}

    def _a_saves(self, story, S, **_):
        return {"ok": True, "saves": S.slots()}

    def _a_rewind(self, story, S, steps=1, **_):
        st = self._need_run(S)
        self._ironman(S, "回溯")
        new = engine.rewind(st, steps)
        S.set_run(new)
        S.profile["stats"]["rewinds"] = S.profile["stats"].get("rewinds", 0) + 1
        r = engine.advance(story, new, S.profile["s"], S.profile["seen"], n=0)
        self._decorate(story, S, new, r)
        return {"ok": True, "msg": "回到选项点", "state": r, "opts": new.get("opts")}

    def _a_log(self, story, S, n=30, **_):
        st = self._need_run(S)
        n = max(1, min(int(n or 30), 300))
        return {"ok": True, "log": st.get("log", [])[-n:], "choices": st.get("choices", [])}

    def _a_status(self, story, S, **_):
        st = S.run
        r = {"ok": True, "title": story.title, "mode": story.mode, "started": bool(st),
             "routes": [r.get("title") for r in story.routes], "stats": S.profile["stats"],
             "system_vars": S.profile["s"], "saves": [x["slot"] for x in S.slots()]}
        if st:
            r["state"] = engine.peek(story, st)
            self._decorate(story, S, st, r["state"])
            r["opts"] = st.get("opts")
            r["choices_made"] = st.get("choices", [])[-10:]
        return r

    def _a_profile(self, story, S, **_):
        seen = S.profile.get("seen", {})
        total = sum(sc.says for sc in story.scenes.values()) or 1
        got = sum(min(b - a + 1, 10 ** 9) for rs in seen.values() for a, b in rs)
        return {"ok": True, "stats": S.profile["stats"], "system_vars": S.profile["s"],
                "read_ratio": round(min(1.0, got / total), 4), "seen_scenes": len(seen),
                "humanlike": humanlike(S.profile, S.run)}

    def _a_persona(self, story, S, text=None, **_):
        """人设：每个 agent 自己的性格/口味，选项时会提醒（让不同 agent 走出不同的路）。text 为空 = 只看。"""
        if text is not None:
            S.profile["persona"] = str(text).strip()[:600]
            return {"ok": True, "msg": "人设已记下" if S.profile["persona"] else "人设已清空", "persona": S.profile["persona"]}
        return {"ok": True, "persona": S.profile.get("persona", "")}

    def _a_gallery(self, story, S, **_):
        """收集进度：结局、路线、CG、已读。"""
        st = S.profile.get("stats", {})
        got_end = list(dict.fromkeys(e.get("name", "") for e in st.get("endings", []) if e.get("kind") == "ending"))
        seen = S.profile.get("seen", {})
        routes = [r.get("title") for r in story.routes]
        seen_routes = sorted({story.scenes[s].route for s in seen if s in story.scenes and story.scenes[s].route})
        total = sum(sc.says for sc in story.scenes.values()) or 1
        got = sum(b - a + 1 for rs in seen.values() for a, b in rs)
        cg_all = story.cg_total()
        return {"ok": True, "endings": got_end, "endings_total": story.endings_total(),
                "routes": routes, "routes_seen": seen_routes,
                "cg_seen": len(S.profile.get("cg", [])), "cg_total": cg_all,
                "read_ratio": round(min(1.0, got / total), 4), "games": st.get("games", 0)}

    def _decorate(self, story, S, st, r):
        """给选项加标记（hints 打开时）和人设提醒。"""
        c = r.get("choice")
        if not c:
            return
        if (st.get("opts") or {}).get("hints") and st.get("pending"):
            picked = set(S.profile.get("picked", []))
            seen = S.profile.get("seen", {})
            p = st["pending"]
            op = story.scene(p["scene"]).ops[p["pc"]]
            for o, po in zip(c["options"], p["options"]):
                marks = []
                if "%s:%s:%s" % (p["scene"], p["pc"], po["k"]) in picked:
                    marks.append("picked")
                g = (op["options"][po["k"]].get("goto") or {})
                try:
                    tsid, tpc = story.resolve(g.get("scene"), g.get("label"), p["scene"]) if g else (p["scene"], p["pc"] + 1)
                    fs = story.first_say(tsid, tpc)
                    if fs and not engine.seen_has(seen, fs[0], fs[1]):
                        marks.append("new")
                except Exception:  # noqa
                    pass
                if marks:
                    o["marks"] = marks
        if S.profile.get("persona"):
            c["persona"] = S.profile["persona"]

    def _meta(self, story, st, note):
        sc = story.scenes.get(st.get("scene"))
        last = (st.get("log") or [{}])[-1]
        return {"title": sc.title if sc else "", "turn": st.get("turn"), "note": (note or "")[:120],
                "preview": ((last.get("who") + "：") if last.get("who") else "") + engine.plain(last.get("text", ""))[:60],
                "pending": bool(st.get("pending"))}


def has_clicks(story):
    """剧本里有没有可点的句子（say 上带 click 字段）；结果缓存在 story 上。"""
    v = getattr(story, "_gb_has_clicks", None)
    if v is None:
        v = any(op.get("click") for sc in story.scenes.values() for op in sc.ops)
        try:
            story._gb_has_clicks = v
        except AttributeError:
            pass
    return v


def humanlike(profile, run):
    """「像不像人」的几个可量化指标（不打分，给人看趋势）。"""
    st = profile.get("stats", {})
    ch = (run or {}).get("choices") or []
    thinks = [c["think_s"] for c in ch if c.get("think_s") is not None and not c.get("auto")]
    with_reason = [c for c in ch if (c.get("reason") or "").strip() and not c.get("auto")]
    picks = [c["i"] for c in ch if not c.get("auto")]
    return {
        "choices_this_game": len([c for c in ch if not c.get("auto")]),
        "reason_rate": round(len(with_reason) / len(picks), 2) if picks else None,
        "median_think_s": sorted(thinks)[len(thinks) // 2] if thinks else None,
        "always_first_option": (all(i == 1 for i in picks) and len(picks) >= 3) if picks else None,
        "lines_per_choice": round(st.get("lines", 0) / max(1, st.get("choices", 0)), 1),
        "saves": st.get("saves", 0), "loads": st.get("loads", 0), "rewinds": st.get("rewinds", 0),
        "endings_seen": len({(e.get("name")) for e in st.get("endings", [])}),
    }
