#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 galbook 挂进 DeepSeek Harness（dsh）——一条命令，不用手改 YAML。

    python dsh-plugin/install.py                  # 装到默认 profile（desktop）
    python dsh-plugin/install.py --dry-run        # 只打印要写进去的内容
    python dsh-plugin/install.py --profile work   # 指定 profile
    python dsh-plugin/install.py --remove         # 卸掉，不留痕

它会：
1. 找到 dsh 的配置文件 <dsh-home>/profiles/<profile>/cordis.patch.yml；
2. 备份成 .bak-时间戳；
3. 追加一段 MCP 配置（stdio 方式，dsh 会自己拉起 python -m galbook mcp），路径按你这台机器自动填；
4. 打印重启和自测的方法。

不改 dsh 本体，不动别的配置条目；重复执行不会写两遍。
"""
from __future__ import annotations

import argparse
import datetime as _dt
import os
import sys
import tempfile

MARK = "mcp-galbook"
HEAD_COMMENT = "# >>> galbook (installed by dsh-plugin/install.py) >>>"
TAIL_COMMENT = "# <<< galbook <<<"

BLOCK = """{head}
- insert:
    - id: {mark}
      name: "@deepseek-ai/dsh-mcp-client"
      config:
        serverName: galbook
        transport: stdio
        command: {command}
        args: {args}
        cwd: {cwd}
        env:
          PYTHONPATH: {repo}
          PYTHONIOENCODING: utf-8
        toolCallTimeoutMs: 60000
{tail}
"""


def repo_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def yaml_str(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def args_list(items):
    return "[" + ", ".join(yaml_str(i) for i in items) + "]"


def find_home(explicit: str | None) -> str:
    if explicit:
        return os.path.abspath(os.path.expanduser(explicit))
    env = os.environ.get("DSH_HOME")
    if env:
        return os.path.abspath(os.path.expanduser(env))
    return os.path.join(os.path.expanduser("~"), ".dsh")


def profiles(home: str):
    d = os.path.join(home, "profiles")
    if not os.path.isdir(d):
        return []
    return sorted(p for p in os.listdir(d) if os.path.isdir(os.path.join(d, p)))


def build_block(args, repo: str) -> str:
    cmd = args.python or sys.executable
    mars = ["-m", "galbook", "mcp",
            "--books", os.path.abspath(args.books),
            "--data", os.path.abspath(args.data),
            "--book", args.book,
            "--agent", args.agent,
            "--lang", args.lang]
    return BLOCK.format(head=HEAD_COMMENT, tail=TAIL_COMMENT, mark=MARK, command=yaml_str(cmd),
                        args=args_list(mars), cwd=yaml_str(repo), repo=yaml_str(repo))


def strip_block(text: str) -> tuple[str, bool]:
    if HEAD_COMMENT not in text:
        return text, False
    start = text.index(HEAD_COMMENT)
    end = text.index(TAIL_COMMENT, start) + len(TAIL_COMMENT)
    rest = text[end:]
    if rest.startswith("\n"):
        rest = rest[1:]
    return text[:start] + rest, True


def main() -> int:
    ap = argparse.ArgumentParser(description="Install galbook MCP into DeepSeek Harness")
    ap.add_argument("--home", help="dsh home（默认 ~/.dsh，也可以用环境变量 DSH_HOME 指定）")
    ap.add_argument("--profile", default="desktop", help="要写入的 profile（默认 desktop）")
    ap.add_argument("--books", default=None, help="剧本目录（默认 <仓库>/books）")
    ap.add_argument("--data", default=None, help="存档目录（默认 <仓库>/play-data）")
    ap.add_argument("--book", default="fog-harbor", help="默认书目")
    ap.add_argument("--agent", default="dsh-agent", help="默认玩家名")
    ap.add_argument("--lang", default="zh", choices=["zh", "en"], help="界面语言")
    ap.add_argument("--python", default=None, help="给 dsh 用的 python 解释器（默认当前这个）")
    ap.add_argument("--dry-run", action="store_true", help="只打印，不写文件")
    ap.add_argument("--remove", action="store_true", help="删掉之前写入的配置")
    a = ap.parse_args()

    repo = repo_root()
    a.books = a.books or os.path.join(repo, "books")
    a.data = a.data or os.path.join(repo, "play-data")
    home = find_home(a.home)

    print(f"仓库   : {repo}")
    print(f"dsh home: {home}")

    ps = profiles(home)
    if not ps:
        print("× 没找到任何 profile。确认 dsh 装过并且启动过一次，或用 --home 指定。")
        print("  已有 profile:", ps or "（无）")
        return 2
    target = os.path.join(home, "profiles", a.profile, "cordis.patch.yml")
    if not os.path.exists(target):
        # 也允许写在 home 根下的 cordis.patch.yml
        alt = os.path.join(home, "cordis.patch.yml")
        if os.path.exists(alt) or a.profile == "desktop":
            target = alt if not os.path.isdir(os.path.join(home, "profiles", a.profile)) else target
    print(f"目标   : {target}")
    print(f"profile: {a.profile}（可用: {', '.join(ps)}）")

    block = build_block(a, repo)
    if a.dry_run:
        print("\n----- 将写入 -----")
        print(block)
        return 0

    text = ""
    if os.path.exists(target):
        with open(target, encoding="utf-8") as f:
            text = f.read()
    text, existed = strip_block(text)

    if a.remove:
        if not existed:
            print("没有找到 galbook 的配置块，什么都没改。")
            return 0
        _backup(target)
        with open(target, "w", encoding="utf-8") as f:
            f.write(text)
        print("✓ 已移除。重启 dsh 生效。")
        return 0

    if MARK in text and not existed:
        print("× 文件里已经有 mcp-galbook（可能是手动加的），为免冲突没有改动。")
        return 3

    if text and not text.endswith("\n"):
        text += "\n"
    new = text + ("\n" if text.strip() else "") + block
    os.makedirs(os.path.dirname(target), exist_ok=True)
    if os.path.exists(target):
        _backup(target)
    with open(target, "w", encoding="utf-8") as f:
        f.write(new)

    print("\n✓ 写入完成。")
    if not os.path.isdir(a.books) or not os.listdir(a.books):
        print("  ! 剧本目录还没有书，先装演示书（中文 + 英文两本）：")
        print(f"    \"{a.python or sys.executable}\" -m galbook demo --books \"{a.books}\"")
    print("  1) 重启 DeepSeek Harness（配置只在启动时读）")
    print("  2) 新建会话，问它：galbook 有哪些工具？应能看到 15 个")
    print("  3) 想先验证不重启：手动给 python -m galbook mcp 发一条 initialize")
    print("  卸载：python dsh-plugin/install.py --remove")
    return 0


def _backup(path: str) -> None:
    stamp = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    bak = f"{path}.bak-{stamp}"
    with open(path, "rb") as s, open(bak, "wb") as d:
        d.write(s.read())
    print(f"备份   : {bak}")


if __name__ == "__main__":
    sys.exit(main())
