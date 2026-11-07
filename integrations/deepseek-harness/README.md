# 接 DeepSeek Harness（dsh）

dsh 有三条路能用 galbook，可以同时开（推荐 **MCP + 技能**：MCP 给工具，技能告诉模型怎么像人一样玩）。
在 dsh `0.2.2-rc.1` 上实测过，见文末「自测」。

## 1. MCP（stdio，dsh 自己起 galbook 进程）

把 [`galbook.patch.yml`](galbook.patch.yml) 里的路径改成你的，然后：

```bash
dsh web --patch integrations/deepseek-harness/galbook.patch.yml            # 临时挂
# 常驻：把 insert 那段合进 $DSH_HOME/profiles/<profile>/cordis.patch.yml
```

工具会以 `mcp__galbook__galbook_next` 这样的名字出现（共 15 个）。`--book` / `--agent` 是默认值，模型也可以在参数里换。

Windows 注意：`command` 写 `python`（或 `py`）；路径用正斜杠或双反斜杠；`env` 里保留 `PYTHONIOENCODING: utf-8`。

## 2. MCP（Streamable HTTP，多个 agent 共用一个服务）

```bash
python3 -m galbook serve --books books --data play-data --tokens tokens.json    # tokens.json: {"口令A": "alice", "口令B": "bob"}
GALBOOK_TOKEN=口令A dsh web --patch integrations/deepseek-harness/galbook-http.patch.yml
```

见 [`galbook-http.patch.yml`](galbook-http.patch.yml)。令牌绑定了名字时，不管 URL 里写的 `agent=` 是什么，都按令牌的名字玩（防冒名）。

## 3. 技能（Skill）+ CLI

技能文件：[`/.agents/skills/galbook/SKILL.md`](../../.agents/skills/galbook/SKILL.md)（Anthropic 技能格式）。

- 在本仓库里启动 dsh：自动发现（项目级 `.agents/skills`）
- 全局使用：`cp -r .agents/skills/galbook ~/.agents/skills/`（或 `~/.dsh/skills/`），重启 dsh

技能里写了：有 MCP 工具就用 MCP；没有就用 shell 跑 CLI：

```bash
export GALBOOK_BOOKS=/path/books GALBOOK_DATA=/path/play-data GALBOOK_BOOK=fog-harbor GALBOOK_AGENT=dsh
python3 -m galbook do new
python3 -m galbook do next n=20
python3 -m galbook do choose i=2 reason="……"
```

CLI 的输出最后一行会写好下一步的命令（`选：galbook do choose i=编号 reason=…`），模型照抄就行。

技能还要求模型**不要直接读 `books/*/story/` 里的剧本 JSON**（防剧透作弊）。这是提示层面的约束；要硬隔离，就只给 dsh 开 MCP / HTTP，不让它碰 books 目录（dsh 的文件沙盒默认只放工作目录）。

## 自测（不需要 API key，不花钱）

```bash
npm i -g @deepseek-ai/dsh
bash integrations/deepseek-harness/selftest/selftest.sh
```

[`selftest/mock_model.py`](selftest/mock_model.py) 是一个假的 Anthropic Messages 端点（dsh 的 DeepSeek 适配器走 Messages 协议，`DEEPSEEK_BASE_URL` 指过去），按固定脚本让 dsh 依次调用 galbook：MCP 路线 `help → persona → new → next → choose → next`，CLI 路线 `skill → bash(do new) → bash(do next) → bash(do choose) → bash(do next)`。它只证明「挂得上、调得通、技能被发现」；真正玩得像不像人，要接真模型（`DEEPSEEK_API_KEY`）看。

2026-11-06 在 Linux、dsh 0.2.2-rc.1、Python 3.13 上的输出（节选）：

```
== mcp：每一步（galbook 工具数 / 技能可见 / 第几步 / 上一步结果开头）
  14 True 1 galbook —— 像人一样玩 galgame（galbook-1.1） | …
  14 True 2 人设已记下 | 当前人设：好奇心重，胆子大 |
  14 True 3 新游戏开始（第 1 周目） | 本局：H=fold 模式=normal 提示=0 语言=zh | …
  14 True 5 你选了：「我陪你去。」（1/3） | 继续：galbook_next() |
  14 True 6 【仓库】第 8 句 | 冰冷的海水没过脚踝。…
== cli：每一步
  0 True 1 <skill_content name="galbook"> | …
  0 True 2 新游戏开始（第 1 周目） | …
  0 True 4 你选了：「我在这儿帮你看着灯。」（2/3） | 继续：galbook do next | …
== 玩家档案：
dsh-agent
dsh-cli
```
