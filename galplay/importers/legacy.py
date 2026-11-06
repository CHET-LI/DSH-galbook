"""老式书稿（book.json + chNNN.json：按卷分章、一页一句、没有原始选项数据）→ 可玩剧本。

没有脚本里的真实分支，所以：有「共通」卷就先读共通，读完让 agent 选走哪条线（按卷）；
每条线读完算一个结局。mode = "linear"，并在 warnings 里写清楚这是「按卷生成的选项」。"""
import json
import os
import threading

from ..ir import story_from_dict
from .common import is_h_title

_cache = {}
_lock = threading.Lock()


def _load(p):
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def _sig(book_dir):
    bj = os.path.join(book_dir, "book.json")
    st = os.stat(bj)
    return (st.st_mtime_ns, st.st_size)


def load(book_dir):
    sig = _sig(book_dir)
    with _lock:
        hit = _cache.get(book_dir)
        if hit and hit[0] == sig:
            return hit[1]
    meta, scenes = build(book_dir)
    story = story_from_dict(meta, scenes)
    story.mode = "linear"
    with _lock:
        _cache[book_dir] = (sig, story)
    return story


def _sprites(step):
    out = {}
    for i, s in enumerate(step.get("sprites") or []):
        if isinstance(s, str):
            out["#%d" % i] = {"img": s, "pos": "center"}
        elif isinstance(s, dict) and s.get("img"):
            out[s.get("name") or "#%d" % i] = {"img": s["img"], "pos": s.get("pos") or "center"}
    return out


def build(book_dir):
    b = _load(os.path.join(book_dir, "book.json"))
    vols = b.get("volumes")
    if not vols:
        vols = [{"title": "", "chapters": b.get("chapters", [])}]
    scenes, smeta = {}, {}
    vol_entries = []
    for vi, v in enumerate(vols):
        chs = v.get("chapters") or []
        first = None
        prev = None
        for ci, c in enumerate(chs):
            sid = "v%d_%s" % (vi, c.get("id") or ("c%d" % ci))
            path = os.path.join(book_dir, c["file"])
            try:
                d = _load(path)
            except (OSError, ValueError):
                continue
            title = d.get("title") or c.get("title") or sid
            ops = [{"op": "label", "name": "top"}]
            bg = cg = None
            sp = {}
            for st in d.get("steps") or []:
                if st.get("bg") != bg:
                    bg = st.get("bg")
                    ops.append({"op": "bg", "img": bg})
                    cg = None
                if st.get("cg") != cg:
                    cg = st.get("cg")
                    ops.append({"op": "cg", "img": cg})
                ns = _sprites(st)
                if ns != sp:
                    ops.append({"op": "sprites_clear"})
                    for name, x in ns.items():
                        ops.append({"op": "sprite", "name": name, "img": x["img"], "pos": x["pos"]})
                    sp = ns
                who = st.get("speaker") or ""
                if who == "旁白":
                    who = ""
                ops.append({"op": "say", "who": who.split("＠")[0], "text": st.get("text", "")})
            scenes[sid] = {"id": sid, "title": title, "ops": ops}
            smeta[sid] = {"title": title, "route": v.get("title", ""), "tags": ["h"] if is_h_title(title) else []}
            if prev:
                scenes[prev]["ops"].append({"op": "jump", "scene": sid})
            first = first or sid
            prev = sid
        if first:
            vol_entries.append({"title": v.get("title") or b.get("title", ""), "first": first, "last": prev})
    common = [e for e in vol_entries if "共通" in e["title"] or "common" in e["title"].lower()]
    others = [e for e in vol_entries if e not in common]
    start_ops = [{"op": "label", "name": "top"}]
    if len(vol_entries) == 1:
        start_ops.append({"op": "jump", "scene": vol_entries[0]["first"]})
        scenes[vol_entries[0]["last"]]["ops"].append({"op": "end", "kind": "ending", "name": vol_entries[0]["title"]})
    else:
        chooser = {"op": "choice", "id": "route", "prompt": "选一条线读下去（老书稿没有原始选项，按卷生成）",
                   "options": [{"text": e["title"], "goto": {"scene": e["first"]}} for e in others]}
        if common:
            c = common[0]
            start_ops.append({"op": "jump", "scene": c["first"]})
            scenes[c["last"]]["ops"].append(chooser)
        else:
            start_ops.append(chooser)
        for e in others:
            scenes[e["last"]]["ops"].append({"op": "end", "kind": "ending", "name": e["title"]})
    scenes["__start__"] = {"id": "__start__", "title": b.get("title", ""), "ops": start_ops}
    smeta["__start__"] = {"title": b.get("title", "")}
    meta = {"format": "galplay/1", "title": b.get("title", ""), "engine": "book-legacy",
            "importer": "galplay-legacy-1", "mode": "linear", "entry": {"scene": "__start__", "label": "top"},
            "scenes": smeta, "routes": [{"id": e["first"], "title": e["title"]} for e in vol_entries],
            "warnings": ["老书稿没有原始脚本里的选项与跳转；这里的选项是按卷（路线）生成的，不代表游戏原本的分支。"]}
    return meta, scenes
