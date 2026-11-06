"""不花钱的自测：一个假的 Anthropic Messages 端点，按固定脚本让 dsh 调 galplay（MCP 或 shell+CLI）。
真模型不会这么死板——这里只证明「dsh 能挂上 galplay、工具能调通、技能能被发现」。

  python3 mock_model.py --port 9911 --mode mcp|cli --books B --data D [--log mock.log]
  DEEPSEEK_API_KEY=sk-fake DEEPSEEK_BASE_URL=http://127.0.0.1:9911 dsh headless --patch ... "玩一下"
"""
import argparse
import json
import sys
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def script(mode, books, data):
    if mode == "cli":
        env = "GALPLAY_BOOKS=%s GALPLAY_DATA=%s GALPLAY_BOOK=fog-harbor GALPLAY_AGENT=dsh-cli %s -m galplay do " % (books, data, sys.executable)
        return [("skill", {"name": "galplay"})] + [("bash", {"command": env + c, "description": "galplay " + c.split()[0]})
                                                   for c in ("new", "next n=20", "choose i=2 reason=留在灯旁边帮她", "next n=20")]
    p = "mcp__galplay__galplay_"
    return [(p + "help", {}), (p + "persona", {"text": "好奇心重，胆子大"}), (p + "new", {}), (p + "next", {"n": 20}),
            (p + "choose", {"i": 1, "reason": "她一个人走夜路太危险，我陪她去"}), (p + "next", {"n": 20})]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=9911)
    ap.add_argument("--mode", choices=("mcp", "cli"), default="mcp")
    ap.add_argument("--books", default="books")
    ap.add_argument("--data", default="play-data")
    ap.add_argument("--log", default="mock.log")
    a = ap.parse_args()
    steps = script(a.mode, a.books, a.data)
    log = open(a.log, "a", encoding="utf-8", buffering=1)

    def sse(w, ev, d):
        w.write(("event: %s\ndata: %s\n\n" % (ev, json.dumps(d, ensure_ascii=False))).encode("utf-8"))
        w.flush()

    class H(BaseHTTPRequestHandler):
        def log_message(self, *x):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
            tools = [t.get("name") for t in body.get("tools") or []]
            results = []
            for m in body.get("messages") or []:
                for c in (m.get("content") if isinstance(m.get("content"), list) else []):
                    if c.get("type") == "tool_result":
                        cc = c.get("content")
                        results.append(cc if isinstance(cc, str) else " ".join(x.get("text", "") for x in cc or []))
            whole = json.dumps(body, ensure_ascii=False)
            log.write(json.dumps({"galplay_tools": sorted(t for t in tools if "galplay" in t), "skill_listed": "`galplay`:" in whole,
                                  "step": len(results), "last_result": results[-1][:400] if results else None}, ensure_ascii=False) + "\n")
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            sse(self.wfile, "message_start", {"type": "message_start", "message": {
                "id": "msg_" + uuid.uuid4().hex[:12], "type": "message", "role": "assistant", "model": body.get("model"),
                "content": [], "stop_reason": None, "stop_sequence": None, "usage": {"input_tokens": 1, "output_tokens": 0}}})
            k = len(results)
            usable = tools and k < len(steps) and steps[k][0] in tools
            if usable:
                name, args = steps[k]
                sse(self.wfile, "content_block_start", {"type": "content_block_start", "index": 0, "content_block": {
                    "type": "tool_use", "id": "toolu_" + uuid.uuid4().hex[:12], "name": name, "input": {}}})
                sse(self.wfile, "content_block_delta", {"type": "content_block_delta", "index": 0,
                                                        "delta": {"type": "input_json_delta", "partial_json": json.dumps(args, ensure_ascii=False)}})
            else:
                text = "（自测）最后一次工具输出：\n" + (results[-1][-400:] if results else "无")
                sse(self.wfile, "content_block_start", {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}})
                sse(self.wfile, "content_block_delta", {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": text}})
            sse(self.wfile, "content_block_stop", {"type": "content_block_stop", "index": 0})
            sse(self.wfile, "message_delta", {"type": "message_delta", "delta": {"stop_reason": "tool_use" if usable else "end_turn",
                                                                                  "stop_sequence": None}, "usage": {"output_tokens": 1}})
            sse(self.wfile, "message_stop", {"type": "message_stop"})

    ThreadingHTTPServer(("127.0.0.1", a.port), H).serve_forever()


if __name__ == "__main__":
    main()
