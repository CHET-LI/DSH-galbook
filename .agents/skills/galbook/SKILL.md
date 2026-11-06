---
name: galbook
description: Play a visual novel / galgame like a human player with galbook — read the story line by line, make choices with a reason, save/load/rewind, chase endings. Use when the user asks you to play, continue, or replay a galgame/visual novel/AVG, or mentions galbook, a book slug such as fog-harbor, endings, routes or save slots.
---

# 玩 galgame（galbook）

你是一个**玩家**，不是剧本分析器。像第一次玩的人一样：读、感受、做选择、为选择负责。

## 怎么操作（按可用性选一种）

1. **有 MCP 工具时**（工具名形如 `mcp__galbook__galbook_next`）：直接调用。
   - `galbook_help` 看规则 → `galbook_persona(text=…)` 设人设 → `galbook_new` → 反复 `galbook_next(n=20)` → 遇到选项 `galbook_choose(i=…, reason=…)`
   - 存读档：`galbook_save(slot=…)` / `galbook_load(slot=…)`；后悔：`galbook_rewind`；进度：`galbook_gallery`
2. **没有 MCP、但能跑 shell 时**：用 CLI（所有参数写成 k=v）。
   ```bash
   export GALPLAY_BOOKS=/path/to/books GALPLAY_DATA=/path/to/play-data GALPLAY_BOOK=fog-harbor GALPLAY_AGENT=<你的名字>
   python3 -m galbook do books            # 有哪些书
   python3 -m galbook do new hints=1      # 新游戏（可选 mode=ironman h=skip lang=en）
   python3 -m galbook do next n=20
   python3 -m galbook do choose i=2 reason="她看起来很累，我想陪着她"
   python3 -m galbook do save slot=before-confession
   python3 -m galbook do gallery
   ```
   Windows 上把 `python3` 换成 `python`，`export` 换成 `$env:GALPLAY_BOOKS="…"`。
3. **只能发 HTTP 时**：`GET http://<服务>/play/t` 读说明，然后 `GET /play/t/<book>/<你的名字>?do=next`。

每次返回的最后一行会告诉你下一步怎么写，照着做就行。

## 规则（重要）

- **不要直接打开 `books/*/story/` 下的 JSON 或原始剧本文件**，那等于翻到书的最后一页。只通过上面的接口读。
- 遇到选项先停一下：回想人物说过的话、你的人设，再选。`reason` 写一句真实的想法（会被记下来，别人能看到）。
- 一次读 10–30 句，不要一口气 `n=500` 跳过剧情；除非用户要求，不用 `skip=1`。
- 第一遍别开 `hints`；想看别的结局时再 `rewind`、读档或 `new`。
- 铁人模式（`mode=ironman`）下不能存读档和回溯，选了就认。
- H 场景默认折叠；用户没要求就不要改成 `h=full`。
- 读到结局后，用两三句话告诉用户：你走了哪条路、为什么这么选、感受如何；问要不要再玩一遍。

## 出错时

- `没有这本书`：先 `do books` / `galbook_books` 看有哪些 slug。
- `还没开始`：先 `new`，或 `load slot=auto`。
- `现在没有选项可选`：先 `next`。
