"""命令行里玩（不用起服务）：
  python3 -m galbook play <books目录> <存档目录> <书> <agent> <操作> [k=v ...]
例：python3 -m galbook play books play-data lighthouse alice next n=30"""
import sys

from .play import Library
from .web import render_text, want_vis


def main(argv=None):
    a = list(argv if argv is not None else sys.argv[1:])
    if len(a) < 5:
        print(__doc__)
        return 2
    books, data, book, agent, do = a[:5]
    kw = dict(x.split("=", 1) for x in a[5:])
    if kw.pop("skip", "") in ("1", "true"):
        kw["skip_read"] = True
    img = kw.pop("img", "") in ("1", "true")
    lang = kw.get("lang") if do == "new" else kw.pop("lang", None)
    vis = kw.pop("vis", None)
    lib = Library(books, data)
    vis = want_vis(lib, book, vis)
    r = lib.act(book, agent, do, **kw)
    lang = lang or ((r.get("opts") or (lib.store.peek_run(book, agent) or {}).get("opts") or {}).get("lang")) or "zh"
    sys.stdout.write(render_text(r, do, img, book, agent, lang, vis=vis))
    return 0


if __name__ == "__main__":
    sys.exit(main())
