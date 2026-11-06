"""独立服务：python3 -m galbook serve --books ./books --data ./play-data [--host 127.0.0.1] [--port 8765]

  /play/...            见 web.py（JSON / 纯文本 / 页面）
  /b/<书>/assets/...   书里的图片（只开放 assets/ 下面，剧本文件不外露，免得剧透/外泄）
  /                    跳到 /play/
  POST /mcp            MCP（Streamable HTTP，JSON 响应）：?book=默认书&agent=默认名，或请求头 X-Galplay-Agent

公开部署时的访问控制（可选）：
  --token XXX                     所有 /play/api 和 /play/t 请求都要带 ?token=XXX 或 Authorization: Bearer XXX
  --tokens tokens.json            {"令牌": "agent 名" | "*"}：每个令牌只能用自己的 agent 名玩（防冒名），"*" 是管理员
  --cors                          加 Access-Control-Allow-Origin: *（给浏览器里的别的前端调用）
默认只听 127.0.0.1。要给局域网/公网用，请自己加 --host 并配令牌、放在反向代理后面。"""
import argparse
import hmac
import json
import mimetypes
import os
import posixpath
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, parse_qs

from . import VERSION
from .web import App
from . import mcp_server


class Auth(object):
    def __init__(self, token=None, tokens=None):
        self.token = token
        self.tokens = dict(tokens or {})

    @property
    def on(self):
        return bool(self.token or self.tokens)

    def check(self, presented, agent):
        """返回 None = 通过，否则返回原因。"""
        if not self.on:
            return None
        if not presented:
            return "需要令牌（?token= 或 Authorization: Bearer）/ token required"
        if self.token and hmac.compare_digest(presented, self.token):
            return None
        for tok, who in self.tokens.items():
            if hmac.compare_digest(presented, tok):
                if who == "*" or agent is None or agent == who:
                    return None
                return "这个令牌只能用名字 %s / this token can only play as %s" % (who, who)
        return "令牌不对 / bad token"

    def bound(self, presented):
        """令牌绑定的 agent 名（管理员 / 共享口令返回 None）。"""
        for tok, who in self.tokens.items():
            if presented and hmac.compare_digest(presented, tok):
                return None if who == "*" else who
        return None


def make_handler(app, books_dir, auth, cors=False, quiet=False, lang="zh"):
    class H(BaseHTTPRequestHandler):
        server_version = "galbook/" + VERSION

        def log_message(self, fmt, *a):
            if not quiet:
                sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % a))

        def _send(self, code, body, ctype, extra=None):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            if cors:
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type, X-Galplay-Agent, Mcp-Session-Id")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def do_OPTIONS(self):
            self._send(204, b"", "text/plain")

        def _play(self, method):
            path, _, query = self.path.partition("?")
            n = int(self.headers.get("Content-Length") or 0)
            if n > 65536:
                return self._send(413, b"too large", "text/plain")
            body = self.rfile.read(n) if n > 0 else b""
            parts = [unquote(p) for p in path.split("/") if p]
            needs = len(parts) >= 3 and parts[1] in ("api", "t") and not (parts[1] == "api" and parts[2] == "books")
            if needs and auth.on:
                agent = parts[3] if len(parts) >= 4 and not (parts[1] == "api" and parts[-1] == "players") else None
                q = parse_qs(query)
                tok = (self.headers.get("Authorization") or "").replace("Bearer ", "", 1).strip() or (q.get("token") or [""])[-1]
                why = auth.check(tok, agent)
                if why:
                    return self._send(403 if why.startswith("这个令牌只能") else 401, json.dumps({"ok": False, "error": why}, ensure_ascii=False).encode(), "application/json; charset=utf-8")
            r = app.handle(method, path, query, body)
            if r is None:
                return self._send(404, b"not found", "text/plain")
            code, ctype, data = r
            return self._send(code, data, ctype)

        def _mcp(self):
            path, _, query = self.path.partition("?")
            q = parse_qs(query)
            n = int(self.headers.get("Content-Length") or 0)
            if n > 262144:
                return self._send(413, b"too large", "text/plain")
            body = self.rfile.read(n) if n > 0 else b""
            force = None
            if auth.on:
                tok = (self.headers.get("Authorization") or "").replace("Bearer ", "", 1).strip() or (q.get("token") or [""])[-1]
                why = auth.check(tok, None)
                if why:
                    return self._send(401, json.dumps({"error": why}, ensure_ascii=False).encode(), "application/json; charset=utf-8")
                force = auth.bound(tok)
            try:
                req = json.loads(body.decode("utf-8") or "null")
            except ValueError:
                return self._send(400, json.dumps({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}}).encode(),
                                  "application/json")
            book = (q.get("book") or [None])[-1]
            agent = self.headers.get("X-Galplay-Agent") or (q.get("agent") or [None])[-1]
            lg = (q.get("lang") or [lang])[-1]
            reqs = req if isinstance(req, list) else [req]
            out = [r for r in (mcp_server.handle(app.lib, x, book, agent, lg, force) for x in reqs) if r is not None]
            if not out:
                return self._send(202, b"", "text/plain")
            res = out if isinstance(req, list) else out[0]
            return self._send(200, json.dumps(res, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

        def do_POST(self):
            if self.path.split("?", 1)[0] == "/mcp":
                return self._mcp()
            if self.path.startswith("/play"):
                return self._play("POST")
            return self._send(404, b"not found", "text/plain")

        def do_GET(self):
            path = self.path.split("?", 1)[0]
            if path == "/mcp":     # 不提供服务端推送流
                return self._send(405, b"method not allowed", "text/plain", {"Allow": "POST"})
            if path == "/":
                return self._send(302, b"", "text/plain", {"Location": "/play/"})
            if path == "/play" or path.startswith("/play/"):
                return self._play("GET")
            if path.startswith("/b/"):
                rest = unquote(path[3:])
                slug, _, sub = rest.partition("/")
                sub = posixpath.normpath("/" + sub).lstrip("/")
                if not slug or slug.startswith(".") or "/" in slug or not sub.startswith("assets/"):
                    return self._send(403, b"forbidden", "text/plain")
                base = os.path.realpath(os.path.join(books_dir, slug))
                target = os.path.realpath(os.path.join(base, sub))
                if not target.startswith(base + os.sep) or not os.path.isfile(target):
                    return self._send(404, b"not found", "text/plain")
                with open(target, "rb") as f:
                    data = f.read()
                return self._send(200, data, mimetypes.guess_type(target)[0] or "application/octet-stream")
            return self._send(404, b"not found", "text/plain")

        do_HEAD = do_GET
    return H


def main(argv=None):
    ap = argparse.ArgumentParser(prog="galbook serve", description="galbook 独立服务")
    ap.add_argument("--books", default="books")
    ap.add_argument("--data", default="play-data")
    ap.add_argument("--host", default=os.environ.get("GALBOOK_HOST", "127.0.0.1"))
    ap.add_argument("--port", type=int, default=int(os.environ.get("GALBOOK_PORT", "8765")))
    ap.add_argument("--token", default=os.environ.get("GALBOOK_TOKEN"))
    ap.add_argument("--tokens", help="JSON 文件：{令牌: agent名 或 *}")
    ap.add_argument("--lang", default="zh", choices=("zh", "en"))
    ap.add_argument("--cors", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args(argv)
    tokens = json.load(open(a.tokens, encoding="utf-8")) if a.tokens else None
    os.makedirs(a.books, exist_ok=True)
    app = App(a.books, a.data, default_lang=a.lang)
    srv = ThreadingHTTPServer((a.host, a.port), make_handler(app, a.books, Auth(a.token, tokens), a.cors, a.quiet, a.lang))
    srv.daemon_threads = True
    print("galbook %s serving http://%s:%d/play/  books=%s data=%s auth=%s" % (
        VERSION, a.host, a.port, os.path.abspath(a.books), os.path.abspath(a.data), "on" if (a.token or tokens) else "off"), flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
