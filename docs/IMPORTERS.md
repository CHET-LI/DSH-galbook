# 导入器：.gal 格式、文本导出、写插件

## 1. `.gal` 手写格式

给自己写故事、手工移植、或者给某个引擎写「转换脚本」的输出目标。一个目录里可以有多个 `.gal`，按文件名顺序读。完整例子：[`galbook/demo/fog-harbor/story.gal`](../galbook/demo/fog-harbor/story.gal)。

```
title: 我的故事            ← 文件开头的 key: value 是元信息（title / author / license …）

=== prologue 序章          ← 新场景：id + 标题
@bg harbor_night           ← 背景（按文件名在 assets 里找）
@show 汐 shio_normal center
旁白直接写。
汐：「台词用全角冒号或「: 」分开，名字 ≤12 字。」
汐「或者名字后面直接跟引号。」
? 你会怎么做？              ← 选项（提示语可省略）
- 「我陪你去。」 -> help do f.trust += 1
- 「隐藏选项」 -> secret if s.cleared
* help                     ← 标签
-> warehouse               ← 跳转：本场景标签 / 场景 id / 场景id#标签
if f.trust >= 2 -> good    ← 条件跳转（也可写 -> good if f.trust >= 2）
$ s.cleared = 1            ← 赋值；f. 本周目，s. 跨周目
call sub                   ← 子程序；return 返回
@end ending 结局名          ← 结束：ending / title / stop
```

其他指令：`@cg 图`、`@cg none`、`@hide 名字`、`@clear`（立绘全下）、`@bgm 名字`、`@event 名字 参数`、`@route 路线名`（标记本场景属于哪条线）、`@tag h`（标记成 H 场景，受玩家的 `h` 选项控制）。`#` 开头是注释。

出错时会指明 `文件:行号`；跳到不存在的目标会在校验时报出来。

## 2. 文本导出（textdump，线性）

`--engine textdump` 吃这三种：

- **VNTextPatch JSON**：`VNTextPatch extractlocal <脚本目录> <输出目录>` 的输出，`[{"name": "灯", "message": "…"}, {"names": ["A","B"], "message": "…"}, {"message": "旁白"}]`
- **CSV / TSV**：表头里要有台词列（`message/text/line/original/原文/台词/本文/セリフ`），可选名字列（`name/speaker/character/who/名前/名字/角色`）
- **TXT**：一行一句，`名字：台词`、`名字「台词」` 或旁白

一个文件 = 一个场景，按文件名自然排序串起来；目录里放 `order.txt`（一行一个文件名）可以自定顺序。自动识别只认 JSON 和带表头的 CSV；纯 TXT 要显式 `--engine textdump`。

## 3. 写插件

插件就是一个 `.py`：

```python
NAME = "myengine"

def detect(src):                      # 可选：自动识别
    return True, "依据"  # 或 (False, "")

def build(src, assets=None, **opts):  # 必须：返回 (meta, scenes)
    ...
```

`scenes` 是 `{场景id: {"id", "title", "ops": [...], "tags": [], "route": ""}}`，`ops` 是 [SCHEMA.md](SCHEMA.md) 里的指令；`meta` 至少要有 `format: "galbook/1"`、`entry`、`scenes`。`importers/common.py` 里有现成的帮手：`SceneB`（攒指令）、`Assets`（按文件名找图，`assets.find(name)`）、`read_text`（自动认 UTF-8/Shift-JIS/GBK）、`is_h_title`。最小的完整例子：[`tests/plugins/myfmt.py`](../tests/plugins/myfmt.py)。

用法：

```bash
python3 -m galbook build --plugin myengine.py --src 解包目录 --out books/x/story
GALPLAY_PLUGINS=/path/to/plugins python3 -m galbook detect 解包目录    # 目录或文件，多个用 : 分隔（Windows 用 ;）
```

插件比内置导入器先识别。`build` 会跑同一套校验，所以插件输出错了也会被指出来。写好了欢迎 PR 进 `galbook/importers/`。

### 写导入器的建议

1. 先拿一个小样本写测试（自己编几行同语法的脚本，**别提交真游戏的文本**）
2. 先只认台词和跳转，跑通 `build` 校验；再加选项、条件、变量
3. 不认识的指令进 `stats.unknown` 计数，别静默丢；需要猜的地方写进 `warnings`
4. 变量映射：本周目 → `f.`，跨周目（通关标记）→ `s.`，写进 `meta["system_vars"]`
