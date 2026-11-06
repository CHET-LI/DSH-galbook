"""python3 -m galbook <命令> …

  build   把解包目录转成可玩剧本      python3 -m galbook build --src 解包目录 --out books/<书>/story
  detect  只认引擎                    python3 -m galbook detect 目录
  serve   起 HTTP 服务（页面+接口）   python3 -m galbook serve --books books --data play-data
  mcp     MCP 服务（stdio）           python3 -m galbook mcp --books books --data play-data --agent alice
  play    命令行里玩一步              python3 -m galbook play books play-data <书> <名字> next n=20
  do      同上，参数走环境变量（给 shell 工具用）
                                      GALPLAY_BOOKS=books GALPLAY_DATA=play-data GALPLAY_BOOK=fog-harbor GALPLAY_AGENT=alice
                                      python3 -m galbook do next n=20 ；python3 -m galbook do books ；python3 -m galbook do help
  tools   打印工具定义                python3 -m galbook tools --format openai|mcp
  demo    装自带的演示故事到 books/   python3 -m galbook demo --books books
  version"""
import sys


def _utf8_stdio():
    """Windows 控制台/管道默认 GBK 之类，中文/日文会乱码或报错：统一 UTF-8。"""
    for f in (sys.stdout, sys.stderr):
        if hasattr(f, "reconfigure") and (f.encoding or "").lower().replace("-", "") != "utf8":
            try:
                f.reconfigure(encoding="utf-8", errors="replace")
            except Exception:  # noqa
                pass


def do(argv):
    """galbook do <动作> [k=v …] [--book B] [--agent A] [--books DIR] [--data DIR] [--lang en]"""
    import os
    from .play import Library
    from . import tools
    kw, rest, flags = {}, [], {}
    it = iter(argv)
    for x in it:
        if x.startswith("--") and x[2:] in ("book", "agent", "books", "data", "lang"):
            flags[x[2:]] = next(it, "")
        elif "=" in x and not x.startswith("="):
            k, _, v = x.partition("=")
            kw[k] = v
        else:
            rest.append(x)
    if not rest:
        print(do.__doc__)
        return 2
    action = rest[0]
    books = flags.get("books") or os.environ.get("GALPLAY_BOOKS", "books")
    data = flags.get("data") or os.environ.get("GALPLAY_DATA", "play-data")
    book = kw.pop("book", None) or flags.get("book") or os.environ.get("GALPLAY_BOOK")
    agent = kw.pop("agent", None) or flags.get("agent") or os.environ.get("GALPLAY_AGENT")
    lang = flags.get("lang") or os.environ.get("GALPLAY_LANG", "zh")
    name = "galbook_" + {"skip": "next"}.get(action, action)
    if action == "skip":
        kw["skip_read"] = True
    if "n" in kw:
        kw["n"] = int(kw["n"])
    if "steps" in kw:
        kw["steps"] = int(kw["steps"])
    if name == "galbook_choose" and kw.get("i", "random") != "random":
        kw["i"] = int(kw["i"])
    if "img" in kw:
        kw["img"] = kw["img"] in ("1", "true")
    try:
        print(tools.call_tool(Library(books, data), name, kw, book, agent, lang, style="cli", lang_override=flags.get("lang")))
    except Exception as e:  # noqa
        from .i18n import msg
        print("错误 / error: %s" % msg(lang, str(e)))
        return 1
    return 0


def main(argv=None):
    _utf8_stdio()
    a = list(sys.argv[1:] if argv is None else argv)
    if not a or a[0] in ("-h", "--help", "help"):
        print(__doc__)
        return 0
    cmd, rest = a[0], a[1:]
    if cmd == "build":
        from .build import main as m
    elif cmd == "serve":
        from .server import main as m
    elif cmd == "mcp":
        from .mcp_server import main as m
    elif cmd == "play":
        from .cli import main as m
    elif cmd == "tools":
        from .tools import main as m
    elif cmd == "detect":
        from .importers import detect
        for d in rest or ["."]:
            print("%s: %s（%s）" % (d, *detect(d)))
        return 0
    elif cmd == "do":
        return do(rest)
    elif cmd == "demo":
        return demo(rest)
    elif cmd in ("version", "--version"):
        from . import VERSION
        print(VERSION)
        return 0
    else:
        print("不认识的命令 %s\n%s" % (cmd, __doc__))
        return 2
    return m(rest)


def demo(argv):
    """把 galbook/demo/ 下的演示故事编译进 books/（图一起拷过去）。"""
    import argparse
    import os
    import shutil
    from .build import main as build
    ap = argparse.ArgumentParser(prog="galbook demo")
    ap.add_argument("--books", default="books")
    a = ap.parse_args(argv)
    root = os.path.join(os.path.dirname(os.path.abspath(__file__)), "demo")
    for slug in sorted(os.listdir(root)):
        src = os.path.join(root, slug)
        if not os.path.isdir(src):
            continue
        dst = os.path.join(a.books, slug)
        if os.path.isdir(os.path.join(src, "assets")):
            shutil.copytree(os.path.join(src, "assets"), os.path.join(dst, "assets"), dirs_exist_ok=True)
        print("== %s" % slug)
        rc = build(["--src", src, "--out", os.path.join(dst, "story"), "--assets-dir", src])
        if rc:
            return rc
    print("好了：python3 -m galbook serve --books %s   然后打开 http://127.0.0.1:8765/play/" % a.books)
    return 0


if __name__ == "__main__":
    sys.exit(main())
