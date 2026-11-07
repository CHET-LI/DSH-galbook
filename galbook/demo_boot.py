"""首次运行引导：books 目录不存在或为空时，把自带演示书装进去。

场景：`npm i galbook` 之后用户手里只有包，没有剧本目录；直接 `python -m galbook mcp`
会因为找不到书而什么都玩不了。这里补一步，让“装完就能玩”成立。
"""
import os
import shutil


def demo_enabled():
    """GALBOOK_NO_DEMO=1/true/yes → 不自动装演示书。"""
    return os.environ.get("GALBOOK_NO_DEMO", "").strip().lower() not in ("1", "true", "yes", "on")


def no_demo_flag(argv):
    """从参数里摘掉 --no-demo；有的话设 GALBOOK_NO_DEMO=1（各入口共用）。返回剩下的参数。"""
    argv = list(argv)
    if "--no-demo" in argv:
        argv = [x for x in argv if x != "--no-demo"]
        os.environ["GALBOOK_NO_DEMO"] = "1"
    return argv


def empty(books_dir):
    if not os.path.isdir(books_dir):
        return True
    try:
        with os.scandir(books_dir) as it:
            return not any(it)
    except OSError:
        return True


def ensure_demo_books(books_dir):
    """返回装了几本；目录里已经有书就不动。

    注意：build() 会往 stdout 打一堆日志。MCP 走 stdio 时 stdout 是协议通道，
    这里必须把它的输出吞掉，否则握手直接坏掉（实测过）。
    """
    if not empty(books_dir):
        return 0
    import contextlib
    import io

    from .build import main as build

    root = os.path.join(os.path.dirname(os.path.abspath(__file__)), "demo")
    if not os.path.isdir(root):
        return 0
    n = 0
    for slug in sorted(os.listdir(root)):
        src = os.path.join(root, slug)
        if not os.path.isdir(src):
            continue
        dst = os.path.join(books_dir, slug)
        if os.path.isdir(os.path.join(src, "assets")):
            shutil.copytree(os.path.join(src, "assets"), os.path.join(dst, "assets"), dirs_exist_ok=True)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = build(["--src", src, "--out", os.path.join(dst, "story"), "--assets-dir", src])
        if rc == 0:
            n += 1
    return n
