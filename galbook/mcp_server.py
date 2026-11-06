"""MCP 服务（stdio，JSON-RPC 2.0，一行一条）：让任何支持 MCP 的 agent 直接玩。

  python3 -m galbook mcp --books ./books --data ./play-data [--book 默认书] [--agent 默认名] [--lang zh|en]

在 MCP 客户端里配置（示例）：
  {"mcpServers": {"galbook": {"command": "python3",
     "args": ["-m", "galbook", "mcp", "--books", "/path/books", "--data", "/path/play-data", "--agent", "alice"]}}}
多个 agent 可以各起一个 MCP 进程（不同 --agent），共用同一个 --data 目录；存储层有文件锁，互不干扰。
也可以不起进程：python3 -m galbook serve 自带 Streamable HTTP 的 MCP 端点 POST /mcp?book=…&agent=…（见 server.py）。"""
import argparse
import json
import sys
import traceback

from . import VERSION
from .play import Library
from .tools import mcp_tools, call_tool
from .i18n import msg

PROTO = "2024-11-05"


def handle(lib, req, book=None, agent=None, lang="zh", force_agent=None):
    """处理一条 JSON-RPC 请求，返回响应 dict；通知返回 None。stdio 和 HTTP（/mcp）共用。
    force_agent：HTTP 令牌绑定了名字时，强制用这个名字（防冒名）。"""
    if not isinstance(req, dict):
        return {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "invalid request"}}
    mid, method, params = req.get("id"), req.get("method"), req.get("params") or {}
    if mid is None:            # 通知（notifications/initialized 等）不回
        return None
    try:
        if method == "initialize":
            res = {"protocolVersion": params.get("protocolVersion") or PROTO, "capabilities": {"tools": {}},
                   "serverInfo": {"name": "galbook", "version": VERSION},
                   "instructions": "Play visual novels like a human: galbook_help first, set galbook_persona, "
                                   "then galbook_new / galbook_next / galbook_choose (always give a reason)."}
        elif method == "ping":
            res = {}
        elif method == "tools/list":
            res = {"tools": mcp_tools()}
        elif method == "tools/call":
            args = dict(params.get("arguments") or {})
            try:
                if force_agent:
                    if args.get("agent") not in (None, "", force_agent):
                        raise ValueError("这个令牌只能用名字 %s / this token can only play as %s" % (force_agent, force_agent))
                    args["agent"] = force_agent
                text = call_tool(lib, params.get("name"), args, book, agent, lang)
                res = {"content": [{"type": "text", "text": text}], "isError": False}
            except (ValueError, KeyError) as e:
                res = {"content": [{"type": "text", "text": msg(lang, str(e))}], "isError": True}
        else:
            return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": "method not found: %s" % method}}
        return {"jsonrpc": "2.0", "id": mid, "result": res}
    except Exception as e:  # noqa
        traceback.print_exc(file=sys.stderr)
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32603, "message": "%s: %s" % (type(e).__name__, e)}}


def serve(lib, book=None, agent=None, lang="zh", fin=None, fout=None):
    fin = fin or sys.stdin
    fout = fout or sys.stdout

    def send(obj):
        fout.write(json.dumps(obj, ensure_ascii=False) + "\n")
        fout.flush()

    for line in fin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except ValueError:
            send({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}})
            continue
        r = handle(lib, req, book, agent, lang)
        if r is not None:
            send(r)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="galbook mcp")
    ap.add_argument("--books", default="books")
    ap.add_argument("--data", default="play-data")
    ap.add_argument("--book")
    ap.add_argument("--agent")
    ap.add_argument("--lang", default="zh", choices=("zh", "en"))
    a = ap.parse_args(argv)
    for f in (sys.stdin, sys.stdout):      # Windows 管道默认不是 UTF-8，MCP 要求 UTF-8
        if hasattr(f, "reconfigure"):
            f.reconfigure(encoding="utf-8")
    serve(Library(a.books, a.data), a.book, a.agent, a.lang)
    return 0


if __name__ == "__main__":
    sys.exit(main())
