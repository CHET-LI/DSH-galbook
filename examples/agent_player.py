#!/usr/bin/env python3
"""一个最小的「agent 玩家」：连 galbook 服务，按人设读剧情、做选择、写理由。只用标准库。

  # 用大模型选（任何 OpenAI 兼容接口：OpenAI / DeepSeek / Qwen / Ollama / vLLM …）
  OPENAI_BASE_URL=https://api.openai.com/v1 OPENAI_API_KEY=sk-... MODEL=gpt-4o-mini \\
  python3 examples/agent_player.py --book fog-harbor --agent alice --persona "胆子大、好奇心重" --decider llm

  # 不用模型：按人设关键词打分（便宜，适合压测/做对照组），或随机
  python3 examples/agent_player.py --book fog-harbor --agent bob --persona "谨慎 温柔 不爱冒险" --decider keyword
  python3 examples/agent_player.py --book fog-harbor --agent carol --decider random --games 3

参数：--server（默认 http://127.0.0.1:8765）--token（服务开了令牌时）--games 玩几局 --pace 每次读几句
      --mode ironman --hints --lang en --rewind-prob 0.3（结局后按概率回到上个选项换一条路）"""
import argparse
import json
import os
import random
import re
import sys
import time
import urllib.parse
import urllib.request


class Client(object):
    def __init__(self, server, book, agent, token=None):
        self.base = "%s/play/api/%s/%s/" % (server.rstrip("/"), urllib.parse.quote(book), urllib.parse.quote(agent))
        self.token = token

    def __call__(self, action, **kw):
        req = urllib.request.Request(self.base + action, data=json.dumps(kw).encode("utf-8"), method="POST",
                                     headers={"Content-Type": "application/json"})
        if self.token:
            req.add_header("Authorization", "Bearer " + self.token)
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            j = json.loads(e.read().decode("utf-8") or "{}")
            raise RuntimeError(j.get("error") or str(e))


def plain(t):
    t = re.sub(r"\[rb,([^,\]]+),[^\]]*\]", r"\1", t or "")
    return re.sub(r"\[[A-Za-z]+(?:,[^\]]*)?\]", "", t)


# ---------- 三种选法 ----------
def decide_random(persona, context, options):
    o = random.choice(options)
    return o["i"], "（随机）"


def decide_keyword(persona, context, options):
    """人设关键词和选项文字的字面重合打分；同分随机。没有模型时也能让不同人设走出不同路线。"""
    words = [w for w in re.split(r"[\s,，、。;；/]+", persona or "") if w]
    pos = {"胆子大": "陪 去 冒险 偷偷 拆", "好奇": "拆 问 知道 秘密 信", "温柔": "陪 谢谢 帮 看着", "谨慎": "看着 不 留",
           "brave": "come with secretly open", "curious": "open know letter", "kind": "watch help thank", "careful": "watch don't"}
    keys = set(words)
    for w in words:
        for k, v in pos.items():
            if k in w:
                keys.update(v.split())
    best, score = [], -1
    for o in options:
        s = sum(1 for k in keys if k and k.lower() in o["text"].lower())
        if s > score:
            best, score = [o], s
        elif s == score:
            best.append(o)
    o = random.choice(best)
    return o["i"], "人设关键词匹配 %d 处" % score if score > 0 else "没有明显倾向，凭感觉"


def decide_llm(persona, context, options):
    base = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    key = os.environ.get("OPENAI_API_KEY", "")
    model = os.environ.get("MODEL", "gpt-4o-mini")
    opts = "\n".join("%d. %s" % (o["i"], o["text"]) for o in options)
    msgs = [{"role": "system", "content": "你在玩一部视觉小说。你的人设：%s\n像真人玩家一样，根据人设和刚才的剧情做选择。"
                                          "只回 JSON：{\"i\": 选项编号, \"reason\": \"一句真实理由\"}" % (persona or "普通玩家")},
            {"role": "user", "content": "最近的剧情：\n%s\n\n选项：\n%s" % (context, opts)}]
    req = urllib.request.Request(base + "/chat/completions", method="POST",
                                 data=json.dumps({"model": model, "messages": msgs, "temperature": 0.8}).encode("utf-8"),
                                 headers={"Content-Type": "application/json", "Authorization": "Bearer " + key})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            txt = json.loads(r.read().decode("utf-8"))["choices"][0]["message"]["content"]
        m = re.search(r"\{.*\}", txt, re.S)
        j = json.loads(m.group(0)) if m else {}
        i = int(j.get("i"))
        if any(o["i"] == i for o in options):
            return i, str(j.get("reason") or "")[:300]
    except Exception as e:  # noqa
        print("  [llm 失败，改随机] %s" % e, file=sys.stderr)
    return decide_random(persona, context, options)


DECIDERS = {"random": decide_random, "keyword": decide_keyword, "llm": decide_llm}


def play(args):
    c = Client(args.server, args.book, args.agent, args.token)
    decide = DECIDERS[args.decider]
    if args.persona:
        c("persona", text=args.persona)
    persona = c("persona").get("persona", "")
    for g in range(args.games):
        r = c("new", mode=args.mode, hints="1" if args.hints else "0", lang=args.lang)
        print("== %s 第 %d 局（%s）" % (args.agent, g + 1, r["msg"]))
        recent = [l for l in r["state"]["lines"]]
        while True:
            st = r["state"]
            if st.get("choice"):
                ctx = "\n".join(("%s：%s" % (l["who"], plain(l["text"]))) if l["who"] else plain(l["text"]) for l in recent[-40:])
                i, why = decide(persona, ctx, st["choice"]["options"])
                time.sleep(args.think)
                c("choose", i=i, reason=why)
                print("  [%s] 选 %d. %s —— %s" % (args.agent, i, next(o["text"] for o in st["choice"]["options"] if o["i"] == i), why))
            elif st.get("ended"):
                print("  [%s] 结局：%s" % (args.agent, st["ended"].get("name")))
                if args.mode != "ironman" and random.random() < args.rewind_prob:
                    r = c("rewind")
                    print("  [%s] （回到上个选项，换条路试试）" % args.agent)
                    continue
                break
            r = c("next", n=args.pace)
            recent += r["state"]["lines"]
    g = c("gallery")
    print("[%s] 收集：结局 %d/%d %s，CG %d/%d，已读 %.0f%%" % (args.agent, len(g["endings"]), g["endings_total"], "、".join(g["endings"]),
                                                g["cg_seen"], g["cg_total"], g["read_ratio"] * 100))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--server", default=os.environ.get("GALPLAY_SERVER", "http://127.0.0.1:8765"))
    ap.add_argument("--token", default=os.environ.get("GALPLAY_TOKEN"))
    ap.add_argument("--book", required=True)
    ap.add_argument("--agent", required=True)
    ap.add_argument("--persona", default="")
    ap.add_argument("--decider", choices=sorted(DECIDERS), default="keyword")
    ap.add_argument("--games", type=int, default=1)
    ap.add_argument("--pace", type=int, default=30)
    ap.add_argument("--mode", default="normal", choices=("normal", "ironman"))
    ap.add_argument("--hints", action="store_true")
    ap.add_argument("--lang", default="zh", choices=("zh", "en"))
    ap.add_argument("--rewind-prob", type=float, default=0.0)
    ap.add_argument("--think", type=float, default=0.0, help="选之前停几秒（让 think_s 更像人）")
    return play(ap.parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
