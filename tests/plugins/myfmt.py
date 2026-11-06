"""插件示例：一个玩具格式 .myfmt（每行「说话人|台词」，「?a|b」是二选一，各自跳到 *a / *b）。
真插件照这个写：模块里有 NAME、detect(src)、build(src, assets=None, **opts) -> (meta, scenes)。"""
import os

NAME = "myfmt"


def detect(src):
    for dp, _, fn in os.walk(src):
        if any(f.endswith(".myfmt") for f in fn):
            return True, "有 .myfmt"
    return False, ""


def build(src, assets=None, **_):
    ops = []
    for f in sorted(os.listdir(src)):
        if f.endswith(".myfmt"):
            for line in open(os.path.join(src, f), encoding="utf-8").read().splitlines():
                if line.startswith("*"):
                    ops.append({"op": "label", "name": line[1:]})
                elif line.startswith("?"):
                    a, b = line[1:].split("|")
                    ops.append({"op": "choice", "id": "c1", "options": [
                        {"text": a, "goto": {"scene": "main", "label": a}}, {"text": b, "goto": {"scene": "main", "label": b}}]})
                elif line.startswith("!end"):
                    ops.append({"op": "end", "kind": "ending", "name": line[5:]})
                elif line:
                    who, _, text = line.rpartition("|")
                    ops.append({"op": "say", "who": who, "text": text})
    scenes = {"main": {"id": "main", "title": "main", "ops": ops, "tags": [], "route": ""}}
    meta = {"format": "galbook/1", "title": "myfmt demo", "engine": "myfmt", "importer": "myfmt-plugin",
            "entry": {"scene": "main", "label": None}, "scenes": {"main": {"title": "main", "tags": []}},
            "routes": [], "system_vars": [], "stats": {"says": sum(o["op"] == "say" for o in ops)}, "warnings": []}
    return meta, scenes
