"""各引擎脚本 → galplay/1 中间格式。

内置：qlie / kag（吉里吉里·Tyrano）/ renpy / nscripter / galscript（.gal 手写格式）/ textdump（VNTextPatch 等文本导出，线性）
插件：环境变量 GALPLAY_PLUGINS（多个用 os.pathsep 分隔）指向 .py 文件或目录；或 build 时 --plugin x.py。
      插件模块要有 NAME、build(src, assets=None, **opts) -> (meta, scenes)，可选 detect(src) -> (bool, 说明)。
      详见 docs/IMPORTERS.md。
"""
import importlib
import importlib.util
import os

NAMES = ("qlie", "kag", "renpy", "nscripter", "galscript", "textdump")
_plugins = {}


def load_plugin(path):
    """加载一个插件文件，返回它的 NAME。"""
    spec = importlib.util.spec_from_file_location("galplay_plugin_%d" % len(_plugins), path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    if not getattr(mod, "NAME", None) or not callable(getattr(mod, "build", None)):
        raise ValueError("插件 %s 缺 NAME 或 build()" % path)
    _plugins[mod.NAME] = mod
    return mod.NAME


def _env_plugins():
    for p in filter(None, os.environ.get("GALPLAY_PLUGINS", "").split(os.pathsep)):
        files = [os.path.join(p, f) for f in sorted(os.listdir(p)) if f.endswith(".py")] if os.path.isdir(p) else [p]
        for f in files:
            if not any(getattr(m, "__file__", None) == f for m in _plugins.values()):
                load_plugin(f)


def names():
    _env_plugins()
    return list(NAMES) + [n for n in _plugins if n not in NAMES]


def get(name):
    _env_plugins()
    if name in _plugins:
        return _plugins[name]
    if name not in NAMES:
        raise ValueError("没有这个导入器: %r（有：%s）" % (name, " ".join(names())))
    return importlib.import_module("." + name, __name__)


def detect(src):
    """按文件特征认引擎。返回 (engine, 依据)；认不出返回 (None, 说明)。插件先认。"""
    if not os.path.isdir(src):
        return None, "目录不存在或不是目录: %s" % src
    _env_plugins()
    for n, m in _plugins.items():
        if callable(getattr(m, "detect", None)):
            ok, why = m.detect(src)
            if ok:
                return n, why
    names_ = []
    for dp, dn, fn in os.walk(src):
        for f in fn:
            names_.append(os.path.join(dp, f))
        if len(names_) > 20000:
            break
    low = [n.lower() for n in names_]

    def has(ext):
        return [n for n in low if n.endswith(ext)]
    if has(".gal"):
        return "galscript", "有 galscript 剧本（.gal）"
    if any(os.path.basename(n) in ("route.s", "select.s") for n in low) or (has(".s") and any("シナリオ" in n for n in names_)):
        return "qlie", "有 QLIE 的 .s 剧本（route.s/select.s 或 シナリオ目录）"
    if has(".pack") and not has(".s"):
        return None, "QLIE .pack 封包：先用 GARbro 解包出 .s 再导入"
    if has(".rpy"):
        return "renpy", "有 Ren'Py 的 .rpy 源码"
    if has(".rpyc") or has(".rpa"):
        return None, "Ren'Py 编译过的 .rpyc/.rpa：先用 unrpa 解包、unrpyc 反编译成 .rpy 再导入"
    if has(".ks"):
        return "kag", "有吉里吉里 KAG / TyranoScript 的 .ks 剧本"
    if has(".xp3"):
        return None, "吉里吉里 .xp3 封包：先用 GARbro / KrkrExtract 解出 .ks 再导入"
    if any(os.path.basename(n) in ("0.txt", "00.txt", "nscript.dat", "nscript.___") for n in low):
        return "nscripter", "有 NScripter 的 0.txt / nscript.dat"
    from . import textdump
    ok, why = textdump.detect(src)
    if ok:
        return "textdump", why
    hint = "（可以先用 VNTextPatch extractlocal 抽成 .json 再用 textdump 导入，能读但没有分支）"
    if any(os.path.basename(n) in ("scene.pck", "gameexe.dat") for n in low):
        return None, "SiglusEngine（Scene.pck）：字节码+按作品加密，见 docs/ENGINES.md"
    if any(os.path.basename(n).startswith("seen") and n.endswith(".txt") for n in low):
        return None, "RealLive（SEEN.TXT）：用 RLdev kprl 反编译，或 VNTextPatch --format=reallive 抽文本" + hint
    if has(".pfs") or has(".ast") or has(".asb"):
        return None, "Artemis（.pfs/.ast）：解包后可用 VNTextPatch 抽文本" + hint
    if has(".mjo"):
        return None, "Majiro（.mjo 字节码）" + hint
    if has(".ws2"):
        return None, "AdvHD（.ws2）" + hint
    if has(".cst"):
        return None, "CatSystem2（.cst）" + hint
    if has(".ybn"):
        return None, "YU-RIS（.ybn）" + hint
    if has(".arc") and any("sysgrp" in n or "data0" in n for n in low):
        return None, "像 BGI/Ethornell（.arc）：解包后 VNTextPatch --format=ethornell" + hint
    return None, "认不出引擎（看了 %d 个文件）" % len(names_)
