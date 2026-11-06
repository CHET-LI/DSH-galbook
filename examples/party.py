#!/usr/bin/env python3
"""一群性格不同的 agent 同时玩同一本书（演示多 agent 并发 + 多元选择）。

  python3 examples/party.py --book fog-harbor            # 默认 6 个不同人设，keyword 选法
  python3 examples/party.py --book fog-harbor --decider llm   # 用大模型（见 agent_player.py 的环境变量）"""
import argparse
import os
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import agent_player  # noqa: E402

CAST = [("brave_rin", "胆子大 好奇 爱冒险"), ("gentle_mio", "温柔 体贴 不爱冒险"), ("careful_ken", "谨慎 稳妥 守规矩"),
        ("curious_ai", "好奇 喜欢秘密 爱拆信"), ("ironman_jo", "说一不二 不回头"), ("chaos_bot", "")]


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--server", default=os.environ.get("GALPLAY_SERVER", "http://127.0.0.1:8765"))
    ap.add_argument("--token", default=os.environ.get("GALPLAY_TOKEN"))
    ap.add_argument("--book", required=True)
    ap.add_argument("--decider", default="keyword", choices=sorted(agent_player.DECIDERS))
    ap.add_argument("--games", type=int, default=2)
    a = ap.parse_args(argv)
    ts = []
    for name, persona in CAST:
        args = ["--server", a.server, "--book", a.book, "--agent", name, "--persona", persona or "随便玩",
                "--decider", "random" if name == "chaos_bot" else a.decider, "--games", str(a.games), "--hints"]
        if a.token:
            args += ["--token", a.token]
        if name.startswith("ironman"):
            args += ["--mode", "ironman"]
        else:
            args += ["--rewind-prob", "0.3"]
        ts.append(threading.Thread(target=agent_player.main, args=(args,)))
    [t.start() for t in ts]
    [t.join() for t in ts]
    print("都玩完了。打开 %s/play/?book=%s 看每个人玩到哪。" % (a.server, a.book))
    return 0


if __name__ == "__main__":
    sys.exit(main())
