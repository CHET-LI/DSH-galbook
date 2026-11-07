"""conv_3days_v2 自测（自制样本，不含原作内容）。
在本目录跑：python3 -m unittest discover -s tests（默认 galbook 仓库在 ../../..，或设 GALBOOK=<仓库目录>）"""
import json, os, sys, tempfile, unittest
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.environ.get("GALBOOK", os.path.abspath(os.path.join(HERE, "..", "..", "..", ".."))))
sys.path.insert(0, os.path.dirname(HERE))
from galbook.importers import load_plugin, get          # noqa
from galbook.ir import validate, save_story, load_story  # noqa
from galbook import engine                               # noqa

SRC = os.path.join(HERE, "sample")


class T(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        load_plugin(os.path.join(os.path.dirname(HERE), "conv_3days_v2.py"))
        cls.meta, cls.scenes = get("3days").build(SRC)
        cls.tmp = tempfile.mkdtemp()
        save_story(cls.tmp, cls.meta, cls.scenes)
        cls.story = load_story(cls.tmp)

    def ops(self, sid):
        return self.scenes[sid]["ops"]

    def test_validate_clean(self):
        self.assertEqual(validate(self.meta, self.scenes), [])
        self.assertEqual(self.meta["stats"]["unknown"], [])

    def test_choice_from_select(self):
        ch = [o for o in self.ops("s-001") if o["op"] == "choice"][0]
        self.assertEqual([o["text"] for o in ch["options"]], ["跟他一起走", "一个人走", "再想想"])  # 注释/空行洗掉
        self.assertEqual(ch["options"][0]["goto"], {"scene": "s-002"})
        self.assertEqual(ch["options"][2]["goto"], {"label": "後で"})

    def test_no_linear_jumps(self):
        for sid, d in self.scenes.items():
            for o in d["ops"]:
                if o["op"] == "jump" and "scene" in o:
                    self.assertNotIn("auto", o)          # 跨场景 jump 全是原作的 .load
                if o["op"] in ("jump", "call", "choice"):
                    self.assertTrue(o.get("src") or o.get("auto"), o)   # 每条要么有原文出处，要么标 auto
                if o.get("auto"):
                    self.assertIn(o.get("note"), ("eof", "case-break"))

    def test_encoding_mixed_and_replace(self):
        self.assertEqual(self.story.scene("s-001").title, "始まり")        # cp932 指令行
        says = [o["text"] for o in self.ops("s-002") if o["op"] == "say"]
        self.assertIn("追", says)                                          # D7B7 不再是 ׷
        self.assertIn("突然", says)                                        # CDBBC8BB 不再是 ͻȻ
        who = [(o["who"], o["text"]) for o in self.ops("s-002") if o["op"] == "say"]
        self.assertIn(("小明", "全角冒号也认。"), who)
        self.assertIn(("", "我暗自发誓：这不是名字。"), who)
        self.assertIn(("？？", "谁？"), who)
        w = self.meta["decode_warnings"]
        self.assertEqual([(x["file"], x["line"]) for x in w], [("s-003.txt", 3)])

    def test_if_else(self):
        s = [o for o in self.ops("s-001") if o["op"] == "say" and "if" in o]
        self.assertEqual(s[0]["if"], "f.一人 && !f.二人")
        self.assertEqual(s[1]["if"], "!(f.一人 && !f.二人)")

    def _run(self, pick):
        st, sysv, seen = engine.new_state(self.story), {}, {}
        r = engine.advance(self.story, st, sysv, seen, n=50)
        self.assertTrue(r.get("choice"), r)
        engine.choose(self.story, st, sysv, pick, "test")
        return st, sysv, seen

    def test_play_branch_1(self):          # 选 1 → .load s-002 → 文件尾 ret 回 a-master → call s-002
        st, sysv, seen = self._run(1)
        r = engine.advance(self.story, st, sysv, seen, n=1)
        self.assertEqual(r["lines"][0]["scene"], "s-002")

    def test_play_branch_2(self):          # 选 2 → case 体 → .endsel 之后 → 第二个（条件）选项出现
        st, sysv, seen = self._run(2)
        r = engine.advance(self.story, st, sysv, seen, n=50)
        texts = [x["text"] for x in r["lines"]]
        self.assertEqual(texts[:3], ["我决定一个人。", "走了以后。", "一个人的时候。"])
        self.assertEqual([o["text"] for o in r["choice"]["options"]], ["甲", "乙"])

    def test_clock_click(self):            # .custom ＤＣ－０１ 記憶Ｍ → 前一句台词上挂 click；.if ＤＣ－０１ 的隐藏选项不动
        says = [o for o in self.ops("s-004") if o["op"] == "say"]
        self.assertNotIn("click", says[0])
        self.assertEqual(says[1]["text"], "時計の針が止まった。")
        self.assertEqual(says[1]["click"], {"id": "ＤＣ－01", "set": "f.ＤＣ－01 = 1", "if": "(f.記憶Ｍ) && (!(f.ＤＣ－01))"})
        ch = [o for o in self.ops("s-004") if o["op"] == "choice"][0]
        self.assertTrue(all(o.get("if") == "f.ＤＣ－01" for o in ch["options"]), ch)   # 同一个变量名（全角数字统一）
        self.assertEqual(self.meta["stats"]["clicks"], 1)
        self.assertEqual(self.meta["stats"]["ignored"].get(".custom"), 1)            # 不带参数的照旧忽略

    def test_clock_click_play(self):
        from galbook.play import Library
        import shutil
        tmp = tempfile.mkdtemp()
        try:
            save_story(os.path.join(tmp, "books", "d", "story"), dict(self.meta, entry={"scene": "s-004"}), self.scenes)
            lib = Library(os.path.join(tmp, "books"), os.path.join(tmp, "data"))
            for mem, hidden in ((0, False), (1, True)):
                lib.act("d", "p%d" % mem, "new")
                st = lib.store.peek_run("d", "p%d" % mem)
                if mem:          # 模拟「之前那一轮记住了」：直接写进这一局的旗
                    with lib.store.session("d", "p1") as S:
                        S.run["f"]["記憶Ｍ"] = 1
                        S.touch_run()
                r = lib.act("d", "p%d" % mem, "next", n=50)
                marks = [ln.get("mark") for ln in r["state"]["lines"]]
                self.assertEqual("◇" in marks, hidden, marks)
                self.assertNotIn("choice", r["state"])               # 不点：直接走默认 .load
                c = lib.act("d", "p%d" % mem, "click")
                self.assertEqual(c["clicked"], hidden)
                if hidden:
                    r = lib.act("d", "p1", "next", n=50)
                    self.assertEqual([o["text"] for o in r["state"]["choice"]["options"]], ["戻る", "進む"])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
