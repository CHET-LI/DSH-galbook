"""给 agent 框架用的工具定义（MCP / OpenAI function calling 共用一份）。

  python3 -m galbook tools --format openai   打印 OpenAI tools JSON
  python3 -m galbook tools --format mcp      打印 MCP tools/list 的 tools 数组
调用时：call_tool(lib, name, args, default_book, default_agent, lang) -> 文本"""
import json

from .play import Library  # noqa: F401  (类型提示用)
from .web import render_text, restyle, HELP
from .i18n import msg
from . import VERSION

_BA = {"book": {"type": "string", "description": "书的 slug（见 galbook_books）。服务端设了默认书时可省略"},
       "agent": {"type": "string", "description": "你的玩家名（1-40 位字母数字/中日文/_-.）。服务端设了默认名时可省略"}}

TOOLS = [
    ("galbook_books", None, "List playable books (slug, title, engine, routes). / 列出能玩的书", {}),
    ("galbook_help", None, "How to play like a human (rules and tips). / 玩法说明", {}),
    ("galbook_status", "status", "Where am I in the story, pending choice, recent lines. / 现在玩到哪", {}),
    ("galbook_new", "new", "Start a new playthrough. / 新游戏", {
        "h": {"type": "string", "enum": ["fold", "full", "skip"], "description": "adult scenes: fold(default)/full/skip"},
        "mode": {"type": "string", "enum": ["normal", "ironman"], "description": "ironman = no save/load/rewind"},
        "hints": {"type": "boolean", "description": "mark options 'picked before' / 'new'"},
        "lang": {"type": "string", "enum": ["zh", "en"], "description": "UI text language"}}),
    ("galbook_next", "next", "Read the next n lines; stops at a choice or ending. / 往下读", {
        "n": {"type": "integer", "minimum": 1, "maximum": 200, "description": "lines to read (default 20)"},
        "skip_read": {"type": "boolean", "description": "fast-forward lines you have already read"},
        "img": {"type": "boolean", "description": "include background/sprite/CG names"}}),
    ("galbook_choose", "choose", "Pick an option at a choice and say why. / 选选项并写理由", {
        "i": {"type": ["integer", "string"], "description": "option number from 1, or \"random\""},
        "reason": {"type": "string", "description": "one sentence: why your persona picks this"}}),
    ("galbook_save", "save", "Save to a slot. / 存档", {
        "slot": {"type": "string", "description": "quick or 1-99"}, "note": {"type": "string"}}),
    ("galbook_load", "load", "Load a slot (auto is written at every choice). / 读档", {
        "slot": {"type": "string", "description": "auto / quick / 1-99"}}),
    ("galbook_saves", "saves", "List save slots. / 存档列表", {}),
    ("galbook_rewind", "rewind", "Go back to the previous choice to choose again. / 回到上个选项", {
        "steps": {"type": "integer", "minimum": 1, "description": "how many choice points back (default 1)"}}),
    ("galbook_log", "log", "Backlog of recent lines and choices made. / 回想", {
        "n": {"type": "integer", "minimum": 1, "maximum": 300}}),
    ("galbook_persona", "persona", "Set or show your persona; it is shown to you at every choice. / 人设", {
        "text": {"type": "string", "description": "omit to show; empty string to clear"}}),
    ("galbook_gallery", "gallery", "Collection progress: endings, routes, CG, read ratio. / 收集进度", {}),
    ("galbook_profile", "profile", "Stats and human-likeness numbers. / 记录", {}),
    ("galbook_click", "click", "Click the screen. / 点一下画面", {}),
]


def _schema(props, need_ba=True):
    p = dict(_BA) if need_ba else {}
    p.update(props)
    return {"type": "object", "properties": p}


def mcp_tools():
    return [{"name": n, "description": d, "inputSchema": _schema(pr, a is not None)} for n, a, d, pr in TOOLS]


def openai_tools():
    return [{"type": "function", "function": {"name": n, "description": d, "parameters": _schema(pr, a is not None)}}
            for n, a, d, pr in TOOLS]


def call_tool(lib, name, args, default_book=None, default_agent=None, lang="zh", style="tool", lang_override=None):
    """执行一个工具，返回纯文本。style：提示里的下一步写成 tool（默认）/ cli / http 形式。"""
    spec = next((x for x in TOOLS if x[0] == name), None)
    if spec is None:
        raise ValueError("unknown tool %s" % name)
    args = dict(args or {})
    if name == "galbook_books":
        return json.dumps(lib.books(), ensure_ascii=False, indent=1)
    if name == "galbook_help":
        return HELP.get(lang, HELP["zh"]) % VERSION
    book = args.pop("book", None) or default_book
    agent = args.pop("agent", None) or default_agent
    if not book or not agent:
        raise ValueError("需要 book 和 agent / book and agent are required")
    img = bool(args.pop("img", False))
    if "hints" in args:
        args["hints"] = "1" if args["hints"] in (True, "1", "true", 1) else "0"
    if args.pop("skip_read", False):
        args["skip_read"] = True
    action = spec[1]
    r = lib.act(book, agent, action, **args)
    run = lib.store.peek_run(book, agent) or {}
    lg = lang_override or ((r.get("opts") or run.get("opts") or {}).get("lang")) or lang
    return restyle(render_text(r, action, img, book, agent, lg), book, agent, style)


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(prog="galbook tools")
    ap.add_argument("--format", choices=("openai", "mcp"), default="openai")
    a = ap.parse_args(argv)
    print(json.dumps(openai_tools() if a.format == "openai" else mcp_tools(), ensure_ascii=False, indent=1))
    return 0


__all__ = ["TOOLS", "mcp_tools", "openai_tools", "call_tool", "msg"]
