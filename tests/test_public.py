"""公开版新增功能：.gal / 文本导出 / 插件 / 多元选项 / 英文 / MCP / 工具定义 / 令牌。"""
import io
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
SAMPLES = os.path.join(HERE, "samples")
DEMO = os.path.join(ROOT, "galbook", "demo")

from galbook import importers  # noqa: E402
from galbook.importers import detect, get  # noqa: E402
from galbook.importers.common import Assets  # noqa: E402
from galbook.ir import validate, save_story  # noqa: E402
from galbook.play import Library  # noqa: E402
from galbook.engine import PlayError  # noqa: E402
from galbook.web import render_text  # noqa: E402
from galbook import tools, mcp_server  # noqa: E402


def wr(p, text):
    with open(p, "w", encoding="utf-8") as f:
        f.write(text)


def mkbook(books, slug, eng, src):
    meta, scenes = get(eng).build(src, assets=Assets())
    probs = validate(meta, scenes)
    assert not probs, probs
    save_story(os.path.join(books, slug, "story"), meta, scenes)
    return meta


def walk(L, book, agent, picks):
    """按 picks 依次选，走到结局；返回结局名。"""
    picks = list(picks)
    for _ in range(100):
        r = L.act(book, agent, "next", n=50)
        st = r["state"]
        if st.get("ended"):
            return st["ended"]["name"]
        if st.get("choice"):
            L.act(book, agent, "choose", i=picks.pop(0))
    raise AssertionError("没走完")


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.books = os.path.join(self.tmp, "books")
        mkbook(self.books, "fog", "galscript", os.path.join(DEMO, "fog-harbor"))
        mkbook(self.books, "fog-en", "galscript", os.path.join(DEMO, "fog-harbor-en"))
        self.L = Library(self.books, os.path.join(self.tmp, "data"))

    def tearDown(self):
        shutil.rmtree(self.tmp)


class TestImportersPublic(unittest.TestCase):
    def test_detect(self):
        self.assertEqual(detect(os.path.join(DEMO, "fog-harbor"))[0], "galscript")
        self.assertEqual(detect(os.path.join(SAMPLES, "textdump"))[0], "textdump")

    def test_textdump_linear(self):
        meta, scenes = get("textdump").build(os.path.join(SAMPLES, "textdump"))
        self.assertEqual(meta["mode"], "linear")
        self.assertEqual(validate(meta, scenes), [])
        says = [o for s in ("01_intro", "02_next") for o in scenes[s]["ops"] if o["op"] == "say"]
        self.assertEqual([o["who"] for o in says], ["", "灯", "灯・誠", "誠", ""])
        self.assertEqual(meta["entry"]["scene"], "01_intro")

    def test_textdump_order_and_txt(self):
        d = tempfile.mkdtemp()
        try:
            wr(os.path.join(d, "b.txt"), "灯：二番目\n地の文。\n")
            wr(os.path.join(d, "a.txt"), "誠「一番目」\n")
            wr(os.path.join(d, "order.txt"), "b.txt\na.txt\n")
            meta, scenes = get("textdump").build(d)
            self.assertEqual(meta["entry"]["scene"], "b")
            self.assertEqual(scenes["b"]["ops"][1], {"op": "say", "who": "灯", "text": "二番目"})
            self.assertEqual(scenes["a"]["ops"][1]["who"], "誠")
            wr(os.path.join(d, "order.txt"), "nope.txt\n")
            with self.assertRaises(ValueError):
                get("textdump").build(d)
        finally:
            shutil.rmtree(d)

    def test_galscript_errors_name_line(self):
        d = tempfile.mkdtemp()
        try:
            with open(os.path.join(d, "x.gal"), "w", encoding="utf-8") as f:
                f.write("=== a\n你好。\n- 没写箭头的选项\n@frobnicate\n-> nowhere\n")
            meta, scenes = get("galscript").build(d)
            self.assertTrue(any("x.gal:3" in w for w in meta["warnings"]), meta["warnings"])
            self.assertTrue(any("x.gal:4" in w and "frobnicate" in w for w in meta["warnings"]), meta["warnings"])
            self.assertTrue(validate(meta, scenes))                    # 跳到不存在的目标：校验报出来
        finally:
            shutil.rmtree(d)

    def test_plugin(self):
        name = importers.load_plugin(os.path.join(HERE, "plugins", "myfmt.py"))
        self.assertEqual(name, "myfmt")
        self.assertIn("myfmt", importers.names())
        self.assertEqual(detect(os.path.join(SAMPLES, "myfmt"))[0], "myfmt")
        tmp = tempfile.mkdtemp()
        try:
            out = os.path.join(tmp, "b", "story")
            r = subprocess.run([sys.executable, "-m", "galbook", "build", "--src", os.path.join(SAMPLES, "myfmt"), "--out", out,
                                "--plugin", os.path.join(HERE, "plugins", "myfmt.py")], cwd=ROOT, capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            L = Library(os.path.join(tmp), os.path.join(tmp, "data"))
            L.act("b", "p", "new")
            self.assertEqual(walk(L, "b", "p", [2]), "右の結末")
        finally:
            shutil.rmtree(tmp)


class TestDiversity(Base):
    def test_endings_and_hidden_route(self):
        L = self.L
        L.act("fog", "a", "new")
        self.assertEqual(walk(L, "fog", "a", [3]), "雾里的背影")
        L.act("fog", "a", "new")
        self.assertEqual(walk(L, "fog", "a", [1, 1]), "灯火")       # trust 2 → 好结局，并解锁隐藏选项
        L.act("fog", "a", "new")
        r = L.act("fog", "a", "next", n=50)
        self.assertEqual(len(r["state"]["choice"]["options"]), 4)
        self.assertEqual(walk(L, "fog", "a", [4]), "回信")
        g = L.act("fog", "a", "gallery")
        self.assertEqual(g["endings_total"], 5)
        self.assertEqual(sorted(g["endings"]), sorted(["雾里的背影", "灯火", "回信"]))
        self.assertEqual(g["cg_total"], 3)
        self.assertEqual(g["cg_seen"], 2)
        self.assertIn("隐藏线", g["routes_seen"])

    def test_hints_marks(self):
        L = self.L
        L.act("fog", "h", "new", hints="1")
        r = L.act("fog", "h", "next", n=50)
        self.assertTrue(all("new" in o.get("marks", []) for o in r["state"]["choice"]["options"]))
        walk(L, "fog", "h", [3])
        L.act("fog", "h", "new", hints="1")
        r = L.act("fog", "h", "next", n=50)
        m = {o["i"]: o.get("marks", []) for o in r["state"]["choice"]["options"]}
        self.assertIn("picked", m[3])
        self.assertNotIn("new", m[3])
        self.assertIn("new", m[1])
        L.act("fog", "nh", "new")
        r = L.act("fog", "nh", "next", n=50)
        self.assertFalse(any(o.get("marks") for o in r["state"]["choice"]["options"]))   # 默认不给提示

    def test_ironman(self):
        L = self.L
        L.act("fog", "i", "new", mode="ironman")
        L.act("fog", "i", "next", n=50)
        L.act("fog", "i", "choose", i=1)
        for act, kw in (("rewind", {}), ("save", {"slot": "s1"}), ("load", {"slot": "auto"})):
            with self.assertRaises(PlayError):
                L.act("fog", "i", act, **kw)
        L.act("fog", "i", "new")                                       # 新的一局恢复普通
        L.act("fog", "i", "next", n=50)
        L.act("fog", "i", "choose", i=1)
        L.act("fog", "i", "rewind")

    def test_random_and_reason(self):
        L = self.L
        L.act("fog", "r", "new")
        L.act("fog", "r", "next", n=50)
        r = L.act("fog", "r", "choose", i="random", reason="掷骰子")
        self.assertIn(r["chosen"]["i"], (1, 2, 3))
        self.assertEqual(r["chosen"]["reason"], "掷骰子")
        self.assertEqual(L.act("fog", "r", "profile")["stats"]["reasons"], 1)

    def test_persona(self):
        L = self.L
        L.act("fog", "p", "persona", text="胆小，讨厌冒险")
        L.act("fog", "p", "new")
        r = L.act("fog", "p", "next", n=50)
        self.assertEqual(r["state"]["choice"].get("persona"), "胆小，讨厌冒险")
        txt = render_text(r, "next", False, "fog", "p", "zh")
        self.assertIn("胆小，讨厌冒险", txt)
        self.assertEqual(L.act("fog", "p", "persona")["persona"], "胆小，讨厌冒险")

    def test_english(self):
        L = self.L
        r = L.act("fog-en", "e", "new", lang="en")
        self.assertIn("New game", render_text(r, "new", False, "fog-en", "e", "en"))
        r = L.act("fog-en", "e", "next", n=50)
        t = render_text(r, "next", False, "fog-en", "e", "en")
        self.assertIn("CHOICE", t)
        self.assertIn("Shio: ", t)
        self.assertNotIn("选项", t)

    def test_h_modes(self):
        d = tempfile.mkdtemp()
        try:
            wr(os.path.join(d, "h.gal"),
                "=== a 开头\n开头。\n-> b\n=== b 夜\n@tag h\n夜里的事。\n-> c\n=== c 早上\n早上。\n@end ending 完\n")
            mkbook(self.books, "hbook", "galscript", d)
        finally:
            shutil.rmtree(d)
        out = {}
        for h in ("full", "fold", "skip"):
            self.L.act("hbook", h, "new", h=h)
            r = self.L.act("hbook", h, "next", n=50)
            out[h] = [l["text"] for l in r["state"]["lines"]]
            if not r["state"].get("ended"):
                out[h] += [l["text"] for l in self.L.act("hbook", h, "next", n=50)["state"]["lines"]]
        self.assertIn("夜里的事。", out["full"])
        self.assertNotIn("夜里的事。", out["fold"])
        self.assertNotIn("夜里的事。", out["skip"])
        self.assertIn("早上。", out["skip"])


class TestCLI(Base):
    def run_do(self, *args, **env):
        e = dict(os.environ, GALPLAY_BOOKS=self.books, GALPLAY_DATA=os.path.join(self.tmp, "data"), GALPLAY_BOOK="fog",
                 GALPLAY_AGENT="cli", PYTHONIOENCODING="utf-8")
        e.update(env)
        r = subprocess.run([sys.executable, "-m", "galbook", "do"] + list(args), cwd=ROOT, env=e, capture_output=True)
        return r.returncode, r.stdout.decode("utf-8")

    def test_do(self):
        self.assertIn("fog-en", self.run_do("books")[1])
        rc, out = self.run_do("new", "hints=1")
        self.assertEqual(rc, 0)
        self.assertIn("galbook do next", out)                          # 下一步提示是 CLI 写法
        rc, out = self.run_do("next", "n=50")
        self.assertIn("galbook do choose i=", out)
        rc, out = self.run_do("choose", "i=2", "reason=测试")
        self.assertIn("2/3", out)
        rc, out = self.run_do("choose", "i=2")
        self.assertEqual(rc, 1)
        rc, out = self.run_do("status", "--agent", "other")
        self.assertIn("还没开始", out)
        rc, out = self.run_do("status", "--lang", "en")
        self.assertIn("lines", out)


class TestTools(Base):
    def test_schemas(self):
        o = tools.openai_tools()
        m = tools.mcp_tools()
        self.assertEqual(len(o), len(m))
        names = {t["function"]["name"] for t in o}
        for n in ("galbook_next", "galbook_choose", "galbook_save", "galbook_load", "galbook_rewind"):
            self.assertIn(n, names)
        json.dumps(o)
        json.dumps(m)

    def test_call_tool(self):
        txt = tools.call_tool(self.L, "galbook_new", {"hints": True}, "fog", "t", "zh")
        self.assertIn("新游戏", txt)
        txt = tools.call_tool(self.L, "galbook_next", {"n": 50}, "fog", "t", "zh")
        self.assertIn("选项", txt)

    def test_mcp_stdio(self):
        reqs = [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2024-11-05"}},
                {"jsonrpc": "2.0", "method": "notifications/initialized"},
                {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
                {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "galbook_new", "arguments": {}}},
                {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "galbook_next", "arguments": {"n": 50}}},
                {"jsonrpc": "2.0", "id": 5, "method": "tools/call", "params": {"name": "galbook_choose", "arguments": {"i": 99}}}]
        fin = io.StringIO("".join(json.dumps(r) + "\n" for r in reqs))
        fout = io.StringIO()
        mcp_server.serve(self.L, "fog", "m", "zh", fin, fout)
        res = {j["id"]: j for j in map(json.loads, fout.getvalue().splitlines())}
        self.assertEqual(sorted(res), [1, 2, 3, 4, 5])                 # 通知不回
        self.assertIn("tools", res[1]["result"]["capabilities"])
        self.assertGreaterEqual(len(res[2]["result"]["tools"]), 10)
        self.assertIn("选项", res[4]["result"]["content"][0]["text"])
        self.assertTrue(res[5]["result"].get("isError"))


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


class TestServerAuth(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        books = os.path.join(cls.tmp, "books")
        mkbook(books, "fog", "galscript", os.path.join(DEMO, "fog-harbor"))
        tok = os.path.join(cls.tmp, "tokens.json")
        wr(tok, json.dumps({"alice-key": "alice", "admin-key": "*"}))
        cls.port = free_port()
        cls.proc = subprocess.Popen([sys.executable, "-m", "galbook", "serve", "--books", books, "--data",
                                     os.path.join(cls.tmp, "data"), "--port", str(cls.port), "--tokens", tok, "--quiet"],
                                    cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(50):
            try:
                urllib.request.urlopen("http://127.0.0.1:%d/play/api/books" % cls.port, timeout=1)
                break
            except Exception:
                time.sleep(0.1)

    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate()
        cls.proc.wait(5)
        shutil.rmtree(cls.tmp)

    def code(self, path, token=None):
        req = urllib.request.Request("http://127.0.0.1:%d%s" % (self.port, path))
        if token:
            req.add_header("Authorization", "Bearer " + token)
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status
        except urllib.error.HTTPError as e:
            return e.code

    def mcp(self, body, token=None, query=""):
        req = urllib.request.Request("http://127.0.0.1:%d/mcp%s" % (self.port, query), data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"}, method="POST")
        if token:
            req.add_header("Authorization", "Bearer " + token)
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, (json.loads(r.read().decode("utf-8") or "null"))
        except urllib.error.HTTPError as e:
            return e.code, None

    def test_mcp_http(self):
        init = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
        self.assertEqual(self.mcp(init)[0], 401)
        code, r = self.mcp(init, "alice-key")
        self.assertEqual(code, 200)
        self.assertEqual(r["result"]["serverInfo"]["name"], "galbook")
        self.assertEqual(self.mcp({"jsonrpc": "2.0", "method": "notifications/initialized"}, "alice-key")[0], 202)
        call = {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "galbook_new", "arguments": {}}}
        code, r = self.mcp(call, "alice-key", "?book=fog&agent=mallory")      # 令牌绑定 alice：URL 里的名字不算
        self.assertFalse(r["result"]["isError"], r)
        self.assertTrue(os.path.isdir(os.path.join(self.tmp, "data", "fog", "alice")))
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "data", "fog", "mallory")))
        call["params"]["arguments"] = {"agent": "bob"}
        code, r = self.mcp(call, "alice-key", "?book=fog")
        self.assertTrue(r["result"]["isError"])
        code, r = self.mcp([{"jsonrpc": "2.0", "id": 3, "method": "ping"}, {"jsonrpc": "2.0", "id": 4, "method": "tools/list"}],
                           "admin-key")
        self.assertEqual([x["id"] for x in r], [3, 4])
        self.assertEqual(self.code("/mcp", "admin-key"), 405)

    def test_tokens(self):
        self.assertEqual(self.code("/play/api/books"), 200)             # 书单公开
        self.assertEqual(self.code("/play/t/fog/alice?do=new"), 401)
        self.assertEqual(self.code("/play/t/fog/alice?do=new", "alice-key"), 200)
        self.assertEqual(self.code("/play/t/fog/bob?do=new", "alice-key"), 403)   # 令牌绑定了 alice
        self.assertEqual(self.code("/play/t/fog/bob?do=new", "admin-key"), 200)
        self.assertEqual(self.code("/play/t/fog/alice?do=status&token=alice-key"), 200)
        self.assertEqual(self.code("/play/t/fog/alice?do=new", "wrong"), 401)


if __name__ == "__main__":
    unittest.main()
