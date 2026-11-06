"""导入器共用：建场景、资源解析、统计。"""
import os
import re


class SceneB(object):
    def __init__(self, sid, title, tags=None, route=""):
        self.id, self.title = sid, title
        self.ops = []
        self.tags = list(tags or [])
        self.route = route

    def add(self, op, **kw):
        d = {"op": op}
        d.update({k: v for k, v in kw.items() if v is not None})
        self.ops.append(d)
        return d

    def data(self):
        return {"id": self.id, "title": self.title, "ops": self.ops, "tags": self.tags, "route": self.route}


class Assets(object):
    """资源索引：大小写不敏感、可省扩展名。paths 是相对书目录的路径（如 assets/画像/bg_001.bmp）。"""
    EXTS = (".png", ".webp", ".jpg", ".jpeg", ".bmp", ".gif", ".svg")

    def __init__(self, paths=(), prefix=""):
        self.by_stem = {}
        self.by_name = {}
        for p in paths:
            p = p.replace("\\", "/")
            full = prefix + p
            base = p.rsplit("/", 1)[-1].lower()
            stem, ext = os.path.splitext(base)
            if ext in self.EXTS:
                self.by_name.setdefault(base, full)
                self.by_stem.setdefault(stem, full)
                # 带子目录的 stem（立ち絵/中/灯_中_01_01_02）
                sub = os.path.splitext(p.lower())[0]
                self.by_stem.setdefault(sub, full)
        self.hit = 0
        self.miss = {}

    @classmethod
    def from_dir(cls, book_dir, sub="assets"):
        root = os.path.join(book_dir, sub)
        paths = []
        for dp, _, fns in os.walk(root):
            for fn in fns:
                paths.append(os.path.relpath(os.path.join(dp, fn), book_dir).replace(os.sep, "/"))
        return cls(paths)

    @classmethod
    def from_list(cls, list_file, prefix="assets/"):
        with open(list_file, encoding="utf-8") as f:
            return cls([ln.strip() for ln in f if ln.strip()], prefix)

    def find(self, name, kind="img"):
        if not name:
            return None
        k = name.replace("\\", "/").lower()
        r = self.by_name.get(k.rsplit("/", 1)[-1]) or self.by_stem.get(k) or \
            self.by_stem.get(os.path.splitext(k)[0]) or self.by_stem.get(k.rsplit("/", 1)[-1])
        if r:
            self.hit += 1
        else:
            self.miss[name] = self.miss.get(name, 0) + 1
        return r

    def report(self):
        tot = self.hit + sum(self.miss.values())
        top = sorted(self.miss.items(), key=lambda x: -x[1])[:15]
        return {"resolved": self.hit, "total": tot, "rate": round(self.hit / tot, 3) if tot else None,
                "missing_top": top}


def read_text(path, encs=("utf-8-sig", "cp932", "gbk", "utf-16")):
    with open(path, "rb") as fh:
        raw = fh.read()
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return raw.decode("utf-16")
    for e in encs:
        try:
            return raw.decode(e)
        except UnicodeDecodeError:
            continue
    return raw.decode("cp932", "replace")


H_RE = re.compile(r"[ＨH](?:シーン|[0-9０-９]+回目|$)|エッチ|ｴｯﾁ")


def is_h_title(t):
    return bool(H_RE.search(t or ""))
