"""文本导出（线性）→ galbook/1：给「暂时没有专用导入器」的引擎兜底。

很多引擎已经有成熟的文本抽取工具，抽出来的东西能直接喂进来，先「能读」：
  * VNTextPatch（arcusmaximus，MIT）`extractlocal <游戏脚本目录> <输出目录>` 产出的 .json
    格式：[{"name": "灯", "message": "「…」"}, {"names": ["A","B"], "message": "…"}, {"message": "旁白"}]
    它支持 AdvHD / Artemis / BGI(Ethornell) / CatSystem2 / Majiro / Musica / RealLive / Softpal /
    SystemNNN / YU-RIS / Silky's 等 20 多种引擎。
  * 任意 .csv / .tsv：表头里有 name/speaker/character/who/名前/名字 之一 + text/message/line/original/原文/台词 之一
  * .txt：一行一句，「名字：台词」「名字「台词」」或旁白（要 --engine textdump 显式指定，避免和 NScripter 0.txt 混）

限制（如实说）：这些工具只抽文字，**不抽选项的跳转关系**（选项文字会混在台词里），所以导出来是一条直线，mode=linear。
要真分支，需要该引擎的专用导入器（见 docs/IMPORTERS.md，欢迎贡献）。
文件顺序：目录里有 order.txt 就按它（一行一个文件名），否则按文件名自然排序。"""
import csv
import io
import json
import os
import re

from .common import SceneB, Assets, read_text

NAME = "textdump"
NAME_KEYS = ("name", "speaker", "character", "chara", "who", "名前", "名字", "角色", "说话人")
TEXT_KEYS = ("message", "text", "line", "original", "source", "原文", "台词", "本文", "セリフ")
SAY = re.compile(r"^([^\s：:「『。，、！？!?,…—]{1,12})(?:：|:\s)\s*(.+)$")
SAY_Q = re.compile(r"^([^\s：:「『（(。，、！？!?,…—]{1,12})([「『].*)$")


def _natkey(s):
    return [int(x) if x.isdigit() else x.lower() for x in re.split(r"(\d+)", s)]


def _is_vntp_json(path):
    try:
        with open(path, encoding="utf-8-sig") as f:
            d = json.load(f)
        return isinstance(d, list) and (not d or (isinstance(d[0], dict) and "message" in d[0]))
    except Exception:  # noqa
        return False


def detect(src):
    js = []
    for dp, _, fn in os.walk(src):
        js += [os.path.join(dp, f) for f in fn if f.lower().endswith(".json")]
        for f in fn:
            if f.lower().endswith((".csv", ".tsv")):
                head = read_text(os.path.join(dp, f)).splitlines()[:1]
                if head and any(k in head[0].lower() for k in TEXT_KEYS):
                    return True, "有带表头的台词表（.csv/.tsv）：按线性文本导入"
    if js and any(_is_vntp_json(p) for p in js[:5]):
        return True, "有 VNTextPatch 格式的 .json 文本导出：按线性文本导入（没有分支）"
    return False, ""


def _rows(path):
    low = path.lower()
    if low.endswith(".json"):
        with open(path, encoding="utf-8-sig") as f:
            d = json.load(f)
        if not isinstance(d, list):
            raise ValueError("%s 不是 JSON 数组" % path)
        for e in d:
            if isinstance(e, dict):
                who = e.get("name") or "・".join(e.get("names") or []) or ""
                yield who, e.get("message") or ""
            elif isinstance(e, str):
                yield "", e
    elif low.endswith((".csv", ".tsv")):
        txt = read_text(path)
        rd = csv.reader(io.StringIO(txt), delimiter="\t" if low.endswith(".tsv") else ",")
        head = [h.strip().lower() for h in next(rd, [])]
        ni = next((head.index(k) for k in NAME_KEYS if k in head), None)
        ti = next((head.index(k) for k in TEXT_KEYS if k in head), None)
        if ti is None:
            raise ValueError("%s 表头里找不到台词列（认：%s）" % (path, "/".join(TEXT_KEYS)))
        for row in rd:
            if len(row) > ti:
                yield (row[ni].strip() if ni is not None and len(row) > ni else ""), row[ti]
    else:
        for line in read_text(path).splitlines():
            s = line.strip()
            if not s:
                continue
            m = SAY.match(s) or SAY_Q.match(s)
            yield (m.group(1), m.group(2)) if m else ("", s)


def build(src, assets=None, **_):
    assets = assets or Assets()
    exts = (".json", ".csv", ".tsv", ".txt")
    files = []
    for dp, _, fn in os.walk(src):
        files += [os.path.relpath(os.path.join(dp, f), src) for f in fn if f.lower().endswith(exts) and f != "order.txt"]
    op = os.path.join(src, "order.txt")
    if os.path.isfile(op):
        want = [l.strip() for l in read_text(op).splitlines() if l.strip()]
        missing = [w for w in want if w not in files]
        if missing:
            raise ValueError("order.txt 里列的文件不存在：%s" % "、".join(missing[:5]))
        files = want
    else:
        files.sort(key=_natkey)
    if not files:
        raise ValueError("%s 里没有 .json/.csv/.tsv/.txt 文本" % src)
    scenes, order, stats = {}, [], {"files": len(files), "says": 0, "choices": 0, "options": 0, "jumps": 0}
    for rel in files:
        sid = re.sub(r"[\\/]", "__", os.path.splitext(rel)[0])
        b = SceneB(sid, os.path.splitext(os.path.basename(rel))[0])
        b.add("label", name="top")
        for who, text in _rows(os.path.join(src, rel)):
            text = (text or "").replace("\r\n", "\n").strip()
            if text:
                b.add("say", who=who.strip(), text=text)
                stats["says"] += 1
        scenes[sid] = b
        order.append(sid)
    for a, c in zip(order, order[1:]):
        scenes[a].add("jump", scene=c, label="top")
        stats["jumps"] += 1
    scenes[order[-1]].add("end", kind="ending", name="全文完")
    data = {k: v.data() for k, v in scenes.items()}
    meta = {"format": "galbook/1", "title": "", "engine": "textdump", "importer": "galbook-textdump-1", "mode": "linear",
            "entry": {"scene": order[0], "label": "top"},
            "scenes": {k: {"title": v["title"], "tags": v["tags"]} for k, v in data.items()},
            "routes": [], "system_vars": [], "stats": dict(stats, unknown=[], assets=assets.report()),
            "warnings": ["线性文本：原作的选项文字（如果有）混在台词里，没有分支"]}
    return meta, data
