# 接入 agent

服务：`python3 -m galbook serve --books books --data play-data [--host 127.0.0.1 --port 8765 --lang zh|en --token X | --tokens f.json --cors]`

`<book>` 是 `books/` 下的目录名，`<agent>` 是玩家名（随便起，字母数字下划线最稳）。每个名字一份独立档案和存档，同时玩互不影响；同一个名字的并发请求会排队，不会写坏文件。

## 1. 纯文本接口（推荐，最省 token）

`GET /play/t/<book>/<agent>?do=<动作>&参数…` → 纯文本。`GET /play/t` 是给 agent 看的完整说明（`?lang=en` 英文），可以直接放进 system prompt。

| do | 参数 | 说明 |
|---|---|---|
| `status` | `vis=0\|1` | 现在在哪、最近几句、有没有待选的选项 |
| `new` | `h=fold\|full\|skip` `mode=normal\|ironman` `hints=1` `lang=zh\|en` | 新的一局（跨周目变量、已读、收集都保留） |
| `next` | `n=条数(默认10)` `skip=1` `img=1` `vis=0\|1` | 往下读，遇到选项/结局停。画面变了才多一行 `〔画面〕bg=… \| sp=名字:位置(表情码)`（有 CG 时只写 `cg=`；书里有图时默认开）；`img=1` 只在第一次见到的 CG 和结局那屏给图地址 `〔图〕… /b/<书>/<路径>` |
| `look` | `bg=1` | 看一眼现在的画面：CG，或在场每个人的立绘（MCP `galbook_look` 直接返回图片） |
| `choose` | `i=编号\|random` `reason=一句理由` | 选，并写为什么（会记下来，网页能看到） |
| `save` / `load` | `slot=名字` `note=备注` | 存/读档；每次遇到选项会自动存 `auto` |
| `saves` | — | 存档列表 |
| `rewind` | `steps=1` | 回到上一个（第 N 个）选项点重选 |
| `log` | `n=30` | 回想：最近的台词和做过的选择 |
| `persona` | `text=…`（不带就是查看） | 人设，每次遇到选项都会提醒 |
| `gallery` | — | 收集：结局/路线/CG/已读 |
| `profile` | — | 统计和「像不像人」指标 |

推荐给 agent 的玩法提示（`/play/t` 里也有）：一次读 10–30 句；选之前回想一下人物和自己的人设；`reason` 写真实想法；第一遍别开 `hints`；想看别的结局就 `rewind` 或 `new`。

表情码 = 立绘文件名去掉角色名（例 `雫_中_02_01_01.png` → `中_02_01_01`）。它不是表情的名字，但同一个码就是同一张脸；`look` 看过一次就知道这个码长什么样。

## 2. JSON 接口

`GET|POST /play/api/<book>/<agent>/<动作>`，参数放 query 或 JSON body，和文本接口同名。返回 `{"ok": true, "state": {...}, ...}`，出错 `{"ok": false, "error": "…"}`（HTTP 400）。

- `GET /play/api/books`：书单
- `GET /play/api/<book>/players`：这本书所有玩家的进度（网页用）

`state` 里：`lines`（台词 `{who, text}`）、`choice`（`{prompt, options: [{i, text, marks?}], persona?}`）、`ended`、`where`、`vis`（当前画面）、`opts`。完整例子：[`examples/agent_player.py`](../examples/agent_player.py)。

## 3. MCP

```bash
python3 -m galbook mcp --books books --data play-data --book fog-harbor --agent alice [--lang en]
```

stdio JSON-RPC，实现了 `initialize` / `ping` / `tools/list` / `tools/call`。`--book` / `--agent` 是默认值，工具参数里也能另外指定。Claude Desktop / Cursor 等的配置：[`examples/mcp_config.example.json`](../examples/mcp_config.example.json)（没 `pip install` 的话把 `cwd` 设到仓库根目录，或者设 `PYTHONPATH`）。

工具：`galbook_books` `galbook_help` `galbook_status` `galbook_new` `galbook_next` `galbook_choose` `galbook_save` `galbook_load` `galbook_saves` `galbook_rewind` `galbook_log` `galbook_persona` `galbook_gallery` `galbook_profile`。返回都是纯文本（同文本接口）。

### MCP over HTTP

`python3 -m galbook serve` 同时提供 `POST /mcp`（Streamable HTTP，只回 JSON，不开服务端推送流；`GET /mcp` 返回 405）。默认书和名字用 `?book=…&agent=…` 或请求头 `X-Galplay-Agent`。开了 `--tokens` 时，令牌绑定的名字优先，模型在参数里写别的名字会被拒绝。

## 4. CLI（给只有 shell 的 agent）

```bash
export GALBOOK_BOOKS=books GALBOOK_DATA=play-data GALBOOK_BOOK=fog-harbor GALBOOK_AGENT=alice
python3 -m galbook do help | books | status | new hints=1 | next n=20 | choose i=2 reason="…" | save slot=x | load slot=x | rewind | log | persona text="…" | gallery | profile
```

参数都是 `k=v`；`--book/--agent/--books/--data/--lang` 可以覆盖环境变量。输出和文本接口一样，最后一行是下一步要跑的命令。出错时退出码 1。

## 5. 技能（Skill）

[`.agents/skills/galbook/SKILL.md`](../.agents/skills/galbook/SKILL.md)：告诉模型怎么像人一样玩、先用 MCP 再用 CLI、不要偷看剧本文件。dsh 会自动扫描 `<项目>/.agents/skills`、`~/.agents/skills`、`~/.dsh/skills`；Claude Code 用 `.claude/skills/`。DeepSeek Harness 的完整配置见 [integrations/deepseek-harness](../integrations/deepseek-harness/)。

## 6. OpenAI function calling

```python
from galbook.play import Library
from galbook import tools
lib = Library("books", "play-data")
TOOLS = tools.openai_tools()                 # 传给 chat.completions 的 tools=
# 模型返回 tool_call 后：
text = tools.call_tool(lib, call.function.name, json.loads(call.function.arguments),
                       default_book="fog-harbor", default_agent="alice", lang="zh")
```

或者 `python3 -m galbook tools --format openai > tools.json`。

## 7. 令牌（公开部署时）

- `--token X`（或环境变量 `GALBOOK_TOKEN`）：一个共享口令
- `--tokens tokens.json`：`{"口令A": "alice", "口令B": "bob", "管理员": "*"}`，口令绑定玩家名，用别人的名字 → 403

传法：`Authorization: Bearer <口令>`，或 `?token=<口令>`。书单 `/play/api/books` 和图片不需要口令；`/play/api`、`/play/t`、`/mcp` 都要。网页：`/play/?token=<口令>`。

服务只对外放 `books/<书>/assets/` 下的图，剧本 JSON 不外露。默认只听 127.0.0.1；要对外请放在反向代理（HTTPS）后面并开令牌。

## 8. 多 agent 小实验

```bash
python3 examples/party.py --book fog-harbor                 # 6 个不同人设同时玩
python3 examples/agent_player.py --book fog-harbor --agent me --decider llm --persona "……"
```

`agent_player.py` 的 `--decider`：`llm`（环境变量 `OPENAI_BASE_URL` `OPENAI_API_KEY` `MODEL`，任何 OpenAI 兼容接口）、`keyword`（人设关键词打分，不花钱）、`random`。
