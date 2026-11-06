#!/usr/bin/env python3
"""逐条核对 README 里说的东西是不是真的存在、真的能跑。在仓库根目录：python3 scripts/verify_claims.py
每条打印 PASS/FAIL 和证据。只用标准库；会起一个临时服务（随机端口），结束时关掉。"""
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable
T = tempfile.mkdtemp()
BOOKS, DATA = os.path.join(T, "books"), os.path.join(T, "data")
results = []


def run(*args, env=None):
    e = dict(os.environ, PYTHONIOENCODING="utf-8", **(env or {}))
    r = subprocess.run([PY, "-m", "galbook"] + list(args), cwd=ROOT, capture_output=True, env=e)
    return r.returncode, r.stdout.decode("utf-8", "replace") + r.stderr.decode("utf-8", "replace")


def check(name, ok, evidence):
    results.append(ok)
    print("%s  %s\n      %s" % ("PASS" if ok else "FAIL", name, evidence.strip().replace("\n", "\n      ")[:400]))


def http(path, data=None, token=None, port=None):
    req = urllib.request.Request("http://127.0.0.1:%d%s" % (port, path), data=data, method="POST" if data else "GET",
                                 headers={"Content-Type": "application/json"})
    if token:
        req.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, r.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")


# 1. 入口
rc, out = run("--help")
check("python3 -m galbook 能跑（galbook/__main__.py）", rc == 0 and "build" in out and "mcp" in out, out.splitlines()[0] + " … " + " ".join(
    l.split()[0] for l in out.splitlines()[2:12] if l.strip()))
# 4. demo
rc, out = run("demo", "--books", BOOKS)
check("python3 -m galbook demo 装出 fog-harbor / fog-harbor-en", rc == 0 and sorted(os.listdir(BOOKS)) == ["fog-harbor", "fog-harbor-en"],
      "ls books → %s\n%s" % (sorted(os.listdir(BOOKS)), out.splitlines()[-1]))
# 7. 多元选项
env = {"GALPLAY_BOOKS": BOOKS, "GALPLAY_DATA": DATA, "GALPLAY_BOOK": "fog-harbor", "GALPLAY_AGENT": "v"}
run("do", "persona", "text=胆小", env=env)
rc, out = run("do", "new", "mode=ironman", "hints=1", "h=skip", env=env)
rc2, out2 = run("do", "next", "n=50", env=env)
rc3, out3 = run("do", "choose", "i=random", "reason=掷骰子", env=env)
rc4, out4 = run("do", "rewind", env=env)
rc5, out5 = run("do", "gallery", env=env)
rc6, out6 = run("do", "status", "--lang", "en", env=env)
check("多元选项：ironman / hints / h / persona / i=random / gallery / lang",
      "模式=ironman" in out and "提示=1" in out and "H=skip" in out and "〔新内容〕" in out2 and "胆小" in out2
      and "你选了" in out3 and "铁人" in out4 and "结局" in out5 and "lines" in out6,
      "\n".join([out.splitlines()[1], [l for l in out2.splitlines() if "〔新内容〕" in l][0], out3.splitlines()[0],
                 out4.strip(), out5.splitlines()[0], out6.splitlines()[0]]))
# 8. OpenAI tools
rc, out = run("tools", "--format", "openai")
tools = json.loads(out) if rc == 0 else []
check("python3 -m galbook tools（OpenAI function calling）", len(tools) >= 10,
      "%d 个工具：%s" % (len(tools), " ".join(t["function"]["name"] for t in tools)))
# 9. textdump + 导入器数量
from importlib import import_module  # noqa: E402
sys.path.insert(0, ROOT)
imp = import_module("galbook.importers")
rc, out = run("build", "--src", os.path.join(ROOT, "tests", "samples", "textdump"), "--out", os.path.join(T, "td", "story"), "--engine", "textdump")
check("--engine textdump 存在且能建书；内置导入器列表", rc == 0 and "textdump" in imp.names(),
      "导入器：%s\n%s" % (" ".join(imp.names()), "\n".join(out.splitlines()[-2:])))
# 2/3. MCP stdio、HTTP MCP、令牌
lines = "\n".join(json.dumps(x) for x in [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
                                           {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}]) + "\n"
r = subprocess.run([PY, "-m", "galbook", "mcp", "--books", BOOKS, "--data", DATA], cwd=ROOT, input=lines.encode(), capture_output=True)
resp = [json.loads(l) for l in r.stdout.decode("utf-8").splitlines()]
check("MCP（stdio）：initialize + tools/list", len(resp) == 2 and resp[0]["result"]["serverInfo"]["name"] == "galbook",
      "serverInfo=%s，tools=%d" % (resp[0]["result"]["serverInfo"], len(resp[1]["result"]["tools"])))
s = socket.socket()
s.bind(("127.0.0.1", 0))
port = s.getsockname()[1]
s.close()
tok = os.path.join(T, "tokens.json")
with open(tok, "w") as f:
    json.dump({"k-alice": "alice", "k-admin": "*"}, f)
srv = subprocess.Popen([PY, "-m", "galbook", "serve", "--books", BOOKS, "--data", DATA, "--port", str(port), "--tokens", tok, "--quiet"],
                       cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
try:
    for _ in range(50):
        try:
            http("/play/api/books", port=port)
            break
        except Exception:  # noqa
            time.sleep(0.1)
    a = http("/play/t/fog-harbor/alice?do=status", port=port)[0]
    b = http("/play/t/fog-harbor/alice?do=status", token="k-alice", port=port)[0]
    c = http("/play/t/fog-harbor/bob?do=status", token="k-alice", port=port)[0]
    d = http("/b/fog-harbor/story/story.json", port=port)[0]
    check("令牌：无令牌 401 / 对的令牌 200 / 冒名 403；剧本不外露 403", (a, b, c, d) == (401, 200, 403, 403),
          "无令牌=%s 对=%s 冒名=%s /b/<书>/story=%s" % (a, b, c, d))
    code, body = http("/mcp?book=fog-harbor&agent=mallory", json.dumps(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "galbook_new", "arguments": {}}}).encode(), "k-alice", port)
    check("MCP（Streamable HTTP）POST /mcp，令牌绑定名字", code == 200 and os.path.isdir(os.path.join(DATA, "fog-harbor", "alice"))
          and not os.path.exists(os.path.join(DATA, "fog-harbor", "mallory")), "HTTP %s，%s" % (code, json.loads(body)["result"]["content"][0]["text"].splitlines()[0]))
finally:
    srv.terminate()
    srv.wait(5)
# 5/6. 文件
need = ["LICENSE", "CONTRIBUTING.md", "README.md", "README.en.md", "pyproject.toml", "docs/AGENTS.md", "docs/ENGINES.md", "docs/IMPORTERS.md",
        "docs/SCHEMA.md", "docs/img/watch.png", "examples/party.py", "examples/agent_player.py", "examples/mcp_config.example.json",
        ".agents/skills/galbook/SKILL.md", "integrations/deepseek-harness/galbook.patch.yml", "integrations/deepseek-harness/selftest/selftest.sh"]
miss = [n for n in need if not os.path.isfile(os.path.join(ROOT, n))]
check("README 里引用的文件都在", not miss, "缺：%s" % miss if miss else "%d 个都在" % len(need))
# 结构
check("仓库根 = 包的上一层（galbook/ 在根目录下）", os.path.isfile(os.path.join(ROOT, "galbook", "__main__.py")) and
      not os.path.exists(os.path.join(ROOT, "galbook", "galbook")), "根目录：%s" % " ".join(sorted(os.listdir(ROOT))))
print("\n%d/%d PASS" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
