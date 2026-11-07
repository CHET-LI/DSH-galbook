"""中间格式 galbook/1（引擎无关）。完整说明见 SCHEMA.md。

books/<slug>/story/story.json
  {"format": "galbook/1", "title", "engine", "importer", "entry": {"scene", "label"},
   "scenes": {"<id>": {"title", "file", "tags": [...], "route"}},
   "routes": [{"id", "title", "start": {"scene", "label"}}],
   "system_vars": [...], "stats": {...}, "warnings": [...]}
books/<slug>/story/scenes/<file>.json
  {"id", "title", "ops": [ {op...}, ... ]}

op 一览（任何 op 都可带 "if": "<条件>"，条件不成立就跳过这一条）
  say     {"who": "灯", "text": "「…」", "voice": "ak_0001"}     who="" 是旁白
  bg      {"img": "assets/画像/bg_001.bmp" | null}                背景（null=清掉）
  cg      {"img": ... | null}                                     事件图（盖整页）
  sprite  {"name": "灯", "img": ... | null, "pos": "center"}      立绘（img=null 下场）
  sprites_clear {}
  bgm     {"name": "bgm006" | null}
  label   {"name": "MAIN"}
  choice  {"id": "sel1", "prompt": "", "options": [{"text", "goto": {"scene", "label"}, "set", "if"}],
           "auto_single": false}
  jump    {"scene": "<id>"?, "label": "<name>"?}                  省略 scene = 本场景
  call    {"scene"?, "label"?}      ret {}
  set     {"expr": "f.x = 1; s.clear_a = 1"}
  event   {"name": "endroll" | "movie" | ..., "arg": ...}         只做标记，给 agent 看
  end     {"kind": "ending" | "title" | "stop", "name": "..."}
"""
import json
import os
import threading

FORMAT = "galbook/1"
OPS = {"say", "bg", "cg", "sprite", "sprites_clear", "bgm", "label", "choice", "jump", "call", "ret",
       "set", "event", "end"}
EXITS = ("choice", "jump", "call", "ret", "end")


class StoryError(ValueError):
    pass


class Scene(object):
    __slots__ = ("id", "title", "ops", "labels", "tags", "route", "says")

    def __init__(self, sid, data, meta=None):
        meta = meta or {}
        self.id = sid
        self.title = data.get("title") or meta.get("title") or sid
        self.ops = data.get("ops") or []
        self.tags = list(meta.get("tags") or data.get("tags") or [])
        self.route = meta.get("route") or data.get("route") or ""
        self.labels = {}
        self.says = 0
        for i, op in enumerate(self.ops):
            if op.get("op") == "label":
                self.labels.setdefault(op.get("name"), i)
            elif op.get("op") == "say":
                self.says += 1


class Story(object):
    """已加载的一本可玩剧本（只读，多线程共享）。"""

    def __init__(self, meta, scenes, base_dir=None):
        self.meta = meta
        self.title = meta.get("title", "")
        self.entry = meta.get("entry") or {}
        self.scenes = scenes          # id -> Scene
        self.base_dir = base_dir
        self.routes = meta.get("routes") or []
        self.mode = meta.get("mode", "branch")

    def scene(self, sid):
        sc = self.scenes.get(sid)
        if sc is None:
            raise StoryError("剧本里没有场景 %r" % sid)
        return sc

    def first_say(self, sid, pc, look=200):
        """从 (sid, pc) 往后找第一句台词的位置（跟着无条件 jump 走），找不到返回 None。用于「新内容」标记。"""
        for _ in range(8):
            sc = self.scenes.get(sid)
            if sc is None:
                return None
            for j in range(pc, min(len(sc.ops), pc + look)):
                op = sc.ops[j]
                k = op.get("op")
                if k == "say":
                    return sid, j
                if k in ("choice", "end", "call", "ret") or (k == "jump" and op.get("if")):
                    return None
                if k == "jump":
                    try:
                        sid, pc = self.resolve(op.get("scene"), op.get("label"), sid)
                    except StoryError:
                        return None
                    break
            else:
                return None
        return None

    @property
    def warnings(self):
        """可疑但不致命：分支被压成直线这类。跟 problems（真的坏了）分开。"""
        if not hasattr(self, "_warnings"):
            w = []
            ch = self.op_counts.get("choice", 0)
            if len(self.routes) > 1 and ch == 0:
                w.append("这本标了 %d 条路线，但全库 0 个选择点——转换时选项可能被当成普通台词吞掉了"
                         % len(self.routes))
            elif len(self.scenes) > 20 and ch == 0:
                w.append("全库 %d 场、0 个选择点；若原作有分支，检查转换器是否丢了 .select / 选项块"
                         % len(self.scenes))
            self._warnings = w
        return self._warnings

    @property
    def op_counts(self):
        """全库 op 计数（say/choice/jump/end…）。choice 为 0 的分支书 = 转换时把选项丢了。"""
        if not hasattr(self, "_op_counts"):
            c = {}
            for sc in self.scenes.values():
                for op in sc.ops:
                    k = op.get("op")
                    c[k] = c.get(k, 0) + 1
            self._op_counts = c
        return self._op_counts

    def _count(self):
        if not hasattr(self, "_counts"):
            cgs, ends = set(), set()
            for sc in self.scenes.values():
                for op in sc.ops:
                    if op.get("op") == "cg" and op.get("img"):
                        cgs.add(op["img"])
                    elif op.get("op") == "end" and (op.get("kind") or "ending") == "ending":
                        ends.add((sc.id, op.get("name")))
            self._counts = (len(cgs), len(ends))
        return self._counts

    def cg_total(self):
        return self._count()[0]

    def endings_total(self):
        return self._count()[1]

    @property
    def problems(self):
        """加载后能查出来的结构问题（没出口的场景等）；空列表 = 没发现。"""
        if not hasattr(self, "_problems"):
            probs = []
            for sid, sc in self.scenes.items():
                if not any(op.get("op") in EXITS for op in sc.ops):
                    probs.append("%s（%s）: 没有出口（缺 choice / jump / end / ret）" % (sid, sc.title))
            self._problems = probs
        return self._problems

    def resolve(self, scene, label, here=None):
        sid = scene or here
        sc = self.scene(sid)
        if label in (None, ""):
            return sid, 0
        if label not in sc.labels:
            raise StoryError("场景 %r 里没有标签 %r" % (sid, label))
        return sid, sc.labels[label]


def validate(meta, scene_datas):
    """返回问题清单（空 = 通过）。scene_datas: id -> scene dict"""
    probs = []
    if meta.get("format") != FORMAT:
        probs.append("format 不是 %s" % FORMAT)
    labels = {}
    for sid, d in scene_datas.items():
        labels[sid] = {op.get("name") for op in d.get("ops", []) if op.get("op") == "label"}
    def chk(where, sc, lb):
        if sc is not None and sc not in scene_datas:
            probs.append("%s: 跳到不存在的场景 %r" % (where, sc))
        elif lb not in (None, "") and lb not in labels.get(sc, set()):
            probs.append("%s: 场景 %r 没有标签 %r" % (where, sc, lb))
    e = meta.get("entry") or {}
    chk("entry", e.get("scene"), e.get("label"))
    for sid, d in scene_datas.items():
        ops_ = d.get("ops") or []
        if not any(op.get("op") in EXITS for op in ops_):
            probs.append("%s（%s）: 场景没有出口——没有 choice / jump / end / ret，"
                         "玩家会卡在最后一句（多半是转换时丢了控制流）" % (sid, d.get("title") or sid))
    for sid, d in scene_datas.items():
        for i, op in enumerate(d.get("ops", [])):
            k = op.get("op")
            w = "%s#%d" % (sid, i)
            if k not in OPS:
                probs.append("%s: 未知 op %r" % (w, k))
            if op.get("click") is not None:     # 只校验，不改任何 op 的语义（点击由 play.py 处理）
                ck = op["click"]
                if k != "say" or not isinstance(ck, dict) or not (ck.get("set") or ck.get("goto")):
                    probs.append("%s: click 只能挂在 say 上，且要有 set 或 goto" % w)
                elif ck.get("goto"):
                    chk(w + ".click", ck["goto"].get("scene") or sid, ck["goto"].get("label"))
            elif k in ("jump", "call"):
                chk(w, op.get("scene") or sid, op.get("label"))
            elif k == "choice":
                if not op.get("options"):
                    probs.append("%s: 选项为空" % w)
                for j, o in enumerate(op.get("options") or []):
                    g = o.get("goto") or {}
                    chk("%s.opt%d" % (w, j), g.get("scene") or sid, g.get("label"))
    return probs


def save_story(out_dir, meta, scene_datas):
    """写出 story.json + scenes/*.json（原子写）。返回写出的文件数。"""
    os.makedirs(os.path.join(out_dir, "scenes"), exist_ok=True)
    meta = dict(meta)
    meta["format"] = FORMAT
    scenes_meta = meta.setdefault("scenes", {})
    n = 0
    for i, (sid, d) in enumerate(scene_datas.items(), 1):
        fn = "scenes/s%04d.json" % i
        m = scenes_meta.setdefault(sid, {})
        m.setdefault("title", d.get("title") or sid)
        m["file"] = fn
        m["says"] = sum(1 for op in d.get("ops", []) if op.get("op") == "say")
        _atomic_json(os.path.join(out_dir, fn), dict(d, id=sid))
        n += 1
    _atomic_json(os.path.join(out_dir, "story.json"), meta)
    return n + 1


def _atomic_json(path, obj):
    tmp = path + ".tmp%d" % os.getpid()
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, path)


_cache = {}
_cache_lock = threading.Lock()


def load_story(story_dir):
    """按 story.json 的 mtime 缓存；改了剧本不用重启服务。"""
    sj = os.path.join(story_dir, "story.json")
    st = os.stat(sj)
    key = (story_dir, st.st_mtime_ns, st.st_size)
    with _cache_lock:
        hit = _cache.get(story_dir)
        if hit and hit[0] == key:
            return hit[1]
    with open(sj, encoding="utf-8") as f:
        meta = json.load(f)
    if meta.get("format") != FORMAT:
        raise StoryError("%s 不是 %s 格式" % (sj, FORMAT))
    scenes = {}
    for sid, m in (meta.get("scenes") or {}).items():
        with open(os.path.join(story_dir, m["file"]), encoding="utf-8") as f:
            scenes[sid] = Scene(sid, json.load(f), m)
    story = Story(meta, scenes, story_dir)
    with _cache_lock:
        _cache[story_dir] = (key, story)
    return story


def story_from_dict(meta, scene_datas):
    """内存里直接构造（legacy 书稿适配、测试用）。"""
    scenes = {sid: Scene(sid, d, (meta.get("scenes") or {}).get(sid)) for sid, d in scene_datas.items()}
    return Story(meta, scenes)
