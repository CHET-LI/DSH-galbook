# galbook/1 中间格式（引擎无关 IR）

一句话：**每个引擎的导入器把原脚本翻成同一种「指令列表」，播放器只认这一种**。新引擎 = 新写一个导入器，播放器、存档、HTTP、界面一行不改。

## 1. 文件布局

```
books/<书>/
├── assets/…                    图片（路径相对书目录；服务只对外放这个目录）
└── story/                      python3 -m galbook build 的输出
    ├── story.json              目录 + 路线 + 统计
    └── scenes/<文件>.json      每个场景一份指令列表
```

兼容：没有 `story/`、只有 `book.json + chNNN.json`（一种简单的「书稿」格式：章节 + 段落）的目录也能玩，`importers/legacy.py` 把它当成一条直线。

## 2. story.json

| 字段 | 说明 |
|---|---|
| `format` | 固定 `"galbook/1"` |
| `title` / `engine` / `importer` | 书名 / 原引擎 / 导入器名+版本 |
| `mode` | `branch`（默认）或 `linear`（文本导出类导入器，没有分支） |
| `entry` | `{"scene", "label"}` 新游戏从哪开始 |
| `scenes` | `{"<id>": {"title", "file", "tags": ["h"…], "route"}}`；`tags` 含 `h` 的场景按玩家的 `h` 选项处理（默认折叠） |
| `routes` | `[{"id", "title", "start": {"scene","label"}}]` 路线标签（给 agent 看「我在哪条线」） |
| `system_vars` | 跨周目变量名（通关标记等），存在 agent 的 profile 里，`new` 不清 |
| `stats` | 导入统计：台词数、选项数、跳转数、未翻译的条件、图片命中率、未识别指令 Top20 |
| `warnings` | 导入时的问题（指名文件和行号） |

## 3. 指令（op）

任何指令都可以带 `"if": "<条件>"`，条件不成立就跳过这一条（`choice` 里是每个选项单独的 `if`）。

| op | 字段 | 说明 |
|---|---|---|
| `say` | `who`, `text`, `voice?` | 一句台词；`who=""` 是旁白。`text` 保留 `[rb,漢字,かな]` 注音，文本接口会去掉 |
| `bg` | `img` \| null | 背景，同时清掉 CG |
| `cg` | `img` \| null | 事件图（盖住背景） |
| `sprite` | `name`, `img` \| null, `pos` | 立绘上场/换表情；`img=null` 下场 |
| `sprites_clear` | — | 全部立绘下场 |
| `bgm` | `name` \| null | 背景音乐（只记名字） |
| `label` | `name` | 跳转目标；`__` 开头是导入器生成的内部标签 |
| `choice` | `id`, `prompt`, `options[]`, `auto_single?` | **选项**。`options: [{"text", "goto": {"scene","label"}, "set?", "if?"}]`；`auto_single=true` 时只剩一个可选项就自动走（例：没解锁隐藏线时的路线选择） |
| `jump` | `scene?`, `label?` | 跳转；省略 `scene` = 本场景内 |
| `call` / `ret` | 同 jump / — | 子程序调用和返回（KAG `[call]`、Ren'Py `call`、NScripter `gosub`） |
| `set` | `expr` | 改变量，例 `f.trust += 1; s.clear_a = 1` |
| `event` | `name`, `arg` | 只做标记给 agent 看（片尾、转场、影片） |
| `end` | `kind`, `name?`, `how?` | 结束：`ending` 结局 / `title` 回标题 / `stop` 停住；没写 name 时用「场景·最后经过的标签」 |

`cg` 指令出现过的图会进「收集」（`gallery`）；`end kind=ending` 的个数就是结局总数。

## 4. 变量和条件

- `f.x`：本周目变量（存在存档里）；`s.x`：系统变量（跨周目，存在 agent 的 profile 里）。
- 条件/赋值是一个很小的安全子集（`expr.py`，用 `ast` 白名单求值，**不 eval**）：数字、字符串、`== != < <= > >=`、`&& || !`、`+ - * / %`、`= += -=`，多条用 `;`。没定义的变量当 0（和多数引擎一致）。
- 各引擎怎么映射：

| 引擎 | 本周目 | 跨周目 |
|---|---|---|
| QLIE | 普通变量 → `f.` | `#X` → `s.X` |
| KAG / Tyrano | `f.` → `f.`；`tf.x` → `f.tf_x` | `sf.` → `s.` |
| Ren'Py | `default`/普通变量 → `f.` | `persistent.X` → `s.X` |
| NScripter | `%0–%199` → `f.vN`；`$N` → `f.strN` | `%200` 起（globalon 全局区）→ `s.vN` |
| galscript（.gal） | `f.` | `s.` |

## 5. 校验（`ir.validate`）

`build` 写文件前必须过：每个 `jump/call/choice.goto` 的场景和标签都存在、`entry` 存在、op 名都认识、`choice` 至少一个选项。不过就不写（`--force` 才写），并逐条列出「哪个场景第几条指令指向了不存在的什么」。

## 6. 玩家状态（存档里存的就是它）

```json
{"scene": "common_day13", "pc": 1823, "stack": [], "f": {}, "vis": {"bg","cg","sprites","bgm"},
 "pending": {"id","options":[…],"shown_at"} | null, "ended": null | {…},
 "turn": 5120, "choices": [{"title","text","i","of","reason","think_s","auto"}],
 "log": [最近 300 句], "rewind": [最近 30 个选项点的快照], "label": "…", "opts": {"h": "fold", "mode": "normal", "hints": false, "lang": "zh"}}
```

存档 = 这份状态的完整拷贝，所以读档、回溯都是精确的（不是「从章节开头重放」）。

## 7. agent 档案（profile，跨周目）

`s` 系统变量、已读、玩过的结局/路线/CG、选过的选项（给「提示」用）、人设 `persona`、统计（台词数、选择数、写了理由的次数、存/读/回溯次数）。`profile` 动作里的 `humanlike` 是一组「像不像人在玩」的指标：每次选择前读了几句、理由率、思考时间中位数、是不是总选第一个。
