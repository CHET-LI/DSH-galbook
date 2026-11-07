#!/usr/bin/env python3
"""发版一条命令：测试 → 版本号同步 → npm 打包 → 打 tag → 提示发布。在仓库根目录跑：

  python3 scripts/release.py 1.2.4            # 完整流程（测试、同步、打包、git commit + tag）
  python3 scripts/release.py 1.2.4 --no-tag   # 不碰 git（只同步版本 + 打包）
  python3 scripts/release.py --check          # 只核对：三处版本一致、README.en 和 package.json 的 description 一致
  python3 scripts/release.py --check --expect 1.2.4   # CI 用：再核对版本 = tag

版本号在三处：pyproject.toml、package.json、galbook/__init__.py（VERSION = "galbook-X.Y.Z"）；
文档里写死的 `galbook-X.Y.Z.tgz` 也一起改。打包结果放 dist/（不进 git）。
不会自己 npm publish（要 npm 账号）；最后打印该跑的命令。只用标准库。"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable
SEMVER = re.compile(r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$")
DOCS_WITH_TGZ = ("README.md", "README.en.md", "dsh-plugin/README.md", "integrations/deepseek-harness/README.md")
FORBIDDEN_IN_PKG = ("books/", "play-data/", "tests/", ".git/", "dist/")


def p(*a):
    return os.path.join(ROOT, *a)


def read(rel):
    with open(p(rel), encoding="utf-8") as f:
        return f.read()


def write(rel, s):
    with open(p(rel), "w", encoding="utf-8", newline="") as f:
        f.write(s)


def versions():
    py = re.search(r'(?m)^version\s*=\s*"([^"]+)"', read("pyproject.toml"))
    pk = json.loads(read("package.json")).get("version")
    ini = re.search(r'(?m)^VERSION\s*=\s*"galbook-([^"]+)"', read("galbook/__init__.py"))
    return {"pyproject.toml": py and py.group(1), "package.json": pk, "galbook/__init__.py": ini and ini.group(1)}


def check(expect=None):
    ok = True
    v = versions()
    vals = set(v.values())
    print("版本：" + "，".join("%s=%s" % kv for kv in v.items()))
    if len(vals) != 1 or None in vals:
        print("FAIL 三处版本不一致")
        ok = False
    if expect and vals != {expect}:
        print("FAIL 版本应该是 %s（tag）" % expect)
        ok = False
    desc = json.loads(read("package.json")).get("description", "")
    en = re.sub(r"\*\*", "", read("README.en.md"))
    if desc and desc not in re.sub(r"\s*\n\s*", " ", en):
        print("FAIL README.en.md 里找不到和 package.json 一样的 description：%s" % desc[:80])
        ok = False
    print("PASS" if ok else "有问题，先修")
    return ok


def run(cmd, **kw):
    print("$ " + " ".join(cmd), flush=True)
    return subprocess.run(cmd, cwd=ROOT, **kw)


def tests():
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    if run([PY, "-m", "unittest", "discover", "-s", "tests"], env=env).returncode != 0:
        sys.exit("测试没过：python -m unittest discover -s tests（发版停止，什么都没改）")
    if run([PY, os.path.join("scripts", "verify_claims.py")], env=env).returncode != 0:
        sys.exit("README 核对没过：python scripts/verify_claims.py（发版停止，什么都没改）")


def sync(new):
    old = versions()["package.json"]
    s = read("pyproject.toml")
    write("pyproject.toml", re.sub(r'(?m)^(version\s*=\s*)"[^"]+"', r'\g<1>"%s"' % new, s, count=1))
    s = read("package.json")   # 只替换 version 那一行，别的格式不动
    write("package.json", re.sub(r'("version"\s*:\s*)"[^"]+"', r'\g<1>"%s"' % new, s, count=1))
    s = read("galbook/__init__.py")
    write("galbook/__init__.py", re.sub(r'(?m)^(VERSION\s*=\s*)"galbook-[^"]+"', r'\g<1>"galbook-%s"' % new, s, count=1))
    changed = ["pyproject.toml", "package.json", "galbook/__init__.py"]
    if old and old != new:
        for rel in DOCS_WITH_TGZ:
            if os.path.isfile(p(rel)):
                s = read(rel)
                t = s.replace("galbook-%s.tgz" % old, "galbook-%s.tgz" % new).replace("dsh-plugin-%s.zip" % old, "dsh-plugin-%s.zip" % new)
                if t != s:
                    write(rel, t)
                    changed.append(rel)
    print("版本 %s → %s：%s" % (old, new, "、".join(changed)))
    return changed


def pack(new):
    npm = shutil.which("npm") or shutil.which("npm.cmd")
    if not npm:
        sys.exit("没找到 npm：装 Node.js 后重跑（或 --no-pack 跳过打包）")
    os.makedirs(p("dist"), exist_ok=True)
    r = run([npm, "pack", "--json", "--pack-destination", "dist"], capture_output=True, text=True, encoding="utf-8")
    if r.returncode != 0:
        sys.exit("npm pack 失败：\n" + (r.stderr or r.stdout)[-2000:])
    info = json.loads(r.stdout)[0]
    tgz = p("dist", info["filename"])
    with tarfile.open(tgz) as t:
        names = [m.name[len("package/"):] for m in t.getmembers() if m.isfile()]
    bad = [n for n in names if n.startswith(FORBIDDEN_IN_PKG) or "__pycache__/" in n or n.endswith(".pyc")]
    need = ["galbook/__init__.py", "cordis.patch.yml", "locale/zh.json", "icon.svg", "bin/galbook.js", "package.json"]
    miss = [n for n in need if n not in names]
    if bad or miss:
        sys.exit("包内容不对：不该有 %s；缺 %s" % (bad[:5], miss))
    print("打包：%s（%d 个文件，%.1f kB）" % (os.path.relpath(tgz, ROOT), len(names), info.get("size", 0) / 1000))
    return tgz


def git_tag(new, changed):
    if not os.path.isdir(p(".git")):
        print("不是 git 仓库：跳过 commit / tag")
        return False
    tag = "v" + new
    if run(["git", "rev-parse", "-q", "--verify", "refs/tags/" + tag], capture_output=True).returncode == 0:
        sys.exit("tag %s 已经存在" % tag)
    run(["git", "add", "--"] + changed, check=True)
    if run(["git", "diff", "--cached", "--quiet"]).returncode != 0:
        run(["git", "commit", "-m", "release %s" % tag], check=True)
    run(["git", "tag", "-a", tag, "-m", "galbook %s" % new], check=True)
    return True


def main(argv=None):
    ap = argparse.ArgumentParser(prog="release.py", description=__doc__.splitlines()[0])
    ap.add_argument("version", nargs="?", help="新版本号，例 1.2.4")
    ap.add_argument("--check", action="store_true", help="只核对，不改任何东西")
    ap.add_argument("--expect", help="配合 --check：版本必须等于它（CI 里传 tag 去掉 v）")
    ap.add_argument("--no-test", action="store_true", help="跳过测试（不建议）")
    ap.add_argument("--no-pack", action="store_true")
    ap.add_argument("--no-tag", action="store_true", help="不 commit、不打 tag")
    a = ap.parse_args(argv)
    if a.check:
        return 0 if check(a.expect) else 1
    if not a.version or not SEMVER.match(a.version):
        ap.error("要给新版本号，形如 1.2.4")
    if not a.no_test:
        tests()
    changed = sync(a.version)
    if not check(a.version):
        return 1
    tgz = None if a.no_pack else pack(a.version)
    tagged = False if a.no_tag else git_tag(a.version, changed)
    print("\n下一步（要 npm 账号，本脚本不代发）：")
    if tagged:
        print("  git push origin HEAD v%s        # 推 tag；仓库配了 NPM_TOKEN 的话 CI 会自动 npm publish" % a.version)
    if tgz:
        print("  npm publish %s --access public   # 或手动发" % os.path.relpath(tgz, ROOT))
    print("  npm view galbook version         # 发完自检")
    return 0


if __name__ == "__main__":
    sys.exit(main())
