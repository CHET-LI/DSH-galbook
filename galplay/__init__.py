"""galplay —— 让 agent 像人一样玩 galgame：读剧本、遇到选项自己选、存档/读档/回溯。

组成：
  ir.py        引擎无关的中间格式（story.json + scenes/*.json）与校验
  expr.py      安全的小表达式求值（条件 / 赋值），不用 eval
  engine.py    运行时：推进、选项、存档快照、已读跳过、回溯
  store.py     多 agent 并发存储：每个 agent 一份档案 + 存档位，逐 agent 加锁、原子写
  web.py       HTTP 接口（独立服务 python -m galplay serve，或嵌进任何 http.server；纯文本接口给 agent 省 token）
  importers/   各引擎脚本 → 中间格式（qlie / kag(吉里吉里·Tyrano) / renpy / nscripter / galscript / textdump / legacy 书稿；可加插件）
  server.py    独立 HTTP 服务（可选令牌、每个令牌绑定 agent 名）
  mcp_server.py MCP（stdio）服务；tools.py 工具定义（MCP / OpenAI 共用）
  i18n.py      文本接口 zh / en
只用 Python 标准库。
"""
VERSION = "galplay-1.1"
