"""把一个解包目录转成可玩剧本。

  python3 -m galbook build --src <解包目录> --out books/<书>/story [--engine auto] \\
          [--assets-dir books/<书>] [--assets-list 文件] [--title 书名] [--entry 标签]

--engine auto 按文件特征认引擎；认不出会说明卡在哪一步（要先用什么工具解包/反编译）。
写出前先校验：所有跳转/选项目标都必须存在，否则不写（加 --force 才写）。"""
import argparse
import json
import sys

from .importers import detect, get, load_plugin, names
from .importers.common import Assets
from .ir import validate, save_story, story_from_dict


def main(argv=None):
    ap = argparse.ArgumentParser(prog="galbook.build")
    ap.add_argument("--src", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--engine", default="auto", help="auto 或导入器名")
    ap.add_argument("--plugin", action="append", default=[], help="额外的导入器插件 .py（可多次）")
    ap.add_argument("--assets-dir", help="书目录（里面的 assets/ 会被索引，路径相对它）")
    ap.add_argument("--assets-list", help="资源清单文件（每行一个相对 assets/ 的路径）")
    ap.add_argument("--title")
    ap.add_argument("--entry")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--strict", action="store_true",
                    help="有未识别指令或选择点对不上就失败（默认只警告）")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    for p in a.plugin:
        print("加载插件：%s" % load_plugin(p))
    eng = a.engine
    if eng != "auto" and eng not in names():
        print("没有导入器 %s（有：%s）" % (eng, " ".join(names())))
        return 2
    if eng == "auto":
        eng, why = detect(a.src)
        print("认引擎：%s（%s）" % (eng or "认不出", why))
        if not eng:
            return 2
    assets = Assets.from_dir(a.assets_dir) if a.assets_dir else (Assets.from_list(a.assets_list) if a.assets_list else Assets())
    kw = {"entry": a.entry} if a.entry else {}
    meta, scenes = get(eng).build(a.src, assets=assets, **kw)
    if a.title:
        meta["title"] = a.title
    probs = validate(meta, scenes)
    st = meta.get("stats", {})
    hist = {}
    for sc in scenes.values():
        for op in sc.get("ops", []):
            hist[op.get("op")] = hist.get(op.get("op"), 0) + 1
    _sel = st.get("choices")
    if isinstance(_sel, int) and _sel != hist.get("choice", 0):
        probs.append("选择点对不上：脚本里认出 %d 个 .select/choice，生成出来的 choice op 只有 %d 个"
                     "（中间可能被当成普通文本吃掉了）" % (_sel, hist.get("choice", 0)))
    print("结构：" + json.dumps(hist, ensure_ascii=False))
    print("分支：choice %d 个、jump %d 个、end %d 个%s" % (
        hist.get("choice", 0), hist.get("jump", 0), hist.get("end", 0),
        "   ← 一个选择点都没有，检查转换器是不是吞了选项" if len(scenes) > 3 and not hist.get("choice") else ""))
    st["ops"] = hist
    clicks = [op["click"] for sc in scenes.values() for op in sc.get("ops", []) if op.get("op") == "say" and op.get("click")]
    if clicks:
        st["clicks"] = len(clicks)
        print("特殊机制：可点的句子 %d 处（say.click；读的时候条件成立会在句尾挂 ◇，do=click 触发）" % len(clicks))
    print("统计：" + json.dumps({k: v for k, v in st.items() if k not in ("assets", "unknown")}, ensure_ascii=False))
    print("图片解析：" + json.dumps(st.get("assets"), ensure_ascii=False))
    print("未识别指令（前 20）：" + json.dumps(st.get("unknown"), ensure_ascii=False))
    print("警告 %d 条%s" % (len(meta.get("warnings", [])), ("：" + "；".join(meta["warnings"][:5])) if meta.get("warnings") else ""))
    print("校验：%s" % ("通过" if not probs else "%d 个问题：%s" % (len(probs), "；".join(probs[:10]))))
    _w = story_from_dict(meta, scenes).warnings
    if _w:
        print("可疑：" + "；".join(_w))
    if a.strict and (probs or st.get("unknown")):
        print("--strict：有未识别指令或校验问题，按约定失败")
        return 1
    if probs and not a.force:
        print("有校验问题，没写文件（--force 强制写）")
        return 1
    if a.dry_run:
        return 0
    n = save_story(a.out, meta, scenes)
    print("写出 %d 个文件 → %s" % (n, a.out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
