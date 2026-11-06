"""多 agent 并发存储。

<data>/<book>/<agent>/profile.json   系统变量 s、已读 seen、统计 stats（跨周目）
<data>/<book>/<agent>/run.json       当前这一局的 state
<data>/<book>/<agent>/saves/<slot>.json   存档位：auto（每到选项自动存）、quick、1..99
同一 agent+书 的操作串行（进程内锁 + flock 文件锁），不同 agent 完全并行；所有写都是 tmp+rename 原子替换。
"""
import contextlib
import json
import os
import re
import threading
import time

try:
    import fcntl
except ImportError:  # Windows：只用进程内锁
    fcntl = None

AGENT_RE = re.compile(r"^[A-Za-z0-9_\-.\u3040-\u30ff\u3400-\u9fff]{1,40}$")
SLOT_RE = re.compile(r"^(auto|quick|[1-9][0-9]?)$")

_locks = {}
_locks_guard = threading.Lock()


class StoreError(ValueError):
    pass


def check_agent(agent):
    if not agent or not AGENT_RE.match(agent) or agent in (".", ".."):
        raise StoreError("agent 名不合法（1-40 位字母数字/中日文/_-.）: %r" % agent)
    return agent


def check_slot(slot):
    slot = str(slot)
    if not SLOT_RE.match(slot):
        raise StoreError("存档位只能是 auto / quick / 1-99: %r" % slot)
    return slot


def _write(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = "%s.tmp%d.%d" % (path, os.getpid(), threading.get_ident())
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, path)


def _read(path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default


class Store(object):
    def __init__(self, root):
        self.root = root
        os.makedirs(root, exist_ok=True)

    def dir(self, book, agent):
        return os.path.join(self.root, book, check_agent(agent))

    @contextlib.contextmanager
    def session(self, book, agent, readonly=False):
        """with store.session(book, agent) as S: S.profile / S.run 可改，退出时一起写回。
        readonly=True：只看（status/log 等），不建目录、不写回——旁观不会凭空多出一个玩家。"""
        d = self.dir(book, agent)
        if readonly and not os.path.isdir(d):
            yield _Session(self, book, agent, d)
            return
        key = (book, agent)
        with _locks_guard:
            lk = _locks.setdefault(key, threading.Lock())
        with lk:
            os.makedirs(d, exist_ok=True)
            lf = open(os.path.join(d, ".lock"), "a")
            try:
                if fcntl:
                    fcntl.flock(lf, fcntl.LOCK_EX)
                s = _Session(self, book, agent, d)
                yield s
                if not readonly:
                    s._flush()
            finally:
                if fcntl:
                    fcntl.flock(lf, fcntl.LOCK_UN)
                lf.close()

    def peek_run(self, book, agent):
        """不加锁只读当前这局（拿语言等设置用）。"""
        return _read(os.path.join(self.dir(book, agent), "run.json"))

    def agents(self, book):
        p = os.path.join(self.root, book)
        if not os.path.isdir(p):
            return []
        out = []
        for a in sorted(os.listdir(p)):
            if not os.path.isfile(os.path.join(p, a, "profile.json")):
                continue
            prof = _read(os.path.join(p, a, "profile.json"), {}) or {}
            run = _read(os.path.join(p, a, "run.json")) or {}
            out.append({"agent": a, "stats": prof.get("stats", {}), "run": {
                "scene": run.get("scene"), "turn": run.get("turn"), "pending": bool(run.get("pending")),
                "ended": run.get("ended"), "choices": len([c for c in run.get("choices") or [] if not c.get("auto")]),
                "updated": prof.get("updated")}})
        return out


class _Session(object):
    def __init__(self, store, book, agent, d):
        self.store, self.book, self.agent, self.d = store, book, agent, d
        self.profile = _read(os.path.join(d, "profile.json")) or {
            "s": {}, "seen": {}, "stats": {"created": time.time(), "lines": 0, "choices": 0, "saves": 0,
                                            "loads": 0, "rewinds": 0, "games": 0, "endings": []}}
        self.run = _read(os.path.join(d, "run.json"))
        self._dirty_run = False

    def set_run(self, state):
        self.run = state
        self._dirty_run = True

    def touch_run(self):
        self._dirty_run = True

    def save_slot(self, slot, meta):
        slot = check_slot(slot)
        if not self.run:
            raise StoreError("还没开始游戏，没东西可存")
        _write(os.path.join(self.d, "saves", slot + ".json"), {"meta": dict(meta, t=time.time()), "state": self.run})

    def load_slot(self, slot):
        slot = check_slot(slot)
        d = _read(os.path.join(self.d, "saves", slot + ".json"))
        if not d:
            raise StoreError("存档位 %s 是空的" % slot)
        return d

    def slots(self):
        p = os.path.join(self.d, "saves")
        out = []
        if os.path.isdir(p):
            for fn in os.listdir(p):
                if fn.endswith(".json"):
                    d = _read(os.path.join(p, fn)) or {}
                    out.append(dict(slot=fn[:-5], **(d.get("meta") or {})))
        key = lambda x: (0 if x["slot"] == "auto" else 1 if x["slot"] == "quick" else 2,
                         int(x["slot"]) if x["slot"].isdigit() else 0)
        return sorted(out, key=key)

    def _flush(self):
        self.profile["updated"] = time.time()
        _write(os.path.join(self.d, "profile.json"), self.profile)
        if self._dirty_run and self.run is not None:
            _write(os.path.join(self.d, "run.json"), self.run)
