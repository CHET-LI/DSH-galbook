# 3days 导入插件（示例）

把《3days ～満ちてゆく刻の彼方で～》中文版的 `data/script/*.txt`（RealLive 系文本脚本）转成 galbook 剧本，带上原作的 `.select` 分支和 `.if` 条件。
本目录只有转换代码和**自制**的测试样本，不含任何游戏内容；请只导入你自己合法拥有的游戏。

```bash
python3 -m galbook build --src <游戏目录>/data/script --out books/3days/story \
        --plugin examples/plugins/3days/conv_3days_v2.py --engine 3days --strict
cd examples/plugins/3days && python3 -m unittest discover -s tests
```

- `.select / .case / .endsel` → `choice`；`.load` → `jump`；`.call` → `call`；`.goto #L` → 本场景 `jump`；`.exit` → `ret`；`.if {…} .else {…}` → 每条指令的 `if`
- 指令/变量名是 cp932、正文是 gbk 的混写脚本：逐行按 `utf-8-sig → cp932 → gbk → big5 → utf-16` 试，排除明显乱码；全失败才 `errors="replace"` 并把 文件:行号 记进 `decode_warnings`
- 转换器自己补的指令都带 `"auto": true`（`.case` 结束跳出、文件尾 `ret`），每条原作控制流带 `src: 文件:行`
