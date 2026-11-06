"""python3 -m unittest discover -s tests -v   （在 galplay/ 目录下跑；只用自带样例，不碰任何商业游戏数据）"""
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
SAMPLES = os.path.join(HERE, "samples")

from galplay import engine  # noqa: E402
from galplay.expr import evaluate, assign  # noqa: E402
from galplay.importers import detect, get  # noqa: E402
from galplay.importers.common import Assets  # noqa: E402
from galplay.ir import validate, story_from_dict, save_story, load_story  # noqa: E402
from galplay.play import Library  # noqa: E402

ENGINES = ("qlie", "kag", "renpy", "nscripter")


def build(eng):
    meta, scenes = get(eng).build(os.path.join(SAMPLES, eng), assets=Assets.from_list(os.path.join(SAMPLES, "assets_demo.txt")))
    return meta, scenes


def play(story, sysv, seen, want):
    """want: 依次要选的选项里包含的字；返回 (台词列表, 结局, 每次看到的选项列表)。"""
    st = engine.new_state(story)
    lines, seen_opts, want = [], [], list(want)
    for _ in range(200):
        r = engine.advance(story, st, sysv, seen, n=50)
        lines += [l["text"] for l in r["lines"]]
        if r.get("choice"):
            opts = [o["text"] for o in r["choice"]["options"]]
            seen_opts.append(opts)
            w = want.pop(0)
            i = next(k for k, t in enumerate(opts, 1) if w in t)
            engine.choose(story, st, sysv, i, "test")
        elif r.get("ended"):
            return lines, r["ended"], seen_opts
    raise AssertionError("没走完")


class TestExpr(unittest.TestCase):
    def test_basic(self):
        f, s = {"a": 1}, {"clear": 0}
        self.assertTrue(evaluate("f.a==1 && !s.clear", f, s))
        assign("f.a+=2; s.clear=1", f, s)
        self.assertEqual((f["a"], s["clear"]), (3, 1))
        self.assertTrue(evaluate("f.missing==0", f, s))   # 没定义的变量当 0，和多数引擎一致
        self.assertTrue(evaluate(None, f, s))


class TestImporters(unittest.TestCase):
    def test_detect(self):
        for e in ENGINES:
            self.assertEqual(detect(os.path.join(SAMPLES, e))[0], e)
        self.assertIsNone(detect("/nonexistent-dir")[0])

    def test_build_validate_and_unlock(self):
        """四种引擎同一个小故事：选「手伝う」→ 灯火结局并记系统变量；再开一局，隐藏选项「岩屋」出现并能走到。"""
        for e in ENGINES:
            with self.subTest(engine=e):
                meta, scenes = build(e)
                self.assertEqual(validate(meta, scenes), [])
                self.assertEqual(meta["warnings"], [])
                story = story_from_dict(meta, scenes)
                sysv, seen = {}, {}
                if e == "qlie":
                    lines, end, opts = play(story, sysv, seen, ["手伝う"])
                else:
                    lines, end, opts = play(story, sysv, seen, ["手伝う"])
                self.assertIn("二人で灯りを守った。夜明けまで。", lines)
                self.assertFalse(any("岩屋" in t for t in opts[0]), opts)
                self.assertTrue(any(v for v in sysv.values()), sysv)
                # 第二周目：隐藏线解锁
                want = ["岩屋"]
                lines2, end2, opts2 = play(story, sysv, seen, want)
                self.assertTrue(any("岩屋" in t for t in opts2[0]), opts2)
                self.assertIn("岩屋の奥で、古い航海日誌を見つけた。", lines2)

    def test_other_branch(self):
        for e in ENGINES:
            with self.subTest(engine=e):
                story = story_from_dict(*build(e))
                lines, end, _ = play(story, {}, {}, ["帰る"])
                self.assertIn("帰り道、振り返ると灯りはまだ揺れていた。", lines)
                self.assertNotIn("二人で灯りを守った。夜明けまで。", lines)

    def test_speakers_and_visuals(self):
        story = story_from_dict(*build("qlie"))
        st = engine.new_state(story)
        r = engine.advance(story, st, {}, {}, n=3)
        self.assertEqual([l["who"] for l in r["lines"]], ["", "灯", "誠"])
        self.assertEqual(r["lines"][1]["vis"]["bg"], "assets/bg_001.png")
        self.assertEqual(r["lines"][1]["vis"]["sprites"][0]["img"], "assets/立ち絵/中/灯_中_01_01_01.png")

    def test_legacy_encodings(self):
        """老作品常见编码：QLIE 剧本是 cp932；NScripter 是 nscript.dat（cp932 再每字节 XOR 0x84）。
        仓库里样例存 UTF-8，这里现场转成老编码再导一遍，结果必须完全一样。"""
        d = tempfile.mkdtemp()
        try:
            q = os.path.join(d, "qlie")
            shutil.copytree(os.path.join(SAMPLES, "qlie"), q)
            for dp, _, fn in os.walk(q):
                for f in fn:
                    p = os.path.join(dp, f)
                    with open(p, encoding="utf-8") as fh:
                        t = fh.read()
                    with open(p, "wb") as fh:
                        fh.write(t.replace("\n", "\r\n").encode("cp932"))
            n = os.path.join(d, "nscripter")
            os.makedirs(n)
            with open(os.path.join(SAMPLES, "nscripter", "0.txt"), encoding="utf-8") as fh:
                t = fh.read()
            with open(os.path.join(n, "nscript.dat"), "wb") as fh:
                fh.write(bytes(b ^ 0x84 for b in t.replace("\n", "\r\n").encode("cp932")))
            a = Assets.from_list(os.path.join(SAMPLES, "assets_demo.txt"))
            for e, src in (("qlie", q), ("nscripter", n)):
                m1, s1 = build(e)
                m2, s2 = get(e).build(src, assets=a)
                self.assertEqual(s1, s2, e)
                self.assertEqual(m1["stats"]["says"], m2["stats"]["says"])
            self.assertEqual(m2["stats"].get("origin"), "nscript.dat")
        finally:
            shutil.rmtree(d)

    def test_save_load_story_roundtrip(self):
        d = tempfile.mkdtemp()
        try:
            meta, scenes = build("kag")
            save_story(d, meta, scenes)
            s2 = load_story(d)
            self.assertEqual(set(s2.scenes), set(scenes))
        finally:
            shutil.rmtree(d)


class TestLibrary(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.books = os.path.join(self.tmp, "books")
        meta, scenes = build("renpy")
        save_story(os.path.join(self.books, "light", "story"), meta, scenes)
        demo = os.environ.get("GALPLAY_DEMO_BOOK", "")   # 可选：一本旧版 book.json + chNNN.json 书稿
        if demo and os.path.isdir(demo):
            shutil.copytree(demo, os.path.join(self.books, "demo"))
        self.lib = Library(self.books, os.path.join(self.tmp, "data"))

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_save_load_rewind(self):
        L = self.lib
        L.act("light", "a", "new")
        r = L.act("light", "a", "next", n=50)
        self.assertIn("choice", r["state"])
        self.assertEqual([s["slot"] for s in L.act("light", "a", "saves")["saves"]], ["auto"])
        L.act("light", "a", "choose", i=2, reason="帰りたい")
        r = L.act("light", "a", "next", n=50)
        self.assertEqual(r["state"]["ended"]["kind"], "title")
        L.act("light", "a", "save", slot="5")
        r = L.act("light", "a", "load", slot="auto")
        self.assertIn("choice", r["state"])
        L.act("light", "a", "choose", i=1)
        r = L.act("light", "a", "next", n=50)
        self.assertIn("二人で灯りを守った。夜明けまで。", [l["text"] for l in r["state"]["lines"]])
        r = L.act("light", "a", "rewind")
        self.assertIn("choice", r["state"])
        p = L.act("light", "a", "profile")
        self.assertEqual(p["system_vars"].get("clear_a"), True)
        self.assertEqual(p["stats"]["loads"], 1)

    def test_skip_read(self):
        L = self.lib
        for _ in range(2):
            L.act("light", "b", "new")
            r = L.act("light", "b", "next", n=50, skip_read=True)
        self.assertGreater(r["state"]["skipped"], 0)

    def test_agents_isolated_and_readonly(self):
        L = self.lib
        L.act("light", "x", "new")
        L.act("light", "x", "next", n=50)
        L.act("light", "spectator", "status")   # 只看不建档
        names = [p["agent"] for p in L.store.agents("light")]
        self.assertEqual(names, ["x"])
        with self.assertRaises(Exception):
            L.act("light", "../evil", "new")
        with self.assertRaises(Exception):
            L.act("light", "x", "save", slot="../../x")

    def test_legacy_book(self):
        if not os.path.isdir(os.path.join(self.books, "demo")):
            self.skipTest("没设 GALPLAY_DEMO_BOOK")
        L = self.lib
        L.act("demo", "r", "new")
        for _ in range(100):
            r = L.act("demo", "r", "next", n=50)
            if r["state"].get("ended"):
                break
            if r["state"].get("choice"):
                L.act("demo", "r", "choose", i=1)
        self.assertTrue(r["state"].get("ended"))


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


class TestHTTPConcurrent(unittest.TestCase):
    """真起 python3 -m galplay serve，50 个 agent 同时玩；再 20 个线程抢同一个 agent。"""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        meta, scenes = build("nscripter")
        save_story(os.path.join(cls.tmp, "books", "light", "story"), meta, scenes)
        os.makedirs(os.path.join(cls.tmp, "books", "light", "assets"))
        with open(os.path.join(cls.tmp, "books", "light", "assets", "bg.svg"), "w") as f:
            f.write("<svg xmlns='http://www.w3.org/2000/svg'/>")
        cls.port = free_port()
        cls.proc = subprocess.Popen([sys.executable, "-m", "galplay", "serve", "--books", os.path.join(cls.tmp, "books"),
                                     "--data", os.path.join(cls.tmp, "play-data"), "--port", str(cls.port), "--quiet"],
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

    def get(self, path):
        with urllib.request.urlopen("http://127.0.0.1:%d%s" % (self.port, path), timeout=20) as r:
            return r.status, r.read().decode("utf-8")

    def code(self, path):
        try:
            return self.get(path)[0]
        except urllib.error.HTTPError as e:
            return e.code

    def test_routes(self):
        self.assertEqual(self.get("/")[0], 200)                       # 302 → /play/
        self.assertIn("galplay", self.get("/play/")[1])
        self.assertIn("/play/t/", self.get("/play/t")[1])
        self.assertIn("do=next", self.get("/play/t?lang=en")[1])
        self.assertEqual(self.code("/b/light/assets/bg.svg"), 200)
        self.assertEqual(self.code("/b/light/story/story.json"), 403)   # 只放 assets/，剧本不外露
        self.assertEqual(self.code("/b/light/assets/../story/story.json"), 403)
        self.assertEqual(self.code("/b/light/assets/%2e%2e/story/story.json"), 403)

    def test_50_agents(self):
        errs, endings = [], {}

        def agent(k):
            try:
                name = "agent%02d" % k
                pick = 1 + k % 2
                self.get("/play/t/light/%s?do=new" % name)
                for _ in range(30):
                    _, t = self.get("/play/t/light/%s?do=next&n=5" % name)
                    if "—— 选项" in t:
                        self.get("/play/t/light/%s?do=choose&i=%d&reason=%s" % (name, pick, urllib.parse.quote("测试")))
                    elif "—— 结束" in t:
                        endings[name] = t
                        return
                errs.append("%s 没走完" % name)
            except Exception as e:  # noqa
                errs.append("%s: %r" % (k, e))

        ts = [threading.Thread(target=agent, args=(k,)) for k in range(50)]
        [t.start() for t in ts]
        [t.join(60) for t in ts]
        self.assertEqual(errs, [])
        self.assertEqual(len(endings), 50)
        for k in range(50):
            want = "二人で灯りを守った" if k % 2 == 0 else "帰り道"
            self.assertIn(want, endings["agent%02d" % k])
        pl = json.loads(self.get("/play/api/light/players")[1])["players"]
        self.assertEqual(len(pl), 50)

    def test_same_agent_hammer(self):
        self.get("/play/t/light/hammer?do=new")
        errs = []

        def hit():
            try:
                self.get("/play/t/light/hammer?do=status")
                self.get("/play/t/light/hammer?do=save&slot=quick")
            except Exception as e:  # noqa
                errs.append(repr(e))
        ts = [threading.Thread(target=hit) for _ in range(20)]
        [t.start() for t in ts]
        [t.join(30) for t in ts]
        self.assertEqual(errs, [])
        d = os.path.join(self.tmp, "play-data", "light", "hammer")
        for fn in ("profile.json", "run.json", os.path.join("saves", "quick.json")):
            with open(os.path.join(d, fn), encoding="utf-8") as f:
                json.load(f)   # 文件都是完整 JSON
        self.assertEqual([f for f in os.listdir(d) if ".tmp" in f], [])


if __name__ == "__main__":
    unittest.main()
