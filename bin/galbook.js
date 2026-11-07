#!/usr/bin/env node
// npx galbook <命令> … → python -m galbook <命令> …（本体是 Python 标准库写的，这里只负责找 Python 和转发）
// 选解释器：GALBOOK_PYTHON > Windows: py -3 / python / python3 > 其他: python3 / python；要求 3.9+。
// 注意：stdin/stdout/stderr 原样继承——MCP 走 stdio 时 stdout 是协议通道，这里自己一个字都不往 stdout 写。
import { spawn, spawnSync } from "node:child_process";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { delimiter } from "node:path";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const CHECK = "import sys; print('%d.%d' % sys.version_info[:2])";

function candidates() {
  if (process.env.GALBOOK_PYTHON) return [[process.env.GALBOOK_PYTHON]];
  return process.platform === "win32" ? [["py", "-3"], ["python"], ["python3"]] : [["python3"], ["python"]];
}

function findPython() {
  const tried = [];
  for (const [cmd, ...pre] of candidates()) {
    const r = spawnSync(cmd, [...pre, "-c", CHECK], { encoding: "utf8", windowsHide: true });
    const v = (r.stdout || "").trim();
    tried.push(cmd + (pre.length ? " " + pre.join(" ") : "") + (r.error ? "（没找到）" : v ? "（" + v + "）" : "（运行失败）"));
    if (!r.error && r.status === 0 && /^\d+\.\d+$/.test(v)) {
      const [maj, min] = v.split(".").map(Number);
      if (maj > 3 || (maj === 3 && min >= 9)) return { cmd, pre, tried };
    }
  }
  return { cmd: null, tried };
}

const py = findPython();
if (!py.cmd) {
  process.stderr.write(
    "galbook 需要 Python 3.9 或更新版本，但这台机器上没找到能用的。\n" +
      "  试过：" + py.tried.join("、") + "\n" +
      "  解决：装 Python（https://www.python.org/downloads/ ，Windows 安装时勾选「Add python.exe to PATH」），\n" +
      "        或者设环境变量 GALBOOK_PYTHON 指向 python 可执行文件，再重试。\n" +
      "galbook needs Python 3.9+ and none was found on PATH. Install it from https://www.python.org/downloads/\n" +
      "(on Windows tick \"Add python.exe to PATH\"), or set GALBOOK_PYTHON to the interpreter path.\n"
  );
  process.exit(127);
}

const env = { ...process.env, PYTHONIOENCODING: process.env.PYTHONIOENCODING || "utf-8" };
env.PYTHONPATH = env.PYTHONPATH ? ROOT + delimiter + env.PYTHONPATH : ROOT;   // 用包里自带的 galbook/
const child = spawn(py.cmd, [...py.pre, "-m", "galbook", ...process.argv.slice(2)], { stdio: "inherit", env, windowsHide: true });
for (const sig of ["SIGINT", "SIGTERM"]) process.on(sig, () => child.kill(sig));
child.on("error", (e) => {
  process.stderr.write("galbook: 启动 Python 失败 / failed to start Python: " + e.message + "\n");
  process.exit(127);
});
child.on("exit", (code, signal) => process.exit(signal ? 1 : code ?? 1));
